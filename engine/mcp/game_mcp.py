"""
CosySim MCP Game Engine
=======================

Full MCP-backed game session management for Truth or Dare and Mystery Investigation.

MCPGameSession
--------------
A tracked, observable game session backed by the ``GameState`` key-value store.
Each session adds:

* **Turn-by-turn history** — every game event logged as a ``GameTurnEntry``
* **Character stat sync** — game outcomes push deltas into scene stats
  (mood, arousal, happiness, openness via SceneStateManager)
* **AgentRouter messaging** — start/end events broadcast to registered agents
* **ActivityBus integration** — state changes visible in admin panel activity feed
* **MCPFramework consequences** — high-scoring events queue bedroom stat bonuses

MCPGameNode
-----------
A ``MCPSceneNode`` sub-type that represents a game as a "virtual sub-scene"
under the parent bedroom scene.  Automatically registered with MCPFramework
as ``bedroom/truth_or_dare`` or ``bedroom/mystery``.

GameSessionInterceptor
----------------------
Priority-35 interceptor (sits between SkillAwarenessInterceptor and the
legacy GameRulesInterceptor).  Detects any active ``MCPGameSession`` for
the current character and:

  - Injects the full turn-by-turn history summary into the system prompt
  - Exposes available game actions as required/optional skill hints
  - Sets ``ctx["active_game_session"]`` for downstream interceptors

Module singletons
-----------------
``get_session_registry()``              → ``GameSessionRegistry``
``get_or_create_session(...)``          → ``MCPGameSession``
``get_active_session(character_id)``    → first active session for char
``all_sessions()``                      → list of all summary dicts
``active_sessions()``                   → list of active summary dicts
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  STAT SYNC PRESETS
#  Maps (session_type, event_type) → scene-stat deltas applied via SSM
# ══════════════════════════════════════════════════════════════════════

STAT_SYNC: Dict[str, Dict[str, Dict[str, float]]] = {
    "truth_or_dare": {
        "dare_completed":  {"openness": 5.0, "happiness": 8.0, "arousal": 3.0},
        "truth_answered":  {"openness": 4.0, "happiness": 4.0},
        "dare_refused":    {"openness": -3.0, "fear": 2.0},
        "game_won":        {"happiness": 15.0, "openness": 10.0},
        "game_ended":      {"happiness": -5.0},
        "escalated_dare":  {"arousal": 10.0, "openness": 8.0, "horniness": 5.0},
        "round_complete":  {"happiness": 3.0},
    },
    "mystery": {
        "clue_found":      {"happiness": 6.0, "openness": 3.0},
        "red_herring":     {"fear": 2.0, "anger": 3.0},
        "culprit_named":   {"happiness": 12.0},
        "game_won":        {"happiness": 18.0, "openness": 8.0},
        "game_lost":       {"happiness": -8.0, "anger": 5.0},
        "game_ended":      {"happiness": -3.0},
    },
}


# ══════════════════════════════════════════════════════════════════════
#  GAME TURN ENTRY  ─ one event in the session history
# ══════════════════════════════════════════════════════════════════════

@dataclass
class GameTurnEntry:
    """A single logged event in the game's history."""
    turn:        int
    event_type:  str
    description: str
    data:        Dict = field(default_factory=dict)
    actor:       str  = "system"    # player | character | system
    timestamp:   float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "turn":        self.turn,
            "event_type":  self.event_type,
            "description": self.description,
            "data":        self.data,
            "actor":       self.actor,
            "timestamp":   self.timestamp,
        }

    def summary(self) -> str:
        return f"[T{self.turn}/{self.event_type}] {self.description}"


# ══════════════════════════════════════════════════════════════════════
#  MCPGameSession  ─ core per-game session object
# ══════════════════════════════════════════════════════════════════════

class MCPGameSession:
    """
    A fully MCP-integrated game session.

    Parameters
    ----------
    game_id      : str   Unique game identifier, e.g. ``tod_char-001``
    session_type : str   ``"truth_or_dare"`` | ``"mystery"``
    character_id : str   Primary player/host character
    scene_id     : str   Parent scene (typically ``"bedroom"``)
    """

    def __init__(
        self,
        game_id:      str,
        session_type: str,
        character_id: str,
        scene_id:     str = "bedroom",
    ) -> None:
        self.game_id      = game_id
        self.session_type = session_type
        self.character_id = character_id
        self.scene_id     = scene_id
        self.started_at   = time.time()
        self.ended_at: Optional[float] = None
        self._history: List[GameTurnEntry] = []
        self._turn    = 0

        # Bootstrap MCP game-state store
        gs = self._gs()
        gs.set(game_id, "session_type",  session_type)
        gs.set(game_id, "character_id",  character_id)
        gs.set(game_id, "scene_id",      scene_id)
        gs.set(game_id, "active",        True)
        gs.set(game_id, "started_at",    self.started_at)
        gs.set(game_id, "turn",          0)
        gs.set(game_id, "score",         0)

        # Register virtual sub-scene node in MCPFramework
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            fw.get_scene(f"{scene_id}/{session_type}")   # auto-creates MCPSceneNode
            char_node = fw.get_character(character_id)
            char_node.enter_scene(scene_id)
        except Exception as exc:
            logger.debug("MCPGameSession: MCP registration failed: %s", exc)

        # Broadcast start event
        self._emit("game_start", f"Game '{session_type}' started for {character_id}", {})
        # v2.7: response_id tracking for game turn replay/undo
        self._response_ids: List[str] = []
        logger.info(
            "MCPGameSession created: %s type=%s char=%s scene=%s",
            game_id, session_type, character_id, scene_id,
        )

    # ── History ──────────────────────────────────────────────────────

    def log_event(
        self,
        event_type:  str,
        description: str,
        data:        Optional[Dict] = None,
        actor:       str = "system",
    ) -> GameTurnEntry:
        """Record a game event; apply stat sync; broadcast to ActivityBus."""
        self._turn += 1
        entry = GameTurnEntry(
            turn=self._turn,
            event_type=event_type,
            description=description,
            data=data or {},
            actor=actor,
        )
        self._history.append(entry)
        self._gs().set(self.game_id, "turn", self._turn)

        self._apply_stat_sync(event_type)
        self._emit(event_type, description, data or {})
        return entry

    def get_history(self, limit: int = 20) -> List[Dict]:
        """Return the last *limit* history entries as dicts."""
        return [e.to_dict() for e in self._history[-limit:]]

    def history_summary(self, limit: int = 10) -> str:
        """Return a brief text summary of recent turns."""
        recent = self._history[-limit:]
        if not recent:
            return "No game history yet."
        return "\n".join(e.summary() for e in recent)

    # ── v2.7: structured turns and branching ─────────────────────────

    def process_turn_structured(
        self,
        prompt: str,
        schema: Dict,
        *,
        schema_name: str = "game_turn",
    ) -> Optional[Dict]:
        """
        Process a game turn using structured JSON output.

        Uses SceneAgent.run_structured() with store=False for reliable
        game decision parsing (dare content, truth questions, clues, etc.)

        Args:
            prompt:      The game turn prompt.
            schema:      JSON schema for the expected response.
            schema_name: Name for the schema.

        Returns:
            Parsed JSON dict, or None on failure.
        """
        try:
            from engine.agents.scene_agent import get_scene_agent
            agent = get_scene_agent()
            result = agent.run_structured(prompt, schema, schema_name=schema_name)
            if result:
                self.log_event("structured_turn", f"Structured: {str(result)[:80]}", result)
            return result
        except Exception as exc:
            logger.error("Structured turn failed: %s", exc)
            return None

    def record_response_id(self, response_id: str) -> None:
        """Track a response_id for potential game undo/replay."""
        if response_id:
            self._response_ids.append(response_id)

    def get_response_ids(self) -> List[str]:
        """Get all tracked response_ids for branching."""
        return list(self._response_ids)

    def process_turn_stateful(
        self,
        user_message: str,
        *,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """Process a game turn using stateful conversation (store=true).

        Maintains conversation history so the game "remembers" previous turns.
        Tracks response_ids for undo/branch support.
        """
        try:
            from engine.lmstudio.conversation import get_conversation_manager

            conv_mgr = get_conversation_manager()
            conv_id = f"game_{self.game_id}"
            conv = conv_mgr.get(conv_id)

            if conv is None:
                system = system_prompt or (
                    f"You are the game master for a {self.session_type} game. "
                    f"Player: {self.character_id}. "
                    f"Keep responses fun, engaging, and appropriate for the game. "
                    f"Track the game state and progress."
                )
                conv = conv_mgr.create(conv_id, system=system)

            resp = conv.send(user_message)
            text = (resp.content or "").strip()

            if resp.response_id:
                self.record_response_id(resp.response_id)

            if text:
                self.log_event(
                    "stateful_turn",
                    f"Turn {self._turn}: {text[:80]}",
                    {"text": text, "response_id": resp.response_id or ""},
                )

            return text

        except Exception as exc:
            logger.error("Stateful game turn failed: %s", exc)
            return None

    def undo_last_turn(self) -> Optional[str]:
        """Undo the last game turn by branching back to the previous response_id."""
        if len(self._response_ids) < 2:
            return None

        try:
            from engine.lmstudio.conversation import get_conversation_manager

            conv_mgr = get_conversation_manager()
            conv_id = f"game_{self.game_id}"
            conv = conv_mgr.get(conv_id)

            if conv is None:
                return None

            # Branch back to 2 turns ago
            branch_rid = self._response_ids[-2]
            resp = conv.send(
                "[Undo last turn — continue from here with a different approach]",
                previous_response_id_override=branch_rid,
            )

            text = (resp.content or "").strip()
            if resp.response_id:
                self._response_ids.pop()  # Remove the undone turn
                self.record_response_id(resp.response_id)

            return text

        except Exception as exc:
            logger.error("Game undo failed: %s", exc)
            return None

    # ── State helpers ─────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._gs().get(self.game_id, key, default)

    def set(self, key: str, value: Any) -> None:
        self._gs().set(self.game_id, key, value)

    def increment(self, key: str, amount: int = 1) -> int:
        return self._gs().increment(self.game_id, key, amount)

    def all_state(self) -> Dict:
        return self._gs().get_all(self.game_id)

    # ── Session lifecycle ─────────────────────────────────────────────

    def end(self, won: bool = False, final_note: str = "") -> None:
        """Close the session, sync stats, schedule post-game consequence."""
        self.ended_at = time.time()
        gs = self._gs()
        gs.set(self.game_id, "active",   False)
        gs.set(self.game_id, "ended_at", self.ended_at)
        gs.set(self.game_id, "won",      won)

        event_label = "game_won" if won else "game_ended"
        self.log_event(event_label, final_note or f"Game over (won={won})", {"won": won})
        self._emit(event_label, final_note or f"Session {self.game_id} ended", {"won": won})

        # Schedule post-game bedroom consequence
        if won:
            try:
                from engine.mcp.framework import get_framework
                get_framework().schedule_consequence(
                    scene_id=self.scene_id,
                    character_id=self.character_id,
                    consequence_type="stat_adjust",
                    params={"stat": "happiness", "delta": 15},
                    trigger_after_turns=1,
                    description=f"Post-{self.session_type} glow — mood lifts after winning",
                )
            except Exception as exc:
                logger.debug("MCPGameSession: post-game consequence failed: %s", exc)

        logger.info("MCPGameSession %s ended (won=%s)", self.game_id, won)

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> Dict:
        state = self.all_state()
        return {
            "game_id":        self.game_id,
            "type":           self.session_type,
            "character_id":   self.character_id,
            "scene_id":       self.scene_id,
            "active":         state.get("active", False),
            "turn":           self._turn,
            "score":          state.get("score", 0),
            "won":            state.get("won"),
            "started_at":     self.started_at,
            "ended_at":       self.ended_at,
            "recent_history": self.history_summary(5),
            "state":          state,
        }

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _gs():
        from engine.mcp.comms_framework import get_game_state
        return get_game_state()

    def _emit(self, event_type: str, description: str, data: Dict) -> None:
        """Broadcast via ActivityBus + AgentRouter."""
        # ActivityBus
        try:
            from engine.services.activity_bus import get_activity_bus
            bus = get_activity_bus()
            bus.publish(
                activity_type=f"game_{event_type}",
                description=description,
                agent_id=self.character_id,
                scene=self.scene_id,
                data={**data, "game_id": self.game_id, "game_type": self.session_type},
            )
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        # AgentRouter — character awareness
        try:
            from engine.mcp.comms_framework import get_router
            get_router().send(
                self.character_id,
                f"[GAME:{self.session_type.upper()}] {description}",
                sender_id=f"game_engine/{self.game_id}",
            )
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    def _apply_stat_sync(self, event_type: str) -> None:
        """Push stat deltas from this event into the scene SceneStateManager."""
        deltas = STAT_SYNC.get(self.session_type, {}).get(event_type)
        if not deltas:
            return
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            ssm.update_stats(self.character_id, **deltas)
            logger.debug(
                "MCPGameSession stat sync: %s %s event=%s deltas=%s",
                self.game_id, self.character_id, event_type, deltas,
            )
        except Exception as exc:
            logger.debug("MCPGameSession: stat sync failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  SESSION REGISTRY  ─ in-process store of all game sessions
# ══════════════════════════════════════════════════════════════════════

_REGISTRY: Dict[str, MCPGameSession] = {}
_REG_LOCK = threading.Lock()


def register_session(session: MCPGameSession) -> None:
    with _REG_LOCK:
        _REGISTRY[session.game_id] = session


def get_session(game_id: str) -> Optional[MCPGameSession]:
    with _REG_LOCK:
        return _REGISTRY.get(game_id)


def get_active_session(character_id: str) -> Optional[MCPGameSession]:
    """Return the active (not ended) session for a character, if any."""
    with _REG_LOCK:
        for session in reversed(list(_REGISTRY.values())):
            if session.character_id == character_id and session.get("active"):
                return session
    return None


def get_or_create_session(
    game_id:      str,
    session_type: str,
    character_id: str,
    scene_id:     str = "bedroom",
) -> MCPGameSession:
    """Return existing active session or create a fresh one."""
    with _REG_LOCK:
        existing = _REGISTRY.get(game_id)
        if existing and existing.get("active"):
            return existing
        session = MCPGameSession(game_id, session_type, character_id, scene_id)
        _REGISTRY[game_id] = session
    return session


def all_sessions() -> List[Dict]:
    """Return summary dicts for all sessions (active and ended)."""
    with _REG_LOCK:
        sessions = list(_REGISTRY.values())
    return [s.summary() for s in sessions]


def active_sessions() -> List[Dict]:
    """Return summary dicts for sessions that are still active."""
    with _REG_LOCK:
        sessions = [s for s in _REGISTRY.values() if s.get("active")]
    return [s.summary() for s in sessions]


# ══════════════════════════════════════════════════════════════════════
#  MCPGameNode  ─ MCPSceneNode subclass for game virtual sub-scenes
# ══════════════════════════════════════════════════════════════════════

class MCPGameNode:
    """
    Lightweight wrapper that makes an MCPGameSession visible as a scene node
    inside MCPFramework.  Created automatically; you don't instantiate this.

    Exposes ``inject_context(ctx)`` so the ``GameSessionInterceptor`` can pull
    the combined game state + history into a ResponseContext in one call.
    """

    def __init__(self, session: MCPGameSession) -> None:
        self.session   = session
        self.scene_id  = f"{session.scene_id}/{session.session_type}"

    def inject_context(self, ctx: Dict) -> str:
        """Build the system-prompt block to inject into a ResponseContext."""
        state   = self.session.all_state()
        history = self.session.history_summary(8)
        game_type = self.session.session_type.replace("_", " ").title()

        lines = [
            f"=== ACTIVE GAME: {game_type} ===",
            f"Game ID    : {self.session.game_id}",
            f"Turn       : {self.session._turn}",
            f"Score      : {state.get('score', 0)}",
            f"Character  : {self.session.character_id}",
        ]

        # Type-specific fields
        if self.session.session_type == "truth_or_dare":
            lines += [
                f"Current    : {state.get('current_type', 'N/A')} — {state.get('current_prompt', '')}",
                f"Rounds     : {state.get('round', 0)}",
            ]
        elif self.session.session_type == "mystery":
            lines += [
                f"Case       : {state.get('case_title', 'Unknown')}",
                f"Clues      : {state.get('clues_found', 0)} / {state.get('clues_total', 5)}",
                f"Accusation : {state.get('accusation', 'none yet')}",
            ]

        lines += [
            "",
            "--- Recent History ---",
            history,
            "=== END GAME CONTEXT ===",
        ]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
#  GameSessionInterceptor  (priority 35)
# ══════════════════════════════════════════════════════════════════════

class GameSessionInterceptor:
    """
    Priority-35 interceptor.

    Pre-call
    --------
    1. Scan active ``MCPGameSession`` registry for the current character.
    2. If found, build and inject the full game context block into system_prompt.
    3. Store the session on ``ctx["active_game_session"]`` for downstream use.

    Post-call
    ---------
    1. Look for shorthand game commands in the reply (e.g. ``[GAME_COMPLETE]``).
    2. Emit game events when detected.
    """
    name     = "game_session"
    priority = 35

    def pre_call(self, ctx) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return

        session = get_active_session(agent_id)
        if session is None:
            # Also check scene-level active games via raw GameState
            try:
                from engine.mcp.comms_framework import get_game_state
                gs = get_game_state()
                for gid in gs.all_games():
                    if gs.get(gid, "active") and gs.get(gid, "character_id") == agent_id:
                        session = get_session(gid)
                        break
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

        if session is None:
            return

        node  = MCPGameNode(session)
        block = node.inject_context(ctx)
        ctx["system_prompt"] = ctx.get("system_prompt", "") + f"\n\n{block}"
        ctx["active_game_session"] = session

        logger.debug(
            "GameSessionInterceptor: injected %s game context for %s",
            session.session_type, agent_id,
        )

    def post_call(self, ctx) -> None:
        session: Optional[MCPGameSession] = ctx.get("active_game_session")
        if session is None:
            return

        # Use pre-parsed data if available
        parsed = ctx.get("parsed")
        if parsed is None:
            from engine.agents.content_router import ContentRouter
            reply = ctx.get("reply", "")
            parsed = ContentRouter.parse_full(reply)
            ctx["parsed"] = parsed

        # Map game events to session event types
        event_map = {
            "GAME_COMPLETE":       ("round_complete", "Round completed"),
            "DARE_COMPLETE":       ("dare_completed", "Dare completed"),
            "TRUTH_COMPLETE":      ("truth_answered", "Truth answered"),
            "CLUE_FOUND":          ("clue_found",     "Clue discovered"),
            "GAME_WIN":            ("game_won",        "Game won"),
            "MYSTERY_SOLVED":      ("game_won",        "Mystery solved"),
            "TRUTH_REVEALED":      ("truth_answered", "Truth revealed"),
            "ROUND_END":           ("round_complete", "Round ended"),
            "CHALLENGE_COMPLETE":  ("round_complete", "Challenge completed"),
        }
        for event_name in parsed.game_events:
            key = event_name.upper()
            if key in event_map:
                event_type, description = event_map[key]
                session.log_event(event_type, description, actor="character")
                logger.debug(
                    "GameSessionInterceptor: detected event %s → %s",
                    key, event_type,
                )
