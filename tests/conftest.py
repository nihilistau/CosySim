"""
Shared pytest fixtures for CosySim tests.

Provides isolated database, config, and EventChain instances per test.
"""
import sys
import os
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_db_path(tmp_path):
    """Return a temporary SQLite database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def temp_db(temp_db_path):
    """Create a fresh Database instance pointing at a temp file."""
    from content.simulation.database.db import Database
    db = Database(temp_db_path)
    return db


@pytest.fixture
def event_chain(temp_db):
    """Create an EventChain backed by a temp database."""
    from content.simulation.database.events import EventChain
    return EventChain(db=temp_db)


@pytest.fixture
def mock_config():
    """Return a dict-based mock config that mimics get_config()."""
    defaults = {
        "lmstudio.base_url": "http://localhost:1234",
        "comfyui.base_url": "http://localhost:8188",
        "tts.engine": "placeholder",
        "database.path": ":memory:",
        "hardware.vram_cap_mb": 11500,
    }
    mock = MagicMock()
    mock.get = lambda key, default=None: defaults.get(key, default)
    return mock
