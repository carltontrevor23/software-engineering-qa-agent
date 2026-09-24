import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests


class InsufficientFundsError(Exception):
    """Raised when the user account balance is below the upgrade threshold."""
    pass


class InactiveUserError(Exception):
    """Raised when the user account status is not active."""
    pass


class UserNotFoundError(Exception):
    """Raised when the user lookup API fails or returns non-200."""
    pass


class AlreadyCancelledError(Exception):
    """Raised when cancellation is requested for a user already on FREE tier."""
    pass


class InvalidTierTransitionError(Exception):
    """Raised when a downgrade is requested from a tier other than PREMIUM."""
    pass


class RefundNotEligibleError(Exception):
    """Raised when there is no eligible upgrade transaction to refund."""
    pass


class AlreadyRefundedError(Exception):
    """Raised when a refund is requested twice for the same upgrade."""
    pass


class TrialAlreadyUsedError(Exception):
    """Raised when a trial is requested for a user who has already used one."""
    pass


class TrialNotEligibleError(Exception):
    """Raised when a trial is requested for an account 14 days or older."""
    pass


class SubscriptionManager:
    UPGRADE_COST: float = 50.00
    DOWNGRADE_CREDIT: float = 20.00
    REFUND_AMOUNT: float = 50.00
    REFUND_WINDOW_DAYS: int = 7
    TRIAL_ELIGIBILITY_DAYS: int = 14
    TRIAL_DURATION_DAYS: int = 14
    API_BASE_URL: str = "https://api.internal.service/users"

    def __init__(self, ledger_dir: str = "/data/ledgers"):
        self.ledger_dir = ledger_dir

    # ------------------------------------------------------------------
    # External API
    # ------------------------------------------------------------------

    def fetch_user_data(self, user_id: str) -> dict:
        url = f"{self.API_BASE_URL}/{user_id}"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            raise UserNotFoundError(f"User {user_id} not found.")
        return response.json()

    # ------------------------------------------------------------------
    # Ledger helpers — every write goes through these for atomic,
    # UTF-8-encoded writes, enforced in one place.
    # ------------------------------------------------------------------

    def _ledger_path(self, user_id: str) -> str:
        return os.path.join(self.ledger_dir, f"{user_id}.json")

    def _read_ledger(self, user_id: str) -> dict:
        path = self._ledger_path(user_id)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_ledger(self, user_id: str, data: dict) -> None:
        os.makedirs(self.ledger_dir, exist_ok=True)
        path = self._ledger_path(user_id)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)

    # ------------------------------------------------------------------
    # Section 2.1: Tier Upgrade (Week 2)
    # ------------------------------------------------------------------

    def process_upgrade(self, user_id: str) -> dict:
        user_data = self.fetch_user_data(user_id)

        if user_data.get("status") != "active":
            raise InactiveUserError(f"User {user_id} is not active.")

        balance = float(user_data.get("balance", 0.0))
        if balance < self.UPGRADE_COST:
            raise InsufficientFundsError(
                f"User balance ${balance} is below required threshold."
            )

        pre_upgrade_tier = user_data.get("tier")
        new_balance = balance - self.UPGRADE_COST
        user_data["balance"] = new_balance
        user_data["tier"] = "PREMIUM"
        # Recorded so process_refund() can find/validate this later.
        user_data["pre_upgrade_tier"] = pre_upgrade_tier
        user_data["upgraded_at"] = datetime.now(timezone.utc).isoformat()
        user_data["refunded"] = False

        self._write_ledger(user_id, user_data)
        return user_data

    # ------------------------------------------------------------------
    # Section 2.2: Subscription Cancellation
    # ------------------------------------------------------------------

    def cancel_subscription(self, user_id: str) -> dict:
        user_data = self.fetch_user_data(user_id)

        if user_data.get("status") != "active":
            raise InactiveUserError(f"User {user_id} is not active.")

        if user_data.get("tier") == "FREE":
            raise AlreadyCancelledError(f"User {user_id} is already on the FREE tier.")

        user_data["tier"] = "FREE"
        user_data["cancelled_at"] = datetime.now(timezone.utc).isoformat()

        self._write_ledger(user_id, user_data)
        return user_data

    # ------------------------------------------------------------------
    # Section 2.3: Subscription Tier Downgrade (PREMIUM -> STANDARD)
    # ------------------------------------------------------------------

    def downgrade_subscription(self, user_id: str) -> dict:
        user_data = self.fetch_user_data(user_id)

        if user_data.get("tier") != "PREMIUM":
            raise InvalidTierTransitionError(
                f"User {user_id} is on tier '{user_data.get('tier')}', not PREMIUM; "
                "only PREMIUM -> STANDARD downgrades are supported."
            )

        if user_data.get("status") != "active":
            raise InactiveUserError(f"User {user_id} is not active.")

        balance = float(user_data.get("balance", 0.0))
        user_data["tier"] = "STANDARD"
        user_data["balance"] = balance + self.DOWNGRADE_CREDIT
        user_data["downgraded_at"] = datetime.now(timezone.utc).isoformat()

        self._write_ledger(user_id, user_data)
        return user_data

    # ------------------------------------------------------------------
    # Section 2.4: Refund Processing
    # ------------------------------------------------------------------

    def process_refund(self, user_id: str) -> dict:
        # Re-fetch: a non-200 is still UserNotFoundError.
        user_data = self.fetch_user_data(user_id)

        ledger = self._read_ledger(user_id)
        upgraded_at_raw = ledger.get("upgraded_at")
        if not upgraded_at_raw:
            raise RefundNotEligibleError(
                f"No upgrade transaction on record for user {user_id}."
            )

        if ledger.get("refunded"):
            raise AlreadyRefundedError(
                f"The upgrade for user {user_id} has already been refunded."
            )

        upgraded_at = datetime.fromisoformat(upgraded_at_raw)
        if datetime.now(timezone.utc) - upgraded_at > timedelta(days=self.REFUND_WINDOW_DAYS):
            raise RefundNotEligibleError(
                f"The upgrade for user {user_id} is outside the "
                f"{self.REFUND_WINDOW_DAYS}-day refund window."
            )

        previous_tier = ledger.get("pre_upgrade_tier") or "STANDARD"
        balance = float(user_data.get("balance", ledger.get("balance", 0.0)))

        ledger["tier"] = previous_tier
        ledger["balance"] = balance + self.REFUND_AMOUNT
        ledger["refunded"] = True
        ledger["refunded_at"] = datetime.now(timezone.utc).isoformat()
        # Reflect fresh fields (e.g. status) without discarding ledger history.
        for key in ("status",):
            if key in user_data:
                ledger[key] = user_data[key]

        self._write_ledger(user_id, ledger)
        return ledger

    # ------------------------------------------------------------------
    # Section 2.5: Trial Period Management
    # ------------------------------------------------------------------

    def start_trial(self, user_id: str) -> dict:
        user_data = self.fetch_user_data(user_id)

        ledger = self._read_ledger(user_id)
        if ledger.get("trial_start_date"):
            raise TrialAlreadyUsedError(f"User {user_id} has already used their trial.")

        registration_date_raw = user_data.get("registration_date")
        if not registration_date_raw:
            # No registration date on record is treated as "not eligible"
            # rather than crashing, to avoid mistaking it for a new account.
            raise TrialNotEligibleError(
                f"User {user_id} has no registration date on record."
            )

        registration_date = datetime.fromisoformat(registration_date_raw)
        account_age_days = (datetime.now(timezone.utc) - registration_date).days
        if account_age_days >= self.TRIAL_ELIGIBILITY_DAYS:
            raise TrialNotEligibleError(
                f"User {user_id}'s account is {account_age_days} days old; "
                f"trials are only available in the first {self.TRIAL_ELIGIBILITY_DAYS} days."
            )

        trial_start = datetime.now(timezone.utc)
        trial_end = trial_start + timedelta(days=self.TRIAL_DURATION_DAYS)

        user_data["tier"] = "PREMIUM"
        user_data["trial_start_date"] = trial_start.isoformat()
        user_data["trial_end_date"] = trial_end.isoformat()

        self._write_ledger(user_id, user_data)
        return user_data
