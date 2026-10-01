# Agent Control Loop Specification: Sense-Plan-Act-Observe-Stop

This document outlines the deterministic 5-stage control loop and decision architecture for the **Bounded User Subscription Agent**.

---

## Stage 1: Sense / Context

### Information Received
* **Initial Turn:** Natural-language user prompt (e.g., extracting intent: `upgrade`, target: `user_id="u123"`).
* **Intermediate Turn:** Observation payload returned by `get_user_subscription_status`:
  * Account status (`active`, `suspended`, `pending`, or `not_found`).
  * Current tier (`FREE`, `STANDARD`, `PREMIUM`).
  * Current balance (e.g., `$100.00`).

### Relevant Context Evaluated
* **Requirements rules** from `docs/requirements/subscription.md`:
  * User account status must be `"active"`.
  * Current tier must not already be `"PREMIUM"`.
  * Current balance must be $\ge \$50.00$ (`UPGRADE_COST`).
* **Safety policy** from `src/approval.py`:
  * `upgrade_user_subscription` is registered in `HIGH_IMPACT_TOOLS` and modifies financial/ledger state.

---

## Stage 2: Plan / Decide

The agent chooses among three deterministic paths based strictly on available context:

* **Path A — Missing Account Context:**
  * **Condition:** Account status, current tier, and balance for `user_id` are not yet known.
  * **Decision:** Call `get_user_subscription_status(user_id)`.

* **Path B — Ineligible / Precondition Failure:**
  * **Condition:** Account data is present, but fails acceptance criteria:
    * User does not exist (`UserNotFoundError`).
    * Status is not `"active"` (e.g., suspended or pending).
    * Tier is already `"PREMIUM"`.
    * Balance is below the $\$50.00$ threshold.
  * **Decision:** Do not request human approval; proceed directly to **Stop** with an explicit refusal explanation.

* **Path C — Eligible for Mutation:**
  * **Condition:** User is active, tier is upgradeable, and balance is $\ge \$50.00$.
  * **Decision:** Call `upgrade_user_subscription(user_id)`.

---

## Stage 3: Act / Tool

The agent triggers the approved tool selected during planning:

### Tool 1: `get_user_subscription_status` *(Autonomous / Low-Impact)*
* **Parameters:** `{"user_id": "u123"}`
* **System Action:** Queries `SubscriptionManager.fetch_user_data()` to fetch read-only metadata.

### Tool 2: `upgrade_user_subscription` *(Higher-Impact Action)*
* **Parameters:** `{"user_id": "u123", "approval_token": <token>}`
* **Connection Point:** The orchestration layer intercepts this call via `is_high_impact()`, requesting human operator confirmation before execution.
* **System Action:** Deducts $\$50.00$, updates tier to `"PREMIUM"`, and performs an atomic write to `/data/ledgers/{user_id}.json`.

---

## Stage 4: Observe

The agent receives and parses the tool result:

### From `get_user_subscription_status`
* **Success Result:** `{"status": "success", "tier": "STANDARD", "account_status": "active", "balance": 100.0}`
* **Error Result:** `{"status": "error", "error": "User not found."}`
* **Effect on Next Step:** Provides the necessary context for the agent to branch into Path B (refusal) or Path C (upgrade).

### From `upgrade_user_subscription` *(or Approval Intercept)*
* **Approved & Succeeded:** `{"status": "success", "tier": "PREMIUM", "balance": 50.0}`
* **Human Rejection:** `{"status": "approval_required", "error": "Action rejected by human operator."}`
* **System/Disk Failure:** `{"status": "error", "error": "Could not write upgrade to ledger..."}`
* **Effect on Next Step:** Determines whether the task succeeded or ended in an explained refusal/failure.

---

## Stage 5: Stop / Re-plan

### When the Agent RE-PLANS
* **Exactly once:** After observing the return payload of `get_user_subscription_status`. The agent re-enters **Stage 2 (Plan/Decide)** equipped with the new account context to decide whether to attempt the upgrade or refuse.

### When the Agent STOPS (Task Complete)
The workflow deterministically stops under four terminal conditions:

1. **Terminal Success:** Tool returns `status: "success"` with updated tier. Agent stops and issues confirmation to the user.
2. **Precondition Refusal:** Ineligibility observed during Stage 2 (e.g., insufficient funds or suspended user). Agent stops and outputs the specific reason.
3. **Human Rejection:** Operator declined approval. Agent stops and explains that the operation was denied by human authorization.
4. **Tool Failure:** Service timed out or disk write failed. Agent stops and reports the failure without retrying.