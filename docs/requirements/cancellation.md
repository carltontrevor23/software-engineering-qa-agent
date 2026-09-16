# Subscription Service Requirements

## Section 2.2: Subscription Cancellation

Feature: User Subscription Cancellation

Acceptance Criteria:
1. The system must fetch current user metadata from the external API endpoint (/users/{user_id}) before processing any cancellation.
2. If the user's status is "active" and their tier is not "FREE", the system must set their tier to "FREE" and record a cancellation timestamp in the local account ledger file at `/data/ledgers/{user_id}.json`.
3. If the user's tier is already "FREE", the system must raise an AlreadyCancelledError and must not modify the ledger file.
4. Cancellation does not issue any refund. Refunds are handled separately (see Section 2.4: Refund Processing).
5. If the user status is not "active" (e.g. "suspended", "pending"), the system must raise an InactiveUserError, consistent with the behaviour defined for tier upgrades in Section 2.1.
6. If the API returns a non-200 HTTP status code, the system must raise a UserNotFoundError.
7. All file writes must be written atomically to disk using UTF-8 encoding, consistent with Section 2.1, Acceptance Criterion 6.
