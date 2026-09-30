# WEEKLY PROGRESS REPORT (WEEK 4)
BSE4104 AI-Native & Agentic Engineering Capstone
GROUP S
PROJECT:  Software-Engineering QA Agent

## Work Completed Against Weekly Objectives 
The primary objective for Week 4 was to move beyond passive text generation by equipping the model with explicit, safe, and deterministic software capabilities via tool and function calling. All five weekly activities were achieved:
* Tool Catalogue & Schema Definition: Authored a comprehensive Tool Catalogue defining tool purpose, JSON input/output schemas, authorization levels, and failure behaviours for core capabilities (`get_user_subscription_status`, `upgrade_user_subscription`, etc.).
* Application Orchestration Implementation: Integrated LangChain and LangGraph in `src/tool_calling.py` using `ChatGoogleGenerativeAI`, binding tool definitions to `gemini-3.6-flash` and executing model-directed tool calls via a state graph.
* Live Inspection & State Mutation Simulation: Implemented read-only account data retrieval (`get_user_subscription_status`) wrapping `SubscriptionManager.fetch_user_data()` and simulated financial state modification (`upgrade_user_subscription`) wrapping `SubscriptionManager.process_upgrade()`.
* Robustness & Boundary Testing: Developed a negative test suite in `tests/test_tool_failures.py` covering missing parameters, unauthorized requests, network timeouts, HTTP 500 outages, and business invariant violations.
* Human-in-the-Loop Approval & Token Architecture: Implemented src/approval.py to gate higher-impact state actions (upgrade_user_subscription, etc.) behind human confirmation using HMAC-SHA256 signed, single-use approval tokens bound to specific tool names, argument hashes, nonces (replay prevention), and 120-second expiration windows.

## Key Engineering Decisions and Rationale
* Separation of Read-Only vs. State-Changing Tools: Designated get_user_subscription_status` as low-risk (auto-authorized) and `upgrade_user_subscription` as high-impact (financial ledger write), enforcing distinct security and confirmation pipelines per operation type.
* Global Network Mocking via `unittest.mock.patch`: Intercepted `requests.get` globally in test suites to prevent actual DNS resolution attempts against internal API hosts ensuring deterministic unit testing.
* Schema Validation at the Boundary: Leveraged Pydantic and LangChain tool schemas to reject malformed or missing parameters before reaching internal application logic.
* Structured Failure Status Payloads: Maintained uniform JSON output shapes (`{"status": "error", "error": "..."}`) across both tools so the language model can distinguish transient network errors from permanent domain errors (e.g., inactive account or insufficient funds).

## Challenges and current response
### Simulated Service Connectivity & DNS Resolution 
* Challenge: During initial test execution, tool calls invoked real HTTP requests against the mock endpoint `https://api.internal.service`, resulting in socket connection errors. 
* Response: Modified test harnesses in `tests/test_tool_failures.py` to patch `requests.get` at the top level, providing simulated 200, 404, 500, and timeout responses across all scenarios.

## Repository & Project Management Evidence
* GitHub Repository: https://github.com/carltontrevor23/software-engineering-qa-agent
* ClickUp Board Link: https://app.clickup.com/1200440000000401/v/li/1200440000008199

## Individual Contribution Summary
* [Modest Nakiroya] Tool Specification & Catalogue: Authored the core Tool Catalogue defining input schemas, output structures, and risk tier classifications. Evidence: `docs/tools/tool_catalogue.md`.
* [Asiimire Praise] Tool Definition & LangChain Binding: Implemented `get_user_subscription_status` and `upgrade_user_subscription` decorators, binding tools to the Gemini client in `src/tool_calling.py`. Evidence: `src/tool_calling.py`.
* [Ednah Kirabo] Tool Verification & Hardening: Checked and improved the two tools already scaffolded on `main`: `get_user_subscription_status` (read-only lookup) and `upgrade_user_subscription` (simulated side effect). Added handling for two failure cases required by the Tool Catalogue: an unavailable lookup service and a ledger write failure, each returning the exact error message specified. Evidence: `src/tool_calling.py`
* [Ayebare Carlton] Human Approval Gate & Token Verification: Implemented src/approval.py implementing policy classification (is_high_impact), cryptographic token minting/verification (create_approval_token, verify_and_consume_token), interactive approval prompts, and unit verification in tests/test_approval.py. Evidence: src/approval.py, tests/test_approval.py
* [Marvin Bisaso] Failure, Boundary & Authorization Testing: Implemented the negative testing suite in `tests/test_tool_failures.py`, resolving external DNS mock issues and verifying test cases covering missing arguments, timeouts, 404s, and account invariant violations. Evidence: `tests/test_tool_failures.py`, test trace logs showing all passed.

## Plan for Next Week (Week 5: Agent Architecture and Bounded Autonomy)
* Define Goal-Directed Task: Identify a realistic software QA scenario requiring multi-step reasoning (e.g., verifying user eligibility, assessing balance requirements, checking downgrade/upgrade prerequisites, and executing approved actions).
* Implement Sense-Plan-Act Loop:  Structure the orchestration cycle around explicit phases: `Sense/Context` - `Plan/Decide` - `Act/Tool` - `Observe` - `Stop/Re-plan`.
* Enforce Execution Bounds: Implement strict runtime limits, including maximum iteration caps, an approved tool registry, terminal stop conditions, and mandatory human hand-off thresholds.
* Workflow Framework Integration: Implement the bounded loop using direct orchestration / LangGraph workflow graphs.
* Capture Execution Traces: Generate and log at least three end-to-end execution traces, including at least one failure/recovery cycle.