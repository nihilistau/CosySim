"""Daily challenge generator — uses NLM to create fresh scene challenges daily."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, Optional

from engine.config import get_config  # noqa: F401
from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

CHALLENGE_PROMPT_TEMPLATE = (
    "Generate a daily challenge for the CosySim scene '{scene}'.\n"
    "Scene theme: {theme}\n"
    "Challenge should be:\n"
    "- Completable in one session (30 min)\n"
    "- Involve at least 2 NPCs\n"
    "- Have a clear win condition\n"
    "- Be creative and thematic\n\n"
    'Return as JSON: {{"title": "...", "description": "...", '
    '"win_condition": "...", "reward": "...", "difficulty": 1-5}}'
)

SCENE_THEMES: Dict[str, str] = {
    "penthouse": "luxury penthouse, seduction, high society secrets",
    "casino": "underground gambling, noir atmosphere, high stakes",
    "arena": "gladiatorial combat, spectacle, honor and glory",
    "tavern": "medieval tavern, mercenaries, rumors and contracts",
    "lounge": "exclusive velvet lounge, deals in shadows",
    "gallery": "art theft, forgery, collector obsession",
    "realm": "fantasy kingdom, political intrigue, magic",
    "neoncity": "cyberpunk dystopia, hacking, corporate espionage",
    "phone": "covert operations, intelligence networks, dead drops",
}

_FALLBACK_CHALLENGES: Dict[str, Dict[str, Any]] = {
    "penthouse": {
        "title": "The Secret Admirer",
        "description": "Uncover who left the cryptic note",
        "win_condition": "Identify the admirer and arrange a meeting",
        "reward": "+20 reputation with The Elite",
        "difficulty": 2,
    },
    "casino": {
        "title": "The Rigged Game",
        "description": "Expose the dealer who's cheating The House",
        "win_condition": "Gather evidence and report to management",
        "reward": "+15 standing with The House, -10 with The Players",
        "difficulty": 3,
    },
    "arena": {
        "title": "The Undefeated",
        "description": "Challenge the arena's reigning champion",
        "win_condition": "Win the bout or earn their respect",
        "reward": "+25 standing with The Gladiators",
        "difficulty": 4,
    },
    "tavern": {
        "title": "Missing Shipment",
        "description": "A merchant's goods never arrived. Find them.",
        "win_condition": "Recover the goods or reveal the thief",
        "reward": "+20 Guild standing + gold reward",
        "difficulty": 2,
    },
    "lounge": {
        "title": "The Whisper Network",
        "description": "Someone is leaking Inner Circle secrets",
        "win_condition": "Identify the leak without exposure",
        "reward": "+30 Inner Circle standing",
        "difficulty": 4,
    },
    "gallery": {
        "title": "The Forgery",
        "description": "A priceless piece may be a fake. Verify it.",
        "win_condition": "Confirm authenticity and expose the forger",
        "reward": "+20 Collectors standing",
        "difficulty": 3,
    },
    "realm": {
        "title": "The Prophecy Fragment",
        "description": "A fragment of the realm prophecy has surfaced",
        "win_condition": "Retrieve and decipher the fragment",
        "reward": "+20 Crown standing, new story arc unlocked",
        "difficulty": 3,
    },
    "neoncity": {
        "title": "Ghost Signal",
        "description": "A rogue AI is broadcasting on Ghost_Net frequencies",
        "win_condition": "Trace and shut down the signal",
        "reward": "+25 Ghost_Net standing",
        "difficulty": 4,
    },
    "phone": {
        "title": "The Dead Drop",
        "description": "An asset left data at a dead drop. Retrieve it safely.",
        "win_condition": "Collect data without being followed",
        "reward": "+20 Network standing",
        "difficulty": 2,
    },
}

_REQUIRED_KEYS = {"title", "description", "win_condition", "reward", "difficulty"}


class DailyChallengeManager:
    """Generates and stores daily challenges per scene using NLM."""

    _instance: Optional["DailyChallengeManager"] = None

    def __init__(self) -> None:
        self._today_challenges: Dict[str, Any] = {}
        self._last_generated: Optional[date] = None

    @classmethod
    def get_instance(cls) -> "DailyChallengeManager":
        """Return the singleton DailyChallengeManager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_challenge(self, scene: str) -> Dict[str, Any]:
        """Return today's challenge for *scene*, generating it on first call.

        Args:
            scene: Scene name.

        Returns:
            Challenge dict with keys: title, description, win_condition,
            reward, difficulty.
        """
        today = date.today()
        if self._last_generated != today:
            self._today_challenges.clear()

        if scene not in self._today_challenges:
            self._today_challenges[scene] = self._generate_challenge(scene)
            self._last_generated = today

        return self._today_challenges[scene]

    def _generate_challenge(self, scene: str) -> Dict[str, Any]:
        """Try Nexus cache first, fall back to pre-written challenges.

        Args:
            scene: Scene name.

        Returns:
            Challenge dict.
        """
        theme = SCENE_THEMES.get(scene, "mystery and intrigue")

        try:
            client = get_nexus_client()
            cache_key = f"daily_challenge_{scene}_{date.today()}"
            cached = client.search(cache_key)
            if cached:
                candidate = json.loads(cached[0].get("content", "{}"))
                if _REQUIRED_KEYS.issubset(candidate):
                    return candidate
        except Exception:
            pass

        return self._fallback_challenge(scene, theme)

    def _fallback_challenge(self, scene: str, theme: str) -> Dict[str, Any]:
        """Return a pre-written fallback challenge for *scene*.

        Args:
            scene: Scene name.
            theme: Scene theme string (unused in fallback, kept for API parity).

        Returns:
            Challenge dict.
        """
        return _FALLBACK_CHALLENGES.get(
            scene,
            {
                "title": f"{scene.title()} Daily Challenge",
                "description": "A mystery awaits.",
                "win_condition": "Solve the mystery.",
                "reward": "Reputation boost",
                "difficulty": 2,
            },
        )

    def seed_all(self) -> Dict[str, str]:
        """Pre-generate challenges for all known scenes and store in Nexus.

        Returns:
            Dict mapping scene -> challenge title.
        """
        results: Dict[str, str] = {}
        for scene in SCENE_THEMES:
            challenge = self.get_challenge(scene)
            results[scene] = challenge.get("title", "unknown")
            try:
                client = get_nexus_client()
                cache_key = f"daily_challenge_{scene}_{date.today()}"
                client.add_entry(
                    title=cache_key,
                    content=json.dumps(challenge),
                    content_type="document",
                    category="challenges",
                    tags=["daily", "challenge", scene],
                )
            except Exception as exc:
                logger.debug("Could not store challenge for %s in Nexus: %s", scene, exc)
        return results


def get_daily_challenge_manager() -> DailyChallengeManager:
    """Return the singleton DailyChallengeManager.

    Returns:
        DailyChallengeManager instance.
    """
    return DailyChallengeManager.get_instance()
