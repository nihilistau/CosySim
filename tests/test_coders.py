"""Tests for The Coders Room scene — state, pipeline, sandbox execution."""
import pytest

from content.scenes.coders.coders_state import (
    AgentRole,
    CodersRoomState,
    FEATURE_SEEDS,
    PipelinePhase,
)


class TestCodersRoomState:
    def setup_method(self):
        self.state = CodersRoomState()

    def test_initial_state(self):
        assert len(self.state.agents) == 4
        assert not self.state.active
        assert self.state.tick_count == 0

    def test_agent_roles(self):
        roles = [a.role for a in self.state.agents]
        assert AgentRole.REVIEWER in roles
        assert AgentRole.WRITER in roles
        assert AgentRole.QA in roles

    def test_agent_names(self):
        names = [a.name for a in self.state.agents]
        assert "Ada" in names
        assert "Linus" in names
        assert "Grace" in names
        assert "Alan" in names

    def test_to_dict(self):
        d = self.state.to_dict()
        assert "agents" in d
        assert len(d["agents"]) == 4
        assert "features" in d
        assert d["tick_count"] == 0

    def test_get_agent(self):
        agent = self.state.get_agent("reviewer_1")
        assert agent is not None
        assert agent.name == "Ada"

    def test_get_agent_not_found(self):
        assert self.state.get_agent("nobody") is None

    def test_get_idle_agent(self):
        agent = self.state.get_idle_agent(AgentRole.REVIEWER)
        assert agent is not None
        assert agent.role == AgentRole.REVIEWER

    def test_get_idle_agent_none_available(self):
        for a in self.state.agents:
            if a.role == AgentRole.REVIEWER:
                a.status = "working"
        assert self.state.get_idle_agent(AgentRole.REVIEWER) is None

    def test_add_feature_random(self):
        feature = self.state.add_feature()
        assert feature.title in [s["title"] for s in FEATURE_SEEDS]
        assert feature.phase == PipelinePhase.FEATURE
        assert len(self.state.features) == 1

    def test_add_feature_custom(self):
        feature = self.state.add_feature("Custom Feature", "Do something cool")
        assert feature.title == "Custom Feature"
        assert feature.description == "Do something cool"

    def test_feature_to_dict(self):
        feature = self.state.add_feature()
        d = feature.to_dict()
        assert "id" in d
        assert "title" in d
        assert "phase" in d

    def test_execute_code_success(self):
        result = self.state.execute_code("x = 2 + 2\nprint(x)")
        assert result["success"]
        assert "4" in result["stdout"]

    def test_execute_code_with_tests(self):
        code = "def add(a, b): return a + b"
        tests = "assert add(1, 2) == 3\nassert add(0, 0) == 0\nprint('All tests passed')"
        result = self.state.execute_code(code, tests)
        assert result["success"]
        assert "All tests passed" in result["stdout"]

    def test_execute_code_failure(self):
        result = self.state.execute_code("raise ValueError('oops')")
        assert not result["success"]
        assert "ValueError" in result["stderr"]

    def test_execute_code_timeout(self):
        result = self.state.execute_code("import time; time.sleep(30)")
        assert not result["success"]
        assert "timed out" in result["stderr"].lower() or result["returncode"] == -1

    def test_execute_code_syntax_error(self):
        result = self.state.execute_code("def broken(")
        assert not result["success"]

    def test_get_current_feature(self):
        self.state.add_feature()
        feature = self.state.get_current_feature()
        assert feature is not None

    def test_get_current_feature_empty(self):
        assert self.state.get_current_feature() is None

    def test_complete_feature(self):
        feature = self.state.add_feature()
        feature.phase = PipelinePhase.TESTING
        feature.test_passed = True
        self.state.complete_feature(feature)
        assert len(self.state.completed_features) == 1
        assert len(self.state.features) == 0

    def test_desk_slots_unique(self):
        slots = [a.desk_slot for a in self.state.agents]
        assert len(set(slots)) == len(slots)


class TestPipelinePhases:
    def test_phase_transitions(self):
        phases = [
            PipelinePhase.IDLE,
            PipelinePhase.FEATURE,
            PipelinePhase.DESIGN,
            PipelinePhase.CODING,
            PipelinePhase.REVIEW,
            PipelinePhase.TESTING,
            PipelinePhase.COMPLETE,
            PipelinePhase.FAILED,
        ]
        assert len(phases) == 8

    def test_feature_starts_at_feature_phase(self):
        state = CodersRoomState()
        feature = state.add_feature()
        assert feature.phase == PipelinePhase.FEATURE
