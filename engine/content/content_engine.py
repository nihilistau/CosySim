"""Dynamic content engine for CosySim v0.68 'Dark Renaissance'.

Manages content pools (quests, events, scenarios, lore, dialogue starters,
arcs, fighters, and world events) backed by the Nexus knowledge base.

Pools are loaded lazily from Nexus on first request and automatically refilled
via NLM generation when the available-item count drops below the low-water
mark.  All pool mutations are protected by a reentrant lock to allow safe use
from multiple scene threads.

Nexus storage convention
------------------------
Each content item is stored as a ``note`` entry with:
  * ``category``   – ``content_pool:{scene}``
  * ``tags``       – list including ``scene:{scene}``, ``type:{content_type}``,
                     ``intensity:{0-3}``, and optionally ``adult:{category}``

Typical search query: ``"scene:bedroom type:scenario intensity:2"``

Example::

    from engine.content import get_content_engine

    engine = get_content_engine()
    quest = engine.get_quest("tavern", tags=["combat"], intensity=2)
    if quest:
        print(quest.title)
        engine.mark_used(quest.id)
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Valid content types handled by this engine.
CONTENT_TYPES = frozenset(
    {
        "quest",
        "event",
        "scenario",
        "lore",
        "dialogue",
        "arc",
        "fighter",
        "world_event",
    }
)

#: Default NLM prompt template for generating new content items.
_GENERATE_PROMPT = (
    "Generate {count} {content_type} items for the '{scene}' scene in a "
    "dark fantasy RPG.  Return a JSON array where every element has keys: "
    "title (str), content (str, 1-3 sentences), intensity (int 0-3), "
    "adult_categories (list[str]), tags (list[str]).  "
    "Tags must include 'scene:{scene}', 'type:{content_type}', and "
    "'intensity:N'.  Only return the JSON array, no extra text."
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ContentItem:
    """A single piece of dynamic content drawn from a content pool.

    Attributes:
        id: Unique identifier (Nexus entry ID or generated UUID).
        title: Short descriptive title visible to the LLM.
        content: Full content body (quest text, event description, etc.).
        scene: Scene this item belongs to (e.g. ``"bedroom"``, ``"tavern"``).
        content_type: Category of content – one of ``quest``, ``event``,
            ``scenario``, ``lore``, ``dialogue``, ``arc``, ``fighter``,
            ``world_event``.
        intensity: Narrative intensity level from 0 (mild) to 3 (extreme).
        adult_categories: Adult content flags present in this item,
            e.g. ``["sexual", "violence"]``.
        tags: Raw Nexus tags attached to this item.
        used: Whether this item has already been consumed.
        created_at: ISO-8601 creation timestamp.
    """

    id: str
    title: str
    content: str
    scene: str
    content_type: str
    intensity: int
    adult_categories: List[str]
    tags: List[str]
    used: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        # Clamp intensity to valid range.
        self.intensity = max(0, min(3, self.intensity))


class ContentPool:
    """Holds all ContentItems for a (scene, content_type) pair.

    Args:
        scene: Scene identifier this pool serves.
        content_type: Type of content stored here.
        low_water_mark: Minimum number of unused items before triggering
            automatic NLM refill.  Defaults to 5.
    """

    def __init__(
        self,
        scene: str,
        content_type: str,
        low_water_mark: int = 5,
    ) -> None:
        self.scene: str = scene
        self.content_type: str = content_type
        self.items: List[ContentItem] = []
        self.low_water_mark: int = low_water_mark

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_depleted(self) -> bool:
        """Return ``True`` when unused items fall below the low-water mark.

        Returns:
            ``True`` if the pool needs refilling.
        """
        return self.available_count() < self.low_water_mark

    def available_count(self) -> int:
        """Return the number of unused items currently in the pool.

        Returns:
            Count of items with ``used == False``.
        """
        return sum(1 for item in self.items if not item.used)

    def total_count(self) -> int:
        """Return the total number of items including consumed ones.

        Returns:
            Total item count.
        """
        return len(self.items)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, item: ContentItem) -> None:
        """Append *item* to the pool, ignoring duplicate IDs.

        Args:
            item: The ContentItem to add.
        """
        existing_ids = {i.id for i in self.items}
        if item.id not in existing_ids:
            self.items.append(item)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def get_unused(
        self,
        intensity: Optional[int] = None,
        tags: Optional[List[str]] = None,
        adult_category: str = "",
    ) -> Optional[ContentItem]:
        """Return the first unused item matching all supplied filters.

        Filters are optional; omitting one means "don't filter by this field".

        Args:
            intensity: If provided, only items with this exact intensity
                level are considered.
            tags: If provided, every tag in this list must appear in the
                item's ``tags`` field.
            adult_category: If non-empty, the item's ``adult_categories``
                must include this value.

        Returns:
            A matching :class:`ContentItem`, or ``None`` if none found.
        """
        for item in self.items:
            if item.used:
                continue
            if intensity is not None and item.intensity != intensity:
                continue
            if tags and not all(t in item.tags for t in tags):
                continue
            if adult_category and adult_category not in item.adult_categories:
                continue
            return item
        return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_PoolKey = Tuple[str, str]  # (scene, content_type)


class ContentEngine:
    """Central engine for dynamic content retrieval and pool management.

    All public ``get_*`` methods share the same lifecycle:

    1. Ensure the pool for ``(scene, content_type)`` is loaded from Nexus.
    2. Return the first unused item matching the supplied filters.
    3. If the pool has dropped below ``low_water_mark``, schedule an async
       NLM refill so future calls will be served without delay.

    Args:
        nexus_client: Optional pre-built Nexus client (mainly for testing).
            If omitted, the global singleton from
            :func:`engine.nexus.client.get_nexus_client` is used.
    """

    def __init__(self, nexus_client=None) -> None:
        self._nexus = nexus_client or get_nexus_client()
        self._pools: Dict[_PoolKey, ContentPool] = {}
        self._lock = threading.RLock()
        self._refills_in_progress: Set[_PoolKey] = set()

    # ------------------------------------------------------------------
    # Public get_* API
    # ------------------------------------------------------------------

    def get_quest(
        self,
        scene: str,
        tags: Optional[List[str]] = None,
        intensity: int = 2,
    ) -> Optional[ContentItem]:
        """Return an unused quest for *scene*.

        Args:
            scene: Target scene identifier.
            tags: Optional extra tags that must be present on the item.
            intensity: Desired intensity level (0-3).

        Returns:
            A :class:`ContentItem` of type ``quest``, or ``None``.
        """
        return self._get(scene, "quest", intensity=intensity, tags=tags)

    def get_event(
        self,
        scene: str,
        tags: Optional[List[str]] = None,
        intensity: int = 2,
    ) -> Optional[ContentItem]:
        """Return an unused event for *scene*.

        Args:
            scene: Target scene identifier.
            tags: Optional extra tags that must be present on the item.
            intensity: Desired intensity level (0-3).

        Returns:
            A :class:`ContentItem` of type ``event``, or ``None``.
        """
        return self._get(scene, "event", intensity=intensity, tags=tags)

    def get_scenario(
        self,
        scene: str,
        intensity: int = 2,
        adult_category: str = "",
    ) -> Optional[ContentItem]:
        """Return an unused scenario for *scene*.

        Args:
            scene: Target scene identifier.
            intensity: Desired intensity level (0-3).
            adult_category: If supplied, only scenarios flagged with this
                adult category are eligible.

        Returns:
            A :class:`ContentItem` of type ``scenario``, or ``None``.
        """
        return self._get(
            scene,
            "scenario",
            intensity=intensity,
            adult_category=adult_category,
        )

    def get_lore(
        self,
        topic: str,
        scene: str = "",
    ) -> Optional[ContentItem]:
        """Return a lore entry matching *topic*.

        The *topic* string is added to the tag filter so that only lore
        tagged with that keyword is returned.  If *scene* is empty the
        search spans all scenes.

        Args:
            topic: Subject keyword to filter lore by (e.g. ``"magic"``).
            scene: Optional scene constraint; pass ``""`` to search all.

        Returns:
            A :class:`ContentItem` of type ``lore``, or ``None``.
        """
        effective_scene = scene or "global"
        return self._get(effective_scene, "lore", tags=[topic])

    def get_dialogue_starter(
        self,
        character_id: str,
        mood: str = "",
        intensity: int = 2,
    ) -> Optional[ContentItem]:
        """Return a dialogue starter suited to *character_id*.

        The *character_id* is treated as the scene key so that each NPC
        has its own dialogue pool.

        Args:
            character_id: Identifier of the character / NPC.
            mood: Optional mood tag (e.g. ``"angry"``, ``"flirty"``).
            intensity: Desired intensity level (0-3).

        Returns:
            A :class:`ContentItem` of type ``dialogue``, or ``None``.
        """
        extra_tags = [mood] if mood else None
        return self._get(
            character_id,
            "dialogue",
            intensity=intensity,
            tags=extra_tags,
        )

    def get_arc(
        self,
        scene: str,
        arc_type: str = "",
    ) -> Optional[ContentItem]:
        """Return an unused story arc for *scene*.

        Args:
            scene: Target scene identifier.
            arc_type: Optional arc-type tag (e.g. ``"romance"``,
                ``"revenge"``).

        Returns:
            A :class:`ContentItem` of type ``arc``, or ``None``.
        """
        extra_tags = [arc_type] if arc_type else None
        return self._get(scene, "arc", tags=extra_tags)

    def get_fighter(
        self,
        scene: str = "arena",
    ) -> Optional[ContentItem]:
        """Return an unused fighter entry for the arena (or *scene*).

        Args:
            scene: Arena or combat scene identifier.  Defaults to
                ``"arena"``.

        Returns:
            A :class:`ContentItem` of type ``fighter``, or ``None``.
        """
        return self._get(scene, "fighter")

    def get_world_event(self) -> Optional[ContentItem]:
        """Return an unused world event from the global pool.

        Returns:
            A :class:`ContentItem` of type ``world_event``, or ``None``.
        """
        return self._get("global", "world_event")

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def mark_used(self, item_id: str) -> None:
        """Mark the item with *item_id* as consumed.

        Scans all pools until the item is found.  Safe to call with IDs
        that no longer exist in any pool.

        Args:
            item_id: The :attr:`ContentItem.id` to mark as used.
        """
        with self._lock:
            for pool in self._pools.values():
                for item in pool.items:
                    if item.id == item_id:
                        item.used = True
                        logger.debug(
                            "Marked item %s (%s) as used in pool %s/%s",
                            item_id,
                            item.title,
                            pool.scene,
                            pool.content_type,
                        )
                        return
        logger.debug("mark_used: item %s not found in any pool", item_id)

    def get_pool_status(self) -> Dict[str, Dict[str, Dict[str, int]]]:
        """Return a nested dict of pool sizes keyed by scene then type.

        The inner dict has two integer keys:

        * ``"available"`` – unused items ready for dispatch.
        * ``"total"``     – all items including consumed ones.

        Returns:
            Nested dict: ``{scene: {content_type: {"available": N, "total": M}}}``.

        Example::

            {
                "tavern": {
                    "quest": {"available": 4, "total": 12},
                    "event": {"available": 7, "total": 10},
                },
                "global": {
                    "world_event": {"available": 2, "total": 5},
                },
            }
        """
        status: Dict[str, Dict[str, Dict[str, int]]] = {}
        with self._lock:
            for (scene, ctype), pool in self._pools.items():
                status.setdefault(scene, {})[ctype] = {
                    "available": pool.available_count(),
                    "total": pool.total_count(),
                }
        return status

    def refill_pool(
        self,
        scene: str,
        content_type: str,
        count: int = 10,
    ) -> int:
        """Use NLM to generate *count* new items and add them to the pool.

        Calls :meth:`~engine.nexus.client.NexusClient.ask` with a
        structured prompt requesting a JSON array of content objects,
        parses the response, persists each item to Nexus, and adds it to
        the in-memory pool.

        Args:
            scene: Scene identifier for the new content.
            content_type: Type of content to generate.
            count: Number of items to request from NLM.

        Returns:
            Number of items successfully added (0 on failure).
        """
        prompt = _GENERATE_PROMPT.format(
            count=count,
            content_type=content_type,
            scene=scene,
        )
        logger.info(
            "Requesting NLM refill: %d %s items for scene '%s'",
            count,
            content_type,
            scene,
        )

        try:
            response = self._nexus.ask(prompt, depth="auto")
        except Exception as exc:
            logger.warning("NLM ask failed during refill: %s", exc)
            return 0

        raw_answer: str = response.get("answer", "") if isinstance(response, dict) else str(response)
        if not raw_answer:
            logger.warning("NLM returned empty answer for refill (%s/%s)", scene, content_type)
            return 0

        items = self._parse_nlm_response(raw_answer, scene, content_type)
        if not items:
            logger.warning(
                "Could not parse NLM response for %s/%s (len=%d)",
                scene,
                content_type,
                len(raw_answer),
            )
            return 0

        added = 0
        pool = self._ensure_pool(scene, content_type)
        for item in items:
            # Persist to Nexus so the item survives restarts.
            nexus_tags = list(
                {
                    f"scene:{item.scene}",
                    f"type:{item.content_type}",
                    f"intensity:{item.intensity}",
                }
                | {f"adult:{cat}" for cat in item.adult_categories}
                | set(item.tags)
            )
            try:
                entry_id = self._nexus.add_entry(
                    title=item.title,
                    content=item.content,
                    content_type="note",
                    category=f"content_pool:{scene}",
                    tags=nexus_tags,
                )
                if entry_id:
                    item.id = entry_id
            except Exception as exc:
                logger.debug("Failed to persist item to Nexus: %s", exc)

            with self._lock:
                pool.add(item)
            added += 1

        logger.info(
            "Refill complete: added %d/%d items to pool %s/%s",
            added,
            count,
            scene,
            content_type,
        )
        return added

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(
        self,
        scene: str,
        content_type: str,
        intensity: Optional[int] = None,
        tags: Optional[List[str]] = None,
        adult_category: str = "",
    ) -> Optional[ContentItem]:
        """Core retrieval logic shared by all public ``get_*`` methods.

        Ensures the pool is populated, selects an item, and schedules
        a background refill when the pool drops below the low-water mark.

        Args:
            scene: Scene or character identifier.
            content_type: One of the values in :data:`CONTENT_TYPES`.
            intensity: Optional exact intensity filter.
            tags: Optional list of tags that must all be present.
            adult_category: Optional adult-category filter.

        Returns:
            A matching :class:`ContentItem`, or ``None``.
        """
        pool = self._ensure_pool(scene, content_type)

        # Populate from Nexus on first access (or when pool is empty).
        with self._lock:
            if pool.total_count() == 0:
                items = self._fetch_from_nexus(
                    scene, content_type, intensity if intensity is not None else 2
                )
                for item in items:
                    pool.add(item)

        item = pool.get_unused(
            intensity=intensity,
            tags=tags,
            adult_category=adult_category,
        )

        # Trigger background refill when pool approaches depletion.
        self._maybe_schedule_refill(scene, content_type, pool)

        return item

    def _ensure_pool(self, scene: str, content_type: str) -> ContentPool:
        """Return the pool for *(scene, content_type)*, creating it if absent.

        Args:
            scene: Scene identifier.
            content_type: Content type.

        Returns:
            The :class:`ContentPool` for the given key.
        """
        key: _PoolKey = (scene, content_type)
        with self._lock:
            if key not in self._pools:
                self._pools[key] = ContentPool(scene, content_type)
            return self._pools[key]

    def _fetch_from_nexus(
        self,
        scene: str,
        content_type: str,
        intensity: int,
    ) -> List[ContentItem]:
        """Search Nexus for content matching *scene* / *content_type* / *intensity*.

        Builds a composite search query from the tag convention and
        parses the returned entries into :class:`ContentItem` objects.

        Args:
            scene: Scene identifier to match.
            content_type: Content type to match.
            intensity: Intensity level to match.

        Returns:
            A list of :class:`ContentItem` objects (may be empty).
        """
        query = f"scene:{scene} type:{content_type} intensity:{intensity}"
        logger.debug("Nexus fetch: %s", query)
        try:
            entries = self._nexus.search(query, limit=50)
        except Exception as exc:
            logger.warning("Nexus search failed: %s", exc)
            return []

        items: List[ContentItem] = []
        for entry in entries:
            item = self._entry_to_item(entry, scene, content_type)
            if item is not None:
                items.append(item)

        logger.debug("Fetched %d items from Nexus for %s/%s", len(items), scene, content_type)
        return items

    def _entry_to_item(
        self,
        entry: Dict,
        fallback_scene: str,
        fallback_type: str,
    ) -> Optional[ContentItem]:
        """Convert a raw Nexus entry dict to a :class:`ContentItem`.

        Extracts ``scene``, ``type``, ``intensity``, and ``adult:*`` values
        from the entry's ``tags`` list.  Falls back to *fallback_scene* and
        *fallback_type* when those tags are absent.

        Args:
            entry: Raw dict returned by :meth:`~NexusClient.search`.
            fallback_scene: Used when no ``scene:`` tag is found.
            fallback_type: Used when no ``type:`` tag is found.

        Returns:
            A populated :class:`ContentItem`, or ``None`` if the entry
            lacks both ``title`` and ``content``.
        """
        title: str = entry.get("title", "")
        content: str = entry.get("content", "")
        if not title and not content:
            return None

        tags: List[str] = entry.get("tags") or []
        if isinstance(tags, str):
            # Guard against malformed tag storage.
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = [t.strip() for t in tags.split(",") if t.strip()]

        # Extract structured fields from tags.
        item_scene = fallback_scene
        item_type = fallback_type
        intensity = 2
        adult_categories: List[str] = []

        for tag in tags:
            if tag.startswith("scene:"):
                item_scene = tag[len("scene:"):]
            elif tag.startswith("type:"):
                item_type = tag[len("type:"):]
            elif tag.startswith("intensity:"):
                try:
                    intensity = int(tag[len("intensity:"):])
                except ValueError:
                    pass
            elif tag.startswith("adult:"):
                adult_categories.append(tag[len("adult:"):])

        return ContentItem(
            id=entry.get("id") or str(uuid.uuid4()),
            title=title,
            content=content,
            scene=item_scene,
            content_type=item_type,
            intensity=intensity,
            adult_categories=adult_categories,
            tags=tags,
            created_at=entry.get("created_at", ""),
        )

    def _parse_nlm_response(
        self,
        raw: str,
        scene: str,
        content_type: str,
    ) -> List[ContentItem]:
        """Parse an NLM-generated JSON array into :class:`ContentItem` objects.

        Attempts to locate a JSON array anywhere in *raw* (NLM sometimes
        wraps responses in prose).  Falls back to treating the entire
        response as a single item's content when no JSON array is found.

        Args:
            raw: Raw string returned by the NLM.
            scene: Scene for fallback item construction.
            content_type: Content type for fallback item construction.

        Returns:
            List of :class:`ContentItem` objects (may be a single-element
            list when JSON parsing fails).
        """
        # Try to extract a JSON array from the response.
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            json_str = raw[start : end + 1]
            try:
                raw_items = json.loads(json_str)
            except json.JSONDecodeError:
                raw_items = None
        else:
            raw_items = None

        if isinstance(raw_items, list):
            items: List[ContentItem] = []
            for obj in raw_items:
                if not isinstance(obj, dict):
                    continue
                tags: List[str] = obj.get("tags") or []
                adult_cats: List[str] = obj.get("adult_categories") or []
                # Ensure canonical tags are present.
                if f"scene:{scene}" not in tags:
                    tags.append(f"scene:{scene}")
                if f"type:{content_type}" not in tags:
                    tags.append(f"type:{content_type}")
                raw_intensity = obj.get("intensity", 2)
                try:
                    parsed_intensity = int(raw_intensity)
                except (TypeError, ValueError):
                    parsed_intensity = 2
                if f"intensity:{parsed_intensity}" not in tags:
                    tags.append(f"intensity:{parsed_intensity}")
                items.append(
                    ContentItem(
                        id=str(uuid.uuid4()),
                        title=obj.get("title", f"Generated {content_type}"),
                        content=obj.get("content", ""),
                        scene=scene,
                        content_type=content_type,
                        intensity=parsed_intensity,
                        adult_categories=adult_cats,
                        tags=tags,
                    )
                )
            return items

        # Fallback: treat whole response as one item.
        logger.debug("NLM response not JSON-parseable; wrapping as single item")
        fallback_tags = [
            f"scene:{scene}",
            f"type:{content_type}",
            "intensity:2",
            "source:nlm_fallback",
        ]
        return [
            ContentItem(
                id=str(uuid.uuid4()),
                title=f"Generated {content_type} for {scene}",
                content=raw.strip(),
                scene=scene,
                content_type=content_type,
                intensity=2,
                adult_categories=[],
                tags=fallback_tags,
            )
        ]

    def _maybe_schedule_refill(
        self,
        scene: str,
        content_type: str,
        pool: ContentPool,
    ) -> None:
        """Schedule a background NLM refill if the pool is depleted.

        Ensures only one refill per *(scene, content_type)* pair is active
        at any time.  The worker thread clears the in-progress flag when
        finished, even on error.

        Args:
            scene: Scene identifier.
            content_type: Content type.
            pool: The pool object to inspect and refill.
        """
        key: _PoolKey = (scene, content_type)
        with self._lock:
            if not pool.is_depleted():
                return
            if key in self._refills_in_progress:
                return
            self._refills_in_progress.add(key)

        logger.info(
            "Pool %s/%s depleted (%d available) – scheduling background refill",
            scene,
            content_type,
            pool.available_count(),
        )

        def _worker() -> None:
            try:
                self.refill_pool(scene, content_type)
            except Exception as exc:
                logger.warning("Background refill failed for %s/%s: %s", scene, content_type, exc)
            finally:
                with self._lock:
                    self._refills_in_progress.discard(key)

        thread = threading.Thread(
            target=_worker,
            name=f"content-refill-{scene}-{content_type}",
            daemon=True,
        )
        thread.start()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[ContentEngine] = None
_engine_lock = threading.Lock()


def get_content_engine(nexus_client=None) -> ContentEngine:
    """Return the global :class:`ContentEngine` singleton.

    Thread-safe.  The singleton is created on first call.  Supplying
    *nexus_client* on subsequent calls has no effect (the existing
    singleton is returned as-is).

    Args:
        nexus_client: Optional Nexus client override for the initial
            creation (useful in tests).

    Returns:
        The singleton :class:`ContentEngine` instance.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ContentEngine(nexus_client=nexus_client)
    return _engine_instance
