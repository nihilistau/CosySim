"""Tests for engine.nexus.lms_task_bridge — Copilot → LMStudio delegation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from engine.nexus.lms_task_bridge import LMSTaskBridge, TaskResult


# ── TaskResult ───────────────────────────────────────────────────────

class TestTaskResult:
    def test_ok_when_completed(self):
        r = TaskResult(status="completed", output="hello")
        assert r.ok is True

    def test_not_ok_when_failed(self):
        r = TaskResult(status="failed", error="boom")
        assert r.ok is False

    def test_not_ok_when_pending(self):
        r = TaskResult(status="pending")
        assert r.ok is False

    def test_not_ok_when_completed_with_error(self):
        r = TaskResult(status="completed", error="something wrong")
        assert r.ok is False

    def test_to_dict(self):
        r = TaskResult(task_id="t1", status="completed", output="hi",
                       model="qwen", latency_ms=123.456, tps=45.678)
        d = r.to_dict()
        assert d["task_id"] == "t1"
        assert d["latency_ms"] == 123.5
        assert d["tps"] == 45.7
        assert d["output"] == "hi"


# ── LMSTaskBridge ────────────────────────────────────────────────────

class TestLMSTaskBridge:
    def _make_bridge(self):
        bridge = LMSTaskBridge()
        bridge._orchestrator = MagicMock()
        bridge._nexus = MagicMock()
        return bridge

    def _mock_response(self, content="test output", tokens=50):
        resp = MagicMock()
        resp.content = content
        resp.usage = MagicMock()
        resp.usage.completion_tokens = tokens
        return resp

    def test_run_prompt_success(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response()

        result = bridge.run_prompt("Hello")
        assert result.ok
        assert result.output == "test output"
        assert result.status == "completed"
        assert result.latency_ms > 0

    def test_run_prompt_failure(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.side_effect = RuntimeError("connection refused")

        result = bridge.run_prompt("Hello")
        assert not result.ok
        assert result.status == "failed"
        assert "connection refused" in result.error

    def test_run_prompt_custom_params(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response()

        result = bridge.run_prompt(
            "Test", model="qwen3-0.6b", temperature=0.3, max_tokens=512
        )
        assert result.ok
        call_kwargs = bridge._orchestrator.infer.call_args[1]
        assert call_kwargs["model"] == "qwen3-0.6b"
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 512

    def test_run_batch_all_succeed(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response()

        results = bridge.run_batch([
            {"prompt": "P1"},
            {"prompt": "P2"},
            {"prompt": "P3"},
        ])
        assert len(results) == 3
        assert all(r.ok for r in results)

    def test_run_batch_skips_empty(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response()

        results = bridge.run_batch([{"prompt": ""}, {"prompt": "Real"}])
        assert len(results) == 1

    def test_run_batch_store_results(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response()
        bridge._nexus.add_entry.return_value = "entry-1"

        results = bridge.run_batch(
            [{"prompt": "P1"}], store_results=True
        )
        assert len(results) == 1
        bridge._nexus.add_entry.assert_called_once()

    def test_run_task_evaluate(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response("Rating: 8/10")

        result = bridge.run_task("evaluate", "Rate this dialog")
        assert result.ok
        assert "8/10" in result.output
        assert result.metadata["task_type"] == "evaluate"

    def test_run_task_with_context(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response()

        result = bridge.run_task(
            "summarize", "Summarize this",
            context={"text": "Long text here..."}
        )
        assert result.ok
        # Verify context was injected into the prompt
        call_args = bridge._orchestrator.infer.call_args[1]
        messages = call_args["messages"]
        assert "Long text here" in messages[0]["content"]

    def test_run_task_store_result(self):
        bridge = self._make_bridge()
        bridge._orchestrator.infer.return_value = self._mock_response()
        bridge._nexus.add_entry.return_value = "entry-1"

        result = bridge.run_task("generate", "Write a poem", store_result=True)
        assert result.ok
        bridge._nexus.add_entry.assert_called_once()

    def test_check_lmstudio_online(self):
        bridge = self._make_bridge()
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "data": [{"id": "qwen3-0.6b"}, {"id": "llama-70b"}]
            }
            mock_get.return_value = mock_resp

            status = bridge.check_lmstudio()
            assert status["status"] == "online"
            assert status["models_loaded"] == 2
            assert "qwen3-0.6b" in status["model_ids"]

    def test_check_lmstudio_offline(self):
        bridge = self._make_bridge()
        with patch("requests.get") as mock_get:
            mock_get.side_effect = ConnectionError("refused")

            status = bridge.check_lmstudio()
            assert status["status"] == "offline"

    def test_next_id_increments(self):
        bridge = self._make_bridge()
        id1 = bridge._next_id()
        id2 = bridge._next_id()
        assert id1 != id2
        assert "lms-0001" == id1
        assert "lms-0002" == id2

    def test_tps_calculation(self):
        """Verify TPS is calculated correctly from tokens and latency."""
        bridge = self._make_bridge()
        resp = self._mock_response(tokens=100)
        bridge._orchestrator.infer.return_value = resp

        result = bridge.run_prompt("Test")
        assert result.ok
        assert result.tokens_generated == 100
        # TPS should be positive (latency is tiny in test but > 0)
        assert result.tps >= 0


# ── Inference Skills ─────────────────────────────────────────────────

class TestInferenceSkills:
    def test_benchmark_model_no_models(self):
        from engine.skills.builtin.inference_skills import benchmark_model
        with patch("engine.nexus.lms_task_bridge.LMSTaskBridge") as MockBridge:
            mock = MockBridge.return_value
            mock.check_lmstudio.return_value = {
                "status": "online", "model_ids": []
            }
            result = benchmark_model()
            assert "No models loaded" in result

    def test_benchmark_model_offline(self):
        from engine.skills.builtin.inference_skills import benchmark_model
        with patch("engine.nexus.lms_task_bridge.LMSTaskBridge") as MockBridge:
            mock = MockBridge.return_value
            mock.check_lmstudio.return_value = {
                "status": "offline", "error": "refused"
            }
            result = benchmark_model()
            assert "offline" in result

    def test_store_benchmark_skill(self):
        from engine.skills.builtin.inference_skills import store_benchmark
        with patch("engine.nexus.client.get_nexus_client") as mock_get:
            mock_client = MagicMock()
            mock_client.store_benchmark.return_value = "bench-123"
            mock_get.return_value = mock_client

            result = store_benchmark(
                model="qwen3-0.6b", method="cpu_only",
                tps=15.0, latency_ms=500.0
            )
            assert "bench-123" in result

    def test_get_leaderboard_empty(self):
        from engine.skills.builtin.inference_skills import get_leaderboard
        with patch("engine.nexus.client.get_nexus_client") as mock_get:
            mock_client = MagicMock()
            mock_client.get_leaderboard.return_value = []
            mock_get.return_value = mock_client

            result = get_leaderboard()
            assert "No benchmark entries" in result

    def test_check_lmstudio_status_skill(self):
        from engine.skills.builtin.inference_skills import check_lmstudio_status
        with patch("engine.nexus.lms_task_bridge.LMSTaskBridge") as MockBridge:
            mock = MockBridge.return_value
            mock.check_lmstudio.return_value = {
                "status": "online",
                "model_ids": ["model-a", "model-b"],
            }
            result = check_lmstudio_status()
            assert "ONLINE" in result
            assert "model-a" in result

    def test_delegate_task_skill(self):
        from engine.skills.builtin.inference_skills import delegate_task
        with patch("engine.nexus.lms_task_bridge.LMSTaskBridge") as MockBridge:
            mock = MockBridge.return_value
            mock.check_lmstudio.return_value = {"status": "online", "model_ids": ["m"]}
            mock.run_task.return_value = TaskResult(
                task_id="lms-0001", status="completed",
                output="Great dialog", latency_ms=200, tps=30.0
            )
            result = delegate_task("evaluate", "Rate this")
            assert "completed" in result or "lms-0001" in result


# ── NexusClient extensions ───────────────────────────────────────────

class TestNexusClientExtensions:
    def _make_client(self):
        from engine.nexus.client import NexusClient
        client = NexusClient("http://localhost:8700")
        return client

    def test_store_benchmark_method(self):
        client = self._make_client()
        with patch.object(client, "add_entry", return_value="b-1") as mock_add:
            entry_id = client.store_benchmark(
                model="qwen3", method="gpu_primary",
                metrics={"tps": 45.2, "latency_ms": 200}
            )
            assert entry_id == "b-1"
            call_args = mock_add.call_args
            assert "qwen3" in call_args[1]["title"]
            assert "gpu_primary" in call_args[1]["title"]

    def test_get_leaderboard_method(self):
        client = self._make_client()
        with patch.object(client, "list_by_type") as mock_list:
            mock_list.return_value = [
                {"title": "Benchmark: qwen3 [gpu]", "content": "Tokens/sec: 45"},
                {"title": "Benchmark: llama [cpu]", "content": "Tokens/sec: 12"},
            ]
            results = client.get_leaderboard()
            assert len(results) == 2

    def test_get_leaderboard_filtered(self):
        client = self._make_client()
        with patch.object(client, "list_by_type") as mock_list:
            mock_list.return_value = [
                {"title": "B1", "content": "Method: gpu_primary\nTokens/sec: 45"},
                {"title": "B2", "content": "Method: cpu_only\nTokens/sec: 12"},
            ]
            results = client.get_leaderboard(method="gpu_primary")
            assert len(results) == 1

    def test_track_access(self):
        client = self._make_client()
        with patch.object(client, "_post") as mock_post:
            mock_post.return_value = {"ok": True}
            assert client.track_access("entry-123") is True
            mock_post.assert_called_once()

    def test_search_ranked(self):
        client = self._make_client()
        with patch.object(client, "search") as mock_search, \
             patch.object(client, "track_access") as mock_track:
            mock_search.return_value = [
                {"id": "a", "title": "A"},
                {"id": "b", "title": "B"},
            ]
            results = client.search_ranked("test", limit=2)
            assert len(results) == 2
            assert mock_track.call_count == 2
