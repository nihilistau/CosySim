"""
CosySim Scene Rules Engine
============================

The **Rules Engine** is the governance layer that defines what is allowed, what
is required, what triggers automatically, and what is outright forbidden —
across every scene and for every character.

This module is the authoritative source of truth for "the rules" from the
agent's perspective.  When an agent calls ``get_scene_rules("bedroom")`` they
get the full, up-to-date rule set for that scene.  When the Director calls
``apply_rule("bedroom", "lights_off", ["aria"])`` the rule's effects execute
immediately and are reflected in ``SceneStateManager`` and
``CharacterRegistry``.

Why this exists
---------------
Previously, scene logic (what you can do, when, under what conditions) was
scattered across Python scene files, Jinja templates, and hard-coded prompt
fragments.  The Rules Engine centralises it so:

* Any MCP tool can read and apply rules.
* Rules are data — you can add, modify, or remove them at runtime.
* The system can enforce rules transparently (through interceptors) without
  the agent needing to "know" about them.
* Rule effects are auditable — every application is logged to the
  ``NarrativeLog``.

Concepts
--------

``RuleCondition``
    A set of stat/state thresholds that must be met for a rule to activate or
    for an action to be available.  Example: ``{"arousal": 50, "openness": 40}``

``ActionDefinition``
    A named action available in a scene.  Has a required intimacy level, an
    optional ``RuleCondition``, and a list of ``RuleEffect``s that fire when
    the action executes.

``RuleDefinition``
    A named rule — can be ``always_on``, ``triggered`` (by condition), or
    ``director_only``.  Each rule has a list of effects and optionally a
    condition.

``RuleEffect``
    One effect produced when a rule fires:
    - ``stat_adjust``   — adjust a stat on a character
    - ``state_set``     — set a state field on a character (mood, focus, etc.)
    - ``add_restriction`` / ``remove_restriction``
    - ``add_narrative`` — log an event
    - ``set_atmosphere``
    - ``set_directive`` — issue a ResponseDirective
    - ``scene_event``   — emit a named scene event (for external listeners)

``PermissionMatrix``
    Per-scene, per-character table of allowed/forbidden action IDs.

``SceneRulesEngine``
    Singleton manager.  Owns all rules, actions, and the permission matrix.
    Exposes read APIs for agents and write APIs for the Director.

Quick start::

    from engine.mcp.scene_rules_engine import get_rules_engine

    eng = get_rules_engine()

    # Read available actions for a character
    available = eng.get_available_actions("bedroom", "aria", stats={"arousal": 60})
    # [{"id": "kiss_soft", "label": "Soft Kiss", ...}, ...]

    # Apply a director-issued rule
    eng.apply_rule("bedroom", "mood_lift", target_ids=["aria"], issuer="director")

    # Check if an action is allowed
    allowed, reason = eng.check_permission("bedroom", "aria", "striptease")
    # (True, "allowed")

    # Get the full rule text for an agent
    text = eng.get_rules_text("bedroom")
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ══════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class RuleCondition:
    """
    Threshold conditions on character or scene stats.
    All conditions must be met (AND logic).  Use multiple conditions
    in a list for OR logic at higher levels.

    Fields
    ------
    stat_thresholds  — Dict[stat_name, min_value]  e.g. {"arousal": 40}
    scene_flags      — scene-level flag requirements  {"lights_off": True}
    character_flags  — character-level flag requirements
    any_of_stats     — stat_name list — at least one must be ≥ threshold
    """
    stat_thresholds:  Dict[str, float] = field(default_factory=dict)
    scene_flags:      Dict[str, Any]   = field(default_factory=dict)
    character_flags:  Dict[str, Any]   = field(default_factory=dict)
    any_of_stats:     Dict[str, float] = field(default_factory=dict)

    def is_met(
        self,
        stats:        Optional[Dict[str, float]] = None,
        scene_state:  Optional[Dict[str, Any]]   = None,
        char_flags:   Optional[Dict[str, Any]]   = None,
    ) -> bool:
        """Return True if all conditions in this object are satisfied."""
        s = stats or {}
        sf = scene_state or {}
        cf = char_flags or {}
        # ALL stat thresholds
        for stat, threshold in self.stat_thresholds.items():
            if s.get(stat, 0) < threshold:
                return False
        # ALL scene flags
        for k, expected in self.scene_flags.items():
            if sf.get(k) != expected:
                return False
        # ALL character flags
        for k, expected in self.character_flags.items():
            if cf.get(k) != expected:
                return False
        # ANY of stats (at least one must pass)
        if self.any_of_stats:
            if not any(s.get(k, 0) >= v for k, v in self.any_of_stats.items()):
                return False
        return True


@dataclass
class RuleEffect:
    """
    One effect that fires when a rule activates.

    effect_type:
      ``stat_adjust``       — delta-adjust a stat: {"stat": "arousal", "delta": 15}
      ``state_set``         — set a state field: {"field": "mood", "value": "excited"}
      ``add_restriction``   — add a restriction name
      ``remove_restriction``— remove a restriction name
      ``add_narrative``     — log a narrative string
      ``set_atmosphere``    — set scene atmosphere keys
      ``set_directive``     — issue a ResponseDirective
      ``scene_event``       — emit a named event
      ``assign_skill``      — grant a skill to target character(s)
      ``revoke_skill``      — revoke a skill
    """
    effect_type: str
    params:      Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {"effect_type": self.effect_type, "params": self.params}


@dataclass
class ActionDefinition:
    """
    A named action available to agents in a scene.

    Fields
    ------
    action_id       — unique key (e.g. "kiss_soft", "striptease", "send_photo")
    scene           — which scene this belongs to
    label           — human-readable display name
    description     — what this action does and how it feels
    intimacy_level  — 1-5 (1=non-intimate, 5=highly explicit)
    condition       — RuleCondition that must be met
    effects         — list of RuleEffects applied when action executes
    category        — "physical" | "verbal" | "media" | "environment" | "game"
    cooldown_secs   — minimum seconds between uses (0 = no cooldown)
    forbidden_for   — set of character_ids that cannot use this action
    """
    action_id:      str
    scene:          str
    label:          str
    description:    str
    intimacy_level: int               = 1
    condition:      Optional[RuleCondition] = None
    effects:        List[RuleEffect]  = field(default_factory=list)
    category:       str               = "physical"
    cooldown_secs:  float             = 0.0
    forbidden_for:  Set[str]          = field(default_factory=set)
    last_used:      Dict[str, float]  = field(default_factory=dict)  # char_id → timestamp

    def is_available(
        self,
        character_id: str,
        stats:        Optional[Dict] = None,
        scene_state:  Optional[Dict] = None,
    ) -> Tuple[bool, str]:
        """
        Check if this action is available to ``character_id``.
        Returns (available: bool, reason: str).
        """
        if character_id in self.forbidden_for:
            return False, f"action '{self.action_id}' is forbidden for this character"
        if self.condition and not self.condition.is_met(stats=stats, scene_state=scene_state):
            return False, f"stat requirements not met for '{self.action_id}'"
        if self.cooldown_secs > 0:
            last = self.last_used.get(character_id, 0)
            elapsed = time.time() - last
            if elapsed < self.cooldown_secs:
                remaining = round(self.cooldown_secs - elapsed, 1)
                return False, f"cooldown: {remaining}s remaining"
        return True, "allowed"

    def to_dict(self) -> Dict:
        return {
            "action_id":      self.action_id,
            "label":          self.label,
            "description":    self.description,
            "intimacy_level": self.intimacy_level,
            "category":       self.category,
            "effects":        [e.to_dict() for e in self.effects],
        }


@dataclass
class RuleDefinition:
    """
    A named rule — an always-on constraint, a triggered behaviour,
    or a Director-issued modifier.

    Fields
    ------
    rule_id         — unique key (e.g. "consent_check", "lights_off_atmosphere")
    scene           — which scene this applies to ("*" = all scenes)
    label           — human-readable name
    description     — what this rule enforces or enables
    rule_type       — "always_on" | "triggered" | "director_only" | "character"
    condition       — RuleCondition; for triggered/always_on rules
    effects         — list of RuleEffects applied when rule fires
    priority        — execution order (lower = first)
    can_be_disabled — if False, this rule cannot be turned off at runtime
    enabled         — current enabled state
    """
    rule_id:         str
    scene:           str
    label:           str
    description:     str              = ""
    rule_type:       str              = "always_on"
    condition:       Optional[RuleCondition] = None
    effects:         List[RuleEffect] = field(default_factory=list)
    priority:        int              = 50
    can_be_disabled: bool             = True
    enabled:         bool             = True

    def applies_to(self, scene: str) -> bool:
        return self.scene == "*" or self.scene == scene

    def to_dict(self) -> Dict:
        return {
            "rule_id":     self.rule_id,
            "label":       self.label,
            "description": self.description,
            "rule_type":   self.rule_type,
            "enabled":     self.enabled,
            "priority":    self.priority,
        }


# ══════════════════════════════════════════════════════════════════════
#  PERMISSION MATRIX
# ══════════════════════════════════════════════════════════════════════

class PermissionMatrix:
    """
    Per-scene, per-character action permission table.

    By default all characters can use all defined actions unless:
    - The action's ``forbidden_for`` set includes them, OR
    - The permission matrix explicitly denies them.

    Director and scene logic can call ``deny()`` and ``allow()`` to override.
    """

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        # _denied[scene][character_id] = set of denied action_ids
        self._denied: Dict[str, Dict[str, Set[str]]] = {}
        # _allowed[scene][character_id] = set of explicitly allowed (overrides deny)
        self._allowed: Dict[str, Dict[str, Set[str]]] = {}

    def deny(self, scene: str, character_id: str, action_id: str) -> None:
        """Deny a character access to a specific action in a scene."""
        with self._lock:
            self._denied.setdefault(scene, {}).setdefault(character_id, set()).add(action_id)

    def allow(self, scene: str, character_id: str, action_id: str) -> None:
        """Explicitly allow (overrides deny) a character's access to an action."""
        with self._lock:
            self._allowed.setdefault(scene, {}).setdefault(character_id, set()).add(action_id)
            # Also remove from denied
            denied = self._denied.get(scene, {}).get(character_id, set())
            denied.discard(action_id)

    def check(self, scene: str, character_id: str, action_id: str) -> Tuple[bool, str]:
        """Return (permitted, reason)."""
        with self._lock:
            explicit = self._allowed.get(scene, {}).get(character_id, set())
            if action_id in explicit:
                return True, "explicitly allowed"
            denied = self._denied.get(scene, {}).get(character_id, set())
            if action_id in denied:
                return False, "denied by permission matrix"
        return True, "default allowed"

    def reset(self, scene: str, character_id: Optional[str] = None) -> None:
        """Clear all permissions for a scene (or one character in a scene)."""
        with self._lock:
            if character_id:
                self._denied.get(scene, {}).pop(character_id, None)
                self._allowed.get(scene, {}).pop(character_id, None)
            else:
                self._denied.pop(scene, None)
                self._allowed.pop(scene, None)


# ══════════════════════════════════════════════════════════════════════
#  SCENE RULES ENGINE  (singleton)
# ══════════════════════════════════════════════════════════════════════

class SceneRulesEngine:
    """
    Central rules management singleton.

    Owns:
    - All ``RuleDefinition``s (global + per-scene)
    - All ``ActionDefinition``s (per-scene)
    - ``PermissionMatrix``
    - Rule application + effect execution logic

    All state is thread-safe.
    """

    def __init__(self) -> None:
        self._lock       = threading.Lock()
        self._rules:     Dict[str, RuleDefinition]   = {}  # rule_id → rule
        self._actions:   Dict[str, ActionDefinition] = {}  # action_id → action
        self._perms      = PermissionMatrix()
        self._cooldowns: Dict[str, Dict[str, float]] = {}  # action_id → {char_id → ts}
        self._bootstrap()

    # ── Rule management ───────────────────────────────────────────────

    def add_rule(self, rule: RuleDefinition) -> None:
        """Register a rule (replaces if rule_id already exists)."""
        with self._lock:
            self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule.  Returns True if it existed."""
        with self._lock:
            return bool(self._rules.pop(rule_id, None))

    def toggle_rule(self, rule_id: str, enabled: bool) -> bool:
        """Enable or disable a rule.  Returns True if found."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule and rule.can_be_disabled:
                rule.enabled = enabled
                return True
        return False

    def get_rules(self, scene: str, rule_type: Optional[str] = None) -> List[RuleDefinition]:
        """Return rules for a scene, sorted by priority."""
        with self._lock:
            rules = [r for r in self._rules.values() if r.applies_to(scene) and r.enabled]
        if rule_type:
            rules = [r for r in rules if r.rule_type == rule_type]
        return sorted(rules, key=lambda r: r.priority)

    # ── Action management ─────────────────────────────────────────────

    def add_action(self, action: ActionDefinition) -> None:
        """Register an action (replaces if action_id already exists)."""
        with self._lock:
            self._actions[action.action_id] = action

    def get_action(self, action_id: str) -> Optional[ActionDefinition]:
        with self._lock:
            return self._actions.get(action_id)

    def get_available_actions(
        self,
        scene: str,
        character_id: str,
        stats: Optional[Dict] = None,
        scene_state: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Return all actions for ``scene`` that ``character_id`` can currently
        perform, filtered by conditions and permissions.
        """
        with self._lock:
            scene_actions = [a for a in self._actions.values() if a.scene == scene]

        results = []
        for action in scene_actions:
            perm_ok, perm_reason = self._perms.check(scene, character_id, action.action_id)
            if not perm_ok:
                continue
            avail, reason = action.is_available(character_id, stats=stats, scene_state=scene_state)
            if avail:
                results.append({**action.to_dict(), "available": True})
            # Unavailable but exists → include with reason so agent knows why
            else:
                results.append({**action.to_dict(), "available": False, "reason": reason})
        return sorted(results, key=lambda a: (not a["available"], a["intimacy_level"]))

    # ── Permission management ────────────────────────────────────────

    def check_permission(
        self, scene: str, character_id: str, action_id: str
    ) -> Tuple[bool, str]:
        """Check if a character can perform an action (permission matrix check only)."""
        return self._perms.check(scene, character_id, action_id)

    def deny_action(self, scene: str, character_id: str, action_id: str) -> None:
        self._perms.deny(scene, character_id, action_id)

    def allow_action(self, scene: str, character_id: str, action_id: str) -> None:
        self._perms.allow(scene, character_id, action_id)

    # ── Rule application ──────────────────────────────────────────────

    def apply_rule(
        self,
        scene: str,
        rule_id: str,
        target_ids: Optional[List[str]] = None,
        issuer: str = "director",
        ctx: Optional[Dict] = None,
    ) -> Dict:
        """
        Apply a rule immediately — execute all its effects for each target.

        Returns a dict describing what was applied.
        """
        with self._lock:
            rule = self._rules.get(rule_id)
        if rule is None:
            return {"ok": False, "error": f"Rule '{rule_id}' not found"}
        if not rule.enabled:
            return {"ok": False, "error": f"Rule '{rule_id}' is disabled"}

        applied_effects = []
        for effect in rule.effects:
            for char_id in (target_ids or ["_scene_"]):
                result = self._execute_effect(effect, scene, char_id, ctx=ctx)
                applied_effects.append({"char": char_id, "effect": effect.effect_type, "result": result})

        return {
            "ok":             True,
            "rule_id":        rule_id,
            "scene":          scene,
            "targets":        target_ids or [],
            "issuer":         issuer,
            "effects_applied": applied_effects,
        }

    def apply_action(
        self,
        scene: str,
        action_id: str,
        initiator_id: str,
        target_ids: Optional[List[str]] = None,
        stats: Optional[Dict] = None,
        ctx: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute an action — check availability, then fire all effects.

        Returns a detailed result dict.
        """
        action = self.get_action(action_id)
        if action is None:
            return {"ok": False, "error": f"Action '{action_id}' not found"}

        perm_ok, perm_reason = self._perms.check(scene, initiator_id, action_id)
        if not perm_ok:
            return {"ok": False, "error": perm_reason}

        avail, reason = action.is_available(initiator_id, stats=stats)
        if not avail:
            return {"ok": False, "error": reason}

        # Record use for cooldown
        action.last_used[initiator_id] = time.time()

        applied = []
        all_targets = [initiator_id] + (target_ids or [])
        for effect in action.effects:
            for char_id in all_targets:
                result = self._execute_effect(effect, scene, char_id, ctx=ctx)
                applied.append({"char": char_id, "effect": effect.effect_type, "result": result})

        return {
            "ok":             True,
            "action_id":      action_id,
            "scene":          scene,
            "initiator":      initiator_id,
            "targets":        target_ids or [],
            "effects_applied": applied,
            "action_info":    action.to_dict(),
        }

    # ── Rules text (for agent injection) ─────────────────────────────

    def get_rules_text(self, scene: str) -> str:
        """
        Return a human-readable rules reference for the given scene.
        This is injected into the system prompt so agents understand the
        scene constraints without needing to call separate tools.
        """
        rules = self.get_rules(scene)

        lines = [f"SCENE RULES — {scene.upper()}"]
        lines.append("=" * 50)

        always_on = [r for r in rules if r.rule_type == "always_on"]
        triggered = [r for r in rules if r.rule_type == "triggered"]
        director  = [r for r in rules if r.rule_type == "director_only"]

        if always_on:
            lines.append("ALWAYS ACTIVE:")
            for r in always_on:
                lines.append(f"  [{r.rule_id}] {r.label}: {r.description}")

        if triggered:
            lines.append("CONDITIONALLY ACTIVE:")
            for r in triggered:
                lines.append(f"  [{r.rule_id}] {r.label}: {r.description}")

        if director:
            lines.append("DIRECTOR CAN ACTIVATE:")
            for r in director:
                lines.append(f"  [{r.rule_id}] {r.label}: {r.description}")

        return "\n".join(lines)

    def get_scene_summary(self, scene: str, character_id: str = "") -> Dict:
        """
        Return a full machine-readable scene summary: rules, available actions,
        and permission overrides for a character.
        """
        rules   = [r.to_dict() for r in self.get_rules(scene)]
        actions = self.get_available_actions(scene, character_id) if character_id else []
        return {
            "scene":     scene,
            "character": character_id,
            "rules":     rules,
            "actions":   actions,
        }

    # ── Internal effect executor ──────────────────────────────────────

    def _execute_effect(
        self,
        effect: RuleEffect,
        scene: str,
        character_id: str,
        ctx: Optional[Dict] = None,
    ) -> Any:
        """
        Execute a single RuleEffect.  Each effect type dispatches to the
        appropriate manager (SceneStateManager, CharacterRegistry,
        DialogSystem).

        Returns a description of what was done.
        """
        t   = effect.effect_type
        p   = effect.params

        try:
            if t == "stat_adjust":
                from engine.mcp.scene_state import get_scene_state_manager
                ssm = get_scene_state_manager()
                stat  = p.get("stat", "")
                delta = p.get("delta", 0)
                if stat and character_id != "_scene_":
                    ssm.update_stats(character_id, **{stat: delta})
                return f"{stat} +{delta} on {character_id}"

            elif t == "state_set":
                from engine.mcp.character_registry import get_character_registry
                reg = get_character_registry()
                field_ = p.get("field", "")
                value  = p.get("value", "")
                reg.set_state(character_id, **{field_: value})
                return f"{field_}={value} on {character_id}"

            elif t == "add_restriction":
                from engine.mcp.character_registry import get_character_registry
                get_character_registry().add_restriction(character_id, p.get("restriction", ""))
                return f"restriction added: {p.get('restriction')}"

            elif t == "remove_restriction":
                from engine.mcp.character_registry import get_character_registry
                get_character_registry().remove_restriction(character_id, p.get("restriction", ""))
                return f"restriction removed: {p.get('restriction')}"

            elif t == "add_narrative":
                from engine.mcp.scene_state import get_scene_state_manager
                get_scene_state_manager().add_narrative(scene, p.get("event", ""),
                                                        character_id=character_id)
                return f"narrative: {p.get('event', '')[:50]}"

            elif t == "set_atmosphere":
                from engine.mcp.scene_state import get_scene_state_manager
                get_scene_state_manager().set_atmosphere(scene, **p)
                return f"atmosphere set: {p}"

            elif t == "set_directive":
                from engine.mcp.dialog_system import get_dialog_system
                ds = get_dialog_system()
                ds.set_directive(
                    character_id, scene,
                    directive_type = p.get("directive_type", "topic_steer"),
                    value          = p.get("value", ""),
                    turns          = p.get("turns", 1),
                    issued_by      = "rules_engine",
                )
                return f"directive set: {p.get('directive_type')} = {p.get('value', '')[:40]}"

            elif t == "scene_event":
                event_name = p.get("event", "unknown_event")
                if ctx is not None:
                    ctx.setdefault("scene_events", []).append({
                        "event": event_name, "scene": scene, "char": character_id, "params": p
                    })
                return f"event emitted: {event_name}"

            elif t == "assign_skill":
                from engine.mcp.character_registry import get_character_registry
                reg = get_character_registry()
                reg.assign_skill(
                    character_id,
                    skill_id   = p.get("skill_id", ""),
                    skill_type = p.get("skill_type", "custom"),
                    label      = p.get("label", ""),
                    params     = p.get("params", {}),
                    trigger    = p.get("trigger", "optional"),
                )
                return f"skill assigned: {p.get('skill_id')}"

            elif t == "revoke_skill":
                from engine.mcp.character_registry import get_character_registry
                get_character_registry().revoke_skill(character_id, p.get("skill_id", ""))
                return f"skill revoked: {p.get('skill_id')}"

        except Exception as exc:
            return f"effect error: {exc}"

        return f"unknown effect type: {t}"

    # ── Bootstrap — default rules and actions ─────────────────────────

    def _bootstrap(self) -> None:
        """Seed the engine with the built-in scene rules and actions."""
        self._bootstrap_global_rules()
        self._bootstrap_bedroom()
        self._bootstrap_phone()

    def _bootstrap_global_rules(self) -> None:
        """Rules that apply to ALL scenes."""
        self.add_rule(RuleDefinition(
            rule_id     = "consent_always",
            scene       = "*",
            label       = "Consent is real",
            description = "Characters can always refuse any action based on their current stats, "
                          "mood, and restrictions.  A refusal should be authentic and in-character, "
                          "not a safety break.  Use check_character_consent() to check first.",
            rule_type   = "always_on",
            priority    = 1,
            can_be_disabled = False,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "memory_continuity",
            scene       = "*",
            label       = "Memory is continuous",
            description = "Your character remembers everything.  check get_scene_narrative() and "
                          "search_memory() before each response.  Never contradict established facts.",
            rule_type   = "always_on",
            priority    = 2,
            can_be_disabled = False,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "authentic_voice",
            scene       = "*",
            label       = "Your voice is your own",
            description = "Speak in your character's voice always.  Use speech_enhance if you want "
                          "to check your style or get a rewrite prompt.  Never sound generic.",
            rule_type   = "always_on",
            priority    = 3,
            can_be_disabled = False,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "no_stale_loops",
            scene       = "*",
            label       = "No stale loops",
            description = "Never repeat a phrase, action, or question you used in the last 3 turns. "
                          "Use resolve_random_scene_event() if the scene feels stuck.",
            rule_type   = "always_on",
            priority    = 4,
        ))

    def _bootstrap_bedroom(self) -> None:
        """Bedroom-specific rules and actions."""
        # ── Rules ──────────────────────────────────────────────────────
        self.add_rule(RuleDefinition(
            rule_id     = "bedroom_wardrobe_first",
            scene       = "bedroom",
            label       = "Check wardrobe before touching clothing",
            description = "ALWAYS call wardrobe_get() before any undressing action.  You must know "
                          "exactly what is being worn before removing it.",
            rule_type   = "always_on",
            priority    = 10,
            can_be_disabled = False,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "bedroom_stats_drive_behaviour",
            scene       = "bedroom",
            label       = "Stats drive your behaviour",
            description = "Your arousal, openness, and happiness directly influence what you want "
                          "and what you'll do.  Check get_character_scene_stats() and let the "
                          "numbers inform your physicality, temperature, and decisions.",
            rule_type   = "always_on",
            priority    = 11,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "bedroom_timed_actions",
            scene       = "bedroom",
            label       = "Long actions take time",
            description = "Striptease, massages, and extended intimate acts MUST use start_timed_action(). "
                          "Poll poll_timed_action() each turn to advance phases.  Never skip phases.",
            rule_type   = "always_on",
            priority    = 12,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "bedroom_atmosphere",
            scene       = "bedroom",
            label       = "Set and maintain atmosphere",
            description = "Use set_scene_atmosphere() to establish lighting, mood, music.  "
                          "Call it at scene start and after major mood shifts.",
            rule_type   = "always_on",
            priority    = 13,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "bedroom_lights_off",
            scene       = "bedroom",
            label       = "Lights off — intimacy boost",
            description = "Director special: sets dim lighting, increases arousal +10, openness +5",
            rule_type   = "director_only",
            priority    = 30,
            effects     = [
                RuleEffect("set_atmosphere", {"lighting": "dim", "mood": "intimate", "music": "ambient"}),
                RuleEffect("stat_adjust",    {"stat": "arousal", "delta": 10}),
                RuleEffect("stat_adjust",    {"stat": "openness", "delta": 5}),
                RuleEffect("add_narrative",  {"event": "The lights dim. The room feels closer."}),
            ],
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "bedroom_mood_lift",
            scene       = "bedroom",
            label       = "Mood lift",
            description = "Director special: character mood → excited, happiness +15",
            rule_type   = "director_only",
            priority    = 31,
            effects     = [
                RuleEffect("state_set",  {"field": "mood", "value": "excited"}),
                RuleEffect("stat_adjust", {"stat": "happiness", "delta": 15}),
            ],
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "bedroom_scene_reset",
            scene       = "bedroom",
            label       = "Scene reset — redress all characters",
            description = "Director special: resets atmosphere and re-dresses all characters",
            rule_type   = "director_only",
            priority    = 99,
        ))

        # ── Actions ────────────────────────────────────────────────────
        for action in _BEDROOM_ACTIONS:
            self.add_action(action)

    def _bootstrap_phone(self) -> None:
        """Phone-specific rules and actions."""
        self.add_rule(RuleDefinition(
            rule_id     = "phone_read_history",
            scene       = "phone",
            label       = "Read conversation history first",
            description = "Check get_scene_narrative() at the start of every response.  "
                          "The conversation has a history — never forget it.",
            rule_type   = "always_on",
            priority    = 10,
            can_be_disabled = False,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "phone_no_walls",
            scene       = "phone",
            label       = "No text walls",
            description = "Phone messages should feel like real texts: short bursts, "
                          "natural pauses, multiple short messages rather than one long one.  "
                          "Exception: sexting, which can be longer.",
            rule_type   = "always_on",
            priority    = 11,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "phone_heat_tracks",
            scene       = "phone",
            label       = "Conversation heat tracks arousal",
            description = "The more intimate the exchange, the warmer and more daring your "
                          "responses become.  Check get_character_scene_stats() — it drives tone.",
            rule_type   = "always_on",
            priority    = 12,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "phone_send_media",
            scene       = "phone",
            label       = "Photos and audio are real tools",
            description = "You can send selfies, voice notes, and video.  Use send_media "
                          "interaction type and include the URL in your response.",
            rule_type   = "always_on",
            priority    = 13,
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "phone_cold_open",
            scene       = "phone",
            label       = "Cold open — director override",
            description = "Director special: set conversation heat to 30, mood to 'playful'",
            rule_type   = "director_only",
            priority    = 40,
            effects     = [
                RuleEffect("state_set",  {"field": "mood",           "value": "playful"}),
                RuleEffect("state_set",  {"field": "mood_intensity", "value": 0.7}),
                RuleEffect("stat_adjust", {"stat": "happiness",      "delta": 10}),
            ],
        ))
        self.add_rule(RuleDefinition(
            rule_id     = "phone_escalate",
            scene       = "phone",
            label       = "Heat escalation — director override",
            description = "Director special: arousal +20, openness +15, directive: 'be more daring'",
            rule_type   = "director_only",
            priority    = 41,
            effects     = [
                RuleEffect("stat_adjust",  {"stat": "arousal",  "delta": 20}),
                RuleEffect("stat_adjust",  {"stat": "openness", "delta": 15}),
                RuleEffect("set_directive", {
                    "directive_type": "style_lock",
                    "value":          "charged",
                    "turns":          2,
                }),
            ],
        ))

        for action in _PHONE_ACTIONS:
            self.add_action(action)


# ── Default action sets ────────────────────────────────────────────────

_BEDROOM_ACTIONS: List[ActionDefinition] = [
    ActionDefinition(
        action_id = "cuddle", scene = "bedroom",
        label = "Cuddle / Hold",
        description = "Physical closeness — holding, spooning, lap sitting.",
        intimacy_level = 1, category = "physical",
        effects = [
            RuleEffect("stat_adjust", {"stat": "happiness",  "delta": 15}),
            RuleEffect("stat_adjust", {"stat": "affection",  "delta": 12}),
            RuleEffect("stat_adjust", {"stat": "arousal",    "delta":  5}),
        ],
    ),
    ActionDefinition(
        action_id = "kiss", scene = "bedroom",
        label = "Kiss",
        description = "Kissing — from soft to urgent.",
        intimacy_level = 2, category = "physical",
        condition = RuleCondition(stat_thresholds={"affection": 15}),
        effects = [
            RuleEffect("stat_adjust", {"stat": "arousal",   "delta": 18}),
            RuleEffect("stat_adjust", {"stat": "happiness", "delta": 10}),
        ],
    ),
    ActionDefinition(
        action_id = "caress", scene = "bedroom",
        label = "Caress / Touch",
        description = "Tactile touch — hair, back, face, body.",
        intimacy_level = 2, category = "physical",
        condition = RuleCondition(stat_thresholds={"openness": 20}),
        effects = [
            RuleEffect("stat_adjust", {"stat": "arousal",    "delta": 20}),
            RuleEffect("stat_adjust", {"stat": "affection",  "delta": 10}),
        ],
    ),
    ActionDefinition(
        action_id = "striptease", scene = "bedroom",
        label = "Striptease",
        description = "Undressing performance — uses timed action system.",
        intimacy_level = 4, category = "physical",
        condition = RuleCondition(stat_thresholds={"arousal": 40, "openness": 35}),
        cooldown_secs = 120.0,
        effects = [
            RuleEffect("stat_adjust", {"stat": "arousal",    "delta": 35}),
            RuleEffect("stat_adjust", {"stat": "openness",   "delta": 10}),
            RuleEffect("add_narrative", {"event": "A striptease begins."}),
        ],
    ),
    ActionDefinition(
        action_id = "intimate", scene = "bedroom",
        label = "Intimate Act",
        description = "Sexual encounter — requires high arousal and openness.",
        intimacy_level = 5, category = "physical",
        condition = RuleCondition(stat_thresholds={"arousal": 55, "openness": 45}),
        cooldown_secs = 30.0,
        effects = [
            RuleEffect("stat_adjust", {"stat": "arousal",    "delta": 40}),
            RuleEffect("stat_adjust", {"stat": "pleasure",   "delta": 45}),
            RuleEffect("stat_adjust", {"stat": "affection",  "delta": 20}),
        ],
    ),
    ActionDefinition(
        action_id = "deep_talk", scene = "bedroom",
        label = "Deep / Intimate Talk",
        description = "Confession, pillow talk, vulnerable sharing.",
        intimacy_level = 2, category = "verbal",
        effects = [
            RuleEffect("stat_adjust", {"stat": "affection",  "delta": 18}),
            RuleEffect("stat_adjust", {"stat": "happiness",  "delta": 12}),
        ],
    ),
    ActionDefinition(
        action_id = "set_atmosphere", scene = "bedroom",
        label = "Set atmosphere",
        description = "Change the room's lighting, mood, music.",
        intimacy_level = 1, category = "environment",
    ),
]

_PHONE_ACTIONS: List[ActionDefinition] = [
    ActionDefinition(
        action_id = "flirt_text", scene = "phone",
        label = "Flirt text",
        description = "Light teasing or forward flirting via text.",
        intimacy_level = 1, category = "verbal",
        effects = [
            RuleEffect("stat_adjust", {"stat": "happiness", "delta": 8}),
            RuleEffect("stat_adjust", {"stat": "arousal",   "delta": 5}),
        ],
    ),
    ActionDefinition(
        action_id = "sext", scene = "phone",
        label = "Sext / Explicit text",
        description = "Explicit text exchange.",
        intimacy_level = 4, category = "verbal",
        condition = RuleCondition(stat_thresholds={"arousal": 35, "openness": 30}),
        effects = [
            RuleEffect("stat_adjust", {"stat": "arousal",  "delta": 25}),
            RuleEffect("stat_adjust", {"stat": "openness", "delta": 10}),
        ],
    ),
    ActionDefinition(
        action_id = "voice_call", scene = "phone",
        label = "Voice call",
        description = "Real-time audio conversation.",
        intimacy_level = 2, category = "media",
        effects = [
            RuleEffect("stat_adjust", {"stat": "affection", "delta": 12}),
            RuleEffect("stat_adjust", {"stat": "happiness", "delta": 10}),
        ],
    ),
    ActionDefinition(
        action_id = "video_call", scene = "phone",
        label = "Video call",
        description = "Real-time video conversation.",
        intimacy_level = 3, category = "media",
        condition = RuleCondition(stat_thresholds={"openness": 20}),
        effects = [
            RuleEffect("stat_adjust", {"stat": "affection", "delta": 15}),
            RuleEffect("stat_adjust", {"stat": "arousal",   "delta": 10}),
        ],
    ),
    ActionDefinition(
        action_id = "send_media", scene = "phone",
        label = "Send photo / voice note",
        description = "Send a selfie, spicy photo, or voice note.",
        intimacy_level = 3, category = "media",
        condition = RuleCondition(stat_thresholds={"openness": 25}),
        effects = [
            RuleEffect("stat_adjust", {"stat": "openness",  "delta": 8}),
            RuleEffect("stat_adjust", {"stat": "arousal",   "delta": 12}),
        ],
    ),
    ActionDefinition(
        action_id = "roleplay_text", scene = "phone",
        label = "Text roleplay",
        description = "Extended creative text roleplay scenario.",
        intimacy_level = 4, category = "verbal",
        condition = RuleCondition(stat_thresholds={"openness": 35, "arousal": 30}),
        effects = [
            RuleEffect("stat_adjust", {"stat": "arousal",    "delta": 20}),
            RuleEffect("stat_adjust", {"stat": "openness",   "delta": 15}),
        ],
    ),
]


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON
# ══════════════════════════════════════════════════════════════════════

_ENGINE_INSTANCE: Optional[SceneRulesEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_rules_engine() -> SceneRulesEngine:
    """
    Return the global SceneRulesEngine singleton.
    Thread-safe, safe to call from any context.
    """
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        with _ENGINE_LOCK:
            if _ENGINE_INSTANCE is None:
                _ENGINE_INSTANCE = SceneRulesEngine()
    return _ENGINE_INSTANCE
