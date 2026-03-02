"""Tests for DialogueGate interceptor and Reputation HUD (Track C, v0.71)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_ctx(**kwargs) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "agent_id": "lola",
        "player_id": "player",
        "system_prompt": "You are Lola.",
        "reply": "",
        "skip_llm": False,
    }
    ctx.update(kwargs)
    return ctx


def _fw_with_rep(reputation: int) -> MagicMock:
    fw = MagicMock()
    fw.get.return_value = reputation
    fw.set = MagicMock()
    return fw


# ──────────────────────────────────────────────────────────────────────────────
#  DialogueGateInterceptor
# ──────────────────────────────────────────────────────────────────────────────

class TestDialogueGateInterceptor:

    def _gate(self, reputation: int, config: Dict | None = None):
        from engine.agents.dialogue_gate import DialogueGateInterceptor
        gate = DialogueGateInterceptor(config=config)
        gate._get_reputation = lambda char_id, player_id: reputation
        return gate

    # ── Hard gate (refuse) ────────────────────────────────────────────────────

    def test_pre_call_blocks_below_refuse_threshold(self):
        ctx = _make_ctx()
        self._gate(-51).pre_call(ctx)
        assert ctx["skip_llm"] is True

    def test_pre_call_block_sets_reply(self):
        ctx = _make_ctx()
        self._gate(-75).pre_call(ctx)
        assert ctx["reply"] != ""
        assert "nothing to say" in ctx["reply"]

    def test_pre_call_refusal_includes_score(self):
        ctx = _make_ctx()
        self._gate(-80).pre_call(ctx)
        assert "-80" in ctx["reply"]

    def test_pre_call_not_blocked_exactly_at_refuse_threshold(self):
        """Boundary: -50 is NOT refused (< not <=)."""
        ctx = _make_ctx()
        self._gate(-50).pre_call(ctx)
        assert ctx.get("skip_llm") is not True

    def test_pre_call_blocks_at_minus_100(self):
        ctx = _make_ctx()
        self._gate(-100).pre_call(ctx)
        assert ctx["skip_llm"] is True

    # ── Hostile tone ──────────────────────────────────────────────────────────

    def test_pre_call_hostile_tone_injected(self):
        ctx = _make_ctx()
        self._gate(-30).pre_call(ctx)
        assert "[TONE:HOSTILE]" in ctx["system_prompt"]
        assert ctx.get("skip_llm") is not True

    def test_pre_call_hostile_tone_at_minus_21(self):
        ctx = _make_ctx()
        self._gate(-21).pre_call(ctx)
        assert "[TONE:HOSTILE]" in ctx["system_prompt"]

    def test_pre_call_no_tone_at_minus_20_boundary(self):
        ctx = _make_ctx()
        original = ctx["system_prompt"]
        self._gate(-20).pre_call(ctx)
        assert ctx["system_prompt"] == original

    # ── Neutral (no modification) ─────────────────────────────────────────────

    def test_pre_call_neutral_zero_noop(self):
        ctx = _make_ctx()
        original = ctx["system_prompt"]
        self._gate(0).pre_call(ctx)
        assert ctx["system_prompt"] == original
        assert ctx.get("skip_llm") is not True

    def test_pre_call_neutral_positive_19_noop(self):
        ctx = _make_ctx()
        original = ctx["system_prompt"]
        self._gate(19).pre_call(ctx)
        assert ctx["system_prompt"] == original

    # ── Friendly tone ─────────────────────────────────────────────────────────

    def test_pre_call_friendly_tone_at_20(self):
        ctx = _make_ctx()
        self._gate(20).pre_call(ctx)
        assert "[TONE:FRIENDLY]" in ctx["system_prompt"]

    def test_pre_call_friendly_tone_at_30(self):
        ctx = _make_ctx()
        self._gate(30).pre_call(ctx)
        assert "[TONE:FRIENDLY]" in ctx["system_prompt"]

    # ── Intimate tone ─────────────────────────────────────────────────────────

    def test_pre_call_intimate_tone_at_50(self):
        ctx = _make_ctx()
        self._gate(50).pre_call(ctx)
        assert "[TONE:INTIMATE]" in ctx["system_prompt"]

    def test_pre_call_intimate_tone_at_100(self):
        ctx = _make_ctx()
        self._gate(100).pre_call(ctx)
        assert "[TONE:INTIMATE]" in ctx["system_prompt"]

    def test_pre_call_intimate_overrides_friendly(self):
        """Score >= 50 should give intimate, not friendly."""
        ctx = _make_ctx()
        self._gate(60).pre_call(ctx)
        assert "[TONE:INTIMATE]" in ctx["system_prompt"]
        assert "[TONE:FRIENDLY]" not in ctx["system_prompt"]

    # ── No agent_id ───────────────────────────────────────────────────────────

    def test_pre_call_no_agent_id_is_noop(self):
        ctx = _make_ctx(agent_id="")
        original = ctx["system_prompt"]
        self._gate(50).pre_call(ctx)
        assert ctx["system_prompt"] == original

    # ── Custom thresholds ─────────────────────────────────────────────────────

    def test_custom_refuse_threshold(self):
        gate = self._gate(-60, config={"refuse_threshold": -70})
        ctx = _make_ctx()
        gate.pre_call(ctx)
        assert ctx.get("skip_llm") is not True

    def test_custom_friendly_threshold_lower(self):
        gate = self._gate(10, config={"friendly_threshold": 5})
        ctx = _make_ctx()
        gate.pre_call(ctx)
        assert "[TONE:FRIENDLY]" in ctx["system_prompt"]

    # ── post_call ─────────────────────────────────────────────────────────────

    def test_post_call_noop(self):
        ctx = _make_ctx(reply="Hi there!")
        self._gate(0).post_call(ctx)
        assert ctx["reply"] == "Hi there!"

    def test_post_call_does_not_alter_blocked_reply(self):
        """skip_llm path: reply set in pre_call is left intact."""
        ctx = _make_ctx()
        gate = self._gate(-80)
        gate.pre_call(ctx)
        locked_reply = ctx["reply"]
        gate.post_call(ctx)
        assert ctx["reply"] == locked_reply

    # ── Class attributes ──────────────────────────────────────────────────────

    def test_name_attribute(self):
        from engine.agents.dialogue_gate import DialogueGateInterceptor
        assert DialogueGateInterceptor.name == "dialogue_gate"

    def test_priority_below_personality_guard(self):
        from engine.agents.dialogue_gate import DialogueGateInterceptor
        assert DialogueGateInterceptor.priority < 50

    def test_inherits_interceptor_base(self):
        from engine.agents.dialogue_gate import DialogueGateInterceptor
        from engine.mcp.comms_framework import InterceptorBase
        assert issubclass(DialogueGateInterceptor, InterceptorBase)

    def test_get_reputation_returns_zero_on_error(self):
        from engine.agents.dialogue_gate import DialogueGateInterceptor
        gate = DialogueGateInterceptor()
        with patch("engine.agents.dialogue_gate.get_framework", side_effect=RuntimeError("boom")):
            rep = gate._get_reputation("lola", "player")
        assert rep == 0


# ──────────────────────────────────────────────────────────────────────────────
#  _rep_label
# ──────────────────────────────────────────────────────────────────────────────

class TestRepLabel:

    @pytest.fixture(autouse=True)
    def _import(self):
        from engine.skills.builtin.reputation_skills import _rep_label
        self.fn = _rep_label

    def test_devoted_high(self):      assert self.fn(100) == "devoted"
    def test_devoted_boundary(self):  assert self.fn(75)  == "devoted"
    def test_trusted_below(self):     assert self.fn(74)  == "trusted"
    def test_trusted_boundary(self):  assert self.fn(50)  == "trusted"
    def test_friendly_below(self):    assert self.fn(49)  == "friendly"
    def test_friendly_boundary(self): assert self.fn(20)  == "friendly"
    def test_neutral_pos(self):       assert self.fn(19)  == "neutral"
    def test_neutral_zero(self):      assert self.fn(0)   == "neutral"
    def test_neutral_neg(self):       assert self.fn(-19) == "neutral"
    def test_wary_boundary(self):     assert self.fn(-20) == "wary"
    def test_wary_inner(self):        assert self.fn(-49) == "wary"
    def test_hostile_boundary(self):  assert self.fn(-50) == "hostile"
    def test_hostile_inner(self):     assert self.fn(-74) == "hostile"
    def test_enemy_boundary(self):    assert self.fn(-75) == "enemy"
    def test_enemy_max(self):         assert self.fn(-100) == "enemy"


# ──────────────────────────────────────────────────────────────────────────────
#  Reputation skills
# ──────────────────────────────────────────────────────────────────────────────

class TestReputationSkills:

    def _fw(self, store: dict | None = None) -> MagicMock:
        _store: dict = dict(store or {})

        def _get(key, default=0):
            return _store.get(key, default)

        def _set(key, value):
            _store[key] = value

        fw = MagicMock()
        fw.get.side_effect = _get
        fw.set.side_effect = _set
        fw._store = _store
        return fw

    # get_reputation

    def test_get_rep_default_neutral(self):
        from engine.skills.builtin.reputation_skills import get_reputation
        fw = self._fw()
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = get_reputation("lola")
        assert "+0" in r and "neutral" in r

    def test_get_rep_positive(self):
        from engine.skills.builtin.reputation_skills import get_reputation
        fw = self._fw({"characters.lola.reputation.player": 60})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = get_reputation("lola")
        assert "+60" in r and "trusted" in r

    def test_get_rep_negative(self):
        from engine.skills.builtin.reputation_skills import get_reputation
        fw = self._fw({"characters.viktor.reputation.player": -30})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = get_reputation("viktor")
        assert "-30" in r and "wary" in r

    def test_get_rep_custom_player(self):
        from engine.skills.builtin.reputation_skills import get_reputation
        fw = self._fw({"characters.aria.reputation.alex": 80})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = get_reputation("aria", player_id="alex")
        assert "+80" in r and "devoted" in r

    # modify_reputation

    def test_modify_increase(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw({"characters.lola.reputation.player": 20})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            modify_reputation("lola", 15)
        assert fw._store["characters.lola.reputation.player"] == 35

    def test_modify_decrease(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw({"characters.lola.reputation.player": 10})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            modify_reputation("lola", -25)
        assert fw._store["characters.lola.reputation.player"] == -15

    def test_modify_clamp_max(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw({"characters.lola.reputation.player": 90})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            modify_reputation("lola", 50)
        assert fw._store["characters.lola.reputation.player"] == 100

    def test_modify_clamp_min(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw({"characters.lola.reputation.player": -90})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            modify_reputation("lola", -50)
        assert fw._store["characters.lola.reputation.player"] == -100

    def test_modify_already_at_max_noop(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw({"characters.lola.reputation.player": 100})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            modify_reputation("lola", 1)
        assert fw._store["characters.lola.reputation.player"] == 100

    def test_modify_already_at_min_noop(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw({"characters.lola.reputation.player": -100})
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            modify_reputation("lola", -1)
        assert fw._store["characters.lola.reputation.player"] == -100

    def test_modify_includes_reason(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw()
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = modify_reputation("lola", 5, reason="gift given")
        assert "gift given" in r

    def test_modify_no_reason_clean_output(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw()
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = modify_reputation("lola", 5)
        assert "reason" not in r

    def test_modify_positive_delta_emoji(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw()
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = modify_reputation("lola", 10)
        assert "📈" in r

    def test_modify_negative_delta_emoji(self):
        from engine.skills.builtin.reputation_skills import modify_reputation
        fw = self._fw()
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = modify_reputation("lola", -10)
        assert "📉" in r

    # get_all_reputations

    def test_get_all_empty(self):
        from engine.skills.builtin.reputation_skills import get_all_reputations
        fw = MagicMock()
        fw.get.return_value = {}
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = get_all_reputations()
        assert "No character" in r

    def test_get_all_lists_chars(self):
        from engine.skills.builtin.reputation_skills import get_all_reputations
        fw = MagicMock()
        fw.get.return_value = {
            "lola":  {"reputation": {"player": 40}},
            "viktor": {"reputation": {"player": -30}},
        }
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = get_all_reputations()
        assert "lola" in r and "viktor" in r
        assert "+40" in r and "-30" in r

    def test_get_all_non_dict_char_no_crash(self):
        from engine.skills.builtin.reputation_skills import get_all_reputations
        fw = MagicMock()
        fw.get.return_value = {"lola": "string_value"}
        with patch("engine.skills.builtin.reputation_skills.get_framework", return_value=fw):
            r = get_all_reputations()
        assert "lola" in r


# ──────────────────────────────────────────────────────────────────────────────
#  Static asset existence + content
# ──────────────────────────────────────────────────────────────────────────────

_SHARED = Path(__file__).parent.parent / "content" / "shared"


class TestAssetFiles:

    def test_reputation_hud_html_exists(self):
        assert (_SHARED / "templates" / "reputation_hud.html").exists()

    def test_reputation_css_exists(self):
        assert (_SHARED / "static" / "css" / "reputation.css").exists()

    def test_reputation_js_exists(self):
        assert (_SHARED / "static" / "js" / "reputation.js").exists()

    def test_hud_has_hud_element(self):
        t = (_SHARED / "templates" / "reputation_hud.html").read_text()
        assert "cs-rep-hud" in t

    def test_hud_has_score_element(self):
        t = (_SHARED / "templates" / "reputation_hud.html").read_text()
        assert "cs-rep-score" in t

    def test_hud_has_bar_element(self):
        t = (_SHARED / "templates" / "reputation_hud.html").read_text()
        assert "cs-rep-bar" in t

    def test_hud_has_label_element(self):
        t = (_SHARED / "templates" / "reputation_hud.html").read_text()
        assert "cs-rep-label" in t

    def test_hud_has_name_element(self):
        t = (_SHARED / "templates" / "reputation_hud.html").read_text()
        assert "cs-rep-name" in t

    def test_css_has_hud_class(self):
        c = (_SHARED / "static" / "css" / "reputation.css").read_text(encoding="utf-8")
        assert ".cs-rep-hud" in c

    def test_css_has_bar_class(self):
        c = (_SHARED / "static" / "css" / "reputation.css").read_text(encoding="utf-8")
        assert ".cs-rep-bar" in c

    def test_css_has_all_disposition_colours(self):
        c = (_SHARED / "static" / "css" / "reputation.css").read_text(encoding="utf-8")
        for label in ("devoted", "trusted", "friendly", "neutral", "wary", "hostile", "enemy"):
            assert label in c, f"Missing disposition colour for: {label}"

    def test_css_has_animation(self):
        c = (_SHARED / "static" / "css" / "reputation.css").read_text(encoding="utf-8")
        assert "@keyframes" in c

    def test_css_z_index_below_portrait(self):
        c = (_SHARED / "static" / "css" / "reputation.css").read_text(encoding="utf-8")
        assert "800" in c

    def test_js_has_class(self):
        j = (_SHARED / "static" / "js" / "reputation.js").read_text()
        assert "ReputationHUD" in j

    def test_js_has_update_method(self):
        j = (_SHARED / "static" / "js" / "reputation.js").read_text()
        assert "update(" in j

    def test_js_reputation_update_event(self):
        j = (_SHARED / "static" / "js" / "reputation.js").read_text()
        assert "reputation_update" in j

    def test_js_character_speaking_event(self):
        j = (_SHARED / "static" / "js" / "reputation.js").read_text()
        assert "character_speaking" in j

    def test_js_reputation_data_event(self):
        j = (_SHARED / "static" / "js" / "reputation.js").read_text()
        assert "reputation_data" in j


# ──────────────────────────────────────────────────────────────────────────────
#  Shared __init__ injects reputation assets
# ──────────────────────────────────────────────────────────────────────────────

class TestSharedInjection:

    def test_inject_tags_include_reputation_css(self):
        from content.shared import _INJECT_TAGS
        assert "reputation.css" in _INJECT_TAGS

    def test_inject_tags_include_reputation_js(self):
        from content.shared import _INJECT_TAGS
        assert "reputation.js" in _INJECT_TAGS
