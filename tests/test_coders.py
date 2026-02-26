"""Tests for The Coders Room scene — state, pipeline, sandbox execution."""
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from content.scenes.coders.coders_state import (
    AgentRole,
    CodersRoomState,
    FEATURE_SEEDS,
    PipelinePhase,
)


class TestCodersRoomState:
    def setup_method(self):
        self.state = CodersRoomState()

    def test_initial_state(self):
        assert len(self.state.agents) == 4
        assert not self.state.active
        assert self.state.tick_count == 0

    def test_agent_roles(self):
        roles = [a.role for a in self.state.agents]
        assert AgentRole.REVIEWER in roles
        assert AgentRole.WRITER in roles
        assert AgentRole.QA in roles

    def test_agent_names(self):
        names = [a.name for a in self.state.agents]
        assert "Ada" in names
        assert "Linus" in names
        assert "Grace" in names
        assert "Alan" in names

    def test_to_dict(self):
        d = self.state.to_dict()
        assert "agents" in d
        assert len(d["agents"]) == 4
        assert "features" in d
        assert d["tick_count"] == 0

    def test_get_agent(self):
        agent = self.state.get_agent("reviewer_1")
        assert agent is not None
        assert agent.name == "Ada"

    def test_get_agent_not_found(self):
        assert self.state.get_agent("nobody") is None

    def test_get_idle_agent(self):
        agent = self.state.get_idle_agent(AgentRole.REVIEWER)
        assert agent is not None
        assert agent.role == AgentRole.REVIEWER

    def test_get_idle_agent_none_available(self):
        for a in self.state.agents:
            if a.role == AgentRole.REVIEWER:
                a.status = "working"
        assert self.state.get_idle_agent(AgentRole.REVIEWER) is None

    def test_add_feature_random(self):
        feature = self.state.add_feature()
        assert feature.title in [s["title"] for s in FEATURE_SEEDS]
        assert feature.phase == PipelinePhase.FEATURE
        assert len(self.state.features) == 1

    def test_add_feature_custom(self):
        feature = self.state.add_feature("Custom Feature", "Do something cool")
        assert feature.title == "Custom Feature"
        assert feature.description == "Do something cool"

    def test_feature_to_dict(self):
        feature = self.state.add_feature()
        d = feature.to_dict()
        assert "id" in d
        assert "title" in d
        assert "phase" in d

    def test_execute_code_success(self):
        result = self.state.execute_code("x = 2 + 2\nprint(x)")
        assert result["success"]
        assert "4" in result["stdout"]

    def test_execute_code_with_tests(self):
        code = "def add(a, b): return a + b"
        tests = "assert add(1, 2) == 3\nassert add(0, 0) == 0\nprint('All tests passed')"
        result = self.state.execute_code(code, tests)
        assert result["success"]
        assert "All tests passed" in result["stdout"]

    def test_execute_code_failure(self):
        result = self.state.execute_code("raise ValueError('oops')")
        assert not result["success"]
        assert "ValueError" in result["stderr"]

    def test_execute_code_timeout(self):
        result = self.state.execute_code("import time; time.sleep(30)")
        assert not result["success"]
        assert "timed out" in result["stderr"].lower() or result["returncode"] == -1

    def test_execute_code_syntax_error(self):
        result = self.state.execute_code("def broken(")
        assert not result["success"]

    def test_get_current_feature(self):
        self.state.add_feature()
        feature = self.state.get_current_feature()
        assert feature is not None

    def test_get_current_feature_empty(self):
        assert self.state.get_current_feature() is None

    def test_complete_feature(self):
        feature = self.state.add_feature()
        feature.phase = PipelinePhase.TESTING
        feature.test_passed = True
        self.state.complete_feature(feature)
        assert len(self.state.completed_features) == 1
        assert len(self.state.features) == 0

    def test_desk_slots_unique(self):
        slots = [a.desk_slot for a in self.state.agents]
        assert len(set(slots)) == len(slots)


class TestPipelinePhases:
    def test_phase_transitions(self):
        phases = [
            PipelinePhase.IDLE,
            PipelinePhase.FEATURE,
            PipelinePhase.DESIGN,
            PipelinePhase.CODING,
            PipelinePhase.REVIEW,
            PipelinePhase.TESTING,
            PipelinePhase.COMPLETE,
            PipelinePhase.FAILED,
        ]
        assert len(phases) == 8

    def test_feature_starts_at_feature_phase(self):
        state = CodersRoomState()
        feature = state.add_feature()
        assert feature.phase == PipelinePhase.FEATURE


# ---------------------------------------------------------------------------
# Session Persistence (v0.56b)
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    """Tests for _save_session, _load_session, _list_sessions and routes."""

    # ── helpers ──

    @pytest.fixture
    def sessions_dir(self, tmp_path):
        """Temporary directory standing in for data/coders_sessions."""
        d = tmp_path / "coders_sessions"
        d.mkdir()
        return d

    @pytest.fixture
    def scene_bare(self, sessions_dir):
        """CodersRoomScene bypassing __init__ — no Flask, no MCP."""
        from content.scenes.coders.coders_scene import CodersRoomScene

        scene = object.__new__(CodersRoomScene)
        scene._SESSIONS_DIR = sessions_dir
        scene.state = None
        return scene

    @pytest.fixture
    def scene_active(self, scene_bare):
        """scene_bare with a populated CodersRoomState."""
        scene_bare.state = CodersRoomState()
        scene_bare.state.active = True
        scene_bare.state.tick_count = 42
        scene_bare.state.total_lines = 100
        scene_bare.state.total_tests = 7
        scene_bare.state.get_agent("writer_1").lines_written = 50
        scene_bare.state.get_agent("reviewer_1").reviews_done = 3
        scene_bare.state.get_agent("qa_1").tests_run = 5
        return scene_bare

    @pytest.fixture
    def client(self, tmp_path):
        """Flask test client backed by a fully-routed CodersRoomScene."""
        from content.scenes.coders.coders_scene import CodersRoomScene
        from engine.scenes.base_scene import BaseScene
        from engine.mcp.framework import MCPSceneMixin
        from engine.scenes.nexus_mixin import NexusSceneMixin

        sessions_dir = tmp_path / "route_sessions"

        def _base_init(self_inner, scene_name, host="0.0.0.0", port=5000):
            self_inner.scene_name = scene_name
            self_inner.host = host
            self_inner.port = port

        with (
            patch.object(BaseScene, "__init__", _base_init),
            patch.object(MCPSceneMixin, "_mcp_init"),
            patch.object(NexusSceneMixin, "nexus_init"),
            patch.object(BaseScene, "mount_overlay"),
            patch.object(BaseScene, "mount_skills_server"),
            patch.object(BaseScene, "register_health_route"),
            patch(
                "content.scenes.coders.coders_scene.get_scene_state_manager",
                return_value=MagicMock(),
            ),
            patch("content.scenes.coders.coders_scene.TagRegistry") as mock_tr,
            patch("content.scenes.coders.coders_scene.register_coders_rules"),
        ):
            mock_tr.get.return_value = MagicMock()
            scene = CodersRoomScene(port=0)
            scene._SESSIONS_DIR = sessions_dir
            scene.app.config["TESTING"] = True
            yield scene.app.test_client(), scene

    # ── _save_session ──

    def test_save_returns_none_when_no_state(self, scene_bare):
        """Saving with no active state returns None."""
        assert scene_bare._save_session() is None

    def test_save_writes_json_file(self, scene_active, sessions_dir):
        """A .json file is created in the sessions directory."""
        path = scene_active._save_session()
        assert path is not None
        saved = Path(path)
        assert saved.exists()
        assert saved.suffix == ".json"

    def test_save_creates_directory_if_missing(self, tmp_path):
        """_save_session creates _SESSIONS_DIR when it doesn't exist."""
        from content.scenes.coders.coders_scene import CodersRoomScene

        scene = object.__new__(CodersRoomScene)
        scene._SESSIONS_DIR = tmp_path / "nested" / "sessions"
        scene.state = CodersRoomState()
        assert scene._save_session() is not None
        assert scene._SESSIONS_DIR.exists()

    def test_save_json_contains_required_keys(self, scene_active, sessions_dir):
        """Saved JSON must include all persistence keys."""
        scene_active._save_session()
        sid = scene_active.state.session_id
        data = json.loads((sessions_dir / f"{sid}.json").read_text(encoding="utf-8"))
        for key in (
            "session_id", "tick_count", "total_lines", "total_tests",
            "agents", "completed_features", "saved_at",
        ):
            assert key in data, f"missing key: {key}"

    def test_save_preserves_counters(self, scene_active, sessions_dir):
        """tick_count, total_lines, total_tests survive serialisation."""
        scene_active._save_session()
        data = json.loads(
            (sessions_dir / f"{scene_active.state.session_id}.json").read_text()
        )
        assert data["tick_count"] == 42
        assert data["total_lines"] == 100
        assert data["total_tests"] == 7

    def test_save_includes_agent_stats(self, scene_active, sessions_dir):
        """Per-agent counters appear in the saved JSON."""
        scene_active._save_session()
        data = json.loads(
            (sessions_dir / f"{scene_active.state.session_id}.json").read_text()
        )
        agents = {a["id"]: a for a in data["agents"]}
        assert agents["writer_1"]["lines_written"] == 50
        assert agents["reviewer_1"]["reviews_done"] == 3
        assert agents["qa_1"]["tests_run"] == 5

    def test_save_serialises_completed_features(self, scene_active, sessions_dir):
        """Completed features are serialised as a separate list."""
        feat = scene_active.state.add_feature("Saved Feature", "desc")
        feat.phase = PipelinePhase.TESTING
        feat.test_passed = True
        scene_active.state.complete_feature(feat)

        scene_active._save_session()
        data = json.loads(
            (sessions_dir / f"{scene_active.state.session_id}.json").read_text()
        )
        assert len(data["completed_features"]) == 1
        assert data["completed_features"][0]["title"] == "Saved Feature"

    # ── _load_session ──

    def test_load_returns_false_for_missing_session(self, scene_bare):
        """Loading a non-existent session_id returns False."""
        assert scene_bare._load_session("nonexistent_id") is False

    def test_load_restores_state(self, scene_active, sessions_dir):
        """A round-trip save ➜ load restores counters."""
        scene_active._save_session()
        sid = scene_active.state.session_id

        from content.scenes.coders.coders_scene import CodersRoomScene

        fresh = object.__new__(CodersRoomScene)
        fresh._SESSIONS_DIR = sessions_dir
        fresh.state = None

        assert fresh._load_session(sid) is True
        assert fresh.state is not None
        assert fresh.state.session_id == sid
        assert fresh.state.tick_count == 42
        assert fresh.state.total_lines == 100
        assert fresh.state.total_tests == 7

    def test_load_restores_agent_stats(self, scene_active, sessions_dir):
        """Agent lines_written / reviews_done / tests_run survive round-trip."""
        scene_active._save_session()
        sid = scene_active.state.session_id

        from content.scenes.coders.coders_scene import CodersRoomScene

        fresh = object.__new__(CodersRoomScene)
        fresh._SESSIONS_DIR = sessions_dir
        fresh.state = None
        fresh._load_session(sid)

        assert fresh.state.get_agent("writer_1").lines_written == 50
        assert fresh.state.get_agent("reviewer_1").reviews_done == 3
        assert fresh.state.get_agent("qa_1").tests_run == 5

    def test_load_sets_inactive(self, scene_active, sessions_dir):
        """Loaded sessions start inactive (user must explicitly resume)."""
        scene_active._save_session()
        sid = scene_active.state.session_id

        from content.scenes.coders.coders_scene import CodersRoomScene

        fresh = object.__new__(CodersRoomScene)
        fresh._SESSIONS_DIR = sessions_dir
        fresh.state = None
        fresh._load_session(sid)

        assert fresh.state.active is False

    def test_load_returns_false_on_corrupt_json(self, scene_bare, sessions_dir):
        """Corrupt JSON files are handled gracefully."""
        (sessions_dir / "bad.json").write_text("{not valid", encoding="utf-8")
        assert scene_bare._load_session("bad") is False

    # ── _list_sessions ──

    def test_list_empty_directory(self, scene_bare):
        """Empty sessions dir returns an empty list."""
        assert scene_bare._list_sessions() == []

    def test_list_missing_directory(self, tmp_path):
        """Non-existent sessions dir returns an empty list (no crash)."""
        from content.scenes.coders.coders_scene import CodersRoomScene

        scene = object.__new__(CodersRoomScene)
        scene._SESSIONS_DIR = tmp_path / "nope"
        assert scene._list_sessions() == []

    def test_list_returns_saved_sessions(self, scene_active):
        """A saved session appears in the listing."""
        scene_active._save_session()
        result = scene_active._list_sessions()
        assert len(result) == 1
        assert result[0]["session_id"] == scene_active.state.session_id
        assert "saved_at" in result[0]

    def test_list_multiple_sessions(self, scene_bare, sessions_dir):
        """Multiple session files are all returned."""
        for i in range(3):
            sid = f"coders_test{i:03d}"
            data = {
                "session_id": sid, "completed": i,
                "total_lines": i * 10, "total_tests": i,
                "saved_at": time.time() + i,
            }
            (sessions_dir / f"{sid}.json").write_text(
                json.dumps(data), encoding="utf-8",
            )
        assert len(scene_bare._list_sessions()) == 3

    def test_list_skips_corrupt_files(self, scene_bare, sessions_dir):
        """Corrupt files are silently skipped."""
        good = {"session_id": "good_one", "saved_at": 1.0}
        (sessions_dir / "good_one.json").write_text(
            json.dumps(good), encoding="utf-8",
        )
        (sessions_dir / "corrupt.json").write_text("NOT JSON", encoding="utf-8")
        result = scene_bare._list_sessions()
        assert len(result) == 1
        assert result[0]["session_id"] == "good_one"

    # ── Route tests ──

    def test_route_list_sessions_empty(self, client):
        """GET /api/sessions returns empty list when no saves exist."""
        http, _scene = client
        resp = http.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_route_save_no_active_session(self, client):
        """POST /api/session/save returns 400 when state is None."""
        http, _scene = client
        resp = http.post("/api/session/save")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_route_save_active_session(self, client):
        """POST /api/session/save succeeds with active state."""
        http, scene = client
        scene.state = CodersRoomState()
        resp = http.post("/api/session/save")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "path" in body

    def test_route_load_missing_session_id(self, client):
        """POST /api/session/load without session_id returns 400."""
        http, _scene = client
        resp = http.post("/api/session/load", json={})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "session_id required"

    def test_route_load_unknown_session(self, client):
        """POST /api/session/load with unknown id returns 404."""
        http, _scene = client
        resp = http.post(
            "/api/session/load", json={"session_id": "does_not_exist"},
        )
        assert resp.status_code == 404

    def test_route_save_then_load_roundtrip(self, client):
        """Full HTTP round-trip: save → clear → load restores state."""
        http, scene = client
        scene.state = CodersRoomState()
        scene.state.tick_count = 99

        http.post("/api/session/save")
        sid = scene.state.session_id
        scene.state = None  # clear

        resp = http.post("/api/session/load", json={"session_id": sid})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["tick_count"] == 99

    def test_route_list_after_save(self, client):
        """GET /api/sessions includes a just-saved session."""
        http, scene = client
        scene.state = CodersRoomState()
        http.post("/api/session/save")

        resp = http.get("/api/sessions")
        sessions = resp.get_json()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == scene.state.session_id
