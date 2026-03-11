"""
AnimationConfig — YAML-driven animation configuration loader.

Loads and merges animation configs from YAML files:
- animations.yaml: state machine, expressions, procedural params
- interactions.yaml: location/action mappings, chains, transitions
- characters.yaml: character body dimensions and material configs
- outfits.yaml: outfit definitions and layer mappings
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


class AnimationConfig:
    """YAML-driven animation configuration for a scene.

    Args:
        config_dir: Path to the scene's config directory (e.g. 'config/penthouse').
    """

    def __init__(self, config_dir: str) -> None:
        self.config_dir = config_dir
        self._cache: Dict[str, Any] = {}
        self._load_all()

    def _load_yaml(self, name: str) -> Dict[str, Any]:
        """Load a YAML file by name from the config directory."""
        path = os.path.join(self.config_dir, f"{name}.yaml")
        if not os.path.exists(path):
            logger.warning("Config file not found: %s", path)
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            logger.error("Failed to load %s: %s", path, exc)
            return {}

    def _load_all(self) -> None:
        """Load all animation-related configs."""
        self._cache = {
            "animations": self._load_yaml("animations"),
            "interactions": self._load_yaml("interactions"),
            "characters": self._load_yaml("characters"),
            "outfits": self._load_yaml("outfits"),
            "scene": self._load_yaml("scene"),
        }

    def reload(self) -> None:
        """Reload all configs from disk."""
        self._cache.clear()
        self._load_all()
        logger.info("Animation config reloaded from %s", self.config_dir)

    def get(self, dotpath: str, default: Any = None) -> Any:
        """Get a config value by dot-notation path.

        Args:
            dotpath: Dot-separated path like 'animations.idle.breathing.speed'.
            default: Default value if path not found.

        Returns:
            The config value or default.
        """
        parts = dotpath.split(".")
        current: Any = self._cache
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    # ── State Machine Helpers ──

    def get_state_category(self, state: str) -> Optional[str]:
        """Get the category name for an animation state."""
        categories = self.get("animations.state_categories", {})
        for cat_name, cat_data in categories.items():
            if state in cat_data.get("states", []):
                return cat_name
        return None

    def get_state_priority(self, state: str) -> int:
        """Get the priority level for an animation state."""
        categories = self.get("animations.state_categories", {})
        for cat_data in categories.values():
            if state in cat_data.get("states", []):
                return cat_data.get("priority", 0)
        return 0

    def get_blend_duration(self, from_state: str, to_state: str) -> float:
        """Get the blend duration for a state transition."""
        overrides = self.get("animations.blend_overrides", {})
        key = f"{from_state} -> {to_state}"
        if key in overrides:
            return overrides[key]
        any_key = f"any -> {to_state}"
        if any_key in overrides:
            return overrides[any_key]
        from_any_key = f"{from_state} -> any"
        if from_any_key in overrides:
            return overrides[from_any_key]
        return overrides.get("default", 0.6)

    # ── Interaction Helpers ──

    def get_location_interactions(self, location_id: str) -> Dict[str, Any]:
        """Get all available interactions for a location."""
        locations = self.get("interactions.locations", {})
        loc = locations.get(location_id, {})
        return loc.get("interactions", {})

    def get_location_default_state(self, location_id: str) -> str:
        """Get the default animation state for a location."""
        locations = self.get("interactions.locations", {})
        loc = locations.get(location_id, {})
        return loc.get("default_state", "idle")

    def get_interaction_state(
        self, location_id: str, action: str
    ) -> Tuple[str, str]:
        """Get the animation state and expression for a location+action pair.

        Args:
            location_id: Location identifier (e.g. 'bed', 'couch').
            action: Action name (e.g. 'sleep', 'cuddle').

        Returns:
            Tuple of (animation_state, expression).
        """
        interactions = self.get_location_interactions(location_id)
        if action in interactions:
            entry = interactions[action]
            return entry.get("state", "idle"), entry.get("expression", "neutral")

        universal = self.get("interactions.universal", {})
        if action in universal:
            entry = universal[action]
            return entry.get("state", "idle"), entry.get("expression", "neutral")

        return self.get_location_default_state(location_id), "neutral"

    def is_paired_interaction(self, location_id: str, action: str) -> bool:
        """Check if an interaction requires two characters."""
        interactions = self.get_location_interactions(location_id)
        if action in interactions:
            return interactions[action].get("paired", False)
        universal = self.get("interactions.universal", {})
        if action in universal:
            return universal[action].get("paired", False)
        return False

    def get_interaction_chain(self, chain_name: str) -> List[Dict[str, Any]]:
        """Get the steps for an interaction chain sequence."""
        chains = self.get("interactions.chains", {})
        chain = chains.get(chain_name, {})
        return chain.get("steps", [])

    # ── Paired Animation Helpers ──

    def get_paired_config(self, animation: str) -> Dict[str, Any]:
        """Get paired animation configuration."""
        return self.get(f"animations.paired_animations.{animation}", {})

    # ── Expression Helpers ──

    def get_expression(self, name: str) -> Dict[str, float]:
        """Get expression morph values by name."""
        return self.get(f"animations.expressions.{name}", {})

    def get_all_expressions(self) -> Dict[str, Dict[str, Any]]:
        """Get all expression definitions."""
        return self.get("animations.expressions", {})

    # ── Outfit Helpers ──

    def get_outfit(self, outfit_name: str) -> Dict[str, Any]:
        """Get outfit definition by name."""
        outfits = self.get("outfits.outfits", {})
        return outfits.get(outfit_name, {})

    def get_all_outfits(self) -> Dict[str, Any]:
        """Get all outfit definitions."""
        return self.get("outfits.outfits", {})

    # ── Character Helpers ──

    def get_character_config(self, character_id: str) -> Dict[str, Any]:
        """Get character configuration by ID."""
        chars = self.get("characters.characters", {})
        return chars.get(character_id, {})

    def get_all_characters(self) -> Dict[str, Any]:
        """Get all character configurations."""
        return self.get("characters.characters", {})

    # ── Full Config Export ──

    def as_dict(self) -> Dict[str, Any]:
        """Return all configs as a single dictionary (for API serialization)."""
        return dict(self._cache)
