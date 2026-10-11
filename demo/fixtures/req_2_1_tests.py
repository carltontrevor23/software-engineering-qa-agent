"""
Hand-written tests for REQ-2.1 used by --offline mode in place of model output.
The exact-$50.00 case fails when demo/run_demo.py --planted-bug is active.
"""

from unittest.mock import MagicMock, patch

import pytest

from subscription_service.subscription_manager import (
    InsufficientFundsError,
    SubscriptionManager,
)

GET = "subscription_service.subscription_manager.requests.get"


def _user(balance):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"status": "active", "tier": "STANDARD", "balance": balance}
    return resp


def test_upgrade_at_exactly_50_00(tmp_path):
    # AC-2: balance greater than or equal to $50.00 upgrades and deducts $50.00.
    with patch(GET, return_value=_user(50.00)):
        result = SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")
    assert result["tier"] == "PREMIUM"
    assert result["balance"] == 0.0


def test_upgrade_above_50_00(tmp_path):
    # AC-2: balance above the threshold upgrades.
    with patch(GET, return_value=_user(50.01)):
        result = SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")
    assert result["tier"] == "PREMIUM"


def test_upgrade_below_50_00_raises(tmp_path):
    # AC-3: balance under $50.00 raises InsufficientFundsError and writes nothing.
    with patch(GET, return_value=_user(49.99)):
        with pytest.raises(InsufficientFundsError):
            SubscriptionManager(ledger_dir=str(tmp_path)).process_upgrade("u1")
    assert not (tmp_path / "u1.json").exists()
