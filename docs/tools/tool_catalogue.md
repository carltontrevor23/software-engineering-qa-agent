# Tool Catalogue — Week 4

Project: Software-Engineering QA Agent (Inspectra)
Wraps: src/subscription_manager.py (SubscriptionManager)

This catalogue defines the tools the agent is permitted to call. Each
tool wraps an existing, already-implemented method rather than adding
new business logic, so tool behaviour matches what
src/subscription_manager.py actually does.

============================================================
Tool 1: get_user_subscription_status
============================================================

Purpose
-------
Read-only lookup of a user's current subscription metadata (tier,
status, balance). Used when the agent needs to answer a question
about a user's account, or needs current state before deciding
whether a higher-impact action (like an upgrade) is even valid to
attempt.

Wraps: SubscriptionManager.fetch_user_data()

Risk level: Low. No side effects, no writes, read-only.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "type": "string",
      "description": "The unique identifier of the user to look up."
    }
  },
  "required": ["user_id"]
}
```

Output Schema
-------------
```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["success", "error"]
    },
    "user_id": { "type": "string" },
    "tier": { "type": "string" },
    "account_status": { "type": "string" },
    "balance": { "type": "number" },
    "error": {
      "type": ["string", "null"],
      "description": "Populated only when status is 'error'."
    }
  },
  "required": ["status"]
}
```

Authorization
-------------
- May be called freely by the agent without human approval, since it
  is read-only and returns only the requesting context's own data
  (no cross-user browsing).
- Does not require the user to be in "active" status to look them up;
  the point of this tool is to check status, not assume it.

Failure Behaviour
------------------
- Missing user_id: reject before calling the underlying function;
  return `{"status": "error", "error": "user_id is required"}`.
- API returns non-200 (maps to UserNotFoundError in
  SubscriptionManager.fetch_user_data()): return
  `{"status": "error", "error": "User not found."}`. Do not retry
  silently; surface the failure so the agent can decide whether to
  ask the human for a corrected user_id.
- Unavailable external API (network/timeout): return
  `{"status": "error", "error": "User lookup service unavailable, try again later."}`.
  This is a transient failure, distinct from "user not found."

============================================================
Tool 2: upgrade_user_subscription
============================================================

Purpose
-------
Upgrades a user's tier to PREMIUM and deducts the upgrade cost from
their ledger balance. This is the tool version of the
process_upgrade() flow already implemented and tested in Week 2.

Wraps: SubscriptionManager.process_upgrade()

Risk level: Higher impact. Modifies a user's balance and tier, and
writes to a persistent ledger file. This is a financial action, not
a read.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "type": "string",
      "description": "The unique identifier of the user to upgrade."
    },
    "human_approved": {
      "type": "boolean",
      "description": "Must be true. Set only after a human has explicitly confirmed this specific upgrade action. The tool must refuse to execute if this is false or missing."
    }
  },
  "required": ["user_id", "human_approved"]
}
```

Output Schema
-------------
```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["success", "error", "approval_required"]
    },
    "user_id": { "type": "string" },
    "new_tier": { "type": "string" },
    "new_balance": { "type": "number" },
    "error": {
      "type": ["string", "null"],
      "description": "Populated only when status is 'error' or 'approval_required'."
    }
  },
  "required": ["status"]
}
```

Authorization
-------------
- Requires human_approved: true to execute. This is the higher-impact
  action Week 4 requires gating behind approval, since it moves real
  balance and changes account state. If human_approved is missing or
  false, the tool must not call process_upgrade() at all; it returns
  `{"status": "approval_required", "error": "This action requires human confirmation before it can run."}`
  and stops there.
- The agent may propose this action and describe what it would do,
  but may not set human_approved itself. Only an explicit human
  confirmation step in the application layer may set it to true.

Failure Behaviour
------------------
Maps directly to SubscriptionManager.process_upgrade()'s existing
exceptions, so tool failures stay consistent with what Week 2's test
cases already established:
- Missing user_id: reject before calling the underlying function;
  return `{"status": "error", "error": "user_id is required"}`.
- human_approved is false or missing: return status
  "approval_required" as described above, not a generic error, so
  the agent can distinguish "blocked pending approval" from "genuinely
  failed."
- User not active (InactiveUserError): return
  `{"status": "error", "error": "User account is not active."}`.
- Insufficient balance (InsufficientFundsError): return
  `{"status": "error", "error": "User balance is below the required threshold."}`.
- User not found / API non-200 (UserNotFoundError): return
  `{"status": "error", "error": "User not found."}`.
- Ledger write failure (disk/permission error): return
  `{"status": "error", "error": "Could not write upgrade to ledger, action not completed."}`.
  The tool must not report success unless the ledger write actually
  succeeded, since a reported success with no ledger record would be
  a silent data integrity failure.

============================================================
Notes
============================================================
- Neither tool is permitted to perform a downgrade, cancellation,
  refund, or trial start yet. Those map to real exceptions already
  defined in the requirements corpus (InvalidTierTransitionError,
  AlreadyCancelledError, RefundNotEligibleError,
  AlreadyRefundedError, TrialAlreadyUsedError,
  TrialNotEligibleError) but are out of scope for this week's two
  required tools. They are natural candidates to add as additional
  tools in a later iteration, each needing the same
  approval-before-execution treatment as upgrade_user_subscription.
- Per the assignment's safety boundary, neither tool may be
  triggered by anything other than an explicit request tied to a
  specific user_id; no bulk or unattended execution across multiple
  users is in scope.