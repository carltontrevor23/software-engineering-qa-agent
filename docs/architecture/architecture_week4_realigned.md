# Architecture — Week 4 (realigned)

**Project:** Software-Engineering QA Agent (Inspectra)

This diagram replaces `inspectra_architecture_week4 (1).png`, which showed the agent calling the
subscription service. The agent now **tests** the subscription service (the system under test,
`sut/`); it never operates it.

```mermaid
flowchart LR
    dev([Developer])

    subgraph app["Inspectra (src/)"]
        orch["LangGraph orchestrator<br/>tool_calling.py<br/>allow-list, 1 call per step, MAX_HOPS"]
        gate{{"Approval gate<br/>approval.py<br/>HMAC single-use token"}}
        mem[("Case history<br/>memory.py<br/>data/memory/*.jsonl")]
    end

    gemini["Gemini<br/>model_client.py"]
    rag[("RAG: BM25 over<br/>docs/requirements/<br/>rag.py")]

    subgraph box["Sandbox (sandbox.py)"]
        gen["sandbox/generated/<br/>generated tests"]
        runner["pytest subprocess<br/>no shell, 60 s timeout,<br/>secret-free env"]
    end

    sut[("System under test<br/>sut/subscription_service/<br/>sut/tests/")]
    drafts[("evidence/issues/drafts/")]
    filed[("evidence/issues/filed/")]

    dev -- "Check REQ-2.1" --> orch
    orch <-- "decide next tool" --> gemini
    orch -- "search_requirements" --> rag
    orch -- "propose_tests" --> gemini
    gemini -. "pytest code (policy-checked)" .-> gen
    orch -- "run_tests" --> runner
    runner -- "imports (read-only)" --> sut
    gen --> runner
    orch -- "draft_issue" --> drafts
    orch -- "file_issue / save_test_to_suite" --> gate
    gate -- "human: y/N" --> dev
    gate -- "approved" --> filed
    gate -- "approved" --> sut
    orch -- "record outcome" --> mem
    mem -. "shown to the human only" .-> gate
```

## Boundaries

| Component | Deterministic or AI | Notes |
|---|---|---|
| Requirement IDs (`REQ-X.Y`) | Deterministic | Parsed from `## Section X.Y:` headings |
| Retrieval | Deterministic (BM25) | Week 3 pipeline, unchanged |
| Choosing the next tool, writing test code, summarising failures | AI (Gemini) | Bounded by the allow-list and hop limit |
| Code policy check, path checks, timeout, env scrubbing | Deterministic | `sandbox.py` |
| Filing an issue, changing `sut/tests/` | Human decision | Token minted only after approval; verified inside the tool |
| Editing SUT source, merging, deploying, secrets, shell | Not possible | No tool exposes these actions |

The case history (dotted line) is printed for the human approver only. It is never sent to the
model and is not part of the arguments bound into the approval token.
