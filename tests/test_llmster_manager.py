"""Tests for engine.lmstudio.llmster_manager — LlmsterManager CLI wrapper."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from engine.lmstudio.llmster_manager import (
    LlmsterManager,
    LlmsterStatus,
    ModelLoadResult,
)


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """Mock config for llmster manager."""
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: {
        "lmstudio.llmster.lms_path": "",
        "lmstudio.llmster.default_n_parallel": 4,
        "lmstudio.llmster.unified_kv_cache": True,
    }.get(key, default)
    return cfg


@pytest.fixture
def manager(mock_config):
    """Create a LlmsterManager with mocked config."""
    with patch("engine.lmstudio.llmster_manager.get_config", return_value=mock_config):
        mgr = LlmsterManager(lms_path="/usr/bin/lms")
    return mgr


# ── Data Model Tests ───────────────────────────────────────────────────

class TestLlmsterStatus:
    def test_defaults(self):
        s = LlmsterStatus()
        assert s.daemon_running is False
        assert s.server_running is False
        assert s.loaded_models == []

    def test_to_dict(self):
        s = LlmsterStatus(daemon_running=True, server_port=1234)
        d = s.to_dict()
        assert d["daemon_running"] is True
        assert d["server_port"] == 1234


class TestModelLoadResult:
    def test_defaults(self):
        r = ModelLoadResult()
        assert r.success is False
        assert r.model_id == ""

    def test_to_dict(self):
        r = ModelLoadResult(success=True, model_id="test/model", n_parallel=4)
        d = r.to_dict()
        assert d["success"] is True
        assert d["n_parallel"] == 4


# ── Daemon Control Tests ──────────────────────────────────────────────

class TestDaemonControl:
    def test_daemon_status_success(self, manager):
        with patch.object(manager, "_run") as mock_run:
            # status command
            status_result = MagicMock()
            status_result.returncode = 0
            status_result.stdout = "Server running on port 1234"
            status_result.stderr = ""

            # version command
            version_result = MagicMock()
            version_result.returncode = 0
            version_result.stdout = "lms ac18535"

            mock_run.side_effect = [status_result, version_result]

            with patch.object(manager, "list_loaded", return_value=[]):
                status = manager.daemon_status()

            assert status.daemon_running is True
            assert status.server_port == 1234
            assert "ac18535" in status.cli_version

    def test_daemon_status_not_running(self, manager):
        with patch.object(manager, "_run") as mock_run:
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "Not running"
            mock_run.return_value = result

            with patch.object(manager, "list_loaded", return_value=[]):
                status = manager.daemon_status()

            assert status.daemon_running is False

    def test_daemon_status_binary_missing(self, manager):
        with patch.object(manager, "_run", side_effect=FileNotFoundError("lms")):
            status = manager.daemon_status()
            assert status.error != ""
            assert "not found" in status.error.lower()

    def test_daemon_up(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            assert manager.daemon_up() is True
            mock_run.assert_called_once_with(["daemon", "up"], timeout=30)

    def test_daemon_up_failure(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="already running")
            assert manager.daemon_up() is False

    def test_daemon_down(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            assert manager.daemon_down() is True


# ── Server Control Tests ──────────────────────────────────────────────

class TestServerControl:
    def test_server_start(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.server_start(port=5678) is True
            mock_run.assert_called_once_with(
                ["server", "start", "--port", "5678"], timeout=15
            )

    def test_server_stop(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.server_stop() is True


# ── Model Operations Tests ────────────────────────────────────────────

class TestModelOperations:
    def test_load_model_success(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Model loaded. instance id: abc123\n",
                stderr="",
            )
            result = manager.load_model("qwen/qwen3-8b", n_parallel=4)
            assert result.success is True
            assert result.model_id == "qwen/qwen3-8b"
            assert result.n_parallel == 4

    def test_load_model_with_context(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Loaded", stderr=""
            )
            manager.load_model("test/model", context_length=8192, gpu_offload=0.9)
            args = mock_run.call_args[0][0]
            assert "--context-length" in args
            assert "8192" in args
            assert "--gpu-offload" in args
            assert "0.9" in args

    def test_load_model_failure(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="Model not found"
            )
            result = manager.load_model("bad/model")
            assert result.success is False
            assert "not found" in result.error.lower()

    def test_load_model_default_n_parallel(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Loaded", stderr=""
            )
            result = manager.load_model("test/model")
            assert result.n_parallel == 4  # default from config
            args = mock_run.call_args[0][0]
            assert "--n-parallel" in args
            assert "4" in args

    def test_unload_model(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.unload_model("test/model") is True

    def test_list_models(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="qwen/qwen3-8b\nllama/llama-3-8b\n",
            )
            models = manager.list_models()
            assert len(models) == 2
            assert models[0]["id"] == "qwen/qwen3-8b"

    def test_list_loaded(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="qwen/qwen3-8b llm\n",
            )
            loaded = manager.list_loaded()
            assert len(loaded) == 1
            assert loaded[0]["id"] == "qwen/qwen3-8b"
            assert loaded[0]["type"] == "llm"

    def test_download_model(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.download_model("test/model") is True

    def test_runtime_update(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.runtime_update("llama.cpp") is True


# ── Server Info Test ──────────────────────────────────────────────────

class TestServerInfo:
    def test_get_server_info(self, manager):
        with patch.object(manager, "daemon_status") as mock_status:
            mock_status.return_value = LlmsterStatus(
                daemon_running=True, server_port=1234
            )
            info = manager.get_server_info()
            assert info["daemon_running"] is True
            assert info["lms_path"] == "/usr/bin/lms"
            assert info["default_n_parallel"] == 4


# ── Singleton Test ────────────────────────────────────────────────────

class TestSingleton:
    def test_get_llmster_manager(self):
        import engine.lmstudio.llmster_manager as mod
        mod._manager = None
        with patch.object(mod, "LlmsterManager") as MockClass:
            MockClass.return_value = MagicMock()
            m1 = mod.get_llmster_manager()
            m2 = mod.get_llmster_manager()
            assert m1 is m2
            MockClass.assert_called_once()
        mod._manager = None


# ── CLI Error Handling Tests ──────────────────────────────────────────

class TestErrorHandling:
    def test_run_timeout(self, manager):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("lms", 30)):
            with pytest.raises(subprocess.TimeoutExpired):
                manager._run(["status"])

    def test_run_file_not_found(self, manager):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError):
                manager._run(["status"])

    def test_daemon_up_exception(self, manager):
        with patch.object(manager, "_run", side_effect=Exception("boom")):
            assert manager.daemon_up() is False

    def test_daemon_down_exception(self, manager):
        with patch.object(manager, "_run", side_effect=Exception("boom")):
            assert manager.daemon_down() is False

    def test_list_models_failure(self, manager):
        with patch.object(manager, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert manager.list_models() == []

    def test_unload_exception(self, manager):
        with patch.object(manager, "_run", side_effect=Exception("boom")):
            assert manager.unload_model("test") is False
