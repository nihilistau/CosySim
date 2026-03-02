"""Tests for cosysim-scene-fx.css and design_tokens.css refreshed values."""
import pathlib
import re

CSS_DIR = pathlib.Path(__file__).parent.parent / "content" / "shared" / "static" / "css"
SCENE_FX = CSS_DIR / "cosysim-scene-fx.css"
TOKENS   = CSS_DIR / "design_tokens.css"

SCENES = ["bedroom", "phone", "lounge", "tavern", "casino", "gallery", "arena", "realm", "neoncity"]
KEYFRAMES = [
    "bedroom-glow", "casino-pulse", "arena-rumble", "tavern-flicker",
    "realm-breathe", "neoncity-scan", "lounge-drift", "gallery-float", "phone-glitch",
]


class TestSceneFxExists:
    def test_file_exists(self) -> None:
        assert SCENE_FX.exists(), f"Missing: {SCENE_FX}"


class TestSceneFxSelectors:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_all_data_scene_selectors_present(self) -> None:
        for scene in SCENES:
            selector = f'[data-scene="{scene}"]'
            assert selector in self.css, f"Missing selector: {selector}"

    def test_all_nine_selectors_count(self) -> None:
        # Each scene appears at least in the variable override block
        for scene in SCENES:
            count = self.css.count(f'[data-scene="{scene}"]')
            assert count >= 1, f"data-scene={scene} not found in scene-fx.css"


class TestSceneFxKeyframes:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_all_keyframes_defined(self) -> None:
        for kf in KEYFRAMES:
            assert f"@keyframes {kf}" in self.css, f"Missing @keyframes {kf}"

    def test_nine_keyframes_total(self) -> None:
        found = re.findall(r"@keyframes\s+([\w-]+)", self.css)
        assert len(found) >= 9, f"Expected ≥9 @keyframes, found {len(found)}: {found}"


class TestSceneFxAnimationReferences:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_all_animations_referenced(self) -> None:
        for kf in KEYFRAMES:
            assert kf in self.css, f"Animation '{kf}' not referenced in animation binding"

    def test_nine_animation_bindings(self) -> None:
        # Each scene::before block references an animation
        for scene in SCENES:
            assert f'[data-scene="{scene}"]::before' in self.css, (
                f"Missing ::before animation binding for scene '{scene}'"
            )


class TestDesignTokensDepthShadows:
    def setup_method(self) -> None:
        self.css = TOKENS.read_text(encoding="utf-8")

    def test_depth_1_present(self) -> None:
        assert "--cs-depth-1:" in self.css

    def test_depth_2_present(self) -> None:
        assert "--cs-depth-2:" in self.css

    def test_depth_3_present(self) -> None:
        assert "--cs-depth-3:" in self.css

    def test_depth_4_present(self) -> None:
        assert "--cs-depth-4:" in self.css

    def test_depth_5_present(self) -> None:
        assert "--cs-depth-5:" in self.css


class TestDesignTokensTransitionPage:
    def test_transition_page_variable(self) -> None:
        css = TOKENS.read_text(encoding="utf-8")
        assert "--cs-transition-page:" in css


class TestDesignTokensCoreVariablesIntact:
    """Smoke test — ensures the core token set was not accidentally removed."""

    def setup_method(self) -> None:
        self.css = TOKENS.read_text(encoding="utf-8")

    def test_bg_deepest_present(self) -> None:
        assert "--cs-bg-deepest:" in self.css

    def test_glass_blur_present(self) -> None:
        assert "--cs-glass-blur:" in self.css

    def test_neon_blue_present(self) -> None:
        assert "--cs-neon-blue:" in self.css

    def test_shadow_md_present(self) -> None:
        assert "--cs-shadow-md:" in self.css

    def test_scene_accent_present(self) -> None:
        assert "--cs-scene-accent:" in self.css
