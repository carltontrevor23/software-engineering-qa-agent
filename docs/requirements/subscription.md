# Subscription Service Requirements

## Section 2.1: Tier Upgrades
Feature: User Subscription Tier Upgrader

Acceptance Criteria:
1. The system must fetch current user metadata from an external API endpoint (/users/{user_id}).
2. If the user's current account balance is greater than or equal to $50.00 and their status is "active", upgrade their tier to "PREMIUM" and deduct $50.00 from their local account ledger file at `/data/ledgers/{user_id}.json`.
3. If the user's balance is under $50.00, raise an InsufficientFundsError and do not modify the ledger file or upgrade the tier.
4. If the user status is not "active" (e.g., "suspended", "pending"), raise an InactiveUserError.
5. If the API returns a non-200 HTTP status code, raise a UserNotFoundError.
6. All file writes must be written atomically to disk using UTF-8 encoding.