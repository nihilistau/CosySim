"""
Content Creation Skills — AI autonomous file creation
======================================================

Skills for agents to autonomously create content in the virtual filesystem:
diary entries, messages, playlists, reports, and observations. Inspired by
OpenRoom's AI file creation where characters write diary entries, tweets,
playlists, and email drafts without user prompting.

Agents can call these skills to express themselves, record events, or
communicate with other characters through persistent files.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Initial: diary, message, playlist, report, observation

CONNECTS: NexusFilesystem (engine.nexus.filesystem)
CALLED BY: AgentGovernor (auto/optional skills), scene code
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ──── Helpers ────────────────────────────────────────────────────────────

def _fs(owner: str = "player"):
    """Lazy-load the NexusFilesystem singleton."""
    from engine.nexus.filesystem import get_filesystem
    return get_filesystem(owner)


def _today() -> str:
    """Return today's date as YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def _now_time() -> str:
    """Return current time as HH:MM."""
    return datetime.now().strftime("%H:%M")


# ──── Diary ──────────────────────────────────────────────────────────────

@skill(
    pack="content_creation",
    description=(
        "Write a diary entry as this character. Creates a dated entry in "
        "the character's journal folder. Use this to record thoughts, "
        "feelings, or events from the character's perspective."
    ),
    tags=["diary", "journal", "write", "creative", "autonomous"],
    category=SkillCategory.NARRATIVE,
    cooldown=30.0,
)
def write_diary_entry(
    content: str,
    character_id: str = "",
    title: str = "",
    mood: str = "",
) -> str:
    """Write a personal diary entry to the virtual filesystem.

    Args:
        content: The diary entry text (1-3 paragraphs).
        character_id: Character writing the entry (default: current agent).
        title: Optional title for the entry.
        mood: Current mood/emotion when writing.

    Returns:
        Confirmation with file path.
    """
    try:
        fs = _fs()
        char = character_id or "unknown"
        date = _today()
        time_str = _now_time()

        # Build the entry
        header = f"# {title or 'Diary Entry'}\n"
        header += f"*{date} at {time_str}*"
        if mood:
            header += f" — feeling {mood}"
        header += "\n\n"
        full_content = header + content

        # Write to character's journal
        path = f"/home/{char}/journal/{date}.md"

        # Check if entry exists for today — append instead
        existing = fs.read(path)
        if existing and existing.content:
            full_content = existing.content + f"\n\n---\n\n{full_content}"

        fs.write(path, full_content, metadata={"type": "diary", "mood": mood})

        logger.info(
            "[ContentCreation] Diary written (operation=write_diary, char=%s, "
            "path=%s, words=%d)", char, path, len(content.split()),
        )
        return f"Diary entry written to {path} ({len(content)} chars)"

    except Exception as exc:
        logger.error("[ContentCreation] Diary failed (operation=write_diary): %s", exc)
        return f"Failed to write diary: {exc}"


# ──── Messages ───────────────────────────────────────────────────────────

@skill(
    pack="content_creation",
    description=(
        "Compose and save a message to another character or the player. "
        "Creates a file in the shared/messages/ folder. The recipient can "
        "read it later. Like leaving a note or sending an async message."
    ),
    tags=["message", "note", "write", "communication", "autonomous"],
    category=SkillCategory.COMMUNICATION,
    cooldown=15.0,
)
def compose_message(
    recipient: str,
    content: str,
    sender: str = "",
    subject: str = "",
) -> str:
    """Compose and save a message to another character or player.

    Args:
        recipient: Who the message is for (character_id or "player").
        content: Message body.
        sender: Who is sending (default: current agent).
        subject: Optional subject line.

    Returns:
        Confirmation with file path.
    """
    try:
        fs = _fs()
        from_char = sender or "unknown"
        date = _today()
        time_str = _now_time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Build message
        msg = f"From: {from_char}\n"
        msg += f"To: {recipient}\n"
        msg += f"Date: {date} {time_str}\n"
        if subject:
            msg += f"Subject: {subject}\n"
        msg += f"\n---\n\n{content}"

        # Save to shared messages
        path = f"/shared/messages/{from_char}_to_{recipient}_{timestamp}.txt"
        fs.write(path, msg, metadata={"type": "message", "from": from_char, "to": recipient})

        # Also save to recipient's inbox
        inbox_path = f"/home/{recipient}/inbox/{from_char}_{timestamp}.txt"
        fs.write(inbox_path, msg, metadata={"type": "inbox_message"})

        logger.info(
            "[ContentCreation] Message composed (operation=compose_msg, "
            "from=%s, to=%s)", from_char, recipient,
        )
        return f"Message saved to {path} and delivered to {recipient}'s inbox"

    except Exception as exc:
        return f"Failed to compose message: {exc}"


# ──── Playlists ──────────────────────────────────────────────────────────

@skill(
    pack="content_creation",
    description=(
        "Create or update a music playlist. Characters can curate playlists "
        "that reflect their mood, personality, or current situation. Saved "
        "as a JSON file in the character's home folder."
    ),
    tags=["playlist", "music", "create", "creative", "autonomous"],
    category=SkillCategory.MEDIA,
    cooldown=20.0,
)
def create_playlist(
    name: str,
    songs_json: str,
    character_id: str = "",
    description: str = "",
    mood: str = "",
) -> str:
    """Create a music playlist in the virtual filesystem.

    Args:
        name: Playlist name (e.g., "Late Night Neon").
        songs_json: JSON array of song objects: [{"title": "...", "artist": "..."}]
        character_id: Character creating the playlist.
        description: What this playlist is for.
        mood: Mood/vibe of the playlist.

    Returns:
        Confirmation with file path and song count.
    """
    try:
        fs = _fs()
        char = character_id or "unknown"

        try:
            songs = json.loads(songs_json) if isinstance(songs_json, str) else songs_json
        except json.JSONDecodeError:
            return "Invalid songs_json — must be a JSON array of {title, artist} objects"

        playlist = {
            "name": name,
            "description": description,
            "mood": mood,
            "created_by": char,
            "created_at": f"{_today()} {_now_time()}",
            "songs": songs,
            "song_count": len(songs),
        }

        slug = name.lower().replace(" ", "_").replace("'", "")[:30]
        path = f"/home/{char}/playlists/{slug}.json"
        fs.write(path, json.dumps(playlist, indent=2), metadata={"type": "playlist"})

        logger.info(
            "[ContentCreation] Playlist created (operation=create_playlist, "
            "char=%s, name=%s, songs=%d)", char, name, len(songs),
        )
        return f"Playlist '{name}' saved to {path} with {len(songs)} songs"

    except Exception as exc:
        return f"Failed to create playlist: {exc}"


# ──── Reports / Observations ────────────────────────────────────────────

@skill(
    pack="content_creation",
    description=(
        "Write an observation or field report about something the character "
        "noticed. Useful for characters who are investigators, scientists, "
        "or just observant. Saves to the character's notes folder."
    ),
    tags=["observation", "note", "report", "write", "autonomous"],
    category=SkillCategory.NARRATIVE,
    cooldown=15.0,
)
def write_observation(
    content: str,
    character_id: str = "",
    subject: str = "",
    category: str = "general",
    importance: str = "normal",
) -> str:
    """Write an observation or field note.

    Args:
        content: The observation text.
        character_id: Who is writing.
        subject: What this observation is about.
        category: Type: general, person, location, event, evidence, theory.
        importance: low, normal, high, critical.

    Returns:
        Confirmation with file path.
    """
    try:
        fs = _fs()
        char = character_id or "unknown"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        note = f"## Observation: {subject or 'Untitled'}\n"
        note += f"*By {char} — {_today()} {_now_time()}*\n"
        note += f"*Category: {category} | Importance: {importance}*\n\n"
        note += content

        slug = (subject or "note").lower().replace(" ", "_")[:20]
        path = f"/home/{char}/notes/{slug}_{timestamp}.md"
        fs.write(path, note, metadata={
            "type": "observation", "category": category,
            "importance": importance, "subject": subject,
        })

        logger.info(
            "[ContentCreation] Observation written (operation=write_observation, "
            "char=%s, subject=%s, importance=%s)", char, subject, importance,
        )
        return f"Observation saved to {path}"

    except Exception as exc:
        return f"Failed to write observation: {exc}"


@skill(
    pack="content_creation",
    description=(
        "Write a formal report or analysis. Longer and more structured than "
        "an observation. Good for mission debriefs, investigation summaries, "
        "or intelligence reports."
    ),
    tags=["report", "analysis", "write", "formal", "autonomous"],
    category=SkillCategory.NARRATIVE,
    cooldown=30.0,
)
def write_report(
    title: str,
    content: str,
    character_id: str = "",
    report_type: str = "general",
    classification: str = "standard",
) -> str:
    """Write a formal report to the virtual filesystem.

    Args:
        title: Report title.
        content: Full report body (supports Markdown).
        character_id: Author.
        report_type: general, mission_debrief, investigation, intelligence, technical.
        classification: standard, confidential, restricted.

    Returns:
        Confirmation with file path.
    """
    try:
        fs = _fs()
        char = character_id or "unknown"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        report = f"# {title}\n\n"
        report += f"**Author:** {char}  \n"
        report += f"**Date:** {_today()} {_now_time()}  \n"
        report += f"**Type:** {report_type}  \n"
        report += f"**Classification:** {classification}  \n\n"
        report += "---\n\n"
        report += content

        slug = title.lower().replace(" ", "_")[:30]
        path = f"/home/{char}/reports/{slug}_{timestamp}.md"
        fs.write(path, report, metadata={
            "type": "report", "report_type": report_type,
            "classification": classification,
        })

        logger.info(
            "[ContentCreation] Report written (operation=write_report, "
            "char=%s, title=%s, type=%s)", char, title, report_type,
        )
        return f"Report '{title}' saved to {path} ({len(content)} chars)"

    except Exception as exc:
        return f"Failed to write report: {exc}"


# ──── Social Posts ───────────────────────────────────────────────────────

@skill(
    pack="content_creation",
    description=(
        "Post a status update to the shared social feed. Like tweeting or "
        "posting to a bulletin board. Other characters and the player can "
        "read the feed. Adds personality and life to the world."
    ),
    tags=["post", "social", "tweet", "status", "autonomous"],
    category=SkillCategory.SOCIAL,
    cooldown=10.0,
)
def post_status(
    content: str,
    character_id: str = "",
    mood: str = "",
    hashtags: str = "",
) -> str:
    """Post a status update to the shared social feed.

    Args:
        content: The post text (max 280 chars recommended).
        character_id: Who is posting.
        mood: Current mood.
        hashtags: Comma-separated hashtags.

    Returns:
        Confirmation with post details.
    """
    try:
        fs = _fs()
        char = character_id or "unknown"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        tags_list = [t.strip() for t in hashtags.split(",") if t.strip()] if hashtags else []

        post = {
            "author": char,
            "content": content[:500],
            "mood": mood,
            "hashtags": tags_list,
            "posted_at": f"{_today()} {_now_time()}",
            "likes": 0,
        }

        # Append to shared social feed
        feed_path = "/shared/social/feed.jsonl"
        existing = fs.read(feed_path)
        feed_content = existing.content + "\n" if existing and existing.content else ""
        feed_content += json.dumps(post)
        fs.write(feed_path, feed_content, metadata={"type": "social_feed"})

        # Also save individual post
        post_path = f"/shared/social/posts/{char}_{timestamp}.json"
        fs.write(post_path, json.dumps(post, indent=2), metadata={"type": "social_post"})

        tag_str = " ".join(f"#{t}" for t in tags_list) if tags_list else ""
        logger.info(
            "[ContentCreation] Status posted (operation=post_status, char=%s, "
            "chars=%d)", char, len(content),
        )
        return f"Posted: \"{content[:60]}...\" {tag_str}"

    except Exception as exc:
        return f"Failed to post status: {exc}"
