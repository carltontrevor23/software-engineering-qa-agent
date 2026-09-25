# WEEKLY PROGRESS REPORT (WEEK 1)
BSE4104 AI-Native & Agentic Engineering Capstone
GROUP S
PROJECT:  Software-Engineering QA Agent

## Work Completed Against Weekly Objectives 
The primary objective for Week 1 was to establish foundational system governance, determine operational boundaries between model reasoning and deterministic control, and formulate all core project charter deliverables before implementing agent code:
* Use Case Selection & Scoping: Formally selected the Software-Engineering QA Agent domain, tightly bounding operations to unit test proposal, sandboxed test execution, traceback error triage, and draft issue summaries.
* Project Charter Formulation: Authored the comprehensive Project Charter detailing the problem statement, primary user personas, explicit in-scope and out-of-scope boundaries, assumptions, and operational constraints.
* User Stories & Acceptance Criteria: Defined ten testable user stories (US-01 through US-10) covering requirement-to-test synthesis, execution isolation, failure summarization, tool-level security intercepts, state tracking, and full audit traceability.
* AI Boundary Matrix: Formulated an explicit boundary matrix categorizing system actions across three strict control tiers: AI Reasoning, Deterministic Software, and Human-Gated Authorization.
* System Context Architecture: Designed the System Context Diagram specifying data boundaries between the developer, orchestration/guardrail layer, foundation model, knowledge base, isolated runner, and persistent trace store.
* Repository & Workspace Setup: Initialized the version-controlled GitHub repository following standard architectural conventions and configured the project ClickUp workspace with assigned tasks.

## Key Engineering Decisions and Rationale
* Separation of Reasoning from Execution: Established an architectural boundary ensuring the language model only proposes tests and drafts summaries; deterministic execution tooling runs sandboxed tests, and direct file modification or repository commits strictly require human approval.
* Strict Out-of-Scope Hardening: Explicitly barred the agent from autonomous code merging, staging/production deployments, credential or secret access, and unbounded shell execution to prevent unauthorized system mutation.
* Corpus Bounding for Traceable Verification: Scoped the target system under test to a manageable domain specification (10 to 50 requirements documents) to guarantee that every generated test case can be deterministically traced to documented acceptance criteria.
* Auditable Trace Requirement: Architected the system from day one to mandate that every model invocation, prompt version, tool execution, refusal, and error event is recorded into persistent trace logs.

## Challenges and current response
### Defining Action Boundaries Across Hybrid Autonomy:
* Challenge: Distinguishing which testing tasks could safely run autonomously versus those posing security, integrity, or code-corruption risks.  
* Response: Formulated the AI Boundary Matrix to formally enforce that all state-changing operations (such as committing files, pushing branches, or modifying live databases) are human-gated, whereas low-risk read operations remain automated.

## Repository & Project Management Evidence
* GitHub Repository: https://github.com/carltontrevor23/software-engineering-qa-agent
* ClickUp Board Link: https://app.clickup.com/1200440000000401/v/li/1200440000002596

## Individual Contribution Summary
* [Marvin Bisaso] Project Charter & Problem Statement: Led the drafting of the Project Charter, outlining core objectives, user profiles, operational assumptions, and delivery timelines. Evidence: Project Charter document in repository docs/
* [Nakiroya Modest] Architecture & System Context: Designed the System Context Architecture Diagram defining boundary interactions between the user, agent orchestrator, sandbox, and external APIs. Evidence: System context diagram file in docs/
* [Carlton Ayebare] User Stories & Acceptance Criteria: Authored the core user stories and acceptance criteria defining automated test proposal, sandboxing, and execution requirements. Evidence: User stories register in docs/
* [Praise Asiimire] Governance & AI Boundary Matrix: Formulated the AI Boundary Matrix and governance rules mapping autonomous reasoning tasks against human-gated actions. Evidence: AI Boundary Matrix document in docs/
* [Ednah Kirabo] Repository Setup, Traceability Specs & Management: Initialized the GitHub repository skeleton, set up the ClickUp workspace and deliverable tracking, and authored traceability requirements. Evidence: Initial repository commits, ClickUp workspace board.

## Plan for Next Week (Week 2: Foundation Model Baseline & Prompt Engineering)
* Foundation Model Selection: Select and document the foundation model baseline (evaluating capabilities, token pricing, latency, and rate limits).
* Draft Prompt Specification v1.0:  Author structured prompt template v1.0 covering role, task instructions, context variables, grounding constraints, and output formatting.
* Implement Model Client Baseline: Build `src/model_client.py` using the official SDK to handle API calls, structured trace logging, and resilient error handling without RAG or external tools.
* Execute 10-Case Prompt Evaluation: Design an evaluation matrix and evaluate prompt performance across two iterations (v1.0 vs. v1.1) spanning happy path, boundary, negative, and adversarial test scenarios.