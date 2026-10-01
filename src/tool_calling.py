from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional
from unittest.mock import patch
import requests

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
from approval import (
    is_high_impact,
    request_human_approval,
    verify_and_consume_token,
)

SYSTEM_PROMPT = "You are a subscription assistant. Use the available tools to answer."
LEDGER_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "ledgers")
manager = SubscriptionManager(ledger_dir=LEDGER_DIR)

# Upper bound on assistant -> tool round-trips per run.
MAX_HOPS = 4


class AgentState(MessagesState):
    hops: int


# Tool 1 — read-only, no approval needed.
@tool
def get_user_subscription_status(user_id: str) -> Dict[str, Any]:
    """Look up a user's current subscription tier, status and balance."""
    try:
        data = manager.fetch_user_data(user_id)
        return {"status": "success", "user_id": user_id, **data}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except requests.exceptions.RequestException:
        return {"status": "error", "error": "User lookup service unavailable, try again later."}


# Tool 2 — state-changing: upgrades tier, deducts cost.
@tool
def upgrade_user_subscription(
    user_id: str, approval_token: Optional[str] = None
) -> Dict[str, Any]:
    """Upgrade a user's subscription to PREMIUM and deduct the upgrade cost."""
    # 1. Cryptographic token verification inside the tool boundary
    is_valid, reason = verify_and_consume_token(
        approval_token, "upgrade_user_subscription", {"user_id": user_id}
    )
    if not is_valid:
        return {"status": "approval_required", "error": reason}

    # 2. Perform the upgrade if verification succeeded
    try:
        result = manager.process_upgrade(user_id)
        return {"status": "success", "user_id": user_id, **result}
    except InactiveUserError:
        return {"status": "error", "error": "User account is not active."}
    except InsufficientFundsError:
        return {"status": "error", "error": "User balance is below the required threshold."}
    except UserNotFoundError:
        return {"status": "error", "error": "User not found."}
    except requests.exceptions.RequestException:
        return {"status": "error", "error": "User lookup service unavailable, try again later."}
    except OSError:
        return {
            "status": "error",
            "error": "Could not write upgrade to ledger, action not completed.",
        }


TOOLS = [get_user_subscription_status, upgrade_user_subscription]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}

# STEP 1 — bind tools to the model.
llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME, 
    google_api_key=API_KEY,
    timeout=60,
    max_retries=3,
    )
llm_with_tools = llm.bind_tools(TOOLS)


# STEP 2 — model decides: answer directly, or call a tool?
def assistant(state: MessagesState) -> Dict[str, Any]:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
   
# Retry once if the remote socket closed during human prompt delay
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = llm_with_tools.invoke(messages)
            return {"messages": [response]}
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            import time
            time.sleep(1)

# STEP 3 — run the requested tool with Human-in-the-Loop interception.
def execute_tools(state: MessagesState) -> Dict[str, Any]:
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]
    tool_name = tool_call["name"]
    call_id = tool_call["id"]
    args = dict(tool_call.get("args", {}))

    tool_obj = TOOLS_BY_NAME.get(tool_name)
    if tool_obj is None:
        result: Any = {"status": "error", "error": f"Unknown tool '{tool_name}'."}
    else:
        # Check if the tool modifies state or moves balance
        if is_high_impact(tool_name):
            approved, token, message = request_human_approval(tool_name, args)
            if not approved:
                result = {
                    "status": "error",
                    "error": f"Action blocked: {message}",
                }
            else:
                # Inject the signed, single-use token into the tool execution call
                args["approval_token"] = token
                result = tool_obj.invoke(args)
        else:
            result = tool_obj.invoke(args)

    return {
        "messages": [
            ToolMessage(content=str(result), tool_call_id=call_id, name=tool_name)
        ]
    }


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
    if not final_replies:
        return ""
    content = final_replies[-1].content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


class _FakeResponse:
    def __init__(self, status_code: int, payload: Optional[dict] = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


if __name__ == "__main__":
    os.makedirs(LEDGER_DIR, exist_ok=True)

    # Patch both targets so network calls are never attempted:
    with patch("subscription_manager.requests.get") as mock_sm_get, \
         patch("requests.get") as mock_global_get:
        
        fake_resp = _FakeResponse(
            200, {"status": "active", "tier": "STANDARD", "balance": 100.0}
        )
        mock_sm_get.return_value = fake_resp
        mock_global_get.return_value = fake_resp

        print("\n--- Query 1: Read-Only Lookup ---")
        print(run("What's the subscription status of user u123?"))

        print("\n--- Query 2: State Mutation (Upgrade) ---")
        print(run("Please upgrade user u123 to premium."))