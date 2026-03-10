"""Default story arc templates for all 9 CosySim scenes."""
from __future__ import annotations

import copy

from engine.story.story_arc import ArcStep, ArcStatus, StoryArc, get_story_arc_engine

SCENE_ARC_TEMPLATES: dict = {
    "penthouse": [
        StoryArc(
            id="penthouse_seduction",
            name="The Seduction",
            scene="penthouse",
            steps=[
                ArcStep("open", "Open with charm"),
                ArcStep("tension", "Build tension"),
                ArcStep("reveal", "The reveal"),
                ArcStep("resolution", "Resolution"),
            ],
        ),
    ],
    "casino": [
        StoryArc(
            id="casino_heist",
            name="The Big Score",
            scene="casino",
            steps=[
                ArcStep("scout", "Scout the floor"),
                ArcStep("network", "Network with players"),
                ArcStep("play", "High-stakes game"),
                ArcStep("cash_out", "Cash out clean"),
            ],
        ),
    ],
    "arena": [
        StoryArc(
            id="arena_champion",
            name="Rise to Champion",
            scene="arena",
            steps=[
                ArcStep("enter", "Enter the arena"),
                ArcStep("qualify", "Qualify in prelims"),
                ArcStep("semifinal", "Survive the semifinal"),
                ArcStep("final", "Win the final"),
            ],
        ),
    ],
    "tavern": [
        StoryArc(
            id="tavern_contract",
            name="The Contract",
            scene="tavern",
            steps=[
                ArcStep("rumors", "Gather rumours"),
                ArcStep("meet", "Meet the contact"),
                ArcStep("negotiate", "Negotiate terms"),
                ArcStep("accept", "Accept the job"),
            ],
        ),
    ],
    "lounge": [
        StoryArc(
            id="lounge_deal",
            name="The Deal",
            scene="lounge",
            steps=[
                ArcStep("arrive", "Make your entrance"),
                ArcStep("mingle", "Work the room"),
                ArcStep("approach", "Approach the mark"),
                ArcStep("close", "Close the deal"),
            ],
        ),
    ],
    "gallery": [
        StoryArc(
            id="gallery_theft",
            name="The Theft",
            scene="gallery",
            steps=[
                ArcStep("case", "Case the gallery"),
                ArcStep("distract", "Create a distraction"),
                ArcStep("acquire", "Acquire the piece"),
                ArcStep("escape", "Make the exit"),
            ],
        ),
    ],
    "realm": [
        StoryArc(
            id="realm_throne",
            name="Claim the Throne",
            scene="realm",
            steps=[
                ArcStep("summon", "Answer the summons"),
                ArcStep("trial", "Pass the trial"),
                ArcStep("alliance", "Forge alliances"),
                ArcStep("claim", "Claim the throne"),
            ],
        ),
    ],
    "neoncity": [
        StoryArc(
            id="neoncity_hack",
            name="The Deep Hack",
            scene="neoncity",
            steps=[
                ArcStep("infiltrate", "Infiltrate the network"),
                ArcStep("bypass", "Bypass security"),
                ArcStep("extract", "Extract the data"),
                ArcStep("ghost", "Go ghost"),
            ],
        ),
    ],
    "phone": [
        StoryArc(
            id="phone_intel",
            name="The Intel Run",
            scene="phone",
            steps=[
                ArcStep("contact", "Establish contact"),
                ArcStep("verify", "Verify the source"),
                ArcStep("transfer", "Transfer intel"),
                ArcStep("cutoff", "Clean cutoff"),
            ],
        ),
    ],
}


def seed_default_arcs() -> None:
    """Register all default arc templates into the StoryArcEngine."""
    engine = get_story_arc_engine()
    for scene_arcs in SCENE_ARC_TEMPLATES.values():
        for arc in scene_arcs:
            arc_copy = copy.deepcopy(arc)
            engine.create_arc(arc_copy)
