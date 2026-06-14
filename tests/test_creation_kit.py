"""Tests for the Creation Kit — component registry, layout persistence, skills.

Version: v1.49.2 [2026-03-22]
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──── Component Registry ──────────────────────────────────────────────────────


class TestComponentRegistry:
    """Tests for engine.creation.component_registry."""

    def test_list_components_returns_list(self):
        from engine.creation.component_registry import list_components
        components = list_components()
        assert isinstance(components, list)
        assert len(components) > 0

    def test_list_components_all_have_required_fields(self):
        from engine.creation.component_registry import list_components
        required = {"type", "label", "category"}
        for comp in list_components():
            assert required.issubset(comp.keys()), f"Component {comp.get('type')} missing fields"

    def test_get_component_existing(self):
        from engine.creation.component_registry import get_component
        comp = get_component("glass_panel")
        assert comp is not None
        assert comp["type"] == "glass_panel"
        assert "label" in comp
        assert "category" in comp

    def test_get_component_nonexistent(self):
        from engine.creation.component_registry import get_component
        assert get_component("nonexistent_widget_xyz") is None

    def test_get_categories_returns_dict(self):
        from engine.creation.component_registry import get_categories
        cats = get_categories()
        assert isinstance(cats, (list, dict))

    def test_list_components_by_category(self):
        from engine.creation.component_registry import list_components
        all_comps = list_components()
        layout_comps = [c for c in all_comps if c["category"] == "layout"]
        assert len(layout_comps) > 0
        assert all(c["category"] == "layout" for c in layout_comps)

    def test_component_count_above_minimum(self):
        """Project should have at least 40 components."""
        from engine.creation.component_registry import get_component_count
        assert get_component_count() >= 40


# ──── Creation Skills ─────────────────────────────────────────────────────────


class TestCreationSkills:
    """Tests for engine.skills.builtin.creation_skills."""

    def test_list_creation_components_returns_json(self):
        from engine.skills.builtin.creation_skills import list_creation_components
        result = list_creation_components()
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_creation_components_with_category(self):
        from engine.skills.builtin.creation_skills import list_creation_components
        result = list_creation_components(category="layout")
        data = json.loads(result)
        assert all(c["category"] == "layout" for c in data)

    def test_get_creation_component_valid(self):
        from engine.skills.builtin.creation_skills import get_creation_component
        result = get_creation_component("text_block")
        data = json.loads(result)
        assert data["type"] == "text_block"

    def test_get_creation_component_invalid(self):
        from engine.skills.builtin.creation_skills import get_creation_component
        result = get_creation_component("nonexistent_xyz")
        data = json.loads(result)
        assert "error" in data

    def test_list_creation_categories(self):
        from engine.skills.builtin.creation_skills import list_creation_categories
        result = list_creation_categories()
        data = json.loads(result)
        assert isinstance(data, (list, dict))

    def test_list_layouts(self):
        from engine.skills.builtin.creation_skills import list_layouts
        result = list_layouts()
        data = json.loads(result)
        assert isinstance(data, list)


# ──── Layout Persistence ──────────────────────────────────────────────────────


class TestLayoutPersistence:
    """Tests for layout save/load via skills."""

    def test_save_and_load_layout(self, tmp_path):
        from engine.skills.builtin.creation_skills import save_layout, load_layout, _layouts_dir
        # Patch layouts dir to temp
        with patch("engine.skills.builtin.creation_skills._layouts_dir", return_value=tmp_path):
            layout = {"components": [{"type": "glass_panel", "props": {}}]}
            result = save_layout("test_layout", json.dumps(layout))
            assert "saved" in result.lower()

            loaded = load_layout("test_layout")
            data = json.loads(loaded)
            assert data["components"][0]["type"] == "glass_panel"

    def test_load_nonexistent_layout(self, tmp_path):
        from engine.skills.builtin.creation_skills import load_layout
        with patch("engine.skills.builtin.creation_skills._layouts_dir", return_value=tmp_path):
            result = load_layout("nonexistent")
            data = json.loads(result)
            assert "error" in data

    def test_delete_layout(self, tmp_path):
        from engine.skills.builtin.creation_skills import save_layout, delete_layout
        with patch("engine.skills.builtin.creation_skills._layouts_dir", return_value=tmp_path):
            save_layout("to_delete", json.dumps({"components": []}))
            result = delete_layout("to_delete")
            assert "deleted" in result.lower()

    def test_save_invalid_json(self, tmp_path):
        from engine.skills.builtin.creation_skills import save_layout
        with patch("engine.skills.builtin.creation_skills._layouts_dir", return_value=tmp_path):
            result = save_layout("bad", "not valid json {{{")
            assert "invalid" in result.lower()
