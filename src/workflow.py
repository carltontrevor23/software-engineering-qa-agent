"""
src/workflow.py

Explicit workflow state for one QA run (Week 6, realigned).

The phase machine decides which tools are allowed next, and pins run_tests,
file_issue and save_test_to_suite to the exact files produced earlier in the
same run. Fields are updated only from tool results, never from LLM text.
Used by the LangGraph agent (guard_middleware.py) and the MCP server (mcp_server.py).

Follow-ups: a later message in the same thread may continue a finished run (save the
tests, refine them, ask about the code) through carry_over(); anything else starts fresh.
"""

from __future__ import annotations

import re
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
    START: {"search_requirements", "propose_tests", "read_code"},
    REQUIREMENT_RESOLVED: {"propose_tests", "search_requirements", "read_code"},
    TESTS_PROPOSED: {"run_tests"},
    TESTS_RUN_PASSED: {"save_test_to_suite", "refine_tests", "read_code"},
    TESTS_RUN_FAILED: {"draft_issue", "propose_tests", "refine_tests", "read_code"},
    ISSUE_DRAFTED: {"file_issue"},
    DONE: set(),
    STOPPED: set(),
}
# One initial proposal plus one regenerate after a failed run.
MAX_PROPOSALS = 2
# Proposals plus refinements per thread (a refinement writes a new test file like a proposal).
MAX_TEST_VERSIONS = 5

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
    if tool_name == "refine_tests" and wf["proposals_made"] >= MAX_TEST_VERSIONS:
        return f"Tool refine_tests is not allowed: {MAX_TEST_VERSIONS} test versions were already written."
    if tool_name in ("run_tests", "save_test_to_suite", "refine_tests") and not _same_file(
        args.get("test_file"), wf["test_file"]
    ):
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

    if tool_name in ("propose_tests", "refine_tests"):
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
            return {"phase": DONE, "stop_reason": "tests_saved"}
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


_REQUIREMENT_MENTION_RE = re.compile(r"REQ-\d+(?:\.\d+)*", re.I)
_CARRY_PHASES = {"all_tests_passed": TESTS_RUN_PASSED, "test_defect_reported": TESTS_RUN_FAILED}


def carry_over(state: Dict[str, Any], request_text: str) -> Optional[Dict[str, Any]]:
    """Workflow fields for a follow-up message, or None when the message starts a fresh run.

    Only a run that ended with tests that passed, or with a test judged wrong, can be continued,
    and only by a message that names no requirement: naming one (even the same one) means
    "check it", which starts over. The test file stays pinned, so a follow-up can act only on
    the tests the previous run produced. Human approval is still asked for every save.
    """
    previous = from_state(state)
    if previous["phase"] != DONE or not previous["test_file"] or not previous["requirement_id"]:
        return None
    phase = _CARRY_PHASES.get(previous["stop_reason"])
    if phase is None or _REQUIREMENT_MENTION_RE.search(request_text or ""):
        return None
    return {**previous, "phase": phase, "stop_reason": None, "draft_path": None}
