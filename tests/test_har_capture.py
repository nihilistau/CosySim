"""Tests for browser-attached HAR/CDP capture helpers."""

from __future__ import annotations

from scripts import har_capture


def test_extract_runtime_evaluate_value_reads_current_cdp_shape() -> None:
    """Runtime.evaluate values should be read from the direct CDP result shape."""
    result = {"result": {"type": "string", "value": '{"ok": true}'}}
    assert har_capture._extract_runtime_evaluate_value(result) == '{"ok": true}'


def test_extract_runtime_evaluate_value_accepts_legacy_nested_shape() -> None:
    """Legacy nested wrappers should still be tolerated for robustness."""
    result = {"result": {"result": {"type": "string", "value": '{"ok": true}'}}}
    assert har_capture._extract_runtime_evaluate_value(result) == '{"ok": true}'


def test_build_nlm_session_metadata_extracts_notebook_context() -> None:
    """Notebook URLs should produce source_path and notebook_id metadata."""
    page_data = {
        "bl": "boq_labs-tailwind-frontend_20260305.10_p0",
        "f_sid": 123456,
        "at": "token-value",
        "href": "https://notebooklm.google.com/notebook/1241f5d1-d91c-4bce-910c-6c559500e9a1",
    }

    metadata = har_capture._build_nlm_session_metadata(page_data)

    assert metadata["bl"] == "boq_labs-tailwind-frontend_20260305.10_p0"
    assert metadata["f_sid"] == "123456"
    assert metadata["at"] == "token-value"
    assert metadata["source_path"] == "/notebook/1241f5d1-d91c-4bce-910c-6c559500e9a1"
    assert metadata["notebook_id"] == "1241f5d1-d91c-4bce-910c-6c559500e9a1"


def test_select_cdp_tab_prefers_requested_pattern() -> None:
    """Tab selection should prefer the requested service before generic Google tabs."""
    tabs = [
        {"type": "page", "url": "https://www.google.com", "webSocketDebuggerUrl": "ws://google"},
        {"type": "page", "url": "https://notebooklm.google.com/notebook/test", "webSocketDebuggerUrl": "ws://nlm"},
    ]

    ws_url, page_url = har_capture._select_cdp_tab(tabs, preferred_patterns=["notebooklm"])

    assert ws_url == "ws://nlm"
    assert "notebooklm.google.com" in page_url
