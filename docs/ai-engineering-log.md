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
