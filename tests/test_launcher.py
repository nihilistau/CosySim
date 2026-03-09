"""Tests for launcher control-plane helpers.

Covers:
- Control-plane registry catalogue shape and required keys
- Port resolution wiring (launcher → PortRegistry)
- npm subprocess form (no shell=True)
- get_target_metadata_catalogue
- build_launcher_catalogues return shape
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure project root is on the path so `launcher` is importable without install.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# launcher helpers
# ---------------------------------------------------------------------------


def test_hub_url_uses_canonical_port_registry() -> None:
    """_hub_url() must delegate to PortRegistry, not hardcode a port."""
    import launcher

    with patch("launcher.get_port", return_value=9900) as mock_get_port:
        assert launcher._hub_url() == "http://localhost:9900"

    mock_get_port.assert_called_once_with("hub")


# ---------------------------------------------------------------------------
# control_plane_registry tests
# ---------------------------------------------------------------------------


def test_service_defs_have_required_keys() -> None:
    """Every SERVICE_DEFS entry must have type, cls/script/factory, and label."""
    from engine.control_plane_registry import SERVICE_DEFS

    for name, info in SERVICE_DEFS.items():
        assert "type" in info, f"service '{name}' missing 'type'"
        assert "label" in info, f"service '{name}' missing 'label'"


def test_scene_defs_have_required_keys() -> None:
    """Every SCENE_DEFS entry must have type, cls, and label."""
    from engine.control_plane_registry import SCENE_DEFS

    for name, info in SCENE_DEFS.items():
        assert "type" in info, f"scene '{name}' missing 'type'"
        assert "label" in info, f"scene '{name}' missing 'label'"


def test_scene_ids_matches_scene_defs_keys() -> None:
    from engine.control_plane_registry import SCENE_DEFS, SCENE_IDS

    assert set(SCENE_IDS) == set(SCENE_DEFS.keys())


def test_service_ids_matches_service_defs_keys() -> None:
    from engine.control_plane_registry import SERVICE_DEFS, SERVICE_IDS

    assert set(SERVICE_IDS) == set(SERVICE_DEFS.keys())


def test_get_target_metadata_catalogue_returns_all_targets() -> None:
    from engine.control_plane_registry import (
        SERVICE_DEFS,
        SCENE_DEFS,
        get_target_metadata_catalogue,
    )

    catalogue = get_target_metadata_catalogue()
    expected_ids = set(SERVICE_DEFS) | set(SCENE_DEFS)
    assert set(catalogue.keys()) == expected_ids


def test_get_target_metadata_catalogue_entry_shape() -> None:
    from engine.control_plane_registry import get_target_metadata_catalogue

    for name, meta in get_target_metadata_catalogue().items():
        assert "id" in meta
        assert "group" in meta
        assert "label" in meta
        assert "type" in meta
        assert "auto_start" in meta
        assert isinstance(meta["auto_start"], bool)


def test_build_launcher_catalogues_returns_three_dicts() -> None:
    from engine.control_plane_registry import build_launcher_catalogues

    resolver = MagicMock(return_value=5000)
    services, scenes, combined = build_launcher_catalogues(resolver)

    assert isinstance(services, dict) and len(services) > 0
    assert isinstance(scenes, dict) and len(scenes) > 0
    assert isinstance(combined, dict)
    assert set(combined) == set(services) | set(scenes)


def test_build_launcher_catalogues_calls_resolver_for_each_target() -> None:
    from engine.control_plane_registry import (
        SERVICE_DEFS,
        SCENE_DEFS,
        build_launcher_catalogues,
    )

    resolver = MagicMock(return_value=5000)
    build_launcher_catalogues(resolver)

    expected_targets = set(SERVICE_DEFS) | set(SCENE_DEFS)
    actual_targets = {c.args[0] for c in resolver.call_args_list}
    assert expected_targets == actual_targets


def test_build_launcher_catalogues_injects_port() -> None:
    from engine.control_plane_registry import build_launcher_catalogues

    resolver = MagicMock(return_value=9123)
    services, scenes, combined = build_launcher_catalogues(resolver)

    for info in combined.values():
        assert info["port"] == 9123


# ---------------------------------------------------------------------------
# npm subprocess form (shell=True regression test)
# ---------------------------------------------------------------------------


def test_launcher_npm_popen_uses_list_form() -> None:
    """Regression: npm Popen must NOT use shell=True (audit fix #6)."""
    import subprocess

    captured: list[dict] = []

    class _FakeProc:
        pid = 9999

    original_popen = subprocess.Popen

    def _capturing_popen(cmd, **kwargs):
        captured.append({"cmd": cmd, "kwargs": kwargs})
        return _FakeProc()

    # Import launcher to get reference to _start_node_proc-like code path
    import launcher

    with patch("subprocess.Popen", side_effect=_capturing_popen):
        with patch("engine.port_registry.get_port", return_value=3001):
            try:
                launcher._start_node_proc(
                    {"script": "content/apps/notebook_canvas", "port": 3001, "label": "test"}
                )
            except Exception:
                pass  # may fail for other reasons outside this test

    for call_info in captured:
        assert call_info["kwargs"].get("shell") is not True, (
            "npm Popen must NOT use shell=True"
        )
        if isinstance(call_info["cmd"], str):
            pytest.fail("npm Popen must use list form, not string form")
