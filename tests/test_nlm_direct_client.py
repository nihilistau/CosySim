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


def test_get_page_params_prefers_preloaded_values(client: NLMDirectClient) -> None:
    """Explicitly preloaded session params are used without hitting the network."""
    client._bl = "boq_test_label"
    client._f_sid = "-12345"

    with patch.object(client._session, "get") as mock_get:
        result = client._get_page_params()

    assert result == ("boq_test_label", "-12345")
    mock_get.assert_not_called()


def test_load_saved_session_params_prefers_service_sessions() -> None:
    """NotebookLM service_sessions are treated as the canonical saved session source."""
    account = MagicMock()
    account.service_sessions = {
        "notebooklm": {
            "bl": "boq_labs-tailwind-frontend_20260305.05_p0",
            "f_sid": "-99999",
            "at": "service-at",
        }
    }
    account.nlm_session = {
        "bl": "boq_labs-tailwind-frontend_20260304.01_p0",
        "f_sid": "-12345",
        "at": "legacy-at",
    }

    client = NLMDirectClient(account)

    assert client._bl == "boq_labs-tailwind-frontend_20260305.05_p0"
    assert client._f_sid == "-99999"
    assert client._at_token == "service-at"


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


# ──── SDK gap methods ──────────────────────────────────────────────────────────


def test_get_notebook_returns_dict(client: NLMDirectClient) -> None:
    """Happy path: returns dict result as-is."""
    with patch.object(client, "_rpc_call", return_value={"id": "nb-1", "title": "T"}) as mock_rpc:
        result = client.get_notebook("nb-1")
    assert result["id"] == "nb-1"
    mock_rpc.assert_called_once_with("mFtdI", ["nb-1"], timeout=30)


def test_get_notebook_wraps_list_result(client: NLMDirectClient) -> None:
    """Wraps list result with notebook_id."""
    with patch.object(client, "_rpc_call", return_value=["nb-1", "Title", 3]):
        result = client.get_notebook("nb-1")
    assert result["id"] == "nb-1"
    assert "raw" in result


def test_get_notebook_returns_id_on_none(client: NLMDirectClient) -> None:
    """Returns minimal dict when RPC returns None."""
    with patch.object(client, "_rpc_call", return_value=None):
        result = client.get_notebook("nb-1")
    assert result == {"id": "nb-1"}


def test_get_source_calls_correct_rpc(client: NLMDirectClient) -> None:
    """Calls K4YCPe with [notebook_id, source_id]."""
    with patch.object(client, "_rpc_call", return_value={"id": "s-1"}) as mock_rpc:
        result = client.get_source("nb-1", "s-1")
    assert result["id"] == "s-1"
    mock_rpc.assert_called_once_with("K4YCPe", ["nb-1", "s-1"], timeout=30)


def test_get_source_wraps_list(client: NLMDirectClient) -> None:
    """Wraps list result with id and notebook_id."""
    with patch.object(client, "_rpc_call", return_value=["s-1", "My Source"]):
        result = client.get_source("nb-1", "s-1")
    assert result["id"] == "s-1"
    assert result["notebook_id"] == "nb-1"


def test_list_sources_returns_list_of_dicts(client: NLMDirectClient) -> None:
    """Parses list of dict items."""
    rpc_result = [{"id": "s-1", "type": "url"}, {"id": "s-2", "type": "text"}]
    with patch.object(client, "_rpc_call", return_value=rpc_result) as mock_rpc:
        sources = client.list_sources("nb-1")
    assert len(sources) == 2
    assert sources[0]["id"] == "s-1"
    mock_rpc.assert_called_once_with("jtGGne", ["nb-1"], timeout=30)


def test_list_sources_wraps_non_dict_items(client: NLMDirectClient) -> None:
    """Wraps non-dict list items in {'raw': item}."""
    with patch.object(client, "_rpc_call", return_value=[["s-1", "url"], ["s-2", "text"]]):
        sources = client.list_sources("nb-1")
    assert all("raw" in s for s in sources)


def test_list_sources_returns_empty_on_none(client: NLMDirectClient) -> None:
    """Returns empty list when RPC returns None."""
    with patch.object(client, "_rpc_call", return_value=None):
        assert client.list_sources("nb-1") == []


def test_process_source_calls_correct_rpc(client: NLMDirectClient) -> None:
    """Calls bfEAsb with [notebook_id, source_id]."""
    with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
        client.process_source("nb-1", "s-1")
    mock_rpc.assert_called_once_with("bfEAsb", ["nb-1", "s-1"], timeout=60)


def test_add_source_dispatches_url(client: NLMDirectClient) -> None:
    """Dispatches 'url' type to add_source_url."""
    with patch.object(client, "add_source_url", return_value="s-url") as mock:
        result = client.add_source("nb-1", "url", "https://example.com", title="Ex")
    mock.assert_called_once_with("nb-1", "https://example.com", title="Ex")
    assert result == "s-url"


def test_add_source_dispatches_text(client: NLMDirectClient) -> None:
    """Dispatches 'text' type to add_source_text."""
    with patch.object(client, "add_source_text", return_value="s-text") as mock:
        result = client.add_source("nb-1", "text", "some content")
    mock.assert_called_once_with("nb-1", "some content", title="Text Source")
    assert result == "s-text"


def test_add_source_dispatches_file(client: NLMDirectClient) -> None:
    """Dispatches 'file' type to add_source_file."""
    with patch.object(client, "add_source_file", return_value="s-file") as mock:
        result = client.add_source("nb-1", "file", "/path/to/doc.pdf")
    mock.assert_called_once_with("nb-1", "/path/to/doc.pdf")
    assert result == "s-file"


def test_add_source_raises_on_unknown_type(client: NLMDirectClient) -> None:
    """Raises ValueError for unknown source type."""
    with pytest.raises(ValueError, match="Unknown source_type"):
        client.add_source("nb-1", "video", "https://youtube.com/x")


def test_send_chat_message_returns_string(client: NLMDirectClient) -> None:
    """Returns first list element as string."""
    with patch.object(client, "_rpc_call", return_value=["Hello from NLM"]) as mock_rpc:
        result = client.send_chat_message("nb-1", "What is this about?")
    assert result == "Hello from NLM"
    mock_rpc.assert_called_once_with("tJHFsf", ["nb-1", "What is this about?", None], timeout=120)


def test_send_chat_message_with_conversation_id(client: NLMDirectClient) -> None:
    """Passes conversation_id through payload."""
    with patch.object(client, "_rpc_call", return_value=["reply"]) as mock_rpc:
        client.send_chat_message("nb-1", "Follow up", conversation_id="conv-42")
    mock_rpc.assert_called_once_with("tJHFsf", ["nb-1", "Follow up", "conv-42"], timeout=120)


def test_send_chat_message_returns_empty_on_none(client: NLMDirectClient) -> None:
    """Returns empty string when RPC returns None."""
    with patch.object(client, "_rpc_call", return_value=None):
        assert client.send_chat_message("nb-1", "hello") == ""


def test_get_shared_notebook_returns_dict(client: NLMDirectClient) -> None:
    """Returns dict result from RPC."""
    with patch.object(client, "_rpc_call", return_value={"id": "nb-shared"}) as mock_rpc:
        result = client.get_shared_notebook("share-token-123")
    assert result["id"] == "nb-shared"
    mock_rpc.assert_called_once_with("jzEKsc", ["share-token-123"], timeout=30)


def test_get_shared_notebook_wraps_list(client: NLMDirectClient) -> None:
    """Wraps list result with share_token."""
    with patch.object(client, "_rpc_call", return_value=["nb-id", "Shared NB"]):
        result = client.get_shared_notebook("share-tok")
    assert result["share_token"] == "share-tok"


def test_get_notebook_analysis_passes_depth(client: NLMDirectClient) -> None:
    """Passes [analysis_depth] as second payload element."""
    with patch.object(client, "_rpc_call", return_value={"themes": ["A"]}) as mock_rpc:
        result = client.get_notebook_analysis("nb-1", analysis_depth=2)
    assert result["themes"] == ["A"]
    mock_rpc.assert_called_once_with("VfAZjd", ["nb-1", [2]], timeout=60)


def test_get_notebook_analysis_wraps_list(client: NLMDirectClient) -> None:
    """Wraps list result with notebook_id key."""
    with patch.object(client, "_rpc_call", return_value=[["theme_A"], 0.9]):
        result = client.get_notebook_analysis("nb-1")
    assert result["notebook_id"] == "nb-1"
    assert "analysis" in result


def test_get_audio_overview_options_uses_source_path(client: NLMDirectClient) -> None:
    """Passes notebook source_path to _rpc_call."""
    with patch.object(client, "_rpc_call", return_value=[[1, "Deep Dive"], [2, "Brief"]]) as mock_rpc:
        options = client.get_audio_overview_options("nb-1")
    assert mock_rpc.call_args.kwargs.get("source_path") == "/notebook/nb-1"
    assert len(options) == 2


def test_get_audio_overview_options_returns_empty_on_none(client: NLMDirectClient) -> None:
    """Returns empty list when RPC returns None."""
    with patch.object(client, "_rpc_call", return_value=None):
        assert client.get_audio_overview_options("nb-1") == []


def test_get_ice_config_calls_correct_rpc(client: NLMDirectClient) -> None:
    """Calls Of0kDd with [notebook_id]."""
    with patch.object(client, "_rpc_call", return_value={"ice_servers": []}) as mock_rpc:
        result = client.get_ice_config("nb-1")
    assert "ice_servers" in result
    mock_rpc.assert_called_once_with("Of0kDd", ["nb-1"], timeout=15)


def test_send_sdp_offer_calls_correct_rpc(client: NLMDirectClient) -> None:
    """Calls eyWvXc with [notebook_id, sdp_offer, session_id]."""
    with patch.object(client, "_rpc_call", return_value=["sdp-answer", "sess-1"]) as mock_rpc:
        result = client.send_sdp_offer("nb-1", "v=0\r\n...", session_id="sess-1")
    assert result["sdp_answer"] == "sdp-answer"
    mock_rpc.assert_called_once_with("eyWvXc", ["nb-1", "v=0\r\n...", "sess-1"], timeout=30)


def test_update_notebook_delegates_to_title(client: NLMDirectClient) -> None:
    """update_notebook delegates to update_notebook_title."""
    with patch.object(client, "update_notebook_title") as mock:
        client.update_notebook("nb-1", "New Title")
    mock.assert_called_once_with("nb-1", "New Title")
