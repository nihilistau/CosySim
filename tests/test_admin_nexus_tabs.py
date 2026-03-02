"""
Tests for CosySim v0.71 Track E: Admin overlay [NEXUS] and [KNOWLEDGE] tabs.

Verifies HTML structure, CSS classes, JavaScript functions, and backend routes
are all present and correctly implemented. No running server required.
"""
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

REPO       = Path(__file__).parent.parent
TEMPLATE   = REPO / "content" / "shared" / "templates" / "admin_overlay.html"
CSS_FILE   = REPO / "content" / "shared" / "static" / "css" / "admin_overlay.css"
JS_FILE    = REPO / "content" / "shared" / "static" / "js" / "admin_overlay.js"
SHARED_PY  = REPO / "content" / "shared" / "__init__.py"


# ── Fixtures ─────────────────────────────────────────────────────────────────

class _Files:
    html: str = ""
    css:  str = ""
    js:   str = ""
    py:   str = ""

    @classmethod
    def load(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")
        cls.css  = CSS_FILE.read_text(encoding="utf-8")
        cls.js   = JS_FILE.read_text(encoding="utf-8")
        cls.py   = SHARED_PY.read_text(encoding="utf-8")


_Files.load()


# ── Tab buttons ──────────────────────────────────────────────────────────────

class TestTabButtons:
    """Both new tab buttons must be present in the template."""

    def test_nexus_tab_button_present(self):
        assert 'data-tab="nexus"' in _Files.html

    def test_knowledge_tab_button_present(self):
        assert 'data-tab="knowledge"' in _Files.html

    def test_knowledge_tab_label(self):
        assert "[KNOWLEDGE]" in _Files.html

    def test_nexus_tab_label(self):
        assert "[NEXUS]" in _Files.html

    def test_knowledge_aria_controls(self):
        assert 'aria-controls="cs-admin-panel-knowledge"' in _Files.html

    def test_nexus_aria_controls(self):
        assert 'aria-controls="cs-admin-panel-nexus"' in _Files.html


# ── Tab panel wrapper IDs ────────────────────────────────────────────────────

class TestTabPanelIds:
    """Wrapper divs with the canonical IDs must exist."""

    def test_cs_tab_nexus_exists(self):
        assert 'id="cs-tab-nexus"' in _Files.html

    def test_cs_tab_knowledge_exists(self):
        assert 'id="cs-tab-knowledge"' in _Files.html

    def test_cs_admin_panel_knowledge_exists(self):
        assert 'id="cs-admin-panel-knowledge"' in _Files.html

    def test_cs_admin_panel_nexus_exists(self):
        assert 'id="cs-admin-panel-nexus"' in _Files.html


# ── Nexus status grid elements ───────────────────────────────────────────────

class TestNexusStatusGrid:
    """All four stat cells and the refresh button must be present."""

    def test_nexus_status_grid_id(self):
        assert 'id="cs-nexus-status-grid"' in _Files.html

    def test_nexus_conn_id(self):
        assert 'id="cs-nexus-conn"' in _Files.html

    def test_nexus_entries_id(self):
        assert 'id="cs-nexus-entries"' in _Files.html

    def test_nexus_qa_id(self):
        assert 'id="cs-nexus-qa"' in _Files.html

    def test_nexus_hits_id(self):
        assert 'id="cs-nexus-hits"' in _Files.html

    def test_nexus_refresh_button(self):
        assert 'id="cs-nexus-refresh"' in _Files.html


# ── Nexus search elements ────────────────────────────────────────────────────

class TestNexusSearch:
    """Search input, button, and results container must be present."""

    def test_nexus_search_input_id(self):
        assert 'id="cs-nexus-search-input"' in _Files.html

    def test_nexus_search_btn_id(self):
        assert 'id="cs-nexus-search-btn"' in _Files.html

    def test_nexus_search_results_id(self):
        assert 'id="cs-nexus-search-results"' in _Files.html

    def test_backward_compat_query_id(self):
        """Legacy cs-nexus-query ID must still exist for backward compat."""
        assert 'id="cs-nexus-query"' in _Files.html


# ── Knowledge tab form elements ──────────────────────────────────────────────

class TestKnowledgeForm:
    """All knowledge store form elements must be present."""

    def test_know_title_input(self):
        assert 'id="cs-know-title"' in _Files.html

    def test_know_content_textarea(self):
        assert 'id="cs-know-content"' in _Files.html

    def test_know_type_select(self):
        assert 'id="cs-know-type"' in _Files.html

    def test_know_store_btn(self):
        assert 'id="cs-know-store-btn"' in _Files.html

    def test_know_result_element(self):
        assert 'id="cs-know-result"' in _Files.html

    def test_know_recent_element(self):
        assert 'id="cs-know-recent"' in _Files.html

    def test_know_reload_button(self):
        assert 'id="cs-know-reload"' in _Files.html

    def test_know_type_options(self):
        assert 'value="note"' in _Files.html
        assert 'value="decision"' in _Files.html
        assert 'value="code"' in _Files.html
        assert 'value="document"' in _Files.html


# ── CSS classes ──────────────────────────────────────────────────────────────

class TestCSSClasses:
    """All v0.71 CSS classes must be defined."""

    def test_cs_nexus_grid_defined(self):
        assert ".cs-nexus-grid" in _Files.css

    def test_cs_nexus_grid_is_grid(self):
        assert "display: grid" in _Files.css

    def test_cs_nexus_stat_defined(self):
        assert ".cs-nexus-stat" in _Files.css

    def test_cs_nexus_label_defined(self):
        assert ".cs-nexus-label" in _Files.css

    def test_cs_nexus_value_defined(self):
        assert ".cs-nexus-value" in _Files.css

    def test_cs_nexus_results_defined(self):
        assert ".cs-nexus-results" in _Files.css

    def test_cs_textarea_defined(self):
        assert ".cs-textarea" in _Files.css

    def test_cs_select_defined(self):
        assert ".cs-select" in _Files.css

    def test_cs_input_defined(self):
        assert ".cs-input" in _Files.css

    def test_cs_btn_defined(self):
        assert ".cs-btn" in _Files.css

    def test_cs_btn_sm_defined(self):
        assert ".cs-btn-sm" in _Files.css

    def test_cs_admin_section_defined(self):
        assert ".cs-admin-section" in _Files.css


# ── JavaScript functions ─────────────────────────────────────────────────────

class TestJavaScriptFunctions:
    """All v0.71 JS functions must be present in admin_overlay.js."""

    def test_load_nexus_tab_function(self):
        assert "loadNexusTab" in _Files.js

    def test_load_knowledge_function(self):
        assert "_loadKnowledge" in _Files.js

    def test_store_knowledge_function(self):
        assert "_storeKnowledge" in _Files.js

    def test_nexus_status_endpoint_referenced(self):
        assert "/api/nexus/status" in _Files.js

    def test_nexus_search_endpoint_referenced(self):
        assert "/api/nexus/search" in _Files.js

    def test_nexus_store_endpoint_referenced(self):
        assert "/api/nexus/store" in _Files.js

    def test_knowledge_case_in_switch(self):
        assert "knowledge" in _Files.js

    def test_load_nexus_still_present(self):
        """Backward compat: original _loadNexus must still exist."""
        assert "_loadNexus" in _Files.js

    def test_search_nexus_still_present(self):
        """Backward compat: _searchNexus must still exist."""
        assert "_searchNexus" in _Files.js


# ── Backend routes ───────────────────────────────────────────────────────────

class TestBackendRoutes:
    """All three Nexus API routes must be registered in shared __init__.py."""

    def test_nexus_status_route_defined(self):
        assert '"/api/nexus/status"' in _Files.py

    def test_nexus_search_route_defined(self):
        assert '"/api/nexus/search"' in _Files.py

    def test_nexus_store_route_defined(self):
        assert '"/api/nexus/store"' in _Files.py

    def test_nexus_status_api_function(self):
        assert "nexus_status_api" in _Files.py

    def test_nexus_search_api_function(self):
        assert "nexus_search_api" in _Files.py

    def test_nexus_store_api_function(self):
        assert "nexus_store_api" in _Files.py

    def test_get_nexus_client_used(self):
        assert "get_nexus_client" in _Files.py

    def test_jsonify_imported(self):
        assert "jsonify" in _Files.py

    def test_nexus_store_post_method(self):
        assert 'methods=["POST"]' in _Files.py or "methods=['POST']" in _Files.py
