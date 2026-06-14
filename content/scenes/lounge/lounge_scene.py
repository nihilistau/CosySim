"""
The Velvet Lounge — Scene
==========================
A 1920s underground jazz speakeasy.  Two resident characters — Lola Voss
(singer/owner) and Viktor Marlowe (bartender) — powered entirely by the
MCP framework.

Port: 5557

Everything in this scene is MCP-governed:
  • Drink orders → MCPFramework consequence chains → stat effects
  • Stage performance → MCPTimer → song duration → mood_contagion on finish
  • Heat meter → MCPTimer tick → threshold rules → consequence chains
  • Trust economy → gates secrets, back room, premium pours
  • Back room → MCPSceneNode permission rule
  • Cross-agent comms → Lola ↔ Viktor via MCPFramework.cross_scene_send
  • Random events → MCPFramework.random_pick each turn
  • Response control → ResponseDirective system steers every character reply

Version: v1.58.0 [2026-06-11]
Author:  CosySim Team

Change Log:
    v1.58.0 [2026-06-11] — Fixed 5 set_directive() calls passing scene_id=
                            (DialogSystem kwarg is scene=); these failed every
                            stage song, drink ritual and secret reveal
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import render_template, jsonify, request
from flask_socketio import emit

import sys
from engine.paths import ROOT as _root
sys.path.insert(0, str(_root))

from engine.scenes.flask_scene import FlaskScene
from content.scenes.lounge.lounge_mcp import (
    register_lounge_rules,
    SCENE_ID, LOLA_ID, VIKTOR_ID,
    COCKTAILS, SONGS, LOLA_SECRETS, VIKTOR_SECRETS,
    get_cocktail, get_all_cocktails, get_song_by_mood,
    get_available_secrets, pick_random_event,
)
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry

try:
    from engine.world.world_state import get_world_state
    from engine.events.event_bus import get_event_bus, EventBus
    _WORLD_AVAILABLE = True
except ImportError:
    _WORLD_AVAILABLE = False

logger = logging.getLogger(__name__)

# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)

# v1.49.1 [2026-03-22] — Use port registry instead of hardcoded value
try:
    from engine.port_registry import get_port
    LOUNGE_PORT = get_port("lounge", 5557)
except Exception:
    LOUNGE_PORT = 5557

# ──────────────────────────────────────────────────────────────────────────────
#  LOUNGE SCENE
# ──────────────────────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class LoungeScene(FlaskScene):
    """THE VELVET PIT — v0.68 'Dark Renaissance'.

    Underground lounge beneath the streets. Amber-lit. Heat never drops to zero.
    State is almost entirely owned by MCPFramework / SceneStateManager.
    This class provides the Flask/SocketIO scaffolding and thin Python
    state that cannot live in the framework (active_song timer, seating map, etc.).
    """

    SCENE_METADATA = {
        "name":         "lounge",
        "display_name": "THE VELVET PIT",
        "title":        "The Lounge",
        "port":         5557,
        "type":         "social",
        "accent_color": "#f59e0b",
        "accent_rgb":   "245 158 11",
        "description":  "Below the streets. Above the law. The heat never leaves.",
        "version":      "0.68",
        "codename":     "Dark Renaissance",
        "genre":        "social",
        "max_characters": 5,
        "features": [
            "heat_system", "trust_economy", "seating_map", "world_time",
            "smoke_particles", "mcp_framework", "multi_agent",
            "music_system", "conversation_heat",
        ],
    }

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = LOUNGE_PORT) -> None:
        super().__init__(host=host, port=port)

        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        self.register_shop_route(self.app)
        self.app.config["SECRET_KEY"] = "velvet_lounge_secret_1920s"
        self.register_bench_route(self.app, self.socketio)

        # Mount control overlay
        from engine.overlay import mount_overlay
        mount_overlay(self.app, self.socketio)

        # ── Lounge state (thin — framework owns the rest) ────────────────────
        self.turn_count        : int             = 0
        self.heat_level        : int             = 0      # 0-100; police danger
        self.guest_trust       : int             = 10     # 0-100; trust score
        self.secrets_revealed  : List[str]       = []
        self.in_back_room      : bool            = False
        self.current_song      : Optional[Dict]  = None
        self.song_start_time   : Optional[float] = None
        self.events_log        : List[Dict]      = []
        self.seating_map       : List[Dict]      = self._init_seating_map()
        self.world_time_slot   : str             = "EVENING"
        self.heat_timer_id     : Optional[str]   = None
        self._heat_lock        = threading.Lock()

        # ── Agents (lazy — loaded on first message) ──────────────────────────
        self._lola_agent   = None
        self._viktor_agent = None

        # ── Setup ────────────────────────────────────────────────────────────
        self._setup_routes()
        self._setup_socketio()
        register_lounge_rules()
        self._seed_lounge_registry()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()

        # ── Start heat timer ─────────────────────────────────────────────────
        self._start_heat_timer()

        # ── Start first song ─────────────────────────────────────────────────
        self._start_next_song()

        # ── EventBus subscription ────────────────────────────────────────────
        try:
            from engine.events.event_bus import get_event_bus
            get_event_bus().subscribe("world_sim.lounge_event", self._on_world_lounge_event)
        except Exception as exc:
            logger.debug("EventBus subscribe failed: %s", exc)

        # ── World State ──────────────────────────────────────────────────────
        self._world_state = None
        self._event_bus = None
        if _WORLD_AVAILABLE:
            self._world_state = get_world_state()
            self._event_bus = get_event_bus()
            self._event_bus.subscribe("world.tick", self._on_world_tick)
            self._event_bus.subscribe("world.time_change", self._on_time_change)

    # ══════════════════════════════════════════════════════════════════════════
    #  FRAMEWORK SHORTCUTS
    # ══════════════════════════════════════════════════════════════════════════

    @property
    def _fw(self):
        from engine.mcp.framework import get_framework
        return get_framework()

    @property
    def _ssm(self):
        from engine.mcp.scene_state import get_scene_state_manager
        return get_scene_state_manager()

    # ══════════════════════════════════════════════════════════════════════════
    #  REGISTRY SEEDING  — populate CharacterRegistry with Lola + Viktor
    # ══════════════════════════════════════════════════════════════════════════

    def _seed_lounge_registry(self) -> None:
        """
        Register Lola Voss and Viktor Marlowe in the CharacterRegistry so
        CharacterRegistryInterceptor, TTSStyleInterceptor, and MoodSyncInterceptor
        all have full profile + state data on their first call.

        Profiles are defined here so the lounge scene is self-contained.
        The DB is consulted first; these values are used as fallbacks.
        """
        try:
            from engine.mcp.character_registry import get_character_registry, apply_default_skills

            reg = get_character_registry()

            # ── Lola Voss — singer / speakeasy owner ─────────────────────
            lola_rec = reg.register(
                LOLA_ID,
                name        = "Lola Voss",
                age         = 29,
                appearance  = {
                    "hair":   "dark brunette, finger-waved",
                    "eyes":   "deep brown, lined in kohl",
                    "height": "5'6",
                    "style":  "1920s beaded gown, elbow gloves",
                },
                personality = {
                    "warmth":          0.7,
                    "assertiveness":   0.8,
                    "sensuality":      0.75,
                    "wit":             0.85,
                    "vulnerability":   0.5,
                    "openness":        0.65,
                    "playfulness":     0.6,
                    "empathy":         0.7,
                },
                backstory   = (
                    "Lola Voss fled Vienna in 1919 and built The Velvet Lounge from "
                    "nothing. She sings because it keeps her honest. She owns the room "
                    "every night because the alternative is losing it."
                ),
                voice_style = (
                    "warm, smoky contralto. Slow and deliberate. "
                    "Intimacy over projection. Faint Eastern European consonants."
                ),
                scene_roles = [SCENE_ID],
            )
            lola_rec.profile.voice_id = LOLA_ID   # maps to voices.yaml key "lola"
            reg.set_state(LOLA_ID, mood="calm", mood_intensity=0.6, energy=75.0)
            apply_default_skills(LOLA_ID)

            # ── Viktor Marlowe — bartender / silent guardian ─────────────
            viktor_rec = reg.register(
                VIKTOR_ID,
                name        = "Viktor Marlowe",
                age         = 38,
                appearance  = {
                    "hair":   "close-cropped, dark with grey at the temples",
                    "eyes":   "pale grey, give nothing away",
                    "height": "6'2",
                    "style":  "white shirt, black waistcoat, rolled sleeves",
                },
                personality = {
                    "assertiveness":   0.75,
                    "warmth":          0.4,
                    "empathy":         0.6,
                    "wit":             0.5,
                    "vulnerability":   0.2,
                    "openness":        0.3,
                    "dominance":       0.7,
                    "playfulness":     0.2,
                },
                backstory   = (
                    "Viktor Marlowe has a past he doesn't discuss. "
                    "He came to the lounge three years ago and never left. "
                    "He measures people the same way he measures spirits: carefully, quietly."
                ),
                voice_style = (
                    "deep measured baritone. Unhurried. Short sentences. "
                    "Eastern European accent, refined. Resonates from the chest."
                ),
                scene_roles = [SCENE_ID],
            )
            viktor_rec.profile.voice_id = VIKTOR_ID   # maps to voices.yaml key "viktor"
            reg.set_state(VIKTOR_ID, mood="neutral", mood_intensity=0.3, energy=85.0)
            apply_default_skills(VIKTOR_ID)

            logger.info("[%s] Registry seeded: Lola Voss + Viktor Marlowe (operation=seed)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] Registry seeding failed (operation=seed): %s", SCENE_ID, exc)

    @property
    def _reg(self):
        from engine.mcp.character_registry import get_character_registry
        return get_character_registry()

    @property
    def _ds(self):
        from engine.mcp.dialog_system import get_dialog_system
        return get_dialog_system()

    @property
    def _eng(self):
        from engine.mcp.scene_rules_engine import get_rules_engine
        return get_rules_engine()

    # ══════════════════════════════════════════════════════════════════════════
    #  HEAT MANAGEMENT  — MCPTimer tracks heat build; rules fire at thresholds
    # ══════════════════════════════════════════════════════════════════════════

    def _start_heat_timer(self) -> None:
        """Start a slow-ticking heat build timer."""
        try:
            timer_id = self._fw.start_timer(
                name             = "lounge_heat",
                duration_secs    = 180,   # heat builds every 3 minutes
                on_complete_note = "heat_tick",
                metadata         = {"scene": SCENE_ID},
            )
            self.heat_timer_id = timer_id

            # Schedule recurring heat increase as a consequence chain
            self._fw.schedule_consequence(
                scene_id             = SCENE_ID,
                character_id         = VIKTOR_ID,
                consequence_type     = "scene_event",
                params               = {"event_type": "heat_tick"},
                trigger_after_turns  = 6,   # every 6 turns
                description          = "Heat builds — someone's been watching the door too long.",
            )
        except Exception as exc:
            logger.warning("[%s] Heat timer start failed (operation=tick): %s", SCENE_ID, exc)

    def _tick_heat(self, delta: int = 5) -> None:
        """Increment heat and check threshold rules via the MCP rules engine."""
        with self._heat_lock:
            self.heat_level = min(100, self.heat_level + delta)

        heat = self.heat_level
        ssm  = self._ssm

        # Persist heat as explicit scene state, not character stats
        ssm.set_scene_state(SCENE_ID, heat_level=heat)

        # Sync heat to StateCoordinator for governance visibility
        try:
            from engine.mcp.state_coordinator import get_coordinator
            get_coordinator().update(
                VIKTOR_ID, mood="alert" if heat >= 65 else "watchful",
                source="lounge_heat", scene=SCENE_ID,
            )
        except Exception:
            pass

        if heat >= 85:
            self._apply_rule("heat_critical_rule")
        elif heat >= 65:
            self._apply_rule("heat_warning_rule")

        # Notify frontend
        self.socketio.emit("heat_update", {"heat": heat}, namespace="/")

        # Viktor notifies Lola via MCPFramework cross-scene message
        if heat >= 65:
            self._fw.cross_scene_send(
                from_char  = VIKTOR_ID,
                from_scene = SCENE_ID,
                to_char    = LOLA_ID,
                to_scene   = SCENE_ID,
                message    = f"[HEAT {heat}] Heat rising. Keep it calm on stage.",
                message_type = "internal_warning",
            )

    def _cool_heat(self, delta: int = 15) -> None:
        """Reduce heat (time passes, tension eases)."""
        with self._heat_lock:
            self.heat_level = max(0, self.heat_level - delta)
        self._ssm.set_scene_state(SCENE_ID, heat_level=self.heat_level)
        if self.heat_level < 40:
            self._apply_rule("heat_clear_rule")
        self.socketio.emit("heat_update", {"heat": self.heat_level}, namespace="/")

    # ══════════════════════════════════════════════════════════════════════════
    #  STAGE MANAGEMENT — MCPTimer + mood_contagion + rule gates
    # ══════════════════════════════════════════════════════════════════════════

    def _start_next_song(self, requested_id: Optional[str] = None) -> Dict:
        """Pick the next song Lola performs, start an MCPTimer, return song dict."""
        try:
            lola_state  = self._reg.get_state(LOLA_ID) or {}
            mood_score  = int(lola_state.get("mood_intensity", 0.5) * 100)

            if requested_id:
                song = next((s for s in SONGS if s["id"] == requested_id), None)
                if song and song["mood_req"] <= mood_score + 20:  # slight grace for requests
                    pass
                else:
                    song = None

            if not song if requested_id else True:
                song = get_song_by_mood(mood_score)

            self.current_song     = song
            self.song_start_time  = time.time()

            # Start MCPTimer for song duration
            self._fw.start_timer(
                name             = f"song_{song['id']}",
                duration_secs    = song["duration"],
                on_complete_note = f"song_complete:{song['id']}",
                metadata         = {"song_id": song["id"], "title": song["title"]},
            )

            # Set atmosphere from song definition
            if song.get("atmosphere"):
                self._ssm.set_atmosphere(SCENE_ID, **song["atmosphere"])

            # Set a style directive for Lola during this song
            self._ds.set_directive(
                character_id   = LOLA_ID,
                scene          = SCENE_ID,
                directive_type = "mood_set",
                value          = f"performing '{song['title']}' — {song.get('note', '')}",
                turns          = max(2, song["duration"] // 30),
                issued_by      = "lounge_stage",
            )

            # Narrative
            self._ssm.add_narrative(
                SCENE_ID, LOLA_ID,
                f"Lola begins '{song['title']}'. {song.get('note', '')}",
            )

            # Notify frontend
            self.socketio.emit("song_started", {
                "song": {
                    "id"      : song["id"],
                    "title"   : song["title"],
                    "duration": song["duration"],
                    "note"    : song.get("note", ""),
                }
            }, namespace="/")

            return song

        except Exception as exc:
            logger.warning("[%s] _start_next_song failed (operation=music): %s", SCENE_ID, exc)
            return {}

    def _finish_song(self, song_id: str) -> None:
        """Called when a song timer completes. Fire mood_contagion + start next."""
        try:
            song = next((s for s in SONGS if s["id"] == song_id), None)
            if not song:
                return

            # Mood contagion — Lola's performance mood spreads to the guest
            from engine.mcp.tools.scene import mood_contagion as mc_tool
            mc_tool(
                source_character_id = LOLA_ID,
                scene_id            = SCENE_ID,
                stat_json           = json.dumps(song["effects"]),
                spread_fraction     = 0.6,
            )

            # Trust boost if it was "come_undone"
            if song.get("trust_boost_for_all"):
                self.guest_trust = min(100, self.guest_trust + 5)
                self._check_trust_gates()

            # Narrative
            self._ssm.add_narrative(
                SCENE_ID, LOLA_ID,
                f"'{song['title']}' ends. A beat of silence before the applause.",
            )

            # Notify frontend
            self.socketio.emit("song_ended", {"song_id": song_id, "title": song["title"]}, namespace="/")

            # Check for heat cooldown after quiet songs
            if song["effects"].get("heat", 0) <= 0:
                self._cool_heat(5)

            # Start next song after a brief pause
            def _next():
                time.sleep(8)
                self._start_next_song()
            threading.Thread(target=_next, daemon=True).start()

        except Exception as exc:
            logger.warning("[%s] _finish_song failed (operation=music): %s", SCENE_ID, exc)

    # ══════════════════════════════════════════════════════════════════════════
    #  TRUST GATES
    # ══════════════════════════════════════════════════════════════════════════

    def _check_trust_gates(self) -> List[str]:
        """Check MCP rules that depend on trust level; fire any that unlock."""
        fired = []
        trust = self.guest_trust
        ssm   = self._ssm

        if trust >= 70 and not self._get_scene_flag("back_room_unlocked"):
            self._apply_rule("back_room_gate")
            fired.append("back_room_gate")
            self.socketio.emit("back_room_unlocked", {}, namespace="/")

        if trust >= 35 and not self._get_scene_flag("champagne_available"):
            self._apply_rule("champagne_gate")
            fired.append("champagne_gate")

        # Sync guest state through StateCoordinator after trust checks
        self._sync_guest_state()
        return fired

    def _sync_guest_state(self) -> None:
        """Push guest trust / heat / back-room state through the StateCoordinator."""
        try:
            from engine.mcp.state_coordinator import get_coordinator
            get_coordinator().update(
                "guest",
                mode="set",
                source="lounge_sync",
                scene=SCENE_ID,
                trust=self.guest_trust,
                heat=self.heat_level,
            )
        except Exception:
            pass

    def _get_scene_flag(self, flag: str) -> Any:
        try:
            state = self._ssm.get_scene_state(SCENE_ID) or {}
            return state.get(flag, False)
        except Exception:
            return False

    # ══════════════════════════════════════════════════════════════════════════
    #  RULE APPLICATION  (delegates to SceneRulesEngine)
    # ══════════════════════════════════════════════════════════════════════════

    def _apply_rule(self, rule_id: str, character_id: str = VIKTOR_ID) -> Dict:
        try:
            eng    = self._eng
            result = eng.apply_rule(SCENE_ID, rule_id, target_ids=[character_id], issuer="lounge_scene")
            if result.get("narrative"):
                self._log_event(result["narrative"], event_type="rule", rule_id=rule_id)
            return result
        except Exception as exc:
            logger.debug("_apply_rule %s failed: %s", rule_id, exc)
            return {}

    # ══════════════════════════════════════════════════════════════════════════
    #  DRINK SYSTEM  — serve drink → consequence chain → stat effects
    # ══════════════════════════════════════════════════════════════════════════

    def _serve_drink(
        self,
        drink_id : str,
        character: str = "guest",
    ) -> Dict[str, Any]:
        """Process a drink order through the MCP consequence chain."""
        cocktail = get_cocktail(drink_id)
        if not cocktail:
            return {"ok": False, "error": "Unknown drink."}

        trust_req = cocktail.get("trust_req", 0)
        if self.guest_trust < trust_req:
            return {
                "ok": False,
                "error": f"Viktor shakes his head once. That one's not for everyone.",
            }

        if cocktail.get("back_room_required") and not self.in_back_room:
            return {
                "ok": False,
                "error": "Viktor doesn't acknowledge you asked.",
            }

        # Schedule stat effects as a consequence chain (fires next turn)
        for stat, delta in cocktail["stat_effects"].items():
            if stat in ("trust", "arousal", "openness", "inhibition",
                        "happiness", "affection", "confidence"):
                self._fw.schedule_consequence(
                    scene_id            = SCENE_ID,
                    character_id        = "guest",
                    consequence_type    = "stat_adjust",
                    params              = {"stat": stat, "delta": delta},
                    trigger_after_turns = 1,
                    description         = f"Drink effect: {drink_id} — {stat} {'+' if delta > 0 else ''}{delta}",
                )

        # If this is champagne or special, fire Lola reaction
        if cocktail.get("lola_reaction"):
            self._fw.cross_scene_send(
                from_char    = VIKTOR_ID,
                from_scene   = SCENE_ID,
                to_char      = LOLA_ID,
                to_scene     = SCENE_ID,
                message      = f"Served '{cocktail['name']}' to the guest.",
                message_type = "drink_notification",
            )
            self._ds.set_directive(
                character_id   = LOLA_ID,
                scene          = SCENE_ID,
                directive_type = "must_include",
                value          = "catches the guest's eye briefly",
                turns          = 1,
                issued_by      = "drink_notification",
            )

        # Viktor joins guest for bourbon
        if cocktail.get("viktor_joins"):
            self._ds.set_directive(
                character_id   = VIKTOR_ID,
                scene          = SCENE_ID,
                directive_type = "must_include",
                value          = "pours a glass for himself and stays at that end of the bar",
                turns          = 1,
                issued_by      = "bourbon_ritual",
            )

        # Trust bump for drinking something meaningful
        if trust_req > 0:
            self.guest_trust = min(100, self.guest_trust + 2)
            self._check_trust_gates()

        # Narrative
        viktor_line = cocktail.get("viktor_line", f"Serves the {cocktail['name']}.")
        self._ssm.add_narrative(SCENE_ID, VIKTOR_ID, viktor_line)

        self._log_event(
            f"Guest orders {cocktail['name']}. {viktor_line}",
            event_type="drink_served",
            drink_id=drink_id,
        )

        return {
            "ok"       : True,
            "drink"    : cocktail["name"],
            "note"     : cocktail["note"],
            "viktor"   : viktor_line,
            "effects"  : cocktail["stat_effects"],
            "will_fire_next_turn": True,
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  SECRETS SYSTEM
    # ══════════════════════════════════════════════════════════════════════════

    def _get_secret(self, character: str = LOLA_ID) -> Optional[Dict]:
        """Reveal the next available secret for the given character."""
        available = [
            s for s in get_available_secrets(character, self.guest_trust)
            if s["id"] not in self.secrets_revealed
        ]
        if not available:
            return None

        secret = available[0]
        self.secrets_revealed.append(secret["id"])

        # Apply secret effects
        for stat, delta in secret.get("effect", {}).items():
            if stat == "trust":
                self.guest_trust = min(100, self.guest_trust + delta)
            else:
                self._fw.schedule_consequence(
                    scene_id            = SCENE_ID,
                    character_id        = "guest",
                    consequence_type    = "stat_adjust",
                    params              = {"stat": stat, "delta": delta},
                    trigger_after_turns = 1,
                    description         = f"Secret revealed: {secret['title']}",
                )

        # Trust gate re-check
        self._check_trust_gates()

        # Directive: character naturally reveals this
        char_id = LOLA_ID if character == LOLA_ID else VIKTOR_ID
        self._ds.set_directive(
            character_id   = char_id,
            scene          = SCENE_ID,
            directive_type = "must_include",
            value          = secret["content"][:100],
            turns          = 1,
            issued_by      = "secret_reveal",
        )

        self._ssm.add_narrative(
            SCENE_ID, char_id,
            f"Reveals secret: '{secret['title']}'.",
        )

        return secret

    # ══════════════════════════════════════════════════════════════════════════
    #  RANDOM EVENTS  — fires each turn via MCPFramework.random_pick
    # ══════════════════════════════════════════════════════════════════════════

    def _maybe_fire_event(self) -> Optional[Dict]:
        """Fire a random lounge event ~30% of the time."""
        try:
            result = self._fw.random_pick(
                n       = 1,
                options = ["event", "quiet", "quiet", "quiet"],
            )
            if result.get("picks", ["quiet"])[0] != "event":
                return None

            event = pick_random_event(self.heat_level)

            # Heat events increase heat
            if event.get("effects", {}).get("heat"):
                self._tick_heat(event["effects"]["heat"])

            # Viktor internal MCP message for meta-events
            if event.get("viktor_internal"):
                self._fw.cross_scene_send(
                    from_char  = VIKTOR_ID,
                    from_scene = SCENE_ID,
                    to_char    = LOLA_ID,
                    to_scene   = SCENE_ID,
                    message    = event["viktor_internal"],
                    message_type = "internal",
                )

            # Stat effects to guest
            for stat, delta in event.get("effects", {}).items():
                if stat in ("arousal", "openness", "trust", "happiness"):
                    if stat == "trust":
                        self.guest_trust = min(100, self.guest_trust + delta)
                    else:
                        self._fw.schedule_consequence(
                            scene_id            = SCENE_ID,
                            character_id        = "guest",
                            consequence_type    = "stat_adjust",
                            params              = {"stat": stat, "delta": delta},
                            trigger_after_turns = 1,
                            description         = f"Random event: {event['id']}",
                        )

            self._log_event(event["text"], event_type="random_event", event_id=event["id"])
            return event

        except Exception as exc:
            logger.debug("_maybe_fire_event failed: %s", exc)
            return None

    # ══════════════════════════════════════════════════════════════════════════
    #  AGENT REPLY  — governed through MCPFramework pipeline
    # ══════════════════════════════════════════════════════════════════════════

    def _get_agent_reply(
        self,
        character_id   : str,
        user_message   : str,
        history        : Optional[List] = None,
    ) -> Dict[str, Any]:
        """Get a governed reply from Lola or Viktor with rich metadata.

        Returns dict with: text, mood, image_requests, action_tags.
        """
        result = {
            "text": "",
            "mood": None,
            "image_requests": [],
            "action_tags": [],
            "degraded": False,
            "error": None,
        }
        try:
            from engine.mcp.comms_framework import get_governor, InteractionPolicy

            agent = self._get_or_create_agent(character_id)
            if agent is None:
                result["degraded"] = True
                result["error"] = "agent unavailable"
                result["text"] = self._fallback_reply(character_id, user_message)
                return result

            policy = InteractionPolicy(
                max_reply_tokens     = 350,
                min_reply_tokens     = 30,
                enforce_in_character = True,
                required_tone        = (
                    "low and precise, with weight" if character_id == LOLA_ID
                    else "sparse and deliberate"
                ),
            )

            # Reset processed metadata on agent before call
            if hasattr(agent, '_last_processed'):
                agent._last_processed = None

            gov = get_governor(agent, scene=SCENE_ID, policy=policy)
            text = gov.reply(user_message, history=history or [])
            result["text"] = text

            # Extract rich metadata if the agent used infer_processed()
            proc = getattr(agent, '_last_processed', None)
            if proc:
                result["mood"] = proc.mood_tags[0] if proc.mood_tags else None
                result["image_requests"] = list(proc.image_requests)
                result["action_tags"] = list(proc.action_tags)
                if result["mood"]:
                    self._update_character_mood(character_id, result["mood"])
            return result

        except Exception as exc:
            logger.warning("[%s] Agent reply failed (operation=chat, agent=%s): %s", SCENE_ID, character_id, exc)
            result["degraded"] = True
            result["error"] = str(exc)
            result["text"] = self._fallback_reply(character_id, user_message)
            return result

    def _update_character_mood(self, character_id: str, mood: str) -> None:
        """Push mood update to MCP framework and StateCoordinator."""
        try:
            char_node = self._fw.get_character(character_id)
            if char_node:
                char_node.update_state({"mood": mood, "last_mood_source": "lounge_reply"})
        except Exception:
            pass
        try:
            from engine.mcp.state_coordinator import get_coordinator
            get_coordinator().update(
                character_id, mood=mood, source="lounge_reply", scene=SCENE_ID,
            )
        except Exception:
            pass

    def _get_or_create_agent(self, character_id: str):
        """Return existing agent or create a minimal stub."""
        if character_id == LOLA_ID:
            if self._lola_agent is None:
                self._lola_agent = self._create_stub_agent(character_id)
            return self._lola_agent
        elif character_id == VIKTOR_ID:
            if self._viktor_agent is None:
                self._viktor_agent = self._create_stub_agent(character_id)
            return self._viktor_agent
        return None

    def _create_stub_agent(self, character_id: str):
        """Create a minimal CharacterAgent-compatible object for the lounge."""
        try:
            from content.simulation.database.db import Database
            from engine.agents.character_agent import CharacterAgent

            db   = Database()
            char = db.get_character(character_id)
            if char:
                return CharacterAgent(character=char, scene="lounge")

            # Create ephemeral agent if character not in DB
            profile = self._reg.get_profile(character_id)
            if not profile:
                return None

            class _LoungeStubbedAgent:
                """IAgent-compliant stub for lounge characters not in the DB."""
                def __init__(self_, cid, name, voice_style, backstory):
                    self_.character_id = cid
                    self_.character = type("_Char", (), {
                        "id"  : cid,
                        "name": name,
                        "_backstory": backstory,
                        "_voice_style": voice_style,
                    })()
                    self_.capabilities = set()
                    self_._last_processed = None

                def reply(self_, message, *, chain_id=None, history=None, **_kwargs):
                    """Use infer_processed() for rich streaming response."""
                    try:
                        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
                        from engine.agents.virtual_agent import InferenceRequest
                        from engine.mcp.comms_framework import build_governance_context
                        mgr = get_virtual_agent_manager()
                        system = (
                            f"You are {self_.character.name}. {self_.character._backstory}\n"
                            "You work at The Velvet Lounge, a 1920s speakeasy.\n"
                            "Stay in character. Express mood with [MOOD:emotion] tags.\n"
                            "If describing something visual, use [IMAGE:description].\n"
                            "Use [ACTION:description] for physical actions."
                        )
                        gov_ctx = build_governance_context(self_.character_id, SCENE_ID, message)
                        if gov_ctx:
                            system = f"{system}\n\n{gov_ctx}"
                        msgs = [{"role": "system", "content": system}]
                        for turn in (history or []):
                            msgs.append({"role": turn.get("role", "user"), "content": turn.get("content", "")})
                        msgs.append({"role": "user", "content": message})
                        req = InferenceRequest(
                            agent_id=self_.character_id,
                            messages=msgs,
                            temperature=0.85,
                            max_output_tokens=350,
                            conversation_id=f"lounge_{self_.character_id}",
                            store=True,
                            metadata={"scene": "lounge", "character_name": self_.character.name},
                        )
                        proc = mgr.infer_processed(req)
                        self_._last_processed = proc
                        return (proc.clean_text or "").strip()
                    except Exception:
                        return ""

                def quick_query(self_, prompt: str, *, max_tokens: int = 200) -> str:
                    return self_.reply(prompt)

                def cancel(self_) -> None:
                    pass

            return _LoungeStubbedAgent(
                character_id,
                profile.name,
                profile.voice_style or "",
                profile.backstory or "",
            )

        except Exception as exc:
            logger.debug("_create_stub_agent(%s) failed: %s", character_id, exc)
            return None

    def _fallback_reply(self, character_id: str, user_message: str) -> str:
        """Stylistic fallback when the full pipeline isn't available."""
        if character_id == LOLA_ID:
            fallbacks = [
                "She pauses mid-thought. Something in her expression shifts. 'That's an interesting thing to say.'",
                "She tilts her head. Her eyes don't leave yours. She doesn't answer immediately.",
                "The corner of her mouth moves. Not quite a smile. 'You're not what I expected.'",
                "'I'll think about that,' she says, and she means it.",
            ]
        else:
            fallbacks = [
                "Viktor sets a glass down without looking up. 'Mm.'",
                "He wipes the bar once. Precisely. Lets the silence stand.",
                "'Most people don't ask that,' he says. He doesn't add anything.",
                "He nods. Exactly once. It's enough.",
            ]
        import random
        return random.choice(fallbacks)

    # ══════════════════════════════════════════════════════════════════════════
    #  EVENT LOG
    # ══════════════════════════════════════════════════════════════════════════

    def _log_event(self, text: str, **meta) -> None:
        entry = {
            "id"        : str(uuid.uuid4())[:8],
            "timestamp" : datetime.now().isoformat(),
            "text"      : text,
            **meta,
        }
        self.events_log.append(entry)
        if len(self.events_log) > 100:
            self.events_log = self.events_log[-80:]
        self.socketio.emit("lounge_event", entry, namespace="/")

    def _init_seating_map(self) -> List[Dict]:
        """Initialise 8 tables with default occupancy."""
        tables = []
        for i in range(1, 9):
            tables.append({
                "id":       f"table_{i}",
                "label":    f"T{i}",
                "occupied": False,
                "npc":      None,
                "faction":  None,
            })
        return tables

    def _get_tables_state(self) -> List[Dict]:
        """Return current seating map state."""
        return self.seating_map

    def _get_world_time_slot(self) -> str:
        """Return world time label based on hour."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "MORNING"
        elif 12 <= hour < 17:
            return "LATE AFTERNOON"
        elif 17 <= hour < 21:
            return "EVENING"
        elif 21 <= hour < 24:
            return "MIDNIGHT RUSH"
        else:
            return "LAST CALL"

    def _get_events_tonight(self) -> List[Dict]:
        """Return tonight's events from ContentEngine or fallback list."""
        try:
            from engine.content.content_engine import get_content_engine
            eng = get_content_engine()
            return eng.get_events(scene="lounge", limit=5)
        except Exception:
            pass
        return [
            {"id": "jazz_set",    "title": "Jazz Quartet",  "desc": "Live jazz on the main stage."},
            {"id": "card_game",   "title": "Card Table",    "desc": "High-stakes poker in the back."},
            {"id": "poetry",      "title": "Poetry Night",  "desc": "Spoken word between sets."},
        ]

    def _on_world_lounge_event(self, event_data: dict) -> None:
        """Handle world_sim.lounge_event from EventBus; forward to clients."""
        try:
            self.socketio.emit("lounge_event", event_data, namespace="/")
        except Exception as exc:
            logger.debug("_on_world_lounge_event forward failed: %s", exc)

    def _on_world_tick(self, event: dict) -> None:
        """Push ambient time to UI on every world tick."""
        if hasattr(self, "socketio") and self.socketio and hasattr(self, "_world_state") and self._world_state:
            try:
                t = self._world_state.get_time()
                self.socketio.emit("ambient_update", {"hour": getattr(t, "hour", 0)})
            except Exception:
                pass

    def _on_time_change(self, event: dict) -> None:
        """React to time-of-day changes."""
        pass  # scenes override this for time-gated content

    # ══════════════════════════════════════════════════════════════════════════
    #  FRAMEWORK TICK  — called each turn; fires consequences + checks timers
    # ══════════════════════════════════════════════════════════════════════════

    def _tick_framework(self) -> None:
        """Tick MCPFramework: fire pending consequences + check song timers."""
        try:
            # Framework tick: fire scheduled consequences
            fired = self._fw.tick(SCENE_ID)
            for item in fired:
                ctype = item.get("consequence_type")
                if ctype == "scene_event":
                    event_type = item.get("params", {}).get("event_type", "")
                    if event_type == "heat_tick":
                        self._tick_heat(4)
                        # Re-schedule
                        self._fw.schedule_consequence(
                            scene_id            = SCENE_ID,
                            character_id        = VIKTOR_ID,
                            consequence_type    = "scene_event",
                            params              = {"event_type": "heat_tick"},
                            trigger_after_turns = 6,
                            description         = "Heat keeps building.",
                        )
                logger.debug("Lounge consequence fired: %s", item.get("consequence_id"))

            # Check song timer
            if self.current_song and self.song_start_time:
                elapsed = time.time() - self.song_start_time
                if elapsed >= self.current_song["duration"]:
                    self._finish_song(self.current_song["id"])
                    self.current_song    = None
                    self.song_start_time = None

            # Drain Lola's cross-scene inbox for Viktor messages
            lola_inbox = self._fw.get_cross_scene_inbox(LOLA_ID)
            if lola_inbox:
                for msg in lola_inbox:
                    if msg.get("type") == "internal_warning":
                        # Lola quietly adjusts her demeanour
                        self._ds.set_directive(
                            character_id   = LOLA_ID,
                            scene          = SCENE_ID,
                            directive_type = "mood_set",
                            value          = "guarded, watchful, not showing it",
                            turns          = 2,
                            issued_by      = "heat_viktor_warning",
                        )
                    elif msg.get("type") == "drink_notification":
                        pass  # Already handled in _serve_drink

        except Exception as exc:
            logger.debug("_tick_framework failed: %s", exc)

    # ══════════════════════════════════════════════════════════════════════════
    #  FLASK ROUTES
    # ══════════════════════════════════════════════════════════════════════════

    def _setup_routes(self) -> None:

        @self.app.route("/")
        def index():
            return render_template(
                "lounge.html",
                **self.inject_navbar_context(),
                world_time=self._get_world_time_slot(),
            )

        @self.app.route("/api/tables")
        def api_tables():
            return jsonify({"tables": self._get_tables_state()})

        @self.app.route("/api/events_tonight")
        def api_events_tonight():
            return jsonify({"events": self._get_events_tonight()})

        @self.app.route("/api/state")
        def api_state():
            return jsonify(self._get_state_snapshot())

        @self.app.route("/api/menu")
        def api_menu():
            cocktails = get_all_cocktails(self.guest_trust)
            return jsonify({"cocktails": cocktails, "trust": self.guest_trust})

        @self.app.route("/api/order", methods=["POST"])
        def api_order():
            data     = request.json or {}
            drink_id = data.get("drink_id", "")
            result   = self._serve_drink(drink_id)
            return jsonify(result)

        @self.app.route("/api/message", methods=["POST"])
        def api_message():
            data       = request.json or {}
            message    = data.get("message", "").strip()
            target     = data.get("target", LOLA_ID)   # "lola" or "viktor"
            history    = data.get("history", [])

            if not message:
                return jsonify({"error": "Empty message."}), 400

            self.turn_count += 1

            # Framework tick first
            self._tick_framework()

            # Maybe fire a random event
            rand_event = self._maybe_fire_event()

            # Trust increase per genuine interaction
            self.guest_trust = min(100, self.guest_trust + 1)
            self._check_trust_gates()

            # Build context injection for the agent
            ctx_note = self._build_context_note(rand_event)
            augmented = f"{message}\n\n[SCENE CONTEXT]{ctx_note}[/SCENE CONTEXT]" if ctx_note else message

            reply_data = self._get_agent_reply(target, augmented, history=history)
            reply = reply_data.get("text", "")

            self._log_event(
                f"Guest → {target}: \"{message[:60]}...\"",
                event_type="message_sent",
            )
            self._log_event(
                f"{target}: \"{reply[:80]}...\"",
                event_type="reply",
                mood=reply_data.get("mood"),
            )

            return jsonify({
                "reply"       : reply,
                "from"        : target,
                "mood"        : reply_data.get("mood"),
                "degraded"    : bool(reply_data.get("degraded")),
                "error"       : reply_data.get("error"),
                "trust"       : self.guest_trust,
                "heat"        : self.heat_level,
                "turn"        : self.turn_count,
                "random_event": rand_event,
                "song"        : self._current_song_info(),
            })

        @self.app.route("/api/request_song", methods=["POST"])
        def api_request_song():
            data       = request.json or {}
            song_id    = data.get("song_id", "")
            song       = self._start_next_song(requested_id=song_id)
            if not song:
                return jsonify({"ok": False, "error": "Lola shakes her head. Not yet."})
            return jsonify({"ok": True, "song": song["title"], "note": song.get("note","")})

        @self.app.route("/api/back_room", methods=["POST"])
        def api_back_room():
            if self.guest_trust < 70:
                return jsonify({
                    "ok": False,
                    "error": "Viktor doesn't move. There is no back room. Not for you.",
                })
            self.in_back_room = True
            self._sync_guest_state()
            result = self._apply_rule("back_room_gate")
            self._ssm.add_narrative(
                SCENE_ID, "guest",
                "The guest passes through the curtain into the back room.",
            )
            return jsonify({
                "ok"   : True,
                "note" : "Viktor tilts his head toward the curtain. You understand.",
                "rules": self._eng.get_rules_summary(SCENE_ID),
            })

        @self.app.route("/api/ask_secret", methods=["POST"])
        def api_ask_secret():
            data      = request.json or {}
            character = data.get("character", LOLA_ID)
            secret    = self._get_secret(character)
            if not secret:
                return jsonify({
                    "ok"   : False,
                    "error": (
                        "She says nothing for a moment. 'Not yet.' "
                        if character == LOLA_ID
                        else "Viktor just shakes his head. Not tonight."
                    ),
                })
            return jsonify({
                "ok"     : True,
                "secret" : secret["title"],
                "content": secret["content"],
                "effect" : secret.get("effect", {}),
            })

        @self.app.route("/api/songs")
        def api_songs():
            lola_state = self._reg.get_state(LOLA_ID) or {}
            mood_score = int(lola_state.get("mood_intensity", 0.5) * 100)
            available  = [s for s in SONGS if s["mood_req"] <= mood_score + 20]
            return jsonify({
                "songs": [
                    {"id": s["id"], "title": s["title"], "note": s.get("note","")}
                    for s in available
                ],
                "lola_mood": mood_score,
            })

        @self.app.route("/api/rules")
        def api_rules():
            rules   = self._eng.get_rules(SCENE_ID)
            summary = self._eng.get_rules_summary(SCENE_ID) if hasattr(self._eng, 'get_rules_summary') else ""
            return jsonify({
                "rules"  : [{"id": r.rule_id, "label": r.label, "desc": r.description} for r in rules],
                "summary": summary,
            })

        @self.app.route("/api/framework_status")
        def api_framework_status():
            try:
                fw_status = self._fw.get_status()
                return jsonify(fw_status)
            except Exception as exc:
                return jsonify({"error": str(exc)})

        @self.app.route("/api/economy")
        def api_economy():
            """Return current economy state for this scene."""
            try:
                from engine.economy.economy import get_economy_manager
                em = get_economy_manager()
                player_id = request.args.get("player_id", "player")
                return jsonify({
                    "scene": SCENE_ID,
                    "balance": em.get_balance(player_id),
                    "debt": em.check_debt(player_id),
                    "recent_transactions": [t.to_dict() for t in em.get_history(player_id, limit=10)],
                })
            except Exception as exc:
                logger.error("[%s] Economy API error (operation=economy): %s", SCENE_ID, exc)
                return jsonify({"error": str(exc)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    #  SOCKETIO
    # ══════════════════════════════════════════════════════════════════════════

    def _setup_socketio(self) -> None:

        @self.socketio.on("connect")
        def on_connect():
            emit("welcome", {
                "message": (
                    "The iron stairs lead down. The Velvet Pit exhales heat and amber light. "
                    "Something is playing. Something always is. Viktor doesn't look up. "
                    "He doesn't need to."
                ),
                "state": self._get_state_snapshot(),
            })

        @self.socketio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_state_snapshot())

        @self.socketio.on("heat_action")
        def on_heat_action(data):
            action = data.get("action", "")
            if action == "cool":
                self._cool_heat(20)
            elif action == "heat":
                self._tick_heat(10)

        @self.socketio.on("get_lounge_state")
        def on_get_lounge_state():
            emit("lounge_state", {
                **self._get_state_snapshot(),
                "heat_level": self.heat_level,
                "seating":    self._get_tables_state(),
                "current_event": (self._get_events_tonight() or [{}])[0],
                "staff": [
                    {"id": LOLA_ID,   "name": "Lola Voss",    "role": "Singer · Owner"},
                    {"id": VIKTOR_ID, "name": "Viktor Marlowe","role": "Bartender"},
                ],
                "world_time": self._get_world_time_slot(),
            })

        @self.socketio.on("approach_table")
        def on_approach_table(data):
            table_id = data.get("table_id", "") if isinstance(data, dict) else ""
            table = next((t for t in self.seating_map if t["id"] == table_id), None)
            if not table:
                emit("table_response", {"ok": False, "error": "No such table."})
                return
            table["occupied"] = True
            npc_name = table.get("npc") or "a patron"
            emit("table_response", {
                "ok":      True,
                "table":   table,
                "message": f"You approach {table_id}. {npc_name} looks up.",
            })
            self.socketio.emit("seating_update", {"tables": self.seating_map}, namespace="/")

        @self.socketio.on("order_drink")
        def on_order_drink(data):
            drink = data.get("drink", "gin_fizz") if isinstance(data, dict) else "gin_fizz"
            result = self._serve_drink(drink)
            # Economy transaction (best-effort)
            if result.get("ok"):
                try:
                    from engine.economy.economy import get_economy_manager, TransactionType
                    price = COCKTAILS.get(drink, {}).get("price", 0)
                    if price > 0:
                        get_economy_manager().transact(
                            amount=-price,
                            txn_type=TransactionType.SPEND,
                            scene=SCENE_ID,
                            description=f"Drink: {drink}",
                        )
                except Exception:
                    pass
            emit("drink_response", result)

        @self.socketio.on("get_events_tonight")
        def on_get_events_tonight():
            emit("events_tonight", {"events": self._get_events_tonight()})

    # ══════════════════════════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_context_note(self, rand_event: Optional[Dict]) -> str:
        lines = []
        if self.current_song:
            elapsed = int(time.time() - (self.song_start_time or time.time()))
            remaining = max(0, self.current_song["duration"] - elapsed)
            lines.append(
                f"Lola is performing '{self.current_song['title']}' "
                f"({remaining}s remaining)."
            )
        atm = self._ssm.get_atmosphere(SCENE_ID)
        if atm:
            parts = [f"{k}={v}" for k, v in atm.items() if v]
            lines.append(f"Atmosphere: {', '.join(parts)}")
        lines.append(f"Guest trust level: {self.guest_trust}/100")
        lines.append(f"Heat level: {self.heat_level}/100")
        if self.in_back_room:
            lines.append("Guest is in the back room.")
        if rand_event:
            lines.append(f"SCENE EVENT: {rand_event['text']}")
        narrative = self._ssm.get_narrative_entries(SCENE_ID, limit=3)
        if narrative:
            lines.append("Recent events: " + " | ".join(e["event"] for e in narrative))
        return "\n".join(lines)

    def _current_song_info(self) -> Optional[Dict]:
        if not self.current_song:
            return None
        elapsed   = int(time.time() - (self.song_start_time or time.time()))
        remaining = max(0, self.current_song["duration"] - elapsed)
        return {
            "id"       : self.current_song["id"],
            "title"    : self.current_song["title"],
            "elapsed"  : elapsed,
            "remaining": remaining,
            "progress" : min(1.0, elapsed / max(1, self.current_song["duration"])),
        }

    def _get_state_snapshot(self) -> Dict:
        atm      = self._ssm.get_atmosphere(SCENE_ID) or {}
        lola_st  = self._reg.get_state(LOLA_ID) or {}
        viktor_st= self._reg.get_state(VIKTOR_ID) or {}
        narrative= self._ssm.get_narrative_entries(SCENE_ID, limit=5)
        rules    = self._eng.get_rules(SCENE_ID)

        return {
            "trust"          : self.guest_trust,
            "heat"           : self.heat_level,
            "turn"           : self.turn_count,
            "in_back_room"   : self.in_back_room,
            "back_room_avail": self.guest_trust >= 70,
            "current_song"   : self._current_song_info(),
            "atmosphere"     : atm,
            "lola_mood"      : lola_st.get("mood", "performing"),
            "viktor_mood"    : viktor_st.get("mood", "watchful"),
            "secrets_revealed": len(self.secrets_revealed),
            "narrative"      : [e["event"] for e in narrative],
            "active_rules"   : [{"id": r.rule_id, "label": r.label} for r in rules[:4]],
            "fw_turn"        : self._fw.turn if hasattr(self._fw, "turn") else 0,
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  BaseScene abstract methods
    # ══════════════════════════════════════════════════════════════════════════

    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_shutdown(self) -> None:
        """Hook: unsubscribe world events and save framework state."""
        if hasattr(self, "_event_bus") and self._event_bus:
            try:
                self._event_bus.unsubscribe("world.tick", self._on_world_tick)
                self._event_bus.unsubscribe("world.time_change", self._on_time_change)
            except Exception:
                pass
        try:
            self._fw.save_state()
        except Exception:
            pass
        try:
            self.socketio.stop()
        except Exception:
            pass

    def get_plugin_info(self) -> dict:
        """Return metadata consumed by the admin panel and launcher."""
        return {
            "name":        "The Velvet Lounge",
            "description": "Below the streets. Above the law. The heat never leaves.",
            "version":     "0.68",
            "codename":    "Dark Renaissance",
            "author":      "CosySim",
            "port":        LOUNGE_PORT,
            "tags":        ["lounge", "velvet_pit", "mcp", "multi-agent", "dark_renaissance"],
            "skill_packs": ["lounge", "memory", "character", "voice"],
            "routes": [
                {"path": "/",                    "methods": ["GET"],  "description": "Main lounge UI"},
                {"path": "/api/state",           "methods": ["GET"],  "description": "Scene state"},
                {"path": "/api/tables",          "methods": ["GET"],  "description": "Seating map"},
                {"path": "/api/events_tonight",  "methods": ["GET"],  "description": "Tonight's events"},
                {"path": "/api/message",         "methods": ["POST"], "description": "Send message to character"},
                {"path": "/api/order",           "methods": ["POST"], "description": "Order a drink"},
                {"path": "/api/health",          "methods": ["GET"],  "description": "Health check"},
                {"path": "/api/bench/metrics",   "methods": ["GET"],  "description": "Benchmark HUD metrics"},
                {"path": "/api/tts/speak",       "methods": ["POST"], "description": "TTS synthesis"},
            ],
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  BaseScene START
    # ══════════════════════════════════════════════════════════════════════════

    def on_before_serve(self) -> None:
        """Hook: wire framework event bus for cross-scene events."""
        try:
            self._fw.on("environment_change", lambda evt: self._on_env_event(evt))
            self._fw.on("story_beat", lambda evt: self._on_story_beat(evt))
        except Exception:
            pass

    def _on_env_event(self, evt) -> None:
        """React to environment changes from the event bus."""
        if evt.payload.get("scene_id") == SCENE_ID:
            try:
                self.socketio.emit("environment_update", evt.payload)
            except Exception:
                pass

    def _on_story_beat(self, evt) -> None:
        """React to story beats from the event bus."""
        if evt.payload.get("scene_id") == SCENE_ID:
            try:
                self.events_log.append({"type": "story_beat", "data": evt.payload})
                self.socketio.emit("story_beat", evt.payload)
            except Exception:
                pass


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    scene = LoungeScene()
    scene.start()
