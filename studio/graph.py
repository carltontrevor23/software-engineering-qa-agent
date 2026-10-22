"""
studio/graph.py

Graph factories served by LangGraph Studio (see langgraph.json). Both are async factories:
the model is chosen when the server builds the graph, so importing this file never fails
on a missing key. Studio supplies its own checkpointer, so none is passed.

Building the graph imports modules and reads the prompt file, which are blocking calls, so
each factory does that work in a worker thread instead of on the server's event loop.

  make_graph          the live agent (INSPECTRA_MODEL: groq | gemini | scripted)
  make_offline_graph  scripted model + fixture tests + planted bug; no network, no quota
  make_offline_pass_graph  the same without the bug: tests pass, so follow-ups (save, refine,
                      ask about the code) can be tried offline
"""

import asyncio
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


def _build_offline(planted_bug: bool = True):
    _use_src()
    from offline import build_offline_agent

    return build_offline_agent(planted_bug=planted_bug)


async def make_graph(config=None):
    return await asyncio.to_thread(_build_live)


async def make_offline_graph(config=None):
    return await asyncio.to_thread(_build_offline)


async def make_offline_pass_graph(config=None):
    return await asyncio.to_thread(_build_offline, False)
