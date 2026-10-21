# software-engineering-qa-agent (Inspectra)

An AI-native **software-engineering QA agent** for the BSE4104 capstone. For one requirement of a
system under test, Inspectra:
1. finds the requirement (BM25 retrieval over `docs/requirements/`);
2. asks the model to propose pytest tests;
3. runs them in a sandbox;
4. if the code contradicts the requirement, drafts an issue, which **a human approves or rejects**
   before it is filed (locally, or on GitHub).

The system under test is a small subscription service in [`sut/`](sut/). The agent tests it; it
never operates it. The agent cannot merge, deploy, read secrets, run arbitrary shell commands, or
edit the SUT source.

## Setup

1. **Create and activate a virtual environment**
   ```
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # macOS / Linux
   ```
2. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```
3. **Configure `.env`** (never commit it; it is git-ignored)
   ```
   cp .env.example .env
   ```
   - `GEMINI_API_KEY`: required for live model calls (`src/model_client.py` and `src/tool_calling.py`).
     Offline rehearsals (`--offline`) and the automated test suite (`pytest`) run without a key.
     Get a free key at https://aistudio.google.com.
   - `GITHUB_TOKEN`, `GITHUB_REPO`: optional. When both are set, approved issues are filed on
     GitHub. Use a fine-grained token limited to *Issues: write* on a dedicated demo repository.

The free Gemini tier allows about 20 requests per day per model; one live end-to-end run uses about
5–8. Use `--offline` for rehearsals.

## Running the tests

```
venv\Scripts\python -m pytest tests/ sut/tests/ -v
```

The tests make no real model calls or GitHub calls. Memory, sandbox, trace and issue folders are
redirected to temp directories.

## Running the agent

**CLI (live model):**
```
python src/tool_calling.py "Check REQ-2.1 against the code"
```
It prints the final answer and the stop reason. High-impact steps stop at an interactive
`Authorize this action? [y/N]` prompt.

**Demo runner:**
```
python demo/run_demo.py                          # REQ-2.1, correct SUT, live model
python demo/run_demo.py --planted-bug            # boundary defect planted in a temp copy of sut/
python demo/run_demo.py --planted-bug --offline  # no model calls: scripted LLM + fixture tests
python demo/run_demo.py --requirement REQ-2.4    # another requirement
```
- `--planted-bug` changes `if balance < self.UPGRADE_COST:` to `<=` **in a temporary copy only**,
  so the exact-$50.00 boundary test fails.
- `--offline` labels every line `[SCRIPTED LLM]`.
- The runner prints one line per hop (tool, status, test outcome, workflow phase) and the final
  stop reason. At the approval prompt it shows the requirement's recent test runs and an
  advisory (`FIRST FAILURE` / `RECURRING`).

**Trace capture:** `python src/capture_week5_traces.py` writes the three Week 5 traces to
`evidence/traces/week5_live_traces.jsonl` and `evidence/week5_live_execution_traces.md`.

## Running the MCP server

```
python src/mcp_server.py          # terminal 1: listens on http://127.0.0.1:8000/mcp; approve/reject here
python src/mcp_demo_client.py     # terminal 2: walks REQ-2.1 through the tools
```
The server applies the same phase guard, sandbox, secret redaction and human approval as the agent,
and refuses client-supplied approval tokens. See [`docs/architecture/mcp_interface_spec.md`](docs/architecture/mcp_interface_spec.md).

## Repository map

```
sut/                          # SYSTEM UNDER TEST (the agent tests this, never edits it)
  subscription_service/       #   subscription_manager.py
  tests/                      #   human-written baseline tests (+ approved generated tests)
src/
  tool_calling.py             # LangGraph agent: tools, AgentState, approval hand-off, CLI
  workflow.py                 # phase machine: allowed tools per phase, file pinning, stop reasons
  qa_tools.py                 # tool implementations (search, propose, run, draft, file, save)
  sandbox.py                  # pytest runner: allow-listed paths, no shell, timeout, no secrets
  approval.py                 # human approval gate + HMAC single-use tokens
  guardrails.py               # deterministic input/output validation and secret redaction
  tracer.py                   # 6-dimensional JSONL execution tracing and observability
  memory.py                   # requirement test-run history (advisory for the approver)
  rag.py                      # BM25 retrieval over docs/requirements
  model_client.py             # Gemini client, prompt templates, call logging
  demo_support.py             # scripted LLM, planted bug, tracing (demo, traces, tests)
  mcp_server.py, mcp_demo_client.py
  capture_week5_traces.py, run_rag_evaluation.py
demo/                         # run_demo.py + fixtures/req_2_1_tests.py
prompts/                      # versioned prompts (agent v2.0, test proposal v1.0/v1.1 + addendum)
docs/
  requirements/               # requirement corpus (REQ-2.1 ... REQ-2.6)
  architecture/               # architecture, task contract, control loop, state model, memory, MCP
  tools/tool_catalogue.md
  evaluation/                 # evaluation cases, RAG questions, criteria, failure catalogue
  weekly-reports/
  ai-engineering-log.md
evidence/                     # test evidence, traces, issue drafts/filed, defect & limitation logs
tests/                        # agent, tools, guardrails, observability, memory, MCP, RAG tests
sandbox/generated/            # generated tests (git-ignored)
data/                         # runtime memory (git-ignored)
```

## Model

Gemini (`MODEL_NAME` in `.env`, default `gemini-3.8-flash`). It is called through LangChain for the
agent loop and through the Google GenAI SDK for test proposals.

## Known Limitations

Full defect remediation and limitation evidence is recorded in
[`evidence/week8_defect_fixes_and_known_limitations.md`](evidence/week8_defect_fixes_and_known_limitations.md).
The remaining architectural and operational limitations are:

1. **Single-Module SUT Scope & Partial Feature Coverage (`sut/`, `src/qa_tools.py`)**
   - `propose_tests` is bound to a single system-under-test module
     (`sut/subscription_service/subscription_manager.py`) rather than arbitrary multi-file or
     multi-repository codebases.
   - While `docs/requirements/` contains six requirements (`REQ-2.1` through `REQ-2.6`), only
     `REQ-2.1` (Tier Upgrades) is implemented in `subscription_manager.py`. Running the agent on
     `REQ-2.2`–`REQ-2.6` exercises missing-feature detection (`EV-17`) rather than passing tests.
2. **Offline Rehearsal Fixture Scope (`demo/run_demo.py`, `src/demo_support.py`)**
   - `--offline` mode uses a deterministic `ScriptedLLM` and the hand-written `REQ-2.1` test
     fixture (`demo/fixtures/req_2_1_tests.py`). It is intended for quota-free presentation
     rehearsals on `REQ-2.1`, not general offline test synthesis for other requirements.
3. **Process-Level Sandbox Rather Than OS Containerization (`src/sandbox.py`)**
   - Tests run in an isolated `pytest` subprocess (`shell=False`, 60 s timeout, minimal
     secret-free environment, static AST allow-list/denylist), not an OS container (Docker/seccomp).
   - Static AST inspection blocks dangerous imports, dynamic builtins (`eval`, `exec`, `__import__`),
     mutating `os`/`pathlib` calls, write/append `open()`, and outbound `requests` calls, but
     generated tests can still read local files on disk or consume CPU/memory up to the 60 s timeout.
4. **Lexical BM25 Retrieval Without Semantic Embeddings (`src/rag.py`)**
   - `search_requirements` uses pure-Python Okapi BM25 over Markdown chunks. Queries that
     paraphrase requirements without sharing lexical terms or identifiers with the specification
     may score below `min_score = 1.0` and return `NO_RELEVANT_REQUIREMENTS_FOUND`.
5. **Pattern-Based Output Verification & Test Oracle Quality (`src/guardrails.py`)**
   - `check_final_answer()` uses regex sentence rules to block unsupported `"tests passed"` or
     `"issue filed"` claims, which may miss unusually phrased claims.
   - `run_tests` verifies syntactic and runtime execution in `pytest`, but cannot guarantee that
     passing LLM-generated assertions deeply test every semantic nuance of a requirement without
     human review at the approval gate.
6. **In-Memory Session State & Single-Process Locking (`src/mcp_server.py`, `src/memory.py`, `src/approval.py`)**
   - `mcp_server.py` keeps a single shared `_session` workflow in memory on `127.0.0.1:8000`
     without client authentication (suitable for local single-developer use, not multi-tenant
     deployment).
   - `approval.py` tracks consumed token nonces (`_CONSUMED_NONCES`) in process memory, and
     `memory.py` uses a `threading.Lock` (thread-safe within one process, not across separate OS
     processes) with manual/scheduled invocation of `purge_expired_records()`.
7. **Free-Tier Gemini Quota & Rate-Limit Latency (`src/model_client.py`, `src/tool_calling.py`)**
   - Free-tier Gemini limits (~20 requests/day per model) constrain back-to-back live runs and
     introduce 32–65 s retry delays when `429 RESOURCE_EXHAUSTED` or `503` responses occur.

## Notes for the team

- Prompts live in `prompts/`, one file per version. Never edit an old version in place.
- Record material AI-assisted changes in `docs/ai-engineering-log.md`.
- Superseded subscription-agent evidence is kept in `evidence/legacy/`.
