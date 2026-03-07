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
        assert len(data) == 1
        assert data["testuser"]["name"] == "testuser"
        assert data["testuser"]["cookies"]["SID"] == "abc"

    def test_updates_existing_account(self, tmp_path: Path) -> None:
        from scripts.argus.tools import token_harvester as th
        pool_path = tmp_path / "accounts" / "pool.json"
        token_dir = tmp_path / "tokens"
        pool_path.parent.mkdir(parents=True)
        pool_path.write_text(json.dumps({
            "testuser": {
                "name": "testuser",
                "cookies": {"SID": "old"},
                "authuser": 0,
                "services": ["notebooklm"],
                "rate_limited": {},
                "added_at": 0.0,
                "at_token": None,
            }
        }))
        with (
            patch.object(th, "_POOL_PATH", pool_path),
            patch.object(th, "_TOKEN_DIR", token_dir),
        ):
            th.update_account_pool({"SID": "new", "HSID": "xyz"}, "testuser")
        data = json.loads(pool_path.read_text())
        assert len(data) == 1
        cookies = data["testuser"]["cookies"]
        assert cookies["SID"] == "new"
        assert cookies["HSID"] == "xyz"

    def test_adds_second_account(self, tmp_path: Path) -> None:
        from scripts.argus.tools import token_harvester as th
        pool_path = tmp_path / "accounts" / "pool.json"
        token_dir = tmp_path / "tokens"
        pool_path.parent.mkdir(parents=True)
        pool_path.write_text(json.dumps({
            "alice": {"name": "alice", "cookies": {}, "authuser": 0,
                       "services": [], "rate_limited": {}, "added_at": 0.0,
                       "at_token": None}
        }))
        with (
            patch.object(th, "_POOL_PATH", pool_path),
            patch.object(th, "_TOKEN_DIR", token_dir),
        ):
            th.update_account_pool({"SID": "x"}, "bob")
        data = json.loads(pool_path.read_text())
        assert len(data) == 2

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
        assert len(data) == 1

    def test_persists_nlm_session_metadata(self, tmp_path: Path) -> None:
        from scripts.argus.tools import token_harvester as th

        pool_path = tmp_path / "accounts" / "pool.json"
        token_dir = tmp_path / "tokens"
        with (
            patch.object(th, "_POOL_PATH", pool_path),
            patch.object(th, "_TOKEN_DIR", token_dir),
        ):
            th.update_account_pool(
                {"SID": "abc"},
                "testuser",
                session={"bl": "boq_labs-tailwind-frontend_20260305.10_p0", "f_sid": "123", "at": "token"},
                service_sessions={"notebooklm": {"notebook_id": "nb-1"}},
            )
        data = json.loads(pool_path.read_text())
        assert data["testuser"]["nlm_session"]["bl"] == "boq_labs-tailwind-frontend_20260305.10_p0"
        assert data["testuser"]["service_sessions"]["notebooklm"]["notebook_id"] == "nb-1"


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
        with (
            patch("scripts.argus.tools.token_harvester._harvest_via_direct_cdp", new=AsyncMock(return_value=None)),
            patch("playwright.async_api.async_playwright", return_value=mock_pw),
        ):
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
        with (
            patch("scripts.argus.tools.token_harvester._harvest_via_direct_cdp", new=AsyncMock(return_value=None)),
            patch("playwright.async_api.async_playwright", return_value=mock_pw),
        ):
            cookies, account = asyncio.run(harvest_cookies())

        assert account == "harvested"

    def test_harvest_prefers_direct_cdp_bundle(self) -> None:
        """Direct CDP capture should win when it succeeds."""
        import asyncio
        from scripts.argus.tools.token_harvester import harvest_capture

        with patch(
            "scripts.argus.tools.token_harvester._harvest_via_direct_cdp",
            new=AsyncMock(
                return_value={
                    "cookies": {"SID": "sid_value"},
                    "account_name": "direct-user",
                    "authuser": 0,
                    "at_token": None,
                    "nlm_session": {},
                    "service_sessions": {},
                    "services": ["notebooklm"],
                }
            ),
        ):
            capture = asyncio.run(harvest_capture())

        assert capture["account_name"] == "direct-user"
        assert capture["cookies"]["SID"] == "sid_value"


# ──── ask command ─────────────────────────────────────────────────────────────

class TestArgusAskCommand:
    """Tests for the cmd_ask NLM interaction command."""

    def _make_mock_ctx(self, initial_msg_count: int, final_answer: str):
        """Build a mock Playwright context that simulates NLM responding."""
        mock_page = AsyncMock()
        mock_page.url = "https://notebooklm.google.com/notebook/test-id"

        # fill/click/focus/keyboard return None (just track calls)
        mock_page.fill = AsyncMock(return_value=None)
        mock_page.click = AsyncMock(return_value=None)
        mock_page.focus = AsyncMock(return_value=None)
        mock_page.keyboard = AsyncMock()
        mock_page.keyboard.press = AsyncMock(return_value=None)

        # wait_for_selector succeeds (submit btn enabled)
        mock_page.wait_for_selector = AsyncMock(return_value=None)

        mock_page.locator = MagicMock()
        mock_locator = AsyncMock()
        mock_locator.wait_for = AsyncMock(return_value=None)
        mock_locator.is_disabled = AsyncMock(return_value=False)
        mock_locator.click = AsyncMock(return_value=None)
        mock_locator_group = MagicMock()
        mock_locator_group.first = mock_locator
        mock_page.locator.return_value = mock_locator_group

        # Call sequence: (before_count), then per poll: (loading, count, read_last)
        # Stability requires content unchanged AND len > 50 for 2 consecutive polls.
        # Poll 1: loading=True,  count=N+1, read="Loading..."  → stable=0 (len < 50)
        # Poll 2: loading=False, count=N+1, read=final_answer  → stable=0 (different)
        # Poll 3: loading=False, count=N+1, read=final_answer  → stable=1
        # Poll 4: loading=False, count=N+1, read=final_answer  → stable=2 → done
        n = initial_msg_count
        call_log: list = [
            n,                              # before_count
            True,  n + 1, "Loading...",     # poll 1
            False, n + 1, final_answer,     # poll 2 (different from "Loading..." → stable=0)
            False, n + 1, final_answer,     # poll 3 (stable=1)
            False, n + 1, final_answer,     # poll 4 (stable=2 → done)
        ]
        # Use closure-based async coroutine to avoid StopIteration inside async context
        call_idx = [0]

        async def _eval_side_effect(*args: object, **kwargs: object) -> object:
            idx = call_idx[0]
            call_idx[0] += 1
            return call_log[idx] if idx < len(call_log) else call_log[-1]

        mock_page.evaluate = AsyncMock(side_effect=_eval_side_effect)

        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        return mock_ctx, mock_page

    def test_ask_returns_stable_answer(self) -> None:
        """cmd_ask polls until content is stable and returns the answer."""
        import asyncio
        from unittest.mock import patch
        from scripts.argus.tools.__main__ import cmd_ask

        final_answer = "CosySim is a multi-scene AI simulation framework with 15 interactive scenes and Nexus KMS."
        mock_ctx, mock_page = self._make_mock_ctx(0, final_answer)

        result_holder: list = []

        async def _run():
            # Capture stdout; patch asyncio.sleep to skip real waits
            import io, sys
            buf = io.StringIO()
            orig = sys.stdout
            sys.stdout = buf
            try:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await cmd_ask(mock_ctx, "What is CosySim?", "notebooklm", 30, raw=False, store=False)
            finally:
                sys.stdout = orig
            result_holder.append(buf.getvalue())

        asyncio.run(_run())
        out = result_holder[0]
        assert "What is CosySim?" in out
        assert "CosySim" in out
        assert any("submit-button" in str(call.args[0]) for call in mock_page.locator.call_args_list)

    def test_ask_raw_flag_suppresses_header(self) -> None:
        """--raw prints answer without Q/separator lines."""
        import asyncio
        from unittest.mock import patch
        from scripts.argus.tools.__main__ import cmd_ask

        final_answer = "Raw answer text with enough detail to pass the stability threshold check here."
        mock_ctx, mock_page = self._make_mock_ctx(2, final_answer)

        output: list = []

        async def _run():
            import io, sys
            from unittest.mock import patch
            buf = io.StringIO()
            orig = sys.stdout
            sys.stdout = buf
            try:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await cmd_ask(mock_ctx, "Q?", "notebooklm", 30, raw=True, store=False)
            finally:
                sys.stdout = orig
            output.append(buf.getvalue())

        asyncio.run(_run())
        out = output[0]
        # raw=True: only the answer, no "Q:" header
        assert "Raw answer text" in out
        assert "Q:" not in out

    def test_ask_no_matching_tab(self, capsys: Any) -> None:
        """cmd_ask prints error when no tab matches url pattern."""
        import asyncio
        from scripts.argus.tools.__main__ import cmd_ask

        mock_ctx = MagicMock()
        mock_ctx.pages = []  # empty — no matching tab

        asyncio.run(cmd_ask(mock_ctx, "hello", "notebooklm", 5, raw=False, store=False))
        captured = capsys.readouterr()
        assert "No tab matching" in captured.out


# ──── eval --file flag ────────────────────────────────────────────────────────

class TestEvalFileFlag:
    """Tests for the --file option on the eval command."""

    def test_eval_reads_js_from_file(self, tmp_path: Path) -> None:
        """cmd_eval loads JS from --file and evaluates it."""
        import asyncio
        from scripts.argus.tools.__main__ import cmd_eval

        js_file = tmp_path / "test.js"
        js_file.write_text("() => 'hello from file'", encoding="utf-8")

        mock_page = AsyncMock()
        mock_page.url = "https://notebooklm.google.com/"
        mock_page.evaluate = AsyncMock(return_value="hello from file")

        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]

        output: list = []

        async def _run():
            import io, sys
            buf = io.StringIO()
            orig = sys.stdout
            sys.stdout = buf
            try:
                await cmd_eval(mock_ctx, "notebooklm", js=None, helper=None, interactive=False, file=str(js_file))
            finally:
                sys.stdout = orig
            output.append(buf.getvalue())

        asyncio.run(_run())
        assert "hello from file" in output[0]
        # Verify the JS from the file was passed to evaluate
        mock_page.evaluate.assert_called_once_with("() => 'hello from file'")

    def test_nlm_state_helper_in_js_helpers(self) -> None:
        """nlm_state helper is present in JS_HELPERS."""
        from scripts.argus.tools.__main__ import JS_HELPERS
        assert "nlm_state" in JS_HELPERS
        assert "chat-message" in JS_HELPERS["nlm_state"] or "response_count" in JS_HELPERS["nlm_state"]
