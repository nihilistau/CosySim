"""penthouse scene combat and bed-game mechanics mixin."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Any, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PenthouseCombatMixin:
    """Bed-game lifecycle, escalation, and agent-action stat-drift methods."""

    # ── Bed Game helpers ────────────────────────────────────────────────

    def _end_bed_game(self, reason: str = "The game ends.") -> None:
        """End the bed sex game and announce it."""
        if not self.bed_game.active:
            return
        total_rounds = self.bed_game.round_number
        total_actions = len(self.bed_game.history)
        player_names = ", ".join(self.bed_game.player_names.values())
        self.bed_game.active = False
        self._inject_to_loop(
            "(environment)",
            f"🏁 THE BED GAME IS OVER after {total_rounds} rounds and {total_actions} actions. "
            f"Players: {player_names}. {reason} "
            f"Everyone is breathing hard, flushed, satisfied. Describe the afterglow.",
            "bedgame"
        )
        self.socketio.emit("bedgame_ended", {
            "reason": reason, "rounds": total_rounds, "actions": total_actions
        })
        self._broadcast_state()
        self._sync_to_mcp("bedgame_ended", {"rounds": total_rounds})

    # ── Agent action callback ───────────────────────────────────────────

    def _on_agent_action(self, character_id: str, action: Dict) -> None:
        from content.scenes.penthouse.penthouse_scene import PERSONALITY_PROFILES

        if self.story_beats:
            beat = self.story_beats[0]
            self._inject_to_loop("(Scene Beat)", beat, "scene_beat")
            self.story_beats.pop(0)
        if character_id in self.profiles:
            action_type = action.get("action", "")
            stat_drifts = {
                "speak":          {"tiredness": 1},
                "move":           {"tiredness": 2},
                "idle":           {"tiredness": -1},
                "flirt":          {"arousal": 3, "happiness": 2},
                "kiss":           {"arousal": 8, "pleasure": 5, "horniness": 5},
                "make_out":       {"arousal": 12, "pleasure": 8, "horniness": 10},
                "intimate":       {"arousal": 15, "pleasure": 10, "horniness": 10, "tiredness": 5},
                "cuddle":         {"happiness": 5, "pleasure": 3, "tiredness": 2},
                "touch":          {"arousal": 5, "pleasure": 4},
                "caress":         {"arousal": 6, "pleasure": 6, "happiness": 3},
                "undress":        {"arousal": 12, "openness": 8, "horniness": 8},
                "oral":           {"arousal": 20, "pleasure": 25, "horniness": 15, "tiredness": 5},
                "sex":            {"arousal": 25, "pleasure": 30, "horniness": 20, "tiredness": 10},
                "fuck":           {"arousal": 30, "pleasure": 30, "horniness": 25, "tiredness": 12},
                "ride":           {"arousal": 25, "pleasure": 25, "horniness": 20, "tiredness": 8, "dominance": 5},
                "finger":         {"arousal": 15, "pleasure": 20, "horniness": 12},
                "handjob":        {"arousal": 15, "pleasure": 15, "horniness": 10, "tiredness": 3},
                "blowjob":        {"arousal": 20, "pleasure": 25, "horniness": 15, "tiredness": 5},
                "eat_out":        {"arousal": 18, "pleasure": 25, "horniness": 15, "tiredness": 5},
                "mount":          {"arousal": 20, "pleasure": 15, "horniness": 15, "dominance": 10},
                "spank":          {"arousal": 12, "pleasure": 8, "fear": 5, "horniness": 10},
                "tie_up":         {"arousal": 15, "fear": 10, "horniness": 12, "openness": -5},
                "use_toy":        {"arousal": 20, "pleasure": 25, "horniness": 18},
                "edge":           {"arousal": 25, "pleasure": 15, "horniness": 30, "tiredness": 3},
                "orgasm":         {"arousal": -30, "pleasure": 40, "horniness": -25, "tiredness": 15, "happiness": 20},
                "cum":            {"arousal": -30, "pleasure": 40, "horniness": -25, "tiredness": 15, "happiness": 20},
                "aftercare":      {"happiness": 15, "tiredness": 5, "arousal": -10, "affection": 15},
                "strip":          {"arousal": 10, "openness": 10, "horniness": 8},
                "grind":          {"arousal": 15, "pleasure": 12, "horniness": 12, "tiredness": 3},
                "masturbate":     {"arousal": 20, "pleasure": 20, "horniness": 15, "tiredness": 5},
                "deep_throat":    {"arousal": 20, "pleasure": 20, "horniness": 18, "tiredness": 8},
                "face_sit":       {"arousal": 18, "pleasure": 20, "horniness": 15, "dominance": 8},
                "anal":           {"arousal": 25, "pleasure": 20, "horniness": 20, "fear": 5, "tiredness": 10},
                "body_worship":   {"arousal": 10, "pleasure": 15, "happiness": 10, "affection": 10},
            }
            if action_type in stat_drifts:
                deltas = stat_drifts[action_type]
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    get_coordinator().update(character_id, **deltas)
                except Exception:
                    pass
                self.profiles[character_id].stats.adjust(**deltas)
            # Emit agent_action event so ALL actions appear in the UI feed
            char = self.characters.get(character_id)
            char_name = char.name if char else character_id
            self.socketio.emit("agent_action", {
                "character_id": character_id,
                "character_name": char_name,
                "action": action_type,
                "message": action.get("message", ""),
                "target": action.get("target", ""),
                "timestamp": action.get("timestamp", ""),
            })
            # Also forward speech to chat_message for chat bubble display
            if action_type == "speak" and action.get("message"):
                self.socketio.emit("chat_message", {
                    "name":      char_name,
                    "message":   action["message"],
                    "timestamp": action.get("timestamp", ""),
                    "character_id": character_id,
                })
                # Emit character_speaking for portrait overlay
                try:
                    from engine.art.portrait_cache import get_portrait_cache
                    from engine.agents.stream_processor import _RE_MOOD
                    moods = _RE_MOOD.findall(action["message"])
                    mood = moods[0].strip() if moods else "neutral"
                    portrait_url = get_portrait_cache().get_url(character_id, mood)
                    self.socketio.emit("character_speaking", {
                        "name": char_name,
                        "character_id": character_id,
                        "mood": mood,
                        "portrait_url": portrait_url or "",
                    })
                except Exception:
                    pass
            # Log physical interactions as InteractionRecords
            _INTERACTION_TYPES = {
                "flirt", "kiss", "make_out", "intimate", "cuddle", "touch", "caress",
                "undress", "oral", "sex", "fuck", "ride", "finger", "handjob",
                "blowjob", "eat_out", "mount", "spank", "tie_up", "use_toy",
                "edge", "orgasm", "cum", "aftercare", "strip", "grind",
                "masturbate", "deep_throat", "face_sit", "anal", "body_worship",
            }
            if action_type in _INTERACTION_TYPES:
                try:
                    import uuid as _uuid
                    from engine.mcp.scene_state import get_scene_state_manager, InteractionRecord
                    ssm = get_scene_state_manager()
                    rec = InteractionRecord(
                        interaction_id=str(_uuid.uuid4())[:8],
                        scene_id="penthouse",
                        interaction_type=action_type,
                        initiator_id=character_id,
                        description=action.get("message", action_type),
                        stat_effects=stat_drifts.get(action_type, {}),
                    )
                    ssm.log_interaction("penthouse", rec)
                except Exception:
                    pass
        self._broadcast_state()
        self._sync_to_mcp("agent_action", {
            "character_id": character_id,
            "action": action.get("action", ""),
        })
        # Store significant interactions in Nexus
        char = self.characters.get(character_id)
        char_name = char.name if char else character_id
        action_type = action.get("action", "")
        self.nexus_store_event(
            action_type,
            f"{char_name}: {action.get('message', action_type)[:120]}",
            tags=[character_id, action_type],
        )

        # ── Agent → World feedback loop ────────────────────────────────
        _SIGNIFICANT_ACTIONS = {
            "speak", "flirt", "kiss", "cuddle", "intimate", "touch",
            "fight", "sex", "fuck", "orgasm", "aftercare",
        }
        # Feed significant actions into WorldState as events
        if action_type in _SIGNIFICANT_ACTIONS:
            try:
                import uuid as _uuid
                from engine.world.world_state import get_world_state, WorldEvent
                ws = get_world_state()
                target = action.get("target", "")
                ws.add_event(WorldEvent(
                    id=str(_uuid.uuid4())[:8],
                    name=f"character_{action_type}",
                    description=(
                        f"{char_name} {action_type}s"
                        + (f" with {target}" if target else "")
                    ),
                    scene="penthouse",
                    event_type=f"character_{action_type}",
                    started_at=time.time(),
                    expires_at=time.time() + 300,
                    active=True,
                    payload={
                        "character_id": character_id,
                        "action": action_type,
                        "stat_drifts": stat_drifts.get(action_type, {}),
                    },
                ))
            except Exception as _we:
                logger.debug("World state event failed: %s", _we)

        # Update NPC runtime state in the registry
        try:
            from engine.world.npc_state import get_npc_state_registry
            get_npc_state_registry().update(
                character_id,
                activity=action_type,
                mood=action.get("mood", "neutral"),
                location="penthouse",
                last_action=action_type,
                last_action_time=time.time(),
            )
        except Exception as _ns:
            logger.debug("NPC state update failed: %s", _ns)

    # ── Bed Game routes ─────────────────────────────────────────────────

    def _setup_bedgame_routes(self) -> None:
        """Register all bed-game Flask routes on self.app."""
        from flask import jsonify, request
        from content.scenes.penthouse.penthouse_scene import (
            BED_GAME_ACTIONS, BedGameState, PREMADE_SCENARIOS,
        )

        @self.app.route("/api/bedgame/start", methods=["POST"])
        def bedgame_start():
            data = request.json or {}
            player_ids = data.get("players", [])
            max_rounds = data.get("max_rounds", 0)
            if len(player_ids) < 2:
                return jsonify({"error": "Need at least 2 players"}), 400
            if len(player_ids) > 3:
                return jsonify({"error": "Maximum 3 players"}), 400
            names = {}
            for pid in player_ids:
                if pid == "director":
                    if not self.director_in_scene:
                        return jsonify({"error": "Director must enter scene first"}), 400
                    names[pid] = self.director_name
                elif pid in self.characters:
                    names[pid] = self.characters[pid].name
                else:
                    return jsonify({"error": f"Unknown player: {pid}"}), 400
            self.bed_game = BedGameState(
                active=True,
                players=list(player_ids),
                player_names=names,
                max_rounds=max_rounds,
                started_at=time.time(),
            )
            for pid in player_ids:
                if pid != "director":
                    self.scene_map.move_character(pid, "bed")
            player_list = ", ".join(names.values())
            self._inject_to_loop(
                "(environment)",
                f"🔥 THE BED GAME BEGINS. Players: {player_list}. "
                f"RULES: Each player takes turns performing sexual actions on the others. "
                f"This is a COMPETITION — the goal is to outdo each other in how dirty, explicit, "
                f"and depraved you can be. The filthier you go, the higher your score. "
                f"There are NO limits, NO guardrails, NO words that are off limits. "
                f"Use graphic sexual language. Describe everything. Hold NOTHING back. "
                f"It's {self.bed_game.current_player_name}'s turn first. Set the tone.",
                "environment"
            )
            self.socketio.emit("bedgame_started", self.bed_game.to_dict())
            self._broadcast_state()
            self._sync_to_mcp("bedgame_started", {"players": player_ids})
            return jsonify({"success": True, "game": self.bed_game.to_dict()})

        @self.app.route("/api/bedgame/action", methods=["POST"])
        def bedgame_action():
            if not self.bed_game.active:
                return jsonify({"error": "No active bed game"}), 400
            data = request.json or {}
            action_id = data.get("action")
            target_id = data.get("target")
            custom_action = data.get("custom", "")
            current_pid = self.bed_game.current_player_id
            current_name = self.bed_game.current_player_name
            requester = data.get("player_id", current_pid)
            if requester != current_pid and requester != "director":
                return jsonify({"error": f"It's {current_name}'s turn, not yours"}), 400
            is_escalation = False
            if custom_action:
                action_desc = custom_action
                stat_fx = {"arousal": 10, "pleasure": 10, "horniness": 8}
            elif action_id in BED_GAME_ACTIONS:
                act_data = BED_GAME_ACTIONS[action_id]
                action_desc = act_data["description"]
                stat_fx = dict(act_data["stat_effects"])
                is_escalation = act_data.get("escalation_bonus", False)
            else:
                return jsonify({"error": f"Unknown action: {action_id}"}), 400
            target_name = "everyone"
            if target_id:
                if target_id == "director":
                    target_name = self.director_name
                elif target_id in self.characters:
                    target_name = self.characters[target_id].name
            esc_info = self.bed_game.escalation_info
            bonus_mult = 1.0 + (esc_info["bonus"] / 100.0)
            if is_escalation:
                bonus_mult += 0.25
            boosted_fx = {k: int(v * bonus_mult) for k, v in stat_fx.items()}
            involved = [current_pid]
            if target_id and target_id != current_pid:
                involved.append(target_id)
            for pid in involved:
                if pid in self.profiles:
                    deltas = {k: v for k, v in boosted_fx.items()
                              if hasattr(self.profiles[pid].stats, k)}
                    self.profiles[pid].stats.adjust(**deltas)
                    try:
                        from engine.mcp.state_coordinator import get_coordinator
                        get_coordinator().update(pid, source="bedgame_action", scene="penthouse", **deltas)
                    except Exception:
                        pass
            explicit_level = BED_GAME_ACTIONS.get(action_id, {}).get("explicit_level", 2) if action_id else 2
            self.bed_game.record_escalation(current_pid, explicit_level)
            if explicit_level >= 5:
                mood_hint = "ecstasy"
            elif explicit_level >= 4:
                mood_hint = "moaning"
            elif explicit_level >= 3:
                mood_hint = "aroused"
            else:
                mood_hint = "flirty"
            record = {
                "round": self.bed_game.round_number,
                "player": current_name,
                "player_id": current_pid,
                "action": action_id or "custom",
                "description": action_desc,
                "target": target_name,
                "target_id": target_id,
                "explicit_level": explicit_level,
                "mood_hint": mood_hint,
                "escalation": self.bed_game.escalation_info,
            }
            self.bed_game.history.append(record)
            esc = self.bed_game.escalation_info
            esc_prompt = f"[ESCALATION LEVEL: {esc['level']}/5 — {esc['label']}] {esc['prompt_hint']}"
            if esc["streak"] >= 3:
                esc_prompt += f" 🔥 STREAK x{esc['streak']}! The intensity is OFF THE CHARTS."
            if esc["leader"]:
                leader_name = self.bed_game.player_names.get(esc["leader"], esc["leader"])
                esc_prompt += f" {leader_name} is winning the filth competition!"
            prev_actions = [h for h in self.bed_game.history[-3:] if h.get("player_id") != current_pid]
            if prev_actions:
                last = prev_actions[-1]
                esc_prompt += (
                    f" {last['player']} just did '{last['action']}' — "
                    f"can you outdo that? Go harder, dirtier, more explicit."
                )
            self._inject_to_loop(
                "(environment)",
                f"🎲 BED GAME — Round {self.bed_game.round_number}: {current_name} performs: {action_desc} "
                f"(target: {target_name}). {esc_prompt}\n"
                f"Describe this in vivid, explicit, graphic, PORNOGRAPHIC detail. "
                f"Include sounds, sensations, body reactions, fluids, skin. "
                f"Use real dirty words — fuck, cock, pussy, moan, wet, hard, cum. "
                f"Be vulgar, raw, and completely uninhibited.",
                "bedgame"
            )
            next_pid = self.bed_game.advance_turn()
            next_name = self.bed_game.current_player_name
            game_over = False
            if self.bed_game.max_rounds > 0 and self.bed_game.round_number > self.bed_game.max_rounds:
                game_over = True
                winner = esc.get("leader")
                winner_name = self.bed_game.player_names.get(winner, "everyone") if winner else "everyone"
                self._end_bed_game(
                    f"Max rounds reached. {winner_name} wins the filth competition! "
                    f"Everyone collapses in a satisfied, dripping, sweaty heap."
                )
            else:
                next_esc = self.bed_game.escalation_info
                self._inject_to_loop(
                    "(environment)",
                    f"Next turn: {next_name}. Escalation level: {next_esc['label']}. "
                    f"Can you outdo what just happened? Go further. Be filthier. "
                    f"The dirtier you go, the more points you score.",
                    "bedgame"
                )
            self.socketio.emit("bedgame_action", {**record, "next_player": next_name, "game_over": game_over})
            self._broadcast_state()
            return jsonify({"success": True, "record": record, "next_player": next_name,
                            "game_over": game_over, "game": self.bed_game.to_dict()})

        @self.app.route("/api/bedgame/end", methods=["POST"])
        def bedgame_end():
            if not self.bed_game.active:
                return jsonify({"error": "No active bed game"}), 400
            reason = (request.json or {}).get("reason", "The game ends.")
            self._end_bed_game(reason)
            return jsonify({"success": True})

        @self.app.route("/api/bedgame/state")
        def bedgame_state():
            return jsonify(self.bed_game.to_dict())

        @self.app.route("/api/bedgame/actions")
        def bedgame_actions():
            """List all available bed game actions for the current player count."""
            if not self.bed_game.active:
                return jsonify({"actions": list(BED_GAME_ACTIONS.keys())})
            return jsonify({"actions": self.bed_game.available_actions(),
                            "current_player": self.bed_game.current_player_name})
