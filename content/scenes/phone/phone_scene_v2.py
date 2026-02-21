"""
Phone Scene v2 — Full Rewrite
================================
Multi-contact iOS-style messaging scene backed by PhoneDB.

Features
--------
* Thread-based messaging:  DMs + group chats
* MCP governor pipeline on every AI reply
* MCPTimer-driven autonomous agent texting (per character)
* Background ticker thread (10 s interval)
* Truth-or-dare game via MCPGameSession
* Voice / photo / video message cards
* Real-time Socket.IO events to the browser
* Data-wipe admin route (messages + media, keeps characters)
"""
from __future__ import annotations

import logging
import os
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_socketio import SocketIO, emit, join_room

project_root = Path(__file__).parent.parent.parent.parent
import sys; sys.path.insert(0, str(project_root))

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework
from content.scenes.phone.phone_db import PhoneDB
from content.scenes.phone.phone_rules_v2 import (
    register_phone_rules,
    autotxt_cooldown,
    autotxt_prompt,
    get_truth, get_dare,
    SCENE_ID,
)
from content.simulation.database.db import Database
from content.simulation.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)

# ── Media paths ────────────────────────────────────────────────────────────────
_SCENE_ROOT  = Path(__file__).parent
_STATIC_DIR  = _SCENE_ROOT / "static"
_TEMPLATE_DIR = _SCENE_ROOT / "templates"
_MEDIA_VOICE  = project_root / "content" / "simulation" / "media" / "voice"
_MEDIA_VIDEO  = project_root / "content" / "simulation" / "media" / "video"
_MEDIA_PHOTO  = project_root / "content" / "simulation" / "media" / "photo"

for _d in [_MEDIA_VOICE, _MEDIA_VIDEO, _MEDIA_PHOTO]:
    _d.mkdir(parents=True, exist_ok=True)


# ── Adapter: wraps a character for the governor pipeline ──────────────────────

class _PhoneCharacterAgent:
    """
    Minimal duck-type that satisfies AgentGovernor.
    Keeps a direct reference to the scene's _generate_reply method so the
    15 MCP interceptors fire on every phone response.
    """

    def __init__(self, char_id: str, scene: "PhoneSceneV2"):
        self.char_id = char_id
        self._scene  = scene
        # character attribute read by CharacterRegistryInterceptor
        self.character = None

    def _refresh(self):
        self.character = self._scene.db.get_character(self.char_id)

    def reply(self, message: str, *, chain_id=None, history=None, **_kwargs) -> str:
        return self._scene._generate_reply(self.char_id, message)

    def quick_query(self, prompt: str) -> str:
        return self._scene._generate_reply(self.char_id, prompt)


# ── Main scene class ──────────────────────────────────────────────────────────

class PhoneSceneV2(BaseScene, MCPSceneMixin, mcp_scene_id=SCENE_ID):
    """iOS-style phone scene — multi-contact DMs, group chats, truth-or-dare."""

    # ── lifecycle ───────────────────────────────────────────────────────────────

    def __init__(self, host: str = "0.0.0.0", port: int = 5555):
        super().__init__(scene_name="phone", host=host, port=port)

        self.phone_db = PhoneDB()
        self.db       = Database()
        self.llm      = get_llm_service()

        # Per-character governor adapters  {char_id: _PhoneCharacterAgent}
        self._agents: Dict[str, _PhoneCharacterAgent] = {}

        # Autonomous-texting timer state  {char_id: deadline_epoch}
        self._autotxt_deadlines: Dict[str, float] = {}
        self._autotxt_lock = threading.Lock()

        # Background ticker
        self._ticker_stop = threading.Event()
        self._ticker_thread: Optional[threading.Thread] = None

        # Flask + SocketIO
        self.app = Flask(
            __name__,
            template_folder=str(_TEMPLATE_DIR),
            static_folder=str(_STATIC_DIR),
        )
        self.app.secret_key = os.urandom(24)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")

        self._register_routes()
        self._register_socketio()

    def start(self) -> None:
        self._seed_characters()
        self._start_ticker()
        try:
            fw = get_framework()
            node = fw.get_scene(SCENE_ID)
            register_phone_rules(node)
        except Exception as exc:
            logger.warning("MCP rule registration skipped: %s", exc)
        logger.info("PhoneSceneV2 started on %s:%s", self.host, self.port)
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, use_reloader=False)

    def stop(self) -> None:
        self._ticker_stop.set()
        logger.info("PhoneSceneV2 stopped")

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name":        "Phone (v2)",
            "scene_id":    SCENE_ID,
            "description": "iOS-style multi-contact messaging scene with MCP governor.",
            "version":     "2.0.0",
            "port":        self.port,
            "skill_packs": [],
        }

    # ── character seeding ────────────────────────────────────────────────────

    def _seed_characters(self) -> None:
        """Load all characters and create their DM threads if missing."""
        try:
            chars = self.db.get_all_characters()
            for row in chars:
                char_id = str(row.get("id") or row.get("character_id") or "")
                if not char_id:
                    continue
                self.phone_db.get_or_create_dm(char_id)
                self._agents[char_id] = _PhoneCharacterAgent(char_id, self)
                self._schedule_autotxt(char_id)
            logger.info("Seeded %d characters into phone scene", len(chars))
        except Exception as exc:
            logger.warning("Character seeding failed: %s", exc)

    # ── autonomous texting ───────────────────────────────────────────────────

    def _schedule_autotxt(self, char_id: str, extra_delay: float = 0.0) -> None:
        """Set a random future deadline for the next autonomous text from char_id."""
        try:
            char = self.db.get_character(char_id)
            trust     = float((char or {}).get("trust",     30))
            affection = float((char or {}).get("affection", 30))
        except Exception:
            trust = affection = 30.0
        cooldown = autotxt_cooldown(trust, affection) + extra_delay
        with self._autotxt_lock:
            self._autotxt_deadlines[char_id] = time.time() + cooldown

    def _start_ticker(self) -> None:
        self._ticker_stop.clear()
        self._ticker_thread = threading.Thread(
            target=self._ticker_loop, daemon=True, name="phone-autotxt-ticker"
        )
        self._ticker_thread.start()

    def _ticker_loop(self) -> None:
        while not self._ticker_stop.wait(10):
            now = time.time()
            with self._autotxt_lock:
                due = [cid for cid, dl in self._autotxt_deadlines.items() if dl <= now]
            for char_id in due:
                self._fire_autotxt(char_id)

    def _fire_autotxt(self, char_id: str) -> None:
        """Generate and deliver an autonomous text from char_id."""
        try:
            thread_id = self.phone_db.get_or_create_dm(char_id)
            char      = self.db.get_character(char_id)
            conv_mode = "neutral"
            try:
                thread_msgs = self.phone_db.get_messages(thread_id, limit=5)
                if any(m.get("content", "") for m in thread_msgs):
                    conv_mode = "warm"
            except Exception:
                pass

            prompt = autotxt_prompt(conv_mode)
            text   = self._generate_reply(char_id, prompt, system_override=prompt)
            if not text.strip():
                return

            msg = self.phone_db.save_message(
                thread_id=thread_id,
                sender_id=char_id,
                content=text,
                msg_type="text",
            )
            self._emit("message_new", {
                "thread_id": thread_id,
                "message":   msg,
                "char_name": (char or {}).get("name", char_id),
            })
            self._emit("thread_updated", {"thread_id": thread_id})
        except Exception as exc:
            logger.warning("autotxt fire failed for %s: %s", char_id, exc)
        finally:
            self._schedule_autotxt(char_id)

    # ── LLM reply ────────────────────────────────────────────────────────────

    def _generate_reply(self, char_id: str, user_msg: str, *,
                        system_override: Optional[str] = None) -> str:
        """Run the governor pipeline (or fall back to direct LLM) and return reply text."""
        try:
            from engine.mcp.comms_framework import get_governor
            agent = self._agents.get(char_id)
            if agent is None:
                agent = _PhoneCharacterAgent(char_id, self)
                self._agents[char_id] = agent
            agent._refresh()

            gov = get_governor(agent, scene=SCENE_ID)
            return gov.reply(user_msg, chain_id=None, history=None)
        except Exception as exc:
            logger.debug("Governor unavailable (%s), falling back to LLM", exc)

        # Direct LLM fallback
        try:
            char = self.db.get_character(char_id)
            name = (char or {}).get("name", "Character")
            personality = (char or {}).get("personality", "")
            system = system_override or (
                f"You are {name}. {personality}\n"
                "Reply naturally as a real person texting. Keep messages short."
            )
            return self.llm.get_response(
                system_prompt=system,
                user_message=user_msg,
                max_tokens=200,
            )
        except Exception as exc:
            logger.error("LLM reply failed: %s", exc)
            return ""

    # ── Socket.IO ────────────────────────────────────────────────────────────

    def _emit(self, event: str, data: Any) -> None:
        try:
            self.socketio.emit(event, data)
        except Exception:
            pass

    def _register_socketio(self) -> None:
        sio = self.socketio

        @sio.on("join_thread")
        def _join(data):
            tid = data.get("thread_id", "")
            if tid:
                join_room(f"thread_{tid}")

        @sio.on("typing")
        def _typing(data):
            tid = data.get("thread_id", "")
            emit("typing", data, to=f"thread_{tid}", include_self=False)

    # ── HTTP routes ──────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        app = self.app

        # ── Page ─────────────────────────────────────────────────────────────
        @app.route("/")
        def index():
            return render_template("phone_ui_v2.html")

        # ── Threads ─────────────────────────────────────────────────────────
        @app.route("/api/threads")
        def get_threads():
            try:
                threads = self.phone_db.list_threads()
                return jsonify({"ok": True, "threads": threads})
            except Exception as exc:
                logger.error("list_threads: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/threads/dm", methods=["POST"])
        def open_dm():
            body    = request.get_json(force=True, silent=True) or {}
            char_id = str(body.get("character_id", "")).strip()
            if not char_id:
                return jsonify({"ok": False, "error": "character_id required"}), 400
            try:
                tid = self.phone_db.get_or_create_dm(char_id)
                return jsonify({"ok": True, "thread_id": tid})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/threads/group", methods=["POST"])
        def create_group():
            body       = request.get_json(force=True, silent=True) or {}
            name       = str(body.get("name", "Group")).strip()
            member_ids = list(body.get("member_ids", []))
            if not member_ids:
                return jsonify({"ok": False, "error": "member_ids required"}), 400
            try:
                tid = self.phone_db.create_group(name, member_ids)
                return jsonify({"ok": True, "thread_id": tid})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Messages ─────────────────────────────────────────────────────────
        @app.route("/api/thread/<thread_id>/messages")
        def get_messages(thread_id: str):
            limit  = int(request.args.get("limit", 50))
            before = request.args.get("before")
            try:
                msgs = self.phone_db.get_messages(thread_id, limit=limit, before=before)
                self.phone_db.mark_read(thread_id)
                return jsonify({"ok": True, "messages": msgs})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/thread/<thread_id>/send", methods=["POST"])
        def send_message(thread_id: str):
            body     = request.get_json(force=True, silent=True) or {}
            content  = str(body.get("content", "")).strip()
            msg_type = str(body.get("type", "text"))

            if not content and msg_type == "text":
                return jsonify({"ok": False, "error": "content required"}), 400

            # Save player message
            try:
                user_msg = self.phone_db.save_message(
                    thread_id=thread_id,
                    sender_id="user",
                    content=content,
                    msg_type=msg_type,
                )
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

            self._emit("message_new", {"thread_id": thread_id, "message": user_msg})

            # Determine which characters are in this thread
            try:
                members = self.phone_db.get_thread_members(thread_id)
            except Exception:
                members = []

            # Generate AI replies (off-thread to return fast)
            def _reply_worker():
                for char_id in members:
                    if char_id == "user":
                        continue
                    try:
                        # Emit typing indicator
                        self._emit("typing", {"thread_id": thread_id, "char_id": char_id, "active": True})
                        time.sleep(random.uniform(0.5, 2.0))

                        reply_text = self._generate_reply(char_id, content)
                        if not reply_text.strip():
                            continue

                        char = self.db.get_character(char_id)
                        ai_msg = self.phone_db.save_message(
                            thread_id=thread_id,
                            sender_id=char_id,
                            content=reply_text,
                            msg_type="text",
                        )
                        self._emit("typing", {"thread_id": thread_id, "char_id": char_id, "active": False})
                        self._emit("message_new", {
                            "thread_id": thread_id,
                            "message":   ai_msg,
                            "char_name": (char or {}).get("name", char_id),
                        })
                        self._emit("thread_updated", {"thread_id": thread_id})
                    except Exception as exc:
                        logger.error("Reply worker error for %s: %s", char_id, exc)
                        self._emit("typing", {"thread_id": thread_id, "char_id": char_id, "active": False})

            threading.Thread(target=_reply_worker, daemon=True).start()
            return jsonify({"ok": True, "message": user_msg})

        # ── Contacts ─────────────────────────────────────────────────────────
        @app.route("/api/contacts")
        def get_contacts():
            try:
                chars = self.db.get_all_characters()
                contacts = []
                for row in (chars or []):
                    char_id = str(row.get("id") or row.get("character_id") or "")
                    unread  = 0
                    try:
                        tid = self.phone_db.get_or_create_dm(char_id)
                        unread = self.phone_db.thread_unread(tid)
                    except Exception:
                        pass
                    contacts.append({
                        "id":        char_id,
                        "name":      row.get("name", ""),
                        "avatar":    row.get("avatar_url") or row.get("image_url") or "",
                        "mood":      row.get("mood", ""),
                        "status":    row.get("status", "online"),
                        "unread":    unread,
                    })
                return jsonify({"ok": True, "contacts": contacts})
            except Exception as exc:
                logger.error("get_contacts: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Games ─────────────────────────────────────────────────────────────
        @app.route("/api/games/start", methods=["POST"])
        def start_game():
            body      = request.get_json(force=True, silent=True) or {}
            thread_id = str(body.get("thread_id", "")).strip()
            char_id   = str(body.get("character_id", "")).strip()
            if not thread_id or not char_id:
                return jsonify({"ok": False, "error": "thread_id and character_id required"}), 400
            try:
                session_id = self.phone_db.create_game_session(thread_id, char_id, "truth_or_dare")
                # System message announcing the game
                self.phone_db.save_message(
                    thread_id=thread_id,
                    sender_id="system",
                    content=f"Truth or Dare game started! 🎮",
                    msg_type="system",
                    metadata={"session_id": session_id},
                )
                self._emit("game_event", {"thread_id": thread_id, "event": "game_started", "session_id": session_id})
                return jsonify({"ok": True, "session_id": session_id})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/games/action", methods=["POST"])
        def game_action():
            body       = request.get_json(force=True, silent=True) or {}
            thread_id  = str(body.get("thread_id", "")).strip()
            choice     = str(body.get("choice", "")).lower()  # 'truth' | 'dare'
            session    = self.phone_db.get_game_session(thread_id)
            if not session:
                return jsonify({"ok": False, "error": "No active game session"}), 404
            if choice not in ("truth", "dare"):
                return jsonify({"ok": False, "error": "choice must be 'truth' or 'dare'"}), 400

            challenge = get_truth() if choice == "truth" else get_dare()
            state = session.get("state") or {}
            state["last_choice"]    = choice
            state["last_challenge"] = challenge
            state["round"]          = state.get("round", 0) + 1
            self.phone_db.update_game_state(session["id"], state)

            # Deliver challenge as a system message, then get AI reaction
            self.phone_db.save_message(
                thread_id=thread_id,
                sender_id="system",
                content=challenge,
                msg_type="game",
                metadata={"choice": choice, "round": state["round"]},
            )
            self._emit("game_event", {
                "thread_id": thread_id,
                "event":     "challenge",
                "choice":    choice,
                "challenge": challenge,
                "round":     state["round"],
            })

            # AI responds to the challenge off-thread
            char_id = session.get("character_id", "")
            def _ai_react():
                try:
                    reaction = self._generate_reply(
                        char_id,
                        f"You are playing truth or dare. The challenge is: {challenge}\n"
                        f"Respond in character — accept, react, answer, or playfully negotiate.",
                    )
                    if reaction:
                        msg = self.phone_db.save_message(
                            thread_id=thread_id,
                            sender_id=char_id,
                            content=reaction,
                            msg_type="text",
                        )
                        self._emit("message_new", {"thread_id": thread_id, "message": msg})
                except Exception as exc:
                    logger.error("game AI react: %s", exc)

            threading.Thread(target=_ai_react, daemon=True).start()
            return jsonify({"ok": True, "challenge": challenge, "round": state["round"]})

        @app.route("/api/games/end", methods=["POST"])
        def end_game():
            body      = request.get_json(force=True, silent=True) or {}
            thread_id = str(body.get("thread_id", "")).strip()
            session   = self.phone_db.get_game_session(thread_id)
            if not session:
                return jsonify({"ok": False, "error": "No active game session"}), 404
            self.phone_db.end_game_session(session["id"])
            self.phone_db.save_message(
                thread_id=thread_id,
                sender_id="system",
                content="Game ended. Thanks for playing! 🏁",
                msg_type="system",
            )
            self._emit("game_event", {"thread_id": thread_id, "event": "game_ended"})
            return jsonify({"ok": True})

        # ── Media static serve ────────────────────────────────────────────────
        @app.route("/media/voice/<filename>")
        def serve_voice(filename: str):
            return send_from_directory(str(_MEDIA_VOICE), filename)

        @app.route("/media/video/<filename>")
        def serve_video(filename: str):
            return send_from_directory(str(_MEDIA_VIDEO), filename)

        @app.route("/media/photo/<filename>")
        def serve_photo(filename: str):
            return send_from_directory(str(_MEDIA_PHOTO), filename)

        # ── Admin ─────────────────────────────────────────────────────────────
        @app.route("/api/admin/wipe-messages", methods=["POST"])
        def wipe_messages():
            try:
                count = self.phone_db.wipe_messages()
                # Wipe media files
                wiped_media = 0
                for _dir in [_MEDIA_VOICE, _MEDIA_VIDEO, _MEDIA_PHOTO]:
                    for f in _dir.iterdir():
                        if f.is_file():
                            try:
                                f.unlink()
                                wiped_media += 1
                            except Exception:
                                pass
                logger.info("Admin wipe: %d messages + %d media files deleted", count, wiped_media)
                self._emit("admin_wipe", {"messages": count, "media": wiped_media})
                return jsonify({"ok": True, "messages_deleted": count, "media_deleted": wiped_media})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/admin/stats")
        def admin_stats():
            try:
                unread = self.phone_db.total_unread()
                threads = self.phone_db.list_threads()
                return jsonify({
                    "ok":       True,
                    "unread":   unread,
                    "threads":  len(threads),
                    "scene_id": SCENE_ID,
                })
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500


# ── Module entry point ────────────────────────────────────────────────────────

def create_app(host: str = "0.0.0.0", port: int = 5555) -> PhoneSceneV2:
    """Factory used by the scene manager / launcher."""
    scene = PhoneSceneV2(host=host, port=port)
    return scene


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scene = create_app()
    scene.start()
