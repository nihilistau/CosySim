"""Tests for Intel Hub scene."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def hub_app():
    """Intel Hub Flask test client."""
    mock_config = MagicMock()
    mock_config.get = MagicMock(side_effect=lambda key, default=None: {
        "intel_hub.port": 5580,
        "nexus.host": "localhost",
        "nexus.port": 8700,
    }.get(key, default))

    with patch("engine.config.get_config", return_value=mock_config):
        with patch("engine.mcp.get_framework", return_value=MagicMock()):
            with patch("engine.mcp.get_character_registry", return_value=MagicMock()):
                with patch("engine.mcp.get_dialog_system", return_value=MagicMock()):
                    with patch("engine.nexus.client.get_nexus_client", return_value=MagicMock()):
                        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
                        scene = IntelHubScene.__new__(IntelHubScene)
                        scene.app = MagicMock()
                        scene.config = mock_config
                        yield scene


class TestIntelHubScene:
    def test_scene_metadata(self):
        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
        assert hasattr(IntelHubScene, "SCENE_METADATA")
        assert IntelHubScene.SCENE_METADATA.get("type") == "admin"
        assert "Intelligence Hub" in IntelHubScene.SCENE_METADATA.get("title", "")

    def test_scene_package_has_init(self):
        """Package is importable."""
        import content.scenes.intel_hub
        assert content.scenes.intel_hub is not None

    def test_skills_module_importable(self):
        from content.scenes.intel_hub import intel_hub_skills
        assert intel_hub_skills is not None

    def test_skills_have_skill_decorator(self):
        from content.scenes.intel_hub.intel_hub_skills import (
            intel_hub_status,
            intel_hub_cache_status,
        )
        assert callable(intel_hub_status)
        assert callable(intel_hub_cache_status)


class TestIntelHubConfig:
    def test_port_in_default_yaml(self):
        import yaml
        from pathlib import Path
        cfg_path = Path("config/default.yaml")
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text())
            intel_hub_cfg = cfg.get("scenes", {}).get("intel_hub", {})
            assert intel_hub_cfg.get("port") == 5580
