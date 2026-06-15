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
        assert "version" in data  # version changes with each release
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

    # ── Combat routes (no game) ──

    def test_combat_start_without_game(self):
        resp = self.client.post("/api/combat/start")
        assert resp.status_code == 400

    def test_combat_attack_without_game(self):
        resp = self.client.post("/api/combat/attack")
        assert resp.status_code == 400

    def test_combat_flee_without_game(self):
        resp = self.client.post("/api/combat/flee")
        assert resp.status_code == 400

    # ── Quest routes (no game) ──

    def test_quests_without_game(self):
        resp = self.client.get("/api/quests")
        assert resp.status_code == 400

    def test_quest_accept_without_game(self):
        resp = self.client.post("/api/quests/accept", json={"quest": "rats_in_cellar"})
        assert resp.status_code == 400


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
        # v0.68 skills
        assert len(metas) >= 3
        assert any("faction" in n or "city" in n or "credit" in n for n in names)

    def test_coders_skills_registered(self):
        from engine.skills.registry import SKILL_REGISTRY
        import content.scenes.coders.coders_skills  # noqa: F401
        metas = SKILL_REGISTRY.get_pack_metas("coders")
        names = {m.name for m in metas}
        assert "coders_run_code" in names
        assert "coders_add_feature" in names
        assert len(metas) >= 5


# ═══════════════════════════════════════════════════════════════
#  MCP FRAMEWORK INTEGRATION — verify scenes wire to framework
# ═══════════════════════════════════════════════════════════════

class TestMCPFrameworkIntegration:
    """Verify all showcase scenes properly integrate with the MCP framework.

    v1.62.0 [2026-06-15] — MCP integration moved from MCPSceneMixin into
    FlaskScene (``FlaskScene._connect_mcp()`` replaces ``MCPSceneMixin._mcp_init()``,
    per v1.51.0 "Migrated to FlaskScene"). Scenes no longer subclass MCPSceneMixin
    nor carry ``_mcp_scene_id``; the framework binding is now expressed via the
    FlaskScene base class, the ``mcp`` property, and ``SCENE_METADATA["name"]``.
    The old ``issubclass(..., MCPSceneMixin)`` / ``_mcp_scene_id`` assertions were
    stale and asserted an obsolete mechanism — updated to the current contract.
    """

    def test_realm_has_mcp_integration(self):
        from content.scenes.realm.realm_scene import RealmScene
        from engine.scenes.flask_scene import FlaskScene
        assert issubclass(RealmScene, FlaskScene)
        assert isinstance(getattr(RealmScene, "mcp", None), property)
        assert RealmScene.SCENE_METADATA["name"] == "realm"

    def test_neoncity_has_mcp_integration(self):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        from engine.scenes.flask_scene import FlaskScene
        assert issubclass(NeonCityScene, FlaskScene)
        assert isinstance(getattr(NeonCityScene, "mcp", None), property)
        assert NeonCityScene.SCENE_METADATA["name"] == "neoncity"

    def test_coders_has_mcp_integration(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        from engine.scenes.flask_scene import FlaskScene
        assert issubclass(CodersRoomScene, FlaskScene)
        assert isinstance(getattr(CodersRoomScene, "mcp", None), property)
        assert CodersRoomScene.SCENE_METADATA["name"] == "coders"

    def test_realm_mcp_node_created(self):
        from content.scenes.realm.realm_scene import RealmScene
        scene = RealmScene(port=15570)
        assert hasattr(scene, "mcp")
        assert scene.mcp.scene_id == "realm"

    def test_neoncity_mcp_node_created(self):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        scene = NeonCityScene(port=15571)
        assert hasattr(scene, "mcp")
        assert scene.mcp.scene_id == "neoncity"

    def test_coders_mcp_node_created(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        scene = CodersRoomScene(port=15572)
        assert hasattr(scene, "mcp")
        assert scene.mcp.scene_id == "coders"

    def test_framework_knows_all_scenes(self):
        """After instantiating scenes, framework should track all of them."""
        from engine.mcp.framework import get_framework
        from content.scenes.realm.realm_scene import RealmScene
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        from content.scenes.coders.coders_scene import CodersRoomScene
        RealmScene(port=15573)
        NeonCityScene(port=15574)
        CodersRoomScene(port=15575)
        fw = get_framework()
        scene_ids = set(fw._scenes.keys())
        assert "realm" in scene_ids
        assert "neoncity" in scene_ids
        assert "coders" in scene_ids

    def test_realm_state_sync(self):
        """RealmScene._sync_to_mcp() should push state to framework node."""
        from content.scenes.realm.realm_scene import RealmScene
        from content.scenes.realm.realm_state import RealmGameState
        scene = RealmScene(port=15576)
        scene.state = RealmGameState()
        scene._sync_to_mcp()
        node_state = scene.mcp.get_state()
        assert "player_stats" in node_state
        assert "session_id" in node_state

    def test_neoncity_state_sync(self):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        from content.scenes.neoncity.neoncity_state import NeonCityGameState
        scene = NeonCityScene(port=15577)
        scene.state = NeonCityGameState()
        scene._sync_to_mcp()
        node_state = scene.mcp.get_state()
        assert isinstance(node_state, dict)

    def test_coders_state_sync(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        from content.scenes.coders.coders_state import CodersRoomState
        scene = CodersRoomScene(port=15578)
        scene.state = CodersRoomState()
        scene._sync_to_mcp()
        node_state = scene.mcp.get_state()
        assert isinstance(node_state, dict)
