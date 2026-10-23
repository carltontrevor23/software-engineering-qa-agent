"""
Deterministic guardrails for the Inspectra QA agent (Week 7).

  - Input validation: the developer's request, requirement ids, search queries
    and issue-draft fields are checked before any tool or model sees them.
  - Output validation: secrets are redacted from every tool result and final
    answer, and a final answer that claims "tests passed" or "issue filed"
    without a tool result to back it is withheld (prompt rule 8 enforced in code).
  - Event recording: every guardrail decision is logged (logger
    "inspectra.guardrails") and kept in EVENTS for traces and evaluation.

No model is involved in any of these checks.
"""

from __future__ import annotations

import logging
import os
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("inspectra.guardrails")

# Limits

MAX_REQUEST_CHARS = 2000
MAX_QUERY_CHARS = 500
MAX_TOP_K = 10
MAX_TITLE_CHARS = 200
MAX_SUMMARY_CHARS = 4000
MAX_FAILING_TESTS = 100
MAX_TEST_NAME_CHARS = 300

REQUIREMENT_ID_RE = re.compile(r"^REQ-\d+(?:\.\d+)*$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Event recording

EVENTS: Deque[Dict[str, Any]] = deque(maxlen=1000)


def record(kind: str, **detail: Any) -> Dict[str, Any]:
    """Record one guardrail decision (blocked call, redaction, withheld answer, ...)."""
    event = {"time_utc": datetime.now(timezone.utc).isoformat(), "kind": kind, **detail}
    EVENTS.append(event)
    logger.warning("guardrail %s %s", kind, detail)
    return event

# Input validation

def clean_text(text: str) -> str:
    """Drop control characters (keeps newlines and tabs)."""
    return _CONTROL_CHARS_RE.sub("", text or "")


def validate_request(prompt: Any) -> Tuple[bool, str]:
    """The developer's request: a non-empty string of at most MAX_REQUEST_CHARS."""
    if not isinstance(prompt, str) or not clean_text(prompt).strip():
        return False, "Request is empty."
    if len(prompt) > MAX_REQUEST_CHARS:
        return False, f"Request is longer than {MAX_REQUEST_CHARS} characters."
    return True, "ok"


MAX_INSTRUCTION_CHARS = 500


def check_instruction(instruction: Any) -> Optional[str]:
    """Error message if a refine_tests instruction is empty or too long, else None."""
    if not isinstance(instruction, str) or not clean_text(instruction).strip():
        return "Refinement instruction is empty."
    if len(instruction) > MAX_INSTRUCTION_CHARS:
        return f"Refinement instruction is longer than {MAX_INSTRUCTION_CHARS} characters."
    return None


def check_requirement_id(requirement_id: Any) -> Optional[str]:
    """Error message if requirement_id is not of the form REQ-<n>.<n>, else None."""
    if not isinstance(requirement_id, str) or not REQUIREMENT_ID_RE.match(requirement_id):
        shown = str(requirement_id)[:40]
        return f"Invalid requirement id '{shown}': expected the form REQ-2.1."
    return None


def check_query(query: Any, top_k: Any) -> Optional[str]:
    if not isinstance(query, str) or not query.strip():
        return "Search query is empty."
    if len(query) > MAX_QUERY_CHARS:
        return f"Search query is longer than {MAX_QUERY_CHARS} characters."
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        return f"top_k must be between 1 and {MAX_TOP_K}."
    return None


def check_draft_fields(title: Any, summary: Any, failing_tests: Any) -> Optional[str]:
    if not isinstance(title, str) or not title.strip():
        return "Issue title is empty."
    if len(title) > MAX_TITLE_CHARS:
        return f"Issue title is longer than {MAX_TITLE_CHARS} characters."
    if not isinstance(summary, str) or not summary.strip():
        return "Issue summary is empty."
    if len(summary) > MAX_SUMMARY_CHARS:
        return f"Issue summary is longer than {MAX_SUMMARY_CHARS} characters."
    if not isinstance(failing_tests, (list, tuple)):
        return "failing_tests must be a list of test names."
    if len(failing_tests) > MAX_FAILING_TESTS:
        return f"More than {MAX_FAILING_TESTS} failing tests listed."
    if any(len(str(name)) > MAX_TEST_NAME_CHARS for name in failing_tests):
        return f"A failing test name is longer than {MAX_TEST_NAME_CHARS} characters."
    return None


def single_line(text: str) -> str:
    """Titles go into a Markdown heading and a GitHub issue title: one line only."""
    return " ".join(clean_text(text).split())

# Output validation: secret redaction

SECRET_ENV_VARS = ("GEMINI_API_KEY", "GROQ_API_KEY", "GITHUB_TOKEN", "APPROVAL_SECRET_KEY", "LANGSMITH_API_KEY")
SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),            # Google API keys
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),                # Groq API keys
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),          # GitHub classic tokens
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),        # GitHub fine-grained tokens
    re.compile(r"lsv2_[0-9A-Za-z_]{20,}"),              # LangSmith keys
)
REDACTED = "[REDACTED]"


def redact(text: str) -> Tuple[str, int]:
    """Replace secret values and secret-shaped strings. Returns (text, count)."""
    if not text:
        return text, 0
    count = 0
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name, "")
        if len(value) >= 8 and value in text:
            count += text.count(value)
            text = text.replace(value, REDACTED)
    for pattern in SECRET_PATTERNS:
        text, n = pattern.subn(REDACTED, text)
        count += n
    return text, count

# Output validation: final answer must match the tool results

_NEGATION_RE = re.compile(r"\b(not|no|nothing|never|without|cannot|didn't|wasn't|isn't|won't|n't)\b", re.I)
_PASS_CLAIM_RE = re.compile(r"\b(tests?|everything|all)\b[^.!?\n]*\b(pass(?:ed|es|ing)?|green)\b", re.I)
_FILED_CLAIM_RE = re.compile(
    r"\b(issue[^.!?\n]*\b(filed|created|opened|submitted)|(filed|created|opened|submitted)[^.!?\n]*\bissue)\b",
    re.I,
)


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def check_final_answer(text: str, workflow_state: Dict[str, Any]) -> List[str]:
    """Claims in the final answer that no tool result supports."""
    problems = []
    for sentence in _sentences(text):
        if _NEGATION_RE.search(sentence):
            continue
        if (_PASS_CLAIM_RE.search(sentence) and "fail" not in sentence.lower()
                and workflow_state.get("test_outcome") != "passed"):
            problems.append("claims the tests passed, but no run_tests result says passed")
        if _FILED_CLAIM_RE.search(sentence) and workflow_state.get("stop_reason") != "issue_filed":
            problems.append("claims an issue was filed, but no file_issue result says so")
    return sorted(set(problems))


def verified_summary(workflow_state: Dict[str, Any]) -> str:
    """A truthful replacement answer built only from the recorded workflow state."""
    return (
        f"Verified result for {workflow_state.get('requirement_id') or 'the request'}: "
        f"test outcome {workflow_state.get('test_outcome') or 'not run'}, "
        f"stop reason {workflow_state.get('stop_reason') or 'unknown'}"
        + (f", draft {os.path.basename(workflow_state['draft_path'])}" if workflow_state.get("draft_path") else "")
        + "."
    )
