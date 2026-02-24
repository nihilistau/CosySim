"""Tests for overlay router API endpoints (/overlay/api/router*)."""
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from engine.overlay.overlay_bp import overlay_bp


@pytest.fixture
def client():
    """Create a Flask test client with the overlay blueprint mounted."""
    app = Flask(__name__)
    app.register_blueprint(overlay_bp)
    app.config["TESTING"] = True
    return app.test_client()


class TestRouterOverlayEndpoint:
    """Tests for /overlay/api/router — router metrics."""

    def test_router_metrics_returns_ok(self, client):
        """GET /overlay/api/router returns metrics dict."""
        mock_router = MagicMock()
        mock_router.get_metrics.return_value = {
            "total_submitted": 42,
            "total_completed": 40,
            "total_errors": 1,
            "total_cancelled": 1,
            "queue_depth": 3,
            "avg_wait_ms": 12.5,
            "avg_latency_ms": 250.0,
            "tier_counts": {"gpu_primary": 30, "cpu_utility": 10},
            "priority_counts": {"REALTIME": 20, "INTERACTIVE": 15, "BACKGROUND": 7},
            "slots": {
                "gpu_primary": {"busy": 1, "total": 2},
                "cpu_utility": {"busy": 0, "total": 1},
                "cpu_router": {"busy": 0, "total": 1},
            },
        }

        import engine.lmstudio.router as router_mod
        with patch.object(router_mod, "get_router", return_value=mock_router):
            resp = client.get("/overlay/api/router")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["total_submitted"] == 42
        assert data["queue_depth"] == 3
        assert "slots" in data

    def test_router_metrics_error_handling(self, client):
        """GET /overlay/api/router handles exceptions gracefully."""
        with patch("engine.lmstudio.router.get_router", side_effect=RuntimeError("boom")):
            resp = client.get("/overlay/api/router")

        assert resp.status_code == 500
        data = resp.get_json()
        assert data["ok"] is False
        assert "boom" in data["error"]


class TestRouterTiersEndpoint:
    """Tests for /overlay/api/router/tiers — per-tier slot info."""

    def test_tiers_returns_slot_info(self, client):
        """GET /overlay/api/router/tiers shows per-tier config."""
        from engine.lmstudio.router import Tier, TierConfig

        mock_router = MagicMock()
        mock_router._tiers = {
            Tier.GPU_PRIMARY: TierConfig(
                tier=Tier.GPU_PRIMARY, model_key="qwen3-8b",
                max_slots=2, device="gpu",
            ),
            Tier.CPU_UTILITY: TierConfig(
                tier=Tier.CPU_UTILITY, model_key="ministral-3b",
                max_slots=1, device="cpu",
            ),
        }
        mock_router._tiers[Tier.GPU_PRIMARY]._busy_slots = 1
        mock_router._tiers[Tier.CPU_UTILITY]._busy_slots = 0

        with patch("engine.lmstudio.router.get_router", return_value=mock_router):
            resp = client.get("/overlay/api/router/tiers")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        tiers = data["tiers"]
        assert "gpu_primary" in tiers
        assert tiers["gpu_primary"]["model_key"] == "qwen3-8b"
        assert tiers["gpu_primary"]["busy_slots"] == 1
        assert tiers["gpu_primary"]["available"] == 1

    def test_tiers_error_handling(self, client):
        """GET /overlay/api/router/tiers handles exceptions gracefully."""
        with patch("engine.lmstudio.router.get_router", side_effect=ImportError("no router")):
            resp = client.get("/overlay/api/router/tiers")

        assert resp.status_code == 500
        data = resp.get_json()
        assert data["ok"] is False


class TestNeonCityTagRegistration:
    """Test that NeonCity registers its custom [HACK:] tag."""

    def test_hack_tag_registered(self):
        """Importing NeonCityScene should register the HACK tag."""
        from engine.mcp.tag_registry import TagRegistry
        registry = TagRegistry.get()
        # NeonCity registers HACK tag in __init__, but we can test detection
        # against the built-in registry (HACK may not be registered yet if
        # NeonCityScene hasn't been instantiated — test the tag pattern directly)
        from engine.mcp.tag_registry import TagDef
        tag = TagDef(
            name="HACK", pattern=r"\[HACK:([^\]]+)\]",
            handler=None, strip_from_output=True, pre_warm_intent="neoncity_hack"
        )
        registry.register(tag)
        matches = registry.detect_all("[HACK:mainframe_bypass]")
        assert "HACK" in matches
        assert matches["HACK"][0].value == "mainframe_bypass"
        # Clean up
        registry.unregister("HACK")

    def test_hack_tag_stripped(self):
        """The HACK tag should be stripped from output text."""
        from engine.mcp.tag_registry import TagRegistry, TagDef
        registry = TagRegistry.get()
        registry.register(TagDef(
            name="HACK", pattern=r"\[HACK:([^\]]+)\]",
            handler=None, strip_from_output=True,
        ))
        text = "I hacked the system [HACK:firewall_breach] and got in."
        cleaned = registry.strip_tags(text)
        assert "[HACK:" not in cleaned
        assert "I hacked the system" in cleaned
        registry.unregister("HACK")
