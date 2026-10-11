# Agent Contract Test Evidence (Weeks 5–6, realigned)

**Project:** Software-Engineering QA Agent (Inspectra)
**Deliverable:** Bounded agent workflow (Week 5) and explicit workflow state (Week 6)
**Target:** `src/tool_calling.py`, `src/workflow.py`, `src/demo_support.py`, `src/approval.py`
**Test suite:** `tests/test_agent_contract.py` (offline: scripted LLM, fixture tests, all writes in `tmp_path`)
**Related evidence:** `evidence/week5_live_execution_traces.md`, `evidence/memory_evaluation_evidence.md`

The earlier version of this file tested the subscription-upgrade agent. It is in git history.

---

### 1. What the tests check

| Contract rule | Tests |
|---|---|
| Iteration limit `MAX_HOPS = 7` | `test_iteration_cap_stops_loop`, `test_route_after_tools_stops_exactly_at_max_hops`, `test_longest_path_plus_one_replan_still_ends_in_answer`, `test_hop_limit_sets_hop_budget_exhausted` |
| Tool allow-list | `test_unknown_tool_is_rejected`, `test_contract_lists_qa_tools` |
| One call per step | `test_extra_tool_calls_get_error_results`, `test_hops_increment_once_per_step` |
| Goal, prompt version, stop conditions | `test_contract_goal_limits_and_prompt_version`, `test_system_prompt_is_loaded_from_versioned_file` |
| Human hand-off | `test_human_rejection_blocks_file_issue`, `test_planted_bug_with_human_rejection_files_nothing`, `test_rejection_sets_stopped_human_rejection` |
| Full workflow: search → propose → run → draft → file | `test_planted_bug_full_path_with_approval_files_one_issue`, `test_full_run_state_fields_from_tool_results` |
| Stop after a pass, no draft | `test_all_tests_pass_stops_after_run_tests` |
| Test-defect stop | `test_answer_after_failed_run_is_test_defect` |
| Phase guard: refused calls are not executed | `test_tool_not_allowed_in_phase_is_not_executed`, `test_file_issue_not_allowed_before_a_draft`, `test_propose_regenerate_allowed_once_after_failure` |
| File pinning (prompt-injection defence) | `test_run_tests_pinned_to_proposed_file`, `test_file_issue_pinned_to_drafted_file` |
| Preconditions on missing files | `test_run_tests_precondition_missing_file`, `test_file_issue_precondition_missing_draft` |
| Planted defect never touches the real SUT | `test_planted_bug_never_modifies_real_sut` |
| Workflow fields initialised; run outcome stored in memory | `test_initial_state_has_all_workflow_fields`, `test_run_tests_outcome_is_recorded_in_memory` |

---

### 2. Execution log (2026-10-11)

```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.1.1, pluggy-1.6.0 -- D:\New folder\software-engineering-qa-agent\venv\Scripts\python.exe
rootdir: D:\New folder\software-engineering-qa-agent
plugins: anyio-4.13.0, langsmith-0.14.0
collecting ... collected 27 items

tests/test_agent_contract.py::test_iteration_cap_stops_loop PASSED       [  3%]
tests/test_agent_contract.py::test_unknown_tool_is_rejected PASSED       [  7%]
tests/test_agent_contract.py::test_contract_lists_qa_tools PASSED        [ 11%]
tests/test_agent_contract.py::test_human_rejection_blocks_file_issue PASSED [ 14%]
tests/test_agent_contract.py::test_extra_tool_calls_get_error_results PASSED [ 18%]
tests/test_agent_contract.py::test_hops_increment_once_per_step PASSED   [ 22%]
tests/test_agent_contract.py::test_contract_goal_limits_and_prompt_version PASSED [ 25%]
tests/test_agent_contract.py::test_system_prompt_is_loaded_from_versioned_file PASSED [ 29%]
tests/test_agent_contract.py::test_route_after_tools_stops_exactly_at_max_hops PASSED [ 33%]
tests/test_agent_contract.py::test_planted_bug_full_path_with_approval_files_one_issue PASSED [ 37%]
tests/test_agent_contract.py::test_planted_bug_with_human_rejection_files_nothing PASSED [ 40%]
tests/test_agent_contract.py::test_all_tests_pass_stops_after_run_tests PASSED [ 44%]
tests/test_agent_contract.py::test_longest_path_plus_one_replan_still_ends_in_answer PASSED [ 48%]
tests/test_agent_contract.py::test_planted_bug_never_modifies_real_sut PASSED [ 51%]
tests/test_agent_contract.py::test_run_tests_precondition_missing_file PASSED [ 55%]
tests/test_agent_contract.py::test_file_issue_precondition_missing_draft PASSED [ 59%]
tests/test_agent_contract.py::test_initial_state_has_all_workflow_fields PASSED [ 62%]
tests/test_agent_contract.py::test_tool_not_allowed_in_phase_is_not_executed PASSED [ 66%]
tests/test_agent_contract.py::test_file_issue_not_allowed_before_a_draft PASSED [ 70%]
tests/test_agent_contract.py::test_run_tests_pinned_to_proposed_file PASSED [ 74%]
tests/test_agent_contract.py::test_file_issue_pinned_to_drafted_file PASSED [ 77%]
tests/test_agent_contract.py::test_propose_regenerate_allowed_once_after_failure PASSED [ 81%]
tests/test_agent_contract.py::test_full_run_state_fields_from_tool_results PASSED [ 85%]
tests/test_agent_contract.py::test_rejection_sets_stopped_human_rejection PASSED [ 88%]
tests/test_agent_contract.py::test_answer_after_failed_run_is_test_defect PASSED [ 92%]
tests/test_agent_contract.py::test_hop_limit_sets_hop_budget_exhausted PASSED [ 96%]
tests/test_agent_contract.py::test_run_tests_outcome_is_recorded_in_memory PASSED [100%]

============================= 27 passed in 42.83s =============================
```
