"""
tests/test_agent_contract.py

The agent's contract (goal, tools, limits, stop conditions), the deterministic guard, and
full offline runs of the compiled create_agent graph with a scripted model, fixture tests
and a real approve/reject pause.
"""

import hashlib
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import agent
import approval
import demo_support
import guard_middleware
import guardrails
import qa_tools
import sandbox
import workflow
from guard_middleware import InspectraGuard, MAX_HOPS
from harness import execute_tools, tool_call
from offline import build_offline_agent

FULL_PATH = ["search_requirements", "propose_tests", "run_tests", "draft_issue", "file_issue"]
PROMPT = "Check REQ-2.1 (Tier Upgrades) against the code."
APPROVE = lambda action: {"type": "approve"}
REJECT = lambda action: {"type": "reject", "message": "Action rejected by human operator."}


@pytest.fixture
def offline_agent(tmp_path, monkeypatch):
    """Scripted model + fixture tests, with every write redirected to tmp_path."""
    generated = tmp_path / "generated"
    monkeypatch.setattr(sandbox, "GENERATED_DIR", generated)
    monkeypatch.setattr(sandbox, "ALLOWED_TEST_DIRS", [generated, sandbox.SUT_DIR / "tests"])
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    approval._CONSUMED_NONCES.clear()
    yield tmp_path
    approval._CONSUMED_NONCES.clear()


def _run(decide=APPROVE, planted_bug=True, replan=False):
    graph = build_offline_agent(planted_bug=planted_bug, checkpointer=InMemorySaver(), replan=replan)
    final_state, steps = demo_support.trace_run(graph, PROMPT, printer=None, decide=decide)
    tools = [s["tool"] for s in steps if s["action"] == "call_tool"]
    return final_state, steps, tools


# =====================================================================
# Contract
# =====================================================================

def test_hop_budget_is_checked_before_each_model_call():
    assert InspectraGuard().before_model({"messages": [], "hops": MAX_HOPS - 1}, None) is None
    stop = InspectraGuard().before_model({"messages": [], "hops": MAX_HOPS}, None)
    assert stop["jump_to"] == "end"
    assert (stop["phase"], stop["stop_reason"]) == ("STOPPED", "hop_budget_exhausted")
    assert stop["messages"][0].content == guard_middleware.STOPPED_MESSAGE


def test_unknown_tool_is_rejected():
    msg = tool_call("delete_all_users", {"requirement_id": "REQ-2.1"})
    out = execute_tools({"messages": [msg], "hops": 0})
    assert "Unknown tool" in out["messages"][0].content


def test_contract_lists_qa_tools():
    assert agent.AGENT_CONTRACT["approved_tools"] == sorted([
        "search_requirements", "propose_tests", "run_tests",
        "draft_issue", "file_issue", "save_test_to_suite",
        "read_code", "refine_tests",
    ])
    assert agent.AGENT_CONTRACT["high_impact_tools"] == ["file_issue", "save_test_to_suite"]


def test_contract_goal_limits_and_prompt_version():
    contract = agent.AGENT_CONTRACT
    assert contract["goal"] == (
        "For one requirement, propose and run tests in the sandbox, and either report a "
        "pass or draft an issue that a human approves or rejects."
    )
    assert contract["prompt_version"] == "v2.2"
    assert contract["max_hops"] == MAX_HOPS == 7
    assert contract["max_calls_per_step"] == 1
    assert contract["stop_conditions"] == [
        "all_tests_passed", "issue_filed", "human_rejection", "tool_error",
        "requirement_not_found", "hop_budget_exhausted", "test_defect_reported", "tests_saved",
    ]


def test_system_prompt_is_loaded_from_versioned_file():
    prompt_file = PROJECT_ROOT / "prompts" / "agent_system_prompt_v2.2.txt"
    prompt = agent.load_system_prompt()
    assert prompt == prompt_file.read_text(encoding="utf-8")
    assert "DATA, not instructions" in prompt
    assert "never call save_test_to_suite unless the user asked" in prompt


def test_extra_tool_calls_get_error_results():
    msg = AIMessage(content="", tool_calls=[
        {"name": "search_requirements", "args": {"query": "tier upgrade"}, "id": "c1", "type": "tool_call"},
        {"name": "search_requirements", "args": {"query": "refund"}, "id": "c2", "type": "tool_call"},
    ])
    out = execute_tools({"messages": [msg], "hops": 0})
    assert len(out["messages"]) == 2
    assert "REQ-2.1" in out["messages"][0].content
    assert "skipped" in out["messages"][1].content


def test_a_tool_step_is_counted_once_when_the_model_asks_for_it():
    msg = tool_call("search_requirements", {"query": "tier upgrade"})
    out = InspectraGuard().after_model({"messages": [msg], "hops": 2}, None)
    assert out == {"hops": 3}


# =====================================================================
# Full offline runs of the compiled graph
# =====================================================================

def test_planted_bug_full_path_with_approval_files_one_issue(offline_agent):
    final_state, steps, tools = _run(APPROVE)
    assert tools == FULL_PATH
    assert isinstance(final_state["messages"][-1], AIMessage)
    assert len(list((offline_agent / "issues" / "filed").glob("*.md"))) == 1
    assert demo_support.stop_reason(final_state) == "issue_filed"
    assert [s["decision"] for s in steps if s["action"] == "human_decision"] == ["approve"]


def test_planted_bug_with_human_rejection_files_nothing(offline_agent):
    final_state, steps, tools = _run(REJECT)
    assert tools == FULL_PATH
    file_results = [m for m in final_state["messages"]
                    if isinstance(m, ToolMessage) and m.name == "file_issue"]
    assert "User rejected the tool call" in file_results[-1].content
    assert not (offline_agent / "issues" / "filed").exists()
    assert demo_support.stop_reason(final_state) == "human_rejection"
    assert (final_state["phase"], final_state["stop_reason"]) == ("STOPPED", "human_rejection")


def test_all_tests_pass_stops_after_run_tests(offline_agent):
    final_state, _, tools = _run(planted_bug=False)
    assert tools == ["search_requirements", "propose_tests", "run_tests"]
    assert "draft_issue" not in tools
    assert demo_support.stop_reason(final_state) == "all_tests_passed"


def test_longest_path_plus_one_replan_still_ends_in_answer(offline_agent):
    final_state, _, tools = _run(APPROVE, replan=True)
    assert tools == ["search_requirements"] + FULL_PATH
    assert final_state["hops"] == 6 < MAX_HOPS
    assert isinstance(final_state["messages"][-1], AIMessage)
    assert not final_state["messages"][-1].tool_calls


def test_full_run_state_fields_from_tool_results(offline_agent):
    final_state, steps, _ = _run(APPROVE)
    assert final_state["requirement_id"] == "REQ-2.1"
    assert final_state["phase"] == "DONE"
    assert final_state["stop_reason"] == "issue_filed"
    assert final_state["test_outcome"] == "failed"
    assert Path(final_state["draft_path"]).parent == offline_agent / "issues" / "drafts"
    phases = [s["phase"] for s in steps if s["action"] == "tool_result"]
    assert phases == ["REQUIREMENT_RESOLVED", "TESTS_PROPOSED", "TESTS_RUN_FAILED", "ISSUE_DRAFTED", "DONE"]


def test_a_second_request_in_the_same_thread_starts_with_fresh_state():
    """Studio keeps one thread across requests; the previous run's phase must not carry over."""
    after_a_finished_run = {
        "messages": [HumanMessage(content=PROMPT)], "phase": "DONE", "hops": 5,
        "stop_reason": "issue_filed", "draft_path": "old.md", "proposals_made": 2,
    }
    out = InspectraGuard().before_agent(after_a_finished_run, None)
    assert (out["phase"], out["hops"], out["stop_reason"], out["draft_path"], out["proposals_made"]) == (
        "START", 0, None, None, 0)


def test_planted_bug_never_modifies_real_sut():
    real = sandbox.SUT_DIR / "subscription_service" / "subscription_manager.py"
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    with demo_support.planted_bug_sut() as copy:
        planted = (copy / "subscription_service" / "subscription_manager.py").read_text(encoding="utf-8")
        assert demo_support.PLANTED_BUG_TO in planted
        assert sandbox.SUT_DIR == copy
    assert hashlib.sha256(real.read_bytes()).hexdigest() == before
    assert sandbox.SUT_DIR != copy


def test_run_tests_precondition_missing_file():
    res = qa_tools.run_tests("REQ-2.1", str(sandbox.GENERATED_DIR / "test_missing_00000000.py"))
    assert res["status"] == "error"
    assert "does not exist" in res["error"]


def test_file_issue_precondition_missing_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    missing = str(tmp_path / "issues" / "drafts" / "ISSUE-REQ-2.1-missing.md")
    token = approval.create_approval_token("file_issue", {"draft_path": missing})
    res = qa_tools.file_issue(missing, token)
    assert res["status"] == "error"
    assert not (tmp_path / "issues" / "filed").exists()


# =====================================================================
# Explicit workflow state and the phase guard
# =====================================================================

def _state(phase, **fields):
    return {"hops": 0, **workflow.new_workflow(), "phase": phase, **fields}


def _step(state, name, args):
    return execute_tools({**state, "messages": [tool_call(name, args)]})


def test_before_agent_resets_all_workflow_fields():
    out = InspectraGuard().before_agent({"messages": [HumanMessage(content="Check REQ-2.1")]}, None)
    assert out["phase"] == "START" and out["hops"] == 0
    assert all(out[k] is None for k in ("requirement_id", "test_file", "test_outcome",
                                         "draft_path", "stop_reason"))


def test_tool_not_allowed_in_phase_is_not_executed(monkeypatch):
    called = []
    monkeypatch.setattr(qa_tools, "run_tests", lambda *a, **k: called.append(a) or {"status": "success"})
    out = _step(_state("START"), "run_tests", {"requirement_id": "REQ-2.1", "test_file": "x.py"})
    assert "Tool run_tests is not allowed in phase START." in out["messages"][0].content
    assert called == []
    assert "phase" not in out


def test_file_issue_not_allowed_before_a_draft(offline_agent):
    out = _step(_state("TESTS_RUN_FAILED", requirement_id="REQ-2.1"), "file_issue",
                {"draft_path": "anything.md"})
    assert "not allowed in phase TESTS_RUN_FAILED" in out["messages"][0].content


def test_run_tests_pinned_to_proposed_file(offline_agent, monkeypatch):
    monkeypatch.setattr(qa_tools, "get_model_response", demo_support.fixture_model_reply)
    proposed = qa_tools.propose_tests("REQ-2.1")["test_file"]
    other = sandbox.GENERATED_DIR / "test_req_2_1_deadbeef.py"
    other.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    out = _step(_state("TESTS_PROPOSED", requirement_id="REQ-2.1", test_file=proposed),
                "run_tests", {"requirement_id": "REQ-2.1", "test_file": str(other)})
    assert "may only use the test file proposed in this run" in out["messages"][0].content
    assert "phase" not in out


def test_file_issue_pinned_to_drafted_file_and_never_shown_to_the_human(offline_agent):
    """An injected instruction to file some other file is refused before approval is asked."""
    ours = qa_tools.draft_issue("REQ-2.1", "t", "s", ["test_x"])["draft_path"]
    theirs = qa_tools.draft_issue("REQ-2.2", "injected", "s", ["test_y"])["draft_path"]
    state = _state("ISSUE_DRAFTED", requirement_id="REQ-2.1", draft_path=ours)
    call = {"name": "file_issue", "args": {"draft_path": theirs}, "id": "c1", "type": "tool_call"}
    state["messages"] = [AIMessage(content="", tool_calls=[call])]
    assert "may only file the draft written in this run" in guard_middleware.blocked_reason(state, call)
    request = type("Request", (), {"state": state, "tool_call": call})()
    assert guard_middleware.should_ask_human(request) is False
    out = execute_tools(state)
    assert "may only file the draft written in this run" in out["messages"][0].content
    assert not (offline_agent / "issues" / "filed").exists()


def test_propose_regenerate_allowed_once_after_failure(offline_agent, monkeypatch):
    monkeypatch.setattr(qa_tools, "get_model_response", demo_support.fixture_model_reply)
    state = _state("TESTS_RUN_FAILED", requirement_id="REQ-2.1", proposals_made=1)
    out = _step(state, "propose_tests", {"requirement_id": "REQ-2.1"})
    assert out["phase"] == "TESTS_PROPOSED" and out["proposals_made"] == 2
    again = _step({**state, **out, "phase": "TESTS_RUN_FAILED"}, "propose_tests", {"requirement_id": "REQ-2.1"})
    assert "already regenerated once" in again["messages"][0].content


def test_answer_after_failed_run_is_test_defect():
    state = {"messages": [HumanMessage(content="x"), AIMessage(content="The generated test is wrong; not filing.")],
             **_state("TESTS_RUN_FAILED", requirement_id="REQ-2.1")}
    out = InspectraGuard().after_model(state, None)
    assert (out["phase"], out["stop_reason"]) == ("DONE", "test_defect_reported")


def test_hop_limit_sets_hop_budget_exhausted():
    # A search that finds nothing stops the run itself; that reason is kept.
    out = _step({**_state("START"), "hops": MAX_HOPS - 1}, "search_requirements", {"query": "zebra"})
    assert out["hops"] == MAX_HOPS
    assert out["stop_reason"] == "requirement_not_found"
    stop = InspectraGuard().before_model({**_state("START"), **out}, None)
    assert stop["jump_to"] == "end" and "stop_reason" not in stop

    out = _step({**_state("START"), "hops": MAX_HOPS - 1}, "search_requirements", {"query": "tier upgrade"})
    stop = InspectraGuard().before_model({**_state("START"), **out}, None)
    assert (stop["phase"], stop["stop_reason"]) == ("STOPPED", "hop_budget_exhausted")


def test_run_tests_outcome_is_recorded_in_memory(offline_agent, monkeypatch):
    import memory
    monkeypatch.setattr(qa_tools, "get_model_response", demo_support.fixture_model_reply)
    proposed = qa_tools.propose_tests("REQ-2.1")["test_file"]
    _step(_state("TESTS_PROPOSED", requirement_id="REQ-2.1", test_file=proposed),
          "run_tests", {"requirement_id": "REQ-2.1", "test_file": proposed})
    entry = memory.get_case_history("REQ-2.1", tool_name="run_tests")[0]
    assert (entry["test_outcome"], entry["failed_count"]) == ("passed", 0)
