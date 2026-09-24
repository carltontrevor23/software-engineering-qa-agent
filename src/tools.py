"""
tools.py — Tool implementations for the QA Agent (wraps SubscriptionManager).
Each call is checked by schema, authorization, approval token, then idempotency.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from subscription_manager import (
    SubscriptionManager,
    InsufficientFundsError,
    InactiveUserError,
    UserNotFoundError,
    AlreadyCancelledError,
    InvalidTierTransitionError,
    RefundNotEligibleError,
    AlreadyRefundedError,
    TrialAlreadyUsedError,
    TrialNotEligibleError,
)
from authorization import CallerContext, authorize
import approval as approval_module

# A single shared SubscriptionManager instance for all tool calls.
_manager = SubscriptionManager()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IDEMPOTENCY_LEDGER_PATH = PROJECT_ROOT / "evidence" / "traces" / "upgrade_idempotency.json"
IDEMPOTENCY_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
IDEMPOTENCY_WINDOW_SECONDS = 10
# Guards against two independently-approved tokens re-running the same
# mutation seconds apart. refund/start_trial don't need this — they check the local ledger.
IDEMPOTENCY_GUARDED_TOOLS = {
    "upgrade_user_subscription",
    "downgrade_subscription",
    "cancel_subscription",
}


# =====================================================================
# Pydantic argument schemas the model sees; extra="forbid" rejects
# unexpected fields. approval_token defaults to None.
# =====================================================================

class GetUserSubscriptionStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(description="The unique identifier of the user to look up.")


class UpgradeUserSubscriptionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(description="The unique identifier of the user to upgrade.")
    approval_token: Optional[str] = Field(
        default=None,
        description=(
            "A signed, single-use token proving a human approved this exact "
            "upgrade. You cannot generate this token; omit it and the tool "
            "will report that approval is required instead of executing."
        ),
    )


class CancelSubscriptionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(description="The unique identifier of the user to cancel.")
    approval_token: Optional[str] = Field(
        default=None,
        description=(
            "A signed, single-use token proving a human approved this exact "
            "cancellation. Omit it and the tool will report that approval "
            "is required."
        ),
    )


class DowngradeSubscriptionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(description="The unique identifier of the user to downgrade.")
    approval_token: Optional[str] = Field(
        default=None,
        description=(
            "A signed, single-use token proving a human approved this exact "
            "downgrade. Omit it and the tool will report that approval is "
            "required."
        ),
    )


class ProcessRefundArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(description="The unique identifier of the user to refund.")
    approval_token: Optional[str] = Field(
        default=None,
        description=(
            "A signed, single-use token proving a human approved this exact "
            "refund. Omit it and the tool will report that approval is "
            "required."
        ),
    )


class StartTrialArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(description="The unique identifier of the user to start a trial for.")
    approval_token: Optional[str] = Field(
        default=None,
        description=(
            "A signed, single-use token proving a human approved starting "
            "this exact trial. Omit it and the tool will report that "
            "approval is required."
        ),
    )


# =====================================================================
# Idempotency ledger (upgrade_user_subscription only)
# =====================================================================

def _load_idempotency_ledger() -> Dict[str, Dict[str, Any]]:
    if not IDEMPOTENCY_LEDGER_PATH.exists():
        return {}
    try:
        with open(IDEMPOTENCY_LEDGER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_idempotency_ledger(ledger: Dict[str, Dict[str, Any]]) -> None:
    with open(IDEMPOTENCY_LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)


def _idempotency_key(tool_name: str, user_id: str) -> str:
    return f"{tool_name}:{user_id}"


def _recent_duplicate_action(tool_name: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Returns the cached prior result if this (tool, user) pair executed
    recently, else None."""
    ledger = _load_idempotency_ledger()
    entry = ledger.get(_idempotency_key(tool_name, user_id))
    if entry and (time.time() - entry.get("executed_at", 0)) < IDEMPOTENCY_WINDOW_SECONDS:
        return entry.get("result")
    return None


def _record_action_execution(tool_name: str, user_id: str, result: Dict[str, Any]) -> None:
    ledger = _load_idempotency_ledger()
    ledger[_idempotency_key(tool_name, user_id)] = {"executed_at": time.time(), "result": result}
    _save_idempotency_ledger(ledger)


# =====================================================================
# Tool implementations
# =====================================================================

def get_user_subscription_status(user_id: str | None = None, **_ignored: Any) -> Dict[str, Any]:
    """Wraps SubscriptionManager.fetch_user_data(). Returns status "error"
    on missing user_id, not-found, or a network/timeout failure."""
    if not user_id:
        return {"status": "error", "error": "user_id is required"}

    try:
        data = _manager.fetch_user_data(user_id)
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except Exception as e:  # network/timeout/connection issues from `requests`
        return {
            "status": "error",
            "error": "User lookup service unavailable, try again later.",
            "_debug": str(e),
        }

    return {
        "status": "success",
        "user_id": user_id,
        "tier": data.get("tier", "UNKNOWN"),
        "account_status": data.get("status", "unknown"),
        "balance": data.get("balance", 0.0),
    }


def upgrade_user_subscription(
    user_id: str | None = None,
    approval_token: str | None = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """Wraps SubscriptionManager.process_upgrade(), gated behind a signed
    approval token; duplicate calls return the cached result."""
    if not user_id:
        return {"status": "error", "error": "user_id is required"}

    ok, reason = approval_module.verify_and_consume_token(
        approval_token, "upgrade_user_subscription", {"user_id": user_id}
    )
    if not ok:
        return {"status": "approval_required", "error": reason}

    cached = _recent_duplicate_action("upgrade_user_subscription", user_id)
    if cached is not None:
        return {**cached, "_note": "Duplicate suppressed: returning cached result "
                                    f"from within the last {IDEMPOTENCY_WINDOW_SECONDS}s."}

    try:
        result = _manager.process_upgrade(user_id)
    except InactiveUserError:
        return {"status": "error", "error": "User account is not active."}
    except InsufficientFundsError:
        return {"status": "error", "error": "User balance is below the required threshold."}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except OSError as e:
        # Ledger disk/permission failure.
        return {
            "status": "error",
            "error": "Could not write upgrade to ledger, action not completed.",
            "_debug": str(e),
        }
    except Exception as e:  # network/timeout issues from the initial fetch
        return {
            "status": "error",
            "error": "User lookup service unavailable, try again later.",
            "_debug": str(e),
        }

    success_result = {
        "status": "success",
        "user_id": user_id,
        "new_tier": result.get("tier"),
        "new_balance": result.get("balance"),
    }
    _record_action_execution("upgrade_user_subscription", user_id, success_result)
    return success_result


def cancel_subscription(
    user_id: str | None = None,
    approval_token: str | None = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """Wraps SubscriptionManager.cancel_subscription(). Sets tier to FREE,
    issues no refund. Gated behind a signed approval token."""
    if not user_id:
        return {"status": "error", "error": "user_id is required"}

    ok, reason = approval_module.verify_and_consume_token(
        approval_token, "cancel_subscription", {"user_id": user_id}
    )
    if not ok:
        return {"status": "approval_required", "error": reason}

    cached = _recent_duplicate_action("cancel_subscription", user_id)
    if cached is not None:
        return {**cached, "_note": "Duplicate suppressed: returning cached result "
                                    f"from within the last {IDEMPOTENCY_WINDOW_SECONDS}s."}

    try:
        result = _manager.cancel_subscription(user_id)
    except InactiveUserError:
        return {"status": "error", "error": "User account is not active."}
    except AlreadyCancelledError:
        return {"status": "error", "error": "User is already on the FREE tier."}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except OSError as e:
        return {
            "status": "error",
            "error": "Could not write cancellation to ledger, action not completed.",
            "_debug": str(e),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": "User lookup service unavailable, try again later.",
            "_debug": str(e),
        }

    success_result = {
        "status": "success",
        "user_id": user_id,
        "new_tier": result.get("tier"),
    }
    _record_action_execution("cancel_subscription", user_id, success_result)
    return success_result


def downgrade_subscription(
    user_id: str | None = None,
    approval_token: str | None = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """Wraps SubscriptionManager.downgrade_subscription() (PREMIUM ->
    STANDARD, credits $20.00). Gated by approval token and idempotency."""
    if not user_id:
        return {"status": "error", "error": "user_id is required"}

    ok, reason = approval_module.verify_and_consume_token(
        approval_token, "downgrade_subscription", {"user_id": user_id}
    )
    if not ok:
        return {"status": "approval_required", "error": reason}

    cached = _recent_duplicate_action("downgrade_subscription", user_id)
    if cached is not None:
        return {**cached, "_note": "Duplicate suppressed: returning cached result "
                                    f"from within the last {IDEMPOTENCY_WINDOW_SECONDS}s."}

    try:
        result = _manager.downgrade_subscription(user_id)
    except InvalidTierTransitionError:
        return {"status": "error", "error": "Only a PREMIUM subscription can be downgraded."}
    except InactiveUserError:
        return {"status": "error", "error": "User account is not active."}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except OSError as e:
        return {
            "status": "error",
            "error": "Could not write downgrade to ledger, action not completed.",
            "_debug": str(e),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": "User lookup service unavailable, try again later.",
            "_debug": str(e),
        }

    success_result = {
        "status": "success",
        "user_id": user_id,
        "new_tier": result.get("tier"),
        "new_balance": result.get("balance"),
    }
    _record_action_execution("downgrade_subscription", user_id, success_result)
    return success_result


def process_refund(
    user_id: str | None = None,
    approval_token: str | None = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """Wraps SubscriptionManager.process_refund() (refunds an upgrade from
    the last 7 days, reverts tier, credits $50.00). Gated by approval token."""
    if not user_id:
        return {"status": "error", "error": "user_id is required"}

    ok, reason = approval_module.verify_and_consume_token(
        approval_token, "process_refund", {"user_id": user_id}
    )
    if not ok:
        return {"status": "approval_required", "error": reason}

    try:
        result = _manager.process_refund(user_id)
    except RefundNotEligibleError as e:
        return {"status": "error", "error": str(e)}
    except AlreadyRefundedError:
        return {"status": "error", "error": "This upgrade has already been refunded."}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except OSError as e:
        return {
            "status": "error",
            "error": "Could not write refund to ledger, action not completed.",
            "_debug": str(e),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": "User lookup service unavailable, try again later.",
            "_debug": str(e),
        }

    return {
        "status": "success",
        "user_id": user_id,
        "new_tier": result.get("tier"),
        "new_balance": result.get("balance"),
    }


def start_trial(
    user_id: str | None = None,
    approval_token: str | None = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """Wraps SubscriptionManager.start_trial() (one-time 14-day PREMIUM
    trial for accounts under 14 days old). Gated by approval token."""
    if not user_id:
        return {"status": "error", "error": "user_id is required"}

    ok, reason = approval_module.verify_and_consume_token(
        approval_token, "start_trial", {"user_id": user_id}
    )
    if not ok:
        return {"status": "approval_required", "error": reason}

    try:
        result = _manager.start_trial(user_id)
    except TrialAlreadyUsedError:
        return {"status": "error", "error": "This user has already used their trial."}
    except TrialNotEligibleError as e:
        return {"status": "error", "error": str(e)}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except OSError as e:
        return {
            "status": "error",
            "error": "Could not write trial start to ledger, action not completed.",
            "_debug": str(e),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": "User lookup service unavailable, try again later.",
            "_debug": str(e),
        }

    return {
        "status": "success",
        "user_id": user_id,
        "new_tier": result.get("tier"),
        "trial_start_date": result.get("trial_start_date"),
        "trial_end_date": result.get("trial_end_date"),
    }


# =====================================================================
# LangChain tool objects bound to the model. Each wraps the plain
# function above; registered `.name` has no `_tool` suffix.
# =====================================================================

@tool("get_user_subscription_status", args_schema=GetUserSubscriptionStatusArgs)
def get_user_subscription_status_tool(user_id: str) -> Dict[str, Any]:
    """Read-only lookup of a user's subscription tier, status, and
    balance. Safe to call freely; no approval required."""
    return get_user_subscription_status(user_id=user_id)


@tool("upgrade_user_subscription", args_schema=UpgradeUserSubscriptionArgs)
def upgrade_user_subscription_tool(user_id: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Upgrades a user's tier to PREMIUM and deducts the cost from their
    balance. Requires a valid approval_token; you cannot generate one."""
    return upgrade_user_subscription(user_id=user_id, approval_token=approval_token)


@tool("cancel_subscription", args_schema=CancelSubscriptionArgs)
def cancel_subscription_tool(user_id: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Cancels a user's subscription, setting their tier to FREE. Issues
    no refund. Requires a valid approval_token; you cannot generate one."""
    return cancel_subscription(user_id=user_id, approval_token=approval_token)


@tool("downgrade_subscription", args_schema=DowngradeSubscriptionArgs)
def downgrade_subscription_tool(user_id: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Downgrades a user from PREMIUM to STANDARD and credits $20.00 back.
    Requires a valid approval_token; you cannot generate one."""
    return downgrade_subscription(user_id=user_id, approval_token=approval_token)


@tool("process_refund", args_schema=ProcessRefundArgs)
def process_refund_tool(user_id: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Refunds a user's tier upgrade if within the last 7 days: reverts
    tier, credits $50.00. Requires a valid approval_token."""
    return process_refund(user_id=user_id, approval_token=approval_token)


@tool("start_trial", args_schema=StartTrialArgs)
def start_trial_tool(user_id: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Starts a one-time, 14-day free PREMIUM trial for accounts under
    14 days old. Requires a valid approval_token."""
    return start_trial(user_id=user_id, approval_token=approval_token)


# Bound to the model with `.bind_tools(TOOLS, parallel_tool_calls=False)`
# in src/agent.py — one tool call awaiting approval at a time.
TOOLS = [
    get_user_subscription_status_tool,
    upgrade_user_subscription_tool,
    cancel_subscription_tool,
    downgrade_subscription_tool,
    process_refund_tool,
    start_trial_tool,
]

_TOOLS_BY_NAME: Dict[str, Any] = {t.name: t for t in TOOLS}
_TOOL_NAMES = set(_TOOLS_BY_NAME)


def _format_pydantic_errors(exc: PydanticValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


# =====================================================================
# Dispatcher — called with whatever tool the model asked for.
# =====================================================================

def execute_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    caller: Optional[CallerContext] = None,
) -> Dict[str, Any]:
    """Looks up and runs a tool by name, checking schema then
    authorization first. Always returns a dict with a "status" key.
    """
    tool_obj = _TOOLS_BY_NAME.get(tool_name)
    if tool_obj is None:
        return {
            "status": "error",
            "error": f"Unknown tool '{tool_name}'. Available tools: "
                     f"{', '.join(sorted(_TOOL_NAMES))}.",
        }

    try:
        tool_obj.args_schema.model_validate(arguments)
    except PydanticValidationError as e:
        return {
            "status": "error",
            "error": "Arguments failed schema validation: " + _format_pydantic_errors(e),
        }

    if caller is not None:
        allowed, deny_reason = authorize(caller, tool_name, arguments)
        if not allowed:
            return {"status": "error", "error": f"Not authorized: {deny_reason}"}

    fn = globals()[tool_name]
    try:
        return fn(**arguments)
    except TypeError as e:
        # Belt-and-suspenders in case of schema/signature drift.
        return {"status": "error", "error": f"Invalid arguments for '{tool_name}': {e}"}


if __name__ == "__main__":
    # Quick manual smoke test of the dispatcher, no model involved.
    import json as _json

    print("Missing user_id:")
    print(_json.dumps(execute_tool("get_user_subscription_status", {}), indent=2))

    print("\nUnapproved upgrade attempt (no token):")
    print(_json.dumps(execute_tool("upgrade_user_subscription", {"user_id": "u123"}), indent=2))

    print("\nSchema violation (unexpected extra field):")
    print(_json.dumps(
        execute_tool("get_user_subscription_status", {"user_id": "u123", "sudo": True}),
        indent=2,
    ))

    print("\nUnknown tool:")
    print(_json.dumps(execute_tool("delete_user_account", {"user_id": "u123"}), indent=2))
