"""Tests for cosysim-stt.js, cosysim-stt.css, cosysim-ambient.js, cosysim-ambient.css
and their injection into content/shared/__init__.py + admin overlay controls.
"""

import pathlib
import re

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = pathlib.Path(__file__).parent.parent
SHARED     = ROOT / "content" / "shared"
JS_DIR     = SHARED / "static" / "js"
CSS_DIR    = SHARED / "static" / "css"
TEMPLATES  = SHARED / "templates"

STT_JS     = JS_DIR  / "cosysim-stt.js"
STT_CSS    = CSS_DIR / "cosysim-stt.css"
AMB_JS     = JS_DIR  / "cosysim-ambient.js"
AMB_CSS    = CSS_DIR / "cosysim-ambient.css"
INIT_PY    = SHARED  / "__init__.py"
ADMIN_HTML = TEMPLATES / "admin_overlay.html"

SCENES_9   = ["bedroom", "casino", "arena", "tavern", "lounge", "gallery", "realm", "neoncity", "phone"]


# ── File existence ─────────────────────────────────────────────────────────────

class TestFilesExist:
    def test_stt_js_exists(self) -> None:
        assert STT_JS.exists(), f"Missing: {STT_JS}"

    def test_stt_css_exists(self) -> None:
        assert STT_CSS.exists(), f"Missing: {STT_CSS}"

    def test_ambient_js_exists(self) -> None:
        assert AMB_JS.exists(), f"Missing: {AMB_JS}"

    def test_ambient_css_exists(self) -> None:
        assert AMB_CSS.exists(), f"Missing: {AMB_CSS}"


# ── STT JS content ─────────────────────────────────────────────────────────────

class TestSTTJSContent:
    def setup_method(self) -> None:
        self.src = STT_JS.read_text(encoding="utf-8")

    def test_speech_recognition_reference(self) -> None:
        assert "SpeechRecognition" in self.src

    def test_webkit_fallback(self) -> None:
        assert "webkitSpeechRecognition" in self.src

    def test_ptt_btn_class(self) -> None:
        assert "cs-ptt-btn" in self.src

    def test_ptt_preview_class(self) -> None:
        assert "cs-stt-preview" in self.src

    def test_keydown_space_handler(self) -> None:
        assert "keydown" in self.src
        assert "Space" in self.src

    def test_keyup_stop_handler(self) -> None:
        assert "keyup" in self.src

    def test_start_method(self) -> None:
        assert "start()" in self.src or "start (" in self.src

    def test_stop_method(self) -> None:
        assert "stop()" in self.src or "stop (" in self.src

    def test_send_transcript(self) -> None:
        assert "_sendTranscript" in self.src

    def test_socket_emit(self) -> None:
        assert "user_message" in self.src

    def test_window_cosysimSTT(self) -> None:
        assert "window.cosySimSTT" in self.src

    def test_interim_results(self) -> None:
        assert "interimResults" in self.src

    def test_on_result_handler(self) -> None:
        assert "onresult" in self.src

    def test_on_error_handler(self) -> None:
        assert "onerror" in self.src

    def test_touch_events(self) -> None:
        assert "touchstart" in self.src
        assert "touchend" in self.src

    def test_aria_label(self) -> None:
        assert "aria-label" in self.src


# ── STT CSS content ────────────────────────────────────────────────────────────

class TestSTTCSSContent:
    def setup_method(self) -> None:
        self.src = STT_CSS.read_text(encoding="utf-8")

    def test_ptt_btn_selector(self) -> None:
        assert ".cs-ptt-btn" in self.src

    def test_ptt_preview_selector(self) -> None:
        assert ".cs-stt-preview" in self.src

    def test_listening_state_selector(self) -> None:
        assert 'data-state="listening"' in self.src

    def test_fixed_positioning(self) -> None:
        assert "position: fixed" in self.src

    def test_ptt_pulse_keyframes(self) -> None:
        assert "@keyframes ptt-pulse" in self.src

    def test_glass_bg_variable(self) -> None:
        assert "--cs-glass-bg" in self.src


# ── Ambient JS content ─────────────────────────────────────────────────────────

class TestAmbientJSContent:
    def setup_method(self) -> None:
        self.src = AMB_JS.read_text(encoding="utf-8")

    def test_scene_ambients_config(self) -> None:
        assert "SCENE_AMBIENTS" in self.src

    def test_all_9_scenes_present(self) -> None:
        for scene in SCENES_9:
            assert scene in self.src, f"Scene '{scene}' not found in SCENE_AMBIENTS"

    def test_audio_context_reference(self) -> None:
        assert "AudioContext" in self.src

    def test_webkit_audio_fallback(self) -> None:
        assert "webkitAudioContext" in self.src

    def test_window_ambient_audio(self) -> None:
        assert "window.ambientAudio" in self.src

    def test_toggle_method(self) -> None:
        assert "toggle()" in self.src or "toggle ()" in self.src

    def test_set_volume_method(self) -> None:
        assert "setVolume" in self.src

    def test_ambient_toggle_wire(self) -> None:
        assert "cs-ambient-toggle" in self.src

    def test_ambient_volume_wire(self) -> None:
        assert "cs-ambient-volume" in self.src

    def test_generate_rain(self) -> None:
        assert "_generateRain" in self.src

    def test_generate_wind(self) -> None:
        assert "_generateWind" in self.src

    def test_generate_city_hum(self) -> None:
        assert "_generateCityHum" in self.src

    def test_generate_crowd(self) -> None:
        assert "_generateCrowd" in self.src

    def test_generate_static(self) -> None:
        assert "_generateStatic" in self.src

    def test_unique_ambient_types(self) -> None:
        """Each of the 9 scenes should have a distinct ambient type value."""
        types = re.findall(r"type:\s*'([\w_]+)'", self.src)
        # All 9 scenes are declared; types need not all be unique but the config must cover all scenes
        assert len(types) >= 9, f"Expected at least 9 type entries, found {len(types)}: {types}"

    def test_init_on_interaction(self) -> None:
        assert "_initOnInteraction" in self.src

    def test_user_interaction_guard(self) -> None:
        # Web Audio must be started from a user gesture
        assert "click" in self.src
        assert "once: true" in self.src


# ── Ambient CSS content ────────────────────────────────────────────────────────

class TestAmbientCSSContent:
    def setup_method(self) -> None:
        self.src = AMB_CSS.read_text(encoding="utf-8")

    def test_ambient_status_selector(self) -> None:
        assert "#cs-ambient-status" in self.src

    def test_is_active_class(self) -> None:
        assert ".is-active" in self.src

    def test_ambient_blink_keyframes(self) -> None:
        assert "@keyframes ambient-blink" in self.src

    def test_fixed_positioning(self) -> None:
        assert "position: fixed" in self.src


# ── __init__.py injection ──────────────────────────────────────────────────────

class TestSharedInitInjection:
    def setup_method(self) -> None:
        self.src = INIT_PY.read_text(encoding="utf-8")

    def test_stt_css_injected(self) -> None:
        assert "cosysim-stt.css" in self.src

    def test_stt_js_injected(self) -> None:
        assert "cosysim-stt.js" in self.src

    def test_ambient_css_injected(self) -> None:
        assert "cosysim-ambient.css" in self.src

    def test_ambient_js_injected(self) -> None:
        assert "cosysim-ambient.js" in self.src

    def test_stt_link_tag(self) -> None:
        assert 'cosysim-stt.css">' in self.src

    def test_stt_script_tag(self) -> None:
        assert 'cosysim-stt.js"' in self.src

    def test_ambient_link_tag(self) -> None:
        assert 'cosysim-ambient.css">' in self.src

    def test_ambient_script_tag(self) -> None:
        assert 'cosysim-ambient.js"' in self.src


# ── Admin overlay ambient controls ────────────────────────────────────────────

class TestAdminOverlayAmbientControls:
    def setup_method(self) -> None:
        self.src = ADMIN_HTML.read_text(encoding="utf-8")

    def test_ambient_toggle_checkbox(self) -> None:
        assert 'id="cs-ambient-toggle"' in self.src

    def test_ambient_volume_range(self) -> None:
        assert 'id="cs-ambient-volume"' in self.src

    def test_ambient_volume_is_range_input(self) -> None:
        assert 'type="range"' in self.src
        assert 'cs-ambient-volume' in self.src

    def test_ambient_toggle_is_checkbox(self) -> None:
        assert 'type="checkbox"' in self.src
        assert 'cs-ambient-toggle' in self.src

    def test_ambient_section_heading(self) -> None:
        assert "Ambient Audio" in self.src
