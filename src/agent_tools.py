"""
src/agent_tools.py

The six approved tools of the Inspectra agent (Week 4 contract; see docs/tools/tool_catalogue.md).
Thin LangChain wrappers: the implementations and their validation live in qa_tools.py.
These six names are the tool allow-list.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

import qa_tools


# Tool 1: read-only RAG search over docs/requirements.
@tool
def search_requirements(query: str, top_k: int = 3) -> Dict[str, Any]:
    """Search the requirement documents and return matching requirement ids, sources and text."""
    return qa_tools.search_requirements(query, top_k)


# Tool 2: model proposes pytest tests; written only to sandbox/generated/.
@tool
def propose_tests(requirement_id: str) -> Dict[str, Any]:
    """Propose pytest tests for one requirement (e.g. REQ-2.1) and save them in the sandbox."""
    return qa_tools.propose_tests(requirement_id)


# Tool 3: runs allowed test files in the sandbox (no shell, timeout, no secrets).
@tool
def run_tests(requirement_id: str, test_file: str) -> Dict[str, Any]:
    """Run a sandboxed test file for a requirement and report passed/failed counts."""
    return qa_tools.run_tests(requirement_id, test_file)


# Tool 4: low-impact simulated side effect, a local Markdown draft.
@tool
def draft_issue(
    requirement_id: str, title: str, summary: str, failing_tests: List[str]
) -> Dict[str, Any]:
    """Draft an issue (not filed) describing failing tests for a requirement."""
    return qa_tools.draft_issue(requirement_id, title, summary, failing_tests)


# Tool 5: HIGH IMPACT, files an issue; needs a human-approved signed token.
@tool
def file_issue(draft_path: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """File a drafted issue. Requires human approval."""
    return qa_tools.file_issue(draft_path, approval_token)


# Tool 6: HIGH IMPACT, adds a generated test to the repo's suite; needs approval.
@tool
def save_test_to_suite(test_file: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Copy a generated test into the system-under-test suite. Requires human approval."""
    return qa_tools.save_test_to_suite(test_file, approval_token)


TOOLS = [
    search_requirements,
    propose_tests,
    run_tests,
    draft_issue,
    file_issue,
    save_test_to_suite,
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
