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
    ]

    chars = ["lola", "aria", "viktor", "frankie", "mira"]
    topics = ["coffee", "music", "movies", "cats", "cooking", "travel", "games"]
    texts = ["hello!", "I miss you", "thinking of you", "want to hang out?"]

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
    patterns = [
        ("bedroom_scene: character responding to player speech", "realtime", "gpu", "interactive_dialogue"),
        ("phone_scene: autonomous text from NPC", "background", "cpu", "auto_text"),
        ("phone_scene: player sent message, waiting for reply", "realtime", "gpu", "interactive_dialogue"),
        ("bedroom_scene: narrator describing scene", "interactive", "gpu", "narration"),
        ("system: checking if NPC should text player", "background", "cpu", "decision_check"),
        ("system: classifying tags from stream", "realtime", "router", "tag_extraction"),
        ("system: validating response format", "batch", "router", "validation"),
        ("lounge_scene: character performing action", "interactive", "gpu", "scene_action"),
        ("realm_scene: combat narration", "realtime", "gpu", "game_critical"),
        ("phone_scene: generating emoji reaction", "background", "cpu", "trivial_generation"),
        ("system: embedding memory for RAG", "batch", "cpu", "embedding"),
        ("bedroom_scene: generating image prompt", "interactive", "gpu", "creative"),
        ("system: route tool call", "realtime", "router", "tool_routing"),
        ("lounge_scene: NPC idle chatter", "background", "cpu", "ambient"),
        ("bedroom_scene: player waiting for response", "realtime", "gpu", "user_facing"),
    ]

    examples = []
    for _ in range(count):
        pat, priority, tier, reason = random.choice(patterns)
        # Add some variance
        noise = random.choice(["", " (high load)", " (idle)", " (model warm)"])
        output = json.dumps({"priority": priority, "tier": tier, "reason": reason})
        examples.append({
            "instruction": "Classify the following request's priority level and target tier.",
            "input": pat + noise,
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
    valid_examples = [
        ("dialogue", "*smiles warmly* Hey there! How's it going?", True, "valid_dialogue_with_action"),
        ("dialogue", "I was just thinking about you!", True, "valid_dialogue"),
        ("dialogue", "Oh, that's interesting. Tell me more.", True, "valid_dialogue"),
        ("json_action", '{"action":"speak","text":"hello"}', True, "valid_json"),
        ("json_action", '{"mood":"happy","energy":80}', True, "valid_json"),
        ("tool_call", '<tool_call>{"name":"roll_dice","arguments":{"sides":6}}</tool_call>', True, "valid_tool_call"),
    ]
    invalid_examples = [
        ("json_action", "Sure! I'd love to help you with that.", False, "plain_text_not_json"),
        ("json_action", "Here's what I think we should do:", False, "plain_text_not_json"),
        ("dialogue", '{"response": "hello"}', False, "json_not_dialogue"),
        ("dialogue", "", False, "empty_response"),
        ("tool_call", "I'll search for that memory now.", False, "plain_text_not_tool_call"),
        ("json_action", "{invalid json", False, "malformed_json"),
        ("dialogue", "As an AI language model, I cannot", False, "ai_refusal"),
    ]

    examples = []
    for _ in range(count):
        if random.random() < 0.5:
            expected, got, valid, reason = random.choice(valid_examples)
        else:
            expected, got, valid, reason = random.choice(invalid_examples)

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
    "tool_routing":       (generate_tool_routing, 400),
    "priority_classify":  (generate_priority_classify, 300),
    "decision_classify":  (generate_decision_classify, 300),
    "response_validate":  (generate_response_validate, 300),
}


def write_jsonl(data: List[Dict], path: Path) -> int:
    """Write a list of dicts as JSONL. Returns number of rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Gemma 270M training datasets")
    parser.add_argument("--out", default="training/datasets", help="Output directory")
    parser.add_argument("--only", help="Generate only this dataset (comma-separated)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)
    out_dir = Path(args.out)

    targets = GENERATORS
    if args.only:
        names = [n.strip() for n in args.only.split(",")]
        targets = {k: v for k, v in GENERATORS.items() if k in names}

    total = 0
    for name, (gen_fn, default_count) in targets.items():
        data = gen_fn(default_count)
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
