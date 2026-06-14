"""
CosySim Character Registry
===========================

Central, MCP-accessible store for every character's **profile**, **personality**,
**assigned skills**, **behavioral state**, and **runtime attributes**.

Why this exists
---------------
Before this module, character data was scattered across the database,
``scene_state.py`` stats, Jinja templates, and hard-coded scene constants.
The registry collects everything into one thread-safe singleton so that:

* Any MCP tool can ask "what's Aria's eye color?" in one call.
* Any interceptor can read a character's personality curve before building
  the system prompt.
* The Director can change a character's mood, focus, restrictions, or granted
  skills at runtime — and that change is immediately visible to every governor.
* Different characters genuinely have different capabilities (skills).

Architecture
------------
``CharacterProfile``     — immutable identity (name, age, appearance, backstory,
                           personality vector, voice style)
``CharacterState``       — mutable runtime state (mood, focus, restrictions,
                           current_role, energy, inhibition)
``SkillEntry``           — a named skill with metadata (type, params, enabled)
``CharacterRecord``      — combines profile + state + skills into one object
``CharacterRegistry``    — singleton manager; thread-safe read/write for all of
                           the above.

It deliberately does NOT own clothing or arousal stats — those stay in
``scene_state.SceneStateManager`` so the two concerns stay decoupled.

Skill types (``SkillEntry.skill_type``)
---------------------------------------
  memory_recall    — RAG-backed consistent memory
  speech_enhance   — Stylistic voice transformation
  dialog_choices   — Guided response options from DialogSystem
  web_lookup       — Realtime information via web search
  image_gen        — ComfyUI image generation
  mood_influence   — Passive mood drift / aura effect on nearby characters
  personality_lock — Enforce personality constraints at post-call
  custom           — Arbitrary, payload-defined behaviour

Quick start::

    from engine.mcp.character_registry import get_character_registry

    reg = get_character_registry()

    # Register a new character
    reg.register("aria", name="Aria", age=26,
                 appearance={"hair": "brunette", "eyes": "green", "height": "5'7"},
                 personality={"warmth": 0.9, "curiosity": 0.8, "assertiveness": 0.5},
                 backstory="A creative writer who loves late-night conversations.",
                 voice_style="warm, playful, drops into teasing easily")

    # Grant skills
    reg.assign_skill("aria", "memory_recall",
                     skill_type="memory_recall",
                     params={"top_k": 6, "min_score": 0.35})
    reg.assign_skill("aria", "speech_enhance",
                     skill_type="speech_enhance",
                     params={"default_style": "playful"})

    # Query attributes
    eyes = reg.get_attribute("aria", "eyes")               # "green"
    personality = reg.get_profile("aria").personality      # dict

    # Update state
    reg.set_state("aria", mood="excited", mood_intensity=0.8)
    reg.set_state("aria", focus="user_intimacy")
    mood = reg.get_state("aria")["mood"]                   # "excited"

    # Restrict / unrestrict behaviour
    reg.add_restriction("aria", "refuse_explicit")
    reg.remove_restriction("aria", "refuse_explicit")

    # Check granted skills
    skills = reg.get_skills("aria")                        # list[SkillEntry]
    has_mem = reg.has_skill("aria", "memory_recall")       # True
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CharacterProfile:
    """
    Immutable identity data for a character.

    Fields
    ------
    character_id    — unique string key (e.g. "aria", "lena")
    name            — display name
    age             — integer age
    appearance      — dict of physical descriptors: hair, eyes, height, body, etc.
    personality     — dict of trait scores 0.0-1.0:
                      warmth, curiosity, assertiveness, playfulness, empathy,
                      dominance, vulnerability, wit, sensuality, openness
    backstory       — a paragraph describing who they are before this session
    voice_style     — natural language description of how they speak
    pronouns        — {"subject": "she", "object": "her", "possessive": "her"}
    scene_roles     — which scenes this character is active in
    created_at      — unix timestamp
    """
    character_id:  str
    name:          str
    age:           int                        = 22
    appearance:    Dict[str, Any]             = field(default_factory=dict)
    personality:   Dict[str, float]           = field(default_factory=dict)
    backstory:     str                        = ""
    voice_style:   str                        = "natural, conversational"
    pronouns:      Dict[str, str]             = field(default_factory=lambda: {
                        "subject": "she", "object": "her", "possessive": "her"
                    })
    scene_roles:   List[str]                  = field(default_factory=list)
    voice_id:      str                        = ""   # maps to voices.yaml key (e.g. "lola", "companion_f")
    created_at:    float                      = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "character_id": self.character_id,
            "name":         self.name,
            "age":          self.age,
            "appearance":   self.appearance,
            "personality":  self.personality,
            "backstory":    self.backstory,
            "voice_style":  self.voice_style,
            "pronouns":     self.pronouns,
            "scene_roles":  self.scene_roles,
        }

    def get_attribute(self, key: str, default: Any = None) -> Any:
        """Flat attribute lookup: checks appearance, then top-level fields."""
        if key in self.appearance:
            return self.appearance[key]
        return getattr(self, key, default)


@dataclass
class CharacterState:
    """
    Mutable runtime state — changes during a session without touching profile.

    Fields
    ------
    mood            — current emotional label: happy, sad, excited, nervous, etc.
    mood_intensity  — 0.0-1.0 strength of the current mood
    focus           — what the character is focused on right now (free string)
    current_role    — active role in the scene: flirt, confessor, aggressor, etc.
    energy          — 0-100 physical/mental energy
    inhibition      — 0-100 (0=fully uninhibited, 100=highly guarded)
    restrictions    — set of active behavioural restrictions (MCP-enforced)
    flags           — arbitrary key→value runtime flags
    last_updated    — unix timestamp of last modification
    """
    mood:           str             = "neutral"
    mood_intensity: float           = 0.5
    focus:          str             = ""
    current_role:   str             = "default"
    energy:         float           = 80.0
    inhibition:     float           = 30.0
    restrictions:   Set[str]        = field(default_factory=set)
    flags:          Dict[str, Any]  = field(default_factory=dict)
    last_updated:   float           = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "mood":           self.mood,
            "mood_intensity": self.mood_intensity,
            "focus":          self.focus,
            "current_role":   self.current_role,
            "energy":         self.energy,
            "inhibition":     self.inhibition,
            "restrictions":   sorted(self.restrictions),
            "flags":          self.flags,
            "last_updated":   self.last_updated,
        }


@dataclass
class SkillEntry:
    """
    One skill assigned to a character.

    Fields
    ------
    skill_id       — unique name within a character's skill set (e.g. "memory_recall")
    skill_type     — one of the registered skill types (see module docstring)
    label          — human-readable description shown to agent
    params         — dict of configuration for this skill instance
    enabled        — if False, skill is visible but not executed
    trigger        — "auto" | "optional" | "required" (same semantics as manifests)
    priority       — execution order among auto-triggered skills (lower = first)
    """
    skill_id:   str
    skill_type: str
    label:      str             = ""
    params:     Dict[str, Any]  = field(default_factory=dict)
    enabled:    bool            = True
    trigger:    str             = "optional"
    priority:   int             = 50

    def to_dict(self) -> Dict:
        return {
            "skill_id":   self.skill_id,
            "skill_type": self.skill_type,
            "label":      self.label or self.skill_id,
            "params":     self.params,
            "enabled":    self.enabled,
            "trigger":    self.trigger,
            "priority":   self.priority,
        }


@dataclass
class CharacterRecord:
    """Combines profile + state + skills into one record."""
    profile:  CharacterProfile
    state:    CharacterState              = field(default_factory=CharacterState)
    skills:   Dict[str, SkillEntry]       = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "profile": self.profile.to_dict(),
            "state":   self.state.to_dict(),
            "skills":  {k: v.to_dict() for k, v in self.skills.items()},
        }


# ══════════════════════════════════════════════════════════════════════
#  CHARACTER REGISTRY  (singleton)
# ══════════════════════════════════════════════════════════════════════

class CharacterRegistry:
    """
    Thread-safe singleton: the one authoritative store for ALL character
    data.  Every governor, interceptor, and scene can read and write from
    here — changes are immediately visible everywhere.

    Usage pattern
    -------------
    Always go through ``get_character_registry()`` — never instantiate
    directly.  The registry is populated at scene startup and can be
    refreshed from the database, a YAML config, or the Director API.
    """

    def __init__(self) -> None:
        self._lock:    threading.RLock        = threading.RLock()
        self._chars:   Dict[str, CharacterRecord] = {}

    # ── Registration ─────────────────────────────────────────────────

    def register(
        self,
        character_id: str,
        *,
        name:        str,
        age:         int                    = 22,
        appearance:  Optional[Dict]         = None,
        personality: Optional[Dict]         = None,
        backstory:   str                    = "",
        voice_style: str                    = "natural, conversational",
        pronouns:    Optional[Dict]         = None,
        scene_roles: Optional[List[str]]    = None,
    ) -> CharacterRecord:
        """
        Register a character.  Calling again with the same id replaces the
        profile but preserves existing state and skills.
        """
        with self._lock:
            profile = CharacterProfile(
                character_id = character_id,
                name         = name,
                age          = age,
                appearance   = appearance   or {},
                personality  = personality  or {},
                backstory    = backstory,
                voice_style  = voice_style,
                pronouns     = pronouns     or {"subject": "she", "object": "her", "possessive": "her"},
                scene_roles  = scene_roles  or [],
            )
            existing = self._chars.get(character_id)
            if existing:
                existing.profile = profile
                return existing
            record = CharacterRecord(profile=profile)
            self._chars[character_id] = record
            return record

    def ensure(self, character_id: str) -> CharacterRecord:
        """
        Return the record for character_id, creating a minimal stub if not yet
        registered.  Useful when the system encounters an unknown character mid-scene.
        """
        with self._lock:
            if character_id not in self._chars:
                self.register(character_id, name=character_id.replace("_", " ").title())
            return self._chars[character_id]

    # ── Profile queries ───────────────────────────────────────────────

    def get_profile(self, character_id: str) -> Optional[CharacterProfile]:
        """Return the character's profile, or None if not registered."""
        with self._lock:
            rec = self._chars.get(character_id)
            return rec.profile if rec else None

    def get_attribute(self, character_id: str, attribute: str, default: Any = None) -> Any:
        """
        Flat attribute lookup against a character's profile.
        Checks: appearance dict → direct profile fields → default.

        Examples::

            reg.get_attribute("aria", "eyes")       # "green"
            reg.get_attribute("aria", "age")         # 26
            reg.get_attribute("aria", "voice_style") # "playful..."
        """
        profile = self.get_profile(character_id)
        if profile is None:
            return default
        return profile.get_attribute(attribute, default)

    def list_characters(self, scene_role: Optional[str] = None) -> List[str]:
        """Return all registered character IDs, optionally filtered by scene role."""
        with self._lock:
            if scene_role is None:
                return list(self._chars.keys())
            return [
                cid for cid, rec in self._chars.items()
                if scene_role in rec.profile.scene_roles
            ]

    # ── State read/write ──────────────────────────────────────────────

    def get_state(self, character_id: str) -> Dict[str, Any]:
        """
        Return a snapshot dict of the character's current runtime state.
        Always returns a dict (even for unknown characters — returns defaults).
        """
        rec = self.ensure(character_id)
        return rec.state.to_dict()

    def set_state(self, character_id: str, **values) -> None:
        """
        Update one or more state fields.

        Known fields: mood, mood_intensity, focus, current_role, energy,
                      inhibition, flags (dict-merged).

        Unknown field names are stored in ``state.flags[key] = value``.
        """
        rec = self.ensure(character_id)
        with self._lock:
            state = rec.state
            known = {"mood", "mood_intensity", "focus", "current_role", "energy", "inhibition"}
            for k, v in values.items():
                if k in known:
                    setattr(state, k, v)
                elif k == "flags":
                    state.flags.update(v if isinstance(v, dict) else {k: v})
                else:
                    state.flags[k] = v
            state.last_updated = time.time()

    def add_restriction(self, character_id: str, restriction: str) -> None:
        """
        Add a named behavioural restriction (e.g. ``"refuse_explicit"``,
        ``"no_dominant_behaviour"``).  The PolicyEnforcerInterceptor and
        PersonalityGuardInterceptor read these.
        """
        rec = self.ensure(character_id)
        with self._lock:
            rec.state.restrictions.add(restriction)
            rec.state.last_updated = time.time()

    def remove_restriction(self, character_id: str, restriction: str) -> None:
        """Remove a named behavioural restriction."""
        rec = self.ensure(character_id)
        with self._lock:
            rec.state.restrictions.discard(restriction)
            rec.state.last_updated = time.time()

    def get_restrictions(self, character_id: str) -> Set[str]:
        """Return the current set of behavioural restrictions for a character."""
        rec = self.ensure(character_id)
        return set(rec.state.restrictions)

    # ── Skill management ──────────────────────────────────────────────

    def assign_skill(
        self,
        character_id: str,
        skill_id: str,
        skill_type: str,
        label: str = "",
        params: Optional[Dict] = None,
        enabled: bool = True,
        trigger: str = "optional",
        priority: int = 50,
    ) -> SkillEntry:
        """
        Assign a skill to a character.  Calling again with the same skill_id
        replaces it.

        Example::

            reg.assign_skill("aria", "web_lookup",
                             skill_type="web_lookup",
                             label="Search the web for current information",
                             params={"max_results": 3},
                             trigger="optional")
        """
        rec = self.ensure(character_id)
        entry = SkillEntry(
            skill_id   = skill_id,
            skill_type = skill_type,
            label      = label or skill_id.replace("_", " ").title(),
            params     = params or {},
            enabled    = enabled,
            trigger    = trigger,
            priority   = priority,
        )
        with self._lock:
            rec.skills[skill_id] = entry
        return entry

    def revoke_skill(self, character_id: str, skill_id: str) -> bool:
        """Remove a skill from a character.  Returns True if it existed."""
        rec = self.ensure(character_id)
        with self._lock:
            return bool(rec.skills.pop(skill_id, None))

    def toggle_skill(self, character_id: str, skill_id: str, enabled: bool) -> bool:
        """Enable or disable a skill without removing it.  Returns True if found."""
        rec = self.ensure(character_id)
        with self._lock:
            skill = rec.skills.get(skill_id)
            if skill:
                skill.enabled = enabled
                return True
        return False

    def get_skills(
        self,
        character_id: str,
        *,
        trigger: Optional[str] = None,
        enabled_only: bool = True,
    ) -> List[SkillEntry]:
        """
        Return a character's skills, sorted by priority.
        Optionally filter by trigger type and/or enabled state.
        """
        rec = self.ensure(character_id)
        with self._lock:
            skills = list(rec.skills.values())
        if enabled_only:
            skills = [s for s in skills if s.enabled]
        if trigger:
            skills = [s for s in skills if s.trigger == trigger]
        return sorted(skills, key=lambda s: s.priority)

    def has_skill(self, character_id: str, skill_id: str) -> bool:
        """Return True if the character has this skill (enabled or not)."""
        rec = self.ensure(character_id)
        with self._lock:
            return skill_id in rec.skills

    def get_skill(self, character_id: str, skill_id: str) -> Optional[SkillEntry]:
        """Return a specific SkillEntry or None."""
        rec = self.ensure(character_id)
        with self._lock:
            return rec.skills.get(skill_id)

    # ── Full record ───────────────────────────────────────────────────

    def get_record(self, character_id: str) -> Optional[CharacterRecord]:
        """Return the full CharacterRecord (profile + state + skills), or None."""
        with self._lock:
            return self._chars.get(character_id)

    def get_character_summary(self, character_id: str) -> Dict:
        """
        Return a compact summary suitable for injection into an LLM system prompt.
        Includes name, age, key personality traits, mood, active restrictions.
        """
        rec = self.ensure(character_id)
        p = rec.profile
        s = rec.state

        # Top personality traits (top 4 by value)
        top_traits = sorted(p.personality.items(), key=lambda x: -x[1])[:4]
        trait_text = ", ".join(f"{k}={v:.1f}" for k, v in top_traits)

        return {
            "character_id":  character_id,
            "name":          p.name,
            "age":           p.age,
            "pronouns":      p.pronouns,
            "voice_style":   p.voice_style,
            "voice_id":      p.voice_id,
            "appearance":    p.appearance,
            "top_traits":    trait_text,
            "backstory":     p.backstory[:300] if p.backstory else "",
            "mood":          s.mood,
            "mood_intensity": s.mood_intensity,
            "focus":         s.focus,
            "current_role":  s.current_role,
            "energy":        s.energy,
            "inhibition":    s.inhibition,
            "restrictions":  sorted(s.restrictions),
            "active_skills": [sk.skill_id for sk in self.get_skills(character_id)],
        }

    # ── Bulk operations ───────────────────────────────────────────────

    def load_from_dict(self, character_id: str, data: Dict) -> CharacterRecord:
        """
        Hydrate a CharacterRecord from a plain dict (e.g. loaded from YAML).
        Merges profile, state, and skills.
        """
        profile_data = data.get("profile", data)  # support flat or nested
        rec = self.register(
            character_id,
            name        = profile_data.get("name", character_id),
            age         = profile_data.get("age", 22),
            appearance  = profile_data.get("appearance", {}),
            personality = profile_data.get("personality", {}),
            backstory   = profile_data.get("backstory", ""),
            voice_style = profile_data.get("voice_style", "natural"),
            pronouns    = profile_data.get("pronouns"),
            scene_roles = profile_data.get("scene_roles", []),
        )
        # Load state if present
        state_data = data.get("state", {})
        if state_data:
            restrictions = set(state_data.pop("restrictions", []))
            self.set_state(character_id, **state_data)
            with self._lock:
                rec.state.restrictions = restrictions

        # Load skills if present
        for skill_id, sk_data in data.get("skills", {}).items():
            self.assign_skill(
                character_id,
                skill_id,
                skill_type = sk_data.get("skill_type", "custom"),
                label      = sk_data.get("label", ""),
                params     = sk_data.get("params", {}),
                enabled    = sk_data.get("enabled", True),
                trigger    = sk_data.get("trigger", "optional"),
                priority   = sk_data.get("priority", 50),
            )
        return rec

    # ── Persistence ──────────────────────────────────────────────────

    def persist_to_db(self, character_id: Optional[str] = None) -> int:
        """
        Write runtime state back to the database for persistence across restarts.

        If *character_id* is given, persists that character only.
        If omitted, persists ALL registered characters.

        Returns the number of characters successfully persisted.
        """
        try:
            from content.simulation.database.db import Database
            db = Database()
        except Exception as exc:
            # v1.49.3 [2026-03-22] — Structured logging context
            logger.warning("[CharacterRegistry] Cannot access DB (operation=persist_to_db): %s", exc)
            return 0

        ids = [character_id] if character_id else list(self.list_characters())
        persisted = 0
        for cid in ids:
            rec = self.get_record(cid)
            if rec is None:
                continue
            state = rec.state
            try:
                db.update_character_state(
                    cid,
                    mood=state.mood,
                    energy=state.energy,
                    arousal=getattr(state, "arousal", 0.0) or state.flags.get("arousal", 0.0),
                    metadata={"inhibition": state.inhibition, "flags": state.flags},
                )
                persisted += 1
            except Exception as exc:
                logger.debug("persist_to_db(%s): %s", cid, exc)
        if persisted:
            logger.info("[CharacterRegistry] Persisted to DB (operation=persist_to_db, saved=%d, total=%d)", persisted, len(ids))
        return persisted


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON + DEFAULT CHARACTER TEMPLATES
# ══════════════════════════════════════════════════════════════════════

_REGISTRY_INSTANCE: Optional[CharacterRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_character_registry() -> CharacterRegistry:
    """
    Return the global CharacterRegistry singleton.
    Creates it on first call — safe to call from any thread.
    """
    global _REGISTRY_INSTANCE
    if _REGISTRY_INSTANCE is None:
        with _REGISTRY_LOCK:
            if _REGISTRY_INSTANCE is None:
                _REGISTRY_INSTANCE = CharacterRegistry()
                _bootstrap_defaults(_REGISTRY_INSTANCE)
    return _REGISTRY_INSTANCE


# Default skill templates applied to all characters unless overridden
_DEFAULT_SKILLS = [
    SkillEntry(
        skill_id   = "memory_recall",
        skill_type = "memory_recall",
        label      = "Recall memories relevant to this conversation",
        params     = {"top_k": 5, "min_score": 0.3},
        trigger    = "auto",
        priority   = 10,
    ),
    SkillEntry(
        skill_id   = "speech_enhance",
        skill_type = "speech_enhance",
        label      = "Speak in your authentic voice with the right style and tone",
        params     = {"default_style": "natural"},
        trigger    = "auto",
        priority   = 20,
    ),
    SkillEntry(
        skill_id   = "check_restrictions",
        skill_type = "personality_lock",
        label      = "Check what you will and won't do right now",
        params     = {},
        trigger    = "auto",
        priority   = 5,
    ),
    SkillEntry(
        skill_id   = "get_dialog_options",
        skill_type = "dialog_choices",
        label      = "Get contextual dialog suggestions for this moment",
        params     = {"max_options": 4},
        trigger    = "optional",
        priority   = 30,
    ),
    SkillEntry(
        skill_id   = "web_lookup",
        skill_type = "web_lookup",
        label      = "Search for real-time information when asked",
        params     = {"max_results": 3},
        trigger    = "optional",
        priority   = 60,
    ),
]


def _bootstrap_defaults(reg: CharacterRegistry) -> None:
    """
    Seed the registry with the base default skills.
    Scene startup code should call ``reg.register()`` with full profiles.
    The stub character `__framework__` is used by system-level tools.
    """
    reg.register(
        "__framework__",
        name        = "Framework",
        backstory   = "Internal framework system character — not an agent.",
        scene_roles = [],
    )


def seed_registry_from_character(char: Any, *, voice_id: str = "") -> None:
    """
    Populate the registry from a ``Character`` ORM/dataclass-style object.

    Inspects the most common attribute names used across CosySim character
    models (``Character``, ``CharacterData``, ``_Char`` stubs) and fills in
    as much profile + state data as is available.  Safe to call multiple
    times — successive calls update the profile and merge state.

    Args:
        char:     Any object with at least ``.id`` and ``.name`` attributes.
        voice_id: Explicit voices.yaml key (e.g. ``"lola"``).  When omitted
                  the registry checks if ``char.id`` matches a voices.yaml
                  entry and uses that.
    """
    if char is None:
        return
    cid  = getattr(char, "id", None) or getattr(char, "character_id", None)
    name = getattr(char, "name", None)
    if not cid or not name:
        return

    # Resolve voice_id: explicit arg → char.voice_id attr → char.id as fallback
    resolved_voice_id = (
        voice_id
        or getattr(char, "voice_id", "")
        or ""
    )
    if not resolved_voice_id:
        # Check if the character id itself is a valid voices.yaml key
        try:
            from engine.config import get_config
            voices = get_config().get("voices", {})
            if isinstance(voices, dict) and cid in voices:
                resolved_voice_id = cid
        except Exception as exc:
            # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
            logger.warning("[CharacterRegistry] Voice config lookup failed (operation=register): %s", exc)

    # Gather personality traits from whatever attributes exist
    _trait_keys = [
        "warmth", "curiosity", "assertiveness", "playfulness", "empathy",
        "dominance", "vulnerability", "wit", "sensuality", "openness",
        "humor", "flirtiness", "intelligence", "creativity", "formality",
    ]
    personality: Dict[str, float] = {}
    for k in _trait_keys:
        v = getattr(char, k, None)
        if v is not None:
            try:
                personality[k] = float(v)
            except (TypeError, ValueError) as exc:
                # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
                logger.warning("[CharacterRegistry] Personality trait parse failed (operation=register, key=%s): %s", k, exc)

    # Appearance dict — accept existing dict, string description, or build from attrs
    _raw_app = getattr(char, "appearance", {}) or {}
    if isinstance(_raw_app, dict):
        appearance: Dict[str, Any] = dict(_raw_app)
    else:
        appearance: Dict[str, Any] = {"description": str(_raw_app)} if _raw_app else {}
    for k in ("hair", "eyes", "height", "body", "skin", "style"):
        v = getattr(char, k, None)
        if v is not None:
            appearance.setdefault(k, v)

    reg = get_character_registry()
    rec = reg.register(
        cid,
        name        = name,
        age         = int(getattr(char, "age", 22) or 22),
        appearance  = appearance,
        personality = personality,
        backstory   = getattr(char, "backstory", "") or "",
        voice_style = getattr(char, "voice_style", "") or getattr(char, "description", "") or "natural",
        pronouns    = getattr(char, "pronouns", None),
        scene_roles = list(getattr(char, "scene_roles", []) or []),
    )
    rec.profile.voice_id = resolved_voice_id

    # Sync mutable state from character object
    state_kwargs: Dict[str, Any] = {}
    for k in ("mood", "focus", "current_role", "energy", "inhibition"):
        v = getattr(char, k, None)
        if v is not None:
            try:
                state_kwargs[k] = type(getattr(rec.state, k))(v)
            except Exception:
                state_kwargs[k] = v
    mood_intensity = getattr(char, "mood_intensity", None)
    if mood_intensity is not None:
        try:
            state_kwargs["mood_intensity"] = float(mood_intensity)
        except Exception as exc:
            # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
            logger.warning("[CharacterRegistry] mood_intensity parse failed (operation=register): %s", exc)
    if state_kwargs:
        reg.set_state(cid, **state_kwargs)

    apply_default_skills(cid)


def apply_default_skills(character_id: str) -> None:
    """
    Grant the standard default skill set to a character.
    Call this after ``register()`` if you want the full baseline.
    """
    reg = get_character_registry()
    for sk in _DEFAULT_SKILLS:
        if not reg.has_skill(character_id, sk.skill_id):
            reg.assign_skill(
                character_id,
                sk.skill_id,
                skill_type = sk.skill_type,
                label      = sk.label,
                params     = dict(sk.params),
                enabled    = sk.enabled,
                trigger    = sk.trigger,
                priority   = sk.priority,
            )
