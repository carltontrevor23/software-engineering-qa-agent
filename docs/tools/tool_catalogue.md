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

**Update — current implementation:** `human_approved` (a plain
boolean) has been replaced by `approval_token` (a signed, single-use
string), because a boolean can simply be asserted by whoever fills in
the arguments — including the model itself — while a token has to be
minted by the orchestration layer after a real human confirms, and
cannot be forged or reused. The schema now shipped is:
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string" },
    "approval_token": {
      "type": "string",
      "description": "A signed, single-use approval token minted by the orchestration layer after a human explicitly confirms this exact action. The model cannot generate this. Omit it and the tool reports approval_required."
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
- Requires approval before it will execute (originally specified here
  as `human_approved: true`; now enforced via the `approval_token`
  described above). This is the higher-impact action Week 4 requires
  gating behind approval, since it moves real balance and changes
  account state. If approval is missing or invalid, the tool must not
  call process_upgrade() at all; it returns
  `{"status": "approval_required", "error": "This action requires human confirmation before it can run."}`
  and stops there.
- The agent may propose this action and describe what it would do,
  but may not grant its own approval. Only an explicit human
  confirmation step in the application layer can produce a valid
  approval_token.

Failure Behaviour
------------------
Maps directly to SubscriptionManager.process_upgrade()'s existing
exceptions, so tool failures stay consistent with what Week 2's test
cases already established:
- Missing user_id: reject before calling the underlying function;
  return `{"status": "error", "error": "user_id is required"}`.
- approval_token is missing or invalid (expired, tampered, wrong tool,
  wrong arguments, already used): return status "approval_required"
  as described above, not a generic error, so the agent can
  distinguish "blocked pending approval" from "genuinely failed."
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
Tool 3: cancel_subscription
============================================================

Purpose
-------
Cancels a user's subscription: sets their tier to FREE. Issues no
refund (see Tool 5: process_refund for that).

Wraps: SubscriptionManager.cancel_subscription()

Risk level: Higher impact. Changes account state, customer-facing.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string" },
    "approval_token": { "type": "string", "description": "Signed, single-use token proving human approval of this exact cancellation. The model cannot generate this." }
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
    "status": { "type": "string", "enum": ["success", "error", "approval_required"] },
    "user_id": { "type": "string" },
    "new_tier": { "type": "string" },
    "error": { "type": ["string", "null"] }
  },
  "required": ["status"]
}
```

Authorization
-------------
Same treatment as upgrade_user_subscription: approval_token required,
model cannot self-approve. `self` may cancel only their own account;
`support` may cancel any single named account.

Failure Behaviour
------------------
- Missing user_id / invalid or missing approval_token: same shape as
  Tool 2.
- User not active (InactiveUserError): `{"status": "error", "error":
  "User account is not active."}`.
- Already on FREE tier (AlreadyCancelledError): `{"status": "error",
  "error": "User is already on the FREE tier."}`.
- User not found: `{"status": "error", "error": "User not found."}`.
- Ledger write failure: `{"status": "error", "error": "Could not
  write cancellation to ledger, action not completed."}`.

============================================================
Tool 4: downgrade_subscription
============================================================

Purpose
-------
Downgrades a user from PREMIUM to STANDARD and credits $20.00 back to
their ledger balance.

Wraps: SubscriptionManager.downgrade_subscription()

Risk level: Higher impact. Moves balance and changes tier.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string" },
    "approval_token": { "type": "string", "description": "Signed, single-use token proving human approval of this exact downgrade. The model cannot generate this." }
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
    "status": { "type": "string", "enum": ["success", "error", "approval_required"] },
    "user_id": { "type": "string" },
    "new_tier": { "type": "string" },
    "new_balance": { "type": "number" },
    "error": { "type": ["string", "null"] }
  },
  "required": ["status"]
}
```

Authorization
-------------
Same treatment as upgrade_user_subscription. `self` may downgrade
only their own account; `support` may downgrade any single named
account.

Failure Behaviour
------------------
- Missing user_id / invalid or missing approval_token: same shape as
  Tool 2.
- Tier is not PREMIUM (InvalidTierTransitionError): `{"status":
  "error", "error": "Only a PREMIUM subscription can be downgraded."}`.
- User not active (InactiveUserError): `{"status": "error", "error":
  "User account is not active."}`.
- User not found: `{"status": "error", "error": "User not found."}`.
- Ledger write failure: `{"status": "error", "error": "Could not
  write downgrade to ledger, action not completed."}`.

============================================================
Tool 5: process_refund
============================================================

Purpose
-------
Refunds a user's most recent tier upgrade if it completed within the
last 7 days: reverts their tier and credits $50.00 back to their
balance.

Wraps: SubscriptionManager.process_refund()

Risk level: Higher impact. Financial.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string" },
    "approval_token": { "type": "string", "description": "Signed, single-use token proving human approval of this exact refund. The model cannot generate this." }
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
    "status": { "type": "string", "enum": ["success", "error", "approval_required"] },
    "user_id": { "type": "string" },
    "new_tier": { "type": "string" },
    "new_balance": { "type": "number" },
    "error": { "type": ["string", "null"] }
  },
  "required": ["status"]
}
```

Authorization
-------------
Same approval treatment as the other state-changing tools. `self`
may refund only their own account; `support` may refund any single
named account.

Failure Behaviour
------------------
- Missing user_id / invalid or missing approval_token: same shape as
  Tool 2.
- No eligible upgrade on record, or it's older than 7 days
  (RefundNotEligibleError): `{"status": "error", "error": "<specific
  reason>"}`.
- Already refunded (AlreadyRefundedError): `{"status": "error",
  "error": "This upgrade has already been refunded."}`.
- User not found: `{"status": "error", "error": "User not found."}`.
- Ledger write failure: `{"status": "error", "error": "Could not
  write refund to ledger, action not completed."}`.

============================================================
Tool 6: start_trial
============================================================

Purpose
-------
Starts a one-time, 14-day free PREMIUM trial for a user whose account
is less than 14 days old and who has not already used a trial. No
balance is deducted.

Wraps: SubscriptionManager.start_trial()

Risk level: Higher impact. No money moves, but grants free access to
a paid tier, so it is gated the same as the financial tools.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string" },
    "approval_token": { "type": "string", "description": "Signed, single-use token proving human approval of starting this exact trial. The model cannot generate this." }
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
    "status": { "type": "string", "enum": ["success", "error", "approval_required"] },
    "user_id": { "type": "string" },
    "new_tier": { "type": "string" },
    "trial_start_date": { "type": "string" },
    "trial_end_date": { "type": "string" },
    "error": { "type": ["string", "null"] }
  },
  "required": ["status"]
}
```

Authorization
-------------
Same approval treatment as the other state-changing tools. `self`
may start a trial only for their own account; `support` may act on
any single named account.

Failure Behaviour
------------------
- Missing user_id / invalid or missing approval_token: same shape as
  Tool 2.
- Trial already used (TrialAlreadyUsedError): `{"status": "error",
  "error": "This user has already used their trial."}`.
- Account 14 days or older (TrialNotEligibleError): `{"status":
  "error", "error": "<specific reason>"}`.
- User not found: `{"status": "error", "error": "User not found."}`.
- Ledger write failure: `{"status": "error", "error": "Could not
  write trial start to ledger, action not completed."}`.

============================================================
Notes
============================================================
- All four tools added alongside Tools 1–2 (cancel_subscription,
  downgrade_subscription, process_refund, start_trial) reuse the same
  approval-before-execution treatment as upgrade_user_subscription —
  this was flagged as future work in the original version of this
  document, and is now implemented for all six tools.
- Per the assignment's safety boundary, no tool (1–6) may be
  triggered by anything other than an explicit request tied to a
  specific user_id; no bulk or unattended execution across multiple
  users is in scope.
- A downgrade from STANDARD to FREE remains out of scope for
  downgrade_subscription; use cancel_subscription for that case
  instead.