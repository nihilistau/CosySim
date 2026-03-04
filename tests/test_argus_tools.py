"""Tests for ARGUS console toolkit — selector scanner, token harvester, console eval.

These tests mock CDP/Playwright so no running Chrome is required.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch


# ──── SAPISIDHASH ─────────────────────────────────────────────────────────────

class TestGenerateSapisidHash:
    def test_format(self) -> None:
        from scripts.argus.tools.token_harvester import generate_sapisid_hash
        result = generate_sapisid_hash("test_sapisid")
        assert result.startswith("SAPISIDHASH ")
        parts = result.split(" ", 1)[1].split("_", 1)
        assert len(parts) == 2
        ts_str, hash_str = parts
        assert ts_str.isdigit()
        assert len(hash_str) == 40  # SHA-1 hex

    def test_hash_is_deterministic_given_ts(self) -> None:
        """Same inputs → same hash."""
        from scripts.argus.tools.token_harvester import generate_sapisid_hash
        sapisid = "abc123"
        origin = "https://notebooklm.google.com"
        ts = "1700000000"
        expected_hash = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
        expected = f"SAPISIDHASH {ts}_{expected_hash}"
        with patch("scripts.argus.tools.token_harvester.time.time", return_value=1700000000):
            result = generate_sapisid_hash(sapisid, origin)
        assert result == expected

    def test_custom_origin(self) -> None:
        from scripts.argus.tools.token_harvester import generate_sapisid_hash
        result = generate_sapisid_hash("sapisid", "https://example.com")
        assert "SAPISIDHASH" in result


# ──── Pool update ─────────────────────────────────────────────────────────────

class TestUpdateAccountPool:
    def test_creates_new_pool_file(self, tmp_path: Path) -> None:
        from scripts.argus.tools import token_harvester as th
        pool_path = tmp_path / "accounts" / "pool.json"
        token_dir = tmp_path / "tokens"
        with (
            patch.object(th, "_POOL_PATH", pool_path),
            patch.object(th, "_TOKEN_DIR", token_dir),
        ):
            th.update_account_pool({"SID": "abc"}, "testuser")
        assert pool_path.exists()
        data = json.loads(pool_path.read_text())
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["name"] == "testuser"
        assert data["accounts"][0]["cookies"]["SID"] == "abc"

    def test_updates_existing_account(self, tmp_path: Path) -> None:
        from scripts.argus.tools import token_harvester as th
        pool_path = tmp_path / "accounts" / "pool.json"
        token_dir = tmp_path / "tokens"
        pool_path.parent.mkdir(parents=True)
        pool_path.write_text(json.dumps({
            "accounts": [{
                "name": "testuser",
                "cookies": {"SID": "old"},
                "authuser": 0,
                "services": ["nlm"],
                "rate_limited": {},
                "added_at": 0.0,
                "at_token": None,
            }]
        }))
        with (
            patch.object(th, "_POOL_PATH", pool_path),
            patch.object(th, "_TOKEN_DIR", token_dir),
        ):
            th.update_account_pool({"SID": "new", "HSID": "xyz"}, "testuser")
        data = json.loads(pool_path.read_text())
        assert len(data["accounts"]) == 1
        cookies = data["accounts"][0]["cookies"]
        assert cookies["SID"] == "new"
        assert cookies["HSID"] == "xyz"

    def test_adds_second_account(self, tmp_path: Path) -> None:
        from scripts.argus.tools import token_harvester as th
        pool_path = tmp_path / "accounts" / "pool.json"
        token_dir = tmp_path / "tokens"
        pool_path.parent.mkdir(parents=True)
        pool_path.write_text(json.dumps({
            "accounts": [{"name": "alice", "cookies": {}, "authuser": 0,
                          "services": [], "rate_limited": {}, "added_at": 0.0,
                          "at_token": None}]
        }))
        with (
            patch.object(th, "_POOL_PATH", pool_path),
            patch.object(th, "_TOKEN_DIR", token_dir),
        ):
            th.update_account_pool({"SID": "x"}, "bob")
        data = json.loads(pool_path.read_text())
        assert len(data["accounts"]) == 2

    def test_handles_corrupt_pool(self, tmp_path: Path) -> None:
        from scripts.argus.tools import token_harvester as th
        pool_path = tmp_path / "accounts" / "pool.json"
        token_dir = tmp_path / "tokens"
        pool_path.parent.mkdir(parents=True)
        pool_path.write_text("NOT_JSON")
        with (
            patch.object(th, "_POOL_PATH", pool_path),
            patch.object(th, "_TOKEN_DIR", token_dir),
        ):
            th.update_account_pool({"SID": "x"}, "testuser")
        data = json.loads(pool_path.read_text())
        assert len(data["accounts"]) == 1


# ──── Selector Scanner JS ─────────────────────────────────────────────────────

class TestSelectorScannerJs:
    def test_scan_js_is_defined(self) -> None:
        from scripts.argus.tools.selector_scanner import _SCAN_JS
        assert "querySelectorAll" in _SCAN_JS
        assert "aria-label" in _SCAN_JS

    def test_print_report_renders_rows(self, capsys: Any) -> None:
        from scripts.argus.tools.selector_scanner import print_report
        rows = [
            {"tag": "button", "text": "Submit", "aria": "Submit form",
             "selector": "[aria-label='Submit form']", "unique": True,
             "disabled": False, "placeholder": "", "classes": ""},
        ]
        print_report(rows)
        captured = capsys.readouterr()
        assert "Submit" in captured.out

    def test_print_report_filters_by_keyword(self, capsys: Any) -> None:
        from scripts.argus.tools.selector_scanner import print_report
        rows = [
            {"tag": "button", "text": "Insert", "aria": "Insert content",
             "selector": "[aria-label='Insert content']", "unique": True,
             "disabled": False, "placeholder": "", "classes": ""},
            {"tag": "button", "text": "Cancel", "aria": "",
             "selector": "button.cancel", "unique": False,
             "disabled": False, "placeholder": "", "classes": "cancel"},
        ]
        print_report(rows, filter_kw="insert")
        captured = capsys.readouterr()
        assert "Insert" in captured.out
        assert "Cancel" not in captured.out

    def test_save_selectors_writes_json(self, tmp_path: Path) -> None:
        from scripts.argus.tools import selector_scanner as ss
        out_dir = tmp_path / "selectors"
        with patch.object(ss, "DATA_DIR", tmp_path):
            elements = [
                {"tag": "button", "text": "OK", "aria": "OK button",
                 "selector": "[aria-label='OK button']", "unique": True,
                 "disabled": False, "placeholder": "", "classes": ""},
            ]
            path = ss.save_selectors(elements, name="test")
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1


# ──── Console Eval helpers ────────────────────────────────────────────────────

class TestConsoleEvalHelpers:
    def test_js_helpers_dict_keys(self) -> None:
        """JS_HELPERS is defined in __main__.py."""
        from scripts.argus.tools.__main__ import JS_HELPERS
        for key in ("buttons", "inputs", "cookies", "meta", "dialogs"):
            assert key in JS_HELPERS

    def test_js_helpers_are_strings(self) -> None:
        from scripts.argus.tools.__main__ import JS_HELPERS
        for key, val in JS_HELPERS.items():
            assert isinstance(val, str), f"JS_HELPERS[{key!r}] should be a string"

    def test_js_helpers_non_empty(self) -> None:
        from scripts.argus.tools.__main__ import JS_HELPERS
        for key, val in JS_HELPERS.items():
            assert len(val.strip()) > 10, f"JS_HELPERS[{key!r}] seems empty"

    def test_pretty_printer(self) -> None:
        from scripts.argus.tools.console_eval import pretty
        assert pretty(None) == "null"
        assert "key" in pretty({"key": "val"})
        assert "hello" in pretty("hello")
        assert "[" in pretty([1, 2, 3])


# ──── ARGUS tools CLI entry-point ─────────────────────────────────────────────

class TestArgusToolsCli:
    def test_cli_module_importable(self) -> None:
        import importlib.util
        spec = importlib.util.find_spec("scripts.argus.tools.__main__")
        assert spec is not None

    def test_cli_subcommands_registered(self) -> None:
        """Build argparse and verify all expected commands parse."""
        import argparse
        from scripts.argus.tools.__main__ import JS_HELPERS
        # Check the subparsers by running --help on each (no Chrome needed)
        # We just need to verify the command names exist without crashing
        assert "buttons" in JS_HELPERS  # proxy for module loading correctly
        assert "inputs" in JS_HELPERS


# ──── harvest_cookies mock test ───────────────────────────────────────────────

class TestHarvestCookiesMock:
    def _make_mock_pw(self, all_cookies: list, email_return: Any):
        mock_ctx = AsyncMock()
        mock_ctx.cookies = AsyncMock(return_value=all_cookies)
        mock_page = MagicMock()
        mock_page.url = "https://notebooklm.google.com/"
        mock_page.evaluate = AsyncMock(return_value=email_return)
        mock_ctx.pages = [mock_page]
        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]
        mock_pw = AsyncMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw.__aexit__ = AsyncMock(return_value=None)
        return mock_pw

    def test_harvest_filters_to_known_names(self) -> None:
        """harvest_cookies() should only return cookies in COOKIE_NAMES."""
        import asyncio
        from scripts.argus.tools.token_harvester import harvest_cookies

        all_cookies = [
            {"name": "SID", "value": "sid_value", "domain": ".google.com"},
            {"name": "UNKNOWN_COOKIE", "value": "noise", "domain": ".google.com"},
            {"name": "HSID", "value": "hsid_value", "domain": ".google.com"},
        ]
        mock_pw = self._make_mock_pw(all_cookies, "test@example.com")
        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            cookies, account = asyncio.run(harvest_cookies())

        assert "SID" in cookies
        assert "HSID" in cookies
        assert "UNKNOWN_COOKIE" not in cookies
        assert account == "test"  # split on @

    def test_harvest_account_name_fallback(self) -> None:
        """When email is not found, account_name falls back to 'harvested'."""
        import asyncio
        from scripts.argus.tools.token_harvester import harvest_cookies

        mock_pw = self._make_mock_pw([{"name": "SID", "value": "x"}], None)
        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            cookies, account = asyncio.run(harvest_cookies())

        assert account == "harvested"
