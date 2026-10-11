"""
src/mcp_server.py

MCP server exposing the Inspectra QA tools (Week 4 realignment: minimal retarget;
the full interface spec is rewritten in the Week 6 realignment).

It reuses tool_calling._run_one_tool(), so the allow-list, case-history
printout, human approval gate and signed token all behave exactly as they do
inside the LangGraph agent. Nothing is re-implemented here.

Transport is streamable HTTP, NOT stdio: the approval gate uses input() on this
terminal, and stdio would use stdin for the MCP protocol itself.

Run:
    python src/mcp_server.py
"""

import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP

import tool_calling
from memory import record_case

mcp = FastMCP("inspectra-qa")


def _call(tool_name: str, args: Dict[str, Any]):
    # approval_token is deliberately NOT accepted from clients:
    # _run_one_tool mints it after a real human approval on this console.
    result = tool_calling._run_one_tool(tool_name, dict(args))
    status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
    record_case(tool_calling.qa_tools.requirement_id_from_args(args), tool_name, status, 0)
    return result


def _refuse_client_token(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    record_case(tool_calling.qa_tools.requirement_id_from_args(args), tool_name, "approval_required", 0)
    return {
        "status": "error",
        "error": "Client-supplied approval tokens are not accepted. Approval is minted server-side after human confirmation.",
    }


@mcp.tool()
def search_requirements(query: str, top_k: int = 3) -> dict:
    """Search the requirement documents. Read-only."""
    return _call("search_requirements", {"query": query, "top_k": top_k})


@mcp.tool()
def propose_tests(requirement_id: str) -> dict:
    """Propose pytest tests for a requirement; written only to the sandbox."""
    return _call("propose_tests", {"requirement_id": requirement_id})


@mcp.tool()
def run_tests(requirement_id: str, test_file: str) -> dict:
    """Run an allowed test file in the sandbox (no shell, timeout, no secrets)."""
    return _call("run_tests", {"requirement_id": requirement_id, "test_file": test_file})


@mcp.tool()
def draft_issue(requirement_id: str, title: str, summary: str, failing_tests: List[str]) -> dict:
    """Write a local issue draft. Nothing is filed."""
    return _call("draft_issue", {
        "requirement_id": requirement_id,
        "title": title,
        "summary": summary,
        "failing_tests": failing_tests,
    })


@mcp.tool()
def file_issue(draft_path: str, approval_token: Optional[str] = None) -> dict:
    """File a drafted issue. Requires human approval on the server console."""
    if approval_token is not None:
        return _refuse_client_token("file_issue", {"draft_path": draft_path})
    return _call("file_issue", {"draft_path": draft_path})


@mcp.tool()
def save_test_to_suite(test_file: str, approval_token: Optional[str] = None) -> dict:
    """Add a generated test to sut/tests. Requires human approval on the server console."""
    if approval_token is not None:
        return _refuse_client_token("save_test_to_suite", {"test_file": test_file})
    return _call("save_test_to_suite", {"test_file": test_file})


if __name__ == "__main__":
    print("[mcp_server] Listening on http://127.0.0.1:8000/mcp")
    mcp.run(transport="streamable-http")
