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
    memory.record_case("u1", "get_user_subscription_status", "success", 0)
    memory.record_case("u2", "get_user_subscription_status", "error", 0)
    memory.record_case("u1", "upgrade_user_subscription", "approval_required", 1)
    memory.record_case("u1", "upgrade_user_subscription", "success", 2)

    history = memory.get_case_history("u1", limit=2)
    assert [(h["tool_name"], h["status"], h["hops"]) for h in history] == [
        ("upgrade_user_subscription", "success", 2),
        ("upgrade_user_subscription", "approval_required", 1),
    ]
    assert all(h["user_id"] == "u1" for h in history)
    assert all(h["timestamp"].endswith("+00:00") for h in history)

    assert len(memory.get_case_history("u1", limit=3)) == 3
    assert [h["status"] for h in memory.get_case_history("u2")] == ["error"]


def test_get_case_history_empty_when_no_file():
    assert not Path(memory.MEMORY_FILE).exists()
    assert memory.get_case_history("u1") == []


def test_case_history_never_reaches_llm_or_token(capsys):
    memory.record_case("u1", "get_user_subscription_status", "success", 0)
    memory.record_case("u1", "upgrade_user_subscription", "approval_required", 1)
    seeded = memory.get_case_history("u1", limit=3)
    leak_markers = ["CASE HISTORY"]
    for h in seeded:
        leak_markers += [h["timestamp"], f"{h['tool_name']} -> {h['status']}"]

    approval_args = []

    def auto_approve(tool_name, args):
        approval_args.append(dict(args))
        return approval.request_human_approval(tool_name, args, auto_decision=True)

    call = {"name": "upgrade_user_subscription", "args": {"user_id": "u1"},
            "id": "c1", "type": "tool_call"}
    msg = AIMessage(content="", tool_calls=[call])
    with patch("src.tool_calling.request_human_approval", side_effect=auto_approve), \
         patch.object(tool_calling.manager, "process_upgrade",
                      return_value={"status": "active", "tier": "PREMIUM", "balance": 50.0}):
        out = execute_tools({"messages": [msg], "hops": 2})

    # The human operator did see the history.
    assert "[CASE HISTORY] last 2 action(s) for u1" in capsys.readouterr().out
    assert "'status': 'success'" in out["messages"][0].content

    # Arguments bound into the approval token carry only the tool's own args.
    assert approval_args == [{"user_id": "u1"}]

    # Nothing from the history appears in the tool results ...
    for tm in out["messages"]:
        for marker in leak_markers:
            assert marker not in str(tm.content)

    # ... or in the messages assistant() sends to the LLM.
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content="Upgraded.")
    state = {"messages": [HumanMessage(content="Upgrade u1"), msg, *out["messages"]], "hops": 3}
    with patch.object(tool_calling, "llm_with_tools", fake_llm):
        assistant(state)
    sent = fake_llm.invoke.call_args.args[0]
    for m in sent:
        for marker in leak_markers:
            assert marker not in str(m.content)

    # The executed call itself was recorded with the pre-increment hop count.
    latest = memory.get_case_history("u1", limit=1)[0]
    assert (latest["tool_name"], latest["status"], latest["hops"]) == (
        "upgrade_user_subscription", "success", 2)
