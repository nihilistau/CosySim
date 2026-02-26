"""Bedroom scene inventory, props, and outfit mixin."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Dict, List, Any, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class BedroomInventoryMixin:
    """Prop management, outfit/position changes, and personality assignment."""

    # ── Prop stat effects ───────────────────────────────────────────────

    def _apply_prop_stat_effect(self, prop_id: str) -> None:
        from content.scenes.bedroom.bedroom_scene import PROPS

        if prop_id not in PROPS:
            return
        effect_str = PROPS[prop_id]["effect"]
        for m in re.finditer(r'([+-])(\d+)\s+(\w+)', effect_str):
            sign = 1 if m.group(1) == '+' else -1
            val = int(m.group(2)) * sign
            stat = m.group(3).lower()
            for cid, profile in self.profiles.items():
                prop_delta = {stat: val * 0.5}
                profile.stats.adjust(**prop_delta)
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    get_coordinator().update(cid, source="prop_effect", scene="bedroom", **prop_delta)
                except Exception:
                    pass

    # ── Props routes ────────────────────────────────────────────────────

    def _setup_props_routes(self) -> None:
        """Register prop-management Flask routes on self.app."""
        from flask import jsonify, request
        from content.scenes.bedroom.bedroom_scene import PROPS

        @self.app.route("/api/props/list")
        def list_props():
            return jsonify({"available": PROPS, "room": self.room_props})

        @self.app.route("/api/props/add", methods=["POST"])
        def add_prop():
            pid = (request.json or {}).get("prop_id")
            if pid not in PROPS:
                return jsonify({"error": "Unknown prop"}), 400
            if pid not in self.room_props:
                self.room_props.append(pid)
            self._apply_prop_stat_effect(pid)
            self._inject_to_loop("(environment)", f"A {PROPS[pid]['label']} has appeared in the room.", "environment")
            self._broadcast_state()
            return jsonify({"success": True, "room_props": self.room_props})

        @self.app.route("/api/props/remove", methods=["POST"])
        def remove_prop():
            pid = (request.json or {}).get("prop_id")
            if pid in self.room_props:
                self.room_props.remove(pid)
            self._broadcast_state()
            return jsonify({"success": True, "room_props": self.room_props})

        @self.app.route("/api/props/give", methods=["POST"])
        def give_prop_to_character():
            data = request.json or {}
            cid = data.get("character_id")
            pid = data.get("prop_id")
            if cid not in self.profiles or pid not in PROPS:
                return jsonify({"error": "Invalid"}), 400
            if pid not in self.profiles[cid].props_held:
                self.profiles[cid].props_held.append(pid)
            self._inject_to_loop("(environment)", f"{self.characters[cid].name} picks up the {PROPS[pid]['label']}.", "environment")
            self._broadcast_state()
            return jsonify({"success": True})

    # ── Outfit / Position / Personality routes ──────────────────────────

    def _setup_outfit_routes(self) -> None:
        """Register outfit, position, and personality Flask routes on self.app."""
        from flask import jsonify, request
        from content.scenes.bedroom.bedroom_scene import (
            OUTFITS, POSITIONS, PERSONALITY_PROFILES,
        )

        @self.app.route("/api/character/outfit", methods=["POST"])
        def set_outfit():
            data = request.json or {}
            cid = data.get("character_id")
            outfit = data.get("outfit", OUTFITS[0])
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            self.profiles[cid].outfit = outfit
            if outfit in ("nothing", "lingerie"):
                self.profiles[cid].stats.adjust(arousal=10, explicitness=5)
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    get_coordinator().update(cid, source="outfit_change", scene="bedroom", arousal=10, explicitness=5)
                except Exception:
                    pass
            self._inject_to_loop("(environment)", f"{self.characters[cid].name} is now wearing: {outfit}.", "environment")
            self._broadcast_state()
            self._sync_to_mcp("outfit_changed", {"character_id": cid, "outfit": outfit})
            return jsonify({"success": True})

        @self.app.route("/api/character/position", methods=["POST"])
        def set_position():
            data = request.json or {}
            cid = data.get("character_id")
            position = data.get("position", POSITIONS[0])
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            self.profiles[cid].position = position
            self._inject_to_loop("(environment)", f"{self.characters[cid].name} is now {position}.", "environment")
            self._broadcast_state()
            self._sync_to_mcp("position_changed", {"character_id": cid, "position": position})
            return jsonify({"success": True})

        @self.app.route("/api/character/personality", methods=["POST"])
        def set_personality():
            data = request.json or {}
            cid = data.get("character_id")
            pk = data.get("personality_key")
            if cid not in self.profiles or pk not in PERSONALITY_PROFILES:
                return jsonify({"error": "Invalid character or personality"}), 400
            p_info = PERSONALITY_PROFILES[pk]
            self.profiles[cid].personality_key = pk
            self.profiles[cid].traits = list(p_info["traits"])
            self.profiles[cid].likes = list(p_info["likes"])
            self.profiles[cid].dislikes = list(p_info["dislikes"])
            self._broadcast_state()
            return jsonify({"success": True})
