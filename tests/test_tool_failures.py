"""
tests/test_tool_failures.py

Week 4 Failure & Boundary Test Suite:
Tests missing parameters, unauthorized requests, unavailable services,
and unexpected tool responses against get_user_subscription_status and
upgrade_user_subscription.
"""

import sys
from pathlib import Path
from unittest.mock import patch
import pytest
import requests
from pydantic import ValidationError

# Ensure root directory is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.tool_calling import (
    get_user_subscription_status,
    upgrade_user_subscription,
    _FakeResponse,
)


# =====================================================================
# 1. Missing Parameters & Schema Validation Errors
# =====================================================================

def test_missing_parameter_status_lookup():
    """Verify invoking status lookup without required user_id fails schema validation."""
    with pytest.raises(ValidationError):
        get_user_subscription_status.invoke({})


def test_missing_parameter_upgrade():
    """Verify invoking upgrade without required user_id fails schema validation."""
    with pytest.raises(ValidationError):
        upgrade_user_subscription.invoke({})


def test_invalid_parameter_type():
    """Verify passing non-string argument fails validation."""
    with pytest.raises(ValidationError):
        get_user_subscription_status.invoke({"user_id": 12345})


# =====================================================================
# 2. Unavailable External Services (Network Failures & Timeouts)
# =====================================================================

@patch("requests.get")
def test_service_unavailable_timeout(mock_get):
    """
    Test handling when external user-lookup API times out.
    """
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out after 5000ms")
    with pytest.raises(requests.exceptions.Timeout):
        get_user_subscription_status.invoke({"user_id": "u123"})


@patch("requests.get")
def test_service_unavailable_500_server_error(mock_get):
    """
    Test when external user lookup returns HTTP 500 internal server error.
    Maps to UserNotFoundError in the baseline SubscriptionManager.
    """
    mock_get.return_value = _FakeResponse(500, {"error": "Internal Database Error"})
    res = get_user_subscription_status.invoke({"user_id": "u123"})
    assert res["status"] == "error"
    assert res["error"] == "User not found."


# =====================================================================
# 3. Unauthorized Requests & Non-Existent Users
# =====================================================================

@patch("requests.get")
def test_unauthorized_user_lookup_404(mock_get):
    """Test lookup of non-existent user returns structured error."""
    mock_get.return_value = _FakeResponse(404, {"error": "User does not exist"})
    res = get_user_subscription_status.invoke({"user_id": "unknown_user_999"})
    assert res["status"] == "error"
    assert res["error"] == "User not found."


@patch("requests.get")
def test_unauthorized_upgrade_404(mock_get):
    """Test upgrade attempt on non-existent or unauthorized user."""
    mock_get.return_value = _FakeResponse(404, {"error": "User does not exist"})
    res = upgrade_user_subscription.invoke({"user_id": "ghost_user_000"})
    assert res["status"] == "error"
    assert res["error"] == "User not found."


# =====================================================================
# 4. Unexpected Tool Responses & Business Invariants
# =====================================================================

@patch("requests.get")
def test_unexpected_response_inactive_user(mock_get):
    """Test that upgrade fails if user account status is not active (e.g. suspended)."""
    mock_get.return_value = _FakeResponse(
        200, {"status": "suspended", "tier": "STANDARD", "balance": 150.0}
    )
    res = upgrade_user_subscription.invoke({"user_id": "u_suspended_1"})
    assert res["status"] == "error"
    assert res["error"] == "User account is not active."


@patch("requests.get")
def test_unexpected_response_insufficient_funds(mock_get):
    """Test that upgrade fails if active user has balance below UPGRADE_COST ($50)."""
    mock_get.return_value = _FakeResponse(
        200, {"status": "active", "tier": "STANDARD", "balance": 25.50}
    )
    res = upgrade_user_subscription.invoke({"user_id": "u_poor_2"})
    assert res["status"] == "error"
    assert res["error"] == "User balance is below the required threshold."


@patch("requests.get")
def test_unexpected_response_boundary_balance(mock_get):
    """Test boundary condition: balance at $49.99 (just below $50 threshold)."""
    mock_get.return_value = _FakeResponse(
        200, {"status": "active", "tier": "STANDARD", "balance": 49.99}
    )
    res = upgrade_user_subscription.invoke({"user_id": "u_edge_3"})
    assert res["status"] == "error"
    assert res["error"] == "User balance is below the required threshold."