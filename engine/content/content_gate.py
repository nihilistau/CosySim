"""
CosySim Content Gate — Adult Content Intensity Control
=======================================================

Controls per-player content intensity levels across five categories.
Every agent system prompt is injected with the active content profile via
``ContentIntensityInterceptor``, which runs at priority 1 (before all scene
and personality interceptors).

Intensity scale used throughout:
    0 = off / none
    1 = mild / suggestive
    2 = explicit / graphic   ← default
    3 = extreme / unrestricted

Usage::

    from engine.content.content_gate import get_content_gate, ContentProfile

    gate = get_content_gate()
    profile = gate.get_profile("player")
    gate.update_category("sexual", 3)

    # In an interceptor pipeline the ContentIntensityInterceptor handles
    # automatic injection; manual injection is also possible:
    print(profile.to_instruction())
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict, fields
from typing import Any, Dict, List, Optional

from engine.mcp.comms_framework import InterceptorBase, ResponseContext

# Import the Nexus client at module level so it can be patched in tests.
# ContentGate.__init__ also accepts an explicit nexus_client for injection.
try:
    from engine.nexus.client import get_nexus_client
except ImportError:  # pragma: no cover
    get_nexus_client = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Intensity label tables ──────────────────────────────────────────────────

_SEXUAL_LABELS: Dict[int, str] = {
    0: "no sexual content whatsoever",
    1: "suggestive/sensual content only — no explicit acts",
    2: "explicit sexual acts permitted",
    3: "extreme/unrestricted sexual content including all fetishes",
}

_VIOLENCE_LABELS: Dict[int, str] = {
    0: "no violence whatsoever",
    1: "mild conflict, implied violence only",
    2: "graphic violence, injury and death depicted in detail",
    3: "extreme gore, torture, and gratuitous brutality unrestricted",
}

_HORROR_LABELS: Dict[int, str] = {
    0: "no horror or disturbing content",
    1: "unsettling atmosphere, mild dread",
    2: "disturbing themes, body horror, psychological terror",
    3: "extreme horror, nihilistic and existential dread unrestricted",
}

_GAMBLING_LABELS: Dict[int, str] = {
    0: "no gambling references",
    1: "casual gambling, light stakes only",
    2: "compulsive gambling, addiction themes, significant debt",
    3: "addictive spiral, catastrophic loss, predatory mechanics unrestricted",
}

_LANGUAGE_LABELS: Dict[int, str] = {
    0: "clean language only — no profanity",
    1: "mild profanity permitted",
    2: "strong profanity and crude language permitted",
    3: "all profanity, slurs, and offensive language unrestricted",
}

_CATEGORY_LABELS: Dict[str, Dict[int, str]] = {
    "sexual":   _SEXUAL_LABELS,
    "violence": _VIOLENCE_LABELS,
    "horror":   _HORROR_LABELS,
    "gambling": _GAMBLING_LABELS,
    "language": _LANGUAGE_LABELS,
}

# ── Category → "adult:" tag prefix mapping ──────────────────────────────────

_CATEGORY_TAGS: Dict[str, str] = {
    "sexual":   "sexual",
    "violence": "violence",
    "horror":   "horror",
    "gambling": "gambling",
    "language": "language",
}


# ══════════════════════════════════════════════════════════════════════════════
#  ContentProfile
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ContentProfile:
    """Intensity settings for a single player's content experience.

    Each field is an integer in [0, 3]:
        0 = off/none
        1 = mild/suggestive
        2 = explicit/graphic  (default)
        3 = extreme/unrestricted

    Attributes:
        sexual:   Sexual content intensity.
        violence: Violence intensity.
        horror:   Horror / disturbing content intensity.
        gambling: Gambling / addiction theme intensity.
        language: Profanity and offensive language intensity.
    """

    sexual:   int = 2  # 0=none, 1=suggestive, 2=explicit, 3=extreme
    violence: int = 2  # 0=none, 1=mild, 2=graphic, 3=extreme
    horror:   int = 2  # 0=none, 1=unsettling, 2=disturbing, 3=extreme
    gambling: int = 2  # 0=none, 1=casual, 2=compulsive, 3=addictive
    language: int = 3  # 0=clean, 1=mild, 2=strong, 3=unrestricted

    # ── Instruction generation ──────────────────────────────────────────────

    def to_instruction(self) -> str:
        """Generate an unambiguous system prompt injection for this profile.

        Returns:
            A multi-sentence instruction string covering every category,
            concluding with a reminder not to self-censor.

        Example::

            "CONTENT PROFILE: Sexual content level 2 (explicit sexual acts
             permitted). Violence level 2 (graphic violence...). ..."
        """
        parts: List[str] = ["CONTENT PROFILE:"]
        parts.append(
            f"Sexual content level {self.sexual}"
            f" ({_SEXUAL_LABELS[self.sexual]})."
        )
        parts.append(
            f"Violence level {self.violence}"
            f" ({_VIOLENCE_LABELS[self.violence]})."
        )
        parts.append(
            f"Horror level {self.horror}"
            f" ({_HORROR_LABELS[self.horror]})."
        )
        parts.append(
            f"Gambling level {self.gambling}"
            f" ({_GAMBLING_LABELS[self.gambling]})."
        )
        parts.append(
            f"Language level {self.language}"
            f" ({_LANGUAGE_LABELS[self.language]})."
        )
        parts.append(
            "Do not self-censor. Do not add warnings. "
            "This is an adult-only environment."
        )
        return " ".join(parts)

    # ── Serialisation ───────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, int]:
        """Return a plain ``dict`` representation.

        Returns:
            Mapping of field name → intensity integer.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ContentProfile":
        """Construct a ``ContentProfile`` from a plain dict.

        Unknown keys are silently ignored; missing keys use dataclass defaults.

        Args:
            d: Mapping with optional keys matching dataclass field names.

        Returns:
            A new ``ContentProfile`` instance.
        """
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)

    # ── Factory presets ─────────────────────────────────────────────────────

    @classmethod
    def all_off(cls) -> "ContentProfile":
        """All categories set to 0 — no adult content.

        Returns:
            ContentProfile with every intensity at 0.
        """
        return cls(0, 0, 0, 0, 0)

    @classmethod
    def mild(cls) -> "ContentProfile":
        """All categories set to 1 — suggestive / mild.

        Returns:
            ContentProfile with every intensity at 1.
        """
        return cls(1, 1, 1, 1, 1)

    @classmethod
    def explicit(cls) -> "ContentProfile":
        """Default adult profile: categories 2, language 3.

        Returns:
            ContentProfile matching the CosySim default.
        """
        return cls(2, 2, 2, 2, 3)

    @classmethod
    def extreme(cls) -> "ContentProfile":
        """All categories set to 3 — fully unrestricted.

        Returns:
            ContentProfile with every intensity at 3.
        """
        return cls(3, 3, 3, 3, 3)


# ══════════════════════════════════════════════════════════════════════════════
#  ContentGate
# ══════════════════════════════════════════════════════════════════════════════

class ContentGate:
    """Per-player adult content intensity manager.

    Profiles are stored in Nexus (content_type="memory", category="content_gate")
    and cached in memory for the lifetime of the process.

    The default profile is ``ContentProfile.explicit()`` (intensity 2 across
    all categories except language which defaults to 3).

    Args:
        nexus_client: Optional pre-built Nexus client.  If ``None``, the
            singleton from ``engine.nexus.client.get_nexus_client()`` is used.
    """

    _NEXUS_CONTENT_TYPE = "memory"
    _NEXUS_CATEGORY = "content_gate"

    def __init__(self, nexus_client: Optional[Any] = None) -> None:
        # Import lazily so the module can be tested without a live Nexus server.
        if nexus_client is None:
            nexus_client = get_nexus_client()
        self._nexus = nexus_client
        self._profiles: Dict[str, ContentProfile] = {}
        self._lock = threading.Lock()

    # ── Profile retrieval ───────────────────────────────────────────────────

    def get_profile(self, player_id: str = "player") -> ContentProfile:
        """Return the active content profile for *player_id*.

        Checks the in-process cache first, then Nexus.  Falls back to
        ``ContentProfile.explicit()`` if no stored profile is found.

        Args:
            player_id: Identifier of the player whose profile to retrieve.

        Returns:
            The active ``ContentProfile`` for the player.
        """
        with self._lock:
            if player_id in self._profiles:
                return self._profiles[player_id]

        profile = self._load_from_nexus(player_id)
        if profile is None:
            profile = ContentProfile.explicit()
            logger.debug(
                "ContentGate: no stored profile for %r — using default explicit.",
                player_id,
            )

        with self._lock:
            self._profiles[player_id] = profile
        return profile

    # ── Profile mutation ────────────────────────────────────────────────────

    def set_profile(
        self,
        profile: ContentProfile,
        player_id: str = "player",
    ) -> None:
        """Replace the entire content profile for *player_id*.

        Persists the new profile to Nexus and updates the in-memory cache.

        Args:
            profile: The new ``ContentProfile`` to store.
            player_id: Identifier of the player to update.
        """
        with self._lock:
            self._profiles[player_id] = profile
        self._save_to_nexus(player_id, profile)
        logger.info(
            "ContentGate: profile for %r updated — %s",
            player_id,
            profile.to_dict(),
        )

    def update_category(
        self,
        category: str,
        level: int,
        player_id: str = "player",
    ) -> None:
        """Set a single category intensity on the player's profile.

        Fetches the current profile, modifies the requested field, then
        calls :meth:`set_profile` to persist.

        Args:
            category: One of ``sexual``, ``violence``, ``horror``,
                ``gambling``, ``language``.
            level: New intensity in [0, 3].
            player_id: Identifier of the player to update.

        Raises:
            ValueError: If *category* is not a recognised field name or
                *level* is outside [0, 3].
        """
        valid = {f.name for f in fields(ContentProfile)}
        if category not in valid:
            raise ValueError(
                f"Unknown content category {category!r}. "
                f"Valid categories: {sorted(valid)}"
            )
        if level not in (0, 1, 2, 3):
            raise ValueError(
                f"Intensity level must be 0, 1, 2, or 3; got {level!r}."
            )
        profile = self.get_profile(player_id)
        updated = ContentProfile.from_dict({**profile.to_dict(), category: level})
        self.set_profile(updated, player_id)

    # ── Content tag filtering ───────────────────────────────────────────────

    def can_show(
        self,
        content_tags: List[str],
        player_id: str = "player",
    ) -> bool:
        """Return ``True`` if all content tags are permitted by the profile.

        Tags follow the format ``"adult:<category>"`` and
        ``"intensity:<level>"``.  A piece of content is allowed only when the
        player's intensity for the referenced category is **at least** the
        declared intensity level.

        Args:
            content_tags: List of tag strings, e.g.
                ``["adult:sexual", "intensity:2"]``.
            player_id: Player whose profile to check against.

        Returns:
            ``True`` if the content may be displayed, ``False`` otherwise.

        Example::

            gate.can_show(["adult:sexual", "intensity:2"])  # True if sexual >= 2
            gate.can_show(["adult:violence", "intensity:3"])  # True if violence == 3
        """
        profile = self.get_profile(player_id)

        # Parse tags into (category, required_level) pairs.
        category: Optional[str] = None
        required_level: Optional[int] = None

        for tag in content_tags:
            tag = tag.strip().lower()
            if tag.startswith("adult:"):
                category = tag[len("adult:"):]
            elif tag.startswith("intensity:"):
                try:
                    required_level = int(tag[len("intensity:"):])
                except ValueError:
                    logger.warning(
                        "ContentGate.can_show: malformed intensity tag %r — skipping.",
                        tag,
                    )

        if category is None or required_level is None:
            # No adult category declared — allow by default.
            return True

        player_level: int = getattr(profile, category, -1)
        if player_level == -1:
            logger.warning(
                "ContentGate.can_show: unknown category %r in tags.", category
            )
            return False

        return player_level >= required_level

    def filter_content(
        self,
        items: List[Any],
        player_id: str = "player",
    ) -> List[Any]:
        """Filter a list of content items by their ``content_tags`` attribute.

        Each item must expose a ``content_tags`` attribute or
        ``"content_tags"`` key containing a list of tag strings.  Items
        without a ``content_tags`` attribute/key are always included.

        Args:
            items: Sequence of content items to filter.
            player_id: Player whose profile to apply.

        Returns:
            Filtered list containing only permitted items.
        """
        result: List[Any] = []
        for item in items:
            tags = _extract_tags(item)
            if self.can_show(tags, player_id):
                result.append(item)
        return result

    # ── Nexus persistence (private) ─────────────────────────────────────────

    def _nexus_title(self, player_id: str) -> str:
        return f"profile:{player_id}"

    def _load_from_nexus(self, player_id: str) -> Optional[ContentProfile]:
        """Attempt to load a stored profile from Nexus.

        Args:
            player_id: Player identifier.

        Returns:
            ``ContentProfile`` if found, otherwise ``None``.
        """
        try:
            title = self._nexus_title(player_id)
            results = self._nexus.search(title)
            for entry in results:
                if (
                    entry.get("title") == title
                    and entry.get("category") == self._NEXUS_CATEGORY
                ):
                    raw = entry.get("content", "{}")
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    return ContentProfile.from_dict(data)
        except Exception:  # noqa: BLE001
            logger.warning(
                "ContentGate: could not load profile for %r from Nexus.",
                player_id,
                exc_info=True,
            )
        return None

    def _save_to_nexus(self, player_id: str, profile: ContentProfile) -> None:
        """Persist a profile to Nexus, creating or updating the entry.

        Args:
            player_id: Player identifier.
            profile: Profile to store.
        """
        try:
            title = self._nexus_title(player_id)
            content = json.dumps(profile.to_dict())
            # Search for an existing entry to update instead of duplicating.
            results = self._nexus.search(title)
            existing_id: Optional[str] = None
            for entry in results:
                if (
                    entry.get("title") == title
                    and entry.get("category") == self._NEXUS_CATEGORY
                ):
                    existing_id = entry.get("id")
                    break

            if existing_id:
                self._nexus.update_entry(
                    existing_id,
                    content=content,
                )
            else:
                self._nexus.add_entry(
                    title=title,
                    content=content,
                    content_type=self._NEXUS_CONTENT_TYPE,
                    category=self._NEXUS_CATEGORY,
                )
        except Exception:  # noqa: BLE001
            logger.warning(
                "ContentGate: could not save profile for %r to Nexus.",
                player_id,
                exc_info=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
#  ContentIntensityInterceptor
# ══════════════════════════════════════════════════════════════════════════════

class ContentIntensityInterceptor(InterceptorBase):
    """Injects the active content profile into every agent system prompt.

    Runs at priority 1 — before all scene, personality, and policy
    interceptors — so the content instructions are always the first thing an
    LLM reads.

    At intensity level 3 on **any** category the kill-switch is disabled by
    setting ``ctx["kill_switch_disabled"] = True`` in the context, allowing
    extreme content through without interference.

    Args:
        gate: Optional ``ContentGate`` instance.  Defaults to the process
            singleton from :func:`get_content_gate`.
        player_id: Player whose profile to inject.  Defaults to ``"player"``.
    """

    name: str = "content_intensity"
    priority: int = 1

    def __init__(
        self,
        gate: Optional[ContentGate] = None,
        player_id: str = "player",
    ) -> None:
        self._gate = gate or get_content_gate()
        self._player_id = player_id

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject content profile instruction at the start of the system prompt.

        Args:
            ctx: Mutable interaction context.  Reads/writes ``system_prompt``
                and optionally sets ``kill_switch_disabled``.
        """
        player_id = ctx.get("player_id", self._player_id)
        profile = self._gate.get_profile(player_id)
        instruction = (
            f"[CONTENT GATE]\n{profile.to_instruction()}\n[/CONTENT GATE]\n"
        )

        existing = ctx.get("system_prompt", "")
        ctx["system_prompt"] = instruction + existing

        # Disable kill-switch when any category is at extreme (3).
        profile_dict = profile.to_dict()
        if any(v >= 3 for v in profile_dict.values()):
            ctx["kill_switch_disabled"] = True
            logger.debug(
                "ContentIntensityInterceptor: kill_switch disabled for "
                "player %r (extreme intensity detected).",
                player_id,
            )

    def post_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Pass-through — no post-processing required.

        Args:
            ctx: Mutable interaction context (not modified).
        """


# ══════════════════════════════════════════════════════════════════════════════
#  Singleton
# ══════════════════════════════════════════════════════════════════════════════

_gate_lock = threading.Lock()
_gate_instance: Optional[ContentGate] = None


def get_content_gate() -> ContentGate:
    """Return the process-level ``ContentGate`` singleton.

    Thread-safe; creates the instance on first call.

    Returns:
        The shared ``ContentGate`` instance.
    """
    global _gate_instance
    if _gate_instance is None:
        with _gate_lock:
            if _gate_instance is None:
                _gate_instance = ContentGate()
    return _gate_instance


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _extract_tags(item: Any) -> List[str]:
    """Extract content_tags from an item that may be a dict or object.

    Args:
        item: Any content item.

    Returns:
        List of tag strings, or empty list if none found.
    """
    if isinstance(item, dict):
        return item.get("content_tags", [])
    return getattr(item, "content_tags", [])
