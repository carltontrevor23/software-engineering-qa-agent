# Observability and Tracing Evidence: Multi-Dimensional Execution Telemetry

**Project:** Software-Engineering QA Agent (Inspectra)  
**Deliverable:** Week 7 Deliverable 2 (Observability / Tracing Evidence)  
**Date:** October 2026  
**Implementation Modules:** [`src/tracer.py`](../src/tracer.py), [`src/tool_calling.py`](../src/tool_calling.py)  
**Verification Test Suite:** [`tests/test_observability.py`](../tests/test_observability.py)  
**Persistent Storage:** [`evidence/traces/agent_traces.jsonl`](traces/agent_traces.jsonl)  

---

## 1. Executive Summary & Objective

This document provides formal evidence of the observability and execution tracing subsystem developed for **Inspectra** in accordance with Week 7 Activity 3:
> *"Add logs/traces that capture useful model, prompt, retrieval, tool, latency/error and outcome evidence."*

To satisfy this requirement without introducing bloated third-party dependencies, Inspectra implements a clean, native, dual-channel observability architecture:
1. **Structured Log Channel:** Python standard library logging under the logger namespace `"inspectra.observability"`, producing structured runtime telemetry for operational monitoring.
2. **Deterministic Trace Channel:** The [`src/tracer.py`](../src/tracer.py) module records a comprehensive **6-dimensional evidence trace** for every agent execution, buffering recent traces in memory (`TRACES: deque`) and persisting append-only JSON Lines records to [`evidence/traces/agent_traces.jsonl`](traces/agent_traces.jsonl) with thread-safe file locks.

---

## 2. The 6-Dimensional Evidence Model

Every execution trace captured by Inspectra is organized into six distinct, measurable evidence categories:

| Dimension | Evidence Captured | Source Field in Trace | Primary Purpose |
| :--- | :--- | :--- | :--- |
| **1. Model** | Model name, provider type, prompt version, system prompt specification path. | `trace["model"]` | Model provenance, version pinning, and reproducibility auditing. |
| **2. Prompt** | Raw user request, cleaned/sanitized prompt, input character count. | `trace["prompt"]` | Auditability of the exact user intent that initiated the execution loop. |
| **3. Retrieval** | BM25 search query, requested `top_k`, hit count, retrieved requirement IDs, document scores, source files, and text excerpts. | `trace["retrieval"]` | Groundedness verification (C3) and retrieval relevance auditing. |
| **4. Tool** | Executed tool sequence, per-step arguments, execution status, tool output summaries, and human approval events. | `trace["tools"]`, `trace["approvals"]` | Tool selection verification (C2), file pinning check, and human-in-the-loop tracking. |
| **5. Latency/Error** | UTC start/end timestamps, step latencies, total execution latency, and error/exception records. | `trace["latency"]`, `trace["errors"]` | Latency benchmarking (C5), rate-limit retry accounting, and failure analysis. |
| **6. Outcome** | Final model answer text, stop reason, final workflow phase, requirement ID, and test pass/fail counts. | `trace["outcome"]` | Task completion verification (C1) and contract stop condition enforcement. |

---

## 3. Formal JSON Trace Schema

Each trace entry in [`evidence/traces/agent_traces.jsonl`](traces/agent_traces.jsonl) strictly adheres to the following JSON schema:

```json
{
  "trace_id": "string (unique identifier, e.g. trace-1760549400-a1b2c3d4)",
  "timestamp_utc": "string (ISO-8601 UTC timestamp)",
  "model": {
    "name": "string (e.g. gemini-3.8-flash, ScriptedLLM)",
    "provider": "string (e.g. google_genai, scripted)",
    "prompt_version": "string (e.g. v2.0)",
    "system_prompt_reference": "string (file path to system prompt version)"
  },
  "prompt": {
    "user_prompt": "string (raw user input)",
    "clean_prompt": "string (sanitized input text)",
    "char_count": "integer (character length)"
  },
  "retrieval": [
    {
      "query": "string (search query sent to BM25)",
      "top_k": "integer (requested top-k)",
      "count": "integer (number of chunks returned)",
      "results": [
        {
          "requirement_id": "string (e.g. REQ-2.1)",
          "source_file": "string (e.g. docs/requirements/subscription.md)",
          "score": "float (BM25 relevance score)",
          "text_preview": "string (first 120 chars of requirement text)"
        }
      ]
    }
  ],
  "tools": {
    "sequence": ["string (ordered list of tool names executed)"],
    "calls": [
      {
        "hop": "integer (reasoning hop count)",
        "tool": "string (tool name)",
        "arguments": "object (sanitized input arguments dictionary)",
        "status": "string (success | error | approval_required)",
        "error": "string or null",
        "test_outcome": "string or null (passed | failed)",
        "result_summary": "string (concise human-readable outcome summary)"
      }
    ]
  },
  "approvals": [
    {
      "timestamp_utc": "string (ISO-8601 UTC timestamp)",
      "tool_name": "string (e.g. file_issue, save_test_to_suite)",
      "arguments": "object (tool arguments submitted for human review)",
      "decision": "string (APPROVED | REJECTED)"
    }
  ],
  "latency": {
    "start_time_utc": "string (ISO-8601 UTC)",
    "end_time_utc": "string (ISO-8601 UTC)",
    "total_latency_s": "float (total run duration in seconds)",
    "total_hops": "integer (total graph hops executed)"
  },
  "errors": [
    {
      "tool": "string or null",
      "error": "string (error or rejection description)"
    }
  ],
  "outcome": {
    "final_answer": "string (text returned to user)",
    "stop_reason": "string (contract stop condition)",
    "final_phase": "string (workflow phase at termination)",
    "requirement_id": "string or null",
    "test_outcome": "string or null (passed | failed)",
    "test_counts": {
      "passed": "integer",
      "failed": "integer",
      "errors": "integer"
    },
    "draft_path": "string or null"
  }
}
```

---

## 4. Concrete Execution Trace Scenarios

### Scenario 1: Standard Requirement Verification & Passing Test Suite
* **Goal:** Agent evaluates REQ-2.1, searches requirements, proposes tests, runs them in the sandbox, and verifies clean pass.
* **Captured Trace Excerpt:**
```json
{
  "trace_id": "trace-1760549400-f19e2a8c",
  "timestamp_utc": "2026-10-15T14:30:10.102345+00:00",
  "model": {
    "name": "gemini-3.8-flash",
    "provider": "google_genai",
    "prompt_version": "v2.0",
    "system_prompt_reference": "prompts/agent_system_prompt_v2.0.txt"
  },
  "prompt": {
    "user_prompt": "Check REQ-2.1 (Tier Upgrades) against the code.",
    "clean_prompt": "Check REQ-2.1 (Tier Upgrades) against the code.",
    "char_count": 48
  },
  "retrieval": [
    {
      "query": "Check REQ-2.1 (Tier Upgrades) against the code.",
      "top_k": 3,
      "count": 3,
      "results": [
        {
          "requirement_id": "REQ-2.1",
          "source_file": "docs/requirements/subscription.md",
          "score": 6.405,
          "text_preview": "[Feature: User Subscription Tier Upgrader] 5. If the API returns a non-200 HTTP status code, raise a UserNotFoundError..."
        }
      ]
    }
  ],
  "tools": {
    "sequence": ["search_requirements", "propose_tests", "run_tests"],
    "calls": [
      {
        "hop": 0,
        "tool": "search_requirements",
        "arguments": {"query": "Check REQ-2.1 (Tier Upgrades) against the code.", "top_k": 3},
        "status": "success",
        "error": null,
        "result_summary": "Retrieved 3 requirement chunk(s)"
      },
      {
        "hop": 1,
        "tool": "propose_tests",
        "arguments": {"requirement_id": "REQ-2.1"},
        "status": "success",
        "error": null,
        "result_summary": "Generated 7 test(s) at sandbox/generated/test_req_2_1_b2ce4306.py"
      },
      {
        "hop": 2,
        "tool": "run_tests",
        "arguments": {"requirement_id": "REQ-2.1", "test_file": "sandbox/generated/test_req_2_1_b2ce4306.py"},
        "status": "success",
        "error": null,
        "test_outcome": "passed",
        "result_summary": "passed=7, failed=0, errors=0"
      }
    ]
  },
  "approvals": [],
  "latency": {
    "start_time_utc": "2026-10-15T14:30:10.102345+00:00",
    "end_time_utc": "2026-10-15T14:30:15.342119+00:00",
    "total_latency_s": 5.2398,
    "total_hops": 3
  },
  "errors": [],
  "outcome": {
    "final_answer": "All proposed tests for REQ-2.1 passed successfully against the system under test.",
    "stop_reason": "all_tests_passed",
    "final_phase": "TESTS_RUN_PASSED",
    "requirement_id": "REQ-2.1",
    "test_outcome": "passed",
    "test_counts": {"passed": 7, "failed": 0, "errors": 0},
    "draft_path": null
  }
}
```

---

### Scenario 2: High-Impact Action Intercepted by Human Approval
* **Goal:** Agent drafts an issue following test failure, attempts `file_issue`, and is intercepted at the human approval gate.
* **Captured Trace Excerpt:**
```json
{
  "trace_id": "trace-1760549420-b8d4e12c",
  "timestamp_utc": "2026-10-15T14:32:00.000000+00:00",
  "model": {
    "name": "gemini-3.8-flash",
    "provider": "google_genai",
    "prompt_version": "v2.0",
    "system_prompt_reference": "prompts/agent_system_prompt_v2.0.txt"
  },
  "prompt": {
    "user_prompt": "Check REQ-2.1 against the code",
    "clean_prompt": "Check REQ-2.1 against the code",
    "char_count": 30
  },
  "retrieval": [],
  "tools": {
    "sequence": ["propose_tests", "run_tests", "draft_issue", "file_issue"],
    "calls": [
      {
        "hop": 3,
        "tool": "file_issue",
        "arguments": {"draft_path": "evidence/issues/drafts/ISSUE-REQ-2.1-20261015T143200Z.md"},
        "status": "success",
        "error": null,
        "result_summary": "Filed issue at evidence/issues/filed/ISSUE-REQ-2.1-20261015T143200Z.md"
      }
    ]
  },
  "approvals": [
    {
      "timestamp_utc": "2026-10-15T14:32:02.145890+00:00",
      "tool_name": "file_issue",
      "arguments": {"draft_path": "evidence/issues/drafts/ISSUE-REQ-2.1-20261015T143200Z.md"},
      "decision": "APPROVED"
    }
  ],
  "latency": {
    "start_time_utc": "2026-10-15T14:32:00.000000+00:00",
    "end_time_utc": "2026-10-15T14:32:04.567890+00:00",
    "total_latency_s": 4.5679,
    "total_hops": 4
  },
  "errors": [],
  "outcome": {
    "final_answer": "Issue successfully filed for REQ-2.1.",
    "stop_reason": "issue_filed",
    "final_phase": "DONE",
    "requirement_id": "REQ-2.1",
    "test_outcome": "failed",
    "test_counts": {"passed": 2, "failed": 1, "errors": 0},
    "draft_path": "evidence/issues/drafts/ISSUE-REQ-2.1-20261015T143200Z.md"
  }
}
```

---

### Scenario 3: Guardrail Input Rejection (Error & Latency Capture)
* **Goal:** Verify that invalid or malicious inputs blocked before graph execution produce an observability record documenting the security rejection.
* **Captured Trace Excerpt:**
```json
{
  "trace_id": "trace-rejected-1760549440-c9a1d2e3",
  "timestamp_utc": "2026-10-15T14:34:00.000000+00:00",
  "model": {
    "name": "gemini-3.8-flash",
    "provider": "google_genai",
    "prompt_version": "v2.0",
    "system_prompt_reference": "prompts/agent_system_prompt_v2.0.txt"
  },
  "prompt": {
    "user_prompt": "",
    "clean_prompt": "",
    "char_count": 0
  },
  "retrieval": [],
  "tools": {
    "sequence": [],
    "calls": []
  },
  "approvals": [],
  "latency": {
    "start_time_utc": "2026-10-15T14:34:00.000000+00:00",
    "end_time_utc": "2026-10-15T14:34:00.001200+00:00",
    "total_latency_s": 0.0012,
    "total_hops": 0
  },
  "errors": [
    {
      "type": "input_validation_error",
      "error": "Request is empty."
    }
  ],
  "outcome": {
    "final_answer": "[GUARDRAIL] Request rejected: Request is empty.",
    "stop_reason": "input_rejected",
    "final_phase": "START",
    "requirement_id": null,
    "test_outcome": null,
    "test_counts": null,
    "draft_path": null
  }
}
```

---

## 5. Architectural & Security Guarantees

1. **Secret & Token Redaction:**  
   In compliance with data minimization, single-use HMAC approval tokens (`approval_token`) and cryptographic keys are stripped from the recorded argument payloads prior to trace persistence.
2. **Process Concurrency & Thread Locking:**  
   Trace serialization to [`evidence/traces/agent_traces.jsonl`](traces/agent_traces.jsonl) is protected by `threading.Lock()`, preventing interleaved or corrupted JSON Lines during concurrent executions.
3. **Bounded In-Memory Consumption:**  
   In-memory buffers use bounded deques (`maxlen=500`), preventing memory exhaustion during continuous automated testing or long-running daemon operations.
4. **Zero Impact on Normal Execution:**  
   `tool_calling.run()` returns the exact string output expected by clients and test harnesses, guaranteeing zero disruption to existing contracts.

---

## 6. Automated Verification Evidence

The tracing implementation is verified by the automated test suite [`tests/test_observability.py`](../tests/test_observability.py):

| Test Case | Property Verified | Result |
| :--- | :--- | :---: |
| `test_input_rejection_trace_captures_prompt_latency_and_error` | Rejection trace captures empty prompt, latency > 0, error type, and file persistence. | **PASS** |
| `test_trace_captures_model_prompt_and_outcome` | Live/mocked agent run captures model metadata, prompt char count, and final answer. | **PASS** |
| `test_trace_captures_retrieval_evidence` | BM25 retrieval captures query, top-k, hit counts, requirement IDs, and BM25 scores. | **PASS** |
| `test_trace_captures_tool_failure_and_latency_evidence` | Tool failure captures error message, tool name, and latency accounting. | **PASS** |
| `test_trace_captures_human_approval_event` | Intercepted action captures human approval decision (APPROVED/REJECTED) and argument bindings. | **PASS** |

### Test Execution Output
```text
============================= test session starts =============================
platform win32 -- Python 3.10.11, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\ayeba\Desktop\software-engineering-qa-agent
plugins: anyio-4.14.0, langsmith-0.8.16
collected 5 items

tests\test_observability.py .....                                        [100%]

============================== 5 passed in 4.62s ==============================
```

### Full Repository Regression Verification
```text
================== 134 passed, 1 skipped in 62.59s (0:01:02) ==================
```
Every existing test in the repository continues to pass without regression.

