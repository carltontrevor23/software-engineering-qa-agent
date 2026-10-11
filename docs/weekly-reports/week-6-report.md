# WEEKLY PROGRESS REPORT (WEEK 6)
**Course:** BSE4104 AI-Native & Agentic Engineering Capstone  
**Group:** GROUP S  
**Project:** Software-Engineering QA Agent (Inspectra)  
**Period:** 5th October – 9th October 2026 (revised 11th October 2026 after realignment)  
**Weekly Focus:** Make workflow state explicit, retain only justified memory, and connect capabilities through clear interfaces.

---

## 1. Work Completed Against Weekly Objectives

**Realignment first.** While reviewing Week 6 against our Week 1 charter, we found that Weeks 4–6
had drifted. The tools upgraded customer subscriptions and deducted money, instead of testing the
subscription service. On branch `realign/weeks-4-6` we retargeted the agent to the charter's QA
workflow: find requirement → propose tests → run them in a sandbox → draft an issue → file it after
human approval. The subscription service is now the system under test in `sut/`. The Week 6 work
below describes the realigned system.

* **Explicit workflow state.** `AgentState` in [`src/tool_calling.py`](../../src/tool_calling.py) now holds
  `messages`, `hops` and seven workflow fields: `requirement_id`, `phase`, `test_file`,
  `test_outcome`, `draft_path`, `stop_reason`, `proposals_made`.
  - The phase machine in [`src/workflow.py`](../../src/workflow.py) updates these from tool results only.
  - It refuses tools that are not allowed in the current phase, without executing them.
  - It pins `run_tests` / `file_issue` to the files produced earlier in the same run.
  - Spec: [`docs/architecture/state_model.md`](../../docs/architecture/state_model.md).
* **Justified persistent memory: requirement test-run history.** [`src/memory.py`](../../src/memory.py)
  appends metadata for each executed tool call to `data/memory/case_history.jsonl`, keyed by
  requirement id. Before `file_issue` or `save_test_to_suite`, the approver sees the last three
  `run_tests` outcomes and a deterministic advisory (`FIRST FAILURE` vs `RECURRING`).
* **Data handling.** [`docs/architecture/memory_design_and_data_handling_note.md`](../../docs/architecture/memory_design_and_data_handling_note.md)
  covers what is stored (7 metadata fields, no test output, code, requirement text or personal
  data), who can access it (developers on the machine and the approver; never the LLM), the 30-day
  retention (`purge_expired_records`) and deletion (`delete_requirement_history`).
* **Memory demonstration.** [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md)
  shows three real demo runs: pass, first failure (approved), recurring failure (rejected). The guard
  tests show the history never reaches the LLM or the approval token, and cannot bypass approval.
* **Interoperability.** Two pieces:
  - **External integration:** `file_issue` creates a GitHub issue when `GITHUB_TOKEN` and
    `GITHUB_REPO` are set, and otherwise files locally. Tested with mocked HTTP; it has not yet been
    run against a real GitHub repository.
  - **MCP interface:** [`src/mcp_server.py`](../../src/mcp_server.py) (FastMCP, streamable HTTP)
    exposes the QA tools with the same phase guard, sandbox and server-side approval. A full
    client–server round trip with [`src/mcp_demo_client.py`](../../src/mcp_demo_client.py) was run
    on 11 Oct (offline model).
  - Spec: [`docs/architecture/mcp_interface_spec.md`](../../docs/architecture/mcp_interface_spec.md).

---

## 2. Key Engineering Decisions and Rationale

1. **Realign rather than continue the drift.** A QA agent that moves money contradicts our charter
   and sits close to the brief's prohibited financial decisions. We kept the subscription service
   as the system under test, which reused our requirements corpus, RAG and approval gate.
2. **State is set from tool results, not model text.** The model only asks for a tool; code decides
   what the result means. This is what lets the phase guard and file pinning block a confused or
   prompt-injected model.
3. **Memory is advisory and human-only.** History is printed for the approver and never sent to the
   model, so it cannot steer the model and cannot approve anything.
4. **MCP over streamable HTTP, approval on the server console.** Clients cannot supply approval
   tokens; the human at the server decides.

---

## 3. Challenges and Current Responses

### Design drift from the charter
* **Challenge:** Weeks 4–6 built a subscription-upgrade agent instead of the QA agent in our Week 1
  charter.
* **Response:** Realigned in three commits on `realign/weeks-4-6`. This drift is also recorded as a
  genuine failure for the Week 7 Failure Catalogue.

### Model quota and availability
* **Challenge:** On 11 Oct, Gemini returned `503 high demand` repeatedly and then `429` after the
  free-tier limit of 20 requests per day. One live end-to-end run uses about 5–8 requests.
* **Response:** `demo/run_demo.py --offline` runs the same graph and tools with a clearly labelled
  scripted LLM. Traces record which mode produced them. Live demo runs must be budgeted.

### Concurrent writes to the memory file
* **Challenge:** Concurrent runs in one process could interleave JSON lines.
* **Response:** A `threading.Lock` guards reads and writes in `src/memory.py`. This does not cover
  separate processes writing at the same time.

### Test isolation
* **Challenge:** Tests must not touch the real memory file, real issue folders or GitHub.
* **Response:** `tests/conftest.py` redirects the memory file to a temp folder and removes
  `GITHUB_TOKEN` / `GITHUB_REPO` for every test; tests redirect issue and sandbox folders to
  `tmp_path`, and mock the model. Note that `GEMINI_API_KEY` must still be present in `.env`,
  because `model_client.py` checks it at import time.

---

## 4. Deliverables Index

| Deliverable Name | File Location | Status |
| :--- | :--- | :---: |
| **State Model** | [`docs/architecture/state_model.md`](../../docs/architecture/state_model.md), [`src/workflow.py`](../../src/workflow.py) | Completed (realigned) |
| **Memory Design and Data Handling Note** | [`docs/architecture/memory_design_and_data_handling_note.md`](../../docs/architecture/memory_design_and_data_handling_note.md) | Completed (realigned) |
| **Working Memory/State Demonstration** | [`evidence/memory_evaluation_evidence.md`](../../evidence/memory_evaluation_evidence.md), [`tests/test_memory.py`](../../tests/test_memory.py), [`tests/test_memory_behavior.py`](../../tests/test_memory_behavior.py) | Completed (realigned) |
| **Integration / MCP Interface Specification** | [`docs/architecture/mcp_interface_spec.md`](../../docs/architecture/mcp_interface_spec.md), [`src/mcp_server.py`](../../src/mcp_server.py), GitHub filing in [`src/qa_tools.py`](../../src/qa_tools.py) | Completed (GitHub path not yet tried against a real repo) |
| **Week 6 Progress Report** | [`docs/weekly-reports/week-6-report.md`](week-6-report.md) | Revised 11 Oct |

---

## 5. Individual Contribution Summary

Original Week 6 work (5–9 Oct), on the earlier subscription design:

* **Modest Nakiroya:** State Modeling & Architecture: the original `state_model.md` (messages, hops, lifecycle).
* **Asiimire Praise:** Persistent Case History Implementation: the original `src/memory.py` JSONL store with locking, and the first round-trip tests in `tests/test_memory.py`.
* **Marvin Bisaso:** Behavioural Safety Verification: `tests/test_memory_behavior.py` and the first `evidence/memory_evaluation_evidence.md` (isolation between keys, no approval bypass).
* **Kirabo Edna Takaisa:** MCP Specification & Server: the first `mcp_interface_spec.md`, the FastMCP server in `src/mcp_server.py`, and `src/mcp_demo_client.py`.
* **Ayebare Carlton:** Data Handling & Deletion: the first data-handling note, `delete_user_case_history` / `purge_expired_records`, their tests, and the original Week 6 report.

Realignment (11 Oct), AI-assisted with Claude Code (see [`docs/ai-engineering-log.md`](../ai-engineering-log.md)):

* **Owner / reviewer:** _to be filled in by the team_. Covers the Week 6 parts of the realignment:
  workflow state and phase guard, requirement test-run memory, GitHub filing, MCP retarget, and the
  doc rewrites.

---

## 6. Repository & Project Management Links

* **GitHub Repository:** https://github.com/carltontrevor23/software-engineering-qa-agent  
* **ClickUp Board Link:** https://app.clickup.com/1200440000000401/v/li/1200440000008199
