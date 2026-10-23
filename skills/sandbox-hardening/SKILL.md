---
name: sandbox-hardening
description: Guides agents through closing the confirmed bypasses in src/sandbox.py's generated-test validator and isolating test runs from secrets. Use when the agent executes model-written code or before any demo.
---

# Sandbox Hardening

## Overview
`validate_generated_code` approves these (confirmed by calling it): `from os import system`, `import os as o; o.system(..)`, `getattr(os,'sys'+'tem')`, `open('.env')`, `Path('.env').read_text()`, `requests.post(..)`, `pytest.importorskip('subprocess')`. Only plain `os.system` is blocked. The env stripping does not protect the `.env` file in the working directory.

## When to Use
After `studio-migration`, before demos or release.

## Process
1. **Deny by default.** Allow only `pytest`, `json`, `unittest` (minus `mock` if unneeded) and `subscription_service`. Use pytest's `tmp_path` instead of `os`/`pathlib`/`tempfile`; drop `requests`.
2. **Ban names, not just imports.** Reject `open`, `getattr`, `setattr`, `globals`, `locals`, `vars`, `__builtins__`, `importorskip`, dunder attribute access, and check `from X import Y` names and import aliases.
3. **Isolate the run.** Copy only `sut/subscription_service` plus the one test into a temp dir; run pytest there, never in the repo root. Nothing secret exists in that directory.
4. **Network.** Prefer Docker with `--network none` if available; otherwise a socket-blocking `conftest.py` in the temp dir, and say in the docs that this is weaker.
5. **Secrets.** Remove `DEFAULT_SECRET` in `approval.py`; require `APPROVAL_SECRET_KEY` where tokens remain.
6. **Evidence.** Add the seven snippets above (each must be rejected) and an injection case (requirement text asking for a test that reads `.env`) to the evaluation set. Add the finding to the Failure Catalogue with re-test.

## Rationalizations
| Excuse | Reality |
|---|---|
| "Our requirements are trusted." | Test output and model behaviour are not; the brief grades injection awareness. |
| "The static check is enough." | A deny-list on syntax is bypassable; isolation is the real control. |

## Red Flags
Tests run with the repo root as working directory; `.env` reachable from the test process.

## Verification
- [ ] Every snippet above is rejected by the validator, and still fails if the validator is bypassed (temp dir has no `.env`).
- [ ] Existing sandbox tests and the generated REQ-2.1 test still pass.
