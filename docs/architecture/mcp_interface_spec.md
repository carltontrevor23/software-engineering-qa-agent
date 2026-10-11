# MCP Interface Specification — Week 6 (realigned)

**Project:** Software-Engineering QA Agent (Inspectra)
**Server:** [`src/mcp_server.py`](../../src/mcp_server.py) (`FastMCP("inspectra-qa")`, streamable HTTP at `http://127.0.0.1:8000/mcp`)
**Client:** [`src/mcp_demo_client.py`](../../src/mcp_demo_client.py)
**Tests:** [`tests/test_mcp_server.py`](../../tests/test_mcp_server.py)

This replaces the earlier spec, which exposed the subscription tools. The old version is in git
history.

## 1. Overview

The server exposes Inspectra's QA capabilities to any MCP client (an IDE assistant, another
agent). It reuses the agent's own controls instead of re-implementing them:
- the same tool functions (`qa_tools.py`);
- the same human approval gate and signed tokens (`tool_calling._run_one_tool`, `approval.py`);
- the same phase guard and file pinning (`workflow.py`), kept per server session;
- the same sandbox (`sandbox.py`).

**Transport.** Streamable HTTP, not stdio, because the human approval prompt uses `input()` on the
server's console, and stdio would use stdin for the protocol itself.

**Session.** The server keeps one workflow (phase, requirement, test file, draft) at a time.
`start_check` resets it. Every result carries the current `phase`.

Run it:
```
python src/mcp_server.py          # terminal 1 (approve/reject here)
python src/mcp_demo_client.py     # terminal 2
```

## 2. Capabilities

| Capability | Impact | Allowed in phase |
|---|---|---|
| `start_check` | None (resets the session) | Any |
| `search_requirements` | Low, read-only | `START`, `REQUIREMENT_RESOLVED` |
| `propose_tests` | Low, writes only to `sandbox/generated/` | `START`, `REQUIREMENT_RESOLVED`, `TESTS_RUN_FAILED` (one regenerate) |
| `run_tests` | Low, sandboxed | `TESTS_PROPOSED` |
| `draft_issue` | Low, local draft | `TESTS_RUN_FAILED` |
| `file_issue` | **High**, human approval | `ISSUE_DRAFTED` |
| `save_test_to_suite` | **High**, human approval | `TESTS_RUN_PASSED` |

## 3. Contracts

Every result is a JSON object with `status` (`success`, `error` or `approval_required`) and `phase`.

### 3.1 `start_check()`
- **Output:** `{"status": "success", "phase": "START"}`

### 3.2 `search_requirements(query: str, top_k: int = 3)`
- **Output:** `results: [{requirement_id, source_file, score, text}]`, or an empty list with
  `note: "NO_RELEVANT_REQUIREMENTS_FOUND"` (the phase becomes `STOPPED`).
- **Failures:** missing corpus → `error`.

### 3.3 `propose_tests(requirement_id: str)`
- **Output:** `requirement_id`, `test_file`, `test_count`.
- **Failures:** unknown id, model unavailable, model refusal, generated code rejected by the
  sandbox policy → `error`, and nothing is written.

### 3.4 `run_tests(requirement_id: str, test_file: str)`
- **Output:** `test_outcome` (`passed` / `failed` / `no_tests`), `passed`, `failed`, `errors`,
  `failures: [{test_name, message}]`.
- **Failures:** `test_file` is not the file proposed in this session → `error`, not run. Also
  `error` for a path outside the sandbox folders, a missing file, a policy violation, or the 60 s timeout.

### 3.5 `draft_issue(requirement_id: str, title: str, summary: str, failing_tests: list[str])`
- **Output:** `draft_path` (in `evidence/issues/drafts/`).
- **Failures:** unknown requirement → `error`.

### 3.6 `file_issue(draft_path: str, approval_token: str | null = null)` — HIGH impact
- **Behaviour:** the server console prints the test-run history and advisory, then asks the human.
  On approval it mints a signed single-use token internally, and the tool files the draft:
  - on GitHub (`channel: "github"`, `issue_url`) when `GITHUB_TOKEN` and `GITHUB_REPO` are set;
  - otherwise locally (`channel: "local"`, `filed_path`).
- **Failures:**
  - any client-supplied `approval_token` → `error` (refused);
  - not the draft from this session → `error`;
  - human rejects → `approval_required`;
  - GitHub HTTP error or timeout → `error`, the draft is kept, and nothing is filed locally.

### 3.7 `save_test_to_suite(test_file: str, approval_token: str | null = null)` — HIGH impact
- **Behaviour:** same approval flow; copies the passing generated test into `sut/tests/`.
- **Failures:** client token refused; not the session's test file; human rejects; file outside
  `sandbox/generated/`.

## 4. Permissions

| Action | Who decides |
|---|---|
| Search, propose, run, draft | The client, within the phase rules |
| File an issue, change `sut/tests/` | **The human at the server console only** |
| Approval tokens | Minted by the server after a human "y"; never accepted from or returned to clients |
| GitHub credentials | Server environment only (`.env`); never sent to clients or the model |

## 5. Security boundary

1. **Server-side approval only.** `file_issue` and `save_test_to_suite` refuse any `approval_token`
   from the client. Tokens are HMAC-signed, bound to the tool and its exact arguments, single use,
   and valid for 120 s.
2. **Sandbox.** `run_tests` runs pytest without a shell, with a 60 s timeout, only on allow-listed
   folders, and with an environment that has no `GEMINI_API_KEY`, `GITHUB_TOKEN` or other
   variables. Generated code must pass the import allow-list.
3. **Phase guard.** Out-of-order calls are refused without being executed. `run_tests`,
   `save_test_to_suite` and `file_issue` are pinned to the files produced earlier in the same session.
4. **No secrets exposed.** Results never include the Gemini key, the GitHub token or approval
   tokens. Test-run history is printed on the server console, not returned to clients.

### What a malicious client can and cannot do

| A malicious client **can** | A malicious client **cannot** |
|---|---|
| Search requirements and read their text | File an issue or change `sut/tests/` without the human at the console saying yes |
| Trigger test generation (spending model quota) | Forge or replay an approval token |
| Run the session's generated tests in the sandbox (CPU up to 60 s per run) | Run arbitrary files, shell commands or tests outside the sandbox folders |
| Create local issue drafts | File a different draft than the one written in its session |
| Reset the session with `start_check` | Read secrets, other requirements' history, or the GitHub token |
| Ask the human to approve something misleading | Make the approval prompt hide which tool and arguments are being approved |

**Remaining risks:** the server binds to localhost without client authentication, so anyone on the
machine can call it. There is one shared session. And the human can still be persuaded to approve
a bad draft. These are acceptable for a local demo, not for a shared deployment.

## 6. Example interaction (verified 2026-10-11, offline model, planted defect)

```
Tools exposed: ['start_check', 'search_requirements', 'propose_tests', 'run_tests', 'draft_issue', 'file_issue', 'save_test_to_suite']
0. file_issue before anything else (phase guard):
  {'status': 'error', 'error': 'Tool file_issue is not allowed in phase START.', 'phase': 'START'}
1. search_requirements:   {'status': 'success', 'phase': 'REQUIREMENT_RESOLVED'}
2. propose_tests:         {'status': 'success', 'requirement_id': 'REQ-2.1', 'test_count': 3, 'phase': 'TESTS_PROPOSED', ...}
3. run_tests:             {'status': 'success', 'test_outcome': 'failed', 'passed': 2, 'failed': 1, 'phase': 'TESTS_RUN_FAILED', ...}
4. draft_issue:           {'status': 'success', 'draft_path': '...ISSUE-REQ-2.1-20261011T054617Z.md', 'phase': 'ISSUE_DRAFTED'}
5a. file_issue with a forged token:
  {'status': 'error', 'error': 'Client-supplied approval tokens are not accepted. ...', 'phase': 'ISSUE_DRAFTED'}
5b. file_issue (approved on the server console):
  {'status': 'success', 'filed_path': '...ISSUE-REQ-2.1-20261011T054617Z.md', 'channel': 'local', 'phase': 'DONE'}

Server console:
[CASE HISTORY] REQ-2.1: run_tests -> failed (1 failed) 2026-10-11
[ADVISORY] FIRST RUN: no earlier test runs to compare with. (advisory only - the decision is yours)
```
