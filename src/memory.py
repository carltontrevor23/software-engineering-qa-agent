"""
src/memory.py

Persistent memory: requirement test-run history (Week 6 justified memory use case).

Every executed tool call is appended to a JSONL log keyed by requirement_id
(e.g. "REQ-2.1"). Before a high-impact action (file_issue, save_test_to_suite),
the human approver is shown that requirement's recent test runs and a
deterministic advisory (recurring failure vs first failure), so they can judge
whether a failure is a real regression or a flaky/incorrect generated test.

The history is for the human operator only. It is never sent to the LLM, never
bound into approval tokens, and never approves or rejects anything by itself.
Records hold metadata only: no test code, test output, requirement text,
personal data or secrets.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "case_history.jsonl")
RETENTION_DAYS = 30

_LOCK = threading.Lock()


def record_case(
    requirement_id: str,
    tool_name: str,
    status: str,
    hops: int,
    test_outcome: Optional[str] = None,
    failed_count: Optional[int] = None,
) -> None:
    """Append one tool-call outcome to the history log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requirement_id": requirement_id,
        "tool_name": tool_name,
        "status": status,
        "hops": hops,
        "test_outcome": test_outcome,
        "failed_count": failed_count,
    }
    with _LOCK:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def _read_entries() -> List[Dict[str, Any]]:
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
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def get_case_history(
    requirement_id: str, limit: int = 3, tool_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return the last `limit` entries for `requirement_id` (optionally one tool), most recent first."""
    if limit <= 0:
        return []
    entries = [
        e for e in _read_entries()
        if e.get("requirement_id") == requirement_id
        and (tool_name is None or e.get("tool_name") == tool_name)
    ]
    return list(reversed(entries[-limit:]))


def _describe(entry: Dict[str, Any]) -> str:
    outcome = entry.get("test_outcome") or entry.get("status")
    if entry.get("test_outcome") == "failed" and entry.get("failed_count") is not None:
        outcome += f" ({entry['failed_count']} failed)"
    return f"{entry.get('tool_name')} -> {outcome} {str(entry.get('timestamp', ''))[:10]}"


def format_history(requirement_id: str, history: List[Dict[str, Any]]) -> str:
    """One line for the human approver, e.g.
    '[CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed) 2026-10-09; run_tests -> passed 2026-10-07'."""
    if not history:
        return f"[CASE HISTORY] {requirement_id}: no earlier test runs recorded."
    return f"[CASE HISTORY] {requirement_id}: " + "; ".join(_describe(h) for h in history)


def advisory(history: List[Dict[str, Any]]) -> str:
    """Deterministic advisory from run_tests history (most recent first). Advisory only."""
    runs = [h for h in history if h.get("tool_name") == "run_tests" and h.get("test_outcome")]
    if not runs:
        return "NO HISTORY: no earlier test runs for this requirement."
    failures = sum(1 for r in runs if r["test_outcome"] == "failed")
    if runs[0]["test_outcome"] != "failed":
        return f"LATEST RUN {runs[0]['test_outcome'].upper()}: failed in {failures} of the last {len(runs)} runs."
    if failures >= 2:
        return f"RECURRING: failed in {failures} of the last {len(runs)} runs."
    if len(runs) > 1:
        return "FIRST FAILURE: previously passing (possible regression or flaky/incorrect generated test)."
    return "FIRST RUN: no earlier test runs to compare with."


def delete_requirement_history(requirement_id: str) -> int:
    """Delete all history records for one requirement. Returns the count deleted."""
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
                if entry.get("requirement_id") == requirement_id:
                    deleted_count += 1
                else:
                    kept.append(stripped)
            except json.JSONDecodeError:
                kept.append(stripped)

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            for item in kept:
                f.write(item + "\n")

    return deleted_count


def purge_expired_records(retention_days: int = RETENTION_DAYS) -> int:
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
