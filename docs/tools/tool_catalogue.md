# Tool Catalogue — Week 4 (realigned)

**Project:** Software-Engineering QA Agent (Inspectra)
**Code:** implementations in [`src/qa_tools.py`](../../src/qa_tools.py) and [`src/sandbox.py`](../../src/sandbox.py); LangChain wrappers in [`src/agent_tools.py`](../../src/agent_tools.py)
**Tests:** [`tests/test_tool_failures.py`](../../tests/test_tool_failures.py)

This catalogue replaces the Week 4 subscription-tool catalogue (`get_user_subscription_status`,
`upgrade_user_subscription`), which made the agent *operate* the subscription service instead
of *testing* it. That version is in git history.

## Workflow and impact levels

```
search_requirements -> propose_tests -> run_tests -> draft_issue -> file_issue
                                                  \-> save_test_to_suite (optional)
```

| Tool | Impact | Authorization | Side effect |
|---|---|---|---|
| `search_requirements` | Low | Automatic | None (read-only) |
| `propose_tests` | Low | Automatic | Writes one file to `sandbox/generated/` (git-ignored scratch) |
| `run_tests` | Low | Automatic, sandboxed | Runs pytest in a separate process |
| `draft_issue` | Low | Automatic | Writes one Markdown draft to `evidence/issues/drafts/` |
| `file_issue` | **High** | Human approval + signed single-use token | Files the issue (`evidence/issues/filed/`) |
| `save_test_to_suite` | **High** | Human approval + signed single-use token | Copies a test into `sut/tests/` (a repo change) |

Common result rules:
- Every tool returns a dict with `status`: `success`, `error` or `approval_required`.
  `status` is the tool's own outcome. `run_tests` reports the tests' result separately in `test_outcome`.
- Expected failures never raise: they return `{"status": "error", "error": "<reason>"}`.
- Missing or wrongly typed arguments are rejected by the Pydantic schema before the tool runs.
- Only these six tools exist. Any other tool name is refused by the allow-list in `InspectraGuard` (`src/guard_middleware.py`).
- The agent may not merge, deploy, read secrets, run arbitrary shell commands or edit the
  SUT source (`sut/subscription_service/`). No tool offers those actions.

Requirement IDs come from the headings in `docs/requirements/*.md`: `## Section 2.1: Tier Upgrades`
becomes `REQ-2.1`. The mapping is deterministic (no LLM).

---

## 1. `search_requirements` — low impact

**Purpose:** find the requirement a developer is asking about (Week 3 BM25 RAG over `docs/requirements/`).

**Input schema**
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "Free-text search, e.g. 'tier upgrade balance'."},
    "top_k": {"type": "integer", "default": 3}
  },
  "required": ["query"]
}
```

**Output schema**
```json
{
  "status": "success | error",
  "results": [
    {"requirement_id": "REQ-2.1", "source_file": "docs/requirements/subscription.md",
     "score": 4.21, "text": "<matching acceptance criterion>"}
  ],
  "note": "NO_RELEVANT_REQUIREMENTS_FOUND (only when results is empty)"
}
```

**Failure behaviour:** no hits returns `success` with an empty list and the note, so the agent
can say "no requirement found" instead of guessing. A missing corpus returns `error`.

---

## 2. `propose_tests` — low impact

**Purpose:** ask Gemini for pytest tests for one requirement and save them in the sandbox.

**How:** builds the prompt from `prompts/v1.1_test_proposal.txt`. The `{{module_description}}` is
the SUT source plus its import line, and `{{requirements_excerpt}}` is the requirement text. It
then appends `prompts/v1.1_pytest_output_addendum.txt`, which asks for one runnable
```` ```python ```` block. Calls are logged under prompt version `v1.1+pytest-addendum-v1`.

**Input schema**
```json
{"type": "object", "properties": {"requirement_id": {"type": "string"}}, "required": ["requirement_id"]}
```

**Output schema**
```json
{"status": "success | error", "requirement_id": "REQ-2.1",
 "test_file": "<abs path>/sandbox/generated/test_req_2_1_<8 hex>.py", "test_count": 7}
```

**Failure behaviour** (nothing is written in any of these cases):

| Condition | Result |
|---|---|
| Unknown requirement id | `error`: `Unknown requirement 'REQ-9.9'.` |
| Model unavailable (quota, network, key) | `error`: `Model unavailable, no tests proposed: ...` |
| Model refuses (`NO_GROUNDED_TESTS_FOUND`) | `error` carrying the refusal text |
| Reply has no python code block | `error` |
| Code fails the sandbox policy (below) | `error`: `Generated tests rejected by sandbox policy: ...` |

---

## 3. `run_tests` — low impact (sandboxed)

**Purpose:** run one test file and report pass/fail with failure messages.

**Input schema**
```json
{"type": "object",
 "properties": {"requirement_id": {"type": "string"}, "test_file": {"type": "string"}},
 "required": ["requirement_id", "test_file"]}
```

**Output schema**
```json
{"status": "success | error", "requirement_id": "REQ-2.1",
 "test_outcome": "passed | failed | no_tests",
 "passed": 6, "failed": 1, "errors": 0,
 "failures": [{"test_name": "test_x::test_upgrade_exact_boundary_balance", "message": "<= 4000 chars>"}]}
```

**Failure behaviour**

| Condition | Result |
|---|---|
| Path outside the allowed folders (e.g. `../../src/agent_tools.py`) | `error`: `... is outside the sandbox's allowed test folders.` |
| File does not exist | `error`: `Test file '...' does not exist.` |
| Generated file fails the policy re-check | `error`: `Test file rejected by sandbox policy: ...` |
| Run exceeds the timeout | `error`: `Test run exceeded the 60s sandbox timeout and was stopped.` |
| pytest produced no report | `error` with truncated output |

---

## 4. `draft_issue` — low impact (simulated side effect)

**Purpose:** write a reviewable issue draft. Nothing leaves the repository.

**Input schema**
```json
{"type": "object",
 "properties": {
   "requirement_id": {"type": "string"},
   "title": {"type": "string"},
   "summary": {"type": "string"},
   "failing_tests": {"type": "array", "items": {"type": "string"}}},
 "required": ["requirement_id", "title", "summary", "failing_tests"]}
```

**Output schema:** `{"status": "success | error", "draft_path": "evidence/issues/drafts/ISSUE-REQ-2.1-<UTC stamp>.md"}`

The draft quotes the requirement text, lists the failing tests, includes the summary, and ends
with `Drafted by Inspectra QA agent - not filed.` An unknown requirement id returns `error`.

---

## 5. `file_issue` — HIGH impact

**Purpose:** file a drafted issue. In this commit it is filed locally to `evidence/issues/filed/`;
the GitHub integration is added in the Week 6 realignment.

**Input schema**
```json
{"type": "object",
 "properties": {"draft_path": {"type": "string"},
                "approval_token": {"type": ["string", "null"], "default": null}},
 "required": ["draft_path"]}
```

**Output schema:** `{"status": "success | error | approval_required", "filed_path": "...", "channel": "local"}`

**Authorization:** the run pauses for the human (Studio approve/reject card, or the terminal prompt in
the CLI; the MCP server asks on its console). Only after approval does the guard mint an HMAC-SHA256 token bound to `file_issue` and `{"draft_path": ...}` (single use, 120 s).
The tool verifies the token itself with `verify_and_consume_token`, so calling it directly without
a token is refused.

| Condition | Result |
|---|---|
| No / tampered / expired / replayed token | `approval_required`, nothing filed |
| Human rejects | `approval_required` (`Action rejected by human operator.`) |
| `draft_path` not an existing file in `evidence/issues/drafts/` | `error` |
| Copy fails | `error`: `Could not file the issue, action not completed.` |

---

## 6. `save_test_to_suite` — HIGH impact

**Purpose:** keep a useful generated test by copying it into `sut/tests/`. This changes the
repository, so it needs approval (Week 1 boundary matrix).

**Input schema**
```json
{"type": "object",
 "properties": {"test_file": {"type": "string"},
                "approval_token": {"type": ["string", "null"], "default": null}},
 "required": ["test_file"]}
```

**Output schema:** `{"status": "success | error | approval_required", "saved_path": "sut/tests/<name>.py"}`

**Authorization and failures:** same token flow as `file_issue`, bound to `{"test_file": ...}`.
A `test_file` outside `sandbox/generated/` (for example a file in `src/`) is refused with `error`.

---

## Sandbox rules (`src/sandbox.py`)

| Rule | Value |
|---|---|
| Allowed test folders | `sandbox/generated/`, `sut/tests/` (paths are resolved first, so `../` cannot escape) |
| Process | `subprocess.run([python, "-m", "pytest", file, "-q", "-p", "no:cacheprovider", "--junitxml", tmp])` with `shell=False`, `cwd` = project root |
| Timeout | 60 s (`TEST_TIMEOUT_SECONDS`); the process is killed on timeout |
| Environment | Only `PATH`, `SYSTEMROOT`, `TEMP`, `TMP`, plus `PYTHONPATH=sut/`. `GEMINI_API_KEY`, `GITHUB_TOKEN` and every other variable are dropped |
| Output | Parsed from the JUnit XML report; each failure message truncated to 4000 chars |
| Generated-code imports allowed | `pytest`, `unittest`, `unittest.mock`, `json`, `os`, `tempfile`, `pathlib`, `requests`, `subscription_service` |
| Generated-code rejected | `eval`, `exec`, `compile`, `__import__`, `os.system`, `os.popen`, `os.remove`, `os.unlink`, `os.rmdir`, `os.exec*`, `os.spawn*`; imports of `subprocess`, `socket`, `shutil`, `ctypes`, `urllib`, `http`; relative imports; code that does not parse |
| When the policy is checked | When `propose_tests` writes the file, and again when `run_tests` runs a generated file |

**Known limits.** This is a process-level sandbox, not an OS container. A generated test can
still use CPU until the timeout, and could open files with `open()`. The import allow-list,
the secret-free environment and the timeout are the controls we rely on; a container is
future work.
