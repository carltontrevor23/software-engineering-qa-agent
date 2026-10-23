---
name: studio-migration
description: Guides agents through moving Inspectra from a hand-built StateGraph with input() approval to create_agent plus middleware, runnable in LangGraph Studio. Use when starting the Week 8 migration or when Studio fails to load the graph.
---

# Studio Migration

## Overview
Behaviour stays the same; the wiring changes to the course idiom (`ai-engineering/notebooks/module-1/studio/{middleware,mcp}.py`). `src/workflow.py` and `src/guardrails.py` remain the source of truth; middleware only calls them.

## When to Use
First, on branch `week8`.

## Process
1. **Scaffold.** Add `langgraph-cli[inmem]` to `requirements.txt` and install. Add root `langgraph.json` pointing at `./studio/graph.py:make_graph` (async). No side effects at import: no key checks, file reads or model construction.
2. **Models.** `src/models.py`: `get_chat_model()` by `INSPECTRA_MODEL` = `groq` (default, `openai/gpt-oss-20b`) | `gemini` | `scripted` (wrap the scripted LLM in `demo_support.py`). Raise missing-key errors inside the factory. Replace `time.sleep(32)` with `ModelRetryMiddleware` and `ModelFallbackMiddleware`.
3. **Tools and state.** Move the six `@tool`s unchanged to `src/agent_tools.py`. `InspectraState(AgentState)` with `workflow.FIELDS`, passed as `state_schema=`.
4. **Guards** in `src/middleware.py`: `@before_agent` input validation; async `@wrap_tool_call` phase guard (blocked or unknown call returns an error `ToolMessage` and never executes; one call per step); after each tool apply `workflow.apply_result`, redact, `memory.record_case`; `@after_agent` answer check and `finalize_on_answer`; `ModelCallLimitMiddleware(run_limit=7)` mapped to `hop_budget_exhausted`.
5. **Approval.** `HumanInTheLoopMiddleware` for `file_issue` and `save_test_to_suite` with `allowed_decisions=["approve","reject"]` (no edit). The card shows requirement id, path and the memory advisory (human-only). Reject maps to `human_rejection`. After approval the guard mints the single-use HMAC token the tool verifies (the MCP server mints its own after console approval); removing the hardcoded `DEFAULT_SECRET` belongs to sandbox-hardening.
6. **Offline graph.** Register `inspectra_offline` (scripted model, planted bug in a temp copy of `sut/`). Port `demo/run_demo.py`, keeping its flags.

## Rationalizations
| Excuse | Reality |
|---|---|
| "Put the rules in the prompt." | Prompts are requests; the guard is enforcement. |
| "Delete the test that no longer fits." | Port it; never delete to go green. |
| "Allow edit in the approval card." | Edit lets arguments change after approval. |

## Red Flags
Import-time `raise`; state written from model text; sync `wrap_*` hooks; a blocked call reaching a human.

## Verification
- [ ] All modules import with no API keys set.
- [ ] `venv\Scripts\python.exe -m pytest tests/ sut/tests/ -q` stays green (baseline 139).
- [ ] In Studio, `inspectra_offline` on REQ-2.1 with the planted bug reaches an approve/reject card; approve gives `issue_filed`, reject gives `human_rejection`.
