"""
approval.py — Signed, single-use, expiring approval tokens for
higher-impact tool calls; replaces a bare, forgeable boolean.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USED_TOKENS_PATH = PROJECT_ROOT / "evidence" / "traces" / "used_approval_tokens.json"
USED_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_TTL_SECONDS = 120


def _get_secret() -> bytes:
    """Loads the HMAC signing key from APPROVAL_SIGNING_SECRET. No
    hardcoded fallback: a missing env var is a hard config error."""
    secret = os.getenv("APPROVAL_SIGNING_SECRET")
    if not secret:
        raise RuntimeError(
            "APPROVAL_SIGNING_SECRET not set. Add a long random value to your "
            ".env, e.g.: APPROVAL_SIGNING_SECRET=$(python -c \"import secrets; "
            "print(secrets.token_hex(32))\"). This key signs approval tokens; "
            "it must never be committed or shared, and rotating it invalidates "
            "every outstanding token (which is the correct behaviour if it leaks)."
        )
    return secret.encode("utf-8")


def _canonical_args_hash(arguments: Dict[str, Any]) -> str:
    """A stable hash of the arguments a human actually approved."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _load_used_tokens() -> Dict[str, float]:
    """Nonce -> expiry timestamp, for tokens already consumed."""
    if not USED_TOKENS_PATH.exists():
        return {}
    try:
        with open(USED_TOKENS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    now = time.time()
    # Prune anything past its own expiry; it can't be replayed anyway.
    return {nonce: exp for nonce, exp in data.items() if exp > now}


def _save_used_tokens(used: Dict[str, float]) -> None:
    with open(USED_TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(used, f, indent=2)


def create_approval_token(
    tool_name: str,
    arguments: Dict[str, Any],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Mints a token binding approval to one specific tool call. Call
    only after a real human has confirmed the action; this just signs."""
    payload = {
        "tool": tool_name,
        "args_hash": _canonical_args_hash(arguments),
        "nonce": uuid.uuid4().hex,
        "issued_at": time.time(),
        "expires_at": time.time() + ttl_seconds,
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_get_secret(), payload_bytes, hashlib.sha256).digest()
    return f"{_b64url(payload_bytes)}.{_b64url(signature)}"


def verify_and_consume_token(
    token: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Verifies a token is well-formed, signed, for this tool/args, and
    unexpired/unused, then marks it used. Failure consumes nothing."""
    if not token:
        return False, "No approval token provided; this action requires human approval first."

    if not isinstance(token, str) or "." not in token:
        return False, "Malformed approval token."

    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(sig_b64)
        payload = json.loads(payload_bytes)
    except Exception:
        return False, "Malformed approval token."

    expected_sig = hmac.new(_get_secret(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_sig):
        return False, "Approval token signature is invalid (tampered or forged)."

    if payload.get("tool") != tool_name:
        return False, "Approval token was issued for a different tool."

    if payload.get("args_hash") != _canonical_args_hash(arguments):
        return False, (
            "Approval token does not match these arguments — the action "
            "changed after it was approved."
        )

    if time.time() > payload.get("expires_at", 0):
        return False, "Approval token has expired; ask the human to approve again."

    nonce = payload.get("nonce")
    used = _load_used_tokens()
    if nonce in used:
        return False, "Approval token has already been used (replay rejected)."

    used[nonce] = payload["expires_at"]
    _save_used_tokens(used)
    return True, None
