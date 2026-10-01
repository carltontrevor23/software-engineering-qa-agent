"""
week5_execution_traces.py — Step-by-step execution traces of the bounded
Sense -> Plan -> Act -> Observe -> Stop loop in src/tool_calling.py.

Uses a scripted fake model and a mocked user-lookup API, so it needs no API
key and makes no network calls. Run it: python week5_execution_traces.py
Output is printed and also saved to evidence/week5_execution_traces.txt.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch

import requests

os.environ.setdefault("GEMINI_API_KEY", "demo-key-not-used")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

import approval  # noqa: E402
import subscription_manager as sm  # noqa: E402
import tool_calling  # noqa: E402

EVIDENCE_PATH = os.path.join(ROOT, "evidence", "week5_execution_traces.txt")


# ---------------------------------------------------------------------
# Fake chat model — replays scripted AIMessage responses instead of
# calling Gemini.
# ---------------------------------------------------------------------

class FakeLLM:
    def __init__(self, responses):
        self._scripted = list(responses)

    def invoke(self, messages):
        if not self._scripted:
            raise AssertionError("Trace script ran out of scripted model responses.")
        return self._scripted.pop(0)


def tool_call_message(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def final_message(text):
    return AIMessage(content=text)


class FakeResponse:
    """Stands in for requests.Response from the external user-lookup API."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


# ---------------------------------------------------------------------
# Tracing — wraps the real compiled graph so tool_calling.run() streams
# it node-by-node and each step is printed as it happens.
# ---------------------------------------------------------------------

class TracingGraph:
    def __init__(self, graph):
        self._graph = graph

    def invoke(self, state):
        print(f"SENSE     user asks: {state['messages'][0].content}")
        final_state = state
        step = 0
        for mode, chunk in self._graph.stream(state, stream_mode=["updates", "values"]):
            if mode == "values":
                final_state = chunk
                continue
            for node, delta in chunk.items():
                step += 1
                for message in delta.get("messages", []):
                    print(f"  step {step} [{node:<13}] {describe(message)}")
                if "hops" in delta:
                    print(f"  {'':22} hops = {delta['hops']}/{tool_calling.MAX_HOPS}")
        return final_state


def describe(message):
    if isinstance(message, ToolMessage):
        return f"OBSERVE  {message.name} -> {message.content}"
    if isinstance(message, AIMessage) and message.tool_calls:
        call = message.tool_calls[0]
        return f"PLAN/ACT model calls {call['name']}({call['args']})"
    if isinstance(message, AIMessage):
        return f"STOP     model answers: {message.content}"
    return f"MESSAGE  {message!r}"


def trace(script, prompt):
    with patch.object(tool_calling, "llm_with_tools", FakeLLM(script)), \
         patch.object(tool_calling, "graph", TracingGraph(tool_calling.graph)):
        answer = tool_calling.run(prompt)
    print(f"RESULT    run() returned: {answer!r}")


class Tee:
    """Writes everything printed to both the console and the evidence file."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, text):
        for s in self._streams:
            s.write(text)

    def flush(self):
        for s in self._streams:
            s.flush()


def banner(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    ledger_dir = tempfile.mkdtemp(prefix="week5_trace_ledgers_")
    approval_requests = []

    def human_approves(tool_name, arguments):
        approval_requests.append((tool_name, arguments))
        print(f"  {'':22} HUMAN    approval requested for {tool_name}({arguments}) -> APPROVED")
        return True

    def ledger_written(user_id):
        return os.path.exists(os.path.join(ledger_dir, f"{user_id}.json"))

    print(f"Week 5 execution traces — generated {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Graph: tool_calling.graph (StateGraph(AgentState), MAX_HOPS = {tool_calling.MAX_HOPS})")
    print("Model: scripted FakeLLM | External API: mocked requests.get | Ledgers: temp dir")

    with patch.object(tool_calling.manager, "ledger_dir", ledger_dir), \
         patch.object(sm.requests, "get") as mock_get:
        approval.set_approval_hook(human_approves)
        try:
            # -----------------------------------------------------------
            # Scenario 1: eligible user, human approves, upgrade succeeds.
            # -----------------------------------------------------------
            banner("SCENARIO 1: Eligible user — approved and upgraded")
            print("u123 is active, STANDARD, balance $100.00. The model looks the user")
            print("up first, then calls the upgrade; the human gate approves it.\n")

            mock_get.return_value = FakeResponse(
                200, {"status": "active", "tier": "STANDARD", "balance": 100.0}
            )
            approval_requests.clear()
            trace(
                [
                    tool_call_message("get_user_subscription_status", {"user_id": "u123"}, "c1"),
                    tool_call_message("upgrade_user_subscription", {"user_id": "u123"}, "c2"),
                    final_message("Done: u123 is now on PREMIUM with a $50.00 balance."),
                ],
                "Please upgrade user u123 to premium.",
            )
            print(f"CHECK     approval requests: {len(approval_requests)} (expected 1)")
            print(f"CHECK     ledger written: {ledger_written('u123')} (expected True)")

            # -----------------------------------------------------------
            # Scenario 2: ineligible user, model refuses, no approval asked.
            # -----------------------------------------------------------
            banner("SCENARIO 2: Ineligible user (balance below $50) — refused, no approval")
            print("u_poor is active, STANDARD, balance $25.50. After the lookup the model")
            print("sees the balance is below $50 and stops without calling the upgrade,")
            print("so the human is never asked.\n")

            mock_get.return_value = FakeResponse(
                200, {"status": "active", "tier": "STANDARD", "balance": 25.50}
            )
            approval_requests.clear()
            trace(
                [
                    tool_call_message("get_user_subscription_status", {"user_id": "u_poor"}, "c1"),
                    final_message(
                        "I can't upgrade u_poor: the balance is $25.50, below the "
                        "$50.00 upgrade cost. No changes were made."
                    ),
                ],
                "Upgrade user u_poor to premium.",
            )
            print(f"CHECK     approval requests: {len(approval_requests)} (expected 0)")
            print(f"CHECK     ledger written: {ledger_written('u_poor')} (expected False)")

            # -----------------------------------------------------------
            # Scenario 3: lookup service drops mid-loop; agent reports it.
            # -----------------------------------------------------------
            banner("SCENARIO 3: Lookup service fails mid-loop — reported, no crash")
            print("u456 looks eligible on the first lookup. After approval, the upgrade")
            print("re-fetches the user and the service raises ConnectionError. The tool")
            print("turns it into a structured error; the model reports it and stops.\n")

            mock_get.side_effect = [
                FakeResponse(200, {"status": "active", "tier": "STANDARD", "balance": 80.0}),
                requests.exceptions.ConnectionError("Connection reset by peer"),
            ]
            approval_requests.clear()
            trace(
                [
                    tool_call_message("get_user_subscription_status", {"user_id": "u456"}, "c1"),
                    tool_call_message("upgrade_user_subscription", {"user_id": "u456"}, "c2"),
                    final_message(
                        "I couldn't upgrade u456: the user lookup service is unavailable "
                        "right now, so no changes were made. Please try again later."
                    ),
                ],
                "Upgrade user u456 to premium.",
            )
            print(f"CHECK     approval requests: {len(approval_requests)} (expected 1)")
            print(f"CHECK     ledger written: {ledger_written('u456')} (expected False)")
        finally:
            approval.set_approval_hook(None)

    banner("Done")
    print("Tool results, approval gating, hop counting and routing above came from the")
    print("real src/tool_calling.py, src/approval.py and src/subscription_manager.py")
    print("running on the real LangGraph graph. Only the model's replies and the")
    print("external user-lookup API were scripted.")


if __name__ == "__main__":
    os.makedirs(os.path.dirname(EVIDENCE_PATH), exist_ok=True)
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as evidence:
        original_stdout = sys.stdout
        sys.stdout = Tee(original_stdout, evidence)
        try:
            main()
        finally:
            sys.stdout = original_stdout
    print(f"\nSaved to {os.path.relpath(EVIDENCE_PATH, ROOT)}")
