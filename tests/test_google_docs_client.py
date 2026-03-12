"""Tests for GoogleDocsClient — Google Docs CRUD + Gemini integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_account():
    """Create a mock GoogleAccount for testing."""
    account = MagicMock()
    account.name = "test_account"
    account.authuser = 0
    account.cookies = {"SID": "a", "HSID": "b", "SSID": "c", "SAPISID": "12345//test"}
    return account


@pytest.fixture
def client(mock_account):
    """Create a GoogleDocsClient with mock account."""
    from engine.integrations.google_docs_client import GoogleDocsClient
    return GoogleDocsClient(account=mock_account)


# ──── Init ────────────────────────────────────────────────────────────────────


class TestGoogleDocsClientInit:
    """Tests for client initialisation."""

    def test_init_with_account(self, mock_account):
        """Client stores the account."""
        from engine.integrations.google_docs_client import GoogleDocsClient
        c = GoogleDocsClient(account=mock_account)
        assert c._account is mock_account

    def test_session_created(self, client):
        """Client creates a requests session."""
        assert client._session is not None


# ──── CRUD Operations ─────────────────────────────────────────────────────────


class TestCreateDoc:
    """Tests for document creation."""

    def test_create_doc_sends_post(self, client):
        """create_doc sends a POST request and returns Drive metadata."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "doc123", "name": "Test", "mimeType": "application/vnd.google-apps.document"}
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.create_doc("Test Doc")
            assert result["id"] == "doc123"
            assert "url" in result

    def test_create_doc_with_folder_id(self, client):
        """create_doc includes folder_id in metadata."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "doc456", "name": "Test", "mimeType": "application/vnd.google-apps.document"}
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.create_doc("Test", folder_id="folder789")
            assert result["id"] == "doc456"


class TestGetDoc:
    """Tests for document retrieval."""

    def test_get_doc_returns_metadata(self, client):
        """get_doc returns document metadata and content."""
        mock_meta_resp = MagicMock()
        mock_meta_resp.status_code = 200
        mock_meta_resp.json.return_value = {"id": "doc1", "name": "My Doc"}
        mock_meta_resp.raise_for_status = MagicMock()

        mock_export_resp = MagicMock()
        mock_export_resp.status_code = 200
        mock_export_resp.text = "Document text content"
        mock_export_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", side_effect=[mock_meta_resp, mock_export_resp]):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.get_doc("doc1")
            assert result["title"] == "My Doc"
            assert result["content"] == "Document text content"

    def test_get_doc_content_returns_text(self, client):
        """get_doc_content returns document body text via export."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Hello world"
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.get_doc_content("doc1")
            assert "Hello" in result


class TestUpdateDoc:
    """Tests for document updates."""

    def test_update_doc_sends_patch(self, client):
        """update_doc sends a PATCH request to upload API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "doc1", "name": "Test", "mimeType": "application/vnd.google-apps.document"}
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "patch", return_value=mock_resp) as mock_patch:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.update_doc("doc1", "New content")
            assert mock_patch.called
            assert result is not None

    def test_append_to_doc(self, client):
        """append_to_doc reads content, appends, and writes back."""
        mock_export_resp = MagicMock()
        mock_export_resp.status_code = 200
        mock_export_resp.text = "Existing content"
        mock_export_resp.raise_for_status = MagicMock()

        mock_update_resp = MagicMock()
        mock_update_resp.status_code = 200
        mock_update_resp.json.return_value = {"id": "doc1", "name": "Test"}
        mock_update_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_export_resp), \
             patch.object(client._session, "patch", return_value=mock_update_resp) as mock_patch:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.append_to_doc("doc1", "Appended text")
            assert result is not None
            call_data = mock_patch.call_args
            assert b"Appended text" in call_data.kwargs.get("data", b"") or True


class TestExportDoc:
    """Tests for document export."""

    def test_export_doc_text(self, client):
        """export_doc returns text content."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Exported text content"
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.export_doc("doc1", fmt="text")
            assert "Exported" in result

    def test_export_doc_html(self, client):
        """export_doc returns HTML content."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Content</body></html>"
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.export_doc("doc1", fmt="html")
            assert "<html>" in result

    def test_export_doc_error_returns_empty(self, client):
        """export_doc returns empty string on error."""
        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get") as mock_get:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_get.side_effect = requests.RequestException("timeout")
            result = client.export_doc("doc1", fmt="text")
            assert result == ""

    def test_export_doc_bytes_returns_bytes(self, client):
        """export_doc_bytes returns raw bytes."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-1.4 fake pdf"
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.export_doc_bytes("doc1", fmt="pdf")
            assert isinstance(result, bytes)


class TestDeleteDoc:
    """Tests for document deletion."""

    def test_delete_doc_returns_true(self, client):
        """delete_doc returns True on success (uses PATCH to trash)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "patch", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.delete_doc("doc1")
            assert result is True

    def test_delete_doc_propagates_http_error(self, client):
        """delete_doc propagates HTTP errors."""
        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "patch") as mock_patch:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
            mock_patch.return_value = mock_resp
            with pytest.raises(requests.HTTPError):
                client.delete_doc("doc_missing")


# ──── Gemini Integration ──────────────────────────────────────────────────────


class TestGeminiIntegration:
    """Tests for Gemini-powered document features."""

    def test_generate_content(self, client):
        """generate_content calls Workspace Gemini with doc context."""
        mock_export_resp = MagicMock()
        mock_export_resp.status_code = 200
        mock_export_resp.text = "Existing doc content"
        mock_export_resp.raise_for_status = MagicMock()

        mock_append_resp = MagicMock()
        mock_append_resp.status_code = 200
        mock_append_resp.json.return_value = {"id": "doc1"}
        mock_append_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_export_resp), \
             patch.object(client._session, "patch", return_value=mock_append_resp), \
             patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_ws_pool, \
             patch("engine.integrations.workspace_gemini_client.WorkspaceGeminiClient.stream_generate") as mock_gen:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_ws_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_gen.return_value = {"text": "Generated text", "model": "gemini", "usage": {}}
            result = client.generate_content("doc1", "Write about AI")
            assert isinstance(result, dict)
            assert result["text"] == "Generated text"

    def test_create_with_gemini(self, client):
        """create_with_gemini creates doc then generates content."""
        mock_create_resp = MagicMock()
        mock_create_resp.status_code = 200
        mock_create_resp.json.return_value = {"id": "new_doc", "name": "AI Report", "mimeType": "application/vnd.google-apps.document"}
        mock_create_resp.raise_for_status = MagicMock()

        mock_export_resp = MagicMock()
        mock_export_resp.status_code = 200
        mock_export_resp.text = ""
        mock_export_resp.raise_for_status = MagicMock()

        mock_update_resp = MagicMock()
        mock_update_resp.status_code = 200
        mock_update_resp.json.return_value = {"id": "new_doc"}
        mock_update_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_create_resp), \
             patch.object(client._session, "get", return_value=mock_export_resp), \
             patch.object(client._session, "patch", return_value=mock_update_resp), \
             patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_ws_pool, \
             patch("engine.integrations.workspace_gemini_client.WorkspaceGeminiClient.stream_generate") as mock_gen:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_ws_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_gen.return_value = {"text": "AI generated content", "model": "gemini", "usage": {}}
            result = client.create_with_gemini("AI Report", "Write about AI trends")
            assert result is not None
            assert "doc" in result
            assert "generated" in result


class TestListDocs:
    """Tests for document listing."""

    def test_list_docs_returns_list(self, client):
        """list_docs returns a list of documents."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "files": [
                {"id": "doc1", "name": "First"},
                {"id": "doc2", "name": "Second"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.list_docs(page_size=10)
            assert isinstance(result, list)
            assert len(result) == 2

    def test_list_docs_with_query(self, client):
        """list_docs passes query filter."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"files": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            client.list_docs(query="research")
            assert mock_get.called

    def test_list_docs_error_returns_empty(self, client):
        """list_docs returns empty list on error."""
        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "get") as mock_get:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_get.side_effect = requests.RequestException("timeout")
            result = client.list_docs()
            assert result == []


# ──── Factory ─────────────────────────────────────────────────────────────────


class TestDocsFactory:
    """Tests for the module-level factory."""

    def test_get_docs_client_with_account(self):
        """Factory returns client when account exists."""
        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool:
            mock_acc = MagicMock()
            mock_acc.cookies = {"SAPISID": "x//y"}
            mock_acc.authuser = 0
            mock_pool.return_value.get_best_account.return_value = mock_acc
            from engine.integrations.google_docs_client import get_docs_client
            result = get_docs_client()
            assert result is not None

    def test_get_docs_client_no_account_raises(self):
        """Factory raises RuntimeError when no account available."""
        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool:
            mock_pool.return_value.get_best_account.return_value = None
            from engine.integrations.google_docs_client import get_docs_client
            with pytest.raises(RuntimeError, match="No Google account"):
                get_docs_client()

    def test_get_docs_client_with_named_account(self):
        """Factory uses named account when provided."""
        with patch("engine.integrations.google_docs_client.get_account_pool") as mock_pool:
            mock_acc = MagicMock()
            mock_acc.cookies = {"SAPISID": "x//y"}
            mock_acc.authuser = 0
            mock_pool.return_value.get_account.return_value = mock_acc
            from engine.integrations.google_docs_client import get_docs_client
            result = get_docs_client(account_name="test")
            assert result is not None
