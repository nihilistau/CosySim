"""
Gallery Skills — MCP skill functions for the Art Gallery scene.

Exposes art creation, critique, exhibition management, room navigation,
patron interaction, and auction mechanics as @skill-decorated functions
callable by LMS agents via tool use.
"""
from __future__ import annotations

import logging
import random
import time

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)

# Module-level gallery state (shared across skill calls)
_gallery_state = {
    "current_room": "main_hall",
    "current_theme": "Dreams Unveiled",
    "artworks": [],
    "critiques": {},
    "patron_mood": 70,  # 0-100
    "prestige": 50,  # 0-100, gallery reputation
    "visitor_count": 0,
    "auction_active": False,
    "auction_item": None,
    "auction_bids": [],
}


def _get_gallery_scene():
    """Look up the running Gallery scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("gallery")


def _gs():
    """Get or return module-level state."""
    return _gallery_state


# ── Exhibition Management ──────────────────────────────────────

@skill(
    pack="gallery",
    tags=["game", "gallery", "art"],
    category=SkillCategory.GAME,
    description="Get the current exhibition status: theme, artworks, room, prestige, visitors.",
)
def gallery_exhibition_status() -> str:
    """Return current exhibition state."""
    gs = _gs()
    art_count = len(gs["artworks"])
    lines = [
        f"🖼️ Exhibition: '{gs['current_theme']}'",
        f"Room: {gs['current_room'].replace('_', ' ').title()}",
        f"Artworks: {art_count}",
        f"Prestige: {gs['prestige']}/100",
        f"Patron mood: {gs['patron_mood']}/100",
        f"Visitors today: {gs['visitor_count']}",
    ]
    if gs["artworks"]:
        lines.append("Recent works:")
        for a in gs["artworks"][-3:]:
            avg = a.get("avg_score", "?")
            lines.append(f"  • '{a['title']}' ({a['style']}) — rating: {avg}")
    return "\n".join(lines)


@skill(
    pack="gallery",
    tags=["game", "gallery", "art"],
    category=SkillCategory.GAME,
    description="Create a new artwork for the exhibition. Specify title, style, and description.",
    cooldown=15,
)
def gallery_create_art(title: str = "Untitled", style: str = "abstract",
                       description: str = "") -> str:
    """Submit a new artwork to the gallery exhibition."""
    gs = _gs()
    if not title or title == "Untitled":
        return "Give your artwork a title!"
    styles = ["abstract", "impressionist", "surreal", "hyperrealist",
              "cubist", "minimalist", "baroque", "digital", "sculpture", "mixed_media"]
    if style not in styles:
        return f"Unknown style. Choose from: {', '.join(styles)}"

    artwork = {
        "title": title,
        "style": style,
        "description": description or f"A {style} piece titled '{title}'.",
        "created_at": time.time(),
        "scores": [],
        "avg_score": 0,
        "critiques": [],
    }
    gs["artworks"].append(artwork)
    gs["prestige"] = min(100, gs["prestige"] + 2)
    gs["visitor_count"] += random.randint(1, 5)
    return (
        f"🎨 Artwork submitted: '{title}' ({style})\n"
        f"{description or artwork['description']}\n"
        f"Prestige +2 → {gs['prestige']}/100"
    )


@skill(
    pack="gallery",
    tags=["game", "gallery", "art", "critique"],
    category=SkillCategory.SOCIAL,
    description="Critique an artwork. Rate technique, emotion, originality (1-10 each).",
    cooldown=8,
)
def gallery_critique(artwork_title: str = "", technique: int = 5,
                     emotion: int = 5, originality: int = 5) -> str:
    """Give a structured art critique with three scores."""
    gs = _gs()
    if not artwork_title:
        if gs["artworks"]:
            titles = ", ".join(a["title"] for a in gs["artworks"][-5:])
            return f"Specify which artwork to critique. Recent: {titles}"
        return "No artworks to critique."

    artwork = next((a for a in gs["artworks"] if a["title"].lower() == artwork_title.lower()), None)
    if not artwork:
        return f"Artwork '{artwork_title}' not found."

    technique = max(1, min(10, technique))
    emotion = max(1, min(10, emotion))
    originality = max(1, min(10, originality))
    avg = round((technique + emotion + originality) / 3, 1)

    artwork["scores"].append(avg)
    artwork["avg_score"] = round(sum(artwork["scores"]) / len(artwork["scores"]), 1)

    verdicts = {
        (1, 3): "A bold failure, but failure nonetheless.",
        (4, 5): "Shows promise. The technique needs refinement.",
        (6, 7): "Competent work with flashes of brilliance.",
        (8, 8): "Impressive. The composition speaks volumes.",
        (9, 10): "A masterpiece. This belongs in the permanent collection.",
    }
    verdict = "Interesting."
    for (lo, hi), v in verdicts.items():
        if lo <= avg <= hi:
            verdict = v
            break

    # Masterpiece bonus
    if avg >= 9.0:
        gs["prestige"] = min(100, gs["prestige"] + 10)
        verdict += " ✨ MASTERPIECE! Prestige +10."

    gs["patron_mood"] = min(100, gs["patron_mood"] + int(avg))
    return (
        f"📝 Critique of '{artwork_title}':\n"
        f"  Technique: {technique}/10 | Emotion: {emotion}/10 | Originality: {originality}/10\n"
        f"  Average: {avg}/10 — {verdict}"
    )


@skill(
    pack="gallery",
    tags=["game", "gallery"],
    category=SkillCategory.GAME,
    description="Move to a different gallery room: main_hall, modern_wing, sculpture_garden, dark_room, private_collection.",
)
def gallery_change_room(room: str = "main_hall") -> str:
    """Navigate to a gallery room."""
    gs = _gs()
    valid = ["main_hall", "modern_wing", "sculpture_garden", "dark_room", "private_collection"]
    if room not in valid:
        return f"Unknown room. Available: {', '.join(valid)}"
    if room == "private_collection" and gs["prestige"] < 75:
        return f"Private collection requires prestige ≥75. Current: {gs['prestige']}/100."
    gs["current_room"] = room
    room_desc = {
        "main_hall": "The grand entrance hall. High ceilings, natural light, featured exhibitions.",
        "modern_wing": "Contemporary art. Neon installations and digital pieces.",
        "sculpture_garden": "Open-air garden with stone and metal sculptures.",
        "dark_room": "Dimly lit. Provocative, experimental works displayed here.",
        "private_collection": "The curator's private gallery. Only the most discerning may enter.",
    }
    return f"🚪 Moved to {room.replace('_', ' ').title()}.\n{room_desc.get(room, '')}"


@skill(
    pack="gallery",
    tags=["game", "gallery", "art", "debate"],
    category=SkillCategory.SOCIAL,
    description="Challenge another critic to an art debate. Topic and stance required.",
    cooldown=20,
)
def gallery_art_debate(topic: str = "modern art", stance: str = "for") -> str:
    """Start an art debate. Prestige boost if you win."""
    gs = _gs()
    # Simulated debate outcome based on prestige + randomness
    skill_roll = random.randint(1, 20) + (gs["prestige"] // 10)
    opponent_roll = random.randint(1, 20) + random.randint(3, 8)

    if skill_roll > opponent_roll:
        gs["prestige"] = min(100, gs["prestige"] + 5)
        gs["patron_mood"] = min(100, gs["patron_mood"] + 10)
        return (
            f"🏆 Debate on '{topic}' ({stance}): YOU WIN!\n"
            f"Your argument was compelling. Prestige +5 → {gs['prestige']}/100."
        )
    elif skill_roll == opponent_roll:
        return f"⚖️ Debate on '{topic}': A draw. Both arguments had merit."
    else:
        gs["prestige"] = max(0, gs["prestige"] - 3)
        return (
            f"😞 Debate on '{topic}': You lost this round.\n"
            f"Your opponent's counterpoints were stronger. Prestige -3 → {gs['prestige']}/100."
        )


@skill(
    pack="gallery",
    tags=["game", "gallery", "theme"],
    category=SkillCategory.GAME,
    description="Change the exhibition theme. Themes: dreams_unveiled, urban_decay, nature_reimagined, forbidden_beauty, digital_frontiers, chaos_and_order.",
    cooldown=30,
)
def gallery_set_theme(theme: str = "dreams_unveiled") -> str:
    """Change the exhibition theme. Clears previous artworks."""
    gs = _gs()
    themes = {
        "dreams_unveiled": "Explorations of the subconscious mind.",
        "urban_decay": "Beauty in architectural collapse and graffiti.",
        "nature_reimagined": "Flora and fauna through surreal lenses.",
        "forbidden_beauty": "Art that challenges conventional aesthetics.",
        "digital_frontiers": "AI-generated art and digital installations.",
        "chaos_and_order": "The tension between structure and entropy.",
    }
    if theme not in themes:
        return f"Unknown theme. Available: {', '.join(themes.keys())}"
    old_count = len(gs["artworks"])
    gs["current_theme"] = theme.replace("_", " ").title()
    gs["artworks"] = []  # New exhibition
    gs["visitor_count"] += random.randint(5, 15)
    return (
        f"🎭 New exhibition: '{gs['current_theme']}'\n"
        f"{themes[theme]}\n"
        f"Previous {old_count} artworks archived. Fresh canvas!"
    )


@skill(
    pack="gallery",
    tags=["game", "gallery", "auction"],
    category=SkillCategory.GAME,
    description="Start an auction for an artwork. Patrons bid.",
    cooldown=30,
)
def gallery_auction(artwork_title: str = "", starting_bid: int = 10) -> str:
    """Auction an artwork. Returns the winning bid."""
    gs = _gs()
    if gs["auction_active"]:
        return "An auction is already in progress."
    artwork = next((a for a in gs["artworks"] if a["title"].lower() == artwork_title.lower()), None)
    if not artwork:
        if gs["artworks"]:
            titles = ", ".join(a["title"] for a in gs["artworks"])
            return f"Artwork not found. Available: {titles}"
        return "No artworks to auction."

    # Simulate bidding war
    num_bidders = random.randint(2, 5)
    current_bid = starting_bid
    for _ in range(num_bidders):
        increment = random.randint(5, 20) * max(1, artwork.get("avg_score", 5) // 2)
        current_bid += increment

    # Prestige affects final price
    prestige_bonus = gs["prestige"] // 20
    final_price = current_bid + (prestige_bonus * random.randint(5, 15))

    # Remove from gallery
    gs["artworks"] = [a for a in gs["artworks"] if a["title"].lower() != artwork_title.lower()]
    gs["prestige"] = min(100, gs["prestige"] + 3)

    return (
        f"🔨 SOLD! '{artwork_title}' auctioned for {final_price}g!\n"
        f"{num_bidders} bidders competed. Prestige +3 → {gs['prestige']}/100."
    )


@skill(
    pack="gallery",
    tags=["game", "gallery", "patron"],
    category=SkillCategory.SOCIAL,
    description="Interact with gallery patrons. Actions: greet, tour, inspire.",
    cooldown=10,
)
def gallery_patron_interact(action: str = "greet") -> str:
    """Interact with gallery visitors to boost mood and prestige."""
    gs = _gs()
    if action == "greet":
        gs["patron_mood"] = min(100, gs["patron_mood"] + 5)
        gs["visitor_count"] += 1
        return f"👋 You greet the patrons warmly. Mood +5 → {gs['patron_mood']}/100."
    elif action == "tour":
        if not gs["artworks"]:
            return "Nothing to tour — the gallery is empty!"
        gs["patron_mood"] = min(100, gs["patron_mood"] + 10)
        gs["prestige"] = min(100, gs["prestige"] + 2)
        return (
            f"🎓 You lead a gallery tour through {len(gs['artworks'])} artworks.\n"
            f"Patron mood +10, Prestige +2."
        )
    elif action == "inspire":
        if gs["patron_mood"] < 60:
            return "Patrons aren't in the mood to be inspired. Raise their mood first."
        gs["prestige"] = min(100, gs["prestige"] + 5)
        return f"✨ Your passionate speech about art inspires the crowd! Prestige +5 → {gs['prestige']}/100."
    return "Actions: greet, tour, inspire."
