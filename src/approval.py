"""
src/approval.py

Human Approval Gate & Signed Token Manager for Higher-Impact Actions.
Fulfills Week 4 objective:
  "Add human approval before any higher-impact action."

Architecture:
  1. Policy: Distinguishes low-impact read-only queries from higher-impact state changes.
  2. Tokens: Generates and verifies HMAC-SHA256 single-use approval tokens bound to
     the exact tool name, arguments, and expiration time (replay prevention).
  3. Approval Gate: Prompts the human operator (interactively or via callback)
     before any higher-impact tool is executed.
"""

from __future__ import annotations

import os
import time
import json
import hmac
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple


# =====================================================================
# 1. Policy: Higher-Impact Actions
# =====================================================================

# Tools that modify financial balances, change user subscription tiers,
# or perform persistent file writes to the ledger.
HIGH_IMPACT_TOOLS = {
    "upgrade_user_subscription",
    "cancel_subscription",
    "downgrade_subscription",
    "process_refund",
    "start_trial",
}


def is_high_impact(tool_name: str) -> bool:
    """Check if a tool performs a state-changing or higher-impact action."""
    return tool_name in HIGH_IMPACT_TOOLS


# =====================================================================
# 2. Token Management (HMAC-SHA256 Signed Single-Use Tokens)
# =====================================================================

DEFAULT_SECRET = "qa-agent-approval-secret-key-2026"
APPROVAL_SECRET_KEY = os.getenv("APPROVAL_SECRET_KEY", DEFAULT_SECRET)

# In-memory store of consumed nonces to prevent token replay attacks
_CONSUMED_NONCES: set[str] = set()

# Flag to control strict token enforcement at the raw tool function level
_STRICT_TOKEN_ENFORCEMENT: bool = False


def set_strict_token_enforcement(enabled: bool) -> None:
    """Enable or disable strict token requirement inside tool functions."""
    global _STRICT_TOKEN_ENFORCEMENT
    _STRICT_TOKEN_ENFORCEMENT = enabled


def is_strict_token_enforcement() -> bool:
    """Return whether strict token requirement is active."""
    return _STRICT_TOKEN_ENFORCEMENT


def _hash_arguments(arguments: Dict[str, Any]) -> str:
    """Produce a deterministic short hash of the tool arguments (excluding any token)."""
    clean_args = {k: v for k, v in sorted(arguments.items()) if k != "approval_token"}
    serialized = json.dumps(clean_args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def create_approval_token(
    tool_name: str,
    arguments: Dict[str, Any],
    ttl_seconds: int = 120,
    secret_key: Optional[str] = None,
) -> str:
    """
    Mint a signed, single-use approval token after explicit human approval.

    Token format:
        <tool_name>.<args_hash>.<expiry_epoch>.<nonce>.<hmac_signature>

    Args:
        tool_name: The name of the tool to be approved.
        arguments: The exact arguments the tool will receive.
        ttl_seconds: Time-to-live in seconds before the token expires (default 120s).
        secret_key: Optional secret key for signing.

    Returns:
        A signed approval token string.
    """
    secret = (secret_key or APPROVAL_SECRET_KEY).encode("utf-8")
    args_hash = _hash_arguments(arguments)
    expiry = int(time.time()) + ttl_seconds
    nonce = secrets.token_hex(8)

    payload = f"{tool_name}.{args_hash}.{expiry}.{nonce}"
    signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    return f"{payload}.{signature}"


def verify_and_consume_token(
    token: Optional[str],
    tool_name: str,
    arguments: Dict[str, Any],
    secret_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Verify the cryptographic signature, expiration, tool binding, argument binding,
    and single-use status of an approval token.

    Args:
        token: The approval token string to verify.
        tool_name: The tool attempting execution.
        arguments: The actual arguments provided to the tool.
        secret_key: Optional secret key for verification.

    Returns:
        (is_valid: bool, reason_or_success_message: str)
    """
    if not token or not isinstance(token, str):
        return False, "Approval token missing: human confirmation required before executing higher-impact action."

    parts = token.split(".")
    if len(parts) != 5:
        return False, "Approval token is malformed."

    tok_tool, tok_args_hash, tok_expiry_str, nonce, tok_signature = parts

    # 1. Check tool name binding
    if tok_tool != tool_name:
        return False, f"Token was issued for tool '{tok_tool}', not '{tool_name}'."

    # 2. Check argument binding (cannot reuse a token approved for user A on user B)
    expected_args_hash = _hash_arguments(arguments)
    if tok_args_hash != expected_args_hash:
        return False, "Token arguments mismatch: token was not approved for these specific arguments."

    # 3. Check expiration
    try:
        tok_expiry = int(tok_expiry_str)
    except ValueError:
        return False, "Token has an invalid expiration timestamp."

    if time.time() > tok_expiry:
        return False, "Approval token has expired (exceeded 120-second validity window)."

    # 4. Check cryptographic signature (tamper protection)
    secret = (secret_key or APPROVAL_SECRET_KEY).encode("utf-8")
    payload = f"{tok_tool}.{tok_args_hash}.{tok_expiry_str}.{nonce}"
    expected_sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(tok_signature, expected_sig):
        return False, "Approval token signature is invalid or has been tampered with."

    # 5. Check replay attack (single-use enforcement)
    if nonce in _CONSUMED_NONCES:
        return False, "Approval token has already been consumed (replay attempt detected)."

    # Mark token as used
    _CONSUMED_NONCES.add(nonce)
    return True, "Token verified and consumed successfully."


# =====================================================================
# 3. Human Approval Gate
# =====================================================================

# Optional callback hook for automated testing or UI integration
_APPROVAL_HOOK: Optional[Callable[[str, Dict[str, Any]], bool]] = None


def set_approval_hook(hook: Optional[Callable[[str, Dict[str, Any]], bool]]) -> None:
    """Register a custom callback function for approving actions (useful for tests/UI)."""
    global _APPROVAL_HOOK
    _APPROVAL_HOOK = hook


def request_human_approval(
    tool_name: str,
    arguments: Dict[str, Any],
    auto_decision: Optional[bool] = None,
) -> Tuple[bool, Optional[str], str]:
    """
    Prompt the human operator to approve a higher-impact action before execution.

    Args:
        tool_name: Name of the higher-impact tool requested.
        arguments: Arguments passed to the tool.
        auto_decision: Optional boolean to bypass prompt (e.g. for testing).

    Returns:
        (approved: bool, token: Optional[str], message: str)
    """
    clean_args = {k: v for k, v in arguments.items() if k != "approval_token"}

    # 1. Check if auto_decision is passed
    if auto_decision is not None:
        approved = auto_decision
    # 2. Check if a programmatic hook is set
    elif _APPROVAL_HOOK is not None:
        approved = _APPROVAL_HOOK(tool_name, clean_args)
    # 3. Fallback: Interactive terminal prompt for human operator
    else:
        print("\n" + "=" * 65)
        print(" [HUMAN APPROVAL REQUIRED] - HIGHER-IMPACT ACTION INTERCEPTED")
        print("=" * 65)
        print(f" Tool:      {tool_name}")
        print(f" Arguments: {json.dumps(clean_args, indent=2)}")
        print(" Warning:   This action modifies account state and persistent ledgers.")
        print("-" * 65)
        try:
            choice = input(" Authorize this action? [y/N]: ").strip().lower()
            approved = choice in ["y", "yes"]
        except (EOFError, KeyboardInterrupt):
            approved = False

    if approved:
        token = create_approval_token(tool_name, clean_args)
        return True, token, "Action approved by human operator."
    else:
        return False, None, "Action rejected by human operator."
