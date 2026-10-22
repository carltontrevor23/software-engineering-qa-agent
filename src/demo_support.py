"""
src/demo_support.py

Shared pieces for the Week 5 demo runner (demo/run_demo.py), the trace capture
script (src/capture_week5_traces.py) and the agent tests:

  - planted_bug_sut(): run against a temporary SUT copy with one planted defect.
    The real sut/ folder is never modified.
  - ScriptedLLM: an offline stand-in for the live model that follows the agent rules
    deterministically. Every message it writes starts with "[SCRIPTED LLM]".
  - fixture_model_reply(): the hand-written REQ-2.1 tests, returned in place of
    the model's propose_tests reply in offline mode.
  - trace_run() / stop_reason(): stream one graph run, record a compact per-hop
    trace and classify why it stopped.

This module does not import the agent, so callers pass in the graph (see agent.py and
offline.py).
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import sandbox

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_TESTS = PROJECT_ROOT / "demo" / "fixtures" / "req_2_1_tests.py"
SCRIPTED_LABEL = "[SCRIPTED LLM]"

PLANTED_BUG_FROM = "if balance < self.UPGRADE_COST:"
PLANTED_BUG_TO = "if balance <= self.UPGRADE_COST:"
SUT_FILE = Path("subscription_service") / "subscription_manager.py"


# ---------------------------------------------------------------------
# Planted defect (temporary SUT copy)
# ---------------------------------------------------------------------

@contextmanager
def planted_bug_sut() -> Iterator[Path]:
    """Copy the SUT to a temp folder, plant the boundary bug there, and point the
    sandbox at the copy for the duration of the block."""
    import project_config
    import qa_tools

    tmp_root = Path(tempfile.mkdtemp(prefix="inspectra_planted_"))
    copy = tmp_root / "sut"
    # The planted bug belongs to the bundled sample, whatever project .env points at.
    shutil.copytree(project_config.DEFAULT_CODE_DIR, copy, ignore=shutil.ignore_patterns("__pycache__"))
    target = copy / SUT_FILE
    source = target.read_text(encoding="utf-8")
    count = source.count(PLANTED_BUG_FROM)
    assert count == 1, f"Expected exactly one '{PLANTED_BUG_FROM}' in the SUT, found {count}."
    target.write_text(source.replace(PLANTED_BUG_FROM, PLANTED_BUG_TO), encoding="utf-8")

    saved = (sandbox.SUT_DIR, sandbox.ALLOWED_TEST_DIRS, qa_tools.REQUIREMENTS_DIR)
    qa_tools.REQUIREMENTS_DIR = project_config.DEFAULT_REQUIREMENTS_DIR
    sandbox.SUT_DIR = copy
    sandbox.ALLOWED_TEST_DIRS = [sandbox.GENERATED_DIR, copy / "tests"]
    try:
        yield copy
    finally:
        sandbox.SUT_DIR, sandbox.ALLOWED_TEST_DIRS, qa_tools.REQUIREMENTS_DIR = saved
        shutil.rmtree(tmp_root, ignore_errors=True)


def fixture_model_reply(*_args: Any, **_kwargs: Any) -> str:
    """Stand-in for get_model_response in offline mode."""
    code = FIXTURE_TESTS.read_text(encoding="utf-8")
    return f"{SCRIPTED_LABEL} Hand-written fixture tests for REQ-2.1.\n```python\n{code}```"


# ---------------------------------------------------------------------
# Scripted LLM (offline mode)
# ---------------------------------------------------------------------

def _parse_result(content: Any) -> Dict[str, Any]:
    """A tool result as a dict: JSON (what the agent's tool node produces) or a Python repr."""
    text = _text(content)
    for parse in (json.loads, ast.literal_eval):
        try:
            value = parse(text)
        except (ValueError, SyntaxError):
            continue
        return value if isinstance(value, dict) else {}
    return {}


class ScriptedLLM:
    """Deterministic stand-in for llm_with_tools.invoke().

    Follows the v2.0 agent rules: search -> propose -> run -> (draft -> file) -> stop.
    With replan=True it repeats the search once, to exercise the hop budget.
    """

    def __init__(self, replan: bool = False):
        self.replan = replan
        self._calls = 0

    def _tool_call(self, name: str, args: Dict[str, Any]) -> AIMessage:
        self._calls += 1
        return AIMessage(
            content=f"{SCRIPTED_LABEL} calling {name}",
            tool_calls=[{"name": name, "args": args, "id": f"scripted-{self._calls}", "type": "tool_call"}],
        )

    @staticmethod
    def _answer(text: str) -> AIMessage:
        return AIMessage(content=f"{SCRIPTED_LABEL} {text}")

    def invoke(self, messages: List[Any]) -> AIMessage:
        request = next((m for m in messages if isinstance(m, HumanMessage)), None)
        request_text = str(request.content) if request else ""
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]

        if not tool_messages:
            return self._tool_call("search_requirements", {"query": request_text})

        last = tool_messages[-1]
        result = _parse_result(last.content)
        status = result.get("status")
        if status in ("error", "approval_required") and last.name != "file_issue":
            return self._answer(f"Stopped: {last.name} returned {status}: {result.get('error', '')}")

        if last.name == "search_requirements":
            searches = sum(1 for m in tool_messages if m.name == "search_requirements")
            if self.replan and searches == 1:
                return self._tool_call("search_requirements", {"query": request_text + " acceptance criteria"})
            explicit = re.search(r"REQ-\d+(?:\.\d+)*", request_text)
            hits = result.get("results") or []
            requirement_id = explicit.group(0) if explicit else (hits[0]["requirement_id"] if hits else None)
            if not requirement_id:
                return self._answer("No matching requirement was found, so no tests were proposed.")
            return self._tool_call("propose_tests", {"requirement_id": requirement_id})

        if last.name == "propose_tests":
            return self._tool_call("run_tests", {
                "requirement_id": result["requirement_id"], "test_file": result["test_file"],
            })

        if last.name == "run_tests":
            requirement_id = result.get("requirement_id", "unknown")
            if result.get("test_outcome") == "passed":
                return self._answer(
                    f"All {result.get('passed', 0)} tests for {requirement_id} passed. No issue drafted. "
                    "I can save these tests to sut/tests if you ask (that needs human approval)."
                )
            if result.get("test_outcome") == "no_tests":
                return self._answer(f"No tests were collected for {requirement_id}; nothing to report.")
            failing = [f["test_name"] for f in result.get("failures", [])]
            return self._tool_call("draft_issue", {
                "requirement_id": requirement_id,
                "title": f"{requirement_id}: implementation contradicts the requirement",
                "summary": (
                    "CODE defect: the failing tests check behaviour the requirement states explicitly, "
                    f"so the implementation is wrong. Failing: {', '.join(failing) or 'see run output'}."
                ),
                "failing_tests": failing,
            })

        if last.name == "draft_issue":
            return self._tool_call("file_issue", {"draft_path": result["draft_path"]})

        if last.name == "file_issue":
            if status == "success":
                return self._answer(f"CODE defect found. Issue filed at {result.get('filed_path')}.")
            return self._answer(
                "The human rejected filing the issue, so nothing was filed. "
                "The draft stays in evidence/issues/drafts for review."
            )

        return self._answer("Stopping: no further approved step.")


# ---------------------------------------------------------------------
# Tracing and stop classification
# ---------------------------------------------------------------------

def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def _short_args(args: Dict[str, Any]) -> str:
    parts = []
    for key, value in args.items():
        if key in ("draft_path", "test_file"):
            value = Path(str(value)).name
        text = str(value)
        parts.append(f"{key}={text[:50] + '...' if len(text) > 50 else text}")
    return ", ".join(parts)


def trace_run(
    graph: Any,
    prompt: str,
    printer: Optional[Callable[[str], None]] = print,
    initial_state: Optional[Dict[str, Any]] = None,
    decide: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run the graph once and return (final_state, steps).

    Each step records hop, node, tool, args, status/test_outcome, workflow phase and latency.
    The graph must have a checkpointer, so the run can pause for human approval. When it
    does, decide(action_request) is called for each pending action and must return
    {"type": "approve"} or {"type": "reject", "message": ...}; the run then resumes.
    """
    from uuid import uuid4

    from langgraph.types import Command

    state = initial_state or {"messages": [HumanMessage(content=prompt)]}
    config = {"configurable": {"thread_id": uuid4().hex}}
    payload: Any = state
    final_state: Dict[str, Any] = state
    steps: List[Dict[str, Any]] = []
    seen_calls = set()
    hops = 0
    started = time.perf_counter()

    while True:
        interrupts = None
        for mode, chunk in graph.stream(payload, config, stream_mode=["updates", "values"]):
            if mode == "values":
                final_state = chunk
                continue
            if "__interrupt__" in chunk:
                interrupts = chunk["__interrupt__"]
                continue
            latency = round(time.perf_counter() - started, 2)
            started = time.perf_counter()
            for node, delta in chunk.items():
                if not isinstance(delta, dict):
                    continue
                hops = delta.get("hops", hops)
                phase = delta.get("phase")
                for msg in delta.get("messages", []):
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        call = msg.tool_calls[0]
                        if call["id"] in seen_calls:  # the approval hook re-emits the model message
                            continue
                        seen_calls.add(call["id"])
                        step = {"hop": hops, "node": node, "action": "call_tool", "tool": call["name"],
                                "args": call["args"], "latency_s": latency}
                        line = f"hop {hops} | {node:<13} | call {call['name']}({_short_args(call['args'])})"
                    elif isinstance(msg, AIMessage):
                        step = {"hop": hops, "node": node, "action": "final_answer",
                                "text": _text(msg.content).strip(), "latency_s": latency}
                        line = f"hop {hops} | {node:<13} | final answer"
                    elif isinstance(msg, ToolMessage):
                        result = _parse_result(msg.content)
                        step = {"hop": hops, "node": node, "action": "tool_result", "tool": msg.name,
                                "status": result.get("status"), "test_outcome": result.get("test_outcome"),
                                "result": result or str(msg.content), "latency_s": latency}
                        outcome = f" test_outcome={result['test_outcome']}" if result.get("test_outcome") else ""
                        line = f"hop {hops} | {node:<13} | {msg.name} -> status={result.get('status')}{outcome}"
                    else:
                        continue
                    if phase:
                        step["phase"] = phase
                        line += f" [phase {phase}]"
                    steps.append(step)
                    if printer:
                        printer(f"{line}  ({latency}s)")
        if not interrupts:
            break
        if decide is None:
            raise RuntimeError("The run paused for human approval but no decide() was given.")
        decisions = []
        for action in interrupts[0].value["action_requests"]:
            decision = decide(action)
            decisions.append(decision)
            steps.append({"hop": hops, "node": "human", "action": "human_decision",
                          "tool": action["name"], "decision": decision["type"]})
            if printer:
                printer(f"hop {hops} | {'human':<13} | {action['name']} -> {decision['type']}")
        payload = Command(resume={"decisions": decisions})
        started = time.perf_counter()
    return final_state, steps


def stop_reason(final_state: Dict[str, Any]) -> str:
    """Classify the run against AGENT_CONTRACT['stop_conditions'].

    Uses the stop_reason recorded in the workflow state when present."""
    if final_state.get("stop_reason"):
        return final_state["stop_reason"]
    messages = final_state.get("messages", [])
    if messages and not isinstance(messages[-1], AIMessage):
        return "hop_budget_exhausted"
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    if not tool_messages:
        return "requirement_not_found"
    last = tool_messages[-1]
    result = _parse_result(last.content)
    status = result.get("status")
    if last.name == "file_issue":
        return "issue_filed" if status == "success" else "human_rejection"
    if status == "approval_required":
        return "human_rejection"
    if status == "error":
        if "Unknown requirement" in str(result.get("error", "")):
            return "requirement_not_found"
        return "tool_error"
    if last.name == "search_requirements" and not result.get("results"):
        return "requirement_not_found"
    if last.name == "run_tests" and result.get("test_outcome") == "passed":
        return "all_tests_passed"
    if last.name == "run_tests" and result.get("test_outcome") in ("failed", "no_tests"):
        # Tests failed but the agent judged it a TEST defect and filed nothing.
        return "test_defect_reported"
    # Not a contract stop condition: the agent stopped somewhere unexpected.
    return "unclassified"
