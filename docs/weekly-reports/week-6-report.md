# WEEKLY PROGRESS REPORT (WEEK 6)
**Course:** BSE4104 AI-Native & Agentic Engineering Capstone  
**Group:** GROUP S  
**Project:** Software-Engineering QA Agent (Inspectra)  
**Period:** 5th October – 9th October 2026  
**Weekly Focus:** Make workflow state explicit, retain only justified memory, and connect capabilities through clear interfaces.

---

## 1. Work Completed Against Weekly Objectives

All five Week 6 activities and expected deliverables were successfully completed, thoroughly documented, and verified through automated test suites:

* **Explicit Session/Workflow State Modeling:** Formalized the runtime state architecture in [`src/tool_calling.py`](../../src/tool_calling.py) using LangGraph's typed `AgentState(MessagesState)`. Session state is strictly bounded to `messages` and an integer `hops` counter, enforcing hard iteration bounds (`MAX_HOPS = 4`) and call limits (`MAX_CALLS_PER_STEP = 1`). Authored the official state specification at [`docs/architecture/state_model.md`](../../docs/architecture/state_model.md).
* **Justified Persistent-Memory Implementation:** Implemented durable case-history tracking in [`src/memory.py`](../../src/memory.py) using an append-only, thread-locked JSON Lines store at `data/memory/case_history.jsonl`. Each record captures tool outcome metadata (`timestamp`, `user_id`, `tool_name`, `status`, `hops`) to surface recent operational attempts to human approvers during high-impact action authorization.
* **Data Handling, Access, Retention & Deletion Specification:** Authored the comprehensive [`docs/architecture/memory_design_and_data_handling_note.md`](../../docs/architecture/memory_design_and_data_handling_note.md) detailing schema definitions, data minimization rules (zero PII, zero raw chat logs), an RBAC access matrix, rolling 30-day retention policies, and GDPR Article 17 ("Right to be Forgotten") erasure functions (`delete_user_case_history` and `purge_expired_records`).
* **Demonstration of Non-Silent Decision Control:** Developed comprehensive behavioral tests in [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py) and compiled audit evidence in [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md). Verified that historical execution logs provide operational visibility without silently bypassing HMAC authorization gates, forging single-use approval tokens, or leaking into LLM prompt contexts.
* **MCP-Style Interoperability Specification & Server Implementation:** Authored the complete Model Context Protocol interface specification in [`docs/architecture/mcp_interface_spec.md`](../../docs/architecture/mcp_interface_spec.md). Over-delivered on the integration requirement by implementing both a production-ready FastAPI JSON-RPC 2.0 server in [`src/mcp_server.py`](../../src/mcp_server.py) and an interactive verification client in [`src/mcp_demo_client.py`](../../src/mcp_demo_client.py).

---

## 2. Key Engineering Decisions and Rationale

1. **Strict Decoupling of Ephemeral State vs. Persistent Memory:**
   Session state (`AgentState`) exists only in RAM for the lifetime of one `run(prompt)` invocation, holding conversational context and hop counters. Persistent memory (`case_history.jsonl`) resides on disk across sessions. The two are strictly firewalled: persistent logs are never copied into `AgentState["messages"]`, ensuring historical records cannot poison the LLM prompt or induce hallucinated authority.
2. **Advisory-Only Memory Gate (Zero Silent Control):**
   Case history is read solely by the execution orchestrator to present context to the human approver during high-impact interceptions. Historical approvals do not auto-authorize future actions; state mutations still unconditionally require an unconsumed, cryptographically signed HMAC-SHA256 token minted upon explicit human consent.
3. **Privacy-by-Design and Data Minimization:**
   In compliance with GDPR Article 5(1)(c), memory persists only 5 structured operational metadata fields. Unstructured conversational banter, user queries, billing credentials, and PII are systematically discarded at session conclusion.
4. **Interoperability Standard (Model Context Protocol / JSON-RPC 2.0):**
   Selected standard JSON-RPC 2.0 over ad-hoc REST endpoints for external capability exposure, providing standardized protocol methods (`initialize`, `tools/list`, `tools/call`) compatible with modern agent ecosystems.

---

## 3. Challenges and Current Responses

### Concurrency and File Contention on Log Appends
* **Challenge:** Multiple concurrent agent executions could trigger race conditions or interleaved JSON lines when writing to `data/memory/case_history.jsonl`.
* **Response:** Integrated thread-level locking (`threading.Lock`) guarding both write and read operations in [`src/memory.py`](../../src/memory.py), ensuring atomic append and flush sequences.

### Preventing Prompt Injection via Audit Trails
* **Challenge:** If past tool execution results contain hostile payloads, feeding past history into the LLM prompt could trigger prompt-injection or context drift.
* **Response:** History is formatted exclusively for standard console output for the human reviewer (`[CASE HISTORY]...`) and is never attached to `ToolMessage` or `AIMessage` objects passed into `llm_with_tools.invoke()`. This guarantee is covered by unit tests in [`tests/test_memory.py`](../../tests/test_memory.py#L48-L97).

### Test Environment API Isolation
* **Challenge:** Unit test runners without active external Gemini API credentials encountered import-time initialization failures in model clients.
* **Response:** Configured test harnesses and fixtures in [`tests/conftest.py`](../../tests/conftest.py) to provide isolated temporary storage fixtures (`tmp_path`) and test mocks, enabling full test suite execution without external network or API key dependencies.

---

## 4. Deliverables Index

| Deliverable Name | File Location | Status |
| :--- | :--- | :---: |
| **State Model** | [`docs/architecture/state_model.md`](../../docs/architecture/state_model.md) | **Completed** |
| **Memory Design and Data Handling Note** | [`docs/architecture/memory_design_and_data_handling_note.md`](../../docs/architecture/memory_design_and_data_handling_note.md) | **Completed** |
| **Working Memory/State Demonstration** | [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py), [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md) | **Completed** |
| **Integration / MCP Interface Specification** | [`docs/architecture/mcp_interface_spec.md`](../../docs/architecture/mcp_interface_spec.md), [`src/mcp_server.py`](../../src/mcp_server.py) | **Completed** |
| **Week 6 Progress Report** | [`docs/weekly-reports/week-6-report.md`](week-6-report.md) | **Completed** |

---

## 5. Individual Contribution Summary

* **Modest Nakiroya:** State Modeling & Architecture  
  * Authored the official state specification at [`docs/architecture/state_model.md`](../../docs/architecture/state_model.md). Defined the LangGraph `AgentState` schema, field mutation rules, lifecycle boundaries, and recursion guard limits.
* **Asiimire Praise:** Persistent Case History Implementation  
  * Implemented the persistent memory store in [`src/memory.py`](../../src/memory.py), structured JSONL disk storage, thread-safe access control, and initial round-trip unit tests in [`tests/test_memory.py`](../../tests/test_memory.py).
* **Marvin Bisaso:** Behavioral Safety Verification & Non-Silent Control Tests  
  * Authored the automated verification suite in [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py) and compiled empirical audit logs in [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md). Formally proved multi-tenant isolation and verified that past approvals cannot silently bypass HMAC gates.
* **Kirabo Edna Takaisa:** MCP Specification & Server Implementation  
  * Authored the JSON-RPC 2.0 interface specification at [`docs/architecture/mcp_interface_spec.md`](../../docs/architecture/mcp_interface_spec.md). Developed the working MCP FastAPI server in [`src/mcp_server.py`](../../src/mcp_server.py) and the interactive client in [`src/mcp_demo_client.py`](../../src/mcp_demo_client.py).
* **Ayebare Carlton:** Data Handling Governance & Deletion Lifecycle  
  * Authored the formal [`docs/architecture/memory_design_and_data_handling_note.md`](../../docs/architecture/memory_design_and_data_handling_note.md), implemented right-to-erasure and retention purge routines (`delete_user_case_history`, `purge_expired_records`) in [`src/memory.py`](../../src/memory.py), added test coverage in [`tests/test_memory.py`](../../tests/test_memory.py), normalized MCP documentation paths, and compiled the Week 6 Progress Report.

---

## 6. Repository & Project Management Links

* **GitHub Repository:** https://github.com/carltontrevor23/software-engineering-qa-agent  
* **ClickUp Board Link:** https://app.clickup.com/1200440000000401/v/li/1200440000008199

