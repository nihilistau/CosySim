"""Tests for the Fine-tuned LMStudio Router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.lmstudio.finetuned_router import FinetunedRouter, get_finetuned_router


@pytest.fixture
def router():
    return FinetunedRouter()


class TestFinetunedRouter:
    def test_register_and_is_available(self, router):
        assert not router.is_available("qa_evaluator")
        router.register_model("qa_evaluator", "/tmp/model/merged")
        assert router.is_available("qa_evaluator")

    def test_deregister_removes_model(self, router):
        router.register_model("router_v2", "/tmp/model")
        router.deregister_model("router_v2")
        assert not router.is_available("router_v2")

    def test_route_returns_none_when_unavailable(self, router):
        result = router.route("qa_evaluator", "How does Nexus work?")
        assert result is None

    def test_route_qa_evaluation_unavailable(self, router):
        result = router.route_qa_evaluation("Q?", "A.")
        assert result is None

    def test_route_request_classification_unavailable(self, router):
        result = router.route_request_classification("search for docs")
        assert result is None

    def test_route_calls_lmstudio_when_available(self, router):
        router.register_model("qa_evaluator", "test-model-path")
        with patch.object(router, "_call_lmstudio", return_value="ESSENTIAL") as mock_call:
            result = router.route("qa_evaluator", "How does Nexus work?")
        assert result == "ESSENTIAL"
        mock_call.assert_called_once()

    def test_route_returns_none_on_lmstudio_failure(self, router):
        router.register_model("qa_evaluator", "test-model")
        with patch.object(router, "_call_lmstudio", side_effect=ConnectionError("LMStudio down")):
            result = router.route("qa_evaluator", "question")
        assert result is None

    def test_get_active_models_empty(self, router):
        assert router.get_active_models() == {}

    def test_get_active_models_populated(self, router):
        router.register_model("qa_evaluator", "/tmp/qa")
        router.register_model("router_v2", "/tmp/router")
        active = router.get_active_models()
        assert active["qa_evaluator"] == "/tmp/qa"
        assert active["router_v2"] == "/tmp/router"

    def test_load_from_registry_no_models(self, router):
        with patch("training.model_registry.get_model_registry") as mock_reg:
            mock_reg.return_value.get_active.return_value = None
            count = router.load_from_registry()
        assert count == 0

    def test_load_from_registry_with_active_models(self, router):
        mock_model = MagicMock()
        mock_model.merged_path = "/tmp/merged"
        mock_model.adapter_path = "/tmp/adapter"

        with patch("training.model_registry.get_model_registry") as mock_reg:
            mock_reg.return_value.get_active.return_value = mock_model
            count = router.load_from_registry()
        assert count > 0  # at least some model types registered

    def test_singleton(self):
        r1 = get_finetuned_router()
        r2 = get_finetuned_router()
        assert r1 is r2
