"""Training data generator for Gemma 270M fine-tuning.

Generates JSONL datasets from CosySim's tag system, tool definitions,
and scene patterns.  Each dataset targets a specific router capability:

  1. tag_extraction   — parse [MOOD:x] [IMAGE:x] etc from LLM output
  2. tool_routing     — classify user intent → tool call
  3. priority_classify — request → priority tier
  4. decision_classify — character state → next action
  5. response_validate — check if output matches expected format

Usage::

    python -m training.generate_datasets          # all datasets
    python -m training.generate_datasets --only tag_extraction
    python -m training.generate_datasets --out training/datasets
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── Constants ────────────────────────────────────────────────────────

MOODS = [
    "happy", "sad", "angry", "nervous", "excited", "bored",
    "flirty", "shy", "confident", "embarrassed", "curious",
    "playful", "tired", "surprised", "annoyed", "dreamy",
    "mischievous", "tender", "sassy", "worried",
]

ACTIONS = [
    "sit_down", "stand_up", "walk_over", "lean_against_wall",
    "look_away", "cross_arms", "smile", "laugh", "giggle",
    "wave", "wink", "blush", "sigh", "yawn", "stretch",
    "dance", "twirl", "pose", "flip_hair", "bite_lip",
    "pout", "hug", "nudge", "lean_in", "pull_away",
    "check_phone", "put_phone_down", "take_photo",
]

IMAGE_PROMPTS = [
    "a warm selfie in the bedroom",
    "a candid photo by the window",
    "a cute selfie making a peace sign",
    "a mirror selfie in casual outfit",
    "a playful pose on the couch",
    "a close-up portrait with soft lighting",
    "a full body shot in the living room",
    "a silly face selfie",
    "a cozy photo wrapped in blanket",
    "a sunset photo on the balcony",
]

VOICE_STYLES = [
    "whisper", "shout", "sing", "giggle", "serious",
    "playful", "seductive", "nervous", "excited", "deadpan",
]

STATS = [
    ("arousal", (-20, 30)), ("trust", (-15, 20)),
    ("attraction", (-10, 25)), ("energy", (-30, 20)),
    ("mood_score", (-20, 20)), ("confidence", (-10, 15)),
]

DIALOGUE_TEMPLATES = [
    "Hey, what's up?",
    "I was just thinking about you.",
    "Want to do something fun?",
    "*smiles warmly* That's really sweet of you.",
    "I'm not sure about that... let me think.",
    "*laughs* Oh my god, that's hilarious!",
    "Can we talk about something?",
    "I really enjoyed our conversation earlier.",
    "*sighs* It's been such a long day.",
    "You always know how to make me smile.",
    "I've been meaning to tell you something.",
    "*looks away shyly* I, um...",
    "That reminds me of something funny.",
    "I feel like we haven't talked in ages!",
    "Honestly? I'm a little nervous right now.",
]

TOOL_NAMES = [
    "search_memory", "store_memory", "get_character_state",
    "adjust_relationship", "update_mood", "roll_dice",
    "get_game_state", "set_game_state", "generate_image_request",
    "get_scene_context", "wardrobe_get", "wardrobe_remove_item",
    "send_selfie", "send_voice_message", "check_relationship",
    "get_conversation_heat", "bump_conversation_heat",
    "get_dialog_options", "perform_interaction",
    "get_random_topic", "suggest_activity",
]


# ── Dataset generators ───────────────────────────────────────────────

def _random_tags(min_tags: int = 1, max_tags: int = 4) -> tuple[str, dict]:
    """Generate random tag string and structured extraction."""
    n = random.randint(min_tags, max_tags)
    tag_types = random.sample(
        ["mood", "action", "image", "stat", "voice", "selfie"],
        min(n, 6),
    )
    tags_str = ""
    extracted: Dict[str, Any] = {}

    for tt in tag_types:
        if tt == "mood":
            m = random.choice(MOODS)
            tags_str += f" [MOOD:{m}]"
            extracted["mood"] = m
        elif tt == "action":
            a = random.choice(ACTIONS)
            tags_str += f" [ACTION:{a}]"
            extracted["action"] = a
        elif tt == "image":
            p = random.choice(IMAGE_PROMPTS)
            tags_str += f" [IMAGE:{p}]"
            extracted.setdefault("images", []).append(p)
        elif tt == "selfie":
            p = random.choice(IMAGE_PROMPTS)
            tags_str += f" [SELFIE:{p}]"
            extracted.setdefault("images", []).append(p)
        elif tt == "stat":
            stat_name, (lo, hi) = random.choice(STATS)
            val = random.randint(lo, hi)
            sign = "+" if val >= 0 else ""
            tags_str += f" [STAT:{stat_name}{sign}{val}]"
            extracted.setdefault("stats", {})[stat_name] = val
        elif tt == "voice":
            v = random.choice(VOICE_STYLES)
            tags_str += f" [VOICE:{v}]"
            extracted["voice"] = v

    return tags_str.strip(), extracted


def generate_tag_extraction(count: int = 800) -> List[Dict]:
    """Dataset 1: tag extraction from LLM output."""
    examples = []
    for _ in range(count):
        dialogue = random.choice(DIALOGUE_TEMPLATES)
        tags_str, extracted = _random_tags()
        # Insert tags at random positions in dialogue
        words = dialogue.split()
        insert_pos = random.randint(0, len(words))
        text_with_tags = " ".join(words[:insert_pos]) + " " + tags_str + " " + " ".join(words[insert_pos:])
        text_with_tags = text_with_tags.strip()

        extracted["clean_text"] = dialogue
        tool_call = json.dumps({"name": "route_tags", "arguments": extracted})

        examples.append({
            "instruction": "Extract all tags from the following LLM output and return a structured tool call.",
            "input": text_with_tags,
            "output": f"<tool_call>{tool_call}</tool_call>",
        })
    return examples


def generate_tool_routing(count: int = 400) -> List[Dict]:
    """Dataset 2: classify user/agent intent to correct tool call."""
    intents = [
        ("I want to know how {char} feels about me", "get_character_state", {"character_id": "{char}"}),
        ("Remember that the player likes {topic}", "store_memory", {"text": "player likes {topic}", "character_id": "system"}),
        ("What do I remember about {topic}?", "search_memory", {"query": "{topic}"}),
        ("How is the relationship between {char_a} and {char_b}?", "check_relationship", {"character_a": "{char_a}", "character_b": "{char_b}"}),
        ("Make {char} feel more {mood}", "update_mood", {"character_id": "{char}", "mood_updates": "__MOOD_JSON__"}),
        ("{char} should trust {char_b} more", "adjust_relationship", {"character_a": "{char}", "character_b": "{char_b}", "trust_delta": 10}),
        ("Roll a dice to decide", "roll_dice", {"sides": 6, "count": 1}),
        ("What's the current game state?", "get_game_state", {"game_id": "current"}),
        ("Take a selfie", "send_selfie", {"character_id": "{char}", "description": "a quick selfie"}),
        ("Send a voice note saying {text}", "send_voice_message", {"character_id": "{char}", "text": "{text}"}),
        ("What can I do right now?", "get_dialog_options", {"character_id": "{char}", "context": "current_scene"}),
        ("How hot is this conversation?", "get_conversation_heat", {"character_id": "{char}", "scene_id": "current"}),
        ("What's {char} wearing?", "wardrobe_get", {"character_id": "{char}"}),
        ("What's happening in the scene?", "get_scene_context", {"scene": "current"}),
        ("Suggest something fun to do", "suggest_activity", {"scene_id": "current"}),
        ("Give me a random topic to talk about", "get_random_topic", {"category": "general"}),
        ("Take off {char}'s jacket", "wardrobe_remove_item", {"character_id": "{char}", "item_id": "jacket", "removed_by": "player"}),
        # ── Extended skill routing intents ──
        ("Search Nexus for {topic}", "nexus_search", {"query": "{topic}"}),
        ("Ask Nexus how {topic} works", "nexus_ask", {"question": "how does {topic} work?"}),
        ("Store this decision about {topic}", "nexus_add", {"title": "Decision: {topic}", "content": "{text}"}),
        ("Start research on {topic}", "nexus_research", {"question": "{topic}"}),
        ("Generate an image of {char} at the beach", "generate_image_request", {"prompt": "{char} at the beach"}),
        ("Check system health", "system_status", {}),
        ("What skills are available?", "list_all_skills", {}),
        ("Start a mystery game", "games_mystery_start", {"character_id": "{char}"}),
        ("Roll for truth or dare", "games_tod_roll", {"character_id": "{char}"}),
        ("Check {char}'s phone messages", "phone_get_messages", {"character_id": "{char}"}),
        ("Send {char} a text message", "phone_send_message", {"character_id": "{char}", "text": "{text}"}),
        ("What's the conversation history with {char}?", "get_conversation_history", {"character_id": "{char}"}),
        ("Change the lighting to dim", "set_environment", {"lighting": "dim"}),
        ("Play some music", "play_ambient", {"sound": "music", "scene_id": "current"}),
        ("How are all the characters feeling?", "get_all_character_states", {}),
        ("Log this session to Nexus", "nexus_log_session", {"project": "CosySim"}),
        ("Store a code snippet about {topic}", "coding_store_snippet", {"title": "{topic}", "code": "# example"}),
    ]

    chars = ["lola", "aria", "viktor", "frankie", "mira"]
    topics = [
        "coffee", "music", "movies", "cats", "cooking", "travel", "games",
        "books", "fashion", "sports", "art", "science", "history", "dreams",
        "space", "nature", "technology", "dance", "photography", "yoga",
    ]
    texts = [
        "hello!", "I miss you", "thinking of you", "want to hang out?",
        "good morning!", "how's your day?", "can we talk?", "I'm bored",
        "what are you doing?", "let's do something fun", "I had a dream about you",
        "check this out!", "are you free later?", "I need your advice",
    ]

    examples = []
    for _ in range(count):
        template, tool_name, args_template = random.choice(intents)
        char = random.choice(chars)
        char_b = random.choice([c for c in chars if c != char])
        topic = random.choice(topics)
        mood = random.choice(MOODS)
        text = random.choice(texts)

        input_text = template.format(
            char=char, char_a=char, char_b=char_b,
            topic=topic, mood=mood, text=text,
        )
        args = {}
        for k, v in args_template.items():
            if isinstance(v, str):
                formatted = v.format(
                    char=char, char_a=char, char_b=char_b,
                    topic=topic, mood=mood, text=text,
                )
                if formatted == "__MOOD_JSON__":
                    formatted = json.dumps({mood: 20})
                args[k] = formatted
            else:
                args[k] = v

        tool_call = json.dumps({"name": tool_name, "arguments": args})
        examples.append({
            "instruction": "Classify the following intent and return the appropriate tool call.",
            "input": input_text,
            "output": f"<tool_call>{tool_call}</tool_call>",
        })
    return examples


def generate_priority_classify(count: int = 300) -> List[Dict]:
    """Dataset 3: classify request priority and tier."""
    scenes = [
        "bedroom_scene", "phone_scene", "lounge_scene", "casino_scene",
        "gallery_scene", "realm_scene", "tavern_scene", "coders_scene",
        "games_scene", "hub_scene", "arena_scene", "shop_scene",
    ]
    chars = ["lola", "aria", "viktor", "frankie", "mira"]
    actions_realtime = [
        "character responding to player speech",
        "player waiting for response",
        "combat round narration",
        "player making critical choice",
        "real-time dialogue exchange",
    ]
    actions_interactive = [
        "narrator describing scene",
        "character performing action",
        "generating image prompt",
        "NPC describing environment",
        "group conversation round",
        "code review generation",
        "artwork description",
    ]
    actions_background = [
        "autonomous text from NPC",
        "checking if NPC should text player",
        "NPC idle chatter",
        "generating emoji reaction",
        "autonomous mood update",
        "scheduling idle animation",
    ]
    actions_batch = [
        "embedding memory for RAG",
        "storing decision to Nexus",
        "auto-training threshold check",
        "bulk memory indexing",
        "nightly knowledge export",
    ]
    actions_router = [
        "classifying tags from stream",
        "validating response format",
        "route tool call",
        "priority classification",
        "NPC decision tree evaluation",
    ]

    tier_map = {
        "realtime": ("gpu", ["interactive_dialogue", "game_critical", "user_facing", "combat_narration"]),
        "interactive": ("gpu", ["narration", "scene_action", "creative", "multi_character", "game_action"]),
        "background": ("cpu", ["auto_text", "decision_check", "ambient", "trivial_generation", "mood_update"]),
        "batch": ("cpu", ["embedding", "knowledge_write", "maintenance", "indexing", "export"]),
        "router": ("router", ["tag_extraction", "validation", "tool_routing", "meta_routing", "decision_classify"]),
    }

    noise_options = [
        "", " (high load)", " (idle)", " (model warm)", " (cold start)",
        " (VRAM 80%)", " (queue depth 3)", " (priority override)",
        " (batch window)", " (low latency required)",
    ]

    examples = []
    for _ in range(count):
        scene = random.choice(scenes)
        char = random.choice(chars)
        priority = random.choice(list(tier_map.keys()))
        tier, reasons = tier_map[priority]
        reason = random.choice(reasons)

        if priority == "realtime":
            action = random.choice(actions_realtime)
        elif priority == "interactive":
            action = random.choice(actions_interactive)
        elif priority == "background":
            action = random.choice(actions_background)
        elif priority == "batch":
            action = random.choice(actions_batch)
        else:
            action = random.choice(actions_router)
            scene = "system"

        noise = random.choice(noise_options)
        context = f"{scene}: {char} {action}" if scene != "system" else f"system: {action}"
        output = json.dumps({"priority": priority, "tier": tier, "reason": reason})
        examples.append({
            "instruction": "Classify the following request's priority level and target tier.",
            "input": context + noise,
            "output": output,
        })
    return examples


def generate_decision_classify(count: int = 300) -> List[Dict]:
    """Dataset 4: NPC state → next action decision."""
    actions_map = [
        ({"mood": "bored", "energy_low": True, "player_nearby": True}, "speak", "comment about being bored"),
        ({"mood": "happy", "energy_low": False, "player_nearby": False}, "idle", ""),
        ({"mood": "flirty", "energy_low": False, "player_nearby": True}, "speak", "playful comment"),
        ({"mood": "tired", "energy_low": True, "player_nearby": False}, "rest", ""),
        ({"mood": "excited", "energy_low": False, "player_nearby": True}, "suggest_activity", "something fun"),
        ({"mood": "sad", "energy_low": True, "player_nearby": True}, "speak", "share feelings"),
        ({"mood": "curious", "energy_low": False, "player_nearby": True}, "ask_question", "about player"),
        ({"mood": "nervous", "energy_low": False, "player_nearby": True}, "fidget", ""),
        ({"mood": "mischievous", "energy_low": False, "player_nearby": True}, "tease", "playful teasing"),
        ({"mood": "playful", "energy_low": False, "player_nearby": False}, "text_player", "send fun message"),
    ]

    examples = []
    for _ in range(count):
        state_template, action, hint = random.choice(actions_map)
        char = random.choice(["lola", "aria", "viktor", "frankie", "mira"])
        energy = random.randint(10, 90)
        mood_score = random.randint(-20, 40)

        state_str = (
            f"Character: {char}, mood={state_template['mood']}, "
            f"energy={energy}, mood_score={mood_score}, "
            f"player_nearby={state_template['player_nearby']}, "
            f"last_action={'idle' if random.random() < 0.5 else 'speak'}"
        )
        output = json.dumps({
            "action": action,
            "target": "player" if state_template.get("player_nearby") else "none",
            "message_hint": hint,
        })
        examples.append({
            "instruction": "Given the character's current state, decide what they should do next.",
            "input": state_str,
            "output": output,
        })
    return examples


def generate_response_validate(count: int = 300) -> List[Dict]:
    """Dataset 5: validate LLM response format."""
    chars = ["lola", "aria", "viktor", "frankie", "mira"]
    moods = MOODS[:10]
    actions = ACTIONS[:15]

    def _make_valid_dialogue() -> tuple[str, str]:
        templates = [
            "*smiles warmly* Hey there! How's it going?",
            "I was just thinking about you!",
            "Oh, that's interesting. Tell me more.",
            f"*{random.choice(actions)}* Did you miss me?",
            f"*laughs* You always know how to make me {random.choice(moods)}.",
            f"I'm feeling a bit {random.choice(moods)} today, but seeing you helps.",
            "Want to do something fun together?",
            f"*{random.choice(actions)}* I've been waiting for you.",
            "That reminds me of something funny that happened earlier.",
            "Can we talk about something? It's been on my mind.",
            f"*{random.choice(actions)}* You're so sweet, you know that?",
            "I had the craziest dream last night...",
            f"Honestly? I'm feeling pretty {random.choice(moods)} right now.",
            "Tell me more about yourself. I want to know everything!",
            f"*{random.choice(actions)}* Mmm, that sounds nice.",
        ]
        text = random.choice(templates)
        reason = "valid_dialogue" if not text.startswith("*") else "valid_dialogue_with_action"
        return text, reason

    def _make_valid_json() -> tuple[str, str]:
        variants = [
            json.dumps({"action": random.choice(actions), "text": "hello"}),
            json.dumps({"mood": random.choice(moods), "energy": random.randint(20, 90)}),
            json.dumps({"target": random.choice(chars), "action": "approach"}),
            json.dumps({"type": "emote", "emote": random.choice(actions)}),
            json.dumps({"state_update": {"mood": random.choice(moods), "confidence": random.randint(30, 80)}}),
        ]
        return random.choice(variants), "valid_json"

    def _make_valid_tool_call() -> tuple[str, str]:
        tool = random.choice(TOOL_NAMES)
        args = {"query": random.choice(["music", "memories", "feelings"])} if "search" in tool else {"sides": 6}
        tc = json.dumps({"name": tool, "arguments": args})
        return f"<tool_call>{tc}</tool_call>", "valid_tool_call"

    def _make_invalid() -> tuple[str, str, str]:
        """Returns (expected_format, actual_output, reason)."""
        invalids = [
            ("json_action", "Sure! I'd love to help you with that.", "plain_text_not_json"),
            ("json_action", "Here's what I think we should do:", "plain_text_not_json"),
            ("json_action", f"I think {random.choice(chars)} should {random.choice(actions)}.", "plain_text_not_json"),
            ("dialogue", json.dumps({"response": "hello"}), "json_not_dialogue"),
            ("dialogue", json.dumps({"text": "Hi", "mood": random.choice(moods)}), "json_not_dialogue"),
            ("dialogue", "", "empty_response"),
            ("dialogue", "   ", "empty_response"),
            ("tool_call", f"I'll {random.choice(actions)} for you now.", "plain_text_not_tool_call"),
            ("tool_call", "Let me search for that memory now.", "plain_text_not_tool_call"),
            ("json_action", "{invalid json", "malformed_json"),
            ("json_action", "{'key': 'single quotes'}", "malformed_json"),
            ("json_action", "{missing_value: }", "malformed_json"),
            ("dialogue", "As an AI language model, I cannot", "ai_refusal"),
            ("dialogue", "I'm sorry, but I can't help with that.", "ai_refusal"),
            ("dialogue", "I don't have the ability to", "ai_refusal"),
            ("tool_call", f"<tool_call>{{invalid}}</tool_call>", "malformed_tool_call"),
            ("dialogue", f"[{random.choice(chars).upper()}]: Hello", "wrong_format_prefix"),
            ("json_action", "null", "null_response"),
            ("tool_call", json.dumps({"name": "unknown_tool", "arguments": {}}), "missing_tool_call_wrapper"),
        ]
        return random.choice(invalids)

    examples = []
    for _ in range(count):
        if random.random() < 0.5:
            # Valid example
            fmt_choice = random.choice(["dialogue", "json", "tool"])
            if fmt_choice == "dialogue":
                got, reason = _make_valid_dialogue()
                expected = "dialogue"
            elif fmt_choice == "json":
                got, reason = _make_valid_json()
                expected = "json_action"
            else:
                got, reason = _make_valid_tool_call()
                expected = "tool_call"
            valid = True
        else:
            expected, got, reason = _make_invalid()
            valid = False

        input_text = f"Expected: {expected}. Got: {got}"
        suggested = "none" if valid else "retry_with_constraint"
        output = json.dumps({
            "valid": valid,
            "reason": reason,
            "suggested_action": suggested,
        })
        examples.append({
            "instruction": "Validate whether the LLM response matches the expected format.",
            "input": input_text,
            "output": output,
        })
    return examples


# ── Writer ───────────────────────────────────────────────────────────

GENERATORS = {
    "tag_extraction":     (generate_tag_extraction, 800),
    "tool_routing":       (generate_tool_routing, 600),
    "priority_classify":  (generate_priority_classify, 400),
    "decision_classify":  (generate_decision_classify, 400),
    "response_validate":  (generate_response_validate, 400),
}


def write_jsonl(data: List[Dict], path: Path) -> int:
    """Write a list of dicts as JSONL. Returns number of rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(data)


def _dedup(data: List[Dict]) -> List[Dict]:
    """Remove duplicate examples by (input, output) pair."""
    seen: set = set()
    unique: List[Dict] = []
    for item in data:
        key = (item.get("input", ""), item.get("output", ""))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Gemma 270M training datasets")
    parser.add_argument("--out", default="training/datasets", help="Output directory")
    parser.add_argument("--only", help="Generate only this dataset (comma-separated)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--scale", type=float, default=1.0, help="Multiply dataset sizes (e.g. 2.0 for 2x)")
    parser.add_argument("--no-dedup", action="store_true", help="Skip deduplication")
    args = parser.parse_args()

    random.seed(args.seed)
    out_dir = Path(args.out)

    targets = GENERATORS
    if args.only:
        names = [n.strip() for n in args.only.split(",")]
        targets = {k: v for k, v in GENERATORS.items() if k in names}

    total = 0
    for name, (gen_fn, default_count) in targets.items():
        # Over-generate then dedup to hit target count
        scaled_count = int(default_count * args.scale)
        raw_count = scaled_count * 3 if not args.no_dedup else scaled_count
        data = gen_fn(raw_count)
        if not args.no_dedup:
            before = len(data)
            data = _dedup(data)
            data = data[:scaled_count]  # Trim to target
            print(f"  {name}: generated {before}, deduped to {len(data)}")
        # 90/10 train/val split
        random.shuffle(data)
        split = int(len(data) * 0.9)
        train, val = data[:split], data[split:]

        n_train = write_jsonl(train, out_dir / f"{name}_train.jsonl")
        n_val = write_jsonl(val, out_dir / f"{name}_val.jsonl")
        total += n_train + n_val
        print(f"  {name}: {n_train} train + {n_val} val = {n_train + n_val}")

    print(f"\nTotal: {total} examples written to {out_dir}/")


if __name__ == "__main__":
    main()
