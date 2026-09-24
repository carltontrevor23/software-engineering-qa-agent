from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import tools_condition

from model_client import API_KEY, MODEL_NAME
from subscription_manager import (
    InactiveUserError,
    InsufficientFundsError,
    SubscriptionManager,
    UserNotFoundError,
)
import subscription_manager as sm

SYSTEM_PROMPT = "You are a subscription assistant. Use the available tools to answer."
manager = SubscriptionManager()


# Tool 1 — read-only, no approval needed.
@tool
def get_user_subscription_status(user_id: str) -> Dict[str, Any]:
    """Look up a user's current subscription tier, status and balance."""
    try:
        data = manager.fetch_user_data(user_id)
        return {"status": "success", "user_id": user_id, **data}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}


# Tool 2 — simulated side effect: upgrades tier, deducts cost.
@tool
def upgrade_user_subscription(user_id: str) -> Dict[str, Any]:
    """Upgrade a user's subscription to PREMIUM and deduct the upgrade cost."""
    try:
        result = manager.process_upgrade(user_id)
        return {"status": "success", "user_id": user_id, **result}
    except InactiveUserError:
        return {"status": "error", "error": "User account is not active."}
    except InsufficientFundsError:
        return {"status": "error", "error": "User balance is below the required threshold."}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}


TOOLS = [get_user_subscription_status, upgrade_user_subscription]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}

# STEP 1 — bind tools to the model.
llm = ChatGoogleGenerativeAI(model=MODEL_NAME, google_api_key=API_KEY)
llm_with_tools = llm.bind_tools(TOOLS)


# STEP 2 — model decides: answer directly, or call a tool?
def assistant(state: MessagesState) -> Dict[str, Any]:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


# STEP 3 — run the requested tool, return the result as a ToolMessage.
def execute_tools(state: MessagesState) -> Dict[str, Any]:
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]
    tool_name = tool_call["name"]
    call_id = tool_call["id"]

    tool_obj = TOOLS_BY_NAME.get(tool_name)
    if tool_obj is None:
        result: Any = {"status": "error", "error": f"Unknown tool '{tool_name}'."}
    else:
        result = tool_obj.invoke(tool_call["args"])

    return {"messages": [ToolMessage(content=str(result), tool_call_id=call_id, name=tool_name)]}


# STEP 4 — wire into a graph; tools_condition routes tool calls vs END.
builder = StateGraph(MessagesState)
builder.add_node("assistant", assistant)
builder.add_node("execute_tools", execute_tools)
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition, {"tools": "execute_tools", END: END})
builder.add_edge("execute_tools", "assistant")
graph = builder.compile()


def run(prompt: str) -> str:
    """Sends one prompt through the graph and returns the model's final text answer."""
    result = graph.invoke({"messages": [HumanMessage(content=prompt)]})
    final_replies = [m for m in result["messages"] if isinstance(m, AIMessage) and m.content]
    return final_replies[-1].content if final_replies else ""


class _FakeResponse:
    def __init__(self, status_code: int, payload: Optional[dict] = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


if __name__ == "__main__":
    # api.internal.service isn't a real reachable service — mocked
    # here the same way every test in this project mocks it.
    with patch.object(sm, "requests") as mock_requests:
        mock_requests.get.return_value = _FakeResponse(
            200, {"status": "active", "tier": "STANDARD", "balance": 100.0}
        )
        print(run("What's the subscription status of user u123?"))
        print(run("Please upgrade user u123 to premium."))