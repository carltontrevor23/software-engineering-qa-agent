"""
src/mcp_server.py

MCP server exposing the Inspectra QA tools (Week 6, realigned).
Spec: docs/architecture/mcp_interface_spec.md

It reuses the agent's own controls instead of re-implementing them:
  - tool_runner.run_one_tool(): allow-list, test-run history + advisory printed
    for the human, the console approval gate, and the signed single-use token;
  - workflow.check_call()/apply_result(): the same phase guard and file pinning
    as the LangGraph agent (guard_middleware.py), kept per server session (one requirement at a time);
  - sandbox.py rules inside run_tests.

Clients can never supply approval tokens; approval happens on this console.

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

import qa_tools
import tool_runner
import workflow

mcp = FastMCP("inspectra-qa")

# One workflow per server session, so a client follows the same phases as the agent.
_session: Dict[str, Any] = workflow.new_workflow()


def _call(tool_name: str, args: Dict[str, Any]):
    blocked = workflow.check_call(_session, tool_name, args)
    if blocked:
        return {"status": "error", "error": blocked, "phase": _session["phase"]}
    result = tool_runner.run_one_tool(tool_name, dict(args), requirement_id=_session["requirement_id"])
    _session.update(workflow.apply_result(_session, tool_name, result))
    key = _session["requirement_id"] or qa_tools.requirement_id_from_args(args)
    tool_runner.record(key, tool_name, result, 0)
    return {**result, "phase": _session["phase"]} if isinstance(result, dict) else result


def _refuse_client_token() -> Dict[str, Any]:
    return {
        "status": "error",
        "error": "Client-supplied approval tokens are not accepted. Approval is minted server-side after human confirmation.",
        "phase": _session["phase"],
    }


@mcp.tool()
def start_check() -> dict:
    """Start a new requirement check (resets the workflow to phase START)."""
    _session.clear()
    _session.update(workflow.new_workflow())
    return {"status": "success", "phase": _session["phase"]}


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
    """Run the test file proposed in this session, in the sandbox (no shell, timeout, no secrets)."""
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
    """File the draft written in this session. Requires human approval on the server console."""
    if approval_token is not None:
        return _refuse_client_token()
    return _call("file_issue", {"draft_path": draft_path})


@mcp.tool()
def save_test_to_suite(test_file: str, approval_token: Optional[str] = None) -> dict:
    """Add the passing generated test to sut/tests. Requires human approval on the server console."""
    if approval_token is not None:
        return _refuse_client_token()
    return _call("save_test_to_suite", {"test_file": test_file})


if __name__ == "__main__":
    print("[mcp_server] Listening on http://127.0.0.1:8000/mcp")
    mcp.run(transport="streamable-http")
