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
        assert "grid" in scenes
        assert len(scenes) == 18

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


class TestCanonicalControlPlaneHelpers:
    def test_aliases_resolve_to_canonical_ports(self):
        reg = _fresh_registry()
        assert reg.get("qwen3_tts") == reg.get("tts") == 8600
        assert reg.get("web_bridge") == reg.get("bridge") == 8601
        assert reg.get("notebooklm_proxy") == reg.get("nlm_proxy") == 8800

    def test_build_scene_port_map_matches_launcher_truth(self):
        from engine.port_registry import build_scene_port_map

        scene_ports = build_scene_port_map()
        assert scene_ports[5565] == "heist"
        assert scene_ports[5566] == "command_center"
        assert scene_ports[5567] == "games"
        assert scene_ports[5568] == "asset_studio"
        assert scene_ports[5575] == "system_control"
        assert scene_ports[5580] == "intel_hub"

    def test_build_scene_listing_has_correct_phone_and_bedroom_ports(self):
        from engine.port_registry import build_scene_listing

        scenes = {scene["id"]: scene for scene in build_scene_listing()}
        assert scenes["bedroom"]["port"] == 5556
        assert scenes["bedroom"]["name"] == "THE PENTHOUSE"
        assert scenes["phone"]["port"] == 5555
        assert scenes["phone"]["name"] == "SIGNAL"

    def test_build_health_endpoints_uses_canonical_urls(self):
        from engine.port_registry import build_health_endpoints

        endpoints = {endpoint["id"]: endpoint for endpoint in build_health_endpoints()}
        assert endpoints["command_center"]["port"] == 5566
        assert endpoints["command_center"]["url"] == "http://localhost:5566/api/health"
        assert endpoints["tts"]["url"] == "http://localhost:8600/health"
        assert endpoints["lmstudio"]["url"] == "http://localhost:1234/api/v1/models"

    def test_build_target_listing_includes_health_url_metadata(self):
        from engine.port_registry import build_target_listing

        targets = {target["id"]: target for target in build_target_listing(("lmstudio", "bedroom"))}
        assert targets["lmstudio"]["health_url"] == "http://localhost:1234/api/v1/models"
        assert targets["bedroom"]["health_url"] == "http://localhost:5556/api/health"

    def test_hub_catalogue_targets_include_new_control_plane_surfaces(self):
        from engine.port_registry import HUB_CATALOGUE_TARGETS

        assert "grid" in HUB_CATALOGUE_TARGETS
        assert "asset_studio" in HUB_CATALOGUE_TARGETS
        assert "system_control" in HUB_CATALOGUE_TARGETS
