"""Tests for SDK gap methods added to engine.integrations.aistudio_client.

Covers the 18 new MakerSuiteService methods extracted from HAR 2026-03-05.
All network calls are mocked — no real HTTP traffic.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.aistudio_client import AIStudioClient, get_aistudio_client


# ──── Fixtures ────────────────────────────────────────────────────────────────

FAKE_COOKIES = {"SAPISID": "test_sapisid", "SID": "test_sid"}


@pytest.fixture
def client() -> AIStudioClient:
    """AIStudioClient with fake cookies — no real HTTP."""
    return AIStudioClient(cookies=FAKE_COOKIES)


def _mock_post(client: AIStudioClient, response: dict) -> MagicMock:
    """Patch _post_safe to return a fixed response dict."""
    m = MagicMock(return_value=response)
    client._post_safe = m  # type: ignore[method-assign]
    return m


# ──── Code Assistant ──────────────────────────────────────────────────────────

def test_code_assistant_offline_calls_correct_method(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"result": "ok"})
    req = {"prompt": "def foo():", "language": "python"}
    result = client.code_assistant_offline(req)
    assert result == {"result": "ok"}
    mock.assert_called_once_with("CodeAssistantOffline", req)


def test_stream_code_assistant_offline_upload(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"ack": True})
    result = client.stream_code_assistant_offline_upload("gen-123", b"\x00\x01\x02")
    assert result["ack"] is True
    call_args = mock.call_args[0]
    assert call_args[0] == "StreamCodeAssistantOfflineGenerationUpload"
    assert call_args[1]["generationId"] == "gen-123"
    assert call_args[1]["chunk"] == "000102"  # hex of b"\x00\x01\x02"


def test_get_code_assistant_snapshot(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"snapshotId": "snap-456", "data": {}})
    result = client.get_code_assistant_snapshot("snap-456")
    assert result["snapshotId"] == "snap-456"
    mock.assert_called_once_with("GetCodeAssistantSnapshot", {"snapshotId": "snap-456"})


def test_load_code_assistant_interaction_history(client: AIStudioClient) -> None:
    interactions = [{"id": "i1"}, {"id": "i2"}]
    _mock_post(client, {"interactions": interactions})
    result = client.load_code_assistant_interaction_history("sess-99")
    assert result == {"interactions": interactions}


def test_list_code_assistant_configurations(client: AIStudioClient) -> None:
    configs = [{"id": "cfg-1", "name": "default"}]
    _mock_post(client, {"configurations": configs})
    result = client.list_code_assistant_configurations()
    assert result == configs


def test_list_code_assistant_features(client: AIStudioClient) -> None:
    features = [{"name": "inline_complete", "enabled": True}]
    _mock_post(client, {"features": features})
    result = client.list_code_assistant_features()
    assert result == features


def test_list_code_assistant_offline_generations(client: AIStudioClient) -> None:
    gens = [{"id": "g1"}, {"id": "g2"}]
    _mock_post(client, {"generations": gens})
    result = client.list_code_assistant_offline_generations(page_size=10)
    assert result == gens


def test_list_code_gen_suggestion_cards(client: AIStudioClient) -> None:
    cards = [{"title": "Fix bug", "prompt": "Fix the error in this code"}]
    _mock_post(client, {"cards": cards})
    result = client.list_code_gen_suggestion_cards(context="bugfix")
    assert result == cards


def test_generate_code_assistant_suggestion_chips(client: AIStudioClient) -> None:
    chips = ["Explain this", "Refactor", "Add tests"]
    _mock_post(client, {"chips": chips})
    result = client.generate_code_assistant_suggestion_chips("write a sort function")
    assert result == chips


# ──── Applet management ────────────────────────────────────────────────────────

def test_list_recent_applets(client: AIStudioClient) -> None:
    applets = [{"name": "applets/abc"}, {"name": "applets/def"}]
    _mock_post(client, {"applets": applets})
    result = client.list_recent_applets(limit=5)
    assert result == applets


def test_store_recent_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"stored": True})
    result = client.store_recent_applet("applets/xyz")
    assert result["stored"] is True
    mock.assert_called_once_with("StoreRecentApplet", {"appletName": "applets/xyz"})


def test_save_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "applets/xyz", "version": 2})
    result = client.save_applet("applets/xyz", {"displayName": "My App"})
    assert result["version"] == 2
    mock.assert_called_once_with(
        "SaveApplet",
        {"appletName": "applets/xyz", "updates": {"displayName": "My App"}},
    )


def test_list_unset_applet_secrets(client: AIStudioClient) -> None:
    _mock_post(client, {"secretKeys": ["API_KEY", "DB_PASS"]})
    result = client.list_unset_applet_secrets("applets/xyz")
    assert result == ["API_KEY", "DB_PASS"]


def test_provision_and_initialize_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"status": "PROVISIONED"})
    config = {"displayName": "test app", "template": "blank"}
    result = client.provision_and_initialize_applet(config)
    assert result["status"] == "PROVISIONED"
    mock.assert_called_once_with("ProvisionAndInitializeApplet", config)


# ──── Projects & billing ──────────────────────────────────────────────────────

def test_list_imported_projects(client: AIStudioClient) -> None:
    projects = [{"projectId": "proj-123", "displayName": "My Project"}]
    _mock_post(client, {"projects": projects})
    result = client.list_imported_projects()
    assert result == projects


def test_list_promos(client: AIStudioClient) -> None:
    promos = [{"promoId": "TRIAL", "credits": 300}]
    _mock_post(client, {"promos": promos})
    result = client.list_promos()
    assert result == promos


# ──── Logging / metrics ───────────────────────────────────────────────────────

def test_log_event_calls_correct_method(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.log_event("page_view", {"page": "/home"})
    mock.assert_called_once_with("Log", {"eventType": "page_view", "payload": {"page": "/home"}})


def test_log_event_without_payload(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.log_event("session_start")
    call_body = mock.call_args[0][1]
    assert "payload" not in call_body
    assert call_body["eventType"] == "session_start"


def test_fetch_metric_time_series(client: AIStudioClient) -> None:
    data_points = [{"timestamp": "2026-03-05T00:00:00Z", "value": 42}]
    mock = _mock_post(client, {"dataPoints": data_points})
    result = client.fetch_metric_time_series(
        "token_count",
        start_time="2026-03-04T00:00:00Z",
        granularity="DAY",
    )
    assert result == data_points
    call_body = mock.call_args[0][1]
    assert call_body["metricName"] == "token_count"
    assert call_body["granularity"] == "DAY"
    assert call_body["startTime"] == "2026-03-04T00:00:00Z"


def test_fetch_metric_time_series_defaults(client: AIStudioClient) -> None:
    _mock_post(client, {"dataPoints": []})
    result = client.fetch_metric_time_series("request_count")
    assert result == []


# ──── Singleton ───────────────────────────────────────────────────────────────

def test_get_aistudio_client_returns_instance() -> None:
    import engine.integrations.aistudio_client as _mod
    _mod._client = None
    with patch(
        "engine.integrations.google_account_pool.get_account_pool",
        side_effect=ImportError,
    ):
        c = get_aistudio_client(cookies=FAKE_COOKIES)
    _mod._client = None  # reset singleton
    assert isinstance(c, AIStudioClient)
