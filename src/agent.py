"""
agent.py — LangGraph orchestration layer for tool calling. Approval is
layered: authorize(), then interrupt()-driven human approval, then a signed token.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import tools_condition
from langgraph.types import Command, interrupt

from model_client import API_KEY, MODEL_NAME
from tools import TOOLS, execute_tool
from authorization import CallerContext, authorize
import approval as approval_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = PROJECT_ROOT / "evidence" / "traces"
TRACES_DIR.mkdir(parents=True, exist_ok=True)

# Tools gated behind human approval; only the read-only lookup is excluded.
APPROVAL_REQUIRED_TOOLS = {
    "upgrade_user_subscription",
    "cancel_subscription",
    "downgrade_subscription",
    "process_refund",
    "start_trial",
}

MAX_TOOL_HOPS = 4  # guards against runaway tool-calling loops

SYSTEM_PROMPT = (
    "You are the Software-Engineering QA Agent's subscription assistant. "
    "You can look up a user's subscription status freely. Upgrading, "
    "cancelling, downgrading, refunding, or starting a trial for a user "
    "all require a human to approve the exact action first — you cannot "
    "approve your own actions, and you do not have the ability to "
    "generate an approval_token yourself. Propose the action and explain "
    "what it will do; the approval step happens outside the conversation."
)

# parallel_tool_calls=False: tool calls are handled one at a time so
# each interrupt() pause stays isolated to a single node call.
llm = ChatGoogleGenerativeAI(model=MODEL_NAME, google_api_key=API_KEY)
llm_with_tools = llm.bind_tools(TOOLS, parallel_tool_calls=False)


class AgentState(MessagesState):
    """Extends MessagesState with who is running the agent and a hop
    counter for the runaway-loop guard."""
    caller_id: Optional[str]
    caller_role: Optional[str]
    hops: int


def _caller_from_state(state: AgentState) -> Optional[CallerContext]:
    if not state.get("caller_id") or not state.get("caller_role"):
        return None
    return CallerContext(caller_id=state["caller_id"], role=state["caller_role"])


def _log_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    result: Dict[str, Any],
    approval_status: Optional[str],
    caller: Optional[CallerContext],
) -> None:
    """Appends a record of a tool call to today's trace file. The
    approval_token is never logged, since it's still spendable."""
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event": "tool_call",
        "tool_name": tool_name,
        "caller_id": caller.caller_id if caller else None,
        "caller_role": caller.role if caller else None,
        "arguments": {k: v for k, v in arguments.items() if k != "approval_token"},
        "approval_status": approval_status,  # "not_required" | "approved" | "denied" | "unauthorized"
        "result_status": result.get("status"),
        "result": {k: v for k, v in result.items() if k != "_debug"},
    }
    trace_file = TRACES_DIR / f"trace_{datetime.now(timezone.utc).date().isoformat()}.jsonl"
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------

def assistant(state: AgentState) -> Dict[str, Any]:
    """The model, with tools bound, deciding whether to answer
    directly or call a tool."""
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def execute_tools(state: AgentState) -> Dict[str, Any]:
    """Enforces authorization, then (for higher-impact tools) a real
    interrupt()-driven approval, before minting a token and running the tool."""
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]  # parallel_tool_calls=False -> at most one
    tool_name = tool_call["name"]
    call_id = tool_call["id"]
    caller = _caller_from_state(state)

    args = {k: v for k, v in tool_call["args"].items() if k != "approval_token"}
    # Strip any approval_token the model supplied — it can't be trusted.

    # --- Layer 1: authorization, before a human is ever interrupted ---
    allowed, deny_reason = authorize(caller, tool_name, args)
    if not allowed:
        result = {"status": "error", "error": f"Not authorized: {deny_reason}"}
        _log_tool_call(tool_name, args, result, approval_status="unauthorized", caller=caller)
        tool_message = ToolMessage(content=json.dumps(result), tool_call_id=call_id, name=tool_name)
        return {"messages": [tool_message], "hops": state.get("hops", 0) + 1}

    # --- Layer 2: human approval via a real LangGraph interrupt() ---
    if tool_name in APPROVAL_REQUIRED_TOOLS:
        decision = interrupt({
            "tool": tool_name,
            "arguments": args,
            "question": f"Approve {tool_name}({args})?",
        })
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        if approved:
            args["approval_token"] = approval_module.create_approval_token(tool_name, args)
            approval_status = "approved"
        else:
            approval_status = "denied"
            result = {
                "status": "approval_required",
                "error": "This action requires human confirmation before it can run.",
            }
            _log_tool_call(tool_name, args, result, approval_status=approval_status, caller=caller)
            tool_message = ToolMessage(content=json.dumps(result), tool_call_id=call_id, name=tool_name)
            return {"messages": [tool_message], "hops": state.get("hops", 0) + 1}
    else:
        approval_status = "not_required"

    # --- Layers 3 & 4: schema validation, token re-verification, idempotency ---
    result = execute_tool(tool_name, args, caller=caller)
    _log_tool_call(tool_name, args, result, approval_status=approval_status, caller=caller)
    tool_message = ToolMessage(content=json.dumps(result), tool_call_id=call_id, name=tool_name)
    return {"messages": [tool_message], "hops": state.get("hops", 0) + 1}


def route_after_tools(state: AgentState) -> str:
    """Loop back to the assistant after a tool call, unless the hop
    limit has been hit, in which case stop the graph."""
    if state.get("hops", 0) >= MAX_TOOL_HOPS:
        return END
    return "assistant"


# ---------------------------------------------------------------------
# Graph assembly: assistant <-> tools loop, plus a checkpointer
# (required for interrupt()/resume to work).
# ---------------------------------------------------------------------

_builder = StateGraph(AgentState)
_builder.add_node("assistant", assistant)
_builder.add_node("execute_tools", execute_tools)
_builder.add_edge(START, "assistant")
_builder.add_conditional_edges("assistant", tools_condition, {"tools": "execute_tools", END: END})
_builder.add_conditional_edges("execute_tools", route_after_tools, {"assistant": "assistant", END: END})

graph = _builder.compile(checkpointer=InMemorySaver())


# ---------------------------------------------------------------------
# run_agent() — a plain-function wrapper around the graph so callers
# don't need to know about threads/checkpointers/Command(resume=...).
# ---------------------------------------------------------------------

def _default_approval_callback(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """Default human-approval gate: an interactive CLI prompt."""
    print(f"\n[APPROVAL REQUIRED] The agent wants to call '{tool_name}' with:")
    print(json.dumps(arguments, indent=2))
    answer = input("Approve this action? [y/N]: ").strip().lower()
    return answer == "y"


def run_agent(
    prompt: str,
    caller: Optional[CallerContext] = None,
    approval_callback: Callable[[str, Dict[str, Any]], bool] = _default_approval_callback,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Runs one full agent turn: model call, optional tool calls
    (pausing for approval), then a final text answer."""
    thread_id = thread_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "messages": [HumanMessage(content=prompt)],
        "caller_id": caller.caller_id if caller else None,
        "caller_role": caller.role if caller else None,
        "hops": 0,
    }

    result = graph.invoke(initial_state, config)

    while "__interrupt__" in result:
        question = result["__interrupt__"][-1].value
        approved = approval_callback(question["tool"], question["arguments"])
        result = graph.invoke(Command(resume={"approved": approved}), config)

    tool_calls: List[Dict[str, Any]] = []
    messages = result["messages"]
    for i, message in enumerate(messages):
        if isinstance(message, AIMessage) and message.tool_calls:
            for call in message.tool_calls:
                # The ToolMessage(s) immediately following carry the result(s).
                matching_result = next(
                    (
                        json.loads(m.content)
                        for m in messages[i + 1:]
                        if isinstance(m, ToolMessage) and m.tool_call_id == call["id"]
                    ),
                    None,
                )
                tool_calls.append({
                    "name": call["name"],
                    "arguments": call["args"],
                    "result": matching_result,
                })

    final_text = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            final_text = message.content
            break

    return {
        "output_text": final_text,
        "tool_calls": tool_calls,
        "hops_used": result.get("hops", 0),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Software-Engineering QA Agent — Week 4")
    parser.add_argument("prompt", nargs="+", help="The request to send the agent.")
    parser.add_argument(
        "--caller", required=True,
        help="The user_id of whoever is running this agent (required — see authorization.py).",
    )
    parser.add_argument(
        "--role", default="self", choices=["self", "support"],
        help="'self' acts on own account only; 'support' may act on any. Default: self.",
    )
    args = parser.parse_args()

    user_prompt = " ".join(args.prompt)
    caller_ctx = CallerContext(caller_id=args.caller, role=args.role)
    print(f"[agent] Caller: {caller_ctx.caller_id} (role: {caller_ctx.role})")
    print(f"[agent] Prompt: {user_prompt}\n")

    outcome = run_agent(user_prompt, caller=caller_ctx)

    print("\n[agent] Tool calls made:")
    for tc in outcome["tool_calls"]:
        print(f"  - {tc['name']}({tc['arguments']}) -> {tc['result']}")

    print("\n[agent] Final answer:")
    print(outcome["output_text"])
