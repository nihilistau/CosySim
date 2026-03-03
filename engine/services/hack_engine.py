"""Hacking engine for CosySim v0.81 "THE LIVING CITY".

Provides the core mechanics for the hacking mini-game:

- **Hackable targets** — any MCP node or scene device tagged as hackable,
  with a security level (1–5) and a list of possible rewards.
- **Grid puzzle** — 4×4 to 6×6 matrix of hex codes; the player must
  select a sequence of cells matching the target pattern before the
  trace timer fills. Generated deterministically from the target's seed.
- **Cyberdeck stats** — the equipped cyberdeck's ``crack_speed`` and
  ``trace_resist`` modifiers extend the timer and improve success chance.
- **Outcome logic** — success grants access/intel/credits; failure raises
  heat and optionally locks the target temporarily.

Usage::

    from engine.services.hack_engine import get_hack_engine

    engine = get_hack_engine()
    engine.register_target("lab_terminal", security_level=3, rewards=["intel:200"])
    puzzle = engine.generate_puzzle("lab_terminal")
    result = engine.evaluate_attempt("lab_terminal", puzzle["id"], solution)
"""
from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Module-level wrappers for testable patching ──────────────────────────────

def get_player_state():
    """Wrapper so tests can patch ``engine.services.hack_engine.get_player_state``."""
    from engine.world.player_state import get_player_state as _gps
    return _gps()


# ──── Constants ────────────────────────────────────────────────────────────────

# Hex codes pool used to populate the grid
_HEX_POOL = [
    "1C", "BD", "FF", "55", "7A", "E9", "2D", "C4",
    "A7", "BB", "3F", "88", "6E", "D0", "4B", "91",
    "00", "AB", "5C", "F3",
]

# Base timer per security level (seconds)
_BASE_TIMER: Dict[int, float] = {1: 18.0, 2: 15.0, 3: 12.0, 4: 9.0, 5: 7.0}

# Grid size per security level (rows × cols = square)
_GRID_SIZE: Dict[int, int] = {1: 4, 2: 4, 3: 5, 4: 5, 5: 6}

# Sequence length per security level
_SEQ_LEN: Dict[int, int] = {1: 3, 2: 4, 3: 4, 4: 5, 5: 5}

# Heat penalty on failed hack (% heat added)
_FAIL_HEAT_DELTA: Dict[int, int] = {1: 5, 2: 8, 3: 12, 4: 18, 5: 25}

# Trace resist per tick bonus (seconds per point)
_TRACE_RESIST_BONUS = 0.4

# Crack speed bonus (reduces sequence length by 1 per 3 points, min 2)
_CRACK_SPEED_PER_SEQ = 3

# Active puzzle TTL (seconds before auto-expire)
_PUZZLE_TTL = 300.0


# ──── Data Structures ──────────────────────────────────────────────────────────


@dataclass
class HackTarget:
    """Represents a hackable device or node in a scene."""

    target_id: str
    security_level: int = 1              # 1–5
    label: str = ""                      # Display name
    location: str = ""                   # Scene or area name
    rewards: List[str] = field(default_factory=list)  # "credits:500", "intel:key_access", "item:corp_keycard"
    locked_until: float = 0.0            # epoch timestamp; 0 = not locked
    hack_count: int = 0                  # successful hacks
    last_hacked: float = 0.0

    def is_locked(self) -> bool:
        return self.locked_until > time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "security_level": self.security_level,
            "label": self.label or self.target_id,
            "location": self.location,
            "rewards": list(self.rewards),
            "locked": self.is_locked(),
            "locked_until": self.locked_until if self.is_locked() else None,
            "hack_count": self.hack_count,
        }


@dataclass
class HackPuzzle:
    """A single generated hacking puzzle instance."""

    puzzle_id: str
    target_id: str
    grid: List[List[str]]                # rows × cols of hex codes
    solution: List[Tuple[int, int]]      # list of (row, col) cells in order
    time_limit: float                    # seconds
    created_at: float = field(default_factory=time.time)
    solved: bool = False
    failed: bool = False

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > _PUZZLE_TTL

    def to_dict(self) -> Dict[str, Any]:
        """Serialise puzzle for the frontend — solution is NOT included."""
        return {
            "puzzle_id": self.puzzle_id,
            "target_id": self.target_id,
            "grid": self.grid,
            "grid_size": len(self.grid),
            "sequence_length": len(self.solution),
            "time_limit": self.time_limit,
            "created_at": self.created_at,
            "solved": self.solved,
            "failed": self.failed,
        }


@dataclass
class HackResult:
    """Outcome of a hack attempt."""

    success: bool
    target_id: str
    puzzle_id: str
    rewards_granted: List[str] = field(default_factory=list)
    heat_delta: int = 0
    xp_delta: int = 0
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "target_id": self.target_id,
            "puzzle_id": self.puzzle_id,
            "rewards_granted": self.rewards_granted,
            "heat_delta": self.heat_delta,
            "xp_delta": self.xp_delta,
            "message": self.message,
        }


# ──── HackEngine ───────────────────────────────────────────────────────────────


class HackEngine:
    """Core hacking engine singleton.

    Thread-safe. Manages hackable targets, generates puzzles, and evaluates
    attempt solutions with cyberdeck/skill modifiers applied.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._targets: Dict[str, HackTarget] = {}
        self._puzzles: Dict[str, HackPuzzle] = {}   # puzzle_id → HackPuzzle
        self._seed_counter: int = 0
        self._register_builtin_targets()

    # ── Target Registration ─────────────────────────────────────────────────────

    def register_target(
        self,
        target_id: str,
        security_level: int = 1,
        label: str = "",
        location: str = "",
        rewards: Optional[List[str]] = None,
    ) -> HackTarget:
        """Register (or update) a hackable target.

        Args:
            target_id: Unique identifier.
            security_level: 1 (trivial) to 5 (military-grade).
            label: Human-readable display name.
            location: Scene/area where the target exists.
            rewards: List of reward strings e.g. ``["credits:500", "intel:faction_data"]``.

        Returns:
            The registered :class:`HackTarget`.
        """
        level = max(1, min(5, security_level))
        with self._lock:
            if target_id in self._targets:
                t = self._targets[target_id]
                t.security_level = level
                if label:
                    t.label = label
                if location:
                    t.location = location
                if rewards is not None:
                    t.rewards = list(rewards)
            else:
                self._targets[target_id] = HackTarget(
                    target_id=target_id,
                    security_level=level,
                    label=label or target_id,
                    location=location,
                    rewards=list(rewards or []),
                )
            return self._targets[target_id]

    def get_target(self, target_id: str) -> Optional[HackTarget]:
        with self._lock:
            return self._targets.get(target_id)

    def list_targets(self, location: str = "") -> List[Dict[str, Any]]:
        """List all registered targets, optionally filtered by location."""
        with self._lock:
            targets = list(self._targets.values())
        if location:
            targets = [t for t in targets if t.location == location]
        return [t.to_dict() for t in targets]

    # ── Puzzle Generation ───────────────────────────────────────────────────────

    def generate_puzzle(
        self,
        target_id: str,
        hacking_skill: int = 1,
        trace_resist: int = 0,
        crack_speed: int = 0,
    ) -> Dict[str, Any]:
        """Generate a new hacking puzzle for the given target.

        Cyberdeck modifiers are applied:
        - ``trace_resist`` extends the time limit by ``_TRACE_RESIST_BONUS`` seconds per point.
        - ``crack_speed`` reduces the required sequence length by 1 per ``_CRACK_SPEED_PER_SEQ`` points.

        Args:
            target_id: The target to hack.
            hacking_skill: Player hacking skill level (1–5). Higher = slightly longer timer.
            trace_resist: Cyberdeck trace resist modifier.
            crack_speed: Cyberdeck crack speed modifier.

        Returns:
            Puzzle dict (no solution field) or ``{"error": str}`` if unavailable.
        """
        with self._lock:
            target = self._targets.get(target_id)
        if target is None:
            return {"error": f"Unknown target: {target_id}"}
        if target.is_locked():
            return {"error": "Target is locked", "locked_until": target.locked_until}

        level = target.security_level
        size = _GRID_SIZE[level]
        base_seq = _SEQ_LEN[level]

        # Apply crack speed (reduce sequence, min 2)
        crack_bonus = crack_speed // _CRACK_SPEED_PER_SEQ
        seq_len = max(2, base_seq - crack_bonus)

        # Apply trace resist and skill bonus to timer
        timer = _BASE_TIMER[level]
        timer += trace_resist * _TRACE_RESIST_BONUS
        timer += (hacking_skill - 1) * 0.5   # small skill bonus

        # Deterministic seed from target_id + counter so puzzles vary
        with self._lock:
            self._seed_counter += 1
            seed_val = self._seed_counter
        seed_str = f"{target_id}:{seed_val}"
        rng = random.Random(int(hashlib.md5(seed_str.encode()).hexdigest(), 16))

        # Build grid
        grid: List[List[str]] = [
            [rng.choice(_HEX_POOL) for _ in range(size)]
            for _ in range(size)
        ]

        # Build solution (random walk through the grid, no duplicate cells)
        all_cells = [(r, c) for r in range(size) for c in range(size)]
        solution_cells = rng.sample(all_cells, seq_len)

        # Stamp the required hex sequence into the grid (so solution is valid)
        solution_codes = [rng.choice(_HEX_POOL) for _ in range(seq_len)]
        for (r, c), code in zip(solution_cells, solution_codes):
            grid[r][c] = code

        puzzle_id = hashlib.sha1(f"{target_id}:{seed_val}:{time.time()}".encode()).hexdigest()[:12]

        puzzle = HackPuzzle(
            puzzle_id=puzzle_id,
            target_id=target_id,
            grid=grid,
            solution=solution_cells,
            time_limit=round(timer, 1),
        )
        with self._lock:
            # Clean up expired puzzles lazily
            self._puzzles = {
                pid: p for pid, p in self._puzzles.items()
                if not p.is_expired()
            }
            self._puzzles[puzzle_id] = puzzle

        result = puzzle.to_dict()
        # Include the solution sequence codes so the frontend can highlight the pattern
        result["sequence_codes"] = solution_codes
        return result

    # ── Attempt Evaluation ──────────────────────────────────────────────────────

    def evaluate_attempt(
        self,
        puzzle_id: str,
        submitted: List[Tuple[int, int]],
        elapsed_seconds: float = 0.0,
    ) -> HackResult:
        """Evaluate a player's submitted solution for a puzzle.

        The solution is correct if the submitted cells match the puzzle's
        solution sequence in order. A timed-out submission is auto-failed.

        Args:
            puzzle_id: The puzzle being solved.
            submitted: List of ``(row, col)`` tuples in selection order.
            elapsed_seconds: Time elapsed since puzzle generation. If > ``time_limit``, fail.

        Returns:
            :class:`HackResult` with outcome, rewards, and heat delta.
        """
        with self._lock:
            puzzle = self._puzzles.get(puzzle_id)

        if puzzle is None:
            return HackResult(
                success=False, target_id="", puzzle_id=puzzle_id,
                message="Puzzle not found or expired."
            )
        if puzzle.solved or puzzle.failed:
            return HackResult(
                success=puzzle.solved, target_id=puzzle.target_id, puzzle_id=puzzle_id,
                message="Puzzle already completed."
            )
        if elapsed_seconds > puzzle.time_limit or puzzle.is_expired():
            puzzle.failed = True
            return self._apply_failure(puzzle, reason="Trace complete — connection terminated.")

        # Check solution
        submitted_tuples = [tuple(cell) for cell in submitted]
        correct = list(map(tuple, puzzle.solution))
        if submitted_tuples == correct:
            puzzle.solved = True
            return self._apply_success(puzzle)
        else:
            puzzle.failed = True
            return self._apply_failure(puzzle, reason="Sequence mismatch — trace triggered.")

    def _apply_success(self, puzzle: HackPuzzle) -> HackResult:
        """Apply success outcome: grant rewards, award XP."""
        with self._lock:
            target = self._targets.get(puzzle.target_id)

        rewards_granted: List[str] = []
        heat_delta = 0
        xp_delta = 0

        if target:
            target.hack_count += 1
            target.last_hacked = time.time()
            rewards_granted = list(target.rewards)
            xp_delta = target.security_level * 20

            # Apply credit rewards to PlayerState
            try:
                ps = get_player_state()
                for reward in rewards_granted:
                    if reward.startswith("credits:"):
                        amount = int(reward.split(":")[1])
                        ps.earn_credits(amount, reason=f"hack:{target.target_id}")
                    elif reward.startswith("intel:"):
                        pass  # Callers can handle intel grants
                ps.improve_skill("hacking", amount=1)  # Tiny skill XP
            except Exception as exc:
                logger.warning("HackEngine: failed to apply PlayerState rewards: %s", exc)

        logger.info("HackEngine: successful hack on %s | rewards=%s", puzzle.target_id, rewards_granted)
        return HackResult(
            success=True,
            target_id=puzzle.target_id,
            puzzle_id=puzzle.puzzle_id,
            rewards_granted=rewards_granted,
            heat_delta=heat_delta,
            xp_delta=xp_delta,
            message="ACCESS GRANTED",
        )

    def _apply_failure(self, puzzle: HackPuzzle, reason: str = "Hack failed.") -> HackResult:
        """Apply failure outcome: raise heat, optionally lock target."""
        with self._lock:
            target = self._targets.get(puzzle.target_id)

        heat_delta = 0
        if target:
            level = target.security_level
            heat_delta = _FAIL_HEAT_DELTA[level]
            # Lock target for security_level * 60 seconds
            lock_duration = level * 60.0
            target.locked_until = time.time() + lock_duration

            try:
                ps = get_player_state()
                ps.adjust_heat(heat_delta, reason=f"hack_fail:{target.target_id}")
            except Exception as exc:
                logger.warning("HackEngine: failed to apply heat on failure: %s", exc)

        logger.info("HackEngine: failed hack on %s | heat+%d", puzzle.target_id, heat_delta)
        return HackResult(
            success=False,
            target_id=puzzle.target_id,
            puzzle_id=puzzle.puzzle_id,
            heat_delta=heat_delta,
            message=reason,
        )

    # ── Convenience ─────────────────────────────────────────────────────────────

    def reset_target_lock(self, target_id: str) -> bool:
        """Remove the cooldown lock on a target (admin/debug use)."""
        with self._lock:
            t = self._targets.get(target_id)
            if t:
                t.locked_until = 0.0
                return True
        return False

    # ── Built-in Targets ────────────────────────────────────────────────────────

    def _register_builtin_targets(self) -> None:
        """Register default hackable devices present in CosySim scenes."""
        defaults = [
            # (target_id, level, label, location, rewards)
            ("signal_comms_tower",   3, "Comms Tower",          "SIGNAL",           ["credits:800",  "intel:signal_freq"]),
            ("penthouse_vault_door", 4, "Vault Door Access",    "THE PENTHOUSE",    ["credits:2000", "item:corp_keycard"]),
            ("velvet_atm",           2, "ATM Terminal",         "THE VELVET PIT",   ["credits:500"]),
            ("anchor_security_cam",  1, "Security Camera",     "THE RUSTY ANCHOR", ["intel:anchor_patrol"]),
            ("club_noir_vip_list",   2, "VIP Access Terminal",  "CLUB NOIR",        ["intel:vip_list", "credits:200"]),
            ("obscura_server",       4, "Hidden Server Rack",   "THE OBSCURA",      ["intel:faction_data", "credits:1500"]),
            ("colosseum_bet_fix",    3, "Betting System",       "THE COLOSSEUM",    ["credits:1200"]),
            ("throne_corp_console",  5, "Corp Command Console", "THE SHATTERED THRONE", ["intel:throne_blueprint", "credits:3000"]),
            ("neoncity_adboard",     1, "Advertising Board",    "NEON CITY",        ["credits:100"]),
            ("lab_mainframe",        5, "Lab Mainframe",        "THE LAB",          ["intel:experiment_data", "credits:2500"]),
            ("score_vault",          4, "Score Vault",          "THE SCORE",        ["credits:1800", "item:ghost_net_token"]),
            ("cmd_uplink",           3, "Command Uplink",       "Command Center",   ["intel:orders", "credits:600"]),
            ("arcade_high_score",    1, "High Score Board",     "THE ARCADE",       ["credits:50",  "intel:player_dossier"]),
            ("grid_node_alpha",      3, "Grid Node Alpha",      "THE GRID",         ["intel:grid_topology", "credits:900"]),
            ("briefing_intel_feed",  2, "Intel Feed Terminal",  "THE BRIEFING ROOM", ["intel:mission_brief"]),
        ]
        for target_id, level, label, location, rewards in defaults:
            self.register_target(target_id, security_level=level, label=label,
                                 location=location, rewards=rewards)


# ──── Singleton ────────────────────────────────────────────────────────────────

_HACK_ENGINE: Optional[HackEngine] = None
_HACK_ENGINE_LOCK = threading.Lock()


def get_hack_engine() -> HackEngine:
    """Return the HackEngine singleton."""
    global _HACK_ENGINE
    if _HACK_ENGINE is None:
        with _HACK_ENGINE_LOCK:
            if _HACK_ENGINE is None:
                _HACK_ENGINE = HackEngine()
    return _HACK_ENGINE


def reset_hack_engine() -> None:
    """Reset the singleton (test use only)."""
    global _HACK_ENGINE
    with _HACK_ENGINE_LOCK:
        _HACK_ENGINE = None
