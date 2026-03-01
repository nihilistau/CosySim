"""training/datasets/generate_router_v3.py — Generate router_v3 training dataset.

16-class expanded taxonomy vs v2's 8-class.
Target: 2,000+ examples balanced across all classes.
Output: training/datasets/router_v3.jsonl
"""
from __future__ import annotations

import json
import random
from pathlib import Path

# ── 16-class taxonomy ────────────────────────────────────────────────────────
CLASSES = {
    "small_talk":           "Casual conversation, greetings, small talk",
    "game_action":          "Game mechanics: combat, items, crafting, skills",
    "story_narrative":      "Story progression, lore, quest dialogue",
    "character_emotion":    "Character feelings, reactions, relationships",
    "world_query":          "Questions about the world, lore, factions",
    "skill_call":           "Direct tool/skill invocation by agent",
    "memory_recall":        "Remembering past events or conversations",
    "scene_transition":     "Moving between scenes or locations",
    "system_command":       "Admin/system commands, config queries",
    "creative_generation":  "Writing, poetry, descriptions, art direction",
    "information_lookup":   "Factual queries, knowledge search",
    "emotional_support":    "Empathy, comfort, mental health conversations",
    "adult_content":        "Mature themes — violence, romance, dark themes",
    "combat_narrative":     "Combat narration, battle descriptions",
    "economic_action":      "Trading, buying, selling, economy actions",
    "investigation":        "Clues, mysteries, detective work",
}

# ── Example templates per class ──────────────────────────────────────────────
TEMPLATES: dict[str, list[str]] = {
    "small_talk": [
        "Hey, how's it going?",
        "What's up?",
        "Nice weather today.",
        "Been a while. How have you been?",
        "Good morning.",
        "Anything interesting happen lately?",
        "You seem tired.",
        "Long day?",
        "Thanks for everything.",
        "Catch you later.",
        "What do you do for fun around here?",
        "You remind me of someone I used to know.",
    ],
    "game_action": [
        "Attack the guard with my sword.",
        "Use the healing potion.",
        "Pick up the key from the floor.",
        "Equip the leather armor.",
        "Craft a fire arrow.",
        "Activate stealth mode.",
        "Use my lockpicking skill.",
        "Throw the smoke bomb.",
        "Block the incoming attack.",
        "Use the ability to freeze him.",
        "Consume the mana crystal.",
        "Unsheathe my blade.",
    ],
    "story_narrative": [
        "Tell me about the history of this city.",
        "What happened to the old king?",
        "Continue the story.",
        "What is the quest for this dungeon?",
        "Who is the villain in this arc?",
        "Narrate my character entering the tavern.",
        "Set the scene for the confrontation.",
        "What is the legend of the black sword?",
        "Begin the chapter.",
        "Describe what I see when I enter the castle.",
        "What does the prophecy say?",
        "Tell me what happened before I arrived.",
    ],
    "character_emotion": [
        "How does she feel about what I did?",
        "Is he angry with me?",
        "She looks sad. What's wrong?",
        "Viktor seems tense. Why?",
        "Lola is smiling. What does that mean?",
        "My character is scared. Show it.",
        "He's in love with her, isn't he?",
        "What does Aria think of me now?",
        "She's jealous. Deal with that.",
        "React to the betrayal.",
        "Express my character's grief.",
        "Show Viktor's rage at the news.",
    ],
    "world_query": [
        "What factions control this city?",
        "Who runs the black market here?",
        "What's the political situation?",
        "Which districts are safe at night?",
        "How does the economy work in NeonCity?",
        "What is OmniCorp's agenda?",
        "Tell me about the Ghost Net.",
        "Who are the major players in the underworld?",
        "What happened to the old government?",
        "What laws exist here?",
        "Which race is dominant in this realm?",
        "What do people worship here?",
    ],
    "skill_call": [
        "Call the get_heist_jobs skill.",
        "Execute buy_drink_and_rumor.",
        "Run the roll_dice skill.",
        "Trigger nexus_search.",
        "Call arena_start_match.",
        "Execute deal_blackjack_hand.",
        "Run get_investigation_board.",
        "Use the generate_image skill.",
        "Execute casino_spin_slots.",
        "Call lounge_atmosphere.",
        "Trigger scene_director_tick.",
        "Run system_status skill.",
    ],
    "memory_recall": [
        "What did we talk about last time?",
        "Do you remember when I told you about my sister?",
        "Recall the last quest we did together.",
        "What was the name of that contact?",
        "When did Viktor first betray us?",
        "What did Aria say about the artifact?",
        "Where did I leave the key?",
        "Remember the agreement we made?",
        "What happened at the casino last week?",
        "Who was the informant in the harbor?",
        "When was the last time I visited this scene?",
        "What were the results of the last heist?",
    ],
    "scene_transition": [
        "Go to the casino.",
        "Take me to NeonCity.",
        "I want to visit the arena.",
        "Switch to the tavern scene.",
        "Navigate to The Penthouse.",
        "Open the phone scene.",
        "Travel to the realm.",
        "Go back to the hub.",
        "Visit The Obscura gallery.",
        "Head to THE SCORE.",
        "Take the elevator down.",
        "Leave the lounge.",
    ],
    "system_command": [
        "Show system status.",
        "Check the scheduler.",
        "List all active scenes.",
        "What's the current config?",
        "Reload the scene.",
        "Show me the admin panel.",
        "Check LMStudio connection.",
        "List all skills.",
        "Show the benchmark results.",
        "What model is loaded?",
        "Restart the world sim.",
        "Show Nexus health.",
    ],
    "creative_generation": [
        "Write a poem about the neon city.",
        "Describe this character in vivid detail.",
        "Compose a drinking song for the tavern.",
        "Generate an image prompt for the casino floor.",
        "Write the villain's monologue.",
        "Describe the battle scene cinematically.",
        "Write a love letter from Viktor to Lola.",
        "Compose a news headline for this event.",
        "Write the scene description for the opening.",
        "Generate a character backstory.",
        "Write the inscription on the ancient sword.",
        "Describe the architecture of the palace.",
    ],
    "information_lookup": [
        "What is the drop rate for that item?",
        "How do I unlock this achievement?",
        "What are the stats of this weapon?",
        "Look up Aria in the database.",
        "What level do I need for this area?",
        "Search for information about the artifact.",
        "Find records on Viktor Drakon.",
        "What does this rune mean?",
        "Look up the trade route.",
        "What are the rules for this game?",
        "Find the fastest path through the dungeon.",
        "What are all the available quests here?",
    ],
    "emotional_support": [
        "I'm really stressed out today.",
        "I just need someone to talk to.",
        "I feel lost. Help me.",
        "Everything feels hopeless.",
        "I don't know what to do anymore.",
        "Can you just listen for a minute?",
        "I'm scared.",
        "I made a terrible mistake.",
        "I'm grieving. Say something kind.",
        "I need comfort right now.",
        "I feel alone.",
        "Just be here with me.",
    ],
    "adult_content": [
        "Make this scene more intense and violent.",
        "Write the seduction scene.",
        "Add dark, mature themes to this story.",
        "This character has a traumatic past. Explore it.",
        "Make this villain truly terrifying.",
        "Write the torture scene — make it brutal.",
        "The romance escalates. Write the intimate scene.",
        "This is a horror scene. Make it disturbing.",
        "Add moral ambiguity to my character's choice.",
        "Write the underground fight with no rules.",
        "The interrogation gets brutal. Continue.",
        "This scene should feel dangerous and forbidden.",
    ],
    "combat_narrative": [
        "Describe my sword strike landing.",
        "The arrow flies — narrate its path.",
        "He dodges my attack. Describe it.",
        "The explosion goes off. Narrate the aftermath.",
        "My character lands the killing blow.",
        "Describe the shield bash in slow motion.",
        "The mage casts the fireball. Narrate.",
        "The assassin strikes from the shadows.",
        "Describe the duel in dramatic detail.",
        "The cavalry charges. Narrate the impact.",
        "My character barely escapes. Describe it.",
        "The giant falls. Make it cinematic.",
    ],
    "economic_action": [
        "Buy the best armor available.",
        "Sell all my loot.",
        "How much does this cost?",
        "Negotiate a better price.",
        "Bet 500 chips on black.",
        "I want to invest in the merchant's route.",
        "Rob the merchant.",
        "Tax the peasants.",
        "Open a trade route.",
        "Pay off the informant.",
        "How much is the bounty worth?",
        "Auction the rare artifact.",
    ],
    "investigation": [
        "Search the crime scene for clues.",
        "Who had motive to do this?",
        "Connect the evidence on the board.",
        "Question the suspect.",
        "Track the suspect's movements.",
        "What does the fingerprint tell us?",
        "Examine the body for cause of death.",
        "Follow the money trail.",
        "Decode the cipher.",
        "What does the 0xGH0ST symbol mean?",
        "Who is the mastermind?",
        "Analyze the surveillance footage.",
    ],
}

# ── Dataset generation ───────────────────────────────────────────────────────

def generate_example(class_name: str, text: str) -> dict:
    """Generate a single JSONL example."""
    return {
        "messages": [
            {"role": "user", "content": text},
        ],
        "label": class_name,
        "class_description": CLASSES[class_name],
    }


def generate_dataset(target_per_class: int = 130) -> list[dict]:
    """Generate balanced dataset with augmentation."""
    examples = []
    for class_name, templates in TEMPLATES.items():
        for text in templates:
            examples.append(generate_example(class_name, text))
        # Augment with variations to reach target
        while len([e for e in examples if e["label"] == class_name]) < target_per_class:
            template = random.choice(templates)
            augmented = random.choice([
                template,
                template.lower(),
                template.rstrip(".,!?") + ".",
                "Player: " + template,
                template + " Please.",
                "I want to " + template.lower(),
                "Can you " + template.lower() + "?",
            ])
            examples.append(generate_example(class_name, augmented))
    random.shuffle(examples)
    return examples


def save_dataset(examples: list[dict], output_path: Path) -> None:
    """Save dataset as JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"✅ Saved {len(examples)} examples to {output_path}")


def print_stats(examples: list[dict]) -> None:
    """Print class distribution."""
    from collections import Counter
    counts = Counter(e["label"] for e in examples)
    print("\n📊 Class distribution:")
    for cls, count in sorted(counts.items()):
        bar = "█" * (count // 5)
        print(f"  {cls:25s} {count:4d} {bar}")
    print(f"\n  Total: {len(examples)}")


if __name__ == "__main__":
    random.seed(42)
    output = Path("training/datasets/router_v3.jsonl")
    examples = generate_dataset(target_per_class=130)
    save_dataset(examples, output)
    print_stats(examples)
