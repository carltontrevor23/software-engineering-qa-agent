# Memory Design and Data Handling Note

**Project:** Software-Engineering QA Agent (Inspectra)  
**System:** Bounded Autonomous Subscription & QA Agent  
**Deliverable:** Week 6 Deliverable 2 (Activities 2 & 3: Memory, State, and Interoperability)  
**Date:** October 2026  
**Implementation Source:** [`src/memory.py`](../../src/memory.py), [`src/tool_calling.py`](../../src/tool_calling.py), [`src/approval.py`](../../src/approval.py)  
**Verification Evidence:** [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py), [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md)  

---

## 1. Executive Summary & Architectural Scope

This document specifies the design, operational justification, access control rules, retention limits, and deletion procedures for the persistent memory subsystem of **Inspectra**. 

In accordance with Week 6 requirements, Inspectra distinguishes between:
1. **Ephemeral Workflow/Session State (`AgentState`)**: In-memory, non-persistent, bounded LangGraph state that exists solely for the duration of a single `run(prompt)` invocation.
2. **Justified Persistent Memory (`CaseHistoryMemory`)**: An append-only, structured log stored on disk (`data/memory/case_history.jsonl`) that records operational execution outcomes to assist human decision-makers during high-impact action approvals.

Following the core principle of **bounded autonomy**, persistent memory in Inspectra operates in a strictly **advisory capacity for human approvers**. It does not persist raw conversational transcripts, does not alter the system prompt, and is strictly prohibited from bypassing human approval gates or forging authorization tokens.

---

## 2. What is Stored (and What is Excluded)

### 2.1 Storage Format and Location
* **Storage Medium:** Flat file on local disk in JSON Lines format (`.jsonl`).
* **Storage Path:** `data/memory/case_history.jsonl` (relative to project root).
* **Concurrency Control:** Process-level thread synchronization (`threading.Lock`) ensuring atomic appends and safe concurrent reads across worker threads.

### 2.2 Record Schema
Every entry in `case_history.jsonl` represents a completed or intercepted tool-call event. Each record conforms strictly to the following 5-field schema:

| Field Name | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `timestamp` | `string` (ISO-8601 UTC) | Exact UTC timestamp of the execution attempt. | `"2026-10-09T11:45:00.123456+00:00"` |
| `user_id` | `string` | Unique identifier of the user account subject to the operation. | `"u123"` |
| `tool_name` | `string` | The deterministic tool identifier invoked or intercepted. | `"upgrade_user_subscription"` |
| `status` | `string` | Outcome status code of the tool invocation. | `"success"`, `"failed_tier_downgrade_disallowed"`, `"approval_required"`, `"rejected"` |
| `hops` | `integer` | Count of reasoning hops consumed in the session prior to tool invocation. | `2` |

#### Canonical JSON Representation
```json
{
  "timestamp": "2026-10-09T11:45:00.123456+00:00",
  "user_id": "u123",
  "tool_name": "upgrade_user_subscription",
  "status": "success",
  "hops": 2
}
```

### 2.3 Explicit Data Minimization: What is Excluded
Under the GDPR principle of **data minimization** (Article 5(1)(c)), persistent memory excludes any data that is not strictly necessary for operational safety auditing:

1. **No Personally Identifiable Information (PII):** User emails, real names, phone numbers, IP addresses, and billing credentials are never captured in memory. Only an opaque `user_id` is maintained.
2. **No Natural Language Transcripts:** Raw user chat messages, conversational banter, and LLM internal reasoning chains are discarded when the session ends. They are never written to disk.
3. **No Cryptographic Tokens or Secrets:** HMAC-SHA256 authorization tokens (`approval_token`), server secrets, and API keys are strictly excluded from logs.
4. **No Unstructured Payloads:** Tool arguments that could potentially contain arbitrary text are discarded; only the static tool name and structured execution status code are persisted.

---

## 3. Why It is Stored (Justification)

Persistent case history is implemented to solve a concrete failure mode in multi-step AI agents: **context blindness during high-impact operations**.

### 3.1 Operational Rationale
When an autonomous agent requests human approval for a high-impact action (such as `upgrade_user_subscription`), evaluating the request in isolation creates severe blind spots:
* **Repeated Failure Detection:** An approver needs to know whether the user has experienced 4 consecutive failures in the last 10 minutes due to billing locks or system errors.
* **Brute-Force & Abuse Prevention:** If an adversarial user triggers repeated upgrade calls to stress internal APIs, the approver can immediately spot the burst of repeated requests and reject the action.
* **Operational Velocity:** Approvers can verify whether an upgrade request is an initial inquiry or a re-attempt following an infrastructure outage.

### 3.2 Legitimate Improvement Without Silent Control
As formally verified in [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py) and documented in [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md):
* **Contextual Uplift:** The human operator is provided with the user's last $N$ actions (default $N = 3$) at the moment of approval interception:
  ```text
  [CASE HISTORY] last 2 action(s) for u123:
    1. upgrade_user_subscription -> failed_tier_downgrade_disallowed (2026-10-09T11:30:12Z)
    2. get_user_subscription_status -> success (2026-10-09T11:42:01Z)
  [HUMAN APPROVAL REQUIRED] - HIGHER-IMPACT ACTION INTERCEPTED
  Tool: upgrade_user_subscription
  Arguments: {"user_id": "u123", "target_tier": "enterprise"}
  Authorize this action? [y/N]:
  ```
* **Strict Non-Silent Decision Boundary:** The presence of historical success records in `case_history.jsonl` **cannot**:
  * Bypass the human approval gate.
  * Reduce the required approval threshold.
  * Auto-generate a valid cryptographic approval token.
  * Alter the tool's deterministic validation rules.

---

## 4. Access Control & Security Boundaries: Who Can Access

Access to persistent memory is strictly governed by the principle of least privilege. The following Role-Based Access Control (RBAC) matrix governs all interactions:

| Actor / Component | Read Access | Write Access | Access Mechanism | Security Purpose |
| :--- | :---: | :---: | :--- | :--- |
| **Human Approver / Operator** | **Yes** | **No** | Formatted console / UI summary via `_run_one_tool()` | Inspect past actions before granting HMAC approval. |
| **Agent / LLM Core** | **No** | **No** | Completely firewalled; not present in `AgentState` | Prevents prompt-injection attacks and hallucinated authority. |
| **Execution Orchestrator** | **Yes** | **Yes** | `record_case()` and `get_case_history()` in `src/memory.py` | Appends completed tool outcomes; retrieves bounded history. |
| **End User / API Client** | **No** | **No** | No direct endpoint or RPC access | Prevents enumeration of operational logs across tenants. |
| **System Auditor / Admin** | **Yes** | **Yes (Purge)** | Direct log access / Administrative maintenance CLI | System monitoring, compliance audits, and data erasure. |

### 4.1 Tenant Isolation
To prevent multi-tenant data leakage:
* `get_case_history(user_id: str)` strictly filters records matching the exact target `user_id`.
* One user's execution history is never mingled with, or visible during the review of, another user's session.
* Tenant isolation is verified by automated regression test `test_memory_tenant_isolation`.

### 4.2 LLM Decoupling Firewall
A critical vulnerability in naive memory implementations is feeding historical logs directly into the LLM prompt. Inspectra enforces an architectural firewall:
* The LangGraph state schema (`AgentState`) contains strictly `messages: List[BaseMessage]` and `hops: int`.
* `case_history.jsonl` is read directly by the orchestrator tool runner and emitted exclusively to standard output (or human operator console).
* Memory entries are **never converted into `HumanMessage` or `ToolMessage`** objects in the LangGraph graph, guaranteeing that external actors cannot poison future LLM reasoning via forged historical status logs.

---

## 5. Retention Policy

To avoid unbounded log growth and adhere to data privacy standards, Inspectra applies a deterministic retention schedule:

### 5.1 Retention Schedule
* **Active Operational Window:** Case history records are retained for a rolling duration of **30 calendar days** from the record's `timestamp`.
* **Rationale for 30-Day Window:** Subscription billing cycles and dispute resolution windows operate on monthly cycles. A 30-day window provides sufficient operational context for billing reviews while preventing indefinite data hoards.
* **Retention Cap:** If an individual user account exceeds **50 historical records** within 30 days, older records for that user are pruned to prevent log saturation attacks.

### 5.2 Storage Capacity Bounds
Because records are minimal (~120 bytes per JSONL entry):
* $1,000$ tool executions $\approx$ $120\text{ KB}$.
* $100,000$ tool executions $\approx$ $12\text{ MB}$.
Storage overhead remains negligible, allowing file-locked JSONL storage to operate efficiently without heavy external database dependencies.

---

## 6. Deletion Procedures & Data Subject Rights

Inspectra provides clear operational mechanisms for purging persistent memory in compliance with GDPR Article 17 ("Right to be Forgotten") and system lifecycle policies.

### 6.1 User-Requested Erasure (Right to be Forgotten)
When a user requests erasure of their account data or exercises their right to be forgotten:
1. An administrator or automated account-deletion webhook triggers the purge function:
   ```python
   delete_user_case_history(user_id: str) -> int
   ```
2. The orchestrator acquires the process file lock (`_LOCK`).
3. `case_history.jsonl` is atomically read, all records matching `user_id` are excised, and the remaining records are written back.
4. The number of excised records is logged for audit compliance without retaining any personal identifiers.

### 6.2 Rolling Retention Purge Procedure
Automated maintenance purges expired records based on timestamp:
```python
purge_expired_records(retention_days: int = 30) -> int
```
* **Execution Frequency:** Scheduled to run daily as an administrative batch job or on application initialization.
* **Mechanism:** Records with `timestamp < (now - retention_days)` are filtered out atomically.
* **Zero Shadow Copies:** In accordance with secure erasure practices, temporary scratch buffers used during atomic rewrites are unlinked immediately.

### 6.3 Emergency / Test Teardown Purge
For test environments and sandbox resets:
* `clear_all_memory()` or direct deletion of `data/memory/case_history.jsonl` provides a clean slate.
* Unit test suites automatically use isolated temporary directories or mock file fixtures to prevent polluting production logs (see [`tests/test_memory.py`](../../tests/test_memory.py)).

---

## 7. Verification & Compliance Matrix

| Requirement (Course Brief Week 6) | Document Section | Implementation & Test Evidence | Status |
| :--- | :--- | :--- | :---: |
| **What is stored** | Section 2.1 – 2.2 | `record_case()` in [`src/memory.py`](../../src/memory.py) | **Verified** |
| **Data minimization (what is not stored)** | Section 2.3 | `AgentState` schema in [`src/tool_calling.py`](../../src/tool_calling.py) | **Verified** |
| **Why it is stored (justification)** | Section 3.1 – 3.2 | Operational review flow in [`src/tool_calling.py`](../../src/tool_calling.py) | **Verified** |
| **Who can access it (RBAC)** | Section 4.0 – 4.2 | `test_memory_tenant_isolation` in [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py) | **Verified** |
| **Retention policy** | Section 5.1 – 5.2 | Rolling 30-day / 50-record cap specification | **Specified** |
| **Deletion procedures** | Section 6.1 – 6.3 | Purge and erasure procedures specified | **Specified** |
| **Non-silent control guarantee** | Section 3.2 | `test_memory_never_silently_bypasses_human_approval` | **Verified** |

