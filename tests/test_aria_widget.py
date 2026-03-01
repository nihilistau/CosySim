"""
Tests for B4: Aria Floating Widget static assets and template structure.

Verifies that all required files exist and contain the expected HTML elements,
CSS classes, and JavaScript API surface. These are structural / smoke tests
that do not require a running Flask server or browser.
"""
import sys
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────

REPO = Path(__file__).parent.parent
TEMPLATE       = REPO / 'content' / 'shared' / 'templates' / 'aria_widget.html'
CSS_FILE       = REPO / 'content' / 'shared' / 'static' / 'css' / 'aria_widget.css'
JS_FILE        = REPO / 'content' / 'shared' / 'static' / 'js'  / 'aria_widget.js'
PORTRAIT_CSS   = REPO / 'content' / 'shared' / 'static' / 'css' / 'cosysim-aria-portrait.css'
PORTRAIT_JS    = REPO / 'content' / 'shared' / 'static' / 'js'  / 'cosysim-aria-portrait.js'


# ── File existence ───────────────────────────────────────────────────────────

class TestAriaWidgetFilesExist:
    """All asset files must be present."""

    def test_template_exists(self):
        assert TEMPLATE.exists(), f'Missing: {TEMPLATE}'

    def test_legacy_css_exists(self):
        assert CSS_FILE.exists(), f'Missing: {CSS_FILE}'

    def test_legacy_js_exists(self):
        assert JS_FILE.exists(), f'Missing: {JS_FILE}'

    def test_portrait_css_exists(self):
        assert PORTRAIT_CSS.exists(), f'Missing: {PORTRAIT_CSS}'

    def test_portrait_js_exists(self):
        assert PORTRAIT_JS.exists(), f'Missing: {PORTRAIT_JS}'


# ── HTML structure ───────────────────────────────────────────────────────────

class TestAriaWidgetHTML:
    """Template loads the portrait system assets."""

    @classmethod
    def setup_class(cls):
        cls.html = TEMPLATE.read_text(encoding='utf-8')

    def test_portrait_css_linked(self):
        assert 'cosysim-aria-portrait.css' in self.html

    def test_portrait_js_linked(self):
        assert 'cosysim-aria-portrait.js' in self.html


# ── CSS structure ────────────────────────────────────────────────────────────

class TestAriaWidgetCSS:
    """CSS must define the required classes, states, and animations."""

    @classmethod
    def setup_class(cls):
        cls.css = CSS_FILE.read_text(encoding='utf-8')

    def test_widget_class_defined(self):
        assert '.cs-aria-widget' in self.css

    def test_fixed_positioning(self):
        assert 'position: fixed' in self.css

    def test_bottom_right(self):
        assert 'bottom:' in self.css
        assert 'right:' in self.css

    def test_z_index_9200(self):
        assert '9200' in self.css

    def test_toggle_button_class(self):
        assert '.cs-aria-toggle' in self.css

    def test_toggle_circular(self):
        assert 'border-radius: 50%' in self.css

    def test_portrait_class(self):
        assert '.cs-aria-portrait' in self.css

    def test_state_ring_class(self):
        assert '.cs-aria-state-ring' in self.css

    def test_idle_state_ring(self):
        assert 'data-state="idle"' in self.css

    def test_talking_state_ring(self):
        assert 'data-state="talking"' in self.css

    def test_thinking_state_ring(self):
        assert 'data-state="thinking"' in self.css

    def test_listening_state_ring(self):
        assert 'data-state="listening"' in self.css

    def test_notification_badge_class(self):
        assert '.cs-aria-notif' in self.css

    def test_panel_class(self):
        assert '.cs-aria-panel' in self.css

    def test_panel_width(self):
        # Panel should be 360px as specified
        assert '360px' in self.css

    def test_panel_header_class(self):
        assert '.cs-aria-panel-header' in self.css

    def test_mode_btn_active_class(self):
        assert '.cs-aria-mode-btn--active' in self.css

    def test_messages_class(self):
        assert '.cs-aria-messages' in self.css

    def test_message_bubble_classes(self):
        assert '.cs-aria-message--user' in self.css
        assert '.cs-aria-message--aria' in self.css

    def test_input_row_class(self):
        assert '.cs-aria-input-row' in self.css

    def test_portrait_large_class(self):
        assert '.cs-aria-portrait-large' in self.css

    def test_waveform_bar_class(self):
        assert '.cs-waveform-bar' in self.css

    def test_waveform_animation(self):
        assert 'cs-waveform-bounce' in self.css

    def test_mic_btn_class(self):
        assert '.cs-aria-mic-btn' in self.css

    def test_ring_animations_defined(self):
        assert 'cs-aria-ring-idle' in self.css
        assert 'cs-aria-ring-talking' in self.css
        assert 'cs-aria-ring-thinking' in self.css


# ── JavaScript structure ─────────────────────────────────────────────────────

class TestAriaWidgetJS:
    """JavaScript must expose the AriaWidget class and required methods."""

    @classmethod
    def setup_class(cls):
        cls.js = JS_FILE.read_text(encoding='utf-8')

    def test_class_defined(self):
        assert 'class AriaWidget' in self.js

    def test_global_export(self):
        assert 'window.ariaWidget' in self.js

    def test_open_method(self):
        assert 'open()' in self.js

    def test_close_method(self):
        assert 'close()' in self.js

    def test_toggle_method(self):
        assert 'toggle()' in self.js

    def test_set_state_method(self):
        assert 'setState' in self.js

    def test_set_mode_method(self):
        assert 'setMode' in self.js

    def test_send_message_method(self):
        assert 'sendMessage' in self.js

    def test_append_message_method(self):
        assert 'appendMessage' in self.js

    def test_start_listening_method(self):
        assert 'startListening' in self.js

    def test_stop_listening_method(self):
        assert 'stopListening' in self.js

    def test_set_notification_method(self):
        assert 'setNotification' in self.js

    def test_auto_scroll_method(self):
        assert '_autoScroll' in self.js

    def test_chat_endpoint(self):
        assert '/api/aria/chat' in self.js

    def test_offline_fallback(self):
        assert 'offline' in self.js.lower() or 'Aria is offline' in self.js

    def test_navbar_event_listener(self):
        assert "panel === 'aria'" in self.js

    def test_speech_recognition_used(self):
        assert 'SpeechRecognition' in self.js

    def test_state_values(self):
        for state in ('idle', 'talking', 'thinking', 'listening'):
            # State may appear as a quoted string, object key, or attribute value
            assert state in self.js, f'State not referenced: {state}'

    def test_html_escaping(self):
        assert '_esc' in self.js

    def test_graceful_fetch_catch(self):
        # Every fetch should have a .catch() for resilience
        fetch_count = self.js.count('fetch(')
        catch_count = self.js.count('.catch(')
        assert catch_count >= fetch_count, (
            f'Not all fetch() calls have .catch() ({fetch_count} fetch, {catch_count} catch)'
        )
