"""PresenceTracker — minimal "who is reachable right now" signal for comms (CB-T4).

The "leave-a-message" feature needs a way to ask *is the other party online?* so
a sender (player OR NPC) can post to a thread that the recipient cannot see yet
and have it delivered later. CosySim has no first-class presence system, so this
module provides the smallest thing that works:

* **Player presence** is socket-driven: the player is "online" while at least
  one phone client is connected. When the phone UI is closed (no socket
  clients) the player is "offline" and incoming NPC messages are *left* for
  them rather than dropped. ``connect()`` / ``disconnect()`` are called from the
  phone scene's Socket.IO lifecycle.
* **NPC presence** is co-presence-driven: an NPC is "online" *to the player*
  only when both share a city-map location (the player can plausibly reach
  them in person). When the NPC is elsewhere, a player send is *left* for them.
  This reuses :func:`engine.world.city_map.get_city_map` so no new state is
  introduced.

Everything is config-driven via ``get_config().get("comms.presence.<key>")`` and
degrades safely: if presence cannot be determined (config missing, city map
unavailable, etc.) the tracker reports the recipient as ONLINE so behaviour is
unchanged from before this feature — leaving a message is strictly additive.

Configuration (read via ``get_config().get("comms.presence.<key>")``)::

    comms.presence.enabled                       bool  master toggle (default true)
    comms.presence.player_offline_when_disconnected bool  (default true)
    comms.presence.npc_requires_co_presence      bool  (default true)

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Initial minimal presence tracker (CB-T4): socket-
        driven player presence + co-presence-driven NPC presence, config-gated,
        fail-open (unknown → online). Singleton accessor for the phone scene
        and the NPC comms scheduler to share one view of who is reachable.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ══════════════════════════════════════════════════════════════════════

_DEFAULT_ENABLED = True
_DEFAULT_PLAYER_OFFLINE_WHEN_DISCONNECTED = True
_DEFAULT_NPC_REQUIRES_CO_PRESENCE = True

PLAYER_ID = "user"


# ══════════════════════════════════════════════════════════════════════
#  PRESENCE TRACKER
# ══════════════════════════════════════════════════════════════════════


class PresenceTracker:
    """Tracks who is reachable right now for the leave-a-message flow.

    The tracker holds the set of currently-connected phone socket clients to
    decide player presence, and consults the city map for NPC co-presence. It
    is intentionally tiny and fail-open: when presence is disabled or cannot be
    determined the recipient is reported as online (pre-feature behaviour).

    Attributes:
        n_clients: Number of currently-connected phone socket clients.
    """

    def __init__(self) -> None:
        """Initialise an empty tracker, reading config toggles once."""
        self._lock = threading.Lock()
        self._client_sids: set[str] = set()
        try:
            from engine.config import get_config
            cfg = get_config()
            self._enabled = bool(cfg.get("comms.presence.enabled", _DEFAULT_ENABLED))
            self._player_offline_when_disconnected = bool(
                cfg.get(
                    "comms.presence.player_offline_when_disconnected",
                    _DEFAULT_PLAYER_OFFLINE_WHEN_DISCONNECTED,
                )
            )
            self._npc_requires_co_presence = bool(
                cfg.get(
                    "comms.presence.npc_requires_co_presence",
                    _DEFAULT_NPC_REQUIRES_CO_PRESENCE,
                )
            )
        except Exception as exc:  # config optional in minimal builds/tests
            logger.debug("[presence] config lookup failed, using defaults: %s", exc)
            self._enabled = _DEFAULT_ENABLED
            self._player_offline_when_disconnected = (
                _DEFAULT_PLAYER_OFFLINE_WHEN_DISCONNECTED
            )
            self._npc_requires_co_presence = _DEFAULT_NPC_REQUIRES_CO_PRESENCE

    # ── player socket lifecycle ────────────────────────────────────────

    def connect(self, sid: Optional[str] = None) -> int:
        """Record a connected phone client, marking the player online.

        Args:
            sid: The Socket.IO session id of the connecting client. A synthetic
                id is used when ``None`` so anonymous connects still count.

        Returns:
            The number of clients connected after this connect.
        """
        with self._lock:
            self._client_sids.add(sid or f"anon-{len(self._client_sids)}")
            return len(self._client_sids)

    def disconnect(self, sid: Optional[str] = None) -> int:
        """Record a disconnected phone client.

        Args:
            sid: The Socket.IO session id of the disconnecting client. When
                ``None`` (or unknown) one arbitrary client is dropped so the
                count still decreases.

        Returns:
            The number of clients connected after this disconnect.
        """
        with self._lock:
            if sid is not None and sid in self._client_sids:
                self._client_sids.discard(sid)
            elif self._client_sids:
                self._client_sids.pop()
            return len(self._client_sids)

    @property
    def n_clients(self) -> int:
        """Return the number of currently-connected phone clients."""
        with self._lock:
            return len(self._client_sids)

    # ── presence queries ───────────────────────────────────────────────

    def is_player_online(self) -> bool:
        """Return whether the player is reachable on the phone right now.

        The player is online while at least one phone client is connected. When
        presence is disabled or the disconnect rule is off, the player is always
        considered online (fail-open).

        Returns:
            ``True`` if the player should receive messages immediately.
        """
        if not self._enabled or not self._player_offline_when_disconnected:
            return True
        return self.n_clients > 0

    def is_npc_online(self, npc_id: str) -> bool:
        """Return whether an NPC is reachable by the player right now.

        An NPC is online when co-present with the player (same city-map
        location). When presence is disabled, the co-presence rule is off, or
        locations cannot be determined, the NPC is considered online
        (fail-open) so behaviour matches the pre-feature baseline.

        Args:
            npc_id: The NPC character id.

        Returns:
            ``True`` if the NPC should receive the player's message immediately.
        """
        if not self._enabled or not self._npc_requires_co_presence:
            return True
        try:
            from engine.world.city_map import get_city_map, get_player_state
            cm = get_city_map()
            npc_loc = cm.get_npc_location(npc_id)
            player_loc = get_player_state().active_location
            # Unknown locations → fail open (treat as reachable).
            if not npc_loc or not player_loc:
                return True
            return npc_loc == player_loc
        except Exception as exc:
            logger.debug("[presence] npc presence check failed (npc=%s): %s", npc_id, exc)
            return True

    def is_online(self, character_id: str) -> bool:
        """Return whether a character (player or NPC) is reachable right now.

        Args:
            character_id: ``'user'`` for the player, else an NPC id.

        Returns:
            ``True`` if the character should receive messages immediately.
        """
        if character_id == PLAYER_ID:
            return self.is_player_online()
        return self.is_npc_online(character_id)


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON
# ══════════════════════════════════════════════════════════════════════

_tracker: Optional[PresenceTracker] = None
_singleton_lock = threading.Lock()


def get_presence_tracker() -> PresenceTracker:
    """Return the process-wide :class:`PresenceTracker` singleton.

    Tests that need isolation should construct :class:`PresenceTracker`
    directly instead.

    Returns:
        The shared :class:`PresenceTracker` instance.
    """
    global _tracker
    if _tracker is None:
        with _singleton_lock:
            if _tracker is None:
                _tracker = PresenceTracker()
    return _tracker
