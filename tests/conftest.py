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


# Modules that tests may replace with fakes; restore originals after each test.
_PROTECTED_MODULES = [
    "flask",
    "flask_socketio",
    "engine.world.world_state",
    "engine.world.world_sim",
]


@pytest.fixture(autouse=True)
def _restore_protected_modules():
    """Restore sys.modules entries that test isolation bugs may have replaced."""
    saved = {k: sys.modules.get(k) for k in _PROTECTED_MODULES}
    yield
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


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


def _wipe_singletons() -> None:
    """Set all stateful module-level singletons back to None.

    SKILL_REGISTRY is intentionally excluded — @skill decorators fire only
    once at import time and the registry is safe to share across modules.
    """
    try:
        import engine.mcp.framework as _m
        _m._FW_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.character_registry as _m
        _m._REGISTRY_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.dialog_system as _m
        _m._DIALOG_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.scene_rules_engine as _m
        _m._ENGINE_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.scene_state as _m
        _m._SSM_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.world.world_state as _m
        _m._WORLD_STATE = None
    except Exception:
        pass
    try:
        import engine.world.world_sim as _m
        _m._WORLD_SIM = None
    except Exception:
        pass


@pytest.fixture(autouse=True, scope="module")
def _reset_singletons_per_module():
    """Wipe stateful singletons before and after each test module.

    This prevents cross-module contamination where module A creates real
    singleton objects that module B's mocked tests inadvertently pick up.
    Within a single test module, singletons persist normally.
    """
    _wipe_singletons()
    yield
    _wipe_singletons()


# ──── Optional-dependency skip markers ───────────────────────────────────────

def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:  # type: ignore[type-arg]
    """Auto-skip tests that require optional heavy deps (torch, etc.) when unavailable."""
    try:
        import torch  # noqa: F401
        _torch_ok = True
    except ImportError:
        _torch_ok = False

    if not _torch_ok:
        skip_torch = pytest.mark.skip(reason="torch not installed — skipping GPU/native-TTS tests")
        _torch_test_files = {"test_orpheus_native.py"}
        for item in items:
            if Path(item.fspath).name in _torch_test_files:
                item.add_marker(skip_torch)
