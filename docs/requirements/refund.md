# Subscription Service Requirements

## Section 2.4: Refund Processing

Feature: Upgrade Refund Processing

Acceptance Criteria:
1. Refunds may only be requested for a tier upgrade (see Section 2.1) completed within the last 7 days.
2. The system must fetch the original upgrade transaction record from the local ledger file at `/data/ledgers/{user_id}.json` before processing a refund.
3. If a valid upgrade transaction exists within the 7-day window, the system must revert the user's tier to its previous value and credit $50.00 back to the user's ledger balance.
4. If no upgrade transaction exists, or the transaction is older than 7 days, the system must raise a RefundNotEligibleError.
5. A refund must not be processed more than once for the same upgrade transaction. A second attempt must raise an AlreadyRefundedError.
6. If the API returns a non-200 HTTP status code when re-fetching user metadata, the system must raise a UserNotFoundError.
7. All file writes must be written atomically to disk using UTF-8 encoding.
