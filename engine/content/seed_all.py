"""engine/content/seed_all.py — Seed ContentEngine pools for all scenes.

Run standalone::

    python -m engine.content.seed_all

Or import and call::

    from engine.content.seed_all import seed_content_engine, seed_nexus_qa
    seed_content_engine()
    seed_nexus_qa()
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SCENE_CONTENT_SEEDS: list[dict[str, Any]] = [
    {
        "scene": "penthouse",
        "pool": "dialogue",
        "items": [
            "You look distracted tonight. Something on your mind?",
            "The city never really sleeps, does it.",
            "I've been thinking about what you said earlier.",
            "Pour me another and tell me everything.",
            "Everyone here has secrets. Yours are just more interesting.",
        ],
    },
    {
        "scene": "casino",
        "pool": "dealer_quips",
        "items": [
            "The house always wins. But tonight, I'm rooting for you.",
            "Luck? In this place? You'd need more than luck.",
            "Another hand? I like your style.",
            "Big bet. I respect the confidence.",
            "Zero. The most honest number on the table.",
        ],
    },
    {
        "scene": "lounge",
        "pool": "ambient_dialogue",
        "items": [
            "The saxophonist plays the same song every Friday.",
            "That couple in the corner? First date. Look at them.",
            "The bartender remembers everyone's name. Everyone's drink too.",
            "Late tonight. The city's in a mood.",
            "Music like this should be illegal before midnight.",
        ],
    },
    {
        "scene": "tavern",
        "pool": "rumors",
        "items": [
            "They say the old blacksmith found something in the ruins.",
            "Three merchant caravans disappeared last week alone.",
            "The mayor's been meeting with strangers after dark.",
            "The forest road is cursed now, or so the farmers say.",
            "Word is there's work for people who don't ask questions.",
        ],
    },
    {
        "scene": "gallery",
        "pool": "artwork_descriptions",
        "items": [
            "The brushwork suggests rage — controlled, deliberate rage.",
            "Unsigned. The most valuable signature is absence.",
            "They say the model disappeared the week this was finished.",
            "Acquired from an estate sale. Previous owner, unknown.",
            "The technique predates the style. Anomaly or forgery?",
        ],
    },
    {
        "scene": "heist",
        "pool": "mission_briefings",
        "items": [
            "The vault opens at 23:00. We have a twelve-minute window.",
            "Security rotates every four hours. There's a gap at 02:15.",
            "The mark thinks it's a charity gala. Perfect cover.",
            "Three exits, two guards, one very angry client waiting for delivery.",
            "They've upgraded since last time. Adapt or abort.",
        ],
    },
    {
        "scene": "arena",
        "pool": "announcer_lines",
        "items": [
            "LADIES AND GENTLEMEN — LET THE BLOOD SPORT BEGIN!",
            "The crowd is hungry tonight. Give them what they came for.",
            "Undefeated — until NOW.",
            "An upset? Or destiny? You decide.",
            "The Colosseum has seen empires rise and fall. Tonight, so will you.",
        ],
    },
    {
        "scene": "neoncity",
        "pool": "street_dialogue",
        "items": [
            "Corpo drones up in sector nine again. Stay low.",
            "Black market's moved. Ask Kira where the new spot is.",
            "The Net's been glitchy all week. Ghost code, maybe.",
            "OmniCorp raised prices again. Revolution's getting louder.",
            "You look like someone who needs a job and doesn't ask why.",
        ],
    },
]


def seed_content_engine() -> None:
    """Seed ContentEngine pools for all scenes."""
    try:
        from engine.content.content_engine import get_content_engine
        engine = get_content_engine()
        seeded = 0
        for seed in SCENE_CONTENT_SEEDS:
            scene = seed["scene"]
            pool = seed["pool"]
            for item in seed["items"]:
                try:
                    engine.add_to_pool(scene=scene, pool=pool, content=item)
                    seeded += 1
                except Exception as exc:
                    logger.debug("seed %s/%s skipped: %s", scene, pool, exc)
        logger.info(
            "ContentEngine: seeded %d items across %d scenes",
            seeded,
            len(SCENE_CONTENT_SEEDS),
        )
        print(f"✅ Seeded {seeded} content items across {len(SCENE_CONTENT_SEEDS)} scenes")
    except Exception as exc:
        logger.warning("ContentEngine seeding failed: %s", exc)
        print(f"⚠️  ContentEngine not available: {exc}")


def seed_nexus_qa() -> None:
    """Seed Nexus with basic system Q&A pairs."""
    qa_pairs = [
        (
            "What scenes are in CosySim?",
            "CosySim has 14 active scenes: THE PENTHOUSE (penthouse), SIGNAL (phone), "
            "THE VELVET PIT (lounge), THE RUSTY ANCHOR (tavern), CLUB NOIR (casino), "
            "THE OBSCURA (gallery), THE COLOSSEUM (arena), THE SHATTERED THRONE (realm), "
            "NEON CITY, THE LAB (coders), THE SCORE (heist), THE ARCADE (games), "
            "THE TERMINAL (hub), THE BRIEFING ROOM (intel_hub).",
        ),
        (
            "What is the black glass design?",
            "CosySim v0.68 uses a unified 'black glass' design system: "
            "rgba(8,8,20,0.97) backgrounds, backdrop-filter blur, "
            "rgba(255,255,255,0.08) borders, accent colors per scene, "
            "JetBrains Mono font, 3D particle systems via Three.js.",
        ),
        (
            "How does the EventBus work?",
            "EventBus (engine/events/event_bus.py) is a thread-safe pub/sub. "
            "Use get_event_bus().subscribe('event.name', handler) and "
            "publish('event.name', payload). Persists to Nexus history. "
            "Standard events: world.tick, world.time_change, casino.major_win, arena.match_end.",
        ),
        (
            "How does WorldSim work?",
            "WorldSim (engine/world/world_sim.py) is a background daemon that ticks "
            "every 300s (5 min = 1 sim hour). Emits world.tick and world.time_change "
            "events via EventBus. Access via get_world_sim().start(). "
            "Scenes subscribe to receive clock/weather updates.",
        ),
        (
            "What is the @skill decorator?",
            "Use @skill(pack='scene_name', description='LLM-facing desc', category='GAME') "
            "to register agent tools. Skills auto-register in SKILL_REGISTRY at import time. "
            "Access via get_skill_info('name') or list_all_skills(). "
            "Cost/cooldown/prerequisites supported.",
        ),
    ]
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        for question, answer in qa_pairs:
            try:
                client.add_qa(question, answer, category="system")
            except Exception as exc:
                logger.debug("Nexus QA seed skipped: %s", exc)
        print(f"✅ Seeded {len(qa_pairs)} Nexus Q&A pairs")
    except Exception as exc:
        print(f"⚠️  Nexus not available: {exc}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    seed_content_engine()
    seed_nexus_qa()
    print("Done.")
