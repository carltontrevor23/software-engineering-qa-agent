"""
tests/test_memory.py

Week 6 persistent case-history memory: round-trip storage, empty-start behaviour,
and a guard that the history shown to the human approver never leaks to the LLM.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import tool_calling
from src.tool_calling import assistant, execute_tools

# The memory module tool_calling actually uses (imported by bare name from src/).
memory = sys.modules[tool_calling.record_case.__module__]
approval = sys.modules[tool_calling.request_human_approval.__module__]


def test_record_and_retrieve_round_trip():
    memory.record_case("REQ-2.1", "search_requirements", "success", 0)
    memory.record_case("REQ-2.4", "run_tests", "error", 0)
    memory.record_case("REQ-2.1", "run_tests", "success", 1)
    memory.record_case("REQ-2.1", "file_issue", "approval_required", 2)

    history = memory.get_case_history("REQ-2.1", limit=2)
    assert [(h["tool_name"], h["status"], h["hops"]) for h in history] == [
        ("file_issue", "approval_required", 2),
        ("run_tests", "success", 1),
    ]
    # Field is still named user_id until the Week 6 realignment renames it.
    assert all(h["user_id"] == "REQ-2.1" for h in history)
    assert all(h["timestamp"].endswith("+00:00") for h in history)

    assert len(memory.get_case_history("REQ-2.1", limit=3)) == 3
    assert [h["status"] for h in memory.get_case_history("REQ-2.4")] == ["error"]


def test_get_case_history_empty_when_no_file():
    assert not Path(memory.MEMORY_FILE).exists()
    assert memory.get_case_history("REQ-2.1") == []


def test_case_history_never_reaches_llm_or_token(capsys, tmp_path, monkeypatch):
    qa_tools = sys.modules[tool_calling.qa_tools.__name__]
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    draft = qa_tools.draft_issue(
        "REQ-2.1", "Upgrade rejected at $50.00", "AC-2 boundary fails.", ["test_exactly_50"]
    )["draft_path"]

    memory.record_case("REQ-2.1", "run_tests", "success", 0)
    memory.record_case("REQ-2.1", "file_issue", "approval_required", 1)
    seeded = memory.get_case_history("REQ-2.1", limit=3)
    leak_markers = ["CASE HISTORY"]
    for h in seeded:
        leak_markers += [h["timestamp"], f"{h['tool_name']} -> {h['status']}"]

    approval_args = []

    def auto_approve(tool_name, args):
        approval_args.append(dict(args))
        return approval.request_human_approval(tool_name, args, auto_decision=True)

    call = {"name": "file_issue", "args": {"draft_path": draft},
            "id": "c1", "type": "tool_call"}
    msg = AIMessage(content="", tool_calls=[call])
    with patch("src.tool_calling.request_human_approval", side_effect=auto_approve):
        out = execute_tools({"messages": [msg], "hops": 2})

    # The human operator did see the history.
    assert "[CASE HISTORY] last 2 action(s) for REQ-2.1" in capsys.readouterr().out
    assert "'status': 'success'" in out["messages"][0].content

    # Arguments bound into the approval token carry only the tool's own args.
    assert approval_args == [{"draft_path": draft}]

    # Nothing from the history appears in the tool results ...
    for tm in out["messages"]:
        for marker in leak_markers:
            assert marker not in str(tm.content)

    # ... or in the messages assistant() sends to the LLM.
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content="Issue filed.")
    state = {"messages": [HumanMessage(content="Check REQ-2.1"), msg, *out["messages"]], "hops": 3}
    with patch.object(tool_calling, "llm_with_tools", fake_llm):
        assistant(state)
    sent = fake_llm.invoke.call_args.args[0]
    for m in sent:
        for marker in leak_markers:
            assert marker not in str(m.content)

    # The executed call itself was recorded with the pre-increment hop count.
    latest = memory.get_case_history("REQ-2.1", limit=1)[0]
    assert (latest["tool_name"], latest["status"], latest["hops"]) == (
        "file_issue", "success", 2)


def test_delete_user_case_history():
    memory.record_case("u1", "tool_a", "success", 0)
    memory.record_case("u2", "tool_b", "success", 0)
    memory.record_case("u1", "tool_c", "error", 1)

    assert len(memory.get_case_history("u1", limit=5)) == 2
    assert len(memory.get_case_history("u2", limit=5)) == 1

    deleted = memory.delete_user_case_history("u1")
    assert deleted == 2

    assert memory.get_case_history("u1") == []
    assert len(memory.get_case_history("u2")) == 1
    assert memory.get_case_history("u2")[0]["tool_name"] == "tool_b"


def test_purge_expired_records(monkeypatch):
    import json
    from datetime import datetime, timezone, timedelta

    old_time = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    fresh_time = datetime.now(timezone.utc).isoformat()

    old_entry = {
        "timestamp": old_time,
        "user_id": "u_old",
        "tool_name": "tool_old",
        "status": "success",
        "hops": 0,
    }
    fresh_entry = {
        "timestamp": fresh_time,
        "user_id": "u_fresh",
        "tool_name": "tool_fresh",
        "status": "success",
        "hops": 0,
    }

    import os
    os.makedirs(memory.MEMORY_DIR, exist_ok=True)
    with open(memory.MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(old_entry) + "\n")
        f.write(json.dumps(fresh_entry) + "\n")

    purged = memory.purge_expired_records(retention_days=30)
    assert purged == 1

    remaining_old = memory.get_case_history("u_old")
    remaining_fresh = memory.get_case_history("u_fresh")

    assert remaining_old == []
    assert len(remaining_fresh) == 1
    assert remaining_fresh[0]["user_id"] == "u_fresh"
