# Subscription Service Requirements

## Section 2.3: Subscription Tier Downgrade

Feature: User Subscription Tier Downgrade (PREMIUM to STANDARD)

Acceptance Criteria:
1. The system must fetch current user metadata from the external API endpoint (/users/{user_id}) before processing any downgrade.
2. Downgrade is only permitted from tier "PREMIUM" to tier "STANDARD". Downgrade from "STANDARD" to "FREE" is out of scope for this feature and is handled by the cancellation flow (see Section 2.2).
3. If the user's tier is "PREMIUM" and their status is "active", the system must set their tier to "STANDARD" and credit $20.00 back to the user's local ledger balance.
4. If the user's tier is not "PREMIUM" (e.g. "STANDARD" or "FREE"), the system must raise an InvalidTierTransitionError and must not modify the ledger file.
5. If the user status is not "active", the system must raise an InactiveUserError.
6. If the API returns a non-200 HTTP status code, the system must raise a UserNotFoundError.
7. All file writes must be written atomically to disk using UTF-8 encoding.

Note: This document does not specify whether a downgrade may be reversed within a grace period, or whether downgrade is permitted during an active billing cycle versus only at cycle renewal. This is an open question for product/requirements clarification.
