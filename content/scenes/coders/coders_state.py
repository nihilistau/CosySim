"""
The Coders Room — Agent Pipeline State Engine
==============================================

Manages the idle coding simulation: feature requests, design specs,
code writing, review, and QA. Agents collaborate through shared state
and a sandboxed execution environment.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    REVIEWER = "reviewer"
    WRITER   = "writer"
    QA       = "qa"


class PipelinePhase(str, Enum):
    IDLE       = "idle"
    FEATURE    = "feature"
    DESIGN     = "design"
    CODING     = "coding"
    REVIEW     = "review"
    TESTING    = "testing"
    COMPLETE   = "complete"
    FAILED     = "failed"


@dataclass
class CodeAgent:
    id: str
    name: str
    role: AgentRole
    desk_slot: int = 0
    status: str = "idle"
    current_task: str = ""
    lines_written: int = 0
    reviews_done: int = 0
    tests_run: int = 0
    mood: str = "focused"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "role": self.role.value,
            "desk_slot": self.desk_slot, "status": self.status,
            "current_task": self.current_task,
            "lines_written": self.lines_written,
            "reviews_done": self.reviews_done,
            "tests_run": self.tests_run,
            "mood": self.mood,
        }


@dataclass
class FeatureRequest:
    id: str
    title: str
    description: str
    phase: PipelinePhase = PipelinePhase.FEATURE
    spec: str = ""
    code: str = ""
    review_notes: str = ""
    test_code: str = ""
    test_output: str = ""
    test_passed: bool = False
    assigned_writer: Optional[str] = None
    assigned_reviewer: Optional[str] = None
    assigned_qa: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    conversation_log: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "title": self.title,
            "description": self.description,
            "phase": self.phase.value,
            "spec": self.spec[:500] if self.spec else "",
            "code": self.code,
            "review_notes": self.review_notes[:500] if self.review_notes else "",
            "test_code": self.test_code,
            "test_output": self.test_output[:500] if self.test_output else "",
            "test_passed": self.test_passed,
            "assigned_writer": self.assigned_writer,
            "assigned_reviewer": self.assigned_reviewer,
            "assigned_qa": self.assigned_qa,
            "conversation_log": self.conversation_log[-10:],
        }


# Feature request seeds
FEATURE_SEEDS = [
    {"title": "Fibonacci Sequence Generator", "description": "Write a function that returns the first N fibonacci numbers as a list."},
    {"title": "Caesar Cipher", "description": "Implement encrypt/decrypt functions for a Caesar cipher with configurable shift."},
    {"title": "Simple Stack", "description": "Create a Stack class with push, pop, peek, is_empty methods."},
    {"title": "Word Frequency Counter", "description": "Write a function that counts word frequencies in a text string, returning a dict."},
    {"title": "Temperature Converter", "description": "Functions to convert between Celsius, Fahrenheit, and Kelvin."},
    {"title": "Matrix Multiplication", "description": "Implement matrix multiplication for two 2D lists."},
    {"title": "Palindrome Checker", "description": "Function that checks if a string is a palindrome (ignoring case/spaces)."},
    {"title": "Binary Search", "description": "Implement binary search on a sorted list, returning the index or -1."},
    {"title": "Linked List", "description": "Create a singly linked list with append, prepend, find, and delete methods."},
    {"title": "Simple Calculator", "description": "Parse and evaluate basic math expressions (+, -, *, /) from a string."},
]


class CodersRoomState:
    """Central state for the Coders Room simulation."""

    def __init__(self):
        self.session_id = f"coders_{uuid.uuid4().hex[:8]}"
        self.agents: List[CodeAgent] = [
            CodeAgent(id="reviewer_1", name="Ada", role=AgentRole.REVIEWER, desk_slot=0, mood="meticulous"),
            CodeAgent(id="writer_1",   name="Linus", role=AgentRole.WRITER, desk_slot=1, mood="caffeinated"),
            CodeAgent(id="writer_2",   name="Grace", role=AgentRole.WRITER, desk_slot=2, mood="creative"),
            CodeAgent(id="qa_1",       name="Alan", role=AgentRole.QA, desk_slot=3, mood="skeptical"),
        ]
        self.features: List[FeatureRequest] = []
        self.completed_features: List[FeatureRequest] = []
        self.active: bool = False
        self.tick_count: int = 0
        self.total_lines: int = 0
        self.total_tests: int = 0
        self.sandbox_dir = Path(tempfile.mkdtemp(prefix="cosysim_coders_"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agents": [a.to_dict() for a in self.agents],
            "features": [f.to_dict() for f in self.features],
            "completed": len(self.completed_features),
            "active": self.active,
            "tick_count": self.tick_count,
            "total_lines": self.total_lines,
            "total_tests": self.total_tests,
        }

    def get_agent(self, agent_id: str) -> Optional[CodeAgent]:
        return next((a for a in self.agents if a.id == agent_id), None)

    def get_idle_agent(self, role: AgentRole) -> Optional[CodeAgent]:
        return next((a for a in self.agents if a.role == role and a.status == "idle"), None)

    def add_feature(self, title: str | None = None, description: str | None = None) -> FeatureRequest:
        if title and description:
            seed = {"title": title, "description": description}
        else:
            import random
            seed = random.choice(FEATURE_SEEDS)
        feature = FeatureRequest(
            id=f"feat_{uuid.uuid4().hex[:6]}",
            title=seed["title"],
            description=seed["description"],
        )
        self.features.append(feature)
        return feature

    def execute_code(self, code: str, test_code: str = "") -> Dict[str, Any]:
        """Run Python code in a sandboxed subprocess."""
        full_code = code
        if test_code:
            full_code += "\n\n" + test_code

        code_file = self.sandbox_dir / f"run_{uuid.uuid4().hex[:6]}.py"
        code_file.write_text(full_code, encoding="utf-8")

        try:
            result = subprocess.run(
                ["python", str(code_file)],
                capture_output=True, text=True, timeout=10,
                cwd=str(self.sandbox_dir),
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "stdout": "", "stderr": "Execution timed out (10s)", "returncode": -1}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}
        finally:
            try:
                code_file.unlink()
            except Exception:
                pass

    def get_current_feature(self) -> Optional[FeatureRequest]:
        """Get the first non-complete feature."""
        for f in self.features:
            if f.phase not in (PipelinePhase.COMPLETE, PipelinePhase.FAILED):
                return f
        return None

    def complete_feature(self, feature: FeatureRequest) -> None:
        feature.phase = PipelinePhase.COMPLETE
        feature.completed_at = time.time()
        self.completed_features.append(feature)
        self.features.remove(feature)
        # Free agents
        for a in self.agents:
            if a.current_task == feature.id:
                a.status = "idle"
                a.current_task = ""
