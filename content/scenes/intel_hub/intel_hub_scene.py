"""Intelligence Hub — Unified system monitoring and control center.

The Intelligence Hub is the master control interface for CosySim,
exposing every subsystem in a single, beautiful, real-time dashboard:

  - System overview (health, metrics, live activity)
  - Nexus full knowledge explorer (browse, search, add, edit, Q&A)
  - Librarian NLM chat interface with conversation history
  - Copilot integration (rules, agent files, prompts, hooks, memory)
  - NLM Lab (notebook management, generation, distillation pipeline)
  - Fine-tune Lab (datasets, training jobs, model registry, benchmarks)
  - Scheduler (task list, control, metrics, history)
  - Conversation Analyzer + User Profile
  - Backup Manager (status, list, restore)
  - Cache Pipeline (QA generation, coverage, review sheet)

Port: 5580
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request

from engine.config import get_config
from engine.scenes.base_scene import BaseScene

try:
    from flask_socketio import SocketIO, emit
except ImportError:
    SocketIO = None  # type: ignore
    emit = None  # type: ignore

try:
    from content.shared import register_shared_assets
except ImportError:
    register_shared_assets = None  # type: ignore

logger = logging.getLogger(__name__)

SCENE_ID = "intel_hub"
DEFAULT_PORT = 5580

SCENE_METADATA = {
    "title": "Intelligence Hub",
    "description": "Unified system control: Nexus, Copilot, NLM, fine-tuning, scheduler, backups",
    "genre": "management",
    "type": "admin",
    "max_characters": 1,
    "features": [
        "system overview", "nexus explorer", "librarian", "copilot rules",
        "nlm lab", "fine-tune lab", "scheduler control", "conversation analyzer",
        "user profile", "backup manager", "cache pipeline", "model registry",
    ],
}

# ──── Scene ───────────────────────────────────────────────────────────────────


class IntelHubScene(BaseScene):
    """Intelligence Hub — unified system control panel."""

    SCENE_METADATA = SCENE_METADATA

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        cfg = get_config()
        self._host = host
        self._port = cfg.get("scenes.intel_hub.port", port)
        self._app = Flask(
            __name__,
            template_folder="templates",
            static_folder="static",
            static_url_path="/intel_hub/static",
        )
        if register_shared_assets:
            register_shared_assets(self._app)
        self._socketio: Optional[Any] = None
        self._activity: deque = deque(maxlen=200)
        self._stop_event = threading.Event()
        self._push_thread: Optional[threading.Thread] = None
        self._register_routes()
        self._register_socketio()

    # ── BaseScene interface ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the Intelligence Hub Flask server."""
        self._stop_event.clear()
        self._push_thread = threading.Thread(
            target=self._push_loop, daemon=True, name="intel-hub-push"
        )
        self._push_thread.start()
        logger.info("Intelligence Hub starting on %s:%d", self._host, self._port)
        if self._socketio:
            self._socketio.run(
                self._app, host=self._host, port=self._port,
                debug=False, use_reloader=False, log_output=False,
            )
        else:
            self._app.run(host=self._host, port=self._port, debug=False)

    def stop(self) -> None:
        self._stop_event.set()

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "id": SCENE_ID,
            "title": SCENE_METADATA["title"],
            "description": SCENE_METADATA["description"],
            "port": self._port,
            "url": f"http://localhost:{self._port}",
            "type": "admin",
            "icon": "◆",
        }

    # ── Routes ─────────────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        app = self._app

        # Mount the assistant blueprint (chat, voice, listen endpoints)
        try:
            from engine.assistant.assistant_bp import assistant_bp
            app.register_blueprint(assistant_bp)
        except Exception as _e:
            logger.warning("Could not register assistant blueprint: %s", _e)

        @app.route("/")
        def index():
            return render_template("intel_hub.html", port=self._port)

        @app.route("/health")
        @app.route("/api/health")
        def health():
            return jsonify({"status": "ok", "scene": SCENE_ID, "port": self._port})

        # ── TTS control ───────────────────────────────────────────────────────

        @app.route("/api/tts/config")
        def api_tts_config():
            return jsonify(_get_tts_config())

        @app.route("/api/tts/config", methods=["POST"])
        def api_tts_config_update():
            data = request.json or {}
            return jsonify(_update_tts_config(data))

        @app.route("/api/tts/voices")
        def api_tts_voices():
            return jsonify(_get_tts_voices())

        @app.route("/api/tts/benchmarks")
        def api_tts_benchmarks():
            return jsonify(_get_tts_benchmarks())

        # ── VTT control ───────────────────────────────────────────────────────

        @app.route("/api/vtt/config")
        def api_vtt_config():
            return jsonify(_get_vtt_config())

        @app.route("/api/vtt/config", methods=["POST"])
        def api_vtt_config_update():
            data = request.json or {}
            return jsonify(_update_vtt_config(data))

        # ── Overview ──────────────────────────────────────────────────────────

        @app.route("/api/overview")
        def api_overview():
            return jsonify(self._get_overview())

        @app.route("/api/activity")
        def api_activity():
            return jsonify(list(self._activity))

        # ── Nexus ─────────────────────────────────────────────────────────────

        @app.route("/api/nexus/stats")
        def api_nexus_stats():
            return jsonify(_call_nexus("stats"))

        @app.route("/api/nexus/search")
        def api_nexus_search():
            q = request.args.get("q", "")
            limit = int(request.args.get("limit", 20))
            return jsonify(_call_nexus("search", query=q, limit=limit))

        @app.route("/api/nexus/entries")
        def api_nexus_entries():
            category = request.args.get("category", "")
            limit = int(request.args.get("limit", 50))
            return jsonify(_call_nexus("entries", category=category, limit=limit))

        @app.route("/api/nexus/qa")
        def api_nexus_qa():
            limit = int(request.args.get("limit", 100))
            return jsonify(_call_nexus("qa", limit=limit))

        @app.route("/api/nexus/entry/<entry_id>")
        def api_nexus_entry(entry_id):
            return jsonify(_call_nexus("get_entry", entry_id=entry_id))

        @app.route("/api/nexus/add", methods=["POST"])
        def api_nexus_add():
            data = request.json or {}
            result = _call_nexus(
                "add",
                title=data.get("title", ""),
                content=data.get("content", ""),
                content_type=data.get("content_type", "note"),
                category=data.get("category", "general"),
            )
            self._log_activity("nexus", f"Added entry: {data.get('title', '')}")
            return jsonify(result)

        @app.route("/api/nexus/ask", methods=["POST"])
        def api_nexus_ask():
            data = request.json or {}
            result = _call_nexus("ask", question=data.get("question", ""))
            self._log_activity("librarian", f"Q: {data.get('question', '')[:60]}")
            return jsonify(result)

        @app.route("/api/nexus/categories")
        def api_nexus_categories():
            return jsonify(_call_nexus("categories"))

        # ── Copilot ───────────────────────────────────────────────────────────

        @app.route("/api/copilot/rules")
        def api_copilot_rules():
            return jsonify(_get_copilot_rules())

        @app.route("/api/copilot/agents")
        def api_copilot_agents():
            return jsonify(_get_copilot_agents())

        @app.route("/api/copilot/prompts")
        def api_copilot_prompts():
            return jsonify(_get_nexus_prompts())

        @app.route("/api/copilot/hooks")
        def api_copilot_hooks():
            return jsonify(_get_copilot_hooks())

        @app.route("/api/copilot/memory")
        def api_copilot_memory():
            return jsonify(_get_copilot_memory())

        @app.route("/api/copilot/file")
        def api_copilot_file():
            path = request.args.get("path", "")
            return jsonify(_read_copilot_file(path))

        @app.route("/api/copilot/file", methods=["POST"])
        def api_copilot_file_save():
            data = request.json or {}
            return jsonify(_write_copilot_file(data.get("path", ""), data.get("content", "")))

        # ── NLM Lab ───────────────────────────────────────────────────────────

        @app.route("/api/nlm/notebooks")
        def api_nlm_notebooks():
            return jsonify(_call_nlm("list_notebooks"))

        @app.route("/api/nlm/notebook/<notebook_id>")
        def api_nlm_notebook(notebook_id):
            return jsonify(_call_nlm("get_notebook", notebook_id=notebook_id))

        @app.route("/api/nlm/generate", methods=["POST"])
        def api_nlm_generate():
            data = request.json or {}
            result = _call_nlm("generate", **data)
            self._log_activity("nlm", f"Generate {data.get('type','?')} on {data.get('notebook_id','?')[:8]}")
            return jsonify(result)

        @app.route("/api/nlm/distill", methods=["POST"])
        def api_nlm_distill():
            data = request.json or {}
            result = _call_nlm("distill", notebook_id=data.get("notebook_id"), count=data.get("count", 10))
            self._log_activity("nlm", "Distillation triggered")
            return jsonify(result)

        @app.route("/api/nlm/ask", methods=["POST"])
        def api_nlm_ask():
            data = request.json or {}
            return jsonify(_call_nlm("ask", notebook_id=data.get("notebook_id"), question=data.get("question", "")))

        # ── Fine-tune Lab ─────────────────────────────────────────────────────

        @app.route("/api/finetune/datasets")
        def api_finetune_datasets():
            return jsonify(_get_datasets())

        @app.route("/api/finetune/jobs")
        def api_finetune_jobs():
            return jsonify(_get_training_jobs())

        @app.route("/api/finetune/start", methods=["POST"])
        def api_finetune_start():
            data = request.json or {}
            result = _start_training_job(data)
            self._log_activity("finetune", f"Job started: {data.get('dataset','?')}")
            return jsonify(result)

        @app.route("/api/finetune/models")
        def api_finetune_models():
            return jsonify(_get_model_registry())

        @app.route("/api/finetune/benchmarks")
        def api_finetune_benchmarks():
            return jsonify(_get_benchmarks())

        @app.route("/api/finetune/generate_dataset", methods=["POST"])
        def api_finetune_generate_dataset():
            data = request.json or {}
            result = _generate_dataset(data)
            self._log_activity("finetune", f"Dataset gen: {data.get('type','?')}")
            return jsonify(result)

        # ── Scheduler ─────────────────────────────────────────────────────────

        @app.route("/api/scheduler/tasks")
        def api_scheduler_tasks():
            return jsonify(_get_scheduler_tasks())

        @app.route("/api/scheduler/trigger", methods=["POST"])
        def api_scheduler_trigger():
            data = request.json or {}
            result = _trigger_scheduler_task(data.get("task_id", ""))
            self._log_activity("scheduler", f"Triggered: {data.get('task_id','?')}")
            return jsonify(result)

        @app.route("/api/scheduler/history")
        def api_scheduler_history():
            limit = int(request.args.get("limit", 50))
            return jsonify(_get_scheduler_history(limit))

        # ── Conversation Analyzer ─────────────────────────────────────────────

        @app.route("/api/analyzer/analyze", methods=["POST"])
        def api_analyzer_analyze():
            data = request.json or {}
            result = _run_conversation_analysis(data.get("text", ""), data.get("mode", "auto"))
            self._log_activity("analyzer", "Conversation analyzed")
            return jsonify(result)

        @app.route("/api/analyzer/profile")
        def api_analyzer_profile():
            return jsonify(_get_user_profile())

        @app.route("/api/analyzer/profile", methods=["POST"])
        def api_analyzer_profile_update():
            data = request.json or {}
            return jsonify(_update_user_profile(data))

        @app.route("/api/analyzer/recent")
        def api_analyzer_recent():
            return jsonify(_run_recent_analysis())

        # ── Backups ────────────────────────────────────────────────────────────

        @app.route("/api/backups/list")
        def api_backups_list():
            return jsonify(_list_backups())

        @app.route("/api/backups/run", methods=["POST"])
        def api_backups_run():
            result = _run_backup()
            self._log_activity("backup", "Backup cycle completed")
            return jsonify(result)

        @app.route("/api/backups/restore", methods=["POST"])
        def api_backups_restore():
            data = request.json or {}
            return jsonify(_restore_backup(data.get("path", ""), data.get("target", "")))

        @app.route("/api/backups/status")
        def api_backups_status():
            return jsonify(_backup_status())

        # ── Cache Pipeline ─────────────────────────────────────────────────────

        @app.route("/api/cache/status")
        def api_cache_status():
            return jsonify(_get_cache_status())

        @app.route("/api/cache/run", methods=["POST"])
        def api_cache_run():
            data = request.json or {}
            result = _run_cache_pipeline(data.get("stages"))
            self._log_activity("cache", "Pipeline cycle started")
            return jsonify(result)

        @app.route("/api/cache/review_sheet", methods=["POST"])
        def api_cache_review_sheet():
            data = request.json or {}
            return jsonify(_generate_review_sheet(data.get("path", "data/qa_review.xlsx")))

    # ── Socket.IO ──────────────────────────────────────────────────────────────

    def _register_socketio(self) -> None:
        if SocketIO is None:
            return
        self._socketio = SocketIO(
            self._app, cors_allowed_origins="*",
            async_mode="threading", logger=False, engineio_logger=False,
        )
        sio = self._socketio

        @sio.on("connect")
        def on_connect():
            logger.debug("Intel Hub client connected")
            sio.emit("activity", list(self._activity))

        @sio.on("librarian_chat")
        def on_librarian_chat(data):
            question = data.get("question", "")
            if not question:
                return
            self._log_activity("librarian", f"Chat: {question[:60]}")
            result = _call_nexus("ask", question=question)
            sio.emit("librarian_response", {
                "question": question,
                "answer": result.get("answer", "No response"),
                "source": result.get("source", "nexus"),
                "confidence": result.get("confidence", 0),
            })

        @sio.on("nexus_search")
        def on_nexus_search(data):
            results = _call_nexus("search", query=data.get("q", ""), limit=20)
            sio.emit("search_results", results)

    # ── Push loop ──────────────────────────────────────────────────────────────

    def _push_loop(self) -> None:
        """Push system metrics every 5 seconds via Socket.IO."""
        while not self._stop_event.wait(5.0):
            if self._socketio is None:
                continue
            try:
                metrics = self._get_overview()
                self._socketio.emit("metrics_update", metrics)
            except Exception:
                pass

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_overview(self) -> Dict[str, Any]:
        """Collect overview metrics from all subsystems."""
        overview: Dict[str, Any] = {
            "timestamp": _now(),
            "nexus": {"available": False, "entries": 0, "qa_pairs": 0, "rules": 0},
            "lmstudio": {"available": False, "models": []},
            "scheduler": {"running": False, "task_count": 0, "next_run": None},
            "system": _get_system_resources(),
        }
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            if client.is_available():
                stats = client.get_stats()
                overview["nexus"] = {
                    "available": True,
                    "entries": stats.get("total_entries", 0),
                    "qa_pairs": stats.get("qa_pairs", 0),
                    "rules": stats.get("rules", 0),
                }
        except Exception:
            pass
        try:
            import requests
            r = requests.get("http://localhost:1234/api/v1/models", timeout=2)
            if r.ok:
                models = r.json().get("data", [])
                overview["lmstudio"] = {"available": True, "models": [m.get("id") for m in models]}
        except Exception:
            pass
        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon
            daemon = get_scheduler_daemon()
            overview["scheduler"] = {
                "running": daemon.is_running(),
                "task_count": len(daemon.get_task_list()),
            }
        except Exception:
            pass
        return overview

    def _log_activity(self, category: str, message: str) -> None:
        entry = {"ts": _now(), "cat": category, "msg": message}
        self._activity.appendleft(entry)
        if self._socketio:
            try:
                self._socketio.emit("activity_item", entry)
            except Exception:
                pass


# ──── API Helpers ─────────────────────────────────────────────────────────────

def _call_nexus(action: str, **kwargs) -> Dict[str, Any]:
    """Call Nexus client with graceful fallback."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if not client.is_available():
            return {"error": "Nexus unavailable"}
        if action == "stats":
            return client.get_stats() or {}
        if action == "search":
            results = client.search(kwargs.get("query", ""), limit=kwargs.get("limit", 20))
            return {"results": results or []}
        if action == "entries":
            results = client.find_entries(
                category=kwargs.get("category") or None,
                limit=kwargs.get("limit", 50),
            )
            return {"entries": results or []}
        if action == "qa":
            results = client.find_qa("", limit=kwargs.get("limit", 100))
            return {"pairs": results or []}
        if action == "get_entry":
            result = client.get_entry(kwargs.get("entry_id", ""))
            return result or {"error": "Not found"}
        if action == "add":
            result = client.add_entry(
                title=kwargs.get("title", ""),
                content=kwargs.get("content", ""),
                content_type=kwargs.get("content_type", "note"),
                category=kwargs.get("category", "general"),
            )
            return {"success": True, "id": result}
        if action == "ask":
            result = client.ask(kwargs.get("question", ""))
            return result or {"answer": "No response", "source": "nexus"}
        if action == "categories":
            cats = client.get_categories()
            return {"categories": cats or []}
        return {"error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.error("Nexus call %s failed: %s", action, exc)
        return {"error": str(exc)}


def _call_nlm(action: str, **kwargs) -> Dict[str, Any]:
    """Call NLM hybrid router."""
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        hybrid = get_nlm_hybrid()
        if action == "list_notebooks":
            return {"notebooks": hybrid.list_notebooks() or []}
        if action == "get_notebook":
            return hybrid.get_notebook(kwargs.get("notebook_id", "")) or {}
        if action == "generate":
            nb_id = kwargs.get("notebook_id", "")
            gen_type = kwargs.get("type", "study_guide")
            return hybrid.generate_document(nb_id, gen_type, kwargs.get("prompt", "")) or {}
        if action == "distill":
            return hybrid.distill_to_nexus(
                kwargs.get("notebook_id", ""),
                count=kwargs.get("count", 10),
            ) or {}
        if action == "ask":
            return hybrid.ask(
                notebook_id=kwargs.get("notebook_id"),
                question=kwargs.get("question", ""),
            ) or {}
        return {"error": f"Unknown NLM action: {action}"}
    except Exception as exc:
        logger.warning("NLM call %s failed: %s", action, exc)
        return {"error": str(exc)}


def _get_copilot_rules() -> Dict[str, Any]:
    """Read Copilot governance rules from .github/instructions/ + Nexus."""
    rules = []
    inst_dir = Path(".github") / "instructions"
    if inst_dir.exists():
        for f in sorted(inst_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                rules.append({
                    "file": f.name,
                    "path": str(f),
                    "size": len(content),
                    "preview": content[:300],
                })
            except Exception:
                pass
    # Also fetch from Nexus
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if client.is_available():
            nexus_rules = client.get_all_rules() or []
            return {"files": rules, "nexus_rules": nexus_rules}
    except Exception:
        pass
    return {"files": rules, "nexus_rules": []}


def _get_copilot_agents() -> Dict[str, Any]:
    """Read Copilot agent definition files from .github/agents/."""
    agents = []
    agents_dir = Path(".github") / "agents"
    if agents_dir.exists():
        for f in sorted(agents_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                # Extract agent name from first heading
                name = f.stem.replace("_", " ").replace("-", " ").title()
                agents.append({
                    "file": f.name,
                    "path": str(f),
                    "name": name,
                    "size": len(content),
                    "preview": content[:400],
                    "full": content,
                })
            except Exception:
                pass
    return {"agents": agents, "count": len(agents)}


def _get_nexus_prompts() -> Dict[str, Any]:
    """Fetch versioned prompts from Nexus."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if client.is_available():
            prompts = client.find_entries(content_type="prompt", limit=100)
            return {"prompts": prompts or []}
    except Exception as exc:
        return {"error": str(exc)}
    return {"prompts": []}


def _get_copilot_hooks() -> Dict[str, Any]:
    """List Copilot hook scripts from .github/hooks/."""
    hooks = []
    hooks_dir = Path(".github") / "hooks"
    if hooks_dir.exists():
        for f in sorted(hooks_dir.iterdir()):
            if f.is_file() and f.suffix in (".py", ".sh", ".ps1", ".json"):
                try:
                    stat = f.stat()
                    hooks.append({
                        "file": f.name,
                        "path": str(f),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                except Exception:
                    pass
    return {"hooks": hooks}


def _get_copilot_memory() -> Dict[str, Any]:
    """Fetch Copilot memory entries from Nexus."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if client.is_available():
            entries = client.find_entries(category="copilot", limit=50)
            return {"entries": entries or [], "count": len(entries or [])}
    except Exception:
        pass
    return {"entries": [], "count": 0}


def _read_copilot_file(path: str) -> Dict[str, Any]:
    """Read a Copilot governance file (instructions, agents, hooks)."""
    if not path:
        return {"error": "No path provided"}
    # Security: only allow .github/ paths
    p = Path(path)
    try:
        if not str(p.resolve()).startswith(str(Path(".github").resolve())):
            # Allow session-state too
            if ".copilot" not in str(p) and ".github" not in str(p):
                return {"error": "Access denied — only .github/ paths allowed"}
        content = p.read_text(encoding="utf-8", errors="ignore")
        return {"path": str(p), "content": content, "size": len(content)}
    except Exception as exc:
        return {"error": str(exc)}


def _write_copilot_file(path: str, content: str) -> Dict[str, Any]:
    """Write a Copilot governance file."""
    if not path or not content:
        return {"error": "Path and content required"}
    p = Path(path)
    if ".github" not in str(p):
        return {"error": "Can only write to .github/ paths"}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(p), "size": len(content)}
    except Exception as exc:
        return {"error": str(exc)}


def _get_datasets() -> Dict[str, Any]:
    """List all training datasets."""
    datasets = []
    ds_dir = Path("training") / "datasets"
    if ds_dir.exists():
        for f in sorted(ds_dir.glob("*.jsonl")):
            try:
                lines = sum(1 for _ in open(f, encoding="utf-8"))
                stat = f.stat()
                datasets.append({
                    "name": f.stem,
                    "file": f.name,
                    "path": str(f),
                    "examples": lines,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
            except Exception:
                pass
    return {"datasets": datasets, "count": len(datasets)}


def _get_training_jobs() -> Dict[str, Any]:
    """Get current training job state."""
    state_file = Path("training") / ".auto_train_state.json"
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
            return {"jobs": [state], "active": state.get("status") == "running"}
        except Exception:
            pass
    return {"jobs": [], "active": False}


def _start_training_job(data: Dict[str, Any]) -> Dict[str, Any]:
    """Launch a fine-tuning job (non-blocking)."""
    try:
        dataset = data.get("dataset", "")
        model = data.get("model", "google/gemma-3-270m-it")
        epochs = data.get("epochs", 3)
        if not dataset:
            return {"error": "dataset required"}

        import subprocess, sys
        cmd = [
            sys.executable, "-m", "training.finetune_local",
            "--dataset", dataset, "--epochs", str(epochs),
        ]
        subprocess.Popen(cmd, cwd=str(Path.cwd()))
        return {"success": True, "dataset": dataset, "model": model, "epochs": epochs, "status": "started"}
    except Exception as exc:
        return {"error": str(exc)}


def _generate_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a training dataset using NLM teacher."""
    try:
        from training.generate_datasets import generate_dataset
        dataset_type = data.get("type", "tag_extraction")
        result = generate_dataset(dataset_type)
        return {"success": True, "type": dataset_type, "result": result}
    except Exception as exc:
        return {"error": str(exc)}


def _get_model_registry() -> Dict[str, Any]:
    """List fine-tuned models from training/output/."""
    models = []
    output_dir = Path("training") / "output"
    if output_dir.exists():
        for d in sorted(output_dir.iterdir()):
            if d.is_dir():
                adapter = d / "adapter_model.bin"
                config = d / "adapter_config.json"
                meta_file = d / "benchmark.json"
                meta = {}
                if meta_file.exists():
                    try:
                        with open(meta_file) as f:
                            meta = json.load(f)
                    except Exception:
                        pass
                models.append({
                    "name": d.name,
                    "path": str(d),
                    "has_adapter": adapter.exists(),
                    "has_config": config.exists(),
                    "benchmark": meta,
                    "created": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
    return {"models": models, "count": len(models)}


def _get_benchmarks() -> Dict[str, Any]:
    """Load benchmark results from training/benchmarks/."""
    benchmarks = []
    bench_dir = Path("benchmarks")
    if bench_dir.exists():
        for f in sorted(bench_dir.glob("*_report.json")):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                benchmarks.append({
                    "name": f.stem.replace("_report", ""),
                    "file": f.name,
                    "data": data,
                })
            except Exception:
                pass
    return {"benchmarks": benchmarks}


def _get_scheduler_tasks() -> Dict[str, Any]:
    """Fetch scheduler task list and status."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        tasks = daemon.get_task_list()
        return {"tasks": tasks or [], "running": daemon.is_running()}
    except Exception as exc:
        return {"error": str(exc), "tasks": [], "running": False}


def _trigger_scheduler_task(task_id: str) -> Dict[str, Any]:
    """Manually trigger a scheduler task."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        result = daemon.trigger_now(task_id)
        return {"success": True, "task_id": task_id, "result": result}
    except Exception as exc:
        return {"error": str(exc)}


def _get_scheduler_history(limit: int = 50) -> Dict[str, Any]:
    """Get scheduler task execution history."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        history = daemon.get_execution_history(limit=limit)
        return {"history": history or []}
    except Exception as exc:
        return {"error": str(exc), "history": []}


def _run_conversation_analysis(text: str, mode: str = "auto") -> Dict[str, Any]:
    """Run conversation analysis on provided text."""
    try:
        from engine.nexus.conversation_analyzer import get_conversation_analyzer
        analyzer = get_conversation_analyzer()
        result = analyzer.analyze(text, mode=mode, store_to_profile=True)
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


def _run_recent_analysis() -> Dict[str, Any]:
    """Analyze most recent conversation session."""
    try:
        from engine.nexus.conversation_analyzer import get_conversation_analyzer
        analyzer = get_conversation_analyzer()
        result = analyzer.analyze_recent_turns(store_to_profile=True)
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


def _get_user_profile() -> Dict[str, Any]:
    """Get the full user profile."""
    try:
        from engine.nexus.user_profile import get_user_profile_store
        return get_user_profile_store().get_profile()
    except Exception as exc:
        return {"error": str(exc)}


def _update_user_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    """Merge updates into user profile."""
    try:
        from engine.nexus.user_profile import get_user_profile_store
        store = get_user_profile_store()
        updated = store.merge(data)
        return {"success": True, "profile": updated}
    except Exception as exc:
        return {"error": str(exc)}


def _list_backups() -> Dict[str, Any]:
    try:
        from engine.nexus.backup_manager import get_backup_manager
        return {"backups": get_backup_manager().list_backups()}
    except Exception as exc:
        return {"error": str(exc), "backups": []}


def _run_backup() -> Dict[str, Any]:
    try:
        from engine.nexus.backup_manager import get_backup_manager
        result = get_backup_manager().run_backup()
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


def _restore_backup(path: str, target: str) -> Dict[str, Any]:
    try:
        from engine.nexus.backup_manager import get_backup_manager
        return get_backup_manager().restore_backup(path, target)
    except Exception as exc:
        return {"error": str(exc)}


def _backup_status() -> Dict[str, Any]:
    try:
        from engine.nexus.backup_manager import get_backup_manager
        return get_backup_manager().get_last_result() or {"status": "no backups yet"}
    except Exception as exc:
        return {"error": str(exc)}


def _get_cache_status() -> Dict[str, Any]:
    try:
        from engine.nexus.cache_pipeline import get_cache_pipeline
        pipeline = get_cache_pipeline()
        last = pipeline.get_last_result()
        gaps = pipeline.get_gap_list()
        return {"last_cycle": last, "gaps": gaps or []}
    except Exception as exc:
        return {"error": str(exc)}


def _run_cache_pipeline(stages=None) -> Dict[str, Any]:
    try:
        from engine.nexus.cache_pipeline import get_cache_pipeline
        pipeline = get_cache_pipeline()
        result = pipeline.run_full_cycle(dry_run=False)
        return result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}
    except Exception as exc:
        return {"error": str(exc)}


def _generate_review_sheet(path: str) -> Dict[str, Any]:
    try:
        from engine.nexus.review_sheet import get_review_sheet
        rs = get_review_sheet()
        rs.generate([], path=path)
        return {"success": True, "path": path}
    except Exception as exc:
        return {"error": str(exc)}


def _get_system_resources() -> Dict[str, Any]:
    """Get CPU/RAM/GPU metrics."""
    resources: Dict[str, Any] = {
        "cpu_percent": 0, "ram_percent": 0, "ram_used_gb": 0, "ram_total_gb": 0,
        "gpu_vram_used_mb": 0, "gpu_vram_total_mb": 0, "gpu_percent": 0,
    }
    try:
        import psutil
        resources["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        resources["ram_percent"] = mem.percent
        resources["ram_used_gb"] = round(mem.used / 1e9, 1)
        resources["ram_total_gb"] = round(mem.total / 1e9, 1)
    except Exception:
        pass
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            parts = [x.strip() for x in r.stdout.strip().split(",")]
            if len(parts) == 3:
                resources["gpu_vram_used_mb"] = int(parts[0])
                resources["gpu_vram_total_mb"] = int(parts[1])
                resources["gpu_percent"] = int(parts[2])
    except Exception:
        pass
    return resources


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──── TTS / VTT Helpers ───────────────────────────────────────────────────────

def _get_tts_config() -> Dict[str, Any]:
    """Return current TTS manager config."""
    try:
        from engine.tts.tts_manager import get_tts_manager
        mgr = get_tts_manager()
        cfg = getattr(mgr, "get_tts_config", lambda: {})()
        return {"success": True, "config": cfg or {}}
    except Exception as exc:
        return {"error": str(exc), "config": {}}


def _update_tts_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Update TTS manager config."""
    try:
        from engine.tts.tts_manager import get_tts_manager
        mgr = get_tts_manager()
        if hasattr(mgr, "update_tts_config"):
            mgr.update_tts_config(data)
        return {"success": True}
    except Exception as exc:
        return {"error": str(exc)}


def _get_tts_voices() -> Dict[str, Any]:
    """Return all available TTS voices per backend."""
    try:
        import yaml
        from engine.config import get_config
        cfg = get_config()
        voices_yaml = cfg.get("tts.voices_config", "config/voices.yaml")
        try:
            with open(voices_yaml, "r", encoding="utf-8") as f:
                all_voices = yaml.safe_load(f) or {}
        except Exception:
            all_voices = {}

        # Piper voices — scan model directory
        piper_dir = cfg.get("tts.piper.model_dir", r"C:\Files\Models\tts\piper")
        piper_voices: list[str] = []
        try:
            import os
            piper_voices = [
                f.replace(".onnx", "")
                for f in os.listdir(piper_dir)
                if f.endswith(".onnx")
            ]
        except Exception:
            piper_voices = ["en_US-amy-medium", "en_US-ryan-high"]

        return {
            "success": True,
            "piper": piper_voices,
            "orpheus": list(all_voices.get("voices", {}).keys()),
            "orpheus_native": list(all_voices.get("voices", {}).keys()),
            "qwen3": list(all_voices.get("voices", {}).keys()),
            "designs": all_voices.get("voices", {}),
        }
    except Exception as exc:
        return {"error": str(exc), "piper": [], "orpheus": [], "orpheus_native": [], "qwen3": []}


def _get_tts_benchmarks() -> Dict[str, Any]:
    """Return last known TTS benchmark results from Nexus / stored metrics."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        mm = get_meta_metrics()
        return {
            "success": True,
            "benchmarks": mm.get_metric_series("tts_rtf", limit=20) or [],
        }
    except Exception as exc:
        return {"error": str(exc), "benchmarks": []}


def _get_vtt_config() -> Dict[str, Any]:
    """Return current VTT configuration."""
    try:
        from engine.config import get_config
        cfg = get_config()
        return {
            "success": True,
            "config": {
                "whisper_url": cfg.get("stt.server_url", "http://localhost:5051"),
                "whisper_model": cfg.get("stt.model", "base"),
                "default_backend": cfg.get("stt.default_backend", "web_speech"),
                "language": cfg.get("stt.language", "en-US"),
            },
        }
    except Exception as exc:
        return {"error": str(exc), "config": {}}


def _update_vtt_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Persist VTT config changes at runtime."""
    try:
        from engine.config import get_config
        cfg = get_config()
        for key, val in data.items():
            cfg.set(f"stt.{key}", val)
        return {"success": True}
    except Exception as exc:
        return {"error": str(exc)}


# ──── Module Entry Point ──────────────────────────────────────────────────────

def get_intel_hub_scene(**kwargs) -> IntelHubScene:
    return IntelHubScene(**kwargs)
