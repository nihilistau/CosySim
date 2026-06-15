"""Executive Suite — neon corporate OS desktop scene.
=====================================================

A full-screen neon "operating system" desktop for the executive pillar — a
windowed NeonOS shell (animated skyline + office bezel, left app dock,
draggable windows, bottom taskbar) that later hosts mail, files, notes,
music, code, terminal and a live in-world AI assistant.

This module ships the OS SHELL (ES-T2): the backend that serves the desktop
template and a minimal ``/api/state`` endpoint feeding the system tray
(game clock from :class:`WorldState`, plus config-driven heat / network /
battery readouts). Individual apps register themselves client-side via the
``window.ES`` app-registry API and add their own backend routes in later
v1.62 tasks.

The scene mirrors the canonical FlaskScene template (see
``content/scenes/lab_break/lab_break_scene.py``): FlaskScene base class with
Socket.IO, a one-route full-screen desktop UI, a ``/api/state`` endpoint,
and minimal lifecycle hooks.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Functional OS app backends (ES-T3): /api/files/*,
                            /api/mail/*, /api/notes, /api/console. Read real
                            data (inventory/catalog, phone comms, notes JSON);
                            sandboxed file roots + whitelisted console commands.
    v1.62.0 [2026-06-15] — OS desktop shell (ES-T2): window manager + dock +
                            taskbar + skyline; /api/state returns live clock +
                            tray readouts (replaces ES-T1 placeholder)
    v1.62.0 [2026-06-15] — Initial scaffold (ES-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start

CONNECTS: FlaskScene, SocketIO, WorldState, get_config
CALLED BY: launcher.py, TUI, hub
EMITS: state_update Socket.IO event
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

SCENE_ID = "executive_suite"
# v1.62.0 [2026-06-15] — Structured logging context (SCENE_ID prefix + operation tags)

# v1.62.0 [2026-06-15] — App backend constants (ES-T3 functional OS apps)
# Whitelisted, read-only roots the Files app may browse (no arbitrary FS).
_SAFE_FILE_ROOTS = {"inventory", "catalog", "data"}
# Whitelist of console commands the sandboxed Terminal app accepts. NO shell
# exec, NO arbitrary code — each maps to a small read-only handler.
_CONSOLE_COMMANDS = ("help", "status", "whoami", "scenes", "world", "inbox", "clear")


# ──── Scene Implementation ────────────────────────────────────

# v1.62.0 [2026-06-15] — OS desktop shell on FlaskScene base
class ExecutiveSuiteScene(FlaskScene):
    """Executive Suite: a neon corporate OS desktop (the NeonOS shell).

    Serves a full-screen windowed desktop — animated skyline, office bezel,
    left app dock, draggable windows and a bottom taskbar. The shell defines
    the ``window.ES`` app-registry API; mail / files / notes / music / code /
    terminal / assistant apps register against it in later v1.62 tasks.

    CONNECTS: FlaskScene, SocketIO, WorldState, get_config
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "executive_suite",
        "display_name": "EXECUTIVE SUITE",
        "port": 5596,
        "type": "game",
        "accent_color": "#06b6d4",
        "description": "A full neon OS desktop — mail, files, your live AI assistant.",
        "version": "1.62.0",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "executive-suite-scene"

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._setup_socketio_handlers()

    # ── Routes ─────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all Flask API routes."""
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "executive_suite.html",
                scene_data=self._get_scene_state(),
            )

        @app.route("/api/state")
        def get_state():
            return jsonify(self._get_scene_state())

        # ── App backends (ES-T3) — each app owns its /api/<app>/* namespace ──
        # v1.62.0 [2026-06-15] — Functional OS app routes; read real game data,
        # log in Oracle format, and return JSON errors (never 500 silently).

        # ── files ──────────────────────────────────────────────────────
        @app.route("/api/files/tree")
        def files_tree():
            try:
                return jsonify(self._files_tree())
            except Exception as exc:
                logger.error("[%s] files tree failed (operation=files): %s", SCENE_ID, exc)
                return jsonify({"error": "tree unavailable", "sections": []}), 200

        @app.route("/api/files/read")
        def files_read():
            path = request.args.get("path", "")
            try:
                return jsonify(self._files_read(path))
            except Exception as exc:
                logger.error("[%s] files read failed (operation=files, path=%s): %s",
                             SCENE_ID, path, exc)
                return jsonify({"error": "read unavailable"}), 200

        # ── mail (phone comms; repoints to GlobalCommsLog in sub-project 2) ──
        @app.route("/api/mail/threads")
        def mail_threads():
            try:
                return jsonify(self._mail_threads())
            except Exception as exc:
                logger.error("[%s] mail threads failed (operation=mail): %s", SCENE_ID, exc)
                return jsonify({"threads": [], "unread": 0, "empty": True}), 200

        @app.route("/api/mail/thread/<thread_id>")
        def mail_thread(thread_id: str):
            try:
                return jsonify(self._mail_thread(thread_id))
            except Exception as exc:
                logger.error("[%s] mail thread failed (operation=mail, thread=%s): %s",
                             SCENE_ID, thread_id, exc)
                return jsonify({"error": "thread unavailable", "messages": []}), 200

        @app.route("/api/mail/send", methods=["POST"])
        def mail_send():
            body = request.get_json(silent=True) or {}
            try:
                return jsonify(self._mail_send(body))
            except Exception as exc:
                logger.error("[%s] mail send failed (operation=mail): %s", SCENE_ID, exc)
                return jsonify({"success": False, "error": "send failed"}), 200

        # ── notes ──────────────────────────────────────────────────────
        @app.route("/api/notes", methods=["GET"])
        def notes_get():
            try:
                return jsonify(self._notes_get())
            except Exception as exc:
                logger.error("[%s] notes get failed (operation=notes): %s", SCENE_ID, exc)
                return jsonify({"notes": [], "error": "notes unavailable"}), 200

        @app.route("/api/notes", methods=["POST"])
        def notes_post():
            body = request.get_json(silent=True) or {}
            try:
                return jsonify(self._notes_save(body))
            except Exception as exc:
                logger.error("[%s] notes save failed (operation=notes): %s", SCENE_ID, exc)
                return jsonify({"success": False, "error": "save failed"}), 200

        # ── terminal (sandboxed console) ───────────────────────────────
        @app.route("/api/console", methods=["POST"])
        def console():
            body = request.get_json(silent=True) or {}
            cmd = str(body.get("command", "")).strip()
            try:
                return jsonify(self._console(cmd))
            except Exception as exc:
                logger.error("[%s] console failed (operation=terminal, cmd=%s): %s",
                             SCENE_ID, cmd, exc)
                return jsonify({"ok": False, "lines": ["error: command failed"]}), 200

    # ── App backend helpers (ES-T3) ─────────────────────────────────────
    # v1.62.0 [2026-06-15]

    def _files_tree(self) -> Dict[str, Any]:
        """Build the Files browser tree + grid from REAL game data.

        Sources: player inventory + the item catalog (read-only), plus a
        sandboxed view of safe JSON artifacts under ``data/``. All grid entries
        are read-only; paths are confined to the whitelisted roots.
        """
        from engine.world.inventory import get_inventory, ITEM_CATALOG

        sections: List[Dict[str, Any]] = []

        # PINNED — live inventory
        inv = get_inventory()
        snap = inv.to_dict()
        inv_files = []
        for it in snap.get("items", []):
            inv_files.append({
                "name": it.get("name", it.get("item_id")),
                "path": "inventory/" + it.get("item_id", ""),
                "kind": "doc",
                "size": "x%d" % it.get("quantity", 1),
                "meta": it.get("rarity", ""),
            })
        sections.append({
            "label": "PINNED", "id": "inventory", "icon": "📦",
            "title": "inventory · %d items" % len(inv_files),
            "files": inv_files,
        })

        # DEVICES — full item catalog (read-only reference)
        cat_files = []
        for item_id, meta in ITEM_CATALOG.items():
            cat_files.append({
                "name": meta.get("name", item_id),
                "path": "catalog/" + item_id,
                "kind": "code" if meta.get("category") in ("software", "cyberdeck") else "doc",
                "size": "₵%s" % meta.get("price", "?"),
                "meta": meta.get("category", ""),
            })
        sections.append({
            "label": "DEVICES", "id": "catalog", "icon": "🗂",
            "title": "item catalog · %d entries" % len(cat_files),
            "files": cat_files,
        })

        # DATA — safe JSON artifacts under data/ (sandboxed, read-only)
        data_files = []
        try:
            from engine.paths import DATA_DIR
            for safe_name in ("inventory.json", "executive_suite_notes.json"):
                fp = DATA_DIR / safe_name
                if fp.exists():
                    data_files.append({
                        "name": safe_name,
                        "path": "data/" + safe_name,
                        "kind": "code",
                        "size": "%dB" % fp.stat().st_size,
                        "meta": "json",
                    })
        except Exception as exc:
            logger.debug("[%s] data scan skipped (operation=files): %s", SCENE_ID, exc)
        sections.append({
            "label": "SYSTEM", "id": "data", "icon": "💾",
            "title": "data · %d files" % len(data_files),
            "files": data_files,
        })

        logger.info("[%s] files tree served (operation=files, sections=%d)",
                    SCENE_ID, len(sections))
        return {"sections": sections}

    def _files_read(self, path: str) -> Dict[str, Any]:
        """Return the contents of a single sandboxed file entry.

        Only paths under the whitelisted roots are honoured; anything else is
        rejected (no arbitrary filesystem access).
        """
        root = path.split("/", 1)[0] if "/" in path else path
        if root not in _SAFE_FILE_ROOTS:
            logger.warning("[%s] files read rejected (operation=files, path=%s)",
                           SCENE_ID, path)
            return {"error": "path not allowed"}

        from engine.world.inventory import get_inventory, ITEM_CATALOG
        rest = path.split("/", 1)[1] if "/" in path else ""

        if root == "catalog":
            meta = ITEM_CATALOG.get(rest)
            if not meta:
                return {"error": "not found"}
            return {"name": meta.get("name", rest), "kind": "doc",
                    "body": json.dumps(meta, indent=2)}

        if root == "inventory":
            inv = get_inventory()
            item = inv.get_item(rest)
            if not item:
                return {"error": "not found"}
            return {"name": item.to_dict().get("name", rest), "kind": "doc",
                    "body": json.dumps(item.to_dict(), indent=2)}

        if root == "data":
            from engine.paths import DATA_DIR
            name = Path(rest).name  # strip any traversal
            if name not in ("inventory.json", "executive_suite_notes.json"):
                return {"error": "path not allowed"}
            fp = DATA_DIR / name
            if not fp.exists():
                return {"error": "not found"}
            text = fp.read_text(encoding="utf-8")[:20000]
            return {"name": name, "kind": "code", "body": text}

        return {"error": "not found"}

    def _phone_db(self):
        """Return a PhoneDB instance (lazy import — phone is an optional peer)."""
        from content.scenes.phone.phone_db import PhoneDB
        return PhoneDB()

    def _char_name(self, char_id: str, cache: Dict[str, str]) -> str:
        """Resolve a character id to a display name (cached per request)."""
        if char_id in cache:
            return cache[char_id]
        name = char_id
        try:
            from content.simulation.database.db import Database
            row = Database().get_character(char_id)
            if row and row.get("name"):
                name = row["name"]
        except Exception:
            pass
        cache[char_id] = name
        return name

    def _mail_threads(self) -> Dict[str, Any]:
        """Inbox list from the EXISTING phone comms (PhoneDB threads).

        NOTE: this reads phone_threads / phone_messages. In sub-project 2 this
        repoints to GlobalCommsLog — keep the response shape stable.
        """
        db = self._phone_db()
        threads = db.list_threads()
        cache: Dict[str, str] = {}
        out = []
        for t in threads:
            members = t.get("members") or []
            if t.get("name"):
                frm = t["name"]
            elif members:
                frm = self._char_name(members[0], cache)
            else:
                frm = "unknown"
            out.append({
                "id": t["id"],
                "from": frm,
                "preview": (t.get("last_message") or "")[:120],
                "unread": int(t.get("unread") or 0),
                "time": t.get("updated_at", ""),
            })
        total_unread = sum(x["unread"] for x in out)
        logger.info("[%s] mail threads served (operation=mail, threads=%d, unread=%d)",
                    SCENE_ID, len(out), total_unread)
        return {"threads": out, "unread": total_unread, "empty": not out}

    def _mail_thread(self, thread_id: str) -> Dict[str, Any]:
        """Full message list for one thread (the preview pane)."""
        db = self._phone_db()
        meta = db.get_thread(thread_id)
        if not meta:
            return {"error": "not found", "messages": []}
        cache: Dict[str, str] = {}
        msgs = []
        for m in db.get_messages(thread_id, limit=100):
            sid = m.get("sender_id", "")
            msgs.append({
                "id": m.get("id"),
                "sender_id": sid,
                "from": "You" if sid == "user" else self._char_name(sid, cache),
                "mine": sid == "user",
                "content": m.get("content", ""),
                "time": m.get("created_at", ""),
            })
        try:
            db.mark_read(thread_id)
        except Exception:
            pass
        members = [c for c in (meta.get("members") or []) if c != "user"]
        title = meta.get("name") or (self._char_name(members[0], cache) if members else "thread")
        logger.info("[%s] mail thread served (operation=mail, thread=%s, msgs=%d)",
                    SCENE_ID, thread_id, len(msgs))
        return {"id": thread_id, "title": title, "messages": msgs}

    def _mail_send(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Persist an outbound message into the phone comms thread."""
        thread_id = str(body.get("thread_id", "")).strip()
        content = str(body.get("content", "")).strip()
        if not thread_id or not content:
            return {"success": False, "error": "thread_id and content required"}
        db = self._phone_db()
        if not db.get_thread(thread_id):
            return {"success": False, "error": "unknown thread"}
        msg = db.save_message(thread_id, "user", content)
        logger.info("[%s] mail sent (operation=mail, thread=%s, msg=%s)",
                    SCENE_ID, thread_id, msg.get("id"))
        return {"success": True, "message": {
            "id": msg["id"], "from": "You", "mine": True,
            "content": content, "time": msg["created_at"],
        }}

    def _notes_path(self) -> Path:
        from engine.paths import DATA_DIR
        return DATA_DIR / "executive_suite_notes.json"

    def _notes_get(self) -> Dict[str, Any]:
        """Load persisted notes from data/executive_suite_notes.json."""
        fp = self._notes_path()
        if not fp.exists():
            return {"notes": []}
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            notes = data.get("notes", []) if isinstance(data, dict) else []
        except Exception:
            notes = []
        logger.info("[%s] notes loaded (operation=notes, count=%d)", SCENE_ID, len(notes))
        return {"notes": notes}

    def _notes_save(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Persist the full notes list (client sends the whole document set)."""
        notes = body.get("notes")
        if not isinstance(notes, list):
            return {"success": False, "error": "notes must be a list"}
        fp = self._notes_path()
        fp.parent.mkdir(parents=True, exist_ok=True)
        payload = {"notes": notes, "_saved_at": datetime.now(timezone.utc).isoformat()}
        fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("[%s] notes saved (operation=notes, count=%d)", SCENE_ID, len(notes))
        return {"success": True, "count": len(notes), "saved_at": payload["_saved_at"]}

    def _console(self, cmd: str) -> Dict[str, Any]:
        """Run a whitelisted, read-only console command. No shell exec.

        Unknown commands return a 'command not found' line. Each handler reads
        live game/scene data only.
        """
        word = cmd.split()[0].lower() if cmd else ""
        if not word:
            return {"ok": True, "lines": []}
        if word not in _CONSOLE_COMMANDS:
            logger.info("[%s] console unknown (operation=terminal, cmd=%s)", SCENE_ID, word)
            return {"ok": False, "lines": ["neonsh: command not found: %s" % word,
                                           "type 'help' for available commands"]}

        lines: List[str] = []
        if word == "help":
            lines = ["available commands:",
                     "  status   system + tray readouts",
                     "  whoami   current operator",
                     "  scenes   registered scene roster",
                     "  world    in-game clock / time of day",
                     "  inbox    unread comms summary",
                     "  clear    clear the screen"]
        elif word == "clear":
            return {"ok": True, "clear": True, "lines": []}
        elif word == "whoami":
            lines = ["root@neoncity", "role: operator · clearance F-87"]
        elif word == "status":
            st = self._get_scene_state()
            tray = st.get("tray", {})
            lines = ["NEONOS %s · %s" % (st.get("version", "?"), st.get("status", "?")),
                     "heat     %s%%" % tray.get("heat", "?"),
                     "battery  %s%%" % tray.get("battery", "?"),
                     "network  %s" % tray.get("network", "?"),
                     "volume   %s%%" % tray.get("volume", "?")]
        elif word == "world":
            clk = self._read_clock()
            lines = ["game time: %s" % (clk.get("display") or "—"),
                     "day %s (%s) · hour %s · %s" % (
                         clk.get("game_day"), clk.get("game_day_name"),
                         clk.get("game_hour"), clk.get("time_of_day"))]
        elif word == "scenes":
            try:
                from engine.paths import SCENES_DIR  # noqa: PLC0415
                ids = sorted(p.name for p in SCENES_DIR.iterdir()
                             if p.is_dir() and not p.name.startswith("_"))
                lines = ["registered scenes (%d):" % len(ids)] + ["  " + s for s in ids]
            except Exception:
                lines = ["scene roster unavailable"]
        elif word == "inbox":
            try:
                db = self._phone_db()
                lines = ["unread comms: %d" % db.total_unread(),
                         "threads: %d" % len(db.list_threads())]
            except Exception:
                lines = ["comms offline"]
        logger.info("[%s] console ran (operation=terminal, cmd=%s)", SCENE_ID, word)
        return {"ok": True, "lines": lines}

    def _setup_socketio_handlers(self) -> None:
        """Register Socket.IO event handlers."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("state_update", self._get_scene_state())

        # v1.62.0 [2026-06-15] — Clients can poll fresh state over the socket
        @sio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_scene_state())

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the desktop shell state for the template + tray.

        Pulls the live game clock from :class:`WorldState` when available and
        the system-tray readouts (heat / network / battery) from config so
        nothing is hardcoded. All lookups degrade gracefully — the shell must
        boot even when the world/config subsystems are offline.
        """
        state: Dict[str, Any] = {
            "scene": SCENE_ID,
            "display_name": self.SCENE_METADATA["display_name"],
            "status": "online",
            "accent_color": self.SCENE_METADATA["accent_color"],
            "version": self.SCENE_METADATA["version"],
        }
        state["clock"] = self._read_clock()
        state["tray"] = self._read_tray()
        return state

    def _read_clock(self) -> Dict[str, Any]:
        """Return the current in-game clock (falls back to a static label)."""
        try:
            from engine.world.world_state import get_world_state  # noqa: PLC0415
            wt = get_world_state().get_time()
            return {
                "game_hour": wt.game_hour,
                "game_day": wt.game_day,
                "game_day_name": wt.game_day_name,
                "time_of_day": wt.time_of_day,
                "display": wt.to_display(),
            }
        except Exception as exc:  # WorldState optional — never block boot
            logger.debug("[%s] clock unavailable (operation=state): %s", SCENE_ID, exc)
            return {
                "game_hour": 0,
                "game_day": 0,
                "game_day_name": "Mon",
                "time_of_day": "night",
                "display": "",
            }

    def _read_tray(self) -> Dict[str, Any]:
        """Return system-tray readouts from config (no hardcoded values)."""
        try:
            from engine.config import get_config  # noqa: PLC0415
            cfg = get_config()
        except Exception:  # config optional — fall back to defaults below
            cfg = None

        def _cfg(key: str, default: Any) -> Any:
            if cfg is None:
                return default
            try:
                return cfg.get(key, default)
            except Exception:
                return default

        return {
            "heat": _cfg("executive_suite.tray.heat", 14),
            "battery": _cfg("executive_suite.tray.battery", 87),
            "network": _cfg("executive_suite.tray.network", "nexus"),
            "volume": _cfg("executive_suite.tray.volume", 60),
        }

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.62.0 [2026-06-15] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Pre-serve setup (shell has no background services of its own)."""
        logger.info("[%s] OS shell online (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Cleanup on shutdown."""
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
