"""World news generator — converts living world events into cyberpunk news articles.

Subscribes to EventBus events (faction decisions, world events, market changes,
player actions) and transforms them into themed news articles with headlines,
body text, severity ratings, and categorization. Articles are stored in a ring
buffer and optionally archived to Nexus.
"""
from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Data Models ────


class NewsCategory(str, Enum):
    """News article categories for the NeonCity Chronicle."""

    CRIME = "crime"
    ECONOMY = "economy"
    FACTION = "faction"
    TECH = "tech"
    SOCIAL = "social"
    BREAKING = "breaking"
    SPORTS = "sports"
    UNDERWORLD = "underworld"


class NewsSeverity(int, Enum):
    """Article importance/severity rating."""

    ROUTINE = 1
    NOTABLE = 2
    SIGNIFICANT = 3
    MAJOR = 4
    BREAKING = 5


@dataclass
class NewsArticle:
    """A single news article in the NeonCity Chronicle."""

    article_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    headline: str = ""
    body: str = ""
    category: str = NewsCategory.CRIME.value
    severity: int = NewsSeverity.ROUTINE.value
    district: str = ""
    related_factions: List[str] = field(default_factory=list)
    related_npcs: List[str] = field(default_factory=list)
    related_players: List[str] = field(default_factory=list)
    source_event_type: str = ""
    source_event_id: str = ""
    byline: str = "NeonCity Chronicle Staff"
    timestamp: float = field(default_factory=time.time)
    read_count: int = 0
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = f"{self.source_event_type}:{self.headline[:40]}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize article for API responses."""
        d = asdict(self)
        d["age_minutes"] = int((time.time() - self.timestamp) / 60)
        return d

    def to_headline(self) -> Dict[str, Any]:
        """Short headline format for tickers."""
        return {
            "article_id": self.article_id,
            "headline": self.headline,
            "category": self.category,
            "severity": self.severity,
            "district": self.district,
            "timestamp": self.timestamp,
            "age_minutes": int((time.time() - self.timestamp) / 60),
        }


# ──── Headline + Body Template Libraries ────


_WORLD_EVENT_TEMPLATES: Dict[str, List[Dict[str, str]]] = {
    "crackdown": [
        {
            "headline": "OmniCorp Sweeps {district} — Dozens Detained",
            "body": (
                "Corporate security forces descended on {district} in a massive "
                "crackdown operation. Eyewitnesses report armored units sealing "
                "off blocks while drones scanned every alleyway. Street vendors "
                "scrambled to hide contraband as OmniCorp enforcers checked IDs "
                "and confiscated unauthorized tech. The operation is expected to "
                "drive up black-market prices in the coming days."
            ),
            "category": NewsCategory.CRIME.value,
            "severity": NewsSeverity.SIGNIFICANT.value,
        },
        {
            "headline": "Security Forces Lock Down {district} Amid Rising Tensions",
            "body": (
                "In what officials are calling a 'routine enforcement action', "
                "heavily armed security teams established checkpoints throughout "
                "{district}. Local fixers report that several underground markets "
                "have gone dark, and street-level dealers are lying low. "
                "Contraband prices are expected to spike as supply chains tighten."
            ),
            "category": NewsCategory.CRIME.value,
            "severity": NewsSeverity.NOTABLE.value,
        },
    ],
    "festival": [
        {
            "headline": "Neon Festival Lights Up {district} — Economy Booms",
            "body": (
                "The streets of {district} are alive with holographic displays, "
                "synth-music, and the unmistakable buzz of credits changing hands. "
                "The annual Neon Festival has drawn crowds from every corner of "
                "the city, with merchants reporting record sales. Street food "
                "vendors, chrome shops, and entertainment venues are running at "
                "full capacity as the celebrations continue into the night."
            ),
            "category": NewsCategory.SOCIAL.value,
            "severity": NewsSeverity.NOTABLE.value,
        },
        {
            "headline": "Fight Night Draws Blood and Credits in {district}",
            "body": (
                "The underground fighting circuit erupted in {district} last "
                "night, drawing spectators and gamblers from across the city. "
                "Unsanctioned bouts saw augmented fighters clash in brutal "
                "displays of chrome-enhanced combat. Betting pools reached "
                "record highs as the local economy surged on the influx of "
                "visitors and illicit credits."
            ),
            "category": NewsCategory.SPORTS.value,
            "severity": NewsSeverity.NOTABLE.value,
        },
    ],
    "hack": [
        {
            "headline": "BREAKING: Massive Data Breach Rocks {district}",
            "body": (
                "A sophisticated cyberattack has compromised critical systems "
                "in {district}, exposing sensitive corporate data and personal "
                "records. Netrunners are scrambling to trace the breach while "
                "security firms deploy emergency countermeasures. The stolen "
                "data is already appearing on darknet markets, and tech demand "
                "has surged as organizations rush to upgrade their defenses."
            ),
            "category": NewsCategory.TECH.value,
            "severity": NewsSeverity.MAJOR.value,
        },
        {
            "headline": "Rogue Black ICE Programs Detected in {district} Networks",
            "body": (
                "Network administrators across {district} are on high alert "
                "after autonomous Black ICE programs were detected roaming "
                "local subnets. The rogue countermeasure programs — believed "
                "to have escaped from a corporate server farm — are attacking "
                "unauthorized connections indiscriminately. Several netrunners "
                "have reported neural feedback damage from unexpected ICE "
                "encounters. Tech specialists are in high demand."
            ),
            "category": NewsCategory.TECH.value,
            "severity": NewsSeverity.SIGNIFICANT.value,
        },
    ],
    "shortage": [
        {
            "headline": "Supply Convoy Hijacked — {district} Faces Shortages",
            "body": (
                "A major supply convoy bound for {district} was ambushed on "
                "the outskirts highway early this morning. Raiders made off "
                "with medical supplies, processed food, and synth-stim "
                "shipments. Residents are already feeling the pinch as store "
                "shelves empty and prices climb. Local fixers are offering "
                "premium rates for anyone willing to track the stolen goods."
            ),
            "category": NewsCategory.ECONOMY.value,
            "severity": NewsSeverity.SIGNIFICANT.value,
        },
    ],
    "surplus": [
        {
            "headline": "Surplus Shipment Floods {district} Markets",
            "body": (
                "An unexpected surplus shipment has arrived in {district}, "
                "flooding local markets with cheap goods. Merchants are "
                "slashing prices to move inventory, creating a buyer's "
                "paradise for savvy shoppers. Economic analysts warn the "
                "price depression may be temporary as demand catches up."
            ),
            "category": NewsCategory.ECONOMY.value,
            "severity": NewsSeverity.ROUTINE.value,
        },
    ],
    "crash": [
        {
            "headline": "MARKET CRASH: Prices Plummet Across {district}",
            "body": (
                "A sudden economic downturn has sent prices spiraling "
                "downward across {district}. Traders are panic-selling "
                "inventory as confidence collapses. Some analysts blame "
                "corporate manipulation while others point to cascading "
                "debt defaults in the underground economy. Bargain hunters "
                "are moving in, but veterans warn: 'When prices crash this "
                "hard, someone always profits — and it's never the little guy.'"
            ),
            "category": NewsCategory.ECONOMY.value,
            "severity": NewsSeverity.MAJOR.value,
        },
    ],
    "war": [
        {
            "headline": "TURF WAR: Gangs Clash in {district} — Casualties Reported",
            "body": (
                "Violence erupted in {district} as rival gangs fought for "
                "territorial control in a bloody overnight battle. Automatic "
                "weapons fire and small explosions were reported across "
                "multiple blocks. Emergency services are overwhelmed, and "
                "residents are advised to stay indoors. Weapons and combat "
                "stim prices have spiked as both sides arm up for continued "
                "hostilities."
            ),
            "category": NewsCategory.CRIME.value,
            "severity": NewsSeverity.MAJOR.value,
        },
    ],
    "disaster": [
        {
            "headline": "Power Grid Failure Plunges {district} Into Darkness",
            "body": (
                "A catastrophic power grid failure has left large sections "
                "of {district} without electricity. Emergency generators "
                "are straining under the load as hospitals, security systems, "
                "and communication networks scramble for backup power. Tech "
                "crews are working around the clock to restore service, but "
                "estimates range from hours to days. Looters have already been "
                "spotted in the blacked-out zones."
            ),
            "category": NewsCategory.BREAKING.value,
            "severity": NewsSeverity.BREAKING.value,
        },
    ],
}

_FACTION_TEMPLATES: Dict[str, List[Dict[str, str]]] = {
    "expand": [
        {
            "headline": "{faction} Expands Operations Into {district}",
            "body": (
                "{faction} operatives have been spotted establishing new "
                "footholds in {district}, marking a significant territorial "
                "expansion. Local businesses report being 'offered protection' "
                "as the faction consolidates its presence. Rival organizations "
                "are watching the move closely, with tensions running high."
            ),
            "category": NewsCategory.FACTION.value,
            "severity": NewsSeverity.NOTABLE.value,
        },
    ],
    "sabotage": [
        {
            "headline": "{faction} Accused of Sabotage in {district}",
            "body": (
                "Covert operatives linked to {faction} are suspected of "
                "disrupting {target}'s operations in {district}. Witnesses "
                "report mysterious equipment failures, data corruption, and "
                "supply chain disruptions targeting {target} assets. While "
                "no official claim has been made, intelligence sources point "
                "firmly at {faction} involvement."
            ),
            "category": NewsCategory.UNDERWORLD.value,
            "severity": NewsSeverity.SIGNIFICANT.value,
        },
    ],
    "raid": [
        {
            "headline": "RAID: {faction} Strikes {target} in {district}",
            "body": (
                "In a brazen assault, {faction} forces launched a direct "
                "raid on {target} holdings in {district}. The attack, which "
                "lasted several hours, resulted in significant damage to "
                "{target}'s infrastructure and personnel. Control of key "
                "positions has shifted as {faction} capitalizes on the chaos."
            ),
            "category": NewsCategory.CRIME.value,
            "severity": NewsSeverity.MAJOR.value,
        },
    ],
    "defend": [
        {
            "headline": "{faction} Fortifies Position in {district}",
            "body": (
                "{faction} has reinforced its defensive posture in {district}, "
                "deploying additional security and surveillance assets. The "
                "move signals growing concern about rival incursions and "
                "suggests the faction is prioritizing territorial consolidation "
                "over expansion."
            ),
            "category": NewsCategory.FACTION.value,
            "severity": NewsSeverity.ROUTINE.value,
        },
    ],
    "negotiate": [
        {
            "headline": "{faction} Opens Diplomatic Channels With {target}",
            "body": (
                "In a surprising move, representatives of {faction} have "
                "initiated negotiations with {target} over territorial "
                "boundaries in {district}. Sources close to the talks "
                "describe the atmosphere as 'cautiously optimistic', though "
                "street-level operatives on both sides remain on high alert."
            ),
            "category": NewsCategory.FACTION.value,
            "severity": NewsSeverity.NOTABLE.value,
        },
    ],
    "recruit": [
        {
            "headline": "{faction} Recruiting Aggressively in {district}",
            "body": (
                "{faction} has launched a major recruitment drive in "
                "{district}, offering signing bonuses, chrome upgrades, "
                "and protection to locals willing to join their ranks. "
                "The push comes amid rising competition for talent as "
                "faction conflicts intensify across the city."
            ),
            "category": NewsCategory.FACTION.value,
            "severity": NewsSeverity.ROUTINE.value,
        },
    ],
    "fortify": [
        {
            "headline": "{faction} Hardens Defenses in {district}",
            "body": (
                "Construction crews linked to {faction} have been spotted "
                "installing new security infrastructure in {district}. "
                "Surveillance cameras, automated turrets, and reinforced "
                "checkpoints suggest the faction is digging in for a "
                "prolonged territorial hold."
            ),
            "category": NewsCategory.FACTION.value,
            "severity": NewsSeverity.ROUTINE.value,
        },
    ],
}

_FACTION_WAR_TEMPLATES: List[Dict[str, str]] = [
    {
        "headline": "WAR: {attacker} vs {defender} — {district} Becomes Battleground",
        "body": (
            "Open warfare has erupted in {district} as {attacker} forces "
            "launched a major offensive against {defender} positions. The "
            "fighting has engulfed multiple blocks, with both sides deploying "
            "heavy weapons and cybernetic shock troops. Civilians are fleeing "
            "the combat zone as infrastructure crumbles. This marks the most "
            "significant escalation in faction hostilities this quarter."
        ),
        "category": NewsCategory.BREAKING.value,
        "severity": NewsSeverity.BREAKING.value,
    },
    {
        "headline": "FACTION WAR Erupts in {district} — {attacker} Launches Offensive",
        "body": (
            "The uneasy peace in {district} shattered today as {attacker} "
            "launched a coordinated assault on {defender} strongholds. "
            "Explosions and gunfire echoed through the streets for hours as "
            "both factions committed their full force. Control of the district "
            "hangs in the balance, and neighboring areas brace for spillover "
            "violence."
        ),
        "category": NewsCategory.BREAKING.value,
        "severity": NewsSeverity.BREAKING.value,
    },
]

_MARKET_TEMPLATES: List[Dict[str, str]] = [
    {
        "headline": "Markets Volatile — {changes} Price Shifts Recorded",
        "body": (
            "NeonCity's underground economy saw {changes} significant price "
            "movements today as supply and demand forces continue to reshape "
            "the marketplace. Traders are watching key commodities closely, "
            "with particular attention on weapons, tech components, and "
            "consumable supplies. Smart buyers are positioning themselves "
            "for what analysts predict could be a turbulent trading week."
        ),
        "category": NewsCategory.ECONOMY.value,
        "severity": NewsSeverity.ROUTINE.value,
    },
    {
        "headline": "Economic Pulse: {changes} Commodity Shifts Shake Markets",
        "body": (
            "The daily market report shows {changes} notable price adjustments "
            "across NeonCity's trading floors. Supply chain disruptions and "
            "faction activity continue to drive volatility in key sectors. "
            "Contraband markets remain particularly unpredictable as enforcement "
            "patterns shift with faction territorial changes."
        ),
        "category": NewsCategory.ECONOMY.value,
        "severity": NewsSeverity.ROUTINE.value,
    },
]

_PLAYER_ACTION_TEMPLATES: Dict[str, List[Dict[str, str]]] = {
    "heist.job_complete": [
        {
            "headline": "Daring Heist Rocks the City — Mastermind Still at Large",
            "body": (
                "An audacious heist has been pulled off in the city, leaving "
                "security teams scrambling to piece together what happened. "
                "Witnesses describe a precisely coordinated operation that "
                "bypassed multiple layers of defense. The perpetrators remain "
                "unidentified, and local fixers are already buzzing about the "
                "job's sophistication."
            ),
            "category": NewsCategory.CRIME.value,
            "severity": NewsSeverity.SIGNIFICANT.value,
        },
    ],
    "arena.match_end": [
        {
            "headline": "Arena Results: Blood and Glory in the Colosseum",
            "body": (
                "Another night of brutal combat concluded at the Colosseum, "
                "with fighters pushing their augmented bodies to the limit. "
                "Betting pools saw massive turnover as favored combatants "
                "clashed in the cage. Medical teams were kept busy as the "
                "crowd roared for more."
            ),
            "category": NewsCategory.SPORTS.value,
            "severity": NewsSeverity.ROUTINE.value,
        },
    ],
    "casino.major_win": [
        {
            "headline": "Lucky Streak at Club Noir — Big Winner Walks Away Rich",
            "body": (
                "A high-roller hit an impressive winning streak at the Velvet "
                "Pit casino last night, walking away with a substantial pile "
                "of credits. The house took the loss in stride, but security "
                "was noticeably tighter for the rest of the evening. Regular "
                "patrons are hoping the luck is contagious."
            ),
            "category": NewsCategory.SOCIAL.value,
            "severity": NewsSeverity.NOTABLE.value,
        },
    ],
    "economy.transaction": [
        {
            "headline": "Notable Trade: Large Transaction Moves Markets",
            "body": (
                "A significant transaction has rippled through local markets, "
                "catching the attention of traders and fixers alike. While the "
                "details remain murky, the volume suggests a major player is "
                "making moves. Market watchers are adjusting their positions "
                "accordingly."
            ),
            "category": NewsCategory.ECONOMY.value,
            "severity": NewsSeverity.ROUTINE.value,
        },
    ],
}

_BYLINES: List[str] = [
    "NeonCity Chronicle Staff",
    "Mx. Vex — Street Beat",
    "Zero_Cool — Digital Frontier",
    "Raven Darkholme — Faction Watch",
    "Chrome Jenkins — Economy Desk",
    "Pulse — Breaking News",
    "Nyx — Underground Report",
    "DataSlinger — Tech Column",
    "Red — Combat Zone Correspondent",
    "Ghost — Anonymous Source",
]


# ──── WorldNewsGenerator ────


class WorldNewsGenerator:
    """Generates in-game cyberpunk news articles from world events.

    Subscribes to EventBus events, transforms them into themed articles,
    and maintains a ring buffer of recent articles for the news ticker,
    phone news app, and NPC awareness system.
    """

    MAX_ARTICLES = 200
    DEDUP_WINDOW_SECONDS = 120.0
    MIN_MARKET_CHANGES_FOR_ARTICLE = 3

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._articles: deque[NewsArticle] = deque(maxlen=self.MAX_ARTICLES)
        self._fingerprints: Dict[str, float] = {}
        self._subscription_ids: List[str] = []
        self._started = False
        self._stats = {
            "articles_generated": 0,
            "events_received": 0,
            "duplicates_skipped": 0,
            "articles_by_category": {c.value: 0 for c in NewsCategory},
            "articles_by_severity": {s.value: 0 for s in NewsSeverity},
        }
        self._custom_handlers: Dict[str, Callable] = {}

    def start(self) -> None:
        """Subscribe to EventBus events."""
        if self._started:
            return

        try:
            from engine.events.event_bus import get_event_bus

            bus = get_event_bus()

            event_handlers = {
                "world_event": self._handle_world_event,
                "faction_decision": self._handle_faction_decision,
                "faction_war": self._handle_faction_war,
                "world.economy_tick": self._handle_market_tick,
                "heist.job_complete": self._handle_player_action,
                "arena.match_end": self._handle_player_action,
                "casino.major_win": self._handle_player_action,
                "economy.transaction": self._handle_player_action,
            }

            for event_type, handler in event_handlers.items():
                sub_id = bus.subscribe(
                    event_type, handler, subscriber_id=f"news_gen:{event_type}"
                )
                self._subscription_ids.append(sub_id)

            self._started = True
            logger.info(
                "WorldNewsGenerator started — subscribed to %d event types",
                len(event_handlers),
            )
        except Exception:
            logger.warning("WorldNewsGenerator could not subscribe to EventBus")

    def stop(self) -> None:
        """Unsubscribe from EventBus."""
        if not self._started:
            return

        try:
            from engine.events.event_bus import get_event_bus

            bus = get_event_bus()
            for sub_id in self._subscription_ids:
                bus.unsubscribe(sub_id)
        except Exception:
            pass

        self._subscription_ids.clear()
        self._started = False
        logger.info("WorldNewsGenerator stopped")

    # ──── Event Handlers ────

    def _handle_world_event(self, event: Dict[str, Any]) -> None:
        """Handle living world stochastic events."""
        with self._lock:
            self._stats["events_received"] += 1

        payload = event.get("payload", event)
        event_type = payload.get("type", "")
        district = payload.get("district", "Unknown")
        narrative = payload.get("narrative", "")

        templates = _WORLD_EVENT_TEMPLATES.get(event_type, [])
        if not templates:
            self._generate_generic_world_article(payload)
            return

        template = random.choice(templates)
        headline = template["headline"].format(district=district)
        body = template["body"].format(district=district)

        article = NewsArticle(
            headline=headline,
            body=body,
            category=template["category"],
            severity=int(template["severity"]),
            district=district,
            source_event_type="world_event",
            source_event_id=str(payload.get("tick", "")),
            byline=random.choice(_BYLINES),
        )

        self._publish_article(article)

    def _handle_faction_decision(self, event: Dict[str, Any]) -> None:
        """Handle faction AI decisions."""
        with self._lock:
            self._stats["events_received"] += 1

        payload = event.get("payload", event)
        action = payload.get("action", "idle")
        faction = payload.get("faction", "Unknown")
        district = payload.get("target_district", "Unknown")
        target = payload.get("target_faction", "rival forces")
        control_delta = abs(payload.get("control_delta", 0))

        if action == "idle" or control_delta < 0.5:
            return

        templates = _FACTION_TEMPLATES.get(action, [])
        if not templates:
            return

        template = random.choice(templates)
        headline = template["headline"].format(
            faction=faction, district=district, target=target
        )
        body = template["body"].format(
            faction=faction, district=district, target=target
        )

        severity = int(template["severity"])
        if control_delta >= 3.0:
            severity = min(severity + 1, NewsSeverity.BREAKING.value)

        article = NewsArticle(
            headline=headline,
            body=body,
            category=template["category"],
            severity=severity,
            district=district,
            related_factions=[faction] + ([target] if target != "rival forces" else []),
            source_event_type="faction_decision",
            source_event_id=f"{faction}:{action}",
            byline=random.choice(_BYLINES),
        )

        self._publish_article(article)

    def _handle_faction_war(self, event: Dict[str, Any]) -> None:
        """Handle faction war events — always generates BREAKING news."""
        with self._lock:
            self._stats["events_received"] += 1

        payload = event.get("payload", event)
        attacker = payload.get("attacker", "Unknown")
        defender = payload.get("defender", "Unknown")
        district = payload.get("district", "Unknown")

        template = random.choice(_FACTION_WAR_TEMPLATES)
        headline = template["headline"].format(
            attacker=attacker, defender=defender, district=district
        )
        body = template["body"].format(
            attacker=attacker, defender=defender, district=district
        )

        article = NewsArticle(
            headline=headline,
            body=body,
            category=NewsCategory.BREAKING.value,
            severity=NewsSeverity.BREAKING.value,
            district=district,
            related_factions=[attacker, defender],
            source_event_type="faction_war",
            source_event_id=f"{attacker}_vs_{defender}",
            byline="Pulse — Breaking News",
        )

        self._publish_article(article)

    def _handle_market_tick(self, event: Dict[str, Any]) -> None:
        """Handle market economy ticks — only generates article on notable changes."""
        with self._lock:
            self._stats["events_received"] += 1

        payload = event.get("payload", event)
        changes = payload.get("price_changes", 0)

        if changes < self.MIN_MARKET_CHANGES_FOR_ARTICLE:
            return

        template = random.choice(_MARKET_TEMPLATES)
        headline = template["headline"].format(changes=changes)
        body = template["body"].format(changes=changes)

        article = NewsArticle(
            headline=headline,
            body=body,
            category=NewsCategory.ECONOMY.value,
            severity=NewsSeverity.ROUTINE.value,
            source_event_type="market_tick",
            source_event_id=str(payload.get("tick", "")),
            byline="Chrome Jenkins — Economy Desk",
        )

        self._publish_article(article)

    def _handle_player_action(self, event: Dict[str, Any]) -> None:
        """Handle player-generated events (heists, arena, casino)."""
        with self._lock:
            self._stats["events_received"] += 1

        event_type = event.get("event_type", "")
        payload = event.get("payload", event)

        templates = _PLAYER_ACTION_TEMPLATES.get(event_type, [])
        if not templates:
            return

        template = random.choice(templates)
        headline = template["headline"]
        body = template["body"]

        player_id = payload.get("player_id", "")

        article = NewsArticle(
            headline=headline,
            body=body,
            category=template["category"],
            severity=int(template["severity"]),
            related_players=[player_id] if player_id else [],
            source_event_type=event_type,
            source_event_id=str(payload.get("id", "")),
            byline=random.choice(_BYLINES),
        )

        self._publish_article(article)

    def _generate_generic_world_article(self, payload: Dict[str, Any]) -> None:
        """Generate a generic article for unmapped world events."""
        name = payload.get("name", "Unknown Event")
        district = payload.get("district", "Unknown")
        narrative = payload.get("narrative", f"An event occurred in {district}.")

        article = NewsArticle(
            headline=f"City Alert: {name} in {district}",
            body=narrative,
            category=NewsCategory.BREAKING.value,
            severity=NewsSeverity.NOTABLE.value,
            district=district,
            source_event_type="world_event",
            source_event_id=str(payload.get("tick", "")),
            byline=random.choice(_BYLINES),
        )

        self._publish_article(article)

    # ──── Article Management ────

    def _publish_article(self, article: NewsArticle) -> bool:
        """Add article to buffer after dedup check. Returns True if published."""
        with self._lock:
            now = time.time()

            # Dedup check
            if article.fingerprint in self._fingerprints:
                last_seen = self._fingerprints[article.fingerprint]
                if now - last_seen < self.DEDUP_WINDOW_SECONDS:
                    self._stats["duplicates_skipped"] += 1
                    return False

            self._fingerprints[article.fingerprint] = now
            self._articles.appendleft(article)
            self._stats["articles_generated"] += 1
            self._stats["articles_by_category"][article.category] = (
                self._stats["articles_by_category"].get(article.category, 0) + 1
            )
            self._stats["articles_by_severity"][article.severity] = (
                self._stats["articles_by_severity"].get(article.severity, 0) + 1
            )

            # Prune old fingerprints
            cutoff = now - self.DEDUP_WINDOW_SECONDS * 2
            stale = [fp for fp, ts in self._fingerprints.items() if ts < cutoff]
            for fp in stale:
                del self._fingerprints[fp]

        logger.debug("News: [%s] %s", article.category.upper(), article.headline)
        return True

    def inject_article(self, article: NewsArticle) -> bool:
        """Manually inject an article (for testing or custom events)."""
        return self._publish_article(article)

    def publish_custom_article(
        self,
        headline: str,
        body: str,
        category: str = NewsCategory.SOCIAL.value,
        severity: int = NewsSeverity.NOTABLE.value,
        district: str = "",
        byline: str = "NeonCity Chronicle Staff",
        related_npcs: Optional[List[str]] = None,
        related_players: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Publish a custom news article from conversations, skills, or player actions.

        This is the public API for creating news articles that don't originate
        from EventBus events — e.g. gossip, player-generated content, or
        AI conversation outcomes that should appear in the news ticker.

        Args:
            headline: Article headline (shown in ticker).
            body: Full article body text.
            category: NewsCategory value string.
            severity: NewsSeverity int value.
            district: District where the event occurred.
            byline: Author credit.
            related_npcs: NPC IDs involved.
            related_players: Player IDs involved.

        Returns:
            Article ID if published, None if deduped.
        """
        article = NewsArticle(
            headline=headline,
            body=body,
            category=category,
            severity=severity,
            district=district,
            byline=byline,
            related_npcs=related_npcs or [],
            related_players=related_players or [],
            source_event_type="custom",
        )
        if self._publish_article(article):
            logger.info("News: custom article published: %s", headline[:60])
            return article.article_id
        return None

    # ──── Query API ────

    def get_headlines(
        self, limit: int = 10, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get latest headlines, optionally filtered by category."""
        with self._lock:
            articles = list(self._articles)

        if category:
            articles = [a for a in articles if a.category == category]

        return [a.to_headline() for a in articles[:limit]]

    def get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get full article by ID."""
        with self._lock:
            for article in self._articles:
                if article.article_id == article_id:
                    article.read_count += 1
                    return article.to_dict()
        return None

    def get_breaking_news(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get only BREAKING severity articles."""
        with self._lock:
            breaking = [
                a for a in self._articles
                if a.severity >= NewsSeverity.MAJOR.value
            ]
        return [a.to_dict() for a in breaking[:limit]]

    def get_by_category(
        self, category: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get articles filtered by category."""
        with self._lock:
            filtered = [a for a in self._articles if a.category == category]
        return [a.to_dict() for a in filtered[:limit]]

    def get_by_district(
        self, district: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get articles about a specific district."""
        with self._lock:
            filtered = [
                a for a in self._articles
                if a.district.lower() == district.lower()
            ]
        return [a.to_dict() for a in filtered[:limit]]

    def get_by_faction(
        self, faction: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get articles mentioning a specific faction."""
        with self._lock:
            filtered = [
                a for a in self._articles
                if faction in a.related_factions
                or faction.lower() in a.headline.lower()
                or faction.lower() in a.body.lower()
            ]
        return [a.to_dict() for a in filtered[:limit]]

    def search_articles(
        self, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Full-text search across headlines and bodies."""
        query_lower = query.lower()
        with self._lock:
            matches = [
                a for a in self._articles
                if query_lower in a.headline.lower()
                or query_lower in a.body.lower()
            ]
        return [a.to_dict() for a in matches[:limit]]

    def get_ticker_feed(self, limit: int = 5) -> List[str]:
        """Get formatted ticker strings for the news crawl."""
        with self._lock:
            articles = list(self._articles)[:limit]

        severity_icons = {
            1: "○",
            2: "◐",
            3: "●",
            4: "◆",
            5: "⚡",
        }

        return [
            f"{severity_icons.get(a.severity, '○')} {a.headline}"
            for a in articles
        ]

    def get_editorial_digest(self, count: int = 5) -> str:
        """Generate a narrative digest of recent news for NPC awareness."""
        with self._lock:
            articles = list(self._articles)[:count]

        if not articles:
            return "The city is quiet today. No major incidents to report."

        lines = ["NEONCITY CHRONICLE — LATEST EDITION", ""]
        for i, article in enumerate(articles, 1):
            lines.append(f"{i}. {article.headline}")
            first_sentence = article.body.split(". ")[0] + "."
            lines.append(f"   {first_sentence}")
            lines.append("")

        return "\n".join(lines)

    def get_all_articles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all articles as dicts."""
        with self._lock:
            return [a.to_dict() for a in list(self._articles)[:limit]]

    def stats(self) -> Dict[str, Any]:
        """Return generator statistics."""
        with self._lock:
            return {
                **self._stats,
                "buffer_size": len(self._articles),
                "buffer_max": self.MAX_ARTICLES,
                "fingerprints_tracked": len(self._fingerprints),
                "started": self._started,
                "subscriptions": len(self._subscription_ids),
            }

    def reset(self) -> None:
        """Clear all articles and stats."""
        with self._lock:
            self._articles.clear()
            self._fingerprints.clear()
            self._stats = {
                "articles_generated": 0,
                "events_received": 0,
                "duplicates_skipped": 0,
                "articles_by_category": {c.value: 0 for c in NewsCategory},
                "articles_by_severity": {s.value: 0 for s in NewsSeverity},
            }


# ──── Singleton ────

_instance: Optional[WorldNewsGenerator] = None
_instance_lock = threading.Lock()


def get_news_generator() -> WorldNewsGenerator:
    """Get or create the singleton WorldNewsGenerator."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = WorldNewsGenerator()
    return _instance


def reset_news_generator() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.stop()
        _instance = None
