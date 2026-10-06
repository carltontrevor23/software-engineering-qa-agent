# State Model — Week 6, Task 1

Project: Software-Engineering QA Agent (Inspectra)
Grounded in: src/tool_calling.py (AgentState), src/memory.py

This document makes explicit what was previously only implicit in
code: the shape of session state, its lifecycle, and who is allowed
to read or write each field. It also draws the line between session
state (this document) and persistent memory (src/memory.py, covered
separately under Week 6's memory activities), since the two are
easy to conflate but behave very differently.

============================================================
1. What counts as one session
============================================================
One session is one call to `run(prompt)`, corresponding to the
agent's bounded goal: resolve one user's upgrade request to either a
human-approved success or an explained refusal (see AGENT_CONTRACT
in tool_calling.py). A session begins when `graph.invoke(...)` is
called and ends when `run()` returns a final answer or the
`STOPPED_MESSAGE` (hop budget exhausted).

============================================================
2. The state object
============================================================
```python
class AgentState(MessagesState):
    hops: int
```

This extends LangGraph's built-in `MessagesState`, which itself
supplies one field:

| Field      | Type              | Written by                          | Read by                                   |
|------------|-------------------|--------------------------------------|--------------------------------------------|
| `messages` | list of Human/AI/ToolMessage | `assistant()` appends the model's response; `execute_tools()` appends one ToolMessage per executed tool call | `assistant()` reads the full list to build the next LLM call; `run()` reads it to extract the final text reply |
| `hops`     | int               | `execute_tools()` only, incremented exactly once per step | `route_after_tools()` only, to decide whether to loop back to `assistant` or stop |

Two things are deliberately NOT part of this state object, worth
calling out since their absence is a design decision, not an
oversight:
- **The system prompt.** `assistant()` builds
  `[SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]` fresh
  on every call. It is injected at read time, not stored in state,
  so it cannot drift or be overwritten mid-session.
- **Case history from memory.py.** `get_case_history()` is called
  directly inside `_run_one_tool()` and printed for the human
  approver. It is never written into `state["messages"]`, so it
  never reaches the LLM and never becomes part of this session's
  state. This is enforced, not just intended:
  `test_case_history_never_reaches_llm_or_token` asserts it directly.

============================================================
3. Lifecycle
============================================================
- **Created**: fresh at the start of `run()`, with
  `{"messages": [HumanMessage(content=prompt)], "hops": 0}`. Nothing
  is loaded from a prior session; state does not persist across
  separate `run()` calls.
- **Mutated**: each graph node returns a partial update that
  LangGraph merges into state. `assistant()` adds one AIMessage per
  call. `execute_tools()` adds one ToolMessage per executed tool
  call and increments `hops` by exactly 1, regardless of how many
  tool calls were requested in that step (`MAX_CALLS_PER_STEP = 1`
  enforces only one actually executes; extras get a "skipped" error
  message instead of being silently dropped).
- **Destroyed**: when `run()` returns, the state object is not
  written to disk anywhere. It exists only for the duration of one
  `graph.invoke()` call, in memory, in the Python process running
  the script.

============================================================
4. Session state vs. persistent memory
============================================================
These are two different things and this project already implements
both, worth being explicit about the boundary between them since
Week 6 asks for both a state model and a separate memory note:

| | Session state (this document) | Persistent memory (src/memory.py) |
|---|---|---|
| Scope | One `run()` call | One `user_id`, across all sessions |
| Storage | In-memory only, never written to disk | Appended to `data/memory/case_history.jsonl` |
| Lifetime | Destroyed when `run()` returns | Persists indefinitely across runs |
| Who can read it | The LLM (via `messages`), the routing logic (via `hops`) | Only the human approver, printed at the point of a high-impact tool call; never sent to the LLM or bound into an approval token |
| Influence on decisions | Directly: `hops` gates the stop condition, `messages` is what the LLM reasons over | Advisory only: informs a human before they approve or reject; does not alter what the LLM is told or automatically change the outcome |

============================================================
5. Bounds enforced through state
============================================================
Two hard limits are enforced purely through fields in this state
object, not through external configuration:
- `MAX_HOPS = 4`: `route_after_tools()` returns `END` once
  `state["hops"] >= MAX_HOPS`, regardless of whether the task
  actually finished. This is the session's iteration cap.
- `MAX_CALLS_PER_STEP = 1`: enforced inside `execute_tools()` by
  index-checking `last_message.tool_calls`, not by a state field,
  but it directly shapes how `hops` increments (one step, one
  executed call, one hop, no matter how many calls the model
  requested).