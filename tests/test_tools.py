"""
tests/test_tools.py — Exercises every failure/authorization/validation
path for the tools: schema, approval tokens, idempotency, dispatcher auth.
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APPROVAL_SIGNING_SECRET", "test-signing-secret-do-not-use-in-prod")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import subscription_manager as sm
import approval as approval_module
import tools as tools_module
from tools import (
    get_user_subscription_status,
    upgrade_user_subscription,
    cancel_subscription,
    downgrade_subscription,
    process_refund,
    start_trial,
    execute_tool,
    IDEMPOTENCY_LEDGER_PATH,
)
from authorization import CallerContext


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _clear_idempotency_ledger():
    if IDEMPOTENCY_LEDGER_PATH.exists():
        IDEMPOTENCY_LEDGER_PATH.unlink()


def _clear_used_tokens():
    if approval_module.USED_TOKENS_PATH.exists():
        approval_module.USED_TOKENS_PATH.unlink()


def setUpModule():
    _clear_idempotency_ledger()
    _clear_used_tokens()


def datetime_now_minus_days(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# =====================================================================
# get_user_subscription_status — read-only, no approval needed
# =====================================================================

class TestGetUserSubscriptionStatus(unittest.TestCase):

    def test_missing_user_id(self):
        result = get_user_subscription_status()
        self.assertEqual(result["status"], "error")
        self.assertIn("user_id is required", result["error"])

    @patch.object(sm.requests, "get")
    def test_user_not_found_non_200(self, mock_get):
        mock_get.return_value = FakeResponse(404)
        result = get_user_subscription_status(user_id="ghost_user")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "User not found.")

    @patch.object(sm.requests, "get")
    def test_service_unavailable_network_error(self, mock_get):
        mock_get.side_effect = ConnectionError("simulated network failure")
        result = get_user_subscription_status(user_id="u123")
        self.assertEqual(result["status"], "error")
        self.assertIn("unavailable", result["error"])

    @patch.object(sm.requests, "get")
    def test_success(self, mock_get):
        mock_get.return_value = FakeResponse(
            200, {"status": "active", "balance": 100.0, "tier": "STANDARD"}
        )
        result = get_user_subscription_status(user_id="u123")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tier"], "STANDARD")


# =====================================================================
# upgrade_user_subscription — approval-token gated
# =====================================================================

class TestUpgradeUserSubscriptionApprovalLifecycle(unittest.TestCase):
    """Every way an approval token can be missing, wrong, or reused."""

    def setUp(self):
        _clear_used_tokens()
        _clear_idempotency_ledger()

    def test_missing_token(self):
        result = upgrade_user_subscription(user_id="u123")
        self.assertEqual(result["status"], "approval_required")
        self.assertIn("requires human approval", result["error"])

    def test_garbage_token(self):
        result = upgrade_user_subscription(user_id="u123", approval_token="not-a-real-token")
        self.assertEqual(result["status"], "approval_required")

    def test_tampered_signature_is_rejected(self):
        token = approval_module.create_approval_token(
            "upgrade_user_subscription", {"user_id": "u123"}
        )
        payload_part, sig_part = token.split(".", 1)
        tampered = payload_part + "." + sig_part[:-2] + ("aa" if sig_part[-2:] != "aa" else "bb")
        result = upgrade_user_subscription(user_id="u123", approval_token=tampered)
        self.assertEqual(result["status"], "approval_required")
        self.assertIn("signature", result["error"].lower())

    def test_token_bound_to_different_user_id_is_rejected(self):
        # A token approved for u123 is reused to try upgrading u999.
        token = approval_module.create_approval_token(
            "upgrade_user_subscription", {"user_id": "u123"}
        )
        result = upgrade_user_subscription(user_id="u999", approval_token=token)
        self.assertEqual(result["status"], "approval_required")
        self.assertIn("does not match", result["error"])

    def test_token_for_a_different_tool_is_rejected(self):
        token = approval_module.create_approval_token(
            "get_user_subscription_status", {"user_id": "u123"}
        )
        result = upgrade_user_subscription(user_id="u123", approval_token=token)
        self.assertEqual(result["status"], "approval_required")
        self.assertIn("different tool", result["error"])

    def test_expired_token_is_rejected(self):
        token = approval_module.create_approval_token(
            "upgrade_user_subscription", {"user_id": "u123"}, ttl_seconds=-1
        )
        result = upgrade_user_subscription(user_id="u123", approval_token=token)
        self.assertEqual(result["status"], "approval_required")
        self.assertIn("expired", result["error"].lower())

    @patch.object(sm.os, "replace")
    @patch.object(sm.os, "makedirs")
    @patch.object(sm, "open", create=True)
    @patch.object(sm.requests, "get")
    def test_valid_token_executes_exactly_once_then_is_rejected_on_replay(
        self, mock_get, mock_open, mock_makedirs, mock_replace
    ):
        # Only SubscriptionManager's own ledger write is mocked; approval.py's
        # used-token ledger writes for real, since replay rejection is the point.
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})
        token = approval_module.create_approval_token(
            "upgrade_user_subscription", {"user_id": "u123"}
        )

        first = upgrade_user_subscription(user_id="u123", approval_token=token)
        self.assertEqual(first["status"], "success")

        # Replaying the same token: rejected by the single-use check.
        second = upgrade_user_subscription(user_id="u123", approval_token=token)
        self.assertEqual(second["status"], "approval_required")
        self.assertIn("already been used", second["error"])


class TestUpgradeUserSubscriptionBusinessFailures(unittest.TestCase):
    """The original SubscriptionManager failure paths, now reached via a valid token."""

    def setUp(self):
        _clear_used_tokens()
        _clear_idempotency_ledger()

    def _valid_token(self, user_id="u123"):
        return approval_module.create_approval_token(
            "upgrade_user_subscription", {"user_id": user_id}
        )

    def test_missing_user_id(self):
        result = upgrade_user_subscription(approval_token="whatever")
        self.assertEqual(result["status"], "error")
        self.assertIn("user_id is required", result["error"])

    @patch.object(sm.requests, "get")
    def test_inactive_user(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "suspended", "balance": 100.0})
        result = upgrade_user_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("not active", result["error"])

    @patch.object(sm.requests, "get")
    def test_insufficient_funds(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 10.0})
        result = upgrade_user_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("below", result["error"])

    @patch.object(sm.requests, "get")
    def test_user_not_found(self, mock_get):
        mock_get.return_value = FakeResponse(404)
        result = upgrade_user_subscription(
            user_id="ghost", approval_token=self._valid_token("ghost")
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "User not found.")

    @patch.object(sm.requests, "get")
    @patch.object(sm, "open", create=True)
    def test_ledger_write_failure(self, mock_open, mock_get):
        # Scoped to sm.open so the token is verified for real before the mocked write.
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})
        mock_open.side_effect = OSError("simulated disk permission error")
        result = upgrade_user_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("ledger", result["error"])

    @patch.object(sm.os, "replace")
    @patch.object(sm.os, "makedirs")
    @patch.object(sm, "open", create=True)
    @patch.object(sm.requests, "get")
    def test_success(self, mock_get, mock_open, mock_makedirs, mock_replace):
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})
        result = upgrade_user_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["new_tier"], "PREMIUM")
        self.assertEqual(result["new_balance"], 50.0)


class TestUpgradeIdempotency(unittest.TestCase):
    """Two independently-approved upgrades of the same user, seconds apart,
    must not double-execute against the real business logic."""

    def setUp(self):
        _clear_used_tokens()
        _clear_idempotency_ledger()

    @patch.object(sm.os, "replace")
    @patch.object(sm.os, "makedirs")
    @patch.object(sm, "open", create=True)
    @patch.object(sm.requests, "get")
    def test_second_approved_upgrade_within_window_is_suppressed(
        self, mock_get, mock_open, mock_makedirs, mock_replace
    ):
        # sm.open is mocked; tools.py's own idempotency ledger writes for
        # real, since detecting the duplicate is the point of this test.
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})

        token1 = approval_module.create_approval_token(
            "upgrade_user_subscription", {"user_id": "u123"}
        )
        first = upgrade_user_subscription(user_id="u123", approval_token=token1)
        self.assertEqual(first["status"], "success")
        self.assertEqual(first["new_balance"], 50.0)

        # A separate, independently valid token for the same user.
        token2 = approval_module.create_approval_token(
            "upgrade_user_subscription", {"user_id": "u123"}
        )
        second = upgrade_user_subscription(user_id="u123", approval_token=token2)
        self.assertEqual(second["status"], "success")
        self.assertIn("_note", second)
        self.assertIn("Duplicate suppressed", second["_note"])
        # Critically: the balance was NOT deducted a second time.
        self.assertEqual(second["new_balance"], 50.0)


# =====================================================================
# cancel_subscription — approval-token gated, idempotency-guarded
# =====================================================================

class TestCancelSubscription(unittest.TestCase):

    def setUp(self):
        _clear_used_tokens()
        _clear_idempotency_ledger()

    def _valid_token(self, user_id="u123"):
        return approval_module.create_approval_token("cancel_subscription", {"user_id": user_id})

    def test_missing_user_id(self):
        result = cancel_subscription(approval_token="whatever")
        self.assertEqual(result["status"], "error")
        self.assertIn("user_id is required", result["error"])

    def test_missing_token(self):
        result = cancel_subscription(user_id="u123")
        self.assertEqual(result["status"], "approval_required")

    @patch.object(sm.requests, "get")
    def test_inactive_user(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "suspended", "tier": "STANDARD"})
        result = cancel_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("not active", result["error"])

    @patch.object(sm.requests, "get")
    def test_already_free(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "active", "tier": "FREE"})
        result = cancel_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("already", result["error"].lower())

    @patch.object(sm.requests, "get")
    def test_user_not_found(self, mock_get):
        mock_get.return_value = FakeResponse(404)
        result = cancel_subscription(
            user_id="ghost", approval_token=self._valid_token("ghost")
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "User not found.")

    @patch.object(sm.os, "replace")
    @patch.object(sm.os, "makedirs")
    @patch.object(sm, "open", create=True)
    @patch.object(sm.requests, "get")
    def test_success(self, mock_get, mock_open, mock_makedirs, mock_replace):
        mock_get.return_value = FakeResponse(200, {"status": "active", "tier": "STANDARD"})
        result = cancel_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["new_tier"], "FREE")

    @patch.object(sm.os, "replace")
    @patch.object(sm.os, "makedirs")
    @patch.object(sm, "open", create=True)
    @patch.object(sm.requests, "get")
    def test_duplicate_cancel_within_window_is_suppressed(
        self, mock_get, mock_open, mock_makedirs, mock_replace
    ):
        mock_get.return_value = FakeResponse(200, {"status": "active", "tier": "STANDARD"})
        first = cancel_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(first["status"], "success")

        second = cancel_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(second["status"], "success")
        self.assertIn("_note", second)
        self.assertIn("Duplicate suppressed", second["_note"])


# =====================================================================
# downgrade_subscription — approval-token gated, idempotency-guarded
# =====================================================================

class TestDowngradeSubscription(unittest.TestCase):

    def setUp(self):
        _clear_used_tokens()
        _clear_idempotency_ledger()

    def _valid_token(self, user_id="u123"):
        return approval_module.create_approval_token("downgrade_subscription", {"user_id": user_id})

    def test_missing_user_id(self):
        result = downgrade_subscription(approval_token="whatever")
        self.assertEqual(result["status"], "error")
        self.assertIn("user_id is required", result["error"])

    def test_missing_token(self):
        result = downgrade_subscription(user_id="u123")
        self.assertEqual(result["status"], "approval_required")

    @patch.object(sm.requests, "get")
    def test_not_premium_rejected(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "active", "tier": "STANDARD", "balance": 30.0})
        result = downgrade_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("PREMIUM", result["error"])

    @patch.object(sm.requests, "get")
    def test_inactive_user(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "suspended", "tier": "PREMIUM", "balance": 30.0})
        result = downgrade_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("not active", result["error"])

    @patch.object(sm.requests, "get")
    def test_user_not_found(self, mock_get):
        mock_get.return_value = FakeResponse(404)
        result = downgrade_subscription(
            user_id="ghost", approval_token=self._valid_token("ghost")
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "User not found.")

    @patch.object(sm.os, "replace")
    @patch.object(sm.os, "makedirs")
    @patch.object(sm, "open", create=True)
    @patch.object(sm.requests, "get")
    def test_success(self, mock_get, mock_open, mock_makedirs, mock_replace):
        mock_get.return_value = FakeResponse(200, {"status": "active", "tier": "PREMIUM", "balance": 30.0})
        result = downgrade_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["new_tier"], "STANDARD")
        self.assertEqual(result["new_balance"], 50.0)

    @patch.object(sm.os, "replace")
    @patch.object(sm.os, "makedirs")
    @patch.object(sm, "open", create=True)
    @patch.object(sm.requests, "get")
    def test_duplicate_downgrade_within_window_is_suppressed(
        self, mock_get, mock_open, mock_makedirs, mock_replace
    ):
        mock_get.return_value = FakeResponse(200, {"status": "active", "tier": "PREMIUM", "balance": 30.0})
        first = downgrade_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(first["status"], "success")
        self.assertEqual(first["new_balance"], 50.0)

        second = downgrade_subscription(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(second["status"], "success")
        self.assertIn("_note", second)
        # Critically: not credited a second time.
        self.assertEqual(second["new_balance"], 50.0)


# =====================================================================
# process_refund — approval-token gated, self-protected via ledger
# =====================================================================

class TestProcessRefund(unittest.TestCase):

    def setUp(self):
        _clear_used_tokens()
        _clear_idempotency_ledger()

    def _valid_token(self, user_id="u123"):
        return approval_module.create_approval_token("process_refund", {"user_id": user_id})

    def test_missing_user_id(self):
        result = process_refund(approval_token="whatever")
        self.assertEqual(result["status"], "error")
        self.assertIn("user_id is required", result["error"])

    def test_missing_token(self):
        result = process_refund(user_id="u123")
        self.assertEqual(result["status"], "approval_required")

    @patch.object(sm.requests, "get")
    def test_no_upgrade_on_record_is_not_eligible(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 0.0})
        result = process_refund(user_id="never_upgraded", approval_token=self._valid_token("never_upgraded"))
        self.assertEqual(result["status"], "error")
        self.assertIn("No upgrade transaction", result["error"])

    @patch.object(sm.requests, "get")
    def test_user_not_found(self, mock_get):
        mock_get.return_value = FakeResponse(404)
        result = process_refund(user_id="ghost", approval_token=self._valid_token("ghost"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "User not found.")

    @patch.object(sm.requests, "get")
    def test_success_then_second_refund_of_same_upgrade_is_rejected(self, mock_get):
        # Needs a real temp ledger dir: process_refund() reads what
        # upgrade_user_subscription actually wrote across two calls.
        with tempfile.TemporaryDirectory() as tmp_ledger_dir:
            with patch.object(tools_module._manager, "ledger_dir", tmp_ledger_dir):
                # Upgrade first, so there's a real transaction to refund.
                mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})
                upgrade_token = approval_module.create_approval_token(
                    "upgrade_user_subscription", {"user_id": "u123"}
                )
                upgraded = upgrade_user_subscription(user_id="u123", approval_token=upgrade_token)
                self.assertEqual(upgraded["status"], "success")

                mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 50.0})
                refund_token = self._valid_token()
                refunded = process_refund(user_id="u123", approval_token=refund_token)
                self.assertEqual(refunded["status"], "success")
                self.assertEqual(refunded["new_tier"], "STANDARD")  # pre_upgrade_tier
                self.assertEqual(refunded["new_balance"], 100.0)

                # A fresh, validly-signed token must still be rejected,
                # since process_refund() checks the local ledger's "refunded" flag.
                second_refund_token = self._valid_token()
                second_refund = process_refund(user_id="u123", approval_token=second_refund_token)
                self.assertEqual(second_refund["status"], "error")
                self.assertIn("already been refunded", second_refund["error"])


# =====================================================================
# start_trial — approval-token gated, self-protected via ledger
# =====================================================================

class TestStartTrial(unittest.TestCase):

    def setUp(self):
        _clear_used_tokens()
        _clear_idempotency_ledger()

    def _valid_token(self, user_id="u123"):
        return approval_module.create_approval_token("start_trial", {"user_id": user_id})

    def test_missing_user_id(self):
        result = start_trial(approval_token="whatever")
        self.assertEqual(result["status"], "error")
        self.assertIn("user_id is required", result["error"])

    def test_missing_token(self):
        result = start_trial(user_id="u123")
        self.assertEqual(result["status"], "approval_required")

    @patch.object(sm.requests, "get")
    def test_account_too_old_not_eligible(self, mock_get):
        old_registration = (datetime_now_minus_days(30)).isoformat()
        mock_get.return_value = FakeResponse(200, {"status": "active", "registration_date": old_registration})
        result = start_trial(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")
        self.assertIn("14 days", result["error"])

    @patch.object(sm.requests, "get")
    def test_missing_registration_date_not_eligible(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "active"})
        result = start_trial(user_id="u123", approval_token=self._valid_token())
        self.assertEqual(result["status"], "error")

    @patch.object(sm.requests, "get")
    def test_user_not_found(self, mock_get):
        mock_get.return_value = FakeResponse(404)
        result = start_trial(user_id="ghost", approval_token=self._valid_token("ghost"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "User not found.")

    @patch.object(sm.requests, "get")
    def test_success_then_second_trial_is_rejected(self, mock_get):
        # Needs a real temp ledger dir: TrialAlreadyUsedError depends on
        # reading back what the first call actually wrote.
        with tempfile.TemporaryDirectory() as tmp_ledger_dir:
            with patch.object(tools_module._manager, "ledger_dir", tmp_ledger_dir):
                new_registration = datetime_now_minus_days(2).isoformat()
                mock_get.return_value = FakeResponse(
                    200, {"status": "active", "registration_date": new_registration}
                )

                first = start_trial(user_id="u123", approval_token=self._valid_token())
                self.assertEqual(first["status"], "success")
                self.assertEqual(first["new_tier"], "PREMIUM")
                self.assertIsNotNone(first["trial_start_date"])

                second_token = self._valid_token()
                second = start_trial(user_id="u123", approval_token=second_token)
                self.assertEqual(second["status"], "error")
                self.assertIn("already used their trial", second["error"])


# =====================================================================
# Dispatcher — schema validation + unknown tool + authorization
# =====================================================================

class TestExecuteToolDispatcher(unittest.TestCase):

    def test_unknown_tool_name(self):
        result = execute_tool("delete_user_account", {"user_id": "u123"})
        self.assertEqual(result["status"], "error")
        self.assertIn("Unknown tool", result["error"])

    def test_missing_required_field_rejected_by_schema(self):
        result = execute_tool("get_user_subscription_status", {})
        self.assertEqual(result["status"], "error")
        self.assertIn("schema validation", result["error"])

    def test_unexpected_extra_field_rejected_by_schema(self):
        result = execute_tool(
            "get_user_subscription_status", {"user_id": "u123", "sudo": True}
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("schema validation", result["error"])
        self.assertIn("sudo", result["error"])

    def test_wrong_type_rejected_by_schema(self):
        result = execute_tool("get_user_subscription_status", {"user_id": 12345})
        self.assertEqual(result["status"], "error")
        self.assertIn("schema validation", result["error"])

    @patch.object(sm.requests, "get")
    def test_no_caller_skips_authorization_but_not_schema(self, mock_get):
        # Authorization is opt-in via `caller`; schema validation always runs.
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})
        result = execute_tool("get_user_subscription_status", {"user_id": "u123"})
        self.assertEqual(result["status"], "success")

    @patch.object(sm.requests, "get")
    def test_authorized_caller_targeting_own_account(self, mock_get):
        mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})
        caller = CallerContext(caller_id="u123", role="self")
        result = execute_tool(
            "get_user_subscription_status", {"user_id": "u123"}, caller=caller
        )
        self.assertEqual(result["status"], "success")

    def test_unauthorized_caller_targeting_someone_elses_account(self):
        caller = CallerContext(caller_id="u999", role="self")
        result = execute_tool(
            "get_user_subscription_status", {"user_id": "u123"}, caller=caller
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("Not authorized", result["error"])

    def test_support_role_may_target_any_single_account(self):
        caller = CallerContext(caller_id="support_agent_1", role="support")
        with patch.object(sm.requests, "get") as mock_get:
            mock_get.return_value = FakeResponse(200, {"status": "active", "balance": 100.0})
            result = execute_tool(
                "get_user_subscription_status", {"user_id": "any_user"}, caller=caller
            )
        self.assertEqual(result["status"], "success")

    def test_unrecognised_role_denied(self):
        caller = CallerContext(caller_id="u123", role="superadmin")
        result = execute_tool(
            "get_user_subscription_status", {"user_id": "u123"}, caller=caller
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("Not authorized", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
