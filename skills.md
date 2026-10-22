# skills.md — Inspectra Week 8

Format follows [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills): one folder per
skill, `skills/<name>/SKILL.md`. Work on branch `week8`. Run the skills in order; each ends with a
Verification checklist that must hold before the next starts. Read only the skill you are on.

| # | Skill | Outcome |
|---|---|---|
| 1 | [studio-migration](skills/studio-migration/SKILL.md) | `create_agent` + middleware + interrupt approval, runs in Studio, offline demo graph |
| 2 | [sandbox-hardening](skills/sandbox-hardening/SKILL.md) | Validator bypasses closed, test runs isolated from secrets |
| 3 | [verify-and-release](skills/verify-and-release/SKILL.md) | 42 scenarios re-run, traces captured, docs updated |

## Behaviour to preserve

`search_requirements` → `propose_tests` (to `sandbox/generated/` only) → `run_tests` (sandboxed pytest)
→ judge code vs test defect (one regenerate) → `draft_issue` → `file_issue` / `save_test_to_suite`
(human approval). It never merges, deploys, reads secrets, runs arbitrary shell, or edits
`sut/subscription_service/`.

## Invariants

- Exactly six tools; phase guard in `src/workflow.py` stays the source of truth.
- State comes from tool results, never model text; the model cannot approve its own actions.
- Unbacked "passed" / "filed" claims are withheld; secrets are redacted; never print `.env` values.
- Stop reasons unchanged; 7 round trips, one tool call per step.
- Never edit an old prompt version or `sut/subscription_service/`; log changes in
  `docs/ai-engineering-log.md`.

## Facts

- Use `venv\Scripts\python.exe` (bash `python` is broken). Baseline: `-m pytest tests/ sut/tests/ -q`
  → 139 passed. Re-run after each skill.
- Gemini free tier ≈ 20 requests/day; rehearse with the scripted model.
- Reference: `ai-engineering/notebooks/module-1/studio/{middleware,mcp}.py`. Verify any LangChain API
  against installed source before use; `wrap_*` hooks are async in Studio; pass no checkpointer.

## Rules

One skill = one commit on `week8`. No push, merge or tag unless asked. Never delete a test to go green.
Report what ran, what passed, and what was skipped.
