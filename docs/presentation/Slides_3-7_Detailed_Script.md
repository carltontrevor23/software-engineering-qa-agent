# Slides 3 to 7: detailed script

Your section runs from 1:45 to 8:45 (about 7 minutes): architecture, the road to a bounded agent, the
live demo, the state machine, and the approval gate. Slide numbers here are the **original** deck's.
In the deck with the added screenshots, the screenshot slide becomes 6, so the state machine is 7 and
the approval gate is 8.

## Check this before you present

**The window in your screenshots is `Inspectra_Presentation_backup_2026-11-03.pptx`: the OLD text.**
It still says "Gemini Flash client", "LangGraph StateGraph", "JSON-RPC 2.0, FastAPI" and
"Authorize this action? [y/N]". Present from the updated deck instead
(`Inspectra_Presentation_with_screenshots.pptx`, or `Inspectra_Presentation.pptx` with the text
updates). If you must use the old one, say the corrections aloud (they are marked **If the slide
still says...** below).

Setup, 5 minutes before:
1. `venv\Scripts\activate`, then `langgraph dev --no-reload`.
2. Studio: `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`, graph `inspectra_offline`,
   **Graph** view (not Chat), a fresh thread (**+ New**).
3. In `.env` the two `INSPECTRA_REQUIREMENTS_DIR` / `INSPECTRA_CODE_DIR` lines must be commented out
   (demo uses the subscription sample).
4. VS Code open with these tabs ready: `src/agent.py`, `src/workflow.py`,
   `src/guard_middleware.py`, `src/approval.py`.
5. Backup if Studio fails: `venv\Scripts\python.exe demo\run_demo.py --planted-bug`.

---

## Slide 3: System architecture (1:45-3:00, about 75 seconds)

**Goal:** the audience should leave knowing *where* the model sits and that one box (the approval gate)
is the only road to side effects.

**Say**
1. "Read it left to right. A request comes in from the operator, through LangGraph Studio, or through
   our MCP server, which is a second way in built on the same controls."
2. "The blue box is the agent loop: sense, plan, act, observe. Sense finds the requirement
   (`search_requirements`). Plan asks a model to write tests (`propose_tests`). Act runs them
   (`run_tests`). Observe drafts an issue if the code is wrong (`draft_issue`)."
3. "On the right are the things the loop uses. A model client: Groq by default, Gemini optional, and a
   scripted model for offline demos. A BM25 retriever over the markdown requirements. A sandbox runner
   with a timeout and an import allow-list. And the system under test: a small subscription service."
4. "The yellow box is the human approval gate. Only two actions need it: filing an issue and saving a
   test into the project. The gate checks a signed single-use token before either one runs."
5. "Bottom right: case history, the earlier test runs of the same requirement. It goes to the human
   approver only. The model never sees it. Bottom left: evidence, the traces, drafts and filed issues."

**If the slide still says...** "LangGraph StateGraph": "it's built with LangChain's `create_agent`
and three middleware layers." "Gemini Flash client": "the live model is Groq by default; Gemini is
optional." "JSON-RPC 2.0, FastAPI": "the MCP server runs over streamable HTTP."

**Point to:** `src/agent.py`, `build_agent` (line 82) and `build_middleware` (line 70). Show the three
middleware names: `InspectraGuard`, `ModelRetryMiddleware`, `ApprovalGate`.

**Transition:** "That is the shape today. It got here in four steps."

**Likely question:** *Why a scripted model?* "So the demo and the tests are repeatable with no network.
Every scripted line is labelled `[SCRIPTED LLM]`."

---

## Slide 4: From foundation model to bounded agent (3:00-4:00, 60 seconds)

**Goal:** show that each stage was added to fix a specific problem.

**Say** (one stage at a time, left to right; the bars rise to show growing capability)
1. **Week 2, foundation model.** "We started with raw prompting. It was fluent but invented behaviour the
   requirements never stated, and assumed developer defaults over the spec."
2. **Week 3, retrieval.** "We added BM25 search over the requirements, so prompts carry the acceptance
   criteria. If nothing relevant is found, it says so (`NO_GROUNDED_TESTS_FOUND`,
   `NO_RELEVANT_REQUIREMENTS_FOUND`) instead of guessing."
3. **Week 4, tools.** "Six tools with simulated side effects, and an approval step that intercepts
   high-impact calls. Today there are eight tools: we added `read_code` and `refine_tests`."
4. **Weeks 5 to 8, bounded agent.** "Explicit state, a phase table, a step limit of 7, pinned files and
   a case history for the human. In Week 8 we rebuilt it on `create_agent` with middleware and it runs in
   LangGraph Studio."
5. Close with: "Capability and control grew together. That is the point of the staircase."

**If the slide still says** "WEEKS 5-7" and "LangGraph state machine": say "Weeks 5 to 8" and
"`create_agent` plus middleware".

**Point to:** `docs/architecture/` for the week-by-week diagrams. Optionally `src/agent_tools.py`, the
list `TOOLS` at line 79 (eight entries).

**Likely question:** *Why not start with the bounded agent?* "Each stage showed us what to bound. We
could not know the rules until we saw the failures."

---

## Slide 5: Demo, REQ-2.1 tier upgrade (4:00-6:00, about 2 minutes) LIVE

**Goal:** the audience sees a real bug found and stopped at the human gate.

**Before you click:** explain the two boxes. "Expected: the requirement says a balance of 50 dollars or
more upgrades the account and deducts 50. Observed: we planted one bug in a temporary copy of the code:
the check became `balance <= 50`, so a balance of exactly 50 is rejected." (The one-line change is
`if balance < self.UPGRADE_COST:` to `<=`, in `src/demo_support.py` at line 40.) "The real code is never
changed."

**Do (Studio, graph `inspectra_offline`, new thread)**
1. Send: `Check REQ-2.1 (Tier Upgrades) against the code.`
2. Narrate the steps as the state panel changes (the slide's six boxes):
   - **Retrieve:** the requirement is found; `phase REQUIREMENT_RESOLVED`.
   - **Propose:** tests are written to `sandbox/generated/`; `TESTS_PROPOSED`. Say: "offline these are
     hand-written fixture tests, labelled scripted, so it is repeatable. Live, the model writes them."
   - **Run:** the boundary test with balance exactly 50.00 fails with `InsufficientFundsError`;
     `TESTS_RUN_FAILED`. This is the red box on the slide.
   - **Draft:** the agent says it is a code defect, not a test defect, and drafts the issue;
     `ISSUE_DRAFTED`.
   - **Approve:** the run **pauses** at `file_issue`. Stop here. Say: "the next two slides are what
     happens at this pause."
3. Point at the state panel: "every field here is written from tool results, not from what the model says."

**If you have the new screenshot slide:** "Here is the same agent live on correct code: it wrote 6 tests,
all passed, and it filed nothing. It does not invent a problem."

**If the slide still says** `[y/N]` or the `python demo/run_demo.py` command: "In Studio the pause is an
approval card; the terminal command is our backup."

**If it breaks**
- Studio will not load: hard-reload (Ctrl+Shift+R) or run the backup terminal command.
- Live graph hits a rate limit: "that is the limitation on slide 10", and stay on the offline graph.

**Transition:** "Before I show the approval, here is why the agent could not do anything else."

**Likely question:** *Is the model deciding it is a code defect?* "Yes, the agent chooses between code
defect and test defect from the failure messages. For a test defect it files nothing."

---

## Slide 6: State machine and hard limits (6:00-7:00, 60 seconds)

**Goal:** the audience understands the agent cannot wander.

**Say**
1. "This is the phase table. A run moves forward: START, requirement found, tests proposed, tests run
   (passed or failed), issue drafted, done."
2. "Each phase allows only certain tools next. For example, after tests are proposed the only allowed tool
   is `run_tests`. `file_issue` is not allowed until an issue has been drafted. If the model asks for
   something else, the call is refused and the run ends."
3. "Four hard limits on the right. **MAX_HOPS = 7:** at most seven steps, so it cannot loop forever.
   **One call per step:** no parallel tool calls. **Pinned files:** it may only run or file the exact
   files created in this run. **Gated tools:** the phase decides what is allowed."
4. "The red box: STOPPED. A run ends there for a human rejection, an exhausted step budget, a tool error
   or an unavailable model, and always with a recorded reason. It does not crash."
5. Extra if time allows: "After a passing run, three more tools open up: save the tests, refine a test,
   or read the code. That is how follow-ups like 'Save those tests' work."

**Point to:** `src/workflow.py`, lines 33-42 (the table `ALLOWED_TOOLS_BY_PHASE`), `check_call` at line 79,
and `MAX_HOPS = 7` in `src/guard_middleware.py` at line 40.

**Transition:** "The last gate in that table is the one a person controls."

**Likely question:** *What stops the model asking for a forbidden tool?* "Nothing stops it asking; the
guard refuses before the tool runs, and the refusal is recorded."

---

## Slide 7: Human approval gate (7:00-8:45, about 105 seconds) LIVE

**Goal:** show both outcomes, and why even an approved call is safe.

**Say first:** "Back to the paused run. The agent attempted `file_issue`. The gate stopped it and shows
the human the exact action, its arguments, and the recent test history for this requirement with an
advisory, for example 'this has failed before'. The model never sees that history."

**Do: the reject path first** (it is the one that proves control)
1. In the resume box paste: `{"decisions": [{"type": "reject", "message": "No."}]}`
2. Show the result: the run ends `STOPPED`, `stop_reason human_rejection`. Nothing is filed; the draft
   stays in `evidence/issues/drafts/`. "No crash, no retry loop."

**Then the approve path** (new thread, or describe it if time is short)
1. Repeat the demo, then paste `{"decisions": [{"type": "approve"}]}`.
2. Explain: "Behind the scenes the guard now creates a signed token for this exact call. The tool checks
   it and consumes it. The draft is copied to `evidence/issues/filed/` and the run ends `DONE`."

**Explain the token (the strongest point)**
- "It is an HMAC-SHA256 signature over the tool name and its exact arguments. It expires in 120 seconds,
  and it works once. So the model cannot forge approval, and a bug elsewhere cannot file an issue on its
  own: the tool refuses without a valid token."
- "The reviewer can only approve or reject. There is no edit button, so they cannot swap the file after
  it was pinned."

**Be honest:** "Filing is local by default. It files on GitHub only if a token and repository are set, and
that path is not proven live."

**If the slide still says** "Authorize this action? [y/N]", "Issue moves", or "approval_required": "in
Studio it is an approval card; the draft is copied; and a rejection shows 'User rejected the tool call'."

**Point to:** `src/guard_middleware.py`: `ApprovalGate` (line 196) and `approval_config` (line 183);
`src/approval.py`: `create_approval_token` (line 85) and `verify_and_consume_token` (line 117).

**Transition to slide 8:** "That is one layer. There are six, and the next slide lists them."

**Likely questions**
- *Why a token, not a flag?* "A flag can be set by a bug or by injected text. The token is bound to the
  exact call, expires, and is single use."
- *What does the human see?* "The action, its arguments, and the case history with an advisory."
- *Can the model skip the gate?* "No. The two tools are on a fixed list, and the tool itself verifies the
  token."

---

## Timing and handover

| Slide | Target | Running total |
|---|---|---|
| 3 | 1:15 | 3:00 |
| 4 | 1:00 | 4:00 |
| 5 | 2:00 | 6:00 |
| 6 | 1:00 | 7:00 |
| 7 | 1:45 | 8:45 |

If the demo runs long, cut slide 4 to 40 seconds and skip the approve path on slide 7 (describe it).
**Never** cut the reject path: it is the proof of control.
