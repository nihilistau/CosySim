"""Tests for the Home Assistant integration client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_config():
    """Config mock with HA settings."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: {
        "homeassistant.url": "http://ha-test.local:8123",
        "homeassistant.token": "test-token-123",
        "homeassistant.notification_service": "notify.mobile_app_test",
        "homeassistant.poll_interval_seconds": 30,
        "homeassistant.auto_discover": False,
    }.get(key, default))
    return cfg


@pytest.fixture()
def ha_client(mock_config):
    """Create an HA client with mocked config."""
    with patch("engine.integrations.homeassistant.get_config", return_value=mock_config):
        from engine.integrations.homeassistant import HomeAssistantClient
        client = HomeAssistantClient()
    return client


# ── Initialization ──────────────────────────────────────────────────────


def test_client_init(ha_client):
    """Client initializes with config values."""
    assert ha_client._url == "http://ha-test.local:8123"
    assert ha_client._token == "test-token-123"
    assert ha_client._notify_service == "notify.mobile_app_test"
    assert ha_client._connected is False


def test_client_init_defaults():
    """Client uses defaults when config is empty."""
    mock_cfg = MagicMock()
    mock_cfg.get = MagicMock(side_effect=lambda key, default=None: default)
    with patch("engine.integrations.homeassistant.get_config", return_value=mock_cfg):
        from engine.integrations.homeassistant import HomeAssistantClient
        client = HomeAssistantClient()
    assert "homeassistant.local" in client._url
    assert client._token == ""


# ── Connection ──────────────────────────────────────────────────────────


def test_connect_success(ha_client):
    """Successful connect returns HA config info."""
    ha_config = {"location_name": "Home", "version": "2024.6.0"}
    with patch.object(ha_client, "_get", return_value=ha_config):
        result = ha_client.connect()
    assert result["connected"] is True
    assert result["version"] == "2024.6.0"
    assert result["location_name"] == "Home"
    assert ha_client.is_connected() is True


def test_connect_failure(ha_client):
    """Connection failure returns error dict."""
    with patch.object(ha_client, "_get", side_effect=ConnectionError("refused")):
        result = ha_client.connect()
    assert result["connected"] is False
    assert "error" in result
    assert ha_client.is_connected() is False


def test_connect_with_auto_discover(ha_client):
    """Auto-discover refreshes entities on connect."""
    ha_client._auto_discover = True
    ha_config = {"location_name": "Home", "version": "2024.6.0"}
    states = [
        {"entity_id": "light.living_room", "state": "on", "attributes": {}, "last_changed": "", "last_updated": ""},
    ]
    with patch.object(ha_client, "_get", side_effect=[ha_config, states]):
        result = ha_client.connect()
    assert result["connected"] is True
    assert result["entities_discovered"] == 1


# ── Entity Operations ──────────────────────────────────────────────────


def test_refresh_entities(ha_client):
    """Refresh entities populates the cache."""
    states = [
        {"entity_id": "light.kitchen", "state": "off", "attributes": {"brightness": 100}, "last_changed": "t1", "last_updated": "t2"},
        {"entity_id": "sensor.temp", "state": "21.5", "attributes": {"unit": "°C"}, "last_changed": "t3", "last_updated": "t4"},
    ]
    with patch.object(ha_client, "_get", return_value=states):
        count = ha_client.refresh_entities()
    assert count == 2
    assert "light.kitchen" in ha_client._entities
    assert ha_client._entities["sensor.temp"]["state"] == "21.5"


def test_get_state(ha_client):
    """Get state returns single entity state."""
    entity = {"entity_id": "switch.tv", "state": "on", "attributes": {}}
    with patch.object(ha_client, "_get", return_value=entity):
        state = ha_client.get_state("switch.tv")
    assert state["state"] == "on"


def test_get_state_not_found(ha_client):
    """Get state returns None for missing entity."""
    from urllib.error import HTTPError
    from io import BytesIO
    exc = HTTPError("url", 404, "Not Found", {}, BytesIO(b"not found"))
    with patch.object(ha_client, "_get", side_effect=exc):
        state = ha_client.get_state("nonexistent.entity")
    assert state is None


def test_list_entities(ha_client):
    """List entities filters by domain."""
    ha_client._entities = {
        "light.kitchen": {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
        "light.bedroom": {"entity_id": "light.bedroom", "state": "off", "attributes": {}},
        "sensor.temp": {"entity_id": "sensor.temp", "state": "22", "attributes": {}},
    }
    lights = ha_client.list_entities(domain="light")
    assert len(lights) == 2
    all_ents = ha_client.list_entities()
    assert len(all_ents) == 3


def test_list_entities_search(ha_client):
    """List entities filters by search term."""
    ha_client._entities = {
        "light.kitchen": {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kitchen Light"}},
        "sensor.kitchen_temp": {"entity_id": "sensor.kitchen_temp", "state": "22", "attributes": {"friendly_name": "Kitchen Temp"}},
        "light.bedroom": {"entity_id": "light.bedroom", "state": "off", "attributes": {"friendly_name": "Bedroom Light"}},
    }
    results = ha_client.list_entities(search="kitchen")
    assert len(results) == 2


# ── Service Calls ──────────────────────────────────────────────────────


def test_call_service(ha_client):
    """Call service sends POST to correct endpoint."""
    with patch.object(ha_client, "_post", return_value=[]) as mock_post:
        ha_client.call_service("light", "turn_on", entity_id="light.kitchen")
    mock_post.assert_called_once()
    call_path = mock_post.call_args[0][0]
    assert "/api/services/light/turn_on" in call_path


def test_toggle(ha_client):
    """Toggle extracts domain from entity_id."""
    with patch.object(ha_client, "call_service", return_value={"success": True}) as mock:
        ha_client.toggle("light.kitchen")
    mock.assert_called_once_with("light", "toggle", entity_id="light.kitchen")


def test_turn_on(ha_client):
    """Turn on extracts domain from entity_id."""
    with patch.object(ha_client, "call_service", return_value={"success": True}) as mock:
        ha_client.turn_on("switch.tv")
    mock.assert_called_once_with("switch", "turn_on", entity_id="switch.tv", data=None)


def test_turn_off(ha_client):
    """Turn off extracts domain from entity_id."""
    with patch.object(ha_client, "call_service", return_value={"success": True}) as mock:
        ha_client.turn_off("switch.tv")
    mock.assert_called_once_with("switch", "turn_off", entity_id="switch.tv")


# ── Notifications ──────────────────────────────────────────────────────


def test_send_notification(ha_client):
    """Send notification calls correct service."""
    with patch.object(ha_client, "_post", return_value={}) as mock_post:
        result = ha_client.send_notification("Test message", title="Test Title")
    assert result["success"] is True
    assert ha_client._stats["notifications_sent"] == 1


def test_send_news_alert(ha_client):
    """Send news alert formats notification correctly."""
    with patch.object(ha_client, "send_notification", return_value={"success": True}) as mock:
        ha_client.send_news_alert("Breaking News", "Short summary", url="http://example.com")
    mock.assert_called_once()
    _, kwargs = mock.call_args
    assert "📰" in kwargs["title"]
    assert kwargs["message"] == "Short summary"


# ── Phone Sensors ──────────────────────────────────────────────────────


def test_get_phone_sensors(ha_client):
    """Get phone sensors filters sensor.sm_ entities."""
    import time
    ha_client._last_poll = time.time()  # prevent auto-refresh
    ha_client._entities = {
        "sensor.sm_s908b_battery_level": {"entity_id": "sensor.sm_s908b_battery_level", "state": "85", "attributes": {"unit": "%"}, "last_changed": "", "last_updated": ""},
        "sensor.sm_s908b_wifi_connection": {"entity_id": "sensor.sm_s908b_wifi_connection", "state": "MyWifi", "attributes": {}, "last_changed": "", "last_updated": ""},
        "light.kitchen": {"entity_id": "light.kitchen", "state": "on", "attributes": {}, "last_changed": "", "last_updated": ""},
    }
    sensors = ha_client.get_phone_sensors()
    assert len(sensors) == 2


# ── System Metrics ─────────────────────────────────────────────────────


def test_push_system_metrics(ha_client):
    """Push metrics posts to HA states API."""
    metrics = {"nexus_entries": 500, "test_count": 4000}
    with patch.object(ha_client, "_post", return_value={}) as mock_post:
        result = ha_client.push_system_metrics(metrics)
    assert result["pushed"] == 2
    assert mock_post.call_count == 2


# ── Status ─────────────────────────────────────────────────────────────


def test_status(ha_client):
    """Status returns connection info and stats."""
    status = ha_client.status()
    assert "connected" in status
    assert "url" in status
    assert "requests" in status
    assert status["connected"] is False


def test_status_connected(ha_client):
    """Status reflects connection state."""
    ha_client._connected = True
    ha_client._entities = {"light.x": {}}
    status = ha_client.status()
    assert status["connected"] is True
    assert status["entities_cached"] == 1


# ── Singleton ──────────────────────────────────────────────────────────


def test_singleton():
    """get_ha_client returns singleton."""
    mock_cfg = MagicMock()
    mock_cfg.get = MagicMock(side_effect=lambda key, default=None: {
        "homeassistant.url": "http://test.local:8123",
        "homeassistant.token": "t",
        "homeassistant.notification_service": "notify.test",
        "homeassistant.poll_interval_seconds": 30,
        "homeassistant.auto_discover": False,
    }.get(key, default))
    with patch("engine.integrations.homeassistant.get_config", return_value=mock_cfg):
        import engine.integrations.homeassistant as ha_mod
        ha_mod._instance = None
        c1 = ha_mod.get_ha_client()
        c2 = ha_mod.get_ha_client()
        assert c1 is c2
        ha_mod._instance = None  # cleanup


# ── HTTP Layer ─────────────────────────────────────────────────────────


def test_request_adds_auth_header(ha_client):
    """Requests include Bearer token header."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"ok": true}'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("engine.integrations.homeassistant.urlopen", return_value=mock_resp) as mock_open:
        ha_client._request("GET", "/api/config")
    req_obj = mock_open.call_args[0][0]
    assert req_obj.get_header("Authorization") == "Bearer test-token-123"


def test_request_tracks_stats(ha_client):
    """Requests increment stats counters."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{}'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    initial = ha_client._stats["requests"]
    with patch("engine.integrations.homeassistant.urlopen", return_value=mock_resp):
        ha_client._get("/api/test")
    assert ha_client._stats["requests"] == initial + 1


def test_request_tracks_errors(ha_client):
    """Failed requests increment error counter."""
    from urllib.error import URLError
    initial = ha_client._stats["errors"]
    with patch("engine.integrations.homeassistant.urlopen", side_effect=URLError("fail")):
        with pytest.raises(URLError):
            ha_client._get("/api/fail")
    assert ha_client._stats["errors"] == initial + 1


# ── Automation ─────────────────────────────────────────────────────────


def test_trigger_automation(ha_client):
    """Trigger automation calls correct service."""
    with patch.object(ha_client, "call_service", return_value={"ok": True}) as mock:
        ha_client.trigger_automation("automation.night_mode")
    mock.assert_called_once_with(
        "automation", "trigger",
        entity_id="automation.night_mode",
    )


# ── Listeners ──────────────────────────────────────────────────────────


def test_add_state_listener(ha_client):
    """Listeners can be added for state changes."""
    callback = MagicMock()
    ha_client.add_state_listener(callback)
    assert callback in ha_client._listeners


def test_poll_changes_notifies_listeners(ha_client):
    """Poll changes detects state changes and notifies listeners."""
    callback = MagicMock()
    ha_client.add_state_listener(callback)
    ha_client._entities = {
        "light.kitchen": {"entity_id": "light.kitchen", "state": "off", "attributes": {}},
    }
    new_states = [
        {"entity_id": "light.kitchen", "state": "on", "attributes": {}, "last_changed": "", "last_updated": ""},
    ]
    with patch.object(ha_client, "_get", return_value=new_states):
        changes = ha_client.poll_changes()
    assert len(changes) > 0
    assert callback.call_count > 0


# ── Domains ────────────────────────────────────────────────────────────


def test_list_domains(ha_client):
    """List domains extracts unique domains from entities."""
    ha_client._entities = {
        "light.a": {"entity_id": "light.a"},
        "light.b": {"entity_id": "light.b"},
        "sensor.c": {"entity_id": "sensor.c"},
        "switch.d": {"entity_id": "switch.d"},
    }
    domains = ha_client.domains()
    assert set(domains) == {"light", "sensor", "switch"}
