import sys
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import tool_calling
from src.tool_calling import execute_tools, route_after_tools, MAX_HOPS


def _call(name, user_id, call_id):
    return {"name": name, "args": {"user_id": user_id}, "id": call_id, "type": "tool_call"}


def test_iteration_cap_stops_loop():
    assert route_after_tools({"hops": MAX_HOPS}) == END
    assert route_after_tools({"hops": MAX_HOPS - 1}) == "assistant"


def test_unknown_tool_is_rejected():
    msg = AIMessage(content="", tool_calls=[_call("delete_all_users", "u1", "c1")])
    out = execute_tools({"messages": [msg], "hops": 0})
    assert "Unknown tool" in out["messages"][0].content


def test_human_rejection_blocks_upgrade():
    msg = AIMessage(content="", tool_calls=[_call("upgrade_user_subscription", "u1", "c1")])
    with patch("src.tool_calling.request_human_approval",
               return_value=(False, None, "Action rejected by human operator.")), \
         patch.object(tool_calling.manager, "process_upgrade") as mock_upgrade:
        out = execute_tools({"messages": [msg], "hops": 0})
    mock_upgrade.assert_not_called()
    assert "approval_required" in out["messages"][0].content


def test_extra_tool_calls_get_error_results():
    msg = AIMessage(content="", tool_calls=[
        _call("get_user_subscription_status", "u1", "c1"),
        _call("get_user_subscription_status", "u2", "c2"),
    ])
    with patch.object(tool_calling.manager, "fetch_user_data",
                      return_value={"status": "active", "tier": "STANDARD", "balance": 100.0}):
        out = execute_tools({"messages": [msg], "hops": 0})
    assert len(out["messages"]) == 2
    assert "skipped" in out["messages"][1].content


def test_hops_increment_once_per_step():
    msg = AIMessage(content="", tool_calls=[_call("delete_all_users", "u1", "c1")])
    assert execute_tools({"messages": [msg], "hops": 2})["hops"] == 3