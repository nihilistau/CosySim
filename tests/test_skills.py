"""Tests for the skill registry and @skill decorator."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.skills.skill import skill, SkillPack
from engine.skills.registry import SKILL_REGISTRY


class TestSkillDecorator:
    """@skill decorator registers functions correctly."""

    def test_decorator_with_args(self):
        @skill(pack="test_pack", description="A test skill", tags=["test"])
        def _dummy_skill(x: int) -> str:
            return str(x)

        meta = SKILL_REGISTRY.get_skill("_dummy_skill")
        assert meta is not None
        assert meta.pack == "test_pack"
        assert meta.description == "A test skill"
        assert "test" in meta.tags

        # Function still callable
        assert _dummy_skill(42) == "42"

    def test_decorator_without_args(self):
        @skill
        def _bare_skill(y: str) -> str:
            """Does bare things."""
            return y.upper()

        meta = SKILL_REGISTRY.get_skill("_bare_skill")
        assert meta is not None
        assert meta.pack == "default"
        assert _bare_skill("hi") == "HI"


class TestSkillPack:
    """SkillPack returns tools for a given pack name."""

    def test_pack_tools_list(self):
        @skill(pack="test_tools_pack")
        def _tool_a(a: int) -> str:
            return str(a)

        @skill(pack="test_tools_pack")
        def _tool_b(b: str) -> str:
            return b

        pack = SkillPack("test_tools_pack")
        tools = pack.tools
        assert len(tools) >= 2
        func_names = [t.__name__ for t in tools]
        assert "_tool_a" in func_names
        assert "_tool_b" in func_names


class TestChainContext:
    """Thread-local chain context for skill functions."""

    def test_set_and_get(self):
        from engine.skills.chain_context import (
            set_chain_context, get_chain_context, clear_chain_context,
        )
        set_chain_context(chain_id="abc-123", scene_id="phone", character_id="char-1")
        ctx = get_chain_context()
        assert ctx["chain_id"] == "abc-123"
        assert ctx["scene_id"] == "phone"
        assert ctx["character_id"] == "char-1"
        clear_chain_context()

    def test_clear_resets(self):
        from engine.skills.chain_context import (
            set_chain_context, get_chain_context, clear_chain_context,
        )
        set_chain_context(chain_id="xyz")
        clear_chain_context()
        ctx = get_chain_context()
        assert ctx.get("chain_id") is None

    def test_empty_by_default(self):
        from engine.skills.chain_context import get_chain_context
        # In a fresh thread-local, should return empty dict
        ctx = get_chain_context()
        assert isinstance(ctx, dict)
