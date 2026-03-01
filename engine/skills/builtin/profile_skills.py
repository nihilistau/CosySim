"""profile_skills.py — MCP skills for conversation analysis, user profile, and backups.

Exposes the ConversationAnalyzer, UserProfileStore, and BackupManager to
LLM agents and the MCP tool surface:

  analyze_conversation()         — extract structured facts from text
  analyze_recent_conversation()  — analyze last session automatically
  user_profile_get()             — return full user profile
  user_profile_update()          — merge data into profile
  user_profile_add_fact()        — add a single fact
  user_profile_facts()           — list all known facts
  user_profile_context()         — compact markdown context summary
  backup_run()                   — run a full database backup cycle
  backup_list()                  — list all backup files with metadata
  backup_restore()               — restore a backup to a target path
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ──── Lazy Getters ─────────────────────────────────────────────────────────────

def _analyzer():
    from engine.nexus.conversation_analyzer import get_conversation_analyzer
    return get_conversation_analyzer()


def _profile():
    from engine.nexus.user_profile import get_user_profile_store
    return get_user_profile_store()


def _backup():
    from engine.nexus.backup_manager import get_backup_manager
    return get_backup_manager()


# ──── Conversation Analysis Skills ────────────────────────────────────────────

@skill(
    pack="profile",
    description=(
        "Extract structured facts about the user from a conversation text. "
        "Returns name, age, tech background, projects, preferences, facts, "
        "topics of interest, decisions, and action items as JSON."
    ),
    category=SkillCategory.MEMORY,
    tags=["conversation", "analysis", "user-profile", "extraction"],
)
def analyze_conversation(
    conversation_text: str,
    mode: str = "auto",
) -> str:
    """Analyze a conversation and extract structured user facts.

    Args:
        conversation_text: Multi-turn conversation text to analyze.
        mode: Extraction mode — "auto", "nlm", "lm", or "heuristic".

    Returns:
        JSON string with extracted facts.
    """
    result = _analyzer().analyze(conversation_text, mode=mode, store_to_profile=True)
    return json.dumps(result.to_dict(), indent=2)


@skill(
    pack="profile",
    description=(
        "Automatically fetch the most recent Copilot session turns and analyze "
        "them for user facts. Stores findings in the user profile and Nexus."
    ),
    category=SkillCategory.MEMORY,
    tags=["conversation", "analysis", "automatic", "session"],
)
def analyze_recent_conversation(
    turns_back: int = 50,
) -> str:
    """Analyze recent session turns and update the user profile.

    Args:
        turns_back: Number of conversation turns to include (default 50).

    Returns:
        JSON string with extraction result.
    """
    result = _analyzer().analyze_recent_turns(
        turns_back=turns_back,
        store_to_profile=True,
    )
    return json.dumps(result.to_dict(), indent=2)


@skill(
    pack="profile",
    description="Return the last conversation analysis result.",
    category=SkillCategory.MEMORY,
    tags=["conversation", "analysis", "status"],
)
def conversation_analyzer_status() -> str:
    """Return the last analysis result from the ConversationAnalyzer.

    Returns:
        JSON string with last extraction result, or null if none.
    """
    result = _analyzer().get_last_result()
    return json.dumps(result, indent=2) if result else "null"


# ──── User Profile Skills ──────────────────────────────────────────────────────

@skill(
    pack="profile",
    description=(
        "Return the full structured user profile — name, technical background, "
        "projects, preferences, facts, topics of interest, and conversation count."
    ),
    category=SkillCategory.MEMORY,
    tags=["user-profile", "preferences", "facts"],
)
def user_profile_get() -> str:
    """Return the full user profile as JSON.

    Returns:
        JSON string with complete profile.
    """
    return json.dumps(_profile().get_profile(), indent=2)


@skill(
    pack="profile",
    description=(
        "Return a compact markdown summary of the user profile suitable for "
        "injection into an LLM system prompt."
    ),
    category=SkillCategory.MEMORY,
    tags=["user-profile", "context", "summary"],
)
def user_profile_context() -> str:
    """Return a compact markdown context summary of the user profile.

    Returns:
        Markdown string with key profile facts.
    """
    return _profile().get_context_summary()


@skill(
    pack="profile",
    description=(
        "Return a list of all known facts about the user extracted from conversations."
    ),
    category=SkillCategory.MEMORY,
    tags=["user-profile", "facts"],
)
def user_profile_facts() -> str:
    """Return all known user facts as a JSON list.

    Returns:
        JSON array of fact strings.
    """
    profile = _profile().get_profile()
    return json.dumps(profile.get("facts", []), indent=2)


@skill(
    pack="profile",
    description=(
        "Add a single fact about the user to the persistent profile. "
        "Example: 'Has RTX 2060 12GB VRAM'."
    ),
    category=SkillCategory.MEMORY,
    tags=["user-profile", "facts", "update"],
)
def user_profile_add_fact(fact: str) -> str:
    """Add a fact to the user profile.

    Args:
        fact: A factual statement about the user.

    Returns:
        Confirmation message.
    """
    _profile().add_fact(fact)
    return f"Fact added: {fact}"


@skill(
    pack="profile",
    description=(
        "Set a preference in the user profile. "
        "Example: key='output_verbosity', value='concise'."
    ),
    category=SkillCategory.MEMORY,
    tags=["user-profile", "preferences", "update"],
)
def user_profile_set_preference(key: str, value: str) -> str:
    """Set a user preference.

    Args:
        key: Preference key.
        value: Preference value.

    Returns:
        Confirmation message.
    """
    _profile().add_preference(key, value)
    return f"Preference set: {key} = {value}"


@skill(
    pack="profile",
    description=(
        "Merge a JSON object of updates into the user profile. "
        "Lists are extended with unique values; dicts are merged recursively."
    ),
    category=SkillCategory.MEMORY,
    tags=["user-profile", "update", "merge"],
)
def user_profile_update(updates_json: str) -> str:
    """Merge updates into the user profile.

    Args:
        updates_json: JSON object with profile fields to update.

    Returns:
        Updated profile as JSON.
    """
    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON: {exc}"})
    updated = _profile().merge(updates)
    return json.dumps(updated, indent=2)


# ──── Backup Skills ────────────────────────────────────────────────────────────

@skill(
    pack="profile",
    description=(
        "Run a full database backup cycle for all CosySim SQLite databases "
        "(Nexus, session store, training flywheel). Stores compressed .db.gz "
        "files with timestamps. Returns backup summary."
    ),
    category=SkillCategory.SYSTEM,
    tags=["backup", "database", "maintenance"],
)
def backup_run() -> str:
    """Run a full backup of all databases.

    Returns:
        JSON string with backup result summary.
    """
    result = _backup().run_backup()
    return json.dumps(result.to_dict(), indent=2)


@skill(
    pack="profile",
    description=(
        "List all available database backup files with their filenames, "
        "sizes, ages, and timestamps."
    ),
    category=SkillCategory.SYSTEM,
    tags=["backup", "database", "list"],
)
def backup_list() -> str:
    """List all backup files.

    Returns:
        JSON array of backup file metadata.
    """
    return json.dumps(_backup().list_backups(), indent=2)


@skill(
    pack="profile",
    description=(
        "Restore a database backup from a .db.gz file to a target path. "
        "Use backup_list to find available backups first."
    ),
    category=SkillCategory.SYSTEM,
    tags=["backup", "restore", "database"],
)
def backup_restore(backup_path: str, target_path: str) -> str:
    """Restore a backup to a target path.

    Args:
        backup_path: Path to the .db.gz backup file.
        target_path: Destination path for the restored .db file.

    Returns:
        JSON result with success status and restored path.
    """
    result = _backup().restore_backup(backup_path, target_path)
    return json.dumps(result, indent=2)
