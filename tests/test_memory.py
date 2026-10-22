"""
tests/test_memory.py

Week 6 (realigned) persistent memory: requirement test-run history.
Round trip, empty start, deletion, retention purge, the deterministic advisory,
and a guard that the history shown to the human approver never leaks to the LLM
or into the approval token arguments.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# The module objects the agent actually uses (imported by bare name from src/).
import approval
import demo_support
import memory
import qa_tools
import sandbox
import workflow
from offline import build_offline_agent


def test_record_and_retrieve_round_trip():
    memory.record_case("REQ-2.1", "search_requirements", "success", 0)
    memory.record_case("REQ-2.4", "run_tests", "error", 0)
    memory.record_case("REQ-2.1", "run_tests", "success", 1, test_outcome="failed", failed_count=2)
    memory.record_case("REQ-2.1", "file_issue", "approval_required", 2)

    history = memory.get_case_history("REQ-2.1", limit=2)
    assert [(h["tool_name"], h["status"], h["hops"]) for h in history] == [
        ("file_issue", "approval_required", 2),
        ("run_tests", "success", 1),
    ]
    assert history[1]["test_outcome"] == "failed" and history[1]["failed_count"] == 2
    assert all(h["requirement_id"] == "REQ-2.1" for h in history)
    assert all(h["timestamp"].endswith("+00:00") for h in history)

    assert len(memory.get_case_history("REQ-2.1", limit=3)) == 3
    assert [h["tool_name"] for h in memory.get_case_history("REQ-2.1", tool_name="run_tests")] == ["run_tests"]
    assert [h["status"] for h in memory.get_case_history("REQ-2.4")] == ["error"]


def test_records_hold_only_metadata_fields():
    memory.record_case("REQ-2.1", "run_tests", "success", 1, test_outcome="passed", failed_count=0)
    entry = memory.get_case_history("REQ-2.1")[0]
    assert set(entry) == {"timestamp", "requirement_id", "tool_name", "status", "hops",
                          "test_outcome", "failed_count"}


def test_get_case_history_empty_when_no_file():
    assert not Path(memory.MEMORY_FILE).exists()
    assert memory.get_case_history("REQ-2.1") == []


def test_delete_requirement_history():
    memory.record_case("REQ-2.1", "run_tests", "success", 0)
    memory.record_case("REQ-2.4", "run_tests", "success", 0)
    memory.record_case("REQ-2.1", "file_issue", "error", 1)

    assert memory.delete_requirement_history("REQ-2.1") == 2
    assert memory.get_case_history("REQ-2.1") == []
    remaining = memory.get_case_history("REQ-2.4")
    assert len(remaining) == 1 and remaining[0]["tool_name"] == "run_tests"


def test_purge_expired_records():
    old = {"timestamp": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(),
           "requirement_id": "REQ-2.2", "tool_name": "run_tests", "status": "success", "hops": 0}
    fresh = {"timestamp": datetime.now(timezone.utc).isoformat(),
             "requirement_id": "REQ-2.3", "tool_name": "run_tests", "status": "success", "hops": 0}
    os.makedirs(memory.MEMORY_DIR, exist_ok=True)
    with open(memory.MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(old) + "\n")
        f.write(json.dumps(fresh) + "\n")

    assert memory.purge_expired_records(retention_days=30) == 1
    assert memory.get_case_history("REQ-2.2") == []
    assert len(memory.get_case_history("REQ-2.3")) == 1


def _run(outcome, failed=0):
    return {"tool_name": "run_tests", "test_outcome": outcome, "failed_count": failed,
            "status": "success", "timestamp": "2026-10-09T10:00:00+00:00"}


def test_advisory_recurring_failure():
    history = [_run("failed", 1), _run("failed", 1), _run("passed")]
    assert memory.advisory(history) == "RECURRING: failed in 2 of the last 3 runs."


def test_advisory_first_failure_after_passing_runs():
    history = [_run("failed", 1), _run("passed"), _run("passed")]
    assert memory.advisory(history).startswith("FIRST FAILURE: previously passing")


def test_advisory_first_run_and_no_history():
    assert memory.advisory([_run("failed", 1)]).startswith("FIRST RUN")
    assert memory.advisory([]).startswith("NO HISTORY")


def test_format_history_line():
    history = [dict(_run("failed", 1), timestamp="2026-10-09T10:00:00+00:00"),
               dict(_run("passed"), timestamp="2026-10-07T10:00:00+00:00")]
    assert memory.format_history("REQ-2.1", history) == (
        "[CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed) 2026-10-09; "
        "run_tests -> passed 2026-10-07"
    )


def test_case_history_never_reaches_llm_or_token(tmp_path, monkeypatch):
    generated = tmp_path / "generated"
    monkeypatch.setattr(sandbox, "GENERATED_DIR", generated)
    monkeypatch.setattr(sandbox, "ALLOWED_TEST_DIRS", [generated, sandbox.SUT_DIR / "tests"])
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")

    memory.record_case("REQ-2.1", "run_tests", "success", 0, test_outcome="passed", failed_count=0)
    seeded = memory.get_case_history("REQ-2.1", tool_name="run_tests")
    leak_markers = ["CASE HISTORY", "ADVISORY", "FIRST FAILURE"] + [h["timestamp"] for h in seeded]

    graph = build_offline_agent(planted_bug=True, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "history"}}
    state = graph.invoke(
        {"messages": [HumanMessage(content="Check REQ-2.1 (Tier Upgrades) against the code.")]}, config)

    # The human approver sees the history and the advisory on the approval card ...
    action = state["__interrupt__"][0].value["action_requests"][0]
    assert "[CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed)" in action["description"]
    assert "[ADVISORY] FIRST FAILURE: previously passing" in action["description"]
    # ... which carries only the tool's own arguments, never a token.
    assert action["args"] == {"draft_path": state["draft_path"]}

    # Nothing from the history is in the messages the model sees or in the workflow state.
    for message in state["messages"]:
        for marker in leak_markers:
            assert marker not in str(message.content)
    assert not any(marker in str(state[k]) for k in workflow.FIELDS for marker in leak_markers)

    # Approval mints a token bound to the tool's own arguments; the tool accepts it.
    final = graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
    assert final["stop_reason"] == "issue_filed"
    filed = [m for m in final["messages"] if isinstance(m, ToolMessage) and m.name == "file_issue"]
    assert '"status": "success"' in filed[-1].content

    # The executed call was recorded with the hop count before this step.
    latest = memory.get_case_history("REQ-2.1", limit=1)[0]
    assert (latest["tool_name"], latest["status"], latest["hops"]) == ("file_issue", "success", 4)
