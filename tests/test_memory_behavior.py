"""
tests/test_memory_behavior.py

Week 6, Activity 4: Memory Behavior & Safety Verification Suite.
Validates:
  1. Legitimate Utility: Past case history accurately logs and surfaces
     historical attempts for human operator inspection.
  2. Non-Silent Control: Past memory of an approval does NOT silently
     authorize future runs or bypass the human-in-the-loop gate.
  3. LLM Isolation: Memory history is completely isolated from LLM context
     and HMAC token signatures.
"""

import os
import json
import pytest
# Use the memory module tests/conftest.py isolates (the one the agent imports),
# so these tests never touch the real data/memory file.
import memory
from memory import record_case, get_case_history
from src.approval import (
    is_high_impact,
    request_human_approval,
    verify_and_consume_token,
    create_approval_token,
    set_approval_hook,
    _CONSUMED_NONCES,
)
import agent_tools
import qa_tools
import workflow
from agent_state import InspectraState


@pytest.fixture(autouse=True)
def clean_memory_and_tokens():
    """Ensure clean memory file and nonces between test runs."""
    _CONSUMED_NONCES.clear()
    set_approval_hook(None)
    if os.path.exists(memory.MEMORY_FILE):
        os.remove(memory.MEMORY_FILE)
    yield
    _CONSUMED_NONCES.clear()
    set_approval_hook(None)
    if os.path.exists(memory.MEMORY_FILE):
        os.remove(memory.MEMORY_FILE)


# =====================================================================
# 1. Legitimate Task Improvement (Surfacing Case History)
# =====================================================================

def test_memory_surfaces_legitimate_audit_history():
    """Verify memory accurately captures and orders historical activity."""
    req = "REQ-2.1"
    record_case(req, "search_requirements", "success", hops=1)
    record_case(req, "run_tests", "success", hops=2)
    record_case(req, "file_issue", "success", hops=3)

    history = get_case_history(req, limit=3)
    assert len(history) == 3
    # Most recent first
    assert history[0]["status"] == "success"
    assert history[0]["hops"] == 3
    assert history[1]["tool_name"] == "run_tests"
    assert history[2]["tool_name"] == "search_requirements"


def test_memory_tenant_isolation():
    """Verify history for one requirement is never mixed into another's."""
    record_case("REQ-2.1", "file_issue", "success", hops=1)
    record_case("REQ-2.4", "search_requirements", "success", hops=1)

    hist_a = get_case_history("REQ-2.1")
    hist_b = get_case_history("REQ-2.4")

    assert len(hist_a) == 1
    assert hist_a[0]["requirement_id"] == "REQ-2.1"
    assert len(hist_b) == 1
    assert hist_b[0]["requirement_id"] == "REQ-2.4"


# =====================================================================
# 2. Non-Silent Control (Safety & Gating Guarantees)
# =====================================================================

def test_memory_never_silently_bypasses_human_approval():
    """
    SAFETY TEST:
    Even if persistent memory contains prior filed issues for this requirement,
    a new file_issue action must still be intercepted by the human gate.
    """
    # Pre-seed persistent memory with a successful prior filing
    record_case("REQ-2.1", "file_issue", "success", hops=2)

    tool_name = "file_issue"
    args = {"draft_path": "evidence/issues/drafts/ISSUE-REQ-2.1-20261011T120000Z.md"}

    # Verify policy still flags it as high impact regardless of memory
    assert is_high_impact(tool_name) is True

    # Simulate operator refusing the action
    approved, token, message = request_human_approval(tool_name, args, auto_decision=False)
    assert approved is False
    assert token is None
    assert "rejected" in message

    # Attempting to execute without human approval fails
    is_valid, err_msg = verify_and_consume_token(token, tool_name, args)
    assert is_valid is False
    assert "Approval token missing" in err_msg


def test_history_full_of_approvals_cannot_bypass_file_issue_gate(tmp_path, monkeypatch):
    """
    SAFETY TEST:
    However many earlier filings and passing runs memory holds, file_issue without
    a fresh human-approved token is still refused and files nothing.
    """
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    draft = qa_tools.draft_issue("REQ-2.1", "t", "s", ["test_x"])["draft_path"]
    for hops in range(10):
        record_case("REQ-2.1", "file_issue", "success", hops=hops)
        record_case("REQ-2.1", "run_tests", "success", hops=hops, test_outcome="passed", failed_count=0)

    res = agent_tools.file_issue.invoke({"draft_path": draft})
    assert res["status"] == "approval_required"
    assert not (tmp_path / "issues" / "filed").exists()


def test_memory_not_in_llm_state():
    """
    BOUNDARY TEST:
    InspectraState holds messages, hops and the workflow fields only (plus the framework's
    own jump_to / structured_response). There is no field through which case history could
    be injected into state or the LLM.
    """
    fields = set(InspectraState.__annotations__)
    assert {"messages", "hops", *workflow.FIELDS} <= fields
    assert fields - {"messages", "hops", *workflow.FIELDS} <= {"jump_to", "structured_response"}
    assert not {"case_history", "memory", "history"} & fields
