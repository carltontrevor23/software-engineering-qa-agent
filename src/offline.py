"""
src/offline.py

The offline demo agent: a scripted model, the hand-written REQ-2.1 fixture tests, and
(optionally) a planted boundary defect in a temporary copy of the system under test.
No network and no API quota. Every scripted line is labelled [SCRIPTED LLM].

Only the two tools that touch the model or the SUT are swapped; names, schemas and
docstrings are identical to agent_tools.py, so the agent sees the same tools. The fixture model replies with the same
hand-written tests for a refinement, so an offline refinement shows the flow, not new tests.
The real sut/ folder is never modified.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from langchain_core.tools import tool

import demo_support
import qa_tools
import sandbox
from agent_tools import TOOLS
from models import ScriptedChatModel


@contextmanager
def _fixture_model() -> Iterator[None]:
    saved = qa_tools.get_model_response
    qa_tools.get_model_response = demo_support.fixture_model_reply
    try:
        yield
    finally:
        qa_tools.get_model_response = saved


def offline_tools(planted_bug: bool = True) -> list:
    @tool
    def propose_tests(requirement_id: str) -> Dict[str, Any]:
        """Propose pytest tests for one requirement (e.g. REQ-2.1) and save them in the sandbox."""
        with _fixture_model():
            return qa_tools.propose_tests(requirement_id)

    @tool
    def run_tests(requirement_id: str, test_file: str) -> Dict[str, Any]:
        """Run a sandboxed test file for a requirement and report passed/failed counts."""
        if not planted_bug:
            return qa_tools.run_tests(requirement_id, test_file)
        with demo_support.planted_bug_sut():
            return qa_tools.run_tests(requirement_id, test_file)

    @tool
    def refine_tests(requirement_id: str, test_file: str, instruction: str) -> Dict[str, Any]:
        """Write a new test file from the previous test_file, changed as the user asked (for example
        'add a test for a negative balance'). Then run it with run_tests."""
        with _fixture_model():
            return qa_tools.refine_tests(requirement_id, test_file, instruction)

    @tool
    def save_test_to_suite(test_file: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
        """Copy a generated test into the system-under-test suite. Requires human approval."""
        # An offline demo must not add files to the real sut/tests: save into a temporary suite.
        real = sandbox.SUT_DIR
        sandbox.SUT_DIR = Path(tempfile.mkdtemp(prefix="inspectra_offline_suite_"))
        try:
            return qa_tools.save_test_to_suite(test_file, approval_token)
        finally:
            sandbox.SUT_DIR = real

    swapped = {
        "propose_tests": propose_tests, "run_tests": run_tests, "refine_tests": refine_tests,
        "save_test_to_suite": save_test_to_suite,
    }
    return [swapped.get(t.name, t) for t in TOOLS]


def build_offline_agent(planted_bug: bool = True, checkpointer: Any = None, replan: bool = False):
    from agent import build_agent

    return build_agent(
        model=ScriptedChatModel(replan=replan),
        tools=offline_tools(planted_bug),
        checkpointer=checkpointer,
    )
