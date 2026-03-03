"""Tests for the centralised port registry."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────

def _fresh_registry():
    """Create a fresh PortRegistry bypassing config loading."""
    with patch("engine.port_registry.PortRegistry._load_from_config"):
        from engine.port_registry import PortRegistry
        return PortRegistry()


# ── Core Lookup ──────────────────────────────────────────────────

class TestPortLookup:
    def test_get_known_service(self):
        reg = _fresh_registry()
        assert reg.get("phone") == 5555

    def test_get_unknown_with_default(self):
        reg = _fresh_registry()
        assert reg.get("nonexistent", 9999) == 9999

    def test_get_unknown_raises(self):
        reg = _fresh_registry()
        with pytest.raises(KeyError, match="nonexistent"):
            reg.get("nonexistent")

    def test_all_default_ports_present(self):
        reg = _fresh_registry()
        ports = reg.all_ports()
        assert len(ports) >= 25
        assert "bedroom" in ports
        assert "lmstudio" in ports
        assert "orpheus_tts" in ports

    def test_get_url(self):
        reg = _fresh_registry()
        url = reg.get_url("lmstudio", path="/v1")
        assert url == "http://localhost:1234/v1"

    def test_get_url_custom_scheme(self):
        reg = _fresh_registry()
        url = reg.get_url("nexus", scheme="https")
        assert url == "https://localhost:8700"


# ── Registration ─────────────────────────────────────────────────

class TestRegistration:
    def test_register_new_service(self):
        reg = _fresh_registry()
        reg.register("my_service", 7777)
        assert reg.get("my_service") == 7777

    def test_register_overrides_existing(self):
        reg = _fresh_registry()
        reg.register("phone", 6000)
        assert reg.get("phone") == 6000


# ── Conflict Detection ──────────────────────────────────────────

class TestConflictDetection:
    def test_no_conflicts_in_defaults(self):
        reg = _fresh_registry()
        assert reg.find_conflicts() == []

    def test_detects_conflict(self):
        reg = _fresh_registry()
        reg.register("my_service", 5555)  # same as phone
        conflicts = reg.find_conflicts()
        assert len(conflicts) == 1
        ports = [c[2] for c in conflicts]
        assert 5555 in ports

    def test_multiple_conflicts(self):
        reg = _fresh_registry()
        reg.register("svc_a", 5555)
        reg.register("svc_b", 5555)
        conflicts = reg.find_conflicts()
        assert len(conflicts) >= 1


# ── Groups ───────────────────────────────────────────────────────

class TestGroups:
    def test_scenes_group(self):
        reg = _fresh_registry()
        scenes = reg.for_group("scenes")
        assert "phone" in scenes
        assert "bedroom" in scenes
        assert len(scenes) == 17

    def test_tts_group(self):
        reg = _fresh_registry()
        tts = reg.for_group("tts")
        assert "qwen3_tts" in tts
        assert "orpheus_tts" in tts
        assert len(tts) == 4

    def test_unknown_group(self):
        reg = _fresh_registry()
        assert reg.for_group("nonexistent") == {}


# ── Summary ──────────────────────────────────────────────────────

class TestSummary:
    def test_summary_format(self):
        reg = _fresh_registry()
        s = reg.summary()
        assert "SCENES" in s
        assert "phone" in s
        assert ":5555" in s


# ── Config Integration ───────────────────────────────────────────

class TestConfigIntegration:
    def test_loads_scene_port_from_config(self):
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda key, *args: {
            "scenes.phone.port": 6000,
            "scenes.bedroom.port": 6001,
        }.get(key, args[0] if args else None)

        with patch("engine.config.get_config", return_value=mock_cfg):
            from engine.port_registry import PortRegistry
            reg = PortRegistry()
        assert reg.get("phone") == 6000
        assert reg.get("bedroom") == 6001

    def test_loads_lmstudio_port(self):
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda key, *args: {
            "lmstudio.port": 5678,
        }.get(key, args[0] if args else None)

        with patch("engine.config.get_config", return_value=mock_cfg):
            from engine.port_registry import PortRegistry
            reg = PortRegistry()
        assert reg.get("lmstudio") == 5678

    def test_config_unavailable_uses_defaults(self):
        with patch.dict("sys.modules", {"engine.config": None}):
            from engine.port_registry import PortRegistry
            reg = PortRegistry()
        assert reg.get("phone") == 5555


# ── Convenience Functions ────────────────────────────────────────

class TestConvenienceFunctions:
    def test_get_port_function(self):
        with patch("engine.port_registry._registry", None):
            with patch("engine.port_registry.PortRegistry._load_from_config"):
                from engine.port_registry import get_port
                assert get_port("bedroom") == 5556

    def test_get_service_url_function(self):
        with patch("engine.port_registry._registry", None):
            with patch("engine.port_registry.PortRegistry._load_from_config"):
                from engine.port_registry import get_service_url
                url = get_service_url("nexus", path="/api/health")
                assert url == "http://localhost:8700/api/health"
