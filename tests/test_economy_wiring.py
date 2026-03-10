"""Tests for EconomyManager wiring across all 9 active scenes.

Verifies:
    - /api/economy route exists and returns valid JSON on each scene
    - /api/consequences route exists and returns expected structure on the
      3 consequence-heavy scenes (tavern, realm, neoncity)
    - EconomyManager and ConsequenceStore are fully mocked — no live Nexus
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared mock factories
# ---------------------------------------------------------------------------

ECONOMY_PATCH = "engine.economy.economy.get_economy_manager"
CONSEQUENCE_PATCH = "engine.mechanics.consequences.get_consequence_store"


def _nexus_mock() -> MagicMock:
    m = MagicMock()
    m.search.return_value = []
    m.add_entry.return_value = "entry-001"
    m.update_entry.return_value = True
    m.list_by_type.return_value = []
    return m


def _economy_mock(balance: int = 1500) -> MagicMock:
    m = MagicMock()
    m.get_balance.return_value = balance
    m.check_debt.return_value = 0
    m.get_history.return_value = []
    return m


def _consequence_store_mock() -> MagicMock:
    m = MagicMock()
    m.get_history.return_value = []
    m.get_pending.return_value = []
    return m


def _fw_mock() -> MagicMock:
    fw = MagicMock()
    fw.get_status.return_value = {}
    fw.emit_event.return_value = None
    fw.get_event_log.return_value = []
    fw.list_agent_profiles.return_value = []
    fw.list_timers.return_value = []
    fw.get_pending_consequences.return_value = []
    fw.tick.return_value = None
    return fw


def _build_scene(scene_cls_path: str, port: int):
    """Instantiate a scene class with heavy dependencies mocked."""
    nexus = _nexus_mock()
    fw = _fw_mock()

    with patch("engine.economy.economy.get_nexus_client", return_value=nexus), \
         patch("engine.mechanics.consequences.get_nexus_client", return_value=nexus), \
         patch("engine.mcp.framework.get_framework", return_value=fw):

        module_path, cls_name = scene_cls_path.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        SceneCls = getattr(mod, cls_name)
        scene = SceneCls(port=port)

    return scene, fw


# ---------------------------------------------------------------------------
# Economy route tests
# ---------------------------------------------------------------------------


class _EconomyRouteBase:
    """Subclasses set scene_cls_path and scene_port."""

    scene_cls_path: str
    scene_port: int
    economy_patch: str = ECONOMY_PATCH  # override for scenes with module-level imports

    @pytest.fixture(autouse=True)
    def setup_scene(self):
        self.em = _economy_mock()
        scene, self.fw = _build_scene(self.scene_cls_path, self.scene_port)
        self.client = scene.app.test_client()

    def test_economy_route_exists(self):
        """GET /api/economy should return 200."""
        with patch(self.economy_patch, return_value=self.em):
            resp = self.client.get("/api/economy")
        assert resp.status_code == 200

    def test_economy_route_returns_json(self):
        """GET /api/economy returns a dict with required keys."""
        with patch(self.economy_patch, return_value=self.em):
            resp = self.client.get("/api/economy")
        data = resp.get_json()
        assert isinstance(data, dict)
        assert "balance" in data
        assert "scene" in data
        assert "debt" in data
        assert "recent_transactions" in data

    def test_economy_balance_value(self):
        """balance reflects EconomyManager.get_balance() return value."""
        with patch(self.economy_patch, return_value=self.em):
            resp = self.client.get("/api/economy")
        assert resp.get_json()["balance"] == 1500

    def test_economy_debt_is_zero(self):
        """debt is 0 when player is not in debt."""
        with patch(self.economy_patch, return_value=self.em):
            resp = self.client.get("/api/economy")
        assert resp.get_json()["debt"] == 0

    def test_economy_recent_transactions_is_list(self):
        """recent_transactions must be a list."""
        with patch(self.economy_patch, return_value=self.em):
            resp = self.client.get("/api/economy")
        assert isinstance(resp.get_json()["recent_transactions"], list)


class TestCasinoEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.casino.casino_scene.CasinoScene"
    scene_port = 19559


class TestArenaEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.arena.ArenaScene"
    scene_port = 19561


class TestRealmEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.realm.realm_scene.RealmScene"
    scene_port = 19562


class TestNeoncityEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.neoncity.neoncity_scene.NeonCityScene"
    scene_port = 19563
    # neoncity imports get_economy_manager at module level, so patch the local binding
    economy_patch = "content.scenes.neoncity.neoncity_scene.get_economy_manager"


class TestTavernEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.tavern.tavern_scene.TavernScene"
    scene_port = 19564


class TestLoungeEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.lounge.lounge_scene.LoungeScene"
    scene_port = 19565


class TestGalleryEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.gallery.gallery_scene.GalleryScene"
    scene_port = 19566


class TestBedroomEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.penthouse.penthouse_scene.PenthouseScene"
    scene_port = 19567


class TestPhoneEconomyRoute(_EconomyRouteBase):
    scene_cls_path = "content.scenes.phone.phone_scene_v2.PhoneSceneV2"
    scene_port = 19568


# ---------------------------------------------------------------------------
# Consequence route tests — tavern, realm, neoncity
# ---------------------------------------------------------------------------


class _ConsequenceRouteBase:
    """Subclasses set scene_cls_path and scene_port."""

    scene_cls_path: str
    scene_port: int

    @pytest.fixture(autouse=True)
    def setup_scene(self):
        self.em = _economy_mock()
        self.cs = _consequence_store_mock()
        scene, self.fw = _build_scene(self.scene_cls_path, self.scene_port)
        self.client = scene.app.test_client()

    def test_consequences_route_exists(self):
        """GET /api/consequences should return 200."""
        with patch(CONSEQUENCE_PATCH, return_value=self.cs), \
             patch(ECONOMY_PATCH, return_value=self.em):
            resp = self.client.get("/api/consequences")
        assert resp.status_code == 200

    def test_consequences_returns_json(self):
        """GET /api/consequences returns a dict."""
        with patch(CONSEQUENCE_PATCH, return_value=self.cs), \
             patch(ECONOMY_PATCH, return_value=self.em):
            resp = self.client.get("/api/consequences")
        assert isinstance(resp.get_json(), dict)

    def test_consequences_has_recent_and_pending_keys(self):
        """Response must contain 'recent' and 'pending' lists."""
        with patch(CONSEQUENCE_PATCH, return_value=self.cs), \
             patch(ECONOMY_PATCH, return_value=self.em):
            resp = self.client.get("/api/consequences")
        data = resp.get_json()
        assert "recent" in data
        assert "pending" in data
        assert isinstance(data["recent"], list)
        assert isinstance(data["pending"], list)

    def test_consequences_empty_when_store_empty(self):
        """Both lists are empty when ConsequenceStore returns nothing."""
        self.cs.get_history.return_value = []
        self.cs.get_pending.return_value = []
        with patch(CONSEQUENCE_PATCH, return_value=self.cs), \
             patch(ECONOMY_PATCH, return_value=self.em):
            resp = self.client.get("/api/consequences")
        data = resp.get_json()
        assert data["recent"] == []
        assert data["pending"] == []


class TestTavernConsequenceRoute(_ConsequenceRouteBase):
    scene_cls_path = "content.scenes.tavern.tavern_scene.TavernScene"
    scene_port = 19764


class TestRealmConsequenceRoute(_ConsequenceRouteBase):
    scene_cls_path = "content.scenes.realm.realm_scene.RealmScene"
    scene_port = 19762


class TestNeoncityConsequenceRoute(_ConsequenceRouteBase):
    scene_cls_path = "content.scenes.neoncity.neoncity_scene.NeonCityScene"
    scene_port = 19763
