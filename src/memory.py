"""
src/memory.py

Persistent case-history memory (Week 6 justified persistent-memory use case).

Every executed tool call is appended to a JSONL log keyed by user_id. Before a
higher-impact action, the human approver is shown that user's recent history
so they can spot repeated or suspicious requests. The history is for the human
operator only: it is never sent to the LLM or bound into approval tokens.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "case_history.jsonl")

_LOCK = threading.Lock()


def record_case(user_id: str, tool_name: str, status: str, hops: int) -> None:
    """Append one tool-call outcome to the case-history log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "tool_name": tool_name,
        "status": status,
        "hops": hops,
    }
    with _LOCK:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def get_case_history(user_id: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Return the last `limit` entries for `user_id`, most recent first."""
    if not os.path.exists(MEMORY_FILE):
        return []
    with _LOCK:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("user_id") == user_id:
            entries.append(entry)
    if limit <= 0:
        return []
    return list(reversed(entries[-limit:]))


def delete_user_case_history(user_id: str) -> int:
    """Delete all case history records for a given user_id (GDPR right to erasure).

    Returns the count of deleted records.
    """
    if not os.path.exists(MEMORY_FILE):
        return 0
    with _LOCK:
        if not os.path.exists(MEMORY_FILE):
            return 0
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        kept = []
        deleted_count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
                if entry.get("user_id") == user_id:
                    deleted_count += 1
                else:
                    kept.append(stripped)
            except json.JSONDecodeError:
                kept.append(stripped)

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            for item in kept:
                f.write(item + "\n")

    return deleted_count


def purge_expired_records(retention_days: int = 30) -> int:
    """Purge records older than retention_days based on ISO timestamp.

    Returns the count of purged records.
    """
    if not os.path.exists(MEMORY_FILE) or retention_days < 0:
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    with _LOCK:
        if not os.path.exists(MEMORY_FILE):
            return 0
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        kept = []
        purged_count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
                ts_str = entry.get("timestamp")
                if ts_str:
                    entry_dt = datetime.fromisoformat(ts_str)
                    if entry_dt.timestamp() < cutoff:
                        purged_count += 1
                        continue
                kept.append(stripped)
            except (json.JSONDecodeError, ValueError):
                kept.append(stripped)

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            for item in kept:
                f.write(item + "\n")

    return purged_count
