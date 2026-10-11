"""
tests/test_mcp_server.py

The MCP server enforces the same controls as the agent: phase guard, file pinning,
server-side approval only (client tokens refused), sandboxed runs.
Offline: get_model_response returns the hand-written fixture tests.
"""

import pytest

pytest.importorskip("mcp")

import approval
import demo_support
import mcp_server
import qa_tools
import sandbox


@pytest.fixture(autouse=True)
def offline_server(tmp_path, monkeypatch):
    generated = tmp_path / "generated"
    monkeypatch.setattr(sandbox, "GENERATED_DIR", generated)
    monkeypatch.setattr(sandbox, "ALLOWED_TEST_DIRS", [generated, sandbox.SUT_DIR / "tests"])
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    monkeypatch.setattr(qa_tools, "get_model_response", demo_support.fixture_model_reply)
    approval._CONSUMED_NONCES.clear()
    mcp_server.start_check()
    yield tmp_path
    approval.set_approval_hook(None)


def _to_failed_run():
    found = mcp_server.search_requirements("tier upgrade balance")
    req = found["results"][0]["requirement_id"]
    proposed = mcp_server.propose_tests(req)
    run = mcp_server.run_tests(req, proposed["test_file"])
    return req, proposed, run


def test_phase_guard_applies_to_mcp_clients():
    res = mcp_server.file_issue("evidence/issues/drafts/x.md")
    assert res["status"] == "error"
    assert "not allowed in phase START" in res["error"]


def test_mcp_walkthrough_with_server_side_approval(offline_server):
    with demo_support.planted_bug_sut():
        req, proposed, run = _to_failed_run()
    assert (req, run["test_outcome"], run["phase"]) == ("REQ-2.1", "failed", "TESTS_RUN_FAILED")
    draft = mcp_server.draft_issue(req, "t", "s", [f["test_name"] for f in run["failures"]])
    assert draft["phase"] == "ISSUE_DRAFTED"

    forged = mcp_server.file_issue(draft["draft_path"], approval_token="forged.token")
    assert forged["status"] == "error" and "not accepted" in forged["error"]
    assert not (offline_server / "issues" / "filed").exists()

    approval.set_approval_hook(lambda tool_name, args: True)
    filed = mcp_server.file_issue(draft["draft_path"])
    assert (filed["status"], filed["phase"]) == ("success", "DONE")


def test_mcp_client_cannot_run_other_files():
    found = mcp_server.search_requirements("tier upgrade balance")
    mcp_server.propose_tests(found["results"][0]["requirement_id"])
    res = mcp_server.run_tests("REQ-2.1", str(sandbox.SUT_DIR / "tests" / "test_subscription_manager.py"))
    assert res["status"] == "error"
    assert "may only use the test file proposed in this run" in res["error"]


def test_mcp_save_test_refuses_client_token():
    res = mcp_server.save_test_to_suite("any.py", approval_token="forged.token")
    assert res["status"] == "error" and "not accepted" in res["error"]
