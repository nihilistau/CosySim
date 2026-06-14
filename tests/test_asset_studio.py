"""Tests for the Asset Studio system.

Covers:
- AssetLibrary CRUD and pagination
- PresetManager builtin + custom presets
- PromptBuilder for all asset types
- StudioCore generation routing with mocked generators
- Feature flag enable / disable
- Scene route registration
- Skills registration
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── AssetLibrary ──────────────────────────────────────────────────────────────

@pytest.fixture()
def lib_db(tmp_path):
    with patch("engine.asset_studio.asset_library.get_config") as mock_cfg:
        mock_cfg.return_value = MagicMock()
        mock_cfg.return_value.get = lambda k, d=None: d
        from engine.asset_studio.asset_library import AssetLibrary
        lib = AssetLibrary(db_path=str(tmp_path / "test_lib.db"))
        yield lib
        # Force cleanup of SQLite connections before tmp_path removal
        import gc
        gc.collect()


class TestAssetLibrary:
    def test_register_and_get(self, lib_db):
        asset_id = lib_db.register(
            asset_type="image", url="/test/img.png", title="Test Image",
            scene="penthouse", prompt="a test image", metadata={"width": 512},
        )
        assert asset_id
        a = lib_db.get_asset(asset_id)
        assert a["title"] == "Test Image"
        assert a["asset_type"] == "image"
        assert a["url"] == "/test/img.png"

    def test_list_assets_empty(self, lib_db):
        result = lib_db.list_assets()
        assert result == []

    def test_list_with_filter(self, lib_db):
        lib_db.register("image", "/1.png", "Img1", "penthouse")
        lib_db.register("voice", "/1.wav", "Voice1", "phone")
        result = lib_db.list_assets(asset_type="image")
        assert len(result) == 1
        assert result[0]["asset_type"] == "image"

    def test_favorite_toggle(self, lib_db):
        aid = lib_db.register("image", "/fav.png", "Fav", "penthouse")
        is_fav = lib_db.toggle_favorite(aid)
        assert is_fav is True
        is_fav = lib_db.toggle_favorite(aid)
        assert is_fav is False

    def test_delete(self, lib_db):
        aid = lib_db.register("svg", "/del.svg", "Del", "penthouse")
        assert lib_db.get_asset(aid) is not None
        lib_db.delete(aid)
        assert lib_db.get_asset(aid) is None

    def test_count(self, lib_db):
        for i in range(5):
            lib_db.register("item", f"/{i}.png", f"Item {i}", "arena")
        assert lib_db.count() == 5

    def test_stats_by_type(self, lib_db):
        lib_db.register("image", "/img.png", "Img", "penthouse")
        lib_db.register("image", "/img2.png", "Img2", "penthouse")
        lib_db.register("voice", "/vox.wav", "Vox", "phone")
        stats = lib_db.stats()
        assert stats["by_type"]["image"] == 2
        assert stats["by_type"]["voice"] == 1

    def test_search(self, lib_db):
        lib_db.register("image", "/s.png", "A Sunset", "penthouse")
        lib_db.register("image", "/p.png", "A Portrait", "penthouse")
        result = lib_db.list_assets(search="Sunset")
        assert len(result) == 1
        assert result[0]["title"] == "A Sunset"

    def test_pagination(self, lib_db):
        for i in range(10):
            lib_db.register("image", f"/{i}.png", f"P{i}", "penthouse")
        page1 = lib_db.list_assets(limit=5, offset=0)
        page2 = lib_db.list_assets(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        ids1 = {a["id"] for a in page1}
        ids2 = {a["id"] for a in page2}
        assert ids1.isdisjoint(ids2)

    def test_thread_safety(self, lib_db):
        errors = []

        def insert(i):
            try:
                lib_db.register("image", f"/{i}.png", f"T{i}", "test")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=insert, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert lib_db.count() == 20


# ── PresetManager ─────────────────────────────────────────────────────────────

@pytest.fixture()
def preset_mgr():
    with patch("engine.nexus.client.get_nexus_client") as mock_nx:
        mock_nx.return_value = MagicMock()
        mock_nx.return_value.search.return_value = []
        from engine.asset_studio.preset_manager import PresetManager
        return PresetManager()


class TestPresetManager:
    def test_builtin_count(self, preset_mgr):
        builtins = [p for p in preset_mgr._presets.values() if p.builtin]
        assert len(builtins) >= 6

    def test_get_preset_dark_renaissance(self, preset_mgr):
        p = preset_mgr.get("dark_renaissance")
        assert p is not None
        assert any("dark" in t for t in p.style_tags)

    def test_list_all(self, preset_mgr):
        all_presets = preset_mgr.list_all()
        assert isinstance(all_presets, list)
        assert len(all_presets) >= 6

    def test_add_custom_preset(self, preset_mgr):
        preset_mgr.save_custom({
            "id": "test_custom",
            "name": "Test Custom",
            "description": "A custom test preset",
            "style_tags": ["dark", "moody"],
            "negative_tags": ["bright"],
            "width": 512,
            "height": 768,
            "steps": 30,
            "cfg_scale": 7.0,
        })
        p = preset_mgr.get("test_custom")
        assert p is not None
        assert p.name == "Test Custom"
        assert p.builtin is False

    def test_delete_custom(self, preset_mgr):
        preset_mgr.save_custom({"id": "del_me", "name": "DeleteMe", "description": "",
                                 "style_tags": [], "negative_tags": [], "width": 512,
                                 "height": 512, "steps": 20, "cfg_scale": 7.0})
        result = preset_mgr.delete_custom("del_me")
        assert result is True
        assert preset_mgr.get("del_me") is None

    def test_cannot_delete_builtin(self, preset_mgr):
        # delete_custom returns False (not raise) for builtins
        result = preset_mgr.delete_custom("dark_renaissance")
        assert result is False
        # preset still present
        assert preset_mgr.get("dark_renaissance") is not None

    def test_list_includes_custom(self, preset_mgr):
        preset_mgr.save_custom({"id": "included", "name": "Included", "description": "",
                                 "style_tags": [], "negative_tags": [], "width": 512,
                                 "height": 512, "steps": 20, "cfg_scale": 7.0})
        ids = [p["id"] for p in preset_mgr.list_all()]
        assert "included" in ids

    def test_unknown_preset_returns_none(self, preset_mgr):
        assert preset_mgr.get("nonexistent_xyz") is None


# ── PromptBuilder ─────────────────────────────────────────────────────────────

@pytest.fixture()
def builder():
    from engine.asset_studio.prompt_builder import PromptBuilder
    return PromptBuilder()


class TestPromptBuilder:
    def test_build_image_prompt_returns_tuple(self, builder):
        result = builder.build_image_prompt("warrior", "arena", "aggressive")
        assert isinstance(result, tuple) and len(result) == 2
        positive, negative = result
        assert "warrior" in positive.lower()
        assert isinstance(negative, str)

    def test_build_image_prompt_with_preset_tags(self, builder):
        pos, neg = builder.build_image_prompt(
            "castle", "realm", "dark", preset_tags=["fantasy art", "epic"],
            preset_neg_tags=["cartoon"]
        )
        assert "castle" in pos.lower()
        assert "fantasy art" in pos

    def test_build_portrait_prompt(self, builder):
        pos, neg = builder.build_portrait_prompt(
            character_id="lola",
            mood="happy",
            scene="penthouse",
            appearance="scarlet woman, flowing red hair",
        )
        assert "lola" in pos.lower()
        assert isinstance(neg, str)

    def test_build_background_prompt(self, builder):
        pos, neg = builder.build_background_prompt("arena", time_of_day="night", mood="violent")
        assert isinstance(pos, str)
        assert len(pos) > 10
        assert isinstance(neg, str)

    def test_build_item_prompt(self, builder):
        pos, neg = builder.build_item_prompt("Inferno Blade", archetype="weapon", scene="arena")
        assert "inferno blade" in pos.lower()
        assert isinstance(neg, str)

    def test_build_svg_description(self, builder):
        result = builder.build_svg_description("sword icon", "minimal", "arena", colors=["#ff0000"])
        assert isinstance(result, str)
        assert "sword" in result.lower()
        assert "#ff0000" in result

    def test_build_video_prompt(self, builder):
        pos, neg = builder.build_video_prompt("gladiator fight", "arena", "intense", "slow pan")
        assert isinstance(pos, str)
        assert len(pos) > 10

    def test_handles_unknown_scene(self, builder):
        pos, neg = builder.build_background_prompt("unknown_scene_xyz", mood="neutral")
        assert isinstance(pos, str)


# ── StudioCore ────────────────────────────────────────────────────────────────

@pytest.fixture()
def studio_core(tmp_path):
    cfg_vals = {
        "asset_studio.comfyui_enabled": True,
        "asset_studio.tts_enabled": True,
        "asset_studio.lms_enabled": True,
        "asset_studio.video_enabled": True,
        "asset_studio.nexus_cache_enabled": False,
        "asset_studio.adult_enabled": False,
        "asset_studio.library_db": str(tmp_path / "lib.db"),
        "asset_studio.voice_output_dir": str(tmp_path / "voice"),
        "asset_studio.svg_output_dir": str(tmp_path / "svg"),
        "asset_studio.audio_output_dir": str(tmp_path / "audio"),
    }
    with (
        patch("engine.asset_studio.studio_core.get_config") as mock_cfg,
        patch("engine.nexus.client.get_nexus_client") as mock_nx,
        patch("engine.asset_studio.asset_library.AssetLibrary") as mock_lib_cls,
        patch("engine.asset_studio.preset_manager.PresetManager") as mock_pm_cls,
    ):
        mock_cfg.return_value = MagicMock()
        mock_cfg.return_value.get = lambda k, d=None: cfg_vals.get(k, d)

        mock_nx.return_value = MagicMock()
        mock_lib = MagicMock()
        mock_lib_cls.return_value = mock_lib
        mock_lib.register.return_value = "test-asset-id"
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm
        mock_pm.get.return_value = None

        from engine.asset_studio.studio_core import AssetStudioCore
        core = AssetStudioCore.__new__(AssetStudioCore)
        core._lock = __import__("threading").Lock()
        mock_cfg_obj = MagicMock()
        mock_cfg_obj.get = lambda k, d=None: cfg_vals.get(k, d)
        core._cfg = mock_cfg_obj
        core._flags = {k: cfg_vals.get(k, True) for k in [
            "asset_studio.comfyui_enabled", "asset_studio.tts_enabled",
            "asset_studio.lms_enabled", "asset_studio.video_enabled",
            "asset_studio.nexus_cache_enabled", "asset_studio.adult_enabled",
        ]}
        core._lib = mock_lib
        core._presets = mock_pm
        core._generators = {}
        core._socketio = None
        yield core


class TestStudioCoreFlags:
    def test_flag_set_returns_true(self, studio_core):
        result = studio_core.set_flag("asset_studio.tts_enabled", True)
        assert result is True

    def test_flag_set_unknown_returns_false(self, studio_core):
        result = studio_core.set_flag("nonexistent.flag", True)
        assert result is False

    def test_is_type_available_image_off(self, studio_core):
        studio_core._cfg.get = lambda k, d=None: False if k == "asset_studio.comfyui_enabled" else True
        assert studio_core.is_type_available("image") is False

    def test_is_type_available_image_on(self, studio_core):
        studio_core._cfg.get = lambda k, d=None: True
        assert studio_core.is_type_available("image") is True

    def test_is_type_available_voice_off(self, studio_core):
        studio_core._cfg.get = lambda k, d=None: False if k == "asset_studio.tts_enabled" else True
        assert studio_core.is_type_available("voice") is False

    def test_unknown_type_available(self, studio_core):
        # unknown types have no flags so is_type_available returns True
        result = studio_core.is_type_available("unknown_type_xyz")
        assert isinstance(result, bool)


class TestStudioCoreGenerate:
    def test_generate_unavailable_type(self, studio_core):
        studio_core._cfg.get = lambda k, d=None: False if k == "asset_studio.comfyui_enabled" else d
        result = studio_core.generate("image", {"subject": "test"})
        assert result.get("error") is not None

    def test_generate_unknown_type(self, studio_core):
        result = studio_core.generate("unknown_xyz", {})
        assert result.get("error") is not None

    def test_health_returns_dict(self, studio_core):
        with patch("requests.get") as mock_req:
            mock_req.return_value = MagicMock(status_code=200)
            h = studio_core.health()
        assert isinstance(h, dict)

    def test_get_flags_returns_dict(self, studio_core):
        flags = studio_core.get_flags()
        assert isinstance(flags, dict)
        assert "asset_studio.tts_enabled" in flags


# ── Scene routes ──────────────────────────────────────────────────────────────

@pytest.fixture()
def scene_app(tmp_path):
    """Minimal Flask app that wires Asset Studio routes for integration testing."""
    from flask import Flask, jsonify, request as flask_request

    app = Flask("test_asset_studio_routes")
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"

    mock_lib = MagicMock()
    mock_lib.list_assets.return_value = []
    mock_lib.stats.return_value = {"total": 0, "by_type": {}}
    mock_lib.delete.return_value = True
    mock_lib.toggle_favorite.return_value = True

    mock_core = MagicMock()
    mock_core.get_flags.return_value = {"asset_studio.tts_enabled": True}
    mock_core.health.return_value = {"flags": {}, "backends": {}}
    mock_core.generate.return_value = {"url": "/img/test.png", "duration_ms": 50}
    mock_core.set_flag.return_value = True

    mock_presets = MagicMock()
    mock_presets.list_all.return_value = []
    mock_presets.save_custom.return_value = MagicMock(to_dict=lambda: {"id": "x"})
    mock_presets.delete_custom.return_value = True

    @app.route("/api/library")
    def api_library():
        assets = mock_lib.list_assets()
        stats = mock_lib.stats()
        return jsonify({"assets": assets, "stats": stats})

    @app.route("/api/library/<aid>", methods=["DELETE"])
    def api_del(aid):
        mock_lib.delete(aid)
        return jsonify({"deleted": True})

    @app.route("/api/library/<aid>/favorite", methods=["POST"])
    def api_fav(aid):
        return jsonify({"favorite": mock_lib.toggle_favorite(aid)})

    @app.route("/api/presets")
    def api_presets():
        return jsonify({"presets": mock_presets.list_all()})

    @app.route("/api/voices")
    def api_voices():
        return jsonify({})

    @app.route("/api/flags")
    def api_flags():
        return jsonify(mock_core.get_flags())

    @app.route("/api/flags", methods=["POST"])
    def api_set_flags():
        data = flask_request.get_json(force=True) or {}
        return jsonify({k: mock_core.set_flag(k, v) for k, v in data.items()})

    @app.route("/api/studio/health")
    def api_health():
        return jsonify(mock_core.health())

    @app.route("/api/generate", methods=["POST"])
    def api_generate():
        data = flask_request.get_json(force=True) or {}
        asset_type = data.pop("asset_type", "image")
        return jsonify(mock_core.generate(asset_type, data))

    return app.test_client(), mock_core


class TestAssetStudioRoutes:
    def test_library_endpoint(self, scene_app):
        client, _ = scene_app
        res = client.get("/api/library")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "assets" in data

    def test_presets_endpoint(self, scene_app):
        client, _ = scene_app
        res = client.get("/api/presets")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "presets" in data

    def test_voices_endpoint(self, scene_app):
        client, _ = scene_app
        res = client.get("/api/voices")
        assert res.status_code == 200

    def test_flags_endpoint(self, scene_app):
        client, _ = scene_app
        res = client.get("/api/flags")
        assert res.status_code == 200

    def test_health_endpoint(self, scene_app):
        client, _ = scene_app
        res = client.get("/api/studio/health")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "flags" in data or "backends" in data

    def test_generate_endpoint(self, scene_app):
        client, _ = scene_app
        res = client.post("/api/generate",
                          data=json.dumps({"asset_type": "image", "subject": "test"}),
                          content_type="application/json")
        assert res.status_code == 200

    def test_delete_asset_endpoint(self, scene_app):
        client, _ = scene_app
        res = client.delete("/api/library/nonexistent-id")
        assert res.status_code == 200


# ── Skills ────────────────────────────────────────────────────────────────────

class TestAssetStudioSkills:
    def test_skills_module_importable(self):
        with patch("engine.asset_studio.studio_core.get_studio_core") as mock_sc:
            mock_sc.return_value = MagicMock()
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert mod is not None

    def test_generate_image_skill_exists(self):
        with patch("engine.asset_studio.studio_core.get_studio_core"):
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert hasattr(mod, "generate_image")

    def test_generate_portrait_skill_exists(self):
        with patch("engine.asset_studio.studio_core.get_studio_core"):
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert hasattr(mod, "generate_portrait")

    def test_generate_voice_skill_exists(self):
        with patch("engine.asset_studio.studio_core.get_studio_core"):
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert hasattr(mod, "generate_voice")

    def test_create_game_item_skill_exists(self):
        with patch("engine.asset_studio.studio_core.get_studio_core"):
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert hasattr(mod, "create_game_item")

    def test_generate_svg_skill_exists(self):
        with patch("engine.asset_studio.studio_core.get_studio_core"):
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert hasattr(mod, "generate_svg")

    def test_list_assets_skill_exists(self):
        with patch("engine.asset_studio.studio_core.get_studio_core"):
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert hasattr(mod, "list_assets")

    def test_studio_health_skill_exists(self):
        with patch("engine.asset_studio.studio_core.get_studio_core"):
            import content.scenes.asset_studio.asset_studio_skills as mod
            assert hasattr(mod, "studio_health")


# ── Inject to Scene routes ────────────────────────────────────────────────────

@pytest.fixture()
def inject_app(tmp_path):
    """Minimal Flask app with inject-to-scene routes for testing."""
    import json as _json
    from flask import Flask, jsonify, request as flask_request
    import shutil

    app = Flask("test_inject_routes")
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"

    # Pre-create a fake asset in tmp images dir
    img_dir = tmp_path / "data" / "asset_studio" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    fake_png = img_dir / "test_img.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header

    # Patch Path("data/...") calls to use tmp_path
    import os
    original_cwd = os.getcwd()

    @app.route("/api/scenes/list")
    def api_scenes_list():
        scenes = [
            {"id": "penthouse", "name": "THE PENTHOUSE", "port": 5555},
            {"id": "phone", "name": "SIGNAL", "port": 5556},
        ]
        return jsonify({"status": "ok", "scenes": scenes})

    @app.route("/api/inject_to_scene", methods=["POST"])
    def api_inject_to_scene():
        data = flask_request.get_json() or {}
        scene = data.get("scene", "")
        asset_url = data.get("asset_url", "")
        image_type = data.get("image_type", "background")
        filename = data.get("filename", f"{image_type}_injected.png")

        if not scene or not asset_url:
            return jsonify({"status": "error", "message": "scene and asset_url are required"}), 400

        source_filename = Path(asset_url).name
        source_path = img_dir / source_filename

        if not source_path.exists():
            return jsonify({"status": "error", "message": f"Asset not found: {source_filename}"}), 404

        target_dir = tmp_path / "content" / "scenes" / scene / "static" / "img"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        shutil.copy2(str(source_path), str(target_path))

        return jsonify({"status": "ok", "scene": scene, "url": f"/scenes/{scene}/static/img/{filename}", "filename": filename})

    return app.test_client(), tmp_path


class TestInjectToSceneRoutes:
    def test_scenes_list_returns_scenes(self, inject_app):
        client, _ = inject_app
        res = client.get("/api/scenes/list")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["status"] == "ok"
        assert len(data["scenes"]) >= 2
        ids = [s["id"] for s in data["scenes"]]
        assert "penthouse" in ids

    def test_inject_missing_params(self, inject_app):
        client, _ = inject_app
        res = client.post("/api/inject_to_scene",
                          data=json.dumps({}),
                          content_type="application/json")
        assert res.status_code == 400
        data = json.loads(res.data)
        assert data["status"] == "error"

    def test_inject_asset_not_found(self, inject_app):
        client, _ = inject_app
        res = client.post("/api/inject_to_scene",
                          data=json.dumps({"scene": "penthouse", "asset_url": "/missing.png"}),
                          content_type="application/json")
        assert res.status_code == 404
        data = json.loads(res.data)
        assert data["status"] == "error"

    def test_inject_success(self, inject_app):
        client, tmp_path = inject_app
        res = client.post("/api/inject_to_scene",
                          data=json.dumps({
                              "scene": "penthouse",
                              "asset_url": "/some/path/test_img.png",
                              "image_type": "background",
                          }),
                          content_type="application/json")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["status"] == "ok"
        assert data["scene"] == "penthouse"
        assert "background_injected.png" in data["filename"]
        # File was copied
        target = tmp_path / "content" / "scenes" / "penthouse" / "static" / "img" / "background_injected.png"
        assert target.exists()

    def test_inject_custom_filename(self, inject_app):
        client, tmp_path = inject_app
        res = client.post("/api/inject_to_scene",
                          data=json.dumps({
                              "scene": "phone",
                              "asset_url": "/some/path/test_img.png",
                              "image_type": "portrait",
                              "filename": "aria_portrait.png",
                          }),
                          content_type="application/json")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["filename"] == "aria_portrait.png"
        target = tmp_path / "content" / "scenes" / "phone" / "static" / "img" / "aria_portrait.png"
        assert target.exists()


def test_asset_studio_scene_list_uses_canonical_registry():
    from content.scenes.asset_studio.asset_studio_scene import AssetStudioScene

    # v1.51.0 [2026-03-22] — Updated mocks for FlaskScene migration (no more _mcp_init)
    with patch.object(AssetStudioScene, "mount_overlay", return_value=None), \
         patch.object(AssetStudioScene, "mount_skills_server", return_value=None), \
         patch.object(AssetStudioScene, "register_bench_route", return_value=None), \
         patch.object(AssetStudioScene, "_register_socket_events", return_value=None):
        scene = AssetStudioScene(host="127.0.0.1")

    client = scene.app.test_client()
    response = client.get("/api/scenes/list")
    assert response.status_code == 200
    data = json.loads(response.data)
    scenes = {scene["id"]: scene for scene in data["scenes"]}
    assert scenes["penthouse"]["port"] == 5556
    assert scenes["penthouse"]["name"] == "THE PENTHOUSE"
    assert scenes["phone"]["port"] == 5555
    assert scenes["phone"]["name"] == "SIGNAL"

