"""Tests for the Flask dashboard scene.
===========================================

Covers:
- GET /api/dashboard/stats — aggregate counts
- GET /api/characters — list characters
- POST /api/characters — create character (success + validation)
- GET /api/characters/<id> — get single character
- PUT /api/characters/<id> — update character
- DELETE /api/characters/<id> — delete character
- GET /api/personalities — list personalities
- POST /api/personalities — create custom personality
- POST /api/personalities/init — initialize defaults
- GET /api/roles — list roles
- POST /api/roles — create custom role
- POST /api/roles/init — initialize defaults
- GET /api/characters/<id>/memories — list memories
- POST /api/characters/<id>/memories — add memory
- PUT /api/memories/<id> — update memory
- DELETE /api/memories/<id> — delete memory
- GET /api/characters/<id>/memories/search — semantic search

Version: v1.49.3 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.3 [2026-03-22] — Initial test suite for DashboardScene REST API routes
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ──── Fixtures ────────────────────────────────────────────────────────


def _make_mock_db() -> MagicMock:
    """Build a mock Database with sensible defaults for all methods used
    by DashboardScene routes.

    Returns:
        Configured MagicMock mimicking Database.
    """
    db = MagicMock()
    db.get_all_characters.return_value = [
        {"id": "char-001", "name": "Lola"},
        {"id": "char-002", "name": "Viktor"},
    ]
    db.get_all_personalities.return_value = [
        {"id": "pers-001", "name": "Sarcastic"},
    ]
    db.get_all_roles.return_value = [
        {"id": "role-001", "name": "Bartender"},
    ]
    db.get_character.return_value = {"id": "char-001", "name": "Lola"}
    db.get_character_memories.return_value = [
        {"id": "mem-001", "content": "First day in the city", "importance": 0.8},
    ]
    db.add_memory.return_value = "mem-new-001"
    db.update_memory.return_value = True
    db.delete_memory.return_value = True
    db.delete_character.return_value = True
    return db


def _make_mock_rag() -> MagicMock:
    """Build a mock RAGMemory.

    Returns:
        Configured MagicMock mimicking RAGMemory.
    """
    rag = MagicMock()
    rag.get_memory_count.return_value = 42
    rag.query_memories.return_value = [
        {"content": "Sunset over the neon skyline", "score": 0.92},
        {"content": "First night at the club", "score": 0.85},
    ]
    rag.add_memory.return_value = None
    return rag


def _make_mock_personality_mgr() -> MagicMock:
    """Build a mock Personality manager.

    Returns:
        Configured MagicMock mimicking Personality.
    """
    mgr = MagicMock()
    mgr.list_all.return_value = [
        {"id": "pers-001", "name": "Sarcastic", "system_prompt": "You are sarcastic."},
    ]
    mgr.get.return_value = {
        "id": "pers-new-001",
        "name": "Brooding",
        "system_prompt": "You brood a lot.",
    }
    mgr.create_custom.return_value = "pers-new-001"
    mgr.initialize_defaults.return_value = ["pers-d1", "pers-d2", "pers-d3"]
    return mgr


def _make_mock_role_mgr() -> MagicMock:
    """Build a mock Role manager.

    Returns:
        Configured MagicMock mimicking Role.
    """
    mgr = MagicMock()
    mgr.list_all.return_value = [
        {"id": "role-001", "name": "Bartender", "description": "Serves drinks."},
    ]
    mgr.get.return_value = {
        "id": "role-new-001",
        "name": "Bouncer",
        "description": "Keeps the peace.",
    }
    mgr.create_custom.return_value = "role-new-001"
    mgr.initialize_defaults.return_value = ["role-d1", "role-d2"]
    return mgr


def _make_mock_character(name: str = "TestChar", char_id: str = "char-new-001") -> MagicMock:
    """Build a mock Character instance with to_dict().

    Args:
        name: Character name.
        char_id: Character ID.

    Returns:
        Configured MagicMock mimicking Character.
    """
    char = MagicMock()
    char.name = name
    char.id = char_id
    char.to_dict.return_value = {"id": char_id, "name": name}
    return char


# v1.49.3 [2026-03-22] — Central fixture: mock all DB/RAG dependencies, build test client
@pytest.fixture()
def dashboard_client():
    """Create a DashboardScene with all external dependencies mocked
    and return (test_client, mock_db, mock_rag, mock_personality_mgr, mock_role_mgr).

    CONNECTS: Database, RAGMemory, Personality, Role, Character
    """
    mock_db = _make_mock_db()
    mock_rag = _make_mock_rag()
    mock_pers = _make_mock_personality_mgr()
    mock_role = _make_mock_role_mgr()

    with patch("content.scenes.dashboard.dashboard_scene.Database", return_value=mock_db), \
         patch("content.scenes.dashboard.dashboard_scene.RAGMemory", return_value=mock_rag), \
         patch("content.scenes.dashboard.dashboard_scene.Personality", return_value=mock_pers), \
         patch("content.scenes.dashboard.dashboard_scene.Role", return_value=mock_role), \
         patch("content.scenes.dashboard.dashboard_scene.get_port", return_value=18501), \
         patch("content.scenes.dashboard.dashboard_scene.get_config", return_value=MagicMock()):
        from content.scenes.dashboard.dashboard_scene import DashboardScene
        scene = DashboardScene(port=18501)
        client = scene.app.test_client()
        yield client, mock_db, mock_rag, mock_pers, mock_role


# ──── Stats Route ─────────────────────────────────────────────────────


class TestDashboardStats:
    """GET /api/dashboard/stats — aggregate counts."""

    def test_stats_returns_200(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/dashboard/stats")
        assert resp.status_code == 200

    def test_stats_json_structure(self, dashboard_client):
        client, mock_db, mock_rag, *_ = dashboard_client
        resp = client.get("/api/dashboard/stats")
        data = resp.get_json()
        assert "characters" in data
        assert "personalities" in data
        assert "roles" in data
        assert "memories" in data

    def test_stats_counts_match_db(self, dashboard_client):
        """Verify counts come from DB and RAG calls."""
        client, mock_db, mock_rag, *_ = dashboard_client
        resp = client.get("/api/dashboard/stats")
        data = resp.get_json()
        # DB returns 2 characters, 1 personality, 1 role; RAG returns 42 memories
        assert data["characters"] == 2
        assert data["personalities"] == 1
        assert data["roles"] == 1
        assert data["memories"] == 42

    def test_stats_calls_db_methods(self, dashboard_client):
        client, mock_db, mock_rag, *_ = dashboard_client
        client.get("/api/dashboard/stats")
        mock_db.get_all_characters.assert_called_once()
        mock_db.get_all_personalities.assert_called_once()
        mock_db.get_all_roles.assert_called_once()
        mock_rag.get_memory_count.assert_called_once()

    def test_stats_error_returns_500(self, dashboard_client):
        """When the DB raises, the route should return 500 with error JSON."""
        client, mock_db, *_ = dashboard_client
        mock_db.get_all_characters.side_effect = RuntimeError("DB offline")
        resp = client.get("/api/dashboard/stats")
        assert resp.status_code == 500
        data = resp.get_json()
        assert "error" in data


# ──── Characters Routes ───────────────────────────────────────────────


class TestCharactersList:
    """GET /api/characters — list all characters."""

    def test_list_returns_200(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/characters")
        assert resp.status_code == 200

    def test_list_returns_array(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/characters")
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_error_returns_500(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.get_all_characters.side_effect = RuntimeError("DB error")
        resp = client.get("/api/characters")
        assert resp.status_code == 500


class TestCharactersCreate:
    """POST /api/characters — create a new character."""

    def test_create_requires_name(self, dashboard_client):
        """Missing name should return 400."""
        client, *_ = dashboard_client
        resp = client.post("/api/characters", json={"age": 25})
        assert resp.status_code == 400
        assert "name" in resp.get_json()["error"].lower()

    def test_create_empty_body_returns_400(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.post("/api/characters", json={})
        assert resp.status_code == 400

    @patch("content.scenes.dashboard.dashboard_scene.Character")
    def test_create_success_returns_201(self, mock_char_cls, dashboard_client):
        """Valid name returns 201 with character dict."""
        client, mock_db, *_ = dashboard_client
        mock_char = _make_mock_character("Mira", "char-mira")
        mock_char_cls.create.return_value = mock_char

        resp = client.post("/api/characters", json={"name": "Mira", "age": 22})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Mira"
        assert data["id"] == "char-mira"

    @patch("content.scenes.dashboard.dashboard_scene.Character")
    def test_create_calls_character_create(self, mock_char_cls, dashboard_client):
        """Verify Character.create is called with correct args."""
        client, mock_db, *_ = dashboard_client
        mock_char_cls.create.return_value = _make_mock_character()

        client.post("/api/characters", json={"name": "Aria", "personality_id": "pers-001"})
        mock_char_cls.create.assert_called_once_with(
            name="Aria",
            personality_id="pers-001",
            db=mock_db,
        )


class TestCharactersGetOne:
    """GET /api/characters/<id> — get single character."""

    @patch("content.scenes.dashboard.dashboard_scene.Character")
    def test_get_existing_returns_200(self, mock_char_cls, dashboard_client):
        client, *_ = dashboard_client
        mock_char_cls.load.return_value = _make_mock_character("Lola", "char-001")
        resp = client.get("/api/characters/char-001")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Lola"

    @patch("content.scenes.dashboard.dashboard_scene.Character")
    def test_get_missing_returns_404(self, mock_char_cls, dashboard_client):
        client, *_ = dashboard_client
        mock_char_cls.load.return_value = None
        resp = client.get("/api/characters/char-missing")
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()


class TestCharactersUpdate:
    """PUT /api/characters/<id> — update character."""

    @patch("content.scenes.dashboard.dashboard_scene.Character")
    def test_update_success_returns_200(self, mock_char_cls, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_char = _make_mock_character("Lola", "char-001")
        mock_char_cls.load.return_value = mock_char
        resp = client.put("/api/characters/char-001", json={"mood": "happy"})
        assert resp.status_code == 200
        mock_char.save.assert_called_once_with(mood="happy")

    @patch("content.scenes.dashboard.dashboard_scene.Character")
    def test_update_missing_returns_404(self, mock_char_cls, dashboard_client):
        client, *_ = dashboard_client
        mock_char_cls.load.return_value = None
        resp = client.put("/api/characters/char-missing", json={"mood": "sad"})
        assert resp.status_code == 404

    def test_update_empty_body_returns_error(self, dashboard_client):
        """Empty JSON body triggers a parse error caught by the exception handler.

        The route uses ``get_json(force=True)`` which raises BadRequest on
        unparseable input.  The scene's broad ``except Exception`` catches it
        and returns 500 with an error payload.
        """
        client, *_ = dashboard_client
        resp = client.put(
            "/api/characters/char-001",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 500
        assert "error" in resp.get_json()


class TestCharactersDelete:
    """DELETE /api/characters/<id> — delete character."""

    def test_delete_success_returns_ok(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.get_character.return_value = {"id": "char-001", "name": "Lola"}
        mock_db.delete_character.return_value = True
        resp = client.delete("/api/characters/char-001")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        mock_db.delete_character.assert_called_once_with("char-001")

    def test_delete_missing_returns_404(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.get_character.return_value = None
        resp = client.delete("/api/characters/char-missing")
        assert resp.status_code == 404

    def test_delete_failure_returns_500(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.get_character.return_value = {"id": "char-001"}
        mock_db.delete_character.return_value = False
        resp = client.delete("/api/characters/char-001")
        assert resp.status_code == 500


# ──── Personalities Routes ────────────────────────────────────────────


class TestPersonalitiesList:
    """GET /api/personalities — list all personalities."""

    def test_list_returns_200(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/personalities")
        assert resp.status_code == 200

    def test_list_returns_array(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/personalities")
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Sarcastic"


class TestPersonalitiesCreate:
    """POST /api/personalities — create custom personality."""

    def test_create_requires_name_and_prompt(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.post("/api/personalities", json={"name": "Chill"})
        assert resp.status_code == 400
        assert "required" in resp.get_json()["error"].lower()

    def test_create_success_returns_201(self, dashboard_client):
        client, _, _, mock_pers, *_ = dashboard_client
        resp = client.post("/api/personalities", json={
            "name": "Brooding",
            "system_prompt": "You brood a lot.",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == "pers-new-001"
        assert data["name"] == "Brooding"
        mock_pers.create_custom.assert_called_once()

    def test_create_passes_optional_fields(self, dashboard_client):
        """Traits, communication_style, sexual_openness, values are forwarded."""
        client, _, _, mock_pers, *_ = dashboard_client
        client.post("/api/personalities", json={
            "name": "Nerd",
            "system_prompt": "You love science.",
            "traits": ["curious", "bookish"],
            "values": ["knowledge"],
            "sexual_openness": 0.2,
        })
        call_kwargs = mock_pers.create_custom.call_args
        assert call_kwargs.kwargs.get("traits") == ["curious", "bookish"] or \
               call_kwargs[1].get("traits") == ["curious", "bookish"]


class TestPersonalitiesInit:
    """POST /api/personalities/init — initialize default templates."""

    def test_init_returns_created_count(self, dashboard_client):
        client, _, _, mock_pers, *_ = dashboard_client
        resp = client.post("/api/personalities/init")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["created"] == 3
        assert len(data["ids"]) == 3
        mock_pers.initialize_defaults.assert_called_once()


# ──── Roles Routes ────────────────────────────────────────────────────


class TestRolesList:
    """GET /api/roles — list all roles."""

    def test_list_returns_200(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/roles")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert data[0]["name"] == "Bartender"


class TestRolesCreate:
    """POST /api/roles — create custom role."""

    def test_create_requires_name_and_description(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.post("/api/roles", json={"name": "Guard"})
        assert resp.status_code == 400

    def test_create_success_returns_201(self, dashboard_client):
        client, _, _, _, mock_role = dashboard_client
        resp = client.post("/api/roles", json={
            "name": "Bouncer",
            "description": "Keeps the peace.",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == "role-new-001"
        mock_role.create_custom.assert_called_once()

    def test_create_passes_optional_fields(self, dashboard_client):
        client, _, _, _, mock_role = dashboard_client
        client.post("/api/roles", json={
            "name": "Hacker",
            "description": "Breaks systems.",
            "required_traits": ["clever"],
            "context": "cyberspace",
            "scenario": "heist",
        })
        call_kwargs = mock_role.create_custom.call_args
        # Verify optional params forwarded (positional or keyword)
        assert "clever" in str(call_kwargs)


class TestRolesInit:
    """POST /api/roles/init — initialize default templates."""

    def test_init_returns_created_count(self, dashboard_client):
        client, _, _, _, mock_role = dashboard_client
        resp = client.post("/api/roles/init")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["created"] == 2
        assert len(data["ids"]) == 2
        mock_role.initialize_defaults.assert_called_once()


# ──── Memories Routes ─────────────────────────────────────────────────


class TestMemoriesList:
    """GET /api/characters/<id>/memories — list memories for a character."""

    def test_list_returns_200(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/characters/char-001/memories")
        assert resp.status_code == 200

    def test_list_returns_array(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        resp = client.get("/api/characters/char-001/memories")
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 1
        mock_db.get_character_memories.assert_called_once_with("char-001", limit=100)

    def test_list_respects_limit_param(self, dashboard_client):
        """Query param ?limit=10 should be forwarded to DB."""
        client, mock_db, *_ = dashboard_client
        client.get("/api/characters/char-001/memories?limit=10")
        mock_db.get_character_memories.assert_called_once_with("char-001", limit=10)


class TestMemoriesAdd:
    """POST /api/characters/<id>/memories — add a memory."""

    def test_add_requires_content(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.post("/api/characters/char-001/memories", json={})
        assert resp.status_code == 400
        assert "content" in resp.get_json()["error"].lower()

    def test_add_success_returns_201(self, dashboard_client):
        client, mock_db, mock_rag, *_ = dashboard_client
        resp = client.post("/api/characters/char-001/memories", json={
            "content": "Met a stranger at the docks",
            "importance": 0.7,
            "emotion": "curious",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == "mem-new-001"
        assert data["ok"] is True

    def test_add_writes_to_db_and_rag(self, dashboard_client):
        """Both DB and RAG should receive the memory."""
        client, mock_db, mock_rag, *_ = dashboard_client
        client.post("/api/characters/char-001/memories", json={
            "content": "Neon rain",
            "importance": 0.9,
        })
        mock_db.add_memory.assert_called_once_with(
            "char-001", "Neon rain", importance=0.9, emotion=None,
        )
        mock_rag.add_memory.assert_called_once()

    def test_add_succeeds_even_if_rag_fails(self, dashboard_client):
        """RAG failure should not block the 201 — DB write is canonical."""
        client, mock_db, mock_rag, *_ = dashboard_client
        mock_rag.add_memory.side_effect = RuntimeError("Embedding service down")
        resp = client.post("/api/characters/char-001/memories", json={
            "content": "Important memory",
        })
        # Should still succeed because DB write went through
        assert resp.status_code == 201


class TestMemoriesUpdate:
    """PUT /api/memories/<id> — update a memory."""

    def test_update_success_returns_ok(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.update_memory.return_value = True
        resp = client.put("/api/memories/mem-001", json={"importance": 0.95})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        mock_db.update_memory.assert_called_once_with("mem-001", importance=0.95)

    def test_update_empty_body_returns_error(self, dashboard_client):
        """Empty JSON body triggers a parse error caught by the exception handler.

        Same behavior as character update — ``get_json(force=True)`` raises
        BadRequest, caught by the broad ``except Exception`` → 500.
        """
        client, *_ = dashboard_client
        resp = client.put(
            "/api/memories/mem-001",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 500
        assert "error" in resp.get_json()

    def test_update_failure_returns_500(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.update_memory.return_value = False
        resp = client.put("/api/memories/mem-001", json={"content": "updated"})
        assert resp.status_code == 500


class TestMemoriesDelete:
    """DELETE /api/memories/<id> — delete a memory."""

    def test_delete_success_returns_ok(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.delete_memory.return_value = True
        resp = client.delete("/api/memories/mem-001")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_delete_failure_returns_500(self, dashboard_client):
        client, mock_db, *_ = dashboard_client
        mock_db.delete_memory.return_value = False
        resp = client.delete("/api/memories/mem-001")
        assert resp.status_code == 500


# ──── Memory Search Route ─────────────────────────────────────────────


class TestMemoriesSearch:
    """GET /api/characters/<id>/memories/search — semantic search."""

    def test_search_requires_q_param(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/characters/char-001/memories/search")
        assert resp.status_code == 400
        assert "q" in resp.get_json()["error"].lower()

    def test_search_empty_q_returns_400(self, dashboard_client):
        client, *_ = dashboard_client
        resp = client.get("/api/characters/char-001/memories/search?q=")
        assert resp.status_code == 400

    def test_search_returns_results(self, dashboard_client):
        client, _, mock_rag, *_ = dashboard_client
        resp = client.get("/api/characters/char-001/memories/search?q=sunset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["score"] == 0.92

    def test_search_passes_n_param(self, dashboard_client):
        """Query param ?n=3 should be forwarded to RAG."""
        client, _, mock_rag, *_ = dashboard_client
        client.get("/api/characters/char-001/memories/search?q=neon&n=3")
        mock_rag.query_memories.assert_called_once_with(
            "char-001", "neon", n_results=3, scene_id="dashboard",
        )

    def test_search_error_returns_500(self, dashboard_client):
        client, _, mock_rag, *_ = dashboard_client
        mock_rag.query_memories.side_effect = RuntimeError("Embedding down")
        resp = client.get("/api/characters/char-001/memories/search?q=test")
        assert resp.status_code == 500
        assert "error" in resp.get_json()
