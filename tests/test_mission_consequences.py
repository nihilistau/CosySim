"""
Tests — Mission Consequences, Chains, Skill Scaling & Crew Gating
=================================================================

Covers the v1.60.0 "Living Systems" mission upgrade:

  * Consequences: success raises faction control + reputation; heist success
    also adds heat; failure raises heat and bleeds reputation/faction.
  * Mission chains: completion unlocks gated follow-ups, including success vs.
    failure branches and standing/reputation-gated branches.
  * Skill scaling: difficulty/reward scale with relevant player skills at
    accept time, and scaling is idempotent.
  * Crew gating: assigning a busy roster member is rejected; unknown members
    fail open.

Hermetic: every test patches ``engine.world.mission.get_player_state`` with a
fake, points the manager's save path at ``tmp_path``, and forces config values
in-process. No reliance on global ``data/*.json`` state.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — NEW. Verifies the closed consequence loop, chains,
        scaling, and crew enforcement.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from engine.world.mission import MissionManager, reset_mission_manager
from engine.world.mission_chains import (
    ChainBranch,
    ChainRegistry,
    ChainStage,
    MissionChain,
    reset_chain_registry,
)


# ──── Fakes ──────────────────────────────────────────────────────────────────


class FakePlayerState:
    """Minimal stand-in implementing the PlayerState surface the manager uses."""

    def __init__(self, skills: Optional[Dict[str, int]] = None) -> None:
        self._skills: Dict[str, int] = skills or {
            "hacking": 1, "combat": 1, "stealth": 1, "social": 1,
            "tech": 1, "driving": 0, "medicine": 0, "trading": 0,
        }
        self.reputation: int = 50
        self.heat: int = 0
        self.faction_standings: Dict[str, int] = {
            "OmniCorp": 0, "NeoTech": 0, "BlackMarket": 0,
            "Ghost_Net": 0, "SynthSec": 0, "DeepState": 0,
        }
        self.calls: List[str] = []

    # -- skills --
    def get_skill(self, skill: str) -> int:
        return int(self._skills.get(skill, 0))

    @property
    def skills(self) -> Dict[str, int]:
        return dict(self._skills)

    # -- mutators (clamped like the real thing) --
    def update_faction_standing(self, faction: str, delta: int) -> int:
        if faction not in self.faction_standings:
            return 0
        self.faction_standings[faction] = max(-100, min(100, self.faction_standings[faction] + delta))
        self.calls.append(f"faction:{faction}:{delta}")
        return self.faction_standings[faction]

    def adjust_faction(self, faction: str, delta: int) -> int:
        # Alias used by the legacy reward path (_apply_rewards).
        return self.update_faction_standing(faction, delta)

    def update_reputation(self, delta: int, reason: str = "") -> int:
        self.reputation = max(0, min(100, self.reputation + delta))
        self.calls.append(f"rep:{delta}")
        return self.reputation

    def adjust_reputation(self, delta: int, reason: str = "") -> int:
        return self.update_reputation(delta, reason=reason)

    def add_heat(self, amount: int, reason: str = "") -> int:
        self.heat = max(0, min(100, self.heat + amount))
        self.calls.append(f"heat:{amount}")
        return self.heat

    # -- reward surface (so _apply_rewards never explodes) --
    def earn_credits(self, amount: int, reason: str = "") -> int:
        return amount

    def add_xp(self, amount: int, reason: str = "") -> int:
        return amount


class FakeCrewMember:
    def __init__(self, available: bool = True) -> None:
        self.available = available


class FakeCrewManager:
    def __init__(self, members: Dict[str, FakeCrewMember]) -> None:
        self._members = members

    def get_member(self, cid: str) -> Optional[FakeCrewMember]:
        return self._members.get(cid)


# ──── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Hermetic isolation: fresh save path + singletons + forced config."""
    MissionManager._SAVE_PATH = tmp_path / "missions_test.json"
    reset_mission_manager()
    reset_chain_registry()

    # Force a known, deterministic config for every mission.* key we read.
    import engine.world.mission as mission_mod

    forced: Dict[str, Any] = dict(mission_mod._MISSION_DEFAULTS)
    monkeypatch.setattr(mission_mod, "_cfg", lambda path: forced.get(path), raising=True)

    yield forced

    reset_mission_manager()
    reset_chain_registry()


@pytest.fixture()
def ps(monkeypatch) -> FakePlayerState:
    """Install a FakePlayerState and return it for assertions."""
    fake = FakePlayerState()
    import engine.world.mission as mission_mod

    monkeypatch.setattr(mission_mod, "get_player_state", lambda: fake, raising=True)
    return fake


@pytest.fixture()
def mgr(ps) -> MissionManager:
    from engine.world.mission import get_mission_manager

    return get_mission_manager()


def _complete(mgr: MissionManager, mission_id: str) -> Dict[str, Any]:
    """Accept, satisfy all required objectives, and complete a mission."""
    mgr.accept(mission_id)
    m = mgr.get_mission(mission_id)
    for obj in m.objectives:
        if not obj.optional:
            mgr.complete_objective(mission_id, obj.id)
    return mgr.complete(mission_id, notes="test")


# ──── Consequences: success ──────────────────────────────────────────────────


class TestSuccessConsequences:
    def test_success_raises_faction_control_and_rep(self, mgr, ps):
        # recon_corp_signal: difficulty 2, faction Ghost_Net.
        # Template reward ALSO grants reputation +5 and faction_rep +10 to
        # Ghost_Net; consequences stack on top of those.
        before_rep = ps.reputation
        result = _complete(mgr, "recon_corp_signal")

        assert result["success"] is True
        cons = result["consequences"]
        # Consequence deltas are isolated and deterministic:
        # control_per_difficulty(3) * difficulty(2) = +6 Ghost_Net.
        assert cons["faction"] == "Ghost_Net"
        assert cons["faction_delta"] == 6
        # rep_success flat +4 (consequence only).
        assert cons["reputation_delta"] == 4
        # Net state = reward (rep+5, Ghost_Net faction_rep+10) + consequence.
        assert ps.faction_standings["Ghost_Net"] == 10 + 6
        assert ps.reputation == before_rep + 5 + 4

    def test_heist_success_adds_heat_and_control_bonus(self, mgr, ps):
        # heist_lab_prototype: difficulty 4, no reward faction set.
        result = _complete(mgr, "heist_lab_prototype")
        cons = result["consequences"]
        # No faction on this heist → no faction delta even with heist bonus.
        assert cons["faction"] is None
        assert cons["faction_delta"] == 0
        # Heist leaves a heat trail on success: heat_success_heist = 5.
        assert cons["heat_delta"] == 5
        assert ps.heat == 5

    def test_heist_with_faction_gets_control_bonus(self, mgr, ps):
        # hit_velvet_pit_enforcers is a HIT (not heist) with OmniCorp faction.
        # Build a synthetic heist+faction mission to prove the bonus path.
        from engine.world.mission import MissionType
        m = mgr.get_mission("heist_colosseum_credits")  # heist, difficulty 3
        # Inject a faction onto an existing heist template.
        m.reward.faction = "BlackMarket"
        result = _complete(mgr, "heist_colosseum_credits")
        cons = result["consequences"]
        # control = 3*3 + heist_bonus(4) = 13.
        assert cons["faction"] == "BlackMarket"
        assert cons["faction_delta"] == 13
        assert ps.faction_standings["BlackMarket"] == 13


# ──── Consequences: failure ──────────────────────────────────────────────────


class TestFailureConsequences:
    def test_failure_raises_heat_and_bleeds_rep(self, mgr, ps):
        mgr.accept("recon_corp_signal")  # difficulty 2
        before_rep = ps.reputation
        result = mgr.fail("recon_corp_signal", reason="caught")

        assert result["success"] is True
        cons = result["consequences"]
        # heat_fail_per_difficulty(4) * 2 = +8.
        assert cons["heat_delta"] == 8
        assert ps.heat == 8
        # rep_fail_per_difficulty(2) * 2 = -4.
        assert cons["reputation_delta"] == -4
        assert ps.reputation == before_rep - 4
        # faction bleed = -(3*2)//2 = -3 Ghost_Net.
        assert cons["faction_delta"] == -3
        assert ps.faction_standings["Ghost_Net"] == -3

    def test_consequences_disabled_is_noop(self, mgr, ps, _isolate):
        _isolate["mission.consequences.enabled"] = False
        mgr.accept("recon_corp_signal")
        result = mgr.fail("recon_corp_signal", reason="x")
        assert result["consequences"]["heat_delta"] == 0
        assert ps.heat == 0
        assert ps.reputation == 50


# ──── Skill scaling ──────────────────────────────────────────────────────────


class TestSkillScaling:
    def test_high_skill_scales_up_difficulty_and_reward(self, mgr, ps):
        # heist relevant skills: hacking/stealth/tech. Max them out.
        ps._skills.update({"hacking": 5, "stealth": 5, "tech": 5})
        m = mgr.get_mission("heist_lab_prototype")
        base_diff = m.difficulty           # 4
        base_credits = m.reward.credits    # 5000

        mgr.accept("heist_lab_prototype")
        m = mgr.get_mission("heist_lab_prototype")

        assert m.scaled is True
        assert m.base_difficulty == base_diff
        assert m.base_reward_credits == base_credits
        # mean skill 5, pivot 1 → delta 4. diff_scale 1+0.3*4=2.2 → 4*2.2=8.8→9→clamp 5.
        assert m.difficulty == 5
        # reward_scale 1+0.2*4 = 1.8 → 5000*1.8 = 9000.
        assert m.reward.credits == 9000

    def test_low_skill_keeps_baseline(self, mgr, ps):
        # Default skills give mean == pivot for some types → no change.
        ps._skills.update({"hacking": 1, "stealth": 1, "tech": 1})
        m = mgr.get_mission("heist_lab_prototype")
        base = m.difficulty
        base_credits = m.reward.credits
        mgr.accept("heist_lab_prototype")
        m = mgr.get_mission("heist_lab_prototype")
        assert m.difficulty == base
        assert m.reward.credits == base_credits

    def test_scaling_is_idempotent_on_base(self, mgr, ps):
        ps._skills.update({"hacking": 5, "stealth": 5, "tech": 5})
        mgr.accept("heist_lab_prototype")
        m = mgr.get_mission("heist_lab_prototype")
        once_credits = m.reward.credits
        # Re-scale from base directly; must not compound.
        m.status = m.status  # no-op, keep type
        mgr._scale_to_player(m)
        assert m.reward.credits == once_credits

    def test_scaling_disabled_skips(self, mgr, ps, _isolate):
        _isolate["mission.scaling.enabled"] = False
        ps._skills.update({"hacking": 5, "stealth": 5, "tech": 5})
        base = mgr.get_mission("heist_lab_prototype").difficulty
        mgr.accept("heist_lab_prototype")
        assert mgr.get_mission("heist_lab_prototype").difficulty == base


# ──── Mission chains ─────────────────────────────────────────────────────────


class TestMissionChains:
    def test_gating_locks_followups_when_enabled(self, _isolate):
        _isolate["mission.chains.gating_enabled"] = True
        reset_mission_manager()
        from engine.world.mission import get_mission_manager
        m = get_mission_manager()
        # heist_score_safe is a gated stage-2 mission → locked & hidden.
        assert m.get_mission("heist_score_safe").locked is True
        ids = {x["id"] for x in m.list_available()}
        assert "heist_score_safe" not in ids
        # entry mission stays available.
        assert "heist_lab_prototype" in ids

    def test_gating_off_keeps_all_available(self, mgr):
        # Default fixture has gating disabled.
        assert mgr.get_mission("heist_score_safe").locked is False
        ids = {x["id"] for x in mgr.list_available()}
        assert "heist_score_safe" in ids

    def test_success_branch_unlocks_next_stage(self, _isolate, monkeypatch, tmp_path):
        _isolate["mission.chains.gating_enabled"] = True
        fake = FakePlayerState()
        import engine.world.mission as mission_mod
        monkeypatch.setattr(mission_mod, "get_player_state", lambda: fake, raising=True)
        reset_mission_manager()
        from engine.world.mission import get_mission_manager
        m = get_mission_manager()

        assert m.get_mission("heist_score_safe").locked is True
        result = _complete(m, "heist_lab_prototype")
        # Success branch unlocks the big score; failure branch target stays locked.
        assert "heist_score_safe" in result["unlocked"]
        assert m.get_mission("heist_score_safe").locked is False
        assert m.get_mission("heist_colosseum_credits").locked is True
        assert "heist_lab_prototype" in m.get_mission("heist_score_safe").unlocked_by

    def test_failure_branch_unlocks_alternate(self, _isolate, monkeypatch):
        _isolate["mission.chains.gating_enabled"] = True
        fake = FakePlayerState()
        import engine.world.mission as mission_mod
        monkeypatch.setattr(mission_mod, "get_player_state", lambda: fake, raising=True)
        reset_mission_manager()
        from engine.world.mission import get_mission_manager
        m = get_mission_manager()

        m.accept("heist_lab_prototype")
        result = m.fail("heist_lab_prototype", reason="botched")
        # Failure routes to the smaller arena job, not the big score.
        assert "heist_colosseum_credits" in result["unlocked"]
        assert m.get_mission("heist_colosseum_credits").locked is False
        assert m.get_mission("heist_score_safe").locked is True

    def test_standing_gated_branch_requires_threshold(self, _isolate, monkeypatch):
        _isolate["mission.chains.gating_enabled"] = True
        fake = FakePlayerState()
        import engine.world.mission as mission_mod
        monkeypatch.setattr(mission_mod, "get_player_state", lambda: fake, raising=True)
        reset_mission_manager()
        from engine.world.mission import get_mission_manager
        m = get_mission_manager()

        # faction_war: enforcers → obscura → (Ghost_Net>=10) alliance.
        _complete(m, "hit_velvet_pit_enforcers")
        assert m.get_mission("deal_obscura_faction").locked is False

        # Complete obscura but Ghost_Net standing is 0 → alliance stays locked.
        _complete(m, "deal_obscura_faction")
        assert m.get_mission("deal_command_center_alliance").locked is True


class TestChainRegistry:
    def test_branch_condition_default_always(self):
        stage = ChainStage(mission_id="a", branches=[ChainBranch(unlocks="b")])
        assert stage.resolve({"outcome": "failed"}) == ["b"]

    def test_first_match_wins_without_allow_multiple(self):
        stage = ChainStage(
            mission_id="a",
            branches=[
                ChainBranch(unlocks="b", condition=lambda c: c.get("outcome") == "completed"),
                ChainBranch(unlocks="c"),
            ],
        )
        assert stage.resolve({"outcome": "completed"}) == ["b"]
        assert stage.resolve({"outcome": "failed"}) == ["c"]

    def test_allow_multiple_unlocks_all(self):
        stage = ChainStage(
            mission_id="a",
            allow_multiple=True,
            branches=[ChainBranch(unlocks="b"), ChainBranch(unlocks="c")],
        )
        assert stage.resolve({}) == ["b", "c"]

    def test_prerequisites_and_gating(self):
        reg = ChainRegistry()
        assert reg.is_gated("heist_score_safe") is True
        assert "heist_lab_prototype" in reg.prerequisites("heist_score_safe")
        assert reg.is_gated("heist_lab_prototype") is False
        assert reg.chain_for_mission("heist_score_safe").id == "heist_escalation"

    def test_custom_chain_registry(self):
        chain = MissionChain(
            id="t", title="T", description="d",
            stages=[
                ChainStage(mission_id="m1", branches=[ChainBranch(unlocks="m2")]),
                ChainStage(mission_id="m2"),
            ],
        )
        reg = ChainRegistry(chains=[chain])
        assert reg.resolve_unlocks("m1", {"outcome": "completed"}) == ["m2"]
        assert reg.all_entry_missions() == ["m1"]


# ──── Crew gating ────────────────────────────────────────────────────────────


class TestCrewGating:
    def test_busy_roster_member_rejected(self, mgr, ps, monkeypatch):
        crew = FakeCrewManager({"viktor": FakeCrewMember(available=False)})
        import engine.world.crew as crew_mod
        monkeypatch.setattr(crew_mod, "get_crew_manager", lambda: crew, raising=True)

        mgr.accept("recon_corp_signal")
        result = mgr.assign_crew("recon_corp_signal", ["viktor"])
        assert result["success"] is False
        assert "viktor" in result["unavailable"]
        assert mgr.get_mission("recon_corp_signal").assigned_crew == []

    def test_available_roster_member_assigned(self, mgr, ps, monkeypatch):
        crew = FakeCrewManager({"viktor": FakeCrewMember(available=True)})
        import engine.world.crew as crew_mod
        monkeypatch.setattr(crew_mod, "get_crew_manager", lambda: crew, raising=True)

        mgr.accept("recon_corp_signal")
        result = mgr.assign_crew("recon_corp_signal", ["viktor"])
        assert result["success"] is True
        assert "viktor" in result["assigned_crew"]

    def test_unknown_member_fails_open(self, mgr, ps, monkeypatch):
        crew = FakeCrewManager({})  # empty roster
        import engine.world.crew as crew_mod
        monkeypatch.setattr(crew_mod, "get_crew_manager", lambda: crew, raising=True)

        mgr.accept("recon_corp_signal")
        result = mgr.assign_crew("recon_corp_signal", ["ghost"])
        assert result["success"] is True
        assert "ghost" in result["assigned_crew"]

    def test_enforcement_disabled_allows_busy(self, mgr, ps, monkeypatch, _isolate):
        _isolate["mission.crew.enforce_availability"] = False
        crew = FakeCrewManager({"viktor": FakeCrewMember(available=False)})
        import engine.world.crew as crew_mod
        monkeypatch.setattr(crew_mod, "get_crew_manager", lambda: crew, raising=True)

        mgr.accept("recon_corp_signal")
        result = mgr.assign_crew("recon_corp_signal", ["viktor"])
        assert result["success"] is True
