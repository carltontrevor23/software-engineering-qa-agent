"""
studio/graph.py

Graph factories served by LangGraph Studio (see langgraph.json). Both are async factories:
the model is chosen when the server builds the graph, so importing this file never fails
on a missing key. Studio supplies its own checkpointer, so none is passed.

Building the graph imports modules and reads the prompt file, which are blocking calls, so
each factory does that work in a worker thread instead of on the server's event loop.

  make_graph          the live agent (INSPECTRA_MODEL: groq | gemini | scripted)
  make_offline_graph  scripted model + fixture tests; no network, no quota. The code under test has
                      a planted bug by default (tests fail, an issue is drafted, a human approves
                      or rejects). Set INSPECTRA_OFFLINE_BUG=0 and restart the server for the
                      passing case, where the follow-ups (save, refine, ask about the code) work.
"""

import asyncio
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")


def _use_src() -> None:
    if SRC not in sys.path:
        sys.path.insert(0, SRC)


def _build_live():
    _use_src()
    from agent import build_agent

    return build_agent()


def _offline_bug() -> bool:
    """The offline code under test has a planted bug unless INSPECTRA_OFFLINE_BUG is 0/false/no/off."""
    return os.getenv("INSPECTRA_OFFLINE_BUG", "1").strip().lower() not in ("0", "false", "no", "off")


def _build_offline():
    _use_src()
    from offline import build_offline_agent

    return build_offline_agent(planted_bug=_offline_bug())


async def make_graph(config=None):
    return await asyncio.to_thread(_build_live)


async def make_offline_graph(config=None):
    return await asyncio.to_thread(_build_offline)

