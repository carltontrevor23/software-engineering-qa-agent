# Memory Design and Data Handling Note — Week 6 (realigned)

**Project:** Software-Engineering QA Agent (Inspectra)
**Code:** [`src/memory.py`](../../src/memory.py); used in `post_call()` and `approval_description()` in
[`src/guard_middleware.py`](../../src/guard_middleware.py) (and `tool_runner.py` for the MCP server)
**Tests:** [`tests/test_memory.py`](../../tests/test_memory.py), [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py)
**Evidence:** [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md)

This replaces the earlier note, which described a customer case history keyed by `user_id`. The
old version is in git history.

## 1. The use case: requirement test-run history

Inspectra keeps one persistent memory: **the history of test runs per requirement** (for example
`REQ-2.1`).

**Why it is justified.** When tests fail, the human must decide whether to file an issue. A single
failing run is ambiguous: it may be a real regression, or a flaky or incorrect *generated* test.
Knowing how earlier runs for the same requirement went makes that decision better:
- previously passing and now failing → a likely regression, or a wrong new test;
- failing again and again → a stable defect worth filing.

The current run cannot provide that information; only memory can.

**What it does.** Before `file_issue` or `save_test_to_suite`, the approval prompt shows the last
three `run_tests` outcomes and a deterministic advisory:

```
[CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed) 2026-10-11; run_tests -> failed (1 failed) 2026-10-11; run_tests -> passed 2026-10-11
[ADVISORY] RECURRING: failed in 2 of the last 3 runs. (advisory only - the decision is yours)
 Authorize this action? [y/N]:
```

| Advisory | Rule (from the last 3 `run_tests` records, newest first) |
|---|---|
| `RECURRING: failed in N of the last M runs.` | Newest run failed and at least 2 runs failed |
| `FIRST FAILURE: previously passing (possible regression or flaky/incorrect generated test).` | Newest run failed, earlier runs passed |
| `FIRST RUN: no earlier test runs to compare with.` | Only one run on record |
| `LATEST RUN PASSED: ...` | Newest run passed |
| `NO HISTORY: ...` | No runs on record |

## 2. It does not silently control decisions

- **Advisory only.** History never approves or rejects anything. The human still answers `y/N`, and
  a fresh signed single-use token is still required
  (`test_history_full_of_approvals_cannot_bypass_file_issue_gate`).
- **Never sent to the LLM.** It is printed to the console only. It is not added to `messages`,
  `ToolMessage` content or any state field (`test_case_history_never_reaches_llm_or_token`).
- **Not part of the token.** The approval token hashes only the tool's own arguments
  (`{"draft_path": ...}`), checked in the same guard test.
- **Deterministic.** The advisory is computed by code from stored outcomes; no model is involved.

## 3. What is stored, and what is not

Format: JSON Lines, one record per executed tool call, at `data/memory/case_history.jsonl`.

| Field | Example | Notes |
|---|---|---|
| `timestamp` | `2026-10-11T05:49:18.2+00:00` | UTC ISO 8601 |
| `requirement_id` | `REQ-2.1` | Key |
| `tool_name` | `run_tests` | One of the six approved tools |
| `status` | `success` | The tool's own outcome |
| `hops` | `2` | Hop count when the call ran |
| `test_outcome` | `failed` | `run_tests` only, otherwise `null` |
| `failed_count` | `1` | `run_tests` only: failed + errors |

**Not stored:** test code, test output or failure messages, requirement text, prompts or model
replies, file contents, approval tokens, API keys or GitHub tokens.

**The records contain no personal data.** They describe test runs of a software requirement, not
people. (The earlier GDPR "right to be forgotten" framing applied to customer records and no longer
applies.)

Calls refused by the phase guard, or skipped as extra calls in one step, are not executed and are
therefore not recorded.

## 4. Who can access it

| Who | Access |
|---|---|
| Developers with access to the machine or working copy | Read/write the file directly. It is git-ignored (`data/`), so it is never pushed. |
| The human approver | Sees the last 3 runs + advisory at the approval prompt |
| The LLM | **None** |
| MCP clients | **None**: the server prints history on its own console only |

Writes and reads are guarded by a `threading.Lock`, so concurrent runs in one process do not
interleave lines.

## 5. Retention

Records are kept for **30 days** (`RETENTION_DAYS`). `purge_expired_records(retention_days=30)`
removes older records and returns the count. Purging is run manually (or from a scheduled job);
nothing calls it automatically at the moment.

## 6. Deletion

- **One requirement:** `delete_requirement_history("REQ-2.1")` removes all its records and returns the count.
- **Everything:** delete `data/memory/case_history.jsonl`; it is recreated on the next run.
- **Tests:** `tests/conftest.py` points memory at a temp file for every test, so tests never touch
  the real file.

## 7. Verification

| Property | Test |
|---|---|
| Round trip, newest first, limit, filter by tool | `test_record_and_retrieve_round_trip` |
| Only metadata fields stored | `test_records_hold_only_metadata_fields` |
| Empty before the first run | `test_get_case_history_empty_when_no_file` |
| Deletion | `test_delete_requirement_history` |
| 30-day purge | `test_purge_expired_records` |
| Advisory wording | `test_advisory_*`, `test_format_history_line` |
| Never reaches the LLM / token | `test_case_history_never_reaches_llm_or_token` |
| Cannot bypass approval | `test_history_full_of_approvals_cannot_bypass_file_issue_gate`, `test_memory_never_silently_bypasses_human_approval` |
| run_tests outcome recorded | `test_run_tests_outcome_is_recorded_in_memory` |
| GitHub token never stored | `test_github_token_never_in_tool_message_or_memory` |
