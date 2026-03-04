"""
The Coders Room — AI Agent Idle Code Simulation
================================================

A 2D office where AI agents write, review, and test real Python code.
Showcases the v3.x pipeline with multi-agent collaboration through
stateful and stateless LMS calls, sandboxed code execution, and
live terminal output.
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from engine.mcp.framework import MCPSceneMixin, get_framework
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry, TagDef
from content.scenes.coders.coders_rules import register_coders_rules
from content.shared import register_shared_assets

from .coders_state import (
    AgentRole,
    CodersRoomState,
    FEATURE_SEEDS,
    PipelinePhase,
)

logger = logging.getLogger(__name__)

SCENE_ID = "coders"
DEFAULT_PORT = 5564


class CodersRoomScene(BaseScene, MCPSceneMixin, NexusSceneMixin, mcp_scene_id="coders"):
    """The Coders Room — AI Agent Idle Code Simulation."""

    SCENE_METADATA = {
        "name": "coders",
        "display_name": "THE LAB",
        "port": 5564,
        "type": "system",
        "accent_color": "#4ade80",
        "accent_rgb": "74 222 128",
        "description": "Green means go. The code writes itself. You just watch.",
        # Legacy compat fields
        "genre": "coding_simulation",
        "max_characters": 3,
        "features": ["code_generation", "code_review", "testing", "pipeline_phases",
                     "sandboxed_execution", "multi_agent_collab"],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(scene_name=SCENE_ID, host=host, port=port)
        self._mcp_init()

        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config["SECRET_KEY"] = "coders_room_v3"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        register_shared_assets(self.app)

        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_health_route(self.app)
        self.register_hud_route(self.app)
        self.register_announcer_route(self.app)
        self.register_bench_route(self.app, self.socketio)
        self.register_tts_route(self.app)

        self.state: Optional[CodersRoomState] = None
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()
        self._tag_registry.register(TagDef(
            name="CODE", pattern=r"\[CODE:([^\]]+)\]",
            handler=None, strip_from_output=True, pre_warm_intent="coders_code"
        ))
        register_coders_rules()
        self._tick_thread: Optional[threading.Thread] = None
        self._running = False

        self.nexus_init("coders")

        self._setup_routes()
        self._setup_socketio()

    def _llm_call(self, system: str, user: str, max_tokens: int = 1500, agent_id: str = "coders_agent") -> str:
        """Stateless LLM call with governance context."""
        try:
            from engine.lmstudio.lms_client import get_lms_client
            from engine.mcp.comms_framework import build_governance_context
            client = get_lms_client()
            gov_ctx = build_governance_context(agent_id, "coders", user)
            full_system = f"{system}\n\n{gov_ctx}" if gov_ctx else system
            messages = [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user},
            ]
            resp = client.chat(messages, temperature=0.7, max_tokens=max_tokens, store=False)
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.warning("Coders LLM call failed: %s", e)
            return ""

    def _extract_code(self, text: str) -> str:
        """Extract Python code from markdown code blocks."""
        import re
        match = re.search(r'```python\s*(.*?)```', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r'```\s*(.*?)```', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback: lines that look like code
        lines = [l for l in text.split("\n") if l.strip() and not l.startswith("#") and not l.startswith("*")]
        return "\n".join(lines)

    def _tick(self) -> None:
        """One pipeline tick — advance the current feature through phases."""
        if not self.state or not self.state.active:
            return
        self.state.tick_count += 1

        # Tick MCP framework for consequences
        get_framework().tick(SCENE_ID)

        feature = self.state.get_current_feature()

        # Auto-queue new features when idle
        if not feature:
            feature = self.state.add_feature()
            self._emit_chat("System", f"📋 New feature request: {feature.title}")

        # Phase machine
        if feature.phase == PipelinePhase.FEATURE:
            self._phase_design(feature)
        elif feature.phase == PipelinePhase.DESIGN:
            self._phase_code(feature)
        elif feature.phase == PipelinePhase.CODING:
            self._phase_review(feature)
        elif feature.phase == PipelinePhase.REVIEW:
            self._phase_test(feature)
        elif feature.phase == PipelinePhase.TESTING:
            self._phase_finalize(feature)

        self._sync_to_mcp()
        self.socketio.emit("state_update", self.state.to_dict())

    def _phase_design(self, feature) -> None:
        """Reviewer drafts design spec."""
        agent = self.state.get_idle_agent(AgentRole.REVIEWER)
        if not agent:
            return
        agent.status = "working"
        agent.current_task = feature.id
        self._emit_chat(agent.name, f"I'll draft specs for '{feature.title}'...")

        spec = self._llm_call(
            f"You are {agent.name}, a senior code reviewer. Write a brief technical spec (max 200 words). Include: function signatures, edge cases, expected behavior.",
            f"Feature: {feature.title}\nDescription: {feature.description}\nWrite the spec.",
        )
        feature.spec = spec
        feature.assigned_reviewer = agent.id
        feature.phase = PipelinePhase.DESIGN
        feature.conversation_log.append({"agent": agent.name, "message": f"Spec drafted:\n{spec[:300]}"})
        agent.reviews_done += 1
        agent.status = "idle"
        agent.current_task = ""
        self._emit_chat(agent.name, f"✅ Spec ready. Handing off to a writer.")
        self.socketio.emit("terminal_output", {"agent": agent.name, "output": spec})

    def _phase_code(self, feature) -> None:
        """Writer produces Python code."""
        agent = self.state.get_idle_agent(AgentRole.WRITER)
        if not agent:
            return
        agent.status = "coding"
        agent.current_task = feature.id
        self._emit_chat(agent.name, f"Writing code for '{feature.title}'...")

        code = self._llm_call(
            f"You are {agent.name}, a Python developer. Write clean, working Python code. Return ONLY the code in a ```python``` block. No explanations.",
            f"Feature: {feature.title}\nSpec:\n{feature.spec}\n\nWrite the Python implementation.",
        )
        extracted = self._extract_code(code)
        feature.code = extracted
        feature.assigned_writer = agent.id
        feature.phase = PipelinePhase.CODING
        feature.conversation_log.append({"agent": agent.name, "message": f"Code written ({len(extracted.splitlines())} lines)"})
        agent.lines_written += len(extracted.splitlines())
        self.state.total_lines += len(extracted.splitlines())
        agent.status = "idle"
        agent.current_task = ""
        self._emit_chat(agent.name, f"✅ {len(extracted.splitlines())} lines written. Ready for review.")
        self.socketio.emit("terminal_output", {"agent": agent.name, "output": extracted})

    def _phase_review(self, feature) -> None:
        """Reviewer reviews the code."""
        agent = self.state.get_idle_agent(AgentRole.REVIEWER)
        if not agent:
            return
        agent.status = "reviewing"
        agent.current_task = feature.id
        self._emit_chat(agent.name, f"Reviewing code for '{feature.title}'...")

        review = self._llm_call(
            f"You are {agent.name}, a meticulous code reviewer. Review this Python code. Comment on correctness, edge cases, style. Be direct. Max 150 words.",
            f"Feature: {feature.title}\nSpec:\n{feature.spec[:200]}\n\nCode:\n```python\n{feature.code}\n```\n\nReview it.",
        )
        feature.review_notes = review
        feature.phase = PipelinePhase.REVIEW
        feature.conversation_log.append({"agent": agent.name, "message": f"Review: {review[:300]}"})
        agent.reviews_done += 1
        agent.status = "idle"
        agent.current_task = ""

        # Simulate reviewer banter with writer
        writer = self.state.get_agent(feature.assigned_writer)
        writer_name = writer.name if writer else "the writer"
        self._emit_chat(agent.name, f"Code review done. Notes for {writer_name}: {review[:150]}...")
        self.socketio.emit("terminal_output", {"agent": agent.name, "output": review})

    def _phase_test(self, feature) -> None:
        """QA agent writes and runs tests."""
        agent = self.state.get_idle_agent(AgentRole.QA)
        if not agent:
            return
        agent.status = "testing"
        agent.current_task = feature.id
        self._emit_chat(agent.name, f"Writing tests for '{feature.title}'...")

        test_code = self._llm_call(
            f"You are {agent.name}, a QA engineer. Write pytest-style test functions for this code. Use assert statements. Return ONLY the test code in a ```python``` block. Include the imports needed.",
            f"Feature: {feature.title}\nCode:\n```python\n{feature.code}\n```\n\nWrite 3-5 test functions.",
        )
        extracted_tests = self._extract_code(test_code)
        feature.test_code = extracted_tests
        feature.assigned_qa = agent.id
        feature.phase = PipelinePhase.TESTING

        # Execute in sandbox
        self._emit_chat(agent.name, "Running tests...")
        exec_result = self.state.execute_code(feature.code, extracted_tests)
        feature.test_output = exec_result.get("stdout", "") + exec_result.get("stderr", "")
        feature.test_passed = exec_result.get("success", False)

        agent.tests_run += 1
        self.state.total_tests += 1
        agent.status = "idle"
        agent.current_task = ""

        status = "✅ PASSED" if feature.test_passed else "❌ FAILED"
        self._emit_chat(agent.name, f"Tests {status}. Output: {feature.test_output[:200]}")
        self.socketio.emit("terminal_output", {
            "agent": agent.name,
            "output": f"=== TEST RESULT: {status} ===\n{feature.test_output[:500]}",
        })

    def _phase_finalize(self, feature) -> None:
        """Complete or fail the feature."""
        if feature.test_passed:
            self.state.complete_feature(feature)
            self._emit_chat("System", f"🎉 Feature '{feature.title}' completed successfully!")
        else:
            # Mark failed — will auto-retry or queue new
            feature.phase = PipelinePhase.FAILED
            self._emit_chat("System", f"⚠️ Feature '{feature.title}' failed tests. Moving on.")
            self.state.features.remove(feature)

    def _emit_chat(self, agent_name: str, message: str) -> None:
        self.socketio.emit("agent_chat", {
            "agent": agent_name,
            "message": message,
            "timestamp": time.time(),
        })

    def _tick_loop(self, interval: float) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("Coders tick error: %s", e)
            time.sleep(interval)

    def _sync_to_mcp(self) -> None:
        if not self.state:
            return
        try:
            self.mcp.update_state(self.state.to_dict())
        except Exception:
            pass
        # Sync agent stats to SceneStateManager for cross-system visibility
        try:
            for agent in (self.state.agents or []):
                self._state_mgr.add_narrative(SCENE_ID, f"{agent.name}: {agent.status}")
        except Exception:
            pass
        # Sync agent state through the StateCoordinator for governance visibility
        try:
            from engine.mcp.state_coordinator import get_coordinator
            coord = get_coordinator()
            for agent in (self.state.agents or []):
                coord.update(
                    agent.id,
                    mood=agent.status,
                    source="coders_sync",
                    scene=SCENE_ID,
                )
        except Exception:
            pass

    def _setup_routes(self):

        @self.app.route("/")
        def index():
            return render_template("coders.html", feature_seeds=FEATURE_SEEDS,
                                   **self.inject_navbar_context())

        @self.app.route("/api/scene/info")
        def scene_info():
            return jsonify(self.get_plugin_info())

        @self.app.route("/api/state")
        def get_state():
            if not self.state:
                return jsonify({"active": False})
            return jsonify({"active": True, **self.state.to_dict()})

        @self.app.route("/api/start", methods=["POST"])
        def start_sim():
            data = request.json or {}
            interval = data.get("interval", 15)
            self.state = CodersRoomState()
            self.state.active = True
            # Queue initial feature
            self.state.add_feature()
            self._running = True
            self._tick_thread = threading.Thread(target=self._tick_loop, args=(interval,), daemon=True)
            self._tick_thread.start()
            self.socketio.emit("state_update", self.state.to_dict())
            return jsonify({"success": True, "session_id": self.state.session_id})

        @self.app.route("/api/stop", methods=["POST"])
        def stop_sim():
            self._running = False
            if self.state:
                self.state.active = False
            return jsonify({"success": True})

        @self.app.route("/api/feature/add", methods=["POST"])
        def add_feature():
            if not self.state:
                return jsonify({"error": "Not started"}), 400
            data = request.json or {}
            feature = self.state.add_feature(data.get("title"), data.get("description"))
            return jsonify({"success": True, "feature": feature.to_dict()})

        @self.app.route("/api/tick", methods=["POST"])
        def manual_tick():
            if not self.state:
                return jsonify({"error": "Not started"}), 400
            self._tick()
            return jsonify(self.state.to_dict())

        @self.app.route("/api/sessions")
        def list_sessions():
            return jsonify(self._list_sessions())

        @self.app.route("/api/session/save", methods=["POST"])
        def save_session():
            path = self._save_session()
            if path:
                return jsonify({"success": True, "path": path})
            return jsonify({"error": "No active session"}), 400

        @self.app.route("/api/session/load", methods=["POST"])
        def load_session():
            data = request.json or {}
            session_id = data.get("session_id", "")
            if not session_id:
                return jsonify({"error": "session_id required"}), 400
            if self._load_session(session_id):
                return jsonify({"success": True, **self.state.to_dict()})
            return jsonify({"error": "Session not found"}), 404

    def _setup_socketio(self):
        @self.socketio.on("connect")
        def on_connect():
            if self.state:
                self.socketio.emit("state_update", self.state.to_dict())

    # ── BaseScene contract ──

    def start(self) -> None:
        logger.info("THE LAB v0.68 Dark Renaissance starting on port %d", self.port)
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self.nexus_flush()
        self._running = False
        if self.state:
            self._save_session()
        self._mcp_deregister_scene()

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "THE LAB",
            "scene_id": SCENE_ID,
            "description": "Matrix-green AI agent coding pipeline — write, review, test, deploy.",
            "version": "0.68",
            "port": self.port,
            "author": "CosySim",
            "tags": ["coding", "agents", "idle_sim", "sandbox", "matrix", "dark_renaissance"],
            "skill_packs": ["coders"],
            "routes": [
                {"path": "/api/start",       "methods": ["POST"], "description": "Start simulation"},
                {"path": "/api/stop",        "methods": ["POST"], "description": "Stop simulation"},
                {"path": "/api/state",       "methods": ["GET"],  "description": "Get state"},
                {"path": "/api/feature/add", "methods": ["POST"], "description": "Add feature request"},
                {"path": "/api/tick",        "methods": ["POST"], "description": "Manual tick"},
                {"path": "/api/sessions",    "methods": ["GET"],  "description": "List saved sessions"},
                {"path": "/api/session/load", "methods": ["POST"], "description": "Load saved session"},
            ],
        }

    # ── Session Persistence ──

    _SESSIONS_DIR = Path("data/coders_sessions")

    def _save_session(self) -> Optional[str]:
        """Save current session state to disk."""
        if not self.state:
            return None
        self._SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = self._SESSIONS_DIR / f"{self.state.session_id}.json"
        data = self.state.to_dict()
        data["completed_features"] = [f.to_dict() for f in self.state.completed_features]
        data["saved_at"] = time.time()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Coders session saved: %s", path)
        return str(path)

    def _load_session(self, session_id: str) -> bool:
        """Restore a previously saved session."""
        path = self._SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.state = CodersRoomState()
            self.state.session_id = data.get("session_id", session_id)
            self.state.tick_count = data.get("tick_count", 0)
            self.state.total_lines = data.get("total_lines", 0)
            self.state.total_tests = data.get("total_tests", 0)
            for ad in data.get("agents", []):
                agent = self.state.get_agent(ad.get("id", ""))
                if agent:
                    agent.lines_written = ad.get("lines_written", 0)
                    agent.reviews_done = ad.get("reviews_done", 0)
                    agent.tests_run = ad.get("tests_run", 0)
            self.state.active = False
            logger.info("Coders session loaded: %s", session_id)
            return True
        except Exception as exc:
            logger.warning("Failed to load session %s: %s", session_id, exc)
            return False

    def _list_sessions(self) -> List[Dict[str, Any]]:
        """List all saved sessions."""
        if not self._SESSIONS_DIR.exists():
            return []
        sessions = []
        for path in sorted(self._SESSIONS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", path.stem),
                    "completed": data.get("completed", 0),
                    "total_lines": data.get("total_lines", 0),
                    "total_tests": data.get("total_tests", 0),
                    "saved_at": data.get("saved_at", 0),
                })
            except Exception:
                pass
        return sessions
