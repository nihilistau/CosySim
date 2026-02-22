"""
Control Overlay Blueprint — Real-time system monitoring & interaction panel

Flask Blueprint mountable on any CosySim scene.  Provides:

* ``/overlay/`` — Main overlay panel HTML/JS/CSS
* ``/overlay/api/status`` — System status (models, VRAM, agents, scenes)
* ``/overlay/api/agents`` — All registered agents with state
* ``/overlay/api/agent/<id>`` — Detailed agent info + edit
* ``/overlay/api/pipeline`` — Interceptor pipeline state
* ``/overlay/api/config`` — Get/set config values
* ``/overlay/api/models`` — Model management (load/unload/list)
* ``/overlay/api/resources`` — ResourceManager status & control
* ``/overlay/api/events`` — SSE stream of real-time framework events
* ``/overlay/api/act`` — Inject messages / act as agent
* ``/overlay/api/memory`` — Browse agent memories
* ``/overlay/api/skills`` — List all registered skills
* ``/overlay/api/inference`` — Inference config defaults & override

Mount::

    from engine.overlay import mount_overlay
    mount_overlay(app, socketio)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, Optional

from flask import Blueprint, Response, jsonify, request, render_template_string

logger = logging.getLogger(__name__)

overlay_bp = Blueprint("overlay", __name__, url_prefix="/overlay")


# ── Main panel HTML ─────────────────────────────────────────────────────

@overlay_bp.route("/")
def overlay_panel():
    """Serve the overlay panel."""
    return render_template_string(_OVERLAY_HTML)


# ── System Status ───────────────────────────────────────────────────────

@overlay_bp.route("/api/status")
def api_status():
    """Combined system status."""
    result: Dict[str, Any] = {"ok": True, "timestamp": time.time()}

    # LMStudio
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        available = client.is_available()
        models = client.get_models() if available else []
        result["lmstudio"] = {
            "available": available,
            "native_api": available,  # v1 API is always native
            "models": models,
        }
    except Exception as exc:
        result["lmstudio"] = {"available": False, "error": str(exc)}

    # Resource Manager
    try:
        from engine.lmstudio.resource_manager import get_resource_manager
        result["resources"] = get_resource_manager().get_status()
    except Exception as exc:
        result["resources"] = {"error": str(exc)}

    # MCP Framework
    try:
        from engine.mcp.framework import get_framework
        fw = get_framework()
        result["framework"] = fw.get_status()
    except Exception as exc:
        result["framework"] = {"error": str(exc)}

    # Skills
    try:
        from engine.skills.registry import SKILL_REGISTRY
        result["skills_count"] = len(SKILL_REGISTRY._skills)
    except Exception:
        result["skills_count"] = 0

    return jsonify(result)


# ── Agents ──────────────────────────────────────────────────────────────

@overlay_bp.route("/api/agents")
def api_agents():
    """List all registered agents with their state."""
    try:
        from engine.mcp.character_registry import get_character_registry
        registry = get_character_registry()
        agents = []
        for cid in registry.list_characters():
            profile = registry.get_profile(cid)
            state = registry.get_state(cid)
            agents.append({
                "id": cid,
                "name": profile.name if profile else cid,
                "state": state,
                "scene": profile.scene_roles[0] if profile and profile.scene_roles else "",
            })
        return jsonify({"ok": True, "agents": agents})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@overlay_bp.route("/api/agent/<agent_id>", methods=["GET", "POST"])
def api_agent_detail(agent_id: str):
    """Get or update agent details."""
    try:
        from engine.mcp.character_registry import get_character_registry
        registry = get_character_registry()

        if request.method == "POST":
            data = request.get_json(force=True)
            registry.set_state(agent_id, **data.get("state", {}))
            return jsonify({"ok": True})

        info = registry.get_profile(agent_id)

        # Get MCP framework node info
        mcp_info = {}
        try:
            from engine.mcp.framework import get_framework
            char_node = get_framework().get_character(agent_id)
            mcp_info = {
                "inbox": list(char_node._inbox),
                "current_scene": char_node._current_scene,
                "tags": list(char_node._tags),
            }
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "agent": {
                "id": agent_id,
                "name": info.name if info else agent_id,
                "state": registry.get_state(agent_id),
                "mcp": mcp_info,
            },
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Pipeline ────────────────────────────────────────────────────────────

@overlay_bp.route("/api/pipeline")
def api_pipeline():
    """Get interceptor pipeline configuration."""
    try:
        from engine.mcp.comms_framework import InterceptorPipeline
        # Return info about registered interceptors
        pipeline_info = {"interceptors": [], "note": "Pipeline is per-governor instance"}
        return jsonify({"ok": True, "pipeline": pipeline_info})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Config ──────────────────────────────────────────────────────────────

@overlay_bp.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Get or update config values."""
    try:
        from engine.config import get_config
        cfg = get_config()

        if request.method == "POST":
            data = request.get_json(force=True)
            for key, value in data.items():
                cfg.set(key, value)
            return jsonify({"ok": True})

        # Return key config sections
        sections = {}
        for section in ["llm", "lmstudio", "hardware", "mcp", "tts", "comfyui"]:
            sections[section] = cfg.get(section, {})

        return jsonify({"ok": True, "config": sections})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Models ──────────────────────────────────────────────────────────────

@overlay_bp.route("/api/models")
def api_models():
    """List loaded and available models."""
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        loaded = client.get_models()

        # Also get model manager status
        from engine.lmstudio.model_manager import get_model_manager
        mm_status = get_model_manager().status()

        return jsonify({
            "ok": True,
            "loaded": loaded,
            "manager": mm_status,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@overlay_bp.route("/api/models/load", methods=["POST"])
def api_models_load():
    """Load a model."""
    try:
        data = request.get_json(force=True)
        model_id = data.get("model_id", "")
        if not model_id:
            return jsonify({"ok": False, "error": "model_id required"}), 400

        from engine.lmstudio.lms_client import get_lms_client
        from engine.lmstudio.inference_config import LoadConfig
        client = get_lms_client()

        load_config = LoadConfig(
            context_length=data.get("context_length"),
            gpu_offload=data.get("gpu_offload"),
            flash_attention=data.get("flash_attention"),
            ttl=data.get("ttl"),
        )
        success = client.load_model(model_id, config=load_config)
        return jsonify({"ok": success})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@overlay_bp.route("/api/models/unload", methods=["POST"])
def api_models_unload():
    """Unload a model."""
    try:
        data = request.get_json(force=True)
        model_id = data.get("model_id", "")
        if not model_id:
            return jsonify({"ok": False, "error": "model_id required"}), 400

        from engine.lmstudio.lms_client import get_lms_client
        get_lms_client().unload_model(model_id)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Resources ───────────────────────────────────────────────────────────

@overlay_bp.route("/api/resources", methods=["GET", "POST"])
def api_resources():
    """Get or update ResourceManager."""
    try:
        from engine.lmstudio.resource_manager import get_resource_manager
        rm = get_resource_manager()

        if request.method == "POST":
            data = request.get_json(force=True)
            result = rm.update_config(**data)
            return jsonify({"ok": True, "resources": result})

        return jsonify({"ok": True, "resources": rm.get_status()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Events SSE ──────────────────────────────────────────────────────────

@overlay_bp.route("/api/events")
def api_events():
    """SSE stream of real-time framework events."""
    def event_stream():
        try:
            from engine.services.activity_bus import get_activity_bus
            bus = get_activity_bus()
            last_id = 0
            while True:
                events = bus.get_recent(limit=10, since_id=last_id)
                for evt in events:
                    evt_id = evt.get("id", 0)
                    if evt_id > last_id:
                        last_id = evt_id
                    yield f"data: {json.dumps(evt)}\n\n"
                time.sleep(1.0)
        except GeneratorExit:
            pass
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


# ── Act as Agent ────────────────────────────────────────────────────────

@overlay_bp.route("/api/act", methods=["POST"])
def api_act():
    """Inject a message or act as an agent in the current scene."""
    try:
        data = request.get_json(force=True)
        action = data.get("action", "speak")  # speak, inject_event, override
        agent_id = data.get("agent_id", "")
        message = data.get("message", "")

        if action == "speak" and message:
            from engine.services.activity_bus import get_activity_bus
            get_activity_bus().publish(
                activity_type="user_injection",
                description=f"User speaking as {agent_id}: {message[:100]}",
                agent_id=agent_id or "overlay_user",
                scene=data.get("scene", "system"),
                data={"message": message, "via": "overlay"},
            )
            return jsonify({"ok": True, "injected": True})

        if action == "inject_event":
            from engine.mcp.framework import get_framework
            fw = get_framework()
            fw.emit_event(
                data.get("event_type", "user_event"),
                data.get("event_data", {}),
            )
            return jsonify({"ok": True})

        return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Memory ──────────────────────────────────────────────────────────────

@overlay_bp.route("/api/memory/<agent_id>")
def api_memory(agent_id: str):
    """Browse agent memories from RAG."""
    try:
        query = request.args.get("q", "")
        limit = int(request.args.get("limit", 10))

        from content.simulation.database.rag import RAGMemory
        rag = RAGMemory()
        results = rag.search(query or "recent events", n_results=limit, character_id=agent_id)
        return jsonify({"ok": True, "memories": results or []})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Skills ──────────────────────────────────────────────────────────────

@overlay_bp.route("/api/skills")
def api_skills():
    """List all registered skills."""
    try:
        from engine.skills.registry import SKILL_REGISTRY
        skills = []
        for name, meta in SKILL_REGISTRY._skills.items():
            skills.append({
                "name": name,
                "pack": meta.pack,
                "description": meta.description,
                "tags": meta.tags,
                "category": getattr(meta, "category", ""),
                "cooldown": getattr(meta, "cooldown", 0),
            })
        return jsonify({"ok": True, "skills": skills})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Shared Boards ───────────────────────────────────────────────────

@overlay_bp.route("/api/boards")
def api_boards():
    """List all shared boards (highscores + message boards)."""
    try:
        from engine.mcp.shared_boards import get_shared_boards
        boards = get_shared_boards().list_boards()
        return jsonify({"ok": True, "boards": boards})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@overlay_bp.route("/api/boards/<board_id>/scores")
def api_board_scores(board_id: str):
    """Get highscores for a board."""
    try:
        from engine.mcp.shared_boards import get_shared_boards
        limit = int(request.args.get("limit", 10))
        scores = get_shared_boards().get_highscores(board_id, limit)
        return jsonify({"ok": True, "scores": scores})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@overlay_bp.route("/api/boards/<board_id>/messages", methods=["GET", "POST"])
def api_board_messages(board_id: str):
    """Get or post messages to a shared board."""
    try:
        from engine.mcp.shared_boards import get_shared_boards
        boards = get_shared_boards()
        if request.method == "POST":
            data = request.get_json(force=True)
            result = boards.post_message(
                board_id, data.get("author_id", "anonymous"),
                data["content"], data.get("author_name"))
            return jsonify({"ok": True, "message": result})
        messages = boards.get_messages(
            board_id, int(request.args.get("limit", 50)))
        return jsonify({"ok": True, "messages": messages})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Streaming / v2.7 ────────────────────────────────────────────────────

@overlay_bp.route("/api/streaming")
def api_streaming():
    """v2.7 streaming stats: active streams, processed tokens, conversation branches."""
    result: Dict[str, Any] = {"ok": True}
    # VirtualAgentManager streaming stats
    try:
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        mgr = get_virtual_agent_manager()
        result["manager"] = {
            "total_calls": getattr(mgr, "_total_calls", 0),
            "active_agents": len(getattr(mgr, "_agents", {})),
        }
    except Exception as exc:
        result["manager"] = {"error": str(exc)}

    # Conversation branches
    try:
        from engine.lmstudio.conversation import ConversationManager
        cm = ConversationManager.instance()
        convos = cm.list_conversations() if hasattr(cm, "list_conversations") else []
        result["conversations"] = {
            "count": len(convos),
            "conversations": [
                {
                    "id": c.conversation_id,
                    "turns": len(c._history),
                    "branches": len(getattr(c, "_response_id_history", [])),
                }
                for c in (convos if isinstance(convos, list) else [])
            ][:20],
        }
    except Exception as exc:
        result["conversations"] = {"error": str(exc)}

    # StreamProcessor stats (from recent calls)
    try:
        from engine.agents.stream_processor import StreamProcessor
        result["stream_processor"] = {
            "available": True,
            "tag_patterns": list(StreamProcessor.DEFAULT_TAG_PATTERNS.keys())
            if hasattr(StreamProcessor, "DEFAULT_TAG_PATTERNS") else [],
        }
    except Exception:
        result["stream_processor"] = {"available": False}

    return jsonify(result)


# ── Inference Config ────────────────────────────────────────────────────

@overlay_bp.route("/api/inference", methods=["GET", "POST"])
def api_inference():
    """Get or override inference defaults."""
    try:
        from engine.lmstudio.inference_config import InferenceConfig

        if request.method == "POST":
            data = request.get_json(force=True)
            # Update the global LMS client's inference defaults
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
            new_config = InferenceConfig(**{
                k: v for k, v in data.items()
                if k in InferenceConfig.__dataclass_fields__
            })
            client._inference_defaults = InferenceConfig.merge(
                client._inference_defaults, new_config
            )
            return jsonify({"ok": True, "defaults": client._inference_defaults.to_dict()})

        # GET: return current defaults
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        return jsonify({"ok": True, "defaults": client._inference_defaults.to_dict()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Mount helper ────────────────────────────────────────────────────────

def mount_overlay(app, socketio=None) -> None:
    """
    Register the overlay Blueprint on a Flask app.

    Call this in any scene's setup to enable the control overlay::

        mount_overlay(app, socketio)

    Then access the overlay at ``http://host:port/overlay/``
    A toggle button is injected into every page via after_request.
    """
    app.register_blueprint(overlay_bp)

    @app.after_request
    def _inject_overlay_toggle(response):
        """Inject a floating overlay toggle button into HTML responses."""
        if (response.content_type
                and "text/html" in response.content_type
                and response.status_code == 200
                and "/overlay" not in (getattr(request, 'path', '') or '')):
            try:
                data = response.get_data(as_text=True)
                if "</body>" in data and "overlay-toggle-btn" not in data:
                    snippet = (
                        '<div id="overlay-toggle-btn" onclick="document.getElementById(\'overlay-frame-wrap\').style.display='
                        "document.getElementById('overlay-frame-wrap').style.display==='none'?'block':'none'"
                        '" style="position:fixed;bottom:12px;right:12px;z-index:99999;width:40px;height:40px;'
                        'border-radius:50%;background:#1a1a2e;border:1px solid #4aa0ff;color:#4aa0ff;'
                        'font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;'
                        'box-shadow:0 2px 8px rgba(0,0,0,0.4);">⚙</div>'
                        '<div id="overlay-frame-wrap" style="display:none;position:fixed;top:0;right:0;'
                        'width:420px;height:100vh;z-index:99998;box-shadow:-4px 0 20px rgba(0,0,0,0.5);">'
                        '<iframe src="/overlay/" style="width:100%;height:100%;border:none;"></iframe></div>'
                    )
                    data = data.replace("</body>", snippet + "</body>")
                    response.set_data(data)
            except Exception:
                pass
        return response

    logger.info("Control overlay mounted at /overlay/")


# ── Overlay HTML (inline template) ──────────────────────────────────────

_OVERLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CosySim Control Overlay</title>
<style>
:root {
  --bg: rgba(15, 15, 25, 0.92);
  --bg-panel: rgba(20, 20, 35, 0.95);
  --accent: #6c9fff;
  --accent2: #ff6c9f;
  --text: #e0e0e8;
  --text-dim: #888;
  --border: rgba(100, 100, 140, 0.3);
  --success: #4caf50;
  --warning: #ff9800;
  --error: #f44336;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}

#overlay {
  position: fixed;
  top: 10px; right: 10px;
  width: 420px;
  max-height: 80vh;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  backdrop-filter: blur(20px);
  z-index: 99999;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  resize: both;
  min-width: 320px;
  min-height: 200px;
}

#overlay.minimized {
  width: 48px !important;
  height: 48px !important;
  min-width: 48px;
  min-height: 48px;
  border-radius: 50%;
  cursor: pointer;
  overflow: hidden;
}

#overlay.minimized > *:not(#header) { display: none; }
#overlay.minimized #header { border: none; padding: 0; justify-content: center; }
#overlay.minimized #header span, #overlay.minimized #header .controls { display: none; }

/* ── Header ── */
#header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  cursor: move;
  user-select: none;
  background: rgba(30,30,50,0.5);
}

#header span {
  font-weight: 600;
  font-size: 14px;
  color: var(--accent);
}

#header .controls button {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 4px;
}
#header .controls button:hover { color: var(--text); background: rgba(255,255,255,0.1); }

/* ── Tabs ── */
#tabs {
  display: flex;
  gap: 2px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  background: rgba(20,20,35,0.5);
}

.tab {
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
  transition: all 0.15s;
}
.tab:hover { color: var(--text); background: rgba(255,255,255,0.05); }
.tab.active { color: var(--accent); background: rgba(108,159,255,0.15); font-weight: 600; }

/* ── Content ── */
#content {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
}

.panel { display: none; }
.panel.active { display: block; }

/* ── Common elements ── */
.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.stat-label { color: var(--text-dim); }
.stat-value { font-weight: 500; }
.stat-value.ok { color: var(--success); }
.stat-value.warn { color: var(--warning); }
.stat-value.err { color: var(--error); }

.card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
}

.card h3 {
  font-size: 12px;
  color: var(--accent);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.btn {
  background: rgba(108,159,255,0.2);
  color: var(--accent);
  border: 1px solid rgba(108,159,255,0.3);
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.btn:hover { background: rgba(108,159,255,0.35); }
.btn.danger { background: rgba(244,67,54,0.2); color: var(--error); border-color: rgba(244,67,54,0.3); }

input, select, textarea {
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  width: 100%;
}

.event-item {
  padding: 4px 0;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  font-size: 11px;
}
.event-type { color: var(--accent2); font-weight: 500; }
.event-time { color: var(--text-dim); font-size: 10px; }

/* ── Footer controls ── */
#footer {
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-dim);
}

#footer label { white-space: nowrap; }
#footer input[type="range"] { width: 80px; }
</style>
</head>
<body>

<div id="overlay">
  <div id="header">
    <span>🎮 CosySim Control</span>
    <div class="controls">
      <button onclick="refresh()" title="Refresh">🔄</button>
      <button onclick="toggleMinimize()" title="Minimize">➖</button>
    </div>
  </div>

  <div id="tabs">
    <div class="tab active" data-panel="status">Status</div>
    <div class="tab" data-panel="agents">Agents</div>
    <div class="tab" data-panel="models">Models</div>
    <div class="tab" data-panel="config">Config</div>
    <div class="tab" data-panel="skills">Skills</div>
    <div class="tab" data-panel="events">Events</div>
    <div class="tab" data-panel="streaming">Streaming</div>
    <div class="tab" data-panel="act">Act</div>
    <div class="tab" data-panel="inference">Inference</div>
  </div>

  <div id="content">
    <!-- Status Panel -->
    <div class="panel active" id="p-status">
      <div class="card">
        <h3>System</h3>
        <div id="status-content">Loading...</div>
      </div>
    </div>

    <!-- Agents Panel -->
    <div class="panel" id="p-agents">
      <div id="agents-content">Loading...</div>
    </div>

    <!-- Models Panel -->
    <div class="panel" id="p-models">
      <div class="card">
        <h3>Loaded Models</h3>
        <div id="models-content">Loading...</div>
      </div>
      <div class="card">
        <h3>Load Model</h3>
        <input id="model-id" placeholder="Model identifier..." style="margin-bottom:6px">
        <button class="btn" onclick="loadModel()">Load</button>
      </div>
    </div>

    <!-- Config Panel -->
    <div class="panel" id="p-config">
      <div id="config-content">Loading...</div>
    </div>

    <!-- Skills Panel -->
    <div class="panel" id="p-skills">
      <div id="skills-content">Loading...</div>
    </div>

    <!-- Events Panel -->
    <div class="panel" id="p-events">
      <div id="events-content" style="max-height: 400px; overflow-y: auto;">Connecting...</div>
    </div>

    <!-- Streaming Panel -->
    <div class="panel" id="p-streaming">
      <div class="card">
        <h3>v2.7 Streaming</h3>
        <div id="streaming-content">Loading...</div>
      </div>
      <div class="card">
        <h3>Active Conversations</h3>
        <div id="conversations-content">Loading...</div>
      </div>
    </div>

    <!-- Act Panel -->
    <div class="panel" id="p-act">
      <div class="card">
        <h3>Act as Agent</h3>
        <select id="act-agent" style="margin-bottom:6px">
          <option value="">Select agent...</option>
        </select>
        <textarea id="act-message" placeholder="Message..." rows="3" style="margin-bottom:6px"></textarea>
        <button class="btn" onclick="actAsAgent()">Send</button>
      </div>
    </div>

    <!-- Inference Panel -->
    <div class="panel" id="p-inference">
      <div class="card">
        <h3>Inference Defaults</h3>
        <div id="inference-content">Loading...</div>
      </div>
    </div>
  </div>

  <div id="footer">
    <label>Opacity:</label>
    <input type="range" min="30" max="100" value="92" oninput="setOpacity(this.value)">
    <span id="auto-refresh-label">Auto: 5s</span>
  </div>
</div>

<script>
const BASE = '/overlay/api';
let autoRefreshInterval = null;

// ── Tab switching ──
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('p-' + tab.dataset.panel).classList.add('active');
    refresh();
  });
});

// ── Drag ──
let isDragging = false, dragX, dragY;
const header = document.getElementById('header');
const overlay = document.getElementById('overlay');

header.addEventListener('mousedown', e => {
  isDragging = true;
  dragX = e.clientX - overlay.offsetLeft;
  dragY = e.clientY - overlay.offsetTop;
});
document.addEventListener('mousemove', e => {
  if (!isDragging) return;
  overlay.style.left = (e.clientX - dragX) + 'px';
  overlay.style.top = (e.clientY - dragY) + 'px';
  overlay.style.right = 'auto';
});
document.addEventListener('mouseup', () => isDragging = false);

// ── Minimize ──
function toggleMinimize() {
  overlay.classList.toggle('minimized');
}
overlay.addEventListener('click', e => {
  if (overlay.classList.contains('minimized')) overlay.classList.remove('minimized');
});

// ── Opacity ──
function setOpacity(val) {
  const alpha = val / 100;
  overlay.style.background = `rgba(15, 15, 25, ${alpha})`;
}

// ── API helpers ──
async function api(path) {
  try {
    const r = await fetch(BASE + path);
    return await r.json();
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function apiPost(path, body) {
  try {
    const r = await fetch(BASE + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    return await r.json();
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ── Refresh ──
async function refresh() {
  const active = document.querySelector('.tab.active')?.dataset.panel;
  if (active === 'status') await refreshStatus();
  else if (active === 'agents') await refreshAgents();
  else if (active === 'models') await refreshModels();
  else if (active === 'config') await refreshConfig();
  else if (active === 'skills') await refreshSkills();
  else if (active === 'streaming') await refreshStreaming();
  else if (active === 'inference') await refreshInference();
}

async function refreshStatus() {
  const d = await api('/status');
  if (!d.ok) { document.getElementById('status-content').innerHTML = `<span class="stat-value err">${d.error}</span>`; return; }
  let html = '';
  // LMStudio
  const lm = d.lmstudio || {};
  html += `<div class="stat-row"><span class="stat-label">LMStudio</span><span class="stat-value ${lm.available ? 'ok' : 'err'}">${lm.available ? 'Connected' : 'Offline'}</span></div>`;
  html += `<div class="stat-row"><span class="stat-label">Native API</span><span class="stat-value ${lm.native_api ? 'ok' : 'warn'}">${lm.native_api ? 'Available' : 'Fallback'}</span></div>`;
  if (lm.models) html += `<div class="stat-row"><span class="stat-label">Models</span><span class="stat-value">${lm.models.length} loaded</span></div>`;
  // Resources
  const rm = d.resources || {};
  html += `<div class="stat-row"><span class="stat-label">Strategy</span><span class="stat-value">${rm.strategy || 'N/A'}</span></div>`;
  html += `<div class="stat-row"><span class="stat-label">VRAM</span><span class="stat-value">${rm.vram_used_mb || 0}/${rm.vram_cap_mb || 0} MB</span></div>`;
  // Skills
  html += `<div class="stat-row"><span class="stat-label">Skills</span><span class="stat-value">${d.skills_count} registered</span></div>`;
  document.getElementById('status-content').innerHTML = html;
}

async function refreshAgents() {
  const d = await api('/agents');
  if (!d.ok) { document.getElementById('agents-content').innerHTML = 'Error: ' + d.error; return; }
  let html = '';
  const select = document.getElementById('act-agent');
  select.innerHTML = '<option value="">Select agent...</option>';
  (d.agents || []).forEach(a => {
    html += `<div class="card"><h3>${a.name || a.id}</h3>`;
    html += `<div class="stat-row"><span class="stat-label">Scene</span><span class="stat-value">${a.scene || 'none'}</span></div>`;
    const state = a.state || {};
    Object.entries(state).forEach(([k,v]) => {
      html += `<div class="stat-row"><span class="stat-label">${k}</span><span class="stat-value">${typeof v === 'string' ? v.substring(0,60) : JSON.stringify(v)}</span></div>`;
    });
    html += '</div>';
    select.innerHTML += `<option value="${a.id}">${a.name || a.id}</option>`;
  });
  document.getElementById('agents-content').innerHTML = html || '<div class="stat-value">No agents registered</div>';
}

async function refreshModels() {
  const d = await api('/models');
  if (!d.ok) { document.getElementById('models-content').innerHTML = 'Error'; return; }
  let html = '';
  (d.loaded || []).forEach(m => {
    html += `<div class="stat-row"><span class="stat-label">${m.id}</span><button class="btn danger" style="font-size:10px" onclick="unloadModel('${m.id}')">Unload</button></div>`;
  });
  document.getElementById('models-content').innerHTML = html || 'No models loaded';
}

async function refreshConfig() {
  const d = await api('/config');
  if (!d.ok) { document.getElementById('config-content').innerHTML = 'Error'; return; }
  let html = '';
  Object.entries(d.config || {}).forEach(([section, values]) => {
    html += `<div class="card"><h3>${section}</h3>`;
    if (typeof values === 'object' && values !== null) {
      Object.entries(values).forEach(([k,v]) => {
        const display = typeof v === 'object' ? JSON.stringify(v) : String(v);
        html += `<div class="stat-row"><span class="stat-label">${k}</span><span class="stat-value">${display.substring(0,50)}</span></div>`;
      });
    }
    html += '</div>';
  });
  document.getElementById('config-content').innerHTML = html;
}

async function refreshSkills() {
  const d = await api('/skills');
  if (!d.ok) { document.getElementById('skills-content').innerHTML = 'Error'; return; }
  let html = '';
  const byPack = {};
  (d.skills || []).forEach(s => {
    if (!byPack[s.pack]) byPack[s.pack] = [];
    byPack[s.pack].push(s);
  });
  Object.entries(byPack).forEach(([pack, skills]) => {
    html += `<div class="card"><h3>📦 ${pack} (${skills.length})</h3>`;
    skills.forEach(s => {
      html += `<div class="stat-row"><span class="stat-label">${s.name}</span><span class="stat-value">${(s.description || '').substring(0,40)}</span></div>`;
    });
    html += '</div>';
  });
  document.getElementById('skills-content').innerHTML = html;
}

async function refreshInference() {
  const d = await api('/inference');
  if (!d.ok) { document.getElementById('inference-content').innerHTML = 'Error'; return; }
  let html = '';
  Object.entries(d.defaults || {}).forEach(([k,v]) => {
    html += `<div class="stat-row"><span class="stat-label">${k}</span><span class="stat-value">${v}</span></div>`;
  });
  html += '<div style="margin-top:8px"><button class="btn" onclick="editInference()">Edit</button></div>';
  document.getElementById('inference-content').innerHTML = html;
}

// ── Streaming ──
async function refreshStreaming() {
  const d = await api('/streaming');
  if (!d.ok) { document.getElementById('streaming-content').innerHTML = 'Error'; return; }
  let html = '';
  const mgr = d.manager || {};
  html += `<div class="stat-row"><span class="stat-label">Total Calls</span><span class="stat-value">${mgr.total_calls || 0}</span></div>`;
  html += `<div class="stat-row"><span class="stat-label">Active Agents</span><span class="stat-value">${mgr.active_agents || 0}</span></div>`;
  const sp = d.stream_processor || {};
  html += `<div class="stat-row"><span class="stat-label">StreamProcessor</span><span class="stat-value ${sp.available ? 'ok' : 'warn'}">${sp.available ? 'Available' : 'N/A'}</span></div>`;
  if (sp.tag_patterns) html += `<div class="stat-row"><span class="stat-label">Tag Patterns</span><span class="stat-value">${sp.tag_patterns.join(', ')}</span></div>`;
  document.getElementById('streaming-content').innerHTML = html;

  // Conversations
  const convos = d.conversations || {};
  let chtml = `<div class="stat-row"><span class="stat-label">Total</span><span class="stat-value">${convos.count || 0}</span></div>`;
  (convos.conversations || []).forEach(c => {
    chtml += `<div class="stat-row"><span class="stat-label">${c.id}</span><span class="stat-value">${c.turns} turns, ${c.branches} branches</span></div>`;
  });
  document.getElementById('conversations-content').innerHTML = chtml;
}

// ── Actions ──
async function loadModel() {
  const id = document.getElementById('model-id').value;
  if (!id) return;
  const r = await apiPost('/models/load', {model_id: id});
  alert(r.ok ? 'Model loaded!' : 'Failed: ' + r.error);
  refresh();
}

async function unloadModel(id) {
  const r = await apiPost('/models/unload', {model_id: id});
  refresh();
}

async function actAsAgent() {
  const agent = document.getElementById('act-agent').value;
  const msg = document.getElementById('act-message').value;
  if (!msg) return;
  await apiPost('/act', {action: 'speak', agent_id: agent, message: msg});
  document.getElementById('act-message').value = '';
}

function editInference() {
  const temp = prompt('Temperature (0.0-2.0):', '0.7');
  if (temp === null) return;
  const maxTok = prompt('Max output tokens:', '2000');
  if (maxTok === null) return;
  apiPost('/inference', {
    temperature: parseFloat(temp),
    max_output_tokens: parseInt(maxTok),
  }).then(refresh);
}

// ── Events SSE ──
function connectEvents() {
  const evtSource = new EventSource(BASE + '/events');
  const container = document.getElementById('events-content');
  container.innerHTML = '';
  evtSource.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data);
      const div = document.createElement('div');
      div.className = 'event-item';
      div.innerHTML = `<span class="event-type">${d.activity_type || d.type || '?'}</span> <span>${(d.description || '').substring(0,60)}</span> <span class="event-time">${d.agent_id || ''}</span>`;
      container.prepend(div);
      // Keep max 100 events in DOM
      while (container.children.length > 100) container.removeChild(container.lastChild);
    } catch(err) {}
  };
  evtSource.onerror = () => {
    container.innerHTML = '<div class="stat-value warn">Event stream disconnected. Retrying...</div>';
  };
}

// ── Init ──
refreshStatus();
connectEvents();
autoRefreshInterval = setInterval(refresh, 5000);
</script>
</body>
</html>"""
