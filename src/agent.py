"""
src/agent.py

The Inspectra QA agent, built the course way: create_agent + middleware (Week 8).

    build_agent()   -> compiled graph (pass a checkpointer for CLI/tests; Studio supplies its own)
    run(prompt)     -> final answer text, asking the human on the terminal at approval steps

Importing this module has no side effects: no key checks, no model, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

import approval
import workflow
from agent_state import InspectraState
from agent_tools import TOOLS, TOOLS_BY_NAME
from guard_middleware import (
    MAX_CALLS_PER_STEP,
    MAX_HOPS,
    STOPPED_MESSAGE,
    ApprovalGate,
    InspectraGuard,
    approval_config,
    model_failure_message,
)
from models import get_chat_model, model_label

# Versioned agent prompt (Week 5): the rules live in prompts/, not in code.
PROMPT_VERSION = "v2.0"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / f"agent_system_prompt_{PROMPT_VERSION}.txt"

AGENT_CONTRACT = {
    "goal": "For one requirement, propose and run tests in the sandbox, and either report a "
            "pass or draft an issue that a human approves or rejects.",
    "prompt_version": PROMPT_VERSION,
    "approved_tools": sorted(TOOLS_BY_NAME),
    "high_impact_tools": sorted(approval.HIGH_IMPACT_TOOLS & set(TOOLS_BY_NAME)),
    "max_hops": MAX_HOPS,
    "max_calls_per_step": MAX_CALLS_PER_STEP,
    "phases": list(workflow.PHASES),
    "stop_conditions": [
        "all_tests_passed",
        "issue_filed",
        "human_rejection",
        "tool_error",
        "requirement_not_found",
        "hop_budget_exhausted",
        "test_defect_reported",
    ],
}


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_middleware() -> list:
    """Order matters: the guard is outermost for tool calls; the approval gate pauses the run
    for the two high-impact tools only, and only for calls the guard would let through."""
    return [
        InspectraGuard(),
        ModelRetryMiddleware(
            max_retries=3, initial_delay=2.0, max_delay=40.0, on_failure=model_failure_message
        ),
        ApprovalGate(interrupt_on=approval_config()),
    ]


def build_agent(
    model: Any = None,
    tools: Optional[list] = None,
    checkpointer: Any = None,
    system_prompt: Optional[str] = None,
):
    """The compiled agent graph. The model is chosen here (INSPECTRA_MODEL), not at import."""
    return create_agent(
        model=model or get_chat_model(),
        tools=tools or TOOLS,
        system_prompt=system_prompt or load_system_prompt(),
        state_schema=InspectraState,
        middleware=build_middleware(),
        checkpointer=checkpointer,
        name="inspectra",
    )


def terminal_decision(action: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the human on the terminal. Used only by the CLI; Studio shows an approval card."""
    print("\n" + "=" * 65)
    print(" [HUMAN APPROVAL REQUIRED] - HIGHER-IMPACT ACTION INTERCEPTED")
    print("=" * 65)
    print(action.get("description", action.get("name", "")))
    print("-" * 65)
    try:
        approved = input(" Authorize this action? [y/N]: ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        approved = False
    return {"type": "approve"} if approved else {"type": "reject", "message": "Action rejected by human operator."}


def resume_value(interrupts: Any, decide: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Command:
    """One decision per action request in the interrupt, as HumanInTheLoopMiddleware expects."""
    request = interrupts[0].value
    return Command(resume={"decisions": [decide(action) for action in request["action_requests"]]})


def final_text(state: Dict[str, Any]) -> str:
    replies = [m for m in state["messages"] if isinstance(m, AIMessage) and m.content and not m.tool_calls]
    if not replies:
        return STOPPED_MESSAGE
    content = replies[-1].content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def run(prompt: str, decide: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        graph: Any = None) -> str:
    """Send one request through the agent and return the final answer."""
    from uuid import uuid4

    from langgraph.checkpoint.memory import InMemorySaver

    agent = graph or build_agent(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": uuid4().hex}}
    state = agent.invoke({"messages": [HumanMessage(content=prompt)]}, config)
    while state.get("__interrupt__"):
        state = agent.invoke(resume_value(state["__interrupt__"], decide or terminal_decision), config)
    print(f"[stop_reason] {state.get('stop_reason')} (phase {state.get('phase')})")
    return final_text(state)


if __name__ == "__main__":
    # Usage: python src/agent.py "Check REQ-2.1 against the code"
    if len(sys.argv) < 2:
        print('Usage: python src/agent.py "Check REQ-2.1 against the code"')
        sys.exit(1)
    print(f"model: {model_label()} | prompt {PROMPT_VERSION}")
    print(run(" ".join(sys.argv[1:])))
