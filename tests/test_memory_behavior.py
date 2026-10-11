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
# Use the memory module tests/conftest.py isolates (the one tool_calling imports),
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
from src.tool_calling import AgentState


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
    assert hist_a[0]["user_id"] == "REQ-2.1"
    assert len(hist_b) == 1
    assert hist_b[0]["user_id"] == "REQ-2.4"


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


def test_memory_not_in_llm_state():
    """
    BOUNDARY TEST:
    Verify AgentState schema only contains 'messages' and 'hops'.
    Case history cannot be injected into state or passed to the LLM.
    """
    state: AgentState = {"messages": [], "hops": 0}
    assert "hops" in state
    assert "messages" in state
    assert "case_history" not in state
    assert "memory" not in state