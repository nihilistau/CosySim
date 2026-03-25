"""
Test LMStudio Infrastructure
=============================

Tests for priority enums, model sessions, model manager lifecycle,
inference router priority queue, tier selection, channel selection,
slots, fallback, and lifecycle.

Version: v1.52.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.52.0 [2026-03-25] — Migrated from unittest.TestCase to plain pytest (audit remediation)
"""
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.lmstudio.router import Priority, Tier, Channel
from engine.lmstudio.model_manager import (
    ModelManager, ModelSession, LoadMode, get_model_manager,
)
from engine.lmstudio.router import (
    InferenceRouter, InferenceRequest, TierConfig, RouterMetrics,
)


# ── Helpers ───────────────────────────────────────────────────────


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


def _make_model_manager(mode="concurrent", **config_overrides):
    """Build a ModelManager with sensible defaults for testing.

    Used by ensure_loaded, release, set_mode, eviction, and shutdown tests.
    Returns (manager, cli_mock) when cli interactions need verification,
    or just the manager when they don't.
    """
    defaults = {
        "lmstudio.load_mode": mode,
        "lmstudio.jit_ttl_seconds": 300,
        "lmstudio.default_load_opts.gpu": 0.9,
        "lmstudio.default_load_opts.context_length": 4096,
        "lmstudio.concurrent_model": "test-8b",
        "lmstudio.concurrent_slots": 4,
        "lmstudio.vram_cap_mb": 11500,
        "hardware.gpu_name": "TestGPU",
        "hardware.gpu_vram_mb": 12000,
        "hardware.ram_gb": 32,
        "lmstudio.mcp_enabled": True,
        "lmstudio.api_version": "v1",
    }
    defaults.update(config_overrides)
    cfg = MagicMock()
    cfg.get = lambda key, default=None: defaults.get(key, default)
    cli = MagicMock()
    cli.load_model = MagicMock(return_value=True)
    cli.unload_model = MagicMock()
    cli.list_loaded_models = MagicMock(return_value=[])
    mgr = ModelManager(config=cfg, cli_manager=cli)
    return mgr, cli


def _make_router(**kwargs):
    """Build an InferenceRouter with optional overrides."""
    return InferenceRouter(**kwargs)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def _patch_routerv3():
    """Disable RouterV3 so tests exercise rule-based tier selection."""
    patcher = patch(
        "engine.lmstudio.router_v3_client.get_router_v3_client",
        side_effect=RuntimeError("RouterV3 disabled in tests"),
    )
    patcher.start()
    yield
    patcher.stop()


# ── Router enum tests ───────────────────────────────────────────────


def test_priority_ordering():
    assert Priority.REALTIME < Priority.INTERACTIVE
    assert Priority.INTERACTIVE < Priority.BACKGROUND
    assert Priority.BACKGROUND < Priority.BATCH


def test_priority_values():
    assert Priority.REALTIME == 0
    assert Priority.INTERACTIVE == 1
    assert Priority.BACKGROUND == 2
    assert Priority.BATCH == 3


def test_tier_values():
    assert Tier.GPU_PRIMARY.value == "gpu_primary"
    assert Tier.CPU_UTILITY.value == "cpu_utility"
    assert Tier.CPU_ROUTER.value == "cpu_router"


def test_channel_values():
    assert Channel.SDK.value == "sdk"
    assert Channel.REST.value == "rest"


# ── ModelSession tests ──────────────────────────────────────────────


def test_session_defaults():
    session = ModelSession(model_key="test-model")
    assert session.model_key == "test-model"
    assert session.request_count == 0
    assert session.gpu_fraction == 0.9
    assert session.context_length == 4096
    assert session.ttl_seconds == 300
    assert session.loaded_at > 0


def test_session_touch():
    session = ModelSession(model_key="test-model")
    old_used = session.last_used_at
    time.sleep(0.05)
    session.touch()
    assert session.last_used_at > old_used
    assert session.request_count == 1


def test_session_idle():
    session = ModelSession(model_key="test-model")
    time.sleep(0.1)
    assert session.idle_seconds > 0


# ── LoadMode tests ──────────────────────────────────────────────────


def test_load_mode_values():
    assert LoadMode.CONCURRENT.value == "concurrent"
    assert LoadMode.JIT.value == "jit"
    assert LoadMode.JIT_TTL.value == "jit_ttl"


def test_load_mode_from_string():
    assert LoadMode("concurrent") == LoadMode.CONCURRENT
    assert LoadMode("jit") == LoadMode.JIT
    assert LoadMode("jit_ttl") == LoadMode.JIT_TTL


# ── ModelManager tests ──────────────────────────────────────────────


@patch("engine.lmstudio.model_manager._instance", None)
@patch("engine.lmstudio.model_manager.ModelManager.__init__", return_value=None)
def test_model_manager_singleton(mock_init):
    import engine.lmstudio.model_manager as mm
    mm._instance = None
    mgr1 = get_model_manager()
    mgr2 = get_model_manager()
    assert mgr1 is mgr2


def test_model_manager_set_mode():
    mgr, _cli = _make_model_manager()
    assert mgr.mode == LoadMode.CONCURRENT
    mgr.set_mode(LoadMode.JIT)
    assert mgr.mode == LoadMode.JIT


def test_model_manager_model_not_loaded():
    mgr, _cli = _make_model_manager()
    assert "nonexistent" not in mgr._sessions
    assert mgr.list_sessions() == []


# ── ModelManager ensure_loaded tests ────────────────────────────────


# -- CONCURRENT mode --

def test_ensure_loaded_concurrent_returns_configured_model():
    mgr, cli = _make_model_manager(mode="concurrent")
    result = mgr.ensure_loaded("some-model")
    assert result == "test-8b"
    cli.load_model.assert_not_called()


def test_ensure_loaded_concurrent_already_tracked():
    mgr, cli = _make_model_manager(mode="concurrent")
    mgr.ensure_loaded("model-a")
    mgr.ensure_loaded("model-a")
    sessions = mgr.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].request_count == 2


# -- JIT mode --

def test_ensure_loaded_jit_loads_new_model():
    mgr, cli = _make_model_manager(mode="jit")
    result = mgr.ensure_loaded("model-a")
    assert result == "model-a"
    cli.load_model.assert_called_once()
    assert "model-a" in {s.model_key for s in mgr.list_sessions()}


def test_ensure_loaded_jit_already_loaded_skips_cli():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.ensure_loaded("model-a")
    cli.load_model.reset_mock()
    result = mgr.ensure_loaded("model-a")
    assert result == "model-a"
    cli.load_model.assert_not_called()


def test_ensure_loaded_jit_evicts_previous():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.ensure_loaded("model-a")
    cli.load_model.reset_mock()
    mgr.ensure_loaded("model-b")
    cli.unload_model.assert_called_with("model-a")
    cli.load_model.assert_called_once()
    sessions = mgr.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].model_key == "model-b"


def test_ensure_loaded_jit_records_session():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.ensure_loaded("model-a")
    session = mgr.list_sessions()[0]
    assert session.model_key == "model-a"
    assert session.request_count == 1


def test_ensure_loaded_jit_load_failure_still_tracks():
    mgr, cli = _make_model_manager(mode="jit")
    cli.load_model.return_value = False
    result = mgr.ensure_loaded("model-fail")
    assert result == "model-fail"
    assert len(mgr.list_sessions()) == 1


# -- JIT_TTL mode --

def test_ensure_loaded_jit_ttl_loads_new():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    result = mgr.ensure_loaded("model-a")
    assert result == "model-a"
    cli.load_model.assert_called_once()


def test_ensure_loaded_jit_ttl_already_loaded_touches():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    mgr.ensure_loaded("model-a")
    old_count = mgr.list_sessions()[0].request_count
    cli.load_model.reset_mock()
    mgr.ensure_loaded("model-a")
    cli.load_model.assert_not_called()
    assert mgr.list_sessions()[0].request_count == old_count + 1


def test_ensure_loaded_jit_ttl_multiple_coexist():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    mgr.ensure_loaded("model-a")
    mgr.ensure_loaded("model-b")
    keys = {s.model_key for s in mgr.list_sessions()}
    assert keys == {"model-a", "model-b"}


def test_ensure_loaded_jit_ttl_skips_load_if_lms_has_it():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    cli.list_loaded_models.return_value = [{"model_key": "model-a"}]
    mgr.ensure_loaded("model-a")
    cli.load_model.assert_not_called()


def test_ensure_loaded_passes_custom_params():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.ensure_loaded("model-a", gpu=0.5, context_length=8192, ttl_seconds=60)
    cli.load_model.assert_called_once_with(
        "model-a", gpu=0.5, context_length=8192, ttl=0, force=True,
    )


# ── ModelManager release tests ──────────────────────────────────────


def test_release_jit_unloads():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.ensure_loaded("model-a")
    mgr.release("model-a")
    cli.unload_model.assert_called_with("model-a")
    assert mgr.list_sessions() == []


def test_release_jit_ttl_unloads():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    mgr.ensure_loaded("model-a")
    mgr.release("model-a")
    cli.unload_model.assert_called_with("model-a")
    assert mgr.list_sessions() == []


def test_release_concurrent_is_noop():
    mgr, cli = _make_model_manager(mode="concurrent")
    mgr.ensure_loaded("model-a")
    mgr.release("model-a")
    cli.unload_model.assert_not_called()
    assert len(mgr.list_sessions()) == 1


def test_release_nonexistent_model_no_error():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.release("never-loaded")
    cli.unload_model.assert_called_with("never-loaded")


# ── ModelManager set_mode tests ─────────────────────────────────────


def test_switch_concurrent_to_jit():
    mgr, _cli = _make_model_manager(mode="concurrent")
    mgr.set_mode(LoadMode.JIT)
    assert mgr.mode == LoadMode.JIT


def test_switch_jit_to_jit_ttl():
    mgr, _cli = _make_model_manager(mode="jit")
    mgr.set_mode(LoadMode.JIT_TTL, ttl_seconds=120)
    assert mgr.mode == LoadMode.JIT_TTL
    assert mgr._default_ttl == 120


def test_switch_jit_ttl_to_concurrent():
    mgr, _cli = _make_model_manager(mode="jit_ttl")
    mgr.set_mode(LoadMode.CONCURRENT, concurrent_model="big-model")
    assert mgr.mode == LoadMode.CONCURRENT
    assert mgr._concurrent_model == "big-model"


def test_set_mode_preserves_ttl_when_not_overridden():
    mgr, _cli = _make_model_manager(mode="concurrent")
    mgr.set_mode(LoadMode.JIT)
    assert mgr._default_ttl == 300


def test_set_mode_starts_reaper_for_jit_ttl():
    mgr, _cli = _make_model_manager(mode="concurrent")
    mgr.set_mode(LoadMode.JIT_TTL)
    assert mgr._reaper_thread is not None
    assert mgr._reaper_thread.is_alive()
    mgr._stop_reaper.set()


def test_set_mode_stops_reaper_leaving_jit_ttl():
    mgr, _cli = _make_model_manager(mode="jit_ttl")
    assert mgr._reaper_thread.is_alive()
    mgr.set_mode(LoadMode.JIT)
    assert mgr._stop_reaper.is_set()


# ── ModelManager eviction tests ─────────────────────────────────────


def test_jit_evicts_all_others_on_new_load():
    mgr, cli = _make_model_manager(mode="jit")
    # Manually insert two sessions to simulate state
    mgr._sessions["old-1"] = ModelSession(model_key="old-1")
    mgr._sessions["old-2"] = ModelSession(model_key="old-2")
    mgr.ensure_loaded("new-model")
    assert "old-1" not in {s.model_key for s in mgr.list_sessions()}
    assert "old-2" not in {s.model_key for s in mgr.list_sessions()}
    assert "new-model" in {s.model_key for s in mgr.list_sessions()}


def test_jit_no_eviction_when_same_model():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.ensure_loaded("model-a")
    cli.unload_model.reset_mock()
    mgr.ensure_loaded("model-a")
    cli.unload_model.assert_not_called()


def test_reap_expired_removes_idle_sessions():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    # Insert a session with very short TTL, already expired
    expired_session = ModelSession(model_key="old-model", ttl_seconds=0)
    # ttl_seconds=0 means never expire, so use a tiny TTL
    expired_session.ttl_seconds = 1
    expired_session.last_used_at = time.monotonic() - 10  # idle 10s > 1s TTL
    mgr._sessions["old-model"] = expired_session
    mgr._reap_expired()
    assert "old-model" not in {s.model_key for s in mgr.list_sessions()}
    cli.unload_model.assert_called_with("old-model")


def test_reap_expired_keeps_fresh_sessions():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    fresh = ModelSession(model_key="fresh", ttl_seconds=300)
    mgr._sessions["fresh"] = fresh
    mgr._reap_expired()
    assert "fresh" in {s.model_key for s in mgr.list_sessions()}
    cli.unload_model.assert_not_called()


def test_reap_expired_zero_ttl_never_expires():
    mgr, cli = _make_model_manager(mode="jit_ttl")
    permanent = ModelSession(model_key="perm", ttl_seconds=0)
    permanent.last_used_at = time.monotonic() - 9999
    mgr._sessions["perm"] = permanent
    mgr._reap_expired()
    assert "perm" in {s.model_key for s in mgr.list_sessions()}


# ── ModelManager shutdown tests ─────────────────────────────────────


def test_shutdown_clears_sessions():
    mgr, cli = _make_model_manager(mode="jit")
    mgr.ensure_loaded("model-a")
    mgr.shutdown()
    assert mgr.list_sessions() == []
    cli.unload_model.assert_called()


# ── InferenceRouter priority queue tests ─────────────────────────────


def test_queue_ordering_by_priority():
    router = _make_router(max_queue_depth=50)
    f_batch = router.submit(InferenceRequest(priority=Priority.BATCH))
    f_rt = router.submit(InferenceRequest(priority=Priority.REALTIME))
    f_bg = router.submit(InferenceRequest(priority=Priority.BACKGROUND))
    f_inter = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
    # Queue should order: REALTIME, INTERACTIVE, BACKGROUND, BATCH
    entries = sorted(router._queue)
    priorities = [e[0] for e in entries]
    assert priorities == [0, 1, 2, 3]


def test_same_priority_fifo():
    router = _make_router(max_queue_depth=50)
    f1 = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
    f2 = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
    f3 = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
    sequences = [e[1] for e in sorted(router._queue)]
    assert sequences == sorted(sequences)


def test_submit_increments_metrics():
    router = _make_router(max_queue_depth=50)
    router.submit(InferenceRequest(priority=Priority.REALTIME))
    router.submit(InferenceRequest(priority=Priority.BATCH))
    assert router._metrics.total_submitted == 2
    assert router._metrics.queue_depth == 2


def test_submit_queue_full_returns_failed_future():
    router = InferenceRouter(max_queue_depth=2)
    router.submit(InferenceRequest(priority=Priority.BATCH))
    router.submit(InferenceRequest(priority=Priority.BATCH))
    f = router.submit(InferenceRequest(priority=Priority.BATCH))
    with pytest.raises(RuntimeError):
        f.result(timeout=0.1)


# ── InferenceRouter tier selection tests ─────────────────────────────


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_explicit_tier_used():
    router = _make_router()
    req = InferenceRequest(tier=Tier.CPU_UTILITY)
    assert router.select_tier(req) == Tier.CPU_UTILITY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_classify_routes_to_cpu_router():
    router = _make_router()
    req = InferenceRequest(task_type="classify")
    assert router.select_tier(req) == Tier.CPU_ROUTER


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_route_task_routes_to_cpu_router():
    router = _make_router()
    req = InferenceRequest(task_type="route")
    assert router.select_tier(req) == Tier.CPU_ROUTER


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_tag_extract_routes_to_cpu_router():
    router = _make_router()
    req = InferenceRequest(task_type="tag_extract")
    assert router.select_tier(req) == Tier.CPU_ROUTER


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_act_routes_to_gpu():
    router = _make_router()
    req = InferenceRequest(task_type="act")
    assert router.select_tier(req) == Tier.GPU_PRIMARY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_tools_present_routes_to_gpu():
    router = _make_router()
    req = InferenceRequest(task_type="chat", tools=[{"name": "tool1"}])
    assert router.select_tier(req) == Tier.GPU_PRIMARY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_background_no_tools_routes_to_cpu_utility():
    router = _make_router()
    req = InferenceRequest(priority=Priority.BACKGROUND, task_type="chat")
    assert router.select_tier(req) == Tier.CPU_UTILITY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_batch_no_tools_routes_to_cpu_utility():
    router = _make_router()
    req = InferenceRequest(priority=Priority.BATCH, task_type="chat")
    assert router.select_tier(req) == Tier.CPU_UTILITY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_interactive_chat_routes_to_gpu():
    router = _make_router()
    req = InferenceRequest(priority=Priority.INTERACTIVE, task_type="chat")
    assert router.select_tier(req) == Tier.GPU_PRIMARY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_realtime_routes_to_gpu():
    router = _make_router()
    req = InferenceRequest(priority=Priority.REALTIME, task_type="chat")
    assert router.select_tier(req) == Tier.GPU_PRIMARY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_disabled_cpu_router_falls_through():
    tiers = {
        Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY, max_slots=2),
        Tier.CPU_UTILITY: TierConfig(tier=Tier.CPU_UTILITY, max_slots=1),
        Tier.CPU_ROUTER: TierConfig(tier=Tier.CPU_ROUTER, enabled=False),
    }
    router = InferenceRouter(tiers=tiers)
    req = InferenceRequest(task_type="classify")
    # CPU_ROUTER disabled → tools absent, not background → GPU_PRIMARY
    assert router.select_tier(req) == Tier.GPU_PRIMARY


@pytest.mark.usefixtures("_patch_routerv3")
def test_tier_agent_affinity_used_when_slot_available():
    router = _make_router()
    router.bind_agent("agent-1", Tier.CPU_UTILITY)
    # CPU_UTILITY default has max_slots=1, busy=0 → available
    req = InferenceRequest(agent_id="agent-1", task_type="chat",
                           priority=Priority.INTERACTIVE)
    assert router.select_tier(req) == Tier.CPU_UTILITY


# ── InferenceRouter channel selection tests ──────────────────────────


def test_channel_explicit_channel_used():
    router = _make_router()
    req = InferenceRequest(channel=Channel.REST)
    assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.REST


def test_channel_act_uses_sdk():
    router = _make_router()
    req = InferenceRequest(task_type="act", tools=[{"name": "t"}])
    assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.SDK


def test_channel_tools_present_uses_sdk():
    router = _make_router()
    req = InferenceRequest(tools=[{"name": "t"}])
    assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.SDK


def test_channel_tier_default_channel():
    tiers = {
        Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY, channel=Channel.REST),
    }
    router = InferenceRouter(tiers=tiers)
    req = InferenceRequest(task_type="chat")
    assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.REST


# ── InferenceRouter slot tests ───────────────────────────────────────


def test_has_available_slot_true():
    router = InferenceRouter()
    assert router.has_available_slot(Tier.GPU_PRIMARY)


def test_has_available_slot_false_when_full():
    router = InferenceRouter()
    tc = router._tiers[Tier.GPU_PRIMARY]
    tc._busy_slots = tc.max_slots
    assert not router.has_available_slot(Tier.GPU_PRIMARY)


def test_has_available_slot_false_when_disabled():
    tiers = {
        Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY, enabled=False),
    }
    router = InferenceRouter(tiers=tiers)
    assert not router.has_available_slot(Tier.GPU_PRIMARY)


def test_has_available_slot_missing_tier():
    # Empty dict is falsy, so pass explicit tier with only GPU
    tiers = {Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY)}
    router = InferenceRouter(tiers=tiers)
    assert not router.has_available_slot(Tier.CPU_ROUTER)


# ── InferenceRouter fallback tests ───────────────────────────────────


def test_gpu_full_falls_to_cpu_utility():
    router = InferenceRouter()
    req = InferenceRequest(task_type="chat")
    fallback = router._find_fallback_tier(Tier.GPU_PRIMARY, req)
    assert fallback == Tier.CPU_UTILITY


def test_gpu_full_no_fallback_with_tools():
    router = InferenceRouter()
    req = InferenceRequest(tools=[{"name": "t"}])
    fallback = router._find_fallback_tier(Tier.GPU_PRIMARY, req)
    assert fallback is None


def test_cpu_utility_falls_to_gpu():
    router = InferenceRouter()
    req = InferenceRequest(task_type="chat")
    fallback = router._find_fallback_tier(Tier.CPU_UTILITY, req)
    assert fallback == Tier.GPU_PRIMARY


def test_cpu_router_no_fallback():
    router = InferenceRouter()
    req = InferenceRequest(task_type="classify")
    fallback = router._find_fallback_tier(Tier.CPU_ROUTER, req)
    assert fallback is None


# ── InferenceRouter lifecycle tests ──────────────────────────────────


def test_router_start_stop():
    router = InferenceRouter()
    router.start()
    assert router._running
    router.stop()
    assert not router._running


def test_router_stop_cancels_pending():
    router = InferenceRouter()
    f1 = router.submit(InferenceRequest(priority=Priority.BATCH))
    f2 = router.submit(InferenceRequest(priority=Priority.BATCH))
    router.stop()
    assert len(router._queue) == 0


def test_router_bind_unbind_agent():
    router = InferenceRouter()
    router.bind_agent("agent-1", Tier.GPU_PRIMARY)
    assert router.get_agent_bindings() == {"agent-1": "gpu_primary"}
    router.unbind_agent("agent-1")
    assert router.get_agent_bindings() == {}


def test_router_get_metrics_structure():
    router = InferenceRouter()
    m = router.get_metrics()
    assert "total_submitted" in m
    assert "queue_depth" in m
    assert "slots" in m
    assert "tier_counts" in m
