"""Lazy service getters shared between cosysim_server.py and domain tool files.

Avoids import-time side effects by deferring instantiation until first call.
"""
from __future__ import annotations


def _get_db():
    from content.simulation.database.db import Database
    return Database()


def _get_rag():
    try:
        from content.simulation.database.rag import RAGManager
        return RAGManager()
    except Exception:
        return None


def _get_config():
    from engine.config import get_config
    return get_config()
