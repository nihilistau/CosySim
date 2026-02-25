"""Tests for LMStudio infrastructure — InferenceRouter enums & ModelManager.

All tests use mocks so no LMStudio server is needed.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.lmstudio.router import Priority, Tier, Channel
from engine.lmstudio.model_manager import (
    ModelManager, ModelSession, LoadMode, get_model_manager,
)


# ── Router enum tests ───────────────────────────────────────────────


class TestPriorityEnum(unittest.TestCase):
    """Priority ordering and raw values."""

    def test_priority_ordering(self):
        self.assertLess(Priority.REALTIME, Priority.INTERACTIVE)
        self.assertLess(Priority.INTERACTIVE, Priority.BACKGROUND)
        self.assertLess(Priority.BACKGROUND, Priority.BATCH)

    def test_priority_values(self):
        self.assertEqual(Priority.REALTIME, 0)
        self.assertEqual(Priority.INTERACTIVE, 1)
        self.assertEqual(Priority.BACKGROUND, 2)
        self.assertEqual(Priority.BATCH, 3)


class TestTierEnum(unittest.TestCase):
    """Tier and Channel string values."""

    def test_tier_values(self):
        self.assertEqual(Tier.GPU_PRIMARY.value, "gpu_primary")
        self.assertEqual(Tier.CPU_UTILITY.value, "cpu_utility")
        self.assertEqual(Tier.CPU_ROUTER.value, "cpu_router")

    def test_channel_values(self):
        self.assertEqual(Channel.SDK.value, "sdk")
        self.assertEqual(Channel.REST.value, "rest")


# ── ModelSession tests ──────────────────────────────────────────────


class TestModelSession(unittest.TestCase):
    """ModelSession dataclass behaviour."""

    def test_session_defaults(self):
        session = ModelSession(model_key="test-model")
        self.assertEqual(session.model_key, "test-model")
        self.assertEqual(session.request_count, 0)
        self.assertEqual(session.gpu_fraction, 0.9)
        self.assertEqual(session.context_length, 4096)
        self.assertEqual(session.ttl_seconds, 300)
        self.assertGreater(session.loaded_at, 0)

    def test_session_touch(self):
        session = ModelSession(model_key="test-model")
        old_used = session.last_used_at
        time.sleep(0.05)
        session.touch()
        self.assertGreater(session.last_used_at, old_used)
        self.assertEqual(session.request_count, 1)

    def test_session_idle(self):
        session = ModelSession(model_key="test-model")
        time.sleep(0.1)
        self.assertGreater(session.idle_seconds, 0)


# ── LoadMode tests ──────────────────────────────────────────────────


class TestLoadMode(unittest.TestCase):
    """LoadMode enum values and string construction."""

    def test_load_mode_values(self):
        self.assertEqual(LoadMode.CONCURRENT.value, "concurrent")
        self.assertEqual(LoadMode.JIT.value, "jit")
        self.assertEqual(LoadMode.JIT_TTL.value, "jit_ttl")

    def test_load_mode_from_string(self):
        self.assertEqual(LoadMode("concurrent"), LoadMode.CONCURRENT)
        self.assertEqual(LoadMode("jit"), LoadMode.JIT)
        self.assertEqual(LoadMode("jit_ttl"), LoadMode.JIT_TTL)


# ── ModelManager tests ──────────────────────────────────────────────


def _mock_config(**overrides):
    """Return a dict-like mock config with sensible defaults."""
    defaults = {
        "lmstudio.load_mode": "concurrent",
        "lmstudio.jit_ttl_seconds": 300,
        "lmstudio.default_load_opts.gpu": 0.9,
        "lmstudio.default_load_opts.context_length": 4096,
        "lmstudio.concurrent_model": "test-8b",
    }
    defaults.update(overrides)
    cfg = MagicMock()
    cfg.get = lambda key, default=None: defaults.get(key, default)
    return cfg


class TestModelManager(unittest.TestCase):
    """ModelManager singleton, mode switching, and session tracking."""

    def _make_manager(self, **config_overrides):
        cfg = _mock_config(**config_overrides)
        cli = MagicMock()
        return ModelManager(config=cfg, cli_manager=cli)

    @patch("engine.lmstudio.model_manager._instance", None)
    @patch("engine.lmstudio.model_manager.ModelManager.__init__", return_value=None)
    def test_singleton(self, mock_init):
        import engine.lmstudio.model_manager as mm
        mm._instance = None
        mgr1 = get_model_manager()
        mgr2 = get_model_manager()
        self.assertIs(mgr1, mgr2)

    def test_set_mode(self):
        mgr = self._make_manager()
        self.assertEqual(mgr.mode, LoadMode.CONCURRENT)
        mgr.set_mode(LoadMode.JIT)
        self.assertEqual(mgr.mode, LoadMode.JIT)

    def test_model_not_loaded(self):
        mgr = self._make_manager()
        self.assertNotIn("nonexistent", mgr._sessions)
        self.assertEqual(mgr.list_sessions(), [])


if __name__ == "__main__":
    unittest.main()
