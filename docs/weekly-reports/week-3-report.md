# WEEKLY PROGRESS REPORT (WEEK 3)[cite: 3]
**BSE4104 AI-Native & Agentic Engineering Capstone**[cite: 1, 3]  
**GROUP S**  
**PROJECT:** Software-Engineering QA Agent[cite: 1]  

---

### 1. Work Completed Against Weekly Objectives[cite: 3]
The primary objective for Week 3 was to ground model generation in a controlled, traceable knowledge source using a Retrieval-Augmented Generation (RAG) pipeline[cite: 2]. All five weekly activities were achieved:
* **Controlled Corpus Assembly:** Created a version-controlled requirements corpus under `docs/requirements/` (`cancellation.md`, `downgrade.md`, `notifications.md`, `refund.md`, `trial_period.md`, and `subscription.md`) with explicit section labelling and provenance[cite: 2].
* **Ingestion, Indexing & Retrieval Implementation:** Built an automated ingestion and chunking pipeline in `src/rag.py` using BM25 lexical ranking and strict score thresholds[cite: 2].
* **15-Case RAG Evaluation Suite:** Designed and executed a comprehensive 15-question evaluation suite in `docs/evaluation/rag_evaluation_questions.json` spanning Answerable, Partially Answerable, and Deliberately Unanswerable categories[cite: 2].
* **Failure Analysis:** Investigated, empirically reproduced, and documented three retrieval and grounding failure modes in `docs/evaluation/retrieval_grounding_failures.md`[cite: 2].

---

### 2. Key Engineering Decisions and Rationale[cite: 3]
* **BM25 Lexical Search for Initial Indexing:** Selected BM25 lexical scoring over generic dense vector embeddings for this phase to ensure deterministic keyword matching for specific software identifiers, exact exception class names (`TrialAlreadyUsedError`), and explicit monetary values.
* **Separation of Retrieval Traces from Generation Traces:** Structured `src/run_rag_evaluation.py` to record BM25 chunk IDs and relevance scores independently of model responses to distinguish pure retrieval misses from LLM grounding failures.
* **Explicit Refusal Fallback (`min_score=1.0`):** Enforced a strict minimum relevance score threshold. Queries scoring below 1.0 automatically yield `NO_RELEVANT_REQUIREMENTS_FOUND`, preventing hallucinations on ungrounded queries.
* **Batch Request Pacing:** Enforced rate-limit delays (`time.sleep(65.0)` / dynamic backoff) in `src/model_client.py` to reliably navigate free-tier Requests-Per-Minute (RPM) API quotas without failing batch evaluation runs.

---

### 3. Challenges and current response[cite: 3]
**Rate Limiting (Quota Exceeded):**  
* **Challenge:** Rapid sequential execution of evaluation cases triggered free-tier rate limits (20 RPM cap).  
* **Response:** Updated `src/model_client.py` with backoff logic catching `genai_errors.APIError` and inserted configurable delays in the batch runner.  

---

### 4. Repository & Project Management Evidence[cite: 3]
* **GitHub Repository:** https://github.com/carltontrevor23/software-engineering-qa-agent[cite: 3]
* **ClickUp Board Link:** https://app.clickup.com/1200440000000401/v/b/li/1200440000008198[cite: 3]

---

### 5. Individual Contribution Summary[cite: 3]
* **[Praise Assimire] Corpus Curation & Provenance:** Authored and formatted the controlled specification documents with section IDs, acceptance criteria, and explicit open-scope notes[cite: 2, 3]. *Evidence: (`docs/requirements/cancellation.md`, `downgrade.md`, `notification.md`, `refund.md`, `trial_period.md`)*[cite: 3]
* **[Carlton Ayebare] Pipeline & Indexing Implementation:** Developed core segmenting, indexing, and BM25 search mechanics[cite: 2, 3]. *Evidence: `src/rag.py` and unit tests in `tests/test_rag.py`.*[cite: 3]
* **[Ednah Kirabo] Prompt Engineering & Evaluation Design:** Constructed model context from retrieved evidence and showed sources in the response[cite: 2, 3]. *Evidence: changes in `src/model.py`.*[cite: 3]
* **[Modest Nakiroya] (Prompt Engineering & Evaluation Design):** Authored `prompts/rag_answer_prompt_v1.0.txt` and constructed the 15-case question matrix[cite: 2, 3]. *Evidence: `prompts/rag_answer_prompt_v1.0.txt`, `docs/evaluation/rag_evaluation_questions.json`.*[cite: 3]
* **[Marvin Bisaso] (Documented retrieval failures and what caused them):** Authored the 3-scenario failure root-cause analysis[cite: 2, 3]. *Evidence: `docs/evaluation/retrieval_grounding_failures.md`.*[cite: 3]

---

### 6. Plan for Next Week (Week 4: Tools & Function Calling)[cite: 3, 4]
* **Define Tool Catalogue & Schemas:** Define at least two deterministic tools with JSON input/output schemas, authorization scopes, and error-handling behaviours (e.g., a file/repo reader tool and a sandboxed test runner execution tool)[cite: 4].
* **Application Orchestration:** Implement function/tool-calling capabilities through the model client/orchestrator layer[cite: 4].
* **Simulate State / Side Effects:** Implement at least one tool that retrieves live application data or performs low-risk simulated state mutation (e.g., ticket/issue draft creation or ledger read)[cite: 4].
* **Robustness & Boundary Testing:** Build negative tests validating behaviour on missing parameters, unauthorized tool calls, unavailable external services, and malformed outputs[cite: 4].
* **Human-in-the-Loop Gate:** Add an explicit human-approval mechanism blocking high-impact actions before execution (aligned with the project charter boundary matrix)[cite: 4].