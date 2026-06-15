"""Unit tests for OR-T1 — Oracle omniscience (reads the comms log).

Covers:
* comms-aware fortunes weave a REAL seeded log entry when ``fortune_chance``=1.0
  and mark it observed by ``'oracle'``;
* fortunes fall back to a plain fortune when no comms exist or the budget roll
  fails (and never crash);
* the ``max_refs`` privacy cap is respected (never dumps everything);
* ``read_the_signal`` returns a real finding sourced from seeded comms
  (low-security hack target / player mention / closest pair) and grants the
  bounded reward;
* sensitive comms are skipped under the privacy budget.

Uses an isolated temp ``GlobalCommsLog`` (no real data touched) and a mock
PlayerState / PhoneOS at the boundary.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.world import oracle_comms
from engine.world.comms_log import GlobalCommsLog


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def log(tmp_path, monkeypatch) -> GlobalCommsLog:
    """Return an isolated comms log wired in as the process singleton."""
    cl = GlobalCommsLog(path=tmp_path / "comms_log.db")
    monkeypatch.setattr(oracle_comms, "_get_log", lambda: cl)
    return cl


@pytest.fixture
def mock_player(monkeypatch):
    """Patch get_player_state with a recording mock; return the mock."""
    granted = SimpleNamespace(credits=0, items=[])

    class _PS:
        def earn_credits(self, amount, reason=""):
            granted.credits += amount
            return granted.credits

        def add_item(self, item):
            granted.items.append(item)

    import engine.world.player_state as ps_mod
    monkeypatch.setattr(ps_mod, "get_player_state", lambda: _PS())
    return granted


# ── comms-aware fortunes ───────────────────────────────────────────────


def test_fortune_weaves_real_entry_and_marks_observed(log, monkeypatch):
    rid = log.log("npc_dm", "char-mira", ["char-frankie"], "have you seen the runner?")
    monkeypatch.setattr(oracle_comms.random, "random", lambda: 0.0)  # always weave

    entries = oracle_comms.select_entries()
    assert entries, "expected a seeded entry to be selectable"
    woven = oracle_comms.weave_into("The streams converge.", entries)

    assert woven != "The streams converge."
    assert len(woven) > len("The streams converge.")
    # referenced entry is marked observed by the oracle
    row = log.recent(1)[0]
    assert row["id"] == rid
    assert "oracle" in row["observed_by"]


def test_fortune_falls_back_when_no_comms(log):
    # empty log → no entries → weave is a no-op
    entries = oracle_comms.select_entries()
    assert entries == []
    assert oracle_comms.weave_into("plain fortune", entries) == "plain fortune"


def test_fortune_budget_roll_failure_keeps_plain(log, monkeypatch):
    """When the budget roll fails, the scene returns the base fortune unchanged."""
    log.log("npc_dm", "char-mira", ["char-frankie"], "psst")
    # fortune_chance default 0.4; force the roll to fail (>= chance).
    monkeypatch.setattr(oracle_comms.random, "random", lambda: 0.99)

    from content.scenes.oracle.oracle_scene import OracleScene
    woven = OracleScene._maybe_weave_comms(SimpleNamespace(), "atmospheric base")
    assert woven == "atmospheric base"


def test_max_refs_cap_is_respected(log, monkeypatch):
    """Even with many entries, never reference more than max_refs."""
    for i in range(10):
        log.log("npc_dm", f"char-a{i}", [f"char-b{i}"], f"chatter {i}")
    monkeypatch.setattr(
        oracle_comms, "get_oracle_comms_config",
        lambda: {**oracle_comms._DEFAULTS, "max_refs": 2},
    )
    entries = oracle_comms.select_entries()
    assert len(entries) <= 2


def test_sensitive_entries_skipped(log):
    log.log(
        "npc_dm", "char-aria", ["char-lola"], "private moment",
        kind="intimate", metadata={"sensitive": True},
    )
    entries = oracle_comms.select_entries()
    assert entries == [], "sensitive entries must be excluded from selection"


# ── read_the_signal ────────────────────────────────────────────────────


def test_signal_finds_low_security_hack_target(log, monkeypatch, mock_player):
    log.log("npc_dm", "char-viktor", ["char-frankie"], "the vault is open tonight")

    import engine.world.phone_os as phone_mod
    fake_os = SimpleNamespace(effective_security=lambda cid: 1)
    monkeypatch.setattr(phone_mod, "get_phone_os", lambda: fake_os)

    from engine.skills.builtin.oracle_skills import read_the_signal
    result = read_the_signal()

    assert "security" in result.lower() or "wall is thin" in result.lower()
    # bounded reward granted
    assert mock_player.credits == 75
    assert "intel_fragment" in mock_player.items
    # referenced entry marked observed
    assert "oracle" in log.recent(1)[0]["observed_by"]


def test_signal_finds_player_interest(log, monkeypatch, mock_player):
    # high-security NPCs so hack path is skipped; NPC names the player.
    log.log("npc_dm", "char-mira", ["char-frankie"], "keep an eye on user, they're trouble")

    import engine.world.phone_os as phone_mod
    monkeypatch.setattr(
        phone_mod, "get_phone_os",
        lambda: SimpleNamespace(effective_security=lambda cid: 9),
    )

    finding = oracle_comms.find_signal()
    assert finding is not None
    assert finding["kind"] in ("player_interest", "closest_pair")


def test_signal_closest_pair(log, monkeypatch):
    for _ in range(3):
        log.log("npc_dm", "char-lola", ["char-viktor"], "again")
    log.log("npc_dm", "char-aria", ["char-frankie"], "once")

    import engine.world.phone_os as phone_mod
    monkeypatch.setattr(
        phone_mod, "get_phone_os",
        lambda: SimpleNamespace(effective_security=lambda cid: 9),
    )

    finding = oracle_comms.find_signal()
    assert finding is not None
    if finding["kind"] == "closest_pair":
        assert set(finding["pair"]) == {"char-lola", "char-viktor"}


def test_signal_no_comms_returns_silence(log, mock_player):
    from engine.skills.builtin.oracle_skills import read_the_signal
    result = read_the_signal()
    assert "silence" in result.lower() or "nothing" in result.lower()
    # no reward when nothing found
    assert mock_player.credits == 0
    assert mock_player.items == []
