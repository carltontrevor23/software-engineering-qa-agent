# Subscription Service Requirements

## Section 2.5: Trial Period Management

Feature: Free Trial Period for New Users

Acceptance Criteria:
1. A new user with account age (from registration date) of less than 14 days is eligible for a one-time free trial of the "PREMIUM" tier.
2. Starting a trial must set the user's tier to "PREMIUM" and record a trial_start_date and trial_end_date (trial_start_date + 14 days) in the ledger file, without deducting any balance.
3. If the user has already used a trial (trial_start_date already present in the ledger file), the system must raise a TrialAlreadyUsedError.
4. If the user's account age is 14 days or greater, the system must raise a TrialNotEligibleError.
5. If the API returns a non-200 HTTP status code, the system must raise a UserNotFoundError.
6. All file writes must be written atomically to disk using UTF-8 encoding.

Note: This document does not specify what happens automatically when a trial period ends (e.g. whether the user is auto-downgraded to "FREE", auto-charged, or left on "PREMIUM" until they take action). This behaviour is not yet defined and should be treated as out of scope until clarified.
