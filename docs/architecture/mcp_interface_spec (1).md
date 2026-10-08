# MCP-Style Interface Specification — Week 6, Activity 5

Project: Software-Engineering QA Agent (Inspectra)
Grounded in: `src/tool_calling.py`, `src/approval.py`, `src/memory.py`, `docs/tools/tool_catalogue.md`

## 1. Overview

**Capability documented:** *Subscription upgrade resolution*, the one bounded
workflow the agent already implements (see `AGENT_CONTRACT` in `tool_calling.py`).

Today this capability lives inside one Python process: the LangGraph agent calls
tools in-process. This document specifies how the same capability would be
exposed as an **MCP server** (`inspectra-subscription`) so any MCP-compatible
client (an IDE, another agent, a CLI) could use it without knowing our internals.
No behaviour changes: the spec describes the existing tools behind a protocol boundary.

```
MCP Client (LLM + host app)
        |  JSON-RPC (stdio / streamable HTTP)
        v
MCP Server: inspectra-subscription
   |-- Tools:     get_user_subscription_status, upgrade_user_subscription
   |-- Policy:    allow-list, hop budget, 1 call/step
   |-- Approval:  human gate -> HMAC single-use token
   |-- Audit:     case-history log (human-only)
        |
        v
SubscriptionManager -> external user API, local ledger files
```

## 2. Capability Summary

| Item | Value |
|---|---|
| Server name | `inspectra-subscription` |
| Transport | stdio (local, default); streamable HTTP only behind auth |
| Primitives exposed | **Tools** (2). No resources or prompts exposed. |
| Goal | Resolve one user's upgrade request: human-approved upgrade or explained refusal |
| Limits | `MAX_HOPS = 4`, `MAX_CALLS_PER_STEP = 1` |

## 3. Tools (Contracts)

### 3.1 `get_user_subscription_status` — read-only

**Input**
```json
{
  "type": "object",
  "properties": { "user_id": { "type": "string" } },
  "required": ["user_id"],
  "additionalProperties": false
}
```

**Output**
```json
{
  "status": "success | error",
  "user_id": "string",
  "tier": "FREE | STANDARD | PREMIUM",
  "account_status": "active | suspended | pending",
  "balance": 100.0,
  "error": "string | null"
}
```
Note: `status` is the tool outcome; `account_status` is the user's account state
(renamed in `_account_fields()` to avoid clobbering).

**Errors:** `"User not found."` (API non-200), `"User lookup service unavailable, try again later."` (network/timeout).

**Side effects:** none. **Approval:** not required.

### 3.2 `upgrade_user_subscription` — higher impact

**Input**
```json
{
  "type": "object",
  "properties": {
    "user_id": { "type": "string" }
    "approval_token": {"type": ["string", "null"]}
  },
  "required": ["user_id"]
}
```
The MCP schema exposes approval_token only so the server can explicitly refuse it. Any client-supplied token is rejected with an error and no approval prompt is raised. Real tokens are minted server-side only after a human approves.

**Output**
```json
{
  "status": "success | error | approval_required",
  "user_id": "string",
  "tier": "PREMIUM",
  "balance": 50.0,
  "error": "string | null"
}
```

**Errors**

| Condition | `status` | `error` |
|---|---|---|
| Token missing / invalid / expired / replayed | `approval_required` | specific reason |
| Human rejected | `approval_required` | "Action rejected by human operator." |
| Inactive account | `error` | "User account is not active." |
| Already PREMIUM | `error` | "User is already on the PREMIUM tier." |
| Balance < $50.00 | `error` | "User balance is below the required threshold." |
| User not found | `error` | "User not found." |
| API unreachable | `error` | "User lookup service unavailable, try again later." |
| Ledger write failure | `error` | "Could not write upgrade to ledger, action not completed." |

**Side effects:** deducts $50.00, sets tier to PREMIUM, writes `data/ledgers/{user_id}.json`.

## 4. Permissions

| Tool | Impact | Who decides | Mechanism |
|---|---|---|---|
| `get_user_subscription_status` | Low | Server (automatic) | Allow-list only |
| `upgrade_user_subscription` | High (financial, ledger write) | **Human** | `HIGH_IMPACT_TOOLS` -> `request_human_approval()` -> signed token |

Anything not in `TOOLS_BY_NAME` is rejected (`"Unknown tool"`). No tool can be added at runtime.

## 5. Security Boundary

**Trust zones**

| Zone | Trusted? | Contains |
|---|---|---|
| MCP client / LLM | **Untrusted** (can be prompt-injected) | Prompts, tool-call requests |
| MCP server | Trusted | Allow-list, hop budget, approval gate, token verification |
| Human operator | Authority for high-impact actions | Approve / reject decisions |
| Backend | Trusted, isolated | `SubscriptionManager`, user API, ledger files |

**Controls**

1. **Allow-list**: only the two registered tools execute.
2. **Schema validation**: Pydantic rejects missing or wrong-typed arguments before any logic runs.
3. **Human gate**: the model cannot approve its own action; the gate runs outside the model's context.
4. **Signed token**: HMAC-SHA256, bound to tool name and argument hash, 120 s TTL, single-use nonce. Verified again *inside* the tool (defense in depth).
5. **Bounded loop**: max 4 hops, 1 tool call per step; extra calls return a "skipped" error.
6. **Structured errors only**: no stack traces or internal paths returned to the client.
7. **No secrets exposed**: API keys and `APPROVAL_SECRET_KEY` never appear in tool inputs or outputs.

**Memory boundary:** `case_history.jsonl` is **not** exposed as an MCP resource. It is shown only to the human approver and never reaches the LLM or the token (enforced by `test_case_history_never_reaches_llm_or_token`).

## 6. Example Interaction

```json
// Client -> Server
{"method": "tools/call", "params": {"name": "get_user_subscription_status", "arguments": {"user_id": "u123"}}}
// Server -> Client
{"status": "success", "user_id": "u123", "tier": "STANDARD", "account_status": "active", "balance": 100.0}

// Client -> Server
{"method": "tools/call", "params": {"name": "upgrade_user_subscription", "arguments": {"user_id": "u123"}}}
// Server pauses, shows case history, prompts human: approve? [y/N]
// Server -> Client (on approve)
{"status": "success", "user_id": "u123", "tier": "PREMIUM", "balance": 50.0}
// Server -> Client (on reject)
{"status": "approval_required", "error": "Action rejected by human operator."}
```
