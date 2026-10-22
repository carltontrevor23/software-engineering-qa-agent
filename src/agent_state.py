"""
src/agent_state.py

Session state for one Inspectra run (RAM only; Studio shows it in the state panel).

The workflow fields are written only from tool results (see workflow.py and
middleware.py), never from model text. workflow.FIELDS is the single list of them.
"""

from __future__ import annotations

from typing import Optional

from langchain.agents import AgentState
from typing_extensions import NotRequired


class InspectraState(AgentState):
    hops: NotRequired[int]
    requirement_id: NotRequired[Optional[str]]
    phase: NotRequired[str]
    test_file: NotRequired[Optional[str]]
    test_outcome: NotRequired[Optional[str]]
    draft_path: NotRequired[Optional[str]]
    stop_reason: NotRequired[Optional[str]]
    proposals_made: NotRequired[int]
