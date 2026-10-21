# Week 8 Pre-Presentation Hardening: Critical Defect Fixes & Known Limitations Evidence

**Project:** Software-Engineering QA Agent (Inspectra)  
**Course:** BSE4104 AI-Native & Agentic Engineering Capstone  
**Activity:** Fix critical defects; document known limitations that remain  
**Date:** 2026-10-21  
**Target Modules:** [`src/tool_calling.py`](../src/tool_calling.py), [`src/sandbox.py`](../src/sandbox.py), [`src/guardrails.py`](../src/guardrails.py), [`src/tracer.py`](../src/tracer.py), [`src/model_client.py`](../src/model_client.py), [`src/mcp_server.py`](../src/mcp_server.py), [`tests/conftest.py`](../tests/conftest.py), [`README.md`](../README.md)

---

## 1. Executive Summary

In preparation for the final Week 8 presentation, a full-system audit and dry-run verification were conducted across Inspectra's orchestration loop, sandboxed test runner, deterministic guardrails, observability tracer, MCP server, and offline/live demo entry points.

Six critical defects affecting stop-reason accuracy, AST sandbox security, pytest collection-error classification, secret redaction in traces/MCP outputs, offline import resilience, and guardrail type safety were identified and fixed in [`src/`](../src/). In addition, seven remaining architectural and operational limitations have been formally documented in both [`README.md`](../README.md) and Section 3 of this evidence report so evaluators have a transparent boundary specification.

---

## 2. Critical Defects Fixed

| ID | Component | Defect Summary | Root Cause | Fix Implemented | Verification Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DEF-01** | [`src/tool_calling.py`](../src/tool_calling.py) | **Stop-reason mislabelling on refused tool calls (`EV-08`, `EV-18`, `EV-20`, `EV-41`)** | When `execute_tools()` refused a call via the allow-list or `workflow.check_call()`, `wf["phase"]` stayed unchanged and `wf["stop_reason"]` remained `None`. When `assistant()` later called `workflow.finalize_on_answer(wf)`, the run was misclassified as `requirement_not_found`, `unclassified`, or `test_defect_reported` instead of `tool_error`. | Set `wf["stop_reason"] = "tool_error"` and log `guardrails.record("tool_call_blocked", ...)` when a tool call is refused by the allow-list or `workflow.check_call()`; reset `wf["stop_reason"] = None` before applying results of subsequent valid tool calls. | Refused calls in `START`, `REQUIREMENT_RESOLVED`, `TESTS_PROPOSED`, and `TESTS_RUN_FAILED` now finalize with `stop_reason = "tool_error"` while preserving current phase invariants. |
| **DEF-02** | [`src/sandbox.py`](../src/sandbox.py) | **AST sandbox bypass via `from os import ...`, `from requests import ...`, and `Path.open("w")`** | `validate_generated_code()` checked `ast.ImportFrom` only at the root module level (`os` and `requests` are allow-listed) and checked mutating calls only on `ast.Attribute` (`os.system`, `requests.post`) and bare `ast.Name(id="open")`. Direct symbol imports (`from os import system`, `from requests import post`), `requests.request`/`Session`, and `Path(...).open("w")` bypassed validation. | Extended `validate_generated_code()` to inspect imported symbol names on `ast.ImportFrom` for `os`, `requests`, and `BANNED_MUTATING_CALLS`, added `request`/`Session`/`session` to `BANNED_REQUESTS_CALLS`, and checked `ast.Attribute(attr="open")` for write/append file modes (`"w"`, `"a"`, `"x"`, `"+"`). | Direct imports of `os.system`, `requests.post`, `requests.Session`, and `Path.open("w")` are deterministically rejected before any file is written or executed. |
| **DEF-03** | [`src/sandbox.py`](../src/sandbox.py) | **Negative `passed` count and false `no_tests` outcome on pytest collection errors** | `_parse_junit()` calculated `passed = total - failed - errors - skipped`. When pytest failed during collection (e.g., `ImportError` on an unimplemented class), JUnit XML reported `tests="0" errors="1"`, yielding `passed = -1` and `passed + failed + errors == 0`, which `run_pytest()` misclassified as `test_outcome = "no_tests"`. | Clamped `passed = max(0, total - failed - errors - skipped)` in `_parse_junit()` and checked `if counts["failed"] or counts["errors"]: outcome = "failed"` before checking for `no_tests` in `run_pytest()`. | Collection-time errors now report `passed = 0, errors = 1, test_outcome = "failed"`. |
| **DEF-04** | [`src/tracer.py`](../src/tracer.py), [`src/model_client.py`](../src/model_client.py), [`src/mcp_server.py`](../src/mcp_server.py), [`tests/conftest.py`](../tests/conftest.py) | **Unredacted secrets in JSONL traces, model call logs, and MCP responses (`EV-21`) + test trace pollution** | `tracer.py`, `model_client._log_call()`, and `mcp_server._call()` wrote or returned strings without calling `guardrails.redact()`. Additionally, `tests/conftest.py` did not redirect `tracer.DEFAULT_TRACE_FILE`, causing `pytest` runs to append test records to `evidence/traces/agent_traces.jsonl`. | Added recursive `guardrails.redact()` sanitization (and stripped `approval_token`) in `tracer.py`, `model_client._log_call()`, and `mcp_server._call()`; isolated `tracer.DEFAULT_TRACE_FILE` to `tmp_path` in `tests/conftest.py`. | Planted API keys and GitHub tokens are redacted (`[REDACTED]`) across all trace files and MCP responses; `pytest` leaves `evidence/traces/agent_traces.jsonl` untouched. |
| **DEF-05** | [`src/model_client.py`](../src/model_client.py), [`src/tool_calling.py`](../src/tool_calling.py) | **Import-time crash when `GEMINI_API_KEY` is unset & unhandled graph exception in `tool_calling.run()`** | `model_client.py` raised `RuntimeError` at module import time when `GEMINI_API_KEY` was missing, breaking `--offline` rehearsals and `pytest` on fresh clones. In `tool_calling.run()`, `graph.invoke(state)` was unguarded, so live LLM failures after retries crashed with a raw traceback without recording a trace. | Deferred `GEMINI_API_KEY` enforcement to `get_model_response()` (raising `ModelCallError`), passed an offline placeholder key to `ChatGoogleGenerativeAI` when unset, and wrapped `graph.invoke(state)` in `tool_calling.run()` in a `try...except Exception` block that records a `tool_error` trace and returns a clean `[ERROR]` message. | Offline demo and `pytest` import cleanly without `.env`; unhandled model exceptions in `run()` terminate gracefully with `stop_reason = "tool_error"` and a persisted trace. |
| **DEF-06** | [`src/guardrails.py`](../src/guardrails.py) | **Unhandled `TypeError` in `check_draft_fields()` and boolean `top_k` bypass in `check_query()`** | `check_draft_fields()` called `len(failing_tests)` without verifying `isinstance(failing_tests, (list, tuple))`, raising `TypeError` on `None` or non-iterable inputs. `check_query()` accepted `top_k = True` because `bool` is a subclass of `int` in Python. | Added `isinstance(failing_tests, (list, tuple))` validation in `check_draft_fields()` and explicitly rejected `isinstance(top_k, bool)` in `check_query()`. | Invalid `failing_tests` and boolean `top_k` inputs return structured `{"status": "error", ...}` responses instead of raising unhandled exceptions. |

---

## 3. Known Limitations That Remain

The following limitations are intentional scope boundaries or architectural trade-offs documented for the final presentation and report:

### 3.1 Single-Module SUT Scope & Partial Corpus Implementation (`sut/`, `src/qa_tools.py`)
- **Limitation:** `propose_tests` constructs its prompt from a single hardcoded module (`sut/subscription_service/subscription_manager.py`). Furthermore, while `docs/requirements/` defines six requirements (`REQ-2.1` through `REQ-2.6`), only `REQ-2.1` (Tier Upgrades) is implemented in `subscription_manager.py`.
- **Impact:** Inspectra cannot dynamically discover or test multi-file/multi-package repositories without configuration changes. Running the live agent on `REQ-2.2`–`REQ-2.6` tests missing-feature handling (`EV-17`), where generated tests fail or the model refuses with `NO_GROUNDED_TESTS_FOUND`.
- **Mitigation / Future Work:** Parameterize `SUT_MODULE` via a project manifest or AST symbol index so `propose_tests` can resolve target modules dynamically per requirement.

### 3.2 Static Fixture Scope in `--offline` Rehearsal Mode (`demo/run_demo.py`, `src/demo_support.py`)
- **Limitation:** When `--offline` is passed, `demo_support.fixture_model_reply()` always returns the hand-written `REQ-2.1` boundary tests from `demo/fixtures/req_2_1_tests.py`.
- **Impact:** Offline mode faithfully exercises the full LangGraph control loop, sandbox, memory advisory, and human approval gate for `REQ-2.1` (with or without `--planted-bug`), but is not a general offline test generator for `REQ-2.2`–`REQ-2.6`.
- **Mitigation / Future Work:** Clearly labels every offline output line with `[SCRIPTED LLM]` so evaluators never mistake scripted rehearsal output for live model generation.

### 3.3 Process-Level Sandbox Rather Than OS Containerization (`src/sandbox.py`)
- **Limitation:** `run_pytest()` isolates test execution using a separate Python subprocess (`shell=False`, `TEST_TIMEOUT_SECONDS = 60`, scrubbed `ENV_ALLOW_LIST`, and static AST validation in `validate_generated_code()`), rather than an OS container (Docker, namespaces, or seccomp).
- **Impact:** While static AST checks block dangerous imports (`subprocess`, `socket`, `shutil`, `urllib`, `http`), dynamic execution (`eval`, `exec`, `__import__`), filesystem mutations (`Path.write_text`, `unlink`, write-mode `open()`), and outbound network mutations (`requests.post`/`put`/`delete`/`patch`/`request`/`Session`), a generated test still runs with the host user's filesystem read permissions and can consume CPU/RAM for up to 60 seconds.
- **Mitigation / Future Work:** Run `pytest` inside an ephemeral, read-only, network-disabled Docker container (`--network none --read-only --tmpfs /tmp`).

### 3.4 Lexical BM25 Retrieval Without Semantic Reranking (`src/rag.py`)
- **Limitation:** Requirement retrieval uses pure-Python Okapi BM25 over Markdown chunks (`docs/requirements/`).
- **Impact:** While BM25 excels at exact technical identifiers (`InactiveUserError`, `50.00`, `REQ-2.1`), natural-language queries that paraphrase concepts without overlapping vocabulary can score below `min_score = 1.0` and return `NO_RELEVANT_REQUIREMENTS_FOUND`.
- **Mitigation / Future Work:** Combine BM25 with lightweight dense embeddings (hybrid reciprocal rank fusion) while keeping deterministic citation provenance.

### 3.5 Pattern-Based Output Guardrail & Test Oracle Sufficiency (`src/guardrails.py`)
- **Limitation:** `check_final_answer()` uses regular expressions (`_PASS_CLAIM_RE`, `_FILED_CLAIM_RE`, `_NEGATION_RE`) to catch unsupported claims that tests passed or an issue was filed. Additionally, `run_tests` checks whether generated tests pass against the SUT, not whether the generated assertions are semantically complete.
- **Impact:** Unusual phrasing of an unsupported claim could evade regex matching, and a tautological generated test (`assert True`) would report `test_outcome = "passed"`.
- **Mitigation / Future Work:** Human-in-the-loop review (`approval.py`) gates all repository modifications (`save_test_to_suite`) and external issue creation (`file_issue`), and `propose_tests` logs every generated file for inspection.

### 3.6 Single-Session MCP State & Single-Process Concurrency (`src/mcp_server.py`, `src/memory.py`, `src/approval.py`)
- **Limitation:**
  - `src/mcp_server.py` stores one shared `_session` workflow dictionary in memory on `127.0.0.1:8000` with no client authentication.
  - `src/approval.py` stores consumed token nonces (`_CONSUMED_NONCES`) in RAM per process.
  - `src/memory.py` uses a `threading.Lock` (which synchronizes threads within a single process, not separate OS processes) and requires `purge_expired_records()` to be invoked explicitly.
- **Impact:** Suitable for local single-developer CLI and IDE workflows, but not concurrent multi-user server deployments.
- **Mitigation / Future Work:** Scope MCP workflow state by `session_id`, persist consumed nonces and case history in SQLite with WAL locking, and run retention purging automatically on startup.

### 3.7 Free-Tier Gemini Quota & Rate-Limit Latency (`src/model_client.py`, `src/tool_calling.py`)
- **Limitation:** The default free-tier Gemini API (`gemini-3.8-flash`) enforces strict daily (~20 RPD) and per-minute rate limits. One live end-to-end agent run consumes 3–6 model calls.
- **Impact:** Running multiple live scenarios back-to-back can trigger `429 RESOURCE_EXHAUSTED` or `503` responses, incurring 32–65 second retry pauses or exhausting daily quota.
- **Mitigation / Future Work:** Budget live API calls during the presentation and keep `--offline` mode ready as an instant, zero-quota fallback.

---

## 4. Verification & Re-Test Evidence

### 4.1 Direct Defect Remediation Checks

```text
[DEF-01] Unknown tool in START -> final_phase=DONE, stop_reason=tool_error
[DEF-01] Blocked tool in REQUIREMENT_RESOLVED (EV-20) -> final_phase=DONE, stop_reason=tool_error
[DEF-01] Unpinned file in TESTS_PROPOSED (EV-18) -> final_phase=DONE, stop_reason=tool_error
[DEF-02] 'from os import system' -> ok=False, reason="Use of 'os.system' is not allowed."
[DEF-02] 'from requests import post' -> ok=False, reason="Use of 'requests.post' is not allowed in generated tests."
[DEF-02] 'Path.open("w")' -> ok=False, reason="Opening files in write or append mode is not allowed in generated tests."
[DEF-03] Collection error JUnit (tests=0, errors=1) -> passed=0, errors=1, test_outcome=failed
[DEF-04] Secret redaction in tracer & MCP -> prompt="[REDACTED]", mcp_text="[REDACTED]"
[DEF-05] Unhandled LLM failure in tool_calling.run() -> returns "[ERROR] Model or graph execution failed: ...", trace stop_reason=tool_error
[DEF-06] check_draft_fields(failing_tests=None) -> "failing_tests must be a list of test names."
[DEF-06] check_query(top_k=True) -> "top_k must be between 1 and 10."
```

### 4.2 Full Test Suite Execution (`pytest tests/ sut/tests/ -v`)

All **150 automated tests pass** (with zero new test functions added, preserving the existing suite structure) and `evidence/traces/agent_traces.jsonl` remains clean after test execution:

```text
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\PC 12\Desktop\QA_agent\software-engineering-qa-agent
configfile: pytest.ini
collected 150 items / 1 skipped

tests/test_agent_contract.py (27 passed)
tests/test_failure_remediation.py (10 passed)
tests/test_guardrails_io.py (47 passed)
tests/test_mcp_server.py (1 skipped - optional mcp runtime in external venv)
tests/test_memory.py (10 passed)
tests/test_memory_behavior.py (5 passed)
tests/test_observability.py (5 passed)
tests/test_rag.py (8 passed)
tests/test_tool_failures.py (32 passed)
sut/tests/test_subscription_manager.py (6 passed)

============ 150 passed, 1 skipped in 84.19s (0:01:24) =============
```
