---
name: verify-and-release
description: Guides agents through re-running the 42 scenarios, capturing Studio traces, and updating docs so a fresh clone reaches the demo. Use before tagging the Week 8 release.
---

# Verify and Release

## Overview
Done means the same 42 scenarios (`docs/evaluation/final_evaluation_scenarios.json`) give the same or better results, and the docs describe the new graph.

## When to Use
After `studio-migration` and `sandbox-hardening`.

## Process
1. Run the 31 deterministic scenarios on the new graph; run the 11 live ones only with quota or Groq, and state which model ran. Write `evidence/traces/evaluation_results_v2.0_studio.json` and diff against the previous results. A critical regression must be fixed.
2. Enable LangSmith (`LANGSMITH_TRACING=true`, project `inspectra`). Capture three traces (pass; code defect, filed; tool failure with recovery) to `evidence/traces/week8_studio_*.jsonl`.
3. Update `README.md` (Studio steps, env table, two graphs), `docs/architecture/*` (middleware and approval design, token decision), `docs/ai-engineering-log.md`, and the missing weekly reports (5, 7, 8).
4. Tag `v1.0.0` only when asked. Never push or merge unasked.

## Rationalizations
| Excuse | Reality |
|---|---|
| "Live scenarios skipped, close enough." | Say they were skipped; never imply they ran. |

## Red Flags
A critical scenario flipping to fail; README steps never run on a clean checkout.

## Verification
- [ ] No critical regression; results and three traces committed.
- [ ] README reaches the `inspectra_offline` demo from a fresh clone.
