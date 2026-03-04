"""
Utility tool logic — extracted from cosysim_server.py (Sprint 14 Phase A).

Pure business-logic functions. Each takes its dependencies as parameters
so the MCP @tool wrappers in cosysim_server.py remain thin.
"""
from __future__ import annotations

import json
import logging
import random as _random
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Dice & randomness ─────────────────────────────────────────────────

def roll_dice_logic(sides: int = 6, count: int = 1) -> str:
    """Roll one or more dice and return JSON with results."""
    sides  = max(2, min(sides, 1000))
    count  = max(1, min(count, 20))
    rolls  = [_random.randint(1, sides) for _ in range(count)]
    total  = sum(rolls)
    result = {
        "rolls": rolls,
        "total": total,
        "sides": sides,
        "outcome": "odd" if total % 2 == 1 else "even",
    }
    return json.dumps(result, default=str)


def get_random_topic_logic(category: str = "general") -> str:
    """Return a randomly selected topic or prompt for conversation or games."""
    TOPICS = {
        "truth_questions": [
            "What is your biggest secret you've never told anyone?",
            "Who was your first crush and do you still think about them?",
            "What is the most embarrassing thing that has ever happened to you?",
            "What is something you've done that you deeply regret?",
            "If you could change one decision you've made, what would it be?",
            "Have you ever lied to protect someone's feelings? What happened?",
            "What is the worst thing you've ever done and gotten away with?",
            "What is one thing you wish people understood about you?",
        ],
        "dare_ideas": [
            "Send a voice message saying something embarrassing.",
            "Describe your ideal perfect day in as much vivid detail as possible.",
            "Confess something you've been thinking about but haven't said.",
            "Tell me three things you secretly find attractive.",
            "Describe a dream you've had recently in detail.",
            "Say something kind but totally unexpected.",
            "Invent and tell me a one-minute story right now.",
            "Describe yourself using only three words.",
        ],
        "mystery_clues": [
            "A torn piece of paper with coordinates written in ink.",
            "An old photograph with a face scratched out.",
            "A key that fits no known lock.",
            "A voicemail from a number that doesn't exist.",
            "A book with one passage underlined in red.",
            "A receipt from a restaurant that closed ten years ago.",
            "A note written in a language you don't recognise.",
        ],
        "conversation_starters": [
            "If you could live anywhere in the world, where would you choose?",
            "What is something you want to learn but haven't started yet?",
            "What memory always makes you smile?",
            "If you had one superpower for a day, what would it be?",
            "What song always puts you in a good mood?",
        ],
        "relationship_questions": [
            "What do you value most in a partner?",
            "What is your love language?",
            "Describe your perfect evening together.",
            "What is one thing you've always wanted to do with someone special?",
        ],
        "general": [
            "Tell me something interesting you learned this week.",
            "What is your favourite way to relax?",
            "If you could meet any historical figure, who would it be?",
            "What is the best book or show you've experienced recently?",
        ],
    }
    pool  = TOPICS.get(category, TOPICS["general"])
    topic = _random.choice(pool)
    return json.dumps({"category": category, "topic": topic})


def random_pick_logic(
    n: int,
    options_json: str = "[]",
    weights_json: str = "[]",
    seed: Optional[int] = None,
) -> str:
    """Roll 1–n or pick from a list of options, with optional weights."""
    try:
        from engine.mcp.framework import get_framework
        options = json.loads(options_json) if options_json and options_json != "[]" else None
        weights = json.loads(weights_json) if weights_json and weights_json != "[]" else None
        result  = get_framework().random_pick(n=n, seed=seed, weights=weights, options=options)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Benchmarks & system stats ─────────────────────────────────────────

def get_benchmark_stats_logic() -> str:
    """Return performance benchmark statistics as a formatted string."""
    try:
        from engine.logging import get_benchmarks
        stats = get_benchmarks()
        if not stats:
            return "No benchmark data available."
        lines = []
        for op, s in stats.items():
            lines.append(
                f"{op}: count={s['count']}, avg={s['avg_ms']:.1f}ms, "
                f"p95={s['p95_ms']:.1f}ms, max={s['max_ms']:.1f}ms"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get benchmarks: {e}"


def get_system_stats_logic() -> str:
    """Return current system resource usage as JSON."""
    try:
        from engine.logging.monitor import get_system_monitor
        from engine.services.activity_bus import get_activity_bus
        mon = get_system_monitor()
        bus = get_activity_bus()
        snap = mon.snapshot()
        return json.dumps({
            "cpu_percent":      snap.get("cpu_percent"),
            "ram_used_gb":      snap.get("ram_used_gb"),
            "ram_total_gb":     snap.get("ram_total_gb"),
            "gpu_vram_used_mb": snap.get("gpu_vram_used_mb"),
            "gpu_vram_total_mb":snap.get("gpu_vram_total_mb"),
            "gpu_temp_c":       snap.get("gpu_temp_c"),
            "gpu_name":         snap.get("gpu_name"),
            "loaded_model":     mon.get_loaded_model(),
            "activity":         bus.snapshot(),
        }, indent=2, default=str)
    except Exception as e:
        return f"Stats unavailable: {e}"


# ── Timers ─────────────────────────────────────────────────────────────

def start_timer_logic(
    timer_name: str,
    duration_secs: float,
    on_complete_note: str = "",
) -> str:
    """Start a named countdown timer and return JSON status."""
    try:
        from engine.mcp.framework import get_framework
        timer = get_framework().start_timer(timer_name, duration_secs, on_complete_note=on_complete_note)
        return json.dumps({
            "ok": True,
            "timer_name":    timer.name,
            "duration_secs": timer.duration_secs,
            "status":        "started",
            "note":          "Call check_timer(timer_name) each turn to see progress.",
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def check_timer_logic(timer_name: str) -> str:
    """Check the state of a running timer and return JSON."""
    try:
        from engine.mcp.framework import get_framework
        timer = get_framework().check_timer(timer_name)
        if timer is None:
            return json.dumps({"found": False, "timer_name": timer_name})
        return json.dumps({**timer.to_dict(), "found": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def cancel_timer_logic(timer_name: str) -> str:
    """Cancel a running timer before it completes."""
    try:
        from engine.mcp.framework import get_framework
        ok = get_framework().cancel_timer(timer_name)
        return json.dumps({"ok": ok, "timer_name": timer_name})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ── Activity suggestions ──────────────────────────────────────────────

def suggest_activity_logic(scene_id: str = "phone") -> str:
    """Suggest scene-appropriate activities based on current context."""
    activities = {
        "phone": [
            {"name": "Truth or Dare", "desc": "Start a game with 🎮 Play button", "heat_min": 0},
            {"name": "Photo sharing", "desc": "Ask for a selfie or share one", "heat_min": 20},
            {"name": "Voice note", "desc": "Send a voice message", "heat_min": 0},
            {"name": "Deep conversation", "desc": "Ask about dreams, fears, desires", "heat_min": 10},
            {"name": "Roleplay", "desc": "Suggest a fun scenario to act out", "heat_min": 40},
            {"name": "Flirting game", "desc": "See who can be more creative with compliments", "heat_min": 30},
        ],
        "bedroom": [
            {"name": "Set the mood", "desc": "Change lighting, music, atmosphere", "heat_min": 0},
            {"name": "Wardrobe change", "desc": "Try on different outfits", "heat_min": 10},
            {"name": "Dance", "desc": "Put on music and dance together", "heat_min": 20},
            {"name": "Massage", "desc": "Offer or receive a massage", "heat_min": 40},
            {"name": "Story time", "desc": "Share personal stories or fantasies", "heat_min": 30},
            {"name": "Pillow fight", "desc": "Playful physical activity", "heat_min": 10},
        ],
        "lounge": [
            {"name": "Order drinks", "desc": "Try the cocktail menu", "heat_min": 0},
            {"name": "Karaoke", "desc": "Sing a song together", "heat_min": 0},
            {"name": "People watch", "desc": "Comment on other patrons", "heat_min": 0},
            {"name": "Dance floor", "desc": "Hit the dance floor", "heat_min": 20},
            {"name": "VIP room", "desc": "Move to a more private area", "heat_min": 40},
        ],
    }
    scene_activities = activities.get(scene_id, activities["phone"])
    return json.dumps({
        "scene": scene_id,
        "suggestions": scene_activities,
    }, indent=2)


# ── Framework status ──────────────────────────────────────────────────

def get_framework_status_logic() -> str:
    """Return a full MCPFramework status snapshot as JSON."""
    try:
        from engine.mcp.framework import get_framework
        return json.dumps(get_framework().get_status(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Cross-scene communication ─────────────────────────────────────────

def cross_scene_message_logic(
    from_char: str,
    from_scene: str,
    to_char: str,
    to_scene: str,
    message: str,
    message_type: str = "text",
) -> str:
    """Send a cross-scene message and return JSON result."""
    try:
        from engine.mcp.framework import get_framework
        msg = get_framework().cross_scene_send(
            from_char    = from_char,
            from_scene   = from_scene,
            to_char      = to_char,
            to_scene     = to_scene,
            message      = message,
            message_type = message_type,
        )
        return json.dumps({
            "ok":          True,
            "message_id":  msg.message_id,
            "from":        f"{from_char}@{from_scene}",
            "to":          f"{to_char}@{to_scene}",
            "type":        message_type,
            "preview":     message[:80],
            "note":        f"{to_char} will see this message on their next turn.",
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def get_cross_scene_inbox_logic(character_id: str) -> str:
    """Check for unread cross-scene messages for a character."""
    try:
        from engine.mcp.framework import get_framework
        messages = get_framework().get_cross_scene_inbox(character_id)
        return json.dumps({"character_id": character_id, "messages": messages, "count": len(messages)})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP Resources (logic only) ────────────────────────────────────────

def resource_config_logic(get_config_fn: Callable) -> str:
    """Return current CosySim configuration snapshot as JSON."""
    try:
        config = get_config_fn()
        return json.dumps(dict(config._config), indent=2, default=str)
    except Exception as e:
        return f"Config unavailable: {e}"


def resource_benchmarks_logic() -> str:
    """Return performance benchmark summary as JSON."""
    try:
        from engine.logging import get_benchmarks
        return json.dumps(get_benchmarks(), indent=2, default=str)
    except Exception as e:
        return f"Benchmarks unavailable: {e}"


def resource_character_logic(character_id: str, db: Any) -> str:
    """Return full character profile including personality, state, and relationships."""
    try:
        char = db.get_character(character_id)
        state = db.get_character_state(character_id)
        rels = db.list_relationships(character_id)
        personality = db.get_personality(character_id)
        return json.dumps({
            "character": dict(char) if char else None,
            "personality": dict(personality) if personality else None,
            "state": dict(state) if state else None,
            "relationships": [dict(r) for r in rels] if rels else [],
        }, indent=2, default=str)
    except Exception as e:
        return f"Character data unavailable: {e}"


def resource_chain_logic(chain_id: str, db: Any) -> str:
    """Return full EventChain tree for a specific chain as JSON."""
    try:
        events = db.get_chain_events(chain_id, limit=100)
        return json.dumps(
            [dict(e) if not isinstance(e, dict) else e for e in events],
            indent=2, default=str,
        )
    except Exception as e:
        return f"Chain unavailable: {e}"
