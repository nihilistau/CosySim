"""MCP skills for the multiplayer subsystem.

Exposes session management, player presence, messaging, and
leaderboards to LLM agents and the game engine via the @skill
decorator.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ──── Presence & Session Skills ────


@skill(
    pack="multiplayer",
    description="See which players are in your current scene",
    category="SOCIAL",
    tags=["multiplayer", "presence"],
)
def who_is_here(scene_name: str) -> str:
    """List players currently in a specific scene.

    Args:
        scene_name: Scene to check (e.g., "bedroom", "neoncity").

    Returns:
        Formatted list of players in the scene.
    """
    from engine.multiplayer.presence import get_presence_tracker
    pt = get_presence_tracker()
    players = pt.get_scene_occupancy(scene_name)
    if not players:
        return f"No players currently in {scene_name}."
    lines = [f"Players in {scene_name} ({len(players)}):"]
    for p in players:
        status = p.get("status", "online")
        lines.append(f"  • {p['display_name']} [{status}]")
    return "\n".join(lines)


@skill(
    pack="multiplayer",
    description="Get your current session information",
    category="SYSTEM",
    tags=["multiplayer", "session"],
)
def my_session(player_id: str) -> str:
    """Show current session details for a player.

    Args:
        player_id: The player to look up.

    Returns:
        Session details or 'not connected' message.
    """
    from engine.multiplayer.session_manager import get_session_manager
    sm = get_session_manager()
    session = sm.get_session_by_player(player_id)
    if not session:
        return f"Player {player_id} has no active session."
    state = sm.get_state_by_player(player_id)
    lines = [
        f"Session for {session.display_name}:",
        f"  Status: {session.status.value}",
        f"  Scene: {session.connected_scene or 'none'}",
        f"  Session ID: {session.session_id[:8]}...",
    ]
    if state:
        lines.extend([
            f"  Credits: {state.credits:,}",
            f"  Reputation: {state.reputation}",
            f"  Heat: {state.heat}",
            f"  Items: {len(state.inventory)}",
        ])
    return "\n".join(lines)


@skill(
    pack="multiplayer",
    description="List all online players",
    category="SOCIAL",
    tags=["multiplayer", "presence"],
)
def player_list() -> str:
    """List all currently connected players.

    Returns:
        Formatted list of online players and their scenes.
    """
    from engine.multiplayer.session_manager import get_session_manager
    sm = get_session_manager()
    players = sm.list_online_players()
    if not players:
        return "No players currently online."
    lines = [f"Online Players ({len(players)}):"]
    for p in players:
        scene = p.get("connected_scene") or "lobby"
        lines.append(f"  • {p['display_name']} [{p['status']}] in {scene}")
    return "\n".join(lines)


@skill(
    pack="multiplayer",
    description="Move to a different scene",
    category="SYSTEM",
    tags=["multiplayer", "navigation"],
)
def go_to_scene(player_id: str, scene_name: str) -> str:
    """Move a player to a different scene.

    Args:
        player_id: The player moving.
        scene_name: Target scene name.

    Returns:
        Confirmation or error message.
    """
    from engine.multiplayer.presence import get_presence_tracker
    from engine.multiplayer.session_manager import get_session_manager
    sm = get_session_manager()
    session = sm.get_session_by_player(player_id)
    if not session:
        return f"Player {player_id} has no active session."

    pt = get_presence_tracker()
    old_scene = session.connected_scene
    pt.player_joined_scene(session.session_id, scene_name)
    return f"Moved from {old_scene or 'lobby'} → {scene_name}."


@skill(
    pack="multiplayer",
    description="Set your online status (online/away/busy)",
    category="SOCIAL",
    tags=["multiplayer", "status"],
)
def set_status(player_id: str, status: str) -> str:
    """Change a player's online status.

    Args:
        player_id: The player.
        status: New status — "online", "away", or "busy".

    Returns:
        Confirmation or error message.
    """
    from engine.multiplayer.presence import get_presence_tracker
    from engine.multiplayer.session_manager import get_session_manager
    sm = get_session_manager()
    session = sm.get_session_by_player(player_id)
    if not session:
        return f"Player {player_id} has no active session."

    pt = get_presence_tracker()
    if pt.set_status(session.session_id, status):
        return f"Status set to {status}."
    return f"Invalid status: {status}. Use online, away, or busy."


# ──── Messaging Skills ────


@skill(
    pack="multiplayer",
    description="Send a direct message to another player",
    category="COMMUNICATION",
    tags=["multiplayer", "messaging"],
)
def send_message(sender_id: str, receiver_id: str, content: str) -> str:
    """Send a direct message from one player to another.

    Args:
        sender_id: Sending player.
        receiver_id: Receiving player.
        content: Message text.

    Returns:
        Confirmation with message id.
    """
    from engine.multiplayer.messaging import get_message_store
    from engine.multiplayer.session_manager import get_session_manager

    sm = get_session_manager()
    sender_session = sm.get_session_by_player(sender_id)
    if not sender_session:
        return f"Sender {sender_id} is not connected."

    ms = get_message_store()
    msg = ms.send(sender_id, receiver_id, content)

    state = sm.get_state_by_player(sender_id)
    if state:
        state.increment_stat("messages_sent")

    return f"Message sent to {receiver_id} (id: {msg.message_id[:8]}...)."


@skill(
    pack="multiplayer",
    description="Read unread messages",
    category="COMMUNICATION",
    tags=["multiplayer", "messaging"],
)
def read_messages(player_id: str, mark_read: bool = True) -> str:
    """Get all unread messages for a player.

    Args:
        player_id: The receiving player.
        mark_read: Whether to mark messages as read after retrieval.

    Returns:
        Formatted list of unread messages or 'no new messages'.
    """
    from engine.multiplayer.messaging import get_message_store
    ms = get_message_store()
    unread = ms.get_unread(player_id)
    if not unread:
        return "No unread messages."

    lines = [f"Unread Messages ({len(unread)}):"]
    for msg in unread:
        lines.append(f"  From {msg['sender_id']}: {msg['content']}")

    if mark_read:
        ms.mark_read(player_id)

    return "\n".join(lines)


@skill(
    pack="multiplayer",
    description="Check how many unread messages you have",
    category="COMMUNICATION",
    tags=["multiplayer", "messaging"],
)
def unread_count(player_id: str) -> str:
    """Count unread messages for a player.

    Args:
        player_id: Player to check.

    Returns:
        Unread count message.
    """
    from engine.multiplayer.messaging import get_message_store
    ms = get_message_store()
    count = ms.unread_count(player_id)
    if count == 0:
        return "No unread messages."
    return f"You have {count} unread message{'s' if count != 1 else ''}."


@skill(
    pack="multiplayer",
    description="View conversation history with another player",
    category="COMMUNICATION",
    tags=["multiplayer", "messaging"],
)
def message_history(player_id: str, partner_id: str,
                    limit: int = 20) -> str:
    """Get conversation history with another player.

    Args:
        player_id: Your player id.
        partner_id: The other player.
        limit: Max messages to show.

    Returns:
        Formatted conversation history.
    """
    from engine.multiplayer.messaging import get_message_store
    ms = get_message_store()
    msgs = ms.get_thread(player_id, partner_id, limit=limit)
    if not msgs:
        return f"No conversation with {partner_id}."

    lines = [f"Conversation with {partner_id} ({len(msgs)} messages):"]
    for msg in msgs:
        direction = "→" if msg["sender_id"] == player_id else "←"
        lines.append(f"  {direction} {msg['content']}")
    return "\n".join(lines)


# ──── Leaderboard Skills ────


@skill(
    pack="multiplayer",
    description="View the top players leaderboard",
    category="SOCIAL",
    tags=["multiplayer", "leaderboard", "competition"],
)
def leaderboard(category: str = "credits", limit: int = 10,
                weekly: bool = False) -> str:
    """Display the leaderboard for a category.

    Args:
        category: Category — credits, reputation, kills, heists, hacking, territory.
        limit: Number of top players to show.
        weekly: If True, show weekly rankings.

    Returns:
        Formatted leaderboard.
    """
    from engine.multiplayer.leaderboards import get_leaderboard
    lb = get_leaderboard()
    period = "Weekly" if weekly else "All-Time"
    top = lb.get_top(category, limit=limit, weekly=weekly)
    if not top:
        return f"No scores yet for {category} ({period})."

    lines = [f"🏆 {period} Leaderboard — {category.upper()} (Top {limit}):"]
    for entry in top:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(entry["rank"], "  ")
        lines.append(f"  {medal} #{entry['rank']} {entry['display_name']}: "
                     f"{entry['score']:,}")
    return "\n".join(lines)


@skill(
    pack="multiplayer",
    description="Check your rank on the leaderboard",
    category="SOCIAL",
    tags=["multiplayer", "leaderboard"],
)
def my_rank(player_id: str, category: str = "credits") -> str:
    """Get a player's rank in a leaderboard category.

    Args:
        player_id: Player to look up.
        category: Category to check.

    Returns:
        Rank info or 'not ranked' message.
    """
    from engine.multiplayer.leaderboards import get_leaderboard
    lb = get_leaderboard()
    rank = lb.get_rank(category, player_id)
    if not rank:
        return f"Not ranked in {category} yet."
    return (f"Your rank in {category}: #{rank['rank']} "
            f"(score: {rank['score']:,})")


@skill(
    pack="multiplayer",
    description="View all your scores across categories",
    category="SOCIAL",
    tags=["multiplayer", "leaderboard", "stats"],
)
def my_scores(player_id: str) -> str:
    """Get all leaderboard scores for a player.

    Args:
        player_id: Player to look up.

    Returns:
        Formatted scores across all categories.
    """
    from engine.multiplayer.leaderboards import get_leaderboard
    lb = get_leaderboard()
    scores = lb.get_player_scores(player_id)
    if not scores:
        return "No scores recorded yet."

    lines = [f"Your Scores:"]
    for cat, info in scores.items():
        rank_str = f"#{info['rank']}" if info['rank'] else "unranked"
        lines.append(f"  {cat}: {info['score']:,} ({rank_str})")
    return "\n".join(lines)
