"""
Phone Skills — MCP skill functions for the CosyPhone scene.

Exposes messaging, media, games, and social interactions as @skill-decorated
functions callable by LMS agents via tool use.
"""
from __future__ import annotations

import logging
import threading

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


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
