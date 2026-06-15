"""
Mission Chains — Branching Multi-Stage Storylines
=================================================

Defines *mission chains*: ordered sequences of missions where completing one
stage unlocks the next, including branch points where the player's choice (or
outcome) routes them down divergent paths.

This closes a v1.59 audit gap: missions previously completed in isolation with
no narrative through-line. A chain links existing :class:`Mission` templates
(by ``mission_id``) into A → B → C progressions and exposes:

  * which chain a mission belongs to,
  * which mission(s) a completion unlocks (supporting branches),
  * whether a mission is *gated* (locked until its prerequisite is done).

The chain graph is data-only and side-effect free. :class:`MissionManager`
owns the runtime application (unlocking missions on completion); this module is
the source of truth for the topology.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — NEW. Mission chains subsystem for the "Living
        Systems" release: 4 branching chains (heist escalation, faction war,
        deep-state defection, street-to-syndicate), prerequisite gating, and
        branch resolution by outcome/standing. Paired with consequence
        application + difficulty scaling in engine/world/mission.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Branch Conditions ──────────────────────────────────────────────────────
# A branch picks the next stage from a completion context. The context is a
# plain dict produced by MissionManager (outcome, faction standings, rep, heat).
# Conditions are pure predicates so chains stay testable and config-free.


def _ctx_success(ctx: Dict[str, Any]) -> bool:
    """True when the triggering mission was completed (not failed)."""
    return ctx.get("outcome") == "completed"


def _ctx_failed(ctx: Dict[str, Any]) -> bool:
    """True when the triggering mission was failed."""
    return ctx.get("outcome") == "failed"


def _high_rep(threshold: int) -> Callable[[Dict[str, Any]], bool]:
    """Build a predicate: player reputation >= *threshold*."""

    def _pred(ctx: Dict[str, Any]) -> bool:
        return int(ctx.get("reputation", 0)) >= threshold

    return _pred


def _faction_at_least(faction: str, threshold: int) -> Callable[[Dict[str, Any]], bool]:
    """Build a predicate: standing with *faction* >= *threshold*."""

    def _pred(ctx: Dict[str, Any]) -> bool:
        standings = ctx.get("faction_standings", {}) or {}
        return int(standings.get(faction, 0)) >= threshold

    return _pred


# ──── Dataclasses ────────────────────────────────────────────────────────────


@dataclass
class ChainBranch:
    """A conditional edge from one mission stage to the next.

    Attributes:
        unlocks: Mission ID unlocked when ``condition`` passes.
        condition: Predicate over the completion context. ``None`` = always.
        label: Human-readable description of why this branch is taken.
    """

    unlocks: str
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    label: str = ""

    def matches(self, ctx: Dict[str, Any]) -> bool:
        """Return True if this branch should fire for *ctx*."""
        if self.condition is None:
            return True
        try:
            return bool(self.condition(ctx))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[MissionChains] Branch condition error (operation=branch_eval, unlocks=%s): %s",
                self.unlocks,
                exc,
            )
            return False


@dataclass
class ChainStage:
    """A single mission slot in a chain.

    Attributes:
        mission_id: ID of the :class:`Mission` template that fills this slot.
        branches: Ordered branches evaluated on completion; first match wins
            unless ``allow_multiple`` is set (then all matching fire).
        allow_multiple: If True, every matching branch unlocks (parallel paths).
    """

    mission_id: str
    branches: List[ChainBranch] = field(default_factory=list)
    allow_multiple: bool = False

    def resolve(self, ctx: Dict[str, Any]) -> List[str]:
        """Return the mission IDs unlocked given a completion *ctx*."""
        unlocked: List[str] = []
        for br in self.branches:
            if br.matches(ctx):
                unlocked.append(br.unlocks)
                if not self.allow_multiple:
                    break
        return unlocked


@dataclass
class MissionChain:
    """An ordered, branching sequence of mission stages.

    Attributes:
        id: Stable chain identifier.
        title: Display name of the storyline.
        description: One-line summary.
        stages: Ordered stages. ``stages[0]`` is the entry point and is the
            only stage available without a prerequisite.
    """

    id: str
    title: str
    description: str
    stages: List[ChainStage] = field(default_factory=list)

    # ── Topology helpers ──────────────────────────────────────────────────

    @property
    def entry_mission_id(self) -> str:
        """Mission ID that opens the chain."""
        return self.stages[0].mission_id if self.stages else ""

    @property
    def mission_ids(self) -> List[str]:
        """All mission IDs referenced by this chain (in declaration order)."""
        return [s.mission_id for s in self.stages]

    def stage_for(self, mission_id: str) -> Optional[ChainStage]:
        """Return the stage whose mission matches *mission_id*."""
        return next((s for s in self.stages if s.mission_id == mission_id), None)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the chain topology (conditions are summarised by label)."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "entry": self.entry_mission_id,
            "stages": [
                {
                    "mission_id": s.mission_id,
                    "allow_multiple": s.allow_multiple,
                    "branches": [
                        {"unlocks": b.unlocks, "label": b.label} for b in s.branches
                    ],
                }
                for s in self.stages
            ],
        }


# ──── Chain Definitions ──────────────────────────────────────────────────────
# Mission IDs reference the builtin templates in engine/world/mission.py.
# Entry missions (stage 0) are *not* gated; every later mission is gated until
# a prerequisite branch unlocks it.


def _build_builtin_chains() -> List[MissionChain]:
    """Return the 4 builtin branching mission chains.

    Topology:
        heist_escalation:  lab_prototype → (success) score_safe → colosseum
                                          → (failure) colosseum_credits
        faction_war:       velvet_pit_enforcers → obscura_faction
                                          → (Ghost_Net rep) command_center_alliance
        deepstate_defect:  grid_data → throne_defector → command_center_alliance
        street_syndicate:  arcade_fixer → rusty_anchor_weapons → club_noir_runner
    """
    return [
        # 1. HEIST ESCALATION — branches on success/failure of the big lift.
        MissionChain(
            id="heist_escalation",
            title="The Long Con",
            description="A clean lab lift snowballs into the biggest score in Neon City.",
            stages=[
                ChainStage(
                    mission_id="heist_lab_prototype",
                    branches=[
                        ChainBranch(
                            unlocks="heist_score_safe",
                            condition=_ctx_success,
                            label="Clean lift earns Viktor's trust → The Big Score",
                        ),
                        ChainBranch(
                            unlocks="heist_colosseum_credits",
                            condition=_ctx_failed,
                            label="Botched lift → settle a smaller debt at the arena",
                        ),
                    ],
                ),
                ChainStage(
                    mission_id="heist_score_safe",
                    branches=[
                        ChainBranch(
                            unlocks="hit_colosseum_fixer",
                            label="Heat from the vault job → silence the fixer who saw you",
                        ),
                    ],
                ),
                ChainStage(mission_id="heist_colosseum_credits"),
                ChainStage(mission_id="hit_colosseum_fixer"),
            ],
        ),
        # 2. FACTION WAR — branches on Ghost_Net standing at the broker stage.
        MissionChain(
            id="faction_war",
            title="Fractured City",
            description="Clearing OmniCorp muscle drags you into a faction power struggle.",
            stages=[
                ChainStage(
                    mission_id="hit_velvet_pit_enforcers",
                    branches=[
                        ChainBranch(
                            unlocks="deal_obscura_faction",
                            label="OmniCorp routed → brokers circle The Obscura",
                        ),
                    ],
                ),
                ChainStage(
                    mission_id="deal_obscura_faction",
                    branches=[
                        ChainBranch(
                            unlocks="deal_command_center_alliance",
                            condition=_faction_at_least("Ghost_Net", 10),
                            label="Ghost_Net trusts you → formal alliance summit",
                        ),
                    ],
                ),
                ChainStage(mission_id="deal_command_center_alliance"),
            ],
        ),
        # 3. DEEP-STATE DEFECTION — linear, high-stakes extraction storyline.
        MissionChain(
            id="deepstate_defect",
            title="Ghosts of the State",
            description="A data ghost leads to a defector who could topple DeepState.",
            stages=[
                ChainStage(
                    mission_id="extraction_grid_data",
                    branches=[
                        ChainBranch(
                            unlocks="extraction_throne_defector",
                            condition=_ctx_success,
                            label="Backup data names the defector → extract them",
                        ),
                    ],
                ),
                ChainStage(
                    mission_id="extraction_throne_defector",
                    branches=[
                        ChainBranch(
                            unlocks="deal_command_center_alliance",
                            label="Defector delivered → Command Center opens its doors",
                        ),
                    ],
                ),
                ChainStage(mission_id="deal_command_center_alliance"),
            ],
        ),
        # 4. STREET → SYNDICATE — reputation-gated rise through the ranks.
        MissionChain(
            id="street_syndicate",
            title="From the Gutter Up",
            description="Benching a street fixer is the first rung of a syndicate ladder.",
            stages=[
                ChainStage(
                    mission_id="hit_arcade_fixer",
                    branches=[
                        ChainBranch(
                            unlocks="deal_rusty_anchor_weapons",
                            condition=_high_rep(52),
                            label="Reputation rising → trusted with a debt brokerage",
                        ),
                    ],
                ),
                ChainStage(
                    mission_id="deal_rusty_anchor_weapons",
                    branches=[
                        ChainBranch(
                            unlocks="extraction_club_noir_runner",
                            label="Brokerage proven → a runner needs a fast exit",
                        ),
                    ],
                ),
                ChainStage(mission_id="extraction_club_noir_runner"),
            ],
        ),
    ]


# ──── ChainRegistry ──────────────────────────────────────────────────────────


class ChainRegistry:
    """Read-only index over the builtin mission chains.

    Provides reverse lookups (mission → chain), prerequisite gating, and branch
    resolution. Stateless beyond the topology it is constructed with, so it is
    safe to instantiate fresh per test.

    CONNECTS: MissionManager (consequence application, unlock-on-complete)
    CALLED BY: MissionManager.complete / .fail / .list_available gating
    """

    def __init__(self, chains: Optional[List[MissionChain]] = None) -> None:
        self._chains: List[MissionChain] = chains if chains is not None else _build_builtin_chains()
        self._by_id: Dict[str, MissionChain] = {c.id: c for c in self._chains}

        # Reverse index: mission_id -> (chain, stage)
        self._mission_index: Dict[str, tuple[MissionChain, ChainStage]] = {}
        # Forward gating: mission_id -> list of prerequisite mission_ids
        self._prereqs: Dict[str, List[str]] = {}

        for chain in self._chains:
            for stage in chain.stages:
                # Last writer wins if a mission appears in multiple chains; we
                # also record every prerequisite edge below so gating is a union.
                self._mission_index[stage.mission_id] = (chain, stage)
                for branch in stage.branches:
                    self._prereqs.setdefault(branch.unlocks, []).append(stage.mission_id)

    # ── Queries ───────────────────────────────────────────────────────────

    @property
    def chains(self) -> List[MissionChain]:
        """All registered chains."""
        return list(self._chains)

    def get_chain(self, chain_id: str) -> Optional[MissionChain]:
        """Return a chain by ID."""
        return self._by_id.get(chain_id)

    def chain_for_mission(self, mission_id: str) -> Optional[MissionChain]:
        """Return the chain a mission belongs to, if any."""
        entry = self._mission_index.get(mission_id)
        return entry[0] if entry else None

    def is_chained(self, mission_id: str) -> bool:
        """True if the mission participates in any chain."""
        return mission_id in self._mission_index

    def prerequisites(self, mission_id: str) -> List[str]:
        """Return mission IDs that must be completed to unlock *mission_id*.

        Empty list means the mission is an entry point (ungated) or standalone.
        """
        return list(self._prereqs.get(mission_id, []))

    def is_gated(self, mission_id: str) -> bool:
        """True if the mission is locked behind at least one prerequisite."""
        return bool(self._prereqs.get(mission_id))

    def resolve_unlocks(self, mission_id: str, ctx: Dict[str, Any]) -> List[str]:
        """Return mission IDs unlocked by completing *mission_id* under *ctx*.

        Args:
            mission_id: The mission that just completed/failed.
            ctx: Completion context (``outcome``, ``reputation``,
                ``faction_standings``, ``heat``...).

        Returns:
            List of mission IDs to flip from locked → available. May be empty.
        """
        entry = self._mission_index.get(mission_id)
        if not entry:
            return []
        _chain, stage = entry
        return stage.resolve(ctx)

    def all_entry_missions(self) -> List[str]:
        """Return the entry (ungated) mission IDs across all chains."""
        return [c.entry_mission_id for c in self._chains if c.entry_mission_id]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the full chain catalogue."""
        return {"chains": [c.to_dict() for c in self._chains]}


# ──── Singleton ──────────────────────────────────────────────────────────────

_REGISTRY: Optional[ChainRegistry] = None


def get_chain_registry() -> ChainRegistry:
    """Return the process-wide :class:`ChainRegistry` singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ChainRegistry()
    return _REGISTRY


def reset_chain_registry() -> None:
    """Reset the singleton — for tests only."""
    global _REGISTRY
    _REGISTRY = None
