"""
tests/test_testwriter.py

INSPECTRA_TEST_WRITER=groq sends the test-writing prompts (propose_tests, refine_tests) to Groq
instead of Gemini, with the same contract: text back, every call logged, ModelCallError on failure.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import model_client
import models


@pytest.fixture
def traces(tmp_path, monkeypatch):
    monkeypatch.setattr(model_client, "TRACES_DIR", tmp_path)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setenv("INSPECTRA_TEST_WRITER", "groq")
    return tmp_path


def logged(folder):
    files = list(folder.glob("trace_*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]


def test_default_writer_is_not_groq(monkeypatch):
    monkeypatch.delenv("INSPECTRA_TEST_WRITER", raising=False)
    assert model_client._use_groq() is False
    monkeypatch.setenv("INSPECTRA_TEST_WRITER", "GROQ")
    assert model_client._use_groq() is True


def test_groq_writer_returns_text_and_logs_the_call(traces, monkeypatch):
    chat = SimpleNamespace(invoke=lambda prompt: SimpleNamespace(content="```python\ndef test_x(): pass\n```"))
    monkeypatch.setattr(models, "get_chat_model", lambda provider=None, **kw: chat)
    text = model_client.get_model_response("write tests", prompt_version="t1")
    assert "def test_x" in text
    record = logged(traces)[0]
    assert record["status"] == "success" and record["model"].startswith("groq:") and record["prompt_version"] == "t1"


def test_groq_writer_accepts_list_content(traces, monkeypatch):
    chat = SimpleNamespace(invoke=lambda prompt: SimpleNamespace(content=[{"type": "text", "text": "hello"}, "!"]))
    monkeypatch.setattr(models, "get_chat_model", lambda provider=None, **kw: chat)
    assert model_client.get_model_response("p") == "hello!"


def test_groq_writer_retries_then_reports_a_clear_error(traces, monkeypatch):
    calls = []

    def invoke(prompt):
        calls.append(1)
        raise RuntimeError("503 service unavailable")

    monkeypatch.setattr(models, "get_chat_model", lambda provider=None, **kw: SimpleNamespace(invoke=invoke))
    with pytest.raises(model_client.ModelCallError, match="after retries"):
        model_client.get_model_response("p", max_retries=2)
    assert len(calls) == 3
    assert logged(traces)[-1]["status"] == "failed"


def test_groq_writer_recovers_after_a_transient_error(traces, monkeypatch):
    state = {"n": 0}

    def invoke(prompt):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("timeout")
        return SimpleNamespace(content="ok")

    monkeypatch.setattr(models, "get_chat_model", lambda provider=None, **kw: SimpleNamespace(invoke=invoke))
    assert model_client.get_model_response("p") == "ok"


def test_missing_groq_key_is_a_model_call_error(traces, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(model_client.ModelCallError, match="GROQ_API_KEY"):
        model_client.get_model_response("p")


def test_groq_chat_model_leaves_room_for_the_answer(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)
    chat = models.get_chat_model("groq", reasoning_effort="low")
    assert chat.max_tokens == models.GROQ_MAX_TOKENS >= 4096
    assert chat.reasoning_effort == "low"
    assert models.get_chat_model("groq").reasoning_effort is None
