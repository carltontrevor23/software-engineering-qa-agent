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
    AlreadyPremiumError,
    InactiveUserError,
    InsufficientFundsError,
    SubscriptionManager,
    UserNotFoundError,
)
import subscription_manager as sm
from approval import (
    HIGH_IMPACT_TOOLS,
    is_high_impact,
    request_human_approval,
    verify_and_consume_token,
)

SYSTEM_PROMPT = (
    "You are a subscription assistant. Use the available tools to answer.\n"
    "Rules for upgrades:\n"
    "1. Always call get_user_subscription_status for the user first. Never call "
    "upgrade_user_subscription before you have seen that result.\n"
    "2. In tool results, 'status' is the tool's own outcome (success/error/"
    "approval_required); 'account_status' is the user's account state.\n"
    "3. Only call upgrade_user_subscription if ALL of these hold: account_status "
    "is 'active', tier is not already 'PREMIUM', and balance is >= $50.00.\n"
    "4. If any condition fails, do not call upgrade_user_subscription; stop and "
    "tell the user exactly which condition failed.\n"
    "5. If a tool returns status 'error' or 'approval_required', stop and report "
    "it to the user. Do not retry."
)
LEDGER_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "ledgers")
manager = SubscriptionManager(ledger_dir=LEDGER_DIR)

# Upper bound on assistant -> tool round-trips per run.
MAX_HOPS = 4
# Hard limit: how many tool calls the agent may make in one step.
MAX_CALLS_PER_STEP = 1




class AgentState(MessagesState):
    hops: int


def _account_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Rename the account's 'status' to 'account_status' so it can't clobber the tool's own status."""
    fields = dict(data)
    fields["account_status"] = fields.pop("status", None)
    return fields


# Tool 1 — read-only, no approval needed.
@tool
def get_user_subscription_status(user_id: str) -> Dict[str, Any]:
    """Look up a user's current subscription tier, status and balance."""
    try:
        data = manager.fetch_user_data(user_id)
        return {"status": "success", "user_id": user_id, **_account_fields(data)}
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
        return {"status": "success", "user_id": user_id, **_account_fields(result)}
    except InactiveUserError:
        return {"status": "error", "error": "User account is not active."}
    except AlreadyPremiumError:
        return {"status": "error", "error": "User is already on the PREMIUM tier."}
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

AGENT_CONTRACT = {
    "goal": "Resolve one user's upgrade request: human-approved upgrade or explained refusal.",
    "approved_tools": sorted(TOOLS_BY_NAME),
    "high_impact_tools": sorted(HIGH_IMPACT_TOOLS & set(TOOLS_BY_NAME)),
    "max_hops": MAX_HOPS,
    "max_calls_per_step": MAX_CALLS_PER_STEP,
    "stop_conditions": [
        "success",
        "precondition_refusal",
        "human_rejection",
        "tool_error",
        "hop_budget_exhausted",
    ],
}

# STEP 1 — bind tools to the model.
llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME, 
    google_api_key=API_KEY,
    timeout=60,
    max_retries=3,
    )
llm_with_tools = llm.bind_tools(TOOLS)


# STEP 2 — model decides: answer directly, or call a tool?
def assistant(state: AgentState) -> Dict[str, Any]:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
   
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = llm_with_tools.invoke(messages)
            return {"messages": [response]}
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            import time
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                time.sleep(32)
            else:
                time.sleep(2)

# STEP 3 — run the requested tool with Human-in-the-Loop interception.

def _run_one_tool(tool_name: str, args: Dict[str, Any]) -> Any:
    tool_obj = TOOLS_BY_NAME.get(tool_name)          # allow-list check
    if tool_obj is None:
        return {"status": "error", "error": f"Unknown tool '{tool_name}'."}

    if is_high_impact(tool_name):                    # human hand-off
        approved, token, message = request_human_approval(tool_name, args)
        if not approved:
            return {"status": "approval_required", "error": message}
        args["approval_token"] = token               # signed, single-use
    return tool_obj.invoke(args)


def execute_tools(state: AgentState) -> Dict[str, Any]:
    last_message = state["messages"][-1]
    tool_messages = []
    for index, tool_call in enumerate(last_message.tool_calls):
        if index >= MAX_CALLS_PER_STEP:
            result: Any = {
                "status": "error",
                "error": "Only one tool call is allowed per step; this call was skipped.",
            }
        else:
            result = _run_one_tool(tool_call["name"], dict(tool_call.get("args", {})))
        tool_messages.append(
            ToolMessage(content=str(result), tool_call_id=tool_call["id"], name=tool_call["name"])
        )
    return {"messages": tool_messages, "hops": state.get("hops", 0) + 1}


# Stop condition — end the loop once the hop budget is spent.
def route_after_tools(state: AgentState) -> str:
    if state.get("hops", 0) >= MAX_HOPS:
        return END
    return "assistant"


# Stop condition — end the loop once the hop budget is spent.
def route_after_tools(state: AgentState) -> str:
    if state.get("hops", 0) >= MAX_HOPS:
        return END
    return "assistant"


# STEP 4 — wire into a graph; tools_condition routes tool calls vs END.
builder = StateGraph(AgentState)
builder.add_node("assistant", assistant)
builder.add_node("execute_tools", execute_tools)
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition, {"tools": "execute_tools", END: END})
builder.add_conditional_edges(
    "execute_tools", route_after_tools, {"assistant": "assistant", END: END}
)
graph = builder.compile()

STOPPED_MESSAGE = "Stopped: reached the maximum number of tool-call steps"


def run(prompt: str) -> str:
    """Sends one prompt through the graph and returns the model's final text answer."""
    result = graph.invoke({"messages": [HumanMessage(content=prompt)], "hops": 0})
    # Hop limit hit: the loop ended on a tool result instead of an AI reply.
    if not isinstance(result["messages"][-1], AIMessage):
        return STOPPED_MESSAGE
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