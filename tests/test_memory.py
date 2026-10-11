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
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import tool_calling
from src.tool_calling import assistant, execute_tools

# The modules tool_calling actually uses (imported by bare name from src/).
memory = sys.modules[tool_calling.record_case.__module__]
approval = sys.modules[tool_calling.request_human_approval.__module__]
qa_tools = tool_calling.qa_tools
workflow = tool_calling.workflow


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


def test_case_history_never_reaches_llm_or_token(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    draft = qa_tools.draft_issue(
        "REQ-2.1", "Upgrade rejected at $50.00", "AC-2 boundary fails.", ["test_exactly_50"]
    )["draft_path"]

    memory.record_case("REQ-2.1", "run_tests", "success", 0, test_outcome="passed", failed_count=0)
    memory.record_case("REQ-2.1", "run_tests", "success", 1, test_outcome="failed", failed_count=1)
    seeded = memory.get_case_history("REQ-2.1", tool_name="run_tests")
    leak_markers = ["CASE HISTORY", "ADVISORY", "FIRST FAILURE"]
    leak_markers += [h["timestamp"] for h in seeded]

    approval_args = []

    def auto_approve(tool_name, args):
        approval_args.append(dict(args))
        return approval.request_human_approval(tool_name, args, auto_decision=True)

    call = {"name": "file_issue", "args": {"draft_path": draft}, "id": "c1", "type": "tool_call"}
    msg = AIMessage(content="", tool_calls=[call])
    state = {"messages": [msg], "hops": 2, **workflow.new_workflow(),
             "phase": workflow.ISSUE_DRAFTED, "requirement_id": "REQ-2.1", "draft_path": draft}
    with patch("src.tool_calling.request_human_approval", side_effect=auto_approve):
        out = execute_tools(state)

    # The human operator did see the history and the advisory.
    printed = capsys.readouterr().out
    assert "[CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed)" in printed
    assert "[ADVISORY] FIRST FAILURE: previously passing" in printed
    assert "'status': 'success'" in out["messages"][0].content

    # Arguments bound into the approval token carry only the tool's own args.
    assert approval_args == [{"draft_path": draft}]

    # Nothing from the history appears in the tool results or the new state ...
    for tm in out["messages"]:
        for marker in leak_markers:
            assert marker not in str(tm.content)
    assert not any(marker in str(out[k]) for k in workflow.FIELDS for marker in leak_markers)

    # ... or in the messages assistant() sends to the LLM.
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content="Issue filed.")
    next_state = {**state, **out, "messages": [HumanMessage(content="Check REQ-2.1"), msg, *out["messages"]]}
    with patch.object(tool_calling, "llm_with_tools", fake_llm):
        assistant(next_state)
    sent = fake_llm.invoke.call_args.args[0]
    for m in sent:
        for marker in leak_markers:
            assert marker not in str(m.content)

    # The executed call itself was recorded with the pre-increment hop count.
    latest = memory.get_case_history("REQ-2.1", limit=1)[0]
    assert (latest["tool_name"], latest["status"], latest["hops"]) == ("file_issue", "success", 2)
