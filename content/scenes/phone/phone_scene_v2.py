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

from flask import jsonify, request, render_template, send_from_directory
from flask_socketio import emit, join_room

from engine.paths import ROOT as project_root
import sys; sys.path.insert(0, str(project_root))

from engine.scenes.flask_scene import FlaskScene
from engine.mcp.framework import get_framework
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
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry

logger = logging.getLogger(__name__)

# ── Media paths ────────────────────────────────────────────────────────────────
_SCENE_ROOT  = Path(__file__).parent
_STATIC_DIR  = _SCENE_ROOT / "static"
_TEMPLATE_DIR = _SCENE_ROOT / "templates"
_MEDIA_VOICE  = project_root / "content" / "simulation" / "media" / "voice"
_MEDIA_VIDEO  = project_root / "content" / "simulation" / "media" / "video"
_MEDIA_PHOTO  = project_root / "content" / "simulation" / "media" / "photo"
_MEDIA_IMAGES = project_root / "content" / "simulation" / "media" / "images"

for _d in [_MEDIA_VOICE, _MEDIA_VIDEO, _MEDIA_PHOTO, _MEDIA_IMAGES]:
    _d.mkdir(parents=True, exist_ok=True)


# ── Adapter: wraps a character for the governor pipeline ──────────────────────

class _PhoneCharacterAgent:
    """
    Minimal duck-type that satisfies AgentGovernor.

    **v2.8 — Stateful conversations:**  Uses ConversationManager for server-side
    state via ``previous_response_id``.  First call replays history from phone_db;
    subsequent calls send ONLY the new message (80%+ token savings).

    **IMPORTANT — no recursion rule:**  ``reply()`` must call the LLM
    *directly* via ``VirtualAgentManager``.  It must NOT call back into
    ``PhoneSceneV2._generate_reply()``; that method already wraps us in a
    governor, so calling it again would create an infinite loop.
    """

    def __init__(self, char_id: str, scene: "PhoneSceneV2"):
        self.char_id = char_id
        self._scene  = scene
        self.character = None
        self._last_processed = None

    def _refresh(self):
        self.character = self._scene.db.get_character(self.char_id)

    def _get_conversation(self, thread_id: str = ""):
        """Get or create a stateful Conversation for this character thread."""
        from engine.lmstudio.conversation import get_conversation_manager
        conv_id = f"phone_{self.char_id}_{thread_id}" if thread_id else f"phone_{self.char_id}"
        conv_mgr = get_conversation_manager()
        return conv_mgr.get_or_create(conv_id, system="", model=None)

    def reply(self, message: str, *, chain_id=None, history=None, governance_context=None, **_kwargs) -> str:
        """Route through VirtualAgentManager with streaming — invoked by the governor after interceptors fire."""
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            from engine.agents.stream_processor import strip_token_artifacts
            char  = self._scene.db.get_character(self.char_id)
            name  = (char or {}).get("name", "Character")
            pers  = (char or {}).get("personality", "")

            # Phone-specific formatting — identity comes from interceptors via governance_context
            base_system = (
                "Reply naturally as a real person texting. Keep messages short and conversational.\n"
                "Use emojis naturally 😏💕🔥. Be expressive and emotionally vivid.\n"
                "You may express mood with [MOOD:emotion] tags.\n"
                "To send a selfie, include [IMAGE:description of the selfie].\n"
                "To send a voice message, include [VOICE:tone].\n"
                "Never repeat your previous messages. Always advance the conversation."
            )
            # Interceptor context (personality, scene rules, heat, variety, etc.) prepends identity
            if governance_context:
                system = f"{governance_context}\n\n{base_system}"
            else:
                # Fallback — no governor, build minimal identity
                system = f"You are {name}. {pers}\n{base_system}"
            msgs = [{"role": "system", "content": system}]
            for turn in (history or []):
                msgs.append({"role": turn.get("role", "user"), "content": turn.get("content", "")})
            msgs.append({"role": "user", "content": message})
            mgr = get_virtual_agent_manager()
            req = InferenceRequest(
                agent_id=self.char_id,
                messages=msgs,
                temperature=0.9,
                max_output_tokens=4000,
                conversation_id=f"phone_{self.char_id}",
                store=True,
                metadata={"scene": "phone", "character_name": name},
            )
            # Prefer pipeline path for watcher + kill switch
            if hasattr(mgr, "infer_with_pipeline"):
                try:
                    response = mgr.infer_with_pipeline(req)
                except Exception:
                    response = mgr.infer_processed(req)
            else:
                response = mgr.infer_processed(req)
            self._last_processed = response
            text = (response.clean_text or "").strip()
            return strip_token_artifacts(text)
        except Exception as exc:
            logger.debug("_PhoneCharacterAgent.reply failed: %s", exc)
            return ""

    def quick_query(self, prompt: str) -> str:
        return self.reply(prompt)


# ── Main scene class ──────────────────────────────────────────────────────────

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class PhoneSceneV2(FlaskScene):
    """iOS-style phone scene — multi-contact DMs, group chats, truth-or-dare."""

    SCENE_METADATA = {
        "name": "phone",
        "display_name": "PHONE",
        "port": 5555,
        "title": "Phone",
        "description": "iOS-style phone interface with messaging, calls, and character social media. "
                       "Characters send autonomous texts and maintain relationships.",
        "genre": "social_simulation",
        "type": "social",
        "max_characters": 5,
        "features": ["messaging", "autonomous_texts", "character_relationships", "phone_os",
                     "contacts", "social_feed", "conversation_threads"],
    }

    # ── lifecycle ───────────────────────────────────────────────────────────────

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = 5555):
        super().__init__(host=host, port=port)

        self.phone_db = PhoneDB()
        self.db       = Database()
        self.llm      = get_llm_service()

        # Per-character governor adapters  {char_id: _PhoneCharacterAgent}
        self._agents: Dict[str, _PhoneCharacterAgent] = {}

        # Autonomous-texting timer state  {char_id: deadline_epoch}
        self._autotxt_deadlines: Dict[str, float] = {}
        self._autotxt_lock = threading.Lock()
        self._autotxt_muted = False  # Global mute for autonomous messages
        self._tick_lock = threading.RLock()

        # Background ticker
        self._ticker_stop = threading.Event()
        self._ticker_thread: Optional[threading.Thread] = None

        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        self.app.secret_key = os.urandom(24)

        # Mount control overlay
        from engine.overlay import mount_overlay
        mount_overlay(self.app, self.socketio)

        self._register_routes()
        self._register_socketio()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()

    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_before_serve(self) -> None:
        """Hook: seed characters, start ticker, register MCP rules, subscribe world events."""
        self._seed_characters()
        self._start_ticker()
        try:
            fw = get_framework()
            node = fw.get_scene(SCENE_ID)
            register_phone_rules(node)
            # Wire up framework event listeners
            fw.on("mood_contagion", lambda evt: self._on_mood_event(evt))
            fw.on("story_beat", lambda evt: self._on_story_beat(evt))
        except Exception as exc:
            logger.warning("MCP rule registration skipped: %s", exc)
        self._subscribe_world_events()

    def on_shutdown(self) -> None:
        """Hook: stop ticker and save framework state."""
        self._ticker_stop.set()
        try:
            get_framework().save_state()
        except Exception:
            pass

    def _on_mood_event(self, evt) -> None:
        """React to mood contagion events from the framework bus."""
        if evt.payload.get("source") in self._agents:
            try:
                self.socketio.emit("mood_update", evt.payload)
            except Exception:
                pass

    def _on_story_beat(self, evt) -> None:
        """React to story beat events."""
        if evt.payload.get("scene_id") == SCENE_ID:
            try:
                self.socketio.emit("story_beat", evt.payload)
            except Exception:
                pass

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name":        "Phone (v2)",
            "scene_id":    SCENE_ID,
            "description": "iOS-style multi-contact messaging scene with MCP governor.",
            "version":     "0.50b",
            "port":        self.port,
            "skill_packs": ["memory", "character", "social", "narrative"],
        }

    # ── living world integration ─────────────────────────────────────────────

    def _subscribe_world_events(self) -> None:
        """Subscribe to world event bus channels for living-world integration."""
        try:
            from engine.events.event_bus import get_event_bus, EventTypes
            bus = get_event_bus()
            bus.subscribe(
                EventTypes.PHONE_HACKER_MESSAGE,
                self._on_world_hacker_event,
                "phone_scene",
            )
            bus.subscribe(
                "world.major_event",
                self._on_world_major_event,
                "phone_scene",
            )
            logger.info("PhoneSceneV2 subscribed to world event channels")
        except Exception as exc:
            logger.warning("World event subscription failed: %s", exc)

    def _on_world_hacker_event(self, payload: Dict[str, Any]) -> None:
        """Handle incoming 0xGH0ST hacker event — emit to phone clients."""
        try:
            msg_text = payload.get("message", "")
            if msg_text:
                self._emit("incoming_message", {
                    "from": "0xGH0ST",
                    "text": msg_text,
                    "type": "ghost",
                    "time": "",
                })
        except Exception as exc:
            logger.debug("_on_world_hacker_event failed: %s", exc)

    def _on_world_major_event(self, payload: Dict[str, Any]) -> None:
        """Handle major world event — emit world_alert if intensity is high."""
        try:
            # Fetch the event from the sim log to get intensity
            from engine.world.world_sim import get_world_sim
            sim = get_world_sim()
            sim_event_id = payload.get("sim_event_id", "")
            with sim._lock:
                matching = [
                    e for e in sim._event_log
                    if e.id == sim_event_id
                ]
            event = matching[0] if matching else None
            intensity = (event.intensity if event else 0.0)
            if intensity >= 2.5:
                self._emit("world_alert", {
                    "title": payload.get("title", ""),
                    "scene": payload.get("scene", ""),
                    "event_type": payload.get("event_type", ""),
                    "intensity": intensity,
                })
        except Exception as exc:
            logger.debug("_on_world_major_event failed: %s", exc)

    def _get_incoming_world_messages(self) -> List[Dict[str, Any]]:
        """Return last 5 world events relevant to the phone scene.

        Filters the WorldSim event log for events where scene=="phone"
        or intensity >= 2.5 and returns them as formatted incoming-message
        dicts ready for JSON serialisation.

        Returns:
            List of message dicts with from, text, time, type, heat_impact keys.
        """
        try:
            from engine.world.world_sim import get_world_sim
            sim = get_world_sim()
            all_events = sim.get_all_events(limit=100)
            relevant = [
                e for e in all_events
                if e.scene == "phone" or e.intensity >= 2.5
            ][:5]
            messages = []
            for event in relevant:
                is_ghost = event.actor == "0xGH0ST"
                messages.append({
                    "from": "0xGH0ST" if is_ghost else (event.actor or "SYSTEM"),
                    "text": event.description,
                    "time": event.created_at,
                    "type": "ghost" if is_ghost else "world",
                    "heat_impact": int(event.payload.get("heat_impact", 0)),
                })
            return messages
        except Exception as exc:
            logger.warning("_get_incoming_world_messages failed: %s", exc)
            return []

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
                try:
                    fw = get_framework()
                    fw.get_character(char_id).enter_scene(SCENE_ID)
                except Exception:
                    pass
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
            with self._tick_lock:
                if self._autotxt_muted:
                    continue
                now = time.time()
                with self._autotxt_lock:
                    due = [cid for cid, dl in self._autotxt_deadlines.items() if dl <= now]
                for char_id in due:
                    self._fire_autotxt(char_id)
                try:
                    get_framework().tick(SCENE_ID)
                except Exception:
                    pass

    def _fire_autotxt(self, char_id: str) -> None:
        """Generate and deliver an autonomous text from char_id.

        v2.9: Uses store=false decision query to determine IF and WHAT to text,
        then store=true stateful call for the actual message content.
        """
        with self._tick_lock:
            try:
                thread_id = self.phone_db.get_or_create_dm(char_id)
                char      = self.db.get_character(char_id)
                char_name = (char or {}).get("name", char_id)

                # Determine conversation mode from recent history
                conv_mode = "neutral"
                try:
                    from engine.mcp.scene_rules_engine import get_conversation_heat
                    heat = get_conversation_heat()
                    heat_level = heat.get_level(f"phone_{char_id}")
                    if heat_level in ("hot", "intense"):
                        conv_mode = "intimate"
                    elif heat_level == "warm":
                        conv_mode = "flirty"
                    else:
                        thread_msgs = self.phone_db.get_messages(thread_id, limit=5)
                        if any(m.get("content", "") for m in thread_msgs):
                            conv_mode = "warm"
                except Exception:
                    pass

                prompt = autotxt_prompt(conv_mode)
                reply  = self._generate_reply(char_id, prompt, system_override=prompt)
                text   = reply.get("text", "").strip()
                if not text:
                    return

                metadata = {}
                if reply.get("mood"):
                    metadata["mood"] = reply["mood"]
                if reply.get("image_requests"):
                    metadata["image_requests"] = reply["image_requests"]

                msg = self.phone_db.save_message(
                    thread_id=thread_id,
                    sender_id=char_id,
                    content=text,
                    msg_type="text",
                    metadata=metadata if metadata else None,
                )
                try:
                    get_framework().emit_event("message_sent", {
                        "scene_id": SCENE_ID, "char_id": char_id,
                        "type": "autotxt", "thread_id": thread_id,
                    }, source=SCENE_ID)
                except Exception:
                    pass
                self._emit("message_new", {
                    "thread_id": thread_id,
                    "message":   msg,
                    "char_name": char_name,
                })
                self._emit("thread_updated", {"thread_id": thread_id})
            except Exception as exc:
                logger.warning("autotxt fire failed for %s: %s", char_id, exc)
            finally:
                self._schedule_autotxt(char_id)

    # ── LLM reply ────────────────────────────────────────────────────────────

    def _generate_reply(self, char_id: str, user_msg: str, *,
                        thread_id: Optional[str] = None,
                        system_override: Optional[str] = None) -> Dict[str, Any]:
        """Run the governor pipeline and return a rich reply dict.

        Returns dict with keys: text, mood, image_requests, action_tags, voice_style.
        The governor calls _PhoneCharacterAgent.reply() which uses infer_processed().

        v2.8: Uses ConversationManager for stateful conversations. History is loaded
        from phone_db only for the first interaction; subsequent calls use
        previous_response_id for server-side KV cache continuation.
        """
        from engine.agents.stream_processor import strip_token_artifacts

        # Build conversation history from phone_db (last 20 msgs for context)
        history: List[Dict[str, str]] = []
        if thread_id:
            try:
                recent = self.phone_db.get_messages(thread_id, limit=20)
                for m in recent:
                    role = "assistant" if m.get("sender_id") != "user" else "user"
                    history.append({"role": role, "content": m.get("content", "")})
                # Remove the last entry if it matches current user_msg (already appended)
                if history and history[-1].get("content") == user_msg and history[-1].get("role") == "user":
                    history.pop()
            except Exception as exc:
                logger.debug("Could not load history for %s: %s", thread_id, exc)

        result = {"text": "", "mood": None, "image_requests": [], "action_tags": [], "voice_style": None, "response_id": None}
        try:
            from engine.mcp.comms_framework import get_governor
            agent = self._agents.get(char_id)
            if agent is None:
                agent = _PhoneCharacterAgent(char_id, self)
                self._agents[char_id] = agent
            agent._refresh()
            agent._last_processed = None

            gov = get_governor(agent, scene=SCENE_ID)
            text = gov.reply(user_msg, chain_id=None, history=history or None)
            # Strip token artifacts from governor output
            text = strip_token_artifacts(text or "")
            result["text"] = text

            # Extract rich metadata from processed response
            proc = getattr(agent, "_last_processed", None)
            if proc:
                result["mood"] = proc.mood_tags[0] if proc.mood_tags else None
                result["image_requests"] = list(proc.image_requests)
                result["action_tags"] = list(proc.action_tags)
                result["voice_style"] = proc.voice_style
                result["response_id"] = proc.response_id or None
                # Update character mood in framework
                if result["mood"]:
                    try:
                        fw = get_framework()
                        char_node = fw.get_character(char_id)
                        if char_node:
                            char_node.update_state({"mood": result["mood"]})
                    except Exception:
                        pass
            return result
        except Exception as exc:
            logger.error("Governor reply failed for %s: %s", char_id, exc)
            result["text"] = "(I'm having trouble replying right now. Try again in a moment.)"
            return result

    # ── Socket.IO ────────────────────────────────────────────────────────────

    def _emit(self, event: str, data: Any) -> None:
        try:
            self.socketio.emit(event, data)
        except Exception:
            pass

    # ── News Feed Helpers ───────────────────────────────────────────────────

    def _sync_news_from_nexus(self) -> int:
        """Pull latest news articles from Nexus into the phone feed."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            results = client.search("News:", limit=50)
            if not results:
                return 0

            import hashlib
            count = 0
            for entry in results:
                title = entry.get("title", "")
                content = entry.get("content", "")
                if not title.startswith("News:") and not title.startswith("[News]"):
                    continue

                # Extract URL from content
                url = ""
                for line in content.split("\n"):
                    if line.startswith("URL:"):
                        url = line[4:].strip()
                        break

                # Extract relevance
                relevance = 0.0
                for line in content.split("\n"):
                    if line.startswith("Relevance:"):
                        try:
                            relevance = float(line.split(":")[1].strip())
                        except (ValueError, IndexError):
                            pass
                        break

                item_id = hashlib.sha256(
                    (title + url).encode("utf-8")
                ).hexdigest()[:16]

                clean_title = title.replace("News: ", "").replace("[News] ", "")
                # Build markup card
                markup = self._build_news_markup(clean_title, content, url, relevance)

                new = self.phone_db.upsert_news_item(
                    item_id=item_id,
                    title=clean_title,
                    summary=content[:300],
                    url=url,
                    source_id=entry.get("category", ""),
                    category=entry.get("category", "general"),
                    relevance=relevance,
                    markup=markup,
                    nexus_id=entry.get("id", ""),
                )
                if new:
                    count += 1

            if count > 0:
                self._emit("news_updated", self.phone_db.get_news_stats())
            return count
        except Exception as exc:
            logger.warning("News sync failed: %s", exc)
            return 0

    def _build_news_markup(
        self, title: str, content: str, url: str, relevance: float,
    ) -> str:
        """Build an HTML card for a news article."""
        # Extract summary from content (skip metadata lines)
        summary_lines = []
        for line in content.split("\n"):
            if line.startswith(("**", "Source:", "URL:", "Published:", "Relevance:")):
                continue
            if line.strip():
                summary_lines.append(line.strip())
        summary = " ".join(summary_lines)[:250]

        rel_pct = int(relevance * 100)
        rel_color = "#4caf50" if relevance > 0.6 else "#ff9800" if relevance > 0.3 else "#9e9e9e"

        return f"""<div class="news-card">
  <h3 class="news-title">{title}</h3>
  <p class="news-summary">{summary}</p>
  <div class="news-meta">
    <span class="news-relevance" style="color:{rel_color}">{rel_pct}% relevant</span>
    {f'<a href="{url}" target="_blank" class="news-link">Read →</a>' if url else ''}
  </div>
</div>"""

    def _record_news_feedback(self, item_id: str, feedback: int) -> None:
        """Record news feedback in the training flywheel for the feedback loop."""
        try:
            from engine.nexus.training_flywheel import get_training_flywheel
            flywheel = get_training_flywheel()

            # Get the news item details
            items = self.phone_db.get_news_feed(limit=1000)
            item = next((i for i in items if i["id"] == item_id), None)
            if not item:
                return

            label = "positive" if feedback > 0 else "negative"
            flywheel.collect_from_preference(
                prompt=f"News article: {item['title']}",
                chosen=f"User {label} feedback on news from {item['source_id']}: {item['title']}",
                rejected=f"No feedback on similar articles",
                source="phone_news_feedback",
            )
        except Exception as exc:
            logger.debug("News feedback recording failed: %s", exc)

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
            # v1.52.0 — CosyPhone OS (feature-rich phone/cyberdeck)
            # The game's entry point — this is where it all begins
            return render_template("phone_ui_v2.html")

        # v1.52.0 — SIGNAL terminal as alternate UI (neon_base)
        @app.route("/signal")
        def signal_terminal():
            """SIGNAL cyberdeck terminal — lightweight neon_base messaging."""
            return render_template("signal.html")

        # ── Threads ─────────────────────────────────────────────────────────
        @app.route("/api/threads")
        def get_threads():
            try:
                threads = self.phone_db.list_threads()
                # Enrich each thread with character name + avatar from main DB
                # and deduplicate DMs by character (race-condition clean-up).
                dm_by_char: Dict[str, Dict] = {}
                group_threads: List[Dict] = []
                for t in threads:
                    members = t.get("members", [])
                    if t.get("type") == "dm" and members:
                        char_id   = members[0]
                        char_row  = self.db.get_character(char_id)
                        if char_row:
                            t["name"]        = t.get("name") or char_row.get("name", char_id)
                            t["char_name"]   = char_row.get("name", char_id)
                            t["char_avatar"] = (char_row.get("avatar_url")
                                                or char_row.get("image_url") or "")
                            t["char_id"]     = char_id
                        # Keep only the most-recently-updated thread per character
                        if char_id not in dm_by_char:
                            dm_by_char[char_id] = t
                        else:
                            existing = dm_by_char[char_id]
                            if t["updated_at"] > existing["updated_at"]:
                                t["unread"] = t.get("unread", 0) + existing.get("unread", 0)
                                dm_by_char[char_id] = t
                            else:
                                existing["unread"] = existing.get("unread", 0) + t.get("unread", 0)
                    else:
                        group_threads.append(t)

                result = list(dm_by_char.values()) + group_threads
                result.sort(key=lambda x: x["updated_at"], reverse=True)
                return jsonify({"ok": True, "threads": result})
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
                with self._tick_lock:
                    for char_id in members:
                        if char_id == "user":
                            continue
                        try:
                            # Emit typing indicator
                            self._emit("typing", {"thread_id": thread_id, "char_id": char_id, "active": True})
                            time.sleep(random.uniform(0.5, 2.0))

                            reply = self._generate_reply(char_id, content, thread_id=thread_id)
                            reply_text = reply.get("text", "").strip()
                            if not reply_text:
                                continue

                            char = self.db.get_character(char_id)
                            char_name = (char or {}).get("name", char_id)

                            # Build message metadata from rich response
                            metadata = {}
                            if reply.get("mood"):
                                metadata["mood"] = reply["mood"]

                            ai_msg = self.phone_db.save_message(
                                thread_id=thread_id,
                                sender_id=char_id,
                                content=reply_text,
                                msg_type="text",
                                metadata=metadata if metadata else None,
                                response_id=reply.get("response_id"),
                                conversation_id=f"phone_{char_id}",
                            )
                            self._emit("typing", {"thread_id": thread_id, "char_id": char_id, "active": False})

                            # Handle image requests — generate and send as separate message
                            for img_prompt in reply.get("image_requests", []):
                                try:
                                    from content.simulation.services.comfyui_client import get_comfyui_client
                                    comfy = get_comfyui_client()
                                    image_path = comfy.generate_image(
                                        prompt=f"{char_name} selfie: {img_prompt}",
                                        character_name=char_name,
                                    )
                                    if image_path:
                                        img_msg = self.phone_db.save_message(
                                            thread_id=thread_id,
                                            sender_id=char_id,
                                            content=img_prompt,
                                            msg_type="photo",
                                            metadata={"image_path": str(image_path), "generated": True},
                                        )
                                        self._emit("message_new", {
                                            "thread_id": thread_id,
                                            "message": img_msg,
                                            "char_name": char_name,
                                        })
                                except Exception as img_exc:
                                    logger.debug("Image generation failed: %s", img_exc)

                            try:
                                get_framework().emit_event("message_sent", {
                                    "scene_id": SCENE_ID, "char_id": char_id,
                                    "type": "reply", "thread_id": thread_id,
                                    "mood": reply.get("mood"),
                                }, source=SCENE_ID)
                            except Exception:
                                pass
                            self._emit("message_new", {
                                "thread_id": thread_id,
                                "message":   ai_msg,
                                "char_name": char_name,
                                "mood":      reply.get("mood"),
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
            # Check primary path first, then alternate
            if (_MEDIA_VIDEO / filename).exists():
                return send_from_directory(str(_MEDIA_VIDEO), filename)
            alt_video = project_root / "content" / "media" / "video"
            if (alt_video / filename).exists():
                return send_from_directory(str(alt_video), filename)
            return send_from_directory(str(_MEDIA_VIDEO), filename)

        @app.route("/api/video-message/download/<filename>")
        def download_video(filename: str):
            """Alias for video serving — used by video_messages app."""
            if (_MEDIA_VIDEO / filename).exists():
                return send_from_directory(str(_MEDIA_VIDEO), filename)
            alt_video = project_root / "content" / "media" / "video"
            if (alt_video / filename).exists():
                return send_from_directory(str(alt_video), filename)
            return send_from_directory(str(_MEDIA_VIDEO), filename)

        @app.route("/media/photo/<filename>")
        def serve_photo(filename: str):
            return send_from_directory(str(_MEDIA_PHOTO), filename)

        @app.route("/media/images/<filename>")
        def serve_image(filename: str):
            return send_from_directory(str(_MEDIA_IMAGES), filename)

        # ── Gallery API ───────────────────────────────────────────────────────
        @app.route("/api/gallery")
        def get_gallery():
            """Return all media (images + videos) from media directories."""
            try:
                images = []
                img_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
                vid_exts = (".mp4", ".webm", ".mov")
                # Images
                for media_dir, prefix in [(_MEDIA_PHOTO, "/media/photo/"), (_MEDIA_IMAGES, "/media/images/")]:
                    if media_dir.exists():
                        for f in sorted(media_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                            if f.is_file() and f.suffix.lower() in img_exts:
                                images.append({"id": f.name, "url": prefix + f.name, "name": f.stem,
                                               "type": "image", "created_at": f.stat().st_mtime})
                # Videos
                video_dirs = [_MEDIA_VIDEO]
                alt_video = project_root / "content" / "media" / "video"
                if alt_video.exists():
                    video_dirs.append(alt_video)
                seen = set()
                for vdir in video_dirs:
                    if vdir.exists():
                        for f in sorted(vdir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                            if f.is_file() and f.suffix.lower() in vid_exts and f.name not in seen and f.stat().st_size > 100:
                                seen.add(f.name)
                                images.append({"id": f.name, "url": "/media/video/" + f.name, "name": f.stem,
                                               "type": "video", "created_at": f.stat().st_mtime})
                # Sort all by date descending
                images.sort(key=lambda x: x.get("created_at", 0), reverse=True)
                return jsonify({"ok": True, "images": images})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/gallery/<filename>", methods=["DELETE"])
        def delete_gallery_image(filename: str):
            """Delete an image or video from the gallery."""
            try:
                search_dirs = [_MEDIA_PHOTO, _MEDIA_IMAGES, _MEDIA_VIDEO]
                alt_video = project_root / "content" / "media" / "video"
                if alt_video.exists():
                    search_dirs.append(alt_video)
                for media_dir in search_dirs:
                    target = media_dir / filename
                    if target.exists() and target.is_file():
                        target.unlink()
                        return jsonify({"ok": True})
                return jsonify({"ok": False, "error": "not found"}), 404
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Voice messages list ──────────────────────────────────────────────
        @app.route("/api/voice-messages")
        def get_voice_messages():
            """List all voice message files with metadata."""
            try:
                messages = []
                if _MEDIA_VOICE.exists():
                    for f in sorted(_MEDIA_VOICE.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                        if f.is_file() and f.suffix.lower() in (".mp3", ".wav", ".ogg", ".webm"):
                            messages.append({"filename": f.name, "sender": f.stem.split("_")[0] if "_" in f.stem else "Unknown", "created_at": f.stat().st_mtime, "duration": "0:00"})
                return jsonify({"ok": True, "messages": messages})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Video messages list ──────────────────────────────────────────────
        @app.route("/api/video-messages")
        def get_video_messages():
            """List all video message files with metadata."""
            try:
                messages = []
                # Check both media directories
                video_dirs = [_MEDIA_VIDEO]
                alt_video = project_root / "content" / "media" / "video"
                if alt_video.exists():
                    video_dirs.append(alt_video)
                for vdir in video_dirs:
                    if vdir.exists():
                        for f in sorted(vdir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                            if f.is_file() and f.suffix.lower() in (".mp4", ".webm", ".mov"):
                                messages.append({"filename": f.name, "sender": f.stem.split("_")[0] if "_" in f.stem else "Unknown", "created_at": f.stat().st_mtime})
                return jsonify({"ok": True, "messages": messages})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Voice Studio premade voices ──────────────────────────────────
        @app.route("/api/voice-studio/premade")
        def voice_studio_premade():
            """Return premade voice collection."""
            try:
                from content.scenes.phone.apps.voice_studio import PREMADE_VOICES
                voices = []
                for key, v in PREMADE_VOICES.items():
                    voices.append({"id": key, "name": v["name"], "description": v["description"],
                                   "model_size": v.get("model_size", "1.7b"), "tags": v.get("tags", [])})
                return jsonify({"ok": True, "voices": voices})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Arcade highscores ────────────────────────────────────────────────
        @app.route("/api/arcade/highscore", methods=["POST"])
        def arcade_highscore():
            """Submit an arcade game highscore to SharedBoardManager."""
            body = request.get_json(force=True, silent=True) or {}
            game = str(body.get("game", "")).strip()
            try:
                score = int(body.get("score", 0))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "score must be integer"}), 400
            if not game:
                return jsonify({"ok": False, "error": "game required"}), 400
            try:
                from engine.mcp.shared_boards import get_shared_boards
                boards = get_shared_boards()
                board_id = f"arcade_{game}"
                boards.submit_score(board_id, "player", score, metadata={"game": game, "scene": "phone"})
                return jsonify({"ok": True, "game": game, "score": score})
            except Exception as exc:
                logger.debug("Arcade highscore submit: %s", exc)
                return jsonify({"ok": True, "game": game, "score": score})

        # ── Image generation ─────────────────────────────────────────────────
        @app.route("/api/generate-image", methods=["POST"])
        def generate_image():
            """Generate an image via ComfyUI."""
            body = request.get_json(force=True, silent=True) or {}
            prompt = str(body.get("prompt", "")).strip()
            if not prompt:
                return jsonify({"ok": False, "error": "prompt required"}), 400
            try:
                from content.simulation.services.comfyui_client import get_comfyui_client
                comfy = get_comfyui_client()
                image_path = comfy.generate_image(prompt=prompt, character_name="user")
                if image_path:
                    filename = Path(image_path).name
                    return jsonify({"ok": True, "image_url": f"/media/images/{filename}"})
                return jsonify({"ok": False, "error": "Generation failed"}), 500
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Admin ─────────────────────────────────────────────────────────────
        @app.route("/api/admin/autotxt-mute", methods=["POST"])
        def autotxt_mute():
            """Toggle or set autonomous messaging mute."""
            try:
                data = request.get_json(force=True) if request.data else {}
                if "muted" in data:
                    self._autotxt_muted = bool(data["muted"])
                else:
                    self._autotxt_muted = not self._autotxt_muted
                return jsonify({"ok": True, "muted": self._autotxt_muted})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/admin/autotxt-mute")
        def autotxt_mute_status():
            return jsonify({"ok": True, "muted": self._autotxt_muted})

        @app.route("/api/admin/wipe-messages", methods=["POST"])
        def wipe_messages():
            try:
                count = self.phone_db.wipe_messages()
                # Wipe media files
                wiped_media = 0
                for _dir in [_MEDIA_VOICE, _MEDIA_VIDEO, _MEDIA_PHOTO, _MEDIA_IMAGES]:
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

        # ── News Feed API ─────────────────────────────────────────────
        @app.route("/api/news/feed")
        def news_feed():
            """Get curated news feed."""
            try:
                limit = int(request.args.get("limit", 30))
                offset = int(request.args.get("offset", 0))
                unread_only = request.args.get("unread", "").lower() == "true"
                items = self.phone_db.get_news_feed(
                    limit=limit, offset=offset, unread_only=unread_only,
                )
                stats = self.phone_db.get_news_stats()
                return jsonify({"ok": True, "items": items, "stats": stats})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/news/refresh", methods=["POST"])
        def news_refresh():
            """Pull latest news from Nexus into the phone feed."""
            try:
                count = self._sync_news_from_nexus()
                return jsonify({"ok": True, "synced": count})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/news/feedback", methods=["POST"])
        def news_feedback():
            """Submit feedback on a news item."""
            try:
                body = request.get_json(force=True, silent=True) or {}
                item_id = body.get("item_id", "") or body.get("id", "")
                action = body.get("action", "")
                feedback = body.get("feedback", "")

                if not item_id:
                    return jsonify({"ok": False, "error": "item_id required"}), 400

                if feedback == "up":
                    action = "thumbs_up"
                elif feedback == "down":
                    action = "thumbs_down"

                if not action:
                    return jsonify({"ok": False, "error": "action or feedback required"}), 400

                if action == "read":
                    self.phone_db.set_news_read(item_id)
                elif action == "delete":
                    self.phone_db.delete_news_item(item_id)
                elif action == "thumbs_up":
                    self.phone_db.set_news_feedback(item_id, 1)
                    self.phone_db.set_news_read(item_id)
                    self._record_news_feedback(item_id, 1)
                elif action == "thumbs_down":
                    self.phone_db.set_news_feedback(item_id, -1)
                    self.phone_db.set_news_read(item_id)
                    self._record_news_feedback(item_id, -1)
                else:
                    return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

                self._emit("news_updated", self.phone_db.get_news_stats())
                return jsonify({"ok": True, "action": action, "item_id": item_id})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/news/stats")
        def news_stats():
            """Get news feed statistics."""
            try:
                stats = self.phone_db.get_news_stats()
                feedback = self.phone_db.get_feedback_summary()
                return jsonify({"ok": True, "stats": stats, "feedback": feedback})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── World / Ghost integration ──────────────────────────────────

        @app.route("/api/world/incoming")
        def world_incoming():
            """Return world-triggered incoming messages for the phone scene."""
            return jsonify(self._get_incoming_world_messages())

        @app.route("/api/world/send_ghost", methods=["POST"])
        def world_send_ghost():
            """Send a tip to 0xGH0ST; store in Nexus and earn credits."""
            body = request.get_json(force=True, silent=True) or {}
            message = str(body.get("message", "")).strip()
            if not message:
                return jsonify({"ok": False, "error": "message required"}), 400
            try:
                from engine.nexus.client import get_nexus_client
                from engine.world.player_state import get_player_state
                client = get_nexus_client()
                client.add_entry(
                    title="ghost_outgoing",
                    content=message,
                    content_type="history",
                    category="phone_messages",
                    tags=["ghost", "phone", "outgoing"],
                )
                ps = get_player_state()
                new_balance = ps.earn_credits(50, "ghost_tip")
                state = ps.to_dict()
                return jsonify({
                    "ok": True,
                    "credits_earned": 50,
                    "balance": state["credits"],
                })
            except Exception as exc:
                logger.error("world_send_ghost failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── MCP Framework API ─────────────────────────────────────────
        @app.route("/api/mcp/status")
        def mcp_status():
            try:
                fw = get_framework()
                return jsonify({"ok": True, "status": fw.get_status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/agent-profiles")
        def mcp_agent_profiles():
            try:
                fw = get_framework()
                return jsonify({"ok": True, "profiles": fw.list_agent_profiles()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/event-log")
        def mcp_event_log():
            try:
                fw = get_framework()
                limit = int(request.args.get("limit", 50))
                event_type = request.args.get("type", "")
                return jsonify({"ok": True, "events": fw.get_event_log(event_type=event_type, limit=limit)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/timers")
        def mcp_timers():
            try:
                fw = get_framework()
                return jsonify({"ok": True, "timers": fw.list_timers()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/consequences")
        def mcp_consequences():
            try:
                fw = get_framework()
                return jsonify({"ok": True, "consequences": fw.get_pending_consequences(SCENE_ID)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/lmstudio")
        def mcp_lmstudio():
            try:
                from engine.lmstudio.model_manager import get_model_manager
                mm = get_model_manager()
                return jsonify({"ok": True, "config": mm.get_full_config(), "status": mm.status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/resources")
        def mcp_resources():
            try:
                from engine.lmstudio.resource_manager import get_resource_manager
                rm = get_resource_manager()
                return jsonify({"ok": True, "resources": rm.get_status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/resources/config", methods=["POST"])
        def mcp_resources_config():
            try:
                from engine.lmstudio.resource_manager import get_resource_manager
                rm = get_resource_manager()
                data = request.get_json(force=True)
                result = rm.update_config(**data)
                return jsonify({"ok": True, "resources": result})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/mcp/inference-defaults")
        def mcp_inference_defaults():
            try:
                from engine.lmstudio.inference_config import InferenceConfig
                defaults = InferenceConfig.from_yaml()
                return jsonify({"ok": True, "defaults": defaults.to_dict()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── System Dashboard Routes ──────────────────────────────────

        @app.route("/api/system/dashboard")
        def system_dashboard():
            """Aggregated system health for mobile dashboard."""
            try:
                fw = get_framework()
                status = fw.get_status() if hasattr(fw, "get_status") else {}

                # LMStudio status
                lms = {"online": False}
                try:
                    from engine.lmstudio.model_manager import get_model_manager
                    mm = get_model_manager()
                    lms = {"online": True, **mm.status()}
                except Exception:
                    pass

                # Nexus health
                nexus = {"online": False}
                try:
                    from engine.nexus.client import get_nexus_client
                    client = get_nexus_client()
                    health = client.health() if hasattr(client, "health") else {}
                    nexus = {"online": True, **(health if isinstance(health, dict) else {})}
                except Exception:
                    pass

                # Scheduler status
                scheduler = {"running": False}
                try:
                    from engine.nexus.scheduler_daemon import get_scheduler_daemon
                    sd = get_scheduler_daemon()
                    scheduler = sd.status()
                except Exception:
                    pass

                # Scene registry
                scenes = []
                try:
                    from engine.scenes.scene_registry import get_scene_registry
                    reg = get_scene_registry()
                    scenes = reg.list_scenes() if hasattr(reg, "list_scenes") else []
                except Exception:
                    pass

                # Agent profiles
                agents = []
                try:
                    agents = fw.list_agent_profiles() if hasattr(fw, "list_agent_profiles") else []
                except Exception:
                    pass

                # Meta metrics summary
                metrics = {}
                try:
                    from engine.nexus.meta_metrics import get_meta_metrics
                    mm_inst = get_meta_metrics()
                    metrics = mm_inst.latest_snapshot() if hasattr(mm_inst, "latest_snapshot") else {}
                except Exception:
                    pass

                return jsonify({
                    "ok": True,
                    "mcp": status,
                    "lmstudio": lms,
                    "nexus": nexus,
                    "scheduler": scheduler,
                    "scenes": scenes,
                    "agents": agents,
                    "metrics": metrics,
                })
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/system/chat", methods=["POST"])
        def system_chat():
            """Chat with the phone assistant (cascading through all tiers)."""
            try:
                data = request.get_json(force=True)
                message = data.get("message", "").strip()
                if not message:
                    return jsonify({"ok": False, "error": "No message"}), 400

                voice = data.get("voice", False)
                mode = data.get("mode")

                from engine.assistant.phone_assistant import get_phone_assistant
                pa = get_phone_assistant()
                result = pa.chat(message, mode=mode, voice=voice)
                return jsonify({"ok": True, **result})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/system/assistant/mode", methods=["GET", "POST"])
        def system_assistant_mode():
            """Get or set the phone assistant routing mode."""
            try:
                from engine.assistant.phone_assistant import get_phone_assistant
                pa = get_phone_assistant()
                if request.method == "POST":
                    data = request.get_json(force=True)
                    mode = pa.set_mode(data.get("mode", "auto"))
                    return jsonify({"ok": True, "mode": mode})
                return jsonify({"ok": True, "mode": pa.get_mode()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/system/assistant/status")
        def system_assistant_status():
            """Get phone assistant status including connectivity."""
            try:
                from engine.assistant.phone_assistant import get_phone_assistant
                return jsonify({"ok": True, **get_phone_assistant().status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/system/assistant/history")
        def system_assistant_history():
            """Get phone assistant conversation history."""
            try:
                from engine.assistant.phone_assistant import get_phone_assistant
                limit = int(request.args.get("limit", 20))
                return jsonify({"ok": True, "history": get_phone_assistant().get_history(limit)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/system/scheduler/tasks")
        def system_scheduler_tasks():
            """Get scheduler task list and status."""
            try:
                from engine.nexus.scheduler_daemon import get_scheduler_daemon
                sd = get_scheduler_daemon()
                tasks = sd.list_tasks() if hasattr(sd, "list_tasks") else []
                return jsonify({"ok": True, "tasks": tasks})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/system/nexus/recent")
        def system_nexus_recent():
            """Get recent Nexus entries for the dashboard."""
            try:
                from engine.nexus.client import get_nexus_client
                client = get_nexus_client()
                limit = int(request.args.get("limit", 10))
                results = client.search("*", limit=limit)
                return jsonify({"ok": True, "entries": results or []})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Hacker App Routes ────────────────────────────────────────

        @app.route("/api/hacker/targets")
        def hacker_targets():
            """List all characters with their current state summary."""
            targets = []
            try:
                from engine.mcp.state_coordinator import get_coordinator
                coord = get_coordinator()
                for char_id in (self.active_characters or {}):
                    state = coord.get_full_state(char_id) or {}
                    targets.append({
                        "id": char_id,
                        "name": char_id.replace("_", " ").title(),
                        "mood": state.get("mood", "unknown"),
                        "energy": state.get("energy", 50),
                        "arousal": state.get("arousal", 50),
                        "relationship": state.get("relationship", 50),
                        "scene": state.get("scene", "phone"),
                    })
            except Exception:
                for char_id in (self.active_characters or {}):
                    targets.append({"id": char_id, "name": char_id.replace("_", " ").title(),
                                    "mood": "unknown", "energy": 50, "arousal": 50,
                                    "relationship": 50, "scene": "phone"})
            return jsonify({"ok": True, "targets": targets})

        @app.route("/api/hacker/<char_id>/profile")
        def hacker_profile(char_id):
            """Get full character state, personality, and system data."""
            result = {"id": char_id}
            try:
                from engine.mcp.state_coordinator import get_coordinator
                result["state"] = get_coordinator().get_full_state(char_id) or {}
            except Exception:
                result["state"] = {}
            try:
                from content.simulation.database.db import Database
                db = Database()
                char = db.get_character(char_id)
                if char:
                    result["personality"] = {
                        "backstory": getattr(char, "backstory", ""),
                        "traits": getattr(char, "traits", []),
                        "speech_patterns": getattr(char, "speech_patterns", []),
                        "quirks": getattr(char, "quirks", []),
                        "interests": getattr(char, "interests", []),
                    }
            except Exception:
                result["personality"] = {}
            try:
                from engine.mcp.scene_rules_engine import get_conversation_heat
                heat = get_conversation_heat()
                heat_val = heat.get(f"phone_{char_id}") if hasattr(heat, "get") else 0
                result["heat"] = heat_val or 0
            except Exception:
                result["heat"] = 0
            return jsonify({"ok": True, "profile": result})

        @app.route("/api/hacker/<char_id>/messages")
        def hacker_messages(char_id):
            """Get all messages from a character's DM thread."""
            limit = request.args.get("limit", 100, type=int)
            try:
                thread = self.db.get_or_create_dm(char_id)
                messages = self.db.get_messages(thread["id"], limit=limit)
                return jsonify({"ok": True, "thread_id": thread["id"], "messages": messages})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/hacker/<char_id>/intercept", methods=["POST"])
        def hacker_intercept(char_id):
            """Inject a system-level directive into a character's state."""
            data = request.get_json(silent=True) or {}
            directive = data.get("directive", "")
            if not directive:
                return jsonify({"ok": False, "error": "directive required"}), 400
            try:
                from engine.mcp.state_coordinator import get_coordinator
                coord = get_coordinator()
                state = coord.get_full_state(char_id) or {}
                coord.update(char_id, mood=state.get("mood", "neutral"),
                             source="hacker_inject", scene="phone",
                             metadata={"injected_directive": directive})
                return jsonify({"ok": True, "injected": directive})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Research (NotebookLM) routes ─────────────────────────────────────
        from engine.skills.builtin.notebooklm_skills import (
            notebooklm_ask,
            notebooklm_add_source,
            notebooklm_generate_audio,
            notebooklm_list_notebooks,
        )

        @app.route("/api/research/search", methods=["POST"])
        def research_search():
            data = request.get_json(silent=True) or {}
            question = data.get("question", "")
            notebook_id = data.get("notebook_id", "")
            if not question:
                return jsonify({"ok": False, "error": "question required"}), 400
            try:
                import json as _json
                result = _json.loads(notebooklm_ask(question, notebook_id=notebook_id))
                result["ok"] = True
                return jsonify(result)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/research/add_source", methods=["POST"])
        def research_add_source():
            data = request.get_json(silent=True) or {}
            notebook_id = data.get("notebook_id", "")
            source_type = data.get("source_type", "url")
            source_value = data.get("source_value", "")
            if not notebook_id or not source_value:
                return jsonify({"ok": False, "error": "notebook_id and source_value required"}), 400
            try:
                import json as _json
                result = _json.loads(notebooklm_add_source(notebook_id, source_type=source_type, source_value=source_value))
                result["ok"] = True
                return jsonify(result)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/research/audio", methods=["POST"])
        def research_audio():
            data = request.get_json(silent=True) or {}
            notebook_id = data.get("notebook_id", "")
            customization = data.get("customization", "")
            if not notebook_id:
                return jsonify({"ok": False, "error": "notebook_id required"}), 400
            try:
                import json as _json
                result = _json.loads(notebooklm_generate_audio(notebook_id, customization=customization))
                result["ok"] = True
                return jsonify(result)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/research/notebooks")
        def research_notebooks():
            try:
                import json as _json
                notebooks = _json.loads(notebooklm_list_notebooks())
                return jsonify({"ok": True, "notebooks": notebooks})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.route("/api/economy")
        def api_economy():
            """Return current economy state for this scene."""
            try:
                from engine.economy.economy import get_economy_manager
                em = get_economy_manager()
                player_id = request.args.get("player_id", "player")
                return jsonify({
                    "scene": "phone",
                    "balance": em.get_balance(player_id),
                    "debt": em.check_debt(player_id),
                    "recent_transactions": [t.to_dict() for t in em.get_history(player_id, limit=10)],
                })
            except Exception as exc:
                logger.error("Economy API error: %s", exc)
                return jsonify({"error": str(exc)}), 500


        @app.route("/api/news/feed")
        def api_phone_news_feed():
            category = request.args.get("category", "ai_research")
            limit = min(int(request.args.get("limit", 10)), 20)
            try:
                from engine.nexus.client import get_nexus_client
                client = get_nexus_client()
                results = client.search(f"{category} news", category="news", limit=limit)
                formatted = []
                for r in results:
                    formatted.append({
                        "sender": "NEXUS FEED",
                        "message": f"**{r.get('title', 'News')}**\n{r.get('content', '')[:250]}",
                        "category": category,
                        "timestamp": r.get("created_at", ""),
                    })
                return jsonify({"status": "ok", "messages": formatted})
            except Exception as e:
                return jsonify({"status": "error", "messages": [], "error": str(e)})


# ── Module entry point ────────────────────────────────────────────────────────

def create_app(host: str = "0.0.0.0", port: int = 5555) -> PhoneSceneV2:
    """Factory used by the scene manager / launcher."""
    scene = PhoneSceneV2(host=host, port=port)
    return scene


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scene = create_app()
    scene.start()
