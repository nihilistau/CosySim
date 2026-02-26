"""Tests for engine.lmstudio.model_manager — ModelManager lifecycle controller."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.lmstudio.model_manager import (
    LoadMode,
    ModelManager,
    ModelSession,
)


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """Mock config that mimics ConfigManager.get()."""
    defaults = {
        "lmstudio.load_mode": "concurrent",
        "lmstudio.jit_ttl_seconds": 300,
        "lmstudio.default_load_opts.gpu": 0.9,
        "lmstudio.default_load_opts.context_length": 4096,
        "lmstudio.concurrent_model": "qwen/qwen3-32b",
        "lmstudio.concurrent_slots": 4,
        "lmstudio.vram_cap_mb": 11500,
        "lmstudio.mcp_enabled": True,
        "lmstudio.api_version": "v1",
        "hardware.gpu_name": "RTX 3080",
        "hardware.gpu_vram_mb": 12000,
        "hardware.ram_gb": 32,
    }
    cfg = MagicMock()
    cfg.get = lambda key, default=None: defaults.get(key, default)
    return cfg


@pytest.fixture
def mock_cli():
    """Mock LMStudioManager (CLI manager) for load/unload/list."""
    cli = MagicMock()
    cli.load_model.return_value = True
    cli.unload_model.return_value = True
    cli.list_loaded_models.return_value = []
    return cli


@pytest.fixture
def manager(mock_config, mock_cli):
    """Create a ModelManager with mocked dependencies, CONCURRENT mode."""
    mgr = ModelManager(config=mock_config, cli_manager=mock_cli)
    yield mgr
    mgr._stop_reaper.set()  # ensure reaper is stopped


@pytest.fixture
def jit_config(mock_config):
    """Config that sets load_mode to JIT."""
    base = {
        "lmstudio.load_mode": "jit",
        "lmstudio.jit_ttl_seconds": 300,
        "lmstudio.default_load_opts.gpu": 0.9,
        "lmstudio.default_load_opts.context_length": 4096,
        "lmstudio.concurrent_model": "",
        "lmstudio.concurrent_slots": 4,
        "lmstudio.vram_cap_mb": 11500,
        "lmstudio.mcp_enabled": True,
        "lmstudio.api_version": "v1",
        "hardware.gpu_name": "RTX 3080",
        "hardware.gpu_vram_mb": 12000,
        "hardware.ram_gb": 32,
    }
    cfg = MagicMock()
    cfg.get = lambda key, default=None: base.get(key, default)
    return cfg


@pytest.fixture
def jit_manager(jit_config, mock_cli):
    """ModelManager in JIT mode."""
    mgr = ModelManager(config=jit_config, cli_manager=mock_cli)
    yield mgr
    mgr._stop_reaper.set()


@pytest.fixture
def ttl_config():
    """Config that sets load_mode to JIT_TTL with short TTL for tests."""
    base = {
        "lmstudio.load_mode": "jit_ttl",
        "lmstudio.jit_ttl_seconds": 2,
        "lmstudio.default_load_opts.gpu": 0.8,
        "lmstudio.default_load_opts.context_length": 8192,
        "lmstudio.concurrent_model": "",
        "lmstudio.concurrent_slots": 4,
        "lmstudio.vram_cap_mb": 11500,
        "lmstudio.mcp_enabled": True,
        "lmstudio.api_version": "v1",
        "hardware.gpu_name": "RTX 3080",
        "hardware.gpu_vram_mb": 12000,
        "hardware.ram_gb": 32,
    }
    cfg = MagicMock()
    cfg.get = lambda key, default=None: base.get(key, default)
    return cfg


@pytest.fixture
def ttl_manager(ttl_config, mock_cli):
    """ModelManager in JIT_TTL mode (reaper auto-starts)."""
    mgr = ModelManager(config=ttl_config, cli_manager=mock_cli)
    yield mgr
    mgr._stop_reaper.set()
    if mgr._reaper_thread and mgr._reaper_thread.is_alive():
        mgr._reaper_thread.join(timeout=2)


# ── LoadMode Enum ──────────────────────────────────────────────────────

class TestLoadMode:
    """Tests for the LoadMode enum."""

    def test_concurrent_value(self):
        assert LoadMode.CONCURRENT.value == "concurrent"

    def test_jit_value(self):
        assert LoadMode.JIT.value == "jit"

    def test_jit_ttl_value(self):
        assert LoadMode.JIT_TTL.value == "jit_ttl"

    def test_construct_from_string(self):
        assert LoadMode("concurrent") is LoadMode.CONCURRENT
        assert LoadMode("jit") is LoadMode.JIT
        assert LoadMode("jit_ttl") is LoadMode.JIT_TTL

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            LoadMode("invalid_mode")


# ── ModelSession Dataclass ─────────────────────────────────────────────

class TestModelSession:
    """Tests for the ModelSession tracking dataclass."""

    def test_defaults(self):
        s = ModelSession(model_key="test/model")
        assert s.model_key == "test/model"
        assert s.request_count == 0
        assert s.gpu_fraction == 0.9
        assert s.context_length == 4096
        assert s.ttl_seconds == 300

    def test_touch_increments_request_count(self):
        s = ModelSession(model_key="test/model")
        assert s.request_count == 0
        s.touch()
        assert s.request_count == 1
        s.touch()
        assert s.request_count == 2

    def test_touch_updates_last_used_at(self):
        s = ModelSession(model_key="test/model")
        old_ts = s.last_used_at
        time.sleep(0.05)
        s.touch()
        assert s.last_used_at > old_ts

    def test_idle_seconds_increases(self):
        s = ModelSession(model_key="test/model")
        s.last_used_at = time.monotonic() - 10.0
        assert s.idle_seconds >= 10.0

    def test_is_expired_false_when_ttl_zero(self):
        """TTL=0 means never expire."""
        s = ModelSession(model_key="test/model", ttl_seconds=0)
        s.last_used_at = time.monotonic() - 9999
        assert s.is_expired is False

    def test_is_expired_false_when_within_ttl(self):
        s = ModelSession(model_key="test/model", ttl_seconds=300)
        s.last_used_at = time.monotonic()
        assert s.is_expired is False

    def test_is_expired_true_when_past_ttl(self):
        s = ModelSession(model_key="test/model", ttl_seconds=5)
        s.last_used_at = time.monotonic() - 10.0
        assert s.is_expired is True

    def test_repr(self):
        s = ModelSession(model_key="test/model")
        r = repr(s)
        assert "test/model" in r
        assert "reqs=" in r
        assert "idle=" in r


# ── ModelManager Initialization ────────────────────────────────────────

class TestModelManagerInit:
    """Tests for ModelManager construction and configuration."""

    def test_init_with_explicit_deps(self, mock_config, mock_cli):
        mgr = ModelManager(config=mock_config, cli_manager=mock_cli)
        assert mgr.config is mock_config
        assert mgr._cli is mock_cli
        mgr._stop_reaper.set()

    def test_init_reads_mode_from_config(self, manager):
        assert manager.mode == LoadMode.CONCURRENT

    def test_init_reads_jit_mode(self, jit_manager):
        assert jit_manager.mode == LoadMode.JIT

    def test_init_reads_ttl_defaults(self, manager):
        assert manager._default_ttl == 300
        assert manager._default_gpu == 0.9
        assert manager._default_ctx == 4096

    def test_init_reads_concurrent_model(self, manager):
        assert manager._concurrent_model == "qwen/qwen3-32b"

    def test_init_sessions_empty(self, manager):
        assert manager._sessions == {}

    def test_init_no_reaper_in_concurrent_mode(self, manager):
        """Reaper thread should NOT start in CONCURRENT mode."""
        assert manager._reaper_thread is None

    def test_init_no_reaper_in_jit_mode(self, jit_manager):
        """Reaper thread should NOT start in JIT mode."""
        assert jit_manager._reaper_thread is None

    def test_init_starts_reaper_in_ttl_mode(self, ttl_manager):
        """JIT_TTL mode auto-starts the background reaper."""
        assert ttl_manager._reaper_thread is not None
        assert ttl_manager._reaper_thread.is_alive()

    @patch("engine.lmstudio.client.get_lmstudio_manager")
    @patch("engine.config.get_config")
    def test_init_fallback_to_singletons(self, mock_get_cfg, mock_get_mgr):
        """When no deps passed, init falls back to singletons."""
        mock_get_cfg.return_value = MagicMock(
            get=lambda k, d=None: {
                "lmstudio.load_mode": "concurrent",
            }.get(k, d)
        )
        mock_get_mgr.return_value = MagicMock()
        mgr = ModelManager()
        mock_get_cfg.assert_called_once()
        mock_get_mgr.assert_called_once()
        mgr._stop_reaper.set()


# ── set_mode ───────────────────────────────────────────────────────────

class TestSetMode:
    """Tests for switching load mode at runtime."""

    def test_switch_to_jit(self, manager):
        manager.set_mode(LoadMode.JIT)
        assert manager.mode == LoadMode.JIT

    def test_switch_to_jit_ttl_starts_reaper(self, manager):
        manager.set_mode(LoadMode.JIT_TTL)
        assert manager.mode == LoadMode.JIT_TTL
        assert manager._reaper_thread is not None
        manager._stop_reaper.set()

    def test_switch_from_ttl_to_concurrent_stops_reaper(self, ttl_manager):
        ttl_manager.set_mode(LoadMode.CONCURRENT)
        assert ttl_manager._stop_reaper.is_set()

    def test_override_ttl_seconds(self, manager):
        manager.set_mode(LoadMode.JIT_TTL, ttl_seconds=60)
        assert manager._default_ttl == 60
        manager._stop_reaper.set()

    def test_override_concurrent_model(self, manager):
        manager.set_mode(LoadMode.CONCURRENT, concurrent_model="llama/3-70b")
        assert manager._concurrent_model == "llama/3-70b"


# ── ensure_loaded (CONCURRENT mode) ───────────────────────────────────

class TestEnsureLoadedConcurrent:
    """Tests for ensure_loaded() in CONCURRENT mode."""

    def test_returns_concurrent_model(self, manager):
        """Should return the configured concurrent_model."""
        result = manager.ensure_loaded("any/model")
        assert result == "qwen/qwen3-32b"

    def test_registers_session_on_first_call(self, manager):
        manager.ensure_loaded("any/model")
        sessions = manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].model_key == "qwen/qwen3-32b"

    def test_touch_on_repeated_calls(self, manager):
        manager.ensure_loaded("any/model")
        manager.ensure_loaded("any/model")
        manager.ensure_loaded("any/model")
        sessions = manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].request_count == 3

    def test_no_cli_load_called(self, manager, mock_cli):
        """CONCURRENT mode should NOT call CLI load."""
        manager.ensure_loaded("any/model")
        mock_cli.load_model.assert_not_called()

    def test_concurrent_session_never_expires(self, manager):
        manager.ensure_loaded("any/model")
        session = manager.list_sessions()[0]
        assert session.ttl_seconds == 0
        assert session.is_expired is False

    def test_falls_back_to_model_key_if_no_concurrent_model(self, mock_cli):
        """When concurrent_model is empty, use the requested model_key."""
        cfg = MagicMock()
        cfg.get = lambda k, d=None: {
            "lmstudio.load_mode": "concurrent",
            "lmstudio.concurrent_model": "",
        }.get(k, d)
        mgr = ModelManager(config=cfg, cli_manager=mock_cli)
        result = mgr.ensure_loaded("fallback/model")
        assert result == "fallback/model"
        mgr._stop_reaper.set()


# ── ensure_loaded (JIT mode) ──────────────────────────────────────────

class TestEnsureLoadedJIT:
    """Tests for ensure_loaded() in JIT (just-in-time) mode."""

    def test_loads_model_via_cli(self, jit_manager, mock_cli):
        jit_manager.ensure_loaded("model-a")
        mock_cli.load_model.assert_called_once_with(
            "model-a", gpu=0.9, context_length=4096, ttl=0, force=True
        )

    def test_returns_model_key(self, jit_manager):
        result = jit_manager.ensure_loaded("model-a")
        assert result == "model-a"

    def test_creates_session(self, jit_manager):
        jit_manager.ensure_loaded("model-a")
        sessions = jit_manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].model_key == "model-a"

    def test_evicts_previous_model(self, jit_manager, mock_cli):
        """Loading a new model should unload the old one first."""
        jit_manager.ensure_loaded("model-a")
        jit_manager.ensure_loaded("model-b")

        mock_cli.unload_model.assert_called_once_with("model-a")
        sessions = jit_manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].model_key == "model-b"

    def test_no_eviction_if_same_model(self, jit_manager, mock_cli):
        """Re-loading the same model should NOT evict it."""
        jit_manager.ensure_loaded("model-a")
        jit_manager.ensure_loaded("model-a")

        mock_cli.unload_model.assert_not_called()
        assert mock_cli.load_model.call_count == 1

    def test_touch_on_re_ensure(self, jit_manager):
        jit_manager.ensure_loaded("model-a")
        jit_manager.ensure_loaded("model-a")
        session = jit_manager.list_sessions()[0]
        assert session.request_count == 2

    def test_custom_gpu_and_context(self, jit_manager, mock_cli):
        jit_manager.ensure_loaded("model-a", gpu=0.5, context_length=16384)
        mock_cli.load_model.assert_called_once_with(
            "model-a", gpu=0.5, context_length=16384, ttl=0, force=True
        )

    def test_load_failure_still_creates_session(self, jit_manager, mock_cli):
        """Even if CLI load fails, JIT creates a session (best-effort)."""
        mock_cli.load_model.return_value = False
        result = jit_manager.ensure_loaded("model-a")
        assert result == "model-a"
        assert len(jit_manager.list_sessions()) == 1

    def test_load_exception_creates_fallback_session(self, jit_manager, mock_cli):
        """If CLI load raises an exception, _cli_load catches it and returns False."""
        mock_cli.load_model.side_effect = ConnectionError("LMStudio unreachable")
        result = jit_manager.ensure_loaded("model-a")
        assert result == "model-a"
        assert len(jit_manager.list_sessions()) == 1


# ── ensure_loaded (JIT_TTL mode) ──────────────────────────────────────

class TestEnsureLoadedJITTTL:
    """Tests for ensure_loaded() in JIT_TTL mode."""

    def test_loads_model_if_not_present(self, ttl_manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        mock_cli.load_model.assert_called_once()

    def test_skips_cli_load_if_already_loaded(self, ttl_manager, mock_cli):
        """If model is already loaded in LMStudio, skip CLI load."""
        mock_cli.list_loaded_models.return_value = [
            {"model_key": "model-a", "id": "model-a"}
        ]
        ttl_manager.ensure_loaded("model-a")
        mock_cli.load_model.assert_not_called()

    def test_refreshes_session_on_re_ensure(self, ttl_manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        ttl_manager.ensure_loaded("model-a")

        sessions = ttl_manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].request_count == 2
        # CLI load should be called only once
        mock_cli.load_model.assert_called_once()

    def test_multiple_models_coexist(self, ttl_manager, mock_cli):
        """JIT_TTL allows multiple models loaded simultaneously."""
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        ttl_manager.ensure_loaded("model-b")

        sessions = ttl_manager.list_sessions()
        keys = {s.model_key for s in sessions}
        assert keys == {"model-a", "model-b"}

    def test_custom_ttl_per_model(self, ttl_manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a", ttl_seconds=600)
        session = ttl_manager.list_sessions()[0]
        assert session.ttl_seconds == 600

    def test_uses_default_ttl_from_config(self, ttl_manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        session = ttl_manager.list_sessions()[0]
        assert session.ttl_seconds == 2  # from ttl_config


# ── release ────────────────────────────────────────────────────────────

class TestRelease:
    """Tests for manually releasing (unloading) a model."""

    def test_release_noop_in_concurrent_mode(self, manager, mock_cli):
        """CONCURRENT mode ignores release calls."""
        manager.ensure_loaded("qwen/qwen3-32b")
        manager.release("qwen/qwen3-32b")
        mock_cli.unload_model.assert_not_called()
        # Session should still be there
        assert len(manager.list_sessions()) == 1

    def test_release_removes_session_in_jit(self, jit_manager, mock_cli):
        jit_manager.ensure_loaded("model-a")
        jit_manager.release("model-a")
        assert len(jit_manager.list_sessions()) == 0
        mock_cli.unload_model.assert_called_once_with("model-a")

    def test_release_removes_session_in_ttl(self, ttl_manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        ttl_manager.release("model-a")
        assert len(ttl_manager.list_sessions()) == 0

    def test_release_nonexistent_model_no_error(self, jit_manager, mock_cli):
        """Releasing a model that isn't tracked should not raise."""
        jit_manager.release("nonexistent/model")
        mock_cli.unload_model.assert_called_once_with("nonexistent/model")


# ── list_sessions ──────────────────────────────────────────────────────

class TestListSessions:
    """Tests for listing active model sessions."""

    def test_empty_initially(self, manager):
        assert manager.list_sessions() == []

    def test_returns_snapshot(self, manager):
        """list_sessions returns a copy, not the internal dict values view."""
        manager.ensure_loaded("model-a")
        sessions = manager.list_sessions()
        assert isinstance(sessions, list)
        assert len(sessions) == 1

    def test_multiple_sessions_in_ttl(self, ttl_manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        ttl_manager.ensure_loaded("model-b")
        ttl_manager.ensure_loaded("model-c")
        assert len(ttl_manager.list_sessions()) == 3


# ── status ─────────────────────────────────────────────────────────────

class TestStatus:
    """Tests for the admin status dict."""

    def test_status_contains_required_keys(self, manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        s = manager.status()
        assert "mode" in s
        assert "default_ttl" in s
        assert "concurrent_model" in s
        assert "tracked_sessions" in s
        assert "lmstudio_loaded" in s

    def test_status_mode_value(self, manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        s = manager.status()
        assert s["mode"] == "concurrent"

    def test_status_includes_tracked_sessions(self, manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        manager.ensure_loaded("model-a")
        s = manager.status()
        assert len(s["tracked_sessions"]) == 1
        session_info = s["tracked_sessions"][0]
        assert session_info["model_key"] == "qwen/qwen3-32b"
        assert "idle_seconds" in session_info
        assert "request_count" in session_info
        assert "expired" in session_info

    def test_status_includes_lmstudio_loaded(self, manager, mock_cli):
        mock_cli.list_loaded_models.return_value = [
            {"id": "qwen/qwen3-32b", "type": "llm"}
        ]
        s = manager.status()
        assert len(s["lmstudio_loaded"]) == 1


# ── get_full_config ────────────────────────────────────────────────────

class TestGetFullConfig:
    """Tests for the admin config dict."""

    def test_contains_all_expected_keys(self, manager):
        cfg = manager.get_full_config()
        expected_keys = {
            "mode", "default_ttl", "default_gpu",
            "default_context_length", "concurrent_model",
            "concurrent_slots", "vram_cap_mb", "hardware",
            "mcp_enabled", "api_version", "sessions",
        }
        assert expected_keys.issubset(cfg.keys())

    def test_hardware_section(self, manager):
        cfg = manager.get_full_config()
        hw = cfg["hardware"]
        assert hw["gpu_name"] == "RTX 3080"
        assert hw["gpu_vram_mb"] == 12000
        assert hw["ram_gb"] == 32

    def test_reflects_runtime_changes(self, manager):
        manager.set_mode(LoadMode.JIT, ttl_seconds=120)
        cfg = manager.get_full_config()
        assert cfg["mode"] == "jit"
        assert cfg["default_ttl"] == 120


# ── update_config ──────────────────────────────────────────────────────

class TestUpdateConfig:
    """Tests for runtime config updates."""

    def test_update_mode(self, manager):
        result = manager.update_config(mode="jit")
        assert manager.mode == LoadMode.JIT
        assert result["mode"] == "jit"

    def test_update_concurrent_model(self, manager):
        manager.update_config(concurrent_model="llama/3-70b")
        assert manager._concurrent_model == "llama/3-70b"

    def test_update_gpu(self, manager):
        manager.update_config(gpu=0.5)
        assert manager._default_gpu == 0.5

    def test_update_context_length(self, manager):
        manager.update_config(context_length=32768)
        assert manager._default_ctx == 32768

    def test_update_ttl_without_mode(self, manager):
        manager.update_config(ttl_seconds=60)
        assert manager._default_ttl == 60

    def test_update_mode_with_ttl(self, manager):
        manager.update_config(mode="jit_ttl", ttl_seconds=120)
        assert manager.mode == LoadMode.JIT_TTL
        assert manager._default_ttl == 120
        manager._stop_reaper.set()

    def test_update_returns_full_config(self, manager):
        result = manager.update_config(gpu=0.7)
        assert "mode" in result
        assert "hardware" in result
        assert "sessions" in result

    def test_update_invalid_mode_raises(self, manager):
        with pytest.raises(ValueError):
            manager.update_config(mode="banana")


# ── get_agent_config ───────────────────────────────────────────────────

class TestGetAgentConfig:
    """Tests for agent-role LLM config retrieval."""

    @patch("engine.mcp.framework.get_framework")
    def test_returns_profile_settings(self, mock_fw, manager):
        profile = MagicMock()
        profile.model = "qwen/qwen3-8b"
        profile.context_length = 8192
        profile.max_tokens = 4000
        profile.temperature = 0.5
        profile.top_p = 0.95
        mock_fw.return_value.get_agent_profile.return_value = profile

        cfg = manager.get_agent_config("big")
        assert cfg["role"] == "big"
        assert cfg["model"] == "qwen/qwen3-8b"
        assert cfg["context_length"] == 8192
        assert cfg["max_tokens"] == 4000
        assert cfg["temperature"] == 0.5
        assert cfg["load_mode"] == "concurrent"

    @patch("engine.mcp.framework.get_framework", side_effect=ImportError("no framework"))
    def test_falls_back_to_defaults_without_framework(self, mock_fw, manager):
        """If MCPFramework is unavailable, use fallback defaults."""
        cfg = manager.get_agent_config("big")
        assert cfg["role"] == "big"
        assert cfg["model"] == "qwen/qwen3-32b"
        assert cfg["context_length"] == 4096
        assert cfg["load_mode"] == "concurrent"


# ── ensure_for_agent ───────────────────────────────────────────────────

class TestEnsureForAgent:
    """Tests for agent-role based model loading."""

    @patch("engine.mcp.framework.get_framework")
    def test_loads_model_from_profile(self, mock_fw, manager):
        profile = MagicMock()
        profile.model = "qwen/qwen3-8b"
        profile.context_length = 8192
        mock_fw.return_value.get_agent_profile.return_value = profile

        result = manager.ensure_for_agent("small")
        # In CONCURRENT mode it returns the concurrent model or profile model
        assert result in ("qwen/qwen3-32b", "qwen/qwen3-8b")

    @patch("engine.mcp.framework.get_framework")
    def test_auto_detects_loaded_model_if_profile_empty(self, mock_fw, manager, mock_cli):
        """If profile has no model and no concurrent_model, use loaded model."""
        profile = MagicMock()
        profile.model = ""
        profile.context_length = 4096
        mock_fw.return_value.get_agent_profile.return_value = profile
        # Clear concurrent_model
        manager._concurrent_model = ""
        mock_cli.list_loaded_models.return_value = [
            {"model_key": "auto/detected", "id": "auto/detected"}
        ]
        result = manager.ensure_for_agent("small")
        assert result == "auto/detected"

    def test_returns_concurrent_model_on_framework_error(self, manager):
        """If framework import fails, returns concurrent_model."""
        result = manager.ensure_for_agent("big")
        assert result == "qwen/qwen3-32b"

    def test_returns_empty_if_no_fallback(self, mock_cli):
        """With no framework and no concurrent_model, returns empty."""
        cfg = MagicMock()
        cfg.get = lambda k, d=None: {
            "lmstudio.load_mode": "concurrent",
            "lmstudio.concurrent_model": "",
        }.get(k, d)
        mgr = ModelManager(config=cfg, cli_manager=mock_cli)
        result = mgr.ensure_for_agent("big")
        assert result == ""
        mgr._stop_reaper.set()


# ── CLI Helpers (load / unload) ────────────────────────────────────────

class TestCLIHelpers:
    """Tests for _cli_load and _cli_unload wrappers."""

    def test_cli_load_success(self, manager, mock_cli):
        result = manager._cli_load("model-a", gpu=0.9, ctx=4096, ttl=0)
        assert result is True
        mock_cli.load_model.assert_called_once()

    def test_cli_load_failure(self, manager, mock_cli):
        mock_cli.load_model.return_value = False
        result = manager._cli_load("model-a", gpu=0.9, ctx=4096, ttl=0)
        assert result is False

    def test_cli_load_exception_returns_false(self, manager, mock_cli):
        mock_cli.load_model.side_effect = RuntimeError("VRAM full")
        result = manager._cli_load("model-a", gpu=0.9, ctx=4096, ttl=0)
        assert result is False

    @patch("engine.services.activity_bus.get_activity_bus")
    def test_cli_load_publishes_event(self, mock_bus, manager, mock_cli):
        manager._cli_load("model-a", gpu=0.9, ctx=4096, ttl=0)
        mock_bus.return_value.publish.assert_called_once()
        call_kwargs = mock_bus.return_value.publish.call_args
        assert call_kwargs[1]["activity_type"] == "model_loaded"

    def test_cli_unload_calls_cli(self, manager, mock_cli):
        manager._cli_unload("model-a")
        mock_cli.unload_model.assert_called_once_with("model-a")

    def test_cli_unload_exception_does_not_raise(self, manager, mock_cli):
        """Unload failures are logged but not propagated."""
        mock_cli.unload_model.side_effect = ConnectionError("dead")
        manager._cli_unload("model-a")  # should not raise

    @patch("engine.services.activity_bus.get_activity_bus")
    def test_cli_unload_publishes_event(self, mock_bus, manager, mock_cli):
        manager._cli_unload("model-a")
        mock_bus.return_value.publish.assert_called_once()
        call_kwargs = mock_bus.return_value.publish.call_args
        assert call_kwargs[1]["activity_type"] == "model_unloaded"


# ── TTL Reaper ─────────────────────────────────────────────────────────

class TestReaper:
    """Tests for the JIT_TTL background reaper thread."""

    def test_reaper_thread_is_daemon(self, ttl_manager):
        assert ttl_manager._reaper_thread.daemon is True
        assert ttl_manager._reaper_thread.name == "ModelReaper"

    def test_reap_expired_removes_stale_sessions(self, ttl_manager, mock_cli):
        """Directly invoke _reap_expired to check it removes expired entries."""
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        # Manually backdate the session so it's expired
        ttl_manager._sessions["model-a"].last_used_at = time.monotonic() - 100
        ttl_manager._sessions["model-a"].ttl_seconds = 1

        ttl_manager._reap_expired()

        assert "model-a" not in ttl_manager._sessions
        mock_cli.unload_model.assert_called_with("model-a")

    def test_reap_keeps_fresh_sessions(self, ttl_manager, mock_cli):
        """_reap_expired should not touch sessions that haven't expired."""
        mock_cli.list_loaded_models.return_value = []
        ttl_manager.ensure_loaded("model-a")
        # session just created, well within TTL

        ttl_manager._reap_expired()

        assert "model-a" in ttl_manager._sessions
        mock_cli.unload_model.assert_not_called()

    def test_start_reaper_idempotent(self, ttl_manager):
        """Calling _start_reaper again should not create a second thread."""
        t1 = ttl_manager._reaper_thread
        ttl_manager._start_reaper()
        t2 = ttl_manager._reaper_thread
        assert t1 is t2


# ── shutdown ───────────────────────────────────────────────────────────

class TestShutdown:
    """Tests for graceful shutdown."""

    def test_shutdown_stops_reaper(self, ttl_manager):
        ttl_manager.shutdown()
        assert ttl_manager._stop_reaper.is_set()

    def test_shutdown_clears_sessions(self, jit_manager, mock_cli):
        jit_manager.ensure_loaded("model-a")
        assert len(jit_manager.list_sessions()) == 1
        jit_manager.shutdown()
        assert len(jit_manager.list_sessions()) == 0

    def test_shutdown_unloads_jit_models(self, jit_manager, mock_cli):
        jit_manager.ensure_loaded("model-a")
        jit_manager.shutdown()
        mock_cli.unload_model.assert_called_with("model-a")

    def test_shutdown_does_not_unload_concurrent_models(self, manager, mock_cli):
        """CONCURRENT models are operator-managed; shutdown should not unload."""
        manager.ensure_loaded("model-a")
        manager.shutdown()
        mock_cli.unload_model.assert_not_called()


# ── Singleton ──────────────────────────────────────────────────────────

class TestSingleton:
    """Tests for the get_model_manager singleton."""

    def test_singleton_returns_same_instance(self):
        import engine.lmstudio.model_manager as mod
        old = mod._instance
        try:
            mod._instance = None
            with patch.object(mod, "ModelManager") as MockCls:
                MockCls.return_value = MagicMock()
                m1 = mod.get_model_manager()
                m2 = mod.get_model_manager()
                assert m1 is m2
                MockCls.assert_called_once()
        finally:
            mod._instance = old


# ── Thread Safety ──────────────────────────────────────────────────────

class TestThreadSafety:
    """Verify concurrent access doesn't corrupt state."""

    def test_concurrent_ensure_loaded(self, jit_manager, mock_cli):
        """Multiple threads calling ensure_loaded should not crash."""
        errors = []

        def worker(model: str) -> None:
            try:
                jit_manager.ensure_loaded(model)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(f"model-{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Thread errors: {errors}"
        # After all settle, at least one session should exist
        assert len(jit_manager.list_sessions()) >= 1


# ── Edge Cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge-case and boundary tests."""

    def test_ensure_loaded_with_empty_model_key(self, jit_manager, mock_cli):
        """Empty string model_key is passed through without crash."""
        result = jit_manager.ensure_loaded("")
        assert result == ""

    def test_jit_sequential_eviction_chain(self, jit_manager, mock_cli):
        """Loading A → B → C in JIT should leave only C loaded."""
        jit_manager.ensure_loaded("a")
        jit_manager.ensure_loaded("b")
        jit_manager.ensure_loaded("c")

        sessions = jit_manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].model_key == "c"
        # a and b should have been unloaded
        assert mock_cli.unload_model.call_count == 2

    def test_ttl_model_detected_by_id_field(self, ttl_manager, mock_cli):
        """list_loaded_models may return 'id' instead of 'model_key'."""
        mock_cli.list_loaded_models.return_value = [
            {"id": "model-x"}  # no 'model_key', only 'id'
        ]
        ttl_manager.ensure_loaded("model-x")
        # Should detect it's already loaded and skip CLI load
        mock_cli.load_model.assert_not_called()

    def test_release_then_re_ensure(self, jit_manager, mock_cli):
        """After release, ensure_loaded should reload the model."""
        jit_manager.ensure_loaded("model-a")
        jit_manager.release("model-a")
        jit_manager.ensure_loaded("model-a")
        assert mock_cli.load_model.call_count == 2

    def test_status_with_no_sessions(self, manager, mock_cli):
        mock_cli.list_loaded_models.return_value = []
        s = manager.status()
        assert s["tracked_sessions"] == []

    def test_activity_bus_import_failure_tolerated(self, manager, mock_cli):
        """If activity bus is unavailable, _cli_load still succeeds."""
        with patch(
            "engine.services.activity_bus.get_activity_bus",
            side_effect=ImportError("no bus"),
        ):
            result = manager._cli_load("model-a", gpu=0.9, ctx=4096, ttl=0)
            assert result is True
