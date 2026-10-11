"""
src/mcp_demo_client.py

Demo client for the Inspectra MCP server (Week 6, realigned): walks REQ-2.1 through
the QA tools and shows the server's security boundary.

Start the server first:  python src/mcp_server.py
Then run:                python src/mcp_demo_client.py

If the tests fail, step 5 waits for the human to approve or reject on the SERVER console.
"""

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8000/mcp"


def payload(result):
    text = result.content[0].text if result.content else "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def show(label, data):
    keep = {k: v for k, v in data.items() if k not in ("results", "failures")}
    print(f"{label}\n  {keep}\n")


async def main():
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools exposed:", [t.name for t in tools.tools], "\n")

            await session.call_tool("start_check", {})

            # Security evidence 1: the phase guard refuses out-of-order calls.
            show("0. file_issue before anything else (phase guard):",
                 payload(await session.call_tool("file_issue", {"draft_path": "evidence/issues/drafts/x.md"})))

            found = payload(await session.call_tool("search_requirements", {"query": "tier upgrade balance"}))
            show("1. search_requirements:", found)
            req = found["results"][0]["requirement_id"]

            proposed = payload(await session.call_tool("propose_tests", {"requirement_id": req}))
            show("2. propose_tests:", proposed)
            if proposed.get("status") != "success":
                return

            run = payload(await session.call_tool(
                "run_tests", {"requirement_id": req, "test_file": proposed["test_file"]}))
            show("3. run_tests:", run)

            if run.get("test_outcome") == "failed":
                draft = payload(await session.call_tool("draft_issue", {
                    "requirement_id": req,
                    "title": f"{req}: tests fail against the implementation",
                    "summary": "Filed from the MCP demo client.",
                    "failing_tests": [f["test_name"] for f in run.get("failures", [])],
                }))
                show("4. draft_issue:", draft)

                # Security evidence 2: a client cannot smuggle in its own approval token.
                show("5a. file_issue with a forged token:", payload(await session.call_tool(
                    "file_issue", {"draft_path": draft["draft_path"], "approval_token": "forged.token"})))

                print("5b. file_issue: approve or reject in the SERVER terminal...")
                show("    result:", payload(await session.call_tool("file_issue", {"draft_path": draft["draft_path"]})))
            else:
                print("Tests passed: nothing to file.")


if __name__ == "__main__":
    asyncio.run(main())
