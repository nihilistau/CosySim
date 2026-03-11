"""Tests for the prompt template registry."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from engine.prompts.prompt_registry import (
    PromptRegistry,
    PromptTemplate,
    extract_defaults,
    extract_variables,
    get_prompt_registry,
    _reset_registry,
)


# ──── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the global registry singleton between tests."""
    _reset_registry()
    yield
    _reset_registry()


@pytest.fixture()
def empty_registry(tmp_path: Path) -> PromptRegistry:
    """Registry pointing at an empty directory (no built-in templates)."""
    return PromptRegistry(prompts_dir=str(tmp_path))


@pytest.fixture()
def sample_template() -> PromptTemplate:
    """A minimal template for testing."""
    return PromptTemplate(
        id="test-hello",
        name="Hello Template",
        template="Hello, {{name}}! Welcome to {{place:the world}}.",
        category="test",
        tags=["greeting", "test"],
    )


@pytest.fixture()
def loaded_registry() -> PromptRegistry:
    """Registry loaded from the real prompts/templates directory."""
    return PromptRegistry(prompts_dir="prompts")


# ──── Variable Extraction ────────────────────────────────────────────

class TestVariableExtraction:
    """Tests for extract_variables and extract_defaults."""

    def test_extract_simple_variables(self):
        """Simple {{var}} extraction."""
        text = "Hello {{name}}, you are in {{place}}."
        assert extract_variables(text) == ["name", "place"]

    def test_extract_variables_with_defaults(self):
        """Variables with defaults are still extracted."""
        text = "{{greeting:Hi}} {{name}}!"
        assert extract_variables(text) == ["greeting", "name"]

    def test_extract_defaults_returns_only_defaulted(self):
        """extract_defaults only returns vars that have a default."""
        text = "{{greeting:Hi}} {{name}} in {{place:here}}."
        defaults = extract_defaults(text)
        assert defaults == {"greeting": "Hi", "place": "here"}
        assert "name" not in defaults

    def test_extract_deduplicates(self):
        """Repeated variables appear once."""
        text = "{{x}} and {{y}} and {{x}} again."
        assert extract_variables(text) == ["x", "y"]

    def test_empty_template(self):
        """No variables in plain text."""
        assert extract_variables("No variables here.") == []

    def test_default_empty_string(self):
        """Default can be an empty string."""
        text = "{{name:}}"
        defaults = extract_defaults(text)
        assert defaults == {"name": ""}


# ──── Template Dataclass ─────────────────────────────────────────────

class TestPromptTemplate:
    """Tests for the PromptTemplate dataclass."""

    def test_auto_extracts_variables(self, sample_template: PromptTemplate):
        """Variables are auto-populated from template text."""
        assert sample_template.variables == ["name", "place"]

    def test_timestamps_auto_set(self, sample_template: PromptTemplate):
        """Timestamps are set on creation."""
        assert sample_template.created_at
        assert sample_template.updated_at

    def test_roundtrip_dict(self, sample_template: PromptTemplate):
        """to_dict → from_dict preserves fields."""
        data = sample_template.to_dict()
        restored = PromptTemplate.from_dict(data)
        assert restored.id == sample_template.id
        assert restored.name == sample_template.name
        assert restored.template == sample_template.template
        assert restored.category == sample_template.category
        assert restored.tags == sample_template.tags

    def test_from_dict_ignores_extra_keys(self):
        """Unknown keys in dict are silently dropped."""
        data = {"id": "x", "name": "X", "template": "t", "category": "c", "bogus": 99}
        tpl = PromptTemplate.from_dict(data)
        assert tpl.id == "x"
        assert not hasattr(tpl, "bogus")


# ──── Registration & Retrieval ───────────────────────────────────────

class TestRegistration:
    """Tests for register and get."""

    def test_register_and_get(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Registered template is retrievable."""
        empty_registry.register(sample_template)
        result = empty_registry.get("test-hello")
        assert result is not None
        assert result.name == "Hello Template"

    def test_get_nonexistent_returns_none(self, empty_registry: PromptRegistry):
        """Missing id returns None."""
        assert empty_registry.get("nonexistent") is None

    def test_version_increments(self, empty_registry: PromptRegistry):
        """Re-registering same id bumps version."""
        tpl1 = PromptTemplate(id="v-test", name="V1", template="First", category="test")
        tpl2 = PromptTemplate(id="v-test", name="V2", template="Second", category="test")

        empty_registry.register(tpl1)
        empty_registry.register(tpl2)

        latest = empty_registry.get("v-test")
        assert latest is not None
        assert latest.version == 2
        assert latest.name == "V2"

        v1 = empty_registry.get("v-test", version=1)
        assert v1 is not None
        assert v1.name == "V1"

    def test_get_specific_version(self, empty_registry: PromptRegistry):
        """Can retrieve a specific older version."""
        for i in range(1, 4):
            tpl = PromptTemplate(
                id="multi", name=f"V{i}", template=f"Version {i}", category="test"
            )
            empty_registry.register(tpl)

        assert empty_registry.get("multi", version=2).name == "V2"
        assert empty_registry.get("multi").name == "V3"  # latest


# ──── Rendering ──────────────────────────────────────────────────────

class TestRendering:
    """Tests for render and variable substitution."""

    def test_basic_render(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Variables are substituted in render."""
        empty_registry.register(sample_template)
        result = empty_registry.render("test-hello", name="Alice", place="Wonderland")
        assert "Hello, Alice!" in result
        assert "Welcome to Wonderland." in result

    def test_render_uses_defaults(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Missing variable with default uses the default."""
        empty_registry.register(sample_template)
        result = empty_registry.render("test-hello", name="Bob")
        assert "Welcome to the world." in result

    def test_render_leaves_placeholder_without_default(self, empty_registry: PromptRegistry):
        """Variable without value or default stays as placeholder."""
        tpl = PromptTemplate(
            id="no-default", name="T", template="Hi {{name}}!", category="test"
        )
        empty_registry.register(tpl)
        result = empty_registry.render("no-default")
        assert "{{name}}" in result

    def test_render_unknown_template_raises(self, empty_registry: PromptRegistry):
        """Rendering a nonexistent template raises KeyError."""
        with pytest.raises(KeyError, match="not-found"):
            empty_registry.render("not-found")

    def test_render_increments_usage(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Each render call increments usage_count."""
        empty_registry.register(sample_template)
        empty_registry.render("test-hello", name="A")
        empty_registry.render("test-hello", name="B")
        tpl = empty_registry.get("test-hello")
        assert tpl.usage_count == 2


# ──── Expansion ──────────────────────────────────────────────────────

class TestExpansion:
    """Tests for expand with multiple variable sets."""

    def test_expand_produces_correct_count(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Expand returns one result per variation."""
        empty_registry.register(sample_template)
        variations = [
            {"name": "Alice", "place": "Paris"},
            {"name": "Bob", "place": "London"},
            {"name": "Carol", "place": "Tokyo"},
        ]
        results = empty_registry.expand("test-hello", variations)
        assert len(results) == 3
        assert "Alice" in results[0]
        assert "London" in results[1]
        assert "Tokyo" in results[2]

    def test_expand_empty_variations(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Empty variations list returns empty list."""
        empty_registry.register(sample_template)
        assert empty_registry.expand("test-hello", []) == []


# ──── Search ─────────────────────────────────────────────────────────

class TestSearch:
    """Tests for search by query, category, and tags."""

    def _register_set(self, registry: PromptRegistry) -> None:
        """Helper to register a diverse set of templates."""
        templates = [
            PromptTemplate(id="s1", name="System One", template="sys", category="system", tags=["core"]),
            PromptTemplate(id="s2", name="System Two", template="sys", category="system", tags=["core", "agent"]),
            PromptTemplate(id="c1", name="Char Dialog", template="char", category="character", tags=["dialog"]),
            PromptTemplate(id="t1", name="Task Eval", template="task evaluation", category="task", tags=["eval"]),
        ]
        for t in templates:
            registry.register(t)

    def test_search_by_category(self, empty_registry: PromptRegistry):
        """Category filter returns only matching templates."""
        self._register_set(empty_registry)
        results = empty_registry.search(category="system")
        assert len(results) == 2
        assert all(r.category == "system" for r in results)

    def test_search_by_query(self, empty_registry: PromptRegistry):
        """Query matches against id, name, or template text."""
        self._register_set(empty_registry)
        results = empty_registry.search(query="Dialog")
        assert len(results) == 1
        assert results[0].id == "c1"

    def test_search_by_tags(self, empty_registry: PromptRegistry):
        """Tag filter requires all supplied tags to be present."""
        self._register_set(empty_registry)
        results = empty_registry.search(tags=["core", "agent"])
        assert len(results) == 1
        assert results[0].id == "s2"

    def test_search_combined_filters(self, empty_registry: PromptRegistry):
        """Category + query work together."""
        self._register_set(empty_registry)
        results = empty_registry.search(query="One", category="system")
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_search_no_match(self, empty_registry: PromptRegistry):
        """No matches returns empty list."""
        self._register_set(empty_registry)
        assert empty_registry.search(query="zzz_nonexistent") == []


# ──── Categories ─────────────────────────────────────────────────────

class TestCategories:
    """Tests for list_categories."""

    def test_list_categories(self, empty_registry: PromptRegistry):
        """Lists all unique categories sorted."""
        for cat in ["system", "character", "task", "system"]:
            tpl = PromptTemplate(
                id=f"cat-{cat}-{id(cat)}", name=cat, template="t", category=cat
            )
            empty_registry.register(tpl)
        cats = empty_registry.list_categories()
        assert cats == ["character", "system", "task"]


# ──── Usage Tracking ─────────────────────────────────────────────────

class TestUsageTracking:
    """Tests for record_usage and quality scores."""

    def test_record_usage_increments_count(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Usage count increases with each record_usage call."""
        empty_registry.register(sample_template)
        empty_registry.record_usage("test-hello")
        empty_registry.record_usage("test-hello")
        tpl = empty_registry.get("test-hello")
        assert tpl.usage_count >= 2

    def test_quality_score_updates(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Quality score updates with EMA."""
        empty_registry.register(sample_template)
        empty_registry.record_usage("test-hello", quality=0.8)
        tpl = empty_registry.get("test-hello")
        assert tpl.quality_score == pytest.approx(0.8, abs=0.01)

        empty_registry.record_usage("test-hello", quality=0.4)
        tpl = empty_registry.get("test-hello")
        # EMA: 0.3 * 0.4 + 0.7 * 0.8 = 0.68
        assert tpl.quality_score == pytest.approx(0.68, abs=0.01)

    def test_quality_clamped(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Quality is clamped to 0-1."""
        empty_registry.register(sample_template)
        empty_registry.record_usage("test-hello", quality=5.0)
        tpl = empty_registry.get("test-hello")
        assert tpl.quality_score <= 1.0

    def test_record_unknown_template(self, empty_registry: PromptRegistry):
        """Recording usage for unknown template is a no-op."""
        empty_registry.record_usage("nonexistent", quality=0.5)  # Should not raise


# ──── YAML Import/Export ─────────────────────────────────────────────

class TestYamlRoundTrip:
    """Tests for export_to_yaml and import_from_yaml."""

    def test_export_creates_file(self, empty_registry: PromptRegistry, sample_template: PromptTemplate, tmp_path: Path):
        """Export creates a readable YAML file."""
        empty_registry.register(sample_template)
        out = tmp_path / "exported.yaml"
        result_path = empty_registry.export_to_yaml("test-hello", path=str(out))
        assert Path(result_path).exists()

        with open(result_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["id"] == "test-hello"
        assert data["name"] == "Hello Template"

    def test_import_registers_template(self, empty_registry: PromptRegistry, tmp_path: Path):
        """Importing from YAML registers the template."""
        yaml_data = {
            "id": "imported-tpl",
            "name": "Imported",
            "template": "Hello {{who}}",
            "category": "test",
            "tags": ["import"],
        }
        yaml_file = tmp_path / "import.yaml"
        with open(yaml_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f)

        tpl = empty_registry.import_from_yaml(str(yaml_file))
        assert tpl.id == "imported-tpl"
        assert empty_registry.get("imported-tpl") is not None

    def test_roundtrip_preserves_data(self, empty_registry: PromptRegistry, sample_template: PromptTemplate, tmp_path: Path):
        """Export → import preserves all fields."""
        empty_registry.register(sample_template)
        path = empty_registry.export_to_yaml("test-hello", path=str(tmp_path / "rt.yaml"))

        other_registry = PromptRegistry(prompts_dir=str(tmp_path / "other"))
        imported = other_registry.import_from_yaml(path)

        assert imported.id == sample_template.id
        assert imported.name == sample_template.name
        assert imported.template == sample_template.template
        assert imported.category == sample_template.category
        assert imported.tags == sample_template.tags
        assert imported.variables == sample_template.variables

    def test_export_unknown_raises(self, empty_registry: PromptRegistry):
        """Exporting unknown template raises KeyError."""
        with pytest.raises(KeyError):
            empty_registry.export_to_yaml("nope")


# ──── Built-in Templates ────────────────────────────────────────────

class TestBuiltinTemplates:
    """Tests that built-in templates load correctly."""

    def test_builtin_templates_loaded(self, loaded_registry: PromptRegistry):
        """The 20 built-in templates load from prompts/templates/."""
        stats = loaded_registry.get_stats()
        assert stats["total_templates"] >= 20

    def test_all_categories_present(self, loaded_registry: PromptRegistry):
        """All five categories are represented."""
        categories = loaded_registry.list_categories()
        for expected in ["system", "character", "scene", "task", "evaluation"]:
            assert expected in categories, f"Missing category: {expected}"

    def test_system_templates_exist(self, loaded_registry: PromptRegistry):
        """All 5 system templates are present."""
        for tid in [
            "system-character-agent",
            "system-scene-narrator",
            "system-task-evaluator",
            "system-code-reviewer",
            "system-knowledge-curator",
        ]:
            tpl = loaded_registry.get(tid)
            assert tpl is not None, f"Missing template: {tid}"
            assert tpl.category == "system"

    def test_character_templates_exist(self, loaded_registry: PromptRegistry):
        """All 5 character templates are present."""
        for tid in [
            "char-dialog-base",
            "char-dialog-emotional",
            "char-greeting",
            "char-reaction",
            "char-internal-thought",
        ]:
            tpl = loaded_registry.get(tid)
            assert tpl is not None, f"Missing template: {tid}"
            assert tpl.category == "character"

    def test_builtin_templates_have_variables(self, loaded_registry: PromptRegistry):
        """Built-in templates have extracted variables."""
        tpl = loaded_registry.get("system-character-agent")
        assert tpl is not None
        assert len(tpl.variables) > 0
        assert "character_name" in tpl.variables

    def test_builtin_template_renderable(self, loaded_registry: PromptRegistry):
        """Built-in templates can be rendered with variables."""
        result = loaded_registry.render(
            "char-greeting",
            character_name="Lola",
            target="Viktor",
            personality="flirty and confident",
        )
        assert "Lola" in result
        assert "Viktor" in result


# ──── Statistics ─────────────────────────────────────────────────────

class TestStats:
    """Tests for get_stats."""

    def test_stats_structure(self, empty_registry: PromptRegistry, sample_template: PromptTemplate):
        """Stats dict has expected keys."""
        empty_registry.register(sample_template)
        stats = empty_registry.get_stats()
        assert "total_templates" in stats
        assert "by_category" in stats
        assert "total_versions" in stats
        assert "top_used" in stats
        assert "top_quality" in stats
        assert stats["total_templates"] == 1
        assert stats["by_category"]["test"] == 1

    def test_stats_tracks_versions(self, empty_registry: PromptRegistry):
        """Version count reflects all registered versions."""
        tpl1 = PromptTemplate(id="sv", name="V1", template="first", category="test")
        tpl2 = PromptTemplate(id="sv", name="V2", template="second", category="test")
        empty_registry.register(tpl1)
        empty_registry.register(tpl2)
        stats = empty_registry.get_stats()
        assert stats["total_templates"] == 1
        assert stats["total_versions"] == 2


# ──── Singleton ──────────────────────────────────────────────────────

class TestSingleton:
    """Tests for get_prompt_registry singleton."""

    def test_singleton_returns_same_instance(self):
        """Multiple calls return the same registry."""
        r1 = get_prompt_registry()
        r2 = get_prompt_registry()
        assert r1 is r2

    def test_reset_clears_singleton(self):
        """_reset_registry allows a fresh instance."""
        r1 = get_prompt_registry()
        _reset_registry()
        r2 = get_prompt_registry()
        assert r1 is not r2
