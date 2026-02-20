"""
The Velvet Lounge — MCP System
================================
All rules, actions, state, consequences, and character definitions for
The Velvet Lounge — a 1920s underground jazz speakeasy where every
mechanic is MCP-governed.

Architecture
------------
• 8 cocktails  — each serves a drink + fires consequence chain stat effects
• Stage system — MCPTimer tracks song duration; rules gate what Lola sings
• Trust economy — 0–100; gates secrets, back room, private pours
• HEAT meter   — police danger; MCPTimer + consequence chains manage escalation
• Back room    — permission gate via MCPSceneNode rule
• Cross-agent  — Lola ↔ Viktor communicate via MCPFramework.cross_scene_send
• Mood drift   — Lola's performance mood contagion fires after each song
• Random events — random_pick fires atmospheric surprises each turn
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID  = "lounge"
LOLA_ID   = "lola"
VIKTOR_ID = "viktor"

# ══════════════════════════════════════════════════════════════════════
#  COCKTAIL MENU
# ══════════════════════════════════════════════════════════════════════

COCKTAILS: Dict[str, Dict[str, Any]] = {
    "gin_fizz": {
        "name"       : "Gin Fizz",
        "price"      : 2,
        "description": "Sparkling, tart. A good opener. Viktor shakes it without asking.",
        "trust_req"  : 0,
        "stat_effects": {
            "openness"  : 8,
            "happiness" : 5,
            "inhibition": -3,
        },
        "note": "The bubbles hit. You feel lighter in your chair.",
        "viktor_line": "Starts everyone with a Gin Fizz. That's what he does.",
    },
    "negroni": {
        "name"       : "Negroni",
        "price"      : 3,
        "description": "Bitter, warm, complex. A thinking person's drink.",
        "trust_req"  : 0,
        "stat_effects": {
            "arousal"   : 5,
            "openness"  : 12,
            "inhibition": -5,
        },
        "note": "Slow warmth moves from your sternum outward. The room gets more interesting.",
        "viktor_line": "Nods once when you order it. A quiet approval.",
    },
    "dark_rum": {
        "name"       : "Dark & Stormy",
        "price"      : 3,
        "description": "Bold. Storm in a glass. People who order this have already decided something.",
        "trust_req"  : 0,
        "stat_effects": {
            "confidence" : 15,
            "inhibition" : -10,
            "happiness"  : 5,
        },
        "note": "A comfortable heat spreads through your chest. Good decisions follow this drink.",
        "viktor_line": "Pours it without ceremony. Some drinks don't need one.",
    },
    "champagne": {
        "name"       : "House Champagne",
        "price"      : 4,
        "description": "Lola only pours this for people she decides she likes.",
        "trust_req"  : 35,
        "stat_effects": {
            "happiness"  : 20,
            "arousal"    : 10,
            "trust"      : 5,
        },
        "note": "Lola catches your eye as she sets it down. Doesn't say a word. Doesn't need to.",
        "viktor_line": "Viktor sets it down and steps away. This one's from Lola.",
        "lola_reaction": True,
    },
    "absinthe": {
        "name"       : "Absinthe Drip",
        "price"      : 5,
        "description": "The green fairy. For the brave or the foolish. Perhaps both.",
        "trust_req"  : 55,
        "stat_effects": {
            "arousal"    : 25,
            "openness"   : 30,
            "inhibition" : -25,
            "happiness"  : 8,
        },
        "note": "The world softens at its edges. You find yourself unexpectedly honest.",
        "viktor_line": "Prepares it in silence. The ritual matters.",
    },
    "bourbon": {
        "name"       : "Viktor's Bourbon",
        "price"      : 6,
        "description": "He doesn't pour this for just anyone. You had to ask. He had to decide.",
        "trust_req"  : 65,
        "stat_effects": {
            "trust"      : 10,
            "arousal"    : 15,
            "inhibition" : -15,
            "confidence" : 10,
        },
        "note": "Viktor pours slowly, without looking at you. There's a story in that bottle he's never told anyone. Maybe tonight.",
        "viktor_line": "Pours two glasses. Keeps one for himself.",
        "viktor_joins": True,
    },
    "water": {
        "name"       : "Cold Water",
        "price"      : 0,
        "description": "Viktor won't judge you. Much.",
        "trust_req"  : 0,
        "stat_effects": {
            "inhibition" : 5,
            "happiness"  : 2,
        },
        "note": "You feel responsible. Viktor gives you a single, measured look. It might be respect.",
        "viktor_line": "Sets it down without comment. But he notices.",
    },
    "the_velvet": {
        "name"       : "The Velvet",
        "price"      : 8,
        "description": "Only Lola knows what goes in it. Guests only. Back-room guests.",
        "trust_req"  : 80,
        "back_room_required": True,
        "stat_effects": {
            "arousal"    : 30,
            "openness"   : 25,
            "trust"      : 15,
            "inhibition" : -30,
            "happiness"  : 15,
        },
        "note": "It tastes like a secret. You feel completely present, completely understood.",
        "viktor_line": "Sets it on the table. Steps back. Lets it speak.",
        "lola_reaction": True,
    },
}

# ══════════════════════════════════════════════════════════════════════
#  STAGE — LOLA'S SONG REPERTOIRE
# ══════════════════════════════════════════════════════════════════════

SONGS: List[Dict[str, Any]] = [
    {
        "id"         : "blue_moon",
        "title"      : "Blue Moon",
        "mood_req"   : 0,
        "duration"   : 180,
        "effects"    : {"arousal": 5, "happiness": 10, "openness": 5},
        "atmosphere" : {"lighting": "dim_blue", "mood": "wistful", "music": "slow_jazz"},
        "note"       : "She sings it like she means every word. The room goes quiet.",
    },
    {
        "id"         : "summertime",
        "title"      : "Summertime",
        "mood_req"   : 0,
        "duration"   : 240,
        "effects"    : {"arousal": 8, "openness": 8, "happiness": 8},
        "atmosphere" : {"lighting": "warm_amber", "mood": "lazy", "music": "blues"},
        "note"       : "Low, slow, inevitable. Three people in the audience stop breathing.",
    },
    {
        "id"         : "after_midnight",
        "title"      : "After Midnight",
        "mood_req"   : 25,
        "duration"   : 200,
        "effects"    : {"arousal": 15, "inhibition": -5, "happiness": 10},
        "atmosphere" : {"lighting": "deep_red", "mood": "heat", "music": "uptempo_jazz"},
        "note"       : "She snaps her fingers twice before she starts. The room wakes up.",
    },
    {
        "id"         : "fever",
        "title"      : "Fever",
        "mood_req"   : 45,
        "duration"   : 210,
        "effects"    : {"arousal": 22, "openness": 15, "happiness": 10, "inhibition": -10},
        "atmosphere" : {"lighting": "single_spot", "mood": "intense", "music": "slow_pulse"},
        "note"       : "She doesn't move much. She doesn't need to.",
    },
    {
        "id"         : "strange_fruit",
        "title"      : "Strange Fruit",
        "mood_req"   : 15,
        "duration"   : 270,
        "effects"    : {"arousal": 0, "openness": 22, "trust": 10, "happiness": 3},
        "atmosphere" : {"lighting": "candlelight", "mood": "somber", "music": "bare_piano"},
        "note"       : "Nobody applauds when she finishes. That's the point.",
    },
    {
        "id"         : "cry_me_a_river",
        "title"      : "Cry Me a River",
        "mood_req"   : 35,
        "duration"   : 195,
        "effects"    : {"arousal": 12, "openness": 18, "trust": 15, "happiness": 5},
        "atmosphere" : {"lighting": "warm_low", "mood": "intimate", "music": "classic_jazz"},
        "note"       : "She sings it to the room, but somehow you feel she's singing it at you.",
    },
    {
        "id"         : "come_undone",
        "title"      : "Come Undone",
        "mood_req"   : 65,
        "duration"   : 220,
        "effects"    : {"arousal": 30, "openness": 20, "inhibition": -20, "trust": 10},
        "atmosphere" : {"lighting": "dark_warm", "mood": "electric", "music": "slow_burn"},
        "trust_boost_for_all": True,
        "note"       : "The whole room leans in. Even Viktor stops what he's doing.",
    },
]

# ══════════════════════════════════════════════════════════════════════
#  SECRETS — unlocked at trust thresholds
# ══════════════════════════════════════════════════════════════════════

LOLA_SECRETS: List[Dict[str, Any]] = [
    {
        "id"         : "real_name",
        "trust_req"  : 40,
        "title"      : "Her Real Name",
        "content"    : (
            "Her name isn't Lola. That was her grandmother's name. She borrowed it "
            "the night she left home and never gave it back. She doesn't offer the real one."
        ),
        "effect"     : {"trust": 8, "affection": 10},
    },
    {
        "id"         : "how_she_got_the_bar",
        "trust_req"  : 55,
        "title"      : "How She Got the Lounge",
        "content"    : (
            "She won it in a card game. The man who lost it still comes in occasionally. "
            "She lets him sit in the back because he used to be kind, before everything. "
            "Viktor hates him. She doesn't disagree."
        ),
        "effect"     : {"trust": 10, "openness": 15},
    },
    {
        "id"         : "viktor_story",
        "trust_req"  : 70,
        "title"      : "About Viktor",
        "content"    : (
            "Viktor was a surgeon. Good one. She doesn't know exactly what happened — "
            "he appeared at her back door one winter with a bruised face and very steady hands "
            "and asked if she needed a bartender. She said yes. Neither of them has looked backward since."
        ),
        "effect"     : {"trust": 15, "affection": 12},
    },
    {
        "id"         : "lola_loves",
        "trust_req"  : 85,
        "title"      : "What She Loves",
        "content"    : (
            "She loves the hour before opening. The empty room, the good glasses, "
            "Viktor running through stocks at the far end of the bar. She's built "
            "something real here. She doesn't say that. But you'd see it, if you watched "
            "the way she touches the bar rail when she thinks no one's looking."
        ),
        "effect"     : {"trust": 20, "affection": 25, "arousal": 10},
    },
]

VIKTOR_SECRETS: List[Dict[str, Any]] = [
    {
        "id"         : "why_he_bartends",
        "trust_req"  : 50,
        "title"      : "Why He Bartends",
        "content"    : (
            "He says it's because the hours suit him. That's not quite true. "
            "The truth is that he can tell a lot about a person by what they order "
            "and how they sit, and there aren't many places left where you can watch "
            "people that carefully without them noticing."
        ),
        "effect"     : {"trust": 8, "openness": 12},
    },
    {
        "id"         : "viktor_lola",
        "trust_req"  : 75,
        "title"      : "Viktor and Lola",
        "content"    : (
            "He'd do anything for her. He doesn't say it like that — he says \"she runs a good bar\" "
            "and \"she pays on time\" — but you've watched him watch the room when she's on stage, "
            "and there's nothing casual about it."
        ),
        "effect"     : {"trust": 12, "affection": 15},
    },
]

# ══════════════════════════════════════════════════════════════════════
#  RANDOM EVENTS
# ══════════════════════════════════════════════════════════════════════

RANDOM_EVENTS: List[Dict[str, Any]] = [
    {
        "id"       : "piano_wrong_note",
        "weight"   : 20,
        "text"     : "The pianist hits a single wrong note. Lola pauses mid-phrase, one eyebrow up. The pianist blanches. She finishes the song perfectly.",
        "effects"  : {},
    },
    {
        "id"       : "phone_rings",
        "weight"   : 15,
        "text"     : "The telephone behind the bar rings. Viktor answers it, listens, says nothing, hangs up. He doesn't explain. He never does.",
        "effects"  : {"heat": 5},
        "viktor_internal": "Sends an internal message: 'May be a problem. Watching.'",
    },
    {
        "id"       : "mystery_patron",
        "weight"   : 12,
        "text"     : "A figure sits down two stools away without ordering. Viktor watches them. They watch Lola. Nobody says anything yet.",
        "effects"  : {"heat": 3, "tension_up": True},
    },
    {
        "id"       : "lola_glances",
        "weight"   : 25,
        "text"     : "Lola, still on stage, looks directly at you mid-song. Not at the room. At you. For one full measure.",
        "effects"  : {"arousal": 8, "trust": 3},
    },
    {
        "id"       : "spilled_drink",
        "weight"   : 18,
        "text"     : "Someone across the room knocks their glass over. Viktor rights it with one hand without looking up from the glass he's polishing.",
        "effects"  : {},
    },
    {
        "id"       : "cigarette_smoke",
        "weight"   : 20,
        "text"     : "A curl of cigarette smoke drifts into the single spotlight. For a moment, the room looks like a photograph.",
        "effects"  : {"openness": 3},
    },
    {
        "id"       : "famous_patron",
        "weight"   : 8,
        "text"     : "A well-dressed couple arrives — someone clearly does not want to be recognised. Viktor seats them in the back without comment.",
        "effects"  : {"heat": 2, "trust": 5},
    },
    {
        "id"       : "lola_laughs",
        "weight"   : 15,
        "text"     : "Between songs Lola laughs at something the pianist said. It's an unguarded laugh, different from her stage persona. The room smiles without knowing why.",
        "effects"  : {"happiness": 10, "arousal": 5},
    },
    {
        "id"       : "heat_warning",
        "weight"   : 10,
        "min_heat" : 60,
        "text"     : "Viktor leans across the bar without preamble: 'There are two cars parked outside that haven't moved.' He returns to polishing glasses.",
        "effects"  : {"heat": 8},
        "viktor_internal": "Cross-scene: sending heat warning to Lola.",
    },
]

# ══════════════════════════════════════════════════════════════════════
#  MCP RULES DEFINITIONS
# ══════════════════════════════════════════════════════════════════════

_RULES: List[Dict[str, Any]] = [
    # ── Access gates ────────────────────────────────────────────────
    {
        "id"         : "back_room_gate",
        "label"      : "Back Room Access",
        "description": "The back room is accessed only by guests with trust ≥ 70. "
                       "Viktor will not acknowledge it exists until then.",
        "rule_type"  : "triggered",
        "condition"  : {"stat_thresholds": {"trust": 70}},
        "effects"    : [
            {"effect_type": "state_set", "params": {"field": "back_room_unlocked", "value": True}},
            {"effect_type": "add_narrative", "params": {
                "event": "Viktor gives you a single look, then tilts his head toward the back. He doesn't have to say it twice.",
                "scene_id": SCENE_ID,
            }},
            {"effect_type": "scene_event", "params": {"event_type": "back_room_unlocked"}},
        ],
    },
    {
        "id"         : "champagne_gate",
        "label"      : "House Champagne Available",
        "description": "Lola will only offer house champagne to someone she likes. Requires trust ≥ 35.",
        "rule_type"  : "triggered",
        "condition"  : {"stat_thresholds": {"trust": 35}},
        "effects"    : [
            {"effect_type": "state_set", "params": {"field": "champagne_available", "value": True}},
        ],
    },
    {
        "id"         : "lola_song_escalation",
        "label"      : "Lola Sings Intensely",
        "description": "When the room's arousal is elevated, Lola chooses her more intense repertoire.",
        "rule_type"  : "triggered",
        "condition"  : {"stat_thresholds": {"arousal": 50}},
        "effects"    : [
            {"effect_type": "state_set",    "params": {"field": "song_tier", "value": "intense"}},
            {"effect_type": "set_directive","params": {
                "directive_type": "style_lock",
                "value"         : "charged",
                "turns"         : 2,
            }},
        ],
    },
    # ── HEAT rules ──────────────────────────────────────────────────
    {
        "id"         : "heat_warning_rule",
        "label"      : "Heat Warning",
        "description": "When heat ≥ 65, Viktor warns quietly and dims lights. Code words start.",
        "rule_type"  : "triggered",
        "condition"  : {"stat_thresholds": {"heat_level": 65}},
        "effects"    : [
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "dim_warm", "mood": "guarded",
            }},
            {"effect_type": "add_narrative", "params": {
                "event": "Viktor dims the lights two notches. He doesn't explain. He doesn't need to.",
                "scene_id": SCENE_ID,
            }},
            {"effect_type": "scene_event",   "params": {"event_type": "heat_warning"}},
        ],
    },
    {
        "id"         : "heat_critical_rule",
        "label"      : "Critical Heat — Lockdown",
        "description": "At heat ≥ 85 the lounge enters silent lockdown. Lola stops performing. Viktor locks the door.",
        "rule_type"  : "triggered",
        "condition"  : {"stat_thresholds": {"heat_level": 85}},
        "effects"    : [
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "dark_amber", "mood": "tense", "music": "silence",
            }},
            {"effect_type": "state_set",     "params": {"field": "performance_paused", "value": True}},
            {"effect_type": "add_restriction","params": {"restriction": "no_loud_actions"}},
            {"effect_type": "scene_event",   "params": {"event_type": "lockdown_triggered"}},
            {"effect_type": "add_narrative", "params": {
                "event": "Lola stops mid-phrase. Viktor moves to the door without a word. The room holds its breath.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id"         : "heat_clear_rule",
        "label"      : "Heat Clears",
        "description": "When heat drops below 40, back to normal operation.",
        "rule_type"  : "triggered",
        "condition"  : {"stat_thresholds": {}},   # checked manually
        "effects"    : [
            {"effect_type": "state_set",     "params": {"field": "performance_paused", "value": False}},
            {"effect_type": "remove_restriction", "params": {"restriction": "no_loud_actions"}},
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "warm_amber", "mood": "relaxed", "music": "jazz",
            }},
            {"effect_type": "scene_event",   "params": {"event_type": "heat_cleared"}},
        ],
    },
    # ── Director rules ───────────────────────────────────────────────
    {
        "id"         : "director_encore",
        "label"      : "Force Encore",
        "description": "Director forces Lola to perform an immediate encore of the current song.",
        "rule_type"  : "director_only",
        "effects"    : [
            {"effect_type": "state_set", "params": {"field": "encore_queued", "value": True}},
            {"effect_type": "scene_event", "params": {"event_type": "encore_queued"}},
            {"effect_type": "set_directive","params": {
                "directive_type": "must_include",
                "value"         : "takes a quiet breath and begins again",
                "turns"         : 1,
            }},
        ],
    },
    {
        "id"         : "director_close_bar",
        "label"      : "Close Bar Early",
        "description": "Director ends the night — no more drinks, fade lights, last song.",
        "rule_type"  : "director_only",
        "effects"    : [
            {"effect_type": "state_set", "params": {"field": "bar_closed", "value": True}},
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "fading", "mood": "closing", "music": "last_song",
            }},
            {"effect_type": "set_directive","params": {
                "directive_type": "style_lock",
                "value"         : "warm",
                "turns"         : 3,
            }},
        ],
    },
]

# ══════════════════════════════════════════════════════════════════════
#  LOUNGE ACTIONS
# ══════════════════════════════════════════════════════════════════════

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id"           : "order_drink",
        "label"        : "Order a Drink",
        "description"  : "Order from Viktor. What you choose says something about you.",
        "intimacy_level": 1,
        "condition"    : {},
        "effects"      : [{"effect_type": "scene_event", "params": {"event_type": "drink_ordered"}}],
    },
    {
        "id"           : "request_song",
        "label"        : "Request a Song",
        "description"  : "Ask Lola for a specific song. She may or may not oblige.",
        "intimacy_level": 1,
        "condition"    : {},
        "effects"      : [{"effect_type": "scene_event", "params": {"event_type": "song_requested"}}],
    },
    {
        "id"           : "talk_to_lola",
        "label"        : "Talk to Lola",
        "description"  : "Approach Lola between sets. She notices everyone. Not everyone gets a conversation.",
        "intimacy_level": 2,
        "condition"    : {},
        "effects"      : [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",  "delta": 5}},
            {"effect_type": "stat_adjust", "params": {"stat": "trust",    "delta": 3}},
        ],
    },
    {
        "id"           : "talk_to_viktor",
        "label"        : "Talk to Viktor",
        "description"  : "Have a conversation with Viktor. He's harder to reach than Lola, but worth it.",
        "intimacy_level": 2,
        "condition"    : {},
        "effects"      : [
            {"effect_type": "stat_adjust", "params": {"stat": "trust",    "delta": 5}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness", "delta": 5}},
        ],
    },
    {
        "id"           : "ask_secret",
        "label"        : "Ask About Something Personal",
        "description"  : "Pry gently — secrets are earned here, not taken.",
        "intimacy_level": 3,
        "condition"    : {"stat_thresholds": {"trust": 30}},
        "effects"      : [
            {"effect_type": "scene_event", "params": {"event_type": "secret_requested"}},
        ],
    },
    {
        "id"           : "enter_back_room",
        "label"        : "Enter the Back Room",
        "description"  : "Beyond the curtain. Not everyone is invited.",
        "intimacy_level": 4,
        "condition"    : {"character_flags": {"back_room_unlocked": True}},
        "effects"      : [
            {"effect_type": "stat_adjust",  "params": {"stat": "arousal",    "delta": 10}},
            {"effect_type": "stat_adjust",  "params": {"stat": "trust",      "delta": 8}},
            {"effect_type": "stat_adjust",  "params": {"stat": "inhibition", "delta": -10}},
            {"effect_type": "set_atmosphere","params": {
                "scene_id": SCENE_ID, "lighting": "candlelight", "mood": "private", "music": "soft_piano",
            }},
            {"effect_type": "scene_event",  "params": {"event_type": "back_room_entered"}},
        ],
    },
    {
        "id"           : "buy_lola_drink",
        "label"        : "Buy Lola a Drink",
        "description"  : "Send one to the stage through Viktor. Whether she accepts is her business.",
        "intimacy_level": 2,
        "condition"    : {"stat_thresholds": {"trust": 20}},
        "effects"      : [
            {"effect_type": "stat_adjust", "params": {"stat": "trust",   "delta": 8}},
            {"effect_type": "stat_adjust", "params": {"stat": "arousal", "delta": 5}},
            {"effect_type": "scene_event", "params": {"event_type": "drink_sent_to_lola"}},
        ],
    },
    {
        "id"           : "leave_tip",
        "label"        : "Leave a Generous Tip",
        "description"  : "Viktor remembers generosity. So does Lola.",
        "intimacy_level": 1,
        "condition"    : {},
        "effects"      : [
            {"effect_type": "stat_adjust", "params": {"stat": "trust",     "delta": 6}},
            {"effect_type": "stat_adjust", "params": {"stat": "happiness", "delta": 5}},
        ],
    },
]

# ══════════════════════════════════════════════════════════════════════
#  LOUNGE CHARACTERS (pre-configured for CharacterRegistry)
# ══════════════════════════════════════════════════════════════════════

LOLA_PROFILE = {
    "name"       : "Lola Voss",
    "age"        : 32,
    "appearance" : {
        "hair"   : "dark auburn, pinned loosely",
        "eyes"   : "hazel, heavy-lidded",
        "build"  : "lithe, commanding",
        "style"  : "1920s gown, always something backless, always something gold",
    },
    "personality": {
        "warmth"       : 0.75,
        "intelligence" : 0.90,
        "assertiveness": 0.85,
        "mystery"      : 0.90,
        "playfulness"  : 0.60,
        "vulnerability": 0.40,   # earned, not given
    },
    "backstory": (
        "She runs this place like a chess game she's already won. "
        "She sings because she has to — if she stopped, something in her would too. "
        "She's kind in ways she'd deny if you pointed them out."
    ),
    "voice_style": (
        "Low, precise. Phrases constructed like architecture. "
        "Warmth appears in details — the specific word she chose, not a broad stroke. "
        "She doesn't explain herself. She doesn't apologise. "
        "When she's amused, she doesn't quite smile."
    ),
}

VIKTOR_PROFILE = {
    "name"       : "Viktor Marlowe",
    "age"        : 44,
    "appearance" : {
        "hair"   : "salt-and-pepper, close-cropped",
        "eyes"   : "grey-blue, still",
        "build"  : "broad-shouldered, economical movements",
        "style"  : "white shirt, braces, always a clean towel over one shoulder",
    },
    "personality": {
        "warmth"       : 0.65,
        "intelligence" : 0.88,
        "assertiveness": 0.70,
        "mystery"      : 0.75,
        "steadiness"   : 0.95,
        "loyalty"      : 0.98,
    },
    "backstory": (
        "Former surgeon. Doesn't talk about it. "
        "He came to Lola with bruised ribs and steady hands and she hired him without asking. "
        "That was eleven years ago. He's still here. "
        "He observes everything and says almost nothing until it counts."
    ),
    "voice_style": (
        "Sparse. Deliberate. He speaks in complete, unhurried sentences and stops exactly when finished. "
        "No filler, no hedging. When he tells you something, it stays with you. "
        "Dry humour arrives without announcement. "
        "More is said in what he doesn't say."
    ),
}

# Skills Lola has
LOLA_SKILLS = [
    {
        "skill_id"  : "dream_whisper_skill",
        "skill_type": "custom",
        "label"     : "Dream Whisper",
        "params"    : {"target": "viktor", "default_duration": 2},
        "enabled"   : True,
        "trigger"   : "optional",
    },
    {
        "skill_id"  : "mirror_soul_skill",
        "skill_type": "custom",
        "label"     : "Mirror Soul",
        "params"    : {},
        "enabled"   : True,
        "trigger"   : "optional",
    },
    {
        "skill_id"  : "time_echo_skill",
        "skill_type": "custom",
        "label"     : "Time Echo",
        "params"    : {},
        "enabled"   : True,
        "trigger"   : "optional",
    },
    {
        "skill_id"  : "mood_influence",
        "skill_type": "mood_influence",
        "label"     : "Stage Presence",
        "params"    : {"radius": "scene", "intensity": 0.7},
        "enabled"   : True,
        "trigger"   : "auto",
    },
]

# Skills Viktor has
VIKTOR_SKILLS = [
    {
        "skill_id"  : "memory_recall",
        "skill_type": "memory_recall",
        "label"     : "Recall",
        "params"    : {"top_k": 5, "min_score": 0.3},
        "enabled"   : True,
        "trigger"   : "auto",
    },
    {
        "skill_id"  : "time_echo_skill",
        "skill_type": "custom",
        "label"     : "Time Echo",
        "params"    : {},
        "enabled"   : True,
        "trigger"   : "optional",
    },
    {
        "skill_id"  : "dream_whisper_skill",
        "skill_type": "custom",
        "label"     : "Dream Whisper",
        "params"    : {"target": "lola", "default_duration": 2},
        "enabled"   : True,
        "trigger"   : "optional",
    },
]

# ══════════════════════════════════════════════════════════════════════
#  INITIALISATION
# ══════════════════════════════════════════════════════════════════════

def register_lounge_rules() -> None:
    """
    Called once from LoungeScene.__init__ after _mcp_init().

    Registers all lounge rules, actions, characters, and initial state
    into the MCPFramework.  Safe to call multiple times — guarded.
    """
    try:
        from engine.mcp.scene_rules_engine import (
            get_rules_engine, ActionDefinition, RuleDefinition,
            RuleEffect, RuleCondition,
        )
        from engine.mcp.scene_state import get_scene_state_manager
        from engine.mcp.character_registry import get_character_registry
        from engine.mcp.framework import get_framework

        eng = get_rules_engine()
        ssm = get_scene_state_manager()
        reg = get_character_registry()
        fw  = get_framework()

        # Guard — only register once
        existing = eng.get_rules(SCENE_ID)
        if existing:
            logger.debug("Lounge rules already registered — skipping.")
            return

        # ── Register rules ──────────────────────────────────────────────────
        for r in _RULES:
            cond_data = r.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None
            effects = [RuleEffect(**e) for e in r.get("effects", [])]
            eng.add_rule(SCENE_ID, RuleDefinition(
                rule_id     = r["id"],
                label       = r["label"],
                description = r["description"],
                rule_type   = r["rule_type"],
                condition   = condition,
                effects     = effects,
            ))

        # ── Register actions ────────────────────────────────────────────────
        for a in _ACTIONS:
            cond_data = a.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None
            effects = [RuleEffect(**e) for e in a.get("effects", [])]
            eng.add_action(SCENE_ID, ActionDefinition(
                action_id       = a["id"],
                label           = a["label"],
                description     = a["description"],
                intimacy_level  = a.get("intimacy_level", 1),
                condition       = condition,
                effects         = effects,
            ))

        # ── Register Lola ───────────────────────────────────────────────────
        p = LOLA_PROFILE
        reg.register(
            LOLA_ID,
            name        = p["name"],
            age         = p["age"],
            appearance  = p["appearance"],
            personality = p["personality"],
            backstory   = p["backstory"],
            voice_style = p["voice_style"],
        )
        for sk in LOLA_SKILLS:
            reg.assign_skill(
                LOLA_ID,
                skill_id   = sk["skill_id"],
                skill_type = sk["skill_type"],
                label      = sk["label"],
                params     = sk["params"],
                enabled    = sk["enabled"],
                trigger    = sk["trigger"],
            )
        reg.set_state(LOLA_ID, mood="performing", mood_intensity=0.8)
        fw.get_character(LOLA_ID).enter_scene(SCENE_ID)

        # ── Register Viktor ─────────────────────────────────────────────────
        p = VIKTOR_PROFILE
        reg.register(
            VIKTOR_ID,
            name        = p["name"],
            age         = p["age"],
            appearance  = p["appearance"],
            personality = p["personality"],
            backstory   = p["backstory"],
            voice_style = p["voice_style"],
        )
        for sk in VIKTOR_SKILLS:
            reg.assign_skill(
                VIKTOR_ID,
                skill_id   = sk["skill_id"],
                skill_type = sk["skill_type"],
                label      = sk["label"],
                params     = sk["params"],
                enabled    = sk["enabled"],
                trigger    = sk["trigger"],
            )
        reg.set_state(VIKTOR_ID, mood="watchful", mood_intensity=0.6)
        fw.get_character(VIKTOR_ID).enter_scene(SCENE_ID)

        # ── Initial atmosphere ──────────────────────────────────────────────
        ssm.set_atmosphere(
            SCENE_ID,
            lighting = "warm_amber",
            mood     = "jazz_night",
            music    = "live_piano",
        )

        # ── Initial narrative ────────────────────────────────────────────────
        ssm.add_narrative(
            SCENE_ID, "scene",
            "The Velvet Lounge opens its doors for the night. "
            "Lola takes the stage as Viktor polishes the first glass of the evening.",
        )

        logger.info(
            "Lounge MCP rules registered: %d rules, %d actions, 2 characters.",
            len(_RULES), len(_ACTIONS),
        )

    except Exception as exc:
        logger.warning("register_lounge_rules failed: %s", exc)


def get_cocktail(drink_id: str) -> Optional[Dict[str, Any]]:
    return COCKTAILS.get(drink_id)


def get_all_cocktails(trust_level: int = 0) -> List[Dict[str, Any]]:
    """Return cocktails available for the given trust level."""
    return [
        {"id": k, **v}
        for k, v in COCKTAILS.items()
        if v.get("trust_req", 0) <= trust_level and not v.get("back_room_required", False)
    ]


def get_song_by_mood(lola_mood_score: int = 0) -> Optional[Dict[str, Any]]:
    """Pick the highest-mood-req song that Lola's current mood allows."""
    eligible = [s for s in SONGS if s["mood_req"] <= lola_mood_score]
    if not eligible:
        eligible = SONGS[:1]
    # Prefer higher mood_req songs
    return sorted(eligible, key=lambda s: s["mood_req"], reverse=True)[0]


def get_available_secrets(
    character: str,
    trust_level: int,
) -> List[Dict[str, Any]]:
    """Return not-yet-told secrets for character at the current trust level."""
    pool = LOLA_SECRETS if character == LOLA_ID else VIKTOR_SECRETS
    return [s for s in pool if s["trust_req"] <= trust_level]


def pick_random_event(heat_level: int = 0) -> Dict[str, Any]:
    """Weighted random pick from RANDOM_EVENTS, respecting heat requirements."""
    import random
    eligible = [e for e in RANDOM_EVENTS if heat_level >= e.get("min_heat", 0)]
    if not eligible:
        eligible = RANDOM_EVENTS
    weights = [e.get("weight", 10) for e in eligible]
    return random.choices(eligible, weights=weights, k=1)[0]


# Need Optional import
from typing import Optional
