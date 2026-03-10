"""Tests for cosysim-scene-fx.css ambient animations and design_tokens.css refresh."""
from __future__ import annotations

import re
import pathlib

CSS_DIR = pathlib.Path(__file__).parent.parent / "content" / "shared" / "static" / "css"
SCENE_FX = CSS_DIR / "cosysim-scene-fx.css"
TOKENS   = CSS_DIR / "design_tokens.css"

SCENES = ["penthouse", "phone", "lounge", "tavern", "casino", "gallery", "arena", "realm", "neoncity"]
KEYFRAMES = [
    "penthouse-glow", "phone-glitch", "lounge-drift", "tavern-flicker",
    "casino-pulse", "gallery-float", "arena-rumble", "realm-breathe", "neoncity-scan",
]


def _normalized(path: pathlib.Path) -> str:
    """Read file and collapse all whitespace runs to a single space."""
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


# ── cosysim-scene-fx.css: existence ──────────────────────────────────────────

class TestSceneFxExists:
    def test_file_exists(self) -> None:
        assert SCENE_FX.exists(), f"Missing: {SCENE_FX}"


# ── cosysim-scene-fx.css: [data-scene] selectors ─────────────────────────────

class TestSceneFxSelectors:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_all_data_scene_selectors_present(self) -> None:
        for scene in SCENES:
            selector = f'[data-scene="{scene}"]'
            assert selector in self.css, f"Missing selector: {selector}"

    def test_all_nine_selectors_count(self) -> None:
        for scene in SCENES:
            count = self.css.count(f'[data-scene="{scene}"]')
            assert count >= 1, f"data-scene={scene} not found in scene-fx.css"


# ── cosysim-scene-fx.css: @keyframes ─────────────────────────────────────────

class TestSceneFxKeyframes:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_all_keyframes_defined(self) -> None:
        for kf in KEYFRAMES:
            assert f"@keyframes {kf}" in self.css, f"Missing @keyframes {kf}"

    def test_nine_keyframes_total(self) -> None:
        found = re.findall(r"@keyframes\s+([\w-]+)", self.css)
        assert len(found) >= 9, f"Expected ≥9 @keyframes, found {len(found)}: {found}"


# ── cosysim-scene-fx.css: animation bindings on body ─────────────────────────

class TestSceneFxAnimationBindings:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_all_animations_referenced(self) -> None:
        for kf in KEYFRAMES:
            assert kf in self.css, f"Animation '{kf}' not referenced in animation binding"

    def test_nine_body_animation_bindings(self) -> None:
        """Each [data-scene="X"] (body) block must directly bind an animation."""
        for scene, kf in zip(SCENES, KEYFRAMES):
            pattern = rf'\[data-scene="{re.escape(scene)}"\]\s*\{{[^}}]*animation:\s*{re.escape(kf)}'
            assert re.search(pattern, self.css, re.DOTALL), (
                f'[data-scene="{scene}"] body animation binding for {kf} not found'
            )


# ── cosysim-scene-fx.css: accessibility ──────────────────────────────────────

class TestSceneFxReducedMotion:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_prefers_reduced_motion_block_exists(self) -> None:
        assert "prefers-reduced-motion" in self.css, (
            "prefers-reduced-motion media query missing from cosysim-scene-fx.css"
        )

    def test_prefers_reduced_motion_disables_animations(self) -> None:
        block = re.search(
            r"prefers-reduced-motion:\s*reduce\b.*?}",
            self.css,
            re.DOTALL,
        )
        assert block, "prefers-reduced-motion: reduce block not found"
        assert "animation: none !important" in block.group(), (
            "prefers-reduced-motion block does not disable animations with !important"
        )


# ── cosysim-scene-fx.css: CSS custom properties ───────────────────────────────

class TestSceneFxCustomProperties:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_scene_accent_property_used(self) -> None:
        assert "--cs-scene-accent" in self.css

    def test_scene_glow_property_used(self) -> None:
        assert "--cs-scene-glow" in self.css


# ── cosysim-scene-fx.css: GPU compositing hints ───────────────────────────────

class TestSceneFxWillChange:
    def setup_method(self) -> None:
        self.css = SCENE_FX.read_text(encoding="utf-8")

    def test_will_change_present(self) -> None:
        assert "will-change" in self.css, (
            "will-change not found — GPU compositing hints required"
        )

    def test_will_change_box_shadow_present(self) -> None:
        assert "will-change: box-shadow" in self.css

    def test_will_change_transform_opacity_present(self) -> None:
        assert "will-change: transform, opacity" in self.css


# ── design_tokens.css: existence ─────────────────────────────────────────────

class TestDesignTokensExists:
    def test_file_exists(self) -> None:
        assert TOKENS.exists(), f"Missing: {TOKENS}"


# ── design_tokens.css: --cs-depth-N stack ────────────────────────────────────

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

    def test_depth_1_updated_spread(self) -> None:
        norm = _normalized(TOKENS)
        assert "--cs-depth-1: 0 2px 4px" in norm, "--cs-depth-1 not updated to 0 2px 4px spread"

    def test_depth_5_updated_blur(self) -> None:
        norm = _normalized(TOKENS)
        assert "--cs-depth-5: 0 32px 80px" in norm, "--cs-depth-5 not updated to 0 32px 80px"


# ── design_tokens.css: new/updated tokens ────────────────────────────────────

class TestDesignTokensNewTokens:
    def setup_method(self) -> None:
        self.norm = _normalized(TOKENS)

    def test_bg_deepest_is_true_black(self) -> None:
        assert "--cs-bg-deepest: #000000" in self.norm, (
            "--cs-bg-deepest is not set to #000000"
        )

    def test_glass_blur_md_token_present(self) -> None:
        assert "--cs-glass-blur-md: 24px" in self.norm, (
            "--cs-glass-blur-md: 24px token missing"
        )

    def test_glow_spread_sm_token_present(self) -> None:
        assert "--cs-glow-spread-sm:" in self.norm

    def test_glow_spread_md_token_present(self) -> None:
        assert "--cs-glow-spread-md:" in self.norm

    def test_glow_spread_lg_token_present(self) -> None:
        assert "--cs-glow-spread-lg:" in self.norm


# ── design_tokens.css: core tokens still intact ──────────────────────────────

class TestDesignTokensCoreVariablesIntact:
    """Smoke test — ensures the core token set was not accidentally removed."""

    def setup_method(self) -> None:
        self.css = TOKENS.read_text(encoding="utf-8")

    def test_glass_blur_present(self) -> None:
        assert "--cs-glass-blur:" in self.css

    def test_transition_page_variable(self) -> None:
        assert "--cs-transition-page:" in self.css

    def test_neon_blue_present(self) -> None:
        assert "--cs-neon-blue:" in self.css

    def test_shadow_md_present(self) -> None:
        assert "--cs-shadow-md:" in self.css

    def test_scene_accent_present(self) -> None:
        assert "--cs-scene-accent:" in self.css
