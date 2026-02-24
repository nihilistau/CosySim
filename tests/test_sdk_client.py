"""Tests for engine.lmstudio.sdk_client — SDKClient wrapper.

All tests mock the ``lmstudio`` SDK so they run offline without a running
LMStudio server.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── Fake SDK objects ─────────────────────────────────────────────────

@dataclass
class FakePredictionStats:
    stop_reason: str = "stop"
    prompt_tokens_count: int = 20
    predicted_tokens_count: int = 50
    total_tokens_count: int = 70
    tokens_per_second: float = 25.0
    time_to_first_token_sec: float = 0.1
    accepted_draft_tokens_count: int = 0
    rejected_draft_tokens_count: int = 0


@dataclass
class FakeModelInfo:
    display_name: str = "test-model"


@dataclass
class FakePredictionResult:
    content: str = "Hello from SDK!"
    stats: FakePredictionStats = field(default_factory=FakePredictionStats)
    model_info: FakeModelInfo = field(default_factory=FakeModelInfo)
    reasoning_content: str = ""


class FakePredictionStream:
    """Mimics lms.PredictionStream iteration."""
    def __init__(self, fragments: List[str], result: FakePredictionResult = None):
        self._fragments = fragments
        self._result_obj = result or FakePredictionResult(content="".join(fragments))

    def __iter__(self):
        for frag in self._fragments:
            yield type("Fragment", (), {"content": frag})()

    def result(self):
        return self._result_obj


@dataclass
class FakeActRound:
    content: str = "Act result"


@dataclass
class FakeActResult:
    rounds: list = field(default_factory=lambda: [FakeActRound()])
    total_time_seconds: float = 1.5


class FakeLLMHandle:
    """Mimics an lms.LLM model handle."""
    def __init__(self, model_key="test-model"):
        self._model_key = model_key

    def respond(self, chat, **kwargs):
        return FakePredictionResult()

    def respond_stream(self, chat, **kwargs):
        return FakePredictionStream(["Hello", " from", " SDK!"])

    def act(self, chat, tools, **kwargs):
        return FakeActResult()

    def complete(self, prompt, **kwargs):
        return FakePredictionResult(content=f"Completed: {prompt[:20]}")

    def get_info(self):
        return FakeModelInfo()

    def get_context_length(self):
        return 4096

    def count_tokens(self, text):
        return len(text.split())

    def unload(self):
        pass

    def load_new_instance(self, **kwargs):
        return FakeLLMHandle(f"{self._model_key}-instance")


class FakeEmbeddingModel:
    def embed(self, text):
        return [0.1, 0.2, 0.3] * 10  # 30-dim fake embedding


class FakeLLMNamespace:
    def model(self, key=None):
        return FakeLLMHandle(key or "default-model")


class FakeEmbeddingNamespace:
    def model(self, key=None):
        return FakeEmbeddingModel()


class FakeClient:
    def __init__(self, api_host=None):
        self.llm = FakeLLMNamespace()
        self.embedding = FakeEmbeddingNamespace()

    def list_loaded_models(self):
        return [type("M", (), {"type": "llm", "__str__": lambda s: "test-model"})()]

    def list_downloaded_models(self):
        return [type("M", (), {"__str__": lambda s: "test-model"})()]

    def close(self):
        pass


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global SDK client singleton between tests."""
    import engine.lmstudio.sdk_client as mod
    mod._sdk_client = None
    yield
    mod._sdk_client = None


@pytest.fixture
def sdk_client():
    """Return an SDKClient with a mocked lms.Client."""
    with patch("engine.lmstudio.sdk_client.lms") as mock_lms:
        mock_lms.Client = FakeClient
        mock_lms.Chat = MagicMock()
        # Make Chat() behave like a real object with methods
        chat_instance = MagicMock()
        mock_lms.Chat.return_value = chat_instance

        from engine.lmstudio.sdk_client import SDKClient
        client = SDKClient.__new__(SDKClient)
        client._api_host = None
        client._client = FakeClient()
        client._lock = threading.Lock()
        client._model_handles = {}
        yield client


# ── Tests: Connection lifecycle ──────────────────────────────────────

class TestConnection:
    def test_ensure_connected_creates_client(self, sdk_client):
        assert sdk_client.connected

    def test_close_clears_state(self, sdk_client):
        sdk_client.get_model("test-model")
        assert len(sdk_client._model_handles) > 0
        sdk_client.close()
        assert not sdk_client.connected
        assert len(sdk_client._model_handles) == 0

    def test_connected_property(self, sdk_client):
        assert sdk_client.connected
        sdk_client._client = None
        assert not sdk_client.connected


# ── Tests: Model handle management ───────────────────────────────────

class TestModelHandles:
    def test_get_model_caches(self, sdk_client):
        h1 = sdk_client.get_model("test-model")
        h2 = sdk_client.get_model("test-model")
        assert h1 is h2

    def test_get_default_model(self, sdk_client):
        h = sdk_client.get_model(None)
        assert h is not None

    def test_list_loaded(self, sdk_client):
        models = sdk_client.list_loaded()
        assert len(models) == 1
        assert models[0]["model_key"] == "test-model"

    def test_list_downloaded(self, sdk_client):
        models = sdk_client.list_downloaded()
        assert len(models) == 1

    def test_unload_model(self, sdk_client):
        sdk_client.get_model("test-model")
        assert "test-model" in sdk_client._model_handles
        sdk_client.unload_model("test-model")
        assert "test-model" not in sdk_client._model_handles


# ── Tests: respond() ─────────────────────────────────────────────────

class TestRespond:
    def test_respond_string(self, sdk_client):
        resp = sdk_client.respond("Hello!")
        assert resp.content == "Hello from SDK!"
        assert resp.latency_ms > 0
        assert resp.output_tokens == 50
        assert resp.server_tps == 25.0

    def test_respond_messages(self, sdk_client):
        with patch("engine.lmstudio.sdk_client.lms") as mock_lms:
            mock_lms.Chat = MagicMock
            resp = sdk_client.respond([
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello!"},
            ])
            assert resp.content == "Hello from SDK!"

    def test_respond_with_config(self, sdk_client):
        from engine.lmstudio.inference_config import InferenceConfig
        cfg = InferenceConfig(temperature=0.5, max_output_tokens=100)
        resp = sdk_client.respond("Test", config=cfg)
        assert resp.content == "Hello from SDK!"

    def test_respond_error_returns_error_response(self, sdk_client):
        # Make the underlying respond() raise instead of get_model()
        broken_handle = MagicMock()
        broken_handle.respond.side_effect = RuntimeError("Inference failed")
        sdk_client._model_handles["__default__"] = broken_handle
        resp = sdk_client.respond("Hello!")
        assert "[SDK Error]" in resp.content


# ── Tests: respond_stream() ──────────────────────────────────────────

class TestRespondStream:
    def test_stream_yields_events(self, sdk_client):
        events = list(sdk_client.respond_stream("Hello!"))
        types = [e.event_type for e in events]
        assert types[0] == "chat.start"
        assert "message.delta" in types
        assert types[-1] == "chat.end"

    def test_stream_content(self, sdk_client):
        events = list(sdk_client.respond_stream("Hello!"))
        deltas = [e.content for e in events if e.event_type == "message.delta"]
        assert "".join(deltas) == "Hello from SDK!"

    def test_stream_end_has_stats(self, sdk_client):
        events = list(sdk_client.respond_stream("Hello!"))
        end_event = [e for e in events if e.event_type == "chat.end"][0]
        assert end_event.is_done
        assert end_event.stats is not None
        assert end_event.stats["tokens_per_second"] == 25.0


# ── Tests: act() ─────────────────────────────────────────────────────

class TestAct:
    def test_act_basic(self, sdk_client):
        def dummy_tool(x: str) -> str:
            return f"result: {x}"

        resp = sdk_client.act("Use the tool", tools=[dummy_tool])
        assert resp.content == "Act result"
        assert resp.latency_ms > 0

    def test_act_with_max_rounds(self, sdk_client):
        def tool_a() -> str:
            return "done"

        resp = sdk_client.act("Test", tools=[tool_a], max_rounds=3)
        assert resp.content == "Act result"

    def test_act_unwraps_toolspec(self, sdk_client):
        """Tools with a .fn attribute get unwrapped."""
        tool_with_fn = MagicMock()
        tool_with_fn.fn = lambda: "result"
        resp = sdk_client.act("Test", tools=[tool_with_fn])
        assert resp.content == "Act result"


# ── Tests: complete() ────────────────────────────────────────────────

class TestComplete:
    def test_complete_basic(self, sdk_client):
        resp = sdk_client.complete("Once upon a time")
        assert "Completed:" in resp.content


# ── Tests: embed() ───────────────────────────────────────────────────

class TestEmbed:
    def test_embed_single(self, sdk_client):
        vec = sdk_client.embed("Hello world")
        assert isinstance(vec, list)
        assert len(vec) == 30

    def test_embed_batch(self, sdk_client):
        vecs = sdk_client.embed(["Hello", "World"])
        assert len(vecs) == 2
        assert all(isinstance(v, list) for v in vecs)


# ── Tests: config translation ────────────────────────────────────────

class TestConfigTranslation:
    def test_inference_config_to_sdk(self):
        from engine.lmstudio.inference_config import InferenceConfig
        from engine.lmstudio.sdk_client import SDKClient

        cfg = InferenceConfig(
            temperature=0.7,
            top_p=0.9,
            top_k=40,
            min_p=0.05,
            repeat_penalty=1.1,
            max_output_tokens=2000,
            stop_strings=["<|end|>"],
            draft_model="gemma-270m",
        )
        d = SDKClient.inference_config_to_sdk(cfg)
        assert d["temperature"] == 0.7
        assert d["top_p_sampling"] == 0.9
        assert d["top_k_sampling"] == 40
        assert d["min_p_sampling"] == 0.05
        assert d["repeat_penalty"] == 1.1
        assert d["max_tokens"] == 2000
        assert d["stop_strings"] == ["<|end|>"]
        assert d["draft_model"] == "gemma-270m"

    def test_inference_config_to_sdk_empty(self):
        from engine.lmstudio.inference_config import InferenceConfig
        from engine.lmstudio.sdk_client import SDKClient

        cfg = InferenceConfig()
        d = SDKClient.inference_config_to_sdk(cfg)
        assert d == {}

    def test_to_sdk_config_method(self):
        """Test the to_sdk_config() method on InferenceConfig itself."""
        from engine.lmstudio.inference_config import InferenceConfig

        cfg = InferenceConfig(temperature=0.5, top_p=0.8, max_output_tokens=500)
        d = cfg.to_sdk_config()
        assert d["temperature"] == 0.5
        assert d["top_p_sampling"] == 0.8
        assert d["max_tokens"] == 500


# ── Tests: model info ────────────────────────────────────────────────

class TestModelInfo:
    def test_get_model_info(self, sdk_client):
        info = sdk_client.get_model_info("test-model")
        assert "context_length" in info

    def test_count_tokens(self, sdk_client):
        count = sdk_client.count_tokens("Hello world test")
        assert count == 3  # "Hello", "world", "test"


# ── Tests: singleton ─────────────────────────────────────────────────

class TestSingleton:
    def test_get_sdk_client_returns_none_without_sdk(self):
        with patch("engine.lmstudio.sdk_client.SDK_AVAILABLE", False):
            from engine.lmstudio.sdk_client import get_sdk_client
            assert get_sdk_client() is None

    def test_get_sdk_client_returns_instance(self):
        with patch("engine.lmstudio.sdk_client.SDK_AVAILABLE", True), \
             patch("engine.lmstudio.sdk_client.SDKClient") as MockSDK:
            MockSDK.return_value = MagicMock()
            import engine.lmstudio.sdk_client as mod
            mod._sdk_client = None
            result = mod.get_sdk_client()
            assert result is not None
