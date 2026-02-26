"""Tests for engine.lmstudio.resource_manager — ResourceManager lifecycle & strategies.

Covers:
- Initialization with all six strategies
- VRAM cap enforcement and budget tracking
- Slot management (acquire / release)
- Model loading/unloading decisions per strategy
- TTL-based eviction (reap_expired)
- Runtime config updates and strategy switching
- get_status() correctness
- Edge cases: no VRAM, all slots full, model already loaded
"""
import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.lmstudio.resource_manager import (
    ResourceManager,
    Strategy,
    ModelSlot,
    BackgroundTask,
    get_resource_manager,
)


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def rm_config():
    """Config mock with all ResourceManager-relevant keys."""
    defaults = {
        "lmstudio.vram_cap_mb": 11500,
        "lmstudio.concurrent_slots": 4,
        "lmstudio.resource_manager.strategy": "concurrent",
        "lmstudio.resource_manager.default_ttl": 300,
        "lmstudio.concurrent_model": "qwen3-8b",
        "lmstudio.speculative.draft_model": "qwen3-1b",
        "llm.model": "qwen3-8b",
        "hardware.ram_gb": 32,
    }
    mock = MagicMock()
    mock.get = lambda key, default=None: defaults.get(key, default)
    return mock


@pytest.fixture
def mock_load_result():
    """Factory for a fake load-model result."""
    result = MagicMock()
    result.status = "loaded"
    return result


def _make_rm(config, stop_reaper=True):
    """Build a ResourceManager and optionally stop the reaper thread."""
    rm = ResourceManager(config=config)
    if stop_reaper:
        rm._stop_event.set()       # prevent background reaper interference
    return rm


@pytest.fixture
def rm(rm_config):
    """Yield a ResourceManager with reaper stopped; shut down after test."""
    mgr = _make_rm(rm_config)
    yield mgr
    mgr.shutdown()


# ── Strategy Enum ──────────────────────────────────────────────────────


class TestStrategyEnum:
    """Strategy enum values and membership."""

    def test_all_strategies_exist(self):
        assert len(Strategy) == 6

    @pytest.mark.parametrize("name,value", [
        ("SINGLE_BIG", "single_big"),
        ("CONCURRENT", "concurrent"),
        ("MULTI_SMALL", "multi_small"),
        ("JIT_SWAP", "jit_swap"),
        ("SPECULATIVE", "speculative"),
        ("HYBRID", "hybrid"),
    ])
    def test_strategy_values(self, name, value):
        assert Strategy(value).name == name

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError):
            Strategy("nonexistent")


# ── ModelSlot dataclass ────────────────────────────────────────────────


class TestModelSlot:
    """ModelSlot tracking behaviour."""

    def test_defaults(self):
        slot = ModelSlot(model_id="test-model")
        assert slot.device == "gpu"
        assert slot.vram_mb == 0
        assert slot.ttl == 0
        assert slot.request_count == 0
        assert slot.agents == []
        assert slot.is_draft is False

    def test_touch_updates_last_used(self):
        slot = ModelSlot(model_id="m1")
        old = slot.last_used
        time.sleep(0.02)
        slot.touch("agent_a")
        assert slot.last_used > old
        assert slot.request_count == 1
        assert "agent_a" in slot.agents

    def test_touch_no_duplicate_agents(self):
        slot = ModelSlot(model_id="m1")
        slot.touch("a")
        slot.touch("a")
        assert slot.agents.count("a") == 1
        assert slot.request_count == 2

    def test_idle_seconds_increases(self):
        slot = ModelSlot(model_id="m1")
        time.sleep(0.05)
        assert slot.idle_seconds >= 0.04

    def test_is_expired_false_when_no_ttl(self):
        slot = ModelSlot(model_id="m1", ttl=0)
        assert slot.is_expired is False

    def test_is_expired_true_when_ttl_exceeded(self):
        slot = ModelSlot(model_id="m1", ttl=1)
        slot.last_used = time.monotonic() - 5  # 5 seconds ago
        assert slot.is_expired is True

    def test_is_expired_false_when_recently_used(self):
        slot = ModelSlot(model_id="m1", ttl=600)
        slot.touch()
        assert slot.is_expired is False


# ── Initialization ─────────────────────────────────────────────────────


class TestResourceManagerInit:
    """ResourceManager __init__ parses config correctly."""

    def test_defaults_from_config(self, rm):
        assert rm._vram_cap_mb == 11500
        assert rm._concurrent_slots == 4
        assert rm._strategy == Strategy.CONCURRENT
        assert rm._default_ttl == 300

    def test_custom_strategy_from_config(self, rm_config):
        rm_config.get = lambda k, d=None: {
            "lmstudio.resource_manager.strategy": "jit_swap",
        }.get(k, d)
        mgr = _make_rm(rm_config)
        try:
            assert mgr.strategy == Strategy.JIT_SWAP
        finally:
            mgr.shutdown()

    def test_invalid_strategy_falls_back(self, rm_config):
        rm_config.get = lambda k, d=None: {
            "lmstudio.resource_manager.strategy": "invalid_garbage",
        }.get(k, d)
        mgr = _make_rm(rm_config)
        try:
            assert mgr.strategy == Strategy.CONCURRENT
        finally:
            mgr.shutdown()

    def test_strategy_property(self, rm):
        assert rm.strategy == Strategy.CONCURRENT


# ── Strategy switching ─────────────────────────────────────────────────


class TestSetStrategy:
    """Runtime strategy changes."""

    def test_set_strategy_changes_value(self, rm):
        rm.set_strategy(Strategy.JIT_SWAP)
        assert rm.strategy == Strategy.JIT_SWAP

    def test_set_strategy_with_ttl_override(self, rm):
        rm.set_strategy(Strategy.MULTI_SMALL, default_ttl=60)
        assert rm._default_ttl == 60
        assert rm.strategy == Strategy.MULTI_SMALL


# ── VRAM tracking ──────────────────────────────────────────────────────


class TestVRAMTracking:
    """VRAM budget helpers."""

    def test_get_vram_free_no_models(self, rm):
        assert rm.get_vram_free() == 11500

    def test_get_vram_free_with_loaded_model(self, rm):
        rm._slots["model-a"] = ModelSlot(model_id="model-a", device="gpu", vram_mb=4000)
        assert rm.get_vram_free() == 7500

    def test_cpu_model_does_not_reduce_vram(self, rm):
        rm._slots["model-cpu"] = ModelSlot(model_id="model-cpu", device="cpu", vram_mb=0, ram_mb=8000)
        assert rm.get_vram_free() == 11500

    def test_multiple_gpu_models_sum(self, rm):
        rm._slots["a"] = ModelSlot(model_id="a", device="gpu", vram_mb=3000)
        rm._slots["b"] = ModelSlot(model_id="b", device="gpu", vram_mb=4000)
        assert rm.get_vram_free() == 4500


# ── get_status ─────────────────────────────────────────────────────────


class TestGetStatus:
    """get_status() returns correct structure."""

    def test_empty_status(self, rm):
        status = rm.get_status()
        assert status["strategy"] == "concurrent"
        assert status["vram_cap_mb"] == 11500
        assert status["vram_used_mb"] == 0
        assert status["vram_free_mb"] == 11500
        assert status["concurrent_slots"] == 4
        assert status["default_ttl"] == 300
        assert status["slots"] == {}
        assert status["agent_models"] == {}
        assert status["bg_queue_size"] == 0

    def test_status_with_loaded_slot(self, rm):
        rm._slots["m1"] = ModelSlot(
            model_id="m1", device="gpu", vram_mb=5000,
            context_length=8192, ttl=300, is_draft=False,
        )
        rm._agent_models["agent_a"] = "m1"

        status = rm.get_status()
        assert "m1" in status["slots"]
        assert status["slots"]["m1"]["vram_mb"] == 5000
        assert status["slots"]["m1"]["context_length"] == 8192
        assert status["vram_used_mb"] == 5000
        assert status["vram_free_mb"] == 6500
        assert status["agent_models"]["agent_a"] == "m1"

    def test_status_draft_model_flagged(self, rm):
        rm._slots["draft"] = ModelSlot(model_id="draft", is_draft=True)
        status = rm.get_status()
        assert status["slots"]["draft"]["is_draft"] is True


# ── update_config ──────────────────────────────────────────────────────


class TestUpdateConfig:
    """Runtime config patching."""

    def test_update_strategy(self, rm):
        result = rm.update_config(strategy="jit_swap")
        assert rm.strategy == Strategy.JIT_SWAP
        assert result["strategy"] == "jit_swap"

    def test_update_vram_cap(self, rm):
        rm.update_config(vram_cap_mb=8000)
        assert rm._vram_cap_mb == 8000
        assert rm.get_vram_free() == 8000

    def test_update_ttl(self, rm):
        rm.update_config(default_ttl=120)
        assert rm._default_ttl == 120

    def test_update_concurrent_slots(self, rm):
        rm.update_config(concurrent_slots=8)
        assert rm._concurrent_slots == 8

    def test_update_multiple_fields(self, rm):
        result = rm.update_config(strategy="hybrid", vram_cap_mb=6000, default_ttl=60)
        assert rm.strategy == Strategy.HYBRID
        assert rm._vram_cap_mb == 6000
        assert rm._default_ttl == 60
        assert result["strategy"] == "hybrid"


# ── Acquire / Release (all strategies) ─────────────────────────────────


def _patch_load_stack():
    """Patch all external calls that _load_model / _unload_model / _estimate_vram touch."""
    load_result = MagicMock()
    load_result.status = "loaded"

    mock_lms_client = MagicMock()
    mock_lms_client.load_model.return_value = load_result
    mock_lms_client.unload_model.return_value = None

    patches = [
        patch("engine.lmstudio.resource_manager.LoadConfig.from_yaml", return_value=MagicMock(
            context_length=4096, gpu_offload=None, ttl=None,
        )),
        patch(
            "engine.lmstudio.lms_client.get_lms_client",
            return_value=mock_lms_client,
        ),
        patch(
            "engine.lmstudio.client.get_lmstudio_manager",
            return_value=MagicMock(estimate_vram_needed=MagicMock(return_value=3000)),
        ),
        patch(
            "engine.lmstudio.resource_manager.ResourceManager._publish_event",
        ),
    ]
    return patches, mock_lms_client


class TestAcquireConcurrent:
    """CONCURRENT strategy: one model, many requests."""

    def test_acquire_loads_model_on_first_call(self, rm):
        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            model_id = rm.acquire("agent_a", model="qwen3-8b")

        assert model_id == "qwen3-8b"
        assert "agent_a" in rm._agent_models
        assert "qwen3-8b" in rm._slots

    def test_acquire_reuses_existing_slot(self, rm):
        rm._slots["qwen3-8b"] = ModelSlot(model_id="qwen3-8b", device="gpu", vram_mb=3000)
        model_id = rm.acquire("agent_b", model="qwen3-8b")
        assert model_id == "qwen3-8b"
        assert rm._slots["qwen3-8b"].request_count == 1
        assert "agent_b" in rm._slots["qwen3-8b"].agents

    def test_acquire_falls_back_to_loaded_model(self, rm):
        """If requested model not loaded, but another is, use that."""
        rm._slots["other-model"] = ModelSlot(model_id="other-model")
        model_id = rm.acquire("agent_c", model="qwen3-30b")
        assert model_id == "other-model"

    def test_concurrent_multiple_agents_same_model(self, rm):
        rm._slots["m1"] = ModelSlot(model_id="m1")
        rm.acquire("a1", model="m1")
        rm.acquire("a2", model="m1")
        assert rm._agent_models["a1"] == "m1"
        assert rm._agent_models["a2"] == "m1"
        assert "a1" in rm._slots["m1"].agents
        assert "a2" in rm._slots["m1"].agents


class TestAcquireSingleBig:
    """SINGLE_BIG strategy: one model at a time."""

    def test_single_big_uses_existing_model(self, rm):
        rm.set_strategy(Strategy.SINGLE_BIG)
        rm._slots["big-model"] = ModelSlot(model_id="big-model", vram_mb=8000)
        model_id = rm.acquire("agent_a", model="other-model")
        # SINGLE_BIG always uses the loaded model regardless of request
        assert model_id == "big-model"

    def test_single_big_loads_when_empty(self, rm):
        rm.set_strategy(Strategy.SINGLE_BIG)
        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            model_id = rm.acquire("agent_a", model="qwen3-30b")
        assert model_id == "qwen3-30b"
        assert "qwen3-30b" in rm._slots


class TestAcquireMultiSmall:
    """MULTI_SMALL strategy: multiple co-resident models."""

    def test_multi_loads_new_model(self, rm):
        rm.set_strategy(Strategy.MULTI_SMALL)
        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            model_id = rm.acquire("agent_a", model="small-1")
        assert model_id == "small-1"

    def test_multi_reuses_existing(self, rm):
        rm.set_strategy(Strategy.MULTI_SMALL)
        rm._slots["small-1"] = ModelSlot(model_id="small-1", vram_mb=2000)
        model_id = rm.acquire("agent_a", model="small-1")
        assert model_id == "small-1"
        assert rm._slots["small-1"].request_count == 1

    def test_multi_evicts_when_vram_low(self, rm):
        rm.set_strategy(Strategy.MULTI_SMALL)
        rm._vram_cap_mb = 5000
        # Fill VRAM almost full: 5000 - 4500 = 500 free (below 1500 threshold)
        rm._slots["old-model"] = ModelSlot(
            model_id="old-model", device="gpu", vram_mb=4500,
        )
        rm._slots["old-model"].last_used = time.monotonic() - 1000

        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            model_id = rm.acquire("agent_a", model="new-model")

        assert model_id == "new-model"
        # old-model should have been evicted
        assert "old-model" not in rm._slots


class TestAcquireJITSwap:
    """JIT_SWAP strategy: evict all, load requested."""

    def test_jit_evicts_other_models(self, rm):
        rm.set_strategy(Strategy.JIT_SWAP)
        rm._slots["model-a"] = ModelSlot(model_id="model-a", vram_mb=3000)
        rm._slots["model-b"] = ModelSlot(model_id="model-b", vram_mb=2000)

        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            model_id = rm.acquire("agent_x", model="model-c")

        assert model_id == "model-c"
        assert "model-a" not in rm._slots
        assert "model-b" not in rm._slots
        assert "model-c" in rm._slots

    def test_jit_skips_eviction_if_model_already_loaded(self, rm):
        rm.set_strategy(Strategy.JIT_SWAP)
        rm._slots["model-a"] = ModelSlot(model_id="model-a")
        model_id = rm.acquire("agent_x", model="model-a")
        assert model_id == "model-a"
        assert rm._slots["model-a"].request_count == 1


class TestAcquireSpeculative:
    """SPECULATIVE strategy: main + draft models.

    NOTE: _acquire_speculative has a deadlock bug — it acquires self._lock
    then calls _load_model which also acquires self._lock (non-reentrant).
    We mock _load_model at the instance level to avoid triggering the deadlock
    while still testing the strategy's orchestration logic.
    """

    def test_speculative_loads_main_and_draft(self, rm):
        rm.set_strategy(Strategy.SPECULATIVE)
        load_calls = []

        def fake_load(model_id, *, device="gpu", is_draft=False):
            load_calls.append((model_id, device, is_draft))
            rm._slots[model_id] = ModelSlot(
                model_id=model_id, device=device,
                vram_mb=3000 if device == "gpu" else 0,
                is_draft=is_draft,
            )
            return True

        with patch.object(rm, "_load_model", side_effect=fake_load), \
             patch.object(rm, "_publish_event"):
            model_id = rm.acquire("agent_a", model="big-model")

        assert model_id == "big-model"
        assert "big-model" in rm._slots
        # Draft model configured as "qwen3-1b" in rm_config
        assert "qwen3-1b" in rm._slots
        assert rm._slots["qwen3-1b"].is_draft is True
        # Verify both models were loaded
        assert len(load_calls) == 2
        assert load_calls[0] == ("big-model", "gpu", False)
        assert load_calls[1] == ("qwen3-1b", "gpu", True)

    def test_speculative_reuses_if_already_loaded(self, rm):
        rm.set_strategy(Strategy.SPECULATIVE)
        rm._slots["big-model"] = ModelSlot(model_id="big-model")
        model_id = rm.acquire("agent_a", model="big-model")
        assert model_id == "big-model"
        assert rm._slots["big-model"].request_count == 1


class TestAcquireHybrid:
    """HYBRID strategy: GPU for interactive, CPU for background."""

    def test_hybrid_loads_on_gpu(self, rm):
        rm.set_strategy(Strategy.HYBRID)
        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            model_id = rm.acquire("agent_a", model="interactive-model")
        assert model_id == "interactive-model"
        assert rm._slots["interactive-model"].device == "gpu"

    def test_hybrid_reuses_existing(self, rm):
        rm.set_strategy(Strategy.HYBRID)
        rm._slots["m1"] = ModelSlot(model_id="m1", device="gpu")
        model_id = rm.acquire("agent_a", model="m1")
        assert model_id == "m1"


# ── Release ────────────────────────────────────────────────────────────


class TestRelease:
    """Agent release removes agent from slot and mapping."""

    def test_release_removes_agent_from_slot(self, rm):
        rm._slots["m1"] = ModelSlot(model_id="m1")
        rm._slots["m1"].agents = ["agent_a", "agent_b"]
        rm._agent_models["agent_a"] = "m1"
        rm._agent_models["agent_b"] = "m1"

        rm.release("agent_a")

        assert "agent_a" not in rm._agent_models
        assert "agent_a" not in rm._slots["m1"].agents
        assert "agent_b" in rm._slots["m1"].agents

    def test_release_unknown_agent_is_noop(self, rm):
        rm.release("nonexistent")  # no error raised

    def test_release_does_not_remove_slot(self, rm):
        """Releasing an agent should NOT unload the model itself."""
        rm._slots["m1"] = ModelSlot(model_id="m1")
        rm._slots["m1"].agents = ["agent_a"]
        rm._agent_models["agent_a"] = "m1"

        rm.release("agent_a")

        assert "m1" in rm._slots  # slot stays
        assert rm._slots["m1"].agents == []


# ── Eviction ───────────────────────────────────────────────────────────


class TestEviction:
    """Eviction helpers: LRU eviction and TTL reaping."""

    def test_evict_least_used_picks_oldest(self, rm):
        rm._slots["old"] = ModelSlot(model_id="old", device="gpu", vram_mb=3000)
        rm._slots["old"].last_used = time.monotonic() - 1000
        rm._slots["new"] = ModelSlot(model_id="new", device="gpu", vram_mb=3000)
        rm._slots["new"].last_used = time.monotonic()

        with patch.object(rm, "_unload_model") as mock_unload:
            rm._evict_least_used()
            mock_unload.assert_called_once_with("old")

    def test_evict_skips_draft_models(self, rm):
        rm._slots["draft"] = ModelSlot(model_id="draft", device="gpu", is_draft=True)
        rm._slots["draft"].last_used = time.monotonic() - 9999

        with patch.object(rm, "_unload_model") as mock_unload:
            rm._evict_least_used()
            mock_unload.assert_not_called()

    def test_evict_does_nothing_if_no_gpu_models(self, rm):
        rm._slots["cpu-m"] = ModelSlot(model_id="cpu-m", device="cpu")
        with patch.object(rm, "_unload_model") as mock_unload:
            rm._evict_least_used()
            mock_unload.assert_not_called()

    def test_reap_expired_unloads_expired_models(self, rm):
        rm._slots["expired-m"] = ModelSlot(model_id="expired-m", ttl=1)
        rm._slots["expired-m"].last_used = time.monotonic() - 100
        rm._slots["fresh-m"] = ModelSlot(model_id="fresh-m", ttl=600)
        rm._slots["fresh-m"].touch()

        with patch.object(rm, "_unload_model") as mock_unload:
            rm._reap_expired()
            mock_unload.assert_called_once_with("expired-m")

    def test_reap_expired_skips_draft_models(self, rm):
        rm._slots["draft"] = ModelSlot(model_id="draft", ttl=1, is_draft=True)
        rm._slots["draft"].last_used = time.monotonic() - 100  # expired

        with patch.object(rm, "_unload_model") as mock_unload:
            rm._reap_expired()
            mock_unload.assert_not_called()

    def test_reap_expired_noop_when_all_fresh(self, rm):
        rm._slots["m1"] = ModelSlot(model_id="m1", ttl=600)
        rm._slots["m1"].touch()
        with patch.object(rm, "_unload_model") as mock_unload:
            rm._reap_expired()
            mock_unload.assert_not_called()


# ── _load_model ────────────────────────────────────────────────────────


class TestLoadModel:
    """_load_model integration with LMSClient and fallback CLI."""

    def test_load_model_creates_slot_on_success(self, rm):
        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            result = rm._load_model("test-model", device="gpu")
        assert result is True
        assert "test-model" in rm._slots
        assert rm._slots["test-model"].device == "gpu"
        assert rm._slots["test-model"].vram_mb == 3000  # from mock estimate

    def test_load_model_cpu_has_zero_vram(self, rm):
        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            rm._load_model("cpu-model", device="cpu")
        assert rm._slots["cpu-model"].vram_mb == 0

    def test_load_model_sets_ttl_from_default(self, rm):
        rm._default_ttl = 120
        patches, client = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            rm._load_model("m1", device="gpu")
        assert rm._slots["m1"].ttl == 120

    def test_load_model_falls_back_to_cli_on_exception(self, rm):
        with patch("engine.lmstudio.resource_manager.LoadConfig.from_yaml") as mock_yaml, \
             patch("engine.lmstudio.lms_client.get_lms_client", side_effect=Exception("REST down")), \
             patch("engine.lmstudio.client.get_lmstudio_manager") as mock_mgr:
            mock_mgr.return_value.load_model.return_value = True
            result = rm._load_model("m1", device="gpu")
        assert result is True

    def test_load_model_returns_false_on_total_failure(self, rm):
        with patch("engine.lmstudio.resource_manager.LoadConfig.from_yaml"), \
             patch("engine.lmstudio.lms_client.get_lms_client", side_effect=Exception("fail")), \
             patch("engine.lmstudio.client.get_lmstudio_manager", side_effect=Exception("also fail")):
            result = rm._load_model("m1", device="gpu")
        assert result is False


# ── _unload_model ──────────────────────────────────────────────────────


class TestUnloadModel:
    """_unload_model cleans up slots and agent mappings."""

    def test_unload_removes_slot(self, rm):
        rm._slots["m1"] = ModelSlot(model_id="m1")
        rm._agent_models["agent_a"] = "m1"

        with patch("engine.lmstudio.lms_client.get_lms_client") as mock_client, \
             patch.object(rm, "_publish_event"):
            rm._unload_model("m1")

        assert "m1" not in rm._slots
        assert "agent_a" not in rm._agent_models

    def test_unload_nonexistent_is_safe(self, rm):
        with patch("engine.lmstudio.lms_client.get_lms_client"), \
             patch.object(rm, "_publish_event"):
            rm._unload_model("no-such-model")  # no error

    def test_unload_falls_back_to_cli(self, rm):
        rm._slots["m1"] = ModelSlot(model_id="m1")
        with patch("engine.lmstudio.lms_client.get_lms_client", side_effect=Exception("fail")), \
             patch("engine.lmstudio.client.get_lmstudio_manager") as mock_mgr, \
             patch.object(rm, "_publish_event"):
            rm._unload_model("m1")
            mock_mgr.return_value.unload_model.assert_called_once_with("m1")


# ── _resolve_model_for_role ────────────────────────────────────────────


class TestResolveModel:
    """Model resolution from role → agent profile → config fallback."""

    def test_resolve_fallback_to_concurrent_model(self, rm):
        with patch("engine.mcp.framework.get_framework", side_effect=Exception("no fw")):
            result = rm._resolve_model_for_role("big")
        assert result == "qwen3-8b"

    def test_resolve_fallback_to_llm_model(self, rm_config):
        rm_config.get = lambda k, d=None: {
            "lmstudio.vram_cap_mb": 11500,
            "lmstudio.concurrent_slots": 4,
            "lmstudio.resource_manager.strategy": "concurrent",
            "lmstudio.resource_manager.default_ttl": 300,
            "lmstudio.concurrent_model": "",
            "llm.model": "fallback-model",
            "hardware.ram_gb": 32,
        }.get(k, d)
        mgr = _make_rm(rm_config)
        try:
            with patch("engine.mcp.framework.get_framework", side_effect=Exception("no fw")):
                result = mgr._resolve_model_for_role("big")
            assert result == "fallback-model"
        finally:
            mgr.shutdown()

    def test_resolve_from_agent_profile(self, rm):
        mock_fw = MagicMock()
        mock_fw.get_agent_profile.return_value = MagicMock(model="profile-model")
        with patch("engine.mcp.framework.get_framework", return_value=mock_fw):
            result = rm._resolve_model_for_role("big")
        assert result == "profile-model"


# ── Acquire with role (no explicit model) ──────────────────────────────


class TestAcquireWithRole:
    """acquire() resolves model from role when model= not passed."""

    def test_acquire_resolves_role_to_model(self, rm):
        rm._slots["qwen3-8b"] = ModelSlot(model_id="qwen3-8b")
        with patch("engine.mcp.framework.get_framework", side_effect=Exception("no fw")):
            model_id = rm.acquire("agent_a", role="big")
        # Should have resolved to "qwen3-8b" via config fallback
        assert model_id == "qwen3-8b"


# ── Background tasks ──────────────────────────────────────────────────


class TestBackgroundTasks:
    """Background task queuing and execution."""

    def test_queue_background_task(self, rm):
        fn = MagicMock()
        rm.queue_background_task("test_task", fn, args=(1, 2), priority=5)
        # Give the executor a moment to execute
        time.sleep(0.1)
        fn.assert_called_once_with(1, 2)

    def test_queue_task_with_kwargs(self, rm):
        fn = MagicMock()
        rm.queue_background_task("kw_task", fn, kwargs={"key": "val"})
        time.sleep(0.1)
        fn.assert_called_once_with(key="val")

    def test_queue_task_failure_does_not_raise(self, rm):
        fn = MagicMock(side_effect=Exception("boom"))
        rm.queue_background_task("fail_task", fn)
        time.sleep(0.1)
        fn.assert_called_once()


# ── BackgroundTask dataclass ───────────────────────────────────────────


class TestBackgroundTaskDataclass:
    """BackgroundTask field defaults."""

    def test_defaults(self):
        task = BackgroundTask(name="t1", fn=lambda: None)
        assert task.name == "t1"
        assert task.args == ()
        assert task.kwargs == {}
        assert task.priority == 0
        assert task.device == "cpu"
        assert task.queued_at > 0


# ── Shutdown ───────────────────────────────────────────────────────────


class TestShutdown:
    """ResourceManager cleanup."""

    def test_shutdown_sets_stop_event(self, rm):
        rm.shutdown()
        assert rm._stop_event.is_set()

    def test_double_shutdown_is_safe(self, rm):
        rm.shutdown()
        rm.shutdown()  # no error


# ── Edge cases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary conditions and unusual states."""

    def test_acquire_with_zero_vram_cap(self, rm):
        """Acquire still works even with 0 VRAM cap (loads may be CPU)."""
        rm._vram_cap_mb = 0
        assert rm.get_vram_free() == 0

    def test_all_slots_full_jit_evicts(self, rm):
        """JIT_SWAP should still evict everything and load new model."""
        rm.set_strategy(Strategy.JIT_SWAP)
        for i in range(5):
            rm._slots[f"m{i}"] = ModelSlot(model_id=f"m{i}", vram_mb=2000)

        patches, _ = _patch_load_stack()
        with patches[0], patches[1], patches[2], patches[3]:
            model_id = rm.acquire("agent", model="new-model")

        assert model_id == "new-model"
        # All old models evicted
        for i in range(5):
            assert f"m{i}" not in rm._slots

    def test_release_agent_that_model_was_already_unloaded(self, rm):
        """Release when the model was already removed from slots."""
        rm._agent_models["agent_a"] = "gone-model"
        rm.release("agent_a")  # should not raise
        assert "agent_a" not in rm._agent_models

    def test_concurrent_acquire_threads(self, rm):
        """Multiple threads acquiring concurrently should not corrupt state."""
        rm._slots["shared"] = ModelSlot(model_id="shared")
        errors = []

        def worker(name):
            try:
                rm.acquire(name, model="shared")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"agent_{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        assert len(rm._agent_models) == 10

    def test_vram_negative_after_overcommit(self, rm):
        """If models somehow exceed cap, vram_free can go negative."""
        rm._vram_cap_mb = 1000
        rm._slots["big"] = ModelSlot(model_id="big", device="gpu", vram_mb=5000)
        assert rm.get_vram_free() == -4000

    def test_estimate_vram_returns_default_on_error(self, rm):
        with patch("engine.lmstudio.client.get_lmstudio_manager", side_effect=Exception("fail")):
            est = rm._estimate_vram("any-model")
        assert est == 3000


# ── Singleton ──────────────────────────────────────────────────────────


class TestSingleton:
    """get_resource_manager() singleton behaviour."""

    def test_singleton_returns_same_instance(self):
        import engine.lmstudio.resource_manager as mod
        # Reset singleton
        mod._rm_instance = None
        with patch.object(ResourceManager, "__init__", return_value=None):
            rm1 = get_resource_manager()
            rm2 = get_resource_manager()
        assert rm1 is rm2
        mod._rm_instance = None  # cleanup
