"""
Penthouse Dialog Mixin
======================
Director directives, conversation starters, events, and agent-loop wiring.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Runtime invariant log: agents registered == present
                            characters (warn if any character lacks an agent)
    v1.53.1 [2026-03-26] — Added _register_char_with_loop() for hot-registration
    v1.50.0 [2026-03-24] — Initial extraction from penthouse_scene.py
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Any, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PenthouseDialogMixin:
    """Director directives, conversation starters, events, and agent-loop wiring."""

    # ── Governance helper ───────────────────────────────────────────────

    def _get_governance_context(self, agent_id: str) -> str:
        """Get governance directives from the interceptor pipeline."""
        try:
            from engine.mcp.comms_framework import build_governance_context
            ctx = build_governance_context(agent_id, "penthouse", "")
            return f"{ctx}\n\n" if ctx else ""
        except Exception:
            return ""

    # ── Agent loop lifecycle ────────────────────────────────────────────

    def _start_agent_loop(self, interval: float = 30) -> None:
        from engine.agents.agent_loop import AgentLoop
        from engine.agents.character_agent import CharacterAgent
        from content.scenes.penthouse.penthouse_scene import (
            CharacterProfile, build_roleplay_system_prompt,
        )

        if self.agent_loop and self.agent_loop.is_running:
            return
        self.agent_loop = AgentLoop(
            scene_map=self.scene_map,
            db=self.db,
            socketio=self.socketio,
            scene_id="penthouse",
        )
        for cid, char in self.characters.items():
            agent_cfg = self.agent_model_config.get(cid, {})
            try:
                from engine.mcp.character_registry import seed_registry_from_character
                seed_registry_from_character(char)
            except Exception as _reg_exc:
                logger.debug("Registry seed failed for %s: %s", cid, _reg_exc)
            profile_model = None
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                agent_profile = fw.get_agent_profile("big")
                if agent_profile and not agent_cfg.get("model"):
                    profile_model = agent_profile.get("model_hint")
            except Exception:
                pass
            agent = CharacterAgent(
                char,
                db=self.db,
                skill_packs=["memory", "character"],
                model=agent_cfg.get("model") or profile_model,
                scene="penthouse",
            )
            try:
                from engine.mcp.comms_framework import get_governor
                agent = get_governor(agent, scene="penthouse")
            except Exception:
                pass
            self.agent_loop.register_character(char, agent=agent)

        for cid, char in self.characters.items():
            profile = self.profiles.get(cid, CharacterProfile())
            self._refresh_character_state()
            rp_prompt = build_roleplay_system_prompt(
                char, profile, self.scene_state, self.profiles,
                self.story_beats, self.active_scenario,
            )
            gov_ctx = self._get_governance_context(cid)
            self._inject_to_loop(
                "(system)",
                f"[ROLEPLAY CONTEXT for {char.name}]\n{gov_ctx}{rp_prompt}",
                "system",
            )

        self.agent_loop.set_action_callback(self._on_agent_action)
        self.agent_loop.start(interval=interval)
        self.scene_state["agent_loop_running"] = True
        self._broadcast_state()

        # v1.62.0 [2026-06-15] — Runtime invariant: every present character must
        # have its own registered agent so all take agent-driven turns.
        n_agents = len(self.agent_loop._agents)
        n_chars = len(self.characters)
        if n_agents != n_chars:
            logger.warning(
                "[penthouse] agent/character count mismatch — only some characters "
                "are agent-driven (operation=start_agent_loop, agents=%d, characters=%d, "
                "missing=%s)",
                n_agents, n_chars,
                [c for c in self.characters if c not in self.agent_loop._agents],
            )
        else:
            logger.info(
                "[penthouse] all characters registered with agents "
                "(operation=start_agent_loop, agents=%d, characters=%d)",
                n_agents, n_chars,
            )

    # v1.53.0 [2026-03-26] — Hot-register a single character with a running agent loop
    def _register_char_with_loop(self, char) -> None:
        """Register a character with the running agent loop + inject context."""
        from engine.agents.character_agent import CharacterAgent
        from content.scenes.penthouse.penthouse_scene import (
            CharacterProfile, build_roleplay_system_prompt,
        )

        agent_cfg = self.agent_model_config.get(char.id, {})
        try:
            from engine.mcp.character_registry import seed_registry_from_character
            seed_registry_from_character(char)
        except Exception:
            pass

        profile_model = None
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            agent_profile = fw.get_agent_profile("big")
            if agent_profile and not agent_cfg.get("model"):
                profile_model = agent_profile.get("model_hint")
        except Exception:
            pass

        agent = CharacterAgent(
            char,
            db=self.db,
            skill_packs=["memory", "character"],
            model=agent_cfg.get("model") or profile_model,
            scene="penthouse",
        )
        try:
            from engine.mcp.comms_framework import get_governor
            agent = get_governor(agent, scene="penthouse")
        except Exception:
            pass

        self.agent_loop.register_character(char, agent=agent)

        # v1.62.0 [2026-06-15] — Confirm the hot-added character actually got an
        # agent (not just a character entry), so it takes agent-driven turns.
        if char.id not in self.agent_loop._agents:
            logger.warning(
                "[penthouse] hot-added character has no agent — it will stay idle "
                "(operation=register_char, character=%s)", char.id,
            )

        # Inject roleplay context for the new character
        profile = self.profiles.get(char.id, CharacterProfile())
        self._refresh_character_state()
        rp_prompt = build_roleplay_system_prompt(
            char, profile, self.scene_state, self.profiles,
            self.story_beats, self.active_scenario,
        )
        gov_ctx = self._get_governance_context(char.id)
        self._inject_to_loop(
            "(system)",
            f"[ROLEPLAY CONTEXT for {char.name}]\n{gov_ctx}{rp_prompt}",
            "system",
        )

    # ── Framework event-bus handlers ────────────────────────────────────

    def _on_env_change(self, evt) -> None:
        """React to environment_change events from the framework event bus."""
        if evt.payload.get("scene_id") == "penthouse":
            try:
                change = evt.payload.get("change_type", "")
                if change == "lighting":
                    self.scene_state["lighting_key"] = evt.payload.get("value", "evening")
                self.socketio.emit("environment_update", evt.payload)
            except Exception:
                pass

    def _on_mood_event(self, evt) -> None:
        """Push mood contagion updates to connected clients."""
        try:
            self.socketio.emit("mood_update", evt.payload)
        except Exception:
            pass

    def _on_story_beat(self, evt) -> None:
        """Inject story beats from the event bus."""
        if evt.payload.get("scene_id") == "penthouse":
            beat = evt.payload.get("beat", "")
            if beat and beat not in self.story_beats:
                self.story_beats.append(beat)
            try:
                self.socketio.emit("story_beat", evt.payload)
            except Exception:
                pass

    # ── Director routes ─────────────────────────────────────────────────

    def _setup_director_routes(self) -> None:
        """Register director-control Flask routes on self.app."""
        from flask import jsonify, request
        from content.scenes.penthouse.penthouse_scene import PERSONALITY_PROFILES

        @self.app.route("/api/director/whisper", methods=["POST"])
        def whisper():
            data = request.json or {}
            cid = data.get("character_id")
            msg = data.get("message", "")
            target_name = self.characters[cid].name if cid in self.characters else "All"
            self._inject_to_loop("(Director)", f"[whisper to {target_name}] {msg}", "whisper")
            return jsonify({"success": True})

        @self.app.route("/api/director/give_line", methods=["POST"])
        def give_line():
            data = request.json or {}
            cid = data.get("character_id")
            line = data.get("line", "")
            if cid not in self.characters:
                return jsonify({"error": "Character not loaded"}), 400
            name = self.characters[cid].name
            compliance = self.profiles[cid].stats.compliance_score(
                PERSONALITY_PROFILES.get(self.profiles[cid].personality_key, {}).get("compliance_mod", 0)
            )
            if compliance >= 60:
                instruction = f"[DIRECTOR LINE — say exactly:] \"{line}\""
            else:
                instruction = f"[DIRECTOR SUGGESTION — you may adapt or resist:] \"{line}\""
            self._inject_to_loop("(Director)", f"[to {name}] {instruction}", "director_line")
            return jsonify({"success": True, "compliance": compliance})

        @self.app.route("/api/director/give_action", methods=["POST"])
        def give_action():
            data = request.json or {}
            cid = data.get("character_id") or ""
            action = data.get("action", "")
            target = self.characters[cid].name if cid in self.characters else "All characters"
            compliance_note = ""
            if cid in self.profiles:
                c = self.profiles[cid].stats.compliance_score(
                    PERSONALITY_PROFILES.get(self.profiles[cid].personality_key, {}).get("compliance_mod", 0)
                )
                compliance_note = f" (compliance: {c:.0f})"
            self._inject_to_loop("(Director)", f"[ACTION DIRECTIVE to {target}{compliance_note}] {action}", "director_action")
            return jsonify({"success": True})

        @self.app.route("/api/director/broadcast", methods=["POST"])
        def director_broadcast():
            msg = (request.json or {}).get("message", "")
            name = self.director_name if self.director_in_scene else "(The Director)"
            self._inject_to_loop(name, msg, "director")
            self.socketio.emit("director_speaks", {"name": name, "message": msg,
                                                    "timestamp": datetime.now().isoformat()})
            return jsonify({"success": True})

        @self.app.route("/api/director/enter_scene", methods=["POST"])
        def director_enter():
            data = request.json or {}
            self.director_in_scene = data.get("in_scene", True)
            self.director_name = data.get("name", "The Director")
            if self.director_in_scene:
                self._inject_to_loop("(environment)", f"The Director enters the scene as '{self.director_name}'.", "environment")
            else:
                self.director_avatar = None
                self._inject_to_loop("(environment)", "The Director steps back to observe.", "environment")
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/director/avatar", methods=["POST"])
        def director_avatar():
            """Place or update the director's 3D avatar in the scene."""
            data = request.json or {}
            action = data.get("action", "place")
            if action == "remove":
                self.director_avatar = None
                self._inject_to_loop("(environment)", f"{self.director_name}'s avatar fades from the scene.", "environment")
            else:
                self.director_avatar = {
                    "name": self.director_name,
                    "gender": data.get("gender", "male"),
                    "skin_tone": data.get("skin_tone", "fair"),
                    "hair_color": data.get("hair_color", "brown"),
                    "outfit": data.get("outfit", "casual"),
                    "location_id": data.get("location_id", "bed"),
                }
                self.director_in_scene = True
                loc_name = self.director_avatar["location_id"]
                self._inject_to_loop("(environment)", f"{self.director_name} appears at the {loc_name}.", "environment")
            self._broadcast_state()
            return jsonify({"success": True, "avatar": self.director_avatar})

        @self.app.route("/api/director/avatar/move", methods=["POST"])
        def director_avatar_move():
            """Move the director's avatar to a new location."""
            data = request.json or {}
            if not self.director_avatar:
                return jsonify({"error": "No director avatar in scene"}), 400
            loc_id = data.get("location_id", "bed")
            self.director_avatar["location_id"] = loc_id
            self._inject_to_loop("(environment)", f"{self.director_name} moves to the {loc_id}.", "environment")
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/director/mount", methods=["POST"])
        def director_mount():
            data = request.json or {}
            cid = data.get("character_id")
            position = data.get("position", "standing")
            location_id = data.get("location_id")
            if cid not in self.characters:
                return jsonify({"error": "Character not loaded"}), 400
            name = self.characters[cid].name
            if cid in self.profiles:
                self.profiles[cid].position = position
            if location_id:
                self.scene_map.move_character(cid, location_id)
            self._inject_to_loop("(environment)", f"{name} is now {position} on the {location_id or 'bed'}.", "environment")
            self._broadcast_state()
            return jsonify({"success": True, "position": position})

        @self.app.route("/api/director/interact", methods=["POST"])
        def director_interact():
            data = request.json or {}
            actor_id = data.get("actor_id")
            target_id = data.get("target_id")
            interaction = data.get("interaction", "")
            if not interaction:
                return jsonify({"error": "No interaction specified"}), 400
            actor_name = self.characters[actor_id].name if actor_id in self.characters else self.director_name
            target_name = self.characters[target_id].name if target_id in self.characters else "the room"

            from engine.mcp.interaction_trees import PENTHOUSE_INTERACTIONS, get_interaction_result
            tree_result = None
            interaction_lower = interaction.lower().strip()
            tree_map = {
                "cuddle": "cuddle", "spoon": "cuddle", "hold": "cuddle",
                "kiss": "kiss", "make out": "kiss",
                "touch": "touch", "caress": "touch", "fondle": "touch",
                "massage": "massage", "rub": "massage",
                "talk": "deep_talk", "pillow talk": "deep_talk", "whisper": "deep_talk",
                "sex": "penetration", "fuck": "penetration", "ride": "penetration",
                "penetration": "penetration",
            }
            matched_type = None
            for keyword, tree_type in tree_map.items():
                if keyword in interaction_lower:
                    matched_type = tree_type
                    break

            if matched_type:
                actor_stats = {}
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    actor_stats = get_coordinator().get_full_state(actor_id or "director") or {}
                except Exception:
                    pass
                tree_result = get_interaction_result(
                    matched_type, scene="penthouse", initiator_stats=actor_stats
                )

            if tree_result and not tree_result.get("error"):
                phases = tree_result.get("phases", [])
                fragments = tree_result.get("fragments", [])
                phase_hint = f" Phases: {' → '.join(phases)}." if phases else ""
                fragment_hint = f' Inspiration: "{fragments[0]}"' if fragments else ""
                directive = f"{actor_name} initiates {tree_result['label']} with {target_name}.{phase_hint}{fragment_hint}"
                if tree_result.get("stat_effects") and actor_id:
                    try:
                        from engine.mcp.state_coordinator import get_coordinator
                        get_coordinator().update(actor_id, source="interaction_tree", **tree_result["stat_effects"])
                    except Exception:
                        pass
            else:
                directive = f"{actor_name} {interaction} {target_name}."

            self._inject_to_loop("(environment)", directive, "environment")
            self.socketio.emit("scene_event", {"type": "interaction", "message": directive})
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/interactions")
        def list_interactions():
            """List available interaction types with stat requirements."""
            from engine.mcp.interaction_trees import list_interaction_types
            return jsonify({"ok": True, "interactions": list_interaction_types("penthouse")})

    # ── Conversation routes ─────────────────────────────────────────────

    def _setup_conversation_routes(self) -> None:
        """Register conversation-start Flask routes on self.app."""
        from flask import jsonify, request

        @self.app.route("/api/conversation/start", methods=["POST"])
        def start_conversation():
            data = request.json or {}
            conv_type = data.get("type", "flirt")
            starters = {
                "flirt":       "It's getting quite warm in here... isn't it? Or is that just me?",
                "confession":  "I need to tell you something I've been holding back all evening...",
                "dare":        "I dare you to do something you've never done in this room before.",
                "compliment":  "You have absolutely no idea how beautiful you look right now.",
                "fantasy":     "Tell me your most vivid fantasy. Don't leave anything out.",
                "game":        "Let's play a game. Every lie costs you a piece of clothing.",
                "roleplay_meta": "Let's pretend we just met. You walk in... and I see you for the first time.",
                "power_play":  "For the next ten minutes, I'm telling you what to do. And you will do it.",
            }
            starter = starters.get(conv_type, starters["flirt"])
            char_names = [c.name for c in self.characters.values()]
            speaker = char_names[0] if char_names else "(character)"
            self._inject_to_loop(speaker, starter, "speech")
            self.socketio.emit("conversation_started", {"type": conv_type, "line": starter, "speaker": speaker})
            return jsonify({"success": True, "line": starter})

    # ── Event routes ────────────────────────────────────────────────────

    def _setup_event_routes(self) -> None:
        """Register environment-event Flask routes on self.app."""
        from flask import jsonify, request

        @self.app.route("/api/event/fire", methods=["POST"])
        def fire_event():
            data = request.json or {}
            ev_type = data.get("type", "")
            ev_custom = data.get("custom", "")
            events = {
                "flicker_lights": "The lights flicker and dim ominously.",
                "strange_sound":  "A strange, seductive sound drifts through the room.",
                "cold_draft":     "A sudden icy draft sweeps through, raising goosebumps.",
                "move_object":    "Something shifts on its own in the corner of the room.",
                "knock":          "Three slow knocks from the door — but nobody answers.",
                "power_out":      "The lights go completely dark.",
                "romantic_mood":  "The lighting shifts to a warm, intimate amber glow.",
                "thunder":        "Thunder shakes the room; lightning flashes.",
                "lock_door":      "The sound of a lock clicking. Nobody is leaving tonight.",
                "music_on":       "Slow, sensual music begins playing from an unseen speaker.",
                "candles_light":  "Every candle in the room ignites at once.",
                "rose_petals":    "Rose petals drift from the ceiling onto the bed.",
                "phone_rings":    "A phone rings — persistent, intrusive. Who could it be?",
                "door_opens":     "The door creaks open on its own.",
            }
            if ev_type == "":
                ev_type = data.get("menace_type", data.get("type", ""))
            msg = ev_custom if ev_custom else events.get(ev_type, f"Something unusual happens.")
            self._inject_to_loop("(environment)", msg, "environment")
            self.socketio.emit("scene_event", {"type": ev_type, "message": msg})
            self.socketio.emit("menace_event", {"type": ev_type, "message": msg})
            self._sync_to_mcp("scene_event", {"type": ev_type, "message": msg})
            return jsonify({"success": True, "message": msg})

        @self.app.route("/api/menace", methods=["POST"])
        def menace_action():
            data = request.get_json(force=True)
            data["type"] = data.get("type", "")
            return fire_event()

    # ── Agent-loop routes ───────────────────────────────────────────────

    def _setup_agent_routes(self) -> None:
        """Register agent-loop and model Flask routes on self.app."""
        from flask import jsonify, request
        from pathlib import Path

        @self.app.route("/api/agents/start", methods=["POST"])
        def start_agent_loop():
            if len(self.characters) < 1:
                return jsonify({"error": "Need at least 1 character"}), 400
            interval = (request.json or {}).get("interval", 30)
            self._start_agent_loop(interval)
            return jsonify({"success": True})

        @self.app.route("/api/agents/stop", methods=["POST"])
        def stop_agent_loop():
            if self.agent_loop:
                self.agent_loop.stop()
            self.scene_state["agent_loop_running"] = False
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/agents/tick", methods=["POST"])
        def manual_tick():
            if not self.agent_loop:
                self._start_agent_loop(interval=9999)
                self.agent_loop.stop()
            actions = self.agent_loop.tick()
            self._broadcast_state()
            return jsonify({"actions": actions})

        @self.app.route("/api/agents/whisper", methods=["POST"])
        def whisper_legacy():
            """Legacy whisper endpoint. Prefer /api/director/whisper."""
            data = request.json or {}
            cid = data.get("character_id")
            msg = data.get("message", "")
            target_name = self.characters[cid].name if cid in self.characters else "All"
            self._inject_to_loop("(Director)", f"[whisper to {target_name}] {msg}", "whisper")
            return jsonify({"success": True})

        @self.app.route("/api/agents/model", methods=["POST"])
        def set_agent_model():
            data = request.json or {}
            cid = data.get("character_id")
            model = data.get("model")
            mode = data.get("mode", "default")
            if cid and cid in self.characters:
                self.agent_model_config[cid] = {"model": model, "mode": mode}
                return jsonify({"success": True})
            return jsonify({"error": "Character not loaded"}), 400

        @self.app.route("/api/agents/model", methods=["GET"])
        def get_agent_models():
            config = {}
            for cid in self.characters:
                cfg = self.agent_model_config.get(cid, {})
                config[cid] = {
                    "character": self.characters[cid].name,
                    "model": cfg.get("model"),
                    "mode": cfg.get("mode", "default"),
                }
            return jsonify(config)

        @self.app.route("/api/models/available")
        def list_models():
            models: Dict[str, Any] = {"loaded": [], "available": []}
            try:
                from engine.agents.virtual_agent_manager import get_virtual_agent_manager
                mgr = get_virtual_agent_manager()
                models["agents"] = mgr.list_agents()
                models["stats"] = mgr.get_stats()
            except Exception:
                pass
            try:
                from engine.lmstudio.lms_client import get_lms_client
                client = get_lms_client()
                loaded = client.get_models(loaded_only=True, raw=True)
                models["loaded"] = [
                    {"id": m["id"], "display_name": m.get("display_name", m["id"]),
                     "params": m.get("params", ""), "context_length": m.get("context_length", 0)}
                    for m in loaded
                ]
                all_models = client.get_models(loaded_only=False, raw=True)
                loaded_ids = {m["id"] for m in loaded}
                models["available"] = [
                    {"id": m["id"], "display_name": m.get("display_name", m["id"]),
                     "params": m.get("params", "")}
                    for m in all_models if m["id"] not in loaded_ids
                ]
            except Exception as exc:
                logger.error("Failed to fetch models: %s", exc)
            return jsonify(models)
