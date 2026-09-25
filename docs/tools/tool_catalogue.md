# Tool Catalogue — Week 4

Project: Software-Engineering QA Agent (Inspectra)
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
- Does not require human approval — read-only, no side effects.
- Still passes through the authorization layer: a caller with role
  `self` may only look up their own `user_id`; a caller with role
  `support` may look up any single named `user_id` (never a bulk or
  unbounded query). A missing caller identity, an unrecognised role,
  or a `self` caller requesting someone else's `user_id` is denied
  before the lookup runs, with `{"status": "error", "error": "Not
  authorized: ..."}`.
- Does not require the user to be in "active" status to look them up;
  the point of this tool is to check status, not assume it.

Failure Behaviour
------------------
- Arguments fail schema validation (missing `user_id`, wrong type, or
  an unexpected extra field): return `{"status": "error", "error":
  "Arguments failed schema validation: ..."}` listing every violation.
- Caller not authorized for this `user_id`: return `{"status":
  "error", "error": "Not authorized: <reason>"}`.
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
    "approval_token": {
      "type": "string",
      "description": "A signed, single-use approval token minted by the orchestration layer after a human explicitly confirms this exact action. You cannot generate this token yourself — omit it and the tool will report that approval is required."
    }
  },
  "required": ["user_id"]
}
```
`approval_token` is deliberately NOT in `required`: omitting it must
reach the tool's own `"approval_required"` response (a distinct,
recoverable status the agent can act on), not a generic
schema-validation error. The model is free to include a string here,
but see Authorization below for why that string is never trusted.

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
This is the higher-impact action Week 4 requires gating behind human
approval, since it moves real balance and changes account state. Four
layers, all independently enforced:

1. **Caller authorization** (src/authorization.py): `self` may only
   target their own `user_id`; `support` may target any single named
   `user_id`. Checked in the orchestration layer BEFORE a human is
   ever interrupted for approval — an unauthorized request never
   reaches a human approver — and re-checked independently inside
   `execute_tool()`.
2. **Human approval, via a real LangGraph pause, then a signed token
   — never a boolean** (src/agent.py + src/approval.py): the
   orchestration layer's `execute_tools` graph node calls LangGraph's
   `interrupt({"tool": ..., "arguments": ...})`, which pauses the
   ENTIRE graph — the model has no way to fabricate a resume; it isn't
   part of the conversation the model sees. Something outside the
   graph (the CLI prompt by default) must call `Command(resume=
   {"approved": True})` to wake it back up. Only on a real approval is
   `approval.create_approval_token("upgrade_user_subscription",
   {"user_id": ...})` called to mint a token — HMAC-signed, bound by
   hash to that exact `user_id`, expiring after 120 seconds. The
   model's own `approval_token` argument, if any, is always discarded
   by the orchestration layer before this point; only a token minted
   this way is ever attached to the call the tool actually receives.
   The signed token exists as defense-in-depth ON TOP OF the
   interrupt: the pause alone proves the graph waited for an external
   answer, but the token additionally proves that answer was for
   THESE EXACT arguments and can't be replayed.
3. **Token verification, inside the tool itself**
   (`approval.verify_and_consume_token`): re-checks signature,
   matching tool name, matching arguments (rejects a token approved
   for one `user_id` being reused for another), expiry, and — via a
   persisted nonce ledger — that this exact token has not already
   been spent. A token is marked used only once verification fully
   succeeds, so a failed attempt never burns a still-valid token.
4. **Idempotency guard**: even with two independently valid,
   correctly-approved tokens for the same `user_id` within 10
   seconds, only the first actually calls `process_upgrade()`; the
   second returns the first call's cached result annotated with a
   `_note` field, since `process_upgrade()` has no tier check of its
   own and would silently double-deduct otherwise.

Failure Behaviour
------------------
Maps directly to SubscriptionManager.process_upgrade()'s existing
exceptions plus the layers above, so tool failures stay consistent
with what Week 2's test cases already established:
- Arguments fail schema validation (missing `user_id`, wrong type, or
  an unexpected extra field): return `{"status": "error", "error":
  "Arguments failed schema validation: ..."}`.
- Caller not authorized for this `user_id`: return `{"status":
  "error", "error": "Not authorized: <reason>"}`, before any approval
  or token check even runs.
- `approval_token` missing, malformed, tampered/forged signature,
  issued for a different tool, bound to different arguments, expired,
  or already used (replayed): return `{"status": "approval_required",
  "error": "<specific reason>"}` — a distinct, recoverable status
  from a generic error, so the agent can tell "blocked pending
  approval" apart from "genuinely failed."
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
- A duplicate, independently-approved upgrade within the 10-second
  idempotency window: return the first call's cached `"success"`
  result with an added `_note` explaining the suppression, rather
  than deducting the balance a second time.

============================================================
Tool 3: cancel_subscription
============================================================

Purpose
-------
Cancels a user's subscription: sets their tier to FREE. Issues no
refund (see Tool 5: process_refund for that, which is a separate,
explicitly-requested action).

Wraps: SubscriptionManager.cancel_subscription()
(docs/requirements/cancellation.md, Section 2.2)

Risk level: Higher impact. Changes account state and is
customer-facing (loses paid access), though it moves no money.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string", "description": "The unique identifier of the user to cancel." },
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
Same four-layer treatment as upgrade_user_subscription (authorization
before approval, signed single-use token, idempotency guard). Included
in IDEMPOTENCY_GUARDED_TOOLS because the underlying method checks tier
against the freshly-fetched external API response, not the local
ledger — a second, independently-approved call could otherwise repeat
the write. `self` may cancel only their own account; `support` may
cancel any single named account.

Failure Behaviour
------------------
- Schema/authorization/approval-token failures: identical shape to
  upgrade_user_subscription (see Tool 2).
- User not active (InactiveUserError): `{"status": "error", "error":
  "User account is not active."}`.
- Already on FREE tier (AlreadyCancelledError): `{"status": "error",
  "error": "User is already on the FREE tier."}`.
- User not found / API non-200 (UserNotFoundError): `{"status":
  "error", "error": "User not found."}`.
- Ledger write failure: `{"status": "error", "error": "Could not
  write cancellation to ledger, action not completed."}`.

============================================================
Tool 4: downgrade_subscription
============================================================

Purpose
-------
Downgrades a user from PREMIUM to STANDARD and credits $20.00 back to
their ledger balance. Downgrade from STANDARD to FREE is out of scope
(that's cancellation).

Wraps: SubscriptionManager.downgrade_subscription()
(docs/requirements/downgrade.md, Section 2.3)

Risk level: Higher impact. Moves balance and changes tier.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string", "description": "The unique identifier of the user to downgrade." },
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
Same four-layer treatment as upgrade_user_subscription, including the
idempotency guard (a duplicate approved downgrade would otherwise
double-credit $20.00, for the same reason cancel_subscription needs
the guard — the tier check reads the freshly-fetched API response,
not the local ledger). `self` may downgrade only their own account;
`support` may downgrade any single named account.

Failure Behaviour
------------------
- Schema/authorization/approval-token failures: identical shape to
  upgrade_user_subscription.
- Tier is not PREMIUM (InvalidTierTransitionError): `{"status":
  "error", "error": "Only a PREMIUM subscription can be downgraded."}`.
- User not active (InactiveUserError): `{"status": "error", "error":
  "User account is not active."}`.
- User not found / API non-200 (UserNotFoundError): `{"status":
  "error", "error": "User not found."}`.
- Ledger write failure: `{"status": "error", "error": "Could not
  write downgrade to ledger, action not completed."}`.

============================================================
Tool 5: process_refund
============================================================

Purpose
-------
Refunds a user's most recent tier upgrade if it completed within the
last 7 days: reverts their tier to what it was before the upgrade and
credits $50.00 back to their balance.

Wraps: SubscriptionManager.process_refund()
(docs/requirements/refund.md, Section 2.4)

Risk level: Higher impact. Financial, and reads/writes local
transaction history (not just the external API).

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string", "description": "The unique identifier of the user to refund." },
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
Authorization + signed approval token, same as the other
state-changing tools. **Not** in IDEMPOTENCY_GUARDED_TOOLS: unlike
upgrade/cancel/downgrade, SubscriptionManager.process_refund() checks
its own precondition (the `refunded` flag) against the LOCAL ledger on
every single call, so a second attempt deterministically raises
AlreadyRefundedError on its own — a second, redundant guard here would
just be two mechanisms protecting the same invariant. `self` may
refund only their own account; `support` may refund any single named
account.

Failure Behaviour
------------------
- Schema/authorization/approval-token failures: identical shape to
  upgrade_user_subscription.
- No eligible upgrade on record, or it's older than 7 days
  (RefundNotEligibleError): `{"status": "error", "error": "<specific
  reason>"}`.
- Already refunded (AlreadyRefundedError): `{"status": "error",
  "error": "This upgrade has already been refunded."}`.
- User not found / API non-200 (UserNotFoundError): `{"status":
  "error", "error": "User not found."}`.
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
(docs/requirements/trial_period.md, Section 2.5)

Risk level: Higher impact. No money moves, but it grants free access
to a paid tier — the assignment's "higher-impact action" bar isn't
limited to things that cost money, so this is gated the same as the
financial tools.

Input Schema
------------
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string", "description": "The unique identifier of the user to start a trial for." },
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
Authorization + signed approval token, same as the other
state-changing tools. **Not** in IDEMPOTENCY_GUARDED_TOOLS, for the
same reason as process_refund: `trial_start_date` is checked against
the LOCAL ledger on every call, so a repeat call deterministically
raises TrialAlreadyUsedError on its own. `self` may start a trial only
for their own account; `support` may act on any single named account.

Failure Behaviour
------------------
- Schema/authorization/approval-token failures: identical shape to
  upgrade_user_subscription.
- Trial already used (TrialAlreadyUsedError): `{"status": "error",
  "error": "This user has already used their trial."}`.
- Account 14 days or older (TrialNotEligibleError): `{"status":
  "error", "error": "<specific reason>"}`.
- User not found / API non-200 (UserNotFoundError): `{"status":
  "error", "error": "User not found."}`.
- Ledger write failure: `{"status": "error", "error": "Could not
  write trial start to ledger, action not completed."}`.

============================================================
Notes
============================================================
- All four state-changing tools added in this revision
  (cancel_subscription, downgrade_subscription, process_refund,
  start_trial) reuse the exact same hardening pipeline as
  upgrade_user_subscription: schema validation, pre-approval
  authorization, signed single-use approval tokens, and (for
  upgrade/cancel/downgrade specifically) an idempotency guard. No new
  safety mechanism was invented per tool — the goal was one hardening
  design applied uniformly, not six bespoke ones.
- Per the assignment's safety boundary, no tool may be triggered by
  anything other than an explicit request tied to a specific
  user_id; no bulk or unattended execution across multiple users is
  in scope for any of the six tools.
- A downgrade from STANDARD to FREE remains out of scope for
  downgrade_subscription (per downgrade.md); use cancel_subscription
  for that case instead.
- What happens automatically when a trial period ends (auto-downgrade
  vs. auto-charge vs. left on PREMIUM) is explicitly out of scope per
  trial_period.md and is not implemented by start_trial or anywhere
  else in this codebase.