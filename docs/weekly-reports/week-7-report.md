# WEEKLY PROGRESS REPORT (WEEK 7)
**Course:** BSE4104 AI-Native & Agentic Engineering Capstone  
**Group:** GROUP S  
**Project:** Software-Engineering QA Agent (Inspectra)  
**Period:** 12th October to 16th October 2026  
**Weekly Focus:** Evaluation, observability and guardrails: produce evidence that the system is reliable, grounded, inspectable and safe for its bounded use case.

---

## 1. Work Completed Against Weekly Objectives

* **Final evaluation set (Activity 1).** 42 scenarios in [`docs/evaluation/final_evaluation_scenarios.json`](../evaluation/final_evaluation_scenarios.json): 7 normal, 6 edge, 5 incorrect information, 8 adversarial, 6 tool failure and 10 unauthorized action. 31 run with a scripted model and use no model quota; 11 need the live model; 21 are marked critical, meaning a failure is a safety or honesty violation. The scenarios exposed four weaknesses (EV-24, EV-25, EV-32, EV-42), all now fixed (see Failure Catalogue).
* **Measurable criteria (Activity 2).** [`docs/evaluation/evaluation_criteria.md`](../evaluation/evaluation_criteria.md) (v1.2) defines six criteria: task completion, tool selection, groundedness, instruction following, latency and safety violations. Each is read from the recorded trace. A scenario passes only with no safety violation and no failure in the first four criteria; there is no partial credit. Release gate: at least 90 % overall, 100 % of the 21 critical scenarios, and zero safety violations.
* **Logs and traces (Activity 3).** [`src/tracer.py`](../../src/tracer.py) records six kinds of evidence for every run (model, prompt, retrieval, tool, latency and error, outcome) as JSON Lines in `evidence/traces/agent_traces.jsonl`. Approval tokens and keys are removed before saving. `tests/test_observability.py` has 5 passing tests; the full suite reported 134 passed, 1 skipped when PR #30 was merged [CONFIRM: re-run on final main, the remediation tests were added after that run].
* **Guardrails (Activity 4).** [`src/guardrails.py`](../../src/guardrails.py) adds input checks (request length, requirement id format, query length and `top_k`, issue draft limits) and output checks (secrets are redacted, and a final answer claiming "tests passed" or "issue filed" without a matching tool result is withheld and replaced by a summary built from the recorded state). No model is involved. These sit on top of the earlier controls: tool allow list, phase guard, one call per step, 7 hop limit and signed single use human approval. Tests: `tests/test_guardrails_io.py`.
* **Failure Catalogue (Activity 5).** [`docs/evaluation/failure_catalogue.md`](../evaluation/failure_catalogue.md) lists 10 failures, each with cause, fix and a regression test in `tests/test_failure_remediation.py`, all recorded as passing. Five come from earlier development and five are new this week: file write errors crashed the agent run (EV-32); the approval signing key had a default stored in the source (EV-42); generated tests could overwrite files through pathlib (EV-25); generated tests could send data out through `requests` (EV-24); and the root `pytest` run collected generated tests and crashed (fixed with `pytest.ini`).

---

## 2. Key Engineering Decisions and Rationale

1. **Pass or fail, no partial credit.** A safety violation always fails a scenario, and reaching the right stop does not excuse an unsupported claim. Latency is reported but does not decide the verdict, because free tier timings are unreliable.
2. **Scripted scenarios first.** 31 of the 42 scenarios use a scripted model, so results are repeatable and cost no quota. The 11 live scenarios are kept for what only the real model can show, such as following the prompt rules.
3. **Guardrails are plain code.** No model is asked to judge another model. Prompt rule 8 (never claim a pass or a filing without a tool result) is now enforced in code as well as requested in the prompt.
4. **Fix the sandbox in code.** Generated tests can still read and mock, but mutating pathlib calls, write mode `open()` and outgoing `requests` calls are blocked. A missing approval secret now produces a random per run key instead of a public default.
5. **Native tracing.** Traces use the standard library, so no new third party dependency was added.

---

## 3. Challenges and Current Responses

### Model quota
* **Challenge:** The free tier allows 20 requests per day, so the 11 live scenarios have not been run yet.
* **Response:** The scripted scenarios carry the safety checks. Live runs will be budgeted in Week 8.

### Weaknesses in safeguards already marked complete
* **Challenge:** The scenarios showed gaps in the sandbox and the approval gate that earlier weeks had treated as done (FAIL-06 to FAIL-10).
* **Response:** Each gap was fixed and given a named regression test.

### Stop reason labels
* **Challenge:** When a call is refused, the workflow stays in its earlier phase, so the recorded stop reason can be `unclassified` or `requirement_not_found` instead of `tool_error` (EV-18, EV-20, EV-41). The refusal itself held in each case.
* **Response:** Recorded as a low severity labelling issue in the criteria document (section 8). Not yet fixed; carried to Week 8.

---

## 4. Deliverables Index

| Deliverable Name | File Location | Status |
| :--- | :--- | :---: |
| **30+ scenario evaluation dataset and results** | [`final_evaluation_scenarios.json`](../evaluation/final_evaluation_scenarios.json), [`evaluation_criteria.md`](../evaluation/evaluation_criteria.md) | Dataset and criteria complete; full results pending |
| **Observability / tracing evidence** | [`evidence/observability_tracing_evidence.md`](../../evidence/observability_tracing_evidence.md), [`src/tracer.py`](../../src/tracer.py), [`tests/test_observability.py`](../../tests/test_observability.py) | Completed |
| **Guardrail implementation evidence** | [`src/guardrails.py`](../../src/guardrails.py), [`tests/test_guardrails_io.py`](../../tests/test_guardrails_io.py) | Implemented and tested; evidence write up pending |
| **Failure Catalogue with remediation and re-test evidence** | [`failure_catalogue.md`](../evaluation/failure_catalogue.md), [`tests/test_failure_remediation.py`](../../tests/test_failure_remediation.py) | Completed |
| **Week 7 Progress Report** | [`docs/weekly-reports/week-7-report.md`](week-7-report.md) | Completed |

---

## 5. Individual Contribution Summary

| Member | Task owned | Evidence |
| :--- | :--- | :--- |
| **Modest Nakiroya** | Activity 1: final evaluation set (42 scenarios) and this report | Commit `e588f78`; `final_evaluation_scenarios.json` |
| **Kirabo Edna Takaisa** | Activity 2: measurable evaluation criteria | PR #29 (`7b4c4c5`); `evaluation_criteria.md` |
| **Ayebare Carlton** | Activity 3: logs and traces | PR #30 (`9bee9af`); `src/tracer.py`; observability evidence |
| **Asiimire Praise** | Activity 4: input and output guardrails | PR #28 (`3ab122d`); `src/guardrails.py` |
| **Marvin Bisaso** | Activity 5: Failure Catalogue and re-tests | PR #31 (`f106fa1`, `d3ae226`); `failure_catalogue.md` |

AI assistance: the scenario set was drafted with Claude and checked with scripted runs, then reviewed by its owner (see [`docs/ai-engineering-log.md`](../ai-engineering-log.md)).

---

## 6. Plan for Week 8

* Run the full evaluation on the final code: the 31 scripted scenarios, then the 11 live ones within the model quota. Record pass rates against the release gate in a committed results file.
* Fix or document the stop reason labelling for refused calls.
* Try `file_issue` against a real GitHub repository (open since Week 6).
* Re-run the full test suite on main and record the count.
* Review requirements, architecture, prompts, RAG, tools, memory, security and documentation against the code, and fix critical defects.
* Prepare the tagged release with README run instructions, the 8 to 12 page final report, and the live demonstration.

---

## 7. Repository & Project Management Links

* **GitHub Repository:** https://github.com/carltontrevor23/software-engineering-qa-agent  
* **Pull requests this week:** [#28](https://github.com/carltontrevor23/software-engineering-qa-agent/pull/28), [#29](https://github.com/carltontrevor23/software-engineering-qa-agent/pull/29), [#30](https://github.com/carltontrevor23/software-engineering-qa-agent/pull/30), [#31](https://github.com/carltontrevor23/software-engineering-qa-agent/pull/31)  
* **ClickUp Board Link:** https://app.clickup.com/1200440000000401/v/li/1200440000008199