"""
src/guard_middleware.py

Inspectra's deterministic controls as create_agent middleware (Week 8, replaces the
hand-written assistant and tool-execution nodes of the old tool-calling module).

  before_agent  validate and clean the request; reset the workflow state for this run
  before_model  record a human rejection; stop when the hop budget is spent
  after_model   count a tool step; on a final answer: redact secrets, withhold claims no
                tool result supports, and classify the stop reason
  wrap_tool_call allow-list, phase guard, file pinning and one call per step run before
                the tool; the result updates the workflow state, never the model text

All decisions come from workflow.py and guardrails.py. No model is involved. The human
approval gate itself is HumanInTheLoopMiddleware (see approval_config below).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from langchain.agents.middleware import AgentMiddleware, HumanInTheLoopMiddleware, ToolCallRequest, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

import approval
import guardrails
import memory
import qa_tools
import workflow
from agent_state import InspectraState
from agent_tools import TOOLS_BY_NAME

# Upper bound on model -> tool round-trips per run. The longest legitimate path is 5 tool
# steps (search, propose, run, draft, file); 7 lets that path plus one re-plan step still
# end in a final answer.
MAX_HOPS = 7
# Hard limit: how many tool calls the agent may make in one step.
MAX_CALLS_PER_STEP = 1
STOPPED_MESSAGE = "Stopped: reached the maximum number of tool-call steps"
# Written by ModelRetryMiddleware (via model_failure_message) when every retry has failed.
MODEL_UNAVAILABLE_PREFIX = "[MODEL UNAVAILABLE]"
MAX_MODEL_ERROR_CHARS = 300
SKIPPED_MESSAGE = "Only one tool call is allowed per step; this call was skipped."
# HumanInTheLoopMiddleware writes this text into the tool result when the human rejects.
REJECTED_PREFIX = "User rejected the tool call"


def model_failure_message(exc: Exception) -> str:
    """The reply ModelRetryMiddleware gives when the model is unreachable after all retries."""
    detail, _ = guardrails.redact(f"{type(exc).__name__}: {exc}")
    return f"{MODEL_UNAVAILABLE_PREFIX} The model could not be reached. {detail[:MAX_MODEL_ERROR_CHARS]}"


def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def _last_message(messages: List[Any], kind: type) -> Optional[Any]:
    return next((m for m in reversed(messages) if isinstance(m, kind)), None)


def _call_index(messages: List[Any], tool_call_id: Optional[str]) -> int:
    """Position of this call within the model message that requested it."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.tool_calls:
            ids = [call.get("id") for call in message.tool_calls]
            if tool_call_id in ids:
                return ids.index(tool_call_id)
    return 0


def blocked_reason(state: Dict[str, Any], tool_call: Dict[str, Any]) -> Optional[str]:
    """Why this call must not run now (or None). Used both before the human is asked and
    before the tool runs, so a call the guard would refuse never reaches the approver."""
    name = tool_call["name"]
    if _call_index(state.get("messages", []), tool_call.get("id")) >= MAX_CALLS_PER_STEP:
        return SKIPPED_MESSAGE
    if name not in TOOLS_BY_NAME:
        return f"Unknown tool '{name}'."
    return workflow.check_call(workflow.from_state(state), name, dict(tool_call.get("args", {})))


def _result_message(tool_call: Dict[str, Any], result: Dict[str, Any], status: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result), tool_call_id=tool_call["id"], name=tool_call["name"], status=status
    )


def pre_call(state: Dict[str, Any], tool_call: Dict[str, Any]) -> Tuple[Optional[ToolMessage], Dict[str, Any]]:
    """Returns (refusal, args). A refusal is a ToolMessage and the tool must not run."""
    reason = blocked_reason(state, tool_call)
    if reason:
        guardrails.record("tool_blocked", tool=tool_call["name"], reason=reason)
        return _result_message(tool_call, {"status": "error", "error": reason}, "error"), {}
    args = dict(tool_call.get("args", {}))
    if approval.is_high_impact(tool_call["name"]):
        # The human approved this exact call in HumanInTheLoopMiddleware (it runs first);
        # mint the signed single-use token the tool itself checks.
        args.pop("approval_token", None)
        args["approval_token"] = approval.create_approval_token(tool_call["name"], args)
    return None, args


def parse_result(message: Any) -> Dict[str, Any]:
    """The tool's result dict, from its ToolMessage content."""
    text = _text(getattr(message, "content", message))
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, dict):
        return value
    return {"status": "error", "error": text[:500]}


def post_call(state: Dict[str, Any], tool_call: Dict[str, Any], message: Any) -> Command:
    """Apply one executed tool's result to the workflow state (from the result, not model text)."""
    name = tool_call["name"]
    result = parse_result(message)
    wf = workflow.from_state(state)
    changes = workflow.apply_result(wf, name, result)
    wf.update(changes)

    content, redactions = guardrails.redact(_text(message.content))
    if redactions:
        guardrails.record("secret_redacted", where=name, count=redactions)
    tool_message = message.model_copy(update={"content": content})

    key = wf["requirement_id"] or qa_tools.requirement_id_from_args(tool_call.get("args", {}))
    status = result.get("status", "unknown")
    test_outcome = failed_count = None
    if name == "run_tests" and status == "success":
        test_outcome = result.get("test_outcome")
        failed_count = result.get("failed", 0) + result.get("errors", 0)
    memory.record_case(key, name, status, max(state.get("hops", 1) - 1, 0), test_outcome, failed_count)
    return Command(update={"messages": [tool_message], **changes})


def approval_description(tool_call: Dict[str, Any], state: Dict[str, Any], runtime: Any) -> str:
    """What the human approver sees. The requirement's recent test runs are for the human
    only: this text goes to the approval card, never into the model's messages."""
    args = {k: v for k, v in tool_call.get("args", {}).items() if k != "approval_token"}
    key = state.get("requirement_id") or qa_tools.requirement_id_from_args(args)
    history = memory.get_case_history(key, limit=3, tool_name="run_tests")
    return "\n".join([
        f"HUMAN APPROVAL REQUIRED: {tool_call['name']}",
        f"Arguments: {json.dumps(args, indent=2)}",
        "This action files an issue or changes the repository's test suite.",
        memory.format_history(key, history),
        f"[ADVISORY] {memory.advisory(history)} (advisory only - the decision is yours)",
    ])


def should_ask_human(request: ToolCallRequest) -> bool:
    return blocked_reason(request.state, request.tool_call) is None


def approval_config() -> Dict[str, Any]:
    """interrupt_on for HumanInTheLoopMiddleware: approve or reject only. No edit, so the
    reviewer cannot swap the file after the guard pinned it."""
    return {
        name: {
            "allowed_decisions": ["approve", "reject"],
            "description": approval_description,
            "when": should_ask_human,
        }
        for name in sorted(approval.HIGH_IMPACT_TOOLS)
    }


class ApprovalGate(HumanInTheLoopMiddleware):
    """HumanInTheLoopMiddleware whose async hook runs in a worker thread. The stock async hook
    calls the synchronous one on the event loop, and the guard check and approval card read
    files (path resolution, case history), which the Studio server rejects as blocking."""

    async def aafter_model(self, state: Any, runtime: Any) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.after_model, state, runtime)


class InspectraGuard(AgentMiddleware[InspectraState]):
    state_schema = InspectraState

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: InspectraState, runtime: Any) -> Optional[Dict[str, Any]]:
        last = _last_message(state.get("messages", []), HumanMessage)
        text = _text(last.content) if last else ""
        # A follow-up ("save those tests", "add a test for X") continues a finished run;
        # any other message starts fresh. The human still approves every save.
        carried = workflow.carry_over(state, text)
        fresh = {**(carried or workflow.new_workflow()), "hops": 0}
        ok, reason = guardrails.validate_request(text)
        if not ok:
            guardrails.record("input_rejected", tool="request", reason=reason)
            return {
                **fresh,
                "phase": workflow.STOPPED,
                "stop_reason": "request_rejected",
                "messages": [AIMessage(content=f"[GUARDRAIL] Request rejected: {reason}")],
                "jump_to": "end",
            }
        cleaned = guardrails.clean_text(text)
        if cleaned != text:
            fresh["messages"] = [HumanMessage(content=cleaned, id=last.id)]
        return fresh

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: InspectraState, runtime: Any) -> Optional[Dict[str, Any]]:
        wf = workflow.from_state(state)
        updates: Dict[str, Any] = {}
        recent = []
        for message in reversed(state.get("messages", [])):
            if not isinstance(message, ToolMessage):
                break
            recent.append(message)
        rejected = any(
            m.status == "error" and m.name in approval.HIGH_IMPACT_TOOLS
            and _text(m.content).startswith(REJECTED_PREFIX)
            for m in recent
        )
        if rejected and wf["phase"] not in workflow.TERMINAL_PHASES:
            updates = {"phase": workflow.STOPPED, "stop_reason": "human_rejection"}
            wf.update(updates)
        if state.get("hops", 0) >= MAX_HOPS:
            updates.update(workflow.finalize_on_hop_limit(wf))
            wf.update(updates)
            reason = wf["stop_reason"]
            note = STOPPED_MESSAGE if reason == "hop_budget_exhausted" else f"Stopped: {reason}"
            updates["messages"] = [AIMessage(content=note)]
            updates["jump_to"] = "end"
        return updates or None

    def after_model(self, state: InspectraState, runtime: Any) -> Optional[Dict[str, Any]]:
        message = _last_message(state.get("messages", []), AIMessage)
        if message is None:
            return None
        if message.tool_calls:
            return {"hops": state.get("hops", 0) + 1}
        if _text(message.content).startswith(MODEL_UNAVAILABLE_PREFIX):
            # Not an answer: the model never replied. Say so instead of guessing a reason.
            guardrails.record("model_unavailable")
            return {"phase": workflow.STOPPED, "stop_reason": "model_unavailable"}
        # Final answer: close the run from the recorded phase, not from the answer text.
        wf = workflow.from_state(state)
        updates = workflow.finalize_on_answer(wf)
        text, redactions = guardrails.redact(_text(message.content))
        if redactions:
            guardrails.record("secret_redacted", where="final_answer", count=redactions)
        problems = guardrails.check_final_answer(text, {**wf, **updates})
        if problems:
            guardrails.record("answer_withheld", problems=problems)
            text = (
                "[GUARDRAIL] The model's answer was withheld because it "
                + "; ".join(problems) + ". " + guardrails.verified_summary({**wf, **updates})
            )
        if redactions or problems:
            updates = {**updates, "messages": [message.model_copy(update={"content": text})]}
        return updates or None

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        refusal, args = pre_call(request.state, request.tool_call)
        if refusal:
            return refusal
        message = handler(request.override(tool_call={**request.tool_call, "args": args}))
        return post_call(request.state, request.tool_call, message)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        # pre_call/post_call touch the filesystem (path checks, case history); keep them
        # off the event loop.
        refusal, args = await asyncio.to_thread(pre_call, request.state, request.tool_call)
        if refusal:
            return refusal
        message = await handler(request.override(tool_call={**request.tool_call, "args": args}))
        return await asyncio.to_thread(post_call, request.state, request.tool_call, message)
