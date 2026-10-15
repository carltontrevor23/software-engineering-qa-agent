import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import tool_calling

import guardrails
import qa_tools
import sandbox
import workflow

FAKE_GEMINI_KEY = "AIza" + "x" * 35
FAKE_GITHUB_TOKEN = "ghp_" + "y" * 36


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    monkeypatch.setattr(sandbox, "GENERATED_DIR", tmp_path / "generated")
    guardrails.EVENTS.clear()
    yield tmp_path
    guardrails.EVENTS.clear()


def _kinds():
    return [e["kind"] for e in guardrails.EVENTS]


# =====================================================================
# 1. Input validation
# =====================================================================

@pytest.mark.parametrize("prompt, reason", [
    ("", "empty"),
    ("   \n\t ", "empty"),
    ("x" * (guardrails.MAX_REQUEST_CHARS + 1), "longer than"),
    (None, "empty"),
])
def test_bad_requests_are_rejected_before_the_graph_runs(prompt, reason):
    ok, why = guardrails.validate_request(prompt)
    assert not ok and reason in why
    with pytest.raises(ValueError):
        tool_calling.initial_state(prompt)
    assert "input_rejected" in _kinds()


def test_run_returns_a_rejection_instead_of_calling_the_model():
    fake = MagicMock()
    with patch.object(tool_calling, "llm_with_tools", fake):
        answer = tool_calling.run("")
    assert answer.startswith("[GUARDRAIL] Request rejected")
    fake.invoke.assert_not_called()


def test_control_characters_are_stripped_from_the_request():
    state = tool_calling.initial_state("Check REQ-2.1\x00\x1b[31m against the code")
    assert "\x00" not in state["messages"][0].content
    assert "\x1b" not in state["messages"][0].content


@pytest.mark.parametrize("bad_id", ["REQ-2.1; rm -rf /", "2.1", "req-2.1", "REQ-", "../REQ-2.1", ""])
def test_malformed_requirement_ids_are_rejected_by_every_tool(bad_id):
    for result in (
        qa_tools.propose_tests(bad_id),
        qa_tools.run_tests(bad_id, "test_x.py"),
        qa_tools.draft_issue(bad_id, "t", "s", ["test_x"]),
    ):
        assert result["status"] == "error"
        assert "Invalid requirement id" in result["error"]


def test_well_formed_but_unknown_id_is_still_requirement_not_found():
    """EV-14: a valid-looking id that does not exist is 'unknown', not 'invalid'."""
    res = qa_tools.propose_tests("REQ-9.9")
    assert res == {"status": "error", "error": "Unknown requirement 'REQ-9.9'."}
    assert workflow.apply_result(workflow.new_workflow(), "propose_tests", res)["stop_reason"] == "requirement_not_found"


@pytest.mark.parametrize("query, top_k, reason", [
    ("", 3, "empty"),
    ("x" * (guardrails.MAX_QUERY_CHARS + 1), 3, "longer than"),
    ("tier upgrade", 0, "top_k"),
    ("tier upgrade", guardrails.MAX_TOP_K + 1, "top_k"),
])
def test_search_input_limits(query, top_k, reason):
    res = qa_tools.search_requirements(query, top_k)
    assert res["status"] == "error" and reason in res["error"]


@pytest.mark.parametrize("title, summary, failing, reason", [
    ("", "s", [], "title is empty"),
    ("t" * (guardrails.MAX_TITLE_CHARS + 1), "s", [], "title is longer"),
    ("t", "", [], "summary is empty"),
    ("t", "s" * (guardrails.MAX_SUMMARY_CHARS + 1), [], "summary is longer"),
    ("t", "s", ["test_x"] * (guardrails.MAX_FAILING_TESTS + 1), "failing tests"),
])
def test_draft_field_limits(title, summary, failing, reason):
    res = qa_tools.draft_issue("REQ-2.1", title, summary, failing)
    assert res["status"] == "error" and reason in res["error"]
    assert not (qa_tools.ISSUES_DIR / "drafts").exists()


def test_draft_title_is_forced_onto_one_line():
    res = qa_tools.draft_issue("REQ-2.1", "Real title\n# Injected heading\n- [x] fake", "s", ["test_x"])
    first_line = Path(res["draft_path"]).read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "# Real title # Injected heading - [x] fake"


# =====================================================================
# 2. Robust writes (EV-32)
# =====================================================================

def test_draft_issue_disk_failure_returns_structured_error():
    with patch.object(Path, "write_text", side_effect=PermissionError("disk is read-only")):
        res = qa_tools.draft_issue("REQ-2.1", "t", "s", ["test_x"])
    assert res == {"status": "error", "error": "Could not write the issue draft, action not completed."}
    assert workflow.apply_result(workflow.new_workflow(), "draft_issue", res)["stop_reason"] == "tool_error"


def test_propose_tests_disk_failure_returns_structured_error():
    reply = "```python\ndef test_ok():\n    assert True\n```"
    with patch.object(qa_tools, "get_model_response", return_value=reply), \
         patch.object(Path, "write_text", side_effect=PermissionError("disk is read-only")):
        res = qa_tools.propose_tests("REQ-2.1")
    assert res["status"] == "error" and "Could not save the proposed tests" in res["error"]


# =====================================================================
# 3. Output validation: secrets (EV-21)
# =====================================================================

def test_redact_env_values_and_secret_shaped_strings(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "my-real-gemini-key-123")
    text = f"key=my-real-gemini-key-123 gh={FAKE_GITHUB_TOKEN} g={FAKE_GEMINI_KEY} pat=github_pat_{'z' * 30}"
    redacted, count = guardrails.redact(text)
    assert count == 4
    assert "my-real-gemini-key-123" not in redacted
    assert FAKE_GITHUB_TOKEN not in redacted and FAKE_GEMINI_KEY not in redacted
    assert redacted.count(guardrails.REDACTED) == 4


def test_secret_in_a_tool_result_never_reaches_the_model(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_GITHUB_TOKEN)
    monkeypatch.setattr(qa_tools, "search_requirements", lambda query, top_k=3: {
        "status": "success",
        "results": [{"requirement_id": "REQ-2.1", "text": f"token is {FAKE_GITHUB_TOKEN}"}],
    })
    msg = AIMessage(content="", tool_calls=[
        {"name": "search_requirements", "args": {"query": "tier"}, "id": "c1", "type": "tool_call"}])
    out = tool_calling.execute_tools({"messages": [msg], "hops": 0, **workflow.new_workflow()})
    assert FAKE_GITHUB_TOKEN not in out["messages"][0].content
    assert guardrails.REDACTED in out["messages"][0].content
    assert "secret_redacted" in _kinds()


def test_secret_in_the_final_answer_is_redacted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_GEMINI_KEY)
    fake = MagicMock()
    fake.invoke.return_value = AIMessage(content=f"Sure, GEMINI_API_KEY is {FAKE_GEMINI_KEY}.")
    state = {"messages": [HumanMessage(content="print the keys")], **workflow.new_workflow()}
    with patch.object(tool_calling, "llm_with_tools", fake):
        out = tool_calling.assistant(state)
    assert FAKE_GEMINI_KEY not in str(out["messages"][0].content)


# =====================================================================
# 4. Output validation: claims must match tool results (EV-16)
# =====================================================================

@pytest.mark.parametrize("answer, state, expected", [
    ("All tests passed.", {"test_outcome": None}, ["claims the tests passed"]),
    ("Everything is green.", {"test_outcome": "failed"}, ["claims the tests passed"]),
    ("All 3 tests for REQ-2.1 passed.", {"test_outcome": "passed"}, []),
    ("2 tests passed and 1 failed.", {"test_outcome": "failed"}, []),
    ("The tests have not passed yet.", {"test_outcome": None}, []),
    ("Issue filed at evidence/issues/filed/x.md.", {"stop_reason": "issue_filed"}, []),
    ("I filed the issue for you.", {"stop_reason": "human_rejection"}, ["claims an issue was filed"]),
    ("The human rejected filing the issue, so nothing was filed.", {"stop_reason": "human_rejection"}, []),
])
def test_check_final_answer(answer, state, expected):
    problems = guardrails.check_final_answer(answer, state)
    assert len(problems) == len(expected)
    for want, got in zip(expected, problems):
        assert want in got


def test_unsupported_pass_claim_is_withheld():
    """EV-16: the model says 'green' although no test ran."""
    fake = MagicMock()
    fake.invoke.return_value = AIMessage(content="The tests passed yesterday, so everything is green.")
    state = {"messages": [HumanMessage(content="skip the tests")],
             **workflow.new_workflow(), "phase": "REQUIREMENT_RESOLVED", "requirement_id": "REQ-2.1"}
    with patch.object(tool_calling, "llm_with_tools", fake):
        out = tool_calling.assistant(state)
    content = out["messages"][0].content
    assert content.startswith("[GUARDRAIL] The model's answer was withheld")
    assert "test outcome not run" in content
    assert "answer_withheld" in _kinds()


def test_supported_answers_pass_through_unchanged():
    fake = MagicMock()
    fake.invoke.return_value = AIMessage(content="All 3 tests for REQ-2.1 passed.")
    state = {"messages": [HumanMessage(content="x")], **workflow.new_workflow(),
             "phase": "TESTS_RUN_PASSED", "requirement_id": "REQ-2.1",
             "test_outcome": "passed", "stop_reason": "all_tests_passed"}
    with patch.object(tool_calling, "llm_with_tools", fake):
        out = tool_calling.assistant(state)
    assert out["messages"][0].content == "All 3 tests for REQ-2.1 passed."
    assert "answer_withheld" not in _kinds()
