"""
Heist Scene — Cooperative multi-agent planning & execution showcase.
===================================================================

Port 5565. Flask + SocketIO.

Demonstrates:
- Multi-agent coordination (8 crew members with specialties & backstories)
- Crew affinity system (synergy bonuses, argument risks, betrayal mechanics)
- VirtualPipeline integration (watcher, kill switch, pre-warming)
- Phase-gated MCP rules (planning -> approach -> execution -> escape)
- Real-time game state with skill checks and complications
- Pipeline-aware streaming (moods, images, actions extracted automatically)
- SharedBoard integration (heist leaderboard)

The player acts as the Mastermind, directing the crew. Each crew member
is an AI agent with a personality and specialty. They discuss, argue,
and execute actions based on the heist state and their character.

Version: v1.49.5 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.5 [2026-03-22] — Named crew roster (8 members), affinity system, betrayal mechanics
    v1.51.0 [2026-03-22] — Migrated to FlaskScene base class
    v1.49.3 [2026-03-22] — Structured logging context
    v1.49.1 [2026-03-22] — Use port registry instead of hardcoded value
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import render_template, jsonify, request as flask_request
from flask_socketio import emit, join_room, leave_room

from engine.scenes.flask_scene import FlaskScene
from content.scenes.heist.heist_game import (
    HeistState, Phase, Specialty, VENUES, CrewMember,
)
from content.scenes.heist.heist_rules import register_heist_rules
from content.simulation.database.db import Database
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry, TagDef

try:
    from engine.world.world_state import get_world_state
    from engine.events.event_bus import get_event_bus, EventBus
    _WORLD_AVAILABLE = True
except ImportError:
    _WORLD_AVAILABLE = False

logger = logging.getLogger(__name__)

SCENE_ID = "heist"
# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)
# v1.49.1 [2026-03-22] — Use port registry instead of hardcoded value
try:
    from engine.port_registry import get_port as _get_port
    DEFAULT_PORT = _get_port("heist", 5565)
except Exception:
    DEFAULT_PORT = 5565

# v1.49.5 [2026-03-22] — Named crew with backstories, personalities, and affinities
# CONNECTS: HeistState.add_crew, _init_agent, _build_crew_prompt
# Each crew member has affinity scores toward other members (-100 to +100).
# Positive affinity = synergy bonus; negative = argument risk + potential betrayal.
CREW_ROSTER = {
    "ghost": {
        "name": "Ghost",
        "specialty": "hacker",
        "personality": "ethical, anxious, methodical",
        "backstory": (
            "Ex-OmniCorp security architect. Left after they weaponized her "
            "firewall code. Haunted by what her tools enabled."
        ),
        "system_prompt": (
            "You are Ghost, a brilliant but anxious hacker. You prefer clean, "
            "non-violent solutions. You get nervous when plans change. You "
            "dislike Silk because you suspect she's a double agent."
        ),
        "likes": ["clean_jobs", "detailed_plans"],
        "dislikes": ["violence", "improvisation"],
        "affinity": {"silk": -20, "tank": 10, "doc": 15, "vex": -10, "whisper": 20},
    },
    "tank": {
        "name": "Tank",
        "specialty": "muscle",
        "personality": "loyal, PTSD, protective",
        "backstory": (
            "Former SynthSec enforcer. Still hears the screams from the "
            "Blackout Raid. Quit after refusing an order to gas a residential block."
        ),
        "system_prompt": (
            "You are Tank, a massive ex-enforcer with a gentle soul trapped "
            "in a violent body. You protect the team. You have PTSD flashbacks "
            "when things go loud. You trust Ghost."
        ),
        "likes": ["protecting_team", "quiet_exits"],
        "dislikes": ["loud_entries", "civilian_risk"],
        "affinity": {"ghost": 10, "nails": -15, "doc": 20, "silk": 5},
    },
    "silk": {
        "name": "Silk",
        "specialty": "talker",
        "personality": "charming, manipulative, secrets",
        "backstory": (
            "Nobody knows Silk's real name. She talks her way into anything — "
            "and out of everything. Rumor says she still has OmniCorp contacts."
        ),
        "system_prompt": (
            "You are Silk, a master social engineer. You enjoy manipulation as "
            "an art form. You keep secrets from the team. You find Ghost's "
            "paranoia about you amusing — and slightly accurate."
        ),
        "likes": ["deception", "social_engineering"],
        "dislikes": ["direct_confrontation", "cameras"],
        "affinity": {"ghost": -20, "whisper": 10, "vex": 15, "jet": 5},
    },
    "doc": {
        "name": "Doc",
        "specialty": "driver",
        "personality": "calm, cynical, ex-medic",
        "backstory": (
            "Lost her medical license after stealing pharmaceuticals to treat "
            "people who couldn't afford them. Now she drives getaway and "
            "patches bullet holes."
        ),
        "system_prompt": (
            "You are Doc, a former surgeon turned getaway driver. You're calm "
            "under pressure because you've seen worse in the ER. You care about "
            "the team's safety more than the score."
        ),
        "likes": ["clean_exits", "no_casualties"],
        "dislikes": ["unnecessary_risks", "greed"],
        "affinity": {"tank": 20, "ghost": 15, "nails": -10, "jet": 10},
    },
    "vex": {
        "name": "Vex",
        "specialty": "hacker",
        "personality": "chaotic, genius, unpredictable",
        "backstory": (
            "Teenage prodigy who got bored hacking governments. Does heists "
            "for the thrill, not the money. Laughs at danger. Scares Ghost."
        ),
        "system_prompt": (
            "You are Vex, a chaotic hacker genius. You improvise constantly "
            "and love when plans go sideways because that's when you shine. "
            "You think Ghost is boring and play pranks on her."
        ),
        "likes": ["improvisation", "chaos"],
        "dislikes": ["boring_plans", "waiting"],
        "affinity": {"ghost": -10, "silk": 15, "nails": 20, "whisper": -5},
    },
    "nails": {
        "name": "Nails",
        "specialty": "muscle",
        "personality": "aggressive, short-tempered, effective",
        "backstory": (
            "Underground pit fighter from the Arena. Only knows one speed: "
            "forward. Loyal to whoever pays, but surprisingly sentimental "
            "about a locket she never takes off."
        ),
        "system_prompt": (
            "You are Nails, a pit fighter who solves problems with force. "
            "You're impatient with planning. You have a secret soft side but "
            "hide it behind aggression. You and Tank clash over methods."
        ),
        "likes": ["action", "direct_approach"],
        "dislikes": ["stealth", "long_plans"],
        "affinity": {"tank": -15, "vex": 20, "silk": -5, "doc": -10},
    },
    "whisper": {
        "name": "Whisper",
        "specialty": "talker",
        "personality": "empathetic, perceptive, haunted",
        "backstory": (
            "Former psychologist who specialized in corporate interrogation. "
            "Now uses those skills to read marks and diffuse hostile situations. "
            "Feels guilty about her past."
        ),
        "system_prompt": (
            "You are Whisper, a former interrogation psychologist. You read "
            "people like open books. You use empathy as a weapon. You're "
            "haunted by the people you broke in your old career."
        ),
        "likes": ["reading_people", "nonviolent_solutions"],
        "dislikes": ["torture", "deception"],
        "affinity": {"ghost": 20, "silk": 10, "vex": -5, "tank": 15},
    },
    "jet": {
        "name": "Jet",
        "specialty": "driver",
        "personality": "adrenaline_junkie, loyal, superstitious",
        "backstory": (
            "Former racing pilot banned from every track in NeonCity. Drives "
            "like the laws of physics are suggestions. Has a lucky dice she "
            "won't do a job without."
        ),
        "system_prompt": (
            "You are Jet, an adrenaline-junkie getaway driver. You're fearless "
            "behind the wheel but superstitious — you won't start a heist "
            "without your lucky dice roll. You're fiercely loyal to the team."
        ),
        "likes": ["speed", "impossible_escapes"],
        "dislikes": ["walking", "bad_luck"],
        "affinity": {"doc": 10, "silk": 5, "vex": 15, "nails": 10},
    },
}

# Backward compatibility — old code referenced CREW_TEMPLATES
CREW_TEMPLATES = CREW_ROSTER


# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class HeistScene(FlaskScene):
    """Cooperative heist planning & execution scene."""

    SCENE_METADATA = {
        "name": "heist",
        "display_name": "THE SCORE",
        "port": 5565,
        "type": "thriller",
        "accent_color": "#e11d48",
        "accent_rgb": "225 29 72",
        "description": "Everyone gets a cut. Nobody gets out clean. The clock is ticking.",
        "genre": "crime_coop",
        "max_characters": 4,
        "features": [
            "heist_planning", "crew_roles", "phase_system",
            "multi_agent_cooperation", "branched_conversations",
            "investigation_board", "consequence_system", "economy",
        ],
    }

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        db: Optional[Database] = None,
    ):
        super().__init__(host=host, port=port)

        self.db = db or Database()
        self.game: Optional[HeistState] = None
        self._agents: Dict[str, Any] = {}
        self._crew_config = dict(CREW_TEMPLATES)
        self._ticker_thread: Optional[threading.Thread] = None
        self._ticker_stop = threading.Event()

        # Heist state — v0.68
        self._active_job_id: Optional[str] = None
        self._assigned_roles: Dict[str, str] = {}

        # Engine subsystem refs (wired in on_before_serve)
        self._content_engine = None
        self._economy = None
        self._reputation = None
        self._investigation = None
        self._consequences = None
        self._director = None
        self._event_bus = None

        register_heist_rules()
        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._register_socketio()
        self._register_squad_socketio()  # v1.52.0 — co-op squad rooms

        # v1.52.0 [2026-03-26] — Co-op squad system
        self._squad_manager = None  # Lazy-load on first squad operation

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()
        self._tag_registry.register(TagDef(
            name="PLAN", pattern=r"\[PLAN:([^\]]+)\]",
            handler=None, strip_from_output=True, pre_warm_intent="heist_plan"
        ))

    # ── Routes───────────────────────────────────────────────────────────

    def _register_routes(self):
        app = self.app

        @app.route("/")
        def index():
            return render_template("heist.html", **self.inject_navbar_context())

        @app.route("/api/venues")
        def list_venues():
            return jsonify(VENUES)

        @app.route("/api/game", methods=["GET"])
        def get_game():
            if not self.game:
                return jsonify({"active": False})
            return jsonify({"active": True, **self.game.to_dict()})

        @app.route("/api/game/new", methods=["POST"])
        def new_game():
            data = flask_request.get_json(silent=True) or {}
            venue = data.get("venue", "diamond_exchange")
            self.game = HeistState.new_heist(venue_key=venue)

            # Add crew from templates
            crew_ids = data.get("crew", list(self._crew_config.keys()))
            for cid in crew_ids:
                tmpl = self._crew_config.get(cid)
                if tmpl:
                    self.game.add_crew(cid, tmpl["name"], tmpl["specialty"])
                    self._init_agent(cid, tmpl)

            # v1.49.5 — Evaluate crew affinities on assembly
            self._check_crew_affinity(crew_ids)

            self._broadcast_state()
            self._sync_to_mcp("heist_started", {"venue": venue, "crew": crew_ids})
            return jsonify({"success": True, "game": self.game.to_dict()})

        @app.route("/api/game/action", methods=["POST"])
        def game_action():
            if not self.game:
                return jsonify({"error": "No active game"}), 400
            data = flask_request.get_json(silent=True) or {}
            char_id = data.get("character_id", "")
            action = data.get("action", "")
            if not char_id or not action:
                return jsonify({"error": "character_id and action required"}), 400

            result = self.game.perform_action(char_id, action)

            # Check for complications
            comp = self.game.maybe_complication()
            if comp:
                result["complication"] = comp

            # Check bust/victory
            if self.game.check_bust():
                result["bust"] = True
            elif self.game.check_victory():
                result["victory"] = True

            self._broadcast_state()
            self._broadcast_event(result)
            return jsonify(result)

        @app.route("/api/game/advance", methods=["POST"])
        def advance_phase():
            if not self.game:
                return jsonify({"error": "No active game"}), 400
            new_phase = self.game.advance_phase()
            self._broadcast_state()
            # Submit to leaderboard on heist completion
            if new_phase == Phase.COMPLETE and self.game.loot_collected > 0:
                try:
                    from engine.mcp.shared_boards import get_shared_boards
                    get_shared_boards().submit_score(
                        "heist_legends", "Mastermind",
                        self.game.loot_collected,
                        metadata={
                            "venue": self.game.venue.get("name", "unknown"),
                            "suspicion": self.game.suspicion,
                        },
                    )
                except Exception:
                    pass
            return jsonify({"phase": new_phase.value})

        @app.route("/api/game/loot", methods=["POST"])
        def collect_loot():
            if not self.game:
                return jsonify({"error": "No active game"}), 400
            data = flask_request.get_json(silent=True) or {}
            amount = data.get("amount", 50000)
            total = self.game.collect_loot(amount)
            self._broadcast_state()
            return jsonify({"total": total, "target": self.game.loot_target})

        @app.route("/api/chat", methods=["POST"])
        def chat():
            """Send a message to a crew member (as Mastermind)."""
            if not self.game:
                return jsonify({"error": "No active game"}), 400
            data = flask_request.get_json(silent=True) or {}
            char_id = data.get("character_id")
            message = data.get("message", "").strip()
            if not char_id or not message:
                return jsonify({"error": "character_id and message required"}), 400

            # Generate reply in background thread
            threading.Thread(
                target=self._reply_worker,
                args=(char_id, message),
                daemon=True,
            ).start()
            return jsonify({"success": True, "queued": True})

        @app.route("/api/crew/tick", methods=["POST"])
        def crew_tick():
            """Have all crew members discuss/act for one turn."""
            if not self.game:
                return jsonify({"error": "No active game"}), 400
            results = self._crew_tick()
            return jsonify({"results": results})

    # ── SocketIO ─────────────────────────────────────────────────────────

    def _register_socketio(self):
        @self.socketio.on("connect")
        def on_connect():
            if self.game:
                emit("game_state", self.game.to_dict())

        @self.socketio.on("chat_message")
        def on_chat(data):
            char_id = data.get("character_id")
            message = data.get("message", "").strip()
            if char_id and message and self.game:
                threading.Thread(
                    target=self._reply_worker,
                    args=(char_id, message),
                    daemon=True,
                ).start()

        # ── v0.68 handlers ───────────────────────────────────────────────

        @self.socketio.on("get_heist_state")
        def on_get_heist_state():
            state: Dict[str, Any] = {
                "active": self.game is not None,
                "phase": self.game.phase.value if self.game else "planning",
                "heat": self.game.suspicion if self.game else 0,
                "job_id": self._active_job_id,
                "assigned_roles": self._assigned_roles,
            }
            if self.game:
                state.update(self.game.to_dict())
            emit("heist_state", state)

        @self.socketio.on("get_available_jobs")
        def on_get_available_jobs():
            jobs: List[Dict] = []
            try:
                from engine.content.content_engine import get_content_engine
                ce = get_content_engine()
                if hasattr(ce, "get_heist_jobs"):
                    jobs = ce.get_heist_jobs() or []
            except Exception:
                pass
            if not jobs:
                jobs = [
                    {
                        "id": k,
                        "name": v.get("name", k),
                        "difficulty": v.get("difficulty", 1),
                        "payout": v.get("loot_value", 500_000),
                        "risk": "high" if v.get("difficulty", 1) > 2 else
                                "medium" if v.get("difficulty", 1) > 1 else "low",
                        "guards": v.get("guards", 0),
                        "obstacles": v.get("obstacles", []),
                    }
                    for k, v in VENUES.items()
                ]
            emit("available_jobs", {"jobs": jobs})

        @self.socketio.on("select_job")
        def on_select_job(data):
            job_id = data.get("job_id", "")
            if not job_id:
                emit("error", {"msg": "job_id required"})
                return
            self._active_job_id = job_id
            venue = VENUES.get(job_id, VENUES.get("diamond_exchange", {}))
            emit("job_selected", {"job_id": job_id, "venue": venue})
            self._sync_to_mcp("job_selected", {"job_id": job_id})
            logger.info("[%s] Job selected (operation=job_select): %s", SCENE_ID, job_id)

        @self.socketio.on("assign_crew")
        def on_assign_crew(data):
            crew_member = data.get("crew_member", "")
            role = data.get("role", "")
            if not crew_member or not role:
                emit("error", {"msg": "crew_member and role required"})
                return
            self._assigned_roles[crew_member] = role
            emit("crew_assigned", {
                "crew_member": crew_member,
                "role": role,
                "roles": self._assigned_roles,
            })
            self._sync_to_mcp("crew_assigned", {"crew_member": crew_member, "role": role})
            # v1.49.5 — Check affinities between all assigned crew members
            assigned_ids = list(self._assigned_roles.keys())
            if len(assigned_ids) >= 2:
                self._check_crew_affinity(assigned_ids)

        @self.socketio.on("execute_phase")
        def on_execute_phase(data):
            if not self.game:
                emit("error", {"msg": "No active heist"})
                return
            new_phase = self.game.advance_phase()
            result: Dict[str, Any] = {
                "phase": new_phase.value,
                "state": self.game.to_dict(),
            }
            if self.game.check_bust():
                result["blown"] = True
            elif self.game.check_victory():
                result["complete"] = True
                self._on_heist_complete()
            emit("phase_executed", result)
            self._broadcast_state()

        @self.socketio.on("abort_heist")
        def on_abort_heist():
            if not self.game:
                emit("error", {"msg": "No active heist"})
                return
            heat = self.game.suspicion
            self.game.phase = Phase.FAILED
            # Heat lingers — schedule decay +48 h via ConsequenceStore
            try:
                from engine.mechanics.consequences import get_consequence_store
                cs = get_consequence_store()
                cs.schedule(
                    scene="heist",
                    type="heat_decay",
                    delay_hours=48,
                    payload={"heat": heat, "reason": "abort"},
                )
            except Exception:
                pass
            emit("heist_aborted", {
                "heat": heat,
                "message": "Heist blown. Lay low for 48 hours.",
            })
            self._broadcast_state()
            logger.warning("[%s] Heist aborted (operation=heist, heat=%d)", SCENE_ID, heat)

        @self.socketio.on("get_investigation")
        def on_get_investigation():
            board_state: Dict[str, Any] = {}
            try:
                from engine.mechanics.investigation import get_investigation_board
                board = get_investigation_board()
                if hasattr(board, "get_state"):
                    board_state = board.get_state("heist") or {}
                elif hasattr(board, "get_board"):
                    board_state = board.get_board("heist") or {}
            except Exception:
                pass
            # Fallback: synthesise from live game state
            if not board_state and self.game:
                board_state = {
                    "nodes": [
                        {
                            "id": ob,
                            "label": ob.replace("_", " ").title(),
                            "type": "obstacle",
                            "cleared": False,
                        }
                        for ob in self.game.obstacles_remaining
                    ],
                    "events": self.game.events[-5:] if self.game.events else [],
                }
            emit("investigation_state", {"board": board_state})

    # ── Co-Op Squad SocketIO Handlers ────────────────────────────────────
    # v1.52.0 [2026-03-26] — Room-based multiplayer for co-op heists
    # CONNECTS: SquadManager (engine.multiplayer.squad)
    # CALLED BY: SocketIO events from heist frontend
    # EMITS: squad_state, squad_member_joined, squad_member_left,
    #        squad_roles_updated, squad_ready_state, heist_launched

    def _get_squad_mgr(self):
        """Lazy-load squad manager."""
        if self._squad_manager is None:
            from engine.multiplayer.squad import get_squad_manager
            self._squad_manager = get_squad_manager()
        return self._squad_manager

    def _register_squad_socketio(self) -> None:
        """Register co-op squad SocketIO handlers."""

        @self.socketio.on("squad_create")
        def on_squad_create(data):
            """Create a new heist squad."""
            player_id = data.get("player_id", "player")
            player_name = data.get("player_name", "Mastermind")
            try:
                mgr = self._get_squad_mgr()
                squad = mgr.create_squad(player_id, player_name, scene="heist")
                join_room(f"squad_{squad.squad_id}")
                emit("squad_state", squad.to_dict())
                logger.info("[%s] Squad created: %s (operation=squad)", SCENE_ID, squad.squad_id)
            except ValueError as exc:
                emit("squad_error", {"error": str(exc)})

        @self.socketio.on("squad_join")
        def on_squad_join(data):
            """Join an existing squad."""
            squad_id = data.get("squad_id", "")
            player_id = data.get("player_id", "")
            player_name = data.get("player_name", "")
            try:
                mgr = self._get_squad_mgr()
                mgr.join_squad(squad_id, player_id, player_name)
                join_room(f"squad_{squad_id}")
                squad = mgr.get_squad(squad_id)
                self.socketio.emit("squad_member_joined", {
                    "player_id": player_id,
                    "player_name": player_name,
                    "squad": squad.to_dict() if squad else {},
                }, to=f"squad_{squad_id}")
                logger.info("[%s] Player %s joined squad %s (operation=squad)", SCENE_ID, player_id, squad_id)
            except ValueError as exc:
                emit("squad_error", {"error": str(exc)})

        @self.socketio.on("squad_leave")
        def on_squad_leave(data):
            """Leave a squad."""
            squad_id = data.get("squad_id", "")
            player_id = data.get("player_id", "")
            try:
                mgr = self._get_squad_mgr()
                mgr.leave_squad(squad_id, player_id)
                leave_room(f"squad_{squad_id}")
                self.socketio.emit("squad_member_left", {
                    "player_id": player_id,
                }, to=f"squad_{squad_id}")
            except ValueError as exc:
                emit("squad_error", {"error": str(exc)})

        @self.socketio.on("squad_set_role")
        def on_squad_set_role(data):
            """Set a player's role in the squad."""
            squad_id = data.get("squad_id", "")
            player_id = data.get("player_id", "")
            role = data.get("role", "")
            try:
                mgr = self._get_squad_mgr()
                mgr.set_role(squad_id, player_id, role)
                squad = mgr.get_squad(squad_id)
                self.socketio.emit("squad_roles_updated", {
                    "squad": squad.to_dict() if squad else {},
                }, to=f"squad_{squad_id}")
            except ValueError as exc:
                emit("squad_error", {"error": str(exc)})

        @self.socketio.on("squad_set_ready")
        def on_squad_set_ready(data):
            """Toggle ready state. Auto-starts if all ready."""
            squad_id = data.get("squad_id", "")
            player_id = data.get("player_id", "")
            ready = data.get("ready", True)
            try:
                mgr = self._get_squad_mgr()
                mgr.set_ready(squad_id, player_id, ready)
                squad = mgr.get_squad(squad_id)
                self.socketio.emit("squad_ready_state", {
                    "squad": squad.to_dict() if squad else {},
                }, to=f"squad_{squad_id}")
            except ValueError as exc:
                emit("squad_error", {"error": str(exc)})

        @self.socketio.on("squad_launch_heist")
        def on_squad_launch_heist(data):
            """Launch the heist if all squad members are ready."""
            squad_id = data.get("squad_id", "")
            try:
                mgr = self._get_squad_mgr()
                heist_id = mgr.start_heist(squad_id)
                if not heist_id:
                    emit("squad_error", {"error": "Not all members are ready"})
                    return

                # Create the actual HeistState for this squad
                squad = mgr.get_squad(squad_id)
                self._create_squad_heist(squad)

                self.socketio.emit("heist_launched", {
                    "heist_id": heist_id,
                    "squad": squad.to_dict() if squad else {},
                }, to=f"squad_{squad_id}")
                self._broadcast_state()
                logger.info(
                    "[%s] Squad heist launched (operation=squad_heist, squad=%s, heist=%s, members=%d)",
                    SCENE_ID, squad_id, heist_id, squad.member_count if squad else 0,
                )
            except ValueError as exc:
                emit("squad_error", {"error": str(exc)})

        @self.socketio.on("squad_chat")
        def on_squad_chat(data):
            """Send a message to squad members only."""
            squad_id = data.get("squad_id", "")
            player_id = data.get("player_id", "")
            content = data.get("content", "")
            if squad_id and content:
                self.socketio.emit("squad_message", {
                    "player_id": player_id,
                    "content": content,
                }, to=f"squad_{squad_id}")

        @self.socketio.on("squad_list_open")
        def on_squad_list_open():
            """List open squads available to join."""
            mgr = self._get_squad_mgr()
            emit("squad_list", {"squads": mgr.list_open_squads()})

        @self.socketio.on("squad_vote_phase")
        def on_squad_vote_phase(data):
            """Vote to advance the heist phase (majority required)."""
            squad_id = data.get("squad_id", "")
            player_id = data.get("player_id", "")
            mgr = self._get_squad_mgr()
            squad = mgr.get_squad(squad_id)
            if not squad:
                emit("squad_error", {"error": "Squad not found"})
                return

            # Track votes on squad object
            if not hasattr(squad, "_phase_votes"):
                squad._phase_votes = set()
            squad._phase_votes.add(player_id)

            total = squad.member_count
            votes = len(squad._phase_votes)
            needed = (total // 2) + 1

            if votes >= needed:
                squad._phase_votes = set()
                # Actually advance the phase
                if self.game:
                    self.game.advance_phase()
                    self._broadcast_state()
                self.socketio.emit("squad_phase_advanced", {
                    "votes": votes,
                    "total": total,
                    "new_phase": self.game.phase.value if self.game else "unknown",
                }, to=f"squad_{squad_id}")
            else:
                self.socketio.emit("squad_vote_cast", {
                    "player_id": player_id,
                    "votes": votes,
                    "needed": needed,
                    "total": total,
                }, to=f"squad_{squad_id}")

    def _create_squad_heist(self, squad) -> None:
        """Create a HeistState populated with squad members as crew."""
        if not squad:
            return
        try:
            from content.scenes.heist.heist_game import HeistState
            self.game = HeistState()
            # Add squad members as crew (alongside NPC crew)
            for pid, member in squad.members.items():
                specialty = member.role or "wildcard"
                self.game.add_crew(pid, member.display_name, specialty)
            logger.info(
                "[%s] Squad heist state created with %d players (operation=squad_heist)",
                SCENE_ID, squad.member_count,
            )
        except Exception as exc:
            logger.error("[%s] Squad heist creation failed: %s (operation=squad_heist)", SCENE_ID, exc)

    def _broadcast_to_squad(self, squad_id: str, event: str, data: dict) -> None:
        """Broadcast an event to a specific squad room only."""
        self.socketio.emit(event, data, to=f"squad_{squad_id}")

    # ── Affinity & Betrayal System ───────────────────────────────────────
    # v1.49.5 [2026-03-22] — Crew synergy, argument risk, and betrayal mechanics
    # CONNECTS: CREW_ROSTER affinities, HeistState.suspicion, CrewMember.morale
    # CALLED BY: on_assign_crew handler, _crew_tick, perform_action flow
    # EMITS: crew_synergy, crew_argument, crew_betrayal Socket.IO events

    def _check_crew_affinity(self, crew_ids: List[str]) -> None:
        """Evaluate pairwise affinities between assigned crew members.

        Positive affinity (+10 or higher) logs a synergy bonus.
        Negative affinity (-10 or lower) warns of friction.

        Args:
            crew_ids: List of crew member IDs currently assigned to the heist.
        """
        checked_pairs: set = set()
        for i, cid_a in enumerate(crew_ids):
            tmpl_a = self._crew_config.get(cid_a, {})
            affinities_a = tmpl_a.get("affinity", {})
            for cid_b in crew_ids[i + 1:]:
                pair_key = tuple(sorted([cid_a, cid_b]))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                tmpl_b = self._crew_config.get(cid_b, {})
                affinities_b = tmpl_b.get("affinity", {})

                # Average the bidirectional affinity
                score_ab = affinities_a.get(cid_b, 0)
                score_ba = affinities_b.get(cid_a, 0)
                avg_score = (score_ab + score_ba) / 2.0

                name_a = tmpl_a.get("name", cid_a)
                name_b = tmpl_b.get("name", cid_b)

                if avg_score >= 10:
                    # Synergy bonus — log it and notify clients
                    bonus_pct = min(int(abs(avg_score)), 30)
                    logger.info(
                        "[HEIST] Crew synergy: %s and %s work well together (+%d%% success)",
                        name_a, name_b, bonus_pct,
                    )
                    if hasattr(self, "socketio") and self.socketio:
                        self.socketio.emit("crew_synergy", {
                            "crew_a": cid_a, "crew_b": cid_b,
                            "name_a": name_a, "name_b": name_b,
                            "bonus_pct": bonus_pct,
                            "message": f"{name_a} and {name_b} work well together (+{bonus_pct}% success)",
                        })
                elif avg_score <= -10:
                    # Friction warning — log it and notify clients
                    friction_pct = min(int(abs(avg_score)), 30)
                    logger.warning(
                        "[HEIST] Crew friction: %s and %s have tension (-%d%% reliability, argument risk)",
                        name_a, name_b, friction_pct,
                    )
                    if hasattr(self, "socketio") and self.socketio:
                        self.socketio.emit("crew_friction", {
                            "crew_a": cid_a, "crew_b": cid_b,
                            "name_a": name_a, "name_b": name_b,
                            "friction_pct": friction_pct,
                            "message": f"{name_a} and {name_b} have tension (argument risk, -{friction_pct}% reliability)",
                        })

    def _check_argument_risk(self) -> Optional[Dict[str, Any]]:
        """Roll for crew arguments between members with negative affinity.

        Negative affinity (-10 or lower) gives a 10% chance per turn of an
        argument that raises suspicion by +5.

        Returns:
            Argument event dict if one occurred, None otherwise.
        """
        if not self.game:
            return None

        active_crew = [
            cid for cid, m in self.game.crew.items()
            if not m.arrested
        ]

        for i, cid_a in enumerate(active_crew):
            tmpl_a = self._crew_config.get(cid_a, {})
            affinities_a = tmpl_a.get("affinity", {})
            for cid_b in active_crew[i + 1:]:
                score = affinities_a.get(cid_b, 0)
                if score <= -10 and random.random() < 0.10:
                    name_a = tmpl_a.get("name", cid_a)
                    name_b = self._crew_config.get(cid_b, {}).get("name", cid_b)
                    # Argument raises suspicion
                    self.game.suspicion = min(100, self.game.suspicion + 5)
                    # Both lose morale
                    if cid_a in self.game.crew:
                        self.game.crew[cid_a].morale = max(0, self.game.crew[cid_a].morale - 5)
                    if cid_b in self.game.crew:
                        self.game.crew[cid_b].morale = max(0, self.game.crew[cid_b].morale - 5)

                    event = {
                        "type": "crew_argument",
                        "crew_a": cid_a, "crew_b": cid_b,
                        "name_a": name_a, "name_b": name_b,
                        "suspicion_delta": 5,
                        "message": (
                            f"{name_a} and {name_b} are arguing! "
                            f"Suspicion +5 (now {self.game.suspicion}). Morale drops."
                        ),
                    }
                    logger.warning(
                        "[HEIST] Crew argument: %s vs %s (suspicion +5, now %d)",
                        name_a, name_b, self.game.suspicion,
                    )
                    if hasattr(self, "socketio") and self.socketio:
                        self.socketio.emit("crew_argument", event)
                    return event  # Only one argument per tick
        return None

    def _check_betrayal_risk(self) -> Optional[Dict[str, Any]]:
        """Check if a demoralized crew member betrays the team.

        Conditions: crew morale < 30 AND suspicion > 70 gives a 15% chance
        of betrayal — the traitor tips off guards, suspicion +30.

        Returns:
            Betrayal event dict if one occurred, None otherwise.
        """
        if not self.game:
            return None

        for cid, member in self.game.crew.items():
            if member.arrested:
                continue
            # Betrayal condition: low morale + high suspicion
            if member.morale < 30 and self.game.suspicion > 70:
                if random.random() < 0.15:
                    self.game.suspicion = min(100, self.game.suspicion + 30)
                    tmpl = self._crew_config.get(cid, {})
                    name = tmpl.get("name", member.name)

                    event = {
                        "type": "crew_betrayal",
                        "traitor": cid,
                        "traitor_name": name,
                        "suspicion_delta": 30,
                        "message": (
                            f"BETRAYAL! {name} tipped off the guards! "
                            f"Suspicion +30 (now {self.game.suspicion}). "
                            f"Trust is broken."
                        ),
                    }
                    logger.error(
                        "[HEIST] BETRAYAL: %s tipped off guards (suspicion +30, now %d)",
                        name, self.game.suspicion,
                    )
                    if hasattr(self, "socketio") and self.socketio:
                        self.socketio.emit("crew_betrayal", event)

                    # The traitor is removed from active duty
                    member.arrested = True

                    return event  # Only one betrayal per tick
        return None

    def _get_affinity_bonus(self, char_id: str) -> float:
        """Calculate a success chance modifier based on average affinity with active crew.

        Positive average affinity grants up to +10% bonus; negative up to -10% penalty.

        Args:
            char_id: The crew member performing the action.

        Returns:
            Float modifier to add to success chance (-0.10 to +0.10).
        """
        if not self.game:
            return 0.0
        tmpl = self._crew_config.get(char_id, {})
        affinities = tmpl.get("affinity", {})
        if not affinities:
            return 0.0

        active_crew = [
            cid for cid in self.game.crew
            if cid != char_id and not self.game.crew[cid].arrested
        ]
        if not active_crew:
            return 0.0

        total = sum(affinities.get(cid, 0) for cid in active_crew)
        avg = total / len(active_crew)
        # Scale: avg affinity of +-20 maps to +-0.10 success modifier
        return max(-0.10, min(0.10, avg / 200.0))

    # ── Agent management ─────────────────────────────────────────────────

    def _init_agent(self, char_id: str, template: dict):
        """Initialize an AI agent for a crew member."""
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            mgr = get_virtual_agent_manager()
            self._agents[char_id] = {
                "template": template,
                "conversation_id": f"heist_{self.game.heist_id}_{char_id}",
            }
        except Exception as exc:
            logger.debug("Agent init for %s failed: %s", char_id, exc)

    def _reply_worker(self, char_id: str, message: str):
        """Generate an AI crew member's reply (background thread)."""
        if not self.game or char_id not in self.game.crew:
            return

        member = self.game.crew[char_id]
        agent_info = self._agents.get(char_id, {})
        template = agent_info.get("template", {})
        conv_id = agent_info.get("conversation_id", f"heist_{char_id}")

        # Build context-rich system prompt
        system = self._build_crew_prompt(member, template)

        self.socketio.emit("typing", {"character_id": char_id, "typing": True})

        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest

            mgr = get_virtual_agent_manager()
            req = InferenceRequest(
                agent_id=char_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"[Mastermind]: {message}"},
                ],
                conversation_id=conv_id,
                temperature=0.9,
                max_output_tokens=500,
                store=True,
                metadata={"scene": "heist", "character_name": member.name},
            )

            # Use pipeline path for watcher + kill switch
            if hasattr(mgr, "infer_with_pipeline"):
                try:
                    proc = mgr.infer_with_pipeline(req)
                except Exception:
                    proc = mgr.infer_processed(req)
            else:
                proc = mgr.infer_processed(req)

            text = (proc.clean_text or "").strip()
            mood = proc.mood_tags[0] if proc.mood_tags else None
            image = proc.image_requests[0] if proc.image_requests else None
            actions = list(proc.action_tags) if proc.action_tags else []

            # Sync mood to Coordinator for cross-system visibility
            if mood:
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    get_coordinator().update(
                        char_id, mood=mood,
                        source="heist_reply", scene="heist",
                    )
                except Exception:
                    pass

            if text:
                self.socketio.emit("crew_message", {
                    "character_id": char_id,
                    "name": member.name,
                    "specialty": member.specialty.value,
                    "message": text,
                    "mood": mood,
                    "image": image,
                    "actions": actions,
                    "timestamp": time.time(),
                })

            # If the agent mentioned an action tag, auto-execute it
            for act_tag in actions:
                act = act_tag.lower().strip()
                if act in ("disable_alarm", "crack_safe", "hack_door", "breach_door",
                           "fight", "persuade", "distract", "drive", "scout"):
                    result = self.game.perform_action(char_id, act)
                    self._broadcast_event(result)
                    self._broadcast_state()
                    break

        except Exception as exc:
            logger.error("[%s] Heist reply failed (operation=chat, agent=%s): %s", SCENE_ID, char_id, exc)
        finally:
            self.socketio.emit("typing", {"character_id": char_id, "typing": False})

    # v1.49.5 [2026-03-22] — Added argument and betrayal checks per tick
    def _crew_tick(self) -> List[Dict]:
        """Have each crew member make a decision/comment for this turn.

        Also rolls for crew arguments (negative affinity) and betrayal
        (low morale + high suspicion). These events fire Socket.IO events
        and modify game state in real time.

        Returns:
            List of result dicts describing what happened this tick.
        """
        if not self.game:
            return []
        results = []

        # ── v1.49.5: Argument risk check (before crew acts) ──────────
        # Negative affinity (-10 or lower) = 10% chance of argument per tick
        argument = self._check_argument_risk()
        if argument:
            results.append(argument)

        # ── v1.49.5: Betrayal risk check ──────────────────────────────
        # Morale < 30 AND suspicion > 70 = 15% chance of betrayal
        betrayal = self._check_betrayal_risk()
        if betrayal:
            results.append(betrayal)
            # If suspicion hit 100 from betrayal, check bust immediately
            if self.game.check_bust():
                results.append({"bust": True, "message": "BUSTED after betrayal!"})
                self._broadcast_state()
                return results

        # ── Standard crew tick: each member comments/acts ─────────────
        for char_id, member in self.game.crew.items():
            if member.arrested:
                continue
            # Auto-generate a contextual prompt
            prompt = self._build_tick_prompt(member)
            self._reply_worker(char_id, prompt)
            results.append({"character_id": char_id, "name": member.name})

        # Complication roll
        comp = self.game.maybe_complication()
        if comp:
            self.socketio.emit("complication", {
                "message": comp,
                "phase": self.game.phase.value,
                "timestamp": time.time(),
            })
            results.append({"complication": comp})

        return results

    # v1.49.5 [2026-03-22] — Enriched prompt with backstory, affinity context, system_prompt
    def _build_crew_prompt(self, member: CrewMember, template: dict) -> str:
        """Build a rich system prompt for a crew member.

        Uses system_prompt from CREW_ROSTER if available, falls back to
        personality field. Injects backstory, affinity context with other
        active crew, and phase-specific guidance.

        Args:
            member: The CrewMember dataclass instance.
            template: The crew roster entry dict (from CREW_ROSTER).

        Returns:
            Fully assembled system prompt string for LLM inference.
        """
        # Prefer system_prompt (richer, includes relationship hints), fall back to personality
        personality = template.get("system_prompt", template.get("personality", f"You are {member.name}."))
        backstory = template.get("backstory", "")
        situation = self.game.situation_summary() if self.game else ""

        # v1.49.5 — Build affinity context so the agent knows who it likes/dislikes
        affinity_lines = []
        affinities = template.get("affinity", {})
        if affinities and self.game:
            for other_id, score in affinities.items():
                if other_id in self.game.crew and not self.game.crew[other_id].arrested:
                    other_name = self._crew_config.get(other_id, {}).get("name", other_id)
                    if score >= 15:
                        affinity_lines.append(f"  - You deeply trust {other_name}.")
                    elif score >= 5:
                        affinity_lines.append(f"  - You get along with {other_name}.")
                    elif score <= -15:
                        affinity_lines.append(f"  - You strongly distrust {other_name}.")
                    elif score <= -5:
                        affinity_lines.append(f"  - You're wary of {other_name}.")
        affinity_ctx = ""
        if affinity_lines:
            affinity_ctx = "CREW RELATIONSHIPS:\n" + "\n".join(affinity_lines) + "\n\n"

        phase_guide = ""
        if self.game:
            if self.game.phase == Phase.PLANNING:
                phase_guide = (
                    "You are in the PLANNING phase. Suggest strategies. "
                    "Discuss who should handle what. Be creative."
                )
            elif self.game.phase == Phase.APPROACH:
                phase_guide = (
                    "You are APPROACHING the target. Stay quiet. "
                    "Report what you see. Suggest how to proceed."
                )
            elif self.game.phase == Phase.EXECUTION:
                phase_guide = (
                    "You are INSIDE. Work fast! Clear obstacles. Watch for guards. "
                    "Use your specialty skills — call heist_action when ready to act."
                )
            elif self.game.phase == Phase.ESCAPE:
                phase_guide = (
                    "TIME TO GO! Get to the getaway vehicle. Handle any pursuit. "
                    "Protect the loot. Coordinate the escape."
                )

        backstory_section = f"BACKSTORY: {backstory}\n\n" if backstory else ""

        return (
            f"{personality}\n\n"
            f"{backstory_section}"
            f"{affinity_ctx}"
            f"CURRENT SITUATION:\n{situation}\n\n"
            f"{phase_guide}\n\n"
            f"{self._get_governance_context(member.character_id)}"
            "You may use [MOOD:emotion] to express how you're feeling.\n"
            "You may use [ACTION:action_name] to perform a heist action.\n"
            "You may use [IMAGE:description] to generate a visual.\n"
            "Keep responses under 3 sentences. Stay in character."
        )

    def _get_governance_context(self, agent_id: str) -> str:
        """Get governance directives from the interceptor pipeline."""
        try:
            from engine.mcp.comms_framework import build_governance_context
            ctx = build_governance_context(agent_id, "heist", "")
            return f"{ctx}\n\n" if ctx else ""
        except Exception:
            return ""

    def _build_tick_prompt(self, member: CrewMember) -> str:
        """Build a prompt for autonomous crew tick."""
        if not self.game:
            return "What's the plan?"
        phase = self.game.phase
        suspicion = self.game.suspicion

        if phase == Phase.PLANNING:
            return random.choice([
                "What's our approach? Share your thoughts on the plan.",
                "I've been thinking about the obstacles. What's your take?",
                "How should we divide roles for this job?",
                f"Suspicion is at {suspicion}. Are we being careful enough?",
            ])
        elif phase == Phase.APPROACH:
            return random.choice([
                "What do you see? Any guards?",
                "We need to get past the entrance. Ideas?",
                "Something feels off. What do you think?",
                f"Suspicion: {suspicion}. Should we abort?",
            ])
        elif phase == Phase.EXECUTION:
            obstacles = ", ".join(self.game.obstacles_remaining) or "nothing"
            return random.choice([
                f"Still need to clear: {obstacles}. What's your move?",
                "Hurry up! Time is running out.",
                "I think I heard something. Stay alert!",
                "How much loot have we grabbed? We need more!",
            ])
        elif phase == Phase.ESCAPE:
            return random.choice([
                "GO GO GO! Where's the exit?",
                "Police are closing in. What's the plan?",
                "Did everyone make it out?",
                "Head for the backup route!",
            ])
        return "What now?"

    # ── Broadcast helpers ────────────────────────────────────────────────

    def _broadcast_state(self):
        if self.game:
            self.socketio.emit("game_state", self.game.to_dict())

    def _broadcast_event(self, event: dict):
        self.socketio.emit("game_event", event)

    def _on_heist_complete(self) -> None:
        """Handle heist completion — schedule payout, fire EventBus, update reputation."""
        if not self.game:
            return
        payout = self.game.loot_collected
        job_id = self._active_job_id
        venue_name = self.game.venue.get("name", "unknown") if self.game.venue else "unknown"

        # Payout arrives +24 h via ConsequenceStore
        try:
            from engine.mechanics.consequences import get_consequence_store
            cs = get_consequence_store()
            cs.schedule(
                scene="heist",
                type="payout",
                delay_hours=24,
                payload={"amount": payout, "source": "heist_job", "job_id": job_id},
            )
        except Exception:
            pass

        # Publish to EventBus — heist.job_complete
        try:
            from engine.events.event_bus import get_event_bus
            bus = get_event_bus()
            bus.publish("heist.job_complete", {
                "payout": payout,
                "job_id": job_id,
                "venue": venue_name,
                "crew": list(self.game.crew.keys()),
                "suspicion": self.game.suspicion,
            })
        except Exception:
            pass

        # Update crew reputation
        try:
            from engine.characters.reputation import get_reputation_manager
            rep_mgr = get_reputation_manager()
            for char_id in self.game.crew:
                rep_mgr.update(char_id, delta=10, source="heist_complete")
        except Exception:
            pass

        # Leaderboard
        try:
            from engine.mcp.shared_boards import get_shared_boards
            get_shared_boards().submit_score(
                "heist_legends", "Mastermind",
                payout,
                metadata={"venue": venue_name, "suspicion": self.game.suspicion},
            )
        except Exception:
            pass

        logger.info(
            "[%s] Heist complete (operation=heist_complete, payout=$%d, venue=%s)",
            SCENE_ID, payout, venue_name,
        )

    # ── BaseScene interface ──────────────────────────────────────────────

    def get_plugin_info(self) -> dict:
        return {
            "name": "THE SCORE",
            "description": "Grimy planning room for criminal jobs. Everyone gets a cut.",
            "version": "0.68",
            "author": "CosySim",
            "port": self.port,
            "tags": ["heist", "multi-agent", "cooperative", "game", "pipeline", "mcp"],
            "skill_packs": ["memory", "character"],
        }

    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_before_serve(self) -> None:
        """Hook: wire engine subsystems and subscribe to world events."""
        # Wire engine subsystems (all optional — graceful fallback if unavailable)
        try:
            from engine.content.content_engine import get_content_engine
            self._content_engine = get_content_engine()
        except Exception:
            self._content_engine = None
        try:
            from engine.economy.economy import get_economy_manager
            self._economy = get_economy_manager()
        except Exception:
            self._economy = None
        try:
            from engine.characters.reputation import get_reputation_manager
            self._reputation = get_reputation_manager()
        except Exception:
            self._reputation = None
        try:
            from engine.mechanics.investigation import get_investigation_board
            self._investigation = get_investigation_board()
        except Exception:
            self._investigation = None
        try:
            from engine.mechanics.consequences import get_consequence_store
            self._consequences = get_consequence_store()
        except Exception:
            self._consequences = None
        try:
            from engine.director.scene_director import get_scene_director
            self._director = get_scene_director()
        except Exception:
            self._director = None
        try:
            from engine.events.event_bus import get_event_bus
            self._event_bus = get_event_bus()
        except Exception:
            self._event_bus = None
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            fw.on("environment_change", lambda evt: None)
        except Exception:
            pass
        # ── World State ──────────────────────────────────────────────
        self._world_state = None
        if _WORLD_AVAILABLE:
            self._world_state = get_world_state()
            if self._event_bus is None:
                self._event_bus = get_event_bus()
            self._event_bus.subscribe("world.tick", self._on_world_tick)
            self._event_bus.subscribe("world.time_change", self._on_time_change)

    def on_shutdown(self) -> None:
        """Hook: stop ticker, unsubscribe events, save framework state."""
        self._ticker_stop.set()
        if hasattr(self, "_event_bus") and self._event_bus:
            try:
                self._event_bus.unsubscribe("world.tick", self._on_world_tick)
                self._event_bus.unsubscribe("world.time_change", self._on_time_change)
            except Exception:
                pass
        try:
            from engine.mcp.framework import get_framework
            get_framework().save_state()
        except Exception:
            pass
        logger.info("[%s] Scene stopped (operation=lifecycle)", SCENE_ID)

    # ── World State handlers ──────────────────────────────────────────
    def _on_world_tick(self, event: dict) -> None:
        """React to world simulation tick."""
        if hasattr(self, "socketio") and self.socketio:
            try:
                time_data = self._world_state.get_time()
                self.socketio.emit("world_tick", {
                    "hour": getattr(time_data, "hour", 0),
                    "day": getattr(time_data, "day", 1),
                    "weather": str(getattr(time_data, "weather", "clear")),
                })
            except Exception:
                pass

    def _on_time_change(self, event: dict) -> None:
        """React to time-of-day changes."""
        pass  # scenes override this for time-gated content
