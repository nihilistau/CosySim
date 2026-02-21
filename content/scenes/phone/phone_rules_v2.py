"""
Phone Scene v2 — MCP Rules
============================
Defines all conversation heat gates, autonomous messaging policies,
media unlock rules, and truth-or-dare game rules for the phone scene.

All stat thresholds drive the governor pipeline via heat gates; the
autonomous-texting timer intervals are exposed as scene constants so
the scene can read them directly.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "phone"

# ── Autonomous texting cooldown config ────────────────────────────────────

# Time ranges (seconds) between an agent's unprompted messages.
# The scene picks a value in [lo, hi] after each message.
AUTOTXT_COOLDOWN = {
    "cold":      (600, 1800),   # low trust / just met  (10-30 min)
    "warm":      (180, 600),    # growing relationship    (3-10 min)
    "hot":       (60,  240),    # intimate / flirty       (1-4 min)
    "obsessed":  (20,  90),     # very high affection     (20-90 s)
}

def autotxt_cooldown(trust: float, affection: float) -> float:
    """Return a random cooldown seconds based on relationship warmth."""
    if affection >= 75 or trust >= 80:
        lo, hi = AUTOTXT_COOLDOWN["obsessed"]
    elif affection >= 50 or trust >= 60:
        lo, hi = AUTOTXT_COOLDOWN["hot"]
    elif affection >= 30 or trust >= 35:
        lo, hi = AUTOTXT_COOLDOWN["warm"]
    else:
        lo, hi = AUTOTXT_COOLDOWN["cold"]
    return random.uniform(lo, hi)


# ── Heat gate rules ──────────────────────────────────────────────────────────

HEAT_RULES: List[Dict[str, Any]] = [
    {
        "id": "always_friendly",
        "label": "Friendly Chat",
        "description": "Normal warm conversation — always available.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "flirt_mode",
        "label": "Flirt Mode",
        "description": "Light flirting unlocked when warmth ≥ 35 and happiness ≥ 30.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"warmth": 35, "happiness": 30}},
        "effects": [
            {"effect_type": "state_set", "params": {"field": "conversation_mode", "value": "flirty"}},
            {"effect_type": "set_directive", "params": {
                "directive_type": "style_lock", "value": "playful", "turns": 1,
            }},
        ],
    },
    {
        "id": "sext_gate",
        "label": "Sexting Unlocked",
        "description": "Explicit texting opens at arousal ≥ 55, openness ≥ 50, trust ≥ 40.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"arousal": 55, "openness": 50, "trust": 40}},
        "effects": [
            {"effect_type": "state_set", "params": {"field": "conversation_mode", "value": "intimate"}},
            {"effect_type": "add_narrative", "params": {
                "event": "The conversation has shifted into something more private.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id": "media_sharing",
        "label": "Media Sharing",
        "description": "Personal photo/video sharing at trust ≥ 55, affection ≥ 50.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"trust": 55, "affection": 50}},
        "effects": [
            {"effect_type": "state_set", "params": {"field": "media_sharing_ok", "value": True}},
        ],
    },
    {
        "id": "voice_comfort",
        "label": "Voice Messages OK",
        "description": "Character comfortable sending voice notes at trust ≥ 45.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"trust": 45}},
        "effects": [
            {"effect_type": "state_set", "params": {"field": "voice_msg_ok", "value": True}},
        ],
    },
    {
        "id": "deep_mode",
        "label": "Deep Connection",
        "description": "Emotional depth and secrets shared at trust ≥ 70, affection ≥ 60.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"trust": 70, "affection": 60}},
        "effects": [
            {"effect_type": "set_directive", "params": {
                "directive_type": "style_lock", "value": "vulnerable", "turns": 2,
            }},
        ],
    },
]


# ── Autonomous message templates ─────────────────────────────────────────────
# These are injected as the "user turn" when the agent sends an unprompted text.
# The LLM generates the actual message; this is the prompt scaffolding.

AUTOTXT_PROMPT_COLD = """You are texting the user on your own initiative.
Keep it short, casual and natural — like a real text message.
You just thought of them and decided to reach out.
Write ONLY the text message content, nothing else."""

AUTOTXT_PROMPT_WARM = """You are sending an unprompted text to someone you like.
Make it warm, maybe a little flirty, very natural.
It can be anything: sharing a thought, asking how they are, a meme reference.
Write ONLY the message text."""

AUTOTXT_PROMPT_INTIMATE = """You are sending a spontaneous intimate message to someone
you're very close to. It can be playful, yearning, teasing, or tender.
Keep it authentic to your personality. Short and real.
Write ONLY the message text, no narration."""

AUTOTXT_PROMPT_SEXT = """You are sending a spontaneous sext to someone you're very
attracted to and fully comfortable with. Be genuine, direct, sensual.
Keep it short — a real text, not a novel.
Write ONLY the message text."""

def autotxt_prompt(conv_mode: str) -> str:
    if conv_mode == "intimate":
        return AUTOTXT_PROMPT_INTIMATE
    if conv_mode == "sext":
        return AUTOTXT_PROMPT_SEXT
    if conv_mode == "flirty":
        return AUTOTXT_PROMPT_WARM
    return AUTOTXT_PROMPT_COLD


# ── Truth-or-dare challenges ─────────────────────────────────────────────────

TOD_TRUTHS = [
    "What's the most embarrassing thing you've ever done?",
    "What's your biggest secret that you've never told anyone?",
    "Have you ever had feelings for someone you shouldn't have?",
    "What's the most daring thing you've ever done?",
    "What do you find most attractive about me?",
    "Have you ever lied to someone you care about? What happened?",
    "What's something you've always wanted to try but haven't?",
    "What's your deepest insecurity?",
    "Who was your first crush and what happened?",
    "What's the most rebellious thing you've ever done?",
    "If you could change one thing about yourself, what would it be?",
    "What's the naughtiest thought you've had recently?",
    "Have you ever done something you're not proud of to get what you wanted?",
    "What's your biggest fantasy?",
    "What's the boldest thing you've ever said to someone?",
]

TOD_DARES = [
    "Send me a voice message saying something you'd never normally say.",
    "Tell me something about yourself in 3 words.",
    "Describe your perfect evening in one sentence.",
    "Say the first thing that comes to mind when you think of me.",
    "Tell me a secret you've never told anyone.",
    "Share the last photo in your gallery.",
    "Send me a song that makes you think of me.",
    "Tell me exactly what you're wearing right now.",
    "Describe what you'd want to do if we were together right now.",
    "Write me a short poem, right now, no editing.",
    "Tell me your most embarrassing texting moment.",
    "Describe yourself in 5 emojis.",
    "Tell me the wildest thing you'd do if no one was watching.",
    "Send a voice message doing your best impression of me.",
    "Tell me something you've always wanted to ask but haven't.",
]

def get_truth() -> str:
    return random.choice(TOD_TRUTHS)

def get_dare() -> str:
    return random.choice(TOD_DARES)


# ── Rule registration ─────────────────────────────────────────────────────────

def register_phone_rules(scene_node) -> None:
    """Register all heat rules and scene policies with the MCP scene node."""
    try:
        for rule in HEAT_RULES:
            scene_node.add_rule(rule)
        logger.info("Phone scene v2: registered %d heat rules", len(HEAT_RULES))
    except Exception as exc:
        logger.warning("Phone rules registration incomplete: %s", exc)
