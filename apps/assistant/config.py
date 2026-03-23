"""
Assistant Platform — Configuration
===================================

Port, defaults, model registry, and backend settings.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial configuration
"""
from __future__ import annotations

from pathlib import Path

# ──── Paths ──────────────────────────────────────────────────────────

APP_DIR = Path(__file__).parent
PROJECT_ROOT = APP_DIR.parent.parent
DATA_DIR = APP_DIR / "data"
DATABASE_PATH = DATA_DIR / "conversations.db"
UPLOAD_DIR = DATA_DIR / "uploads"

# ──── Server ─────────────────────────────────────────────────────────

APP_NAME = "CosySim Assistant"
APP_PORT = 5593
APP_HOST = "0.0.0.0"
SECRET_KEY = "cosysim-assistant-dev-key"

# ──── Defaults ───────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "default_model": "gpt-5.4",
    "temperature": 0.7,
    "max_tokens": 4096,
    "top_p": 1.0,
    "system_prompt": "You are a helpful assistant.",
    "account": "nihilistcod",
}

MAX_UPLOAD_MB = 50
MAX_HISTORY_MESSAGES = 100

# ──── Model Registry ─────────────────────────────────────────────────
# Reuses the alias + model list from scripts/model_proxy.py

ALIASES = {
    "opus": "claude-opus-4.6",
    "sonnet": "claude-sonnet-4.6",
    "haiku": "claude-haiku-4.5",
    "gpt5": "gpt-5.4",
    "gpt": "gpt-5.4",
    "codex": "gpt-5.3-codex",
    "gemini": "gemini-3.1-pro",
    "flash": "gemini-3-flash",
    "grok": "grok-code-fast-1",
    "gpt-4": "gpt-5.4",
    "gpt-4o": "gpt-5.4",
    "gpt-4-turbo": "gpt-5.4",
    "gpt-3.5-turbo": "gpt-5.4",
    "claude-3-opus": "claude-opus-4.6",
    "claude-3-sonnet": "claude-sonnet-4.6",
    "claude-3-haiku": "claude-haiku-4.5",
    "claude-3.5-sonnet": "claude-sonnet-4.6",
}

COPILOT_MODELS = [
    {"id": "claude-opus-4.6", "vendor": "Anthropic"},
    {"id": "claude-sonnet-4.6", "vendor": "Anthropic"},
    {"id": "claude-sonnet-4.5", "vendor": "Anthropic"},
    {"id": "claude-sonnet-4", "vendor": "Anthropic"},
    {"id": "claude-opus-4.5", "vendor": "Anthropic"},
    {"id": "claude-haiku-4.5", "vendor": "Anthropic"},
    {"id": "gpt-5.4", "vendor": "OpenAI"},
    {"id": "gpt-5.4-mini", "vendor": "OpenAI"},
    {"id": "gpt-5.3-codex", "vendor": "OpenAI"},
    {"id": "gpt-5.2-codex", "vendor": "OpenAI"},
    {"id": "gpt-5.2", "vendor": "OpenAI"},
    {"id": "gpt-5.1", "vendor": "OpenAI"},
    {"id": "gpt-5.1-codex-max", "vendor": "OpenAI"},
    {"id": "gpt-5-mini", "vendor": "OpenAI"},
    {"id": "gemini-3.1-pro", "vendor": "Google"},
    {"id": "gemini-3-pro", "vendor": "Google"},
    {"id": "gemini-3-flash", "vendor": "Google"},
    {"id": "gemini-2.5-pro", "vendor": "Google"},
    {"id": "grok-code-fast-1", "vendor": "xAI"},
]

COPILOT_MODEL_IDS = {m["id"] for m in COPILOT_MODELS}


def resolve_model(model: str) -> str:
    """Resolve aliases and partial matches to actual model ID."""
    if model in ALIASES:
        return ALIASES[model]
    for m in COPILOT_MODELS:
        if model.lower() == m["id"].lower():
            return m["id"]
    for m in COPILOT_MODELS:
        if model.lower() in m["id"].lower():
            return m["id"]
    return model
