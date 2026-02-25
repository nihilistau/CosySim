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


# ── Extended ModelManager tests ─────────────────────────────────────


class TestModelManagerEnsureLoaded(unittest.TestCase):
    """ModelManager.ensure_loaded() across all three modes."""

    def _make_manager(self, mode="concurrent", **config_overrides):
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

    # -- CONCURRENT mode --

    def test_ensure_loaded_concurrent_returns_configured_model(self):
        mgr, cli = self._make_manager(mode="concurrent")
        result = mgr.ensure_loaded("some-model")
        self.assertEqual(result, "test-8b")
        cli.load_model.assert_not_called()

    def test_ensure_loaded_concurrent_already_tracked(self):
        mgr, cli = self._make_manager(mode="concurrent")
        mgr.ensure_loaded("model-a")
        mgr.ensure_loaded("model-a")
        sessions = mgr.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].request_count, 2)

    # -- JIT mode --

    def test_ensure_loaded_jit_loads_new_model(self):
        mgr, cli = self._make_manager(mode="jit")
        result = mgr.ensure_loaded("model-a")
        self.assertEqual(result, "model-a")
        cli.load_model.assert_called_once()
        self.assertIn("model-a", {s.model_key for s in mgr.list_sessions()})

    def test_ensure_loaded_jit_already_loaded_skips_cli(self):
        mgr, cli = self._make_manager(mode="jit")
        mgr.ensure_loaded("model-a")
        cli.load_model.reset_mock()
        result = mgr.ensure_loaded("model-a")
        self.assertEqual(result, "model-a")
        cli.load_model.assert_not_called()

    def test_ensure_loaded_jit_evicts_previous(self):
        mgr, cli = self._make_manager(mode="jit")
        mgr.ensure_loaded("model-a")
        cli.load_model.reset_mock()
        mgr.ensure_loaded("model-b")
        cli.unload_model.assert_called_with("model-a")
        cli.load_model.assert_called_once()
        sessions = mgr.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].model_key, "model-b")

    def test_ensure_loaded_jit_records_session(self):
        mgr, cli = self._make_manager(mode="jit")
        mgr.ensure_loaded("model-a")
        session = mgr.list_sessions()[0]
        self.assertEqual(session.model_key, "model-a")
        self.assertEqual(session.request_count, 1)

    def test_ensure_loaded_jit_load_failure_still_tracks(self):
        mgr, cli = self._make_manager(mode="jit")
        cli.load_model.return_value = False
        result = mgr.ensure_loaded("model-fail")
        self.assertEqual(result, "model-fail")
        self.assertEqual(len(mgr.list_sessions()), 1)

    # -- JIT_TTL mode --

    def test_ensure_loaded_jit_ttl_loads_new(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        result = mgr.ensure_loaded("model-a")
        self.assertEqual(result, "model-a")
        cli.load_model.assert_called_once()

    def test_ensure_loaded_jit_ttl_already_loaded_touches(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        mgr.ensure_loaded("model-a")
        old_count = mgr.list_sessions()[0].request_count
        cli.load_model.reset_mock()
        mgr.ensure_loaded("model-a")
        cli.load_model.assert_not_called()
        self.assertEqual(mgr.list_sessions()[0].request_count, old_count + 1)

    def test_ensure_loaded_jit_ttl_multiple_coexist(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        mgr.ensure_loaded("model-a")
        mgr.ensure_loaded("model-b")
        keys = {s.model_key for s in mgr.list_sessions()}
        self.assertEqual(keys, {"model-a", "model-b"})

    def test_ensure_loaded_jit_ttl_skips_load_if_lms_has_it(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        cli.list_loaded_models.return_value = [{"model_key": "model-a"}]
        mgr.ensure_loaded("model-a")
        cli.load_model.assert_not_called()

    def test_ensure_loaded_passes_custom_params(self):
        mgr, cli = self._make_manager(mode="jit")
        mgr.ensure_loaded("model-a", gpu=0.5, context_length=8192, ttl_seconds=60)
        cli.load_model.assert_called_once_with(
            "model-a", gpu=0.5, context_length=8192, ttl=0, force=True,
        )


class TestModelManagerRelease(unittest.TestCase):
    """ModelManager.release() behaviour per mode."""

    def _make_manager(self, mode="jit"):
        defaults = {
            "lmstudio.load_mode": mode,
            "lmstudio.jit_ttl_seconds": 300,
            "lmstudio.default_load_opts.gpu": 0.9,
            "lmstudio.default_load_opts.context_length": 4096,
            "lmstudio.concurrent_model": "test-8b",
        }
        cfg = MagicMock()
        cfg.get = lambda key, default=None: defaults.get(key, default)
        cli = MagicMock()
        cli.load_model = MagicMock(return_value=True)
        cli.unload_model = MagicMock()
        cli.list_loaded_models = MagicMock(return_value=[])
        mgr = ModelManager(config=cfg, cli_manager=cli)
        return mgr, cli

    def test_release_jit_unloads(self):
        mgr, cli = self._make_manager(mode="jit")
        mgr.ensure_loaded("model-a")
        mgr.release("model-a")
        cli.unload_model.assert_called_with("model-a")
        self.assertEqual(mgr.list_sessions(), [])

    def test_release_jit_ttl_unloads(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        mgr.ensure_loaded("model-a")
        mgr.release("model-a")
        cli.unload_model.assert_called_with("model-a")
        self.assertEqual(mgr.list_sessions(), [])

    def test_release_concurrent_is_noop(self):
        mgr, cli = self._make_manager(mode="concurrent")
        mgr.ensure_loaded("model-a")
        mgr.release("model-a")
        cli.unload_model.assert_not_called()
        self.assertEqual(len(mgr.list_sessions()), 1)

    def test_release_nonexistent_model_no_error(self):
        mgr, cli = self._make_manager(mode="jit")
        mgr.release("never-loaded")
        cli.unload_model.assert_called_with("never-loaded")


class TestModelManagerSetMode(unittest.TestCase):
    """ModelManager.set_mode() transitions."""

    def _make_manager(self, mode="concurrent"):
        defaults = {
            "lmstudio.load_mode": mode,
            "lmstudio.jit_ttl_seconds": 300,
            "lmstudio.default_load_opts.gpu": 0.9,
            "lmstudio.default_load_opts.context_length": 4096,
            "lmstudio.concurrent_model": "test-8b",
        }
        cfg = MagicMock()
        cfg.get = lambda key, default=None: defaults.get(key, default)
        cli = MagicMock()
        cli.load_model = MagicMock(return_value=True)
        cli.unload_model = MagicMock()
        cli.list_loaded_models = MagicMock(return_value=[])
        return ModelManager(config=cfg, cli_manager=cli)

    def test_switch_concurrent_to_jit(self):
        mgr = self._make_manager(mode="concurrent")
        mgr.set_mode(LoadMode.JIT)
        self.assertEqual(mgr.mode, LoadMode.JIT)

    def test_switch_jit_to_jit_ttl(self):
        mgr = self._make_manager(mode="jit")
        mgr.set_mode(LoadMode.JIT_TTL, ttl_seconds=120)
        self.assertEqual(mgr.mode, LoadMode.JIT_TTL)
        self.assertEqual(mgr._default_ttl, 120)

    def test_switch_jit_ttl_to_concurrent(self):
        mgr = self._make_manager(mode="jit_ttl")
        mgr.set_mode(LoadMode.CONCURRENT, concurrent_model="big-model")
        self.assertEqual(mgr.mode, LoadMode.CONCURRENT)
        self.assertEqual(mgr._concurrent_model, "big-model")

    def test_set_mode_preserves_ttl_when_not_overridden(self):
        mgr = self._make_manager(mode="concurrent")
        mgr.set_mode(LoadMode.JIT)
        self.assertEqual(mgr._default_ttl, 300)

    def test_set_mode_starts_reaper_for_jit_ttl(self):
        mgr = self._make_manager(mode="concurrent")
        mgr.set_mode(LoadMode.JIT_TTL)
        self.assertIsNotNone(mgr._reaper_thread)
        self.assertTrue(mgr._reaper_thread.is_alive())
        mgr._stop_reaper.set()

    def test_set_mode_stops_reaper_leaving_jit_ttl(self):
        mgr = self._make_manager(mode="jit_ttl")
        self.assertTrue(mgr._reaper_thread.is_alive())
        mgr.set_mode(LoadMode.JIT)
        self.assertTrue(mgr._stop_reaper.is_set())


class TestModelManagerEviction(unittest.TestCase):
    """Eviction logic: JIT evict-on-next-load and JIT_TTL reap_expired."""

    def _make_manager(self, mode="jit"):
        defaults = {
            "lmstudio.load_mode": mode,
            "lmstudio.jit_ttl_seconds": 300,
            "lmstudio.default_load_opts.gpu": 0.9,
            "lmstudio.default_load_opts.context_length": 4096,
            "lmstudio.concurrent_model": "",
        }
        cfg = MagicMock()
        cfg.get = lambda key, default=None: defaults.get(key, default)
        cli = MagicMock()
        cli.load_model = MagicMock(return_value=True)
        cli.unload_model = MagicMock()
        cli.list_loaded_models = MagicMock(return_value=[])
        mgr = ModelManager(config=cfg, cli_manager=cli)
        return mgr, cli

    def test_jit_evicts_all_others_on_new_load(self):
        mgr, cli = self._make_manager(mode="jit")
        # Manually insert two sessions to simulate state
        mgr._sessions["old-1"] = ModelSession(model_key="old-1")
        mgr._sessions["old-2"] = ModelSession(model_key="old-2")
        mgr.ensure_loaded("new-model")
        self.assertNotIn("old-1", {s.model_key for s in mgr.list_sessions()})
        self.assertNotIn("old-2", {s.model_key for s in mgr.list_sessions()})
        self.assertIn("new-model", {s.model_key for s in mgr.list_sessions()})

    def test_jit_no_eviction_when_same_model(self):
        mgr, cli = self._make_manager(mode="jit")
        mgr.ensure_loaded("model-a")
        cli.unload_model.reset_mock()
        mgr.ensure_loaded("model-a")
        cli.unload_model.assert_not_called()

    def test_reap_expired_removes_idle_sessions(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        # Insert a session with very short TTL, already expired
        expired_session = ModelSession(model_key="old-model", ttl_seconds=0)
        # ttl_seconds=0 means never expire, so use a tiny TTL
        expired_session.ttl_seconds = 1
        expired_session.last_used_at = time.monotonic() - 10  # idle 10s > 1s TTL
        mgr._sessions["old-model"] = expired_session
        mgr._reap_expired()
        self.assertNotIn("old-model", {s.model_key for s in mgr.list_sessions()})
        cli.unload_model.assert_called_with("old-model")

    def test_reap_expired_keeps_fresh_sessions(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        fresh = ModelSession(model_key="fresh", ttl_seconds=300)
        mgr._sessions["fresh"] = fresh
        mgr._reap_expired()
        self.assertIn("fresh", {s.model_key for s in mgr.list_sessions()})
        cli.unload_model.assert_not_called()

    def test_reap_expired_zero_ttl_never_expires(self):
        mgr, cli = self._make_manager(mode="jit_ttl")
        permanent = ModelSession(model_key="perm", ttl_seconds=0)
        permanent.last_used_at = time.monotonic() - 9999
        mgr._sessions["perm"] = permanent
        mgr._reap_expired()
        self.assertIn("perm", {s.model_key for s in mgr.list_sessions()})


class TestModelManagerShutdown(unittest.TestCase):
    """ModelManager.shutdown() cleanup."""

    def test_shutdown_clears_sessions(self):
        defaults = {
            "lmstudio.load_mode": "jit",
            "lmstudio.jit_ttl_seconds": 300,
            "lmstudio.default_load_opts.gpu": 0.9,
            "lmstudio.default_load_opts.context_length": 4096,
            "lmstudio.concurrent_model": "",
        }
        cfg = MagicMock()
        cfg.get = lambda key, default=None: defaults.get(key, default)
        cli = MagicMock()
        cli.load_model = MagicMock(return_value=True)
        cli.unload_model = MagicMock()
        cli.list_loaded_models = MagicMock(return_value=[])
        mgr = ModelManager(config=cfg, cli_manager=cli)
        mgr.ensure_loaded("model-a")
        mgr.shutdown()
        self.assertEqual(mgr.list_sessions(), [])
        cli.unload_model.assert_called()


# ── InferenceRouter tests ───────────────────────────────────────────

from engine.lmstudio.router import (
    InferenceRouter, InferenceRequest, TierConfig, RouterMetrics,
)


class TestInferenceRouterPriorityQueue(unittest.TestCase):
    """Queue ordering respects priority levels."""

    def _make_router(self):
        return InferenceRouter(max_queue_depth=50)

    def test_queue_ordering_by_priority(self):
        router = self._make_router()
        f_batch = router.submit(InferenceRequest(priority=Priority.BATCH))
        f_rt = router.submit(InferenceRequest(priority=Priority.REALTIME))
        f_bg = router.submit(InferenceRequest(priority=Priority.BACKGROUND))
        f_inter = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
        # Queue should order: REALTIME, INTERACTIVE, BACKGROUND, BATCH
        entries = sorted(router._queue)
        priorities = [e[0] for e in entries]
        self.assertEqual(priorities, [0, 1, 2, 3])

    def test_same_priority_fifo(self):
        router = self._make_router()
        f1 = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
        f2 = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
        f3 = router.submit(InferenceRequest(priority=Priority.INTERACTIVE))
        sequences = [e[1] for e in sorted(router._queue)]
        self.assertEqual(sequences, sorted(sequences))

    def test_submit_increments_metrics(self):
        router = self._make_router()
        router.submit(InferenceRequest(priority=Priority.REALTIME))
        router.submit(InferenceRequest(priority=Priority.BATCH))
        self.assertEqual(router._metrics.total_submitted, 2)
        self.assertEqual(router._metrics.queue_depth, 2)

    def test_submit_queue_full_returns_failed_future(self):
        router = InferenceRouter(max_queue_depth=2)
        router.submit(InferenceRequest(priority=Priority.BATCH))
        router.submit(InferenceRequest(priority=Priority.BATCH))
        f = router.submit(InferenceRequest(priority=Priority.BATCH))
        with self.assertRaises(RuntimeError):
            f.result(timeout=0.1)


class TestInferenceRouterTierSelection(unittest.TestCase):
    """Tier selection logic in select_tier()."""

    def _make_router(self):
        return InferenceRouter()

    def test_explicit_tier_used(self):
        router = self._make_router()
        req = InferenceRequest(tier=Tier.CPU_UTILITY)
        self.assertEqual(router.select_tier(req), Tier.CPU_UTILITY)

    def test_classify_routes_to_cpu_router(self):
        router = self._make_router()
        req = InferenceRequest(task_type="classify")
        self.assertEqual(router.select_tier(req), Tier.CPU_ROUTER)

    def test_route_task_routes_to_cpu_router(self):
        router = self._make_router()
        req = InferenceRequest(task_type="route")
        self.assertEqual(router.select_tier(req), Tier.CPU_ROUTER)

    def test_tag_extract_routes_to_cpu_router(self):
        router = self._make_router()
        req = InferenceRequest(task_type="tag_extract")
        self.assertEqual(router.select_tier(req), Tier.CPU_ROUTER)

    def test_act_routes_to_gpu(self):
        router = self._make_router()
        req = InferenceRequest(task_type="act")
        self.assertEqual(router.select_tier(req), Tier.GPU_PRIMARY)

    def test_tools_present_routes_to_gpu(self):
        router = self._make_router()
        req = InferenceRequest(task_type="chat", tools=[{"name": "tool1"}])
        self.assertEqual(router.select_tier(req), Tier.GPU_PRIMARY)

    def test_background_no_tools_routes_to_cpu_utility(self):
        router = self._make_router()
        req = InferenceRequest(priority=Priority.BACKGROUND, task_type="chat")
        self.assertEqual(router.select_tier(req), Tier.CPU_UTILITY)

    def test_batch_no_tools_routes_to_cpu_utility(self):
        router = self._make_router()
        req = InferenceRequest(priority=Priority.BATCH, task_type="chat")
        self.assertEqual(router.select_tier(req), Tier.CPU_UTILITY)

    def test_interactive_chat_routes_to_gpu(self):
        router = self._make_router()
        req = InferenceRequest(priority=Priority.INTERACTIVE, task_type="chat")
        self.assertEqual(router.select_tier(req), Tier.GPU_PRIMARY)

    def test_realtime_routes_to_gpu(self):
        router = self._make_router()
        req = InferenceRequest(priority=Priority.REALTIME, task_type="chat")
        self.assertEqual(router.select_tier(req), Tier.GPU_PRIMARY)

    def test_disabled_cpu_router_falls_through(self):
        tiers = {
            Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY, max_slots=2),
            Tier.CPU_UTILITY: TierConfig(tier=Tier.CPU_UTILITY, max_slots=1),
            Tier.CPU_ROUTER: TierConfig(tier=Tier.CPU_ROUTER, enabled=False),
        }
        router = InferenceRouter(tiers=tiers)
        req = InferenceRequest(task_type="classify")
        # CPU_ROUTER disabled → tools absent, not background → GPU_PRIMARY
        self.assertEqual(router.select_tier(req), Tier.GPU_PRIMARY)

    def test_agent_affinity_used_when_slot_available(self):
        router = self._make_router()
        router.bind_agent("agent-1", Tier.CPU_UTILITY)
        # CPU_UTILITY default has max_slots=1, busy=0 → available
        req = InferenceRequest(agent_id="agent-1", task_type="chat",
                               priority=Priority.INTERACTIVE)
        self.assertEqual(router.select_tier(req), Tier.CPU_UTILITY)


class TestInferenceRouterChannelSelection(unittest.TestCase):
    """Channel selection logic in select_channel()."""

    def _make_router(self):
        return InferenceRouter()

    def test_explicit_channel_used(self):
        router = self._make_router()
        req = InferenceRequest(channel=Channel.REST)
        self.assertEqual(router.select_channel(req, Tier.GPU_PRIMARY), Channel.REST)

    def test_act_uses_sdk(self):
        router = self._make_router()
        req = InferenceRequest(task_type="act", tools=[{"name": "t"}])
        self.assertEqual(router.select_channel(req, Tier.GPU_PRIMARY), Channel.SDK)

    def test_tools_present_uses_sdk(self):
        router = self._make_router()
        req = InferenceRequest(tools=[{"name": "t"}])
        self.assertEqual(router.select_channel(req, Tier.GPU_PRIMARY), Channel.SDK)

    def test_tier_default_channel(self):
        tiers = {
            Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY, channel=Channel.REST),
        }
        router = InferenceRouter(tiers=tiers)
        req = InferenceRequest(task_type="chat")
        self.assertEqual(router.select_channel(req, Tier.GPU_PRIMARY), Channel.REST)


class TestInferenceRouterSlots(unittest.TestCase):
    """Slot availability checks."""

    def test_has_available_slot_true(self):
        router = InferenceRouter()
        self.assertTrue(router.has_available_slot(Tier.GPU_PRIMARY))

    def test_has_available_slot_false_when_full(self):
        router = InferenceRouter()
        tc = router._tiers[Tier.GPU_PRIMARY]
        tc._busy_slots = tc.max_slots
        self.assertFalse(router.has_available_slot(Tier.GPU_PRIMARY))

    def test_has_available_slot_false_when_disabled(self):
        tiers = {
            Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY, enabled=False),
        }
        router = InferenceRouter(tiers=tiers)
        self.assertFalse(router.has_available_slot(Tier.GPU_PRIMARY))

    def test_has_available_slot_missing_tier(self):
        # Empty dict is falsy, so pass explicit tier with only GPU
        tiers = {Tier.GPU_PRIMARY: TierConfig(tier=Tier.GPU_PRIMARY)}
        router = InferenceRouter(tiers=tiers)
        self.assertFalse(router.has_available_slot(Tier.CPU_ROUTER))


class TestInferenceRouterFallback(unittest.TestCase):
    """Fallback tier selection."""

    def test_gpu_full_falls_to_cpu_utility(self):
        router = InferenceRouter()
        req = InferenceRequest(task_type="chat")
        fallback = router._find_fallback_tier(Tier.GPU_PRIMARY, req)
        self.assertEqual(fallback, Tier.CPU_UTILITY)

    def test_gpu_full_no_fallback_with_tools(self):
        router = InferenceRouter()
        req = InferenceRequest(tools=[{"name": "t"}])
        fallback = router._find_fallback_tier(Tier.GPU_PRIMARY, req)
        self.assertIsNone(fallback)

    def test_cpu_utility_falls_to_gpu(self):
        router = InferenceRouter()
        req = InferenceRequest(task_type="chat")
        fallback = router._find_fallback_tier(Tier.CPU_UTILITY, req)
        self.assertEqual(fallback, Tier.GPU_PRIMARY)

    def test_cpu_router_no_fallback(self):
        router = InferenceRouter()
        req = InferenceRequest(task_type="classify")
        fallback = router._find_fallback_tier(Tier.CPU_ROUTER, req)
        self.assertIsNone(fallback)


class TestInferenceRouterLifecycle(unittest.TestCase):
    """Router start/stop and agent binding."""

    def test_start_stop(self):
        router = InferenceRouter()
        router.start()
        self.assertTrue(router._running)
        router.stop()
        self.assertFalse(router._running)

    def test_stop_cancels_pending(self):
        router = InferenceRouter()
        f1 = router.submit(InferenceRequest(priority=Priority.BATCH))
        f2 = router.submit(InferenceRequest(priority=Priority.BATCH))
        router.stop()
        self.assertEqual(len(router._queue), 0)

    def test_bind_unbind_agent(self):
        router = InferenceRouter()
        router.bind_agent("agent-1", Tier.GPU_PRIMARY)
        self.assertEqual(router.get_agent_bindings(), {"agent-1": "gpu_primary"})
        router.unbind_agent("agent-1")
        self.assertEqual(router.get_agent_bindings(), {})

    def test_get_metrics_structure(self):
        router = InferenceRouter()
        m = router.get_metrics()
        self.assertIn("total_submitted", m)
        self.assertIn("queue_depth", m)
        self.assertIn("slots", m)
        self.assertIn("tier_counts", m)


if __name__ == "__main__":
    unittest.main()
