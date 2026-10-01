# Agent Contract Test Evidence (Week 5)

**Project:** Software-Engineering QA Agent (Inspectra)  
**Deliverable:** Week 5 (Bounded Agent Workflow: limits, allow-list, human hand-off)  
**Target:** `src/tool_calling.py` (`execute_tools`, `route_after_tools`, `MAX_HOPS`), `src/approval.py`  
**Test Suite:** `tests/test_agent_contract.py`  
**Related evidence:** `evidence/week5_execution_traces.txt`, `evidence/tool failure test evidence.md`

---

### 1. Test Summary Matrix

| ID | Test | Contract rule checked | Input / Mock Condition | Expected Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AC-01** | `test_iteration_cap_stops_loop` | Iteration limit (`MAX_HOPS`) | `route_after_tools` called with `hops = MAX_HOPS` and `hops = MAX_HOPS - 1` | Returns `END` at the cap; returns `"assistant"` (continue) one hop below it | **PASS** |
| **AC-02** | `test_unknown_tool_is_rejected` | Approved-tool allow-list | Model requests a tool named `delete_all_users` | Tool result contains `"Unknown tool"`; nothing is executed | **PASS** |
| **AC-03** | `test_human_rejection_blocks_upgrade` | Human hand-off | `request_human_approval` mocked to reject; `process_upgrade` mocked to detect any call | `process_upgrade` is never called; tool result contains `approval_required` | **PASS** |
| **AC-04** | `test_extra_tool_calls_get_error_results` | Calls per step (`MAX_CALLS_PER_STEP`) | Model requests two `get_user_subscription_status` calls in one step | Two tool messages are returned (one per call, so none is left unanswered); the second contains `"skipped"` | **PASS** |
| **AC-05** | `test_hops_increment_once_per_step` | Hop counting | One step run with `hops = 2` | Returned `hops` equals 3 | **PASS** |

Scope note: AC-01 tests the routing decision directly rather than running a full multi-step loop. The full loop behaviour is shown in the execution traces (Section 3). AC-03 proves the approved action does not execute, by asserting `process_upgrade` (the function that writes the ledger) is never called.

---

### 2. Execution Log: Week 5 run (agent contract tests, excerpt from full suite)

These five lines are taken from the full-suite run (`python -m pytest tests/ -v`, 23 passed) recorded in `evidence/tool failure test evidence.md`, Section 3.

```text
tests/test_agent_contract.py::test_iteration_cap_stops_loop PASSED          [  4%]
tests/test_agent_contract.py::test_unknown_tool_is_rejected PASSED          [  8%]
tests/test_agent_contract.py::test_human_rejection_blocks_upgrade PASSED    [ 13%]
tests/test_agent_contract.py::test_extra_tool_calls_get_error_results PASSED [ 17%]
tests/test_agent_contract.py::test_hops_increment_once_per_step PASSED      [ 21%]
```

To capture a standalone log for this suite, run:

```powershell
python -m pytest tests/test_agent_contract.py -v
```

and paste the full output (including the final "5 passed" line) here in place of the excerpt.

---

### 3. Link to execution traces

`evidence/week5_execution_traces.txt` shows the same limits working end to end on the real LangGraph graph:

| Scenario | Outcome | Contract rule demonstrated |
| :--- | :--- | :--- |
| 1. Eligible user (u123) | Human approved, upgrade written, 2/4 hops used | Human hand-off, hop counting |
| 2. Ineligible user (u_poor, $25.50) | Refused, 0 approval requests, no ledger write | Stop on precondition refusal |
| 3. Lookup service fails (u456) | Structured error reported, no ledger write, no crash | Failure recovery |