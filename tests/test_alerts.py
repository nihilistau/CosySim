"""Tests for AlertEngine — threshold-based green/yellow/red alerting."""

import time
import pytest

from engine.observability.alerts import Alert, AlertEngine, AlertRule


class TestAlertRule:
    def test_basic_rule(self):
        rule = AlertRule(node="gpu", metric="vram_pct", yellow=80, red=95)
        assert rule.node == "gpu"
        assert rule.yellow == 80
        assert rule.red == 95
        assert rule.window == 10
        assert not rule.invert


class TestAlertEngine:
    def setup_method(self):
        self.rules = [
            AlertRule(node="gpu_primary", metric="vram_pct", yellow=80, red=95),
            AlertRule(node="pipeline", metric="latency_ms", yellow=500, red=2000),
            AlertRule(node="pipeline", metric="tps", yellow=10, red=5, invert=True),
        ]
        self.engine = AlertEngine(rules=self.rules)

    def test_initial_status_green(self):
        status = self.engine.get_status_map()
        assert status["gpu_primary"] == "green"
        assert status["pipeline"] == "green"

    def test_no_samples_no_alerts(self):
        alerts = self.engine.evaluate()
        assert alerts == []

    def test_green_stays_green(self):
        self.engine.feed("gpu_primary", "vram_pct", 50.0)
        alerts = self.engine.evaluate()
        assert alerts == []
        assert self.engine.get_node_status("gpu_primary") == "green"

    def test_yellow_alert(self):
        self.engine.feed("gpu_primary", "vram_pct", 85.0)
        alerts = self.engine.evaluate()
        assert len(alerts) == 1
        assert alerts[0].level == "yellow"
        assert alerts[0].prev_level == "green"
        assert alerts[0].node == "gpu_primary"

    def test_red_alert(self):
        self.engine.feed("gpu_primary", "vram_pct", 97.0)
        alerts = self.engine.evaluate()
        assert len(alerts) == 1
        assert alerts[0].level == "red"

    def test_no_duplicate_alerts(self):
        """Same level should not fire again."""
        self.engine.feed("gpu_primary", "vram_pct", 85.0)
        alerts1 = self.engine.evaluate()
        assert len(alerts1) == 1

        self.engine.feed("gpu_primary", "vram_pct", 87.0)
        alerts2 = self.engine.evaluate()
        assert alerts2 == []  # Still yellow, no change

    def test_recovery_to_green(self):
        self.engine.feed("gpu_primary", "vram_pct", 85.0)
        self.engine.evaluate()
        assert self.engine.get_node_status("gpu_primary") == "yellow"

        # Recover
        self.engine.feed("gpu_primary", "vram_pct", 50.0)
        # Need enough samples to bring average below threshold
        for _ in range(20):
            self.engine.feed("gpu_primary", "vram_pct", 50.0)
        alerts = self.engine.evaluate()
        assert any(a.level == "green" for a in alerts)

    def test_inverted_metric(self):
        """Low TPS should trigger alert (invert=True)."""
        self.engine.feed("pipeline", "tps", 3.0)  # Below red=5
        alerts = self.engine.evaluate()
        red_alerts = [a for a in alerts if a.node == "pipeline" and a.metric == "tps"]
        assert len(red_alerts) == 1
        assert red_alerts[0].level == "red"

    def test_inverted_metric_high_ok(self):
        """High TPS should be green (invert=True)."""
        self.engine.feed("pipeline", "tps", 50.0)
        alerts = self.engine.evaluate()
        tps_alerts = [a for a in alerts if a.metric == "tps"]
        assert tps_alerts == []  # Still green, no change

    def test_multiple_nodes(self):
        self.engine.feed("gpu_primary", "vram_pct", 97.0)
        self.engine.feed("pipeline", "latency_ms", 600.0)
        alerts = self.engine.evaluate()
        nodes = {a.node for a in alerts}
        assert "gpu_primary" in nodes
        assert "pipeline" in nodes

    def test_get_worst_level(self):
        assert self.engine.get_worst_level() == "green"
        self.engine.feed("pipeline", "latency_ms", 600.0)
        self.engine.evaluate()
        assert self.engine.get_worst_level() == "yellow"
        self.engine.feed("gpu_primary", "vram_pct", 97.0)
        self.engine.evaluate()
        assert self.engine.get_worst_level() == "red"

    def test_reset_node(self):
        self.engine.feed("gpu_primary", "vram_pct", 97.0)
        self.engine.evaluate()
        assert self.engine.get_node_status("gpu_primary") == "red"
        self.engine.reset_node("gpu_primary")
        assert self.engine.get_node_status("gpu_primary") == "green"

    def test_add_rule(self):
        new_rule = AlertRule(node="system", metric="cpu_pct", yellow=85, red=95)
        self.engine.add_rule(new_rule)
        assert len(self.engine.rules) == 4
        assert self.engine.get_node_status("system") == "green"

    def test_callback_fired(self):
        fired = []
        engine = AlertEngine(
            rules=[AlertRule(node="test", metric="val", yellow=50, red=90)],
            on_alert=lambda a: fired.append(a),
        )
        engine.feed("test", "val", 60.0)
        engine.evaluate()
        assert len(fired) == 1
        assert fired[0].level == "yellow"

    def test_from_config(self):
        config = {
            "gpu_vram_pct": {"yellow": 80, "red": 95},
            "avg_latency_ms": {"yellow": 500, "red": 2000},
        }
        engine = AlertEngine.from_config(config)
        assert len(engine.rules) == 2

    def test_clear_samples(self):
        self.engine.feed("gpu_primary", "vram_pct", 85.0)
        self.engine.clear_samples()
        alerts = self.engine.evaluate()
        assert alerts == []


class TestAlert:
    def test_alert_fields(self):
        a = Alert(
            node="gpu", level="red", prev_level="yellow",
            metric="vram_pct", value=96.0, threshold=95,
            message="GPU VRAM critical",
        )
        assert a.node == "gpu"
        assert a.level == "red"
        assert a.ts > 0
