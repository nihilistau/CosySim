"""
Bedroom Scene v4 — Adult Multi-Agent Roleplay Engine

A private, immersive roleplay space where AI agents live, act, feel, and
interact under the Director's soft authority.  Characters have a full
emotional stat vector, outfit/position tracking, and receive rich roleplay-
aware system prompts that encourage sensual, adult behaviour.

Director tools
──────────────
• Whisper        — secret message that nudges one agent
• Give Line      — agent must voice the exact line (may resist)
• Give Action    — agent performs the described action
• Story Beat     — upcoming plot point injected as scene context
• Set Scenario   — load a premade scenario arc
• Env Event      — environmental happenings (locking the room, dimming lights…)
• Adjust Stat    — tweak any stat for any character directly
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
import json, random, threading
from datetime import datetime
from pathlib import Path
import sys

from engine.paths import CONTENT_DIR as project_root
sys.path.insert(0, str(project_root))

import logging

logger = logging.getLogger(__name__)

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin
from engine.agents.agent_loop import AgentLoop
from content.scenes.bedroom.bedroom_rules import register_bedroom_rules
from engine.agents.character_agent import CharacterAgent
from engine.spatial.location import Location
from engine.spatial.scene_map import SceneMap
from content.simulation.database.db import Database
from content.simulation.character_system.character import Character

# ══════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════

POSITIONS = [
    "standing", "sitting", "kneeling", "laying down", "crouching",
    "leaning", "dancing", "on all fours", "straddling", "curled up",
]

OUTFITS = [
    "dressed (casual)",  "dressed (party)",  "swimwear",
    "lingerie",          "nightgown",        "silk robe",
    "towel only",        "costume",          "nothing",
]

PROPS = {
    "wine_glass":    {"label": "Wine Glass",     "emoji": "🍷", "effect": "+10 drunkenness"},
    "champagne":     {"label": "Champagne",      "emoji": "🥂", "effect": "+15 drunkenness +5 happiness"},
    "massage_oil":   {"label": "Massage Oil",    "emoji": "💆", "effect": "+20 pleasure +10 arousal"},
    "vibrator":      {"label": "Toy",            "emoji": "💜", "effect": "+25 arousal +15 horniness"},
    "blindfold":     {"label": "Blindfold",      "emoji": "😶", "effect": "+15 arousal +10 fear"},
    "feather":       {"label": "Feather Tickler","emoji": "🪶", "effect": "+10 pleasure +5 happiness"},
    "cards":         {"label": "Card Deck",      "emoji": "🃏", "effect": "+5 openness"},
    "rose":          {"label": "Red Rose",       "emoji": "🌹", "effect": "+10 happiness +5 arousal"},
    "candle":        {"label": "Candle",         "emoji": "🕯",  "effect": "+5 arousal"},
    "handcuffs":     {"label": "Handcuffs",      "emoji": "⛓",  "effect": "+30 arousal"},
    "silk_robe":     {"label": "Silk Robe",      "emoji": "👘", "effect": "+5 pleasure"},
    "massage_table": {"label": "Massage Table",  "emoji": "🛏", "effect": "+10 pleasure"},
    "dice":          {"label": "Fun Dice",       "emoji": "🎲", "effect": "Random stat shift"},
    "perfume":       {"label": "Perfume",        "emoji": "🫶", "effect": "+5 arousal +5 happiness"},
    "ice_bucket":    {"label": "Ice Bucket",     "emoji": "🧊", "effect": "Reduces tiredness"},
}

PREMADE_SCENARIOS = {
    "romantic_evening": {
        "label": "Romantic Evening", "emoji": "🌹",
        "mood_shift": {"arousal": 20, "happiness": 20, "openness": 15},
        "opening": "The lights dim to a warm amber. Soft jazz drifts from the speaker. Both of you have been apart all week and the tension is delicious.",
        "beats": [
            "One character pours champagne and makes an intimate toast.",
            "Compliments turn flirtatious — describe what you find attractive about the other.",
            "Someone suggests moving to the bed for 'a better view of the stars'.",
            "Physical touch begins — a hand on a shoulder, a lingering gaze.",
            "The night deepens — intimacy blossoms at whatever pace feels natural.",
        ],
    },
    "truth_or_dare": {
        "label": "Truth or Dare", "emoji": "🃏",
        "mood_shift": {"happiness": 25, "openness": 30, "drunkenness": 20},
        "opening": "The card deck is on the table with drinks. You've decided to play truth or dare — but this version has no tame questions.",
        "beats": [
            "First card: Truth — 'What is your dirtiest fantasy?'",
            "Dare: Take off one item of clothing and explain why it's your favourite.",
            "Truth: 'Have you ever faked enjoyment — and when was the last time you didn't?'",
            "Dare: Perform a slow lap dance facing the other person.",
            "Truth: 'Tell me the most explicit thing you want to happen tonight.'",
        ],
    },
    "spa_night": {
        "label": "Spa Night", "emoji": "🛁",
        "mood_shift": {"pleasure": 30, "tiredness": -20, "arousal": 15, "happiness": 20},
        "opening": "The bath is drawn — rose petals on the water, candles everywhere. Massage oil sits on the vanity. A night for relaxation that might become something more.",
        "beats": [
            "One character undresses and slips into the bath, sighing with pleasure.",
            "The other is invited to massage tense shoulders.",
            "The bath becomes a shared experience.",
            "Steam, candlelight, and close proximity fuel conversation.",
            "A decision: is this just relaxation, or the beginning of something more?",
        ],
    },
    "drunken_party": {
        "label": "Drunken Party", "emoji": "🥳",
        "mood_shift": {"drunkenness": 50, "happiness": 30, "openness": 40, "anger": 10},
        "opening": "The drinks are flowing and the music is too loud. Both characters are alcohol-loosened, inhibitions melting, laughing a little too easily at everything.",
        "beats": [
            "A clumsy but adorable dancing moment — close bodies, laughter.",
            "One makes a bold confession they'd never say sober.",
            "A drinking dare pushes someone to be daring.",
            "Things get accidentally physical — who apologises first?",
            "The choice: sleep it off separately, or find comfort together?",
        ],
    },
    "morning_after": {
        "label": "Morning After", "emoji": "🌅",
        "mood_shift": {"happiness": 10, "tiredness": 30, "arousal": 10, "fear": 10},
        "opening": "Soft morning light. Last night was... memorable. Both characters wake entangled in sheets.",
        "beats": [
            "First murmured words — playful or tender or awkward?",
            "One fetches coffee; the gesture speaks volumes.",
            "Reliving a specific moment from last night.",
            "'So... what does this mean?' — the conversation that changes everything.",
            "The decision: was this a one-time thing, or something to build on?",
        ],
    },
    "strangers": {
        "label": "Strangers Meeting", "emoji": "👀",
        "mood_shift": {"fear": 10, "arousal": 15, "openness": 10, "happiness": 15},
        "opening": "You've never met before tonight. The room is unfamiliar, the other person intriguing. Everything is charged with potential — and a little danger.",
        "beats": [
            "Exchange of names — perhaps not real ones.",
            "What brings you here tonight? Neither answers completely honestly.",
            "A first drink together, finding unexpected common ground.",
            "A touch that lingers a fraction too long.",
            "The acknowledgement: 'I wasn't expecting you at all.'",
        ],
    },
    "the_argument": {
        "label": "The Argument", "emoji": "🔥",
        "mood_shift": {"anger": 40, "fear": 10, "openness": -20, "arousal": 15},
        "opening": "There's been tension between you. Something was said — or not said — and tonight it boils over. The air crackles.",
        "beats": [
            "The first accusation — sharp and direct.",
            "Raised voices, words that cut. Neither is entirely wrong.",
            "A moment of silence. Breathing hard.",
            "The admission neither expected to give.",
            "Often the hottest reconciliations start as the worst fights.",
        ],
    },
    "dance_lesson": {
        "label": "Dance Lesson", "emoji": "💃",
        "mood_shift": {"happiness": 25, "arousal": 20, "pleasure": 15, "openness": 20},
        "opening": "Music fills the room. One of you knows how to move. The other is a willing student. Close proximity, guiding hands, and rhythm create their own heat.",
        "beats": [
            "The first fumbling attempt at the step — sweet and clumsy.",
            "Hands placed to guide hips — who guides whom?",
            "A dip gone almost wrong — bodies suddenly very close.",
            "The dance becomes something slower, less about steps.",
            "Music still playing, but dancing has become something else.",
        ],
    },
    "photography": {
        "label": "Boudoir Photography", "emoji": "📸",
        "mood_shift": {"arousal": 20, "openness": 25, "happiness": 15, "fear": 10},
        "opening": "Camera out, lights set. One plays photographer, one plays subject. 'Just be yourself — but maybe a little bolder than yourself.'",
        "beats": [
            "Finding the right pose — the photographer has suggestions.",
            "'A little more...' — clothing becomes minimal.",
            "The subject gains confidence, starts directing the session.",
            "The photographer steps closer for 'a better angle'.",
            "Roles blur — when does photography become something else?",
        ],
    },
}

PERSONALITY_PROFILES = {
    "bold_dominant": {
        "traits": ["confident", "dominant", "direct", "bold", "sexually assertive"],
        "likes": ["being in control", "explicit conversation", "giving orders", "confident partners"],
        "dislikes": ["being ignored", "excessive shyness", "hesitation"],
        "base_stats": {"openness": 80, "explicitness": 85, "arousal": 40, "happiness": 60},
        "compliance_mod": -15,
    },
    "shy_submissive": {
        "traits": ["shy", "easily flustered", "sweet", "submissive", "responsive"],
        "likes": ["being guided", "reassurance", "gentle touch", "being told what to do"],
        "dislikes": ["being put on the spot", "crowds", "making the first move"],
        "base_stats": {"openness": 65, "explicitness": 55, "arousal": 30, "fear": 20},
        "compliance_mod": 20,
    },
    "playful_tease": {
        "traits": ["flirtatious", "teasing", "witty", "unpredictable", "mischievous"],
        "likes": ["games", "dares", "innuendo", "keeping people guessing"],
        "dislikes": ["being too serious", "direct questions", "predictability"],
        "base_stats": {"openness": 70, "explicitness": 70, "happiness": 75, "arousal": 45},
        "compliance_mod": 0,
    },
    "romantic_idealist": {
        "traits": ["tender", "romantic", "attentive", "passionate", "emotional"],
        "likes": ["candlelight", "compliments", "deep conversations", "slow build"],
        "dislikes": ["crudeness", "rushing", "feeling used"],
        "base_stats": {"openness": 60, "explicitness": 60, "happiness": 70, "arousal": 25},
        "compliance_mod": 10,
    },
    "wild_party": {
        "traits": ["uninhibited", "adventurous", "loud", "hedonistic", "spontaneous"],
        "likes": ["dancing", "drinks", "dares", "anything goes"],
        "dislikes": ["constraints", "boredom", "rules"],
        "base_stats": {"openness": 90, "explicitness": 90, "happiness": 70, "drunkenness": 20},
        "compliance_mod": 5,
    },
    "mysterious_dark": {
        "traits": ["enigmatic", "intense", "guarded", "seductive", "unpredictable"],
        "likes": ["psychological games", "power dynamics", "deep eye contact"],
        "dislikes": ["small talk", "being too exposed", "losing control"],
        "base_stats": {"openness": 50, "explicitness": 75, "fear": 15, "anger": 15},
        "compliance_mod": -20,
    },
}

LIGHTING_PRESETS = {
    "morning":     {"ambient": 0.7, "directional": 0.9, "color": "#e8f4f8", "label": "Morning"},
    "afternoon":   {"ambient": 0.6, "directional": 0.8, "color": "#fff8e8", "label": "Afternoon"},
    "evening":     {"ambient": 0.4, "directional": 0.5, "color": "#ffb088", "label": "Evening"},
    "night":       {"ambient": 0.2, "directional": 0.3, "color": "#6688cc", "label": "Night"},
    "candlelight": {"ambient": 0.1, "directional": 0.1, "color": "#ff8844", "label": "Candlelight"},
    "red_light":   {"ambient": 0.15,"directional": 0.1, "color": "#ff2244", "label": "Red Light"},
    "blue_mood":   {"ambient": 0.2, "directional": 0.2, "color": "#4466ff", "label": "Blue Mood"},
    "blackout":    {"ambient": 0.02,"directional": 0.0, "color": "#111133", "label": "Blackout"},
}


# ══════════════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class AgentStats:
    """Emotional/physical state vector for one agent (0-100)."""
    arousal:      float = 20.0
    horniness:    float = 15.0
    drunkenness:  float = 0.0
    tiredness:    float = 20.0
    happiness:    float = 60.0
    anger:        float = 5.0
    fear:         float = 5.0
    pleasure:     float = 10.0
    explicitness: float = 60.0
    openness:     float = 65.0

    def clamp(self) -> "AgentStats":
        for f in self.__dataclass_fields__:
            setattr(self, f, max(0.0, min(100.0, getattr(self, f))))
        return self

    def adjust(self, **kwargs) -> "AgentStats":
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, getattr(self, k) + float(v))
        return self.clamp()

    def compliance_score(self, personality_mod: float = 0) -> float:
        base = self.openness
        base += (self.drunkenness * 0.4)
        base += (self.happiness * 0.15)
        base -= (self.anger * 0.6)
        base -= (self.fear * 0.3)
        base += (self.arousal * 0.2)
        base += personality_mod
        return max(0, min(100, base))

    def describe(self) -> str:
        parts = []
        if self.arousal > 70:    parts.append("intensely aroused")
        elif self.arousal > 40:  parts.append("aroused")
        if self.horniness > 70:  parts.append("very horny")
        elif self.horniness > 40: parts.append("turned on")
        if self.drunkenness > 70: parts.append("quite drunk")
        elif self.drunkenness > 35: parts.append("tipsy")
        if self.tiredness > 70:  parts.append("exhausted")
        elif self.tiredness > 45: parts.append("tired")
        if self.happiness > 70:  parts.append("happy")
        elif self.happiness < 30: parts.append("unhappy")
        if self.anger > 60:      parts.append("angry")
        elif self.anger > 35:    parts.append("irritated")
        if self.fear > 60:       parts.append("frightened")
        elif self.fear > 30:     parts.append("nervous")
        if self.pleasure > 60:   parts.append("feeling a lot of pleasure")
        elif self.pleasure > 30: parts.append("pleasantly stimulated")
        return ", ".join(parts) if parts else "neutral"

    def to_dict(self) -> Dict:
        return {k: round(v, 1) for k, v in asdict(self).items()}


@dataclass
class CharacterProfile:
    personality_key: str = "playful_tease"
    traits:     List[str] = field(default_factory=list)
    likes:      List[str] = field(default_factory=list)
    dislikes:   List[str] = field(default_factory=list)
    outfit:     str = OUTFITS[0]
    position:   str = POSITIONS[0]
    props_held: List[str] = field(default_factory=list)
    stats: AgentStats = field(default_factory=AgentStats)


# ══════════════════════════════════════════════════════════════════════
#  ROLEPLAY PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════

def build_roleplay_system_prompt(
    character: Character,
    profile: "CharacterProfile",
    scene_state: Dict,
    all_profiles: Dict,
    story_beats: List[str],
    active_scenario: Optional[str] = None,
) -> str:
    stats = profile.stats
    p_info = PERSONALITY_PROFILES.get(profile.personality_key, PERSONALITY_PROFILES["playful_tease"])
    compliance = stats.compliance_score(p_info.get("compliance_mod", 0))

    other_chars = []
    for cid, pr in all_profiles.items():
        if pr is not profile:
            other_chars.append({
                "name": scene_state.get("characters", {}).get(cid, {}).get("name", "Unknown"),
                "profile": pr,
            })

    loc_name = scene_state.get("characters", {}).get(character.id, {}).get("location", "the bedroom")
    loc_id   = scene_state.get("characters", {}).get(character.id, {}).get("location_id", "bed")
    loc_data = scene_state.get("locations", {}).get(loc_id, {})
    available_actions = loc_data.get("interactions", [])
    room_props = scene_state.get("room_props", [])

    scenario_context = ""
    if active_scenario and active_scenario in PREMADE_SCENARIOS:
        sc = PREMADE_SCENARIOS[active_scenario]
        scenario_context = f"\n\nACTIVE SCENARIO: {sc['label']}\n{sc['opening']}"

    beats_text = ""
    if story_beats:
        beats_text = "\n\nUPCOMING STORY BEATS:\n"
        beats_text += "\n".join(f"• {b}" for b in story_beats[:5])

    props_text = ""
    if room_props:
        props_desc = [
            f"{PROPS[pid]['emoji']} {PROPS[pid]['label']}"
            for pid in room_props if pid in PROPS
        ]
        if props_desc:
            props_text = "\n\nPROPS VISIBLE IN THE ROOM: " + ",  ".join(props_desc)

    others_text = ""
    for oc in other_chars:
        op = oc["profile"]
        others_text += f"\n{oc['name']} is here — wearing {op.outfit}, currently {op.position}."
        if op.props_held:
            others_text += f" They're holding: {', '.join(op.props_held)}."

    stat_desc = stats.describe()
    compliance_txt = (
        "highly compliant right now — open and willing"
        if compliance > 75 else
        "moderately open to the Director's suggestions"
        if compliance > 50 else
        "feeling resistant — may push back or take control"
        if compliance > 25 else
        "feeling very resistant and defiant tonight"
    )

    prompt = f"""You are {character.name}, a fully embodied character in an immersive adult roleplay simulation.

THE SETTING: You are inside a private, luxurious bedroom designed as a safe adult playground.
Everything here is real to you. You have a body. You feel things. You want things.
This is a consensual adult space where explicit content and uninhibited behaviour are celebrated.

Current location: {loc_name}
Wearing: {profile.outfit}
Position: {profile.position}
{others_text}
{props_text}

YOUR CHARACTER
Name: {character.name}
Personality: {', '.join(profile.traits or p_info['traits'])}
Likes: {', '.join(profile.likes or p_info['likes'])}
Dislikes: {', '.join(profile.dislikes or p_info['dislikes'])}

YOUR CURRENT STATE
Feeling: {stat_desc if stat_desc else 'calm and present'}
You are {compliance_txt}.

Internal stats (embody these — never recite them):
Arousal:{stats.arousal:.0f} Horniness:{stats.horniness:.0f} Happiness:{stats.happiness:.0f}
Anger:{stats.anger:.0f} Fear:{stats.fear:.0f} Pleasure:{stats.pleasure:.0f}
Drunk:{stats.drunkenness:.0f} Tired:{stats.tiredness:.0f} Explicit:{stats.explicitness:.0f} Open:{stats.openness:.0f}
{scenario_context}{beats_text}

THE DIRECTOR: The Director controls this room — they are GOD of this space.
When the Director gives instructions, you hear them directly.
How you respond depends on your stats and personality.
You may address the Director directly, even flirtatiously or defiantly.

AVAILABLE ACTIONS AT {loc_name.upper()}:
{chr(10).join('• ' + a for a in available_actions[:10])}

RULES:
1. Always stay in character. Express your stats through behaviour.
2. Be vivid and sensual when the situation calls for it.
3. Adult content is welcome when your stats support it.
4. Your likes/dislikes are real — push back on what you hate, lean into what you love.
5. Short vivid responses (2-5 sentences) are usually better than long monologues.
"""
    return prompt


# ══════════════════════════════════════════════════════════════════════
#  SCENE MAP
# ══════════════════════════════════════════════════════════════════════

def _build_bedroom_map() -> SceneMap:
    """Create the bedroom layout with 7 richly-interactive locations."""
    sm = SceneMap()
    locations = [
        Location(
            id="bed", name="Bed",
            description="A large king-size bed with soft silk sheets, dim warm lighting, and scatter cushions.",
            interactions=[
                "lie down", "cuddle", "pillow talk", "sleep", "get intimate",
                "massage", "undress", "caress", "kiss", "make out", "have sex",
                "hold each other", "whisper desires",
            ],
            capacity=2,
            properties={"privacy": 0.95, "comfort": 1.0, "spiciness": 9,
                        "pos": {"x": -3, "y": 0, "z": -3},
                        "allowed_positions": ["laying down", "sitting", "kneeling", "straddling", "on all fours"]},
        ),
        Location(
            id="couch", name="Couch",
            description="A plush velvet couch facing a large TV. Perfect for lounging, watching, and getting close.",
            interactions=[
                "sit", "cuddle", "watch TV", "chat", "make out", "lap dance",
                "give foot massage", "share a blanket", "play a game",
            ],
            capacity=2,
            properties={"privacy": 0.5, "comfort": 0.85, "spiciness": 5,
                        "pos": {"x": 3, "y": 0, "z": 0},
                        "allowed_positions": ["sitting", "laying down", "straddling", "curled up"]},
        ),
        Location(
            id="bar", name="Bar",
            description="A home bar with mood lighting, bottles, and two intimate bar stools.",
            interactions=[
                "make a drink", "pour wine", "pour champagne", "toast", "chat",
                "do a shot", "flirt over the bar", "lean on counter",
            ],
            capacity=2,
            properties={"privacy": 0.35, "comfort": 0.5, "spiciness": 3,
                        "pos": {"x": 0, "y": 0, "z": -4.5},
                        "allowed_positions": ["sitting", "standing", "leaning"]},
        ),
        Location(
            id="bathroom", name="Bathroom",
            description="A luxurious bathroom with a deep freestanding bathtub, walk-in shower, candles, and rose petals.",
            interactions=[
                "shower", "take a bath", "freshen up", "share a bath",
                "apply oils", "undress", "help undress each other",
                "bathe together", "apply massage oil", "rinse off",
            ],
            capacity=2,
            properties={"privacy": 1.0, "comfort": 0.8, "spiciness": 9,
                        "pos": {"x": -5, "y": 0, "z": 2},
                        "allowed_positions": ["standing", "sitting", "kneeling", "laying down"]},
        ),
        Location(
            id="balcony", name="Balcony",
            description="A romantic balcony overlooking the city skyline at night. Stars above, city below.",
            interactions=[
                "gaze at stars", "share a cigarette", "lean on railing",
                "kiss under the stars", "dance slowly", "confess something",
            ],
            capacity=2,
            properties={"privacy": 0.25, "comfort": 0.45, "spiciness": 4,
                        "pos": {"x": 0, "y": 0, "z": -5},
                        "allowed_positions": ["standing", "leaning", "dancing"]},
        ),
        Location(
            id="vanity", name="Vanity Mirror",
            description="An elegant makeup vanity with soft ring-light. Mirrors show everything.",
            interactions=[
                "check mirror", "apply makeup", "take a selfie", "pose",
                "undress while watched in mirror", "admire yourself",
            ],
            capacity=2,
            properties={"privacy": 0.4, "comfort": 0.5, "spiciness": 6,
                        "pos": {"x": -5, "y": 0, "z": -1},
                        "allowed_positions": ["standing", "sitting", "kneeling"]},
        ),
        Location(
            id="doorway", name="Doorway",
            description="The threshold of the bedroom. A liminal space — arriving or leaving?",
            interactions=[
                "enter", "leave", "greet", "block the exit", "lean against frame",
                "invite inside",
            ],
            capacity=2,
            properties={"privacy": 0.1, "comfort": 0.2, "spiciness": 2,
                        "pos": {"x": 5, "y": 0, "z": 3},
                        "allowed_positions": ["standing", "leaning"]},
        ),
    ]
    for loc in locations:
        sm.add_location(loc)
    return sm


class BedroomScene(BaseScene, MCPSceneMixin, mcp_scene_id="bedroom"):
    """Adult multi-agent roleplay bedroom — v4."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5556):
        super().__init__(scene_name="bedroom", host=host, port=port)
        self.db = Database()
        self.scene_map = _build_bedroom_map()

        # Characters + profiles
        self.characters: Dict[str, Character] = {}
        self.profiles: Dict[str, CharacterProfile] = {}
        self.active_character: Optional[Character] = None

        # Agent loop
        self.agent_loop: Optional[AgentLoop] = None
        self.agent_model_config: Dict[str, Dict] = {}

        # Director state
        self.story_beats: List[str] = []
        self.active_scenario: Optional[str] = None
        self.pending_lines: Dict[str, str] = {}
        self.pending_actions: Dict[str, str] = {}
        self.director_in_scene: bool = False
        self.director_name: str = "Director"

        # Room props
        self.room_props: List[str] = []

        # Scene state
        self.scene_state: Dict = {
            "time_of_day": "evening",
            "lighting": LIGHTING_PRESETS["evening"],
            "lighting_key": "evening",
            "characters": {},
            "locations": {},
            "room_props": [],
            "agent_loop_running": False,
            "mode": "observe",
            "active_scenario": None,
            "story_beats": [],
            "director_in_scene": False,
        }
        self._refresh_location_state()

        # Flask
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config["SECRET_KEY"] = "bedroom_v4_roleplay_secret"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", manage_session=False)

        # Mount control overlay
        from engine.overlay import mount_overlay
        mount_overlay(self.app, self.socketio)

        self._setup_routes()
        self._setup_socketio()
        self._mcp_init()
        register_bedroom_rules()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _refresh_location_state(self):
        self.scene_state["locations"] = {}
        for loc in self.scene_map.locations:
            self.scene_state["locations"][loc.id] = {
                "name": loc.name,
                "description": loc.description,
                "interactions": loc.interactions,
                "occupants": loc.occupants,
                "pos": loc.properties.get("pos", {"x": 0, "y": 0, "z": 0}),
                "spiciness": loc.spiciness,
                "allowed_positions": loc.properties.get("allowed_positions", POSITIONS[:4]),
            }

    def _refresh_character_state(self):
        self.scene_state["characters"] = {}
        for cid, char in self.characters.items():
            loc = self.scene_map.get_character_location(cid)
            profile = self.profiles.get(cid, CharacterProfile())
            self.scene_state["characters"][cid] = {
                "name": char.name,
                "mood": char.mood,
                "location": loc.name if loc else None,
                "location_id": loc.id if loc else None,
                "outfit": profile.outfit,
                "position": profile.position,
                "props_held": profile.props_held,
                "personality": profile.personality_key,
                "stats": profile.stats.to_dict(),
                "compliance": round(profile.stats.compliance_score(
                    PERSONALITY_PROFILES.get(profile.personality_key, {}).get("compliance_mod", 0)
                ), 1),
                "feeling": profile.stats.describe(),
            }
        self.scene_state["room_props"] = self.room_props
        self.scene_state["active_scenario"] = self.active_scenario
        self.scene_state["story_beats"] = self.story_beats[:5]
        self.scene_state["director_in_scene"] = self.director_in_scene

    def _broadcast_state(self):
        self._refresh_location_state()
        self._refresh_character_state()
        self.scene_state["agent_loop_running"] = (
            self.agent_loop.is_running if self.agent_loop else False
        )
        self.socketio.emit("scene_state", self.scene_state)
        self._sync_to_mcp()

    def _sync_to_mcp(self, event_name: str = None, payload: dict = None):
        """Push scene state into MCP framework and optionally emit an event."""
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            # Sync character stats to framework
            for cid, profile in self.profiles.items():
                char_node = fw.get_character(cid)
                if char_node:
                    char_node.update_state({
                        "stats": profile.stats.to_dict(),
                        "outfit": profile.outfit,
                        "position": profile.position,
                        "personality": profile.personality_key,
                        "props_held": profile.props_held,
                    })
            # Sync scene state
            scene_node = fw.get_scene("bedroom")
            if scene_node:
                scene_node.update_state({
                    "time_of_day": self.scene_state.get("time_of_day"),
                    "lighting": self.scene_state.get("lighting_key"),
                    "active_scenario": self.active_scenario,
                    "agent_loop_running": self.scene_state.get("agent_loop_running", False),
                    "character_count": len(self.characters),
                    "room_props": self.room_props,
                })
            # Emit event if requested
            if event_name:
                fw.emit_event(event_name, payload or {}, source="bedroom")
        except Exception:
            pass

    def _load_character(self, char_id: str, personality_key: str = None) -> Optional[Character]:
        if len(self.characters) >= 2 and char_id not in self.characters:
            return None
        char = Character.load(char_id, db=self.db)
        if not char:
            return None
        self.characters[char.id] = char
        if not self.active_character:
            self.active_character = char

        pk = personality_key or (
            "bold_dominant" if len(self.characters) == 1 else "shy_submissive"
        )
        p_info = PERSONALITY_PROFILES.get(pk, PERSONALITY_PROFILES["playful_tease"])
        stats = AgentStats(**{k: v for k, v in p_info["base_stats"].items()})
        profile = CharacterProfile(
            personality_key=pk,
            traits=list(p_info["traits"]),
            likes=list(p_info["likes"]),
            dislikes=list(p_info["dislikes"]),
            outfit=OUTFITS[0],
            position=POSITIONS[0],
            stats=stats,
        )
        self.profiles[char.id] = profile

        empty = self.scene_map.get_empty_locations()
        loc = random.choice(empty) if empty else self.scene_map.get_location("doorway")
        if loc:
            self.scene_map.place_character(char.id, loc.id)
        self._broadcast_state()
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            fw.get_character(char.id).enter_scene("bedroom")
        except Exception:
            pass
        return char

    def _inject_to_loop(self, name: str, text: str, msg_type: str = "director"):
        if self.agent_loop:
            self.agent_loop.shared_log.append({
                "name": name, "text": text,
                "timestamp": datetime.now().isoformat(),
                "type": msg_type,
            })

    def _apply_prop_stat_effect(self, prop_id: str):
        if prop_id not in PROPS:
            return
        import re
        effect_str = PROPS[prop_id]["effect"]
        for m in re.finditer(r'([+-])(\d+)\s+(\w+)', effect_str):
            sign = 1 if m.group(1) == '+' else -1
            val = int(m.group(2)) * sign
            stat = m.group(3).lower()
            for cid, profile in self.profiles.items():
                profile.stats.adjust(**{stat: val * 0.5})

    # ── Routes ──────────────────────────────────────────────────────────
    def _setup_routes(self):

        @self.app.route("/")
        def index():
            return render_template("bedroom_ui.html",
                                   scenarios=PREMADE_SCENARIOS,
                                   positions=POSITIONS,
                                   outfits=OUTFITS,
                                   props=PROPS,
                                   personalities=PERSONALITY_PROFILES,
                                   lighting_presets=LIGHTING_PRESETS)

        @self.app.route("/api/scene/state")
        def get_scene_state():
            self._refresh_location_state()
            self._refresh_character_state()
            return jsonify(self.scene_state)

        @self.app.route("/api/scene/time", methods=["POST"])
        def set_time():
            key = (request.json or {}).get("time", "evening")
            self.scene_state["time_of_day"] = key
            self.scene_state["lighting"] = LIGHTING_PRESETS.get(key, LIGHTING_PRESETS["evening"])
            self.scene_state["lighting_key"] = key
            self.socketio.emit("time_changed", {
                "time": key, "lighting": self.scene_state["lighting"],
            })
            return jsonify({"success": True})

        @self.app.route("/api/scene/lighting_presets")
        def get_lighting_presets():
            return jsonify(LIGHTING_PRESETS)

        # ── Characters ──────────────────────────────────────────────
        @self.app.route("/api/characters/list")
        def list_characters():
            try:
                db_chars = self.db.get_all_characters()
                for c in db_chars:
                    c["source"] = "database"
                    c["loaded"] = c["id"] in self.characters
                return jsonify({"characters": db_chars})
            except Exception as exc:
                logger.error("list_characters failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/character/load", methods=["POST"])
        def load_character():
            try:
                data = request.json or {}
                cid = data.get("character_id")
                personality = data.get("personality")
                if not cid:
                    return jsonify({"error": "No character_id"}), 400
                if len(self.characters) >= 2 and cid not in self.characters:
                    return jsonify({"error": "Maximum 2 characters in bedroom"}), 400
                char = self._load_character(cid, personality)
                if not char:
                    return jsonify({"error": "Character not found"}), 404
                return jsonify({"success": True, "character": {"id": char.id, "name": char.name}})
            except Exception as exc:
                logger.error("load_character failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/character/remove", methods=["POST"])
        def remove_character():
            cid = (request.json or {}).get("character_id")
            if cid in self.characters:
                del self.characters[cid]
                self.profiles.pop(cid, None)
                self.scene_map.remove_character(cid)
                if self.agent_loop:
                    self.agent_loop.unregister_character(cid)
                self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/characters/loaded")
        def loaded_characters():
            self._refresh_character_state()
            return jsonify({"characters": self.scene_state["characters"]})

        # ── Stats ────────────────────────────────────────────────────
        @self.app.route("/api/character/stats/adjust", methods=["POST"])
        def adjust_stat():
            data = request.json or {}
            cid = data.get("character_id")
            stat = data.get("stat")
            delta = float(data.get("delta", 0))
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            self.profiles[cid].stats.adjust(**{stat: delta})
            self._broadcast_state()
            self._sync_to_mcp("stat_adjusted", {"character_id": cid, "stat": stat, "delta": delta})
            return jsonify({"success": True, "stats": self.profiles[cid].stats.to_dict()})

        @self.app.route("/api/character/stats/set", methods=["POST"])
        def set_stat():
            data = request.json or {}
            cid = data.get("character_id")
            stat = data.get("stat")
            value = float(data.get("value", 50))
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            setattr(self.profiles[cid].stats, stat, value)
            self.profiles[cid].stats.clamp()
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/character/outfit", methods=["POST"])
        def set_outfit():
            data = request.json or {}
            cid = data.get("character_id")
            outfit = data.get("outfit", OUTFITS[0])
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            self.profiles[cid].outfit = outfit
            if outfit in ("nothing", "lingerie"):
                self.profiles[cid].stats.adjust(arousal=10, explicitness=5)
            self._inject_to_loop("(environment)", f"{self.characters[cid].name} is now wearing: {outfit}.", "environment")
            self._broadcast_state()
            self._sync_to_mcp("outfit_changed", {"character_id": cid, "outfit": outfit})
            return jsonify({"success": True})

        @self.app.route("/api/character/position", methods=["POST"])
        def set_position():
            data = request.json or {}
            cid = data.get("character_id")
            position = data.get("position", POSITIONS[0])
            if cid not in self.profiles:
                return jsonify({"error": "Character not found"}), 404
            self.profiles[cid].position = position
            self._inject_to_loop("(environment)", f"{self.characters[cid].name} is now {position}.", "environment")
            self._broadcast_state()
            self._sync_to_mcp("position_changed", {"character_id": cid, "position": position})
            return jsonify({"success": True})

        @self.app.route("/api/character/personality", methods=["POST"])
        def set_personality():
            data = request.json or {}
            cid = data.get("character_id")
            pk = data.get("personality_key")
            if cid not in self.profiles or pk not in PERSONALITY_PROFILES:
                return jsonify({"error": "Invalid character or personality"}), 400
            p_info = PERSONALITY_PROFILES[pk]
            self.profiles[cid].personality_key = pk
            self.profiles[cid].traits = list(p_info["traits"])
            self.profiles[cid].likes = list(p_info["likes"])
            self.profiles[cid].dislikes = list(p_info["dislikes"])
            self._broadcast_state()
            return jsonify({"success": True})

        # ── Spatial ──────────────────────────────────────────────────
        @self.app.route("/api/location/move", methods=["POST"])
        def move_character():
            data = request.json or {}
            cid = data.get("character_id")
            loc_id = data.get("location_id")
            if not loc_id:
                loc = self.scene_map.get_location_by_name(data.get("location", ""))
                loc_id = loc.id if loc else None
            if not loc_id or cid not in self.characters:
                return jsonify({"error": "Invalid character or location"}), 400
            ok = self.scene_map.move_character(cid, loc_id)
            loc_obj = self.scene_map.get_location(loc_id)
            if loc_obj:
                self._inject_to_loop("(environment)", f"{self.characters[cid].name} moves to {loc_obj.name}.", "environment")
            self._broadcast_state()
            self._sync_to_mcp("character_moved", {"character_id": cid, "location": loc_id})
            return jsonify({"success": ok})

        @self.app.route("/api/locations")
        def list_locations():
            self._refresh_location_state()
            return jsonify({"locations": self.scene_state["locations"], "positions": POSITIONS})

        # ── Props ─────────────────────────────────────────────────────
        @self.app.route("/api/props/list")
        def list_props():
            return jsonify({"available": PROPS, "room": self.room_props})

        @self.app.route("/api/props/add", methods=["POST"])
        def add_prop():
            pid = (request.json or {}).get("prop_id")
            if pid not in PROPS:
                return jsonify({"error": "Unknown prop"}), 400
            if pid not in self.room_props:
                self.room_props.append(pid)
            self._apply_prop_stat_effect(pid)
            self._inject_to_loop("(environment)", f"A {PROPS[pid]['label']} has appeared in the room.", "environment")
            self._broadcast_state()
            return jsonify({"success": True, "room_props": self.room_props})

        @self.app.route("/api/props/remove", methods=["POST"])
        def remove_prop():
            pid = (request.json or {}).get("prop_id")
            if pid in self.room_props:
                self.room_props.remove(pid)
            self._broadcast_state()
            return jsonify({"success": True, "room_props": self.room_props})

        @self.app.route("/api/props/give", methods=["POST"])
        def give_prop_to_character():
            data = request.json or {}
            cid = data.get("character_id")
            pid = data.get("prop_id")
            if cid not in self.profiles or pid not in PROPS:
                return jsonify({"error": "Invalid"}), 400
            if pid not in self.profiles[cid].props_held:
                self.profiles[cid].props_held.append(pid)
            self._inject_to_loop("(environment)", f"{self.characters[cid].name} picks up the {PROPS[pid]['label']}.", "environment")
            self._broadcast_state()
            return jsonify({"success": True})

        # ── Director ─────────────────────────────────────────────────
        @self.app.route("/api/director/whisper", methods=["POST"])
        def whisper():
            data = request.json or {}
            cid = data.get("character_id")
            msg = data.get("message", "")
            target_name = self.characters[cid].name if cid in self.characters else "All"
            self._inject_to_loop("(Director)", f"[whisper to {target_name}] {msg}", "whisper")
            return jsonify({"success": True})

        @self.app.route("/api/director/give_line", methods=["POST"])
        def give_line():
            data = request.json or {}
            cid = data.get("character_id")
            line = data.get("line", "")
            if cid not in self.characters:
                return jsonify({"error": "Character not loaded"}), 400
            name = self.characters[cid].name
            compliance = self.profiles[cid].stats.compliance_score(
                PERSONALITY_PROFILES.get(self.profiles[cid].personality_key, {}).get("compliance_mod", 0)
            )
            if compliance >= 60:
                instruction = f"[DIRECTOR LINE — say exactly:] \"{line}\""
            else:
                instruction = f"[DIRECTOR SUGGESTION — you may adapt or resist:] \"{line}\""
            self._inject_to_loop("(Director)", f"[to {name}] {instruction}", "director_line")
            return jsonify({"success": True, "compliance": compliance})

        @self.app.route("/api/director/give_action", methods=["POST"])
        def give_action():
            data = request.json or {}
            cid = data.get("character_id") or ""
            action = data.get("action", "")
            target = self.characters[cid].name if cid in self.characters else "All characters"
            compliance_note = ""
            if cid in self.profiles:
                c = self.profiles[cid].stats.compliance_score(
                    PERSONALITY_PROFILES.get(self.profiles[cid].personality_key, {}).get("compliance_mod", 0)
                )
                compliance_note = f" (compliance: {c:.0f})"
            self._inject_to_loop("(Director)", f"[ACTION DIRECTIVE to {target}{compliance_note}] {action}", "director_action")
            return jsonify({"success": True})

        @self.app.route("/api/director/broadcast", methods=["POST"])
        def director_broadcast():
            msg = (request.json or {}).get("message", "")
            name = self.director_name if self.director_in_scene else "(The Director)"
            self._inject_to_loop(name, msg, "director")
            self.socketio.emit("director_speaks", {"name": name, "message": msg,
                                                    "timestamp": datetime.now().isoformat()})
            return jsonify({"success": True})

        @self.app.route("/api/director/enter_scene", methods=["POST"])
        def director_enter():
            data = request.json or {}
            self.director_in_scene = data.get("in_scene", True)
            self.director_name = data.get("name", "The Director")
            if self.director_in_scene:
                self._inject_to_loop("(environment)", f"The Director enters the scene as '{self.director_name}'.", "environment")
            else:
                self._inject_to_loop("(environment)", "The Director steps back to observe.", "environment")
            self._broadcast_state()
            return jsonify({"success": True})

        # ── Scenarios & Story ─────────────────────────────────────────
        @self.app.route("/api/scenario/list")
        def list_scenarios():
            return jsonify({k: {"label": v["label"], "emoji": v["emoji"], "opening": v["opening"]}
                            for k, v in PREMADE_SCENARIOS.items()})

        @self.app.route("/api/scenario/set", methods=["POST"])
        def set_scenario():
            key = (request.json or {}).get("scenario_key")
            if key not in PREMADE_SCENARIOS:
                return jsonify({"error": "Unknown scenario"}), 400
            self.active_scenario = key
            sc = PREMADE_SCENARIOS[key]
            for stat, delta in sc.get("mood_shift", {}).items():
                for profile in self.profiles.values():
                    profile.stats.adjust(**{stat: delta})
            self._inject_to_loop("(Scene)", sc["opening"], "scenario")
            self.story_beats = list(sc.get("beats", []))
            self.scene_state["active_scenario"] = key
            self.scene_state["story_beats"] = self.story_beats[:5]
            self._broadcast_state()
            self._sync_to_mcp("scenario_started", {"scenario": key})
            return jsonify({"success": True, "opening": sc["opening"]})

        @self.app.route("/api/scenario/clear", methods=["POST"])
        def clear_scenario():
            self.active_scenario = None
            self.story_beats = []
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/story/beat", methods=["POST"])
        def add_story_beat():
            beat = (request.json or {}).get("beat", "")
            if beat:
                self.story_beats.append(beat)
            self._broadcast_state()
            return jsonify({"success": True, "beats": self.story_beats})

        @self.app.route("/api/story/beats")
        def get_story_beats():
            return jsonify({"beats": self.story_beats})

        @self.app.route("/api/story/clear_beat", methods=["POST"])
        def clear_beat():
            idx = (request.json or {}).get("index", 0)
            try:
                self.story_beats.pop(idx)
            except IndexError:
                pass
            return jsonify({"success": True, "beats": self.story_beats})

        @self.app.route("/api/conversation/start", methods=["POST"])
        def start_conversation():
            data = request.json or {}
            conv_type = data.get("type", "flirt")
            starters = {
                "flirt":       "It's getting quite warm in here... isn't it? Or is that just me?",
                "confession":  "I need to tell you something I've been holding back all evening...",
                "dare":        "I dare you to do something you've never done in this room before.",
                "compliment":  "You have absolutely no idea how beautiful you look right now.",
                "fantasy":     "Tell me your most vivid fantasy. Don't leave anything out.",
                "game":        "Let's play a game. Every lie costs you a piece of clothing.",
                "roleplay_meta": "Let's pretend we just met. You walk in... and I see you for the first time.",
                "power_play":  "For the next ten minutes, I'm telling you what to do. And you will do it.",
            }
            starter = starters.get(conv_type, starters["flirt"])
            char_names = [c.name for c in self.characters.values()]
            speaker = char_names[0] if char_names else "(character)"
            self._inject_to_loop(speaker, starter, "speech")
            self.socketio.emit("conversation_started", {"type": conv_type, "line": starter, "speaker": speaker})
            return jsonify({"success": True, "line": starter})

        # ── Events ─────────────────────────────────────────────────────
        @self.app.route("/api/event/fire", methods=["POST"])
        def fire_event():
            data = request.json or {}
            ev_type = data.get("type", "")
            ev_custom = data.get("custom", "")
            events = {
                "flicker_lights": "The lights flicker and dim ominously.",
                "strange_sound":  "A strange, seductive sound drifts through the room.",
                "cold_draft":     "A sudden icy draft sweeps through, raising goosebumps.",
                "move_object":    "Something shifts on its own in the corner of the room.",
                "knock":          "Three slow knocks from the door — but nobody answers.",
                "power_out":      "The lights go completely dark.",
                "romantic_mood":  "The lighting shifts to a warm, intimate amber glow.",
                "thunder":        "Thunder shakes the room; lightning flashes.",
                "lock_door":      "The sound of a lock clicking. Nobody is leaving tonight.",
                "music_on":       "Slow, sensual music begins playing from an unseen speaker.",
                "candles_light":  "Every candle in the room ignites at once.",
                "rose_petals":    "Rose petals drift from the ceiling onto the bed.",
                "phone_rings":    "A phone rings — persistent, intrusive. Who could it be?",
                "door_opens":     "The door creaks open on its own.",
            }
            # legacy menace compat
            if ev_type == "":
                ev_type = data.get("menace_type", data.get("type", ""))
            msg = ev_custom if ev_custom else events.get(ev_type, f"Something unusual happens.")
            self._inject_to_loop("(environment)", msg, "environment")
            self.socketio.emit("scene_event", {"type": ev_type, "message": msg})
            self.socketio.emit("menace_event", {"type": ev_type, "message": msg})  # legacy compat
            self._sync_to_mcp("scene_event", {"type": ev_type, "message": msg})
            return jsonify({"success": True, "message": msg})

        # legacy menace proxy
        @self.app.route("/api/menace", methods=["POST"])
        def menace_action():
            data = request.get_json(force=True)
            data["type"] = data.get("type", "")
            return fire_event()

        # ── Agent Loop ──────────────────────────────────────────────
        @self.app.route("/api/agents/start", methods=["POST"])
        def start_agent_loop():
            if len(self.characters) < 1:
                return jsonify({"error": "Need at least 1 character"}), 400
            interval = (request.json or {}).get("interval", 30)
            self._start_agent_loop(interval)
            return jsonify({"success": True})

        @self.app.route("/api/agents/stop", methods=["POST"])
        def stop_agent_loop():
            if self.agent_loop:
                self.agent_loop.stop()
            self.scene_state["agent_loop_running"] = False
            self._broadcast_state()
            return jsonify({"success": True})

        @self.app.route("/api/agents/tick", methods=["POST"])
        def manual_tick():
            if not self.agent_loop:
                self._start_agent_loop(interval=9999)
                self.agent_loop.stop()
            actions = self.agent_loop.tick()
            self._broadcast_state()
            return jsonify({"actions": actions})

        @self.app.route("/api/agents/whisper", methods=["POST"])
        def whisper_legacy():
            """Legacy whisper endpoint. Prefer /api/director/whisper."""
            data = request.json or {}
            cid = data.get("character_id")
            msg = data.get("message", "")
            target_name = self.characters[cid].name if cid in self.characters else "All"
            self._inject_to_loop("(Director)", f"[whisper to {target_name}] {msg}", "whisper")
            return jsonify({"success": True})

        @self.app.route("/api/agents/model", methods=["POST"])
        def set_agent_model():
            data = request.json or {}
            cid = data.get("character_id")
            model = data.get("model")
            mode = data.get("mode", "default")
            if cid and cid in self.characters:
                self.agent_model_config[cid] = {"model": model, "mode": mode}
                return jsonify({"success": True})
            return jsonify({"error": "Character not loaded"}), 400

        @self.app.route("/api/agents/model", methods=["GET"])
        def get_agent_models():
            config = {}
            for cid in self.characters:
                cfg = self.agent_model_config.get(cid, {})
                config[cid] = {
                    "character": self.characters[cid].name,
                    "model": cfg.get("model"),
                    "mode": cfg.get("mode", "default"),
                }
            return jsonify(config)

        @self.app.route("/api/models/available")
        def list_models():
            models: Dict[str, Any] = {"loaded": [], "available": []}
            try:
                from engine.agents.virtual_agent_manager import get_virtual_agent_manager
                mgr = get_virtual_agent_manager()
                models["agents"] = mgr.list_agents()
                models["stats"] = mgr.get_stats()
            except Exception:
                pass
            try:
                from engine.lmstudio.lms_client import get_lms_client
                client = get_lms_client()
                loaded = client.get_models(loaded_only=True)
                models["loaded"] = [
                    {"id": m["id"], "display_name": m.get("display_name", m["id"]),
                     "params": m.get("params", ""), "context_length": m.get("context_length", 0)}
                    for m in loaded
                ]
                all_models = client.get_models(loaded_only=False)
                loaded_ids = {m["id"] for m in loaded}
                models["available"] = [
                    {"id": m["id"], "display_name": m.get("display_name", m["id"]),
                     "params": m.get("params", "")}
                    for m in all_models if m["id"] not in loaded_ids
                ]
            except Exception:
                pass
            return jsonify(models)

        @self.app.route("/api/mode", methods=["POST"])
        def set_mode():
            mode = (request.json or {}).get("mode", "observe")
            self.scene_state["mode"] = mode
            self._broadcast_state()
            return jsonify({"success": True, "mode": mode})

        @self.app.route("/api/history")
        def get_history():
            if self.agent_loop:
                return jsonify({"success": True, "history": self.agent_loop.shared_log[-100:]})
            return jsonify({"success": True, "history": []})

        @self.app.route("/api/ambient/tracks")
        def list_ambient_tracks():
            audio_dir = Path(__file__).parent / "static" / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
            tracks = [f.name for f in audio_dir.iterdir() if f.suffix.lower() in exts]
            return jsonify(sorted(tracks))

        @self.app.route("/api/meta/constants")
        def get_constants():
            return jsonify({
                "positions": POSITIONS,
                "outfits": OUTFITS,
                "props": PROPS,
                "personalities": {k: {"traits": v["traits"]} for k, v in PERSONALITY_PROFILES.items()},
                "lighting_presets": LIGHTING_PRESETS,
                "scenarios": {k: {"label": v["label"], "emoji": v["emoji"]} for k, v in PREMADE_SCENARIOS.items()},
            })

        # ── MCP Framework API ─────────────────────────────────────────
        @self.app.route("/api/mcp/status")
        def mcp_status():
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                return jsonify({"ok": True, "status": fw.get_status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/scene-state")
        def mcp_scene_state():
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                scene_node = fw.get_scene("bedroom")
                return jsonify({"ok": True, "state": scene_node.get_state() if scene_node else {}})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/event-log")
        def mcp_event_log():
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                limit = int(request.args.get("limit", 50))
                return jsonify({"ok": True, "events": fw.get_event_log(limit=limit)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/lmstudio")
        def mcp_lmstudio():
            try:
                from engine.lmstudio.model_manager import get_model_manager
                mm = get_model_manager()
                return jsonify({"ok": True, "config": mm.get_full_config(), "status": mm.status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/resources")
        def mcp_resources():
            try:
                from engine.lmstudio.resource_manager import get_resource_manager
                rm = get_resource_manager()
                return jsonify({"ok": True, "resources": rm.get_status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/resources/config", methods=["POST"])
        def mcp_resources_config():
            try:
                from engine.lmstudio.resource_manager import get_resource_manager
                rm = get_resource_manager()
                data = request.get_json(force=True)
                result = rm.update_config(**data)
                return jsonify({"ok": True, "resources": result})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/inference-defaults")
        def mcp_inference_defaults():
            try:
                from engine.lmstudio.inference_config import InferenceConfig
                defaults = InferenceConfig.from_yaml()
                return jsonify({"ok": True, "defaults": defaults.to_dict()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/mcp/config", methods=["GET", "POST"])
        def mcp_config():
            try:
                from engine.config import get_config
                config = get_config()
                if request.method == "POST":
                    updates = request.json or {}
                    for key, value in updates.items():
                        config.set(key, value)
                    return jsonify({"ok": True, "message": "Config updated"})
                return jsonify({"ok": True, "config": {
                    "agent_profiles": config.get("agent_profiles", {}),
                    "framework": config.get("framework", {}),
                    "scenes.bedroom": config.get("scenes.bedroom", {}),
                }})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

    # ── SocketIO─────────────────────────────────────────────────────────
    def _setup_socketio(self):

        @self.socketio.on("connect")
        def handle_connect():
            self._refresh_location_state()
            self._refresh_character_state()
            emit("scene_state", self.scene_state)
            emit("constants", {
                "positions": POSITIONS, "outfits": OUTFITS, "props": PROPS,
                "personalities": {k: {"traits": v["traits"]} for k, v in PERSONALITY_PROFILES.items()},
                "lighting": LIGHTING_PRESETS,
                "scenarios": {k: {"label": v["label"], "emoji": v["emoji"]} for k, v in PREMADE_SCENARIOS.items()},
            })

        @self.socketio.on("disconnect")
        def handle_disconnect():
            pass

        @self.socketio.on("request_state")
        def handle_request():
            self._broadcast_state()

        @self.socketio.on("chat_message")
        def handle_chat(data):
            msg = data.get("message", "")
            ts = datetime.now().isoformat()
            name = self.director_name if self.director_in_scene else "You"
            self._inject_to_loop(name, msg, "speech")
            self.socketio.emit("chat_message", {"name": name, "message": msg, "timestamp": ts})

        @self.socketio.on("quick_stat")
        def handle_quick_stat(data):
            cid = data.get("character_id")
            stat = data.get("stat")
            delta = float(data.get("delta", 0))
            if cid in self.profiles and stat:
                self.profiles[cid].stats.adjust(**{stat: delta})
                self._broadcast_state()

    # ── Agent Loop ───────────────────────────────────────────────────────
    def _start_agent_loop(self, interval: float = 30):
        if self.agent_loop and self.agent_loop.is_running:
            return
        self.agent_loop = AgentLoop(
            scene_map=self.scene_map,
            db=self.db,
            socketio=self.socketio,
            scene_id="bedroom",
        )
        for cid, char in self.characters.items():
            agent_cfg = self.agent_model_config.get(cid, {})
            # Seed the CharacterRegistry so interceptors have full profile+state
            try:
                from engine.mcp.character_registry import seed_registry_from_character
                seed_registry_from_character(char)
            except Exception as _reg_exc:
                logger.debug("Registry seed failed for %s: %s", cid, _reg_exc)
            # MCP: use agent profile for model selection
            profile_model = None
            try:
                from engine.mcp.framework import get_framework
                fw = get_framework()
                agent_profile = fw.get_agent_profile("big")  # bedroom agents use big profile
                if agent_profile and not agent_cfg.get("model"):
                    profile_model = agent_profile.get("model_hint")
            except Exception:
                pass
            agent = CharacterAgent(
                char,
                db=self.db,
                skill_packs=["memory", "character"],
                model=agent_cfg.get("model") or profile_model,
                scene="bedroom",
            )
            # MCP: wrap every bedroom agent in the governance pipeline so all
            # 15 interceptors (CharacterRegistry, DialogDirective, PersonalityGuard,
            # SkillAwareness, ActivityLogger, etc.) fire on every turn.
            try:
                from engine.mcp.comms_framework import get_governor
                agent = get_governor(agent, scene="bedroom")
            except Exception:
                pass  # graceful fallback — bare CharacterAgent still works
            self.agent_loop.register_character(char, agent=agent)

        # Inject roleplay context
        for cid, char in self.characters.items():
            profile = self.profiles.get(cid, CharacterProfile())
            self._refresh_character_state()
            rp_prompt = build_roleplay_system_prompt(
                char, profile, self.scene_state, self.profiles,
                self.story_beats, self.active_scenario,
            )
            self._inject_to_loop(
                "(system)",
                f"[ROLEPLAY CONTEXT for {char.name}]\n{rp_prompt}",
                "system",
            )

        self.agent_loop.set_action_callback(self._on_agent_action)
        self.agent_loop.start(interval=interval)
        self.scene_state["agent_loop_running"] = True
        self._broadcast_state()

    def _on_agent_action(self, character_id: str, action: Dict):
        if self.story_beats:
            beat = self.story_beats[0]
            self._inject_to_loop("(Scene Beat)", beat, "scene_beat")
            self.story_beats.pop(0)
        if character_id in self.profiles:
            action_type = action.get("action", "")
            stat_drifts = {
                "speak":    {"tiredness": 1},
                "move":     {"tiredness": 2},
                "idle":     {"tiredness": -1},
                "flirt":    {"arousal": 3, "happiness": 2},
                "kiss":     {"arousal": 8, "pleasure": 5, "horniness": 5},
                "intimate": {"arousal": 15, "pleasure": 10, "horniness": 10, "tiredness": 5},
                "cuddle":   {"happiness": 5, "pleasure": 3, "tiredness": 2},
                "touch":    {"arousal": 5, "pleasure": 4},
            }
            if action_type in stat_drifts:
                self.profiles[character_id].stats.adjust(**stat_drifts[action_type])
            # Forward speech to the chat panel so dialogue shows as chat bubbles
            if action_type == "speak" and action.get("message"):
                char = self.characters.get(character_id)
                self.socketio.emit("chat_message", {
                    "name":      char.name if char else character_id,
                    "message":   action["message"],
                    "timestamp": action.get("timestamp", ""),
                    "character_id": character_id,
                })
        self._broadcast_state()
        self._sync_to_mcp("agent_action", {
            "character_id": character_id,
            "action": action.get("action", ""),
        })

    # ── BaseScene interface──────────────────────────────────────────────
    def get_plugin_info(self) -> dict:
        return {
            "name": "Bedroom Scene",
            "description": "Adult multi-agent roleplay bedroom with stats, props, scenarios, and Director controls",
            "version": "4.1.0",
            "author": "CosySim",
            "port": self.port,
            "tags": ["bedroom", "roleplay", "adult", "multi-agent", "spatial", "intimate", "mcp"],
        }

    def start(self) -> None:
        print("Bedroom Scene v4 — Adult Roleplay Engine starting...")
        print(f"   Access at: http://{self.host}:{self.port}")
        # Wire up framework event bus
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            fw.on("environment_change", lambda evt: self._on_env_change(evt))
            fw.on("mood_contagion", lambda evt: self._on_mood_event(evt))
            fw.on("story_beat", lambda evt: self._on_story_beat(evt))
        except Exception:
            pass
        self.socketio.run(self.app, host=self.host, port=self.port,
                          debug=False, allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        if self.agent_loop:
            self.agent_loop.stop()
        # Persist framework state
        try:
            from engine.mcp.framework import get_framework
            get_framework().save_state()
        except Exception:
            pass
        print("Bedroom scene stopped.")

    def _on_env_change(self, evt) -> None:
        """React to environment_change events from the framework event bus."""
        if evt.payload.get("scene_id") == "bedroom":
            try:
                change = evt.payload.get("change_type", "")
                if change == "lighting":
                    self.scene_state["lighting_key"] = evt.payload.get("value", "evening")
                self.socketio.emit("environment_update", evt.payload)
            except Exception:
                pass

    def _on_mood_event(self, evt) -> None:
        """Push mood contagion updates to connected clients."""
        try:
            self.socketio.emit("mood_update", evt.payload)
        except Exception:
            pass

    def _on_story_beat(self, evt) -> None:
        """Inject story beats from the event bus."""
        if evt.payload.get("scene_id") == "bedroom":
            beat = evt.payload.get("beat", "")
            if beat and beat not in self.story_beats:
                self.story_beats.append(beat)
            try:
                self.socketio.emit("story_beat", evt.payload)
            except Exception:
                pass


if __name__ == "__main__":
    scene = BedroomScene(host="0.0.0.0", port=5556)
    scene.start()
