"""
Assistant Platform — Model Router
===================================

Resolves model names, dispatches to the correct backend (Copilot,
LMStudio, NotebookLM), and provides streaming/non-streaming interfaces.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial router with 3 backends

CONNECTS: GithubCopilotClient, LMSClient, NotebookLMSDK
CALLED BY: routes/api.py, routes/openai_compat.py
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Generator, List, Optional, Tuple

from apps.assistant.config import (
    ALIASES,
    COPILOT_MODEL_IDS,
    COPILOT_MODELS,
    DEFAULT_SETTINGS,
    resolve_model,
)

logger = logging.getLogger(__name__)


# ──── Backend Detection ──────────────────────────────────────────────

def _detect_backend(model: str) -> str:
    """Determine which backend handles this model.

    Returns: 'copilot', 'lmstudio', or 'nlm'
    """
    if model in ("nlm", "notebooklm") or model.startswith("nlm-"):
        return "nlm"
    if model in COPILOT_MODEL_IDS:
        return "copilot"
    # Check if it's a loaded LMStudio model
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        if client.is_available():
            local_models = client.get_models(loaded_only=False)
            for m in local_models:
                if model.lower() in m.key.lower():
                    return "lmstudio"
    except Exception:
        pass
    # Default to Copilot
    return "copilot"


# ──── Dispatch ───────────────────────────────────────────────────────

def dispatch(
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    system_prompt: str = "",
    **kwargs: Any,
) -> Tuple[str, str]:
    """Non-streaming dispatch to the correct backend.

    Returns:
        (response_text, provider_name)
    """
    resolved = resolve_model(model)
    backend = _detect_backend(resolved)

    # Prepend system prompt if provided and not already in messages
    if system_prompt and not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": system_prompt}] + messages

    if backend == "copilot":
        return _call_copilot(messages, resolved), "copilot"
    elif backend == "lmstudio":
        return _call_lmstudio(messages, resolved, temperature, max_tokens), "lmstudio"
    elif backend == "nlm":
        return _call_nlm(messages), "nlm"
    else:
        return _call_copilot(messages, resolved), "copilot"


def dispatch_stream(
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    system_prompt: str = "",
    **kwargs: Any,
) -> Generator[str, None, None]:
    """Streaming dispatch — yields content deltas.

    Only LMStudio supports true token-by-token streaming.
    Copilot and NLM yield the full response as a single chunk.
    """
    resolved = resolve_model(model)
    backend = _detect_backend(resolved)

    if system_prompt and not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": system_prompt}] + messages

    if backend == "lmstudio":
        yield from _stream_lmstudio(messages, resolved, temperature, max_tokens)
    elif backend == "copilot":
        text = _call_copilot(messages, resolved)
        yield text
    elif backend == "nlm":
        text = _call_nlm(messages)
        yield text


# ──── Backend Implementations ────────────────────────────────────────

def _call_copilot(messages: List[Dict[str, Any]], model: str) -> str:
    """Route to GitHub Copilot."""
    from engine.integrations.github_copilot_client import GithubCopilotClient

    account = DEFAULT_SETTINGS.get("account", "nihilistcod")
    client = GithubCopilotClient(account)
    thread_id = client.create_thread()

    # Copilot expects a single prompt — combine messages
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        else:
            parts.append(content)
    prompt = "\n\n".join(parts)

    response = client.send_message(thread_id, prompt, model=model)
    if isinstance(response, tuple):
        return response[0] if response[0] else str(response)
    return str(response)


def _call_lmstudio(
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Route to LMStudio local inference."""
    from engine.lmstudio.lms_client import get_lms_client

    client = get_lms_client()
    response = client.chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.content


def _stream_lmstudio(
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """Stream from LMStudio token-by-token."""
    from engine.lmstudio.lms_client import get_lms_client

    client = get_lms_client()
    for chunk in client.chat_stream(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        if chunk:
            yield chunk


def _call_nlm(messages: List[Dict[str, Any]]) -> str:
    """Route to NotebookLM via SDK or CDP."""
    # Extract the last user message as the question
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            prompt = msg.get("content", "")
            break
    if not prompt:
        prompt = messages[-1].get("content", "") if messages else ""

    # Try SDK first, fall back to CDP
    try:
        from engine.integrations.notebooklm_sdk import get_notebooklm_sdk
        sdk = get_notebooklm_sdk()
        if sdk.session.is_valid:
            # Use the first available notebook
            notebooks = sdk.list_notebooks()
            if notebooks:
                answer = sdk.ask(notebooks[0].id, prompt)
                return answer.answer if answer.answer else "(No response from NotebookLM)"
    except Exception as e:
        logger.debug("[Router] SDK NLM failed, trying CDP: %s", e)

    try:
        import asyncio
        from scripts.nlm_ask import ask
        return asyncio.run(ask(prompt, 9223))
    except Exception as e:
        logger.error("[Router] NLM failed (operation=nlm_ask): %s", e)
        return f"(NotebookLM unavailable: {e})"


# ──── Model Listing ──────────────────────────────────────────────────

def get_available_models() -> List[Dict[str, Any]]:
    """Get all models from all backends, grouped by vendor."""
    models = []

    # Copilot models (always available as static list)
    for m in COPILOT_MODELS:
        models.append({
            "id": m["id"],
            "vendor": m["vendor"],
            "backend": "copilot",
            "available": True,
        })

    # LMStudio models
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        if client.is_available():
            for m in client.get_models(loaded_only=False):
                models.append({
                    "id": m.key,
                    "vendor": "Local",
                    "backend": "lmstudio",
                    "available": True,
                })
    except Exception:
        pass

    # NLM
    models.append({
        "id": "nlm",
        "vendor": "Google (NotebookLM)",
        "backend": "nlm",
        "available": True,
    })

    return models


def get_model_count() -> int:
    """Quick count of available models."""
    return len(COPILOT_MODELS) + 1  # +1 for NLM


def check_backend_status() -> Dict[str, Dict[str, Any]]:
    """Check which backends are online."""
    status = {}

    # Copilot
    try:
        from engine.integrations.github_copilot_client import GithubCopilotClient
        client = GithubCopilotClient(DEFAULT_SETTINGS.get("account", "nihilistcod"))
        models = client.list_models()
        status["copilot"] = {"online": True, "models": len(models)}
    except Exception as e:
        status["copilot"] = {"online": False, "error": str(e)[:100]}

    # LMStudio
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        is_up = client.is_available()
        count = len(client.get_models(loaded_only=False)) if is_up else 0
        status["lmstudio"] = {"online": is_up, "models": count}
    except Exception as e:
        status["lmstudio"] = {"online": False, "error": str(e)[:100]}

    # NLM
    try:
        from engine.integrations.notebooklm_sdk import get_notebooklm_sdk
        sdk = get_notebooklm_sdk()
        status["nlm"] = {"online": sdk.session.is_valid, "models": 1}
    except Exception:
        status["nlm"] = {"online": False, "models": 0}

    return status
