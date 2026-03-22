"""
CYBERSPACE — CosySim Hacking Minigame
======================================

Jack into NeonCity's network. Navigate a 5x5 grid of nodes, hack data vaults,
bypass firewalls, fight ICE (Intrusion Countermeasure Electronics), and steal
credits. The deeper you go, the better the loot — but the deadlier the ICE.

Game loop:
    1. Player jacks in → random 5x5 grid generated
    2. Each turn: move to adjacent node OR use a program
    3. Trace increases every turn (+5 base, +10 near trace nodes)
    4. At trace=100 → forced disconnect (keep partial loot)
    5. HP=0 → flatline (lose session, keep nothing)
    6. Reach core (4,4) and hack it → big score
    7. Exit via exit node → safe escape with loot

Version: v1.49.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.0 [2026-03-22] — Full hacking minigame: grid generation, movement,
                            programs, ICE combat, trace system, LLM narration,
                            REST API + Socket.IO events
    v1.0.0  [2026-03-22] — Initial scaffold via Creation Kit

Usage:
    python launcher.py cyberspace
    python launcher_game.py cyberspace
"""
from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene
from engine.port_registry import get_port
from engine.world.player_state import get_player_state

logger = logging.getLogger(__name__)

SCENE_ID = "cyberspace"
DEFAULT_PORT = get_port(SCENE_ID, 5573)


# ──── Node Types ──────────────────────────────────────────────────────────
# v1.49.0 [2026-03-22] — Network grid node definitions

NODE_TYPES: Dict[str, Dict[str, Any]] = {
    "data_vault": {
        "name": "Data Vault",
        "icon": "\U0001f4e6",       # 📦
        "loot_credits": 200,
        "ice_chance": 0.3,
        "description": "Encrypted data store. Hack it for credits.",
    },
    "firewall": {
        "name": "Firewall",
        "icon": "\U0001f525",       # 🔥
        "blocks_path": True,
        "hack_difficulty": 7,
        "description": "Blocks traversal. Must hack or exploit to pass.",
    },
    "ice_node": {
        "name": "ICE",
        "icon": "\u2744\ufe0f",     # ❄️
        "damage": 20,
        "type": "attack",
        "description": "Intrusion Countermeasure Electronics. Fights back.",
    },
    "trace_node": {
        "name": "Trace",
        "icon": "\U0001f441\ufe0f",  # 👁️
        "trace_speed": 10,
        "alarm_threshold": 100,
        "description": "Accelerates trace. Stay away or cloak up.",
    },
    "backdoor": {
        "name": "Backdoor",
        "icon": "\U0001f6aa",       # 🚪
        "shortcut_to": "random",
        "one_use": True,
        "description": "One-use shortcut to a random deeper node.",
    },
    "empty": {
        "name": "Empty Node",
        "icon": "\u00b7",           # ·
        "safe": True,
        "description": "Clean node. Safe to traverse.",
    },
    "exit": {
        "name": "Exit Jack",
        "icon": "\u2b06\ufe0f",     # ⬆️
        "escape": True,
        "description": "Jack-out point. Escape with your loot.",
    },
    "core": {
        "name": "Core Mainframe",
        "icon": "\U0001f48e",       # 💎
        "loot_credits": 2000,
        "ice_chance": 0.9,
        "boss": True,
        "description": "The prize. Massive payout. Near-certain ICE.",
    },
}


# ──── Programs ────────────────────────────────────────────────────────────
# v1.49.0 [2026-03-22] — Player abilities with cooldowns

PROGRAMS: Dict[str, Dict[str, Any]] = {
    "ping": {
        "name": "Ping",
        "description": "Reveal adjacent nodes",
        "cooldown": 0,
        "cost": 0,
    },
    "decrypt": {
        "name": "Decrypt",
        "description": "Hack a data vault or firewall",
        "cooldown": 2,
        "cost": 5,
    },
    "cloak": {
        "name": "Cloak",
        "description": "Reduce trace by 20 for 3 turns",
        "cooldown": 5,
        "cost": 10,
    },
    "attack": {
        "name": "Attack",
        "description": "Destroy an ICE node",
        "cooldown": 1,
        "cost": 15,
    },
    "exploit": {
        "name": "Exploit",
        "description": "Bypass a firewall without hacking",
        "cooldown": 4,
        "cost": 20,
    },
    "worm": {
        "name": "Worm",
        "description": "Auto-hack adjacent data vaults",
        "cooldown": 8,
        "cost": 30,
    },
}

# Starting programs every hacker begins with
STARTING_PROGRAMS = ["ping", "decrypt", "cloak"]

# Directions → (row_delta, col_delta)
DIRECTIONS: Dict[str, Tuple[int, int]] = {
    "north": (-1, 0),
    "south": (1, 0),
    "east": (0, 1),
    "west": (0, -1),
}

# Grid dimensions
GRID_ROWS = 5
GRID_COLS = 5

# LLM narration system prompt for cyberpunk atmosphere
# CONNECTS: _generate_narration() → LLM pipeline
NARRATION_SYSTEM_PROMPT = (
    "You are the CYBERSPACE narrator for a cyberpunk hacking game. "
    "Generate exactly 1-2 short sentences of cyberpunk narration for the event described. "
    "Use present tense. Be terse, atmospheric, and neon-noir. "
    "Reference circuits, data streams, ice shards, neon grids, and the digital void. "
    "Never break character. No markdown. No lists. Just raw narration."
)


# ──── Hacker State ────────────────────────────────────────────────────────
# v1.49.0 [2026-03-22] — Per-session player state dataclass

@dataclass
class HackerState:
    """Player state for a single cyberspace run.

    CONNECTS: CyberspaceScene._sessions, grid navigation, combat
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    hp: int = 100                   # Integrity — 0 = flatline (kicked)
    position: Tuple[int, int] = (0, 0)
    credits_stolen: int = 0
    data_stolen: List[str] = field(default_factory=list)
    trace_level: int = 0            # 0-100, 100 = traced and kicked
    programs: List[str] = field(default_factory=lambda: list(STARTING_PROGRAMS))
    turns: int = 0
    jacked_in: bool = True
    # Cooldown tracking: program_name → turns until available
    cooldowns: Dict[str, int] = field(default_factory=dict)
    # Cloak active turns remaining
    cloak_remaining: int = 0
    # Revealed nodes (set of (row, col) tuples for fog-of-war)
    revealed: List[Tuple[int, int]] = field(default_factory=list)
    # Whether the core has been hacked
    core_hacked: bool = False
    # Narration log
    narration_log: List[str] = field(default_factory=list)
    # Grid — stored as list of lists for JSON serialization
    grid: List[List[Dict[str, Any]]] = field(default_factory=list)
    # Used backdoors — set of (row, col) tuples
    used_backdoors: List[Tuple[int, int]] = field(default_factory=list)
    # Game result: "active", "escaped", "flatlined", "traced"
    result: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for Socket.IO / REST.

        Returns:
            Dict with all player state fields.
        """
        return {
            "session_id": self.session_id,
            "hp": self.hp,
            "position": list(self.position),
            "credits_stolen": self.credits_stolen,
            "data_stolen": self.data_stolen,
            "trace_level": self.trace_level,
            "programs": self.programs,
            "turns": self.turns,
            "jacked_in": self.jacked_in,
            "cooldowns": dict(self.cooldowns),
            "cloak_remaining": self.cloak_remaining,
            "revealed": [list(r) for r in self.revealed],
            "core_hacked": self.core_hacked,
            "narration_log": self.narration_log[-10:],  # Last 10 entries
            "grid": self.grid,
            "used_backdoors": [list(b) for b in self.used_backdoors],
            "result": self.result,
        }


# ──── Grid Generator ──────────────────────────────────────────────────────
# v1.49.0 [2026-03-22] — Procedural 5x5 grid with weighted node placement
# CONNECTS: CyberspaceScene._jack_in, HackerState.grid

def generate_grid() -> List[List[Dict[str, Any]]]:
    """Generate a randomized 5x5 network grid.

    Layout rules:
        - (0,0) is always 'empty' (safe start)
        - (4,4) is always 'core' (objective)
        - (0,1) or (1,0) gets an 'exit' node (escape route near start)
        - Remaining nodes are weighted random from the pool
        - At least 3 data_vaults, 2 firewalls, 2 ICE nodes, 1 trace node
        - 1 backdoor placed randomly in rows 1-3

    Returns:
        5x5 list of node dicts with type, hacked status, destroyed status.
    """
    grid: List[List[Dict[str, Any]]] = []

    # Initialize with empties
    for r in range(GRID_ROWS):
        row = []
        for c in range(GRID_COLS):
            row.append({
                "type": "empty",
                "hacked": False,
                "destroyed": False,
                "visible": False,
            })
        grid.append(row)

    # Fixed positions
    grid[0][0]["type"] = "empty"
    grid[0][0]["visible"] = True  # Start is always visible
    grid[4][4]["type"] = "core"

    # Exit node near start
    exit_pos = random.choice([(0, 1), (1, 0)])
    grid[exit_pos[0]][exit_pos[1]]["type"] = "exit"

    # Mandatory placements — collect non-fixed cells
    fixed = {(0, 0), (4, 4), exit_pos}
    free_cells = [
        (r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS)
        if (r, c) not in fixed
    ]
    random.shuffle(free_cells)

    # Place mandatory nodes
    mandatory = (
        ["data_vault"] * 3 +
        ["firewall"] * 2 +
        ["ice_node"] * 2 +
        ["trace_node"] * 1
    )

    # Place one backdoor in the mid-grid (rows 1-3)
    mid_cells = [(r, c) for r, c in free_cells if 1 <= r <= 3]
    if mid_cells:
        bd_pos = mid_cells[0]
        grid[bd_pos[0]][bd_pos[1]]["type"] = "backdoor"
        free_cells.remove(bd_pos)

    for i, node_type in enumerate(mandatory):
        if i < len(free_cells):
            pos = free_cells[i]
            grid[pos[0]][pos[1]]["type"] = node_type

    # Fill remaining with weighted random
    remaining_start = len(mandatory)
    filler_weights = {
        "empty": 40,
        "data_vault": 20,
        "ice_node": 15,
        "firewall": 10,
        "trace_node": 10,
        "backdoor": 5,
    }
    filler_types = list(filler_weights.keys())
    filler_probs = [filler_weights[t] for t in filler_types]

    for i in range(remaining_start, len(free_cells)):
        pos = free_cells[i]
        chosen = random.choices(filler_types, weights=filler_probs, k=1)[0]
        grid[pos[0]][pos[1]]["type"] = chosen

    return grid


# ──── Scene Class ─────────────────────────────────────────────────────────
# v1.49.0 [2026-03-22] — Full hacking minigame scene


class CyberspaceScene(FlaskScene):
    """CYBERSPACE — Hacking minigame scene.

    Navigate a 5x5 grid of network nodes, hack data vaults for credits,
    fight ICE, manage trace levels, and escape before you flatline.

    CONNECTS: FlaskScene, PlayerState, VirtualAgentManager (LLM narration)
    CALLED BY: launcher.py, launcher_game.py, TUI
    EMITS: cyberspace_state, ice_encounter, hack_result, trace_warning,
           flatline, escape, cyberspace_narration
    """

    SCENE_METADATA = {
        "name": SCENE_ID,
        "display_name": "CYBERSPACE",
        "port": DEFAULT_PORT,
        "type": "scene",
        "accent_color": "#00ff41",
        "accent_rgb": "0 255 65",
        "description": "Jack into the network. Hack nodes, steal data, dodge ICE. The digital frontier.",
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(host=host, port=port)
        # Per-socket session storage: sid → HackerState
        self._sessions: Dict[str, HackerState] = {}
        self._lock = threading.Lock()
        self._setup_routes()
        self._setup_socketio()

    # ──── REST API Routes ─────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Full REST API for cyberspace minigame
    # CONNECTS: CyberspaceScene._sessions, HackerState, grid logic
    # CALLED BY: Frontend fetch() calls

    def _setup_routes(self) -> None:
        """Register HTTP routes for CYBERSPACE."""

        @self.app.route("/")
        def index() -> str:
            return render_template("cyberspace.html")

        @self.app.route("/api/scene/state")
        def scene_state() -> Any:
            """Return current scene state snapshot."""
            return jsonify(self._build_state())

        # ── GET /api/cyberspace/state ──────────────────────────────────
        @self.app.route("/api/cyberspace/state")
        def api_cyberspace_state() -> Any:
            """Return current grid, player position, HP, trace, programs.

            Returns:
                JSON with hacker state or inactive status.
            """
            sid = request.args.get("sid", "")
            with self._lock:
                session = self._sessions.get(sid)
            if not session or not session.jacked_in:
                return jsonify({"jacked_in": False, "message": "Not jacked in."})
            return jsonify(self._build_cyberspace_state(session))

        # ── POST /api/cyberspace/jack_in ───────────────────────────────
        @self.app.route("/api/cyberspace/jack_in", methods=["POST"])
        def api_jack_in() -> Any:
            """Start a new cyberspace session (generate grid).

            Returns:
                JSON with new session state.
            """
            sid = (request.json or {}).get("sid", uuid.uuid4().hex[:12])
            session = self._jack_in(sid)
            return jsonify(self._build_cyberspace_state(session))

        # ── POST /api/cyberspace/move ──────────────────────────────────
        @self.app.route("/api/cyberspace/move", methods=["POST"])
        def api_move() -> Any:
            """Move to adjacent node.

            Args (JSON body):
                sid: Session ID.
                direction: "north", "south", "east", or "west".

            Returns:
                JSON with updated state and event results.
            """
            data = request.json or {}
            sid = data.get("sid", "")
            direction = data.get("direction", "")
            with self._lock:
                session = self._sessions.get(sid)
            if not session or not session.jacked_in:
                return jsonify({"error": "Not jacked in."}), 400
            result = self._handle_move(session, direction)
            return jsonify(result)

        # ── POST /api/cyberspace/use_program ───────────────────────────
        @self.app.route("/api/cyberspace/use_program", methods=["POST"])
        def api_use_program() -> Any:
            """Use a program (player ability).

            Args (JSON body):
                sid: Session ID.
                program: Program name.
                target: [row, col] target coordinates (optional for some programs).

            Returns:
                JSON with program result.
            """
            data = request.json or {}
            sid = data.get("sid", "")
            program = data.get("program", "")
            target = data.get("target")
            with self._lock:
                session = self._sessions.get(sid)
            if not session or not session.jacked_in:
                return jsonify({"error": "Not jacked in."}), 400
            result = self._handle_program(session, program, target)
            return jsonify(result)

        # ── POST /api/cyberspace/jack_out ──────────────────────────────
        @self.app.route("/api/cyberspace/jack_out", methods=["POST"])
        def api_jack_out() -> Any:
            """Safely exit cyberspace (keep loot).

            Args (JSON body):
                sid: Session ID.

            Returns:
                JSON with final loot summary.
            """
            data = request.json or {}
            sid = data.get("sid", "")
            with self._lock:
                session = self._sessions.get(sid)
            if not session or not session.jacked_in:
                return jsonify({"error": "Not jacked in."}), 400
            result = self._handle_jack_out(session)
            return jsonify(result)

    # ──── Socket.IO Handlers ──────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Full Socket.IO event handlers
    # CONNECTS: Frontend Socket.IO client
    # EMITS: cyberspace_state, ice_encounter, hack_result, trace_warning,
    #        flatline, escape, cyberspace_narration

    def _setup_socketio(self) -> None:
        """Register Socket.IO event handlers."""

        @self.socketio.on("connect")
        def on_connect() -> None:
            logger.info("%s: client connected (sid=%s)", SCENE_ID, request.sid)
            emit("scene_state", self._build_state())

        @self.socketio.on("get_state")
        def on_get_state() -> None:
            """Client requests full state refresh."""
            emit("scene_state", self._build_state())

        @self.socketio.on("cyberspace_jack_in")
        def on_jack_in() -> None:
            """Client jacks into cyberspace — new session."""
            sid = request.sid
            session = self._jack_in(sid)
            emit("cyberspace_state", self._build_cyberspace_state(session))
            narration = self._generate_narration(
                "Player jacks into the network. The grid materializes around them."
            )
            if narration:
                session.narration_log.append(narration)
                emit("cyberspace_narration", {"text": narration})

        @self.socketio.on("cyberspace_move")
        def on_move(data: Dict[str, Any]) -> None:
            """Client moves in the grid."""
            sid = request.sid
            with self._lock:
                session = self._sessions.get(sid)
            if not session or not session.jacked_in:
                emit("error", {"message": "Not jacked in."})
                return
            direction = (data or {}).get("direction", "")
            result = self._handle_move(session, direction)
            # The move handler emits all relevant events internally
            emit("cyberspace_state", self._build_cyberspace_state(session))
            # Forward event-specific emissions
            for event in result.get("events", []):
                emit(event["type"], event["data"])

        @self.socketio.on("cyberspace_use_program")
        def on_use_program(data: Dict[str, Any]) -> None:
            """Client uses a program."""
            sid = request.sid
            with self._lock:
                session = self._sessions.get(sid)
            if not session or not session.jacked_in:
                emit("error", {"message": "Not jacked in."})
                return
            program = (data or {}).get("program", "")
            target = (data or {}).get("target")
            result = self._handle_program(session, program, target)
            emit("cyberspace_state", self._build_cyberspace_state(session))
            for event in result.get("events", []):
                emit(event["type"], event["data"])

        @self.socketio.on("cyberspace_jack_out")
        def on_jack_out() -> None:
            """Client voluntarily jacks out."""
            sid = request.sid
            with self._lock:
                session = self._sessions.get(sid)
            if not session or not session.jacked_in:
                emit("error", {"message": "Not jacked in."})
                return
            result = self._handle_jack_out(session)
            emit("escape", result)
            emit("cyberspace_state", self._build_cyberspace_state(session))

        # Legacy generic action handler — routes to specific handlers
        @self.socketio.on("action")
        def on_action(data: Dict[str, Any]) -> None:
            """Handle a client action (legacy compatibility).

            Args:
                data: Dict with ``action`` (str) and optional payload keys.
            """
            action = (data or {}).get("action", "")
            logger.debug("%s: action '%s' payload=%s", SCENE_ID, action, data)
            if action == "jack_in":
                on_jack_in()
            elif action == "move":
                on_move(data)
            elif action == "use_program":
                on_use_program(data)
            elif action == "jack_out":
                on_jack_out()

    # ──── Jack In ─────────────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Session initialization and grid generation
    # CONNECTS: generate_grid(), HackerState
    # CALLED BY: on_jack_in, api_jack_in

    def _jack_in(self, sid: str) -> HackerState:
        """Create a new hacking session with a fresh grid.

        Args:
            sid: Socket/session ID.

        Returns:
            New HackerState with generated grid.
        """
        grid = generate_grid()
        session = HackerState(
            session_id=sid,
            grid=grid,
            revealed=[(0, 0)],  # Start node always revealed
        )
        # Reveal nodes adjacent to start
        for dr, dc in DIRECTIONS.values():
            nr, nc = dr, dc
            if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                session.revealed.append((nr, nc))

        with self._lock:
            self._sessions[sid] = session
        logger.info(
            "%s: jack_in session=%s — grid generated",
            SCENE_ID, sid,
        )
        return session

    # ──── Movement ────────────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Grid movement with node encounter resolution
    # CONNECTS: HackerState, NODE_TYPES, ICE combat, hack checks
    # CALLED BY: on_move, api_move
    # EMITS: ice_encounter, hack_result, trace_warning, flatline

    def _handle_move(self, session: HackerState, direction: str) -> Dict[str, Any]:
        """Process a player movement in the grid.

        Resolves node encounters: ICE combat, data vault hacking,
        trace node proximity, backdoor teleportation, firewall blocking.

        Args:
            session: Current hacker state.
            direction: "north", "south", "east", or "west".

        Returns:
            Dict with success status, events list, and updated state.
        """
        events: List[Dict[str, Any]] = []

        if direction not in DIRECTIONS:
            return {"success": False, "error": "Invalid direction.", "events": []}

        dr, dc = DIRECTIONS[direction]
        new_r = session.position[0] + dr
        new_c = session.position[1] + dc

        # Bounds check
        if not (0 <= new_r < GRID_ROWS and 0 <= new_c < GRID_COLS):
            return {"success": False, "error": "Edge of the network.", "events": []}

        node = session.grid[new_r][new_c]
        node_type = node["type"]
        node_def = NODE_TYPES.get(node_type, NODE_TYPES["empty"])

        # Firewall blocks movement unless hacked or destroyed
        if node_type == "firewall" and not node["hacked"] and not node["destroyed"]:
            return {
                "success": False,
                "error": "Firewall blocks your path. Use decrypt or exploit first.",
                "events": [],
            }

        # Move player
        session.position = (new_r, new_c)
        session.turns += 1

        # Reveal current + adjacent nodes
        self._reveal_around(session, new_r, new_c)

        # ── Node encounter resolution ─────────────────────────────

        # ICE node — takes damage
        if node_type == "ice_node" and not node["destroyed"]:
            damage = node_def.get("damage", 20)
            session.hp = max(0, session.hp - damage)
            ice_event = {
                "type": "ice_encounter",
                "data": {
                    "position": [new_r, new_c],
                    "damage": damage,
                    "hp_remaining": session.hp,
                    "ice_type": node_def.get("type", "attack"),
                },
            }
            events.append(ice_event)
            logger.info(
                "%s: ICE encounter at (%d,%d) — %d damage, HP=%d",
                SCENE_ID, new_r, new_c, damage, session.hp,
            )
            # LLM narration for ICE encounter
            narration = self._generate_narration(
                f"Player hit by ICE at node ({new_r},{new_c}). "
                f"Took {damage} damage. HP now {session.hp}."
            )
            if narration:
                session.narration_log.append(narration)
                events.append({
                    "type": "cyberspace_narration",
                    "data": {"text": narration},
                })

        # Data vault — auto-hack attempt on entry
        if node_type == "data_vault" and not node["hacked"]:
            hack_result = self._attempt_hack(session, new_r, new_c)
            events.append({
                "type": "hack_result",
                "data": hack_result,
            })

        # Backdoor — teleport to random deeper node (one-use)
        if node_type == "backdoor" and not node["hacked"]:
            bd_pos = (new_r, new_c)
            if bd_pos not in session.used_backdoors:
                dest = self._find_backdoor_destination(session, new_r, new_c)
                if dest:
                    session.used_backdoors.append(bd_pos)
                    node["hacked"] = True  # Mark used
                    session.position = dest
                    self._reveal_around(session, dest[0], dest[1])
                    events.append({
                        "type": "hack_result",
                        "data": {
                            "success": True,
                            "action": "backdoor",
                            "message": f"Backdoor teleported you to ({dest[0]},{dest[1]})!",
                            "new_position": list(dest),
                        },
                    })

        # Core node — big hack attempt
        if node_type == "core" and not node["hacked"]:
            # ICE chance on core
            if random.random() < node_def.get("ice_chance", 0.9):
                core_damage = 30
                session.hp = max(0, session.hp - core_damage)
                events.append({
                    "type": "ice_encounter",
                    "data": {
                        "position": [new_r, new_c],
                        "damage": core_damage,
                        "hp_remaining": session.hp,
                        "ice_type": "boss",
                        "message": "Core Mainframe ICE hits hard!",
                    },
                })
            # Still alive? Hack attempt
            if session.hp > 0:
                core_result = self._attempt_hack(session, new_r, new_c, difficulty=9)
                events.append({
                    "type": "hack_result",
                    "data": core_result,
                })
                if core_result["success"]:
                    session.core_hacked = True
                    narration = self._generate_narration(
                        "Player hacked the Core Mainframe! Massive data download. "
                        "2000 credits stolen. The system screams."
                    )
                    if narration:
                        session.narration_log.append(narration)
                        events.append({
                            "type": "cyberspace_narration",
                            "data": {"text": narration},
                        })

        # Exit node — option to escape (doesn't auto-escape, player must choose)
        if node_type == "exit":
            events.append({
                "type": "hack_result",
                "data": {
                    "success": True,
                    "action": "exit_available",
                    "message": "Exit jack point found. Use jack_out to escape with your loot.",
                },
            })

        # ── Turn-end effects ──────────────────────────────────────

        # Trace increases
        trace_events = self._process_trace(session)
        events.extend(trace_events)

        # Tick cooldowns
        self._tick_cooldowns(session)

        # Check flatline
        if session.hp <= 0:
            session.jacked_in = False
            session.result = "flatlined"
            events.append({
                "type": "flatline",
                "data": {
                    "message": "FLATLINE. Neural integrity zero. You're out.",
                    "credits_lost": session.credits_stolen,
                    "turns_survived": session.turns,
                },
            })
            # Flatlined = lose everything
            session.credits_stolen = 0
            session.data_stolen.clear()
            narration = self._generate_narration(
                "Player flatlined. Neural link severed. Lost everything."
            )
            if narration:
                session.narration_log.append(narration)
                events.append({
                    "type": "cyberspace_narration",
                    "data": {"text": narration},
                })
            logger.info("%s: FLATLINE session=%s turn=%d", SCENE_ID, session.session_id, session.turns)

        # Check trace limit
        if session.trace_level >= 100 and session.jacked_in:
            session.jacked_in = False
            session.result = "traced"
            events.append({
                "type": "flatline",
                "data": {
                    "message": "TRACED. Corporate security locked your signal. Forced disconnect.",
                    "credits_kept": session.credits_stolen,
                    "turns_survived": session.turns,
                },
            })
            # Traced = keep partial loot
            self._apply_loot(session)
            logger.info(
                "%s: TRACED session=%s turn=%d credits=%d",
                SCENE_ID, session.session_id, session.turns, session.credits_stolen,
            )

        return {
            "success": True,
            "events": events,
            "state": self._build_cyberspace_state(session),
        }

    # ──── Program Handler ─────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Program execution logic
    # CONNECTS: HackerState.programs, PROGRAMS, grid nodes
    # CALLED BY: on_use_program, api_use_program

    def _handle_program(
        self,
        session: HackerState,
        program: str,
        target: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Execute a player program.

        Args:
            session: Current hacker state.
            program: Program name from PROGRAMS.
            target: [row, col] target coords (required for targeted programs).

        Returns:
            Dict with success status, events, and description.
        """
        events: List[Dict[str, Any]] = []

        # Validate program
        if program not in PROGRAMS:
            return {"success": False, "error": f"Unknown program: {program}", "events": []}
        if program not in session.programs:
            return {"success": False, "error": f"You don't have {program}.", "events": []}

        prog_def = PROGRAMS[program]

        # Check cooldown
        if session.cooldowns.get(program, 0) > 0:
            return {
                "success": False,
                "error": f"{prog_def['name']} on cooldown ({session.cooldowns[program]} turns).",
                "events": [],
            }

        # Check HP cost (uses trace as "energy" cost)
        cost = prog_def.get("cost", 0)

        # Count as a turn
        session.turns += 1

        # Set cooldown
        cd = prog_def.get("cooldown", 0)
        if cd > 0:
            session.cooldowns[program] = cd

        # Add trace cost
        session.trace_level = min(100, session.trace_level + cost)

        # ── Program-specific logic ────────────────────────────────

        if program == "ping":
            # Reveal all adjacent nodes (including diagonals)
            r, c = session.position
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                        if (nr, nc) not in session.revealed:
                            session.revealed.append((nr, nc))
            events.append({
                "type": "hack_result",
                "data": {
                    "success": True,
                    "action": "ping",
                    "message": "PING sweep complete. Adjacent nodes revealed.",
                },
            })

        elif program == "decrypt":
            # Hack a specific node (data_vault or firewall)
            if not target or len(target) < 2:
                return {
                    "success": False,
                    "error": "Decrypt requires a target [row, col].",
                    "events": [],
                }
            tr, tc = int(target[0]), int(target[1])
            if not self._is_adjacent(session.position, (tr, tc)):
                return {
                    "success": False,
                    "error": "Target must be adjacent to your position.",
                    "events": [],
                }
            node = session.grid[tr][tc]
            if node["type"] not in ("data_vault", "firewall"):
                return {
                    "success": False,
                    "error": f"Cannot decrypt a {NODE_TYPES.get(node['type'], {}).get('name', 'node')}.",
                    "events": [],
                }
            if node["hacked"]:
                return {
                    "success": False,
                    "error": "Already hacked.",
                    "events": [],
                }
            hack_result = self._attempt_hack(session, tr, tc, difficulty=5)
            events.append({
                "type": "hack_result",
                "data": hack_result,
            })

        elif program == "cloak":
            # Reduce trace, grant cloak for 3 turns
            session.trace_level = max(0, session.trace_level - 20)
            session.cloak_remaining = 3
            events.append({
                "type": "hack_result",
                "data": {
                    "success": True,
                    "action": "cloak",
                    "message": "Cloak engaged. Trace reduced by 20. Stealth active for 3 turns.",
                    "trace_level": session.trace_level,
                    "cloak_remaining": session.cloak_remaining,
                },
            })

        elif program == "attack":
            # Destroy an ICE node
            if not target or len(target) < 2:
                return {
                    "success": False,
                    "error": "Attack requires a target [row, col].",
                    "events": [],
                }
            tr, tc = int(target[0]), int(target[1])
            if not self._is_adjacent(session.position, (tr, tc)):
                return {
                    "success": False,
                    "error": "Target must be adjacent to your position.",
                    "events": [],
                }
            node = session.grid[tr][tc]
            if node["type"] != "ice_node":
                return {
                    "success": False,
                    "error": "Attack can only target ICE nodes.",
                    "events": [],
                }
            if node["destroyed"]:
                return {
                    "success": False,
                    "error": "ICE already destroyed.",
                    "events": [],
                }
            # Attack always succeeds but costs trace
            node["destroyed"] = True
            events.append({
                "type": "hack_result",
                "data": {
                    "success": True,
                    "action": "attack",
                    "message": f"ICE node at ({tr},{tc}) destroyed.",
                    "position": [tr, tc],
                },
            })
            narration = self._generate_narration(
                f"Player destroyed ICE node at ({tr},{tc}). "
                "Shards of defensive code scatter into the void."
            )
            if narration:
                session.narration_log.append(narration)
                events.append({
                    "type": "cyberspace_narration",
                    "data": {"text": narration},
                })

        elif program == "exploit":
            # Bypass a firewall without hacking
            if not target or len(target) < 2:
                return {
                    "success": False,
                    "error": "Exploit requires a target [row, col].",
                    "events": [],
                }
            tr, tc = int(target[0]), int(target[1])
            if not self._is_adjacent(session.position, (tr, tc)):
                return {
                    "success": False,
                    "error": "Target must be adjacent to your position.",
                    "events": [],
                }
            node = session.grid[tr][tc]
            if node["type"] != "firewall":
                return {
                    "success": False,
                    "error": "Exploit can only target firewalls.",
                    "events": [],
                }
            if node["hacked"] or node["destroyed"]:
                return {
                    "success": False,
                    "error": "Firewall already bypassed.",
                    "events": [],
                }
            # Exploit always succeeds — marks as destroyed (passable)
            node["destroyed"] = True
            events.append({
                "type": "hack_result",
                "data": {
                    "success": True,
                    "action": "exploit",
                    "message": f"Firewall at ({tr},{tc}) exploited. Path clear.",
                    "position": [tr, tc],
                },
            })

        elif program == "worm":
            # Auto-hack all adjacent data vaults
            r, c = session.position
            hacked_count = 0
            total_credits = 0
            for dr, dc in DIRECTIONS.values():
                nr, nc = r + dr, c + dc
                if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                    adj_node = session.grid[nr][nc]
                    if adj_node["type"] == "data_vault" and not adj_node["hacked"]:
                        adj_node["hacked"] = True
                        loot = NODE_TYPES["data_vault"].get("loot_credits", 200)
                        session.credits_stolen += loot
                        total_credits += loot
                        data_id = f"WORM-{nr}{nc}-{uuid.uuid4().hex[:6]}"
                        session.data_stolen.append(data_id)
                        hacked_count += 1
            events.append({
                "type": "hack_result",
                "data": {
                    "success": hacked_count > 0,
                    "action": "worm",
                    "message": (
                        f"Worm deployed. {hacked_count} data vaults hacked. "
                        f"+{total_credits} credits."
                        if hacked_count > 0
                        else "Worm found no adjacent data vaults to hack."
                    ),
                    "hacked_count": hacked_count,
                    "credits_gained": total_credits,
                },
            })
            if hacked_count > 0:
                narration = self._generate_narration(
                    f"Worm program tears through {hacked_count} data vaults. "
                    f"{total_credits} credits siphoned into the runner's deck."
                )
                if narration:
                    session.narration_log.append(narration)
                    events.append({
                        "type": "cyberspace_narration",
                        "data": {"text": narration},
                    })

        # ── Turn-end effects ──────────────────────────────────────
        trace_events = self._process_trace(session)
        events.extend(trace_events)
        self._tick_cooldowns(session)

        # Check game-over conditions
        if session.hp <= 0:
            session.jacked_in = False
            session.result = "flatlined"
            session.credits_stolen = 0
            session.data_stolen.clear()
            events.append({
                "type": "flatline",
                "data": {
                    "message": "FLATLINE. Neural integrity zero.",
                    "credits_lost": 0,
                    "turns_survived": session.turns,
                },
            })

        if session.trace_level >= 100 and session.jacked_in:
            session.jacked_in = False
            session.result = "traced"
            self._apply_loot(session)
            events.append({
                "type": "flatline",
                "data": {
                    "message": "TRACED. Forced disconnect.",
                    "credits_kept": session.credits_stolen,
                    "turns_survived": session.turns,
                },
            })

        return {
            "success": True,
            "events": events,
            "state": self._build_cyberspace_state(session),
        }

    # ──── Jack Out ────────────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Safe exit with loot retention
    # CONNECTS: PlayerState.earn_credits, HackerState
    # CALLED BY: on_jack_out, api_jack_out
    # EMITS: escape

    def _handle_jack_out(self, session: HackerState) -> Dict[str, Any]:
        """Process a voluntary jack-out (safe escape).

        Applies stolen credits to the global player state.

        Args:
            session: Current hacker state.

        Returns:
            Dict with loot summary.
        """
        session.jacked_in = False
        session.result = "escaped"
        self._apply_loot(session)

        narration = self._generate_narration(
            f"Player jacks out with {session.credits_stolen} credits. "
            "The grid dissolves. Back to meatspace."
        )
        if narration:
            session.narration_log.append(narration)

        logger.info(
            "%s: JACK OUT session=%s turns=%d credits=%d data=%d",
            SCENE_ID, session.session_id, session.turns,
            session.credits_stolen, len(session.data_stolen),
        )

        return {
            "success": True,
            "message": "Jacked out safely. Loot secured.",
            "credits_earned": session.credits_stolen,
            "data_stolen": session.data_stolen,
            "turns": session.turns,
            "core_hacked": session.core_hacked,
            "narration": narration or "",
        }

    # ──── Hack Attempts ───────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Skill-check based hacking with ICE risk
    # CONNECTS: HackerState, NODE_TYPES, random skill check

    def _attempt_hack(
        self,
        session: HackerState,
        row: int,
        col: int,
        difficulty: int = 5,
    ) -> Dict[str, Any]:
        """Attempt to hack a node (data_vault, firewall, or core).

        Skill check: roll d10, must beat difficulty. Lower trace = small bonus.

        Args:
            session: Current hacker state.
            row: Target row.
            col: Target col.
            difficulty: Difficulty threshold (1-10).

        Returns:
            Dict with success, credits, and description.
        """
        node = session.grid[row][col]
        node_type = node["type"]
        node_def = NODE_TYPES.get(node_type, NODE_TYPES["empty"])

        # Use node-specific difficulty if defined
        if "hack_difficulty" in node_def:
            difficulty = node_def["hack_difficulty"]

        # Skill roll: d10 + stealth bonus
        roll = random.randint(1, 10)
        stealth_bonus = 1 if session.cloak_remaining > 0 else 0
        trace_bonus = 1 if session.trace_level < 30 else 0
        total = roll + stealth_bonus + trace_bonus

        success = total >= difficulty

        result: Dict[str, Any] = {
            "success": success,
            "action": "hack",
            "node_type": node_type,
            "position": [row, col],
            "roll": roll,
            "difficulty": difficulty,
            "total": total,
        }

        if success:
            node["hacked"] = True
            loot = node_def.get("loot_credits", 0)
            if loot > 0:
                session.credits_stolen += loot
                data_id = f"DATA-{row}{col}-{uuid.uuid4().hex[:6]}"
                session.data_stolen.append(data_id)
                result["credits_gained"] = loot
                result["data_id"] = data_id
            result["message"] = (
                f"HACK SUCCESS on {node_def['name']}! "
                f"Roll {roll}+{stealth_bonus + trace_bonus} vs {difficulty}. "
                + (f"+{loot} credits." if loot > 0 else "Access granted.")
            )

            # ICE triggered on hack?
            ice_chance = node_def.get("ice_chance", 0)
            if ice_chance > 0 and random.random() < ice_chance:
                ice_damage = 15
                session.hp = max(0, session.hp - ice_damage)
                result["ice_triggered"] = True
                result["ice_damage"] = ice_damage
                result["message"] += f" ICE retaliation! -{ice_damage} HP."

            # LLM narration for successful hack
            narration = self._generate_narration(
                f"Hacker breaches {node_def['name']} at ({row},{col}). "
                f"{'Massive data haul.' if loot >= 1000 else 'Data secured.'}"
            )
            if narration:
                session.narration_log.append(narration)
                result["narration"] = narration
        else:
            result["message"] = (
                f"HACK FAILED on {node_def['name']}. "
                f"Roll {roll}+{stealth_bonus + trace_bonus} vs {difficulty}. "
                "Security tightens."
            )
            # Failed hack increases trace
            session.trace_level = min(100, session.trace_level + 8)

        return result

    # ──── Trace System ────────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Escalating trace mechanic
    # CONNECTS: HackerState.trace_level, trace_node proximity
    # EMITS: trace_warning

    def _process_trace(self, session: HackerState) -> List[Dict[str, Any]]:
        """Process trace escalation for the current turn.

        Base trace: +5 per turn. +10 if adjacent to a trace node.
        Cloak reduces to +2 base. Emits trace_warning at 70+.

        Args:
            session: Current hacker state.

        Returns:
            List of trace-related events.
        """
        events: List[Dict[str, Any]] = []

        if not session.jacked_in:
            return events

        # Base trace increase
        base_trace = 2 if session.cloak_remaining > 0 else 5

        # Proximity to trace nodes
        r, c = session.position
        trace_proximity = 0
        for dr, dc in DIRECTIONS.values():
            nr, nc = r + dr, c + dc
            if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                adj_node = session.grid[nr][nc]
                if adj_node["type"] == "trace_node" and not adj_node["destroyed"]:
                    trace_proximity += NODE_TYPES["trace_node"].get("trace_speed", 10)

        # Also check current node
        current_node = session.grid[r][c]
        if current_node["type"] == "trace_node" and not current_node["destroyed"]:
            trace_proximity += NODE_TYPES["trace_node"].get("trace_speed", 10)

        total_trace = base_trace + trace_proximity
        session.trace_level = min(100, session.trace_level + total_trace)

        # Decrement cloak
        if session.cloak_remaining > 0:
            session.cloak_remaining -= 1

        # Warn at 70+
        if session.trace_level >= 70 and session.jacked_in:
            events.append({
                "type": "trace_warning",
                "data": {
                    "trace_level": session.trace_level,
                    "message": (
                        f"TRACE ALERT: {session.trace_level}%. "
                        "Corporate security is closing in!"
                    ),
                },
            })

        return events

    # ──── Cooldown Management ─────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Per-turn cooldown tick

    def _tick_cooldowns(self, session: HackerState) -> None:
        """Decrement all active cooldowns by 1 turn.

        Args:
            session: Current hacker state.
        """
        expired = []
        for prog, remaining in session.cooldowns.items():
            session.cooldowns[prog] = max(0, remaining - 1)
            if session.cooldowns[prog] == 0:
                expired.append(prog)
        for prog in expired:
            del session.cooldowns[prog]

    # ──── Utility Methods ─────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Grid helpers

    def _is_adjacent(
        self,
        pos_a: Tuple[int, int],
        pos_b: Tuple[int, int],
    ) -> bool:
        """Check if two grid positions are orthogonally adjacent.

        Args:
            pos_a: First position (row, col).
            pos_b: Second position (row, col).

        Returns:
            True if positions are exactly 1 step apart (no diagonals).
        """
        return abs(pos_a[0] - pos_b[0]) + abs(pos_a[1] - pos_b[1]) == 1

    def _reveal_around(self, session: HackerState, row: int, col: int) -> None:
        """Reveal a node and its orthogonal neighbors.

        Args:
            session: Current hacker state.
            row: Center row.
            col: Center col.
        """
        if (row, col) not in session.revealed:
            session.revealed.append((row, col))
        for dr, dc in DIRECTIONS.values():
            nr, nc = row + dr, col + dc
            if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                if (nr, nc) not in session.revealed:
                    session.revealed.append((nr, nc))

    def _find_backdoor_destination(
        self,
        session: HackerState,
        from_r: int,
        from_c: int,
    ) -> Optional[Tuple[int, int]]:
        """Find a random deeper node for backdoor teleportation.

        Selects a random empty or data_vault node in rows deeper than the current.

        Args:
            session: Current hacker state.
            from_r: Backdoor row.
            from_c: Backdoor col.

        Returns:
            (row, col) destination or None if no valid target found.
        """
        candidates = []
        for r in range(from_r + 1, GRID_ROWS):
            for c in range(GRID_COLS):
                node = session.grid[r][c]
                if node["type"] in ("empty", "data_vault") and not node["hacked"]:
                    candidates.append((r, c))
        if candidates:
            return random.choice(candidates)
        return None

    def _apply_loot(self, session: HackerState) -> None:
        """Apply stolen credits to the global PlayerState.

        CONNECTS: PlayerState.earn_credits

        Args:
            session: Current hacker state with credits_stolen.
        """
        if session.credits_stolen > 0:
            try:
                ps = get_player_state()
                ps.earn_credits(
                    session.credits_stolen,
                    reason=f"cyberspace_run_{session.session_id}",
                )
                logger.info(
                    "%s: applied %d credits to PlayerState",
                    SCENE_ID, session.credits_stolen,
                )
            except Exception as exc:
                logger.warning(
                    "%s: failed to apply loot to PlayerState: %s",
                    SCENE_ID, exc,
                )

    # ──── LLM Narration ───────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Cyberpunk narration via LLM inference
    # CONNECTS: VirtualAgentManager.infer_processed, InferenceRequest
    # CALLED BY: Movement encounters, hack results, jack-out

    def _generate_narration(self, event_description: str) -> Optional[str]:
        """Generate a brief cyberpunk narration for a game event via LLM.

        Falls back to None if LLM is unavailable (game continues without narration).

        Args:
            event_description: Plain text description of the event to narrate.

        Returns:
            1-2 sentence cyberpunk narration string, or None on failure.
        """
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest

            mgr = get_virtual_agent_manager()
            req = InferenceRequest(
                agent_id="cyberspace_narrator",
                messages=[
                    {"role": "system", "content": NARRATION_SYSTEM_PROMPT},
                    {"role": "user", "content": event_description},
                ],
                temperature=0.8,
                max_output_tokens=100,
                conversation_id=f"cyberspace_narration",
                store=False,
                metadata={"scene": SCENE_ID, "role": "narrator"},
            )
            proc = mgr.infer_processed(req)
            text = (proc.clean_text or proc.raw_text or "").strip()
            if text:
                logger.debug("%s: narration generated: %s", SCENE_ID, text[:80])
                return text
        except Exception as exc:
            # LLM narration is non-critical — game works without it
            logger.debug(
                "%s: LLM narration unavailable (non-critical): %s",
                SCENE_ID, exc,
            )
        return None

    # ──── State Builders ──────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — State serialization for client

    def _build_state(self) -> Dict[str, Any]:
        """Build a scene state snapshot for the client.

        CALLED BY: /api/scene/state, on_connect, get_state

        Returns:
            Dict with scene metadata and player state.
        """
        ps = get_player_state()
        return {
            "scene_id": SCENE_ID,
            "display_name": "CYBERSPACE",
            "player": {
                "credits": ps.credits,
                "health": ps.health,
                "energy": ps.energy,
                "reputation": ps.reputation,
            },
        }

    def _build_cyberspace_state(self, session: HackerState) -> Dict[str, Any]:
        """Build the full cyberspace game state for the client.

        Applies fog-of-war: only revealed nodes include their type/icon.
        Unrevealed nodes show as "unknown".

        CALLED BY: All Socket.IO handlers, REST endpoints

        Args:
            session: Current hacker state.

        Returns:
            Dict with grid (fog-of-war applied), player state, programs, etc.
        """
        # Build fog-of-war grid
        visible_grid: List[List[Dict[str, Any]]] = []
        for r in range(GRID_ROWS):
            row = []
            for c in range(GRID_COLS):
                if (r, c) in session.revealed:
                    node = session.grid[r][c]
                    node_def = NODE_TYPES.get(node["type"], NODE_TYPES["empty"])
                    row.append({
                        "type": node["type"],
                        "name": node_def["name"],
                        "icon": node_def["icon"],
                        "hacked": node["hacked"],
                        "destroyed": node["destroyed"],
                        "visible": True,
                        "description": node_def.get("description", ""),
                    })
                else:
                    row.append({
                        "type": "unknown",
                        "name": "???",
                        "icon": "?",
                        "hacked": False,
                        "destroyed": False,
                        "visible": False,
                        "description": "Unrevealed node.",
                    })
            visible_grid.append(row)

        # Build programs with cooldown info
        programs_info: List[Dict[str, Any]] = []
        for prog_name in session.programs:
            prog_def = PROGRAMS.get(prog_name, {})
            programs_info.append({
                "id": prog_name,
                "name": prog_def.get("name", prog_name),
                "description": prog_def.get("description", ""),
                "cooldown_max": prog_def.get("cooldown", 0),
                "cooldown_remaining": session.cooldowns.get(prog_name, 0),
                "cost": prog_def.get("cost", 0),
                "available": session.cooldowns.get(prog_name, 0) == 0,
            })

        # Available programs to unlock (not yet owned)
        unlockable = [
            {
                "id": k,
                "name": v["name"],
                "description": v["description"],
                "cost": v["cost"],
            }
            for k, v in PROGRAMS.items()
            if k not in session.programs
        ]

        return {
            "jacked_in": session.jacked_in,
            "session_id": session.session_id,
            "hp": session.hp,
            "max_hp": 100,
            "position": list(session.position),
            "credits_stolen": session.credits_stolen,
            "data_stolen": session.data_stolen,
            "trace_level": session.trace_level,
            "turns": session.turns,
            "cloak_remaining": session.cloak_remaining,
            "core_hacked": session.core_hacked,
            "result": session.result,
            "grid": visible_grid,
            "programs": programs_info,
            "unlockable_programs": unlockable,
            "narration_log": session.narration_log[-10:],
            "grid_size": {"rows": GRID_ROWS, "cols": GRID_COLS},
        }

    # ──── Lifecycle Hooks ─────────────────────────────────────────────
    # v1.49.0 [2026-03-22] — Scene lifecycle

    def on_before_serve(self) -> None:
        """Scene-specific setup before serving.

        CALLED BY: FlaskScene.start()
        """
        logger.info(
            "%s scene ready on port %d — hacking minigame online",
            "CYBERSPACE", DEFAULT_PORT,
        )
