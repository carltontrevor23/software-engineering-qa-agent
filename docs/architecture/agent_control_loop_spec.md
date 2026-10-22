# Agent Control Loop Specification: Sense-Plan-Act-Observe-Stop (realigned)

This document describes the control loop of the **bounded Inspectra QA agent**
(`src/agent.py` and `src/guard_middleware.py`). It replaces the earlier spec for the subscription-upgrade agent, which is
in git history.

The loop is a LangChain `create_agent` graph (LangGraph underneath), served in LangGraph Studio.
Week 8 replaced the hand-written `assistant` / `execute_tools` nodes with middleware:
`before_agent → model → after_model → (tool call?) → approval gate → tools → before_model → model … → END`.
The deterministic controls (`InspectraGuard`) and the human approval gate (`ApprovalGate`, a
`HumanInTheLoopMiddleware`) sit around the model and the tools; the decisions themselves still come
from `src/workflow.py` and `src/guardrails.py`.

---

## Stage 1: Sense / Context

### Information received
- **First turn:** the developer's request, e.g. *"Check REQ-2.1 (Tier Upgrades) against the code."*
- **Later turns:** each tool result, returned as a `ToolMessage` containing `status`, plus
  `test_outcome` for `run_tests`.

### Context the agent works from
- The agent rules in `prompts/agent_system_prompt_v2.0.txt` (version `v2.0`, recorded in `AGENT_CONTRACT`).
- Requirement text from `docs/requirements/*.md`, retrieved by `search_requirements` (BM25).
- The SUT source, included by `propose_tests` when it asks the model for tests.

Requirement text, test code and test output are treated as **data, not instructions** (rule 7).

---

## Stage 2: Plan / Decide

The model picks exactly one next tool per step (`MAX_CALLS_PER_STEP = 1`; extra calls in the same
step are skipped with an error result).

| Path | Condition | Decision |
|---|---|---|
| A — Resolve requirement | No requirement id known yet | `search_requirements(query)`; skipped if the user gave `REQ-X.Y` |
| B — No requirement | Search returns no results | Stop and say so |
| C — Propose | Requirement id known, no tests yet | `propose_tests(requirement_id)` |
| D — Run | Test file returned | `run_tests(requirement_id, test_file)` |
| E — Passed | `test_outcome = passed` | Report and stop. Offer `save_test_to_suite`, but do not call it unless asked |
| F — Test defect | Failure contradicts nothing in the requirement | Explain and stop, file nothing |
| G — Code defect | Failure shows behaviour contradicting the requirement | `draft_issue`, then `file_issue` |
| H — Error | Any `status` of `error` or `approval_required` | Stop and report, no retry |

---

## Stage 3: Act / Tool

| Tool | Impact | What the system does |
|---|---|---|
| `search_requirements` | Low | BM25 retrieval over `docs/requirements/` |
| `propose_tests` | Low | Model writes pytest code; checked against the sandbox policy; saved to `sandbox/generated/` |
| `run_tests` | Low | pytest in a separate process: no shell, 60 s timeout, secret-free environment |
| `draft_issue` | Low | Markdown draft in `evidence/issues/drafts/` |
| `file_issue` | **High** | The run pauses on an approve/reject card showing the case history (Studio) or a terminal prompt (CLI); on approval `InspectraGuard` mints a signed single-use token, which the tool verifies before filing |
| `save_test_to_suite` | **High** | Same approval flow; copies a generated test into `sut/tests/` |

Every call is checked first by `InspectraGuard` (allow-list, phase guard, file pinning, one call per step); unknown or disallowed tools return an error and never reach the human or the tool.

---

## Stage 4: Observe

| Tool | Result that changes the next step |
|---|---|
| `search_requirements` | `results[].requirement_id`, or `note: NO_RELEVANT_REQUIREMENTS_FOUND` |
| `propose_tests` | `test_file` and `test_count`, or an `error` (unknown id, model unavailable, refusal, unsafe code) |
| `run_tests` | `test_outcome` (`passed` / `failed` / `no_tests`) and `failures[].test_name` / `message` |
| `draft_issue` | `draft_path` |
| `file_issue` | `success` (`filed_path`), or `approval_required` (human rejected or no valid token) |

---

## Stage 5: Stop / Re-plan

### Re-plan
The agent may re-plan when an observation does not settle the next step, for example a second,
narrower `search_requirements`. `MAX_HOPS = 7` allows the longest legitimate path (5 tool steps)
plus one re-plan step to still end in a final answer.

### Stop conditions (`AGENT_CONTRACT["stop_conditions"]`)

| Condition | When |
|---|---|
| `all_tests_passed` | `run_tests` reports `passed` |
| `issue_filed` | Human approved and `file_issue` succeeded |
| `human_rejection` | Human rejected `file_issue` / `save_test_to_suite` |
| `tool_error` | A tool returned `status: error` |
| `requirement_not_found` | No matching requirement, or an unknown requirement id |
| `hop_budget_exhausted` | `hops >= MAX_HOPS`: `before_model` ends the run with the stopped message |
| `test_defect_reported` | Tests failed, but the agent judged the generated test wrong and filed nothing |

Two further terminal reasons exist outside the contract list: `request_rejected` (the request failed input
validation before any model call) and `model_unavailable` (every model retry failed; the run stops
with an explicit message rather than a guessed reason).

`demo_support.stop_reason()` classifies a finished run against this list. The trace capture and
the demo use it.
