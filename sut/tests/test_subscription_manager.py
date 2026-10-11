"""
sut/tests/test_subscription_manager.py

Human-written baseline suite for REQ-2.1 (docs/requirements/subscription.md).
The QA agent's generated tests are compared against this suite.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from subscription_service.subscription_manager import (
    AlreadyPremiumError,
    InactiveUserError,
    InsufficientFundsError,
    SubscriptionManager,
    UserNotFoundError,
)

GET = "subscription_service.subscription_manager.requests.get"


def _response(status_code, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    return resp


def _user(balance, status="active", tier="STANDARD"):
    return _response(200, {"status": status, "tier": tier, "balance": balance})


def test_normal_upgrade_deducts_cost_and_writes_ledger(tmp_path):
    with patch(GET, return_value=_user(100.0)):
        result = SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")
    assert result["tier"] == "PREMIUM"
    assert result["balance"] == 50.0
    ledger = json.loads((tmp_path / "u1.json").read_text(encoding="utf-8"))
    assert ledger["tier"] == "PREMIUM" and ledger["balance"] == 50.0


def test_balance_exactly_50_succeeds(tmp_path):
    with patch(GET, return_value=_user(50.00)):
        result = SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")
    assert result["tier"] == "PREMIUM"
    assert result["balance"] == 0.0


def test_balance_49_99_raises_and_leaves_ledger_untouched(tmp_path):
    with patch(GET, return_value=_user(49.99)):
        with pytest.raises(InsufficientFundsError):
            SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")
    assert not (tmp_path / "u1.json").exists()


def test_inactive_user_raises(tmp_path):
    with patch(GET, return_value=_user(100.0, status="suspended")):
        with pytest.raises(InactiveUserError):
            SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")


def test_already_premium_raises(tmp_path):
    with patch(GET, return_value=_user(100.0, tier="PREMIUM")):
        with pytest.raises(AlreadyPremiumError):
            SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")


def test_non_200_http_raises_user_not_found(tmp_path):
    with patch(GET, return_value=_response(404)):
        with pytest.raises(UserNotFoundError):
            SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")
