# WEEKLY PROGRESS REPORT (WEEK 2)
BSE4104 AI-Native & Agentic Engineering Capstone
GROUP S
PROJECT:  Software-Engineering QA Agent

## Work Completed Against Weekly Objectives 
The primary objective for Week 2 was to establish the baseline model integration layer, develop structured prompt specifications, and conduct systematic empirical evaluations comparing prompt performance across both typical and adversarial scenarios:
* Model Integration Baseline: Integrated gemini-3.6-flash via the official Google GenAI SDK inside src/model_client.py, incorporating structured trace logging, resilient exception handling, and an automated batch runner CLI.
* System Under Test Implementation: Implemented the target business logic service in subscription_manager.py with multi-branch validation, external API fetching, ledger file mutations, and custom domain exceptions (InsufficientFundsError, InactiveUserError, UserNotFoundError).
* Prompt Iteration & Specification: Authored and version-controlled two prompt specifications (prompts/v1.0_test_proposal.txt and prompts/v1.1_test_proposal.txt) designed for test case generation, requirement grounding, boundary detection, and hallucination reduction.
* Empirical 10-Case Evaluation: Constructed and executed a 10-case evaluation suite (docs/evaluation/evaluation_cases.json) spanning happy path, boundary, negative, and adversarial failure modes across both prompt iterations.
* Evidence Tracing & Analysis: Captured execution traces under evidence/traces/ and produced comparative analysis evaluating grounding precision, boundary rigor, and refusal accuracy.

## Key Engineering Decisions and Rationale
* Model Client Layer: Implemented get_model_response() in model_client.py independently to ensure single-responsibility isolation and simplify batch benchmarking.
* Separation of Unrecoverable vs. Recoverable Errors: Structured error handling to fail immediately without retry on HTTP 4xx errors (bad authentication, invalid syntax), while reserving retry logic for transient HTTP 429 rate limits and 5xx server issues.
* Automated Batch Execution Interface: Added a CLI argument flag (--run-evaluation) to model_client.py enabling fully automated execution of entire evaluation JSON sets without manual per-case intervention.
* Strict Negative Grounding & Deterministic Refusal: Implemented prompt v1.1 with an explicit failure boundary (NO_GROUNDED_TESTS_FOUND), instructing the model to refuse test generation when requirements excerpts are missing or irrelevant rather than fabricating plausible behaviour.

## Challenges and current response
### Free-Tier API Rate Limits:
* Challenge: Rapid back-to-back batch evaluation runs triggered Google AI Studio free-tier sliding window rate limits (20 Responses Per Minute cap).  
* Response: Integrated pacing delays between test case executions and wrapped API invocations with exponential backoff and retry mechanisms.

## Repository & Project Management Evidence
* GitHub Repository: https://github.com/carltontrevor23/software-engineering-qa-agent
* ClickUp Board Link: https://app.clickup.com/1200440000000401/v/li/1200440000008197

## Individual Contribution Summary
* [Praise Asiimire] Model Integration & Logging Baseline: Built model_client.py, integrating the Google GenAI SDK, exception wrappers (ModelCallError), and persistent trace logging to `evidence/traces/`. Evidence: src/model_client.py.
* [Carlton Ayebare] Prompt Specification & Engineering: Authored the baseline prompt template v1.0_test_proposal.txt, establishing test proposal structure, context injection placeholders, and grounding constraints. Evidence: prompts/v1.0_test_proposal.txt.
* [Ednah Kirabo] System Under Test Implementation: Developed the target business logic in src/subscription_manager.py, including account data fetching, exception hierarchies, and ledger balance transactions. Evidence: src/subscription_manager.py.
* [Nakiroya Modest] Evaluation Suite & Batch Runner: Implemented the 10-case evaluation matrix in docs/evaluation/evaluation_cases.json, implemented run_evaluation function, CLI automation, and conducted the comparative trace analysis. Evidence: docs/evaluation/evaluation_cases.json, comparative evaluation traces.
* [Marvin Bisaso]Prompt Hardening & Guardrails:Implemented v1.1_test_proposal.txt, adding classification tags, numeric boundary checks, and anti-hallucination refusal rules. Evidence: prompts/v1.1_test_proposal.txt.

## Plan for Next Week (Week 3: Grounding and Context Retrieval / RAG)
* Corpus Assembly & Provenance: Assemble a controlled requirements corpus under docs/requirements/ with recorded provenance and section-level metadata.
* Ingestion, Chunking & Indexing: Implement document segmenting, indexing, and retrieval mechanics using BM25 lexical ranking.
* Context Construction: Dynamically format retrieved excerpts into cited prompt contexts with visible source attribution.
* 15-Question Evaluation Suite: Author and execute a 15-case evaluation suite covering answerable, partially answerable, and deliberately unanswerable test scenarios .
* Failure Analysis: Identify, reproduce, and document at least three retrieval/grounding failures and identify their root causes.