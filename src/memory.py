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
