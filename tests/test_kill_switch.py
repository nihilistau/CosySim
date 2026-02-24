"""Tests for KillSwitch — quality gate that cancels bad generations."""

import pytest

from engine.pipeline.kill_switch import KillDecision, KillSwitch
from engine.pipeline.pipeline_result import (
    PipelineConfig,
    WatcherAnalysis,
    WatcherSignal,
)


class TestKillDecision:
    def test_default_no_kill(self):
        d = KillDecision()
        assert not d.should_kill
        assert d.retry_allowed
        assert d.reason == ""

    def test_kill_with_reason(self):
        d = KillDecision(should_kill=True, reason="repetition", confidence=0.95)
        assert d.should_kill
        assert d.confidence == 0.95


class TestKillSwitch:
    def setup_method(self):
        self.config = PipelineConfig(
            kill_switch_enabled=True,
            kill_threshold=0.3,
            max_retries=2,
            retry_temperature_decay=0.15,
        )
        self.ks = KillSwitch(self.config)

    def test_enabled(self):
        assert self.ks.enabled

    def test_disabled(self):
        config = PipelineConfig(kill_switch_enabled=False)
        ks = KillSwitch(config)
        assert not ks.enabled

    def test_disabled_always_passes(self):
        config = PipelineConfig(kill_switch_enabled=False)
        ks = KillSwitch(config)
        analysis = WatcherAnalysis(
            acceptability=0.0,
            signals=[WatcherSignal.KILL],
        )
        decision = ks.evaluate(analysis, "bad content")
        assert not decision.should_kill

    def test_good_content_passes(self):
        analysis = WatcherAnalysis(acceptability=0.9)
        decision = self.ks.evaluate(analysis, "great content")
        assert not decision.should_kill

    def test_low_acceptability_kills(self):
        analysis = WatcherAnalysis(acceptability=0.1)
        decision = self.ks.evaluate(analysis, "bad content")
        assert decision.should_kill
        assert "0.10" in decision.reason
        assert decision.retry_allowed

    def test_kill_signal_kills(self):
        analysis = WatcherAnalysis(
            acceptability=0.5,
            signals=[WatcherSignal.KILL],
            kill_reason="Repetition detected",
        )
        decision = self.ks.evaluate(analysis, "repeated content")
        assert decision.should_kill
        assert "Repetition" in decision.reason

    def test_on_kill_increments_retry(self):
        assert self.ks.retry_count == 0
        self.ks.on_kill("bad content 1")
        assert self.ks.retry_count == 1
        self.ks.on_kill("bad content 2")
        assert self.ks.retry_count == 2

    def test_can_retry_limit(self):
        assert self.ks.can_retry  # 0 < 2
        self.ks.on_kill("bad 1")
        assert self.ks.can_retry  # 1 < 2
        self.ks.on_kill("bad 2")
        assert not self.ks.can_retry  # 2 == 2

    def test_retry_not_allowed_when_exhausted(self):
        self.ks.on_kill("bad 1")
        self.ks.on_kill("bad 2")
        analysis = WatcherAnalysis(acceptability=0.1, signals=[WatcherSignal.KILL])
        decision = self.ks.evaluate(analysis, "bad 3")
        assert decision.should_kill
        assert not decision.retry_allowed

    def test_killed_contents_tracked(self):
        self.ks.on_kill("first bad")
        self.ks.on_kill("second bad")
        contents = self.ks.killed_contents
        assert contents == ["first bad", "second bad"]

    def test_reset_clears_state(self):
        self.ks.on_kill("bad")
        self.ks.reset()
        assert self.ks.retry_count == 0
        assert self.ks.killed_contents == []
        assert self.ks.can_retry

    def test_best_content_tracking(self):
        # First attempt — bad
        analysis1 = WatcherAnalysis(acceptability=0.2)
        self.ks.evaluate(analysis1, "short bad")
        # Second attempt — slightly better
        analysis2 = WatcherAnalysis(acceptability=0.4)
        self.ks.evaluate(analysis2, "longer better content")
        assert self.ks.get_best_content() == "longer better content"


class TestModifyForRetry:
    def setup_method(self):
        self.config = PipelineConfig(
            retry_temperature_decay=0.15,
            max_retries=2,
        )
        self.ks = KillSwitch(self.config)

    def test_temperature_decay(self):
        self.ks.on_kill("bad 1")
        result = self.ks.modify_for_retry(
            messages=[{"role": "system", "content": "Be nice"}],
            original_temperature=0.7,
        )
        # After 1 retry: 0.7 - 0.15 * 1 = 0.55
        assert result["temperature"] == pytest.approx(0.55, abs=0.01)

    def test_temperature_double_decay(self):
        self.ks.on_kill("bad 1")
        self.ks.on_kill("bad 2")
        result = self.ks.modify_for_retry(
            messages=[{"role": "system", "content": "Be nice"}],
            original_temperature=0.7,
        )
        # After 2 retries: 0.7 - 0.15 * 2 = 0.40
        assert result["temperature"] == pytest.approx(0.40, abs=0.01)

    def test_temperature_floor(self):
        """Temperature should not go below 0.1."""
        self.ks.on_kill("bad 1")
        result = self.ks.modify_for_retry(
            messages=[{"role": "system", "content": "Be nice"}],
            original_temperature=0.2,
        )
        assert result["temperature"] >= 0.1

    def test_constraint_appended_to_system(self):
        self.ks.on_kill("bad")
        result = self.ks.modify_for_retry(
            messages=[{"role": "system", "content": "Be nice"}],
            kill_reason="Repetition",
        )
        msg = result["messages"][0]["content"]
        assert "rejected" in msg.lower()
        assert "Repetition" in msg

    def test_constraint_inserted_without_system(self):
        self.ks.on_kill("bad")
        result = self.ks.modify_for_retry(
            messages=[{"role": "user", "content": "Hello"}],
            kill_reason="Off topic",
        )
        assert result["messages"][0]["role"] == "system"
        assert "rejected" in result["messages"][0]["content"].lower()

    def test_original_messages_not_mutated(self):
        original = [{"role": "system", "content": "Be nice"}]
        self.ks.on_kill("bad")
        self.ks.modify_for_retry(original, kill_reason="test")
        assert original[0]["content"] == "Be nice"

    def test_default_temperature(self):
        """When no temperature provided, defaults to 0.7."""
        self.ks.on_kill("bad")
        result = self.ks.modify_for_retry(messages=[], original_temperature=None)
        # 0.7 - 0.15 * 1 = 0.55
        assert result["temperature"] == pytest.approx(0.55, abs=0.01)

    def test_short_directive_on_many_retries(self):
        """After 2+ retries, adds 'SHORT and direct' constraint."""
        self.ks.on_kill("bad 1")
        self.ks.on_kill("bad 2")
        result = self.ks.modify_for_retry(
            messages=[{"role": "system", "content": "Be nice"}],
            kill_reason="",
        )
        assert "SHORT" in result["messages"][0]["content"]
