"""Tests for OracleScene — Neural Consciousness Terminal.
=========================================================

Covers:
- SCENE_METADATA structure validation
- Class import verification
- Route registration (GET /, GET /api/scene/state)
- Observability routes (GET /api/oracle/health, GET /api/oracle/errors,
  GET /api/oracle/errors/rate, GET /api/oracle/trace/<id>,
  GET /api/oracle/logs, GET /api/oracle/diagnose)
- State builder (_build_state)
- LLM helper methods (_generate_response, _extract_insight)
- Cross-scene arrival greeting

Version: v1.49.5 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.5 [2026-03-22] — Initial test suite for OracleScene
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


# ──── Fixtures ────────────────────────────────────────────────────────


def _make_mock_player_state() -> MagicMock:
    """Build a mock PlayerState with sensible defaults.

    Returns:
        Configured MagicMock mimicking PlayerState.
    """
    ps = MagicMock()
    ps.credits = 5000
    ps.health = 85
    ps.energy = 70
    ps.heat = 15
    ps.reputation = 42
    ps.spend_credits = MagicMock()
    return ps


# v1.49.5 [2026-03-22] — Central fixture: mock PlayerState and engine deps
# CONNECTS: PlayerState, FlaskScene, LMStudio
@pytest.fixture()
def oracle_client():
    """Create an OracleScene with all external dependencies mocked
    and return (test_client, scene, mock_player_state).
    """
    mock_ps = _make_mock_player_state()
    with patch("content.scenes.oracle.oracle_scene.get_player_state", return_value=mock_ps), \
         patch("content.scenes.oracle.oracle_scene.get_port", return_value=19003):
        # Patch the error feed wiring to avoid import errors
        with patch("content.scenes.oracle.oracle_scene.OracleScene._wire_oracle_error_feed"):
            from content.scenes.oracle.oracle_scene import OracleScene
            scene = OracleScene(port=19003)
            scene.app.config["TESTING"] = True
            client = scene.app.test_client()
            yield client, scene, mock_ps


# ──── Metadata ────────────────────────────────────────────────────────


class TestOracleMetadata:
    """SCENE_METADATA structure validation."""

    def test_scene_metadata_has_required_fields(self):
        with patch("content.scenes.oracle.oracle_scene.get_player_state", return_value=_make_mock_player_state()), \
             patch("content.scenes.oracle.oracle_scene.get_port", return_value=19003), \
             patch("content.scenes.oracle.oracle_scene.OracleScene._wire_oracle_error_feed"):
            from content.scenes.oracle.oracle_scene import OracleScene
            meta = OracleScene.SCENE_METADATA
            assert meta["name"] == "oracle"
            assert meta["display_name"] == "THE ORACLE"
            assert "port" in meta
            assert "accent_color" in meta
            assert "description" in meta

    def test_metadata_accent_color_is_purple(self):
        with patch("content.scenes.oracle.oracle_scene.get_player_state", return_value=_make_mock_player_state()), \
             patch("content.scenes.oracle.oracle_scene.get_port", return_value=19003), \
             patch("content.scenes.oracle.oracle_scene.OracleScene._wire_oracle_error_feed"):
            from content.scenes.oracle.oracle_scene import OracleScene
            assert OracleScene.SCENE_METADATA["accent_color"] == "#a855f7"


# ──── Import ──────────────────────────────────────────────────────────


class TestOracleImport:
    """Verify the class and constants are importable."""

    def test_class_importable(self):
        from content.scenes.oracle.oracle_scene import OracleScene
        assert OracleScene is not None

    def test_scene_id_constant(self):
        from content.scenes.oracle.oracle_scene import SCENE_ID
        assert SCENE_ID == "oracle"

    def test_fortune_templates_importable(self):
        from content.scenes.oracle.oracle_scene import _FORTUNES, _WHISPERS
        assert isinstance(_FORTUNES, list)
        assert len(_FORTUNES) > 0
        assert isinstance(_WHISPERS, list)
        assert len(_WHISPERS) > 0


# ──── Scene State Route ───────────────────────────────────────────────


class TestOracleSceneState:
    """GET /api/scene/state — scene state snapshot."""

    def test_state_returns_200(self, oracle_client):
        client, _, _ = oracle_client
        resp = client.get("/api/scene/state")
        assert resp.status_code == 200

    def test_state_contains_player_info(self, oracle_client):
        client, _, _ = oracle_client
        data = client.get("/api/scene/state").get_json()
        assert "player" in data
        player = data["player"]
        assert "credits" in player
        assert "health" in player
        assert "energy" in player
        assert "heat" in player

    def test_state_contains_scene_id(self, oracle_client):
        client, _, _ = oracle_client
        data = client.get("/api/scene/state").get_json()
        assert data["scene_id"] == "oracle"
        assert data["display_name"] == "THE ORACLE"

    def test_state_contains_city_data(self, oracle_client):
        client, _, _ = oracle_client
        data = client.get("/api/scene/state").get_json()
        assert "city" in data
        city = data["city"]
        assert "tension" in city
        assert "dominant_faction" in city

    def test_state_tracks_visit_count(self, oracle_client):
        client, _, _ = oracle_client
        data = client.get("/api/scene/state").get_json()
        assert "visits" in data


# ──── Observability Routes (All-Seeing Eye) ───────────────────────────


class TestOracleHealthRoute:
    """GET /api/oracle/health — system health endpoint."""

    def test_health_returns_ok_with_monitor(self, oracle_client):
        client, _, _ = oracle_client
        mock_monitor = MagicMock()
        mock_monitor.snapshot.return_value = {"cpu": 42, "ram_mb": 2048}
        mock_monitor.check_services.return_value = {
            "lmstudio": {"up": True, "latency_ms": 12},
            "nexus": {"up": False, "error": "Connection refused"},
        }
        with patch("content.scenes.oracle.oracle_scene.get_system_monitor", return_value=mock_monitor):
            resp = client.get("/api/oracle/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "system" in data
        assert "services" in data

    def test_health_returns_500_on_error(self, oracle_client):
        """When monitor import fails, should return 500."""
        client, _, _ = oracle_client
        # The default (no mock for get_system_monitor) will cause an ImportError
        # which the route catches and returns 500
        resp = client.get("/api/oracle/health")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["ok"] is False


class TestOracleErrorsRoute:
    """GET /api/oracle/errors — error aggregator snapshot."""

    def test_errors_returns_data_with_aggregator(self, oracle_client):
        client, _, _ = oracle_client
        mock_agg = MagicMock()
        mock_agg.snapshot.return_value = {"top_errors": [], "total": 0}
        with patch("content.scenes.oracle.oracle_scene.get_error_aggregator", return_value=mock_agg):
            resp = client.get("/api/oracle/errors")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "top_errors" in data

    def test_errors_returns_500_when_unavailable(self, oracle_client):
        """When error aggregator is not available, returns 500."""
        client, _, _ = oracle_client
        resp = client.get("/api/oracle/errors")
        assert resp.status_code == 500


class TestOracleErrorRateRoute:
    """GET /api/oracle/errors/rate — error rate over window."""

    def test_error_rate_with_window_param(self, oracle_client):
        client, _, _ = oracle_client
        mock_agg = MagicMock()
        mock_agg.get_error_rate.return_value = {"rate": 0.05, "window": 300}
        with patch("content.scenes.oracle.oracle_scene.get_error_aggregator", return_value=mock_agg):
            resp = client.get("/api/oracle/errors/rate?window=600")
        assert resp.status_code == 200


class TestOracleTraceRoute:
    """GET /api/oracle/trace/<trace_id> — trace waterfall."""

    def test_trace_returns_events(self, oracle_client):
        client, _, _ = oracle_client
        mock_logger = MagicMock()
        mock_event = MagicMock()
        mock_event.timestamp = "2026-03-22T12:00:00"
        mock_event.level = "ERROR"
        mock_event.service = "lmstudio"
        mock_event.message = "Connection timeout"
        mock_event.duration_ms = 5000
        mock_event.span_id = "span-001"
        mock_logger.get_trace.return_value = [mock_event]
        with patch("content.scenes.oracle.oracle_scene.get_structured_logger", return_value=mock_logger):
            resp = client.get("/api/oracle/trace/trace-abc123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["trace_id"] == "trace-abc123"
        assert data["count"] == 1
        assert len(data["events"]) == 1


class TestOracleLogsRoute:
    """GET /api/oracle/logs — query structured logs."""

    def test_logs_returns_filtered_results(self, oracle_client):
        client, _, _ = oracle_client
        mock_logger = MagicMock()
        mock_entry = MagicMock()
        mock_entry.timestamp = "2026-03-22T12:00:00"
        mock_entry.level = "ERROR"
        mock_entry.service = "nexus"
        mock_entry.message = "Failed to connect"
        mock_logger.query.return_value = [mock_entry]
        with patch("content.scenes.oracle.oracle_scene.get_structured_logger", return_value=mock_logger):
            resp = client.get("/api/oracle/logs?level=ERROR&limit=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1


class TestOracleDiagnoseRoute:
    """GET /api/oracle/diagnose — full diagnostic snapshot."""

    def test_diagnose_returns_ok(self, oracle_client):
        client, _, _ = oracle_client
        mock_result = {"services": {}, "errors": 0, "uptime": 3600}
        with patch("content.scenes.oracle.oracle_scene.diagnose", return_value=mock_result):
            resp = client.get("/api/oracle/diagnose")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True


# ──── LLM Helpers ─────────────────────────────────────────────────────


class TestOracleExtractInsight:
    """Test _extract_insight helper."""

    def test_extract_first_sentence_with_period(self, oracle_client):
        _, scene, _ = oracle_client
        result = scene._extract_insight("The city burns. Nothing remains.")
        assert result == "The city burns."

    def test_extract_first_sentence_with_exclamation(self, oracle_client):
        _, scene, _ = oracle_client
        result = scene._extract_insight("Beware! The factions are shifting.")
        assert result == "Beware!"

    def test_extract_truncates_long_text_without_punctuation(self, oracle_client):
        _, scene, _ = oracle_client
        long_text = "a" * 200
        result = scene._extract_insight(long_text)
        assert len(result) <= 84  # 80 + "..."


# ──── Cross-Scene Arrival ─────────────────────────────────────────────


class TestOracleArrival:
    """Test on_player_arrival greetings."""

    def test_arrival_from_known_location(self, oracle_client):
        """Known locations should produce specific greetings."""
        _, scene, _ = oracle_client
        scene.socketio = MagicMock()
        scene.on_player_arrival("THE GRID", {})
        scene.socketio.emit.assert_called_once()
        args = scene.socketio.emit.call_args
        assert args[0][0] == "oracle_response"
        assert "data streams" in args[0][1]["text"]

    def test_arrival_from_unknown_location(self, oracle_client):
        """Unknown locations should produce a generic greeting."""
        _, scene, _ = oracle_client
        scene.socketio = MagicMock()
        scene.on_player_arrival("UNKNOWN PLACE", {})
        scene.socketio.emit.assert_called_once()
        args = scene.socketio.emit.call_args
        assert "UNKNOWN PLACE" in args[0][1]["text"]
