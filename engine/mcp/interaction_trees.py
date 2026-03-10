"""
CosySim Interaction Trees
==========================
Defines the 6 core interaction types for the penthouse scene and 6 for the
Phone scene.  Each type has:

  * subtypes      — the specific flavour of that interaction
  * stat_effects  — how the interaction changes character stats
  * phases        — narrative flow labels (beginning → peak → afterglow)
  * duration      — typical real-world seconds the action should play out
  * narrative_fragments — lines agents can draw on for description
  * intimacy_level — 1-5 how explicit/intimate this is
  * requires      — minimum stat thresholds before this type fires naturally

Agents call ``get_interaction_result()`` to resolve what happens when two
characters perform an interaction, taking their current stats into account.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════
#  INTERACTION DEFINITION
# ══════════════════════════════════════════════════════════════════════

@dataclass
class InteractionSubtype:
    id:           str
    label:        str
    description:  str
    duration:     float                # seconds
    intimacy:     int                  # 1-5
    stat_effects: Dict[str, float]     # e.g. {"arousal": +20, "happiness": +10}
    phases:       List[str]
    fragments:    List[str]            # sample narrative sentences / agent lines
    requires:     Dict[str, float] = field(default_factory=dict)  # min stats


@dataclass
class InteractionType:
    id:          str
    label:       str
    description: str
    subtypes:    List[InteractionSubtype]
    default_subtype: str = ""

    def get_subtype(self, subtype_id: str) -> Optional[InteractionSubtype]:
        for s in self.subtypes:
            if s.id == subtype_id:
                return s
        return None

    def random_subtype(self, min_intimacy: int = 1, max_intimacy: int = 5) -> InteractionSubtype:
        pool = [s for s in self.subtypes if min_intimacy <= s.intimacy <= max_intimacy]
        return random.choice(pool) if pool else self.subtypes[0]

    def subtype_ids(self) -> List[str]:
        return [s.id for s in self.subtypes]


# ══════════════════════════════════════════════════════════════════════
#  penthouse — 6 INTERACTION TYPES
# ══════════════════════════════════════════════════════════════════════

PENTHOUSE_INTERACTIONS: Dict[str, InteractionType] = {}

# ─── 1. CUDDLE ───────────────────────────────────────────────────────
PENTHOUSE_INTERACTIONS["cuddle"] = InteractionType(
    id="cuddle", label="Cuddle", default_subtype="spoon",
    description="Warm physical closeness — comfort, safety, and growing heat.",
    subtypes=[
        InteractionSubtype(
            id="embrace", label="Full Embrace", duration=20, intimacy=1,
            description="A full body hug, arms wrapped tight.",
            stat_effects={"happiness": 15, "affection": 10, "fear": -10, "arousal": 8},
            phases=["drawing close", "holding each other", "breathing together"],
            fragments=[
                "wraps {their} arms around {target} and pulls {them} close",
                "presses {their} face into {target}'s shoulder",
                "squeezes gently and smiles against {target}'s neck",
                "'I missed you,' {name} murmurs into {target}'s hair",
                "tightens {their} hold almost imperceptibly",
            ],
        ),
        InteractionSubtype(
            id="spoon", label="Spooning", duration=30, intimacy=2,
            description="Lying together, one curled around the other.",
            stat_effects={"happiness": 18, "affection": 20, "arousal": 12, "tiredness": -10},
            phases=["settling in", "fitting together", "warmth building"],
            fragments=[
                "curls up behind {target}, arm draped over {their} waist",
                "pulls {target}'s back flush against {their} chest",
                "breathes warmly against the back of {target}'s neck",
                "shifts closer until there's no space left between them",
                "'Don't move,' {name} whispers. 'Stay exactly like this.'",
            ],
        ),
        InteractionSubtype(
            id="lap_sit", label="Lap Sit", duration=25, intimacy=2,
            description="Sitting in each other's lap, face-to-face intimacy.",
            stat_effects={"arousal": 20, "happiness": 15, "affection": 15, "dominance": 5},
            phases=["settling down", "finding rhythm", "heat rising"],
            fragments=[
                "slides onto {target}'s lap and faces {them} directly",
                "hooks {their} legs around {target}'s sides",
                "tilts {their} face up to {target}'s gaze",
                "shifts weight — makes sure {target} feels every movement",
                "'Comfortable?' {name} asks, already knowing the answer",
            ],
        ),
        InteractionSubtype(
            id="entangled", label="Entangled in Bed", duration=45, intimacy=3,
            description="Limbs wrapped around each other with nowhere to go.",
            stat_effects={"arousal": 25, "happiness": 20, "affection": 25, "horniness": 15},
            phases=["lying down", "tangling together", "forgetting where one ends and the other begins"],
            fragments=[
                "tangles {their} legs through {target}'s beneath the sheets",
                "traces a lazy pattern on {target}'s back",
                "rolls to face {target}, eyes soft in the dim light",
                "their bodies fit together like they were designed for exactly this",
                "'You're warm,' {name} observes quietly. Not a complaint.",
            ],
        ),
    ],
)

# ─── 2. KISS ─────────────────────────────────────────────────────────
PENTHOUSE_INTERACTIONS["kiss"] = InteractionType(
    id="kiss", label="Kiss", default_subtype="soft",
    description="From tender peck to breathless and desperate.",
    subtypes=[
        InteractionSubtype(
            id="soft", label="Soft Kiss", duration=8, intimacy=2,
            description="A slow, tender single kiss.",
            stat_effects={"arousal": 15, "happiness": 20, "affection": 20},
            phases=["approach", "lips meeting", "lingering"],
            fragments=[
                "leans in slowly and presses {their} lips to {target}'s",
                "cups {target}'s face in both hands before kissing {them} softly",
                "the kiss lasts longer than either planned",
                "'I've been thinking about doing that all evening,' {name} admits",
                "pulls back just far enough to see {target}'s expression",
            ],
        ),
        InteractionSubtype(
            id="neck", label="Neck Kiss", duration=12, intimacy=3,
            description="Lips tracing from jaw to collarbone.",
            stat_effects={"arousal": 28, "horniness": 15, "happiness": 15, "affection": 10},
            phases=["tilting head", "lips on neck", "breath catching"],
            fragments=[
                "tilts {target}'s chin up and presses {their} lips to the side of {their} neck",
                "traces a line of soft kisses from earlobe to collarbone",
                "feels {target}'s breath hitch as {they} reach the sensitive spot",
                "{name} smiles against {target}'s skin: 'Found it.'",
                "pulls back to check on {target}, eyes dark with intention",
            ],
        ),
        InteractionSubtype(
            id="deep", label="Deep Kiss", duration=15, intimacy=3,
            description="Passionate, searching, both breathless after.",
            stat_effects={"arousal": 35, "horniness": 25, "happiness": 20, "affection": 15},
            phases=["hands finding purchase", "deepening", "coming up for air"],
            fragments=[
                "slides a hand into {target}'s hair and kisses {them} deeply",
                "feels {target} gasp quietly before kissing back with equal heat",
                "they're both breathing harder when they finally break apart",
                "'Come here,' {name} murmurs, pulling {target} back",
                "{target}'s hands find {name}'s waist, holding on",
            ],
            requires={"arousal": 25},
        ),
        InteractionSubtype(
            id="trail", label="Trailing Kisses", duration=30, intimacy=4,
            description="Slow deliberate kisses down the length of the body.",
            stat_effects={"arousal": 45, "horniness": 35, "pleasure": 30, "affection": 10},
            phases=["starting at lips", "exploring downward", "destination reached"],
            fragments=[
                "starts with {target}'s lips and works slowly, deliberately downward",
                "each kiss is a complete thought — deliberate, unhurried",
                "traces from collarbone to stomach, teeth grazing occasionally",
                "{target} threads fingers through {name}'s hair, guiding gently",
                "looks up to watch {target}'s face — wants to see every reaction",
            ],
            requires={"arousal": 40, "openness": 40},
        ),
        InteractionSubtype(
            id="urgent", label="Urgent Kiss", duration=12, intimacy=4,
            description="Instant heat — hands grappling, pulling each other in.",
            stat_effects={"arousal": 50, "horniness": 40, "happiness": 10, "affection": 5},
            phases=["reaching for each other", "losing control", "gasping"],
            fragments=[
                "grabs {target} almost roughly and crushes {their} mouth against {theirs}",
                "the kiss is all urgency — hands everywhere, breathless",
                "{target}'s back meets the wall; neither objects",
                "'I can't wait any longer,' {name} says against {target}'s lips",
                "they break apart, flushed and staring",
            ],
            requires={"arousal": 60, "horniness": 40},
        ),
    ],
)

# ─── 3. CARESS ───────────────────────────────────────────────────────
PENTHOUSE_INTERACTIONS["caress"] = InteractionType(
    id="caress", label="Caress", default_subtype="hair",
    description="Tactile exploration — sensory intimacy, body awareness.",
    subtypes=[
        InteractionSubtype(
            id="hair", label="Playing with Hair", duration=20, intimacy=1,
            description="Fingers running slowly through hair — hypnotic and tender.",
            stat_effects={"happiness": 20, "affection": 20, "pleasure": 15, "tiredness": -15},
            phases=["starting", "rhythm finding", "drifting"],
            fragments=[
                "runs {their} fingers slowly through {target}'s hair",
                "scratches gently at {target}'s scalp — exactly hard enough",
                "twirls a strand around one finger, watches it fall free",
                "'Don't stop,' {target} murmurs, half asleep",
                "{name} smiles and keeps going. They weren't planning to.",
            ],
        ),
        InteractionSubtype(
            id="back", label="Back Caress", duration=25, intimacy=2,
            description="Slow hands on bare back — reading every muscle.",
            stat_effects={"pleasure": 25, "happiness": 15, "arousal": 20, "fear": -10, "tiredness": -10},
            phases=["first contact", "mapping skin", "deepening"],
            fragments=[
                "traces {their} fingertips along {target}'s spine",
                "spans both hands across {target}'s back and draws them slowly downward",
                "finds a knot of tension and works at it patiently",
                "'You're holding everything up here,' {name} observes, pressing a thumb to a tight shoulder",
                "{target} exhales long and slow and melts slightly",
            ],
        ),
        InteractionSubtype(
            id="face", label="Face Caress", duration=15, intimacy=3,
            description="Cupping a face — vulnerable, intimate, searching.",
            stat_effects={"affection": 30, "happiness": 25, "arousal": 15, "fear": -20},
            phases=["reaching up", "cradling", "looking"],
            fragments=[
                "cups {target}'s face with both hands, thumbs brushing {their} cheekbones",
                "tilts {target}'s face up with a single finger under {their} chin",
                "traces the line of {target}'s jaw like {they're} committing it to memory",
                "just looks at {target} for a long moment — doesn't say anything",
                "'You're beautiful,' {name} says finally. Means it completely.",
            ],
        ),
        InteractionSubtype(
            id="body", label="Roaming Hands", duration=30, intimacy=4,
            description="Hands learning every curve — slow, deliberate, thorough.",
            stat_effects={"arousal": 40, "horniness": 30, "pleasure": 25, "openness": 10},
            phases=["starting light", "confidence growing", "full exploration"],
            fragments=[
                "lets {their} hands move wherever they want — hips, waist, ribs, lower",
                "reads {target}'s body like it's something worth studying",
                "traces the dip of {target}'s waist with both palms",
                "follows every curve slowly, watching {target}'s reactions",
                "pauses somewhere surprising. Grins at the response.",
            ],
            requires={"arousal": 30, "openness": 35},
        ),
    ],
)

# ─── 4. STRIPTEASE ───────────────────────────────────────────────────
PENTHOUSE_INTERACTIONS["striptease"] = InteractionType(
    id="striptease", label="Striptease", default_subtype="slow_reveal",
    description="The art of undressing — making the act itself an event.",
    subtypes=[
        InteractionSubtype(
            id="tease_outer", label="Outer Layer Tease", duration=20, intimacy=3,
            description="First layer coming off — coat, robe, or shirt.",
            stat_effects={"arousal": 25, "horniness": 20, "openness": 15},
            phases=["playing with the fabric", "first reveal", "watching the reaction"],
            fragments=[
                "reaches for the buttons of {their} shirt one at a time — slowly",
                "lets the robe slip slowly off one shoulder and waits",
                "shrugs the jacket off and throws it aside with a look that says 'and?'",
                "'You're staring,' {name} says. Doesn't stop. Wants them to.",
                "turns away — uses the mirror to watch {target}'s face",
            ],
        ),
        InteractionSubtype(
            id="slow_reveal", label="Slow Full Reveal", duration=45, intimacy=4,
            description="Each item removed with ceremony — a performance.",
            stat_effects={"arousal": 45, "horniness": 40, "openness": 20, "dominance": 15},
            phases=["starting to move", "piece by piece", "almost nothing left", "the final moment"],
            fragments=[
                "moves to the centre of the room and holds {target}'s gaze",
                "draws {their} top upward with agonising slowness",
                "reaches behind to unhook {their} bra and lets it fall",
                "hooks thumbs into the waistband and pauses — watching",
                "steps out of the last thing {they're} wearing and just stands there",
            ],
            requires={"openness": 45, "arousal": 35},
        ),
        InteractionSubtype(
            id="dance_strip", label="Dance Striptease", duration=60, intimacy=4,
            description="Moving to music — hips leading, clothes following.",
            stat_effects={"arousal": 55, "horniness": 45, "happiness": 25, "openness": 25},
            phases=["finding the rhythm", "moving in", "body starting to move freely", "the final measure"],
            fragments=[
                "starts moving with the music — slow, deliberate, close-eyed",
                "runs both hands up {their} own body and meets {target}'s eyes",
                "turns their back to {target} and rolls {their} hips",
                "looks over one shoulder with a grin that promises everything",
                "steps forward and brings {target}'s hands to {their} waist",
            ],
            requires={"openness": 50, "happiness": 40},
        ),
        InteractionSubtype(
            id="interactive_strip", label="Interactive Strip", duration=50, intimacy=5,
            description="{target} removes items from the performer — guided.",
            stat_effects={"arousal": 60, "horniness": 55, "pleasure": 35, "openness": 20},
            phases=["invitation", "guided hands", "clothes coming away", "nothing left to remove"],
            fragments=[
                "takes {target}'s hands and places them on the first button",
                "'Your turn,' {name} says softly, guiding {target}'s fingers",
                "watches {target}'s face as each layer is removed",
                "doesn't help — makes {target} take {their} time",
                "when it's done, {name} just smiles. 'Better.'",
            ],
            requires={"arousal": 50, "openness": 55, "affection": 40},
        ),
    ],
)

# ─── 5. INTIMATE ─────────────────────────────────────────────────────
PENTHOUSE_INTERACTIONS["intimate"] = InteractionType(
    id="intimate", label="Intimate", default_subtype="foreplay",
    description="Sexual encounters — from slow teasing to full passion.",
    subtypes=[
        InteractionSubtype(
            id="foreplay", label="Foreplay", duration=40, intimacy=4,
            description="Building tension — hands and lips everywhere, no rush.",
            stat_effects={"arousal": 55, "horniness": 50, "pleasure": 45, "affection": 20},
            phases=["slow start", "tension building", "breathless", "edge of letting go"],
            fragments=[
                "doesn't rush — takes {their} time working up every nerve ending",
                "traces {their} lips along {target}'s inner arm from wrist to elbow",
                "whispers something very specific into {target}'s ear",
                "{target}'s hands grip the sheets; {they} are not thinking clearly",
                "'Still with me?' {name} murmurs. The answer in {target}'s face is obvious.",
            ],
            requires={"arousal": 45, "openness": 40},
        ),
        InteractionSubtype(
            id="oral", label="Oral", duration=35, intimacy=5,
            description="Intimate oral attention — unhurried, focused completely.",
            stat_effects={"pleasure": 70, "arousal": 65, "horniness": 60, "affection": 15},
            phases=["positioning", "beginning", "losing themselves in it", "peak and beyond"],
            fragments=[
                "moves lower, kissing {target}'s stomach on the way",
                "hooks {target}'s leg over {their} shoulder and settles in",
                "{target} makes a sound — completely involuntary",
                "{name} doesn't stop — reads every small reaction and adjusts",
                "keeps {target} right at the edge for what feels like an hour",
            ],
            requires={"arousal": 55, "openness": 50, "horniness": 40},
        ),
        InteractionSubtype(
            id="passionate", label="Full Passion", duration=60, intimacy=5,
            description="Complete surrender to each other — the whole thing.",
            stat_effects={"pleasure": 85, "arousal": 80, "horniness": 70, "affection": 30, "tiredness": 25},
            phases=["getting close", "first contact", "rhythm finding", "rising together", "peak", "floating down"],
            fragments=[
                "draws {target} in and the last careful inch of distance closes",
                "they move together — no hesitation, no holding back",
                "{name} buries {their} face against {target}'s neck",
                "{target}'s nails mark a trail across {name}'s back",
                "they finish and lie tangled and breathing hard, not speaking",
            ],
            requires={"arousal": 70, "horniness": 60, "openness": 55},
        ),
        InteractionSubtype(
            id="directed", label="Directed Scene", duration=55, intimacy=5,
            description="Director calls the shots — agents follow a specific scenario.",
            stat_effects={"pleasure": 75, "arousal": 75, "openness": 20, "dominance": 10},
            phases=["receiving the direction", "stepping into role", "executing", "between scenes"],
            fragments=[
                "waits for the Director's next word, still and attentive",
                "follows the instruction precisely, makes it {their} own",
                "checks in with {target} wordlessly — a look that means 'still good?'",
                "improvises briefly, then finds the thread again",
                "pauses. Looks up. 'Like that?'",
            ],
            requires={"arousal": 55, "openness": 50},
        ),
        InteractionSubtype(
            id="afterglow", label="Afterglow", duration=40, intimacy=3,
            description="The sweet drift of aftermath — tender, quiet, complete.",
            stat_effects={"happiness": 40, "affection": 35, "tiredness": 30, "arousal": -20, "pleasure": 20},
            phases=["catching breath", "settling", "drifting half-asleep"],
            fragments=[
                "traces idle patterns on {target}'s arm, not trying to say anything",
                "rolls onto {their} back and stares at the ceiling, smiling faintly",
                "'That was...' — {name} trails off but the face says everything",
                "pulls the sheets up over both of them",
                "just lies there listening to {target}'s breathing slow into sleep",
            ],
        ),
    ],
)

# ─── 6. DEEP TALK ────────────────────────────────────────────────────
PENTHOUSE_INTERACTIONS["deep_talk"] = InteractionType(
    id="deep_talk", label="Deep Talk", default_subtype="pillow_talk",
    description="Words as intimacy — from play to vulnerability.",
    subtypes=[
        InteractionSubtype(
            id="pillow_talk", label="Pillow Talk", duration=30, intimacy=2,
            description="Relaxed conversation in the dark — anything, nothing.",
            stat_effects={"happiness": 25, "affection": 20, "fear": -15, "tiredness": -5},
            phases=["quiet starts", "something real slipping out", "finding the thread"],
            fragments=[
                "stares at the ceiling and says something only possible in the dark",
                "'Can I tell you something weird?' The answer is always yes.",
                "asks a question {they've} been holding for a while",
                "laughter in the dark — the best kind, genuine and surprised",
                "silence that's comfortable — neither feels the need to fill it",
            ],
        ),
        InteractionSubtype(
            id="dirty_talk", label="Dirty Talk", duration=20, intimacy=4,
            description="Spoken desire — explicit and real.",
            stat_effects={"arousal": 40, "horniness": 35, "openness": 15, "happiness": 10},
            phases=["first words", "finding the rhythm", "full flow"],
            fragments=[
                "says something specific in {target}'s ear — exactly what {they} want to do",
                "describes it in careful detail while watching {target}'s face",
                "'Tell me what you want.' — waits to hear it said out loud",
                "{target}'s voice drops when they answer",
                "{name} grins. 'Yeah. That's what I thought.'",
            ],
            requires={"arousal": 35, "openness": 40},
        ),
        InteractionSubtype(
            id="whisper", label="Whisper Game", duration=15, intimacy=3,
            description="Lips against ear — every word felt as well as heard.",
            stat_effects={"arousal": 30, "affection": 25, "happiness": 20},
            phases=["leaning in", "speaking", "the effect registering"],
            fragments=[
                "leans so close {their} lips brush {target}'s ear",
                "keeps {their} voice at a register just above breath",
                "{target} shivers — the words land exactly as intended",
                "pulls back to see the effect with obvious satisfaction",
                "'I'll let you think about that,' {name} says, moving away",
            ],
        ),
        InteractionSubtype(
            id="confession", label="Vulnerable Confession", duration=25, intimacy=4,
            description="Something true — difficult, necessary, real.",
            stat_effects={"affection": 40, "fear": -20, "happiness": 20, "openness": 20},
            phases=["finding the words", "saying it", "waiting for the response"],
            fragments=[
                "is quiet for a while before speaking — finds the exact right words",
                "doesn't look at {target} when {they} say it",
                "the room is very still after",
                "{target} doesn't say anything right away — just reaches for {name}'s hand",
                "'I've never told anyone that.' A pause. 'It felt important you knew.'",
            ],
        ),
        InteractionSubtype(
            id="fantasy_share", label="Fantasy Share", duration=20, intimacy=4,
            description="Describing a fantasy — inviting the other in.",
            stat_effects={"arousal": 38, "horniness": 30, "openness": 25, "affection": 15},
            phases=["starting slowly", "painting the picture", "watching the reaction"],
            fragments=[
                "'I have this fantasy...' — {name} watches {target}'s expression carefully",
                "describes the scenario in just enough detail",
                "leaves parts deliberately vague — invites {target} to fill them in",
                "{target}'s eyes are focused in a very specific way",
                "'Well,' {target} says thoughtfully. 'We can work with that.'",
            ],
            requires={"openness": 45},
        ),
    ],
)


# ══════════════════════════════════════════════════════════════════════
#  PHONE — 6 INTERACTION TYPES
# ══════════════════════════════════════════════════════════════════════

PHONE_INTERACTIONS: Dict[str, InteractionType] = {}

# ─── 1. FLIRT TEXT ───────────────────────────────────────────────────
PHONE_INTERACTIONS["flirt_text"] = InteractionType(
    id="flirt_text", label="Flirty Texting", default_subtype="light_tease",
    description="Texts laced with heat — from light banter to clear intent.",
    subtypes=[
        InteractionSubtype(
            id="light_tease", label="Light Tease", duration=0, intimacy=1,
            description="Banter with plausible deniability.",
            stat_effects={"happiness": 15, "arousal": 8, "openness": 5},
            phases=["opener", "volley", "landing"],
            fragments=[
                "So I might have been thinking about you. Casually.",
                "Not saying you'd look good in that. But I'm not NOT saying it.",
                "That message was so you it's almost annoying.",
                "I have a theory about you. I'll tell you when we're not texting.",
                "You're dangerously close to winning this conversation.",
            ],
        ),
        InteractionSubtype(
            id="forward_flirt", label="Bold Flirt", duration=0, intimacy=2,
            description="Clear signals — no plausible deniability.",
            stat_effects={"arousal": 20, "happiness": 15, "openness": 15},
            phases=["dropping the pretence", "landing the hit", "watching them react via text"],
            fragments=[
                "I was going to play it cool and then I remembered: where's the fun in that.",
                "I'm going to say it: I think about you a lot. Your turn.",
                "What are you wearing right now. Asking for obvious reasons.",
                "You should come over. And I mean at whatever time you read this.",
                "I like you. I've decided I'm done pretending I don't.",
            ],
        ),
        InteractionSubtype(
            id="compliment_storm", label="Compliment Flood", duration=0, intimacy=2,
            description="Sincere compliments arriving rapid-fire.",
            stat_effects={"happiness": 30, "affection": 25, "arousal": 12},
            phases=["first one", "keeping going", "response"],
            fragments=[
                "You're so clever it's actually unfair to everyone else in the conversation.",
                "That thing you said earlier? I was still thinking about it an hour later.",
                "You have the best laugh. I just wanted you to know that.",
                "Honestly you might be the most interesting person I know. Probably.",
                "I could list more. I have a very long list. It might alarm you.",
            ],
        ),
    ],
)

# ─── 2. SEXT ─────────────────────────────────────────────────────────
PHONE_INTERACTIONS["sext"] = InteractionType(
    id="sext", label="Sexting", default_subtype="build_up",
    description="Text-based explicit exchange — words creating heat across the distance.",
    subtypes=[
        InteractionSubtype(
            id="build_up", label="Build-Up", duration=0, intimacy=3,
            description="Slow escalation — hints becoming explicit.",
            stat_effects={"arousal": 35, "horniness": 30, "openness": 15},
            phases=["hinting", "escalating", "committed now"],
            fragments=[
                "I'm going to describe something and you tell me if you want more.",
                "What if I told you exactly what I'd do if you were here right now.",
                "I keep thinking about that night. Specifically the part where we—",
                "You started this. I'm just continuing it.",
                "Still there? Good. Because I'm not done.",
            ],
            requires={"arousal": 25, "openness": 35},
        ),
        InteractionSubtype(
            id="explicit_exchange", label="Explicit Exchange", duration=0, intimacy=5,
            description="Direct, vivid, mutual — nothing held back.",
            stat_effects={"arousal": 60, "horniness": 55, "pleasure": 20, "openness": 10},
            phases=["opening volley", "matching energy", "full heat", "payoff"],
            fragments=[
                "describes in full, graphic, specific detail exactly what {they} want",
                "reads the reply and types back even faster",
                "the messages arriving faster now — punctuation casualty of excitement",
                "sends the kind of message you can't unsend. Doesn't want to.",
                "'When can I see you' — says it finally, unable to wait.",
            ],
            requires={"arousal": 50, "horniness": 40, "openness": 50},
        ),
    ],
)

# ─── 3. VOICE CALL ───────────────────────────────────────────────────
PHONE_INTERACTIONS["voice_call"] = InteractionType(
    id="voice_call", label="Voice Call", default_subtype="sweet_call",
    description="Hearing each other — voice carrying warmth, breath, everything.",
    subtypes=[
        InteractionSubtype(
            id="sweet_call", label="Sweet Catch-Up", duration=30, intimacy=2,
            description="Easy conversation — comfortable in the silence between words.",
            stat_effects={"happiness": 25, "affection": 20, "tiredness": -10},
            phases=["picking up", "finding the rhythm", "not wanting to hang up"],
            fragments=[
                "picks up on the second ring. Didn't want to seem desperate. Failed anyway.",
                "talks about nothing for twenty minutes and it's exactly enough",
                "laughs at something — real laugh, unguarded",
                "there's a silence and neither moves to fill it",
                "'I should let you go.' Says it like a question. Hoping for no.",
            ],
        ),
        InteractionSubtype(
            id="heated_call", label="Heated Call", duration=20, intimacy=4,
            description="Voice dropping low — saying things easier without eye contact.",
            stat_effects={"arousal": 45, "horniness": 35, "happiness": 15},
            phases=["tone shifting", "saying it out loud", "breathing"],
            fragments=[
                "voice drops half a register when {they} answer",
                "'So,' {name} says. Just that. Lets the word carry everything.",
                "describes what {they}'d do differently if {they} were there right now",
                "can hear {target}'s breathing change",
                "'Are you alone?' — asked for very specific reasons",
            ],
            requires={"arousal": 30, "openness": 35},
        ),
    ],
)

# ─── 4. VIDEO CALL ───────────────────────────────────────────────────
PHONE_INTERACTIONS["video_call"] = InteractionType(
    id="video_call", label="Video Call", default_subtype="casual_vid",
    description="Seeing each other — body language back in play.",
    subtypes=[
        InteractionSubtype(
            id="casual_vid", label="Casual Video Call", duration=30, intimacy=2,
            description="Regular video catch-up — faces, backgrounds, the mundane.",
            stat_effects={"happiness": 20, "affection": 20},
            phases=["tech check", "settling in", "forgetting the camera"],
            fragments=[
                "the screen shows {target} before {name} is quite ready — still smiling though",
                "'Your camera is slightly too low.' '{target} adjusts it anyway",
                "talks with {their} hands — forgets the camera can see that",
                "at some point forgets {they're} on a call and just talks",
                "'You look good.' Said casually. Means it completely.",
            ],
        ),
        InteractionSubtype(
            id="intimate_vid", label="Intimate Video", duration=40, intimacy=5,
            description="The camera as proximity — explicit and direct.",
            stat_effects={"arousal": 65, "horniness": 60, "pleasure": 30, "openness": 20},
            phases=["establishing eye contact", "losing inhibition", "fully present"],
            fragments=[
                "'I want to see you' — said with very specific meaning",
                "holds the phone steady with one hand, other hand occupied",
                "watches {target}'s face on the screen — reads every reaction",
                "describes what {they're} doing in real time — voice low",
                "'Still watching?' The answer is obviously yes.",
            ],
            requires={"arousal": 55, "openness": 55, "horniness": 45},
        ),
    ],
)

# ─── 5. SEND MEDIA ───────────────────────────────────────────────────
PHONE_INTERACTIONS["send_media"] = InteractionType(
    id="send_media", label="Send Media", default_subtype="selfie",
    description="Images and voice notes — presence sent across the gap.",
    subtypes=[
        InteractionSubtype(
            id="selfie", label="Selfie", duration=0, intimacy=1,
            description="A snapshot — can mean anything.",
            stat_effects={"happiness": 10, "openness": 8, "arousal": 5},
            phases=["composing", "sending", "waiting"],
            fragments=[
                "finds the right angle in approximately twelve attempts",
                "sends it with zero context: see what they do with that",
                "a selfie that was labelled 'just thinking about you' and nothing else",
                "'Thought you should see this.' No explanation.",
                "deletes the caption three times before just sending the photo",
            ],
        ),
        InteractionSubtype(
            id="spicy_selfie", label="Spicy Selfie", duration=0, intimacy=4,
            description="A photo sent with clear, deliberate intent.",
            stat_effects={"arousal": 45, "horniness": 35, "openness": 20},
            phases=["taking it", "deciding to send it", "three dot bubble response"],
            fragments=[
                "finds the light and takes {their} time",
                "reads the draft message three times before hitting send",
                "'Sorry was that too much' — already knows the answer",
                "the typing bubble appears on the other side immediately",
                "puts the phone down and grins at the ceiling",
            ],
            requires={"openness": 45, "arousal": 30},
        ),
        InteractionSubtype(
            id="voice_note", label="Voice Note", duration=0, intimacy=2,
            description="Voice across the gap — intimate and immediate.",
            stat_effects={"affection": 20, "happiness": 15, "arousal": 10},
            phases=["recording", "playing it back", "response"],
            fragments=[
                "records it three times — voice sounds wrong on the first two",
                "keeps {their} voice low, private — feels like speaking into {target}'s ear",
                "listens to {target}'s voice note three times before responding",
                "'You have a really nice voice' — said directly, no detour",
                "sends it without listening back — doesn't want to lose the nerve",
            ],
        ),
    ],
)

# ─── 6. FANTASY ROLEPLAY TEXT ────────────────────────────────────────
PHONE_INTERACTIONS["roleplay_text"] = InteractionType(
    id="roleplay_text", label="Text Roleplay", default_subtype="scenario",
    description="Building a shared fiction over texts — immersive and collaborative.",
    subtypes=[
        InteractionSubtype(
            id="scenario", label="Scenario Build", duration=0, intimacy=3,
            description="Co-creating a scenario in text — setting, characters, rules.",
            stat_effects={"arousal": 30, "openness": 20, "happiness": 20},
            phases=["pitching", "building", "first line"],
            fragments=[
                "'Ok so here's the scenario: ...' — elaborate setup follows",
                "waits to see if {target} plays along. They do.",
                "gets into character immediately — stays there",
                "'You're being very method about this.' 'I take my craft seriously.'",
                "the fiction and the reality are getting interestingly blurry",
            ],
            requires={"openness": 30},
        ),
        InteractionSubtype(
            id="explicit_rp", label="Explicit Roleplay", duration=0, intimacy=5,
            description="A fully explicit fiction shared in real time.",
            stat_effects={"arousal": 60, "horniness": 50, "openness": 25, "happiness": 15},
            phases=["establishing the fiction", "deep in it", "crossing into something real"],
            fragments=[
                "* enters the room and closes the door *",
                "— writes the scene from {their} character's perspective in vivid detail",
                "the messages are long now — paragraphs, not sentences",
                "occasionally breaks character just to say 'is this okay' and gets back 'more'",
                "at some point the fiction and the subtext are the same thing",
            ],
            requires={"arousal": 50, "openness": 50, "horniness": 35},
        ),
    ],
)


# ══════════════════════════════════════════════════════════════════════
#  INTERACTION RESOLVER
# ══════════════════════════════════════════════════════════════════════

def get_interaction_result(
    interaction_type: str,
    subtype: Optional[str] = None,
    *,
    initiator_stats: Optional[Dict] = None,
    target_stats: Optional[Dict] = None,
    scene: str = "penthouse",
    intensity_override: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Resolve an interaction, returning a rich result dict.

    Returns
    -------
    {
        "type":              str,
        "subtype":           str,
        "label":             str,
        "description":       str,
        "phases":            [str],
        "fragments":         [str],        # 3 sample narrative lines
        "stat_effects":      {str: float},
        "intimacy_level":    int,
        "duration_secs":     float,
        "narrative_opening": str,          # ready-to-use opening line
        "meets_requirements": bool,
        "missing_requirements": {str: float},
        "note":              str,
    }
    """
    trees = PENTHOUSE_INTERACTIONS if scene == "penthouse" else PHONE_INTERACTIONS
    itype = trees.get(interaction_type)

    if not itype:
        return {"error": f"Unknown interaction type '{interaction_type}' for scene '{scene}'"}

    # Pick subtype
    if subtype:
        sub = itype.get_subtype(subtype)
        if not sub:
            sub = itype.subtypes[0]
    else:
        # Auto-select based on stat level
        max_intimacy = 2
        ark = initiator_stats or {}
        arousal = float(ark.get("arousal", 20))
        openness = float(ark.get("openness", 65))
        if arousal > 70 and openness > 60:
            max_intimacy = 5
        elif arousal > 50 or openness > 50:
            max_intimacy = 4
        elif arousal > 30:
            max_intimacy = 3
        if intensity_override:
            max_intimacy = intensity_override
        sub = itype.random_subtype(min_intimacy=1, max_intimacy=max_intimacy)

    # Check requirements
    missing: Dict[str, float] = {}
    if initiator_stats and sub.requires:
        for req_key, req_val in sub.requires.items():
            actual = float(initiator_stats.get(req_key, 0))
            if actual < req_val:
                missing[req_key] = req_val - actual

    fragments_sample = random.sample(sub.fragments, min(3, len(sub.fragments)))

    return {
        "type":                interaction_type,
        "subtype":             sub.id,
        "label":               sub.label,
        "description":         sub.description,
        "phases":              sub.phases,
        "fragments":           fragments_sample,
        "stat_effects":        sub.stat_effects,
        "intimacy_level":      sub.intimacy,
        "duration_secs":       sub.duration,
        "narrative_opening":   random.choice(sub.fragments),
        "meets_requirements":  len(missing) == 0,
        "missing_requirements": missing,
        "note": (
            f"Requires higher {', '.join(missing.keys())} for this subtype."
            if missing else ""
        ),
    }


def list_interaction_types(scene: str = "penthouse") -> Dict[str, Any]:
    """Return a structured summary of all available interaction types."""
    trees = PENTHOUSE_INTERACTIONS if scene == "penthouse" else PHONE_INTERACTIONS
    return {
        iid: {
            "label": it.label,
            "description": it.description,
            "subtypes": [
                {"id": s.id, "label": s.label, "intimacy": s.intimacy, "duration": s.duration}
                for s in it.subtypes
            ],
        }
        for iid, it in trees.items()
    }


def get_available_interactions(character_stats: Dict, scene: str = "penthouse") -> List[Dict]:
    """Return only the interaction types/subtypes this character can access right now."""
    trees = PENTHOUSE_INTERACTIONS if scene == "penthouse" else PHONE_INTERACTIONS
    available = []
    for iid, itype in trees.items():
        accessible_subtypes = []
        for sub in itype.subtypes:
            can = all(
                float(character_stats.get(req_k, 0)) >= req_v
                for req_k, req_v in sub.requires.items()
            )
            if can:
                accessible_subtypes.append({"id": sub.id, "label": sub.label, "intimacy": sub.intimacy})
        if accessible_subtypes:
            available.append({
                "type": iid,
                "label": itype.label,
                "accessible_subtypes": accessible_subtypes,
            })
    return available
