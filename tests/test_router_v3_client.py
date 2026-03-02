"""Tests for RouterV3Client — fine-tuned Qwen2.5-0.5B routing model client."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_tmpdir() -> str:
    """Create a temp dir outside tests/tmp to avoid conftest lock issues."""
    return tempfile.mkdtemp(prefix="rv3test_")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset RouterV3Client singleton between tests."""
    import engine.lmstudio.router_v3_client as mod
    old = mod._instance
    mod._instance = None
    yield
    mod._instance = old


@pytest.fixture()
def tmp_dir():
    """Temp directory that bypasses tests/tmp conftest path."""
    d = _make_tmpdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def registry_file(tmp_dir) -> Path:
    """Write a valid model_registry.json and return its path."""
    merged = Path(tmp_dir) / "merged"
    merged.mkdir()
    registry = Path(tmp_dir) / "model_registry.json"
    data = {
        "models": [
            {
                "model_id": "6115d0f2",
                "model_type": "router_v3",
                "active": True,
                "merged_path": str(merged),
                "adapter_path": None,
            }
        ]
    }
    registry.write_text(json.dumps(data), encoding="utf-8")
    return registry


# ── ModelRegistry lookup ──────────────────────────────────────────────────────

class TestFindActiveModel:
    def test_returns_none_when_registry_missing(self):
        from engine.lmstudio.router_v3_client import RouterV3Client
        with patch("engine.lmstudio.router_v3_client.Path") as mock_path:
            mock_path.return_value.__truediv__ = lambda s, o: MagicMock(exists=lambda: False)
            result = RouterV3Client._find_active_model()
        assert result is None

    def test_reads_active_merged_path(self, tmp_dir, registry_file):
        """Should find the merged path for the active router_v3 entry."""
        from engine.lmstudio.router_v3_client import RouterV3Client

        merged_path = str(Path(tmp_dir) / "merged")

        # Redirect the registry lookup to our temp file
        with patch("builtins.open", side_effect=lambda path, **_: (
            registry_file.open() if "model_registry" in str(path) else open(path)
        )):
            with patch.object(Path, "exists", return_value=True):
                result = RouterV3Client._find_active_model()
        assert result == merged_path

    def test_returns_none_when_no_active_entry(self, tmp_dir):
        """Should return None if no entry has active=True."""
        import engine.lmstudio.router_v3_client as mod
        registry = Path(tmp_dir) / "model_registry.json"
        registry.write_text(
            json.dumps({"models": [{"model_type": "router_v3", "active": False}]}),
            encoding="utf-8",
        )
        with patch("builtins.open", side_effect=lambda p, **_: open(registry)):
            with patch.object(Path, "exists", return_value=True):
                result = mod.RouterV3Client._find_active_model()
        assert result is None

    def test_handles_malformed_registry(self, tmp_dir):
        """Should return None and not raise on JSON parse error."""
        from engine.lmstudio.router_v3_client import RouterV3Client
        with patch("builtins.open", side_effect=ValueError("bad json")):
            with patch.object(Path, "exists", return_value=True):
                result = RouterV3Client._find_active_model()
        assert result is None


# ── RouterV3Client instantiation ──────────────────────────────────────────────

class TestRouterV3ClientInit:
    def test_not_loaded_on_init(self):
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client()
        assert not client._loaded
        assert not client._available

    def test_custom_model_path_stored(self, tmp_dir):
        from engine.lmstudio.router_v3_client import RouterV3Client
        path = str(tmp_dir)
        client = RouterV3Client(model_path=path)
        assert client._model_path == path

    def test_singleton_returns_same_instance(self):
        from engine.lmstudio.router_v3_client import get_router_v3_client
        a = get_router_v3_client()
        b = get_router_v3_client()
        assert a is b

    def test_singleton_is_router_v3_client(self):
        from engine.lmstudio.router_v3_client import RouterV3Client, get_router_v3_client
        assert isinstance(get_router_v3_client(), RouterV3Client)


# ── Rule-based fallback ───────────────────────────────────────────────────────

class TestRulePrediction:
    @pytest.mark.parametrize("task,priority,tools,expected", [
        ("classify", "interactive", False, "cpu_router"),
        ("route", "realtime", False, "cpu_router"),
        ("validate", "background", False, "cpu_router"),
        ("tag_extract", "batch", False, "cpu_router"),
        ("act", "interactive", False, "gpu_primary"),
        ("chat", "interactive", True, "gpu_primary"),
        ("chat", "background", False, "cpu_utility"),
        ("chat", "batch", False, "cpu_utility"),
        ("chat", "interactive", False, "gpu_primary"),
        ("complete", "realtime", False, "gpu_primary"),
    ])
    def test_rule_predict(self, task, priority, tools, expected):
        from engine.lmstudio.router_v3_client import RouterV3Client
        result = RouterV3Client._rule_predict(task, priority, has_tools=tools)
        assert result == expected


# ── Label parsing ─────────────────────────────────────────────────────────────

class TestLabelParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("gpu_primary", "gpu_primary"),
        ("cpu_utility", "cpu_utility"),
        ("cpu_router", "cpu_router"),
        ("GPU_PRIMARY", "gpu_primary"),
        ("t1", "gpu_primary"),
        ("t2", "cpu_utility"),
        ("t3", "cpu_router"),
        ("gpu", "gpu_primary"),
        ("primary", "gpu_primary"),
        ("utility", "cpu_utility"),
        ("router", "cpu_router"),
        ("gpu_primary.", "gpu_primary"),
        ("unknown_label", "gpu_primary"),
        ("", "gpu_primary"),
        ("  gpu_primary  extra words", "gpu_primary"),
    ])
    def test_parse_label(self, raw, expected):
        from engine.lmstudio.router_v3_client import RouterV3Client
        result = RouterV3Client(model_path=None)._parse_label(raw)
        assert result == expected


# ── predict_tier: fallback when no model ─────────────────────────────────────

class TestPredictTierNoModel:
    def test_falls_back_when_no_registry(self):
        """When no model found, predict_tier returns rule-based result."""
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = None
        client._loaded = False
        client._available = False
        client._lock = threading.Lock()
        client._predict_count = 0
        client._error_count = 0
        client._last_predict_ms = 0.0

        with patch.object(RouterV3Client, "_find_active_model", return_value=None):
            result = client.predict_tier("classify", "interactive")
        assert result == "cpu_router"

    def test_falls_back_on_transformers_import_error(self, tmp_dir):
        """If transformers not available, rule fallback is returned."""
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = str(tmp_dir)
        client._loaded = False
        client._available = False
        client._lock = threading.Lock()
        client._predict_count = 0
        client._error_count = 0
        client._last_predict_ms = 0.0

        with patch.dict("sys.modules", {"transformers": None}):
            result = client.predict_tier("classify", "interactive")
        # transformers is not available → rule fallback
        assert result in ("cpu_router", "gpu_primary", "cpu_utility")

    def test_predict_count_increments_on_ml_path(self, tmp_dir):
        """predict_count should increment when ML path is taken."""
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = str(tmp_dir)
        client._loaded = True
        client._available = True
        client._lock = threading.Lock()
        client._predict_count = 0
        client._error_count = 0
        client._last_predict_ms = 0.0

        mock_pipeline = MagicMock(
            return_value=[{"generated_text": "### Response:\ngpu_primary"}]
        )
        client._pipeline = mock_pipeline

        with patch(
            "engine.lmstudio.router_v3_client.RouterV3Client._ensure_loaded",
            return_value=True,
        ):
            result = client.predict_tier("chat", "interactive")

        assert client._predict_count == 1
        assert result == "gpu_primary"

    def test_error_count_increments_on_pipeline_exception(self, tmp_dir):
        """error_count should increment when pipeline raises."""
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = str(tmp_dir)
        client._loaded = True
        client._available = True
        client._lock = threading.Lock()
        client._predict_count = 0
        client._error_count = 0
        client._last_predict_ms = 0.0
        client._pipeline = MagicMock(side_effect=RuntimeError("GPU OOM"))

        with patch(
            "engine.lmstudio.router_v3_client.RouterV3Client._ensure_loaded",
            return_value=True,
        ):
            result = client.predict_tier("act", "realtime")

        assert client._error_count == 1
        assert result == "gpu_primary"  # rule fallback for act


# ── predict_tier: with mocked transformers pipeline ───────────────────────────

class TestPredictTierWithPipeline:
    @pytest.fixture()
    def client_with_mock_pipeline(self):
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = "/fake/model"
        client._loaded = True
        client._available = True
        client._lock = threading.Lock()
        client._predict_count = 0
        client._error_count = 0
        client._last_predict_ms = 0.0
        client._pipeline = MagicMock()
        return client

    def _set_output(self, client, label: str):
        prompt_marker = "### Response:\n"
        client._pipeline.return_value = [
            {"generated_text": f"placeholder{prompt_marker}{label}"}
        ]
        # Make the pipeline return text starting with the prompt so slicing works
        # Actually we need the full prompt + response — mock the call differently
        def fake_call(prompt, **kwargs):
            return [{"generated_text": prompt + label}]
        client._pipeline.side_effect = fake_call

    @pytest.mark.parametrize("label,expected_tier", [
        ("gpu_primary", "gpu_primary"),
        ("cpu_utility", "cpu_utility"),
        ("cpu_router", "cpu_router"),
        ("t1", "gpu_primary"),
        ("t2", "cpu_utility"),
    ])
    def test_returns_parsed_tier(self, client_with_mock_pipeline, label, expected_tier):
        client = client_with_mock_pipeline
        self._set_output(client, label)
        with patch(
            "engine.lmstudio.router_v3_client.RouterV3Client._ensure_loaded",
            return_value=True,
        ):
            result = client.predict_tier("chat", "interactive")
        assert result == expected_tier

    def test_last_predict_ms_set(self, client_with_mock_pipeline):
        client = client_with_mock_pipeline
        self._set_output(client, "gpu_primary")
        with patch(
            "engine.lmstudio.router_v3_client.RouterV3Client._ensure_loaded",
            return_value=True,
        ):
            client.predict_tier("chat", "realtime")
        assert client._last_predict_ms >= 0.0


# ── get_status ────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_status_dict_keys(self):
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = None
        client._loaded = False
        client._available = False
        client._load_error = None
        client._predict_count = 0
        client._error_count = 0
        client._last_predict_ms = 0.0

        with patch.object(RouterV3Client, "_find_active_model", return_value=None):
            status = client.get_status()

        assert set(status.keys()) == {
            "available", "loaded", "model_path", "load_error",
            "predict_count", "error_count", "last_predict_ms",
        }

    def test_status_reflects_loaded_state(self, tmp_dir):
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = str(tmp_dir)
        client._loaded = True
        client._available = True
        client._load_error = None
        client._predict_count = 42
        client._error_count = 1
        client._last_predict_ms = 12.5

        with patch.object(RouterV3Client, "_find_active_model", return_value=str(tmp_dir)):
            status = client.get_status()

        assert status["available"] is True
        assert status["predict_count"] == 42
        assert status["error_count"] == 1
        assert status["last_predict_ms"] == pytest.approx(12.5)


# ── Thread safety ─────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_singleton_thread_safe(self):
        """Multiple threads calling get_router_v3_client should get same instance."""
        from engine.lmstudio.router_v3_client import get_router_v3_client
        results = []

        def worker():
            results.append(get_router_v3_client())

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)

    def test_ensure_loaded_thread_safe(self, tmp_dir):
        """_ensure_loaded should only call _load_from once even with contention."""
        from engine.lmstudio.router_v3_client import RouterV3Client
        client = RouterV3Client.__new__(RouterV3Client)
        client._model_path = str(tmp_dir)
        client._loaded = False
        client._available = False
        client._lock = threading.Lock()
        client._predict_count = 0
        client._error_count = 0
        client._last_predict_ms = 0.0

        load_count = []

        def fake_load(path):
            load_count.append(1)
            client._loaded = True
            client._available = False  # simulating no transformers

        with patch.object(client, "_load_from", side_effect=fake_load):
            threads = [threading.Thread(target=client._ensure_loaded) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(load_count) == 1  # only loaded once

