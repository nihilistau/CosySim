"""Tests for v0.83 Social Layer features — shop, crew HUD, hack routes, inventory API."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ──── Inventory / Shop ────────────────────────────────────────────────────────

class TestInventoryShop:
    """Tests for InventoryManager shop methods added in v0.83."""

    def test_get_catalog_returns_all_items(self):
        from engine.world.inventory import get_inventory, ITEM_CATALOG
        inv = get_inventory()
        catalog = inv.get_catalog()
        assert len(catalog) == len(ITEM_CATALOG)

    def test_get_catalog_has_price_fields(self):
        from engine.world.inventory import get_inventory
        catalog = get_inventory().get_catalog()
        for item in catalog:
            assert "price" in item
            assert "sell_price" in item
            assert item["price"] > 0
            assert item["sell_price"] > 0

    def test_get_catalog_has_owned_qty(self):
        from engine.world.inventory import get_inventory
        catalog = get_inventory().get_catalog()
        for item in catalog:
            assert "owned_qty" in item
            assert isinstance(item["owned_qty"], int)

    def test_get_catalog_filter_by_category(self):
        from engine.world.inventory import get_inventory
        catalog = get_inventory().get_catalog(category="drug")
        assert len(catalog) > 0
        for item in catalog:
            assert item["category"] == "drug"

    def test_get_catalog_unknown_category_returns_empty(self):
        from engine.world.inventory import get_inventory
        catalog = get_inventory().get_catalog(category="nonexistent_xyz")
        assert catalog == []

    def test_buy_item_success(self):
        from engine.world.inventory import get_inventory
        inv = get_inventory()

        ps = MagicMock()
        ps.credits = 5000

        def spend(n):
            ps.credits -= n
        ps.spend_credits = spend

        result = inv.buy_item("stim_pack", quantity=2, player_state=ps)
        assert result["success"] is True
        assert result["cost"] == 160  # 80 * 2
        assert result["quantity"] == 2
        assert result["item_id"] == "stim_pack"

    def test_buy_item_insufficient_credits(self):
        from engine.world.inventory import get_inventory
        inv = get_inventory()

        ps = MagicMock()
        ps.credits = 10  # not enough for specter_3000 (12000)

        result = inv.buy_item("specter_3000", quantity=1, player_state=ps)
        assert result["success"] is False
        assert "Insufficient credits" in result["error"]

    def test_buy_item_unknown_item(self):
        from engine.world.inventory import get_inventory
        result = get_inventory().buy_item("fake_item_xyz")
        assert result["success"] is False
        assert "Unknown item" in result["error"]

    def test_sell_item_success(self):
        from engine.world.inventory import get_inventory
        inv = get_inventory()
        # Ensure item is in inventory
        inv.add_item("stim_pack", quantity=3)

        ps = MagicMock()
        ps.credits = 0

        def earn(n):
            ps.credits += n
        ps.earn_credits = earn

        result = inv.sell_item("stim_pack", quantity=1, player_state=ps)
        assert result["success"] is True
        assert result["earned"] == 30  # sell_price=30
        assert result["quantity"] == 1

    def test_sell_item_not_enough(self):
        from engine.world.inventory import get_inventory
        inv = get_inventory()
        # Remove all stim_packs first to ensure zero owned
        inv._items.pop("stim_pack", None)

        result = inv.sell_item("stim_pack", quantity=99)
        assert result["success"] is False
        assert "Only have" in result["error"]

    def test_sell_item_unknown_item(self):
        from engine.world.inventory import get_inventory
        result = get_inventory().sell_item("fake_item_xyz")
        assert result["success"] is False
        assert "Unknown item" in result["error"]


# ──── BaseScene shop route ────────────────────────────────────────────────────

class TestShopRoute:
    """Tests for BaseScene.register_shop_route() endpoints."""

    @pytest.fixture
    def shop_app(self):
        """Flask test client with shop routes registered."""
        from flask import Flask
        from engine.scenes.base_scene import BaseScene

        class _ConcreteScene(BaseScene):
            SCENE_METADATA = {"name": "test", "port": 9999, "type": "game"}
            def start(self): pass
            def stop(self): pass
            def get_plugin_info(self): return {}

        app = Flask(__name__)
        scene = _ConcreteScene.__new__(_ConcreteScene)
        scene.register_shop_route(app)
        return app.test_client()

    def test_catalog_returns_200(self, shop_app):
        resp = shop_app.get("/api/shop/catalog")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0

    def test_catalog_category_filter(self, shop_app):
        resp = shop_app.get("/api/shop/catalog?category=drug")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        for item in data["items"]:
            assert item["category"] == "drug"

    def test_inventory_endpoint(self, shop_app):
        resp = shop_app.get("/api/shop/inventory")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True
        assert "inventory" in data

    def test_buy_endpoint_no_item_id(self, shop_app):
        resp = shop_app.post("/api/shop/buy",
                             data=json.dumps({}),
                             content_type="application/json")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_sell_endpoint_no_item_id(self, shop_app):
        resp = shop_app.post("/api/shop/sell",
                             data=json.dumps({}),
                             content_type="application/json")
        assert resp.status_code == 400

    def test_affordability_endpoint(self, shop_app):
        resp = shop_app.get("/api/shop/affordability")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True
        assert "credits" in data
        assert isinstance(data["items"], list)

    def test_route_only_registered_once(self):
        """Calling register_shop_route twice should not raise."""
        from flask import Flask
        from engine.scenes.base_scene import BaseScene

        class _ConcreteScene(BaseScene):
            SCENE_METADATA = {"name": "test2", "port": 9998, "type": "game"}
            def start(self): pass
            def stop(self): pass
            def get_plugin_info(self): return {}

        app = Flask(__name__)
        scene = _ConcreteScene.__new__(_ConcreteScene)
        scene.register_shop_route(app)
        scene.register_shop_route(app)  # second call — should be no-op


# ──── ITEM_CATALOG prices ─────────────────────────────────────────────────────

class TestItemCatalogPrices:
    """Verify all catalog items have valid prices."""

    def test_all_items_have_price(self):
        from engine.world.inventory import ITEM_CATALOG
        for item_id, meta in ITEM_CATALOG.items():
            assert "price" in meta, f"{item_id} missing price"
            assert meta["price"] > 0, f"{item_id} price must be > 0"

    def test_all_items_have_sell_price(self):
        from engine.world.inventory import ITEM_CATALOG
        for item_id, meta in ITEM_CATALOG.items():
            assert "sell_price" in meta, f"{item_id} missing sell_price"
            assert meta["sell_price"] > 0, f"{item_id} sell_price must be > 0"

    def test_sell_price_less_than_buy_price(self):
        from engine.world.inventory import ITEM_CATALOG
        for item_id, meta in ITEM_CATALOG.items():
            assert meta["sell_price"] <= meta["price"], \
                f"{item_id} sell_price {meta['sell_price']} > price {meta['price']}"

    def test_legendary_cyberdeck_most_expensive(self):
        from engine.world.inventory import ITEM_CATALOG
        specter = ITEM_CATALOG["specter_3000"]
        mk1 = ITEM_CATALOG["netrunner_mk1"]
        assert specter["price"] > mk1["price"]


# ──── NeonCity scene wiring ───────────────────────────────────────────────────

class TestNeonCityWiring:
    """Verify NeonCity scene has proper route registrations."""

    def test_neoncity_scene_imports(self):
        """NeonCity scene module should import without error."""
        import importlib
        import content.scenes.neoncity.neoncity_scene as m
        assert hasattr(m, "NeonCityScene")

    def test_neoncity_scene_start_method(self):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        assert hasattr(NeonCityScene, "start")
        assert hasattr(NeonCityScene, "stop")
        assert hasattr(NeonCityScene, "get_plugin_info")

    def test_neoncity_metadata(self):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        meta = NeonCityScene.SCENE_METADATA
        assert meta["name"] == "neoncity"
        assert meta["port"] == 5563


# ──── Crew HUD rendering ─────────────────────────────────────────────────────

class TestCrewHUD:
    """Verify CrewManager returns valid HUD data."""

    def test_crew_hud_dict_structure(self):
        from engine.world.crew import get_crew_manager
        crew_mgr = get_crew_manager()
        hud_data = crew_mgr.to_hud_dict()
        assert isinstance(hud_data, list)
        for member in hud_data:
            assert "id" in member
            assert "role" in member
            assert "loyalty" in member
            assert "level" in member
            assert "available" in member

    def test_crew_loyalty_in_range(self):
        from engine.world.crew import get_crew_manager
        for member in get_crew_manager().to_hud_dict():
            assert 0 <= member["loyalty"] <= 100

    def test_crew_role_icon_present(self):
        from engine.world.crew import get_crew_manager
        for member in get_crew_manager().to_hud_dict():
            assert "role_icon" in member
