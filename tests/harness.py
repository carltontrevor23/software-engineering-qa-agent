"""
tests/harness.py

Shared helpers for the agent tests.

  execute_tools(state)   one tool step as the agent's tool node does it: the guard
                         (guard_middleware.pre_call) -> the tool -> the workflow update
                         (guard_middleware.post_call). The human approval pause is NOT
                         part of this step; test it through the compiled graph.
  FixedCallsModel        a chat model that replays a fixed list of replies
  ExplodingModel         a chat model that fails the test if it is ever called
"""

import json
import sys
from pathlib import Path
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import guard_middleware
from agent_tools import TOOLS_BY_NAME


def execute_tools(state: dict) -> dict:
    """Run every tool call in the last AI message; return the state update (messages, workflow
    fields, hops + 1)."""
    hops = state.get("hops", 0) + 1  # the model step has already been counted when tools run
    changes: dict = {}
    messages: List[ToolMessage] = []
    for call in state["messages"][-1].tool_calls:
        current = {**state, **changes, "hops": hops}
        refusal, args = guard_middleware.pre_call(current, call)
        if refusal:
            messages.append(refusal)
            continue
        try:
            result: Any = TOOLS_BY_NAME[call["name"]].invoke(args)
            message = ToolMessage(content=json.dumps(result), tool_call_id=call["id"], name=call["name"])
        except Exception as exc:  # the tool node turns a bad call into an error message
            message = ToolMessage(content=str(exc), tool_call_id=call["id"], name=call["name"], status="error")
        command = guard_middleware.post_call(current, call, message)
        messages.extend(command.update["messages"])
        changes.update({k: v for k, v in command.update.items() if k != "messages"})
    return {"messages": messages, **changes, "hops": hops}


class FixedCallsModel(BaseChatModel):
    """Replies with script[n] on the n-th model call of a run."""

    script: List[Any]

    @property
    def _llm_type(self) -> str:
        return "fixed-calls"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FixedCallsModel":
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        turn = sum(isinstance(m, AIMessage) for m in messages)
        reply = self.script[min(turn, len(self.script) - 1)]
        return ChatResult(generations=[ChatGeneration(message=reply)])


class ExplodingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "exploding"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ExplodingModel":
        return self

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise AssertionError("the model must not be called")


def tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])
