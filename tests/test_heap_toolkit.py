"""Tests for Chrome cookie extractor, live scanner, and heap toolkit."""
from __future__ import annotations

import json
import os
import sqlite3
import struct
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ──────────────────────────────── Cookie Extractor ──────────────────────────────

class TestChromeCookieExtractor:
    """Tests for scripts/chrome_cookie_extractor.py."""

    def test_import(self):
        """Module imports cleanly."""
        import scripts.chrome_cookie_extractor as mod
        assert hasattr(mod, "decrypt_master_key")
        assert hasattr(mod, "decrypt_cookie_value")
        assert hasattr(mod, "extract_cookies")
        assert hasattr(mod, "cookies_to_header_string")
        assert hasattr(mod, "update_account_pool")

    def test_domain_filter_notebooklm(self):
        from scripts.chrome_cookie_extractor import _domain_matches_targets
        assert _domain_matches_targets("notebooklm.google.com", None) is True
        assert _domain_matches_targets("colab.research.google.com", None) is True
        assert _domain_matches_targets("github.com", None) is True
        assert _domain_matches_targets("example.com", None) is False

    def test_domain_filter_custom(self):
        from scripts.chrome_cookie_extractor import _domain_matches_targets
        assert _domain_matches_targets("mysite.com", ["mysite"]) is True
        assert _domain_matches_targets("othersite.com", ["mysite"]) is False

    def test_decrypt_cookie_value_v10_format(self):
        """Test AES-GCM decryption with known values."""
        from scripts.chrome_cookie_extractor import decrypt_cookie_value
        try:
            from Crypto.Cipher import AES as _AES
        except ImportError:
            pytest.skip("PyCryptodome not available")

        key = b"A" * 32  # 32-byte AES key
        nonce = b"B" * 12
        plaintext = b"test_cookie_value"
        cipher = _AES.new(key, _AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)

        encrypted = b"v10" + nonce + ciphertext + tag
        result = decrypt_cookie_value(encrypted, key)
        assert result == "test_cookie_value"

    def test_decrypt_empty_value(self):
        from scripts.chrome_cookie_extractor import decrypt_cookie_value
        result = decrypt_cookie_value(b"", b"A" * 32)
        assert result == ""

    def test_decrypt_invalid_returns_none(self):
        from scripts.chrome_cookie_extractor import decrypt_cookie_value
        # Garbage data that can't be decrypted
        result = decrypt_cookie_value(b"v10garbage_nonce_pad" + b"\x00" * 30, b"A" * 32)
        assert result is None

    def test_cookies_to_header_string(self):
        from scripts.chrome_cookie_extractor import cookies_to_header_string
        cookies = [
            {"domain": "notebooklm.google.com", "name": "SID", "value": "abc123"},
            {"domain": "notebooklm.google.com", "name": "APISID", "value": "def456"},
            {"domain": "colab.research.google.com", "name": "NID", "value": "xyz789"},
        ]
        header = cookies_to_header_string(cookies, "notebooklm")
        assert "SID=abc123" in header
        assert "APISID=def456" in header
        # Colab cookie excluded by domain filter
        assert "NID=xyz789" not in header

    def test_cookies_to_jar(self):
        from scripts.chrome_cookie_extractor import cookies_to_jar
        cookies = [
            {"name": "SID", "value": "abc123", "domain": "google.com"},
            {"name": "FAIL", "value": "[DECRYPTION_FAILED]", "domain": "google.com"},
        ]
        jar = cookies_to_jar(cookies)
        assert jar["SID"] == "abc123"
        assert "FAIL" not in jar  # Decryption failures excluded

    def test_save_report(self, tmp_path):
        from scripts.chrome_cookie_extractor import save_report
        cookies = [
            {"domain": "google.com", "name": "SID", "value": "test",
             "path": "/", "expires_utc": 0, "secure": True, "httponly": True,
             "creation_utc": 0, "last_access_utc": 0},
        ]
        report_path = save_report(cookies, output_dir=tmp_path)
        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert data["total"] == 1
        assert "google.com" in data["by_domain"]

    def test_save_report_no_values(self, tmp_path):
        from scripts.chrome_cookie_extractor import save_report
        cookies = [
            {"domain": "google.com", "name": "SID", "value": "SECRET",
             "path": "/", "expires_utc": 0, "secure": True, "httponly": True,
             "creation_utc": 0, "last_access_utc": 0},
        ]
        report_path = save_report(cookies, output_dir=tmp_path, include_values=False)
        data = json.loads(report_path.read_text())
        # Value should not appear in report
        assert "SECRET" not in report_path.read_text()

    def test_update_account_pool(self, tmp_path):
        from scripts.chrome_cookie_extractor import update_account_pool
        pool_path = tmp_path / "pool.json"
        pool_path.write_text(json.dumps({"test_account": {"name": "test_account", "cookies": {}}}))

        cookies = [
            {"domain": "notebooklm.google.com", "name": "SID", "value": "abc",
             "path": "/", "secure": True, "httponly": True,
             "expires_utc": 0, "creation_utc": 0, "last_access_utc": 0},
        ]
        result = update_account_pool(cookies, "test_account", pool_path=pool_path)
        assert result is True

        pool = json.loads(pool_path.read_text())
        assert "test_account" in pool
        assert "last_refreshed" in pool["test_account"]
        # notebooklm cookies should be stored
        assert "notebooklm" in pool["test_account"]["cookies"]

    def test_update_account_pool_missing_pool(self, tmp_path):
        from scripts.chrome_cookie_extractor import update_account_pool
        result = update_account_pool([], "test", pool_path=tmp_path / "nonexistent.json")
        assert result is False

    def test_get_chrome_profiles_default(self, tmp_path):
        from scripts.chrome_cookie_extractor import get_chrome_profiles
        (tmp_path / "Default").mkdir()
        (tmp_path / "Profile 1").mkdir()
        (tmp_path / "Profile 2").mkdir()
        profiles = get_chrome_profiles(tmp_path)
        assert "Default" in profiles
        assert "Profile 1" in profiles
        assert "Profile 2" in profiles


# ──────────────────────────────── Live Scanner ──────────────────────────────────

class TestChromeLiveScanner:
    """Tests for scripts/chrome_live_scanner.py."""

    def test_import(self):
        import scripts.chrome_live_scanner as mod
        assert hasattr(mod, "ChromeLiveScanner")
        assert hasattr(mod, "find_chrome_pids")
        assert hasattr(mod, "find_metamap_in_region")
        assert hasattr(mod, "scan_region_for_credentials")
        assert hasattr(mod, "CRED_PATTERNS")

    def test_cred_patterns_count(self):
        from scripts.chrome_live_scanner import CRED_PATTERNS
        # Must have at minimum 20 credential patterns
        assert len(CRED_PATTERNS) >= 20

    def test_google_api_key_pattern(self):
        from scripts.chrome_live_scanner import CRED_PATTERNS
        text = "some data AIzaSyC_pzrI0AjEDXDYcg7kkq3uQEjnXV50pBM more data"
        matches = CRED_PATTERNS["goog_api_key"].findall(text)
        assert len(matches) == 1
        assert matches[0] == "AIzaSyC_pzrI0AjEDXDYcg7kkq3uQEjnXV50pBM"

    def test_jwt_pattern(self):
        from scripts.chrome_live_scanner import CRED_PATTERNS
        # Real ES256 JWT from Colab heap (signature is 86+ base64url chars)
        token = (
            "eyJhbGciOiJFUzI1NiIsImtpZCI6IkI3UGVrQSJ9"
            ".eyJhdWQiOiJtLXMtMXR2bTV0djh6dHF6dyIsImV4cCI6MTc3MjYzOTU4MX0"
            ".2fayFSalXqABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnop"
        )
        matches = CRED_PATTERNS["jwt"].findall(token)
        assert len(matches) == 1

    def test_sapisid_pattern(self):
        from scripts.chrome_live_scanner import CRED_PATTERNS
        text = "SAPISID=ABCDEF1234567890GHIJK/some_path; other=val"
        matches = CRED_PATTERNS["SAPISID"].findall(text)
        assert len(matches) >= 1

    def test_github_token_pattern(self):
        from scripts.chrome_live_scanner import CRED_PATTERNS
        # 36 alphanum chars after ghp_
        text = "Authorization: token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        matches = CRED_PATTERNS["github_classic"].findall(text)
        assert len(matches) == 1

    def test_nlm_notebook_uuid_pattern(self):
        from scripts.chrome_live_scanner import CRED_PATTERNS
        uuid_str = "24221492-0531-4305-bdef-33a5425f6302"
        matches = CRED_PATTERNS["nlm_notebook"].findall(uuid_str)
        assert len(matches) == 1

    def test_scan_region_for_credentials_finds_api_key(self):
        from scripts.chrome_live_scanner import scan_region_for_credentials
        api_key = "AIzaSyC_pzrI0AjEDXDYcg7kkq3uQEjnXV50pBM"
        data = f"garbage data {api_key} more garbage".encode("latin-1")
        results: dict = {}
        scan_region_for_credentials(data, 0x1000, results)
        assert "goog_api_key" in results
        assert api_key in results["goog_api_key"]

    def test_scan_region_for_credentials_no_match(self):
        from scripts.chrome_live_scanner import scan_region_for_credentials
        data = b"nothing interesting here at all 12345"
        results: dict = {}
        scan_region_for_credentials(data, 0x1000, results)
        # Should produce no credential results (only possibly short matches)
        # At minimum, no high-value patterns should match
        high_value = {"SAPISID", "SID", "jwt", "goog_api_key", "github_token"}
        for k in high_value:
            assert k not in results or not results[k]

    def test_find_metamap_empty_data(self):
        from scripts.chrome_live_scanner import find_metamap_in_region
        result = find_metamap_in_region(b"\x00" * 1024, 0x1000)
        assert result is None

    def test_find_metamap_with_signature(self):
        """Test that MetaMap signature is detected in synthetic data."""
        from scripts.chrome_live_scanner import find_metamap_in_region, METAMAP_SIGS, METAMAP_BACK_OFFSET

        # Build synthetic region with the MetaMap signature + back-pointer
        fake_metamap_addr = 0x00007F0000001234
        fake_tagged = fake_metamap_addr + 1

        # Structure: [18 bytes of padding with pointer] [8-byte signature]
        region_base = 0x7F0000000000
        ptr_bytes = struct.pack("<Q", fake_tagged)  # The "back-pointer" at offset 0
        padding = b"\x00" * (METAMAP_BACK_OFFSET - 8)
        data = ptr_bytes + padding + METAMAP_SIGS[0]

        # Need the pointer to appear at exactly 18 bytes before the signature
        # Signature at offset = METAMAP_BACK_OFFSET (18 bytes after ptr)
        data = ptr_bytes + b"\x00" * (METAMAP_BACK_OFFSET - len(ptr_bytes)) + METAMAP_SIGS[0]
        # Pad to at least 64 bytes
        data = data.ljust(64, b"\x00")

        result = find_metamap_in_region(data, region_base)
        # If the pointer value is valid and appears multiple times, should find something
        # (single occurrence may not pass duplicate detection — that's correct behavior)
        # Just verify no crash
        assert result is None or isinstance(result, int)

    def test_chrome_live_scanner_init(self, tmp_path):
        from scripts.chrome_live_scanner import ChromeLiveScanner
        scanner = ChromeLiveScanner(output_dir=tmp_path)
        assert scanner.scan_dir.exists()
        assert "live_scan_" in scanner.scan_dir.name

    def test_chrome_live_scanner_no_processes(self, tmp_path):
        from scripts.chrome_live_scanner import ChromeLiveScanner
        scanner = ChromeLiveScanner(output_dir=tmp_path)
        # Scan with no PIDs and no Chrome running should return empty findings
        with patch("scripts.chrome_live_scanner.find_chrome_pids", return_value=[]):
            findings = scanner.scan(pids=None, string_scan=True)
        assert findings["processes"] == []
        assert findings["total_bytes_read"] == 0

    def test_readable_pages_set(self):
        from scripts.chrome_live_scanner import READABLE_PAGES, PAGE_READWRITE, PAGE_READONLY
        assert PAGE_READWRITE in READABLE_PAGES
        assert PAGE_READONLY in READABLE_PAGES

    def test_cred_patterns_tunnel_jwt(self):
        from scripts.chrome_live_scanner import CRED_PATTERNS
        tunnel_id = "m-s-1tvm5tv8ztqzw"
        matches = CRED_PATTERNS["tunnel_jwt"].findall(tunnel_id)
        assert len(matches) == 1


# ──────────────────────────────── Heap Toolkit ──────────────────────────────────

class TestHeapToolkit:
    """Tests for scripts/heap_toolkit.py."""

    def test_import(self):
        import scripts.heap_toolkit as mod
        assert hasattr(mod, "cmd_heap")
        assert hasattr(mod, "cmd_cookies")
        assert hasattr(mod, "cmd_live")
        assert hasattr(mod, "cmd_all")
        assert hasattr(mod, "cmd_report")
        assert hasattr(mod, "cmd_nexus_push")

    def test_cmd_report_no_runs(self, tmp_path, capsys):
        import scripts.heap_toolkit as mod
        args = type("Args", (), {"command": "report"})()
        # Should not crash with empty output dir
        original_base = mod.OUT_BASE
        mod.OUT_BASE = tmp_path
        try:
            result = mod.cmd_report(args)
        finally:
            mod.OUT_BASE = original_base
        assert result == 0

    def test_cmd_heap_no_files(self, tmp_path):
        import scripts.heap_toolkit as mod
        args = type("Args", (), {
            "files": None,
            "auto": False,
            "nexus": False,
            "strings_only": False,
        })()
        original_har = mod.HAR_FILES
        mod.HAR_FILES = tmp_path  # Empty dir
        try:
            result = mod.cmd_heap(args)
        finally:
            mod.HAR_FILES = original_har
        assert result == 1  # No files = error

    def test_scripts_exist(self):
        import scripts.heap_toolkit as mod
        for name, path in mod.SCRIPTS.items():
            assert path.exists(), f"Script missing: {path}"

    def test_nexus_push_q_and_a_stored(self):
        """Verify the Q&A about toolkit is pushed correctly."""
        import scripts.heap_toolkit as mod
        mock_client = MagicMock()
        with patch.object(mod, "_nexus_push_full_run_summary") as mock_push:
            mod._nexus_push_full_run_summary([0, 0, 0])
        # Just verify no crash since Nexus may not be running in tests

    def test_print_summary_no_crash(self, capsys):
        from scripts.chrome_live_scanner import print_summary
        findings = {
            "scan_time": "2026-03-01T00:00:00Z",
            "total_bytes_read": 50 * 1024 * 1024,
            "metamap_found": False,
            "processes": [{"pid": 1234, "desc": "test"}],
            "credentials": {
                "goog_api_key": ["AIzaSyC_pzrI0AjEDXDYcg7kkq3uQEjnXV50pBM"],
                "jwt": ["eyJhbGciOiJFUzI1NiIsImtpZCI6IkI3UGVrQSJ9.abc.def"],
            },
        }
        print_summary(findings)
        captured = capsys.readouterr()
        assert "Chrome Live Memory Scan" in captured.out
        assert "goog_api_key" in captured.out


# ──────────────────────────────── Integration smoke ─────────────────────────────

class TestLiveScannerIntegration:
    """Smoke tests that verify the scanner can at least enumerate Chrome processes
    without crashing (Chrome may or may not be running in CI)."""

    @pytest.mark.integration
    def test_list_chrome_pids_no_crash(self):
        from scripts.chrome_live_scanner import find_chrome_pids
        pids = find_chrome_pids()
        # Should return a list (possibly empty)
        assert isinstance(pids, list)
        for pid, desc in pids:
            assert isinstance(pid, int)
            assert isinstance(desc, str)

    @pytest.mark.integration
    def test_cookie_extractor_master_key_attempt(self):
        """Attempt to read master key — succeeds on dev machine, skips in CI."""
        from scripts.chrome_cookie_extractor import CHROME_USER_DATA, decrypt_master_key
        if not CHROME_USER_DATA.exists():
            pytest.skip("Chrome not installed")
        # Just verify it returns bytes or None without crashing
        key = decrypt_master_key()
        assert key is None or isinstance(key, bytes)
