"""Integration tests for the three showcase scene Flask routes.

Uses Flask test_client to verify routes without starting full servers.
"""
import pytest
import json


# ═══════════════════════════════════════════════════════════════
#  REALM SCENE ROUTES
# ═══════════════════════════════════════════════════════════════

class TestRealmRoutes:
    @pytest.fixture(autouse=True)
    def setup_realm(self):
        from content.scenes.realm.realm_scene import RealmScene
        self.scene = RealmScene(port=15562)
        self.client = self.scene.app.test_client()

    def test_index_renders(self):
        resp = self.client.get("/")
        assert resp.status_code == 200
        assert b"Realm" in resp.data or b"realm" in resp.data

    def test_scene_info(self):
        resp = self.client.get("/api/scene/info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scene_id"] == "realm"
        assert data["version"] == "3.1.0"
        assert "routes" in data

    def test_game_state_no_game(self):
        resp = self.client.get("/api/game/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["active"] is False

    def test_choice_without_game(self):
        resp = self.client.post(
            "/api/game/choice",
            json={"choice_id": "a"},
        )
        assert resp.status_code == 400

    def test_desperation_without_game(self):
        resp = self.client.post("/api/game/desperation")
        assert resp.status_code == 400

    def test_mutiny_without_game(self):
        resp = self.client.post("/api/game/mutiny")
        assert resp.status_code == 400

    def test_steal_without_game(self):
        resp = self.client.post("/api/game/steal", json={"item_name": "test"})
        assert resp.status_code == 400

    def test_use_item_without_game(self):
        resp = self.client.post("/api/game/use_item", json={"item_id": "test"})
        assert resp.status_code == 400

    def test_murder_start_without_game(self):
        resp = self.client.post("/api/murder/start")
        assert resp.status_code == 400

    def test_health_endpoint(self):
        resp = self.client.get("/api/health")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  NEONCITY SCENE ROUTES
# ═══════════════════════════════════════════════════════════════

class TestNeonCityRoutes:
    @pytest.fixture(autouse=True)
    def setup_neoncity(self):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        self.scene = NeonCityScene(port=15563)
        self.client = self.scene.app.test_client()

    def test_index_renders(self):
        resp = self.client.get("/")
        assert resp.status_code == 200
        assert b"NeonCity" in resp.data or b"neon" in resp.data

    def test_scene_info(self):
        resp = self.client.get("/api/scene/info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scene_id"] == "neoncity"

    def test_game_state_no_game(self):
        resp = self.client.get("/api/game/state")
        assert resp.status_code == 200
        assert resp.get_json()["active"] is False

    def test_grid_without_game(self):
        resp = self.client.get("/api/game/grid")
        assert resp.status_code == 400

    def test_move_without_game(self):
        resp = self.client.post("/api/game/move", json={"x": 1, "y": 1})
        assert resp.status_code == 400

    def test_attack_without_game(self):
        resp = self.client.post("/api/game/attack", json={"target_id": "ai_1"})
        assert resp.status_code == 400

    def test_hack_without_game(self):
        resp = self.client.post("/api/game/hack")
        assert resp.status_code == 400

    def test_end_turn_without_game(self):
        resp = self.client.post("/api/game/end_turn")
        assert resp.status_code == 400

    def test_health_endpoint(self):
        resp = self.client.get("/api/health")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  CODERS ROOM SCENE ROUTES
# ═══════════════════════════════════════════════════════════════

class TestCodersRoomRoutes:
    @pytest.fixture(autouse=True)
    def setup_coders(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        self.scene = CodersRoomScene(port=15564)
        self.client = self.scene.app.test_client()

    def test_index_renders(self):
        resp = self.client.get("/")
        assert resp.status_code == 200
        assert b"Coders" in resp.data or b"coders" in resp.data

    def test_scene_info(self):
        resp = self.client.get("/api/scene/info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scene_id"] == "coders"

    def test_state_no_sim(self):
        resp = self.client.get("/api/state")
        assert resp.status_code == 200
        assert resp.get_json()["active"] is False

    def test_add_feature_without_start(self):
        resp = self.client.post("/api/feature/add", json={"title": "Test"})
        assert resp.status_code == 400

    def test_tick_without_start(self):
        resp = self.client.post("/api/tick")
        assert resp.status_code == 400

    def test_stop_without_start(self):
        resp = self.client.post("/api/stop")
        assert resp.status_code == 200

    def test_health_endpoint(self):
        resp = self.client.get("/api/health")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  CROSS-SCENE: skill registration
# ═══════════════════════════════════════════════════════════════

class TestSkillRegistration:
    def test_realm_skills_registered(self):
        from engine.skills.registry import SKILL_REGISTRY
        # Force import
        import content.scenes.realm.realm_skills  # noqa: F401
        metas = SKILL_REGISTRY.get_pack_metas("realm")
        names = {m.name for m in metas}
        assert "realm_inventory" in names
        assert "realm_skill_check" in names
        assert "realm_director_status" in names
        assert len(metas) >= 10

    def test_neoncity_skills_registered(self):
        from engine.skills.registry import SKILL_REGISTRY
        import content.scenes.neoncity.neoncity_skills  # noqa: F401
        metas = SKILL_REGISTRY.get_pack_metas("neoncity")
        names = {m.name for m in metas}
        assert "neoncity_move" in names
        assert "neoncity_hack" in names
        assert len(metas) >= 7

    def test_coders_skills_registered(self):
        from engine.skills.registry import SKILL_REGISTRY
        import content.scenes.coders.coders_skills  # noqa: F401
        metas = SKILL_REGISTRY.get_pack_metas("coders")
        names = {m.name for m in metas}
        assert "coders_run_code" in names
        assert "coders_add_feature" in names
        assert len(metas) >= 5
