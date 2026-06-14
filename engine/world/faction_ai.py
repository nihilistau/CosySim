"""Autonomous faction decision engine for CosySim v1.0 "NeonCity 2".

Provides the AI-driven faction behavior layer that makes territory control
dynamic.  Each faction evaluates its position every tick and makes strategic
decisions: expand into weak districts, defend against rivals, sabotage
enemies, negotiate alliances, or recruit NPCs.

The engine integrates with:

* :mod:`engine.world.territory` — district control percentages
* :mod:`engine.story.faction_politics` — inter-faction relationships
* :mod:`engine.events.event_bus` — broadcasts faction events
* :mod:`engine.world.npc_routines` — interrupts NPCs during faction wars

Decision Weights
~~~~~~~~~~~~~~~~
Each faction's decision is weighted by personality traits:

- **OmniCorp** — corporate, expansionist, prefers economic leverage
- **NeoTech** — tech-focused, defensive, prefers cyberspace operations
- **BlackMarket** — opportunistic, prefers sabotage and smuggling
- **Ghost_Net** — secretive, prefers intelligence and infiltration
- **SynthSec** — militant, prefers direct territorial control
- **DeepState** — manipulative, prefers political maneuvers

Usage::

    from engine.world.faction_ai import get_faction_ai

    ai = get_faction_ai()
    results = ai.tick()  # each faction makes one decision
    print(results["decisions"])  # list of faction actions taken

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — "Living Systems": _decide() now weights actions by
        the *player's* standing with each faction — allies expand near the
        player and avoid raiding them, rivals raid/sabotage the player's turf.
        Territory control shifts are now persisted/broadcast on the EventBus
        (NEONCITY_FACTION_SHIFT) so other scenes can react. War thresholds and
        player-influence knobs are configurable under ``territory.faction_ai``.
    v1.0 — Initial NeonCity faction AI (decisions never considered the player;
        control shifts were computed but never broadcast).

CONNECTS: EventBus, PlayerState (faction_standings), get_config, territory
CALLED BY: world_sim faction tick, faction AI scheduler
EMITS: faction_decision, faction_war, neoncity.faction_shift (EventBus)
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Lazy imports ────

try:
    from engine.events.event_bus import EventTypes as _EventTypes
    from engine.events.event_bus import get_event_bus as _get_event_bus
    _HAS_BUS = True
except ImportError:  # pragma: no cover
    _get_event_bus = lambda: None  # type: ignore[assignment]
    _EventTypes = None  # type: ignore[assignment]
    _HAS_BUS = False


# v1.60.0 [2026-06-13] — Player-standing influence config (safe defaults so the
# engine and hermetic tests run with no config file present).
_DEFAULT_PLAYER_INFLUENCE: float = 0.4   # how strongly player standing tilts decisions (0–1)
_DEFAULT_PLAYER_DISTRICT: str = ""       # district the player currently occupies


def _cfg(key: str, default: Any) -> Any:
    """Read a ``territory.faction_ai.<key>`` config value, never raising."""
    try:
        from engine.config import get_config

        return get_config().get(f"territory.faction_ai.{key}", default)
    except Exception:  # pragma: no cover - config absent in unit tests
        return default


def _get_player_standings() -> Dict[str, int]:
    """Return the player's faction→standing map (empty if unavailable)."""
    try:
        from engine.world.player_state import get_player_state

        return dict(get_player_state().faction_standings)
    except Exception:  # pragma: no cover - PlayerState absent in unit tests
        return {}


# ──── Enums & Data ────


class FactionAction(str, Enum):
    """Actions a faction can take on a tick."""
    EXPAND = "expand"
    DEFEND = "defend"
    SABOTAGE = "sabotage"
    NEGOTIATE = "negotiate"
    RECRUIT = "recruit"
    FORTIFY = "fortify"
    RAID = "raid"
    IDLE = "idle"


@dataclass
class FactionDecision:
    """Record of a faction's decision for one tick.

    Attributes:
        faction: Faction name.
        action: What the faction decided to do.
        target_district: Which district is affected.
        target_faction: Which rival faction is targeted (if any).
        control_delta: How much territory control shifted.
        narrative: Human-readable description of what happened.
        timestamp: When the decision was made.
    """
    faction: str
    action: str
    target_district: str = ""
    target_faction: str = ""
    control_delta: float = 0.0
    narrative: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FactionProfile:
    """Personality and strategic weights for a faction.

    Attributes:
        name: Faction name.
        aggression: How likely to attack (0–1).
        expansion: How likely to expand into new territory (0–1).
        defense: How likely to fortify existing territory (0–1).
        subterfuge: How likely to use sabotage/espionage (0–1).
        diplomacy: How likely to negotiate alliances (0–1).
        preferred_districts: Districts this faction especially values.
        rival_factions: Factions this one has natural enmity with.
    """
    name: str
    aggression: float = 0.5
    expansion: float = 0.5
    defense: float = 0.5
    subterfuge: float = 0.5
    diplomacy: float = 0.5
    preferred_districts: List[str] = field(default_factory=list)
    rival_factions: List[str] = field(default_factory=list)


# ──── Faction Profiles ────

FACTION_PROFILES: Dict[str, FactionProfile] = {
    "OmniCorp": FactionProfile(
        name="OmniCorp",
        aggression=0.3, expansion=0.8, defense=0.6,
        subterfuge=0.2, diplomacy=0.7,
        preferred_districts=["HIGHRISE", "DOWNTOWN"],
        rival_factions=["BlackMarket", "Ghost_Net"],
    ),
    "NeoTech": FactionProfile(
        name="NeoTech",
        aggression=0.2, expansion=0.5, defense=0.8,
        subterfuge=0.6, diplomacy=0.5,
        preferred_districts=["TECH_DISTRICT", "HIGHRISE"],
        rival_factions=["Ghost_Net", "SynthSec"],
    ),
    "BlackMarket": FactionProfile(
        name="BlackMarket",
        aggression=0.6, expansion=0.4, defense=0.3,
        subterfuge=0.9, diplomacy=0.2,
        preferred_districts=["UNDERWORLD", "COMBAT_ZONE"],
        rival_factions=["OmniCorp", "SynthSec"],
    ),
    "Ghost_Net": FactionProfile(
        name="Ghost_Net",
        aggression=0.2, expansion=0.3, defense=0.5,
        subterfuge=0.95, diplomacy=0.4,
        preferred_districts=["TECH_DISTRICT", "UNDERWORLD"],
        rival_factions=["OmniCorp", "NeoTech"],
    ),
    "SynthSec": FactionProfile(
        name="SynthSec",
        aggression=0.8, expansion=0.7, defense=0.7,
        subterfuge=0.3, diplomacy=0.3,
        preferred_districts=["COMBAT_ZONE", "DOWNTOWN"],
        rival_factions=["BlackMarket", "NeoTech"],
    ),
    "DeepState": FactionProfile(
        name="DeepState",
        aggression=0.4, expansion=0.5, defense=0.6,
        subterfuge=0.8, diplomacy=0.7,
        preferred_districts=["HIGHRISE", "UNDERWORLD"],
        rival_factions=["Ghost_Net", "SynthSec"],
    ),
}

# Narrative templates for each action type
ACTION_NARRATIVES: Dict[str, List[str]] = {
    "expand": [
        "{faction} moved operatives into {district}, claiming new ground.",
        "{faction} expanded their influence in {district} through corporate acquisitions.",
        "{faction} established a new presence in {district}.",
        "{faction} pushed into {district}, setting up supply lines.",
    ],
    "defend": [
        "{faction} reinforced their holdings in {district}.",
        "{faction} deployed additional security across {district}.",
        "{faction} fortified key positions in {district}.",
    ],
    "sabotage": [
        "{faction} disrupted {target}'s operations in {district}.",
        "{faction} carried out a covert strike against {target} in {district}.",
        "{faction} sabotaged {target}'s infrastructure in {district}.",
    ],
    "negotiate": [
        "{faction} reached a temporary ceasefire with {target} in {district}.",
        "{faction} negotiated a trade agreement with {target}.",
        "{faction} and {target} agreed to non-aggression in {district}.",
    ],
    "recruit": [
        "{faction} recruited new operatives in {district}.",
        "{faction} bolstered their ranks with local talent from {district}.",
    ],
    "fortify": [
        "{faction} built defensive installations in {district}.",
        "{faction} hardened their operations in {district}.",
    ],
    "raid": [
        "{faction} launched a raid against {target} in {district}.",
        "{faction} hit {target}'s supply depot in {district}.",
        "A sudden {faction} strike crippled {target}'s operations in {district}.",
    ],
    "idle": [
        "{faction} maintained their current posture in {district}.",
    ],
}


# ──── Faction AI Engine ────


class FactionAI:
    """Autonomous faction decision engine.

    Each :meth:`tick` call evaluates every faction's strategic position
    and generates decisions that shift territory control, trigger events,
    and create narrative content.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tick_count: int = 0
        self._history: List[FactionDecision] = []
        self._war_active: Dict[str, Dict[str, str]] = {}  # district → {attacker, defender}
        self._control: Dict[str, Dict[str, float]] = {}
        # v1.60.0 — live snapshot of the player's faction standings and location,
        # so factions can react to the player (allies expand near you, rivals raid).
        self._player_standings: Dict[str, int] = {}
        self._player_district: str = ""
        logger.info("[FactionAI] Initialized (operation=init)")

    def set_control(self, control: Dict[str, Dict[str, float]]) -> None:
        """Update the AI's view of territory control.

        Args:
            control: {district: {faction: control_pct}}.
        """
        with self._lock:
            self._control = {d: dict(f) for d, f in control.items()}

    # v1.60.0 [2026-06-13] — Player context injection for standing-aware decisions
    def set_player_context(
        self,
        standings: Optional[Dict[str, int]] = None,
        district: str = "",
    ) -> None:
        """Inform the AI of the player's faction standings and location.

        Allies (high player standing) will favour expanding into / defending the
        player's district; rivals (low standing) will favour raiding / sabotaging
        it. When *standings* is ``None`` the live :class:`PlayerState` is read.

        Args:
            standings: {faction: standing} (-100…+100). ``None`` → read PlayerState.
            district: District the player currently occupies (uppercase id).
        """
        with self._lock:
            self._player_standings = (
                dict(standings) if standings is not None else _get_player_standings()
            )
            self._player_district = (
                district or str(_cfg("player_district", _DEFAULT_PLAYER_DISTRICT))
            )

    def tick(self) -> Dict[str, Any]:
        """Execute one decision cycle for all factions.

        Each faction evaluates its strategic position and takes one action.
        Actions can shift territory control, trigger wars, and generate
        narrative events.

        Returns:
            Summary with decisions list, wars triggered, and control changes.
        """
        with self._lock:
            self._tick_count += 1
            decisions: List[FactionDecision] = []
            wars_triggered: List[Dict[str, Any]] = []
            control_changes: List[Dict[str, Any]] = []

            # v1.60.0 — refresh player context from PlayerState if not explicitly
            # provided, so faction decisions react to the live player.
            if not self._player_standings:
                self._player_standings = _get_player_standings()

            for faction_name, profile in FACTION_PROFILES.items():
                decision = self._decide(faction_name, profile)
                decisions.append(decision)

                if decision.control_delta != 0.0 and decision.target_district:
                    before = dict(
                        self._control.get(decision.target_district, {})
                    )
                    self._apply_control_shift(
                        decision.target_district,
                        faction_name,
                        decision.control_delta,
                        decision.target_faction,
                    )
                    after = dict(
                        self._control.get(decision.target_district, {})
                    )
                    control_changes.append({
                        "district": decision.target_district,
                        "faction": faction_name,
                        "delta": decision.control_delta,
                        "target_faction": decision.target_faction,
                        "control_before": before,
                        "control_after": after,
                        "action": decision.action,
                        "near_player": (
                            decision.target_district == self._player_district
                        ),
                    })

                    # Check for war trigger (>10% shift)
                    if abs(decision.control_delta) >= 10.0:
                        war = {
                            "district": decision.target_district,
                            "attacker": faction_name,
                            "defender": decision.target_faction or "local forces",
                            "intensity": abs(decision.control_delta),
                        }
                        wars_triggered.append(war)
                        self._war_active[decision.target_district] = {
                            "attacker": faction_name,
                            "defender": decision.target_faction or "",
                        }

                self._history.append(decision)

            # Cap history
            if len(self._history) > 500:
                self._history = self._history[-500:]

        # Emit events outside lock
        for d in decisions:
            self._emit("faction_decision", d.to_dict())
        for w in wars_triggered:
            self._emit("faction_war", w)
        # v1.60.0 — persist/broadcast territory control shifts so other scenes
        # (HUD, neoncity map, director) can react. Uses the canonical
        # NEONCITY_FACTION_SHIFT event type when available.
        shift_type = getattr(_EventTypes, "NEONCITY_FACTION_SHIFT", "neoncity.faction_shift")
        for change in control_changes:
            self._emit(shift_type, change)

        return {
            "tick": self._tick_count,
            "decisions": [d.to_dict() for d in decisions],
            "wars_triggered": wars_triggered,
            "control_changes": control_changes,
        }

    def get_history(self, faction: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent faction decisions.

        Args:
            faction: Filter by faction name (empty = all).
            limit: Maximum entries.

        Returns:
            List of decision dicts (newest first).
        """
        with self._lock:
            records = self._history
            if faction:
                records = [r for r in records if r.faction == faction]
            return [r.to_dict() for r in records[-limit:]][::-1]

    def get_active_wars(self) -> Dict[str, Dict[str, str]]:
        """Return currently active faction wars by district.

        Returns:
            {district: {attacker, defender}}.
        """
        with self._lock:
            return dict(self._war_active)

    def end_war(self, district: str) -> bool:
        """End an active war in a district.

        Args:
            district: District where the war is.

        Returns:
            True if a war was ended.
        """
        with self._lock:
            if district in self._war_active:
                del self._war_active[district]
                return True
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Return faction AI statistics."""
        with self._lock:
            action_counts: Dict[str, int] = {}
            for d in self._history:
                action_counts[d.action] = action_counts.get(d.action, 0) + 1
            return {
                "tick_count": self._tick_count,
                "total_decisions": len(self._history),
                "active_wars": len(self._war_active),
                "action_distribution": action_counts,
                "war_districts": list(self._war_active.keys()),
            }

    def reset(self) -> None:
        """Reset the AI state."""
        with self._lock:
            self._tick_count = 0
            self._history.clear()
            self._war_active.clear()
            self._control.clear()
            self._player_standings = {}
            self._player_district = ""

    # ──── Decision Logic ────

    def _decide(self, faction_name: str, profile: FactionProfile) -> FactionDecision:
        """Make a strategic decision for one faction.

        The decision algorithm:
        1. Evaluate current position (controlled vs desired districts)
        2. Score each possible action based on personality weights and context
        3. Add randomness to prevent predictable behavior
        4. Execute the highest-scoring action
        """
        # Find faction's weakest and strongest districts
        my_districts = self._get_faction_districts(faction_name)
        weakest = self._get_weakest_district(faction_name, profile)
        strongest = self._get_strongest_district(faction_name)

        # Score each action
        scores: Dict[str, float] = {}

        # Expand: high if we have low control in preferred districts
        expand_score = profile.expansion
        if weakest and weakest in profile.preferred_districts:
            expand_score += 0.3
        scores["expand"] = expand_score

        # Defend: high if we have strong positions under threat
        defend_score = profile.defense
        if self._is_under_threat(faction_name, strongest):
            defend_score += 0.4
        scores["defend"] = defend_score

        # Sabotage: high against rivals in our preferred districts
        sabotage_score = profile.subterfuge
        if profile.rival_factions:
            for rival in profile.rival_factions:
                if self._rival_in_preferred(rival, profile):
                    sabotage_score += 0.2
                    break
        scores["sabotage"] = sabotage_score

        # Raid: requires high aggression
        raid_score = profile.aggression * 0.8
        if self._war_active:
            raid_score += 0.2
        scores["raid"] = raid_score

        # Negotiate: high when outnumbered or at war
        negotiate_score = profile.diplomacy
        if len(self._war_active) > 1:
            negotiate_score += 0.3
        scores["negotiate"] = negotiate_score

        # Recruit: always somewhat useful
        scores["recruit"] = 0.3 + random.uniform(0, 0.2)

        # Fortify: useful when holding strong positions
        scores["fortify"] = profile.defense * 0.7

        # v1.60.0 [2026-06-13] — Weight actions by the PLAYER's standing with
        # this faction. Allies (high standing) protect/expand near the player and
        # avoid hostility toward them; rivals (low standing) raid and sabotage the
        # player's turf. This closes the loop where FactionAI ignored the player.
        self._apply_player_standing_bias(faction_name, scores)

        # Add randomness (±20%)
        for action in scores:
            scores[action] += random.uniform(-0.2, 0.2)

        # Pick top action
        best_action = max(scores, key=scores.get)
        return self._execute_action(faction_name, profile, best_action)

    def _apply_player_standing_bias(
        self, faction_name: str, scores: Dict[str, float]
    ) -> None:
        """Tilt a faction's action scores based on the player's standing.

        Mutates *scores* in place. The strength of the tilt is governed by the
        configurable ``territory.faction_ai.player_influence`` knob (0–1).

        Logic:
          * standing > 0 (ally)  → boost expand/defend/negotiate, suppress
            raid/sabotage. Bonus toward expand/defend when the player is *in*
            this faction's district (allies hold ground near you).
          * standing < 0 (rival) → boost raid/sabotage, suppress negotiate.
            Bonus toward raid when the player is in this district (rivals come
            for your turf).

        Args:
            faction_name: The acting faction.
            scores: Action→score map (mutated in place).
        """
        standing = int(self._player_standings.get(faction_name, 0))
        if standing == 0:
            return

        influence = float(_cfg("player_influence", _DEFAULT_PLAYER_INFLUENCE))
        # Normalised magnitude in [0,1] from a -100…+100 standing.
        magnitude = min(1.0, abs(standing) / 100.0) * influence
        near_player = (
            bool(self._player_district)
            and self._player_district in self._control
        )

        if standing > 0:
            # Ally: build and defend, especially near the player; de-escalate.
            scores["expand"] += magnitude * (0.6 + (0.4 if near_player else 0.0))
            scores["defend"] += magnitude * (0.4 + (0.3 if near_player else 0.0))
            scores["negotiate"] += magnitude * 0.3
            scores["raid"] -= magnitude * 0.6
            scores["sabotage"] -= magnitude * 0.4
        else:
            # Rival: raid and sabotage, especially the player's district.
            scores["raid"] += magnitude * (0.6 + (0.5 if near_player else 0.0))
            scores["sabotage"] += magnitude * (0.5 + (0.3 if near_player else 0.0))
            scores["negotiate"] -= magnitude * 0.5
            scores["fortify"] -= magnitude * 0.2

    def _execute_action(
        self, faction_name: str, profile: FactionProfile, action: str
    ) -> FactionDecision:
        """Execute a chosen action and produce a FactionDecision."""
        target_district = self._pick_target_district(faction_name, profile, action)
        target_faction = self._pick_target_faction(faction_name, profile, action, target_district)
        control_delta = self._compute_delta(action, faction_name, target_district)

        narrative = self._generate_narrative(
            action, faction_name, target_district, target_faction
        )

        return FactionDecision(
            faction=faction_name,
            action=action,
            target_district=target_district,
            target_faction=target_faction,
            control_delta=control_delta,
            narrative=narrative,
        )

    def _pick_target_district(
        self, faction: str, profile: FactionProfile, action: str
    ) -> str:
        """Choose which district to target for an action."""
        districts = list(self._control.keys()) if self._control else [
            "DOWNTOWN", "COMBAT_ZONE", "HIGHRISE", "UNDERWORLD",
            "TECH_DISTRICT", "OUTSKIRTS",
        ]

        if action in ("expand", "raid"):
            # v1.60.0 — steer toward the player's district when the player has a
            # strong relationship with this faction: allies expand to be near
            # the player, rivals raid the player's turf.
            standing = int(self._player_standings.get(faction, 0))
            if (
                self._player_district
                and self._player_district in districts
                and abs(standing) >= int(_cfg("player_target_threshold", 25))
            ):
                if (action == "expand" and standing > 0) or (
                    action == "raid" and standing < 0
                ):
                    return self._player_district

            # Target a preferred district where we have low control
            preferred = [d for d in districts if d in profile.preferred_districts]
            if preferred:
                return min(
                    preferred,
                    key=lambda d: self._control.get(d, {}).get(faction, 0),
                )
            return random.choice(districts)

        elif action in ("defend", "fortify"):
            # Defend our strongest district
            return self._get_strongest_district(faction) or random.choice(districts)

        elif action in ("sabotage", "negotiate"):
            # Target a district with our rival
            for rival in profile.rival_factions:
                for d in districts:
                    ctrl = self._control.get(d, {})
                    if ctrl.get(rival, 0) > 20:
                        return d
            return random.choice(districts)

        return random.choice(districts)

    def _pick_target_faction(
        self, faction: str, profile: FactionProfile,
        action: str, district: str,
    ) -> str:
        """Choose which rival faction to target."""
        if action in ("expand", "defend", "fortify", "recruit", "idle"):
            return ""

        ctrl = self._control.get(district, {})
        rivals = [f for f in ctrl if f != faction and ctrl.get(f, 0) > 5]

        # Prefer named rivals
        for rival in profile.rival_factions:
            if rival in rivals:
                return rival

        return rivals[0] if rivals else ""

    def _compute_delta(
        self, action: str, faction: str, district: str
    ) -> float:
        """Compute the territory control shift for an action."""
        base_deltas: Dict[str, float] = {
            "expand": random.uniform(1.5, 4.0),
            "defend": random.uniform(0.5, 1.5),
            "sabotage": random.uniform(-3.0, -1.0),  # target loses this
            "negotiate": 0.0,
            "recruit": random.uniform(0.5, 1.0),
            "fortify": random.uniform(0.3, 0.8),
            "raid": random.uniform(2.0, 5.0),
            "idle": 0.0,
        }
        return round(base_deltas.get(action, 0.0), 1)

    def _apply_control_shift(
        self,
        district: str,
        faction: str,
        delta: float,
        target_faction: str,
    ) -> None:
        """Apply a control shift in the internal control map."""
        if district not in self._control:
            return

        ctrl = self._control[district]
        old = ctrl.get(faction, 0)
        ctrl[faction] = max(0, min(100, old + delta))

        # If targeting another faction, they lose proportionally
        if target_faction and target_faction in ctrl and delta > 0:
            rival_old = ctrl[target_faction]
            ctrl[target_faction] = max(0, rival_old - delta * 0.6)

        # Normalize to roughly 100%
        total = sum(ctrl.values())
        if total > 0 and abs(total - 100) > 5:
            factor = 100.0 / total
            for f in ctrl:
                ctrl[f] = round(ctrl[f] * factor, 1)

    def _generate_narrative(
        self,
        action: str,
        faction: str,
        district: str,
        target: str,
    ) -> str:
        """Generate a narrative description for a faction action."""
        templates = ACTION_NARRATIVES.get(action, ACTION_NARRATIVES["idle"])
        template = random.choice(templates)
        return template.format(
            faction=faction,
            district=district,
            target=target or "unknown forces",
        )

    # ──── Helpers ────

    def _get_faction_districts(self, faction: str) -> Dict[str, float]:
        """Return {district: control_pct} for a faction."""
        return {
            d: ctrl.get(faction, 0)
            for d, ctrl in self._control.items()
        }

    def _get_weakest_district(
        self, faction: str, profile: FactionProfile
    ) -> str:
        """Return the preferred district where the faction has lowest control."""
        my_ctrl = self._get_faction_districts(faction)
        preferred = {
            d: c for d, c in my_ctrl.items()
            if d in profile.preferred_districts
        }
        if preferred:
            return min(preferred, key=preferred.get)
        if my_ctrl:
            return min(my_ctrl, key=my_ctrl.get)
        return ""

    def _get_strongest_district(self, faction: str) -> str:
        """Return the district where the faction has highest control."""
        my_ctrl = self._get_faction_districts(faction)
        if my_ctrl:
            return max(my_ctrl, key=my_ctrl.get)
        return ""

    def _is_under_threat(self, faction: str, district: str) -> bool:
        """Check if a faction's district is contested."""
        if not district:
            return False
        ctrl = self._control.get(district, {})
        my_pct = ctrl.get(faction, 0)
        for rival, pct in ctrl.items():
            if rival != faction and pct > my_pct * 0.8:
                return True
        return False

    def _rival_in_preferred(self, rival: str, profile: FactionProfile) -> bool:
        """Check if a rival has significant control in our preferred districts."""
        for d in profile.preferred_districts:
            ctrl = self._control.get(d, {})
            if ctrl.get(rival, 0) > 20:
                return True
        return False

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish event on EventBus (best-effort, never raises)."""
        if not _HAS_BUS:
            return
        try:
            bus = _get_event_bus()
            if bus:
                bus.publish(event_type, data, scene="faction_ai")
        except Exception as exc:
            logger.debug(
                "[FactionAI] Event emit failed (operation=emit, event=%s): %s",
                event_type,
                exc,
            )


# ──── Singleton ────

_instance: Optional[FactionAI] = None
_instance_lock = threading.Lock()


def get_faction_ai() -> FactionAI:
    """Return the singleton FactionAI instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = FactionAI()
    return _instance


def reset_faction_ai() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
