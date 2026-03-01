"""
Tests for B3: Admin Loft Overlay static assets and template structure.

Verifies that all required files exist and contain the expected HTML elements,
CSS classes, and JavaScript API surface. These are structural / smoke tests
that do not require a running Flask server.
"""
import sys
import re
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────

REPO = Path(__file__).parent.parent
TEMPLATE  = REPO / 'content' / 'shared' / 'templates' / 'admin_overlay.html'
CSS_FILE  = REPO / 'content' / 'shared' / 'static' / 'css' / 'admin_overlay.css'
JS_FILE   = REPO / 'content' / 'shared' / 'static' / 'js'  / 'admin_overlay.js'


# ── File existence ───────────────────────────────────────────────────────────

class TestAdminOverlayFilesExist:
    """All three asset files must be present."""

    def test_template_exists(self):
        assert TEMPLATE.exists(), f'Missing: {TEMPLATE}'

    def test_css_exists(self):
        assert CSS_FILE.exists(), f'Missing: {CSS_FILE}'

    def test_js_exists(self):
        assert JS_FILE.exists(), f'Missing: {JS_FILE}'


# ── HTML structure ───────────────────────────────────────────────────────────

class TestAdminOverlayHTML:
    """Template must contain the required structural elements."""

    @classmethod
    def setup_class(cls):
        cls.html = TEMPLATE.read_text(encoding='utf-8')

    def test_overlay_root_id(self):
        assert 'id="cs-admin-overlay"' in self.html

    def test_aria_modal(self):
        assert 'aria-modal="true"' in self.html

    def test_header_logo(self):
        assert 'THE LOFT' in self.html

    def test_all_eight_tabs_present(self):
        required_tabs = [
            'monitors', 'config', 'agents', 'nexus',
            'training', 'logs', 'content', 'economy',
        ]
        for tab in required_tabs:
            assert f'data-tab="{tab}"' in self.html, f'Missing tab: {tab}'

    def test_close_button(self):
        assert 'id="cs-admin-close"' in self.html

    def test_config_textarea(self):
        assert 'id="cs-config-editor"' in self.html

    def test_intensity_sliders(self):
        for cat in ['sexual', 'violence', 'horror', 'gambling', 'language']:
            assert f'id="ci-{cat}"' in self.html, f'Missing slider: ci-{cat}'

    def test_economy_balance_element(self):
        assert 'id="admin-credits"' in self.html

    def test_nexus_search_form(self):
        assert 'id="cs-nexus-query"' in self.html
        assert 'id="cs-nexus-search-btn"' in self.html

    def test_log_stream_element(self):
        assert 'id="cs-log-stream"' in self.html

    def test_monitor_grid_canvas(self):
        assert 'id="cs-monitor-latency"' in self.html

    def test_agents_grid(self):
        assert 'id="cs-agents-list"' in self.html


# ── CSS structure ────────────────────────────────────────────────────────────

class TestAdminOverlayCSS:
    """CSS must define the required classes and key properties."""

    @classmethod
    def setup_class(cls):
        cls.css = CSS_FILE.read_text(encoding='utf-8')

    def test_overlay_class_defined(self):
        assert '.cs-admin-overlay' in self.css

    def test_full_screen_inset(self):
        assert 'inset: 0' in self.css

    def test_z_index_9500(self):
        assert '9500' in self.css

    def test_hack_green_used(self):
        # Should reference design token or literal green
        assert 'hack-green' in self.css or '#00ff41' in self.css

    def test_monitor_grid_class(self):
        assert '.cs-monitor-grid' in self.css

    def test_config_editor_class(self):
        assert '.cs-config-editor' in self.css

    def test_log_stream_class(self):
        assert '.cs-log-stream' in self.css

    def test_intensity_row_class(self):
        assert '.cs-intensity-row' in self.css

    def test_economy_big_num_class(self):
        assert '.cs-economy-big-num' in self.css

    def test_hack_input_class(self):
        assert '.cs-hack-input' in self.css

    def test_crt_scanline_pseudoelement(self):
        # Scanlines applied via ::before or via CSS variable
        assert ('::before' in self.css or 'crt-scanline' in self.css)

    def test_admin_tab_active_class(self):
        assert '.cs-admin-tab--active' in self.css

    def test_agents_grid_class(self):
        assert '.cs-agents-grid' in self.css


# ── JavaScript structure ─────────────────────────────────────────────────────

class TestAdminOverlayJS:
    """JavaScript must expose the AdminOverlay class and required methods."""

    @classmethod
    def setup_class(cls):
        cls.js = JS_FILE.read_text(encoding='utf-8')

    def test_class_defined(self):
        assert 'class AdminOverlay' in self.js

    def test_global_export(self):
        assert 'window.adminOverlay' in self.js

    def test_open_method(self):
        assert 'open()' in self.js

    def test_close_method(self):
        assert 'close()' in self.js

    def test_toggle_method(self):
        assert 'toggle()' in self.js

    def test_switch_tab_method(self):
        assert '_switchTab' in self.js

    def test_load_monitors(self):
        assert '_loadMonitors' in self.js

    def test_load_config(self):
        assert '_loadConfig' in self.js

    def test_save_config(self):
        assert '_saveConfig' in self.js

    def test_load_agents(self):
        assert '_loadAgents' in self.js

    def test_load_nexus(self):
        assert '_loadNexus' in self.js

    def test_search_nexus(self):
        assert '_searchNexus' in self.js

    def test_load_logs(self):
        assert '_loadLogs' in self.js

    def test_save_content(self):
        assert '_saveContent' in self.js

    def test_load_economy(self):
        assert '_loadEconomy' in self.js

    def test_setup_keyboard(self):
        assert '_setupKeyboard' in self.js

    def test_navbar_event_listener(self):
        assert "panel === 'admin'" in self.js

    def test_escape_key_closes(self):
        assert 'Escape' in self.js

    def test_api_endpoints_referenced(self):
        assert '/api/bench/metrics' in self.js
        assert '/api/admin/config' in self.js
        assert '/api/admin/agents' in self.js
        assert '/api/admin/nexus/stats' in self.js
        assert '/api/admin/economy' in self.js

    def test_html_escaping(self):
        assert '_esc' in self.js or 'innerHTML' not in self.js or '_esc(' in self.js
