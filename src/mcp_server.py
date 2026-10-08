"""
src/mcp_server.py

Week 6 Activity 5: MCP server exposing the existing subscription tools.

It reuses tool_calling._run_one_tool(), so the allow-list, case-history
printout, human approval gate and signed token all behave exactly as they do
inside the LangGraph agent. Nothing is re-implemented here.

Transport is streamable HTTP, NOT stdio: the approval gate uses input() on this
terminal, and stdio would use stdin for the MCP protocol itself.

Run:
    python src/mcp_server.py --mock      # fake backend, no real API needed
    python src/mcp_server.py             # real backend
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP

import tool_calling
from memory import record_case

mcp = FastMCP("inspectra-subscription")


def _call(tool_name: str, user_id: str):
    # The client can only pass user_id. approval_token is deliberately NOT part
    # of the MCP schema: _run_one_tool mints it after a real human approval.
    result = tool_calling._run_one_tool(tool_name, {"user_id": user_id})
    status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
    record_case(user_id, tool_name, status, 0)
    return result


@mcp.tool()
def get_user_subscription_status(user_id: str) -> dict:
    """Look up a user's current subscription tier, account status and balance. Read-only."""
    return _call("get_user_subscription_status", user_id)

@mcp.tool()
def upgrade_user_subscription(user_id: str, approval_token: str | None = None) -> dict:
    """Upgrade a user to PREMIUM and deduct $50.00. Requires human approval on the server console."""
    if approval_token is not None:
        record_case(user_id, "upgrade_user_subscription", "approval_required", 0)
        return {
            "status": "error",
            "error": "Client-supplied approval tokens are not accepted. Approval is minted server-side after human confirmation.",
        }
    return _call("upgrade_user_subscription", user_id)


if __name__ == "__main__":
    if "--mock" in sys.argv:
        from unittest.mock import patch

        fake = tool_calling._FakeResponse(
            200, {"status": "active", "tier": "STANDARD", "balance": 100.0}
        )
        patch("requests.get", return_value=fake).start()
        print("[mcp_server] MOCK backend: every user is active, STANDARD, $100.00")

    print("[mcp_server] Listening on http://127.0.0.1:8000/mcp")
    mcp.run(transport="streamable-http")
