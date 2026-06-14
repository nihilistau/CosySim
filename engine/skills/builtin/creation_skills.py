"""
Creation Kit Skills — LLM-accessible wrappers for the Creation Kit pipeline.
=============================================================================

Provides skills for listing components, managing layouts, exporting scenes,
and working with scene templates. All operations delegate to the existing
Creation Kit engine modules.

Version: v1.49.2 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.2 [2026-03-22] — Initial creation skill pack
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ──── Lazy accessors ─────────────────────────────────────────────────────────

def _registry():
    from engine.creation.component_registry import get_categories, list_components, get_component
    return get_categories, list_components, get_component


def _layouts_dir():
    from pathlib import Path
    d = Path(__file__).resolve().parent.parent.parent.parent / "content" / "scenes" / "creation_kit" / "data" / "layouts"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ──── Component Skills ───────────────────────────────────────────────────────

@skill(
    pack="creation",
    description="List all available Creation Kit components, optionally filtered by category.",
    category="SYSTEM",
    tags=["creation", "component", "ui"],
)
def list_creation_components(category: str = "") -> str:
    """List all Creation Kit components.

    Args:
        category: Optional category filter (Layout, Display, Input, Data, Media, Game, Navigation).

    Returns:
        JSON list of component summaries.
    """
    get_categories, list_components, _ = _registry()
    all_components = list_components()
    if category:
        all_components = [c for c in all_components if c.get("category", "").lower() == category.lower()]
    summary = [{"type": c["type"], "label": c["label"], "category": c["category"]} for c in all_components]
    return json.dumps(summary, indent=2)


@skill(
    pack="creation",
    description="Get detailed info about a specific Creation Kit component including its properties and HTML template.",
    category="SYSTEM",
    tags=["creation", "component"],
)
def get_creation_component(component_type: str) -> str:
    """Get full details for a component type.

    Args:
        component_type: The component type ID (e.g. 'glass_panel', 'text_block').

    Returns:
        JSON with component definition including props, template, and slots.
    """
    _, _, get_component = _registry()
    comp = get_component(component_type)
    if comp is None:
        return json.dumps({"error": f"Component '{component_type}' not found"})
    return json.dumps(comp, indent=2)


@skill(
    pack="creation",
    description="List all available component categories and their component counts.",
    category="SYSTEM",
    tags=["creation", "component", "category"],
)
def list_creation_categories() -> str:
    """List all component categories with counts.

    Returns:
        JSON list of categories with component counts.
    """
    get_categories, _, _ = _registry()
    cats = get_categories()
    return json.dumps(cats, indent=2)


# ──── Layout Skills ──────────────────────────────────────────────────────────

@skill(
    pack="creation",
    description="List all saved Creation Kit layouts.",
    category="SYSTEM",
    tags=["creation", "layout"],
)
def list_layouts() -> str:
    """List all saved layout files.

    Returns:
        JSON list of layout names and file sizes.
    """
    layouts_dir = _layouts_dir()
    layouts = []
    for f in sorted(layouts_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            layouts.append({
                "name": f.stem,
                "file": f.name,
                "component_count": len(data.get("components", [])),
                "size_bytes": f.stat().st_size,
            })
        except Exception as exc:
            logger.debug("Failed to read layout %s: %s", f.name, exc)
    return json.dumps(layouts, indent=2)


@skill(
    pack="creation",
    description="Load a saved Creation Kit layout by name.",
    category="SYSTEM",
    tags=["creation", "layout"],
)
def load_layout(name: str) -> str:
    """Load a layout JSON by name.

    Args:
        name: Layout name (without .json extension).

    Returns:
        JSON layout data.
    """
    layouts_dir = _layouts_dir()
    path = layouts_dir / f"{name}.json"
    if not path.exists():
        return json.dumps({"error": f"Layout '{name}' not found"})
    return path.read_text(encoding="utf-8")


@skill(
    pack="creation",
    description="Save a Creation Kit layout.",
    category="SYSTEM",
    tags=["creation", "layout"],
    cooldown=2.0,
)
def save_layout(name: str, layout_json: str) -> str:
    """Save a layout to disk.

    Args:
        name: Layout name (without .json extension).
        layout_json: JSON string of the layout data.

    Returns:
        Confirmation message.
    """
    layouts_dir = _layouts_dir()
    path = layouts_dir / f"{name}.json"
    try:
        data = json.loads(layout_json)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return f"Layout '{name}' saved ({len(data.get('components', []))} components)"
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc}"


@skill(
    pack="creation",
    description="Delete a saved Creation Kit layout.",
    category="SYSTEM",
    tags=["creation", "layout"],
    cooldown=5.0,
)
def delete_layout(name: str) -> str:
    """Delete a layout from disk.

    Args:
        name: Layout name (without .json extension).

    Returns:
        Confirmation or error message.
    """
    layouts_dir = _layouts_dir()
    path = layouts_dir / f"{name}.json"
    if not path.exists():
        return f"Layout '{name}' not found"
    path.unlink()
    return f"Layout '{name}' deleted"


# ──── Export Skills ──────────────────────────────────────────────────────────

@skill(
    pack="creation",
    description="Export a Creation Kit layout to a full scene directory with Python, HTML, JS, CSS, and test files.",
    category="SYSTEM",
    tags=["creation", "export", "scene"],
    cooldown=10.0,
    cost=3.0,
)
def export_layout_to_scene(layout_name: str, scene_name: str) -> str:
    """Export a saved layout as a complete new scene.

    Args:
        layout_name: Name of the saved layout to export.
        scene_name: Name for the new scene directory.

    Returns:
        Result message with created file paths.
    """
    try:
        from engine.creation.scene_template import create_scene
        result = create_scene(scene_name)
        return json.dumps(result, indent=2)
    except Exception as exc:
        logger.error("Export layout to scene failed: %s", exc)
        return f"Export failed: {exc}"


# ──── Template Skills ────────────────────────────────────────────────────────

@skill(
    pack="creation",
    description="List available scene templates (pre-built layout patterns).",
    category="SYSTEM",
    tags=["creation", "template"],
)
def list_scene_templates() -> str:
    """List all available scene template layouts.

    Returns:
        JSON list of template names and descriptions.
    """
    layouts = list_layouts()
    return layouts  # Templates are stored as layouts
