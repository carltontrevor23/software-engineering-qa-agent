<div align="center">

<img src="./images/logo.jpg" width="70" height="70" />

**MAKERERE UNIVERSITY**

College of Computing and Information Sciences
School of Computing and Informatics Technology

**BSE4104: Emerging Trends in Software Engineering**
**Week 1: Problem Framing and AI-Native Requirements**

</div>

# WEEK 1 PROGRESS REPORT

## GROUP S — DAY

| Name                | Reg. No.       |
|---------------------|----------------|
| Bisaso Marvin       | 23/U/22595     |
| Kirabo Edna Takaisa | 23/U/09900/PS  |
| Asiimire Praise     | 23/U/0273      |
| Nakiroya Modest     | 23/U/13810/EVE |
| Ayebare Carlton T.  | 23/U/07137/EVE |

## AI Native Software QA Agent

### 1. Week 1 Objective

To assess what exactly the QA agent is allowed to think and what it is allowed to touch/use. Before a single line of the agent's own code is written, the project instructions require a use case scoped tightly enough that anyone can read our documentation and know precisely where the model's judgement ends and deterministic, human-gated control begins.

### 2. Work Completed

During week 1, the team completed all planned artifacts defined in the project instructions:

- **Use Case Selection & Scoping:** Formally selected the Software-Engineering QA Agent use case from the project's recommended use cases, bounding it to unit test generation, sandboxed test execution, traceback error triage, and issue summary drafting.
- **Project Charter Formulation:** Authored the complete Project Charter defining the problem statement, primary user, in-scope/out-of-scope boundaries, assumptions and operational constraints.
- **User Stories and Acceptance Criteria:** Defined ten testable user stories covering requirement-to-test synthesis, sandboxed test execution, traceback analysis, draft PR note writing, and tool-level security intercepts, plus the governance, memory, and traceability behaviours.
- **AI Boundary Matrix:** Formulated an explicit boundary matrix categorizing actions reserved for AI reasoning, tasks governed by deterministic software, and high-impact actions strictly restricted to human developers.
- **System Context Architecture:** Produced the System Context Diagram specifying the data boundaries between the developer, orchestration/guardrail layer, LLM agent core, context knowledge base, isolated runner, and local evidence store.
- **Repository & Task Management:** Initialized the project repository on GitHub following the recommended directory structure and set up the ClickUp project with assigned tasks.

### 3. What the Team Established

- Selected the Software-Engineering QA Agent use case, keeping the requirements corpus comfortably inside the project's recommended 10–50 document range so every claim we make is grounded in something real.
- Agreed, and then wrote down, exactly where reasoning ends and control begins: the agent proposes tests, summarizes failures and drafts notes, while deterministic tooling executes tests and computes results nothing ever reaches the repository without explicit human approval.
- Locked a hard out-of-scope boundary as a team: no autonomous merge, no production or staging deployment, no secret access, no arbitrary shell execution and held that line consistently across the Charter, the Matrix, and the architecture diagram.
- Set up the GitHub repository skeleton to the project's recommended structure and filed every Week 1 artefact into it.
- Set up the ClickUp Week 1 board with tasks per deliverable, a named owner on each, and due dates.

### 4. Repository & ClickUp Evidence

- **GitHub Repository:** https://github.com/carltontrevor23/software-engineering-qa-agent.git
- **ClickUp Space:** https://app.clickup.com/1200440000000401/v/s/1200440000002018

### 5. Plan for Next Week

- Select and document the foundation model baseline (analysing capabilities, cost, latency, and access constraints).
- Draft Prompt Specification v1.0 (role, task, context, constraints, output format, and failure handling).
- Build the baseline test-generation interaction script without RAG or tools.
- Run and document the 10-case prompt evaluation table comparing expected vs. actual generated unit tests across two prompt iterations.