"""
tests/test_followups.py

Follow-up turns (Week 8): after a finished run, a later message in the same thread can save the
tests (still needing human approval), refine them, or ask about the code. The rules stay in
workflow.py; the model only chooses among tools the phase allows.
"""

import sys
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import agent
import guard_middleware
import guardrails
import project_config
import qa_tools
import sandbox
import workflow
from harness import FixedCallsModel, tool_call
from offline import build_offline_agent

GOOD_TESTS = "```python\nfrom subscription_service.subscription_manager import SubscriptionManager\n\n\ndef test_x():\n    assert SubscriptionManager\n```"


@pytest.fixture
def redirected(tmp_path, monkeypatch):
    generated = tmp_path / "generated"
    monkeypatch.setattr(sandbox, "GENERATED_DIR", generated)
    monkeypatch.setattr(sandbox, "ALLOWED_TEST_DIRS", [generated, sandbox.SUT_DIR / "tests"])
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    return tmp_path


def passed_state(**extra):
    return {**workflow.new_workflow(), "phase": "DONE", "stop_reason": "all_tests_passed",
            "requirement_id": "REQ-2.1", "test_file": "/g/test_req_2_1_aaaaaaaa.py",
            "test_outcome": "passed", "proposals_made": 1, **extra}


# ---------------------------------------------------------------------
# Deciding whether a message continues the previous run
# ---------------------------------------------------------------------

def test_a_follow_up_continues_a_run_whose_tests_passed():
    carried = workflow.carry_over(passed_state(), "Save those tests.")
    assert carried["phase"] == workflow.TESTS_RUN_PASSED
    assert carried["test_file"] == "/g/test_req_2_1_aaaaaaaa.py" and carried["stop_reason"] is None
    assert workflow.check_call(carried, "save_test_to_suite", {"test_file": carried["test_file"]}) is None


def test_naming_a_requirement_always_starts_fresh():
    assert workflow.carry_over(passed_state(), "Check REQ-2.1 again.") is None
    assert workflow.carry_over(passed_state(), "now check req-2.2") is None


def test_only_passed_or_test_defect_runs_can_be_continued():
    assert workflow.carry_over(passed_state(stop_reason="issue_filed"), "save them") is None
    assert workflow.carry_over(passed_state(stop_reason="human_rejection", phase="STOPPED"), "save them") is None
    assert workflow.carry_over(passed_state(test_file=None), "save them") is None
    assert workflow.carry_over(workflow.new_workflow(), "save them") is None
    defect = workflow.carry_over(passed_state(stop_reason="test_defect_reported", test_outcome="failed"), "fix it")
    assert defect["phase"] == workflow.TESTS_RUN_FAILED


def test_follow_up_tools_are_pinned_to_the_previous_test_file():
    carried = workflow.carry_over(passed_state(), "add a test")
    other = "/g/test_req_2_1_bbbbbbbb.py"
    assert "may only use the test file" in workflow.check_call(carried, "save_test_to_suite", {"test_file": other})
    assert "may only use the test file" in workflow.check_call(carried, "refine_tests", {"test_file": other})
    assert workflow.check_call(carried, "refine_tests", {"test_file": carried["test_file"]}) is None
    assert workflow.check_call(carried, "propose_tests", {}) is not None  # re-checking needs a requirement id
    assert workflow.check_call(carried, "file_issue", {"draft_path": "x"}) is not None


def test_refinements_are_capped():
    carried = {**workflow.carry_over(passed_state(), "add"), "proposals_made": workflow.MAX_TEST_VERSIONS}
    assert "already written" in workflow.check_call(carried, "refine_tests", {"test_file": carried["test_file"]})


def test_read_code_is_allowed_in_every_open_phase_and_never_changes_state():
    for phase in (workflow.START, workflow.REQUIREMENT_RESOLVED, workflow.TESTS_RUN_PASSED, workflow.TESTS_RUN_FAILED):
        assert "read_code" in workflow.ALLOWED_TOOLS_BY_PHASE[phase]
    for phase in (workflow.TESTS_PROPOSED, workflow.ISSUE_DRAFTED, workflow.DONE, workflow.STOPPED):
        assert "read_code" not in workflow.ALLOWED_TOOLS_BY_PHASE[phase]
    assert workflow.apply_result(workflow.new_workflow(), "read_code", {"status": "success"}) == {}


# ---------------------------------------------------------------------
# read_code
# ---------------------------------------------------------------------

def test_read_code_lists_and_reads_the_code_under_test():
    listing = qa_tools.read_code()
    assert listing == {"status": "success", "files": ["subscription_service/subscription_manager.py"]}
    result = qa_tools.read_code("subscription_service/subscription_manager.py")
    assert result["status"] == "success" and "class SubscriptionManager" in result["content"]


@pytest.mark.parametrize("file", [
    "../docs/requirements/subscription.md",
    "../.env",
    "../../.env",
    str(PROJECT_ROOT / ".env"),
    str(PROJECT_ROOT / "src" / "approval.py"),
    "subscription_service/__pycache__/x.py",
    "subscription_service/subscription_manager.pyc",
    "missing.py",
    "x" * 300,
])
def test_read_code_refuses_anything_outside_the_code(file):
    result = qa_tools.read_code(file)
    assert result["status"] == "error" and "content" not in result


def test_read_code_truncates_large_files(tmp_path, monkeypatch):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "big.py").write_text("x = 1\n" * 20_000, encoding="utf-8")
    monkeypatch.setattr(sandbox, "SUT_DIR", tmp_path)
    result = qa_tools.read_code("pkg/big.py")
    assert result["truncated"] is True and len(result["content"]) == qa_tools.MAX_READ_CHARS


def test_secrets_in_code_are_redacted_before_the_model_sees_them(monkeypatch):
    secret = "gsk_" + "a" * 40
    call = {"name": "read_code", "args": {}, "id": "c1", "type": "tool_call"}
    from langchain_core.messages import ToolMessage

    message = ToolMessage(content='{"status": "success", "content": "KEY = \\"%s\\""}' % secret,
                          tool_call_id="c1", name="read_code")
    out = guard_middleware.post_call({"messages": [], "phase": "START", "hops": 1}, call, message)
    assert secret not in out.update["messages"][0].content


# ---------------------------------------------------------------------
# refine_tests
# ---------------------------------------------------------------------

@pytest.fixture
def base_tests(redirected, monkeypatch):
    monkeypatch.setattr(qa_tools, "get_model_response", lambda prompt, prompt_version="": GOOD_TESTS)
    return qa_tools.propose_tests("REQ-2.1")["test_file"]


def test_refine_writes_a_new_file_and_keeps_the_old_one(base_tests, monkeypatch):
    seen = {}

    def model(prompt, prompt_version=""):
        seen["prompt"] = prompt
        return GOOD_TESTS.replace("test_x", "test_negative_balance")

    monkeypatch.setattr(qa_tools, "get_model_response", model)
    result = qa_tools.refine_tests("REQ-2.1", base_tests, "add a test for a negative balance")
    assert result["status"] == "success" and result["test_file"] != base_tests
    assert result["refined_from"] == Path(base_tests).name
    assert Path(base_tests).is_file() and "test_negative_balance" in Path(result["test_file"]).read_text()
    assert "add a test for a negative balance" in seen["prompt"] and "def test_x" in seen["prompt"]
    assert "{{" not in seen["prompt"]


def test_refine_only_accepts_generated_tests_and_sane_instructions(base_tests):
    baseline = str(sandbox.SUT_DIR / "tests" / "test_subscription_manager.py")
    assert "generated" in qa_tools.refine_tests("REQ-2.1", baseline, "add one")["error"]
    assert qa_tools.refine_tests("REQ-2.1", "../../.env", "add one")["status"] == "error"
    assert "empty" in qa_tools.refine_tests("REQ-2.1", base_tests, "  ")["error"]
    assert "longer" in qa_tools.refine_tests("REQ-2.1", base_tests, "x" * 501)["error"]
    assert qa_tools.refine_tests("REQ-9.9", base_tests, "add one")["status"] == "error"
    assert guardrails.check_instruction(None)


def test_refined_code_goes_through_the_same_sandbox_policy(base_tests, monkeypatch):
    hostile = "```python\nimport subprocess\n\n\ndef test_x():\n    subprocess.run(['x'])\n```"
    monkeypatch.setattr(qa_tools, "get_model_response", lambda p, prompt_version="": hostile)
    result = qa_tools.refine_tests("REQ-2.1", base_tests, "add a test")
    assert result["status"] == "error" and "sandbox policy" in result["error"]
    monkeypatch.setattr(qa_tools, "get_model_response", lambda p, prompt_version="": "NO_GROUNDED_TESTS_FOUND: no.")
    assert qa_tools.refine_tests("REQ-2.1", base_tests, "test the moon")["status"] == "error"


# ---------------------------------------------------------------------
# End to end on the offline graph (no network, no quota)
# ---------------------------------------------------------------------

PROMPT = "Check REQ-2.1 (Tier Upgrades) against the code."


def run(graph, config, text=None, decision=None):
    payload = Command(resume={"decisions": [decision]}) if decision else {"messages": [HumanMessage(content=text)]}
    return graph.invoke(payload, config)


def tools_called(state):
    last_human = max(i for i, m in enumerate(state["messages"]) if isinstance(m, HumanMessage))
    return [m.name for m in state["messages"][last_human:] if getattr(m, "type", "") == "tool"]


@pytest.fixture
def thread(redirected):
    graph = build_offline_agent(planted_bug=False, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "follow-up"}}
    state = run(graph, config, PROMPT)
    assert (state["phase"], state["stop_reason"]) == ("DONE", "all_tests_passed")
    return graph, config, state


def test_save_those_tests_pauses_for_approval_and_saves_after_approve(thread):
    graph, config, first = thread
    state = run(graph, config, "Save those tests.")
    request = state["__interrupt__"][0].value["action_requests"][0]
    assert request["name"] == "save_test_to_suite"
    state = run(graph, config, decision={"type": "approve"})
    assert (state["phase"], state["stop_reason"]) == ("DONE", "tests_saved")
    assert tools_called(state) == ["save_test_to_suite"]
    assert not list((sandbox.SUT_DIR / "tests").glob("test_req_2_1_*.py"))  # offline: a temporary suite


def test_rejecting_the_save_saves_nothing(thread):
    graph, config, _ = thread
    run(graph, config, "Save those tests.")
    state = run(graph, config, decision={"type": "reject", "message": "No."})
    assert state["stop_reason"] == "human_rejection"


def test_refine_then_rerun_gives_a_new_test_file_and_outcome(thread):
    graph, config, first = thread
    state = run(graph, config, "Add a test for a negative balance.")
    assert tools_called(state) == ["refine_tests", "run_tests"]
    assert state["test_file"] != first["test_file"] and state["test_outcome"] == "passed"
    assert state["hops"] == 2  # the hop budget restarts for the follow-up


def test_questions_about_the_code_use_read_code_and_need_no_approval(thread):
    graph, config, _ = thread
    state = run(graph, config, "How does the code handle upgrades?")
    assert tools_called(state) == ["read_code", "read_code"]
    assert not state.get("__interrupt__")
    assert "SubscriptionManager" in state["messages"][-1].content


def test_naming_the_requirement_again_checks_it_from_scratch(thread):
    graph, config, first = thread
    state = run(graph, config, PROMPT)
    assert tools_called(state)[0] == "search_requirements"
    assert state["proposals_made"] == 1 and state["test_file"] != first["test_file"]


def test_a_follow_up_on_a_fresh_thread_cannot_save_anything(redirected):
    graph = build_offline_agent(planted_bug=False, checkpointer=InMemorySaver())
    state = run(graph, {"configurable": {"thread_id": "empty"}}, "Save those tests.")
    assert not state.get("__interrupt__") and state["stop_reason"] != "tests_saved"


def test_the_model_cannot_save_a_file_the_run_did_not_produce(redirected):
    state = {"messages": [], **workflow.carry_over(passed_state(test_file=str(redirected / "generated" / "a.py")), "save")}
    call = tool_call("save_test_to_suite", {"test_file": str(redirected / "generated" / "other.py")}).tool_calls[0]
    assert "may only use the test file" in guard_middleware.blocked_reason(state, call)


def test_follow_up_tools_are_in_the_agent_and_paths_stay_operator_set():
    assert {"read_code", "refine_tests"} <= set(agent.AGENT_CONTRACT["approved_tools"])
    assert agent.AGENT_CONTRACT["high_impact_tools"] == ["file_issue", "save_test_to_suite"]
    assert project_config.code_dir() == sandbox.SUT_DIR
