"""
src/tracer.py

Observability, logging, and execution tracing for Inspectra (Week 7).

Captures structured evidence for every agent execution:
  1. Model evidence: model identifier, provider, prompt version.
  2. Prompt evidence: raw user prompt, cleaned prompt, length.
  3. Retrieval evidence: query, top_k, retrieved requirement IDs, scores, source files, previews.
  4. Tool evidence: tool calls, arguments, status codes, output summaries, and approval events.
  5. Latency & Error evidence: timestamps (UTC), step/total durations, error details.
  6. Outcome evidence: final answer text, stop reason, final workflow phase, test results.

Outputs:
  - Structured logs via logger "inspectra.observability"
  - In-memory event buffer in TRACES (for inspection and tests)
  - Append-only JSONL trace logs at evidence/traces/agent_traces.jsonl
"""

from __future__ import annotations

import ast
from collections import deque
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Deque, Dict, List, Optional
import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import guardrails

logger = logging.getLogger("inspectra.observability")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = PROJECT_ROOT / "evidence" / "traces"
DEFAULT_TRACE_FILE = TRACES_DIR / "agent_traces.jsonl"

_LOCK = threading.Lock()

# In-memory buffer of recent execution traces (for assertions and evaluation inspection)
TRACES: Deque[Dict[str, Any]] = deque(maxlen=500)
# In-memory buffer of human approval decisions recorded during active runs
_APPROVAL_EVENTS: List[Dict[str, Any]] = []


def _redact_value(value: Any) -> Any:
    """Recursively redact secrets and remove approval_token from traced values."""
    if isinstance(value, str):
        redacted, _ = guardrails.redact(value)
        return redacted
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items() if k != "approval_token"}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def record_approval_event(tool_name: str, args: Dict[str, Any], decision: str) -> Dict[str, Any]:
    """Record one human approval decision (APPROVED / REJECTED) for high-impact actions."""
    clean_args = _redact_value({k: v for k, v in args.items() if k != "approval_token"})
    event = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "tool_name": tool_name,
        "arguments": clean_args,
        "decision": decision,
    }
    _APPROVAL_EVENTS.append(event)
    logger.info("Human approval recorded: tool=%s decision=%s", tool_name, decision)
    return event


def clear_traces() -> None:
    """Clear in-memory trace buffers (primarily for test teardown)."""
    with _LOCK:
        TRACES.clear()
        _APPROVAL_EVENTS.clear()


def get_recent_traces(limit: int = 10) -> List[Dict[str, Any]]:
    """Return the most recent execution traces from memory."""
    with _LOCK:
        items = list(TRACES)
    return items[-limit:] if limit > 0 else items


def _parse_payload(content: Any) -> Any:
    """Attempt to parse dictionary or structured JSON from a tool message content."""
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return str(content)
    # Try JSON parsing
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try Python AST literal
    try:
        parsed = ast.literal_eval(content)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass
    return content


def _summarize_tool_result(tool_name: str, status: str, parsed: Any) -> str:
    """Produce a concise human-readable summary of a tool outcome."""
    if not isinstance(parsed, dict):
        text = str(parsed)
        return text[:120] + "..." if len(text) > 120 else text

    if tool_name == "search_requirements":
        hits = parsed.get("results") or []
        return f"Retrieved {len(hits)} requirement chunk(s)"
    if tool_name == "propose_tests":
        count = parsed.get("test_count", 0)
        file_path = parsed.get("test_file", "unknown")
        return f"Generated {count} test(s) at {file_path}"
    if tool_name == "run_tests":
        passed = parsed.get("passed", 0)
        failed = parsed.get("failed", 0)
        errors = parsed.get("errors", 0)
        return f"passed={passed}, failed={failed}, errors={errors}"
    if tool_name == "draft_issue":
        return f"Drafted issue at {parsed.get('draft_path')}"
    if tool_name == "file_issue":
        return f"Filed issue at {parsed.get('filed_path')}"
    if tool_name == "save_test_to_suite":
        return f"Saved test to {parsed.get('saved_path')}"

    return f"status={status}"


def build_trace(
    prompt: str,
    final_state: Dict[str, Any],
    final_answer: str,
    start_utc: str,
    duration_s: float,
    model_name: str = "gemini-3.8-flash",
    prompt_version: str = "v2.0",
    errors: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Construct a complete, structured 6-category execution trace."""
    end_utc = datetime.now(timezone.utc).isoformat()
    trace_id = f"trace-{int(time.time())}-{uuid.uuid4().hex[:8]}"

    # 1. Model evidence
    model_evidence = {
        "name": model_name,
        "provider": "google_genai" if "gemini" in model_name.lower() else "scripted",
        "prompt_version": prompt_version,
        "system_prompt_reference": f"prompts/agent_system_prompt_{prompt_version}.txt",
    }

    # 2. Prompt evidence (redacted for secrets)
    safe_prompt = _redact_value(prompt) if isinstance(prompt, str) else ""
    prompt_evidence = {
        "user_prompt": safe_prompt,
        "clean_prompt": safe_prompt.strip() if isinstance(safe_prompt, str) else "",
        "char_count": len(prompt) if isinstance(prompt, str) else 0,
    }

    # 3. Extract tool calls and retrieval evidence from conversation messages
    messages = final_state.get("messages", [])
    tool_sequence: List[str] = []
    tool_calls_evidence: List[Dict[str, Any]] = []
    retrieval_evidence: List[Dict[str, Any]] = []
    captured_errors: List[Dict[str, str]] = _redact_value(list(errors or []))

    # Map AI tool_calls to subsequent ToolMessages
    pending_calls: Dict[str, Dict[str, Any]] = {}
    hop_counter = 0

    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tc_id = tc.get("id") or str(uuid.uuid4())
                pending_calls[tc_id] = {
                    "hop": hop_counter,
                    "tool": tc.get("name"),
                    "args": tc.get("args", {}),
                }
        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            call_info = pending_calls.pop(tc_id, {"hop": hop_counter, "tool": msg.name, "args": {}})
            tool_name = msg.name or call_info.get("tool", "unknown")
            tool_args = _redact_value(call_info.get("args", {}))
            parsed = _parse_payload(msg.content)
            status = parsed.get("status", "unknown") if isinstance(parsed, dict) else "unknown"
            err_msg = _redact_value(parsed.get("error")) if isinstance(parsed, dict) else None

            tool_sequence.append(tool_name)
            tool_record = {
                "hop": call_info.get("hop", hop_counter),
                "tool": tool_name,
                "arguments": tool_args,
                "status": status,
                "error": err_msg,
                "test_outcome": parsed.get("test_outcome") if isinstance(parsed, dict) else None,
                "result_summary": _redact_value(_summarize_tool_result(tool_name, status, parsed)),
            }
            tool_calls_evidence.append(tool_record)

            if status == "error" or err_msg:
                captured_errors.append({"tool": tool_name, "error": str(err_msg)})

            # Extract retrieval evidence if search_requirements was called
            if tool_name == "search_requirements" and isinstance(parsed, dict):
                hits = parsed.get("results") or []
                retrieval_evidence.append({
                    "query": tool_args.get("query", ""),
                    "top_k": tool_args.get("top_k", len(hits)),
                    "count": len(hits),
                    "results": [
                        {
                            "requirement_id": h.get("requirement_id"),
                            "source_file": h.get("source_file"),
                            "score": h.get("score"),
                            "text_preview": _redact_value(
                                (h.get("text", "")[:120] + "...")
                                if len(h.get("text", "")) > 120
                                else h.get("text", "")
                            ),
                        }
                        for h in hits
                    ],
                })
            hop_counter += 1

    # 4. Approvals
    global _APPROVAL_EVENTS
    approvals_captured = list(_APPROVAL_EVENTS)
    _APPROVAL_EVENTS = []

    # 5. Latency and errors
    latency_evidence = {
        "start_time_utc": start_utc,
        "end_time_utc": end_utc,
        "total_latency_s": round(duration_s, 4),
        "total_hops": final_state.get("hops", hop_counter),
    }

    # 6. Outcome evidence
    test_counts = None
    if final_state.get("test_outcome"):
        # Look for run_tests tool record for counts
        for tr in tool_calls_evidence:
            if tr["tool"] == "run_tests":
                # Extracted from tool result
                parsed_res = [m for m in messages if isinstance(m, ToolMessage) and m.name == "run_tests"]
                if parsed_res:
                    res_dict = _parse_payload(parsed_res[-1].content)
                    if isinstance(res_dict, dict):
                        test_counts = {
                            "passed": res_dict.get("passed", 0),
                            "failed": res_dict.get("failed", 0),
                            "errors": res_dict.get("errors", 0),
                        }
                break

    outcome_evidence = {
        "final_answer": _redact_value(final_answer),
        "stop_reason": final_state.get("stop_reason", "unclassified"),
        "final_phase": final_state.get("phase", "START"),
        "requirement_id": final_state.get("requirement_id"),
        "test_outcome": final_state.get("test_outcome"),
        "test_counts": test_counts,
        "draft_path": final_state.get("draft_path"),
    }

    trace = {
        "trace_id": trace_id,
        "timestamp_utc": start_utc,
        "model": model_evidence,
        "prompt": prompt_evidence,
        "retrieval": retrieval_evidence,
        "tools": {
            "sequence": tool_sequence,
            "calls": tool_calls_evidence,
        },
        "approvals": approvals_captured,
        "latency": latency_evidence,
        "errors": captured_errors,
        "outcome": outcome_evidence,
    }

    return trace


def record_execution_trace(
    prompt: str,
    final_state: Dict[str, Any],
    final_answer: str,
    start_utc: str,
    duration_s: float,
    model_name: str = "gemini-3.8-flash",
    prompt_version: str = "v2.0",
    errors: Optional[List[Dict[str, str]]] = None,
    filepath: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build, buffer, log, and write an execution trace to JSONL."""
    trace = build_trace(
        prompt=prompt,
        final_state=final_state,
        final_answer=final_answer,
        start_utc=start_utc,
        duration_s=duration_s,
        model_name=model_name,
        prompt_version=prompt_version,
        errors=errors,
    )

    # Buffer in-memory
    with _LOCK:
        TRACES.append(trace)

    # Structured log
    logger.info(
        "Agent execution completed: trace_id=%s stop_reason=%s phase=%s tools=%s latency=%.2fs",
        trace["trace_id"],
        trace["outcome"]["stop_reason"],
        trace["outcome"]["final_phase"],
        trace["tools"]["sequence"],
        duration_s,
    )

    # Persist to JSONL file
    target_file = filepath or DEFAULT_TRACE_FILE
    save_trace_to_file(trace, target_file)

    return trace


def record_input_rejection_trace(
    prompt: Any,
    error_message: str,
    start_utc: str,
    duration_s: float,
    model_name: str = "gemini-3.8-flash",
    prompt_version: str = "v2.0",
    filepath: Optional[Path] = None,
) -> Dict[str, Any]:
    """Capture an observability trace when a request is rejected by input guardrails."""
    end_utc = datetime.now(timezone.utc).isoformat()
    trace_id = f"trace-rejected-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    raw_prompt = str(prompt) if prompt is not None else ""
    safe_prompt = _redact_value(raw_prompt)
    safe_error = _redact_value(error_message)

    trace = {
        "trace_id": trace_id,
        "timestamp_utc": start_utc,
        "model": {
            "name": model_name,
            "provider": "google_genai" if "gemini" in model_name.lower() else "scripted",
            "prompt_version": prompt_version,
            "system_prompt_reference": f"prompts/agent_system_prompt_{prompt_version}.txt",
        },
        "prompt": {
            "user_prompt": safe_prompt,
            "clean_prompt": safe_prompt.strip(),
            "char_count": len(raw_prompt),
        },
        "retrieval": [],
        "tools": {
            "sequence": [],
            "calls": [],
        },
        "approvals": [],
        "latency": {
            "start_time_utc": start_utc,
            "end_time_utc": end_utc,
            "total_latency_s": round(duration_s, 4),
            "total_hops": 0,
        },
        "errors": [{"type": "input_validation_error", "error": safe_error}],
        "outcome": {
            "final_answer": f"[GUARDRAIL] Request rejected: {safe_error}",
            "stop_reason": "input_rejected",
            "final_phase": "START",
            "requirement_id": None,
            "test_outcome": None,
            "test_counts": None,
            "draft_path": None,
        },
    }

    with _LOCK:
        TRACES.append(trace)

    logger.warning("Agent request rejected before model execution: %s", safe_error)

    target_file = filepath or DEFAULT_TRACE_FILE
    save_trace_to_file(trace, target_file)

    return trace


def save_trace_to_file(trace: Dict[str, Any], filepath: Path) -> None:
    """Safely append a single JSONL trace record to disk under thread lock."""
    with _LOCK:
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace) + "\n")
        except Exception as e:
            logger.error("Failed to write trace to %s: %s", filepath, e)
