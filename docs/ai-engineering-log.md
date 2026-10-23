# AI Engineering Log

**Project:** Software-Engineering QA Agent (Inspectra)

One entry per material AI-assisted change. Each entry records the tool used, what it generated,
and what a team member must review before the change is accepted.

---

## 2026-10-11 — Week 4 realignment: QA tool set and sandbox

- **Tool / model:** Claude Code (Claude Opus 5.5) as coding agent. Gemini (`MODEL_NAME` in `.env`)
  was called once for a live `propose_tests` smoke test.
- **Prompt given:** the team's "Prompt 1: Week 4 realignment" (retarget the tools to the QA
  workflow described in the Week 1 charter).
- **Generated:**
  - `src/qa_tools.py`, `src/sandbox.py` (new)
  - Rewired `src/tool_calling.py`, `src/approval.py`, `src/mcp_server.py`
  - `sut/` (SUT moved with `git mv`, baseline tests)
  - `prompts/v1.1_pytest_output_addendum.txt`
  - Rewritten `tests/test_tool_failures.py` and updated contract/memory tests
  - Tool Catalogue, architecture diagram, regenerated test evidence
- **Verified by the agent:** `venv\Scripts\python -m pytest tests/ sut/tests/ -v` passes (65 tests,
  including real sandboxed pytest runs, a timeout and a secret-isolation check). One live run:
  Gemini proposed 7 tests for REQ-2.1, and all passed policy and ran green.
- **A human must review:**
  - The sandbox policy in `src/sandbox.py`: is the import allow-list right, and are the known
    limits (no OS container; `open()` still possible) acceptable?
  - The approval wiring: only `file_issue` and `save_test_to_suite` are high impact.
  - The deviation in `requirement_id_from_args`: `file_issue` and `save_test_to_suite` take a file
    path, not a `requirement_id`, so the case-history key is taken from the draft name
    (`ISSUE-REQ-2.1-...`) or generated test name (`test_req_2_1_...`).
  - That the baseline SUT tests in `sut/tests/` match the requirements in
    `docs/requirements/subscription.md`.

---

## 2026-10-11 — Week 5 realignment: bounded QA agent loop, demo runner, traces

- **Tool / model:** Claude Code (Claude Opus 5.5) as coding agent; Gemini `gemini-3.8-flash` as the
  live agent model during trace capture.
- **Prompt given:** the team's "Prompt 2: Week 5 realignment".
- **Generated:**
  - `prompts/agent_system_prompt_v2.0.txt`, loaded from file by `src/tool_calling.py`
    (`MAX_HOPS = 7`, new goal and stop conditions, duplicate `route_after_tools` removed, CLI)
  - `src/demo_support.py` (scripted LLM, planted-bug SUT copy, step tracer, stop-reason helper)
  - `demo/run_demo.py`, `demo/fixtures/req_2_1_tests.py`
  - rewritten `src/capture_week5_traces.py`, and new traces in `evidence/traces/week5_live_traces.jsonl`
    and `evidence/week5_live_execution_traces.md`
  - old subscription traces moved to `evidence/legacy/` with `git mv` (see its README)
  - `docs/architecture/task_definition.md`, `agent_control_loop_spec.md`, `agent_task_contract.md`
  - new tests in `tests/test_agent_contract.py`
- **Verified by the agent:** 75 tests pass; offline demo approve and reject paths run end to end.
  T1 was captured live. T2 and T3 fell back to the scripted LLM after the free-tier daily quota
  (20 requests) ran out. The live T2 run's steps are in
  `evidence/traces/week5_capture_console_2026-10-11.log`.
- **Deviation:** a seventh stop condition, `test_defect_reported`, because rule 5 lets the agent stop
  without filing when the generated test is wrong.
- **A human must review:**
  - the agent rules in the v2.0 prompt;
  - that the scripted LLM is clearly labelled and only used offline;
  - whether T2/T3 should be re-captured live once quota allows.

---

## 2026-10-11 — Week 6 realignment: workflow state, test-run memory, GitHub and MCP

- **Tool / model:** Claude Code (Claude Opus 5.5) as coding agent. No live Gemini calls (daily
  free-tier quota exhausted); all verification used the offline scripted LLM and mocks.
- **Prompt given:** the team's "Prompt 3: Week 6 realignment".
- **Generated:**
  - `src/workflow.py` (phases, `ALLOWED_TOOLS_BY_PHASE`, file pinning, stop reasons);
    `AgentState` fields and `initial_state()` in `src/tool_calling.py`
  - `src/memory.py` keyed by `requirement_id`, with `test_outcome` / `failed_count`, the
    `format_history` / `advisory` helpers and `delete_requirement_history`
  - GitHub Issues filing in `qa_tools.file_issue`; `.env.example` GitHub settings
  - `src/mcp_server.py` (session phase guard, `start_check`) and `src/mcp_demo_client.py`
  - tests: `tests/test_memory.py`, `tests/test_memory_behavior.py`, `tests/test_mcp_server.py`,
    and new workflow tests in `tests/test_agent_contract.py` and `tests/test_tool_failures.py`
  - docs: `state_model.md`, `memory_design_and_data_handling_note.md`, `mcp_interface_spec.md`,
    `week-6-report.md`, `README.md`; regenerated `evidence/memory_evaluation_evidence.md` and
    `evidence/agent contract test evidence.md`
- **Verified by the agent:**
  - full suite passes;
  - `demo/run_demo.py --offline` (pass), then `--planted-bug --offline` approved (advisory
    `FIRST FAILURE`), then rejected (advisory `RECURRING`);
  - a real HTTP round trip between `mcp_server.py` and `mcp_demo_client.py` (offline model).
- **Deviations:**
  - an extra state field, `proposals_made`, to enforce "one regenerate";
  - an extra MCP capability, `start_check`, to reset the server session;
  - `test_defect_reported` (from Week 5) is set when the model stops in `TESTS_RUN_FAILED`.
- **A human must review:**
  - the advisory wording and thresholds in `memory.advisory()`;
  - the phase table in `workflow.py`;
  - the GitHub path against a real demo repository (it is only tested with mocked HTTP);
  - the realignment owner entry in `week-6-report.md`, which the team must fill in.

---

## 2026-10-21 — Week 8 final hardening: critical defect fixes and known limitations documentation

- **Tool / model:** Antigravity AI coding assistant.
- **Prompt given:** Fix critical defects before final presentation and document known limitations that remain, with evidence stored in `evidence/` (without adding new regression test functions).
- **Generated / modified:**
  - `src/tool_calling.py`: set `wf["stop_reason"] = "tool_error"` and record `tool_call_blocked` guardrail events when tool calls are refused by the allow-list or `workflow.check_call()` (resolving the EV-08/EV-18/EV-20/EV-41 stop-reason mislabelling defect); guard `graph.invoke(state)` in `run()` so live LLM failures after retries record an observability trace and return a clean `[ERROR]` message instead of an unhandled traceback; allow offline initialization when `GEMINI_API_KEY` is unset.
  - `src/sandbox.py`: block `from os import ...` and `from requests import ...` banned call imports and `Path.open()` write/append modes in `validate_generated_code()`; clamp `passed = max(0, ...)` in `_parse_junit()` and prioritize `failed`/`errors` over `no_tests` in `run_pytest()` so pytest collection errors (`tests=0, errors=1`) are never misclassified as `no_tests`.
  - `src/tracer.py`, `src/model_client.py`, `src/mcp_server.py`: apply `guardrails.redact()` across execution traces, model call logs, and MCP tool responses, and defer `GEMINI_API_KEY` enforcement in `model_client.py` from import time to `get_model_response()`.
  - `src/guardrails.py`: validate `isinstance(failing_tests, (list, tuple))` in `check_draft_fields()` and reject boolean `top_k` values in `check_query()`.
  - `tests/conftest.py`: redirect `tracer.DEFAULT_TRACE_FILE` to `tmp_path` so running `pytest` does not append test records to `evidence/traces/agent_traces.jsonl`.
  - `README.md` & `evidence/week8_defect_fixes_and_known_limitations.md`: documented all 6 critical defect fixes and 7 remaining known limitations.
- **Verified by the agent:** `python -m pytest tests/ sut/tests/ -v` passes (150 passed, 1 skipped) with a clean `git status` on `evidence/traces/agent_traces.jsonl`, and all 6 defect fixes verified via direct execution checks.
- **A human must review:**
  - `evidence/week8_defect_fixes_and_known_limitations.md` and the `Known Limitations` section in `README.md` prior to the final presentation.

## Week 8 - Move to create_agent, middleware and LangGraph Studio (2026-10-22)

- **Task:** Restructure the agent into the idiom taught in the AI engineering course so it runs and can be tested in LangGraph Studio.
- **AI use:** Claude Code did the migration from `skills.md` / `skills/studio-migration`. Files changed or added:
  - `src/agent.py`, `src/agent_state.py`, `src/agent_tools.py`, `src/guard_middleware.py`, `src/models.py`, `src/offline.py`, `src/tool_runner.py`, `studio/graph.py`, `langgraph.json`
  - removed `src/tool_calling.py` and `src/capture_week5_traces.py` (replaced by `src/capture_traces.py`)
- **What stayed deterministic:** phase machine, file pinning, hop budget (7), one tool call per step, secret redaction, unbacked-claim check. They now run as `InspectraGuard` middleware; human approval is `HumanInTheLoopMiddleware` (approve or reject only).
- **Checked by a human:** offline graph approve and reject paths on a real `langgraph dev` server; the full test suite; one live Gemini run (REQ-2.1, tests passed).
- **Not yet done:** Groq path untested (no key); sandbox hardening; 42-scenario re-run on the new graph.

### Week 8 addendum - configurable project and follow-ups (2026-10-22)

- **Task:** make the agent work on any project (paths as operator settings) and allow follow-up turns.
- **AI use:** Claude Code added `src/project_config.py` (INSPECTRA_REQUIREMENTS_DIR, INSPECTRA_CODE_DIR, INSPECTRA_CODE_MODULES), the `read_code` and `refine_tests` tools, `workflow.carry_over()` for follow-ups, prompt v2.1 and `prompts/v1.2_refine_tests.txt`, the offline graph `inspectra_offline_pass`, and a Groq key pattern in the redaction list.
- **Design choices a human should review:** a follow-up continues only after a passed run (or a test judged wrong) and only if the message names no requirement; saves still need human approval; read_code is limited to `.py` files inside the code folder.
- **Tested:** 192 tests pass (`tests/test_project_config.py`, `tests/test_followups.py`). Not yet tested live: follow-ups with Groq or Gemini, and the second sample project (a Gemini 503 and a DNS failure interrupted those runs).

### Week 8 addendum - Groq test writer and deployment check (2026-10-23)

- **Task:** make the agent deployable and testable before deployment.
- **AI use:** Claude Code added `pyproject.toml` and `.dockerignore` (a `langgraph build` failed because the top-level `src/` folder is a reserved package name), split `requirements.txt` from `requirements-dev.txt`, removed the hardcoded approval secret (a random per-process key is used when `APPROVAL_SECRET_KEY` is unset), added prompt v2.2, and added `INSPECTRA_TEST_WRITER=groq` after a Gemini ping took 203 s.
- **Found by testing:** Groq returned an empty reply for the test-writing prompt because its default 2048-token cap was used up by reasoning; `max_tokens` is now 8000 and the writer uses `reasoning_effort="low"`. A refinement of "negative balance" was first refused as ungrounded; the refine prompt now treats cases the requirement's rules determine as grounded.
- **Tested:** the Docker image builds, contains no `.env`, and loads all three graphs. Real Groq flow on REQ-2.1: propose (4 tests, passed), refine (5 tests, passed). One earlier run wrote a test that failed on correct code, so a model-written test can be wrong; the agent's code-defect or test-defect judgement and the human approval step exist for that.
