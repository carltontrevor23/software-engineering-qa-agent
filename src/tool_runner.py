"""
src/tool_runner.py

Runs one approved tool with the console approval gate. Used by the MCP server, which has no
Studio approval card: the human approves on the server console, and a signed single-use
token (approval.py) is minted only after that. The LangGraph agent does not use this; it
approves through HumanInTheLoopMiddleware (see guard_middleware.py).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import qa_tools
from agent_tools import TOOLS_BY_NAME
from approval import is_high_impact, request_human_approval
from memory import advisory, format_history, get_case_history, record_case


def run_one_tool(tool_name: str, args: Dict[str, Any], requirement_id: Optional[str] = None) -> Any:
    tool_obj = TOOLS_BY_NAME.get(tool_name)          # allow-list check
    if tool_obj is None:
        return {"status": "error", "error": f"Unknown tool '{tool_name}'."}

    if is_high_impact(tool_name):                    # human hand-off
        # Test-run history is printed for the human only; never sent to the LLM or hashed.
        case_key = requirement_id or qa_tools.requirement_id_from_args(args)
        history = get_case_history(case_key, limit=3, tool_name="run_tests")
        print(format_history(case_key, history))
        print(f"[ADVISORY] {advisory(history)} (advisory only - the decision is yours)")
        approved, token, message = request_human_approval(tool_name, args)
        if not approved:
            return {"status": "approval_required", "error": message}
        args["approval_token"] = token               # signed, single-use
    return tool_obj.invoke(args)


def record(requirement_id: str, tool_name: str, result: Any, hops: int) -> None:
    status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
    test_outcome = failed_count = None
    if tool_name == "run_tests" and status == "success":
        test_outcome = result.get("test_outcome")
        failed_count = result.get("failed", 0) + result.get("errors", 0)
    record_case(requirement_id, tool_name, status, hops, test_outcome, failed_count)
