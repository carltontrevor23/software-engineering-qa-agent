from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(__file__))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import tools_condition

from model_client import API_KEY, MODEL_NAME
import qa_tools
from approval import (
    HIGH_IMPACT_TOOLS,
    is_high_impact,
    request_human_approval,
)
import workflow
from memory import advisory, format_history, get_case_history, record_case

# Versioned agent prompt (Week 5): the rules live in prompts/, not in code.
PROMPT_VERSION = "v2.0"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / f"agent_system_prompt_{PROMPT_VERSION}.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

# Upper bound on assistant -> tool round-trips per run. The longest legitimate path is
# 5 tool steps (search, propose, run, draft, file); 7 lets that path plus one re-plan
# step still end in a final assistant answer (route_after_tools stops at hops >= MAX_HOPS).
MAX_HOPS = 7
# Hard limit: how many tool calls the agent may make in one step.
MAX_CALLS_PER_STEP = 1


class AgentState(MessagesState):
    """Session state for one run (RAM only). Workflow fields are written by
    execute_tools/assistant from tool results, never from LLM text; see workflow.py."""
    hops: int
    requirement_id: Optional[str]
    phase: str
    test_file: Optional[str]
    test_outcome: Optional[str]
    draft_path: Optional[str]
    stop_reason: Optional[str]
    proposals_made: int


def initial_state(prompt: str) -> Dict[str, Any]:
    return {"messages": [HumanMessage(content=prompt)], "hops": 0, **workflow.new_workflow()}


# Tool 1 — read-only RAG search over docs/requirements.
@tool
def search_requirements(query: str, top_k: int = 3) -> Dict[str, Any]:
    """Search the requirement documents and return matching requirement ids, sources and text."""
    return qa_tools.search_requirements(query, top_k)


# Tool 2 — model proposes pytest tests; written only to sandbox/generated/.
@tool
def propose_tests(requirement_id: str) -> Dict[str, Any]:
    """Propose pytest tests for one requirement (e.g. REQ-2.1) and save them in the sandbox."""
    return qa_tools.propose_tests(requirement_id)


# Tool 3 — runs allowed test files in the sandbox (no shell, timeout, no secrets).
@tool
def run_tests(requirement_id: str, test_file: str) -> Dict[str, Any]:
    """Run a sandboxed test file for a requirement and report passed/failed counts."""
    return qa_tools.run_tests(requirement_id, test_file)


# Tool 4 — low-impact simulated side effect: a local Markdown draft.
@tool
def draft_issue(
    requirement_id: str, title: str, summary: str, failing_tests: List[str]
) -> Dict[str, Any]:
    """Draft an issue (not filed) describing failing tests for a requirement."""
    return qa_tools.draft_issue(requirement_id, title, summary, failing_tests)


# Tool 5 — HIGH IMPACT: files an issue; needs a human-approved signed token.
@tool
def file_issue(draft_path: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """File a drafted issue. Requires human approval."""
    return qa_tools.file_issue(draft_path, approval_token)


# Tool 6 — HIGH IMPACT: adds a generated test to the repo's suite; needs approval.
@tool
def save_test_to_suite(test_file: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Copy a generated test into the system-under-test suite. Requires human approval."""
    return qa_tools.save_test_to_suite(test_file, approval_token)


TOOLS = [
    search_requirements,
    propose_tests,
    run_tests,
    draft_issue,
    file_issue,
    save_test_to_suite,
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}

AGENT_CONTRACT = {
    "goal": "For one requirement, propose and run tests in the sandbox, and either report a "
            "pass or draft an issue that a human approves or rejects.",
    "prompt_version": PROMPT_VERSION,
    "approved_tools": sorted(TOOLS_BY_NAME),
    "high_impact_tools": sorted(HIGH_IMPACT_TOOLS & set(TOOLS_BY_NAME)),
    "max_hops": MAX_HOPS,
    "max_calls_per_step": MAX_CALLS_PER_STEP,
    "phases": list(workflow.PHASES),
    "stop_conditions": [
        "all_tests_passed",
        "issue_filed",
        "human_rejection",
        "tool_error",
        "requirement_not_found",
        "hop_budget_exhausted",
        "test_defect_reported",
    ],
}

# STEP 1 — bind tools to the model.
llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME, 
    google_api_key=API_KEY,
    timeout=60,
    max_retries=3,
    )
llm_with_tools = llm.bind_tools(TOOLS)


# STEP 2 — model decides: answer directly, or call a tool?
def assistant(state: AgentState) -> Dict[str, Any]:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
   
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = llm_with_tools.invoke(messages)
            if getattr(response, "tool_calls", None):
                return {"messages": [response]}
            # Final answer: close the run from the recorded phase, not from the answer text.
            return {"messages": [response], **workflow.finalize_on_answer(workflow.from_state(state))}
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            import time
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                time.sleep(32)
            else:
                time.sleep(2)

# STEP 3 — run the requested tool with Human-in-the-Loop interception.

def _run_one_tool(tool_name: str, args: Dict[str, Any], requirement_id: Optional[str] = None) -> Any:
    tool_obj = TOOLS_BY_NAME.get(tool_name)          # allow-list check
    if tool_obj is None:
        return {"status": "error", "error": f"Unknown tool '{tool_name}'."}

    if is_high_impact(tool_name):                    # human hand-off
        # Test-run history is printed for the human only; never sent to the LLM or hashed.
        case_key = requirement_id or qa_tools.requirement_id_from_args(args)
        history = get_case_history(case_key, limit=3, tool_name="run_tests")
        print(format_history(case_key, history))
        print(f"[ADVISORY] {advisory(history)} (advisory only - the decision is yours)")
        approved, token, message = request_human_approval(tool_name, args)
        if not approved:
            return {"status": "approval_required", "error": message}
        args["approval_token"] = token               # signed, single-use
    return tool_obj.invoke(args)


def _record(requirement_id: str, tool_name: str, result: Any, hops: int) -> None:
    status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
    test_outcome = failed_count = None
    if tool_name == "run_tests" and status == "success":
        test_outcome = result.get("test_outcome")
        failed_count = result.get("failed", 0) + result.get("errors", 0)
    record_case(requirement_id, tool_name, status, hops, test_outcome, failed_count)


def execute_tools(state: AgentState) -> Dict[str, Any]:
    last_message = state["messages"][-1]
    wf = workflow.from_state(state)
    hops = state.get("hops", 0)
    tool_messages = []
    for index, tool_call in enumerate(last_message.tool_calls):
        name = tool_call["name"]
        args = dict(tool_call.get("args", {}))
        executed = False
        if index >= MAX_CALLS_PER_STEP:
            result: Any = {
                "status": "error",
                "error": "Only one tool call is allowed per step; this call was skipped.",
            }
        elif name not in TOOLS_BY_NAME:
            result = {"status": "error", "error": f"Unknown tool '{name}'."}
        else:
            blocked = workflow.check_call(wf, name, args)   # phase guard + file pinning
            if blocked:
                result = {"status": "error", "error": blocked}
            else:
                result = _run_one_tool(name, args, requirement_id=wf["requirement_id"])
                wf.update(workflow.apply_result(wf, name, result))
                executed = True
        tool_messages.append(
            ToolMessage(content=str(result), tool_call_id=tool_call["id"], name=name)
        )
        if executed:
            key = wf["requirement_id"] or qa_tools.requirement_id_from_args(tool_call.get("args", {}))
            _record(key, name, result, hops)
    hops += 1
    if hops >= MAX_HOPS:
        wf.update(workflow.finalize_on_hop_limit(wf))
    return {"messages": tool_messages, "hops": hops, **wf}


# Stop condition — end the loop once the hop budget is spent.
def route_after_tools(state: AgentState) -> str:
    if state.get("hops", 0) >= MAX_HOPS:
        return END
    return "assistant"


# STEP 4 — wire into a graph; tools_condition routes tool calls vs END.
builder = StateGraph(AgentState)
builder.add_node("assistant", assistant)
builder.add_node("execute_tools", execute_tools)
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition, {"tools": "execute_tools", END: END})
builder.add_conditional_edges(
    "execute_tools", route_after_tools, {"assistant": "assistant", END: END}
)
graph = builder.compile()

STOPPED_MESSAGE = "Stopped: reached the maximum number of tool-call steps"


def run(prompt: str) -> str:
    """Sends one prompt through the graph and returns the model's final text answer."""
    result = graph.invoke(initial_state(prompt))
    print(f"[stop_reason] {result.get('stop_reason')} (phase {result.get('phase')})")
    # Hop limit hit: the loop ended on a tool result instead of an AI reply.
    if not isinstance(result["messages"][-1], AIMessage):
        return STOPPED_MESSAGE
    final_replies = [m for m in result["messages"] if isinstance(m, AIMessage) and m.content]
    if not final_replies:
        return ""
    content = final_replies[-1].content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


if __name__ == "__main__":
    # Usage: python src/tool_calling.py "Check REQ-2.1 against the code"
    # High-impact tools stop at the interactive approval prompt in approval.py.
    if len(sys.argv) < 2:
        print('Usage: python src/tool_calling.py "Check REQ-2.1 against the code"')
        sys.exit(1)
    print(run(" ".join(sys.argv[1:])))
