"""Leaderboard system — competitive rankings across categories.

Tracks player scores across 6 categories with weekly and all-time
splits. Scores update from PlayerSessionState when requested.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class LeaderboardCategory(str, Enum):
    """Available leaderboard categories."""
    CREDITS = "credits"
    REPUTATION = "reputation"
    KILLS = "kills"
    HEISTS = "heists"
    HACKING = "hacking"
    TERRITORY = "territory"


@dataclass
class LeaderboardEntry:
    """A single player's score in one category.

    Attributes:
        player_id: Player identifier.
        display_name: Player display name.
        score: Numeric score value.
        updated_at: Last update timestamp.
    """
    player_id: str
    display_name: str
    score: int = 0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self, rank: int = 0) -> Dict[str, Any]:
        """Serialize with optional rank."""
        return {
            "rank": rank,
            "player_id": self.player_id,
            "display_name": self.display_name,
            "score": self.score,
            "updated_at": self.updated_at,
        }


class Leaderboard:
    """Multi-category leaderboard with weekly and all-time rankings.

    Each category maintains a sorted list of player scores. Scores
    are updated explicitly (not pulled automatically) so the caller
    controls when snapshots are taken.
    """

    # Map stat keys to leaderboard categories
    STAT_MAPPING: Dict[str, str] = {
        "credits": "credits",
        "reputation": "reputation",
        "kills": "kills",
        "heists_completed": "heists",
        "hacks_completed": "hacking",
    }

    def __init__(self) -> None:
        """Initialize leaderboard with empty boards."""
        self._lock = threading.RLock()
        # category → player_id → entry
        self._alltime: Dict[str, Dict[str, LeaderboardEntry]] = {
            cat.value: {} for cat in LeaderboardCategory
        }
        self._weekly: Dict[str, Dict[str, LeaderboardEntry]] = {
            cat.value: {} for cat in LeaderboardCategory
        }
        self._week_start: float = self._current_week_start()
        logger.info("Leaderboard initialized (%d categories)",
                    len(LeaderboardCategory))

    @staticmethod
    def _current_week_start() -> float:
        """Get the start of the current week (Monday 00:00 UTC)."""
        import calendar
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        monday = now - datetime.timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        return monday.timestamp()

    def update_score(self, category: str, player_id: str,
                     display_name: str, score: int) -> None:
        """Update a player's score in a category.

        Args:
            category: Leaderboard category (e.g., "credits").
            player_id: Player identifier.
            display_name: Player display name.
            score: New score value.
        """
        if category not in self._alltime:
            logger.warning("Unknown leaderboard category: %s", category)
            return

        now = time.time()
        with self._lock:
            self._check_week_reset()

            entry = LeaderboardEntry(
                player_id=player_id,
                display_name=display_name,
                score=score,
                updated_at=now,
            )
            self._alltime[category][player_id] = entry
            self._weekly[category][player_id] = LeaderboardEntry(
                player_id=player_id,
                display_name=display_name,
                score=score,
                updated_at=now,
            )

    def update_from_session_state(self, player_id: str, display_name: str,
                                   state_dict: Dict[str, Any]) -> int:
        """Bulk-update scores from a PlayerSessionState dict.

        Extracts relevant fields and updates all applicable categories.

        Args:
            player_id: Player identifier.
            display_name: Player display name.
            state_dict: PlayerSessionState.to_dict() output.

        Returns:
            Number of categories updated.
        """
        updated = 0
        credits_val = state_dict.get("credits", 0)
        self.update_score("credits", player_id, display_name, credits_val)
        updated += 1

        rep_val = state_dict.get("reputation", 0)
        self.update_score("reputation", player_id, display_name, rep_val)
        updated += 1

        stats = state_dict.get("stats", {})
        for stat_key, lb_cat in self.STAT_MAPPING.items():
            if stat_key in ("credits", "reputation"):
                continue  # Already handled
            val = stats.get(stat_key, 0)
            self.update_score(lb_cat, player_id, display_name, val)
            updated += 1

        return updated

    def get_top(self, category: str, limit: int = 10,
                weekly: bool = False) -> List[Dict[str, Any]]:
        """Get top players in a category.

        Args:
            category: Leaderboard category.
            limit: Number of top players to return.
            weekly: If True, return weekly rankings.

        Returns:
            List of ranked entry dicts.
        """
        source = self._weekly if weekly else self._alltime
        if category not in source:
            return []

        with self._lock:
            entries = sorted(
                source[category].values(),
                key=lambda e: e.score,
                reverse=True,
            )[:limit]
            return [e.to_dict(rank=i + 1) for i, e in enumerate(entries)]

    def get_rank(self, category: str, player_id: str,
                 weekly: bool = False) -> Optional[Dict[str, Any]]:
        """Get a player's rank in a category.

        Args:
            category: Leaderboard category.
            player_id: Player to look up.
            weekly: If True, check weekly rankings.

        Returns:
            Entry dict with rank, or None if player not found.
        """
        source = self._weekly if weekly else self._alltime
        if category not in source:
            return None

        with self._lock:
            entries = sorted(
                source[category].values(),
                key=lambda e: e.score,
                reverse=True,
            )
            for i, entry in enumerate(entries):
                if entry.player_id == player_id:
                    return entry.to_dict(rank=i + 1)
            return None

    def get_player_scores(self, player_id: str,
                          weekly: bool = False) -> Dict[str, Any]:
        """Get all scores for a player across all categories.

        Args:
            player_id: Player to look up.
            weekly: If True, return weekly scores.

        Returns:
            Dict of category → {score, rank} pairs.
        """
        source = self._weekly if weekly else self._alltime
        result: Dict[str, Any] = {}

        with self._lock:
            for cat in LeaderboardCategory:
                cat_entries = sorted(
                    source[cat.value].values(),
                    key=lambda e: e.score,
                    reverse=True,
                )
                for i, entry in enumerate(cat_entries):
                    if entry.player_id == player_id:
                        result[cat.value] = {
                            "score": entry.score,
                            "rank": i + 1,
                            "total_players": len(cat_entries),
                        }
                        break
                else:
                    result[cat.value] = {
                        "score": 0,
                        "rank": None,
                        "total_players": len(cat_entries),
                    }

        return result

    def _check_week_reset(self) -> None:
        """Reset weekly boards if a new week has started."""
        current_week = self._current_week_start()
        if current_week > self._week_start:
            self._weekly = {cat.value: {} for cat in LeaderboardCategory}
            self._week_start = current_week
            logger.info("Weekly leaderboards reset")

    def get_stats(self) -> Dict[str, Any]:
        """Get leaderboard statistics."""
        with self._lock:
            alltime_counts = {
                cat: len(entries) for cat, entries in self._alltime.items()
            }
            weekly_counts = {
                cat: len(entries) for cat, entries in self._weekly.items()
            }
            return {
                "categories": [c.value for c in LeaderboardCategory],
                "alltime_players": alltime_counts,
                "weekly_players": weekly_counts,
                "week_start": self._week_start,
            }

    def reset(self) -> None:
        """Clear all leaderboard data."""
        with self._lock:
            self._alltime = {cat.value: {} for cat in LeaderboardCategory}
            self._weekly = {cat.value: {} for cat in LeaderboardCategory}
        logger.info("Leaderboard reset")


# ──── Singleton ────

_LEADERBOARD: Optional[Leaderboard] = None
_lb_lock = threading.Lock()


def get_leaderboard() -> Leaderboard:
    """Get or create the global Leaderboard singleton."""
    global _LEADERBOARD
    if _LEADERBOARD is None:
        with _lb_lock:
            if _LEADERBOARD is None:
                _LEADERBOARD = Leaderboard()
    return _LEADERBOARD


def reset_leaderboard() -> None:
    """Reset the global Leaderboard singleton."""
    global _LEADERBOARD
    with _lb_lock:
        if _LEADERBOARD is not None:
            _LEADERBOARD.reset()
        _LEADERBOARD = None
