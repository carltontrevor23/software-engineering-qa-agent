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
   - `INSPECTRA_MODEL`: which model drives the agent: `groq` (default), `gemini` or `scripted`
     (no key, no network).
   - `GROQ_API_KEY`: needed for `INSPECTRA_MODEL=groq`. Free key at https://console.groq.com.
   - `GEMINI_API_KEY`: needed for `INSPECTRA_MODEL=gemini`, and for the live `propose_tests` call,
     which uses Gemini through `src/model_client.py`. Free key at https://aistudio.google.com.
     Importing the code never needs a key; a missing key is reported when a graph is built or used.
   - `GITHUB_TOKEN`, `GITHUB_REPO`: optional. When both are set, approved issues are filed on
     GitHub. Use a fine-grained token limited to *Issues: write* on a dedicated demo repository.

The free Gemini tier allows about 20 requests per day per model; one live end-to-end run uses about
5–8. Use the offline graph or `--offline` for rehearsals.

## Running the tests

```
venv\Scripts\python -m pytest tests/ sut/tests/ -v
```

The tests make no real model calls or GitHub calls. Memory, sandbox and issue folders are redirected
to temp directories.

## Running the agent in LangGraph Studio

```
venv\Scripts\langgraph dev --no-reload      # API on http://127.0.0.1:2024
```
Then open https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024 . (Keep `--no-reload`:
the agent writes generated tests and issue drafts inside the project, and the file watcher would
restart the server in the middle of a run.)

Two graphs are served (see [`langgraph.json`](langgraph.json)):

| Graph | Model | Use it for |
|---|---|---|
| `inspectra_offline` | scripted, with fixture tests and a **planted bug** | rehearsals and the demo: no network, no quota |
| `inspectra` | `INSPECTRA_MODEL` (Groq by default) | the live agent |

Send a message such as `Check REQ-2.1 (Tier Upgrades) against the code.` The state panel shows the
workflow fields (`phase`, `test_outcome`, `stop_reason`, ...) after every step. When the agent wants
to file an issue it **pauses on an approve/reject card** (with the requirement's recent test runs
and an advisory); approve to file it, reject to stop with `human_rejection`.

## Running the agent on the command line

```
python src/agent.py "Check REQ-2.1 against the code"
```
Prints the final answer and the stop reason. The approval step asks `Authorize this action? [y/N]`
on the terminal.

**Demo runner:**
```
python demo/run_demo.py                          # REQ-2.1, correct SUT, live model
python demo/run_demo.py --planted-bug            # boundary defect planted in a temp copy of sut/
python demo/run_demo.py --planted-bug --offline  # no network: scripted model + fixture tests
python demo/run_demo.py --requirement REQ-2.4    # another requirement
```
- `--planted-bug` changes `if balance < self.UPGRADE_COST:` to `<=` **in a temporary copy only**,
  so the exact-$50.00 boundary test fails.
- `--offline` labels every line `[SCRIPTED LLM]`.
- The runner prints one line per hop (tool, status, test outcome, workflow phase), each approval
  decision, and the final stop reason.

**Trace capture:** `python src/capture_traces.py` runs three scenarios and writes
`evidence/traces/week8_traces.jsonl` and `evidence/week8_execution_traces.md`.

## Checking your own project

By default the agent checks the bundled sample (`docs/requirements` and `sut/`). To check
another project, set these in `.env` (the operator sets them; the model cannot):

| Setting | Meaning |
|---|---|
| `INSPECTRA_REQUIREMENTS_DIR` | Folder of `.md` requirement files. Each requirement is a `## Section X.Y: Title` heading (it becomes `REQ-X.Y`) followed by its acceptance criteria. |
| `INSPECTRA_CODE_DIR` | The folder that holds the importable package(s) under test (the folder you would put on `PYTHONPATH`). Approved tests are saved to its `tests/` folder. It cannot be this repository's root. |
| `INSPECTRA_CODE_MODULES` | Optional. Comma-separated `.py` files, relative to the code folder, shown to the test writer. Default: every non-test `.py` file. |

Check the setup, then restart the server (or rerun the CLI):

```
venv\Scripts\python.exe src\project_config.py
```

Limits: one project per server (restart after changing `.env`); only `.md` requirements; the
code is read from a local folder (no GitHub or pull-request source yet); generated tests may
import only the standard test libraries, `requests` and the project's own packages. The offline
graph and `--planted-bug` demo always use the bundled sample.

## Running the MCP server

```
python src/mcp_server.py          # terminal 1: listens on http://127.0.0.1:8000/mcp; approve/reject here
python src/mcp_demo_client.py     # terminal 2: walks REQ-2.1 through the tools
```
The server applies the same phase guard, sandbox and human approval as the agent (approval on its
own console), and refuses client-supplied approval tokens. See [`docs/architecture/mcp_interface_spec.md`](docs/architecture/mcp_interface_spec.md).

## Repository map

```
sut/                          # SYSTEM UNDER TEST (the agent tests this, never edits it)
  subscription_service/       #   subscription_manager.py
  tests/                      #   human-written baseline tests (+ approved generated tests)
langgraph.json                # LangGraph Studio config: graphs inspectra, inspectra_offline
studio/graph.py               # async graph factories served by Studio
skills.md, skills/            # coding-agent skills for the Week 8 migration (see skills.md)
src/
  agent.py                    # create_agent assembly, AGENT_CONTRACT, CLI (build_agent, run)
  agent_tools.py              # the six approved tools (the allow-list)
  agent_state.py              # InspectraState: messages + workflow fields
  guard_middleware.py         # request validation, phase guard, state updates, answer checks, approval gate
  models.py                   # model factory: groq | gemini | scripted (chosen at build time)
  offline.py                  # offline agent: scripted model + fixture tests + planted bug
  tool_runner.py              # console-approval tool runner (used by the MCP server)
  workflow.py                 # phase machine: allowed tools per phase, file pinning, stop reasons
  qa_tools.py                 # tool implementations (search, propose, run, draft, file, save)
  sandbox.py                  # pytest runner: allow-listed paths, no shell, timeout, no secrets
  approval.py                 # HMAC single-use approval tokens + console approval (MCP server)
  memory.py                   # requirement test-run history (advisory for the approver)
  rag.py                      # BM25 retrieval over docs/requirements
  model_client.py             # Gemini client for test proposals, prompt templates, call logging
  demo_support.py             # scripted LLM, planted bug, tracing (demo, traces, tests)
  mcp_server.py, mcp_demo_client.py
  capture_traces.py, run_rag_evaluation.py
demo/                         # run_demo.py + fixtures/req_2_1_tests.py
prompts/                      # versioned prompts (agent v2.0, test proposal v1.0/v1.1 + addendum)
docs/
  requirements/               # requirement corpus (REQ-2.1 ... REQ-2.6)
  architecture/               # architecture, task contract, control loop, state model, memory, MCP
  tools/tool_catalogue.md
  evaluation/                 # evaluation cases and RAG questions
  weekly-reports/
  ai-engineering-log.md
evidence/                     # test evidence, traces, issue drafts/filed, legacy/ (superseded)
tests/                        # agent, tools, memory, MCP, RAG tests (harness.py: shared helpers)
sandbox/generated/            # generated tests (git-ignored)
data/                         # runtime memory (git-ignored)
```

## Model

The agent loop uses the model chosen by `INSPECTRA_MODEL`: Groq `openai/gpt-oss-20b` by default
(`GROQ_MODEL` to change), Gemini (`MODEL_NAME`, default `gemini-3.8-flash`), or the scripted offline
model. Test proposals (`propose_tests`) call Gemini through the Google GenAI SDK in
`src/model_client.py`, except in the offline graph, which uses fixture tests.

## Notes for the team

- Prompts live in `prompts/`, one file per version. Never edit an old version in place.
- Record material AI-assisted changes in `docs/ai-engineering-log.md`.
- Superseded subscription-agent evidence is kept in `evidence/legacy/`.
