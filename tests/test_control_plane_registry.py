"""Tests for the shared control-plane target catalogue."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from engine.control_plane_registry import (
    SCENE_IDS,
    SERVICE_IDS,
    build_launcher_catalogues,
    get_launcher_catalogue_templates,
    get_target_metadata_catalogue,
)


def _port_resolver(target_id: str) -> int:
    """Return a deterministic fake port for each shared control-plane target."""
    all_ids = (*SERVICE_IDS, *SCENE_IDS)
    return 4000 + all_ids.index(target_id)


class TestControlPlaneTemplates:
    def test_get_launcher_catalogue_templates_returns_fresh_copies(self) -> None:
        """Template lookups should not share mutable state across callers."""
        first = get_launcher_catalogue_templates()
        first["services"]["hub"]["label"] = "Changed"

        second = get_launcher_catalogue_templates()
        assert second["services"]["hub"]["label"] == "CosySim Hub"

    def test_target_metadata_catalogue_tracks_service_and_scene_groups(self) -> None:
        """Shared target metadata should expose the canonical launcher grouping."""
        metadata = get_target_metadata_catalogue()

        assert metadata["hub"]["group"] == "service"
        assert metadata["bedroom"]["group"] == "scene"
        assert metadata["canvas"]["label"] == "Nexus Canvas"


class TestBuildLauncherCatalogues:
    def test_build_launcher_catalogues_resolves_ports(self) -> None:
        """Generated launcher catalogues should apply the provided port resolver."""
        services, scenes, all_targets = build_launcher_catalogues(_port_resolver)

        assert services["hub"]["port"] == _port_resolver("hub")
        assert scenes["bedroom"]["port"] == _port_resolver("bedroom")
        assert all_targets["canvas"]["port"] == _port_resolver("canvas")

    def test_build_launcher_catalogues_applies_launcher_yaml_overrides(self, tmp_path: Path) -> None:
        """launcher.yaml auto_start overrides should be reflected in built catalogues."""
        launcher_yaml = tmp_path / "launcher.yaml"
        launcher_yaml.write_text(
            "services:\n"
            "  hub:\n"
            "    auto_start: false\n"
            "scenes:\n"
            "  bedroom:\n"
            "    auto_start: false\n",
            encoding="utf-8",
        )

        with patch("engine.control_plane_registry.LAUNCHER_CONFIG_PATH", launcher_yaml):
            services, scenes, all_targets = build_launcher_catalogues(_port_resolver)

        assert services["hub"]["auto_start"] is False
        assert scenes["bedroom"]["auto_start"] is False
        assert all_targets["hub"]["auto_start"] is False
