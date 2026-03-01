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
TEMPLATE = REPO / 'content' / 'shared' / 'templates' / 'aria_widget.html'
CSS_FILE = REPO / 'content' / 'shared' / 'static' / 'css' / 'aria_widget.css'
JS_FILE  = REPO / 'content' / 'shared' / 'static' / 'js'  / 'aria_widget.js'


# ── File existence ───────────────────────────────────────────────────────────

class TestAriaWidgetFilesExist:
    """All three asset files must be present."""

    def test_template_exists(self):
        assert TEMPLATE.exists(), f'Missing: {TEMPLATE}'

    def test_css_exists(self):
        assert CSS_FILE.exists(), f'Missing: {CSS_FILE}'

    def test_js_exists(self):
        assert JS_FILE.exists(), f'Missing: {JS_FILE}'


# ── HTML structure ───────────────────────────────────────────────────────────

class TestAriaWidgetHTML:
    """Template must contain the required structural elements."""

    @classmethod
    def setup_class(cls):
        cls.html = TEMPLATE.read_text(encoding='utf-8')

    def test_widget_root_id(self):
        assert 'id="cs-aria-widget"' in self.html

    def test_data_state_attribute(self):
        assert 'data-state="idle"' in self.html

    def test_toggle_button(self):
        assert 'id="cs-aria-toggle"' in self.html

    def test_portrait_element(self):
        assert 'id="cs-aria-portrait"' in self.html

    def test_portrait_image(self):
        assert 'aria_idle.png' in self.html

    def test_fallback_emoji(self):
        assert '🤖' in self.html

    def test_state_ring(self):
        assert 'cs-aria-state-ring' in self.html

    def test_notification_badge(self):
        assert 'id="cs-aria-notif"' in self.html

    def test_expanded_panel(self):
        assert 'id="cs-aria-panel"' in self.html

    def test_aria_name_header(self):
        assert 'ARIA' in self.html

    def test_messenger_mode_button(self):
        assert 'data-mode="messenger"' in self.html

    def test_voice_mode_button(self):
        assert 'data-mode="voice"' in self.html

    def test_close_button(self):
        assert 'id="cs-aria-close"' in self.html

    def test_message_log(self):
        assert 'id="cs-aria-messages"' in self.html

    def test_chat_input(self):
        assert 'id="cs-aria-input"' in self.html

    def test_send_button(self):
        assert 'id="cs-aria-send"' in self.html

    def test_voice_portrait_large(self):
        assert 'id="cs-aria-portrait-large"' in self.html

    def test_waveform_bars(self):
        assert 'cs-waveform-bar' in self.html
        # Should have 5 bars
        assert self.html.count('cs-waveform-bar') >= 5

    def test_voice_status(self):
        assert 'id="cs-aria-voice-status"' in self.html

    def test_mic_button(self):
        assert 'id="cs-aria-mic"' in self.html

    def test_aria_live_regions(self):
        # Accessibility: live regions for dynamic content
        assert 'aria-live="polite"' in self.html

    def test_mode_panel_attributes(self):
        assert 'data-mode-panel="messenger"' in self.html
        assert 'data-mode-panel="voice"' in self.html


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
