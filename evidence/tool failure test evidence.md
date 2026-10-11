# Tool Failure and Authorization Test Evidence (Week 4, realigned)

**Project:** Software-Engineering QA Agent (Inspectra)
**Deliverable:** Week 4 Activity 4 (Failure/Authorization Test Evidence)
**Target:** `src/qa_tools.py`, `src/sandbox.py`, `src/tool_calling.py`
**Test suites:** `tests/test_tool_failures.py` (QA tools), `sut/tests/test_subscription_manager.py` (SUT baseline)
**Run:** 2026-10-11, `venv\Scripts\python -m pytest tests/test_tool_failures.py sut/tests/ -v -p no:cacheprovider`

The earlier version of this file tested the removed subscription tools. It is in git history.

---

### 1. Test summary matrix

| ID | Category | Scenario | Expected result | Status |
| :--- | :--- | :--- | :--- | :--- |
| TF-01 | Missing parameter | `propose_tests.invoke({})` | Pydantic `ValidationError` | PASS |
| TF-02 | Missing parameter | `run_tests` without `test_file` | `ValidationError` | PASS |
| TF-03 | Missing parameter | `file_issue.invoke({})` | `ValidationError` | PASS |
| TF-04 | Invalid type | `requirement_id = 12345` | `ValidationError` | PASS |
| TF-05 | Requirement lookup | Section headings parse to REQ-2.1 ... REQ-2.6 | REQ-2.1 maps to `subscription.md` | PASS |
| TF-06 | Unknown requirement | `propose_tests("REQ-9.9")` | `error: Unknown requirement 'REQ-9.9'.` | PASS |
| TF-07 | Retrieval | "tier upgrade balance PREMIUM" | Top hit REQ-2.1 | PASS |
| TF-08 | Retrieval | Unrelated query | Empty results + `NO_RELEVANT_REQUIREMENTS_FOUND` | PASS |
| TF-09 | Generated code | Valid model reply | File in `sandbox/generated/`, `test_count` = 2 | PASS |
| TF-10 | Unsafe generated code | Model reply imports `subprocess` | `error`, nothing written | PASS |
| TF-11 | Model refusal | Reply `NO_GROUNDED_TESTS_FOUND: ...` | `error` carrying the refusal | PASS |
| TF-12 | Unavailable service | `get_model_response` raises `ModelCallError` (429) | `error: Model unavailable ...` | PASS |
| TF-13 | Code policy | `eval`, `os.system`, `os.execv`, `socket`, `shutil`, non-allow-listed import, syntax error | Each rejected with a reason | PASS |
| TF-14 | Code policy | Allowed imports only | Accepted | PASS |
| TF-15 | Unauthorized path | `run_tests("../../src/tool_calling.py")` | `error: ... outside the sandbox's allowed test folders.` | PASS |
| TF-16 | Missing file | `run_tests` on a non-existent file | `error: ... does not exist.` | PASS |
| TF-17 | Real sandbox run | 2 passing tests | `test_outcome = passed`, 2/0/0 | PASS |
| TF-18 | Real sandbox run | 1 pass + 1 fail | `test_outcome = failed`, failure name + message returned | PASS |
| TF-19 | Unavailable / hung test | Infinite loop, timeout 2 s | `error: ... sandbox timeout ...` | PASS |
| TF-20 | Secret isolation | Parent has `GEMINI_API_KEY`, `GITHUB_TOKEN` set | Test inside sandbox sees neither | PASS |
| TF-21 | Defence in depth | Generated file edited to import `subprocess` after writing | `run_tests` refuses it | PASS |
| TF-22 | Simulated side effect | `draft_issue` | Local draft, requirement quoted, marked "not filed" | PASS |
| TF-23 | Unauthorized action | `file_issue` with no token | `approval_required`, nothing filed | PASS |
| TF-24 | Unauthorized action | `file_issue` with tampered token | `approval_required` (signature invalid), nothing filed | PASS |
| TF-25 | Authorized action | `file_issue` with a valid token | Filed locally, content identical to draft | PASS |
| TF-26 | Unauthorized path | `file_issue` on a file outside `drafts/` (valid token) | `error` | PASS |
| TF-27 | Unauthorized action | `save_test_to_suite` with no token | `approval_required`, suite unchanged | PASS |
| TF-28 | Unauthorized path | `save_test_to_suite("src/tool_calling.py")` (valid token) | `error`, suite unchanged | PASS |
| TF-29 | Authorized action | `save_test_to_suite` with a valid token | Copied into `sut/tests/` | PASS |
| TF-30 | Case-history key | Key from `requirement_id`, draft name or generated test name | `REQ-2.1` / `unknown` | PASS |
| SUT-01..06 | SUT baseline | Normal upgrade, $50.00, $49.99, inactive, already PREMIUM, non-200 | All pass on the unmodified SUT | PASS |

---

### 2. Execution log

```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.1.1, pluggy-1.6.0 -- D:\New folder\software-engineering-qa-agent\venv\Scripts\python.exe
rootdir: D:\New folder\software-engineering-qa-agent
plugins: anyio-4.13.0, langsmith-0.14.0
collecting ... collected 42 items

tests/test_tool_failures.py::test_missing_parameter_propose_tests PASSED [  2%]
tests/test_tool_failures.py::test_missing_parameter_run_tests PASSED     [  4%]
tests/test_tool_failures.py::test_missing_parameter_file_issue PASSED    [  7%]
tests/test_tool_failures.py::test_invalid_parameter_type PASSED          [  9%]
tests/test_tool_failures.py::test_requirement_ids_are_parsed_from_section_headings PASSED [ 11%]
tests/test_tool_failures.py::test_unknown_requirement_id PASSED          [ 14%]
tests/test_tool_failures.py::test_search_requirements_finds_tier_upgrades PASSED [ 16%]
tests/test_tool_failures.py::test_search_requirements_no_hits PASSED     [ 19%]
tests/test_tool_failures.py::test_propose_tests_writes_valid_code_to_sandbox PASSED [ 21%]
tests/test_tool_failures.py::test_propose_tests_with_banned_import_writes_nothing PASSED [ 23%]
tests/test_tool_failures.py::test_propose_tests_model_refusal_is_reported PASSED [ 26%]
tests/test_tool_failures.py::test_propose_tests_model_unavailable PASSED [ 28%]
tests/test_tool_failures.py::test_validate_generated_code_rejects[x = eval('1')-eval] PASSED [ 30%]
tests/test_tool_failures.py::test_validate_generated_code_rejects[import os\nos.system('dir')-os.system] PASSED [ 33%]
tests/test_tool_failures.py::test_validate_generated_code_rejects[import os\nos.execv('a', [])-os.execv] PASSED [ 35%]
tests/test_tool_failures.py::test_validate_generated_code_rejects[import socket-socket] PASSED [ 38%]
tests/test_tool_failures.py::test_validate_generated_code_rejects[from shutil import rmtree-shutil] PASSED [ 40%]
tests/test_tool_failures.py::test_validate_generated_code_rejects[import numpy-allow-list] PASSED [ 42%]
tests/test_tool_failures.py::test_validate_generated_code_rejects[def broken(:-does not parse] PASSED [ 45%]
tests/test_tool_failures.py::test_validate_generated_code_accepts_allowed_imports PASSED [ 47%]
tests/test_tool_failures.py::test_run_tests_outside_allowed_dirs_is_refused PASSED [ 50%]
tests/test_tool_failures.py::test_run_tests_missing_file_is_refused PASSED [ 52%]
tests/test_tool_failures.py::test_run_tests_passing_file PASSED          [ 54%]
tests/test_tool_failures.py::test_run_tests_failing_file_reports_failures PASSED [ 57%]
tests/test_tool_failures.py::test_run_tests_timeout PASSED               [ 59%]
tests/test_tool_failures.py::test_run_tests_environment_has_no_secrets PASSED [ 61%]
tests/test_tool_failures.py::test_run_tests_rechecks_generated_code PASSED [ 64%]
tests/test_tool_failures.py::test_draft_issue_is_local_and_marked_not_filed PASSED [ 66%]
tests/test_tool_failures.py::test_file_issue_without_token_is_blocked PASSED [ 69%]
tests/test_tool_failures.py::test_file_issue_with_tampered_token_is_blocked PASSED [ 71%]
tests/test_tool_failures.py::test_file_issue_with_valid_token_files_locally PASSED [ 73%]
tests/test_tool_failures.py::test_file_issue_outside_drafts_is_refused PASSED [ 76%]
tests/test_tool_failures.py::test_save_test_to_suite_without_token_is_blocked PASSED [ 78%]
tests/test_tool_failures.py::test_save_test_to_suite_outside_generated_is_refused PASSED [ 80%]
tests/test_tool_failures.py::test_save_test_to_suite_with_valid_token_copies_test PASSED [ 83%]
tests/test_tool_failures.py::test_case_history_key_comes_from_requirement_or_file_name PASSED [ 85%]
sut/tests/test_subscription_manager.py::test_normal_upgrade_deducts_cost_and_writes_ledger PASSED [ 88%]
sut/tests/test_subscription_manager.py::test_balance_exactly_50_succeeds PASSED [ 90%]
sut/tests/test_subscription_manager.py::test_balance_49_99_raises_and_leaves_ledger_untouched PASSED [ 92%]
sut/tests/test_subscription_manager.py::test_inactive_user_raises PASSED [ 95%]
sut/tests/test_subscription_manager.py::test_already_premium_raises PASSED [ 97%]
sut/tests/test_subscription_manager.py::test_non_200_http_raises_user_not_found PASSED [100%]

============================= 42 passed in 19.99s =============================
```

---

### 3. Live smoke test (real Gemini model)

One live call on 2026-10-11 checked that a real model reply passes the sandbox policy and runs:

```text
qa_tools.propose_tests("REQ-2.1")
  -> {"status": "success", "test_file": "sandbox/generated/test_req_2_1_7e2a54c8.py", "test_count": 7}
qa_tools.run_tests("REQ-2.1", <that file>)
  -> {"status": "success", "test_outcome": "passed", "passed": 7, "failed": 0, "errors": 0}
```

The generated tests included the boundary cases from AC-2 and AC-3 (balance 50.00, 50.01 and 49.99),
inactive statuses, and non-200 HTTP responses. The model call is logged in
`evidence/traces/trace_2026-10-11.jsonl`. The generated file itself lives in the git-ignored
`sandbox/generated/` folder.
