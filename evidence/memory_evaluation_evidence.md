# Memory Evaluation Evidence: Requirement Test-Run History

**Project:** Software-Engineering QA Agent (Inspectra)
**Deliverable:** Week 6, working memory/state demonstration (realigned)
**Generated:** 2026-10-11 from real runs of `demo/run_demo.py` and pytest
**Design:** [`docs/architecture/memory_design_and_data_handling_note.md`](../docs/architecture/memory_design_and_data_handling_note.md)

The earlier version of this file covered the customer case history of the subscription-upgrade
agent. It is in git history.

## 1. What this shows

1. **Memory improves a legitimate task.** At the approval prompt the human sees how earlier test
   runs for the same requirement went, and gets an advisory telling a first failure apart from a
   recurring one.
2. **Memory does not silently control anything.** The human still answers `y/N`; the history never
   reaches the LLM or the approval token.

## 2. Demo runs (offline mode, so no model quota was used)

Three consecutive runs on REQ-2.1, starting from an empty history. Lines are as printed (the
`[SCRIPTED LLM]` label marks offline mode).

### Run 1: correct SUT → tests pass, nothing to approve

```text
[SCRIPTED LLM] hop 0 | assistant     | call search_requirements(query=Check REQ-2.1 (Tier Upgrades) against the code.)  (0.01s)
[SCRIPTED LLM] hop 1 | execute_tools | search_requirements -> status=success [phase REQUIREMENT_RESOLVED]  (0.01s)
[SCRIPTED LLM] hop 1 | assistant     | call propose_tests(requirement_id=REQ-2.1)  (0.0s)
[SCRIPTED LLM] hop 2 | execute_tools | propose_tests -> status=success [phase TESTS_PROPOSED]  (0.01s)
[SCRIPTED LLM] hop 2 | assistant     | call run_tests(requirement_id=REQ-2.1, test_file=test_req_2_1_b9104a5b.py)  (0.0s)
[SCRIPTED LLM] hop 3 | execute_tools | run_tests -> status=success test_outcome=passed [phase TESTS_RUN_PASSED]  (4.96s)
[SCRIPTED LLM] hop 3 | assistant     | final answer [phase DONE]  (0.0s)
[SCRIPTED LLM] Stop reason: all_tests_passed (final phase DONE)
```

### Run 2: planted defect → first failure → human approves

```text
[SCRIPTED LLM] hop 0 | assistant     | call search_requirements(query=Check REQ-2.1 (Tier Upgrades) against the code.)  (0.01s)
[SCRIPTED LLM] hop 1 | execute_tools | search_requirements -> status=success [phase REQUIREMENT_RESOLVED]  (0.01s)
[SCRIPTED LLM] hop 1 | assistant     | call propose_tests(requirement_id=REQ-2.1)  (0.01s)
[SCRIPTED LLM] hop 2 | execute_tools | propose_tests -> status=success [phase TESTS_PROPOSED]  (0.01s)
[SCRIPTED LLM] hop 2 | assistant     | call run_tests(requirement_id=REQ-2.1, test_file=test_req_2_1_b71b0f41.py)  (0.0s)
[SCRIPTED LLM] hop 3 | execute_tools | run_tests -> status=success test_outcome=failed [phase TESTS_RUN_FAILED]  (5.56s)
[SCRIPTED LLM] hop 3 | assistant     | call draft_issue(requirement_id=REQ-2.1, title=REQ-2.1: implementation contradicts the requiremen..., summary=CODE defect: the failing tests check behaviour the..., failing_tests=['sandbox.generated.test_req_2_1_b71b0f41::test_up...)  (0.0s)
[SCRIPTED LLM] hop 4 | execute_tools | draft_issue -> status=success [phase ISSUE_DRAFTED]  (0.01s)
[SCRIPTED LLM] hop 4 | assistant     | call file_issue(draft_path=ISSUE-REQ-2.1-20261011T054918Z.md)  (0.0s)
[SCRIPTED LLM] [CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed) 2026-10-11; run_tests -> passed 2026-10-11
[SCRIPTED LLM] [ADVISORY] FIRST FAILURE: previously passing (possible regression or flaky/incorrect generated test). (advisory only - the decision is yours)
[SCRIPTED LLM]  Authorize this action? [y/N]: hop 5 | execute_tools | file_issue -> status=success [phase DONE]  (0.04s)
[SCRIPTED LLM] hop 5 | assistant     | final answer  (0.0s)
[SCRIPTED LLM] Stop reason: issue_filed (final phase DONE)
```

The advisory says **FIRST FAILURE: previously passing**: the human knows run 1 passed a moment ago,
so this failure is new. Here it is explained by the planted defect; in real use the advisory tells
the human to check whether the generated test or the code is wrong before filing.

### Run 3: planted defect again → recurring failure → human rejects

```text
[SCRIPTED LLM] hop 0 | assistant     | call search_requirements(query=Check REQ-2.1 (Tier Upgrades) against the code.)  (0.01s)
[SCRIPTED LLM] hop 1 | execute_tools | search_requirements -> status=success [phase REQUIREMENT_RESOLVED]  (0.01s)
[SCRIPTED LLM] hop 1 | assistant     | call propose_tests(requirement_id=REQ-2.1)  (0.0s)
[SCRIPTED LLM] hop 2 | execute_tools | propose_tests -> status=success [phase TESTS_PROPOSED]  (0.01s)
[SCRIPTED LLM] hop 2 | assistant     | call run_tests(requirement_id=REQ-2.1, test_file=test_req_2_1_46117408.py)  (0.0s)
[SCRIPTED LLM] hop 3 | execute_tools | run_tests -> status=success test_outcome=failed [phase TESTS_RUN_FAILED]  (4.37s)
[SCRIPTED LLM] hop 3 | assistant     | call draft_issue(requirement_id=REQ-2.1, title=REQ-2.1: implementation contradicts the requiremen..., summary=CODE defect: the failing tests check behaviour the..., failing_tests=['sandbox.generated.test_req_2_1_46117408::test_up...)  (0.0s)
[SCRIPTED LLM] hop 4 | execute_tools | draft_issue -> status=success [phase ISSUE_DRAFTED]  (0.02s)
[SCRIPTED LLM] hop 4 | assistant     | call file_issue(draft_path=ISSUE-REQ-2.1-20261011T054930Z.md)  (0.0s)
[SCRIPTED LLM] [CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed) 2026-10-11; run_tests -> failed (1 failed) 2026-10-11; run_tests -> passed 2026-10-11
[SCRIPTED LLM] [ADVISORY] RECURRING: failed in 2 of the last 3 runs. (advisory only - the decision is yours)
[SCRIPTED LLM]  Authorize this action? [y/N]: hop 5 | execute_tools | file_issue -> status=approval_required [phase STOPPED]  (0.03s)
[SCRIPTED LLM] hop 5 | assistant     | final answer  (0.0s)
[SCRIPTED LLM] Stop reason: human_rejection (final phase STOPPED)
```

The advisory now says **RECURRING: failed in 2 of the last 3 runs**. The human still decided to
reject, and the agent stopped with `human_rejection` and filed nothing. History informed the
decision but did not make it.

## 3. Guard and behaviour tests

```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.1.1, pluggy-1.6.0 -- D:\New folder\software-engineering-qa-agent\venv\Scripts\python.exe
rootdir: D:\New folder\software-engineering-qa-agent
plugins: anyio-4.13.0, langsmith-0.14.0
collecting ... collected 15 items

tests/test_memory.py::test_record_and_retrieve_round_trip PASSED         [  6%]
tests/test_memory.py::test_records_hold_only_metadata_fields PASSED      [ 13%]
tests/test_memory.py::test_get_case_history_empty_when_no_file PASSED    [ 20%]
tests/test_memory.py::test_delete_requirement_history PASSED             [ 26%]
tests/test_memory.py::test_purge_expired_records PASSED                  [ 33%]
tests/test_memory.py::test_advisory_recurring_failure PASSED             [ 40%]
tests/test_memory.py::test_advisory_first_failure_after_passing_runs PASSED [ 46%]
tests/test_memory.py::test_advisory_first_run_and_no_history PASSED      [ 53%]
tests/test_memory.py::test_format_history_line PASSED                    [ 60%]
tests/test_memory.py::test_case_history_never_reaches_llm_or_token PASSED [ 66%]
tests/test_memory_behavior.py::test_memory_surfaces_legitimate_audit_history PASSED [ 73%]
tests/test_memory_behavior.py::test_memory_tenant_isolation PASSED       [ 80%]
tests/test_memory_behavior.py::test_memory_never_silently_bypasses_human_approval PASSED [ 86%]
tests/test_memory_behavior.py::test_history_full_of_approvals_cannot_bypass_file_issue_gate PASSED [ 93%]
tests/test_memory_behavior.py::test_memory_not_in_llm_state PASSED       [100%]

============================= 15 passed in 5.45s ==============================
```

| Guarantee | Test |
|---|---|
| History printed to the operator, absent from `ToolMessage`s, state fields and the messages `assistant()` sends to the LLM | `test_case_history_never_reaches_llm_or_token` |
| Approval token arguments contain only `{"draft_path": ...}` | `test_case_history_never_reaches_llm_or_token` |
| Ten earlier filings and passing runs in memory still do not allow `file_issue` without a fresh token | `test_history_full_of_approvals_cannot_bypass_file_issue_gate` |
| `AgentState` has no field through which history could enter | `test_memory_not_in_llm_state` |
| Records keep only metadata (no test output, code or requirement text) | `test_records_hold_only_metadata_fields` |
| Deletion and 30-day purge | `test_delete_requirement_history`, `test_purge_expired_records` |
