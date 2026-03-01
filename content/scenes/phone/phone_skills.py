"""
Phone Skills — MCP skill functions for the SIGNAL scene (v0.68 Dark Renaissance).

Exposes contact management, ghost-story progression, and investigation-board
clue tracking as ``@skill``-decorated callables for LMS agent tool use.
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ── Scene accessor ────────────────────────────────────────────────────────────

def _get_phone_scene():
    """Return the active NeonPhone scene instance, or None."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("phone")


# ── Skills ────────────────────────────────────────────────────────────────────

@skill(
    pack="phone",
    tags=["game", "phone", "contacts"],
    category=SkillCategory.GAME,
    description="Get all phone contacts and their status",
)
def get_phone_contacts() -> str:
    """Return a formatted list of all SIGNAL contacts with status and unread counts.

    Returns:
        JSON string with contact list, or error message.
    """
    scene = _get_phone_scene()
    if not scene:
        return "SIGNAL scene not active."
    try:
        contacts = []
        for cid, data in scene._threads.items():
            from content.scenes.phone.neon_phone import _CONTACTS
            contact_meta = _CONTACTS.get(cid, {})
            unread = sum(
                1 for m in data
                if m.get("from") == cid and not m.get("read")
            )
            contacts.append({
                "id": cid,
                "name": contact_meta.get("name", cid.upper()),
                "status": contact_meta.get("status", "unknown"),
                "unread": unread,
                "message_count": len(data),
            })
        return json.dumps({"contacts": contacts, "total": len(contacts)}, indent=2)
    except Exception as exc:
        logger.error("get_phone_contacts failed: %s", exc)
        return f"Failed to retrieve contacts: {exc}"


@skill(
    pack="phone",
    tags=["game", "phone", "messaging"],
    category=SkillCategory.GAME,
    description="Send a message to a phone contact",
)
def send_phone_message(contact_id: str = "", message: str = "") -> str:
    """Send a text message to a named SIGNAL contact.

    Args:
        contact_id: Target contact ID (e.g. ``"lola"``, ``"0xgh0st"``).
        message: Message text to send.

    Returns:
        Confirmation string or error message.
    """
    if not contact_id or not message:
        return "Provide both contact_id and message."
    scene = _get_phone_scene()
    if not scene:
        return "SIGNAL scene not active."
    try:
        from content.scenes.phone.neon_phone import _CONTACTS
        if contact_id not in _CONTACTS:
            available = ", ".join(_CONTACTS.keys())
            return f"Unknown contact '{contact_id}'. Available: {available}"
        import uuid
        from datetime import datetime, timezone

        msg = {
            "id": str(uuid.uuid4())[:8],
            "from": "user",
            "text": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": True,
        }
        with scene._lock:
            scene._threads[contact_id].append(msg)

        # Trigger async AI reply
        import threading
        threading.Thread(
            target=scene._generate_ai_reply,
            args=(contact_id, message),
            daemon=True,
        ).start()

        preview = message[:50] + "…" if len(message) > 50 else message
        return f"Message sent to {contact_id.upper()}: \"{preview}\""
    except Exception as exc:
        logger.error("send_phone_message failed: %s", exc)
        return f"Failed to send message: {exc}"


@skill(
    pack="phone",
    tags=["game", "phone", "mystery", "ghost"],
    category=SkillCategory.GAME,
    description="Get the current 0xGH0ST story progress",
)
def get_ghost_story_progress() -> str:
    """Return the current stage and clue summary for the 0xGH0ST mystery arc.

    Returns:
        JSON string with stage number, title, clue, and message count.
    """
    scene = _get_phone_scene()
    if not scene:
        return "SIGNAL scene not active."
    try:
        from content.scenes.phone.neon_phone import _GHOST_STAGES
        stage = scene._current_ghost_stage()
        stage_data = _GHOST_STAGES[min(stage, len(_GHOST_STAGES) - 1)]
        return json.dumps({
            "stage": stage,
            "title": stage_data["title"],
            "clue": stage_data["clue"],
            "messages_exchanged": scene._ghost_message_count,
            "next_stage_at": (
                _GHOST_STAGES[stage + 1]["trigger_count"]
                if stage + 1 < len(_GHOST_STAGES) else None
            ),
        }, indent=2)
    except Exception as exc:
        logger.error("get_ghost_story_progress failed: %s", exc)
        return f"Failed to retrieve ghost progress: {exc}"


@skill(
    pack="phone",
    tags=["game", "phone", "investigation", "ghost"],
    category=SkillCategory.GAME,
    description="Add a clue to the investigation board from a message",
)
def add_message_clue(message_id: str = "", description: str = "") -> str:
    """Pin a message as evidence on the 0xGH0ST investigation board.

    Args:
        message_id: Short ID of the message to reference as evidence.
        description: Human-readable clue description to add to the board.

    Returns:
        Confirmation string with the new clue ID, or error message.
    """
    if not description:
        return "Provide a clue description."
    try:
        from engine.mechanics.investigation import (
            get_investigation_board,
            BOARD_HACKER,
            ClueType,
        )
        board = get_investigation_board(BOARD_HACKER, scene="phone")
        clue = board.add_clue(
            title=f"MSG_{message_id.upper()}" if message_id else "MESSAGE_CLUE",
            content=description,
            clue_type=ClueType.MESSAGE,
            importance=0.6,
            tags=["phone", "signal", "message"],
            revealed=True,
        )
        return f"Clue added to investigation board: {clue.id} — \"{description[:60]}\""
    except Exception as exc:
        logger.error("add_message_clue failed: %s", exc)
        return f"Failed to add clue: {exc}"


@skill(
    pack="phone",
    tags=["game", "phone", "ghost", "mystery"],
    category=SkillCategory.GAME,
    description="Check if 0xGH0ST has new encoded messages",
)
def check_ghost_messages() -> str:
    """Check the 0xGH0ST thread for unread messages and return a summary.

    Returns:
        Formatted string showing unread count and message previews.
    """
    scene = _get_phone_scene()
    if not scene:
        return "SIGNAL scene not active."
    try:
        with scene._lock:
            thread = list(scene._threads.get("0xgh0st", []))

        unread = [m for m in thread if m.get("from") == "0xgh0st" and not m.get("read")]
        if not unread:
            return "No new messages from 0xGH0ST."

        lines = [f"0xGH0ST — {len(unread)} unread message(s):"]
        for msg in unread[-5:]:
            ts = msg.get("timestamp", "")[:19].replace("T", " ")
            preview = msg["text"][:70] + "…" if len(msg["text"]) > 70 else msg["text"]
            lines.append(f"  [{ts}] {preview}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("check_ghost_messages failed: %s", exc)
        return f"Failed to check ghost messages: {exc}"


def _get_phone_scene():
    """Look up the running Phone scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("phone")


def _get_phone_db():
    """Get the phone database from the active scene."""
    scene = _get_phone_scene()
    if not scene:
        return None
    return getattr(scene, "_phone_db", None)


# ── Messaging ──────────────────────────────────────────────────

@skill(
    pack="phone",
    tags=["social", "phone", "messaging"],
    category=SkillCategory.SOCIAL,
    description="Send a text message to a character.",
)
def phone_send_message(character_id: str = "", message: str = "") -> str:
    """Send a text message to a character's DM thread."""
    if not character_id or not message:
        return "Specify character_id and message."
    scene = _get_phone_scene()
    if not scene:
        return "Phone not active."
    db = _get_phone_db()
    if not db:
        return "Phone database not available."
    try:
        thread = db.get_or_create_dm(character_id)
        thread_id = thread["id"] if isinstance(thread, dict) else thread
        saved = db.save_message(
            thread_id=thread_id,
            sender_id="system",
            content=message,
            msg_type="text",
        )
        # Emit socket event if scene has socketio
        sio = getattr(scene, "sio", None)
        if sio:
            sio.emit("message_new", {
                "thread_id": thread_id,
                "message": saved,
            })
        preview = message[:50] + "..." if len(message) > 50 else message
        return f"Message sent to {character_id}: '{preview}'"
    except Exception as e:
        logger.error("phone_send_message failed: %s", e)
        return f"Failed to send message: {e}"


@skill(
    pack="phone",
    tags=["social", "phone", "messaging"],
    category=SkillCategory.SOCIAL,
    description="Check message threads and unread counts.",
)
def phone_check_messages() -> str:
    """Get a summary of message threads and unread messages."""
    db = _get_phone_db()
    if not db:
        return "Phone not active."
    try:
        threads = db.list_threads()
        if not threads:
            return "No message threads."
        total_unread = db.total_unread()
        lines = [f"{len(threads)} threads ({total_unread} total unread):"]
        for t in threads[:8]:
            name = t.get("character_id", t.get("name", "unknown"))
            unread = t.get("unread", 0)
            last = t.get("last_message", "")
            preview = last[:30] + "..." if len(last) > 30 else last
            marker = " 🔴" if unread > 0 else ""
            lines.append(f"  {name}: {unread} unread{marker} — {preview}")
        return "\n".join(lines)
    except Exception as e:
        logger.error("phone_check_messages failed: %s", e)
        return "Could not read messages."


# ── Games ──────────────────────────────────────────────────────

@skill(
    pack="phone",
    tags=["game", "phone", "arcade"],
    category=SkillCategory.GAME,
    description="Start an arcade game on the phone.",
    cooldown=10,
)
def phone_start_game(game_type: str = "trivia", character_id: str = "") -> str:
    """Start a phone game: trivia, would_you_rather, truth_or_dare, story_chain."""
    valid = ["trivia", "would_you_rather", "truth_or_dare", "story_chain"]
    if game_type not in valid:
        return f"Unknown game. Available: {', '.join(valid)}"
    scene = _get_phone_scene()
    if not scene:
        return "Phone not active."
    db = _get_phone_db()
    if not db:
        return "Phone database not available."
    try:
        char_id = character_id or "system"
        thread = db.get_or_create_dm(char_id) if char_id != "system" else {"id": "system"}
        thread_id = thread["id"] if isinstance(thread, dict) else thread
        session_id = db.create_game_session(
            thread_id=thread_id,
            char_id=char_id,
            session_type=game_type,
        )
        # Emit game event
        sio = getattr(scene, "sio", None)
        if sio:
            sio.emit("game_event", {
                "event": "game_started",
                "game_type": game_type,
                "session_id": session_id,
                "thread_id": thread_id,
            })
        return f"Started {game_type.replace('_', ' ').title()} game (session {session_id}) with {char_id}."
    except Exception as e:
        logger.error("phone_start_game failed: %s", e)
        return f"Failed to start game: {e}"


@skill(
    pack="phone",
    tags=["game", "phone", "arcade"],
    category=SkillCategory.GAME,
    description="Submit an action in the current phone game.",
)
def phone_game_action(action: str = "", thread_id: str = "") -> str:
    """Submit a game action (answer, choice, dare, etc)."""
    if not action:
        return "What's your move?"
    db = _get_phone_db()
    if not db:
        return "Phone not active."
    try:
        # Find active game session
        session = None
        if thread_id:
            session = db.get_game_session(thread_id)
        if not session:
            return "No active game session. Start one first."
        session_id = session.get("id", session.get("session_id", ""))
        state = session.get("state", {})
        if isinstance(state, str):
            import json
            try:
                state = json.loads(state)
            except (json.JSONDecodeError, TypeError):
                state = {}
        # Track action in state history
        history = state.get("history", [])
        history.append({"action": action, "round": state.get("round", 0)})
        state["history"] = history
        state["round"] = state.get("round", 0) + 1
        state["last_action"] = action
        db.update_game_state(session_id, state)
        return f"Action recorded: '{action}' (round {state['round']})"
    except Exception as e:
        logger.error("phone_game_action failed: %s", e)
        return f"Game action failed: {e}"


# ── Media ──────────────────────────────────────────────────────

@skill(
    pack="phone",
    tags=["media", "phone"],
    category=SkillCategory.SYSTEM,
    description="Generate an AI image and save to gallery.",
    cooldown=15,
)
def phone_generate_image(prompt: str = "") -> str:
    """Generate an image using AI and save to the phone gallery."""
    if not prompt:
        return "Describe the image you want to generate."
    scene = _get_phone_scene()
    if not scene:
        return "Phone not active."
    try:
        # Use ComfyUI if available
        comfy = getattr(scene, "_comfy", None) or getattr(scene, "comfy", None)
        if comfy and hasattr(comfy, "generate_image"):
            result = comfy.generate_image(prompt)
            if result:
                path = result if isinstance(result, str) else result.get("path", "")
                # Save as photo message if we have a db
                db = _get_phone_db()
                if db and path:
                    thread = db.get_or_create_dm("gallery")
                    thread_id = thread["id"] if isinstance(thread, dict) else thread
                    db.save_message(
                        thread_id=thread_id,
                        sender_id="system",
                        content=f"Generated: {prompt[:60]}",
                        msg_type="photo",
                        metadata={"image_path": path, "generated": True, "prompt": prompt},
                    )
                return f"Image generated: '{prompt[:60]}' → {path}"
            return f"Image generation queued: '{prompt[:60]}'"
        return f"Image generation requested: '{prompt[:80]}' (ComfyUI not connected)"
    except Exception as e:
        logger.error("phone_generate_image failed: %s", e)
        return f"Image generation failed: {e}"


@skill(
    pack="phone",
    tags=["social", "phone"],
    category=SkillCategory.SOCIAL,
    description="Mute or unmute auto-text messages from characters.",
)
def phone_toggle_autotxt(mute: bool = True) -> str:
    """Toggle automatic text messages from characters."""
    scene = _get_phone_scene()
    if not scene:
        return "Phone not active."
    try:
        scene._autotxt_muted = mute
        sio = getattr(scene, "sio", None)
        if sio:
            sio.emit("autotxt_status", {"muted": mute})
        return f"Auto-texts {'muted ⏸️' if mute else 'unmuted ▶️'}."
    except Exception as e:
        logger.error("phone_toggle_autotxt failed: %s", e)
        return f"Auto-texts {'muted' if mute else 'unmuted'}."
