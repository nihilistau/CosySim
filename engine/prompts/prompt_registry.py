"""
prompt_registry.py — Central registry for prompt templates with versioning and metrics.

Manages prompt templates stored as YAML files, supports variable substitution
with ``{{variable}}`` and ``{{variable:default}}`` syntax, tracks usage and
quality scores for A/B testing, and syncs templates to Nexus.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# ──── Variable Extraction ────────────────────────────────────────────

_VAR_PATTERN = re.compile(r"\{\{(\w+)(?::([^}]*))?\}\}")


def extract_variables(template: str) -> List[str]:
    """Extract ``{{variable}}`` and ``{{variable:default}}`` names from text.

    Args:
        template: Template string with ``{{var}}`` placeholders.

    Returns:
        Deduplicated list of variable names in discovery order.
    """
    seen: set[str] = set()
    result: List[str] = []
    for match in _VAR_PATTERN.finditer(template):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def extract_defaults(template: str) -> Dict[str, str]:
    """Extract default values from ``{{variable:default}}`` placeholders.

    Args:
        template: Template string with optional defaults.

    Returns:
        Mapping of variable name → default value (only for vars that have one).
    """
    defaults: Dict[str, str] = {}
    for match in _VAR_PATTERN.finditer(template):
        name, default = match.group(1), match.group(2)
        if default is not None:
            defaults[name] = default
    return defaults


# ──── PromptTemplate Dataclass ───────────────────────────────────────

@dataclass
class PromptTemplate:
    """A versioned prompt template with usage tracking.

    Attributes:
        id: Unique identifier (kebab-case).
        name: Human-readable display name.
        template: Template text with ``{{variable}}`` placeholders.
        category: One of system, character, scene, task, evaluation.
        version: Auto-incrementing version number.
        variables: Extracted variable names from template text.
        tags: Free-form tags for discovery.
        metadata: Arbitrary extra metadata.
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-update timestamp.
        quality_score: Rolling quality score (0-1) from A/B feedback.
        usage_count: Total number of render/expand calls.
    """

    id: str
    name: str
    template: str
    category: str
    version: int = 1
    variables: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    quality_score: float = 0.0
    usage_count: int = 0

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.variables:
            self.variables = extract_variables(self.template)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptTemplate":
        """Deserialize from a plain dictionary.

        Args:
            data: Dictionary with template fields.

        Returns:
            A new PromptTemplate instance.
        """
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


# ──── PromptRegistry ─────────────────────────────────────────────────

class PromptRegistry:
    """Central registry for prompt templates with versioning and metrics.

    Thread-safe. Templates are stored in memory and backed by YAML files
    in the ``prompts/templates/`` directory.

    Args:
        prompts_dir: Root directory for prompt YAML files.
    """

    def __init__(self, prompts_dir: str = "prompts") -> None:
        self._prompts_dir = Path(prompts_dir)
        self._templates_dir = self._prompts_dir / "templates"
        # id → {version → PromptTemplate}
        self._versions: Dict[str, Dict[int, PromptTemplate]] = {}
        # id → latest version number
        self._latest: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._load_builtin_templates()

    # ──── Registration ───────────────────────────────────────────────

    def register(self, template: PromptTemplate) -> None:
        """Register a template. Bumps version if *id* already exists.

        Args:
            template: The prompt template to register.
        """
        with self._lock:
            if template.id in self._latest:
                new_version = self._latest[template.id] + 1
                template.version = new_version
                template.updated_at = datetime.now(timezone.utc).isoformat()
            else:
                template.version = max(template.version, 1)

            self._versions.setdefault(template.id, {})[template.version] = template
            self._latest[template.id] = template.version
            logger.info(
                "Registered template '%s' v%d", template.id, template.version
            )

    # ──── Retrieval ──────────────────────────────────────────────────

    def get(self, template_id: str, version: int = -1) -> Optional[PromptTemplate]:
        """Return a template by id. ``version=-1`` returns the latest.

        Args:
            template_id: Template identifier.
            version: Specific version, or -1 for latest.

        Returns:
            The matching PromptTemplate, or None if not found.
        """
        with self._lock:
            versions = self._versions.get(template_id)
            if not versions:
                return None
            if version == -1:
                version = self._latest[template_id]
            return versions.get(version)

    # ──── Rendering ──────────────────────────────────────────────────

    def render(self, template_id: str, **variables: Any) -> str:
        """Render a template with variable substitution.

        Unknown variables are filled from their default values when
        available, or left as ``{{variable}}`` placeholders.

        Args:
            template_id: Template identifier.
            **variables: Variable name-value pairs.

        Returns:
            The rendered prompt string.

        Raises:
            KeyError: If *template_id* is not registered.
        """
        tpl = self.get(template_id)
        if tpl is None:
            raise KeyError(f"Template '{template_id}' not found")

        with self._lock:
            tpl.usage_count += 1

        defaults = extract_defaults(tpl.template)
        merged = {**defaults, **variables}

        def _replacer(match: re.Match) -> str:
            name = match.group(1)
            if name in merged:
                return str(merged[name])
            # Leave placeholder intact when no value or default
            return match.group(0)

        return _VAR_PATTERN.sub(_replacer, tpl.template)

    # ──── Expansion ──────────────────────────────────────────────────

    def expand(
        self, template_id: str, variations: List[Dict[str, str]]
    ) -> List[str]:
        """Render one template with multiple variable sets.

        Args:
            template_id: Template identifier.
            variations: List of variable-set dicts.

        Returns:
            List of rendered prompt strings.
        """
        return [self.render(template_id, **v) for v in variations]

    # ──── Search ─────────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
    ) -> List[PromptTemplate]:
        """Search templates by query string, category, or tags.

        Args:
            query: Substring to match against id, name, or template text.
            category: Filter by category (exact match).
            tags: Filter by tags (all supplied tags must be present).

        Returns:
            List of matching PromptTemplate objects (latest versions only).
        """
        results: List[PromptTemplate] = []
        query_lower = query.lower()
        tags_set = set(tags) if tags else set()

        with self._lock:
            for tid, ver in self._latest.items():
                tpl = self._versions[tid][ver]
                if category and tpl.category != category:
                    continue
                if tags_set and not tags_set.issubset(set(tpl.tags)):
                    continue
                if query_lower:
                    searchable = f"{tpl.id} {tpl.name} {tpl.template}".lower()
                    if query_lower not in searchable:
                        continue
                results.append(tpl)
        return results

    # ──── Categories ─────────────────────────────────────────────────

    def list_categories(self) -> List[str]:
        """Return sorted list of all unique categories.

        Returns:
            List of category strings.
        """
        with self._lock:
            cats = {
                self._versions[tid][ver].category
                for tid, ver in self._latest.items()
            }
        return sorted(cats)

    # ──── Usage Tracking ─────────────────────────────────────────────

    def record_usage(self, template_id: str, quality: float = 0.0) -> None:
        """Record a usage event and optional quality score.

        Quality is averaged using exponential moving average (α=0.3).

        Args:
            template_id: Template identifier.
            quality: Quality score between 0.0 and 1.0.
        """
        tpl = self.get(template_id)
        if tpl is None:
            logger.warning("Cannot record usage for unknown template '%s'", template_id)
            return

        quality = max(0.0, min(1.0, quality))
        with self._lock:
            tpl.usage_count += 1
            if quality > 0.0:
                alpha = 0.3
                if tpl.quality_score == 0.0:
                    tpl.quality_score = quality
                else:
                    tpl.quality_score = alpha * quality + (1 - alpha) * tpl.quality_score

    # ──── Statistics ─────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return registry statistics.

        Returns:
            Dict with total count, category breakdown, top-used, and top-quality.
        """
        with self._lock:
            templates = [
                self._versions[tid][ver]
                for tid, ver in self._latest.items()
            ]

        by_category: Dict[str, int] = {}
        for t in templates:
            by_category[t.category] = by_category.get(t.category, 0) + 1

        sorted_by_usage = sorted(templates, key=lambda t: t.usage_count, reverse=True)
        sorted_by_quality = sorted(
            [t for t in templates if t.quality_score > 0],
            key=lambda t: t.quality_score,
            reverse=True,
        )

        return {
            "total_templates": len(templates),
            "by_category": by_category,
            "total_versions": sum(
                len(v) for v in self._versions.values()
            ),
            "top_used": [
                {"id": t.id, "usage_count": t.usage_count}
                for t in sorted_by_usage[:5]
            ],
            "top_quality": [
                {"id": t.id, "quality_score": round(t.quality_score, 3)}
                for t in sorted_by_quality[:5]
            ],
        }

    # ──── YAML Export/Import ─────────────────────────────────────────

    def export_to_yaml(self, template_id: str, path: str = "") -> str:
        """Export a template to a YAML file.

        Args:
            template_id: Template identifier.
            path: Output file path. Defaults to ``prompts/templates/{id}.yaml``.

        Returns:
            The path the file was written to.

        Raises:
            KeyError: If *template_id* is not registered.
        """
        tpl = self.get(template_id)
        if tpl is None:
            raise KeyError(f"Template '{template_id}' not found")

        if not path:
            self._templates_dir.mkdir(parents=True, exist_ok=True)
            path = str(self._templates_dir / f"{template_id}.yaml")

        data = tpl.to_dict()
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        logger.info("Exported template '%s' to %s", template_id, path)
        return path

    def import_from_yaml(self, path: str) -> PromptTemplate:
        """Import a template from a YAML file and register it.

        Args:
            path: Path to the YAML file.

        Returns:
            The imported PromptTemplate.

        Raises:
            FileNotFoundError: If *path* does not exist.
        """
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        tpl = PromptTemplate.from_dict(data)
        self.register(tpl)
        logger.info("Imported template '%s' from %s", tpl.id, path)
        return tpl

    # ──── Nexus Sync ─────────────────────────────────────────────────

    def sync_to_nexus(self) -> int:
        """Sync all templates to Nexus knowledge base.

        Returns:
            Number of templates successfully synced.
        """
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception:
            logger.warning("Nexus client unavailable — skipping sync")
            return 0

        count = 0
        with self._lock:
            items = [
                (tid, self._versions[tid][ver])
                for tid, ver in self._latest.items()
            ]

        for tid, tpl in items:
            try:
                content = yaml.dump(tpl.to_dict(), default_flow_style=False)
                client.add_entry(
                    title=f"Prompt: {tpl.name}",
                    content=content,
                    content_type="prompt",
                    category=tpl.category,
                    tags=["prompt-registry", *tpl.tags],
                    created_by="prompt_registry",
                )
                count += 1
            except Exception:
                logger.debug("Failed to sync template '%s' to Nexus", tid, exc_info=True)
        logger.info("Synced %d/%d templates to Nexus", count, len(items))
        return count

    # ──── Built-in Template Loading ──────────────────────────────────

    def _load_builtin_templates(self) -> None:
        """Load YAML templates from the templates directory."""
        if not self._templates_dir.is_dir():
            logger.debug("Templates directory '%s' does not exist", self._templates_dir)
            return

        loaded = 0
        for yaml_file in sorted(self._templates_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if data and isinstance(data, dict) and "id" in data:
                    tpl = PromptTemplate.from_dict(data)
                    self.register(tpl)
                    loaded += 1
            except Exception:
                logger.warning("Failed to load template from '%s'", yaml_file, exc_info=True)
        if loaded:
            logger.info("Loaded %d built-in templates from '%s'", loaded, self._templates_dir)


# ──── Singleton ──────────────────────────────────────────────────────

_registry_instance: Optional[PromptRegistry] = None
_registry_lock = threading.Lock()


def get_prompt_registry(prompts_dir: str = "prompts") -> PromptRegistry:
    """Return the singleton PromptRegistry instance.

    Args:
        prompts_dir: Root prompts directory (only used on first call).

    Returns:
        The global PromptRegistry.
    """
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = PromptRegistry(prompts_dir=prompts_dir)
    return _registry_instance


def _reset_registry() -> None:
    """Reset singleton — for testing only."""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None
