"""
src/models.py

Chat-model factory for the Inspectra agent. The provider is chosen when the graph is
built (INSPECTRA_MODEL), never at import time, so a missing key cannot stop Studio from
loading the other graphs.

  groq       (default) ChatGroq, GROQ_API_KEY; model GROQ_MODEL (default openai/gpt-oss-20b)
  gemini     ChatGoogleGenerativeAI, GEMINI_API_KEY; model MODEL_NAME
  scripted   deterministic offline stand-in (demo_support.ScriptedLLM); no network
"""

from __future__ import annotations

import os
import uuid
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

DEFAULT_PROVIDER = "groq"
PROVIDERS = ("groq", "gemini", "scripted")
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
REQUEST_TIMEOUT_SECONDS = 60


class ModelConfigError(RuntimeError):
    """The selected model provider is unknown or its API key is missing."""


class ScriptedChatModel(BaseChatModel):
    """Offline chat model that follows the v2.0 agent rules deterministically.

    Every message it writes starts with "[SCRIPTED LLM]". Tool-call ids are made unique
    per call, because the agent matches tool results to calls by id.
    """

    replan: bool = False

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        import demo_support

        reply = demo_support.ScriptedLLM(replan=self.replan).invoke(messages)
        reply = AIMessage(
            content=reply.content,
            tool_calls=[{**call, "id": f"scripted-{uuid.uuid4().hex[:8]}"} for call in reply.tool_calls],
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])


def provider_name(provider: Optional[str] = None) -> str:
    name = (provider or os.getenv("INSPECTRA_MODEL") or DEFAULT_PROVIDER).strip().lower()
    if name not in PROVIDERS:
        raise ModelConfigError(f"Unknown INSPECTRA_MODEL '{name}'. Choose one of: {', '.join(PROVIDERS)}.")
    return name


def model_label(provider: Optional[str] = None) -> str:
    """Human-readable 'provider:model' for banners and traces. Never includes a key."""
    name = provider_name(provider)
    if name == "groq":
        return f"groq:{os.getenv('GROQ_MODEL', DEFAULT_GROQ_MODEL)}"
    if name == "gemini":
        return f"gemini:{os.getenv('MODEL_NAME', DEFAULT_GEMINI_MODEL)}"
    return "scripted"


def get_chat_model(provider: Optional[str] = None) -> BaseChatModel:
    name = provider_name(provider)
    if name == "scripted":
        return ScriptedChatModel()
    if name == "groq":
        if not os.getenv("GROQ_API_KEY"):
            raise ModelConfigError(
                "GROQ_API_KEY is not set. Add it to .env, or set INSPECTRA_MODEL=gemini or scripted."
            )
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,  # retries are handled by ModelRetryMiddleware
        )
    if not os.getenv("GEMINI_API_KEY"):
        raise ModelConfigError(
            "GEMINI_API_KEY is not set. Add it to .env, or set INSPECTRA_MODEL=groq or scripted."
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=os.getenv("MODEL_NAME", DEFAULT_GEMINI_MODEL),
        google_api_key=os.getenv("GEMINI_API_KEY"),
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
