import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# The tests run against the bundled sample project, whatever the developer's .env selects.
# Empty values count as unset, and python-dotenv does not override variables that already exist.
for _name in ("INSPECTRA_REQUIREMENTS_DIR", "INSPECTRA_CODE_DIR", "INSPECTRA_CODE_MODULES", "INSPECTRA_TEST_WRITER"):
    os.environ[_name] = ""

# Same module objects that src/guard_middleware.py gets via `from memory/tracer import ...`.
import memory
import tracer


@pytest.fixture(autouse=True)
def isolated_case_history(tmp_path, monkeypatch):
    """Redirect the case-history and trace logs to temp files so tests never touch
    data/memory or evidence/traces/agent_traces.jsonl.
    Also drop any real GitHub credentials loaded from .env, so no test can file a real issue."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    memory_dir = tmp_path / "memory"
    monkeypatch.setattr(memory, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory, "MEMORY_FILE", os.path.join(str(memory_dir), "case_history.jsonl"))
    monkeypatch.setattr(tracer, "DEFAULT_TRACE_FILE", tmp_path / "agent_traces.jsonl")
    yield memory
