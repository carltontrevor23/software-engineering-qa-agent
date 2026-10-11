import sys
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import tool_calling
from src.tool_calling import execute_tools, route_after_tools, MAX_HOPS


def _call(name, requirement_id, call_id):
    return {"name": name, "args": {"requirement_id": requirement_id}, "id": call_id, "type": "tool_call"}


def test_iteration_cap_stops_loop():
    assert route_after_tools({"hops": MAX_HOPS}) == END
    assert route_after_tools({"hops": MAX_HOPS - 1}) == "assistant"


def test_unknown_tool_is_rejected():
    msg = AIMessage(content="", tool_calls=[_call("delete_all_users", "REQ-2.1", "c1")])
    out = execute_tools({"messages": [msg], "hops": 0})
    assert "Unknown tool" in out["messages"][0].content


def test_contract_lists_qa_tools():
    assert tool_calling.AGENT_CONTRACT["approved_tools"] == sorted([
        "search_requirements", "propose_tests", "run_tests",
        "draft_issue", "file_issue", "save_test_to_suite",
    ])
    assert tool_calling.AGENT_CONTRACT["high_impact_tools"] == ["file_issue", "save_test_to_suite"]


def test_human_rejection_blocks_file_issue(tmp_path, monkeypatch):
    qa_tools = tool_calling.qa_tools
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    draft = qa_tools.draft_issue("REQ-2.1", "t", "s", ["test_x"])["draft_path"]
    msg = AIMessage(content="", tool_calls=[
        {"name": "file_issue", "args": {"draft_path": draft}, "id": "c1", "type": "tool_call"}
    ])
    with patch("src.tool_calling.request_human_approval",
               return_value=(False, None, "Action rejected by human operator.")):
        out = execute_tools({"messages": [msg], "hops": 0})
    assert "approval_required" in out["messages"][0].content
    assert not (tmp_path / "issues" / "filed").exists()


def test_extra_tool_calls_get_error_results():
    msg = AIMessage(content="", tool_calls=[
        {"name": "search_requirements", "args": {"query": "tier upgrade"}, "id": "c1", "type": "tool_call"},
        {"name": "search_requirements", "args": {"query": "refund"}, "id": "c2", "type": "tool_call"},
    ])
    out = execute_tools({"messages": [msg], "hops": 0})
    assert len(out["messages"]) == 2
    assert "REQ-2.1" in out["messages"][0].content
    assert "skipped" in out["messages"][1].content


def test_hops_increment_once_per_step():
    msg = AIMessage(content="", tool_calls=[_call("delete_all_users", "REQ-2.1", "c1")])
    assert execute_tools({"messages": [msg], "hops": 2})["hops"] == 3