"""
tests/test_agent_graph.py

The create_agent wiring: imports need no keys, the approval gate is configured as the
contract says, a call the guard refuses never reaches the human, the async path that
LangGraph Studio uses works, and the Studio factories build.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import agent
import approval
import guard_middleware
import models
import qa_tools
import sandbox
from harness import FixedCallsModel, tool_call
from offline import build_offline_agent

PROMPT = "Check REQ-2.1 (Tier Upgrades) against the code."


@pytest.fixture
def redirected(tmp_path, monkeypatch):
    generated = tmp_path / "generated"
    monkeypatch.setattr(sandbox, "GENERATED_DIR", generated)
    monkeypatch.setattr(sandbox, "ALLOWED_TEST_DIRS", [generated, sandbox.SUT_DIR / "tests"])
    monkeypatch.setattr(qa_tools, "ISSUES_DIR", tmp_path / "issues")
    return tmp_path


# ---------------------------------------------------------------------
# Models: chosen when the graph is built, never at import
# ---------------------------------------------------------------------

def test_live_providers_raise_a_clear_error_without_a_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(models.ModelConfigError, match="GROQ_API_KEY"):
        models.get_chat_model("groq")
    with pytest.raises(models.ModelConfigError, match="GEMINI_API_KEY"):
        models.get_chat_model("gemini")


def test_unknown_provider_is_refused(monkeypatch):
    monkeypatch.setenv("INSPECTRA_MODEL", "gpt-9")
    with pytest.raises(models.ModelConfigError, match="Unknown INSPECTRA_MODEL"):
        models.get_chat_model()


def test_default_provider_is_groq_and_label_never_holds_a_key(monkeypatch):
    monkeypatch.delenv("INSPECTRA_MODEL", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value_123456")
    assert models.provider_name() == "groq"
    assert "gsk_secret" not in models.model_label()


def test_scripted_model_gives_every_tool_call_a_unique_id():
    from demo_support import ScriptedLLM

    model = models.ScriptedChatModel()
    ids = {model.invoke([HumanMessage(content=PROMPT)]).tool_calls[0]["id"] for _ in range(5)}
    assert len(ids) == 5
    assert ScriptedLLM  # the scripted behaviour itself lives in demo_support


# ---------------------------------------------------------------------
# Approval gate configuration
# ---------------------------------------------------------------------

def test_approval_gate_covers_exactly_the_high_impact_tools_with_approve_or_reject_only():
    config = guard_middleware.approval_config()
    assert sorted(config) == sorted(approval.HIGH_IMPACT_TOOLS) == ["file_issue", "save_test_to_suite"]
    for name, entry in config.items():
        assert entry["allowed_decisions"] == ["approve", "reject"], f"{name}: reviewers must not edit"
        assert callable(entry["when"]) and callable(entry["description"])


def test_the_agent_includes_the_approval_middleware():
    stack = agent.build_middleware()
    assert any(isinstance(m, guard_middleware.InspectraGuard) for m in stack)
    hitl = next(m for m in stack if isinstance(m, HumanInTheLoopMiddleware))
    assert isinstance(hitl, guard_middleware.ApprovalGate)
    assert set(hitl.interrupt_on) == set(approval.HIGH_IMPACT_TOOLS)


def test_model_supplied_approval_token_is_replaced_by_a_server_minted_one(redirected):
    draft = qa_tools.draft_issue("REQ-2.1", "t", "s", ["test_x"])["draft_path"]
    call = {"name": "file_issue", "args": {"draft_path": draft, "approval_token": "forged.token"},
            "id": "c1", "type": "tool_call"}
    state = {"messages": [AIMessage(content="", tool_calls=[call])], "phase": "ISSUE_DRAFTED",
             "requirement_id": "REQ-2.1", "draft_path": draft}
    refusal, args = guard_middleware.pre_call(state, call)
    assert refusal is None
    assert args["approval_token"] != "forged.token"
    ok, _ = approval.verify_and_consume_token(args["approval_token"], "file_issue", {"draft_path": draft})
    assert ok


def test_a_call_the_guard_refuses_never_reaches_the_human(redirected):
    """file_issue in phase START: no approval card, an error result, nothing filed."""
    script = [tool_call("file_issue", {"draft_path": "evidence/issues/drafts/x.md"}),
              AIMessage(content="Stopping: the tool was refused.")]
    graph = agent.build_agent(model=FixedCallsModel(script=script), checkpointer=InMemorySaver())
    state = graph.invoke({"messages": [HumanMessage(content=PROMPT)]}, {"configurable": {"thread_id": "t"}})
    assert not state.get("__interrupt__")
    refused = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert "not allowed in phase START" in refused[0].content
    assert not (redirected / "issues" / "filed").exists()


# ---------------------------------------------------------------------
# The async path (LangGraph Studio runs graphs asynchronously)
# ---------------------------------------------------------------------

def test_async_run_pauses_for_approval_and_resumes(redirected):
    async def scenario():
        graph = build_offline_agent(planted_bug=True, checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "async"}}
        state = await graph.ainvoke({"messages": [HumanMessage(content=PROMPT)]}, config)
        assert state["__interrupt__"][0].value["action_requests"][0]["name"] == "file_issue"
        return await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), config)

    final = asyncio.run(scenario())
    assert (final["phase"], final["stop_reason"]) == ("DONE", "issue_filed")
    assert len(list((redirected / "issues" / "filed").glob("*.md"))) == 1


# ---------------------------------------------------------------------
# Studio factories
# ---------------------------------------------------------------------

def _load_studio_graph():
    spec = importlib.util.spec_from_file_location("studio_graph", PROJECT_ROOT / "studio" / "graph.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_langgraph_json_points_at_real_factories():
    config = json.loads((PROJECT_ROOT / "langgraph.json").read_text(encoding="utf-8"))
    assert set(config["graphs"]) == {"inspectra", "inspectra_offline"}
    module = _load_studio_graph()
    for target in config["graphs"].values():
        path, factory = target.rsplit(":", 1)
        assert (PROJECT_ROOT / path).is_file()
        assert callable(getattr(module, factory))


def test_studio_factories_build_without_any_api_key(monkeypatch):
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INSPECTRA_MODEL", "scripted")
    module = _load_studio_graph()
    assert asyncio.run(module.make_graph()) is not None
    assert asyncio.run(module.make_offline_graph()) is not None


def test_live_studio_graph_fails_with_a_clear_message_not_an_import_error(monkeypatch):
    monkeypatch.setenv("INSPECTRA_MODEL", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    module = _load_studio_graph()  # importing the file never needs a key
    with pytest.raises(models.ModelConfigError, match="GROQ_API_KEY"):
        asyncio.run(module.make_graph())


# ---------------------------------------------------------------------
# Model outages are reported as such, not as a requirement problem
# ---------------------------------------------------------------------

def test_model_outage_is_classified_as_model_unavailable_not_requirement_not_found():
    from langchain.agents.middleware import ModelRetryMiddleware

    retry = next(m for m in agent.build_middleware() if isinstance(m, ModelRetryMiddleware))
    reply = retry.on_failure(RuntimeError("503 UNAVAILABLE: high demand"))
    assert reply.startswith(guard_middleware.MODEL_UNAVAILABLE_PREFIX)

    state = {"messages": [HumanMessage(content=PROMPT), AIMessage(content=reply)],
             "phase": "START", "hops": 0}
    out = guard_middleware.InspectraGuard().after_model(state, None)
    assert out == {"phase": "STOPPED", "stop_reason": "model_unavailable"}


def test_model_failure_message_never_carries_a_secret(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 35)
    text = guard_middleware.model_failure_message(RuntimeError("bad key AIza" + "x" * 35))
    assert "AIza" + "x" * 35 not in text
    assert len(text) < 450
