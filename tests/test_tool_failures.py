"""
tests/test_tool_failures.py

Week 4 (realigned) Failure, Authorization & Boundary Test Suite for the QA tools:
missing parameters, unknown requirements, sandbox policy violations, real sandboxed
pytest runs (pass / fail / timeout / secret-free environment) and unapproved
high-impact actions (file_issue, save_test_to_suite).
No network and no real LLM: get_model_response is mocked.
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_tools import (
    draft_issue,
    file_issue,
    propose_tests,
    run_tests,
    save_test_to_suite,
    search_requirements,
)

# The module objects the tools actually use (imported by bare name from src/).
import approval
import qa_tools
import sandbox
from model_client import ModelCallError

GOOD_TESTS = '''
import pytest
from subscription_service.subscription_manager import SubscriptionManager

def test_upgrade_cost_is_50():
    # AC-2
    assert SubscriptionManager.UPGRADE_COST == 50.00

def test_ledger_dir_is_kept(tmp_path):
    # AC-2
    assert SubscriptionManager(ledger_dir=str(tmp_path)).ledger_dir == str(tmp_path)
'''


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Point every folder the tools write to at tmp_path; reset approval state."""
    sut_dir = tmp_path / "sut"
    shutil.copytree(sandbox.SUT_DIR / "subscription_service", sut_dir / "subscription_service")
    (sut_dir / "tests").mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setattr(sandbox, "SUT_DIR", sut_dir)
    monkeypatch.setattr(sandbox, "GENERATED_DIR", generated)
    monkeypatch.setattr(sandbox, "ALLOWED_TEST_DIRS", [generated, sut_dir / "tests"])
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    approval._CONSUMED_NONCES.clear()
    approval.set_approval_hook(None)
    yield tmp_path
    approval._CONSUMED_NONCES.clear()
    approval.set_approval_hook(None)


def _write_generated(name: str, code: str) -> str:
    path = sandbox.GENERATED_DIR / name
    path.write_text(code, encoding="utf-8")
    return str(path)


def _make_draft() -> str:
    res = draft_issue.invoke({
        "requirement_id": "REQ-2.1",
        "title": "Upgrade rejected at exactly $50.00",
        "summary": "AC-2 says >= $50.00 upgrades; the code rejects 50.00.",
        "failing_tests": ["test_balance_exactly_50"],
    })
    assert res["status"] == "success"
    return res["draft_path"]


# =====================================================================
# 1. Missing / invalid parameters (schema validation)
# =====================================================================

def test_missing_parameter_propose_tests():
    with pytest.raises(ValidationError):
        propose_tests.invoke({})


def test_missing_parameter_run_tests():
    with pytest.raises(ValidationError):
        run_tests.invoke({"requirement_id": "REQ-2.1"})


def test_missing_parameter_file_issue():
    with pytest.raises(ValidationError):
        file_issue.invoke({})


def test_invalid_parameter_type():
    with pytest.raises(ValidationError):
        propose_tests.invoke({"requirement_id": 12345})


# =====================================================================
# 2. Requirement lookup and search
# =====================================================================

def test_requirement_ids_are_parsed_from_section_headings():
    ids = {r["requirement_id"] for r in qa_tools.list_requirements()}
    assert {"REQ-2.1", "REQ-2.2", "REQ-2.3", "REQ-2.4", "REQ-2.5", "REQ-2.6"} <= ids
    req = qa_tools.load_requirement("REQ-2.1")
    assert req["status"] == "success"
    assert req["source_file"] == "docs/requirements/subscription.md"
    assert "greater than or equal to $50.00" in req["text"]


def test_unknown_requirement_id():
    res = propose_tests.invoke({"requirement_id": "REQ-9.9"})
    assert res == {"status": "error", "error": "Unknown requirement 'REQ-9.9'."}


def test_search_requirements_finds_tier_upgrades():
    res = search_requirements.invoke({"query": "tier upgrade balance PREMIUM"})
    assert res["status"] == "success"
    assert res["results"][0]["requirement_id"] == "REQ-2.1"


def test_search_requirements_no_hits():
    res = search_requirements.invoke({"query": "zebra spaceship lasagna"})
    assert res == {"status": "success", "results": [], "note": "NO_RELEVANT_REQUIREMENTS_FOUND"}


# =====================================================================
# 3. propose_tests and the generated-code policy
# =====================================================================

def test_propose_tests_writes_valid_code_to_sandbox():
    with patch.object(qa_tools, "get_model_response", return_value=f"Test 1: ...\n```python\n{GOOD_TESTS}```"):
        res = propose_tests.invoke({"requirement_id": "REQ-2.1"})
    assert res["status"] == "success"
    assert res["test_count"] == 2
    test_file = Path(res["test_file"])
    assert test_file.parent == sandbox.GENERATED_DIR
    assert test_file.name.startswith("test_req_2_1_")


def test_propose_tests_with_banned_import_writes_nothing():
    reply = "```python\nimport subprocess\n\ndef test_x():\n    subprocess.run('dir')\n```"
    with patch.object(qa_tools, "get_model_response", return_value=reply):
        res = propose_tests.invoke({"requirement_id": "REQ-2.1"})
    assert res["status"] == "error"
    assert "subprocess" in res["error"]
    assert list(sandbox.GENERATED_DIR.iterdir()) == []


def test_propose_tests_model_refusal_is_reported():
    reply = "NO_GROUNDED_TESTS_FOUND: excerpt does not define this behaviour."
    with patch.object(qa_tools, "get_model_response", return_value=reply):
        res = propose_tests.invoke({"requirement_id": "REQ-2.1"})
    assert res["status"] == "error"
    assert res["error"].startswith("NO_GROUNDED_TESTS_FOUND")


def test_propose_tests_model_unavailable():
    with patch.object(qa_tools, "get_model_response", side_effect=ModelCallError("429 quota")):
        res = propose_tests.invoke({"requirement_id": "REQ-2.1"})
    assert res["status"] == "error"
    assert "Model unavailable" in res["error"]


@pytest.mark.parametrize("code, banned", [
    ("x = eval('1')", "eval"),
    ("import os\nos.system('dir')", "os.system"),
    ("import os\nos.execv('a', [])", "os.execv"),
    ("import socket", "socket"),
    ("from shutil import rmtree", "shutil"),
    ("import numpy", "allow-list"),
    ("def broken(:", "does not parse"),
])
def test_validate_generated_code_rejects(code, banned):
    ok, reason = sandbox.validate_generated_code(code)
    assert not ok
    assert banned in reason


def test_validate_generated_code_accepts_allowed_imports():
    assert sandbox.validate_generated_code(GOOD_TESTS) == (True, "ok")


# =====================================================================
# 4. run_tests in the sandbox (real subprocess runs)
# =====================================================================

def test_run_tests_outside_allowed_dirs_is_refused():
    res = run_tests.invoke({"requirement_id": "REQ-2.1", "test_file": "../../src/agent_tools.py"})
    assert res["status"] == "error"
    assert "outside the sandbox" in res["error"]


def test_run_tests_missing_file_is_refused():
    missing = str(sandbox.GENERATED_DIR / "test_does_not_exist.py")
    res = run_tests.invoke({"requirement_id": "REQ-2.1", "test_file": missing})
    assert res["status"] == "error"
    assert "does not exist" in res["error"]


def test_run_tests_passing_file():
    path = _write_generated("test_pass.py", GOOD_TESTS)
    res = run_tests.invoke({"requirement_id": "REQ-2.1", "test_file": path})
    assert res["status"] == "success"
    assert res["test_outcome"] == "passed"
    assert (res["passed"], res["failed"], res["errors"]) == (2, 0, 0)


def test_run_tests_failing_file_reports_failures():
    code = "def test_ok():\n    assert True\n\ndef test_bad():\n    assert 1 == 2, 'boundary broken'\n"
    path = _write_generated("test_fail.py", code)
    res = run_tests.invoke({"requirement_id": "REQ-2.1", "test_file": path})
    assert res["status"] == "success"
    assert res["test_outcome"] == "failed"
    assert (res["passed"], res["failed"]) == (1, 1)
    assert res["failures"][0]["test_name"].endswith("test_bad")
    assert "boundary broken" in res["failures"][0]["message"]


def test_run_tests_timeout(monkeypatch):
    monkeypatch.setattr(sandbox, "TEST_TIMEOUT_SECONDS", 2)
    path = _write_generated("test_hang.py", "def test_hang():\n    while True:\n        pass\n")
    res = run_tests.invoke({"requirement_id": "REQ-2.1", "test_file": path})
    assert res["status"] == "error"
    assert "timeout" in res["error"]


def test_run_tests_environment_has_no_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-leak")
    code = (
        "import os\n\n"
        "def test_no_secrets():\n"
        "    assert 'GEMINI_API_KEY' not in os.environ\n"
        "    assert 'GITHUB_TOKEN' not in os.environ\n"
    )
    path = _write_generated("test_env.py", code)
    res = run_tests.invoke({"requirement_id": "REQ-2.1", "test_file": path})
    assert res["test_outcome"] == "passed", res


def test_run_tests_rechecks_generated_code():
    path = _write_generated("test_sneaky.py", "import subprocess\n\ndef test_x():\n    pass\n")
    res = run_tests.invoke({"requirement_id": "REQ-2.1", "test_file": path})
    assert res["status"] == "error"
    assert "sandbox policy" in res["error"]


# =====================================================================
# 5. Issue drafts and unapproved high-impact actions
# =====================================================================

def test_draft_issue_is_local_and_marked_not_filed():
    draft = Path(_make_draft())
    assert draft.parent == qa_tools.ISSUES_DIR / "drafts"
    text = draft.read_text(encoding="utf-8")
    assert "> 2. If the user's current account balance is greater than or equal to $50.00" in text
    assert "Drafted by Inspectra QA agent - not filed" in text


def test_file_issue_without_token_is_blocked():
    draft = _make_draft()
    res = file_issue.invoke({"draft_path": draft})
    assert res["status"] == "approval_required"
    assert "Approval token missing" in res["error"]
    assert not (qa_tools.ISSUES_DIR / "filed").exists()


def test_file_issue_with_tampered_token_is_blocked():
    draft = _make_draft()
    token = approval.create_approval_token("file_issue", {"draft_path": draft})
    res = file_issue.invoke({"draft_path": draft, "approval_token": token[:-4] + "ffff"})
    assert res["status"] == "approval_required"
    assert "signature is invalid" in res["error"]
    assert not (qa_tools.ISSUES_DIR / "filed").exists()


def test_file_issue_with_valid_token_files_locally():
    draft = _make_draft()
    token = approval.create_approval_token("file_issue", {"draft_path": draft})
    res = file_issue.invoke({"draft_path": draft, "approval_token": token})
    assert res["status"] == "success"
    assert res["channel"] == "local"
    assert Path(res["filed_path"]).read_text(encoding="utf-8") == Path(draft).read_text(encoding="utf-8")


def test_file_issue_outside_drafts_is_refused(tmp_path):
    outside = tmp_path / "not_a_draft.md"
    outside.write_text("x", encoding="utf-8")
    token = approval.create_approval_token("file_issue", {"draft_path": str(outside)})
    res = file_issue.invoke({"draft_path": str(outside), "approval_token": token})
    assert res["status"] == "error"


def test_save_test_to_suite_without_token_is_blocked():
    path = _write_generated("test_req_2_1_abcdef12.py", GOOD_TESTS)
    res = save_test_to_suite.invoke({"test_file": path})
    assert res["status"] == "approval_required"
    assert list((sandbox.SUT_DIR / "tests").iterdir()) == []


def test_save_test_to_suite_outside_generated_is_refused():
    target = str(PROJECT_ROOT / "src" / "agent_tools.py")
    token = approval.create_approval_token("save_test_to_suite", {"test_file": target})
    res = save_test_to_suite.invoke({"test_file": target, "approval_token": token})
    assert res["status"] == "error"
    assert list((sandbox.SUT_DIR / "tests").iterdir()) == []


def test_save_test_to_suite_with_valid_token_copies_test():
    path = _write_generated("test_req_2_1_abcdef12.py", GOOD_TESTS)
    token = approval.create_approval_token("save_test_to_suite", {"test_file": path})
    res = save_test_to_suite.invoke({"test_file": path, "approval_token": token})
    assert res["status"] == "success"
    assert Path(res["saved_path"]).parent == sandbox.SUT_DIR / "tests"


def test_case_history_key_comes_from_requirement_or_file_name():
    assert qa_tools.requirement_id_from_args({"requirement_id": "REQ-2.4"}) == "REQ-2.4"
    assert qa_tools.requirement_id_from_args(
        {"draft_path": "evidence/issues/drafts/ISSUE-REQ-2.1-20261011T120000Z.md"}) == "REQ-2.1"
    assert qa_tools.requirement_id_from_args(
        {"test_file": "sandbox/generated/test_req_2_1_abcdef12.py"}) == "REQ-2.1"
    assert qa_tools.requirement_id_from_args({"query": "refunds"}) == "unknown"


# =====================================================================
# 6. GitHub Issues integration (file_issue, Week 6 realignment)
# =====================================================================

import requests
from unittest.mock import MagicMock

FAKE_TOKEN = "ghp_FAKE_TOKEN_must_never_leak_0123456789"


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("GITHUB_REPO", "demo-owner/inspectra-demo")


def _approved_file(draft):
    token = approval.create_approval_token("file_issue", {"draft_path": draft})
    return file_issue.invoke({"draft_path": draft, "approval_token": token})


def _response(status_code, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    return resp


def test_file_issue_posts_to_github(github_env):
    draft = _make_draft()
    with patch.object(qa_tools.requests, "post", return_value=_response(
            201, {"html_url": "https://github.com/demo-owner/inspectra-demo/issues/7"})) as post:
        res = _approved_file(draft)
    assert res == {"status": "success", "channel": "github",
                   "issue_url": "https://github.com/demo-owner/inspectra-demo/issues/7"}
    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == "https://api.github.com/repos/demo-owner/inspectra-demo/issues"
    assert kwargs["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert kwargs["timeout"] == 15
    assert kwargs["json"]["title"] == "Upgrade rejected at exactly $50.00"
    assert kwargs["json"]["labels"] == ["inspectra-qa"]
    assert kwargs["json"]["body"] == Path(draft).read_text(encoding="utf-8")
    assert FAKE_TOKEN not in str(res)
    # GitHub is the filing channel: no local copy is made.
    assert not (qa_tools.ISSUES_DIR / "filed").exists()


def test_file_issue_github_401_keeps_draft(github_env):
    draft = _make_draft()
    with patch.object(qa_tools.requests, "post", return_value=_response(401, {"message": "Bad credentials"})):
        res = _approved_file(draft)
    assert res["status"] == "error"
    assert "HTTP 401" in res["error"]
    assert FAKE_TOKEN not in str(res)
    assert Path(draft).exists()
    assert not (qa_tools.ISSUES_DIR / "filed").exists()


def test_file_issue_github_timeout_keeps_draft(github_env):
    draft = _make_draft()
    with patch.object(qa_tools.requests, "post", side_effect=requests.exceptions.Timeout("read timed out")):
        res = _approved_file(draft)
    assert res["status"] == "error"
    assert "Timeout" in res["error"]
    assert Path(draft).exists()
    assert not (qa_tools.ISSUES_DIR / "filed").exists()


def test_file_issue_without_github_env_files_locally(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    draft = _make_draft()
    with patch.object(qa_tools.requests, "post") as post:
        res = _approved_file(draft)
    post.assert_not_called()
    assert res["status"] == "success" and res["channel"] == "local"


def test_github_token_never_in_tool_message_or_memory(github_env):
    import memory
    import workflow
    from harness import execute_tools, tool_call

    draft = _make_draft()
    msg = tool_call("file_issue", {"draft_path": draft})
    state = {"messages": [msg], "hops": 0, **workflow.new_workflow(),
             "phase": "ISSUE_DRAFTED", "requirement_id": "REQ-2.1", "draft_path": draft}
    for code in (201, 401):
        with patch.object(qa_tools.requests, "post", return_value=_response(code, {"html_url": "https://x/1"})):
            out = execute_tools(state)
        assert FAKE_TOKEN not in out["messages"][0].content
    assert FAKE_TOKEN not in Path(memory.MEMORY_FILE).read_text(encoding="utf-8")
