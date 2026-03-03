"""Tests for engine/nexus/canvas_api.py — Flask sidecar REST API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def client():
    """Return a Flask test client with the canvas sidecar app."""
    from engine.nexus.canvas_api import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ──── Health ────

def test_health_returns_ok(client: Any) -> None:
    """GET /api/health always returns {status: ok}."""
    with patch("engine.nexus.canvas_api._get_aistudio", return_value=None), \
         patch("engine.nexus.canvas_api._get_account_manager", return_value=None), \
         patch("engine.nexus.canvas_api._get_nexus_client", return_value=None), \
         patch("engine.nexus.canvas_api._get_data_collector", return_value=None):
        resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "services" in data


# ──── Generate ────

def test_generate_calls_aistudio_client(client: Any) -> None:
    """POST /api/generate forwards prompt to AiStudioClient and returns text."""
    mock_client = MagicMock()
    mock_client.generate_with_rotation.return_value = "Hello world"

    with patch("engine.nexus.canvas_api._get_aistudio", return_value=mock_client):
        resp = client.post(
            "/api/generate",
            data=json.dumps({"prompt": "Say hello", "model": "gemini-2.0-flash"}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["text"] == "Hello world"
    assert data["model"] == "gemini-2.0-flash"
    mock_client.generate_with_rotation.assert_called_once()


def test_generate_returns_503_when_no_accounts(client: Any) -> None:
    """POST /api/generate returns 503 when generate_with_rotation returns None."""
    mock_client = MagicMock()
    mock_client.generate_with_rotation.return_value = None

    with patch("engine.nexus.canvas_api._get_aistudio", return_value=mock_client):
        resp = client.post(
            "/api/generate",
            data=json.dumps({"prompt": "test"}),
            content_type="application/json",
        )

    assert resp.status_code == 503
    assert "error" in resp.get_json()


# ──── Models ────

def test_models_returns_list(client: Any) -> None:
    """GET /api/models returns a list of model dicts."""
    mock_client = MagicMock()
    mock_client.list_models.return_value = [
        {"id": "gemini-2.0-flash", "name": "Gemini Flash", "description": "Fast", "context_window": 1048576}
    ]

    with patch("engine.nexus.canvas_api._get_aistudio", return_value=mock_client):
        resp = client.get("/api/models")

    assert resp.status_code == 200
    data = resp.get_json()
    assert "models" in data
    assert isinstance(data["models"], list)
    assert data["models"][0]["id"] == "gemini-2.0-flash"


# ──── Accounts ────

def test_accounts_returns_masked_count(client: Any) -> None:
    """GET /api/accounts returns cookie count not raw cookie values."""
    mock_manager = MagicMock()
    mock_manager.get_all_accounts.return_value = [
        {
            "account_id": "acc1",
            "service": "google",
            "cookies": {"__Secure-1PSID": "abc", "SAPISID": "xyz"},
            "is_rate_limited": False,
            "last_used": None,
            "request_count": 5,
        }
    ]
    mock_manager.account_count.return_value = 1

    with patch("engine.nexus.canvas_api._get_account_manager", return_value=mock_manager):
        resp = client.get("/api/accounts")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["available"] == 1
    acct = data["accounts"][0]
    assert acct["cookies_count"] == 2
    assert "cookies" not in acct


def test_accounts_import_har_calls_import_from_har(client: Any) -> None:
    """POST /api/accounts/import-har delegates to manager.import_from_har."""
    mock_manager = MagicMock()
    mock_manager.import_from_har.return_value = True
    mock_manager._load_account.return_value = {"cookies": {"A": "1", "B": "2"}}

    with patch("engine.nexus.canvas_api._get_account_manager", return_value=mock_manager):
        resp = client.post(
            "/api/accounts/import-har",
            data=json.dumps({"har_path": "/tmp/test.har", "account_id": "acc1"}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["account_id"] == "acc1"
    assert data["cookies_extracted"] == 2
    mock_manager.import_from_har.assert_called_once_with("/tmp/test.har", "acc1", "google")


def test_accounts_import_directory_calls_bulk_import(client: Any) -> None:
    """POST /api/accounts/import-directory delegates to manager.import_all_from_directory."""
    mock_manager = MagicMock()
    mock_manager.import_all_from_directory.return_value = 3

    with patch("engine.nexus.canvas_api._get_account_manager", return_value=mock_manager):
        resp = client.post(
            "/api/accounts/import-directory",
            data=json.dumps({"directory": "/tmp/hars"}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["accounts_imported"] == 3
    mock_manager.import_all_from_directory.assert_called_once_with("/tmp/hars", "google")


# ──── Training ────

def test_training_capture_stores_conversation(client: Any) -> None:
    """POST /api/training/capture calls collector.collect_conversation."""
    mock_collector = MagicMock()
    mock_collector.stats.return_value = {"conversational": 42}

    with patch("engine.nexus.canvas_api._get_data_collector", return_value=mock_collector):
        resp = client.post(
            "/api/training/capture",
            data=json.dumps({
                "system_prompt": "You are Lola.",
                "messages": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi!"},
                ],
                "rating": 0.9,
                "source": "runtime",
            }),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["dataset_size"] == 42
    mock_collector.collect_conversation.assert_called_once()


def test_training_capture_succeeds_when_collector_unavailable(client: Any) -> None:
    """POST /api/training/capture returns 200 even if collector is unavailable."""
    with patch("engine.nexus.canvas_api._get_data_collector", return_value=None):
        resp = client.post(
            "/api/training/capture",
            data=json.dumps({"system_prompt": "x", "messages": [], "rating": None}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is False
    assert data["dataset_size"] == 0


def test_training_stats_counts_jsonl_files(client: Any, tmp_path: Path) -> None:
    """GET /api/training/stats reads line counts from collected directory."""
    # Create fake live JSONL files
    collected = tmp_path / "collected"
    collected.mkdir()
    conv_file = collected / "conversational_live.jsonl"
    conv_file.write_text('{"id":"1"}\n{"id":"2"}\n', encoding="utf-8")

    mock_collector = MagicMock()
    mock_collector.stats.return_value = {"conversational": 2}

    with patch("engine.nexus.canvas_api._get_data_collector", return_value=mock_collector), \
         patch("engine.nexus.canvas_api._COLLECTED_DIR", collected):
        resp = client.get("/api/training/stats")

    assert resp.status_code == 200
    data = resp.get_json()
    assert "total_examples" in data
    assert "by_type" in data
    assert "conversations" in data["by_type"]


# ──── Nexus ────

def test_nexus_search_returns_results(client: Any) -> None:
    """POST /api/nexus/search returns results from NexusClient."""
    mock_nexus = MagicMock()
    mock_nexus.search.return_value = [
        {"id": "e1", "title": "Test Entry", "content": "content here", "category": "dev"}
    ]

    with patch("engine.nexus.canvas_api._get_nexus_client", return_value=mock_nexus):
        resp = client.post(
            "/api/nexus/search",
            data=json.dumps({"query": "interceptor pipeline"}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 1
    assert data["results"][0]["title"] == "Test Entry"


def test_nexus_search_falls_back_to_http(client: Any) -> None:
    """POST /api/nexus/search falls back to Nexus KMS REST when client unavailable."""
    with patch("engine.nexus.canvas_api._get_nexus_client", return_value=None), \
         patch("engine.nexus.canvas_api._nexus_search_fallback", return_value=[{"id": "r1"}]) as mock_fb:
        resp = client.post(
            "/api/nexus/search",
            data=json.dumps({"query": "test query"}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    mock_fb.assert_called_once_with("test query", 10)


def test_nexus_ask_returns_answer(client: Any) -> None:
    """POST /api/nexus/ask returns answer dict from NexusClient."""
    mock_nexus = MagicMock()
    mock_nexus.ask.return_value = {"answer": "42", "source": "cache", "confidence": 0.95}

    with patch("engine.nexus.canvas_api._get_nexus_client", return_value=mock_nexus):
        resp = client.post(
            "/api/nexus/ask",
            data=json.dumps({"question": "What is the meaning of life?"}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["answer"] == "42"
    assert data["confidence"] == 0.95


def test_nexus_add_stores_entry(client: Any) -> None:
    """POST /api/nexus/add stores an entry via NexusClient."""
    mock_nexus = MagicMock()
    mock_nexus.add_entry.return_value = {"id": "entry-123"}

    with patch("engine.nexus.canvas_api._get_nexus_client", return_value=mock_nexus):
        resp = client.post(
            "/api/nexus/add",
            data=json.dumps({"title": "My Note", "content": "Details here"}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["entry_id"] == "entry-123"
    mock_nexus.add_entry.assert_called_once_with(
        "My Note", "Details here", content_type="note", category="general"
    )


# ──── All routes return JSON ────

def test_all_routes_return_json_not_html(client: Any) -> None:
    """All API routes return application/json, not HTML error pages."""
    with patch("engine.nexus.canvas_api._get_aistudio", return_value=None), \
         patch("engine.nexus.canvas_api._get_account_manager", return_value=None), \
         patch("engine.nexus.canvas_api._get_nexus_client", return_value=None), \
         patch("engine.nexus.canvas_api._get_data_collector", return_value=None):
        endpoints = [
            ("GET", "/api/health"),
            ("GET", "/api/models"),
            ("GET", "/api/accounts"),
            ("GET", "/api/training/stats"),
        ]
        for method, path in endpoints:
            resp = client.open(path, method=method)
            content_type = resp.content_type or ""
            assert "application/json" in content_type, (
                f"{method} {path} returned {content_type!r}, expected JSON"
            )
