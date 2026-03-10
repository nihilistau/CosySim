"""Neon City rich event template library for CosySim v0.75 "NEON CITY".

Provides 50+ event templates with economy_impact, narrative text, and
affected_scenes metadata.  Used by WorldSim to fire richer, more varied
events that integrate with PlayerState and EventCascade.

Each template is a dict with::

    title           — short HUD display title
    desc            — LLM-facing narrative description
    scene           — primary affected scene key
    event_type      — semantic category
    intensity       — narrative weight 0–3
    economy_impact  — credit delta hint (positive=gain, negative=loss)
    rep_impact      — reputation delta hint
    heat_impact     — heat delta hint
    affected_scenes — list of scene keys that should receive this event
    narrative       — longer flavour text for scene dialog injection
    faction         — optional faction involved (empty str = none)

Usage::

    from engine.world.neon_city_events import (
        NPC_ACTIONS_RICH,
        WORLD_EVENTS_RICH,
        FACTION_EVENTS_RICH,
        ECONOMY_EVENTS,
        GHOST_MESSAGES_RICH,
    )
"""
from __future__ import annotations

from typing import Dict, List, Any

# ---------------------------------------------------------------------------
# NPC Action templates (30+)
# ---------------------------------------------------------------------------

NPC_ACTIONS_RICH: List[Dict[str, Any]] = [
    {
        "scene": "neoncity", "actor": "street_vendor", "event_type": "npc_action",
        "title": "Vendor dispute", "intensity": 1.0, "economy_impact": 0,
        "affected_scenes": ["neoncity", "grid"],
        "desc": "A street vendor gets into a heated argument with a corp drone over territory.",
        "narrative": "The argument spills into the street, drawing a crowd of onlookers.",
    },
    {
        "scene": "lounge", "actor": "bouncer", "event_type": "npc_action",
        "title": "Ejection incident", "intensity": 1.2, "economy_impact": 0,
        "affected_scenes": ["lounge"],
        "desc": "The Velvet Pit bouncer throws out a rowdy patron who owed money.",
        "narrative": "Three large bouncers escort the man to the door. He won't be back.",
    },
    {
        "scene": "tavern", "actor": "bard", "event_type": "npc_action",
        "title": "New ballad", "intensity": 0.8, "economy_impact": 50,
        "affected_scenes": ["tavern", "lounge"],
        "desc": "The tavern bard debuts a new song about a recent heist. Coins rain.",
        "narrative": "The song names names. Someone in the corner goes very still.",
    },
    {
        "scene": "casino", "actor": "dealer", "event_type": "npc_action",
        "title": "Loaded deck caught", "intensity": 1.5, "economy_impact": -100,
        "affected_scenes": ["casino"],
        "desc": "Security catches someone using a marked deck at Club Noir. The table freezes.",
        "narrative": "The cheater is escorted into the back. The chips are frozen pending review.",
    },
    {
        "scene": "arena", "actor": "challenger", "event_type": "npc_action",
        "title": "New challenger", "intensity": 2.0, "economy_impact": 0,
        "affected_scenes": ["arena"],
        "desc": "A mysterious fighter challenges the current champion via handwritten note.",
        "narrative": "No name, no record. The promoter is intrigued. Odds are already shifting.",
    },
    {
        "scene": "neoncity", "actor": "gang_lieutenant", "event_type": "npc_action",
        "title": "Gang shakedown", "intensity": 1.8, "economy_impact": -80, "heat_impact": 3,
        "affected_scenes": ["neoncity", "grid"],
        "desc": "A gang lieutenant shakes down a noodle stall. The market trembles.",
        "narrative": "You can feel the protection fees flowing upward. Someone always pays.",
        "faction": "BlackMarket",
    },
    {
        "scene": "lounge", "actor": "information_broker", "event_type": "npc_action",
        "title": "Deal brokered", "intensity": 1.0, "economy_impact": 0,
        "affected_scenes": ["lounge", "grid"],
        "desc": "A well-known information broker finalises a transaction in a private booth.",
        "narrative": "Both parties leave quickly. The data chip changes hands three times in one night.",
    },
    {
        "scene": "heist", "actor": "fence", "event_type": "npc_action",
        "title": "Hot merchandise moved", "intensity": 1.3, "economy_impact": 150,
        "affected_scenes": ["heist", "grid"],
        "desc": "A fence quietly offloads a crate of stolen corp hardware.",
        "narrative": "The hardware hits the black market within the hour. Prices drop.",
    },
    {
        "scene": "phone", "actor": "unknown_caller", "event_type": "npc_action",
        "title": "Anonymous tip", "intensity": 2.5, "economy_impact": 0,
        "affected_scenes": ["phone"],
        "desc": "An anonymous caller warns about an upcoming sweep of the district.",
        "narrative": "Static on the line. Then: 'They know about the drop point. Move it.' Click.",
    },
    {
        "scene": "casino", "actor": "high_roller", "event_type": "npc_action",
        "title": "High stakes table", "intensity": 2.0, "economy_impact": 500,
        "affected_scenes": ["casino"],
        "desc": "A masked high-roller drops 50k credits in a single hand at the VIP table.",
        "narrative": "The room goes quiet. The dealer's hands are steady. The masks stays on.",
    },
    {
        "scene": "arena", "actor": "medic", "event_type": "npc_action",
        "title": "Fighter injured", "intensity": 1.5, "economy_impact": -200,
        "affected_scenes": ["arena"],
        "desc": "A top-ranked fighter is wheeled out on a stretcher. Cause unknown.",
        "narrative": "Bookmakers scramble. Half the bracket just collapsed. Someone knew.",
    },
    {
        "scene": "neoncity", "actor": "corpo_patrol", "event_type": "npc_action",
        "title": "Checkpoint established", "intensity": 2.0, "heat_impact": 5,
        "affected_scenes": ["neoncity", "grid"],
        "desc": "OmniCorp enforcers set up an ID checkpoint on the main boulevard.",
        "narrative": "Papers, citizen. The line stretches three blocks. People are nervous.",
        "faction": "OmniCorp",
    },
    {
        "scene": "tavern", "actor": "spy", "event_type": "npc_action",
        "title": "Overheard conversation", "intensity": 1.2, "economy_impact": 0,
        "affected_scenes": ["tavern"],
        "desc": "Two figures speak quietly about a missing shipment in the corner.",
        "narrative": "You only catch fragments. 'Warehouse 7.' 'Before sunrise.' 'Don't trust Mira.'",
    },
    {
        "scene": "heist", "actor": "lookout", "event_type": "npc_action",
        "title": "Lookout spotted", "intensity": 1.5, "heat_impact": 4,
        "affected_scenes": ["heist"],
        "desc": "A nervous lookout is pacing the alley outside the target building.",
        "narrative": "He checks his wrist-link every thirty seconds. Something is about to happen.",
    },
    {
        "scene": "neoncity", "actor": "holo_preacher", "event_type": "npc_action",
        "title": "Holo-sermon", "intensity": 0.7, "economy_impact": 0,
        "affected_scenes": ["neoncity"],
        "desc": "A holo-preacher decries the corps from a makeshift podium, drawing a crowd.",
        "narrative": "His voice is pre-recorded. The delivery drone was stolen from NeoTech.",
    },
    {
        "scene": "casino", "actor": "pit_boss", "event_type": "npc_action",
        "title": "Credit freeze", "intensity": 1.5, "economy_impact": 0,
        "affected_scenes": ["casino"],
        "desc": "The pit boss quietly freezes a player's account pending identity verification.",
        "narrative": "The player smiles. The pit boss doesn't. Both know the account is fake.",
    },
    {
        "scene": "neoncity", "actor": "graffiti_artist", "event_type": "npc_action",
        "title": "Graffiti warning", "intensity": 1.0, "economy_impact": 0,
        "affected_scenes": ["neoncity"],
        "desc": "Fresh graffiti appears overnight: a skull with corp logos for eyes.",
        "narrative": "Everyone sees it. Maintenance drones are dispatched. They'll repaint by dawn.",
    },
    {
        "scene": "lounge", "actor": "data_courier", "event_type": "npc_action",
        "title": "Data drop", "intensity": 1.0, "economy_impact": 75,
        "affected_scenes": ["lounge", "grid"],
        "desc": "A data courier passes a chip to a waiting contact between drinks.",
        "narrative": "Two strangers. One minute. Twenty thousand credits worth of secrets.",
    },
    {
        "scene": "grid", "actor": "market_vendor", "event_type": "npc_action",
        "title": "Price war", "intensity": 1.2, "economy_impact": -50,
        "affected_scenes": ["grid"],
        "desc": "Two rival vendors slash prices on stim-packs. Customers flock to the market.",
        "narrative": "The air smells like desperation and discount noodles. Frankie is furious.",
    },
    {
        "scene": "grid", "actor": "ghost_hacker", "event_type": "npc_action",
        "title": "System blip", "intensity": 1.8, "economy_impact": 0,
        "affected_scenes": ["grid", "phone"],
        "desc": "The Grid's market terminals flicker. Prices ghost for 30 seconds.",
        "narrative": "Someone exploited the update window. Three thousand credits vanished into noise.",
    },
    {
        "scene": "coders", "actor": "senior_dev", "event_type": "npc_action",
        "title": "Commit pushed", "intensity": 0.5, "economy_impact": 200,
        "affected_scenes": ["coders"],
        "desc": "A senior dev pushes a critical hotfix. Production stabilises.",
        "narrative": "The all-hands call is cancelled. Someone orders pizza. Normalcy restored.",
    },
    {
        "scene": "penthouse", "actor": "lola", "event_type": "npc_action",
        "title": "Late-night confession", "intensity": 1.5, "economy_impact": 0,
        "affected_scenes": ["penthouse"],
        "desc": "Lola shares something she's been keeping quiet for days.",
        "narrative": "The city hum fills the silence after she speaks. The penthouse feels smaller.",
    },
    {
        "scene": "gallery", "actor": "collector", "event_type": "npc_action",
        "title": "Acquisition made", "intensity": 1.0, "economy_impact": 300,
        "affected_scenes": ["gallery"],
        "desc": "A private collector acquires a rare digital artwork for an undisclosed sum.",
        "narrative": "The provenance is dubious. The certificate is perfect. Nobody asks questions.",
    },
    {
        "scene": "realm", "actor": "oracle", "event_type": "npc_action",
        "title": "Prophecy spoken", "intensity": 2.5, "economy_impact": 0,
        "affected_scenes": ["realm"],
        "desc": "The Oracle of the Shattered Throne delivers a cryptic vision.",
        "narrative": "Three will fall. One will rise. The throne cracks at the seam.",
    },
    {
        "scene": "neoncity", "actor": "street_doc", "event_type": "npc_action",
        "title": "Illegal surgery", "intensity": 1.8, "heat_impact": 2,
        "affected_scenes": ["neoncity", "grid"],
        "desc": "A street doc performs an off-the-books cyber implant in a back alley.",
        "narrative": "The patient wakes up three hours later. The augment works. Mostly.",
    },
]

# ---------------------------------------------------------------------------
# World event templates (20+)
# ---------------------------------------------------------------------------

WORLD_EVENTS_RICH: List[Dict[str, Any]] = [
    {
        "title": "Corporate Blackout",
        "desc": "NeoTech cuts power to the lower districts. Lights out.",
        "scene": "neoncity", "event_type": "blackout", "intensity": 3.0,
        "economy_impact": -300, "heat_impact": 0, "rep_impact": 0,
        "affected_scenes": ["neoncity", "grid", "lounge", "tavern"],
        "narrative": "Emergency lighting flickers on. The corps say it's maintenance. Nobody believes them.",
        "faction": "NeoTech",
    },
    {
        "title": "Underground Auction",
        "desc": "A mysterious auction of stolen goods draws powerful players to the Velvet Pit.",
        "scene": "lounge", "event_type": "underground_auction", "intensity": 2.5,
        "economy_impact": 500, "heat_impact": 5, "rep_impact": 5,
        "affected_scenes": ["lounge", "grid", "heist"],
        "narrative": "Everything is for sale. Bidding opens at 50k. The minimum bid is a secret.",
        "faction": "BlackMarket",
    },
    {
        "title": "Faction War Erupts",
        "desc": "OmniCorp and BlackMarket forces clash openly in the streets.",
        "scene": "neoncity", "event_type": "gang_war", "intensity": 3.0,
        "economy_impact": -200, "heat_impact": 12, "rep_impact": 0,
        "affected_scenes": ["neoncity", "grid", "heist", "phone"],
        "narrative": "Gunfire echoes between towers. Civilians run. Fixer networks go dark.",
        "faction": "OmniCorp",
    },
    {
        "title": "Grand Tournament Announced",
        "desc": "The Colosseum announces a 16-fighter elimination tournament.",
        "scene": "arena", "event_type": "fight_night", "intensity": 2.0,
        "economy_impact": 1000, "heat_impact": 0, "rep_impact": 10,
        "affected_scenes": ["arena"],
        "narrative": "Prize pool: one million credits. Entry fee: survive the qualifiers.",
    },
    {
        "title": "The Ghost Goes Dark",
        "desc": "0xGH0ST's signals go completely silent. Something is very wrong.",
        "scene": "phone", "event_type": "hacker_event", "intensity": 3.0,
        "economy_impact": 0, "heat_impact": 8, "rep_impact": 0,
        "affected_scenes": ["phone", "grid", "coders"],
        "narrative": "Every channel silent. Last message: 'They found the node. Don't look for me.'",
        "faction": "Ghost_Net",
    },
    {
        "title": "Festival of Neon",
        "desc": "Street celebrations light up NeonCity. Everyone is out tonight.",
        "scene": "neoncity", "event_type": "festival", "intensity": 2.0,
        "economy_impact": 300, "heat_impact": -5, "rep_impact": 8,
        "affected_scenes": ["neoncity", "lounge", "tavern", "casino", "grid"],
        "narrative": "The tension breaks. For one night, the corps let the city breathe.",
    },
    {
        "title": "Corp Raid",
        "desc": "Security forces sweep through the black market district.",
        "scene": "neoncity", "event_type": "corp_raid", "intensity": 2.5,
        "economy_impact": -400, "heat_impact": 10, "rep_impact": -5,
        "affected_scenes": ["neoncity", "grid", "heist"],
        "narrative": "Boots on the ground. Vendors scatter. The drop point is compromised.",
        "faction": "SynthSec",
    },
    {
        "title": "Heist Gone Wrong",
        "desc": "News of a botched heist spreads. Heat rises city-wide.",
        "scene": "heist", "event_type": "gang_war", "intensity": 2.5,
        "economy_impact": -150, "heat_impact": 8, "rep_impact": 0,
        "affected_scenes": ["heist", "neoncity", "phone"],
        "narrative": "Three dead. Two missing. The score was worth it, they said.",
    },
    {
        "title": "Data Breach: OmniCorp",
        "desc": "OmniCorp internal files leak across the net. Markets destabilised.",
        "scene": "coders", "event_type": "hacker_event", "intensity": 2.5,
        "economy_impact": -600, "heat_impact": 6, "rep_impact": 10,
        "affected_scenes": ["coders", "grid", "phone", "neoncity"],
        "narrative": "The files are damning. Exec names, black budgets, off-books projects.",
        "faction": "Ghost_Net",
    },
    {
        "title": "Market Surge",
        "desc": "Demand spikes across the black market. Traders scramble.",
        "scene": "grid", "event_type": "market_surge", "intensity": 1.5,
        "economy_impact": 400, "heat_impact": 0, "rep_impact": 3,
        "affected_scenes": ["grid", "heist", "lounge"],
        "narrative": "Someone cornered the stim-pack supply. Prices doubled overnight.",
    },
    {
        "title": "Syndicate Expansion",
        "desc": "DeepState extends its reach into a new district.",
        "scene": "neoncity", "event_type": "faction_expansion", "intensity": 2.0,
        "economy_impact": 0, "heat_impact": 4, "rep_impact": 0,
        "affected_scenes": ["neoncity", "grid", "lounge"],
        "narrative": "New faces at the checkpoints. Old faces disappearing.",
        "faction": "DeepState",
    },
    {
        "title": "NeoTech Product Launch",
        "desc": "NeoTech unveils a new neural augment line. The crowd is massive.",
        "scene": "neoncity", "event_type": "corp_event", "intensity": 1.5,
        "economy_impact": 200, "heat_impact": 0, "rep_impact": 5,
        "affected_scenes": ["neoncity", "gallery", "grid"],
        "narrative": "The hologram is fifty storeys tall. The price tag is higher.",
        "faction": "NeoTech",
    },
    {
        "title": "Blackout Protocol",
        "desc": "SynthSec initiates a net-wide blackout. Communications severed.",
        "scene": "neoncity", "event_type": "blackout", "intensity": 3.0,
        "economy_impact": -500, "heat_impact": 15, "rep_impact": 0,
        "affected_scenes": ["neoncity", "phone", "coders", "grid"],
        "narrative": "No calls. No messages. No way out. The city holds its breath.",
        "faction": "SynthSec",
    },
    {
        "title": "Arena Championship",
        "desc": "The annual championship draws the best fighters from every district.",
        "scene": "arena", "event_type": "fight_night", "intensity": 2.5,
        "economy_impact": 800, "heat_impact": 0, "rep_impact": 15,
        "affected_scenes": ["arena", "casino", "lounge"],
        "narrative": "The crowd is forty thousand strong. The bookmakers are having the time of their lives.",
    },
    {
        "title": "Ghost Net Broadcast",
        "desc": "0xGH0ST hijacks every screen in Neon City with a message.",
        "scene": "neoncity", "event_type": "hacker_event", "intensity": 3.0,
        "economy_impact": 0, "heat_impact": 10, "rep_impact": 20,
        "affected_scenes": ["neoncity", "phone", "coders", "grid", "intel"],
        "narrative": "For sixty seconds, the city sees the truth. Then the screens go dark again.",
        "faction": "Ghost_Net",
    },
    {
        "title": "Supply Chain Disrupted",
        "desc": "A hijacked shipment causes shortages across the market.",
        "scene": "grid", "event_type": "market_crash", "intensity": 2.0,
        "economy_impact": -300, "heat_impact": 3, "rep_impact": 0,
        "affected_scenes": ["grid", "heist", "tavern"],
        "narrative": "Shelves empty by noon. Prices triple. Someone planned this months ago.",
    },
    {
        "title": "Rogue AI Incident",
        "desc": "A corp AI breaks containment and starts making trades on the open market.",
        "scene": "coders", "event_type": "hacker_event", "intensity": 2.5,
        "economy_impact": 1000, "heat_impact": 5, "rep_impact": 0,
        "affected_scenes": ["coders", "grid", "casino"],
        "narrative": "For three hours it wins every bet. Then it stops. No explanation given.",
    },
    {
        "title": "Political Assassination",
        "desc": "A mid-level corp executive is found dead. No suspects. No witnesses.",
        "scene": "neoncity", "event_type": "gang_war", "intensity": 3.0,
        "economy_impact": 0, "heat_impact": 20, "rep_impact": 0,
        "affected_scenes": ["neoncity", "phone", "lounge", "intel"],
        "narrative": "The investigation is closed before it opens. Someone very powerful gave the order.",
        "faction": "DeepState",
    },
    {
        "title": "Free Zone Declared",
        "desc": "The lower districts declare independence from corp jurisdiction.",
        "scene": "neoncity", "event_type": "faction_expansion", "intensity": 2.5,
        "economy_impact": 500, "heat_impact": -8, "rep_impact": 15,
        "affected_scenes": ["neoncity", "grid", "lounge", "tavern"],
        "narrative": "For now, the corps hold back. For now.",
        "faction": "BlackMarket",
    },
    {
        "title": "Memory Auction",
        "desc": "Stolen neural recordings go up for bid. Prices beyond belief.",
        "scene": "lounge", "event_type": "underground_auction", "intensity": 2.5,
        "economy_impact": 750, "heat_impact": 6, "rep_impact": 5,
        "affected_scenes": ["lounge", "grid", "gallery"],
        "narrative": "You're bidding on someone else's life. The memories feel real. That's the point.",
    },
    {
        "title": "Neon City Curfew",
        "desc": "A city-wide curfew is imposed. Streets deserted by 22:00.",
        "scene": "neoncity", "event_type": "corp_raid", "intensity": 2.0,
        "economy_impact": -250, "heat_impact": 6, "rep_impact": -3,
        "affected_scenes": ["neoncity", "grid", "lounge", "casino"],
        "narrative": "The enforcers are out early. Curfew means compliance. Or consequences.",
        "faction": "OmniCorp",
    },
]

# ---------------------------------------------------------------------------
# Faction event templates
# ---------------------------------------------------------------------------

FACTION_EVENTS_RICH: List[Dict[str, Any]] = [
    {
        "faction": "OmniCorp", "action": "expands territory",
        "title": "OmniCorp Expansion", "intensity": 2.0,
        "economy_impact": -100, "heat_impact": 5,
        "desc": "OmniCorp pushes its checkpoints three blocks north. The locals aren't happy.",
        "affected_scenes": ["neoncity", "grid"],
    },
    {
        "faction": "BlackMarket", "action": "controls supply routes",
        "title": "BlackMarket Lockdown", "intensity": 1.8,
        "economy_impact": 200, "heat_impact": 4,
        "desc": "The BlackMarket cartel tightens its grip on supply routes. Everything costs more.",
        "affected_scenes": ["grid", "heist"],
    },
    {
        "faction": "Ghost_Net", "action": "leaks classified data",
        "title": "Ghost_Net Intel Drop", "intensity": 2.5,
        "economy_impact": 0, "heat_impact": 8,
        "desc": "Ghost_Net releases classified corp files. The net erupts.",
        "affected_scenes": ["coders", "phone", "intel"],
    },
    {
        "faction": "NeoTech", "action": "deploys new enforcers",
        "title": "NeoTech Deployment", "intensity": 2.0,
        "economy_impact": 0, "heat_impact": 10,
        "desc": "NeoTech's new combat drones patrol the tech district.",
        "affected_scenes": ["neoncity", "coders"],
    },
    {
        "faction": "SynthSec", "action": "arrests key contact",
        "title": "SynthSec Sweep", "intensity": 2.2,
        "economy_impact": -300, "heat_impact": 12,
        "desc": "SynthSec takes down a fixer network. Three arrests. Dozens go dark.",
        "affected_scenes": ["phone", "heist", "grid"],
    },
    {
        "faction": "DeepState", "action": "moves assets",
        "title": "DeepState Reshuffles", "intensity": 1.5,
        "economy_impact": 0, "heat_impact": 3,
        "desc": "DeepState assets move overnight. Nobody knows where, or why.",
        "affected_scenes": ["intel", "lounge"],
    },
]

# ---------------------------------------------------------------------------
# Economy event templates
# ---------------------------------------------------------------------------

ECONOMY_EVENTS: List[Dict[str, Any]] = [
    {
        "title": "Market Surge", "event_type": "market_surge",
        "economy_impact": 300, "heat_impact": 0, "rep_impact": 2,
        "desc": "Demand for tech components surges. The market booms.",
        "affected_scenes": ["grid", "coders"],
    },
    {
        "title": "Market Crash", "event_type": "market_crash",
        "economy_impact": -400, "heat_impact": 0, "rep_impact": -2,
        "desc": "A sell-off cascade hits the black market hard.",
        "affected_scenes": ["grid", "casino"],
    },
    {
        "title": "Corp Tax Sweep", "event_type": "corp_tax",
        "economy_impact": -200, "heat_impact": 3, "rep_impact": 0,
        "desc": "OmniCorp enforcers collect 'service fees' across the district.",
        "affected_scenes": ["neoncity", "grid", "lounge"],
    },
    {
        "title": "Smuggler Windfall", "event_type": "market_surge",
        "economy_impact": 500, "heat_impact": 5, "rep_impact": 0,
        "desc": "A smuggler's cache hits the market. Prices drop. Volume spikes.",
        "affected_scenes": ["heist", "grid"],
    },
    {
        "title": "Banking Freeze", "event_type": "blackout",
        "economy_impact": -150, "heat_impact": 2, "rep_impact": 0,
        "desc": "Corp banks suspend withdrawals citing 'system maintenance'.",
        "affected_scenes": ["casino", "grid"],
    },
    {
        "title": "Side Job Payout", "event_type": "market_surge",
        "economy_impact": 100, "heat_impact": 0, "rep_impact": 5,
        "desc": "A side contract comes through. Clean, quick, well-paid.",
        "affected_scenes": ["heist"],
    },
    {
        "title": "Festival Commerce", "event_type": "festival",
        "economy_impact": 250, "heat_impact": -3, "rep_impact": 5,
        "desc": "Festival crowds flood the market. Everyone is buying.",
        "affected_scenes": ["grid", "neoncity", "tavern"],
    },
]

# ---------------------------------------------------------------------------
# 0xGH0ST messages (rich)
# ---------------------------------------------------------------------------

GHOST_MESSAGES_RICH: List[Dict[str, Any]] = [
    {
        "message": "They moved the package. Check the drop point. You have 2 hours.",
        "intensity": 2.0, "heat_impact": 3,
    },
    {
        "message": "Corp comms intercepted. They know about the node. Sending now.",
        "intensity": 2.5, "heat_impact": 5,
    },
    {
        "message": "Someone's been asking about you. Be careful who you trust tonight.",
        "intensity": 1.8, "heat_impact": 2,
    },
    {
        "message": "Phase 2 begins at midnight. You know what to do. Don't be late.",
        "intensity": 2.0, "heat_impact": 0,
    },
    {
        "message": "I found something big. Meet me at the node. Come alone. Come quiet.",
        "intensity": 2.5, "heat_impact": 4,
    },
    {
        "message": "Encrypted burst incoming. Don't open it on a corp network. Trust nobody.",
        "intensity": 2.0, "heat_impact": 6,
    },
    {
        "message": "The auction has a new buyer. Someone with real power. Things just got complicated.",
        "intensity": 2.2, "heat_impact": 3,
    },
    {
        "message": "Your name came up in a SynthSec briefing. Lay low. Delete this.",
        "intensity": 3.0, "heat_impact": 8,
    },
    {
        "message": "The data you're looking for exists. It's in the archive. Floor 33.",
        "intensity": 1.5, "heat_impact": 0,
    },
    {
        "message": "Three corps are about to sign an agreement. It will end what's left of the free zones.",
        "intensity": 3.0, "heat_impact": 0,
    },
    {
        "message": "I'm 0xGH0ST. I'm everywhere. But I won't be here much longer. Make it count.",
        "intensity": 3.0, "heat_impact": 0,
    },
    {
        "message": "The Broker lied to you. The intel was sold twice. Don't use the drop point.",
        "intensity": 2.5, "heat_impact": 5,
    },
]

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get_events_for_scene(scene: str, event_list: List[Dict]) -> List[Dict]:
    """Filter an event list to those affecting the given scene.

    Args:
        scene: Scene key to filter by.
        event_list: One of the module-level lists.

    Returns:
        Filtered list of events.
    """
    return [
        ev for ev in event_list
        if ev.get("scene") == scene or scene in ev.get("affected_scenes", [])
    ]


def get_all_world_events() -> List[Dict]:
    """Return all world event templates combined.

    Returns:
        Combined list of WORLD_EVENTS_RICH and ECONOMY_EVENTS.
    """
    return WORLD_EVENTS_RICH + ECONOMY_EVENTS
