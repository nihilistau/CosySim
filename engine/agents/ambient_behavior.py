"""
AmbientBehavior — cheap, scripted idle micro-behaviors between LLM agent ticks.

The :class:`~engine.agents.agent_loop.AgentLoop` runs *expensive* LLM-driven
decisions on a slow cadence (``scenes.penthouse.agent_loop_interval`` seconds).
Between those ticks the characters are otherwise frozen.  This module adds a
*cheap*, scripted layer that runs much more frequently and emits small idle
motions — shift weight / fidget, glance toward another present character or the
player, a brief expression / mood flicker, or an occasional reposition to a
nearby location — so the scene feels naturally alive WITHOUT hammering the
local model.

Two pieces live here:

  * :func:`select_ambient_action` — a **pure** function (no I/O, no sockets).
    Given a character's mood/stat vector and player-presence flags, it returns
    a single scripted micro-action dict (or ``None`` when ambient is disabled,
    the character is in an active pose / busy, or the dice say "stay still").
    This is the unit-testable core.

  * :class:`AmbientLoop` — a small background tick loop that, for each eligible
    character, calls :func:`select_ambient_action` and emits the SAME socket
    events the existing animation path uses (``set_animation`` /
    ``set_expression``).  Occasionally (low probability, gated by config) it
    instead requests a single LLM ambient line through the existing agent
    callback path — but the default is scripted, so the model is not spammed.

All cadences / weights / probabilities are config-driven under the
``penthouse.ambient.*`` namespace (see :func:`get_ambient_config`).

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Initial: cheap config-driven ambient micro-behaviors
                            (scripted by default; rare LLM line via agent path).
"""
from __future__ import annotations

import logging
import random
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Scripted vocabularies ───────────────────────────────────────────────
# These map onto the EXISTING frontend animation states / expression presets
# (see content/scenes/penthouse/penthouse_skills.py VALID_ANIM_STATES /
# VALID_EXPRESSIONS and penthouse_anim.js).  We deliberately stick to small,
# non-committal idle states so an ambient flicker never reads as a deliberate
# move or pose.

# Small idle body micro-states (cheap, low-commitment animation states).
FIDGET_STATES: List[str] = [
    "idle", "stretch", "shrug", "hair_flip", "arms_crossed",
    "hands_behind", "lean", "primp", "phone", "gaze",
]

# "Glance" reads as a brief look/gaze toward another present character or the
# player — rendered with the gaze state plus a curious/playful flicker.
GLANCE_STATES: List[str] = ["gaze", "flirt", "beckon"]

# Brief, low-intensity expression flickers (subset of VALID_EXPRESSIONS that
# read as a passing mood, never a committed emotional state).
FLICKER_EXPRESSIONS: List[str] = [
    "neutral", "happy", "playful", "bored", "shy", "seductive", "sleepy",
]

# Default ambient micro-action kinds and their *base* relative weights.
DEFAULT_ACTION_WEIGHTS: Dict[str, float] = {
    "fidget": 4.0,      # shift weight / small idle motion
    "glance": 3.0,      # look toward another character or the player
    "expression": 3.0,  # brief mood flicker
    "reposition": 1.0,  # occasional drift to a nearby location
}


# ── Config ──────────────────────────────────────────────────────────────

# Sane defaults — used when config keys are absent so the layer works
# out-of-the-box.  All read via get_config().get("penthouse.ambient.<k>", ...).
_AMBIENT_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "tick_interval": 3.0,          # seconds between cheap ambient ticks
    "action_chance": 0.6,          # P(a given eligible character acts this tick)
    "max_per_tick": 2,             # cap characters touched per tick (cheap fan-out)
    "llm_line_chance": 0.04,       # P(ambient action escalates to an LLM line)
    "reposition_chance": 0.15,     # extra gate on the (already rare) reposition kind
    "player_present_boost": 1.6,   # weight multiplier for player-facing glances
    "action_weights": dict(DEFAULT_ACTION_WEIGHTS),
}


def get_ambient_config() -> Dict[str, Any]:
    """Read the ``penthouse.ambient.*`` config block, applying sane defaults.

    Returns a plain dict so callers never have to remember a key name twice.
    Reads via :func:`engine.config.get_config` so deployments can override any
    value in ``config/default.yaml`` (or env overrides) under ``penthouse:
    ambient:``.
    """
    try:
        from engine.config import get_config
        cfg = get_config()
    except Exception:  # pragma: no cover - config always present in practice
        return dict(_AMBIENT_DEFAULTS)

    def _get(key: str, default: Any) -> Any:
        return cfg.get(f"penthouse.ambient.{key}", default)

    weights = _get("action_weights", None)
    if not isinstance(weights, dict) or not weights:
        weights = dict(DEFAULT_ACTION_WEIGHTS)

    return {
        "enabled": bool(_get("enabled", _AMBIENT_DEFAULTS["enabled"])),
        "tick_interval": float(_get("tick_interval", _AMBIENT_DEFAULTS["tick_interval"])),
        "action_chance": float(_get("action_chance", _AMBIENT_DEFAULTS["action_chance"])),
        "max_per_tick": int(_get("max_per_tick", _AMBIENT_DEFAULTS["max_per_tick"])),
        "llm_line_chance": float(_get("llm_line_chance", _AMBIENT_DEFAULTS["llm_line_chance"])),
        "reposition_chance": float(_get("reposition_chance", _AMBIENT_DEFAULTS["reposition_chance"])),
        "player_present_boost": float(
            _get("player_present_boost", _AMBIENT_DEFAULTS["player_present_boost"])
        ),
        "action_weights": {str(k): float(v) for k, v in weights.items()},
    }


# ── Pure selector ───────────────────────────────────────────────────────

def select_ambient_action(
    *,
    stats: Optional[Dict[str, float]] = None,
    player_present: bool = False,
    player_active: bool = False,
    has_other_characters: bool = False,
    nearby_locations: Optional[List[str]] = None,
    in_active_pose: bool = False,
    is_busy: bool = False,
    config: Optional[Dict[str, Any]] = None,
    rng: Optional[random.Random] = None,
) -> Optional[Dict[str, Any]]:
    """Choose a single cheap, scripted ambient micro-action for one character.

    This is a **pure** function: no sockets, no LLM, no global state (aside from
    reading config defaults when ``config`` is not supplied).  It is the
    unit-testable heart of the ambient layer.

    Weighting honours the character's neurochemistry / mood (the 0-100 stat
    vector — ``arousal``, ``happiness``, ``tiredness``, ``dominance``, …) and
    whether the player is present / active, so an aroused character glances and
    flirts more, a tired one mostly stays still, and everyone looks toward the
    player more when they are around.

    Guards (return ``None``):
        * ambient layer disabled in config (``enabled=False``),
        * the character is in an active paired pose (``in_active_pose``) — we
          must NOT override a deliberate Task-3 pose,
        * the character is otherwise busy (``is_busy``) — a deliberate move /
          interaction is in progress,
        * the per-character dice (``action_chance``) say "stay still" this tick.

    Args:
        stats: The character's stat vector (0-100), e.g. AgentStats.to_dict().
        player_present: True when a client/director is in the scene.
        player_active: True when the player recently interacted (chat/director).
        has_other_characters: True when >=1 other character is present.
        nearby_locations: Candidate location *names* to drift toward (excludes
            the character's current location). Empty/None disables reposition.
        in_active_pose: True when a paired/sex pose is currently playing.
        is_busy: True when a deliberate move/interaction is in progress.
        config: Optional pre-read ambient config (see :func:`get_ambient_config`).
        rng: Optional ``random.Random`` for deterministic tests.

    Returns:
        A micro-action dict, or ``None``. Shape::

            {"kind": "fidget"|"glance"|"expression"|"reposition",
             "channel": "animation"|"expression"|"move",
             "state": "<anim state>",        # animation/move kinds
             "expression": "<preset>",       # expression kind
             "target": "<location name>",    # reposition kind
             "ambient": True}                 # marker — never an LLM action
    """
    cfg = config if config is not None else get_ambient_config()
    if not cfg.get("enabled", True):
        return None
    # Never fight a deliberate pose (Task 3) or an in-progress action.
    if in_active_pose or is_busy:
        return None

    r = rng or random
    stats = stats or {}

    # Per-character "act this tick?" gate keeps the layer cheap and unspammy.
    if r.random() > float(cfg.get("action_chance", 0.6)):
        return None

    arousal = float(stats.get("arousal", 20.0))
    happiness = float(stats.get("happiness", 60.0))
    tiredness = float(stats.get("tiredness", 20.0))
    dominance = float(stats.get("dominance", 50.0))

    base_weights = cfg.get("action_weights") or DEFAULT_ACTION_WEIGHTS
    weights: Dict[str, float] = {
        "fidget": float(base_weights.get("fidget", 4.0)),
        "glance": float(base_weights.get("glance", 3.0)),
        "expression": float(base_weights.get("expression", 3.0)),
        "reposition": float(base_weights.get("reposition", 1.0)),
    }

    # ── Mood / presence weighting ──
    # Aroused or happy characters glance/express more (alive, engaged).
    mood_gain = 1.0 + (arousal / 100.0) + (max(0.0, happiness - 50.0) / 100.0)
    weights["glance"] *= mood_gain
    weights["expression"] *= mood_gain

    # Player presence draws the eye — characters look toward the player more.
    if player_present:
        boost = float(cfg.get("player_present_boost", 1.6))
        weights["glance"] *= boost
        if player_active:
            weights["glance"] *= 1.25

    # Tired characters mostly just stand still (fidget over big motion).
    tired_factor = max(0.2, 1.0 - (tiredness / 150.0))
    weights["reposition"] *= tired_factor
    weights["glance"] *= (0.5 + 0.5 * tired_factor)
    weights["fidget"] *= (1.0 + (tiredness / 200.0))  # tired => small shifts

    # No one to glance at and no player around → glancing makes no sense.
    if not has_other_characters and not player_present:
        weights["glance"] = 0.0

    # Reposition only when there is somewhere to go AND the rare gate passes.
    candidates = list(nearby_locations or [])
    if not candidates or r.random() > float(cfg.get("reposition_chance", 0.15)):
        weights["reposition"] = 0.0

    kinds = [k for k, w in weights.items() if w > 0.0]
    if not kinds:
        return None
    kind = r.choices(kinds, weights=[weights[k] for k in kinds], k=1)[0]

    if kind == "fidget":
        return {
            "kind": "fidget",
            "channel": "animation",
            "state": r.choice(FIDGET_STATES),
            "ambient": True,
        }
    if kind == "glance":
        return {
            "kind": "glance",
            "channel": "animation",
            "state": r.choice(GLANCE_STATES),
            "ambient": True,
        }
    if kind == "expression":
        # Dominant characters skew toward seductive/playful flickers.
        pool = list(FLICKER_EXPRESSIONS)
        if dominance > 65:
            pool = pool + ["seductive", "playful"]
        return {
            "kind": "expression",
            "channel": "expression",
            "expression": r.choice(pool),
            "ambient": True,
        }
    # reposition
    return {
        "kind": "reposition",
        "channel": "move",
        "target": r.choice(candidates),
        "state": "walk",
        "ambient": True,
    }


# ── Background loop ──────────────────────────────────────────────────────

class AmbientLoop:
    """Cheap scripted ambient tick loop for a scene.

    Runs on a fast cadence (``penthouse.ambient.tick_interval``) and, for a few
    eligible characters per tick, emits scripted micro-actions through the
    provider callbacks supplied by the scene.  It NEVER calls the LLM itself;
    on a rare dice (``llm_line_chance``) it instead asks the scene to enqueue a
    single ambient line via the existing agent path.

    The loop is intentionally decoupled from the scene via small callables so it
    stays unit-testable and reuses the scene's existing emit helpers:

    Args:
        is_active: ``() -> bool`` — True only while it is safe to run (agent
            loop running AND at least one client connected). The loop stops
            emitting the instant this returns False.
        list_characters: ``() -> list[str]`` — ids of present characters.
        get_state: ``(cid) -> dict`` — per-character snapshot with keys:
            ``stats`` (dict), ``in_active_pose`` (bool), ``is_busy`` (bool),
            ``nearby_locations`` (list[str]).
        emit_action: ``(cid, action) -> None`` — render a scripted micro-action
            via the scene's existing animation/expression/move emit path.
        player_state: ``() -> tuple[bool, bool]`` — (player_present, player_active).
        request_llm_line: optional ``(cid) -> None`` — enqueue a single ambient
            line via the existing agent path. If None, the LLM escalation is
            skipped entirely (pure scripted mode).
    """

    def __init__(
        self,
        *,
        is_active: Callable[[], bool],
        list_characters: Callable[[], List[str]],
        get_state: Callable[[str], Dict[str, Any]],
        emit_action: Callable[[str, Dict[str, Any]], None],
        player_state: Callable[[], Any],
        request_llm_line: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._is_active = is_active
        self._list_characters = list_characters
        self._get_state = get_state
        self._emit_action = emit_action
        self._player_state = player_state
        self._request_llm_line = request_llm_line

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._tick_count = 0
        self._llm_calls = 0  # for observability / proof of low model use

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def llm_calls(self) -> int:
        return self._llm_calls

    def start(self) -> None:
        """Start the background ambient loop (no-op if disabled or running)."""
        if self._running:
            return
        cfg = get_ambient_config()
        if not cfg.get("enabled", True):
            logger.info("[penthouse] ambient layer disabled in config (operation=ambient_start)")
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(float(cfg.get("tick_interval", 3.0)),),
            daemon=True, name="AmbientLoop",
        )
        self._thread.start()
        logger.info(
            "[penthouse] ambient layer started "
            "(operation=ambient_start, interval=%.1fs)",
            float(cfg.get("tick_interval", 3.0)),
        )

    def stop(self) -> None:
        """Stop the background ambient loop."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        logger.info(
            "[penthouse] ambient layer stopped "
            "(operation=ambient_stop, ticks=%d, llm_lines=%d)",
            self._tick_count, self._llm_calls,
        )

    def _run(self, interval: float) -> None:
        while not self._stop_event.is_set():
            try:
                if self._is_active():
                    self.tick()
            except Exception as exc:  # never let the cheap loop crash the scene
                logger.warning(
                    "[penthouse] ambient tick error (operation=ambient_tick): %s", exc,
                )
            self._stop_event.wait(timeout=interval)

    def tick(self) -> List[Dict[str, Any]]:
        """Run one cheap ambient cycle. Returns the emitted actions (for tests)."""
        self._tick_count += 1
        cfg = get_ambient_config()
        if not cfg.get("enabled", True):
            return []
        # Hard gate: if the scene says it's not safe to run, do nothing.
        if not self._is_active():
            return []

        char_ids = list(self._list_characters() or [])
        if not char_ids:
            return []
        try:
            player_present, player_active = self._player_state()
        except Exception:
            player_present, player_active = False, False

        random.shuffle(char_ids)
        max_per_tick = max(1, int(cfg.get("max_per_tick", 2)))
        emitted: List[Dict[str, Any]] = []

        for cid in char_ids[:max_per_tick]:
            try:
                state = self._get_state(cid) or {}
            except Exception:
                continue
            action = select_ambient_action(
                stats=state.get("stats") or {},
                player_present=player_present,
                player_active=player_active,
                has_other_characters=len(char_ids) > 1,
                nearby_locations=state.get("nearby_locations") or [],
                in_active_pose=bool(state.get("in_active_pose")),
                is_busy=bool(state.get("is_busy")),
                config=cfg,
            )
            if not action:
                continue

            # Rare escalation to a single LLM ambient line via the existing
            # agent path — default is scripted so the model is not spammed.
            if (
                self._request_llm_line is not None
                and random.random() < float(cfg.get("llm_line_chance", 0.04))
            ):
                try:
                    self._request_llm_line(cid)
                    self._llm_calls += 1
                    action = {**action, "escalated_to_llm": True}
                except Exception as exc:
                    logger.debug("[penthouse] ambient LLM line failed for %s: %s", cid, exc)

            try:
                self._emit_action(cid, action)
                emitted.append({"character_id": cid, **action})
            except Exception as exc:
                logger.debug("[penthouse] ambient emit failed for %s: %s", cid, exc)

        if emitted:
            logger.debug(
                "[penthouse] ambient tick fired (operation=ambient_tick, tick=%d, "
                "actions=%d, llm_lines=%d)",
                self._tick_count, len(emitted), self._llm_calls,
            )
        return emitted
