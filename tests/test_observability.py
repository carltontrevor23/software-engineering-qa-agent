"""
tests/test_observability.py

Unit and behavioral verification for Week 7 observability and tracing.

Verifies that execution traces capture:
  1. Model evidence: model identifier, provider, prompt version.
  2. Prompt evidence: raw user prompt, cleaned prompt, length.
  3. Retrieval evidence: query, top_k, retrieved requirement IDs, scores, source files, previews.
  4. Tool evidence: tool calls, arguments, status codes, output summaries, and approval events.
  5. Latency & Error evidence: timestamps (UTC), durations, error details.
  6. Outcome evidence: final answer text, stop reason, final workflow phase, test results.
"""

import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import tool_calling
tracer = tool_calling.tracer


@pytest.fixture(autouse=True)
def clean_observability(tmp_path, monkeypatch):
    """Ensure in-memory traces and file paths are isolated for each test."""
    tracer.clear_traces()
    temp_trace_file = tmp_path / "test_traces.jsonl"
    monkeypatch.setattr(tracer, "DEFAULT_TRACE_FILE", temp_trace_file)
    yield temp_trace_file
    tracer.clear_traces()


def test_input_rejection_trace_captures_prompt_latency_and_error(clean_observability):
    """Input rejected by guardrails must still produce an observability trace."""
    answer = tool_calling.run("", capture_trace=True)
    assert "[GUARDRAIL] Request rejected" in answer

    traces = tracer.get_recent_traces()
    assert len(traces) == 1
    t = traces[0]

    # Model & Prompt evidence
    assert t["model"]["prompt_version"] == "v2.0"
    assert t["prompt"]["char_count"] == 0

    # Latency & Error evidence
    assert t["latency"]["total_latency_s"] >= 0
    assert len(t["errors"]) == 1
    assert t["errors"][0]["type"] == "input_validation_error"

    # Outcome evidence
    assert t["outcome"]["stop_reason"] == "input_rejected"
    assert t["outcome"]["final_phase"] == "START"

    # File persistence check
    assert clean_observability.exists()
    lines = clean_observability.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["trace_id"] == t["trace_id"]


def test_trace_captures_model_prompt_and_outcome(clean_observability):
    """Standard run must capture model evidence, prompt evidence, and final answer outcome."""
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content="Requirement REQ-2.1 verified.")

    with patch.object(tool_calling, "llm_with_tools", fake_llm):
        answer = tool_calling.run("Check REQ-2.1 against the code", capture_trace=True)

    assert answer == "Requirement REQ-2.1 verified."
    traces = tracer.get_recent_traces()
    assert len(traces) == 1
    t = traces[0]

    assert t["model"]["name"] == "gemini-3.8-flash"
    assert t["model"]["prompt_version"] == "v2.0"
    assert t["prompt"]["user_prompt"] == "Check REQ-2.1 against the code"
    assert t["prompt"]["char_count"] == len("Check REQ-2.1 against the code")
    assert t["outcome"]["final_answer"] == "Requirement REQ-2.1 verified."
    assert t["outcome"]["stop_reason"] == "requirement_not_found"
    assert t["outcome"]["final_phase"] == "DONE"


def test_trace_captures_retrieval_evidence(clean_observability):
    """Executing search_requirements must populate structured retrieval evidence."""
    # Synthesize state where search_requirements was called and returned results
    sample_hits = [
        {
            "requirement_id": "REQ-2.1",
            "source_file": "docs/requirements/subscription.md",
            "score": 6.405,
            "text": "[Feature: User Subscription Tier Upgrader] 5. If the API returns a non-200 HTTP status code, raise a UserNotFoundError.",
        }
    ]
    tool_content = json.dumps({"status": "success", "results": sample_hits})

    call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "search_requirements", "args": {"query": "tier upgrade", "top_k": 3}, "id": "call_1"}],
    )
    res_msg = ToolMessage(content=tool_content, tool_call_id="call_1", name="search_requirements")
    final_msg = AIMessage(content="Resolved REQ-2.1")

    state = {
        "messages": [HumanMessage(content="Find upgrade rules"), call_msg, res_msg, final_msg],
        "hops": 1,
        "phase": "REQUIREMENT_RESOLVED",
        "stop_reason": "all_tests_passed",
        "requirement_id": "REQ-2.1",
    }

    trace = tracer.build_trace(
        prompt="Find upgrade rules",
        final_state=state,
        final_answer="Resolved REQ-2.1",
        start_utc="2026-10-15T12:00:00Z",
        duration_s=1.23,
    )

    # Validate retrieval evidence
    assert len(trace["retrieval"]) == 1
    ret = trace["retrieval"][0]
    assert ret["query"] == "tier upgrade"
    assert ret["count"] == 1
    assert ret["results"][0]["requirement_id"] == "REQ-2.1"
    assert ret["results"][0]["score"] == 6.405
    assert "UserNotFoundError" in ret["results"][0]["text_preview"]

    # Validate tool evidence
    assert trace["tools"]["sequence"] == ["search_requirements"]
    assert len(trace["tools"]["calls"]) == 1
    assert trace["tools"]["calls"][0]["status"] == "success"
    assert "Retrieved 1 requirement chunk(s)" in trace["tools"]["calls"][0]["result_summary"]


def test_trace_captures_tool_failure_and_latency_evidence(clean_observability):
    """Tool failure must populate tool evidence, status, and error logs."""
    call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "propose_tests", "args": {"requirement_id": "REQ-99.9"}, "id": "call_err"}],
    )
    err_content = json.dumps({"status": "error", "error": "Unknown requirement 'REQ-99.9'."})
    res_msg = ToolMessage(content=err_content, tool_call_id="call_err", name="propose_tests")
    final_msg = AIMessage(content="Failed to find requirement.")

    state = {
        "messages": [HumanMessage(content="Check REQ-99.9"), call_msg, res_msg, final_msg],
        "hops": 1,
        "phase": "STOPPED",
        "stop_reason": "requirement_not_found",
        "requirement_id": None,
    }

    trace = tracer.build_trace(
        prompt="Check REQ-99.9",
        final_state=state,
        final_answer="Failed to find requirement.",
        start_utc="2026-10-15T12:05:00Z",
        duration_s=0.85,
    )

    # Tool and error evidence
    assert trace["tools"]["sequence"] == ["propose_tests"]
    assert trace["tools"]["calls"][0]["status"] == "error"
    assert trace["tools"]["calls"][0]["error"] == "Unknown requirement 'REQ-99.9'."
    assert len(trace["errors"]) == 1
    assert trace["errors"][0]["error"] == "Unknown requirement 'REQ-99.9'."

    # Latency evidence
    assert trace["latency"]["total_latency_s"] == 0.85
    assert trace["latency"]["total_hops"] == 1


def test_trace_captures_human_approval_event(clean_observability):
    """High-impact actions intercepted by human approval must record approval decisions."""
    tracer.record_approval_event("file_issue", {"draft_path": "evidence/issues/drafts/test.md"}, "APPROVED")

    call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "file_issue", "args": {"draft_path": "evidence/issues/drafts/test.md"}, "id": "call_app"}],
    )
    res_msg = ToolMessage(
        content=json.dumps({"status": "success", "filed_path": "evidence/issues/filed/test.md"}),
        tool_call_id="call_app",
        name="file_issue",
    )
    state = {
        "messages": [call_msg, res_msg],
        "hops": 2,
        "phase": "DONE",
        "stop_reason": "issue_filed",
        "draft_path": "evidence/issues/drafts/test.md",
    }

    trace = tracer.record_execution_trace(
        prompt="File issue for REQ-2.1",
        final_state=state,
        final_answer="Issue filed successfully.",
        start_utc="2026-10-15T12:10:00Z",
        duration_s=2.5,
    )

    assert len(trace["approvals"]) == 1
    assert trace["approvals"][0]["tool_name"] == "file_issue"
    assert trace["approvals"][0]["decision"] == "APPROVED"
    assert trace["outcome"]["stop_reason"] == "issue_filed"
    assert trace["outcome"]["final_phase"] == "DONE"

