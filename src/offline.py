"""
src/offline.py

The offline demo agent: a scripted model, the hand-written REQ-2.1 fixture tests, and
(optionally) a planted boundary defect in a temporary copy of the system under test.
No network and no API quota. Every scripted line is labelled [SCRIPTED LLM].

Only the two tools that touch the model or the SUT are swapped; names, schemas and
docstrings are identical to agent_tools.py, so the agent sees the same six tools.
The real sut/ folder is never modified.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator

from langchain_core.tools import tool

import demo_support
import qa_tools
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

    swapped = {"propose_tests": propose_tests, "run_tests": run_tests}
    return [swapped.get(t.name, t) for t in TOOLS]


def build_offline_agent(planted_bug: bool = True, checkpointer: Any = None, replan: bool = False):
    from agent import build_agent

    return build_agent(
        model=ScriptedChatModel(replan=replan),
        tools=offline_tools(planted_bug),
        checkpointer=checkpointer,
    )
