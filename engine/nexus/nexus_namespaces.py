"""
nexus_namespaces.py — Namespace separation and validation for Nexus KMS.

Defines the knowledge namespace hierarchy, enforces proper categorization,
and provides helpers for safe, tagged, separated knowledge management.

Namespaces:
    system:     — Core engine, framework, infrastructure
    scene:      — Scene-specific state, rules, content
    agent:      — Agent personalities, behaviors, memories
    copilot:    — Copilot CLI sessions, decisions, prompts
    training:   — Fine-tuning data, datasets, model configs
    research:   — Research sessions, design docs, analysis
    content:    — Pre-built dialog, descriptions, assets

Each namespace has rules governing what can be stored, who can access it,
and how it interacts with other namespaces.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  Namespace Definitions
# ══════════════════════════════════════════════════════════════════════

@dataclass
class NexusNamespace:
    """Defines a knowledge namespace with its rules and constraints."""

    name: str
    description: str
    allowed_types: Set[str]
    required_tags: Set[str] = field(default_factory=set)
    allowed_categories: Set[str] = field(default_factory=set)
    can_read_from: Set[str] = field(default_factory=set)
    can_write_to: Set[str] = field(default_factory=set)
    auto_tags: List[str] = field(default_factory=list)


NAMESPACES: Dict[str, NexusNamespace] = {
    "system": NexusNamespace(
        name="system",
        description="Core engine, framework, infrastructure knowledge",
        allowed_types={"document", "code", "note", "prompt"},
        required_tags={"system"},
        allowed_categories={
            "architecture", "infrastructure", "system",
            "conventions", "tools", "api",
        },
        can_read_from={"system"},
        can_write_to={"system"},
        auto_tags=["system"],
    ),
    "scene": NexusNamespace(
        name="scene",
        description="Scene-specific state, rules, content, game logic",
        allowed_types={"document", "code", "note", "prompt", "memory"},
        required_tags={"scene"},
        allowed_categories={
            "scene", "game", "world", "narrative",
            "characters", "environment",
        },
        can_read_from={"system", "scene", "content"},
        can_write_to={"scene"},
        auto_tags=["scene"],
    ),
    "agent": NexusNamespace(
        name="agent",
        description="Agent personalities, behaviors, memories, interaction patterns",
        allowed_types={"prompt", "memory", "note", "document", "code"},
        required_tags={"agent"},
        allowed_categories={
            "agents", "personality", "behavior", "memory",
            "dialog", "interaction",
        },
        can_read_from={"system", "scene", "agent", "content"},
        can_write_to={"agent"},
        auto_tags=["agent"],
    ),
    "copilot": NexusNamespace(
        name="copilot",
        description="Copilot CLI sessions, decisions, prompts, workflow artifacts",
        allowed_types={"history", "note", "prompt", "document", "code"},
        required_tags={"copilot"},
        allowed_categories={
            "sessions", "development", "decisions",
            "debugging", "architecture",
            # Extended: Copilot-specific subcategories
            "copilot-rules", "copilot-history", "copilot-decisions",
            "copilot-plans", "copilot-micro-versions",
        },
        can_read_from={"system", "copilot", "research"},
        can_write_to={"copilot"},
        auto_tags=["copilot"],
    ),
    "training": NexusNamespace(
        name="training",
        description="Fine-tuning data, datasets, model configs, training artifacts",
        allowed_types={"code", "document", "note", "snippet"},
        required_tags={"training"},
        allowed_categories={
            "training", "datasets", "finetuning",
            "models", "evaluation",
        },
        can_read_from={"system", "training", "agent"},
        can_write_to={"training"},
        auto_tags=["training"],
    ),
    "research": NexusNamespace(
        name="research",
        description="Research sessions, design documents, analysis, deep dives",
        allowed_types={"document", "research", "note", "transcript"},
        required_tags={"research"},
        allowed_categories={
            "research", "architecture", "analysis",
            "design", "exploration",
        },
        can_read_from={"system", "research", "copilot"},
        can_write_to={"research"},
        auto_tags=["research"],
    ),
    "content": NexusNamespace(
        name="content",
        description="Pre-built dialog, descriptions, assets for character use",
        allowed_types={"document", "note", "snippet", "code"},
        required_tags={"content"},
        allowed_categories={
            "dialog", "descriptions", "responses",
            "templates", "assets",
        },
        can_read_from={"content", "system"},
        can_write_to={"content"},
        auto_tags=["content"],
    ),
}

# All valid namespace names
VALID_NAMESPACES = set(NAMESPACES.keys())

# All valid content types across all namespaces
ALL_CONTENT_TYPES = {
    "note", "document", "code", "prompt", "memory",
    "history", "snippet", "research", "transcript",
    "plan", "profile",
}

# All valid categories across all namespaces
ALL_CATEGORIES = set()
for ns in NAMESPACES.values():
    ALL_CATEGORIES.update(ns.allowed_categories)


# ══════════════════════════════════════════════════════════════════════
#  Validation
# ══════════════════════════════════════════════════════════════════════

def detect_namespace(category: str, tags: List[str]) -> str:
    """Detect the most likely namespace from category and tags.

    Args:
        category: The entry's category string.
        tags: List of tags on the entry.

    Returns:
        Detected namespace name, or 'system' as default.
    """
    tag_set = set(tags) if tags else set()

    # Direct namespace tag match (highest priority)
    for ns_name in VALID_NAMESPACES:
        if ns_name in tag_set:
            return ns_name

    # Category-based detection
    for ns_name, ns in NAMESPACES.items():
        if category in ns.allowed_categories:
            return ns_name

    return "system"


def validate_entry(
    title: str,
    content_type: str,
    category: str,
    tags: List[str],
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate an entry against namespace rules.

    Args:
        title: Entry title.
        content_type: Entry content type.
        category: Entry category.
        tags: Entry tags.
        namespace: Explicit namespace (auto-detected if None).

    Returns:
        Dict with 'valid' bool, 'namespace', 'errors', 'warnings', 'fixed_tags'.
    """
    errors: List[str] = []
    warnings: List[str] = []
    tag_set = set(tags) if tags else set()

    # Auto-detect namespace if not provided
    if namespace is None:
        namespace = detect_namespace(category, tags)

    ns = NAMESPACES.get(namespace)
    if ns is None:
        errors.append(f"Unknown namespace: {namespace}")
        return {
            "valid": False,
            "namespace": namespace,
            "errors": errors,
            "warnings": warnings,
            "fixed_tags": list(tag_set),
        }

    # Validate content type
    if content_type not in ns.allowed_types:
        warnings.append(
            f"Content type '{content_type}' not typical for namespace '{namespace}'. "
            f"Expected: {sorted(ns.allowed_types)}"
        )

    # Validate category
    if category and category not in ns.allowed_categories:
        warnings.append(
            f"Category '{category}' not typical for namespace '{namespace}'. "
            f"Expected: {sorted(ns.allowed_categories)}"
        )

    # Ensure namespace tag is present
    fixed_tags = tag_set.copy()
    for auto_tag in ns.auto_tags:
        fixed_tags.add(auto_tag)

    # Check required tags
    for req in ns.required_tags:
        if req not in fixed_tags:
            fixed_tags.add(req)
            warnings.append(f"Auto-added required tag: '{req}'")

    return {
        "valid": len(errors) == 0,
        "namespace": namespace,
        "errors": errors,
        "warnings": warnings,
        "fixed_tags": sorted(fixed_tags),
    }


def enforce_namespace(
    title: str,
    content: str,
    content_type: str = "note",
    category: str = "development",
    tags: Optional[List[str]] = None,
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate and fix an entry for proper namespace compliance.

    Returns the corrected entry dict ready for Nexus API submission.

    Args:
        title: Entry title.
        content: Entry content.
        content_type: Content type.
        category: Category.
        tags: Tags list.
        namespace: Explicit namespace (auto-detected if None).

    Returns:
        Dict with corrected entry fields and validation metadata.
    """
    tags = tags or []
    result = validate_entry(title, content_type, category, tags, namespace)

    for w in result.get("warnings", []):
        logger.debug("NexusNamespace: %s", w)

    return {
        "title": title,
        "content": content,
        "content_type": content_type,
        "category": category,
        "tags": result["fixed_tags"],
        "namespace": result["namespace"],
        "valid": result["valid"],
        "warnings": result["warnings"],
        "errors": result["errors"],
    }


# ══════════════════════════════════════════════════════════════════════
#  Access Control
# ══════════════════════════════════════════════════════════════════════

def can_access(reader_namespace: str, target_namespace: str) -> bool:
    """Check if a namespace can read from another namespace.

    Args:
        reader_namespace: The namespace requesting access.
        target_namespace: The namespace being accessed.

    Returns:
        True if access is allowed.
    """
    ns = NAMESPACES.get(reader_namespace)
    if ns is None:
        return False
    return target_namespace in ns.can_read_from


def get_accessible_namespaces(namespace: str) -> Set[str]:
    """Get all namespaces accessible from a given namespace.

    Args:
        namespace: The requesting namespace.

    Returns:
        Set of namespace names that can be read.
    """
    ns = NAMESPACES.get(namespace)
    if ns is None:
        return set()
    return ns.can_read_from.copy()


# ══════════════════════════════════════════════════════════════════════
#  Interaction Rules Generator
# ══════════════════════════════════════════════════════════════════════

def generate_interaction_rules() -> List[Dict[str, Any]]:
    """Generate Nexus rules that enforce namespace separation.

    Returns:
        List of rule dicts ready for POST /api/rules.
    """
    rules: List[Dict[str, Any]] = []

    for ns_name, ns in NAMESPACES.items():
        # Tagging enforcement rule
        rules.append({
            "scope": f"namespace:{ns_name}",
            "rule_type": "validation",
            "name": f"Enforce {ns_name} namespace tags",
            "condition": {
                "namespace": ns_name,
                "check": "tags_present",
                "required_tags": sorted(ns.required_tags),
            },
            "action": {
                "type": "auto_tag",
                "add_tags": ns.auto_tags,
                "warn_if_missing": True,
            },
            "priority": 100,
        })

        # Content type validation rule
        rules.append({
            "scope": f"namespace:{ns_name}",
            "rule_type": "validation",
            "name": f"Validate {ns_name} content types",
            "condition": {
                "namespace": ns_name,
                "check": "content_type",
                "allowed": sorted(ns.allowed_types),
            },
            "action": {
                "type": "warn",
                "message": f"Content type not standard for {ns_name} namespace",
            },
            "priority": 90,
        })

        # Access control rule
        rules.append({
            "scope": f"namespace:{ns_name}",
            "rule_type": "access",
            "name": f"{ns_name} read access policy",
            "condition": {
                "namespace": ns_name,
                "check": "read_access",
            },
            "action": {
                "type": "allow_read_from",
                "namespaces": sorted(ns.can_read_from),
            },
            "priority": 80,
        })

    # Global separation rule
    rules.append({
        "scope": "global",
        "rule_type": "governance",
        "name": "Namespace separation enforcement",
        "condition": {"check": "all_entries"},
        "action": {
            "type": "enforce",
            "message": (
                "All knowledge entries MUST include a namespace tag "
                f"({', '.join(sorted(VALID_NAMESPACES))}). "
                "Entries without namespace tags will be auto-tagged 'system'."
            ),
        },
        "priority": 200,
    })

    return rules
