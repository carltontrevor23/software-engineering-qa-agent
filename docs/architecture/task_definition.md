# Week 5 — Task Definition (Activity 1)

## Evidence the approval gap is real, not assumed
- `src/tool_calling.py`: `upgrade_user_subscription`'s signature only
  accepts `user_id`. Nothing in `execute_tools()` calls
  `approval.is_high_impact()`, `request_human_approval()`, or
  `verify_and_consume_token()` before invoking a tool.
- `tests/test_tool_failures.py` is a genuinely thorough Week 4 suite,
  missing parameters, timeouts, 404s, inactive users, insufficient
  funds, even the exact $49.99 boundary case, but every single call
  to `upgrade_user_subscription.invoke(...)` in it omits
  `approval_token`. None of them test approval being required,
  because the tool does not currently require it.
- `tests/test_approval.py` exists in the repo but is empty. If the
  approval gate were wired in, this is where a test asserting "no
  token means no execution" would live.
Together these three points confirm the gap independently of any one
file being possibly stale.

## Task
Resolve a user's subscription upgrade request end to end, from a
single natural-language ask (e.g. "please upgrade user u123 to
premium") through to either a completed, human-approved upgrade or a
clearly explained refusal.

## Why this genuinely requires multi-step decision making
A single tool call cannot do this correctly, and that is not a
design choice, it is forced by what already exists in the codebase:

1. `upgrade_user_subscription` cannot be called safely without first
   knowing the user's current tier, status, and balance, since
   `process_upgrade()` raises different, meaningful errors
   (`InactiveUserError`, `InsufficientFundsError`,
   `UserNotFoundError`) depending on that state. The agent has to
   call `get_user_subscription_status` first and branch on the
   result, not guess.
2. `upgrade_user_subscription` is registered in
   `approval.py`'s `HIGH_IMPACT_TOOLS` set, meaning it is explicitly
   classified as needing human sign-off. But as currently wired in
   `src/tool_calling.py`, the tool's function signature only accepts
   `user_id`, there is no `approval_token` parameter, and nothing in
   `execute_tools()` calls `request_human_approval()` or
   `verify_and_consume_token()` before invoking it. The approval
   system exists and is well built (signed, single-use, 120-second
   TTL, tool- and argument-bound tokens), it is just not connected to
   the one tool it was built to gate.
3. Because of that gap, this task is not "call one tool, done", it is
   genuinely: sense current state, decide whether the request is even
   valid, stop and hand off to a human before acting, only then act,
   then observe whether the act actually succeeded (ledger write can
   still fail), and report accordingly. Removing any one of those
   steps either breaks correctness (skipping the status check) or
   breaks the safety guarantee Week 4 was supposed to establish
   (skipping the approval gate).

## Sense -> Plan/Decide -> Act/Tool -> Observe -> Stop, applied here
- **Sense**: call `get_user_subscription_status(user_id)`.
- **Plan/Decide**: given tier, status, and balance, decide whether an
  upgrade is even eligible. If not eligible, stop here with a clear
  explanation, no approval request is raised for an action that
  would just fail anyway.
- **Act (gated)**: if eligible, request human approval via
  `approval.py`'s `request_human_approval("upgrade_user_subscription", {...})`.
  Only if approved, call `upgrade_user_subscription` with the
  resulting `approval_token`.
- **Observe**: check the tool's returned `status`. Success means the
  ledger write actually happened, not just that the function
  returned without raising.
- **Stop/Re-plan**: on success, report the new tier and balance. On
  rejection (human said no) or failure (ledger write error), stop
  and report why, do not silently retry a rejected or failed
  higher-impact action.

## What this task exposes as still needing implementation work
This definition surfaces the concrete engineering task for the rest
of Week 5, not just a diagram exercise:
- `upgrade_user_subscription`'s signature in `src/tool_calling.py`
  needs an `approval_token` parameter, and its body needs to call
  `verify_and_consume_token()` before calling
  `manager.process_upgrade()`, returning an error if verification
  fails.
- `execute_tools()` needs to detect when a high-impact tool is being
  called (via `approval.is_high_impact(tool_name)`), pause, call
  `request_human_approval()`, and only proceed to
  `tool_obj.invoke()` if approved, attaching the resulting token to
  the arguments.
- This is also the natural point to enforce a maximum iteration
  count on the assistant/execute_tools loop, since the graph as
  currently built allows the loop to run indefinitely if the model
  keeps deciding to call tools.