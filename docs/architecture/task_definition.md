# Week 5 — Task Definition (realigned)

**Project:** Software-Engineering QA Agent (Inspectra)

This replaces the earlier task definition ("resolve a user's subscription upgrade request"), in
which the agent operated the subscription service. The agent now tests it. The old version is in
git history.

## Task

For **one requirement** of the system under test (for example `REQ-2.1`, Tier Upgrades in
`docs/requirements/subscription.md`), Inspectra proposes tests, runs them in the sandbox, and then
does one of two things:
- reports that the implementation meets the requirement, or
- explains the failure and drafts an issue, which a human approves or rejects before it is filed.

A typical request: *"Check REQ-2.1 (Tier Upgrades) against the code."*

## Why this genuinely needs multi-step decisions

No single tool call can do this, and the next step depends on what the previous step observed:

| After... | Observed | Next step |
|---|---|---|
| `search_requirements` | No matching requirement | Stop: `requirement_not_found` |
| `search_requirements` | A matching `REQ-X.Y` | `propose_tests` for that id |
| `propose_tests` | Error (model unavailable, unsafe code rejected, model refusal) | Stop: `tool_error` |
| `propose_tests` | A test file in `sandbox/generated/` | `run_tests` on that file |
| `run_tests` | `test_outcome = passed` | Report and stop: `all_tests_passed` |
| `run_tests` | Failed, and the failing test expects something the requirement does not say | **Test defect**: report and stop, file nothing (`test_defect_reported`) |
| `run_tests` | Failed, and the behaviour contradicts the requirement | **Code defect**: `draft_issue` |
| `draft_issue` | A draft path | `file_issue`, which hands off to the human |
| `file_issue` | Human approves | Filed: `issue_filed` |
| `file_issue` | Human rejects | Stop: `human_rejection`; the draft stays for review |

The code-vs-test judgement is the part that needs the model. A deterministic script could run the
steps in order, but it could not decide from failure messages whether the code or the generated
test is wrong. Filing is the part that needs a human.

## Sense → Plan/Decide → Act → Observe → Stop, mapped to the real tools

| Stage | In Inspectra |
|---|---|
| **Sense** | The developer's request, plus each tool result returned as a `ToolMessage` |
| **Plan / Decide** | Gemini, following `prompts/agent_system_prompt_v2.0.txt`, chooses the next approved tool (one per step) |
| **Act** | `search_requirements`, `propose_tests`, `run_tests`, `draft_issue`; `file_issue` / `save_test_to_suite` only through the human approval gate |
| **Observe** | `status` (the tool's outcome) and `test_outcome` (the tests' result) in each result |
| **Stop / Re-plan** | Stops on a stop condition or at `MAX_HOPS = 7`; may re-plan once (for example a second search) |

Full contract: [`agent_task_contract.md`](agent_task_contract.md). Loop details:
[`agent_control_loop_spec.md`](agent_control_loop_spec.md).
