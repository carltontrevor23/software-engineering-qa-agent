"""
src/mcp_demo_client.py

Week 6 Activity 5: demo client for the MCP server (evidence for the report).
Start the server first:  python src/mcp_server.py --mock
Then run:                python src/mcp_demo_client.py
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8000/mcp"


def show(label, result):
    text = result.content[0].text if result.content else ""
    print(f"{label}\n  isError={result.isError}\n  {text}\n")


async def main():
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools exposed:", [t.name for t in tools.tools], "\n")

            show("1. Read-only status lookup (no approval):",
                 await session.call_tool("get_user_subscription_status", {"user_id": "u123"}))

            print("2. Upgrade: approve or reject in the SERVER terminal...")
            show("   Upgrade result:",
                 await session.call_tool("upgrade_user_subscription", {"user_id": "u123"}))

            # Security evidence: the client cannot smuggle in its own approval token.
            try:
                r = await session.call_tool(
                    "upgrade_user_subscription",
                    {"user_id": "u123", "approval_token": "forged.token"},
                )
                show("3. Forged token attempt:", r)
            except Exception as e:
                print(f"3. Forged token attempt rejected: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
