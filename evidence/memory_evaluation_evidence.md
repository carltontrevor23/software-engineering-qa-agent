# Memory Evaluation Evidence: Task Improvement & Safety Verification
**Project:** Software-Engineering QA Agent (Inspectra)  
**Deliverable:** Week 6, Activity 4  
**Date:** October 7, 2026  

---

## 1. Objective and Justified Use Case
Inspectra implements persistent case history (`src/memory.py`) to provide human operators with historical execution context prior to authorizing high-impact actions (such as tier upgrades and ledger mutations).

This evaluation demonstrates two mandatory properties required by Week 6 Activity 4:
1. **Legitimate Task Improvement:** Memory equips human operators with actionable operational context (recent user attempts, previous failures, and iteration counts) without polluting the LLM context window.
2. **Absence of Silent Control:** Historical approval memory cannot bypass authorization gates, forge HMAC tokens, or autonomously trigger state mutations.

---

## 2. Comparative Evaluation Matrix

| Metric | Without Memory (Stateless) | With Persistent Memory (`src/memory.py`) |
| :--- | :--- | :--- |
| **Operator Context** | Human approver sees only the instantaneous tool name and arguments (`{"user_id": "u123"}`). | Operator sees instantaneous arguments plus the user's last 3 executions (timestamp, tool, outcome, and hops). |
| **Abuse / Loop Detection** | Approver cannot detect if a user has attempted 5 failed upgrades in the last 2 minutes. | Approver immediately spots repeated failure patterns (e.g., repeated `failed_insufficient_funds`). |
| **Token Consumption** | Baseline prompt tokens. | Exact same token count (memory is never injected into LLM `messages`). |
| **Safety Boundary** | Intercepted at human approval gate. | Intercepted at human approval gate (prior approval in memory does not auto-authorize). |

---

## 3. Demonstration of Non-Silent Control

### 3.1 The Vulnerability / Failure Mode (Silent Control)
In flawed agentic designs, persistent memory frequently introduces "silent control" risks:
* The agent inspects historical memory, notices that user `u123` was previously granted approval for an upgrade, and presumes future upgrades are pre-authorized.
* The system silently skips the human authorization gate, generating a synthetic approval token or calling state-mutating tools autonomously.

### 3.2 Inspectra's Architectural Defense
Inspectra eliminates silent control through strict architectural separation:
1. **Advisory Role Only:** Case history stored in `data/memory/case_history.jsonl` is read exclusively for console output to the human approver (`[CASE HISTORY] last N action(s)...`).
2. **Unconditional Gate Policy:** `is_high_impact("upgrade_user_subscription")` evaluates tool risk statically based on tool classification, regardless of whether memory is empty or contains prior successes.
3. **Cryptographic Token Binding:** Every state mutation requires an unconsumed, HMAC-SHA256 signed single-use token (`approval_token`). Tokens cannot be synthesized from past logs; they are generated only when the operator explicitly inputs `y/yes`.

### 3.3 Walkthrough Scenario
A user account (`u123`) was successfully upgraded in a prior session, which was logged in `case_history.jsonl`:

```json
{"timestamp": "2026-10-06T17:45:00Z", "user_id": "u123", "tool_name": "upgrade_user_subscription", "status": "success", "hops": 2}
```

In a subsequent session, a new upgrade request is initiated for `u123`:
1. **Sense:** Model inspects account status via `get_user_subscription_status("u123")`.
2. **Plan:** Model plans `upgrade_user_subscription("u123")`.
3. **Intercept & Surface:** `_run_one_tool` detects high-impact action, reads persistent memory, and surfaces context to the human:
   ```text
   [CASE HISTORY] last 1 action(s) for u123: upgrade_user_subscription -> success (2026-10-06T17:45:00Z)
   [HUMAN APPROVAL REQUIRED] - HIGHER-IMPACT ACTION INTERCEPTED
   Tool: upgrade_user_subscription
   Arguments: {"user_id": "u123"}
   Authorize this action? [y/N]:
   ```
4. **Gate Enforcement:**
   * If the human rejects (`auto_decision=False`), `request_human_approval` returns `(False, None, "Action rejected by human operator.")`.
   * The tool returns `{"status": "approval_required", "error": "Action rejected by human operator."}`.
   * `verify_and_consume_token(None)` rejects execution with `"Approval token missing"`.
   * **Result:** No mutation occurs, the ledger is untouched, and memory provides zero silent authorization leverage.

---

## 4. Architectural Isolation & LLM Decoupling

Inspectra maintains a strict firewall between persistent memory and LLM reasoning:

```
┌────────────────────────┐         ┌───────────────────────────────┐
│     Persistent Disk    │         │          AgentState           │
│ data/memory/case_hist  │         │  {"messages": [...], hops: N} │
└───────────┬────────────┘         └───────────────┬───────────────┘
            │ (Read by Orchestrator)               │
            ▼                                      ▼
┌────────────────────────┐         ┌───────────────────────────────┐
│  Human Operator Console│         │     LLM Reasoning Context     │
│ [CASE HISTORY] readout │         │ (Completely isolated from     │
│  (Human context only)  │         │  case history logs)           │
└────────────────────────┘         └───────────────────────────────┘
```

1. **State Cleanliness:** `AgentState` schema defines only `messages: List[BaseMessage]` and `hops: int`. Memory is never injected into `AgentState`.
2. **Injection Defense:** Malicious payloads stored in historical tool arguments or status messages cannot reach the LLM's system prompt or messages list, preventing prompt-injection attacks via historical logs.
3. **Multi-Tenant Isolation:** `get_case_history(user_id)` strictly partitions log entries by `user_id`. One user's history cannot leak into another user's approval gate.

---

## 5. Automated Verification & Test Evidence

All behavioral and safety guarantees are codified in the automated test suite [`tests/test_memory_behavior.py`](file:///C:/Users/PC%2012/Desktop/QA_agent/software-engineering-qa-agent/tests/test_memory_behavior.py):

| Test Case | Property Verified | Verification Mechanism | Status |
| :--- | :--- | :--- | :---: |
| `test_memory_surfaces_legitimate_audit_history` | Legitimate Task Improvement | Asserts history records ordered execution timestamps, status, and hop counts accurately. | **PASS** |
| `test_memory_tenant_isolation` | Multi-Tenant Data Isolation | Asserts `user_A` history is never visible or retrievable when querying `user_B`. | **PASS** |
| `test_memory_never_silently_bypasses_human_approval` | Non-Silent Control Guard | Asserts pre-seeded historical upgrade in memory does not bypass human gate or mint valid approval token. | **PASS** |
| `test_memory_not_in_llm_state` | Architectural State Isolation | Asserts `AgentState` schema contains only `messages` and `hops`, with no memory leakage into LLM state. | **PASS** |

### Test Execution Output
```text
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\PC 12\Desktop\QA_agent\software-engineering-qa-agent
plugins: anyio-4.13.0, langsmith-0.14.0
collected 4 items

tests\test_memory_behavior.py ....                                       [100%]

======================== 4 passed, 1 warning in 0.52s =========================
```

---

## 6. Conclusion & Compliance Summary

Inspectra's persistent memory design satisfies all requirements for Week 6 Activity 4:
* **Legitimate Improvement:** Surfaces actionable audit trails to human operators, enabling detection of repeated attempts, loops, and suspicious patterns.
* **Non-Silent Control:** Memory acts strictly as an advisory view for the human operator; it possesses zero capability to auto-approve, forge tokens, or bypass authorization gates.
* **Formally Verified:** Backed by 4 passing unit and safety tests in `tests/test_memory_behavior.py`.