"""Tests for ServerController, LMLinkManager, TaskQueue, and server skills."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────

def _mock_config(overrides: dict | None = None):
    """Create a mock config with sensible LMStudio defaults."""
    defaults = {
        "lmstudio.health.check_interval_seconds": 30,
        "lmstudio.default_load_opts.context_length": 4096,
        "lmstudio.default_load_opts.gpu": 0.9,
        "lmstudio.default_load_opts.ttl": 3600,
        "lmstudio.vram_cap_mb": 12288,
        "lmstudio.models.primary.path": "qwen3-8b",
        "lmstudio.task_queue.affinity": {},
        "lmlink.enabled": False,
        "lmlink.local.name": "workstation",
        "lmlink.local.host": "localhost",
        "lmlink.local.port": 1234,
        "lmlink.local.capabilities": ["inference"],
        "lmlink.peers": [],
        "lmlink.routing.strategy": "capability_first",
        "lmlink.routing.affinity": [],
        "lmlink.routing.failover.enabled": True,
        "lmlink.routing.failover.max_retries": 2,
        "lmlink.routing.failover.retry_delay_ms": 10,
        "lmlink.routing.failover.fallback_to_local": True,
        "lmlink.health.check_interval_seconds": 60,
        "lmlink.health.timeout_ms": 5000,
        "lmlink.health.auto_reconnect": True,
        "lmlink.health.max_reconnect_attempts": 3,
    }
    if overrides:
        defaults.update(overrides)

    cfg = MagicMock()
    cfg.get = lambda key, default=None: defaults.get(key, default)
    return cfg


# ── ServerController Tests ───────────────────────────────────────────────

class TestServerController:
    """Tests for engine.lmstudio.server_controller."""

    def _make_ctrl(self, config=None):
        from engine.lmstudio.server_controller import ServerController
        return ServerController(config=config or _mock_config())

    def test_init(self):
        ctrl = self._make_ctrl()
        assert ctrl._instances == {}
        assert ctrl._agent_instances == {}
        assert ctrl._metrics["total_loads"] == 0

    def test_load_model_via_sdk(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        ctrl._sdk_client = mock_sdk

        instance = ctrl.load_model(
            "qwen3-0.6b",
            context_length=4096,
            gpu_offload=0.8,
            stop_strings=["<|end|>"],
        )

        assert instance.model_key == "qwen3-0.6b"
        assert instance.context_length == 4096
        assert instance.gpu_offload == 0.8
        assert instance.stop_strings == ["<|end|>"]
        assert ctrl._metrics["total_loads"] == 1
        mock_sdk.load_instance.assert_called_once()

    def test_load_model_fallback_to_cli(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        mock_sdk.load_instance.side_effect = RuntimeError("SDK error")
        ctrl._sdk_client = mock_sdk
        mock_cli = MagicMock()
        ctrl._cli_manager = mock_cli

        instance = ctrl.load_model("qwen3-0.6b")
        assert instance.model_key == "qwen3-0.6b"
        mock_cli.load_model.assert_called_once()

    def test_unload_model(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        ctrl._sdk_client = mock_sdk

        ctrl.load_model("test-model")
        assert "test-model" in ctrl._instances

        result = ctrl.unload_model("test-model")
        assert result is True
        assert "test-model" not in ctrl._instances
        assert ctrl._metrics["total_unloads"] == 1

    def test_configure_inference(self):
        ctrl = self._make_ctrl()
        instance = ctrl.configure_inference(
            "qwen3-0.6b",
            stop_strings=["STOP"],
            temperature=0.3,
            max_tokens=1000,
        )
        assert instance.stop_strings == ["STOP"]
        assert instance.temperature == 0.3
        assert instance.max_tokens == 1000
        assert ctrl._metrics["total_config_changes"] == 1

    def test_create_agent_instance(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        ctrl._sdk_client = mock_sdk

        instance = ctrl.create_agent_instance(
            "aria", "qwen3-0.6b", context_length=8192
        )
        assert instance.agent_id == "aria"
        assert instance.model_key == "qwen3-0.6b"
        assert instance.instance_id == "aria_qwen3-0.6b"
        assert ctrl._agent_instances["aria"] == "aria_qwen3-0.6b"
        assert ctrl._metrics["total_instance_creates"] == 1

    def test_get_agent_instance(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        ctrl._sdk_client = mock_sdk

        ctrl.create_agent_instance("aria", "qwen3-0.6b")
        inst = ctrl.get_agent_instance("aria")
        assert inst is not None
        assert inst.agent_id == "aria"

    def test_release_agent_instance_isolated(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        ctrl._sdk_client = mock_sdk

        ctrl.create_agent_instance("aria", "qwen3-0.6b")
        result = ctrl.release_agent_instance("aria")
        assert result is True
        assert "aria" not in ctrl._agent_instances

    def test_release_agent_instance_shared(self):
        ctrl = self._make_ctrl()
        # SDK unavailable → shared model
        ctrl._sdk_client = None
        ctrl._cli_manager = MagicMock()
        ctrl._cli_manager.load_model = MagicMock()

        ctrl.create_agent_instance("aria", "qwen3-0.6b")
        # instance_id == model_key → shared, should NOT unload
        result = ctrl.release_agent_instance("aria")
        assert result is True

    def test_build_request_config_defaults(self):
        ctrl = self._make_ctrl()
        ctrl.configure_inference(
            "model-a",
            stop_strings=["END"],
            temperature=0.5,
            max_tokens=500,
        )
        config = ctrl.build_request_config("model-a")
        assert config["stop_strings"] == ["END"]
        assert config["temperature"] == 0.5
        assert config["max_tokens"] == 500

    def test_build_request_config_with_overrides(self):
        ctrl = self._make_ctrl()
        ctrl.configure_inference("model-a", stop_strings=["END"])
        config = ctrl.build_request_config(
            "model-a",
            override_stop_strings=["STOP"],
            override_temperature=0.1,
        )
        assert config["stop_strings"] == ["STOP"]
        assert config["temperature"] == 0.1

    def test_build_request_config_no_instance(self):
        ctrl = self._make_ctrl()
        config = ctrl.build_request_config("nonexistent")
        assert config == {}

    def test_count_tokens_fallback(self):
        ctrl = self._make_ctrl()
        ctrl._sdk_client = None
        count = ctrl.count_tokens("Hello world, this is a test sentence.")
        # Without SDK, returns -1 (unavailable)
        assert count == -1

    def test_get_server_status_unreachable(self):
        ctrl = self._make_ctrl()
        mock_cli = MagicMock()
        mock_cli.is_server_running.return_value = False
        ctrl._cli_manager = mock_cli

        health = ctrl.get_server_status()
        assert health.reachable is False
        assert health.error == "Server not reachable"

    def test_get_server_status_reachable(self):
        ctrl = self._make_ctrl()
        mock_cli = MagicMock()
        mock_cli.is_server_running.return_value = True
        ctrl._cli_manager = mock_cli
        mock_sdk = MagicMock()
        mock_sdk.list_loaded.return_value = [
            {"model_key": "qwen3-0.6b"},
            {"model_key": "llama-8b"},
        ]
        ctrl._sdk_client = mock_sdk

        health = ctrl.get_server_status()
        assert health.reachable is True
        assert health.loaded_models == 2
        assert "qwen3-0.6b" in health.model_names

    def test_list_models(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        mock_sdk.list_loaded.return_value = [{"model_key": "m1"}]
        mock_sdk.list_downloaded.return_value = [{"model_key": "m2"}]
        ctrl._sdk_client = mock_sdk

        result = ctrl.list_models()
        assert len(result["loaded"]) == 1
        assert len(result["downloaded"]) == 1

    def test_get_full_status(self):
        ctrl = self._make_ctrl()
        mock_cli = MagicMock()
        mock_cli.is_server_running.return_value = True
        ctrl._cli_manager = mock_cli
        mock_sdk = MagicMock()
        mock_sdk.list_loaded.return_value = []
        ctrl._sdk_client = mock_sdk

        status = ctrl.get_full_status()
        assert "server" in status
        assert "instances" in status
        assert "metrics" in status

    def test_get_metrics(self):
        ctrl = self._make_ctrl()
        metrics = ctrl.get_metrics()
        assert metrics["total_loads"] == 0
        assert metrics["active_instances"] == 0

    def test_shutdown(self):
        ctrl = self._make_ctrl()
        mock_sdk = MagicMock()
        ctrl._sdk_client = mock_sdk
        ctrl.load_model("m1")
        ctrl.create_agent_instance("a1", "m2")

        ctrl.shutdown()
        assert len(ctrl._instances) == 0
        assert len(ctrl._agent_instances) == 0

    def test_model_instance_touch(self):
        from engine.lmstudio.server_controller import ModelInstance

        inst = ModelInstance(model_key="test")
        inst.touch(tokens=100)
        assert inst.request_count == 1
        assert inst.total_tokens == 100

    def test_server_health_properties(self):
        from engine.lmstudio.server_controller import ServerHealth

        h = ServerHealth(reachable=True, vram_used_mb=6000, vram_total_mb=12000)
        assert h.healthy is True
        assert h.vram_usage_pct == 50.0
        d = h.to_dict()
        assert d["vram_usage_pct"] == 50.0

    def test_singleton_pattern(self):
        import engine.lmstudio.server_controller as mod
        mod._instance = None
        ctrl1 = mod.get_server_controller(config=_mock_config())
        ctrl2 = mod.get_server_controller()
        assert ctrl1 is ctrl2
        mod._instance = None


# ── LMLinkManager Tests ─────────────────────────────────────────────────

class TestLMLinkManager:
    """Tests for engine.lmstudio.lmlink_manager."""

    def _make_mgr(self, overrides=None):
        import engine.lmstudio.lmlink_manager as mod
        mod._instance = None
        defaults = {
            "lmlink.enabled": True,
            "lmlink.peers": [
                {
                    "name": "nuc",
                    "host": "100.64.0.5",
                    "port": 1234,
                    "capabilities": ["inference"],
                    "max_models": 2,
                    "max_context": 8192,
                    "priority": 2,
                    "tags": ["remote", "arm"],
                },
            ],
            "lmlink.routing.affinity": [
                {"pattern": "*70B*", "prefer": "workstation"},
                {"pattern": "*0.6b*", "prefer": "nuc"},
            ],
        }
        if overrides:
            defaults.update(overrides)
        return mod.LMLinkManager(config=_mock_config(defaults))

    def test_init_peers(self):
        mgr = self._make_mgr()
        assert mgr.enabled is True
        assert len(mgr._peers) == 2
        assert mgr.get_peer("workstation") is not None
        assert mgr.get_peer("nuc") is not None

    def test_local_peer(self):
        mgr = self._make_mgr()
        local = mgr.get_local_peer()
        assert local is not None
        assert local.is_local is True
        assert local.name == "workstation"

    def test_remote_peers(self):
        mgr = self._make_mgr()
        remotes = mgr.get_remote_peers()
        assert len(remotes) == 1
        assert remotes[0].name == "nuc"

    def test_affinity_routing_70b(self):
        mgr = self._make_mgr()
        # workstation is local → reachable=True
        mgr._peers["nuc"].reachable = True

        decision = mgr.resolve_peer("llama-70B-instruct")
        assert decision is not None
        assert decision.peer.name == "workstation"
        assert "affinity_rule" in decision.reason

    def test_affinity_routing_small(self):
        mgr = self._make_mgr()
        mgr._peers["nuc"].reachable = True

        decision = mgr.resolve_peer("qwen3-0.6b")
        assert decision is not None
        assert decision.peer.name == "nuc"
        assert "affinity_rule" in decision.reason

    def test_strategy_local_first(self):
        mgr = self._make_mgr({"lmlink.routing.strategy": "local_first"})
        mgr._strategy = "local_first"
        mgr._peers["nuc"].reachable = True

        # No affinity match → strategy kicks in
        decision = mgr.resolve_peer("some-unknown-model")
        assert decision is not None
        assert decision.peer.name == "workstation"

    def test_strategy_round_robin(self):
        mgr = self._make_mgr({"lmlink.routing.strategy": "round_robin"})
        mgr._strategy = "round_robin"
        mgr._peers["nuc"].reachable = True
        mgr._peers["workstation"].total_requests = 10
        mgr._peers["nuc"].total_requests = 5

        decision = mgr.resolve_peer("some-model")
        assert decision is not None
        assert decision.peer.name == "nuc"

    def test_strategy_least_loaded(self):
        mgr = self._make_mgr({"lmlink.routing.strategy": "least_loaded"})
        mgr._strategy = "least_loaded"
        mgr._peers["nuc"].reachable = True
        mgr._peers["workstation"].loaded_models = ["m1", "m2", "m3"]
        mgr._peers["nuc"].loaded_models = ["m1"]

        decision = mgr.resolve_peer("some-model")
        assert decision is not None
        assert decision.peer.name == "nuc"

    def test_strategy_capability_first(self):
        mgr = self._make_mgr()
        mgr._peers["nuc"].reachable = True
        mgr._peers["nuc"].loaded_models = ["specific-model"]

        decision = mgr.resolve_peer("specific-model")
        assert decision is not None
        assert decision.peer.name == "nuc"

    def test_no_healthy_peers(self):
        mgr = self._make_mgr()
        mgr._peers["workstation"].reachable = False
        mgr._peers["nuc"].reachable = False

        decision = mgr.resolve_peer("any-model")
        assert decision is None

    def test_capability_filter(self):
        mgr = self._make_mgr()
        mgr._peers["nuc"].reachable = True

        # Neither has "vision" capability
        decision = mgr.resolve_peer("model", require_capability="vision")
        assert decision is None

    def test_exclude_peers(self):
        mgr = self._make_mgr()
        mgr._peers["nuc"].reachable = True

        decision = mgr.resolve_peer(
            "some-model",
            exclude_peers=["workstation"],
        )
        assert decision is not None
        assert decision.peer.name == "nuc"

    def test_failover(self):
        mgr = self._make_mgr()
        mgr._peers["nuc"].reachable = True
        mgr._peers["workstation"].reachable = False
        mgr._peers["workstation"].consecutive_failures = 5

        decision = mgr.resolve_with_failover("some-model")
        assert decision is not None
        assert decision.peer.name == "nuc"

    def test_failover_to_local(self):
        mgr = self._make_mgr()
        mgr._peers["nuc"].reachable = False
        mgr._peers["nuc"].consecutive_failures = 5
        mgr._peers["workstation"].reachable = False
        mgr._peers["workstation"].consecutive_failures = 5

        # All unhealthy → fallback to local
        decision = mgr.resolve_with_failover("model")
        assert decision is not None
        assert decision.reason == "fallback_to_local"

    def test_disabled_returns_local(self):
        import engine.lmstudio.lmlink_manager as mod
        mod._instance = None
        mgr = mod.LMLinkManager(config=_mock_config({"lmlink.enabled": False}))

        decision = mgr.resolve_peer("any-model")
        assert decision is not None
        assert decision.reason == "lmlink_disabled_local_default"

    def test_peer_record_success(self):
        from engine.lmstudio.lmlink_manager import LMLinkPeer

        peer = LMLinkPeer(name="test", host="localhost")
        peer.record_success(latency_ms=100)
        assert peer.total_requests == 1
        assert peer.avg_latency_ms == 100.0
        assert peer.consecutive_failures == 0

    def test_peer_record_failure(self):
        from engine.lmstudio.lmlink_manager import LMLinkPeer

        peer = LMLinkPeer(name="test", host="localhost")
        peer.record_failure()
        assert peer.total_errors == 1
        assert peer.consecutive_failures == 1

    def test_peer_healthy_property(self):
        from engine.lmstudio.lmlink_manager import LMLinkPeer

        peer = LMLinkPeer(name="test", host="localhost", reachable=True)
        assert peer.healthy is True
        peer.consecutive_failures = 3
        assert peer.healthy is False

    def test_peer_error_rate(self):
        from engine.lmstudio.lmlink_manager import LMLinkPeer

        peer = LMLinkPeer(name="test", host="localhost")
        peer.total_requests = 8
        peer.total_errors = 2
        assert peer.error_rate == 0.2

    def test_affinity_rule_matches(self):
        from engine.lmstudio.lmlink_manager import AffinityRule

        rule = AffinityRule(pattern="*70B*", prefer="workstation")
        assert rule.matches("llama-70B-instruct") is True
        assert rule.matches("qwen3-0.6b") is False

    def test_routing_decision_to_dict(self):
        from engine.lmstudio.lmlink_manager import LMLinkPeer, RoutingDecision

        peer = LMLinkPeer(name="ws", host="localhost")
        rd = RoutingDecision(peer=peer, model_key="m1", reason="test")
        d = rd.to_dict()
        assert d["peer"] == "ws"
        assert d["model_key"] == "m1"

    def test_get_status(self):
        mgr = self._make_mgr()
        status = mgr.get_status()
        assert status["enabled"] is True
        assert "workstation" in status["peers"]
        assert "nuc" in status["peers"]
        assert len(status["affinity_rules"]) == 2

    def test_singleton(self):
        import engine.lmstudio.lmlink_manager as mod
        mod._instance = None
        mgr1 = mod.get_lmlink_manager(config=_mock_config({"lmlink.enabled": False}))
        mgr2 = mod.get_lmlink_manager()
        assert mgr1 is mgr2
        mod._instance = None


# ── TaskQueue Tests ──────────────────────────────────────────────────────

class TestTaskQueue:
    """Tests for engine.lmstudio.task_queue."""

    def _make_queue(self, config=None, **kwargs):
        import engine.lmstudio.task_queue as mod
        mod._instance = None
        return mod.TaskQueue(config=config or _mock_config(), **kwargs)

    def test_init(self):
        q = self._make_queue()
        assert q.queue_depth == 0
        assert q.active_tasks == 0

    def test_submit_task(self):
        from engine.lmstudio.task_queue import TaskType, TaskStatus

        q = self._make_queue()
        task = q.submit(TaskType.CODE, prompt="Fix this bug")

        assert task.id is not None
        assert task.task_type == TaskType.CODE
        assert task.status == TaskStatus.QUEUED
        assert len(task.messages) == 1
        assert task.messages[0]["role"] == "user"
        assert q.queue_depth == 1

    def test_submit_with_system_prompt(self):
        from engine.lmstudio.task_queue import TaskType

        q = self._make_queue()
        task = q.submit(
            TaskType.CHAT,
            prompt="Hello",
            system_prompt="You are a helper",
        )
        assert len(task.messages) == 2
        assert task.messages[0]["role"] == "system"
        assert task.messages[1]["role"] == "user"

    def test_submit_with_messages(self):
        from engine.lmstudio.task_queue import TaskType

        q = self._make_queue()
        msgs = [{"role": "user", "content": "test"}]
        task = q.submit(TaskType.CHAT, messages=msgs)
        assert task.messages == msgs

    def test_cancel_task(self):
        from engine.lmstudio.task_queue import TaskType, TaskStatus

        q = self._make_queue()
        task = q.submit(TaskType.CHAT, prompt="test")
        assert q.cancel(task.id) is True
        assert task.status == TaskStatus.CANCELLED

    def test_cancel_nonexistent(self):
        q = self._make_queue()
        assert q.cancel("nonexistent") is False

    def test_get_task(self):
        from engine.lmstudio.task_queue import TaskType

        q = self._make_queue()
        task = q.submit(TaskType.CHAT, prompt="test")
        found = q.get_task(task.id)
        assert found is task

    def test_task_ordering(self):
        from engine.lmstudio.task_queue import Task, TaskType, TaskPriority

        t1 = Task(task_type=TaskType.CHAT, priority=TaskPriority.LOW)
        t2 = Task(task_type=TaskType.CODE, priority=TaskPriority.HIGH)
        assert t2 < t1  # HIGH (1) < LOW (3)

    def test_task_metrics(self):
        from engine.lmstudio.task_queue import TaskType

        q = self._make_queue()
        q.submit(TaskType.CODE, prompt="test1")
        q.submit(TaskType.VISION, prompt="test2")
        assert q._metrics.total_submitted == 2

    def test_get_status(self):
        from engine.lmstudio.task_queue import TaskType

        q = self._make_queue()
        q.submit(TaskType.CHAT, prompt="test")
        status = q.get_status()
        assert status["queue_depth"] == 1
        assert status["total_tasks"] == 1
        assert status["started"] is False

    def test_get_recent_tasks(self):
        from engine.lmstudio.task_queue import TaskType

        q = self._make_queue()
        for i in range(5):
            q.submit(TaskType.CHAT, prompt=f"task {i}")
        recent = q.get_recent_tasks(limit=3)
        assert len(recent) == 3

    def test_task_to_dict(self):
        from engine.lmstudio.task_queue import Task, TaskType, TaskPriority

        task = Task(
            task_type=TaskType.CODE,
            priority=TaskPriority.HIGH,
            model_hint="coder-model",
        )
        d = task.to_dict()
        assert d["task_type"] == "code"
        assert d["priority"] == "HIGH"
        assert d["model_hint"] == "coder-model"

    def test_metrics_to_dict(self):
        from engine.lmstudio.task_queue import TaskQueueMetrics

        m = TaskQueueMetrics()
        d = m.to_dict()
        assert d["total_submitted"] == 0
        assert d["total_completed"] == 0

    def test_metrics_record_completion(self):
        from engine.lmstudio.task_queue import TaskQueueMetrics, Task, TaskType

        m = TaskQueueMetrics()
        task = Task(task_type=TaskType.CODE, assigned_model="m1")
        task.latency_ms = 100
        task.tokens_used = 50
        task.started_at = time.time() - 0.5
        m.record_completion(task)

        assert m.total_completed == 1
        assert m.total_tokens == 50
        assert m.by_type["code"] == 1
        assert m.by_model["m1"] == 1

    def test_queue_depth_limit(self):
        from engine.lmstudio.task_queue import TaskType, TaskStatus

        q = self._make_queue(max_queue_depth=2)
        q.submit(TaskType.CHAT, prompt="1")
        q.submit(TaskType.CHAT, prompt="2")
        task3 = q.submit(TaskType.CHAT, prompt="3")
        assert task3.status == TaskStatus.FAILED
        assert task3.error == "Queue full"

    def test_callback_registration(self):
        from engine.lmstudio.task_queue import TaskType

        q = self._make_queue()
        completed = []
        q.on_complete(lambda t: completed.append(t.id))
        assert q._on_complete is not None

    def test_shutdown(self):
        q = self._make_queue()
        q.shutdown()
        assert q._started is False

    def test_default_affinity_map(self):
        from engine.lmstudio.task_queue import DEFAULT_AFFINITY, TaskType

        assert TaskType.CODE in DEFAULT_AFFINITY
        assert TaskType.VISION in DEFAULT_AFFINITY
        assert len(DEFAULT_AFFINITY[TaskType.CODE]) > 0

    def test_singleton(self):
        import engine.lmstudio.task_queue as mod
        mod._instance = None
        q1 = mod.get_task_queue(config=_mock_config())
        q2 = mod.get_task_queue()
        assert q1 is q2
        mod._instance = None


# ── Server Skills Tests ──────────────────────────────────────────────────

class TestLMStudioServerSkills:
    """Tests for engine.skills.builtin.lmstudio_server_skills."""

    @patch("engine.lmstudio.server_controller.get_server_controller")
    def test_lms_load_model(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_load_model
        from engine.lmstudio.server_controller import ModelInstance

        mock_ctrl = MagicMock()
        mock_ctrl.load_model.return_value = ModelInstance(
            model_key="qwen3-0.6b",
            context_length=4096,
            gpu_offload=0.9,
            stop_strings=["END"],
        )
        mock_get.return_value = mock_ctrl

        result = lms_load_model("qwen3-0.6b", stop_strings="END")
        assert "qwen3-0.6b" in result
        assert "loaded" in result.lower()

    @patch("engine.lmstudio.server_controller.get_server_controller")
    def test_lms_unload_model(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_unload_model

        mock_ctrl = MagicMock()
        mock_ctrl.unload_model.return_value = True
        mock_get.return_value = mock_ctrl

        result = lms_unload_model("test-model")
        assert "success" in result

    @patch("engine.lmstudio.server_controller.get_server_controller")
    def test_lms_server_health(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_server_health

        mock_ctrl = MagicMock()
        mock_ctrl.get_full_status.return_value = {"server": {"reachable": True}}
        mock_get.return_value = mock_ctrl

        result = lms_server_health()
        assert "reachable" in result

    @patch("engine.lmstudio.server_controller.get_server_controller")
    def test_lms_configure_model(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_configure_model
        from engine.lmstudio.server_controller import ModelInstance

        mock_ctrl = MagicMock()
        mock_ctrl.configure_inference.return_value = ModelInstance(
            model_key="m1",
            stop_strings=["STOP"],
            temperature=0.3,
            max_tokens=500,
        )
        mock_get.return_value = mock_ctrl

        result = lms_configure_model("m1", stop_strings="STOP", temperature=0.3)
        assert "configured" in result.lower()

    @patch("engine.lmstudio.server_controller.get_server_controller")
    def test_lms_create_agent_instance(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_create_agent_instance
        from engine.lmstudio.server_controller import ModelInstance

        mock_ctrl = MagicMock()
        mock_ctrl.create_agent_instance.return_value = ModelInstance(
            model_key="qwen3-0.6b",
            instance_id="aria_qwen3-0.6b",
            agent_id="aria",
            context_length=8192,
        )
        mock_get.return_value = mock_ctrl

        result = lms_create_agent_instance("aria", "qwen3-0.6b")
        assert "aria" in result
        assert "created" in result.lower()

    @patch("engine.lmstudio.server_controller.get_server_controller")
    def test_lms_count_tokens(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_count_tokens

        mock_ctrl = MagicMock()
        mock_ctrl.count_tokens.return_value = 42
        mock_get.return_value = mock_ctrl

        result = lms_count_tokens("Hello world")
        assert "42" in result

    @patch("engine.lmstudio.lmlink_manager.get_lmlink_manager")
    def test_lms_lmlink_status(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_lmlink_status

        mock_mgr = MagicMock()
        mock_mgr.get_status.return_value = {"enabled": True, "peers": {}}
        mock_get.return_value = mock_mgr

        result = lms_lmlink_status()
        assert "enabled" in result

    @patch("engine.lmstudio.task_queue.get_task_queue")
    def test_lms_queue_status(self, mock_get):
        from engine.skills.builtin.lmstudio_server_skills import lms_queue_status

        mock_q = MagicMock()
        mock_q.get_status.return_value = {"queue_depth": 0, "workers": 4}
        mock_get.return_value = mock_q

        result = lms_queue_status()
        assert "queue_depth" in result
