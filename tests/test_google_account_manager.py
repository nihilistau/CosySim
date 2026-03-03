"""Tests for engine.nexus.google_account_manager."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.nexus.google_account_manager import (
    GoogleAccountManager,
    _GOOGLE_AUTH_COOKIES,
    get_account_manager,
)


# ──── Fixtures ────

@pytest.fixture
def manager(tmp_path: Path) -> GoogleAccountManager:
    """Fresh GoogleAccountManager backed by a temp directory."""
    return GoogleAccountManager(data_dir=tmp_path / "accounts")


@pytest.fixture
def sample_har(tmp_path: Path) -> Path:
    """Write a minimal HAR file with Google auth cookies and an API key."""
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://notebooklm.google.com/",
                        "headers": [
                            {
                                "name": "cookie",
                                "value": (
                                    "SAPISID=abc123SAPISID; "
                                    "SID=test_sid_value_long; "
                                    "__Secure-1PSID=secure1psid_value_long; "
                                    "IRRELEVANT=should_be_ignored"
                                ),
                            },
                            {"name": "X-Goog-Api-Key", "value": "AIza_test_key"},
                        ],
                        "cookies": [
                            {"name": "HSID", "value": "hsid_value_long_enough"},
                        ],
                    },
                    "response": {"content": {"text": ""}},
                },
            ]
        }
    }
    p = tmp_path / "test_capture.har"
    p.write_text(json.dumps(har), encoding="utf-8")
    return p


# ──── Tests ────

def test_import_from_har_saves_cookies(manager: GoogleAccountManager, sample_har: Path) -> None:
    """import_from_har should extract auth cookies and persist them."""
    ok = manager.import_from_har(str(sample_har), "acct1")
    assert ok is True
    acct = manager._load_account("acct1")
    assert acct is not None
    assert "SAPISID" in acct["cookies"]
    assert acct["cookies"]["SAPISID"] == "abc123SAPISID"
    assert acct["api_keys"].get("aistudio") == "AIza_test_key"


def test_import_from_har_filters_irrelevant_cookies(
    manager: GoogleAccountManager, sample_har: Path
) -> None:
    """import_from_har should NOT include cookies not in _GOOGLE_AUTH_COOKIES."""
    manager.import_from_har(str(sample_har), "acct1")
    acct = manager._load_account("acct1")
    assert "IRRELEVANT" not in acct["cookies"]


def test_get_account_returns_lru(manager: GoogleAccountManager, sample_har: Path) -> None:
    """get_account returns the least-recently-used account."""
    manager.import_from_har(str(sample_har), "acct1")
    manager.import_from_har(str(sample_har), "acct2")

    # Touch acct1 first
    a1 = manager.get_account()
    assert a1 is not None
    first_id = a1["account_id"]

    # Next call should prefer acct2 (acct1 was just used)
    a2 = manager.get_account()
    assert a2 is not None
    assert a2["account_id"] != first_id


def test_mark_rate_limited_prevents_selection(
    manager: GoogleAccountManager, sample_har: Path
) -> None:
    """A rate-limited account must not be returned by get_account."""
    manager.import_from_har(str(sample_har), "acct1")
    manager.mark_rate_limited("acct1", backoff_seconds=3600)
    result = manager.get_account()
    assert result is None


def test_sapisid_hash_format_is_correct(
    manager: GoogleAccountManager, sample_har: Path
) -> None:
    """get_sapisid_hash should return '{timestamp}_{sha1hex}'."""
    manager.import_from_har(str(sample_har), "acct1")
    before = int(time.time())
    h = manager.get_sapisid_hash("acct1", "https://aistudio.google.com")
    after = int(time.time())

    assert h is not None
    parts = h.split("_", 1)
    assert len(parts) == 2
    ts, digest = int(parts[0]), parts[1]
    assert before <= ts <= after + 1
    assert len(digest) == 40  # SHA-1 hex length


def test_available_count_decrements_when_rate_limited(
    manager: GoogleAccountManager, sample_har: Path
) -> None:
    """available_count should drop by 1 when an account is rate-limited."""
    manager.import_from_har(str(sample_har), "acct1")
    manager.import_from_har(str(sample_har), "acct2")
    assert manager.available_count() == 2
    manager.mark_rate_limited("acct1")
    assert manager.available_count() == 1


def test_import_all_from_directory(tmp_path: Path) -> None:
    """import_all_from_directory should scan all .har files."""
    har_dir = tmp_path / "hars"
    har_dir.mkdir()
    accounts_dir = tmp_path / "accounts"

    har_body = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://notebooklm.google.com/",
                        "headers": [
                            {
                                "name": "cookie",
                                "value": "SAPISID=x; SID=longsidvalue123",
                            }
                        ],
                        "cookies": [],
                    },
                    "response": {"content": {"text": ""}},
                }
            ]
        }
    }
    (har_dir / "user_a.har").write_text(json.dumps(har_body))
    (har_dir / "user_b.har").write_text(json.dumps(har_body))

    mgr = GoogleAccountManager(data_dir=accounts_dir)
    count = mgr.import_all_from_directory(str(har_dir))
    assert count == 2
    assert mgr.account_count() == 2


def test_import_all_from_directory_missing_returns_zero(tmp_path: Path) -> None:
    """import_all_from_directory with a non-existent path returns 0, not an error."""
    mgr = GoogleAccountManager(data_dir=tmp_path / "accounts")
    count = mgr.import_all_from_directory(str(tmp_path / "nonexistent_dir"))
    assert count == 0


def test_no_sapisid_returns_none(manager: GoogleAccountManager, tmp_path: Path) -> None:
    """get_sapisid_hash returns None when the account has no SAPISID cookie."""
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://notebooklm.google.com/",
                        "headers": [
                            {"name": "cookie", "value": "SID=only_sid_here_long_value"}
                        ],
                        "cookies": [],
                    },
                    "response": {"content": {"text": ""}},
                }
            ]
        }
    }
    har_path = tmp_path / "no_sapisid.har"
    har_path.write_text(json.dumps(har))
    manager.import_from_har(str(har_path), "no_sap")
    result = manager.get_sapisid_hash("no_sap", "https://aistudio.google.com")
    assert result is None


def test_cookies_saved_and_reloaded(manager: GoogleAccountManager, sample_har: Path) -> None:
    """Cookies saved during import should survive a fresh load."""
    manager.import_from_har(str(sample_har), "persist_test")
    # Re-instantiate pointing at same directory
    mgr2 = GoogleAccountManager(data_dir=manager._data_dir)
    acct = mgr2._load_account("persist_test")
    assert acct is not None
    assert "SAPISID" in acct["cookies"]


def test_no_accounts_returns_none(manager: GoogleAccountManager) -> None:
    """get_account returns None when the pool is empty."""
    result = manager.get_account()
    assert result is None
