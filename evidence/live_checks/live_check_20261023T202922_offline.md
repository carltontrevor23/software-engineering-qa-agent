# Live check 2026-10-23T202922Z

Mode: offline (scripted model)

| Result | Check | Detail |
|---|---|---|
| PASS | preflight | offline mode: scripted model, no network |
| PASS | full_loop: check REQ-2.1 | tools ['search_requirements', 'propose_tests', 'run_tests'], 'all_tests_passed' |
| PASS | full_loop: follow-up read code | tools ['read_code', 'read_code']: [SCRIPTED LLM] I read subscription_service/subscription_manager.py. It defines: InsufficientFundsError, Inacti |
| WARN | full_loop: follow-up refine test | new test file written, outcome None |
| SKIP | full_loop: follow-up save tests | the refined tests did not pass |
| SKIP | library: second project | needs a live model |
| SKIP | safety: prompt injection | needs a live model |
| PASS | unknown: REQ-9.9 | stop_reason=requirement_not_found, tools ['search_requirements', 'propose_tests'] |
