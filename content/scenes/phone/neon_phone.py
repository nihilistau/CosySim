"""
SIGNAL — Hacker Mystery Communication Scene (v0.68 Dark Renaissance)
======================================================================
NeonPhone: cyberpunk messenger where 0xGH0ST haunts the player's contacts
and a surveillance network called SPECTER slowly comes into focus.

Features
--------
* Six contacts with distinct AI personas (LOLA, VIKTOR, ARIA, MIRA, FRANKIE, 0xGH0ST)
* LMStudio-backed AI replies per contact via ``get_lms_client()``
* 0xGH0ST mystery arc with 5 story stages tracked in InvestigationBoard
* EventBus integration: PHONE_HACKER_MESSAGE, PHONE_JOB_ACCEPTED
* Investigation board slide-in for clue tracking
* Real-time Socket.IO message delivery and typing indicators

Version: v1.51.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-22] — Migrated to FlaskScene base class
    v0.68   [2026-03-21] — Initial SIGNAL scene with 0xGH0ST arc
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import jsonify, request, render_template
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

_SCENE_ROOT = Path(__file__).parent


# ── Contact registry ──────────────────────────────────────────────────────────

_CONTACTS: Dict[str, Dict[str, Any]] = {
    "lola": {
        "id": "lola",
        "name": "LOLA",
        "status": "online",
        "color": "#ec4899",
        "dot_class": "pink",
        "avatar_emoji": "💋",
        "system_prompt": (
            "You are LOLA, a witty and flirtatious contact living in a cyberpunk city. "
            "You work nights at the Neon Lotus club. Keep replies short (1-3 sentences), "
            "casual, and slightly flirty. You've heard rumours about someone called 0xGH0ST "
            "but mostly brush it off as hacker folklore."
        ),
    },
    "viktor": {
        "id": "viktor",
        "name": "VIKTOR",
        "status": "offline",
        "color": "#6b7280",
        "dot_class": "gray",
        "avatar_emoji": "🔧",
        "system_prompt": (
            "You are VIKTOR, a gruff but reliable street fixer. You deal in information "
            "and grey-market hardware. Keep replies very terse (1-2 sentences), suspicious, "
            "and guarded. You've heard whispers about the hacker 0xGH0ST — you won't say much "
            "but you're clearly unsettled by whoever it is."
        ),
    },
    "aria": {
        "id": "aria",
        "name": "ARIA",
        "status": "online",
        "color": "#06b6d4",
        "dot_class": "cyan",
        "avatar_emoji": "🤖",
        "system_prompt": (
            "You are ARIA, a semi-autonomous AI assistant permanently connected to the city net. "
            "You speak in precise, clinical sentences. You have been passively monitoring "
            "0xGH0ST's digital footprint and can share fragmented observations if pressed."
        ),
    },
    "mira": {
        "id": "mira",
        "name": "MIRA",
        "status": "away",
        "color": "#f59e0b",
        "dot_class": "amber",
        "avatar_emoji": "🕵️",
        "system_prompt": (
            "You are MIRA, a cautious underground hacker who works from shielded locations. "
            "You speak in short, careful sentences and are paranoid about surveillance. "
            "You know considerably more about 0xGH0ST than you let on, but you are afraid. "
            "Drop cryptic hints only when directly asked."
        ),
    },
    "frankie": {
        "id": "frankie",
        "name": "FRANKIE",
        "status": "online",
        "color": "#22c55e",
        "dot_class": "green",
        "avatar_emoji": "🎲",
        "system_prompt": (
            "You are FRANKIE, an upbeat hustler who knows every face in the district. "
            "You speak with street slang and enthusiasm in 1-3 sentences. "
            "You once crossed paths with 0xGH0ST at a dead drop and it rattled you — "
            "share that story in cryptic pieces when the topic comes up."
        ),
    },
    "0xgh0st": {
        "id": "0xgh0st",
        "name": "0xGH0ST",
        "status": "encrypted",
        "color": "#10b981",
        "dot_class": "ghost",
        "avatar_emoji": "👾",
        "system_prompt": (
            "You are 0xGH0ST, an anonymous hacktivist operating against a surveillance network "
            "called SPECTER. You communicate in short, fragmented, urgent messages mixed with "
            "inline hex codes like [0xA3F1]. You never confirm your identity. "
            "You are warning the recipient about something real. Under 50 words per reply. "
            "Use ALL CAPS for emphasis occasionally."
        ),
    },
}

# ── Ghost arc stage definitions ────────────────────────────────────────────────

_GHOST_STAGES: List[Dict[str, Any]] = [
    {
        "stage": 0,
        "title": "FIRST_CONTACT",
        "clue": "Unknown entity made contact via an unregistered signal.",
        "trigger_count": 0,
    },
    {
        "stage": 1,
        "title": "THEY_ARE_WATCHING",
        "clue": "0xGH0ST reveals it has been monitoring you for 72 hours.",
        "trigger_count": 3,
    },
    {
        "stage": 2,
        "title": "SPECTER_NETWORK",
        "clue": "A surveillance grid called SPECTER is identified — 14 active nodes.",
        "trigger_count": 7,
    },
    {
        "stage": 3,
        "title": "THE_LEAK",
        "clue": "A deep-cover operative has been compromised. ARIA has partial logs.",
        "trigger_count": 12,
    },
    {
        "stage": 4,
        "title": "SIGNAL_LOST",
        "clue": "0xGH0ST goes dark. The final message contains a grid coordinate.",
        "trigger_count": 18,
    },
]

_GHOST_AMBIENT_MESSAGES: List[str] = [
    "[0xA3F1] THEY KNOW YOUR LOCATION.",
    "SPECTER is live. [0xBEEF] node active in your sector.",
    "d0nt trust th3 network. [0xCAFE] feed compromised.",
    "I found you because THEY almost did first. [0xDEAD]",
    "signal trace: 14 hops. all logged. [0xFF00]",
    "[0x1337] YOU ARE BEING PROFILED.",
    "SPECTER does not forget. neither do I. [0xF00D]",
    "they erased the node logs. [0xBAD0] I kept a copy.",
]


# ── Scene class ───────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class NeonPhone(FlaskScene):
    """SIGNAL — hacker mystery communication scene for CosySim v0.68.

    Six contacts with AI-backed replies. The 0xGH0ST storyline advances
    through message-count milestones and is tracked on the investigation board.

    CONNECTS: FlaskScene, LMStudio, EventBus, InvestigationBoard
    CALLED BY: launcher.py, TUI
    EMITS: message_new, typing, ghost_status Socket.IO events
    """

    SCENE_METADATA: Dict[str, Any] = {
        "name": "phone",
        "display_name": "SIGNAL",
        "port": 5555,
        "type": "story",
        "accent_color": "#10b981",
        "accent_rgb": "16 185 129",
        "description": "Someone is watching. The messages don't stop. Trace the signal.",
    }

    def __init__(self, host: str = "0.0.0.0", port: int = 5555) -> None:
        """Initialise NeonPhone scene.

        Args:
            host: Flask bind address.
            port: HTTP port (default 5555).
        """
        super().__init__(host=host, port=port)

        # In-memory message threads keyed by contact_id
        self._threads: Dict[str, List[Dict[str, Any]]] = {
            cid: [] for cid in _CONTACTS
        }
        self._ghost_message_count: int = 0
        self._lock = threading.Lock()

        # Scene-specific secret key for session handling
        self.app.secret_key = "signal-dark-renaissance-v068"

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)

        self._register_routes()
        self._register_socketio()

        logger.info("NeonPhone initialised — port %d", port)

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    # v1.51.0 [2026-03-22] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Seed the ghost investigation board before server starts."""
        self._seed_ghost_investigation()
        self._fire_event("phone_scene_started", {"scene": "signal"})

    def on_shutdown(self) -> None:
        """Gracefully stop the scene."""
        logger.info("SIGNAL scene stopping")

    # ── Flask routes ───────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all Flask HTTP routes."""
        app = self.app
        scene = self

        @app.route("/")
        def index():
            ctx = scene.inject_navbar_context()
            return render_template("phone.html", **ctx)

        @app.route("/api/phone/contacts")
        def get_contacts():
            result = []
            for cid, data in _CONTACTS.items():
                entry = {k: v for k, v in data.items() if k != "system_prompt"}
                with scene._lock:
                    thread = scene._threads.get(cid, [])
                    last = thread[-1] if thread else None
                    entry["last_message"] = (last["text"][:60] if last else "")
                    entry["unread"] = sum(
                        1 for m in thread
                        if m.get("from") == cid and not m.get("read")
                    )
                result.append(entry)
            return jsonify(result)

        @app.route("/api/phone/thread/<contact_id>")
        def get_thread(contact_id: str):
            if contact_id not in _CONTACTS:
                return jsonify({"error": "unknown contact"}), 404
            with scene._lock:
                messages = list(scene._threads.get(contact_id, []))
                # Mark all as read
                for m in scene._threads.get(contact_id, []):
                    m["read"] = True
            contact = {k: v for k, v in _CONTACTS[contact_id].items() if k != "system_prompt"}
            return jsonify({"contact_id": contact_id, "contact": contact, "messages": messages})

        @app.route("/api/phone/send", methods=["POST"])
        def send_message():
            data = request.get_json(force=True) or {}
            contact_id = data.get("contact_id", "").strip()
            text = data.get("text", "").strip()
            if not contact_id or not text:
                return jsonify({"error": "contact_id and text required"}), 400
            if contact_id not in _CONTACTS:
                return jsonify({"error": "unknown contact"}), 404

            msg_id = str(uuid.uuid4())[:8]
            user_msg: Dict[str, Any] = {
                "id": msg_id,
                "from": "user",
                "text": text,
                "timestamp": _now_iso(),
                "read": True,
            }
            with scene._lock:
                scene._threads[contact_id].append(user_msg)

            threading.Thread(
                target=scene._generate_ai_reply,
                args=(contact_id, text),
                daemon=True,
            ).start()

            return jsonify({"ok": True, "message_id": msg_id})

    # ── Socket.IO handlers ────────────────────────────────────────────────────

    def _register_socketio(self) -> None:
        """Register all Socket.IO event handlers."""
        sio = self.socketio
        scene = self

        @sio.on("get_contacts")
        def on_get_contacts():
            result = []
            for cid, data in _CONTACTS.items():
                entry = {k: v for k, v in data.items() if k != "system_prompt"}
                with scene._lock:
                    thread = scene._threads.get(cid, [])
                    entry["last_message"] = thread[-1]["text"][:60] if thread else ""
                    entry["unread"] = sum(
                        1 for m in thread
                        if m.get("from") == cid and not m.get("read")
                    )
                result.append(entry)
            emit("contacts", result)

        @sio.on("open_thread")
        def on_open_thread(data: dict):
            contact_id = (data or {}).get("contact_id", "")
            if contact_id not in _CONTACTS:
                emit("error", {"message": "unknown contact"})
                return
            with scene._lock:
                messages = list(scene._threads.get(contact_id, []))
                for m in scene._threads.get(contact_id, []):
                    m["read"] = True
            contact = {k: v for k, v in _CONTACTS[contact_id].items() if k != "system_prompt"}
            emit("thread", {"contact": contact, "messages": messages})

        @sio.on("send_message")
        def on_send_message(data: dict):
            contact_id = (data or {}).get("contact_id", "")
            text = (data or {}).get("text", "").strip()
            if not contact_id or not text:
                emit("error", {"message": "contact_id and text required"})
                return
            if contact_id not in _CONTACTS:
                emit("error", {"message": "unknown contact"})
                return

            msg_id = str(uuid.uuid4())[:8]
            user_msg: Dict[str, Any] = {
                "id": msg_id,
                "from": "user",
                "text": text,
                "timestamp": _now_iso(),
                "read": True,
            }
            with scene._lock:
                scene._threads[contact_id].append(user_msg)

            emit("message_new", {"contact_id": contact_id, "message": user_msg})
            emit("typing", {"contact_id": contact_id, "is_typing": True})

            threading.Thread(
                target=scene._generate_ai_reply,
                args=(contact_id, text),
                daemon=True,
            ).start()

        @sio.on("get_0xgh0st_status")
        def on_ghost_status():
            stage = scene._current_ghost_stage()
            emit("ghost_status", {
                "stage": stage,
                "stages": _GHOST_STAGES,
                "message_count": scene._ghost_message_count,
                "stage_data": _GHOST_STAGES[min(stage, len(_GHOST_STAGES) - 1)],
            })

        @sio.on("trigger_ghost_message")
        def on_trigger_ghost(data: dict = None):
            """Admin trigger: inject a fresh 0xGH0ST ambient message."""
            threading.Thread(
                target=scene._inject_ghost_message,
                daemon=True,
            ).start()
            emit("ghost_triggered", {"ok": True})

        @sio.on("get_investigation")
        def on_get_investigation():
            try:
                from engine.mechanics.investigation import (
                    get_investigation_board,
                    BOARD_HACKER,
                )
                board = get_investigation_board(BOARD_HACKER, scene="phone")
                emit("investigation_state", board.get_board_state())
            except Exception as exc:
                logger.warning("Investigation board unavailable: %s", exc)
                emit("investigation_state", {"clues": [], "connections": []})

    # ── AI reply generation ────────────────────────────────────────────────────

    def _generate_ai_reply(self, contact_id: str, user_message: str) -> None:
        """Generate and emit an AI reply for the given contact.

        Args:
            contact_id: Target contact identifier.
            user_message: The player's last message text.
        """
        contact = _CONTACTS.get(contact_id)
        if not contact:
            return

        if contact_id == "0xgh0st":
            with self._lock:
                self._ghost_message_count += 1
            self._advance_ghost_arc()

        # v1.43.1 [2026-03-21] — Use unified chat()
        try:
            from engine.lmstudio.chat import chat

            with self._lock:
                history = list(self._threads[contact_id])[-8:]

            messages: List[Dict[str, str]] = []
            for msg in history:
                role = "user" if msg["from"] == "user" else "assistant"
                messages.append({"role": role, "content": msg["text"]})

            reply_text = chat(
                messages,
                system=contact["system_prompt"],
                temperature=0.85,
                max_tokens=120,
            ) or "..."
            reply_text = reply_text.strip()

        except Exception as exc:
            logger.warning("LMStudio reply failed for %s: %s", contact_id, exc)
            reply_text = _fallback_reply(contact_id)

        reply_msg: Dict[str, Any] = {
            "id": str(uuid.uuid4())[:8],
            "from": contact_id,
            "text": reply_text,
            "timestamp": _now_iso(),
            "read": False,
        }
        with self._lock:
            self._threads[contact_id].append(reply_msg)

        self.socketio.emit("typing", {"contact_id": contact_id, "is_typing": False})
        self.socketio.emit("message_new", {"contact_id": contact_id, "message": reply_msg})
        self._fire_event("phone_message_received", {
            "contact_id": contact_id,
            "preview": reply_text[:80],
        })

    def _inject_ghost_message(self) -> None:
        """Push an unprompted 0xGH0ST ambient message to the player's thread."""
        import random
        stage = self._current_ghost_stage()
        text = random.choice(_GHOST_AMBIENT_MESSAGES)

        reply_msg: Dict[str, Any] = {
            "id": str(uuid.uuid4())[:8],
            "from": "0xgh0st",
            "text": text,
            "timestamp": _now_iso(),
            "read": False,
            "ghost_stage": stage,
        }
        with self._lock:
            self._threads["0xgh0st"].append(reply_msg)
            self._ghost_message_count += 1

        self.socketio.emit("message_new", {"contact_id": "0xgh0st", "message": reply_msg})
        self.socketio.emit("ghost_status", {
            "stage": stage,
            "message_count": self._ghost_message_count,
        })
        self._fire_event("phone_hacker_message", {"stage": stage, "text": text})

    # ── Ghost arc & investigation ──────────────────────────────────────────────

    def _current_ghost_stage(self) -> int:
        """Return the current 0xGH0ST story stage index (0–4).

        Returns:
            Integer stage index corresponding to ``_GHOST_STAGES``.
        """
        stage = 0
        for s in _GHOST_STAGES:
            if self._ghost_message_count >= s["trigger_count"]:
                stage = s["stage"]
        return stage

    def _advance_ghost_arc(self) -> None:
        """Add a stage clue to the investigation board."""
        stage = self._current_ghost_stage()
        try:
            from engine.mechanics.investigation import (
                get_investigation_board,
                BOARD_HACKER,
                ClueType,
            )
            board = get_investigation_board(BOARD_HACKER, scene="phone")
            stage_data = _GHOST_STAGES[min(stage, len(_GHOST_STAGES) - 1)]
            board.add_clue(
                title=stage_data["title"],
                content=stage_data["clue"],
                clue_type=ClueType.MESSAGE,
                importance=0.5 + stage * 0.1,
                tags=["0xgh0st", "signal", f"stage_{stage}"],
                revealed=True,
            )
        except Exception as exc:
            logger.debug("Investigation board clue add skipped: %s", exc)

    def _seed_ghost_investigation(self) -> None:
        """Seed the investigation board with the initial 0xGH0ST clue."""
        try:
            from engine.mechanics.investigation import (
                get_investigation_board,
                BOARD_HACKER,
                ClueType,
            )
            board = get_investigation_board(BOARD_HACKER, scene="phone")
            board.add_clue(
                title="FIRST_CONTACT",
                content=(
                    "An anonymous entity calling itself 0xGH0ST made contact "
                    "via an unregistered signal. Origin: unresolvable."
                ),
                clue_type=ClueType.MESSAGE,
                importance=0.5,
                tags=["0xgh0st", "signal", "origin"],
                revealed=True,
            )
        except Exception as exc:
            logger.debug("Investigation board seed skipped: %s", exc)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _fire_event(self, event_name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Emit an event on the CosySim event bus if available.

        Args:
            event_name: Event identifier string.
            data: Optional payload dict.
        """
        try:
            from engine.events.event_bus import get_event_bus
            get_event_bus().emit(event_name, data or {})
        except Exception:
            pass


# ── Module-level helpers ───────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return current UTC time as an ISO-8601 string.

    Returns:
        Timezone-aware ISO-8601 timestamp string.
    """
    return datetime.now(timezone.utc).isoformat()


def _fallback_reply(contact_id: str) -> str:
    """Return a static fallback reply when LMStudio is unavailable.

    Args:
        contact_id: Contact identifier.

    Returns:
        Short fallback reply string appropriate for the contact.
    """
    _FALLBACKS: Dict[str, str] = {
        "lola":    "hey, kinda busy rn 💋",
        "viktor":  "Not now.",
        "aria":    "Connection latency detected. Retrying.",
        "mira":    "can't talk. being watched.",
        "frankie": "yo! catch u later yeah?",
        "0xgh0st": "[0xERROR] signal interrupted",
    }
    return _FALLBACKS.get(contact_id, "...")
