"""NLM Content Generator — proactively seeds scene content pools and Director beat instructions.

Uses the Nexus NLM (NotebookLM / Gemini) pipeline to generate scene-specific
dialogue, events, quests, and narrative beat instructions.  These are stored
in Nexus so they are immediately available to the ContentEngine pool system
and the SceneDirector's Nexus-first instruction lookup.

Typical use::

    from engine.content.nlm_generator import get_nlm_generator
    gen = get_nlm_generator()
    gen.seed_scene("tavern", intensity=2)   # fills all pools + beat instructions
    gen.seed_all_scenes()                   # iterates every configured scene

The generator is integrated with the scheduler daemon which calls
``seed_all_scenes`` once every 6 hours (content-refresh task).
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scenes and content types to generate for
# ---------------------------------------------------------------------------

#: Scenes that the generator will seed when ``seed_all_scenes()`` is called.
GENERATOR_SCENES: List[str] = [
    "bedroom",
    "casino",
    "lounge",
    "tavern",
    "heist",
    "gallery",
    "arena",
    "neoncity",
    "realm",
]

#: Content types generated per scene (subset of ContentEngine.CONTENT_TYPES).
_CONTENT_TYPES_PER_SCENE: Dict[str, List[str]] = {
    "bedroom":  ["scenario", "dialogue", "arc"],
    "casino":   ["event", "scenario", "dialogue"],
    "lounge":   ["dialogue", "event", "lore"],
    "tavern":   ["quest", "event", "dialogue", "lore"],
    "heist":    ["scenario", "arc", "event"],
    "gallery":  ["lore", "event", "scenario"],
    "arena":    ["event", "fighter", "scenario"],
    "neoncity": ["event", "world_event", "lore"],
    "realm":    ["quest", "arc", "lore"],
}

#: Instruction generation prompt sent to Nexus/NLM.
_BEAT_INSTR_PROMPT = (
    "Write {count} unique director beat instructions for the '{scene}' scene, "
    "specifically for a '{beat_type}' beat.  The scene is an adult-themed dark-gritty "
    "environment (violence, sex, gambling, horror are allowed).  Each instruction "
    "must be 1–3 sentences directing the AI character on what to do or say next.  "
    "Return a JSON array of strings only, no extra text."
)

#: Dialogue pool generation prompt.
_DIALOGUE_PROMPT = (
    "Generate {count} adult-themed dialogue starters for a character in the '{scene}' "
    "scene at intensity level {intensity} (0=mild, 3=explicit).  "
    "Return a JSON array of short strings (one turn each), no extra text."
)


class NLMContentGenerator:
    """Orchestrates NLM-powered content generation for all CosySim scenes.

    Attributes:
        _lock: Reentrant lock protecting pool generation from concurrent calls.
    """

    def __init__(self) -> None:
        self._lock: threading.RLock = threading.RLock()
        self._nexus: Optional[Any] = None  # lazy-loaded NexusClient

    # ── Private helpers ───────────────────────────────────────────────────

    def _get_nexus(self) -> Any:
        """Return the NexusClient, creating it lazily."""
        if self._nexus is None:
            from engine.nexus.client import get_nexus_client  # noqa: PLC0415
            self._nexus = get_nexus_client()
        return self._nexus

    def _ask_nlm(self, prompt: str) -> str:
        """Ask Nexus/NLM and return the raw answer string."""
        nexus = self._get_nexus()
        try:
            response = nexus.ask(prompt, depth="auto")
            if isinstance(response, dict):
                return response.get("answer", "")
            return str(response)
        except Exception as exc:
            logger.warning("NLM ask failed: %s", exc)
            return ""

    def _parse_json_array(self, raw: str) -> List[str]:
        """Extract the first JSON array from *raw*."""
        if not raw:
            return []
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(raw[start:end])
            return [str(item) for item in data if item]
        except json.JSONDecodeError:
            return []

    def _store_nexus(
        self,
        title: str,
        content: str,
        category: str,
        tags: List[str],
    ) -> Optional[str]:
        """Store an entry in Nexus and return its ID."""
        nexus = self._get_nexus()
        try:
            return nexus.add_entry(
                title=title,
                content=content,
                content_type="note",
                category=category,
                tags=tags,
            )
        except Exception as exc:
            logger.debug("Nexus store failed (%s): %s", title, exc)
            return None

    # ── Public API ────────────────────────────────────────────────────────

    def generate_beat_instructions(
        self,
        scene: str,
        beat_type: str,
        count: int = 5,
    ) -> int:
        """Generate and store Nexus director beat instructions.

        The SceneDirector's ``_get_instruction`` searches Nexus for
        ``"{scene} {beat_type} director beat"`` — entries stored here
        will be found and used instead of the generic template.

        Args:
            scene: Scene identifier (e.g. ``"tavern"``).
            beat_type: Beat type value (e.g. ``"escalation"``).
            count: Number of instructions to generate.

        Returns:
            Number of instructions successfully stored.
        """
        prompt = _BEAT_INSTR_PROMPT.format(
            count=count, scene=scene, beat_type=beat_type
        )
        logger.info(
            "Generating %d %s/%s director beat instructions via NLM",
            count, scene, beat_type,
        )
        raw = self._ask_nlm(prompt)
        instructions = self._parse_json_array(raw)
        if not instructions:
            logger.warning(
                "NLM returned no instructions for %s/%s", scene, beat_type
            )
            return 0

        stored = 0
        for instr in instructions[:count]:
            title = f"{scene} {beat_type} director beat"
            tags = [
                f"scene:{scene}",
                f"beat_type:{beat_type}",
                "director_beat",
                "generated",
            ]
            entry_id = self._store_nexus(title, instr, "content", tags)
            if entry_id:
                stored += 1

        logger.info("Stored %d/%d %s/%s beat instructions", stored, count, scene, beat_type)
        return stored

    def generate_dialogue_pool(
        self,
        scene: str,
        count: int = 10,
        intensity: int = 2,
    ) -> int:
        """Generate dialogue starters and add them to the ContentEngine pool.

        Args:
            scene: Scene identifier.
            count: Number of dialogue starters to generate.
            intensity: Narrative intensity level (0–3).

        Returns:
            Number of items added to the pool.
        """
        prompt = _DIALOGUE_PROMPT.format(count=count, scene=scene, intensity=intensity)
        logger.info(
            "Generating %d dialogue starters for scene '%s' (intensity=%d)",
            count, scene, intensity,
        )
        raw = self._ask_nlm(prompt)
        lines = self._parse_json_array(raw)
        if not lines:
            logger.warning("NLM returned no dialogue starters for %s", scene)
            return 0

        try:
            from engine.content.content_engine import get_content_engine  # noqa: PLC0415
            engine = get_content_engine()
            added = 0
            for line in lines[:count]:
                engine.add_to_pool(
                    scene=scene,
                    pool="dialogue",
                    content=line,
                    intensity=intensity,
                    tags=[f"scene:{scene}", "type:dialogue", f"intensity:{intensity}", "nlm_generated"],
                )
                added += 1
            logger.info("Added %d dialogue items to pool for '%s'", added, scene)
            return added
        except Exception as exc:
            logger.warning("ContentEngine add_to_pool failed: %s", exc)
            return 0

    def seed_scene(
        self,
        scene: str,
        intensity: int = 2,
        beat_count: int = 3,
        content_count: int = 5,
    ) -> Dict[str, int]:
        """Fully seed a scene: beat instructions for all BeatTypes + content pools.

        Args:
            scene: Scene identifier.
            intensity: Content intensity level for dialogue pools.
            beat_count: Beat instructions generated per BeatType.
            content_count: Content items generated per content type.

        Returns:
            Dict with ``"beats"`` and ``"content"`` counts of items stored.
        """
        from engine.director.scene_director import BeatType  # noqa: PLC0415

        with self._lock:
            beats_stored = 0
            content_stored = 0

            logger.info("Seeding scene '%s' via NLM (intensity=%d)", scene, intensity)

            # Generate director beat instructions for all BeatTypes
            for bt in BeatType:
                try:
                    n = self.generate_beat_instructions(scene, bt.value, count=beat_count)
                    beats_stored += n
                except Exception as exc:
                    logger.warning("Beat generation failed for %s/%s: %s", scene, bt.value, exc)

            # Fill content pools
            content_types = _CONTENT_TYPES_PER_SCENE.get(scene, ["dialogue", "event"])
            try:
                from engine.content.content_engine import get_content_engine  # noqa: PLC0415
                engine = get_content_engine()
                for ctype in content_types:
                    try:
                        n = engine.refill_pool(scene, ctype, count=content_count)
                        content_stored += n
                    except Exception as exc:
                        logger.warning("refill_pool failed for %s/%s: %s", scene, ctype, exc)
            except Exception as exc:
                logger.warning("ContentEngine unavailable: %s", exc)

            return {"beats": beats_stored, "content": content_stored}

    def seed_director_beats(self, scene: str, beat_count: int = 5) -> int:
        """Generate director beat instructions for all BeatTypes for a scene.

        This is a lighter seed that only fills the Director instruction cache
        in Nexus, without touching content pools.

        Args:
            scene: Scene identifier.
            beat_count: Instructions per BeatType.

        Returns:
            Total instructions stored across all BeatTypes.
        """
        from engine.director.scene_director import BeatType  # noqa: PLC0415

        total = 0
        with self._lock:
            for bt in BeatType:
                try:
                    total += self.generate_beat_instructions(scene, bt.value, count=beat_count)
                except Exception as exc:
                    logger.warning("Beat gen failed %s/%s: %s", scene, bt.value, exc)
        return total

    def seed_all_scenes(
        self,
        intensity: int = 2,
        beat_count: int = 3,
        content_count: int = 5,
    ) -> Dict[str, Dict[str, int]]:
        """Seed all configured scenes.

        Args:
            intensity: Default intensity level (0–3).
            beat_count: Beat instructions per BeatType per scene.
            content_count: Content items per type per scene.

        Returns:
            Nested dict keyed by scene name → ``{"beats": N, "content": M}``.
        """
        results: Dict[str, Dict[str, int]] = {}
        for scene in GENERATOR_SCENES:
            logger.info("NLMGenerator: seeding scene '%s'…", scene)
            results[scene] = self.seed_scene(
                scene,
                intensity=intensity,
                beat_count=beat_count,
                content_count=content_count,
            )
        totals = {
            "beats": sum(v["beats"] for v in results.values()),
            "content": sum(v["content"] for v in results.values()),
        }
        logger.info(
            "NLMGenerator: seeded %d scenes — %d beats, %d content items",
            len(results), totals["beats"], totals["content"],
        )
        results["_totals"] = totals
        return results


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_GENERATOR_INSTANCE: Optional[NLMContentGenerator] = None
_GENERATOR_LOCK: threading.Lock = threading.Lock()


def get_nlm_generator() -> NLMContentGenerator:
    """Return the process-wide :class:`NLMContentGenerator` singleton."""
    global _GENERATOR_INSTANCE
    if _GENERATOR_INSTANCE is None:
        with _GENERATOR_LOCK:
            if _GENERATOR_INSTANCE is None:
                _GENERATOR_INSTANCE = NLMContentGenerator()
    return _GENERATOR_INSTANCE
