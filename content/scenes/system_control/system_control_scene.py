"""System Control Panel — Live configuration editor, service manager, and system monitor.

Provides:
- Config file browser and live YAML/JSON editor with validation
- Service health dashboard (all CosySim scenes + services)
- NLM proxy status and cookie management
- Nexus health and quick search
- LMStudio status and loaded models
- Real-time log viewer
- System metrics (CPU, RAM, GPU, disk)
"""
from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from engine.config import get_config
from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from content.shared import register_shared_assets

logger = logging.getLogger(__name__)

SCENE_ID = "system_control"
DEFAULT_PORT = 5575

# ── Config file catalogue ────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"
_DATA_DIR = _PROJECT_ROOT / "data"

# Allowed config files (relative to project root)
_EDITABLE_CONFIGS: Dict[str, str] = {
    "default.yaml": "config/default.yaml",
    "development.yaml": "config/development.yaml",
    "production.yaml": "config/production.yaml",
    "launcher.yaml": "config/launcher.yaml",
    "news_sources.yaml": "config/news_sources.yaml",
    "voices.yaml": "config/voices.yaml",
    "skill_manifests.yaml": "config/skill_manifests.yaml",
    "mcp.json": "config/mcp.json",
    "nlm_meta.json": "data/nlm_meta.json",
}

# Known service endpoints for health checks
_SERVICE_ENDPOINTS: List[Dict[str, Any]] = [
    {"id": "nexus", "name": "Nexus KMS", "url": "http://localhost:8700/api/health", "port": 8700},
    {"id": "nlm_proxy", "name": "NLM Proxy", "url": "http://localhost:8800/health", "port": 8800},
    {"id": "hub", "name": "Scene Hub", "url": "http://localhost:8500/health", "port": 8500},
    {"id": "nexus_panel", "name": "Nexus Panel", "url": "http://localhost:5570/api/health", "port": 5570},
    {"id": "command_center", "name": "Command Center", "url": "http://localhost:5566/api/health", "port": 5566},
    {"id": "bedroom", "name": "Bedroom", "url": "http://localhost:5556/api/health", "port": 5556},
    {"id": "phone", "name": "Phone", "url": "http://localhost:5555/api/health", "port": 5555},
    {"id": "heist", "name": "Heist", "url": "http://localhost:5565/api/health", "port": 5565},
    {"id": "realm", "name": "Realm", "url": "http://localhost:5562/api/health", "port": 5562},
    {"id": "neoncity", "name": "NeonCity", "url": "http://localhost:5563/api/health", "port": 5563},
    {"id": "lounge", "name": "Lounge", "url": "http://localhost:5557/api/health", "port": 5557},
    {"id": "tavern", "name": "Tavern", "url": "http://localhost:5558/api/health", "port": 5558},
    {"id": "casino", "name": "Casino", "url": "http://localhost:5559/api/health", "port": 5559},
    {"id": "warzone", "name": "Warzone", "url": "http://localhost:5561/api/health", "port": 5561},
    {"id": "games", "name": "Games", "url": "http://localhost:5567/api/health", "port": 5567},
    {"id": "lmstudio", "name": "LMStudio", "url": "http://localhost:1234/api/v1/models", "port": 1234},
    {"id": "comfyui", "name": "ComfyUI", "url": "http://localhost:8188/system_stats", "port": 8188},
    {"id": "tts", "name": "TTS Server", "url": "http://localhost:8600/health", "port": 8600},
    {"id": "system_control", "name": "System Control", "url": "http://localhost:5575/api/health", "port": 5575},
]


def _http_get(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """Perform a GET request, returning parsed JSON or None on error."""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _check_service(endpoint: Dict[str, Any]) -> Dict[str, Any]:
    """Check health of a single service endpoint."""
    data = _http_get(endpoint["url"], timeout=2.0)
    return {
        "id": endpoint["id"],
        "name": endpoint["name"],
        "port": endpoint["port"],
        "url": endpoint["url"],
        "online": data is not None,
        "data": data,
    }


def _get_system_metrics() -> Dict[str, Any]:
    """Gather basic system metrics (CPU, RAM, GPU if psutil/pynvml available)."""
    metrics: Dict[str, Any] = {"timestamp": time.time()}
    try:
        import psutil
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        metrics["ram_total_gb"] = round(vm.total / 1e9, 1)
        metrics["ram_used_gb"] = round(vm.used / 1e9, 1)
        metrics["ram_percent"] = vm.percent
        disk = psutil.disk_usage(str(_PROJECT_ROOT))
        metrics["disk_total_gb"] = round(disk.total / 1e9, 1)
        metrics["disk_used_gb"] = round(disk.used / 1e9, 1)
        metrics["disk_percent"] = round(disk.percent, 1)
    except ImportError:
        metrics["cpu_percent"] = None
        metrics["ram_percent"] = None

    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        metrics["gpu_vram_used_mb"] = round(mem.used / 1e6, 0)
        metrics["gpu_vram_total_mb"] = round(mem.total / 1e6, 0)
        metrics["gpu_vram_percent"] = round(mem.used / mem.total * 100, 1)
        metrics["gpu_util_percent"] = util.gpu
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        metrics["gpu_name"] = gpu_name if isinstance(gpu_name, str) else gpu_name.decode()
    except Exception:
        metrics["gpu_vram_used_mb"] = None

    return metrics


class SystemControlScene(BaseScene, NexusSceneMixin):
    """System Control Panel — live config editor, service monitor, system tools."""

    SCENE_METADATA = {
        "title": "System Control",
        "description": "Live configuration editor, service health dashboard, NLM proxy control, "
                       "Nexus management, LMStudio status, and system metrics.",
        "genre": "admin",
        "type": "admin",
        "max_characters": 0,
        "features": [
            "config_editor",
            "service_monitor",
            "nlm_control",
            "nexus_health",
            "lmstudio_status",
            "system_metrics",
            "log_viewer",
            "launcher_control",
        ],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        cfg = get_config()
        port = cfg.get(f"scenes.{SCENE_ID}.port", port)
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        scene_dir = Path(__file__).parent
        self.app = Flask(
            __name__,
            template_folder=str(scene_dir / "templates"),
            static_folder=str(scene_dir / "static"),
        )
        self.app.config["SECRET_KEY"] = cfg.get("flask.secret_key", "system-control-key")
        register_shared_assets(self.app)
        CORS(self.app)

        self._register_routes()
        logger.info("SystemControlScene initialized on port %d", port)

    # ── Route registration ────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all HTTP routes."""
        app = self.app

        # ── UI ──────────────────────────────────────────────────────────────

        @app.route("/")
        def index():
            return render_template("system_control_ui.html", title="System Control")

        # ── Health ───────────────────────────────────────────────────────────

        @app.route("/api/health")
        def health():
            return jsonify({"status": "ok", "scene": SCENE_ID, "port": self.port})

        @app.route("/api/plugin_info")
        def plugin_info():
            return jsonify({
                "scene_id": SCENE_ID,
                "title": self.SCENE_METADATA["title"],
                "description": self.SCENE_METADATA["description"],
                "port": self.port,
                "url": f"http://localhost:{self.port}",
            })

        # ── System metrics ────────────────────────────────────────────────────

        @app.route("/api/metrics")
        def system_metrics():
            return jsonify(_get_system_metrics())

        # ── Service health ────────────────────────────────────────────────────

        @app.route("/api/services")
        def service_status():
            """Check health of all known services in parallel."""
            results = []
            threads = []
            lock = threading.Lock()

            def check(ep: Dict[str, Any]) -> None:
                result = _check_service(ep)
                with lock:
                    results.append(result)

            for ep in _SERVICE_ENDPOINTS:
                t = threading.Thread(target=check, args=(ep,))
                threads.append(t)
                t.start()
            for t in threads:
                t.join(timeout=3.0)

            online = sum(1 for r in results if r["online"])
            return jsonify({
                "services": sorted(results, key=lambda x: x["name"]),
                "online": online,
                "total": len(results),
            })

        @app.route("/api/services/<service_id>")
        def service_detail(service_id: str):
            """Get health detail for a specific service."""
            ep = next((e for e in _SERVICE_ENDPOINTS if e["id"] == service_id), None)
            if not ep:
                return jsonify({"error": "unknown service"}), 404
            return jsonify(_check_service(ep))

        # ── Config file management ─────────────────────────────────────────────

        @app.route("/api/config")
        def list_configs():
            """List all editable config files with their existence status."""
            configs = []
            for name, rel_path in _EDITABLE_CONFIGS.items():
                full = _PROJECT_ROOT / rel_path
                configs.append({
                    "name": name,
                    "path": rel_path,
                    "exists": full.exists(),
                    "size": full.stat().st_size if full.exists() else 0,
                    "modified": full.stat().st_mtime if full.exists() else None,
                })
            return jsonify({"configs": configs})

        @app.route("/api/config/<path:filename>")
        def read_config(filename: str):
            """Read a config file's contents.

            The filename must match a key in _EDITABLE_CONFIGS.
            """
            rel_path = _EDITABLE_CONFIGS.get(filename)
            if not rel_path:
                return jsonify({"error": "file not in allowed list"}), 403
            full = _PROJECT_ROOT / rel_path
            if not full.exists():
                return jsonify({"error": "file not found", "path": rel_path}), 404
            content = full.read_text(encoding="utf-8")
            return jsonify({
                "filename": filename,
                "path": rel_path,
                "content": content,
                "size": len(content),
            })

        @app.route("/api/config/<path:filename>", methods=["POST"])
        def write_config(filename: str):
            """Write/update a config file after validation.

            Body (JSON): {"content": "yaml or json string"}

            Validates YAML/JSON before writing. Creates a .bak backup first.
            """
            rel_path = _EDITABLE_CONFIGS.get(filename)
            if not rel_path:
                return jsonify({"error": "file not in allowed list"}), 403
            full = _PROJECT_ROOT / rel_path
            body = request.json or {}
            content = body.get("content", "")
            if not content:
                return jsonify({"error": "empty content"}), 400

            # Validate before writing
            try:
                if filename.endswith(".json"):
                    json.loads(content)
                elif filename.endswith((".yaml", ".yml")):
                    yaml.safe_load(content)
            except (json.JSONDecodeError, yaml.YAMLError) as exc:
                return jsonify({"error": "validation_failed", "detail": str(exc)}), 422

            # Backup existing file
            if full.exists():
                backup = full.with_suffix(full.suffix + ".bak")
                backup.write_bytes(full.read_bytes())

            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            logger.info("Config written: %s (%d chars)", rel_path, len(content))
            return jsonify({"ok": True, "path": rel_path, "size": len(content), "backed_up": True})

        @app.route("/api/config/<path:filename>/restore", methods=["POST"])
        def restore_config(filename: str):
            """Restore a config file from its .bak backup."""
            rel_path = _EDITABLE_CONFIGS.get(filename)
            if not rel_path:
                return jsonify({"error": "file not in allowed list"}), 403
            full = _PROJECT_ROOT / rel_path
            backup = full.with_suffix(full.suffix + ".bak")
            if not backup.exists():
                return jsonify({"error": "no backup found"}), 404
            full.write_bytes(backup.read_bytes())
            return jsonify({"ok": True, "restored_from": str(backup)})

        # ── Launcher config ────────────────────────────────────────────────────

        @app.route("/api/launcher")
        def get_launcher():
            """Read launcher.yaml and return auto_start states."""
            lf = _CONFIG_DIR / "launcher.yaml"
            if not lf.exists():
                return jsonify({"error": "launcher.yaml not found"}), 404
            data = yaml.safe_load(lf.read_text(encoding="utf-8")) or {}
            return jsonify(data)

        @app.route("/api/launcher/<section>/<target>", methods=["POST"])
        def set_launcher_auto_start(section: str, target: str):
            """Toggle auto_start for a launcher target.

            Body (JSON): {"auto_start": true/false}
            Section is 'services' or 'scenes'.
            """
            if section not in ("services", "scenes"):
                return jsonify({"error": "invalid section"}), 400
            body = request.json or {}
            auto_start = bool(body.get("auto_start", False))
            lf = _CONFIG_DIR / "launcher.yaml"
            if not lf.exists():
                return jsonify({"error": "launcher.yaml not found"}), 404
            data = yaml.safe_load(lf.read_text(encoding="utf-8")) or {}
            if section not in data:
                data[section] = {}
            if target not in data[section]:
                data[section][target] = {}
            data[section][target]["auto_start"] = auto_start
            # Write back
            backup = lf.with_suffix(".yaml.bak")
            backup.write_bytes(lf.read_bytes())
            lf.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
            return jsonify({"ok": True, "section": section, "target": target, "auto_start": auto_start})

        # ── NLM proxy passthrough ──────────────────────────────────────────────

        @app.route("/api/nlm/status")
        def nlm_status():
            """Get NLM proxy status."""
            data = _http_get("http://localhost:8800/health")
            if data is None:
                return jsonify({"online": False, "error": "NLM proxy unreachable at :8800"})
            return jsonify({"online": True, **data})

        @app.route("/api/nlm/notebooks")
        def nlm_notebooks():
            """List NLM notebooks via proxy."""
            data = _http_get("http://localhost:8800/notebooks")
            if data is None:
                return jsonify({"error": "NLM proxy unreachable"}), 503
            return jsonify(data)

        @app.route("/api/nlm/import", methods=["POST"])
        def nlm_import_har():
            """Import NLM HAR file via proxy.

            Body (JSON): {"har_path": "C:\\path\\to\\file.har"}
            or multipart with "har_file" field.
            """
            import urllib.request
            import urllib.error
            proxy_url = "http://localhost:8800/cookies/import"
            try:
                if request.is_json:
                    body = json.dumps(request.json or {}).encode()
                    req = urllib.request.Request(
                        proxy_url, data=body,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        return jsonify(json.loads(resp.read().decode()))
                else:
                    return jsonify({"error": "JSON body with har_path required"}), 400
            except Exception as exc:
                return jsonify({"error": str(exc)}), 502

        @app.route("/api/nlm/capture", methods=["POST"])
        def nlm_capture_cookies():
            """Trigger Chrome CDP cookie capture via NLM proxy."""
            import urllib.request
            try:
                req = urllib.request.Request(
                    "http://localhost:8800/cookies/capture",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return jsonify(json.loads(resp.read().decode()))
            except Exception as exc:
                return jsonify({"error": str(exc)}), 502

        # ── Nexus quick summary ────────────────────────────────────────────────

        @app.route("/api/nexus/status")
        def nexus_status():
            """Get Nexus health summary."""
            data = _http_get("http://localhost:8700/api/health")
            if data is None:
                return jsonify({"online": False, "error": "Nexus unreachable at :8700"})
            return jsonify({"online": True, **data})

        @app.route("/api/nexus/search")
        def nexus_search():
            """Quick Nexus search.

            Query params: q (required), limit (default 10)
            """
            import urllib.request
            import urllib.parse
            q = request.args.get("q", "").strip()
            if not q:
                return jsonify({"error": "missing q parameter"}), 400
            limit = request.args.get("limit", 10, type=int)
            params = urllib.parse.urlencode({"q": q, "limit": limit})
            data = _http_get(f"http://localhost:8700/api/search?{params}")
            if data is None:
                return jsonify({"error": "Nexus unreachable"}), 503
            return jsonify(data)

        # ── LMStudio status ────────────────────────────────────────────────────

        @app.route("/api/lmstudio")
        def lmstudio_status():
            """Get LMStudio model list and status."""
            data = _http_get("http://localhost:1234/api/v1/models")
            if data is None:
                return jsonify({"online": False, "error": "LMStudio unreachable at :1234"})
            models = data.get("data", [])
            return jsonify({
                "online": True,
                "model_count": len(models),
                "models": [{"id": m.get("id"), "type": m.get("type")} for m in models],
            })

        # ── Log viewer ────────────────────────────────────────────────────────

        @app.route("/api/logs")
        def list_logs():
            """List available log files."""
            logs_dir = _PROJECT_ROOT / "logs"
            if not logs_dir.exists():
                return jsonify({"logs": []})
            files = []
            for f in sorted(logs_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
            return jsonify({"logs": files})

        @app.route("/api/logs/<filename>")
        def read_log(filename: str):
            """Read the last N lines of a log file.

            Query params: lines (default 200)
            """
            if "/" in filename or ".." in filename:
                return jsonify({"error": "invalid filename"}), 400
            log_file = _PROJECT_ROOT / "logs" / filename
            if not log_file.exists():
                return jsonify({"error": "log not found"}), 404
            lines_count = request.args.get("lines", 200, type=int)
            content = log_file.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()[-lines_count:]
            return jsonify({"filename": filename, "lines": lines, "total_lines": len(content.splitlines())})

        # ── Git status ────────────────────────────────────────────────────────

        @app.route("/api/git")
        def git_status():
            """Return recent git log and current branch."""
            try:
                branch = subprocess.check_output(
                    ["git", "--no-pager", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=str(_PROJECT_ROOT), text=True, timeout=5
                ).strip()
                log_out = subprocess.check_output(
                    ["git", "--no-pager", "log", "--oneline", "-10"],
                    cwd=str(_PROJECT_ROOT), text=True, timeout=5
                ).strip()
                status_out = subprocess.check_output(
                    ["git", "--no-pager", "status", "--short"],
                    cwd=str(_PROJECT_ROOT), text=True, timeout=5
                ).strip()
                return jsonify({
                    "branch": branch,
                    "log": log_out.splitlines(),
                    "status": status_out.splitlines(),
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

    # ── BaseScene interface ───────────────────────────────────────────────────

    def start(self) -> None:
        """Start the System Control Panel Flask server."""
        logger.info("Starting System Control Panel on port %d", self.port)
        self.app.run(
            host=self.host,
            port=self.port,
            debug=False,
            threaded=True,
            use_reloader=False,
        )

    def stop(self) -> None:
        """Stop the System Control Panel."""
        logger.info("System Control Panel stopping")

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return metadata for hub discovery."""
        return {
            "scene_id": SCENE_ID,
            "title": self.SCENE_METADATA["title"],
            "description": self.SCENE_METADATA["description"],
            "port": self.port,
            "url": f"http://localhost:{self.port}",
            "type": "admin",
            "icon": "⚙️",
        }
