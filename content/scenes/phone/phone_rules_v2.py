"""
Phone Scene v2 — MCP Rules
============================
Defines all conversation heat gates, autonomous messaging policies,
media unlock rules, and truth-or-dare game rules for the phone scene.

All stat thresholds drive the governor pipeline via heat gates; the
autonomous-texting timer intervals are exposed as scene constants so
the scene can read them directly.

Change Log:
    v1.62.0 [2026-06-15] — CB-T5: calmer + more varied user inbox.
                            Lengthened AUTOTXT_COOLDOWN ranges (cold/warm in
                            particular) so the player is not pinged constantly;
                            added a config-driven ``comms.autotxt.user_multiplier``
                            (+ per-character override) applied in
                            ``autotxt_cooldown`` to scale all user-facing
                            autotext intervals; expanded the AUTOTXT_PROMPT_*
                            pools into multi-style banks; added topic-seed
                            helpers (``pick_topic_seed`` / ``seed_prompt``) that
                            occasionally weave a real city event/comms topic
                            into an autotext; added per-character anti-repeat
                            style selection (``pick_style`` / ``style_label``).
                            NPC↔NPC scheduling is untouched (separate path).
"""
from __future__ import annotations

import logging
import random
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCENE_ID = "phone"

# ── Autonomous texting cooldown config ────────────────────────────────────

# Time ranges (seconds) between an agent's unprompted messages.
# The scene picks a value in [lo, hi] after each message.
#
# v1.62.0 [2026-06-15] — CB-T5: ranges widened to calm the user inbox. The
# player was getting pinged far too often, especially at cold/warm warmth.
# New base defaults (BEFORE the user_multiplier is applied):
#   cold:     20-60 min   (was 10-30 min)
#   warm:     8-25 min    (was 3-10 min)
#   hot:      3-9 min     (was 1-4 min)
#   obsessed: 45-180 s    (was 20-90 s) — still the most responsive tier, so
#                          high-affection NPCs stay eager, just less spammy.
AUTOTXT_COOLDOWN = {
    "cold":      (1200, 3600),  # low trust / just met    (20-60 min)
    "warm":      (480, 1500),   # growing relationship     (8-25 min)
    "hot":       (180, 540),    # intimate / flirty        (3-9 min)
    "obsessed":  (45,  180),    # very high affection      (45-180 s)
}

# Config keys (read via get_config — never hardcoded at the call site).
_CFG_USER_MULTIPLIER = "comms.autotxt.user_multiplier"
_CFG_PER_CHARACTER   = "comms.autotxt.per_character"
_CFG_TOPIC_CHANCE    = "comms.autotxt.topic_seed_chance"
_DEFAULT_USER_MULTIPLIER = 1.75   # mirrors config/default.yaml
_DEFAULT_TOPIC_CHANCE    = 0.45   # mirrors config/default.yaml


def _user_multiplier(char_id: Optional[str] = None) -> float:
    """Return the user-facing autotext interval multiplier.

    Reads the global ``comms.autotxt.user_multiplier`` and, when a
    ``char_id`` is supplied, prefers a per-character override from
    ``comms.autotxt.per_character`` if one exists. Falls back to the module
    default when config is unavailable so the function never raises.

    Args:
        char_id: Optional character id whose per-character override should
            take precedence over the global multiplier.

    Returns:
        The multiplier as a positive float (clamped to ``>= 0``).
    """
    mult = _DEFAULT_USER_MULTIPLIER
    try:
        from engine.config import get_config
        cfg = get_config()
        mult = float(cfg.get(_CFG_USER_MULTIPLIER, _DEFAULT_USER_MULTIPLIER))
        if char_id:
            overrides = cfg.get(_CFG_PER_CHARACTER, {}) or {}
            if isinstance(overrides, dict) and char_id in overrides:
                mult = float(overrides[char_id])
    except Exception as exc:  # config optional / malformed → safe default
        logger.debug("[%s] user_multiplier lookup failed (operation=autotxt_cfg): %s", SCENE_ID, exc)
    return max(0.0, mult)


def autotxt_cooldown(trust: float, affection: float,
                     char_id: Optional[str] = None) -> float:
    """Return a random cooldown in seconds, scaled by the user multiplier.

    The base ``[lo, hi]`` range is chosen from :data:`AUTOTXT_COOLDOWN` by
    relationship warmth, a value is drawn uniformly from it, and the result is
    multiplied by ``comms.autotxt.user_multiplier`` (or a per-character
    override) so the whole user-facing cadence can be calmed via config
    without changing the warmth tiers.

    Args:
        trust: The character's trust stat.
        affection: The character's affection stat.
        char_id: Optional character id, enabling a per-character multiplier
            override.

    Returns:
        The cooldown in seconds (always ``>= 0``).
    """
    if affection >= 75 or trust >= 80:
        lo, hi = AUTOTXT_COOLDOWN["obsessed"]
    elif affection >= 50 or trust >= 60:
        lo, hi = AUTOTXT_COOLDOWN["hot"]
    elif affection >= 30 or trust >= 35:
        lo, hi = AUTOTXT_COOLDOWN["warm"]
    else:
        lo, hi = AUTOTXT_COOLDOWN["cold"]
    return random.uniform(lo, hi) * _user_multiplier(char_id)


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
#
# v1.62.0 [2026-06-15] — CB-T5: each conv mode now has a POOL of distinct
# opener styles instead of a single template, so back-to-back autotexts from
# the same character feel different. The scene tracks the last-used style per
# character (see ``pick_style``) to avoid repeating an opener immediately, and
# the conversation-variety interceptor still rotates *tone* on top of this — we
# only vary the structural opener, so the two layers don't fight.

# Backwards-compatible single templates (first entry of each pool) — kept as
# named constants because other modules / tests import them by name.
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

# Distinct opener-style banks per conv mode. Each ``(label, prompt)`` pair is a
# different *kind* of opener (question, observation, callback, share, …). The
# label is what the anti-repeat tracker remembers.
AUTOTXT_STYLE_POOLS: Dict[str, List[tuple]] = {
    "cold": [
        ("checkin", AUTOTXT_PROMPT_COLD),
        ("observation", """You are texting the user out of the blue. Open with a
small observation about your day or your surroundings — something mundane and
real that just made you think of them. Keep it short and casual.
Write ONLY the text message content."""),
        ("question", """You are texting the user unprompted. Open with a light,
low-stakes question to start a conversation (what they're up to, an opinion,
a recommendation). Keep it short and natural.
Write ONLY the text message content."""),
        ("random_thought", """You are texting the user on a whim. Share one random
passing thought or something small you noticed, like a real person firing off a
quick text. Keep it short.
Write ONLY the text message content."""),
    ],
    "warm": [
        ("warm_checkin", AUTOTXT_PROMPT_WARM),
        ("share", """You are sending an unprompted text to someone you like. Share
something from your day — a small win, an annoyance, something funny — like
you're keeping them in the loop. Warm and natural, maybe a little flirty.
Write ONLY the message text."""),
        ("callback", """You are texting someone you like out of the blue. Reference
something from an earlier conversation or an inside thing between you two, to
show you were thinking about them. Warm, natural, a little playful.
Write ONLY the message text."""),
        ("playful_tease", """You are texting someone you like unprompted. Open with a
playful tease or a bit of banter. Light, flirty, and natural.
Write ONLY the message text."""),
    ],
    "intimate": [
        ("yearning", AUTOTXT_PROMPT_INTIMATE),
        ("tender", """You are sending a spontaneous message to someone you're very
close to. Be tender and sincere — tell them something soft you're feeling right
now. Short and real, authentic to your personality.
Write ONLY the message text, no narration."""),
        ("teasing", """You are sending a spontaneous message to someone you're very
close to. Be playful and teasing, with warmth and obvious affection underneath.
Short and real.
Write ONLY the message text, no narration."""),
        ("missing_you", """You are texting someone you're very close to out of the
blue because you miss them. Say so in your own voice — yearning but not heavy.
Short and real.
Write ONLY the message text, no narration."""),
    ],
    "sext": [
        ("direct", AUTOTXT_PROMPT_SEXT),
        ("suggestive", """You are sending a spontaneous, suggestive text to someone
you're very attracted to and fully comfortable with. Be teasing and sensual,
hinting at what's on your mind. Keep it short — a real text.
Write ONLY the message text."""),
        ("confession", """You are sending a spontaneous sext to someone you desire.
Confess a thought or fantasy you can't stop thinking about. Direct, genuine,
sensual. Keep it short.
Write ONLY the message text."""),
    ],
}

# Map conv_mode → style-pool key.
_CONV_MODE_TO_POOL = {
    "intimate": "intimate",
    "sext": "sext",
    "flirty": "warm",
    "warm": "warm",
}

# Per-character last-used style label (anti-repeat). Module-level so it
# survives across ticker calls; guarded by a lock for the background thread.
_last_style: Dict[str, str] = {}
_last_style_lock = threading.Lock()


def _pool_key(conv_mode: str) -> str:
    """Map a conversation mode to its style-pool key (default ``'cold'``)."""
    return _CONV_MODE_TO_POOL.get(conv_mode, "cold")


def autotxt_prompt(conv_mode: str) -> str:
    """Return the canonical (first) opener template for a conversation mode.

    Backwards-compatible accessor. New callers should prefer :func:`pick_style`
    to get a *varied*, anti-repeating opener.

    Args:
        conv_mode: One of ``'intimate'``, ``'sext'``, ``'flirty'``, ``'warm'``,
            or anything else (treated as cold).

    Returns:
        The opener prompt scaffold string.
    """
    pool = AUTOTXT_STYLE_POOLS[_pool_key(conv_mode)]
    return pool[0][1]


def pick_style(conv_mode: str, char_id: str) -> tuple:
    """Pick an opener style for ``char_id``, avoiding the previous one.

    Chooses a ``(label, prompt)`` pair from the conv-mode style pool. When the
    pool has more than one entry the previously-used label for this character is
    excluded so the same opener never fires back-to-back. The chosen label is
    recorded for next time.

    Args:
        conv_mode: The conversation mode driving the pool selection.
        char_id: The character about to send the autotext.

    Returns:
        A ``(label, prompt)`` tuple: the style label and its prompt scaffold.
    """
    pool = AUTOTXT_STYLE_POOLS[_pool_key(conv_mode)]
    with _last_style_lock:
        prev = _last_style.get(char_id)
        candidates = [p for p in pool if p[0] != prev] or list(pool)
        choice = random.choice(candidates)
        _last_style[char_id] = choice[0]
    return choice


def style_label(char_id: str) -> Optional[str]:
    """Return the last opener-style label used for ``char_id`` (or ``None``)."""
    with _last_style_lock:
        return _last_style.get(char_id)


# ── Topic seeds (real city events / comms) ───────────────────────────────────
# v1.62.0 [2026-06-15] — CB-T5: occasionally ground an autotext in something
# actually happening in the city instead of a generic check-in. Seeds are drawn
# from recent WorldSim events and/or the GlobalCommsLog. All lookups are
# best-effort: if no source is available the helper returns None and the caller
# falls back to a plain opener.

def topic_seed_chance() -> float:
    """Return the configured probability of seeding an autotext with a topic.

    Returns:
        ``comms.autotxt.topic_seed_chance`` as a float in ``[0, 1]`` (falls
        back to the module default when config is unavailable).
    """
    try:
        from engine.config import get_config
        return float(get_config().get(_CFG_TOPIC_CHANCE, _DEFAULT_TOPIC_CHANCE))
    except Exception:
        return _DEFAULT_TOPIC_CHANCE


def pick_topic_seed(char_id: Optional[str] = None,
                    max_events: int = 8) -> Optional[str]:
    """Pick a short real-world topic to seed an autotext, or ``None``.

    Pools candidate topics from two best-effort sources and returns one at
    random:

    * recent :class:`~engine.world.world_sim.SimEvent` titles/descriptions, and
    * recent :class:`~engine.world.comms_log.GlobalCommsLog` entries about the
      character (when ``char_id`` is given) or the player otherwise.

    Every lookup is wrapped so a missing/empty source never raises — the helper
    simply returns ``None`` when nothing usable exists.

    Args:
        char_id: Character the autotext is from; used to bias comms lookups.
        max_events: Maximum recent world events to consider.

    Returns:
        A short topic string, or ``None`` when no seed is available.
    """
    seeds: List[str] = []

    # Source 1: recent world events (city-wide happenings).
    try:
        from engine.world.world_sim import get_world_sim
        for ev in get_world_sim().get_all_events(limit=max_events):
            topic = (getattr(ev, "title", "") or getattr(ev, "description", "") or "").strip()
            if topic:
                seeds.append(topic)
    except Exception as exc:
        logger.debug("[%s] topic seed: world events unavailable (operation=topic_seed): %s", SCENE_ID, exc)

    # Source 2: recent comms about this character (or the player).
    try:
        from engine.world.comms_log import get_comms_log
        cl = get_comms_log()
        entries = cl.about(char_id, limit=8) if char_id else cl.recent(limit=8)
        for entry in entries:
            content = (entry.get("content") or "").strip()
            # Skip our own past autotexts so we don't echo ourselves.
            if entry.get("sender_id") == char_id and entry.get("kind") in ("autotext", "left_message"):
                continue
            if content:
                seeds.append(content[:140])
    except Exception as exc:
        logger.debug("[%s] topic seed: comms log unavailable (operation=topic_seed): %s", SCENE_ID, exc)

    if not seeds:
        return None
    return random.choice(seeds)


def seed_prompt(base_prompt: str, topic: Optional[str]) -> str:
    """Weave a topic seed into a base opener prompt.

    Args:
        base_prompt: The opener scaffold from :func:`pick_style` /
            :func:`autotxt_prompt`.
        topic: A topic string from :func:`pick_topic_seed`, or ``None``.

    Returns:
        ``base_prompt`` unchanged when ``topic`` is falsy, otherwise the prompt
        augmented with a directive to reference the topic naturally.
    """
    if not topic:
        return base_prompt
    return (
        f"{base_prompt}\n\nReference this real thing happening in the city, "
        f"naturally and in your own voice (don't quote it verbatim): \"{topic}\""
    )


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
