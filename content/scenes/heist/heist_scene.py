"""
Heist Scene — Cooperative multi-agent planning & execution showcase.

Port 5565. Flask + SocketIO.

Demonstrates:
- Multi-agent coordination (3–4 crew members with specialties)
- VirtualPipeline integration (watcher, kill switch, pre-warming)
- Phase-gated MCP rules (planning → approach → execution → escape)
- Real-time game state with skill checks and complications
- Pipeline-aware streaming (moods, images, actions extracted automatically)
- SharedBoard integration (heist leaderboard)

The player acts as the Mastermind, directing the crew. Each crew member
is an AI agent with a personality and specialty. They discuss, argue,
and execute actions based on the heist state and their character.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, render_template, jsonify, request as flask_request
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from engine.mcp.framework import MCPSceneMixin
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
DEFAULT_PORT = 5565

# Crew personality templates
CREW_TEMPLATES = {
    "ghost": {
        "name": "Ghost",
        "specialty": "hacker",
        "personality": (
            "You are Ghost, a quiet and brilliant hacker. You speak in short, "
            "technical sentences. You're calm under pressure but get annoyed when "
            "plans change. You use tech jargon naturally. Dry humor."
        ),
    },
    "tank": {
        "name": "Tank",
        "specialty": "muscle",
        "personality": (
            "You are Tank, the crew's muscle. Big, loud, loyal. You prefer "
            "direct solutions — kick the door, intimidate the guard. You're "
            "protective of the crew. You crack jokes when nervous."
        ),
    },
    "silk": {
        "name": "Silk",
        "specialty": "talker",
        "personality": (
            "You are Silk, the smooth-talking con artist. You can talk your way "
            "into or out of anything. Charming, manipulative, always has a backup "
            "plan. You flirt with danger and everyone else."
        ),
    },
    "wheels": {
        "name": "Wheels",
        "specialty": "driver",
        "personality": (
            "You are Wheels, the getaway driver and scout. You know every street, "
            "every shortcut. You're paranoid — always checking exits. You talk fast "
            "and get impatient waiting. Car metaphors for everything."
        ),
    },
}


class HeistScene(BaseScene, MCPSceneMixin, NexusSceneMixin, mcp_scene_id=SCENE_ID):
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

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        db: Optional[Database] = None,
    ):
        scene_dir = Path(__file__).parent
        self.app = Flask(
            __name__,
            template_folder=str(scene_dir / "templates"),
            static_folder=str(scene_dir / "static"),
        )
        register_shared_assets(self.app)
        # Extend template loader to include shared templates (navbar_v2.html etc.)
        import jinja2 as _jinja2
        _shared_tpl = scene_dir.parent.parent / "shared" / "templates"
        self.app.jinja_loader = _jinja2.ChoiceLoader([
            _jinja2.FileSystemLoader(str(scene_dir / "templates")),
            _jinja2.FileSystemLoader(str(_shared_tpl)),
        ])
        self.register_health_route(self.app)
        self.register_hud_route(self.app)
        self.register_announcer_route(self.app)
        self.register_inventory_route(self.app)
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")

        super().__init__(scene_name="heist", host=host, port=port)

        self.db = db or Database()
        self.game: Optional[HeistState] = None
        self._agents: Dict[str, Any] = {}
        self._crew_config = dict(CREW_TEMPLATES)
        self._ticker_thread: Optional[threading.Thread] = None
        self._ticker_stop = threading.Event()

        # Heist state — v0.68
        self._active_job_id: Optional[str] = None
        self._assigned_roles: Dict[str, str] = {}

        # Engine subsystem refs (wired in start())
        self._content_engine = None
        self._economy = None
        self._reputation = None
        self._investigation = None
        self._consequences = None
        self._director = None
        self._event_bus = None

        register_heist_rules()
        self.register_bench_route(self.app, self.socketio)
        self.register_tts_route(self.app)
        self._register_routes()
        self._register_socketio()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()
        self._tag_registry.register(TagDef(
            name="PLAN", pattern=r"\[PLAN:([^\]]+)\]",
            handler=None, strip_from_output=True, pre_warm_intent="heist_plan"
        ))

        self.nexus_init("heist")

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
            logger.info("Heist job selected: %s", job_id)

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
            logger.warning("Heist aborted — heat=%d", heat)

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
            logger.error("Heist reply failed for %s: %s", char_id, exc)
        finally:
            self.socketio.emit("typing", {"character_id": char_id, "typing": False})

    def _crew_tick(self) -> List[Dict]:
        """Have each crew member make a decision/comment for this turn."""
        if not self.game:
            return []
        results = []
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

    def _build_crew_prompt(self, member: CrewMember, template: dict) -> str:
        """Build a rich system prompt for a crew member."""
        personality = template.get("personality", f"You are {member.name}.")
        situation = self.game.situation_summary() if self.game else ""
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

        return (
            f"{personality}\n\n"
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
            "THE SCORE — heist complete | payout=$%d | venue=%s", payout, venue_name
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

    def start(self) -> None:
        print(f"THE SCORE — Dark Renaissance heist scene starting on port {self.port}...")
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
        self.socketio.run(
            self.app, host=self.host, port=self.port,
            debug=False, allow_unsafe_werkzeug=True,
        )

    def stop(self) -> None:
        self.nexus_flush()
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
        print("Heist scene stopped.")

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
