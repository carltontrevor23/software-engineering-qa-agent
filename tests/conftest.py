import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Same module object that src/tool_calling.py gets via `from memory import ...`.
import memory


@pytest.fixture(autouse=True)
def isolated_case_history(tmp_path, monkeypatch):
    """Redirect the case-history log to a temp file so tests never touch data/memory."""
    memory_dir = tmp_path / "memory"
    monkeypatch.setattr(memory, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory, "MEMORY_FILE", os.path.join(str(memory_dir), "case_history.jsonl"))
    yield memory
