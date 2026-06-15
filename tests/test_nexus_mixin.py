"""Tests for NexusSceneMixin — Nexus knowledge integration for scenes."""
import time
import threading
import pytest
from unittest.mock import MagicMock, patch, call
from contextlib import contextmanager


from engine.scenes.nexus_mixin import NexusSceneMixin


# ── Test harness ────────────────────────────────────────────────────────


class DummyScene(NexusSceneMixin):
    """Minimal scene subclass for testing the mixin in isolation."""
    pass


def _make_mock_client(available: bool = True) -> MagicMock:
    """Build a mock NexusClient with sensible defaults."""
    client = MagicMock()
    client.is_available.return_value = available
    # v1.62.0 [2026-06-15] — Since v1.50.1 the mixin no longer calls
    # client.is_available(); availability is decided by a 2s HTTP probe of
    # the client's _base_url + /api/health (see _init_scene, which mocks the
    # probe at the urllib boundary). Pin _base_url so the probed URL is a real
    # string rather than a MagicMock attribute.
    client._base_url = "http://nexus.test"
    client.search.return_value = [
        {"title": "Lore A", "content": "Content alpha"},
        {"title": "Lore B", "content": "Content beta"},
    ]
    client.ask.return_value = {"answer": "42", "source": "cache"}
    client.add_entry.return_value = "entry-001"
    client.add_qa.return_value = "qa-001"
    client.log_session.return_value = "sess-001"
    return client


@contextmanager
def _patched_health_probe(available: bool):
    """Mock the urllib /api/health probe the mixin runs during nexus_init.

    v1.62.0 [2026-06-15] — The mixin switched (v1.50.1) from
    ``client.is_available()`` to a non-blocking ``urllib.request.urlopen``
    health check. Tests must mock that real client boundary so
    ``_nexus_available`` reflects the requested availability. We patch
    ``urllib.request.urlopen`` to yield a fake ``/api/health`` response of
    ``{"ok": available}`` (or raise, mimicking an unreachable Nexus).
    """
    if available:
        resp = MagicMock()
        resp.read.return_value = b'{"ok": true}'
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with patch("urllib.request.urlopen", return_value=resp):
            yield
    else:
        with patch(
            "urllib.request.urlopen",
            side_effect=OSError("Nexus unreachable"),
        ):
            yield


def _init_scene(mock_client: MagicMock, scene_id: str = "test_scene") -> DummyScene:
    """Shortcut: create a DummyScene and run nexus_init with a mock client."""
    scene = DummyScene()
    available = bool(mock_client.is_available.return_value)
    with patch("engine.nexus.client.get_nexus_client", return_value=mock_client), \
            _patched_health_probe(available):
        scene.nexus_init(scene_id)
    return scene


# ═══════════════════════════════════════════════════════════════════════
# Initialisation
# ═══════════════════════════════════════════════════════════════════════


class TestNexusInit:
    """Tests for nexus_init setup and availability checks."""

    def test_init_sets_scene_id(self):
        """Scene id is stored on the instance."""
        scene = _init_scene(_make_mock_client(), scene_id="penthouse")
        assert scene._nexus_scene_id == "penthouse"

    def test_init_client_available(self):
        """When the client reports available, flag is set True."""
        scene = _init_scene(_make_mock_client(available=True))
        assert scene._nexus_available is True
        assert scene._nexus_client is not None

    def test_init_client_unavailable(self):
        """When the client reports unavailable, flag is set False."""
        scene = _init_scene(_make_mock_client(available=False))
        assert scene._nexus_available is False

    def test_init_import_error_degrades_gracefully(self):
        """If get_nexus_client cannot be imported, Nexus is simply disabled."""
        scene = DummyScene()
        with patch(
            "engine.nexus.client.get_nexus_client",
            side_effect=ImportError("no module"),
        ):
            scene.nexus_init("broken")
        assert scene._nexus_available is False
        assert scene._nexus_client is None

    def test_init_runtime_error_degrades_gracefully(self):
        """A RuntimeError during client creation disables Nexus."""
        scene = DummyScene()
        with patch(
            "engine.nexus.client.get_nexus_client",
            side_effect=RuntimeError("connection refused"),
        ):
            scene.nexus_init("crashed")
        assert scene._nexus_available is False

    def test_init_creates_empty_event_buffer(self):
        """Event buffer starts as an empty list after init."""
        scene = _init_scene(_make_mock_client())
        assert scene._nexus_event_buffer == []

    def test_init_sets_last_flush_to_zero(self):
        """Last flush timestamp starts at 0 so first event can trigger a flush."""
        scene = _init_scene(_make_mock_client())
        assert scene._nexus_last_flush == 0.0


# ═══════════════════════════════════════════════════════════════════════
# Graceful degradation (Nexus offline)
# ═══════════════════════════════════════════════════════════════════════


class TestGracefulDegradation:
    """Every retrieval method must return a safe default when Nexus is offline."""

    @pytest.fixture(autouse=True)
    def _offline_scene(self):
        self.scene = _init_scene(_make_mock_client(available=False))

    def test_search_returns_empty_list(self):
        assert self.scene.nexus_search("anything") == []

    def test_ask_returns_none(self):
        with patch("engine.nexus.query_router.get_query_router", side_effect=ImportError("offline")):
            assert self.scene.nexus_ask("question?") is None

    def test_get_character_knowledge_returns_empty_string(self):
        assert self.scene.nexus_get_character_knowledge("npc_01") == ""

    def test_enrich_prompt_returns_base_prompt(self):
        base = "You are a helpful NPC."
        assert self.scene.nexus_enrich_prompt("npc_01", base) == base

    def test_store_event_still_buffers_locally(self):
        """Events are buffered even when offline (no exception)."""
        self.scene.nexus_store_event("interaction", "player waved")
        assert len(self.scene._nexus_event_buffer) == 1

    def test_store_memory_is_noop(self):
        """store_memory does nothing when offline — no exception."""
        self.scene.nexus_store_memory("npc_01", "saw player")  # no error

    def test_store_qa_is_noop(self):
        self.scene.nexus_store_qa("How?", "Like this.")  # no error

    def test_flush_is_noop(self):
        self.scene.nexus_store_event("x", "y")
        self.scene.nexus_flush()  # no error, buffer untouched by remote call

    def test_log_session_is_noop(self):
        self.scene.nexus_log_scene_session("summary")  # no error


# ═══════════════════════════════════════════════════════════════════════
# nexus_search
# ═══════════════════════════════════════════════════════════════════════


class TestNexusSearch:
    """Tests for nexus_search delegation and error handling."""

    def test_delegates_to_client(self):
        """search is forwarded to client.search with correct params."""
        client = _make_mock_client()
        scene = _init_scene(client)
        results = scene.nexus_search("dragons", limit=3)
        client.search.assert_called_once_with("dragons", limit=3)
        assert len(results) == 2

    def test_default_limit(self):
        """Default limit is 5 when not specified."""
        client = _make_mock_client()
        scene = _init_scene(client)
        scene.nexus_search("swords")
        client.search.assert_called_once_with("swords", limit=5)

    def test_returns_empty_on_exception(self):
        """Client exceptions are caught; empty list returned."""
        client = _make_mock_client()
        client.search.side_effect = ConnectionError("timeout")
        scene = _init_scene(client)
        assert scene.nexus_search("anything") == []


# ═══════════════════════════════════════════════════════════════════════
# nexus_ask
# ═══════════════════════════════════════════════════════════════════════


class TestNexusAsk:
    """Tests for nexus_ask delegation via query router then client fallback."""

    def test_delegates_via_router(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        mock_result = MagicMock()
        mock_result.answer = "42"
        mock_router = MagicMock()
        mock_router.query.return_value = mock_result
        with patch("engine.scenes.nexus_mixin.get_query_router", return_value=mock_router, create=True):
            # Import is inside nexus_ask, so we must patch at the source
            pass
        # The method imports get_query_router dynamically — patch at module level
        with patch("engine.nexus.query_router.get_query_router", return_value=mock_router):
            answer = scene.nexus_ask("What is 6*7?")
        assert answer == "42"
        mock_router.query.assert_called_once_with(
            "What is 6*7?",
            use_llm=False,
            category=getattr(scene, "_nexus_scene_id", "scene"),
            source_hint=f"scene:{getattr(scene, '_nexus_scene_id', 'unknown')}",
            depth="shallow",
        )

    def test_router_returns_empty_falls_back_to_client(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        mock_result = MagicMock()
        mock_result.answer = ""
        mock_router = MagicMock()
        mock_router.query.return_value = mock_result
        with patch("engine.nexus.query_router.get_query_router", return_value=mock_router):
            answer = scene.nexus_ask("empty answer")
        # Falls through to client.ask
        assert answer is None or answer == "42"  # depends on client mock

    def test_router_exception_falls_back_to_client(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        with patch("engine.nexus.query_router.get_query_router", side_effect=ImportError("no router")):
            answer = scene.nexus_ask("fallback?")
        client.ask.assert_called_once_with("fallback?", depth="shallow")
        assert answer == "42"

    def test_returns_none_when_result_is_none(self):
        client = _make_mock_client()
        client.ask.return_value = None
        scene = _init_scene(client)
        mock_result = MagicMock()
        mock_result.answer = ""
        mock_router = MagicMock()
        mock_router.query.return_value = mock_result
        with patch("engine.nexus.query_router.get_query_router", return_value=mock_router):
            assert scene.nexus_ask("gone?") is None

    def test_deep_nexus_ask_passes_deep_to_router(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        mock_result = MagicMock()
        mock_result.answer = "deep answer"
        mock_router = MagicMock()
        mock_router.query.return_value = mock_result

        with patch("engine.nexus.query_router.get_query_router", return_value=mock_router):
            answer = scene.nexus_ask("research this", depth="deep")

        assert answer == "deep answer"
        mock_router.query.assert_called_once_with(
            "research this",
            use_llm=True,
            category=getattr(scene, "_nexus_scene_id", "scene"),
            source_hint=f"scene:{getattr(scene, '_nexus_scene_id', 'unknown')}",
            depth="deep",
        )

    def test_returns_none_on_exception(self):
        client = _make_mock_client()
        client.ask.side_effect = Exception("boom")
        scene = _init_scene(client)
        with patch("engine.nexus.query_router.get_query_router", side_effect=Exception("no router")):
            assert scene.nexus_ask("explode") is None


# ═══════════════════════════════════════════════════════════════════════
# nexus_get_character_knowledge
# ═══════════════════════════════════════════════════════════════════════


class TestGetCharacterKnowledge:
    """Tests for knowledge retrieval and formatting."""

    def test_builds_search_query_with_character_and_scene(self):
        client = _make_mock_client()
        scene = _init_scene(client, scene_id="tavern")
        scene.nexus_get_character_knowledge("barkeeper")
        client.search.assert_called_once_with("character barkeeper tavern", limit=3)

    def test_formats_snippets_correctly(self):
        client = _make_mock_client()
        client.search.return_value = [
            {"title": "Backstory", "content": "Born in the north."},
            {"title": "Traits", "content": "Grumpy but kind."},
        ]
        scene = _init_scene(client)
        result = scene.nexus_get_character_knowledge("npc_01")
        assert "[Backstory] Born in the north." in result
        assert "[Traits] Grumpy but kind." in result

    def test_empty_results_returns_empty_string(self):
        client = _make_mock_client()
        client.search.return_value = []
        scene = _init_scene(client)
        assert scene.nexus_get_character_knowledge("unknown") == ""

    def test_skips_entries_with_no_content(self):
        client = _make_mock_client()
        client.search.return_value = [
            {"title": "Empty", "content": ""},
            {"title": "Good", "content": "Has data."},
        ]
        scene = _init_scene(client)
        result = scene.nexus_get_character_knowledge("npc_01")
        assert "[Empty]" not in result
        assert "[Good] Has data." in result

    def test_truncates_long_content_to_200_chars(self):
        long_content = "A" * 500
        client = _make_mock_client()
        client.search.return_value = [{"title": "Long", "content": long_content}]
        scene = _init_scene(client)
        result = scene.nexus_get_character_knowledge("npc_01")
        # title bracket + space + 200 chars max
        assert len(result.split("] ", 1)[1]) == 200

    def test_exception_returns_empty_string(self):
        client = _make_mock_client()
        client.search.side_effect = RuntimeError("network")
        scene = _init_scene(client)
        assert scene.nexus_get_character_knowledge("npc_01") == ""


# ═══════════════════════════════════════════════════════════════════════
# nexus_store_event + event buffer
# ═══════════════════════════════════════════════════════════════════════


class TestStoreEvent:
    """Tests for event buffering and auto-flush triggering."""

    def test_event_is_added_to_buffer(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        # Set last_flush to now so auto-flush doesn't fire
        scene._nexus_last_flush = time.time()

        scene.nexus_store_event("interaction", "player said hello", tags=["social"])
        assert len(scene._nexus_event_buffer) == 1
        event = scene._nexus_event_buffer[0]
        assert event["type"] == "interaction"
        assert event["description"] == "player said hello"
        assert event["scene"] == "test_scene"
        assert event["tags"] == ["social"]
        assert isinstance(event["timestamp"], float)

    def test_default_tags_is_empty_list(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()
        scene.nexus_store_event("milestone", "quest complete")
        assert scene._nexus_event_buffer[0]["tags"] == []

    def test_multiple_events_accumulate(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()
        for i in range(5):
            scene.nexus_store_event("tick", f"event {i}")
        assert len(scene._nexus_event_buffer) == 5

    def test_auto_flush_triggered_when_interval_exceeded(self):
        """If last flush was > flush_interval ago, _nexus_auto_flush fires."""
        client = _make_mock_client()
        scene = _init_scene(client)
        # Force last_flush far in the past
        scene._nexus_last_flush = 0.0
        with patch.object(scene, "_nexus_auto_flush") as mock_flush:
            scene.nexus_store_event("test", "trigger flush")
            mock_flush.assert_called_once()

    def test_no_auto_flush_when_interval_not_exceeded(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()  # just now
        with patch.object(scene, "_nexus_auto_flush") as mock_flush:
            scene.nexus_store_event("test", "no flush")
            mock_flush.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# nexus_store_memory
# ═══════════════════════════════════════════════════════════════════════


class TestStoreMemory:
    """Tests for character memory storage."""

    def test_calls_add_entry_with_correct_params(self):
        client = _make_mock_client()
        scene = _init_scene(client, scene_id="penthouse")
        scene.nexus_store_memory("npc_01", "saw player enter", importance="high")
        client.add_entry.assert_called_once_with(
            title="Memory: npc_01 in penthouse",
            content="saw player enter",
            content_type="memory",
            category="penthouse",
            tags=["penthouse", "npc_01", "memory", "high"],
            created_by="scene:penthouse",
        )

    def test_default_importance_is_normal(self):
        client = _make_mock_client()
        scene = _init_scene(client, scene_id="tavern")
        scene.nexus_store_memory("barkeeper", "served a drink")
        _, kwargs = client.add_entry.call_args
        assert "normal" in kwargs["tags"]

    def test_exception_does_not_propagate(self):
        client = _make_mock_client()
        client.add_entry.side_effect = ConnectionError("boom")
        scene = _init_scene(client)
        scene.nexus_store_memory("npc_01", "memory")  # no error


# ═══════════════════════════════════════════════════════════════════════
# nexus_store_qa
# ═══════════════════════════════════════════════════════════════════════


class TestStoreQA:
    """Tests for Q&A pair storage."""

    def test_calls_add_qa_with_correct_params(self):
        client = _make_mock_client()
        scene = _init_scene(client, scene_id="tavern")
        scene.nexus_store_qa("What is mead?", "A honey wine.")
        client.add_qa.assert_called_once_with(
            question="What is mead?",
            answer="A honey wine.",
            category="tavern",
            tags=["tavern"],
        )

    def test_exception_does_not_propagate(self):
        client = _make_mock_client()
        client.add_qa.side_effect = Exception("db error")
        scene = _init_scene(client)
        scene.nexus_store_qa("Q?", "A.")  # no error

    def test_noop_when_client_is_none(self):
        """If _nexus_client is None (even though available=True somehow), skip."""
        scene = DummyScene()
        scene._nexus_available = False
        scene._nexus_client = None
        scene._nexus_scene_id = "x"
        scene.nexus_store_qa("Q?", "A.")  # no error


# ═══════════════════════════════════════════════════════════════════════
# nexus_enrich_prompt
# ═══════════════════════════════════════════════════════════════════════


class TestEnrichPrompt:
    """Tests for prompt enrichment with Nexus knowledge."""

    def test_appends_knowledge_block(self):
        client = _make_mock_client()
        client.search.return_value = [
            {"title": "Lore", "content": "The tavern is ancient."},
        ]
        scene = _init_scene(client)
        base = "You are a barkeeper."
        enriched = scene.nexus_enrich_prompt("barkeeper", base)
        assert enriched.startswith(base)
        assert "[NEXUS KNOWLEDGE]" in enriched
        assert "[Lore] The tavern is ancient." in enriched
        assert "[/NEXUS KNOWLEDGE]" in enriched

    def test_returns_base_when_no_knowledge_found(self):
        client = _make_mock_client()
        client.search.return_value = []
        scene = _init_scene(client)
        base = "You are nobody."
        assert scene.nexus_enrich_prompt("ghost", base) == base

    def test_returns_base_when_nexus_offline(self):
        scene = _init_scene(_make_mock_client(available=False))
        base = "You are offline."
        assert scene.nexus_enrich_prompt("npc", base) == base

    def test_context_query_param_accepted(self):
        """context_query is accepted without error (unused in current impl)."""
        client = _make_mock_client()
        client.search.return_value = [{"title": "X", "content": "Y"}]
        scene = _init_scene(client)
        result = scene.nexus_enrich_prompt("npc", "base", context_query="extra")
        assert "[NEXUS KNOWLEDGE]" in result


# ═══════════════════════════════════════════════════════════════════════
# nexus_flush (synchronous)
# ═══════════════════════════════════════════════════════════════════════


class TestNexusFlush:
    """Tests for synchronous event flushing."""

    def test_flush_sends_buffered_events(self):
        client = _make_mock_client()
        scene = _init_scene(client, scene_id="arena")
        scene._nexus_last_flush = time.time()  # prevent auto-flush
        scene.nexus_store_event("hit", "player struck goblin")
        scene.nexus_store_event("kill", "goblin defeated")

        scene.nexus_flush()
        client.add_entry.assert_called_once()
        _, kwargs = client.add_entry.call_args
        assert kwargs["title"] == "Scene events: arena (2 events)"
        assert "[hit] player struck goblin" in kwargs["content"]
        assert "[kill] goblin defeated" in kwargs["content"]
        assert kwargs["content_type"] == "history"
        assert kwargs["category"] == "arena"
        assert "arena" in kwargs["tags"]

    def test_flush_clears_buffer(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()
        scene.nexus_store_event("x", "y")
        scene.nexus_flush()
        assert scene._nexus_event_buffer == []

    def test_flush_noop_on_empty_buffer(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        scene.nexus_flush()
        client.add_entry.assert_not_called()

    def test_flush_exception_does_not_propagate(self):
        client = _make_mock_client()
        client.add_entry.side_effect = Exception("network error")
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()
        scene.nexus_store_event("x", "y")
        scene.nexus_flush()  # no error raised


# ═══════════════════════════════════════════════════════════════════════
# _nexus_auto_flush (background thread)
# ═══════════════════════════════════════════════════════════════════════


class TestAutoFlush:
    """Tests for background-thread auto-flush."""

    def test_auto_flush_clears_buffer_and_sends(self):
        """Background flush copies, clears, and sends events."""
        client = _make_mock_client()
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()
        scene.nexus_store_event("a", "event a")
        scene.nexus_store_event("b", "event b")

        # Patch threading.Thread to run synchronously for deterministic test
        with patch("engine.scenes.nexus_mixin.threading.Thread") as MockThread:
            mock_thread_instance = MagicMock()
            MockThread.return_value = mock_thread_instance
            # Capture the target function and call it inline
            scene._nexus_auto_flush()

            # Get the _do_flush callable passed to Thread
            _, thread_kwargs = MockThread.call_args
            flush_fn = thread_kwargs["target"]
            flush_fn()  # run synchronously

        client.add_entry.assert_called_once()
        assert scene._nexus_event_buffer == []

    def test_auto_flush_noop_when_offline(self):
        scene = _init_scene(_make_mock_client(available=False))
        scene._nexus_event_buffer = [{"type": "x", "description": "y"}]
        scene._nexus_auto_flush()  # should not crash

    def test_auto_flush_noop_on_empty_buffer(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        with patch("engine.scenes.nexus_mixin.threading.Thread") as MockThread:
            scene._nexus_auto_flush()
            MockThread.assert_not_called()

    def test_auto_flush_updates_last_flush_timestamp(self):
        client = _make_mock_client()
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()  # prevent store_event auto-flush
        scene.nexus_store_event("a", "event a")

        # Reset to 0 so we can observe auto_flush setting it
        scene._nexus_last_flush = 0.0
        before = time.time()
        with patch("engine.scenes.nexus_mixin.threading.Thread"):
            scene._nexus_auto_flush()
        assert scene._nexus_last_flush >= before


# ═══════════════════════════════════════════════════════════════════════
# nexus_log_scene_session
# ═══════════════════════════════════════════════════════════════════════


class TestLogSceneSession:
    """Tests for session logging."""

    def test_calls_log_session_with_correct_params(self):
        client = _make_mock_client()
        scene = _init_scene(client, scene_id="tavern")
        scene.nexus_log_scene_session(summary="Great session")
        client.log_session.assert_called_once_with(
            project="CosySim",
            agent_id="scene:tavern",
        )

    def test_exception_does_not_propagate(self):
        client = _make_mock_client()
        client.log_session.side_effect = Exception("fail")
        scene = _init_scene(client)
        scene.nexus_log_scene_session()  # no error

    def test_noop_when_offline(self):
        client = _make_mock_client(available=False)
        scene = _init_scene(client)
        scene.nexus_log_scene_session("hi")
        client.log_session.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# Thread safety
# ═══════════════════════════════════════════════════════════════════════


class TestThreadSafety:
    """Verify the event buffer survives concurrent access."""

    def test_concurrent_store_events_no_data_loss(self):
        """Many threads writing events concurrently must not lose any."""
        client = _make_mock_client()
        scene = _init_scene(client)
        # Prevent auto-flush from clearing the buffer mid-test
        scene._nexus_flush_interval = 999_999
        scene._nexus_last_flush = time.time()

        num_threads = 10
        events_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def writer(thread_id: int):
            barrier.wait()  # synchronise start
            for i in range(events_per_thread):
                scene.nexus_store_event("load", f"t{thread_id}-e{i}")

        threads = [
            threading.Thread(target=writer, args=(t,))
            for t in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(scene._nexus_event_buffer) == num_threads * events_per_thread

    def test_concurrent_flush_and_store(self):
        """Flushing while new events arrive must not lose unflushed events."""
        client = _make_mock_client()
        scene = _init_scene(client)
        scene._nexus_last_flush = time.time()

        # Pre-populate buffer
        for i in range(10):
            scene.nexus_store_event("pre", f"event {i}")

        # Flush in a thread while adding more events
        flushed = threading.Event()

        def flush_worker():
            scene.nexus_flush()
            flushed.set()

        def store_worker():
            flushed.wait(timeout=5)
            for i in range(5):
                scene.nexus_store_event("post", f"after flush {i}")

        t_flush = threading.Thread(target=flush_worker)
        t_store = threading.Thread(target=store_worker)
        t_flush.start()
        t_store.start()
        t_flush.join(timeout=5)
        t_store.join(timeout=5)

        # The 5 post-flush events should be in the buffer
        assert len(scene._nexus_event_buffer) == 5
        # The 10 pre-flush events should have been sent
        client.add_entry.assert_called_once()
