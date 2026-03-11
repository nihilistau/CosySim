"""penthouse scene social, character, spatial, and scenario mixin."""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Dict, List, Any, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PenthouseSocialMixin:
    """Character lifecycle, stats, spatial movement, scenarios, and utility routes."""

    # ── Character loading ───────────────────────────────────────────────

    def _load_character(self, char_id: str, personality_key: str = None) -> Optional[Any]:
        from content.scenes.penthouse.penthouse_scene import (
            OUTFITS, POSITIONS, PERSONALITY_PROFILES, AgentStats, CharacterProfile,
        )
        from content.simulation.character_system.character import Character

        if len(self.characters) >= 2 and char_id not in self.characters:
            return None
        char = Character.load(char_id, db=self.db)
        if not char:
            return None
        self.characters[char.id] = char
        if not self.active_character:
            self.active_character = char

        pk = personality_key or (
            "bold_dominant" if len(self.characters) == 1 else "shy_submissive"
        )
        p_info = PERSONALITY_PROFILES.get(pk, PERSONALITY_PROFILES["playful_tease"])
        stats = AgentStats(**{k: v for k, v in p_info["base_stats"].items()})
        profile = CharacterProfile(
            personality_key=pk,
            traits=list(p_info["traits"]),
            likes=list(p_info["likes"]),
            dislikes=list(p_info["dislikes"]),
            outfit=OUTFITS[0],
            position=POSITIONS[0],
            stats=stats,
        )
        self.profiles[char.id] = profile

        empty = self.scene_map.get_empty_locations()
        loc = random.choice(empty) if empty else self.scene_map.get_location("doorway")
        if loc:
            self.scene_map.place_character(char.id, loc.id)
        self._broadcast_state()
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            fw.get_character(char.id).enter_scene("penthouse")
        except Exception:
            pass
        return char

    # ── Character state refresh ─────────────────────────────────────────

    def _refresh_character_state(self) -> None:
        from content.scenes.penthouse.penthouse_scene import (
            PERSONALITY_PROFILES, CharacterProfile,
        )

        self.scene_state["characters"] = {}
        for cid, char in self.characters.items():
            loc = self.scene_map.get_character_location(cid)
            profile = self.profiles.get(cid, CharacterProfile())
            self.scene_state["characters"][cid] = {
                "name": char.name,
                "gender": self._get_character_gender(char),
                "bio": getattr(char, "description", "") or getattr(char, "bio", "") or "",
                "mood": char.mood,
                "location": loc.name if loc else None,
                "location_id": loc.id if loc else None,
                "outfit": profile.outfit,
                "position": profile.position,
                "props_held": profile.props_held,
                "personality": profile.personality_key,
                "stats": profile.stats.to_dict(),
                "compliance_score": round(profile.stats.compliance_score(
                    PERSONALITY_PROFILES.get(profile.personality_key, {}).get("compliance_mod", 0)
                ), 1),
                "feeling": profile.stats.describe(),
            }
        self.scene_state["room_props"] = self.room_props
        self.scene_state["active_scenario"] = self.active_scenario
        self.scene_state["story_beats"] = self.story_beats[:5]
        self.scene_state["director_in_scene"] = self.director_in_scene
        self.scene_state["director_avatar"] = self.director_avatar
        self.scene_state["bed_game"] = self.bed_game.to_dict()

    # ── Character routes ────────────────────────────────────────────────

    def _setup_character_routes(self) -> None:
        """Register character CRUD Flask routes on self.app."""
        from flask import jsonify, request

        @self.app.route("/api/characters/list")
        def list_characters():
            try:
                db_chars = self.db.get_all_characters()
                for c in db_chars:
                    c["source"] = "database"
                    c["loaded"] = c["id"] in self.characters
                    c["traits"] = c.get("tags", [])
                return jsonify({"characters": db_chars, "count": len(db_chars)})
            except Exception as exc:
                logger.error("list_characters failed: %s", exc, exc_info=True)
                return jsonify({"characters": [], "error": str(exc), "count": 0}), 500

        @self.app.route("/api/character/load", methods=["POST"])
        def load_character():
            try:
                data = request.json or {}
                cid = data.get("character_id")
                personality = data.get("personality")
                if not cid:
                    return jsonify({"error": "No character_id"}), 400
                if len(self.characters) >= 2 and cid not in self.characters:
                    return jsonify({"error": "Maximum 2 characters in penthouse"}), 400
                char = self._load_character(cid, personality)
                if not char:
                    return jsonify({"error": "Character not found"}), 404
                return jsonify({"success": True, "character": {"id": char.id, "name": char.name}})
            except Exception as exc:
                logger.error("load_character failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/character/remove", methods=["POST"])
        def remove_character():
            cid = (request.json or {}).get("character_id")
            if cid in self.characters:
                del self.characters[cid]
                self.profiles.pop(cid, None)
                self.scene_map.remove_character(cid)
                if self.agent_loop:
                    self.agent_loop.unregister_character(cid)
                self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/characters/loaded")
        def loaded_characters():
            self._refresh_character_state()
            return jsonify({"characters": self.scene_state["characters"]})

    # ── Stat routes ─────────────────────────────────────────────────────

    def _setup_stat_routes(self) -> None:
        """Register stat-adjustment Flask routes on self.app."""
        from flask import jsonify, request

        @self.app.route("/api/character/stats/adjust", methods=["POST"])
        def adjust_stat():
            data = request.json or {}
            cid = data.get("character_id")
            stat = data.get("stat")
            delta = float(data.get("delta", 0))
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            self.profiles[cid].stats.adjust(**{stat: delta})
            try:
                from engine.mcp.state_coordinator import get_coordinator
                get_coordinator().update(cid, source="director_adjust", scene="penthouse", **{stat: delta})
            except Exception:
                pass
            self._broadcast_state()
            self._sync_to_mcp("stat_adjusted", {"character_id": cid, "stat": stat, "delta": delta})
            return jsonify({"success": True, "stats": self.profiles[cid].stats.to_dict()})

        @self.app.route("/api/character/stats/set", methods=["POST"])
        def set_stat():
            data = request.json or {}
            cid = data.get("character_id")
            stat = data.get("stat")
            value = float(data.get("value", 50))
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            setattr(self.profiles[cid].stats, stat, value)
            self.profiles[cid].stats.clamp()
            try:
                from engine.mcp.state_coordinator import get_coordinator
                get_coordinator().update(cid, source="director_set", scene="penthouse", **{stat: value})
            except Exception:
                pass
            self._broadcast_state()
            return jsonify({"success": True})

    # ── Spatial routes ──────────────────────────────────────────────────

    def _setup_spatial_routes(self) -> None:
        """Register location/movement Flask routes on self.app."""
        from flask import jsonify, request
        from content.scenes.penthouse.penthouse_scene import POSITIONS

        @self.app.route("/api/location/move", methods=["POST"])
        def move_character():
            data = request.json or {}
            cid = data.get("character_id")
            loc_id = data.get("location_id")
            if not loc_id:
                loc = self.scene_map.get_location_by_name(data.get("location", ""))
                loc_id = loc.id if loc else None
            if not loc_id or cid not in self.characters:
                return jsonify({"error": "Invalid character or location"}), 400
            ok = self.scene_map.move_character(cid, loc_id)
            loc_obj = self.scene_map.get_location(loc_id)
            if loc_obj:
                self._inject_to_loop("(environment)", f"{self.characters[cid].name} moves to {loc_obj.name}.", "environment")
            self._broadcast_state()
            self._sync_to_mcp("character_moved", {"character_id": cid, "location": loc_id})
            return jsonify({"success": ok})

        @self.app.route("/api/locations")
        def list_locations():
            self._refresh_location_state()
            return jsonify({"locations": self.scene_state["locations"], "positions": POSITIONS})

    # ── Scenario / Story-beat routes ────────────────────────────────────

    def _setup_scenario_routes(self) -> None:
        """Register scenario and story-beat Flask routes on self.app."""
        from flask import jsonify, request
        from content.scenes.penthouse.penthouse_scene import PREMADE_SCENARIOS

        @self.app.route("/api/scenario/list")
        def list_scenarios():
            return jsonify({k: {"label": v["label"], "emoji": v["emoji"], "opening": v["opening"]}
                            for k, v in PREMADE_SCENARIOS.items()})

        @self.app.route("/api/scenario/set", methods=["POST"])
        def set_scenario():
            key = (request.json or {}).get("scenario_key")
            if key not in PREMADE_SCENARIOS:
                return jsonify({"error": "Unknown scenario"}), 400
            self.active_scenario = key
            sc = PREMADE_SCENARIOS[key]
            for stat, delta in sc.get("mood_shift", {}).items():
                for cid, profile in self.profiles.items():
                    profile.stats.adjust(**{stat: delta})
                    try:
                        from engine.mcp.state_coordinator import get_coordinator
                        get_coordinator().update(cid, source="scenario_mood", scene="penthouse", **{stat: delta})
                    except Exception:
                        pass
            self._inject_to_loop("(Scene)", sc["opening"], "scenario")
            self.story_beats = list(sc.get("beats", []))
            self.scene_state["active_scenario"] = key
            self.scene_state["story_beats"] = self.story_beats[:5]
            self._broadcast_state()
            self._sync_to_mcp("scenario_started", {"scenario": key})
            return jsonify({"success": True, "opening": sc["opening"]})

        @self.app.route("/api/scenario/clear", methods=["POST"])
        def clear_scenario():
            self.active_scenario = None
            self.story_beats = []
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/story/beat", methods=["POST"])
        def add_story_beat():
            beat = (request.json or {}).get("beat", "")
            if beat:
                self.story_beats.append(beat)
            self._broadcast_state()
            return jsonify({"success": True, "beats": self.story_beats})

        @self.app.route("/api/story/beats")
        def get_story_beats():
            return jsonify({"beats": self.story_beats})

        @self.app.route("/api/story/clear_beat", methods=["POST"])
        def clear_beat():
            idx = (request.json or {}).get("index", 0)
            try:
                self.story_beats.pop(idx)
            except IndexError:
                pass
            return jsonify({"success": True, "beats": self.story_beats})

    # ── Utility / MCP API routes ────────────────────────────────────────

    def _setup_utility_routes(self) -> None:
        """Register mode, history, ambient, constants, and MCP API routes."""
        from flask import jsonify, request
        from pathlib import Path
        from content.scenes.penthouse.penthouse_scene import (
            POSITIONS, OUTFITS, PROPS, PERSONALITY_PROFILES,
            LIGHTING_PRESETS, PREMADE_SCENARIOS,
        )

        @self.app.route("/api/mode", methods=["POST"])
        def set_mode():
            mode = (request.json or {}).get("mode", "observe")
            self.scene_state["mode"] = mode
            self._broadcast_state()
            return jsonify({"success": True, "mode": mode})

        @self.app.route("/api/history")
        def get_history():
            if self.agent_loop:
                return jsonify({"success": True, "history": self.agent_loop.shared_log[-100:]})
            return jsonify({"success": True, "history": []})

        @self.app.route("/api/ambient/tracks")
        def list_ambient_tracks():
            audio_dir = Path(__file__).parent / "static" / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
            tracks = [f.name for f in audio_dir.iterdir() if f.suffix.lower() in exts]
            return jsonify(sorted(tracks))

        @self.app.route("/api/meta/constants")
        def get_constants():
            return jsonify({
                "positions": POSITIONS,
                "outfits": OUTFITS,
                "props": PROPS,
                "personalities": {k: {"traits": v["traits"]} for k, v in PERSONALITY_PROFILES.items()},
                "lighting_presets": LIGHTING_PRESETS,
                "scenarios": {k: {"label": v["label"], "emoji": v["emoji"],
                              "beats": v.get("beats", []), "opening": v.get("opening", "")}
                             for k, v in PREMADE_SCENARIOS.items()},
            })

        # ── MCP Framework API ─────────────────────────────────────────
        @self.app.route("/api/mcp/status")
        def mcp_status():
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                return jsonify({"ok": True, "status": fw.get_status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/scene-state")
        def mcp_scene_state():
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                scene_node = fw.get_scene("penthouse")
                return jsonify({"ok": True, "state": scene_node.get_state() if scene_node else {}})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/event-log")
        def mcp_event_log():
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                limit = int(request.args.get("limit", 50))
                return jsonify({"ok": True, "events": fw.get_event_log(limit=limit)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/lmstudio")
        def mcp_lmstudio():
            try:
                from engine.lmstudio.model_manager import get_model_manager
                mm = get_model_manager()
                return jsonify({"ok": True, "config": mm.get_full_config(), "status": mm.status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/resources")
        def mcp_resources():
            try:
                from engine.lmstudio.resource_manager import get_resource_manager
                rm = get_resource_manager()
                return jsonify({"ok": True, "resources": rm.get_status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/resources/config", methods=["POST"])
        def mcp_resources_config():
            try:
                from engine.lmstudio.resource_manager import get_resource_manager
                rm = get_resource_manager()
                data = request.get_json(force=True)
                result = rm.update_config(**data)
                return jsonify({"ok": True, "resources": result})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/inference-defaults")
        def mcp_inference_defaults():
            try:
                from engine.lmstudio.inference_config import InferenceConfig
                defaults = InferenceConfig.from_yaml()
                return jsonify({"ok": True, "defaults": defaults.to_dict()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/config", methods=["GET", "POST"])
        def mcp_config():
            try:
                from engine.config import get_config
                config = get_config()
                if request.method == "POST":
                    updates = request.json or {}
                    for key, value in updates.items():
                        config.set(key, value)
                    return jsonify({"ok": True, "message": "Config updated"})
                return jsonify({"ok": True, "config": {
                    "agent_profiles": config.get("agent_profiles", {}),
                    "framework": config.get("framework", {}),
                    "scenes.penthouse": config.get("scenes.penthouse", {}),
                }})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500
