"""Lazy service getters shared between cosysim_server.py and domain tool files.

Avoids import-time side effects by deferring instantiation until first call.

All tool modules import these functions directly.  To mock them in tests,
patch the *function objects* via their ``_impl`` attribute::

    with patch("engine.mcp._lazy._get_db", return_value=mock_db):
        ...

This works because every module that does ``from engine.mcp._lazy import _get_db``
gets a reference to the same function object, and each call delegates to
``_overrides`` which ``patch`` can replace.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Override dict — tests can swap in mocks here.
_overrides: dict[str, Any] = {}


def _get_db():
    if "db" in _overrides:
        return _overrides["db"]
    from content.simulation.database.db import Database
    return Database()


def _get_rag():
    if "rag" in _overrides:
        return _overrides["rag"]
    try:
        from content.simulation.database.rag import RAGManager
        return RAGManager()
    except Exception as e:
        logger.debug("[_lazy] RAGManager unavailable (operation=get_rag): %s", e)
        return None


def _get_config():
    if "config" in _overrides:
        return _overrides["config"]
    from engine.config import get_config
    return get_config()
