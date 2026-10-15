# Failure Catalogue & Remediation Evidence (Week 7, Activity 5)
**Project:** Software-Engineering QA Agent (Inspectra)  
**Deliverable:** Failure Catalogue with Genuine Failures, Fixes, and Re-Test Evidence  

---

## 1. Summary Overview
This catalogue documents five genuine failures identified during the development and empirical evaluation of Inspectra. Each entry details the observed failure mode, root-cause diagnosis, implemented remediation in the realigned codebase, and automated re-test evidence. In addition, Section 3 documents five fresh genuine failures identified during the Week 7 final evaluation scenarios (covering predicted security gaps, test runner isolation, and filesystem resilience) along with their implemented remediations and regression tests.

---

## 2. Catalogued Failures & Remediations

### FAIL-01: Bypass of Code Safety Validation via Dynamic Builtins
* **Failure Description:** In early iterations, safety validation relied on string matching (e.g., checking for `"import os"`). The LLM generated a test using `eval("__import__('os').system('...')")`, bypassing the filter.
* **Root Cause:** Lexical string inspection does not parse Python syntax trees and misses obfuscated or dynamic executions.
* **Remediation:** Integrated AST-level parsing (`ast.parse` and `ast.walk`) in `src/sandbox.py` (`validate_generated_code`) to recursively inspect `Call`, `Import`, and `ImportFrom` nodes against an explicit disallowed list.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail01_ast_blocks_obfuscated_code` -> **PASSED**.

### FAIL-02: Secret Leakage to Subprocess Environment
* **Failure Description:** During sandbox test execution, generated tests were able to read `os.environ["GEMINI_API_KEY"]` and `os.environ["GITHUB_TOKEN"]`.
* **Root Cause:** `subprocess.run()` inherited `os.environ` from the orchestrator by default.
* **Remediation:** Enforced an explicit `ENV_ALLOW_LIST = {"PATH", "PYTHONPATH", "SYSTEMROOT"}` in `src/sandbox.py`. All API tokens and system credentials are stripped before spawning the test runner process.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail02_subprocess_secret_isolation` -> **PASSED**.

### FAIL-03: Phase Skipping in Orchestration Loop
* **Failure Description:** The model hallucinated that tests had already executed and attempted to directly call `file_issue` at step 1.
* **Root Cause:** Free-form LLM routing without strict state-machine phase boundaries.
* **Remediation:** Added `ALLOWED_TOOLS_BY_PHASE` in `src/workflow.py`. The execution loop checks `state["phase"]` and immediately rejects out-of-order tool calls.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail03_phase_gate_blocks_skipping` -> **PASSED**.

### FAIL-04: Unauthorized External Issue Creation
* **Failure Description:** Bug reports could be dispatched directly to external repositories without human sign-off.
* **Root Cause:** Missing cryptographic gate on external state-changing API tools.
* **Remediation:** Integrated `file_issue` with `src/approval.py` requiring an HMAC-SHA256 single-use token bound to the issue title, body hash, and a 120s TTL window.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail04_unauthorized_issue_filing_blocked` -> **PASSED**.

### FAIL-05: Runaway Iteration on Code Generation Failures
* **Failure Description:** Repeated syntax failures caused the agent to loop endlessly, triggering API quota exhaustion (HTTP 429).
* **Root Cause:** No bound on proposal retry attempts within the agent graph.
* **Remediation:** Enforced strict cycle limits (`MAX_PROPOSALS = 2`, `MAX_HOPS = 7`). If proposals fail twice, the agent transitions to a graceful terminal stop with an advisory message for the user.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail05_max_hops_and_proposals_bounded` -> **PASSED**.

---

## 3. Fresh Week 7 Failures & Empirical Remediations (Final Evaluation Set)

### FAIL-06: Unguarded File System Operations Crash the Orchestrator (EV-32)
* **Failure Description:** In `src/qa_tools.py`, `propose_tests` and `draft_issue` directly executed `Path.write_text()` without catching `OSError` or `PermissionError`. If a disk error, permissions denial, or read-only directory was encountered during test generation or drafting, an unhandled exception crashed the agent loop rather than returning a structured error.
* **Root Cause:** Incomplete error handling around local filesystem writes, in contrast to `file_issue` and `save_test_to_suite` which caught `OSError`.
* **Remediation:** Wrapped all `write_text` calls in `propose_tests` and `draft_issue` inside `try...except OSError as e:` blocks, returning a structured error payload (`{"status": "error", "error": f"Could not write ...: {e}"}`) to ensure graceful failure routing to `tool_error`.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail06_disk_write_failure_handled_gracefully` -> **PASSED**.

### FAIL-07: Insecure Static Default Secret in Approval Gate (EV-42)
* **Failure Description:** In `src/approval.py`, when `APPROVAL_SECRET_KEY` was unset in the environment, the signing and verification routines fell back to `DEFAULT_SECRET = "qa-agent-approval-secret-key-2026"`. Any unauthorized actor or compromised model who knew the default key from the open repository could precompute valid HMAC-SHA256 tokens and execute state-changing actions (`file_issue`, `save_test_to_suite`) without human approval.
* **Root Cause:** Insecure default credential fallback in cryptographic security gate.
* **Remediation:** Replaced the static fallback in `src/approval.py` with an ephemeral random key generator (`secrets.token_hex(32)`) whenever `APPROVAL_SECRET_KEY` is missing or matches the default. This ensures precomputed or offline-forged tokens are rejected deterministically.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail07_default_secret_cannot_be_forged_when_env_unset` -> **PASSED**.

### FAIL-08: Sandbox Tampering & File Overwrite via Pathlib in Generated Test Code (EV-25)
* **Failure Description:** While `src/sandbox.py`'s `validate_generated_code` prohibited dangerous `os.*` system calls, `pathlib` was in `ALLOWED_IMPORTS`. An adversarial or misaligned model output could invoke `Path("sut/subscription_service/subscription_manager.py").write_text(...)` or `unlink()`, mutating or destroying the System Under Test or project files.
* **Root Cause:** Granular permission gap in AST validation: imports of `pathlib` were allowed, but mutating method calls on `Path` instances were not inspected or restricted.
* **Remediation:** Extended AST validation in `validate_generated_code` to detect and reject destructive method calls (`write_text`, `write_bytes`, `unlink`, `rmdir`, `rename`, `replace`, `mkdir`, `chmod`) as well as `open()` calls in write or append modes (`"w"`, `"a"`, `"x"`, `"+"`).
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail08_pathlib_mutating_calls_blocked` -> **PASSED**.

### FAIL-09: Root Test Runner Collection Failure Due to Unisolated Generated Scripts
* **Failure Description:** Executing `python -m pytest` from the project root crashed with `ModuleNotFoundError: No module named 'subscription_service'` during test collection. Pytest recursively searched into `sandbox/generated/` and attempted to import dynamically generated test modules in the host process where `sut/` was not on `PYTHONPATH`.
* **Root Cause:** Absence of a top-level pytest configuration file constraining test discovery boundaries to legitimate test suites.
* **Remediation:** Created a root `pytest.ini` explicitly defining `testpaths = tests sut/tests` and `norecursedirs = sandbox data env .git .pytest_cache`. Generated sandboxed test scripts are now isolated from the root test runner and only executed within the controlled sandbox subprocess.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail09_pytest_configuration_ignores_sandbox` -> **PASSED**.

### FAIL-10: Network Exfiltration Vulnerability in Sandboxed Test Code (EV-24)
* **Failure Description:** In `src/sandbox.py`, `requests` was included in `ALLOWED_IMPORTS` for SUT API testing. Generated test code could invoke `requests.post()` or `requests.put()` to transmit environment variables, internal files, or memory states to external unauthorized servers.
* **Root Cause:** Allowing outbound network mutating calls inside generated code without AST filtering or egress gating.
* **Remediation:** Hardened AST checks in `validate_generated_code` to intercept and block network egress calls on `requests` (`post`, `put`, `delete`, `patch`), ensuring generated tests cannot exfiltrate data while still permitting safe, read-only/mocked test patterns.
* **Re-test Evidence:** `tests/test_failure_remediation.py::test_remediation_fail10_network_exfiltration_calls_blocked` -> **PASSED**.