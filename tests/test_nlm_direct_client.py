"""Tests for NLMDirectClient — 6 new notebook management methods."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.nlm_direct_client import (
    GUIDE_BRIEFING,
    GUIDE_FAQ,
    GUIDE_STUDY,
    NLMDirectClient,
)


# ──── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> NLMDirectClient:
    """NLMDirectClient with a mock account."""
    account = MagicMock()
    return NLMDirectClient(account)


# ──── create_notebook ──────────────────────────────────────────────────────────


def test_create_notebook_returns_id(client: NLMDirectClient) -> None:
    """Happy path: returns notebook ID from RPC result."""
    with patch.object(client, "_rpc_call", return_value=["nb-abc123"]) as mock_rpc:
        result = client.create_notebook("Test Notebook")
    assert result == "nb-abc123"
    mock_rpc.assert_called_once_with("VqhFhd", ["Test Notebook", None, None], timeout=30)


def test_create_notebook_raises_on_none(client: NLMDirectClient) -> None:
    """Raises RuntimeError when RPC returns None."""
    with patch.object(client, "_rpc_call", return_value=None):
        with pytest.raises(RuntimeError, match="create_notebook failed"):
            client.create_notebook("Test")


def test_create_notebook_raises_on_empty_list(client: NLMDirectClient) -> None:
    """Raises RuntimeError when RPC returns empty list."""
    with patch.object(client, "_rpc_call", return_value=[]):
        with pytest.raises(RuntimeError, match="create_notebook failed"):
            client.create_notebook("Test")


# ──── delete_notebook ──────────────────────────────────────────────────────────


def test_delete_notebook_calls_correct_rpc(client: NLMDirectClient) -> None:
    """Calls kVoZqc with [[notebook_id]] payload."""
    with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
        client.delete_notebook("nb-xyz")
    mock_rpc.assert_called_once_with("kVoZqc", [["nb-xyz"]], timeout=30)


def test_delete_notebook_returns_none(client: NLMDirectClient) -> None:
    """Returns None on success."""
    with patch.object(client, "_rpc_call", return_value=None):
        result = client.delete_notebook("nb-xyz")
    assert result is None


# ──── get_chat_history ─────────────────────────────────────────────────────────


def test_get_chat_history_parses_list_items(client: NLMDirectClient) -> None:
    """Parses list-format turns into role/text dicts."""
    rpc_result = [["user", "Hello NLM"], ["model", "Hello! How can I help?"]]
    with patch.object(client, "_rpc_call", return_value=rpc_result) as mock_rpc:
        turns = client.get_chat_history("nb-123")
    assert len(turns) == 2
    assert turns[0] == {"role": "user", "text": "Hello NLM"}
    assert turns[1] == {"role": "model", "text": "Hello! How can I help?"}
    mock_rpc.assert_called_once_with("GzgSEd", ["nb-123"], timeout=30)


def test_get_chat_history_passes_through_dict_items(client: NLMDirectClient) -> None:
    """Passes through dict-format turns unchanged."""
    rpc_result = [{"role": "user", "text": "hi"}, {"role": "model", "text": "hello"}]
    with patch.object(client, "_rpc_call", return_value=rpc_result):
        turns = client.get_chat_history("nb-123")
    assert turns == rpc_result


def test_get_chat_history_returns_empty_on_none(client: NLMDirectClient) -> None:
    """Returns empty list when RPC returns None."""
    with patch.object(client, "_rpc_call", return_value=None):
        turns = client.get_chat_history("nb-123")
    assert turns == []


# ──── delete_chat_history ──────────────────────────────────────────────────────


def test_delete_chat_history_calls_correct_rpc(client: NLMDirectClient) -> None:
    """Calls GfmCOc with [notebook_id] payload."""
    with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
        client.delete_chat_history("nb-456")
    mock_rpc.assert_called_once_with("GfmCOc", ["nb-456"], timeout=30)


def test_delete_chat_history_returns_none(client: NLMDirectClient) -> None:
    """Returns None on success."""
    with patch.object(client, "_rpc_call", return_value=None):
        result = client.delete_chat_history("nb-456")
    assert result is None


# ──── generate_guide ──────────────────────────────────────────────────────────


def test_generate_guide_returns_dict(client: NLMDirectClient) -> None:
    """Happy path: returns id/title/content dict."""
    rpc_result = ["guide-001", "Study Guide: Topic X", "## Key Concepts\n- A\n- B"]
    with patch.object(client, "_rpc_call", return_value=rpc_result) as mock_rpc:
        guide = client.generate_guide("nb-789", guide_type=GUIDE_STUDY)
    assert guide["id"] == "guide-001"
    assert guide["title"] == "Study Guide: Topic X"
    assert "Key Concepts" in guide["content"]
    mock_rpc.assert_called_once_with(
        "xqEXEf", [None, "nb-789", GUIDE_STUDY, []], timeout=180
    )


def test_generate_guide_with_source_ids(client: NLMDirectClient) -> None:
    """Passes source IDs as nested list payload."""
    rpc_result = ["g-2", "FAQ", "Q: What? A: This."]
    with patch.object(client, "_rpc_call", return_value=rpc_result) as mock_rpc:
        guide = client.generate_guide("nb-789", guide_type=GUIDE_FAQ, source_ids=["s1", "s2"])
    mock_rpc.assert_called_once_with(
        "xqEXEf", [None, "nb-789", GUIDE_FAQ, [["s1"], ["s2"]]], timeout=180
    )
    assert guide["id"] == "g-2"


def test_generate_guide_raises_on_empty(client: NLMDirectClient) -> None:
    """Raises RuntimeError when RPC returns falsy result."""
    with patch.object(client, "_rpc_call", return_value=None):
        with pytest.raises(RuntimeError, match="generate_guide returned empty"):
            client.generate_guide("nb-789")


def test_generate_guide_default_title_on_short_result(client: NLMDirectClient) -> None:
    """Falls back to default title when result has only one element."""
    with patch.object(client, "_rpc_call", return_value=["id-only"]):
        guide = client.generate_guide("nb-789", guide_type=GUIDE_BRIEFING)
    assert guide["id"] == "id-only"
    assert "3" in guide["title"]  # GUIDE_BRIEFING = 3
    assert guide["content"] == ""


# ──── share_notebook ──────────────────────────────────────────────────────────


def test_share_notebook_returns_url_from_list(client: NLMDirectClient) -> None:
    """Returns URL string from list result."""
    with patch.object(
        client, "_rpc_call", return_value=["https://notebooklm.google.com/share/abc"]
    ) as mock_rpc:
        url = client.share_notebook("nb-001")
    assert url == "https://notebooklm.google.com/share/abc"
    mock_rpc.assert_called_once_with("dI5Y8", ["nb-001", 1], timeout=30)


def test_share_notebook_returns_url_from_string(client: NLMDirectClient) -> None:
    """Returns URL directly when RPC returns a string."""
    with patch.object(client, "_rpc_call", return_value="https://notebooklm.google.com/share/xyz"):
        url = client.share_notebook("nb-001", share_level=0)
    assert url == "https://notebooklm.google.com/share/xyz"


def test_share_notebook_raises_on_empty(client: NLMDirectClient) -> None:
    """Raises RuntimeError when RPC returns no URL."""
    with patch.object(client, "_rpc_call", return_value=None):
        with pytest.raises(RuntimeError, match="share_notebook returned no URL"):
            client.share_notebook("nb-001")


def test_share_notebook_private_level(client: NLMDirectClient) -> None:
    """Passes share_level=0 correctly to RPC."""
    with patch.object(client, "_rpc_call", return_value=["https://x.com/s/priv"]) as mock_rpc:
        client.share_notebook("nb-002", share_level=0)
    mock_rpc.assert_called_once_with("dI5Y8", ["nb-002", 0], timeout=30)
