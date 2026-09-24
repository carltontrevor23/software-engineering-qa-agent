"""
authorization.py — Decides whether THIS caller may act on THIS target
user_id. Fails closed: unknown role/caller/tool is denied by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class CallerContext:
    """Who is actually running the agent — not the user_id argument
    (that's the target). Established outside the model entirely."""
    caller_id: str
    role: str  # "self" | "support"


# "self_only": caller may only target their own account. "any_single_user":
# caller (e.g. support) may target any one account, one at a time.
TOOL_AUTHORIZATION_RULES: Dict[str, Dict[str, str]] = {
    "get_user_subscription_status": {"self": "self_only", "support": "any_single_user"},
    "upgrade_user_subscription": {"self": "self_only", "support": "any_single_user"},
    "cancel_subscription": {"self": "self_only", "support": "any_single_user"},
    "downgrade_subscription": {"self": "self_only", "support": "any_single_user"},
    "process_refund": {"self": "self_only", "support": "any_single_user"},
    "start_trial": {"self": "self_only", "support": "any_single_user"},
}


def authorize(
    caller: Optional[CallerContext],
    tool_name: str,
    arguments: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Returns (allowed, reason); reason is None when allowed. Runs
    before approval is requested and before the tool is dispatched."""
    if caller is None:
        return False, "No caller identity available; refusing by default (fail-closed)."

    if not caller.caller_id or not caller.role:
        return False, "Caller identity is incomplete; refusing by default (fail-closed)."

    policy_by_role = TOOL_AUTHORIZATION_RULES.get(tool_name)
    if policy_by_role is None:
        # No explicit policy means catalogue and this module drifted apart.
        return False, (
            f"No authorization policy defined for tool '{tool_name}'. "
            "Refusing until authorization.py is updated to cover it."
        )

    rule = policy_by_role.get(caller.role)
    if rule is None:
        return False, f"Role '{caller.role}' is not permitted to call '{tool_name}'."

    target_user_id = arguments.get("user_id")
    if not target_user_id:
        # Doesn't assume schema validation already caught this.
        return False, "No target user_id present to authorize against."

    if rule == "self_only" and target_user_id != caller.caller_id:
        return False, (
            f"Caller '{caller.caller_id}' (role: self) may only act on their own "
            f"account, not '{target_user_id}'."
        )

    if rule == "any_single_user":
        # Schema already limits calls to one user_id; nothing more to check.
        return True, None

    if rule == "self_only":
        return True, None

    # Unknown rule string — treat as misconfiguration, not permission.
    return False, f"Unrecognised authorization rule '{rule}' for tool '{tool_name}'."
