import json
import os
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


class SubscriptionManager:
    UPGRADE_COST: float = 50.00
    API_BASE_URL: str = "https://api.internal.service/users"

    def __init__(self, ledger_dir: str = "/data/ledgers"):
        self.ledger_dir = ledger_dir

    def fetch_user_data(self, user_id: str) -> dict:
        url = f"{self.API_BASE_URL}/{user_id}"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            raise UserNotFoundError(f"User {user_id} not found.")
        return response.json()

    def process_upgrade(self, user_id: str) -> dict:
        user_data = self.fetch_user_data(user_id)

        if user_data.get("status") != "active":
            raise InactiveUserError(f"User {user_id} is not active.")

        balance = float(user_data.get("balance", 0.0))
        if balance < self.UPGRADE_COST:
            raise InsufficientFundsError(
                f"User balance ${balance} is below required threshold."
            )

        # Update balance and tier
        new_balance = balance - self.UPGRADE_COST
        user_data["balance"] = new_balance
        user_data["tier"] = "PREMIUM"

        # Persist ledger file
        os.makedirs(self.ledger_dir, exist_ok=True)
        ledger_path = os.path.join(self.ledger_dir, f"{user_id}.json")
        with open(ledger_path, "w", encoding="utf-8") as f:
            json.dump(user_data, f, indent=2)

        return user_data