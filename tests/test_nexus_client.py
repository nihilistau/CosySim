"""Tests for engine.nexus.client — NexusClient HTTP client.

Covers constructor, singleton, health/status, search, CRUD, Q&A,
sessions, batch operations, error handling, retry logic, and the
governance actor-resolution helper.

All HTTP calls are mocked via ``unittest.mock.patch`` to avoid hitting
a real Nexus server.
"""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.client import NexusClient, get_nexus_client


# ─── Helpers ─────────────────────────────────────────────────────


def _mock_urlopen_response(data: dict, status: int = 200):
    """Create a mock urllib response that works as a context manager."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _ok(data=None):
    """Shortcut for a successful Nexus API response dict."""
    return {"ok": True, "data": data if data is not None else {}}


def _err(msg: str = "server error"):
    """Shortcut for a failed Nexus API response dict."""
    return {"ok": False, "error": msg}


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    import engine.nexus.client as mod

    mod._client = None
    yield
    mod._client = None


@pytest.fixture
def client():
    """Fresh NexusClient with short timeout for testing."""
    return NexusClient(
        base_url="http://localhost:8700",
        timeout=5,
        max_retries=2,
    )


# ─── Constructor & Singleton ─────────────────────────────────────


class TestConstructorAndSingleton:
    """Tests for NexusClient constructor and get_nexus_client singleton."""

    def test_constructor_sets_defaults(self):
        """Default constructor should set expected base_url, timeout, retries."""
        c = NexusClient(base_url="http://test:9000")

        assert c._base_url == "http://test:9000"
        assert c._timeout == 30
        assert c._max_retries == 2
        assert c._cache == {}
        assert c._cache_ttl == 60

    def test_constructor_strips_trailing_slash(self):
        """Trailing slash in base_url should be stripped."""
        c = NexusClient(base_url="http://test:9000/")

        assert c._base_url == "http://test:9000"

    def test_constructor_custom_params(self):
        """Custom timeout and max_retries should be stored."""
        c = NexusClient("http://x:1234", timeout=10, max_retries=5)

        assert c._timeout == 10
        assert c._max_retries == 5

    def test_constructor_initialises_lazy_facades_as_none(self):
        """Domain facades (rules, sessions, memory) should start as None."""
        c = NexusClient("http://x:1234")

        assert c._rules is None
        assert c._sessions is None
        assert c._memory is None

    def test_get_nexus_client_returns_singleton(self):
        """get_nexus_client should return the same instance on repeated calls."""
        with patch("engine.nexus.client.NexusClient") as MockCls:
            MockCls.return_value = MagicMock(spec=NexusClient)

            first = get_nexus_client(base_url="http://localhost:8700")
            second = get_nexus_client(base_url="http://localhost:8700")

        assert first is second
        MockCls.assert_called_once_with("http://localhost:8700")

    def test_get_nexus_client_creates_with_provided_url(self):
        """get_nexus_client should pass base_url to the NexusClient constructor."""
        with patch("engine.nexus.client.NexusClient") as MockCls:
            MockCls.return_value = MagicMock(spec=NexusClient)
            get_nexus_client(base_url="http://custom:9999")

        MockCls.assert_called_once_with("http://custom:9999")


# ─── Health & Status ─────────────────────────────────────────────


class TestHealthAndStatus:
    """Tests for health(), stats(), and is_available()."""

    def test_health_returns_dict(self, client):
        """health() should return the raw response from /api/health."""
        expected = {"ok": True, "version": "0.50a", "uptime": 3600}
        with patch.object(client, "_request", return_value=expected):
            result = client.health()

        assert result == expected
        assert result["ok"] is True

    def test_health_calls_correct_endpoint(self, client):
        """health() should issue GET /api/health."""
        with patch.object(client, "_request", return_value={"ok": True}) as mock_req:
            client.health()

        mock_req.assert_called_once_with("GET", "/api/health")

    def test_stats_returns_dict(self, client):
        """stats() should return the raw response from /api/stats."""
        expected = {"ok": True, "entries": 42, "sessions": 10}
        with patch.object(client, "_request", return_value=expected):
            result = client.stats()

        assert result == expected

    def test_is_available_true_when_healthy(self, client):
        """is_available() should return True when health() returns ok=True."""
        with patch.object(client, "health", return_value={"ok": True}):
            assert client.is_available() is True

    def test_is_available_false_when_not_ok(self, client):
        """is_available() should return False when health() returns ok=False."""
        with patch.object(client, "health", return_value={"ok": False}):
            assert client.is_available() is False

    def test_is_available_false_on_error(self, client):
        """is_available() should return False when health() raises."""
        with patch.object(client, "health", side_effect=ConnectionError("refused")):
            assert client.is_available() is False


# ─── Search ──────────────────────────────────────────────────────


class TestSearch:
    """Tests for search()."""

    def test_search_returns_list(self, client):
        """search() should return a list of parsed entries."""
        raw_entries = [
            {"id": "e1", "title": "Combat", "content": "Dragon fight"},
            {"id": "e2", "title": "Lore", "content": "Ancient history"},
        ]
        with patch.object(client, "_request", return_value=_ok(raw_entries)), \
             patch.object(NexusClient, "_parse_entry", side_effect=lambda d: d):
            results = client.search("combat")

        assert len(results) == 2
        assert results[0]["title"] == "Combat"
        assert results[1]["id"] == "e2"

    def test_search_empty_results(self, client):
        """search() should return empty list when no results match."""
        with patch.object(client, "_request", return_value=_ok([])), \
             patch.object(NexusClient, "_parse_entry", side_effect=lambda d: d):
            results = client.search("nonexistent topic")

        assert results == []

    def test_search_encodes_query_params(self, client):
        """search() should URL-encode query and limit into the path."""
        with patch.object(client, "_request", return_value=_ok([])) as mock_req:
            client.search("hello world", limit=5)

        path = mock_req.call_args[0][1]
        assert "q=hello+world" in path or "q=hello%20world" in path
        assert "limit=5" in path

    def test_search_uses_default_limit(self, client):
        """search() should default to limit=10."""
        with patch.object(client, "_request", return_value=_ok([])) as mock_req:
            client.search("test")

        path = mock_req.call_args[0][1]
        assert "limit=10" in path

    def test_search_returns_empty_on_error(self, client):
        """search() should return empty list when API returns ok=False."""
        with patch.object(client, "_request", return_value=_err()):
            results = client.search("test")

        assert results == []


# ─── CRUD ────────────────────────────────────────────────────────


class TestCRUD:
    """Tests for add_entry, get_entry, update_entry, delete_entry."""

    # ── add_entry ──

    def test_add_entry_returns_id(self, client):
        """add_entry() should return the new entry ID on success."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload", return_value={
                 "title": "Test", "content": "Body", "content_type": "note",
                 "category": "", "tags": [], "created_by": "cosysim",
             }), \
             patch.object(client, "_request", return_value=_ok({"id": "entry-abc"})):
            result = client.add_entry("Test", "Body")

        assert result == "entry-abc"

    def test_add_entry_with_all_fields(self, client):
        """add_entry() should pass all fields through normalisation."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload", return_value={
                 "title": "Full", "content": "Detail", "content_type": "guide",
                 "category": "combat", "tags": ["a", "b"], "created_by": "system",
             }) as mock_norm, \
             patch.object(client, "_request", return_value=_ok({"id": "xyz"})):
            result = client.add_entry(
                "Full", "Detail",
                content_type="guide", category="combat",
                tags=["a", "b"], created_by="system",
            )

        assert result == "xyz"
        call_kw = mock_norm.call_args[1]
        assert call_kw["title"] == "Full"
        assert call_kw["content_type"] == "guide"
        assert call_kw["category"] == "combat"

    def test_add_entry_posts_normalised_payload(self, client):
        """add_entry() should POST the normalised payload to /api/entries."""
        normalised = {
            "title": "T", "content": "C", "content_type": "note",
            "category": "", "tags": [], "created_by": "cosysim",
        }
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload", return_value=normalised), \
             patch.object(client, "_request", return_value=_ok({"id": "x"})) as mock_req:
            client.add_entry("T", "C")

        mock_req.assert_called_once_with("POST", "/api/entries", normalised)

    def test_add_entry_returns_none_on_api_error(self, client):
        """add_entry() should return None when the API returns ok=False."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload", return_value={
                 "title": "T", "content": "C", "content_type": "note",
                 "category": "", "tags": [], "created_by": "cosysim",
             }), \
             patch.object(client, "_request", return_value=_err()):
            result = client.add_entry("T", "C")

        assert result is None

    def test_add_entry_returns_none_on_governance_failure(self, client):
        """add_entry() should return None when governance denies the write."""
        with patch.object(client, "_check_governance",
                          side_effect=PermissionError("denied")):
            result = client.add_entry("T", "C")

        assert result is None

    # ── get_entry ──

    def test_get_entry_returns_dict(self, client):
        """get_entry() should return a parsed entry on success."""
        entry_data = {"id": "e1", "title": "Test", "content": "Body"}
        with patch.object(client, "_request", return_value=_ok(entry_data)), \
             patch.object(NexusClient, "_parse_entry", side_effect=lambda d: d):
            result = client.get_entry("e1")

        assert result == entry_data

    def test_get_entry_calls_correct_endpoint(self, client):
        """get_entry() should GET /api/entries/{id}."""
        with patch.object(client, "_request", return_value=_ok(None)) as mock_req:
            client.get_entry("abc-123")

        mock_req.assert_called_once_with("GET", "/api/entries/abc-123")

    def test_get_entry_not_found_returns_none(self, client):
        """get_entry() should return None when data is null (entry missing)."""
        with patch.object(client, "_request",
                          return_value={"ok": True, "data": None}):
            result = client.get_entry("nonexistent")

        assert result is None

    def test_get_entry_returns_none_on_api_error(self, client):
        """get_entry() should return None when the API returns ok=False."""
        with patch.object(client, "_request", return_value=_err()):
            result = client.get_entry("e1")

        assert result is None

    # ── update_entry ──

    def test_update_entry_returns_true(self, client):
        """update_entry() should return True on successful update."""
        existing = MagicMock()
        existing.get.return_value = "cosysim"
        with patch.object(client, "get_entry", return_value=existing), \
             patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload", return_value={
                 "title": "Updated", "content": "New", "content_type": "note",
                 "category": "", "tags": [], "created_by": "cosysim",
             }), \
             patch.object(client, "_request", return_value={"ok": True}):
            result = client.update_entry("e1", title="Updated")

        assert result is True

    def test_update_entry_returns_false_on_api_error(self, client):
        """update_entry() should return False when the API reports failure."""
        existing = MagicMock()
        existing.get.return_value = "cosysim"
        with patch.object(client, "get_entry", return_value=existing), \
             patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload", return_value={
                 "title": "T", "content": "C", "content_type": "note",
                 "category": "", "tags": [], "created_by": "cosysim",
             }), \
             patch.object(client, "_request", return_value=_err()):
            result = client.update_entry("e1", title="T")

        assert result is False

    def test_update_entry_returns_false_on_governance_failure(self, client):
        """update_entry() should return False when governance denies."""
        existing = MagicMock()
        existing.get.return_value = ""
        with patch.object(client, "get_entry", return_value=existing), \
             patch.object(client, "_check_governance",
                          side_effect=PermissionError("denied")):
            result = client.update_entry("e1", title="T")

        assert result is False

    # ── delete_entry ──

    def test_delete_entry_returns_true(self, client):
        """delete_entry() should return True on successful deletion."""
        existing = MagicMock()
        existing.get.return_value = ""
        with patch.object(client, "get_entry", return_value=existing), \
             patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_request", return_value={"ok": True}):
            result = client.delete_entry("e1")

        assert result is True

    def test_delete_entry_calls_correct_endpoint(self, client):
        """delete_entry() should DELETE /api/entries/{id}."""
        existing = MagicMock()
        existing.get.return_value = ""
        with patch.object(client, "get_entry", return_value=existing), \
             patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_request", return_value={"ok": True}) as mock_req:
            client.delete_entry("entry-42")

        mock_req.assert_called_once_with("DELETE", "/api/entries/entry-42")

    def test_delete_entry_returns_false_on_governance_failure(self, client):
        """delete_entry() should return False when governance denies."""
        existing = MagicMock()
        existing.get.return_value = ""
        with patch.object(client, "get_entry", return_value=existing), \
             patch.object(client, "_check_governance",
                          side_effect=PermissionError("no")):
            result = client.delete_entry("e1")

        assert result is False


# ─── Q&A ─────────────────────────────────────────────────────────


class TestQA:
    """Tests for Q&A methods: ask, find_qa, add_qa."""

    def test_ask_returns_answer(self, client):
        """ask() should return the data dict from /api/research/ask."""
        answer_data = {"answer": "42", "source": "cache", "confidence": 0.95}
        with patch.object(client, "_request", return_value=_ok(answer_data)):
            result = client.ask("What is the meaning of life?")

        assert result["answer"] == "42"
        assert result["source"] == "cache"

    def test_ask_returns_empty_on_error(self, client):
        """ask() should return empty dict when the API returns ok=False."""
        with patch.object(client, "_request", return_value=_err()):
            result = client.ask("question?")

        assert result == {}

    def test_ask_sends_depth_and_category(self, client):
        """ask() should include depth and category in the POST payload."""
        with patch.object(client, "_request", return_value=_ok({})) as mock_req:
            client.ask("q?", depth="deep", category="combat")

        payload = mock_req.call_args[0][2]
        assert payload["question"] == "q?"
        assert payload["depth"] == "deep"
        assert payload["category"] == "combat"

    def test_ask_defaults_depth_to_auto(self, client):
        """ask() should default depth to 'auto' when not specified."""
        with patch.object(client, "_request", return_value=_ok({})) as mock_req:
            client.ask("question")

        payload = mock_req.call_args[0][2]
        assert payload["depth"] == "auto"

    def test_find_qa_returns_matches(self, client):
        """find_qa() should return list of matching Q&A pairs."""
        matches = [
            {"question": "How?", "answer": "Like this", "score": 0.9},
            {"question": "Why?", "answer": "Because", "score": 0.7},
        ]
        with patch.object(client, "_request", return_value=_ok(matches)):
            results = client.find_qa("How?")

        assert len(results) == 2
        assert results[0]["score"] == 0.9

    def test_find_qa_encodes_params(self, client):
        """find_qa() should URL-encode question and limit in the query string."""
        with patch.object(client, "_request", return_value=_ok([])) as mock_req:
            client.find_qa("two words", limit=3)

        path = mock_req.call_args[0][1]
        assert "q=two+words" in path or "q=two%20words" in path
        assert "limit=3" in path

    def test_find_qa_returns_empty_on_miss(self, client):
        """find_qa() should return empty list when no matches are found."""
        with patch.object(client, "_request", return_value=_ok([])):
            results = client.find_qa("obscure question")

        assert results == []

    def test_find_qa_returns_empty_on_error(self, client):
        """find_qa() should return empty list on API error."""
        with patch.object(client, "_request", return_value=_err()):
            results = client.find_qa("anything")

        assert results == []

    def test_add_qa_returns_id(self, client):
        """add_qa() should return the ID of the stored Q&A pair."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_namespace_tags",
                          return_value=["tag1"]), \
             patch.object(client, "_request",
                          return_value=_ok({"id": "qa-123"})):
            result = client.add_qa("How?", "Like this", category="test")

        assert result == "qa-123"

    def test_add_qa_posts_correct_payload(self, client):
        """add_qa() should POST question, answer, tags, and quality_score."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_namespace_tags",
                          return_value=["combat"]), \
             patch.object(client, "_request",
                          return_value=_ok({"id": "qa-x"})) as mock_req:
            client.add_qa("Q?", "A.", category="combat",
                          tags=["combat"], quality_score=0.8)

        payload = mock_req.call_args[0][2]
        assert payload["question"] == "Q?"
        assert payload["answer"] == "A."
        assert payload["quality_score"] == 0.8
        assert payload["category"] == "combat"

    def test_add_qa_returns_none_on_governance_failure(self, client):
        """add_qa() should return None when governance denies the write."""
        with patch.object(client, "_check_governance",
                          side_effect=PermissionError("no")):
            result = client.add_qa("Q", "A")

        assert result is None


# ─── Sessions ────────────────────────────────────────────────────


class TestSessions:
    """Tests for session tracking methods."""

    def test_log_session_returns_id(self, client):
        """log_session() should return the new session ID."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_request",
                          return_value=_ok({"id": "sess-1"})):
            result = client.log_session(project="CosySim")

        assert result == "sess-1"

    def test_log_session_with_explicit_id(self, client):
        """log_session() should include an explicit session_id in the payload."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_request",
                          return_value=_ok({"id": "my-sess"})) as mock_req:
            client.log_session(session_id="my-sess", project="CosySim")

        payload = mock_req.call_args[0][2]
        assert payload["id"] == "my-sess"
        assert payload["project"] == "CosySim"

    def test_log_session_omits_id_when_not_specified(self, client):
        """log_session() should not include 'id' when session_id is None."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_request",
                          return_value=_ok({"id": "auto-1"})) as mock_req:
            client.log_session(project="test")

        payload = mock_req.call_args[0][2]
        assert "id" not in payload

    def test_log_session_returns_none_on_api_error(self, client):
        """log_session() should return None when the API returns ok=False."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_request", return_value=_err()):
            result = client.log_session(project="test")

        assert result is None

    def test_log_session_returns_none_on_governance_failure(self, client):
        """log_session() should return None when governance denies."""
        with patch.object(client, "_check_governance",
                          side_effect=PermissionError("no")):
            result = client.log_session(project="test")

        assert result is None

    def test_list_sessions_returns_list(self, client):
        """list_sessions() should return list of session dicts."""
        sessions = [
            {"id": "s1", "project": "CosySim", "status": "active"},
            {"id": "s2", "project": "CosySim", "status": "complete"},
        ]
        with patch.object(client, "_request", return_value=_ok(sessions)):
            results = client.list_sessions(project="CosySim")

        assert len(results) == 2
        assert results[0]["id"] == "s1"
        assert results[1]["status"] == "complete"

    def test_list_sessions_builds_query_params(self, client):
        """list_sessions() should include project, status, and limit in path."""
        with patch.object(client, "_request", return_value=_ok([])) as mock_req:
            client.list_sessions(project="X", status="active", limit=10)

        path = mock_req.call_args[0][1]
        assert "project=X" in path
        assert "status=active" in path
        assert "limit=10" in path

    def test_list_sessions_returns_empty_on_error(self, client):
        """list_sessions() should return empty list on API error."""
        with patch.object(client, "_request", return_value=_err()):
            results = client.list_sessions()

        assert results == []


# ─── Batch ───────────────────────────────────────────────────────


class TestBatch:
    """Tests for batch_add()."""

    def test_batch_add_returns_ids(self, client):
        """batch_add() should return list of created entry IDs."""
        entries = [
            {"title": "Entry 1", "content": "Content 1"},
            {"title": "Entry 2", "content": "Content 2"},
        ]
        norm_payloads = [
            {"title": "Entry 1", "content": "Content 1", "content_type": "note",
             "category": "", "tags": [], "created_by": "cosysim"},
            {"title": "Entry 2", "content": "Content 2", "content_type": "note",
             "category": "", "tags": [], "created_by": "cosysim"},
        ]
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload",
                          side_effect=norm_payloads), \
             patch.object(client, "_request",
                          return_value=_ok({"ids": ["id-1", "id-2"]})):
            result = client.batch_add(entries)

        assert result == ["id-1", "id-2"]

    def test_batch_add_posts_normalised_entries(self, client):
        """batch_add() should POST all normalised entries in one request."""
        norm = {"title": "T", "content": "C", "content_type": "note",
                "category": "", "tags": [], "created_by": "cosysim"}
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload",
                          return_value=norm), \
             patch.object(client, "_request",
                          return_value=_ok({"ids": ["x"]})) as mock_req:
            client.batch_add([{"title": "T", "content": "C"}])

        payload = mock_req.call_args[0][2]
        assert "entries" in payload
        assert len(payload["entries"]) == 1

    def test_batch_add_returns_empty_on_all_governance_failures(self, client):
        """batch_add() should return empty list when all entries fail governance."""
        with patch.object(client, "_check_governance",
                          side_effect=PermissionError("no")):
            result = client.batch_add([{"title": "T", "content": "C"}])

        assert result == []

    def test_batch_add_skips_failing_entries(self, client):
        """batch_add() should skip entries that fail governance and keep the rest."""
        norm = {"title": "OK", "content": "C", "content_type": "note",
                "category": "", "tags": [], "created_by": "cosysim"}
        with patch.object(client, "_check_governance",
                          side_effect=[PermissionError("no"), "copilot"]), \
             patch.object(client, "_normalize_entry_payload",
                          return_value=norm), \
             patch.object(client, "_request",
                          return_value=_ok({"ids": ["id-2"]})):
            result = client.batch_add([
                {"title": "Bad", "content": "C"},
                {"title": "OK", "content": "C"},
            ])

        assert result == ["id-2"]

    def test_batch_add_returns_empty_on_api_error(self, client):
        """batch_add() should return empty list when the API returns ok=False."""
        norm = {"title": "T", "content": "C", "content_type": "note",
                "category": "", "tags": [], "created_by": "cosysim"}
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_normalize_entry_payload",
                          return_value=norm), \
             patch.object(client, "_request", return_value=_err()):
            result = client.batch_add([{"title": "T", "content": "C"}])

        assert result == []


# ─── Error Handling (_request) ───────────────────────────────────


class TestErrorHandling:
    """Tests for retry logic, timeouts, and connection errors in _request."""

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_handles_timeout(self, mock_urlopen, client):
        """_request should return error dict on timeout after all retries."""
        mock_urlopen.side_effect = TimeoutError("Connection timed out")

        result = client._request("GET", "/api/health")

        assert result["ok"] is False
        assert "timed out" in result["error"]

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_handles_connection_error(self, mock_urlopen, client):
        """_request should return error dict on connection refused."""
        mock_urlopen.side_effect = ConnectionError("Connection refused")

        result = client._request("GET", "/api/health")

        assert result["ok"] is False
        assert "refused" in result["error"]

    @patch("engine.nexus.client.time.sleep")
    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_retries_on_failure(self, mock_urlopen, mock_sleep, client):
        """_request should retry up to max_retries times with backoff."""
        mock_urlopen.side_effect = ConnectionError("refused")
        client._max_retries = 3

        client._request("GET", "/api/health")

        assert mock_urlopen.call_count == 3
        # Exponential backoff: sleep(0.5*1), sleep(0.5*2) — last attempt has no sleep
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)

    @patch("engine.nexus.client.time.sleep")
    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_succeeds_on_retry(self, mock_urlopen, mock_sleep, client):
        """_request should return success if a retry attempt succeeds."""
        success_resp = _mock_urlopen_response({"ok": True, "data": "hello"})
        mock_urlopen.side_effect = [
            ConnectionError("first fail"),
            success_resp,
        ]

        result = client._request("GET", "/api/test")

        assert result == {"ok": True, "data": "hello"}
        assert mock_urlopen.call_count == 2

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_handles_http_error(self, mock_urlopen, client):
        """_request should handle urllib HTTPError (e.g. 500) gracefully."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://localhost:8700/api/health",
            code=500, msg="Internal Server Error",
            hdrs=None, fp=None,
        )

        result = client._request("GET", "/api/health")

        assert result["ok"] is False

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_handles_url_error(self, mock_urlopen, client):
        """_request should handle urllib URLError (DNS / connection failure)."""
        mock_urlopen.side_effect = urllib.error.URLError("Name resolution failed")

        result = client._request("GET", "/api/health")

        assert result["ok"] is False
        assert "Name resolution" in result["error"]

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_sends_post_with_json_body(self, mock_urlopen, client):
        """POST requests should send a JSON-encoded body with correct header."""
        mock_urlopen.return_value = _mock_urlopen_response({"ok": True})

        client._request("POST", "/api/entries", {"title": "T"})

        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.method == "POST"
        assert req_obj.get_header("Content-type") == "application/json"
        body = json.loads(req_obj.data.decode())
        assert body["title"] == "T"

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_sends_put_with_json_body(self, mock_urlopen, client):
        """PUT requests should send a JSON-encoded body."""
        mock_urlopen.return_value = _mock_urlopen_response({"ok": True})

        client._request("PUT", "/api/entries/e1", {"title": "Updated"})

        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.method == "PUT"
        body = json.loads(req_obj.data.decode())
        assert body["title"] == "Updated"

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_sends_get_without_body(self, mock_urlopen, client):
        """GET requests should not include a request body."""
        mock_urlopen.return_value = _mock_urlopen_response({"ok": True})

        client._request("GET", "/api/health")

        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.method == "GET"
        assert req_obj.data is None

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_sends_delete_without_body(self, mock_urlopen, client):
        """DELETE requests should not include a request body."""
        mock_urlopen.return_value = _mock_urlopen_response({"ok": True})

        client._request("DELETE", "/api/entries/e1")

        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.method == "DELETE"
        assert req_obj.data is None

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_builds_correct_url(self, mock_urlopen, client):
        """_request should combine base_url with path to form the full URL."""
        mock_urlopen.return_value = _mock_urlopen_response({"ok": True})

        client._request("GET", "/api/health")

        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.full_url == "http://localhost:8700/api/health"

    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_uses_configured_timeout(self, mock_urlopen, client):
        """_request should pass the client's timeout to urlopen."""
        mock_urlopen.return_value = _mock_urlopen_response({"ok": True})

        client._request("GET", "/api/test")

        _, kwargs = mock_urlopen.call_args
        assert kwargs["timeout"] == 5

    @patch("engine.nexus.client.time.sleep")
    @patch("engine.nexus.client.urllib.request.urlopen")
    def test_request_no_retry_when_max_retries_is_one(self, mock_urlopen,
                                                       mock_sleep):
        """With max_retries=1 there should be exactly one attempt and no sleep."""
        c = NexusClient("http://localhost:8700", timeout=5, max_retries=1)
        mock_urlopen.side_effect = ConnectionError("fail")

        c._request("GET", "/api/test")

        assert mock_urlopen.call_count == 1
        mock_sleep.assert_not_called()


# ─── Governance Actor Resolution ─────────────────────────────────


class TestGovernanceActorResolution:
    """Tests for the module-level _resolve_governance_actor helper."""

    def test_agent_id_takes_priority(self):
        """Explicit agent_id should override created_by."""
        from engine.nexus.client import _resolve_governance_actor

        assert _resolve_governance_actor(agent_id="bench") == "bench"

    def test_empty_inputs_default_to_copilot(self):
        """No agent_id and no created_by should resolve to 'copilot'."""
        from engine.nexus.client import _resolve_governance_actor

        assert _resolve_governance_actor() == "copilot"

    def test_cosysim_resolves_to_copilot(self):
        """'cosysim' created_by should resolve to 'copilot'."""
        from engine.nexus.client import _resolve_governance_actor

        assert _resolve_governance_actor(created_by="cosysim") == "copilot"

    def test_trusted_prefix_resolves_to_copilot(self):
        """created_by with a trusted prefix should resolve to 'copilot'."""
        from engine.nexus.client import _resolve_governance_actor

        for prefix in ("copilot_agent", "nexus_sync", "session_x",
                        "research_pipeline", "system_task", "api_handler",
                        "content_gen", "workflow_run", "benchmark_run"):
            assert _resolve_governance_actor(created_by=prefix) == "copilot", \
                f"Expected 'copilot' for created_by='{prefix}'"

    def test_trusted_suffix_resolves_to_copilot(self):
        """created_by with a trusted suffix should resolve to 'copilot'."""
        from engine.nexus.client import _resolve_governance_actor

        for suffix in ("data_workflow", "nightly_sync", "event_logger",
                        "nexus_bridge", "llm_pipeline", "qa_distiller",
                        "asset_generator"):
            assert _resolve_governance_actor(created_by=suffix) == "copilot", \
                f"Expected 'copilot' for created_by='{suffix}'"

    def test_untrusted_actor_passes_through(self):
        """Untrusted created_by should pass through as lowercase."""
        from engine.nexus.client import _resolve_governance_actor

        assert _resolve_governance_actor(created_by="External_User") == "external_user"

    def test_whitespace_created_by_treated_as_empty(self):
        """Whitespace-only created_by should resolve to 'copilot'."""
        from engine.nexus.client import _resolve_governance_actor

        assert _resolve_governance_actor(created_by="   ") == "copilot"


# ─── Additional Public Methods ───────────────────────────────────


class TestAdditionalMethods:
    """Tests for less-common public methods to ensure coverage."""

    def test_list_entries_with_filters(self, client):
        """list_entries() should include type, category, and limit in path."""
        with patch.object(client, "_request", return_value=_ok([])) as mock_req:
            client.list_entries(content_type="guide", category="combat", limit=5)

        path = mock_req.call_args[0][1]
        assert "type=guide" in path
        assert "category=combat" in path
        assert "limit=5" in path

    def test_list_entries_returns_empty_on_error(self, client):
        """list_entries() should return empty list on API error."""
        with patch.object(client, "_request", return_value=_err()):
            results = client.list_entries()

        assert results == []

    def test_list_plugins_returns_list(self, client):
        """list_plugins() should return list of plugin dicts."""
        plugins = [{"name": "tagger", "scope": "global"}]
        with patch.object(client, "_request", return_value=_ok(plugins)):
            result = client.list_plugins()

        assert len(result) == 1
        assert result[0]["name"] == "tagger"

    def test_list_plugins_empty_on_error(self, client):
        """list_plugins() should return empty list on API error."""
        with patch.object(client, "_request", return_value=_err()):
            assert client.list_plugins() == []

    def test_nlm_ask_sends_question(self, client):
        """nlm_ask() should POST question to /api/nlm/ask."""
        with patch.object(client, "_request",
                          return_value={"ok": True}) as mock_req:
            client.nlm_ask("What is the answer?")

        call_args = mock_req.call_args
        assert call_args[0][1] == "/api/nlm/ask"
        assert call_args[0][2]["question"] == "What is the answer?"

    def test_nlm_ask_includes_notebook_params(self, client):
        """nlm_ask() should include notebook_id or notebook_url when given."""
        with patch.object(client, "_request",
                          return_value={"ok": True}) as mock_req:
            client.nlm_ask("Q?", notebook_id="nb-1",
                           notebook_url="https://nlm.example.com")

        payload = mock_req.call_args[0][2]
        assert payload["notebook_id"] == "nb-1"
        assert payload["notebook_url"] == "https://nlm.example.com"

    def test_track_access_returns_true_on_success(self, client):
        """track_access() should return True when annotation succeeds."""
        with patch.object(client, "_request", return_value={"ok": True}):
            assert client.track_access("entry-1") is True

    def test_track_access_returns_false_on_failure(self, client):
        """track_access() should return False when annotation fails."""
        with patch.object(client, "_request", return_value={"ok": False}):
            assert client.track_access("entry-1") is False

    def test_import_youtube_returns_data(self, client):
        """import_youtube() should return data dict on success."""
        with patch.object(client, "_request",
                          return_value=_ok({"title": "Vid", "entry_id": "yt-1"})):
            result = client.import_youtube("https://youtube.com/watch?v=xyz")

        assert result["title"] == "Vid"
        assert result["entry_id"] == "yt-1"

    def test_import_youtube_returns_empty_on_error(self, client):
        """import_youtube() should return empty dict on API error."""
        with patch.object(client, "_request", return_value=_err()):
            result = client.import_youtube("https://youtube.com/watch?v=xyz")

        assert result == {}

    def test_research_starts_session(self, client):
        """research() should return research session data."""
        with patch.object(client, "_request",
                          return_value=_ok({"research_id": "r-1"})):
            result = client.research("deep question")

        assert result["research_id"] == "r-1"

    def test_research_includes_optional_params(self, client):
        """research() should pass notebook_id and sources when provided."""
        with patch.object(client, "_request",
                          return_value=_ok({})) as mock_req:
            client.research("q", notebook_id="nb-1", sources=["s1", "s2"])

        payload = mock_req.call_args[0][2]
        assert payload["notebook_id"] == "nb-1"
        assert payload["sources"] == ["s1", "s2"]

    def test_converse_continues_research(self, client):
        """converse() should POST a follow-up message to a research session."""
        with patch.object(client, "_request",
                          return_value=_ok({"response": "analysis"})) as mock_req:
            result = client.converse("r-1", "follow up")

        assert result["response"] == "analysis"
        assert "/api/research/r-1/converse" in mock_req.call_args[0][1]

    def test_finish_research_returns_summary(self, client):
        """finish_research() should return the distilled Q&A count."""
        with patch.object(client, "_request",
                          return_value=_ok({"qa_pairs": 3})):
            result = client.finish_research("r-1")

        assert result["qa_pairs"] == 3

    def test_update_session_returns_true(self, client):
        """update_session() should return True on success."""
        with patch.object(client, "_check_governance", return_value="copilot"), \
             patch.object(client, "_request", return_value={"ok": True}):
            result = client.update_session("s-1", summary="done")

        assert result is True

    def test_update_session_returns_false_on_governance_failure(self, client):
        """update_session() should return False when governance denies."""
        with patch.object(client, "_check_governance",
                          side_effect=PermissionError("no")):
            result = client.update_session("s-1", summary="done")

        assert result is False

    def test_get_session_returns_data(self, client):
        """get_session() should return session dict on success."""
        session_data = {"id": "s-1", "project": "CosySim", "status": "active"}
        with patch.object(client, "_request", return_value=_ok(session_data)):
            result = client.get_session("s-1")

        assert result == session_data

    def test_get_session_returns_none_on_error(self, client):
        """get_session() should return None on API error."""
        with patch.object(client, "_request", return_value=_err()):
            result = client.get_session("s-1")

        assert result is None

    def test_nlm_status_returns_dict(self, client):
        """nlm_status() should return the raw response from /api/nlm/status."""
        status = {"ok": True, "backends": {"http": "up", "browser": "down"}}
        with patch.object(client, "_request", return_value=status):
            result = client.nlm_status()

        assert result["backends"]["http"] == "up"

    def test_nlm_list_notebooks_returns_list(self, client):
        """nlm_list_notebooks() should return list of notebook dicts."""
        notebooks = [{"id": "nb-1", "name": "Research"}]
        with patch.object(client, "_request", return_value=_ok(notebooks)):
            result = client.nlm_list_notebooks()

        assert len(result) == 1
        assert result[0]["name"] == "Research"

    def test_nlm_list_notebooks_empty_on_error(self, client):
        """nlm_list_notebooks() should return empty list on API error."""
        with patch.object(client, "_request", return_value=_err()):
            assert client.nlm_list_notebooks() == []


# ─── Internal Method Wiring ──────────────────────────────────────


class TestInternalWiring:
    """Verify that _get/_post/_put/_delete delegate to _request correctly."""

    def test_get_delegates_to_request(self, client):
        """_get should call _request with GET."""
        with patch.object(client, "_request", return_value={}) as mock_req:
            client._get("/api/test")

        mock_req.assert_called_once_with("GET", "/api/test")

    def test_post_delegates_to_request(self, client):
        """_post should call _request with POST and payload."""
        payload = {"key": "value"}
        with patch.object(client, "_request", return_value={}) as mock_req:
            client._post("/api/test", payload)

        mock_req.assert_called_once_with("POST", "/api/test", payload)

    def test_put_delegates_to_request(self, client):
        """_put should call _request with PUT and payload."""
        payload = {"key": "updated"}
        with patch.object(client, "_request", return_value={}) as mock_req:
            client._put("/api/test", payload)

        mock_req.assert_called_once_with("PUT", "/api/test", payload)

    def test_delete_delegates_to_request(self, client):
        """_delete should call _request with DELETE."""
        with patch.object(client, "_request", return_value={}) as mock_req:
            client._delete("/api/test")

        mock_req.assert_called_once_with("DELETE", "/api/test")
