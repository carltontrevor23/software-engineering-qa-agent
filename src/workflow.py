"""
src/workflow.py

Explicit workflow state for one QA run (Week 6, realigned).

The phase machine decides which tools are allowed next, and pins run_tests,
file_issue and save_test_to_suite to the exact files produced earlier in the
same run. Fields are updated only from tool results, never from LLM text.
Used by the LangGraph agent (guard_middleware.py) and the MCP server (mcp_server.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

START = "START"
REQUIREMENT_RESOLVED = "REQUIREMENT_RESOLVED"
TESTS_PROPOSED = "TESTS_PROPOSED"
TESTS_RUN_PASSED = "TESTS_RUN_PASSED"
TESTS_RUN_FAILED = "TESTS_RUN_FAILED"
ISSUE_DRAFTED = "ISSUE_DRAFTED"
DONE = "DONE"
STOPPED = "STOPPED"
PHASES = (START, REQUIREMENT_RESOLVED, TESTS_PROPOSED, TESTS_RUN_PASSED,
          TESTS_RUN_FAILED, ISSUE_DRAFTED, DONE, STOPPED)
TERMINAL_PHASES = (DONE, STOPPED)

ALLOWED_TOOLS_BY_PHASE = {
    START: {"search_requirements", "propose_tests"},
    REQUIREMENT_RESOLVED: {"propose_tests", "search_requirements"},
    TESTS_PROPOSED: {"run_tests"},
    TESTS_RUN_PASSED: {"save_test_to_suite"},
    TESTS_RUN_FAILED: {"draft_issue", "propose_tests"},
    ISSUE_DRAFTED: {"file_issue"},
    DONE: set(),
    STOPPED: set(),
}
# One initial proposal plus one regenerate after a failed run.
MAX_PROPOSALS = 2

FIELDS = ("requirement_id", "phase", "test_file", "test_outcome", "draft_path",
          "stop_reason", "proposals_made")


def new_workflow() -> Dict[str, Any]:
    return {
        "requirement_id": None,
        "phase": START,
        "test_file": None,
        "test_outcome": None,
        "draft_path": None,
        "stop_reason": None,
        "proposals_made": 0,
    }


def from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """The workflow fields of a graph state, with defaults for any that are missing."""
    wf = new_workflow()
    for key in FIELDS:
        if state.get(key) is not None:
            wf[key] = state[key]
    return wf


def _same_file(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return Path(a).resolve() == Path(b).resolve()


def check_call(wf: Dict[str, Any], tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """Return an error message if the call is not allowed now, else None."""
    phase = wf["phase"]
    if tool_name not in ALLOWED_TOOLS_BY_PHASE.get(phase, set()):
        return f"Tool {tool_name} is not allowed in phase {phase}."
    if tool_name == "propose_tests" and phase == TESTS_RUN_FAILED and wf["proposals_made"] >= MAX_PROPOSALS:
        return f"Tool propose_tests is not allowed in phase {phase}: tests were already regenerated once."
    if tool_name in ("run_tests", "save_test_to_suite") and not _same_file(args.get("test_file"), wf["test_file"]):
        return f"{tool_name} may only use the test file proposed in this run ({wf['test_file']})."
    if tool_name == "file_issue" and not _same_file(args.get("draft_path"), wf["draft_path"]):
        return f"file_issue may only file the draft written in this run ({wf['draft_path']})."
    return None


def apply_result(wf: Dict[str, Any], tool_name: str, result: Any) -> Dict[str, Any]:
    """Deterministic state update from one executed tool's result. Returns the changed fields."""
    if not isinstance(result, dict):
        return {"phase": STOPPED, "stop_reason": "tool_error"}
    status = result.get("status")

    if tool_name == "search_requirements":
        hits = result.get("results") or []
        if status == "success" and hits:
            return {"phase": REQUIREMENT_RESOLVED, "requirement_id": hits[0].get("requirement_id")}
        if wf["requirement_id"]:
            return {}  # a re-plan search found nothing; keep the earlier resolution
        if status == "success":
            return {"phase": STOPPED, "stop_reason": "requirement_not_found"}
        return {"phase": STOPPED, "stop_reason": "tool_error"}

    if tool_name == "propose_tests":
        if status == "success":
            return {"phase": TESTS_PROPOSED, "requirement_id": result.get("requirement_id"),
                    "test_file": result.get("test_file"), "test_outcome": None,
                    "proposals_made": wf["proposals_made"] + 1}
        if "Unknown requirement" in str(result.get("error", "")):
            return {"phase": STOPPED, "stop_reason": "requirement_not_found"}
        return {"phase": STOPPED, "stop_reason": "tool_error"}

    if tool_name == "run_tests":
        if status != "success":
            return {"phase": STOPPED, "stop_reason": "tool_error"}
        outcome = result.get("test_outcome")
        if outcome == "passed":
            return {"phase": TESTS_RUN_PASSED, "test_outcome": outcome, "stop_reason": "all_tests_passed"}
        return {"phase": TESTS_RUN_FAILED, "test_outcome": outcome}

    if tool_name == "draft_issue":
        if status == "success":
            return {"phase": ISSUE_DRAFTED, "draft_path": result.get("draft_path")}
        return {"phase": STOPPED, "stop_reason": "tool_error"}

    if tool_name == "file_issue":
        if status == "success":
            return {"phase": DONE, "stop_reason": "issue_filed"}
        if status == "approval_required":
            return {"phase": STOPPED, "stop_reason": "human_rejection"}
        return {"phase": STOPPED, "stop_reason": "tool_error"}

    if tool_name == "save_test_to_suite":
        if status == "success":
            return {"phase": DONE}
        if status == "approval_required":
            return {"phase": STOPPED, "stop_reason": "human_rejection"}
        return {"phase": STOPPED, "stop_reason": "tool_error"}

    return {}


def finalize_on_answer(wf: Dict[str, Any]) -> Dict[str, Any]:
    """The model gave a final answer: close the run and classify why it stopped."""
    if wf["phase"] in TERMINAL_PHASES:
        return {} if wf["stop_reason"] else {"stop_reason": "unclassified"}
    reasons = {
        START: "requirement_not_found",
        TESTS_RUN_PASSED: "all_tests_passed",
        # Tests failed and the agent judged the generated test wrong, so it filed nothing.
        TESTS_RUN_FAILED: "test_defect_reported",
    }
    # Any other phase means the agent left the workflow early; not a contract stop condition.
    return {"phase": DONE, "stop_reason": wf["stop_reason"] or reasons.get(wf["phase"], "unclassified")}


def finalize_on_hop_limit(wf: Dict[str, Any]) -> Dict[str, Any]:
    if wf["phase"] in TERMINAL_PHASES:
        return {}
    return {"phase": STOPPED, "stop_reason": "hop_budget_exhausted"}
