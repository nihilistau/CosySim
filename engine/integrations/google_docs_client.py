"""Google Docs API client via docs.google.com and clients6.google.com.

Provides document creation, reading, writing, export, and Gemini-powered
content generation using the same Google session cookies used for Drive,
Sheets, and NotebookLM integrations.

Endpoints confirmed from HAR captures of Google Docs interactions (March 2026).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_DOCS_BASE = "https://docs.google.com"
_DRIVE_BASE = "https://clients6.google.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://clients6.google.com/upload/drive/v3"
_DOCS_MIME = "application/vnd.google-apps.document"
_DOCS_ORIGIN = "https://docs.google.com"
_DOCS_REFERER = "https://docs.google.com/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

# Export MIME types for document conversion
_EXPORT_MIMES = {
    "text": "text/plain",
    "html": "text/html",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "rtf": "application/rtf",
    "md": "text/markdown",
}


# ──── Client ─────────────────────────────────────────────────────────────────


class GoogleDocsClient:
    """Google Docs API client using browser session cookies.

    Provides document lifecycle operations (create, read, update, export) and
    Gemini-powered content generation via the Workspace Gemini endpoints.

    Args:
        account: Authenticated GoogleAccount from the pool.
    """

    def __init__(self, account: GoogleAccount) -> None:
        self._account = account
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _get_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build request headers with SAPISIDHASH auth.

        Args:
            extra: Additional headers to merge in.

        Returns:
            Complete headers dict.
        """
        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)
        sapisid = self._account.cookies.get("SAPISID", "")
        sapisid1p = self._account.cookies.get("__Secure-1PAPISID", sapisid)
        sapisid3p = self._account.cookies.get("__Secure-3PAPISID", sapisid)

        ts = str(int(time.time()))
        origin = _DOCS_ORIGIN

        def _hash(key: str, prefix: str = "SAPISIDHASH") -> str:
            digest = hashlib.sha1(f"{ts} {key} {origin}".encode()).hexdigest()
            return f"{prefix} {ts}_{digest}"

        auth_parts: List[str] = []
        if sapisid:
            auth_parts.append(_hash(sapisid))
        if sapisid1p:
            auth_parts.append(_hash(sapisid1p, "SAPISID1PHASH"))
        if sapisid3p:
            auth_parts.append(_hash(sapisid3p, "SAPISID3PHASH"))

        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": cookie_header,
            "Origin": origin,
            "Referer": _DOCS_REFERER,
            "X-Goog-Authuser": str(self._account.authuser),
            "X-Same-Domain": "1",
        }
        if auth_parts:
            headers["Authorization"] = " ".join(auth_parts)
        if extra:
            headers.update(extra)
        return headers

    # ──── Document Creation ──────────────────────────────────────────────────

    def create_doc(
        self,
        title: str,
        folder_id: Optional[str] = None,
        initial_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new Google Docs document in Drive.

        Args:
            title: Document title.
            folder_id: Optional parent folder ID to place the doc in.
            initial_content: Optional initial text content to insert.

        Returns:
            Dict with id, name, mimeType, and url of the created document.
        """
        metadata: Dict[str, Any] = {"name": title, "mimeType": _DOCS_MIME}
        if folder_id:
            metadata["parents"] = [folder_id]

        headers = self._get_headers({"Content-Type": "application/json"})
        params = {"fields": "id,name,mimeType"}
        resp = self._session.post(
            f"{_DRIVE_BASE}/files",
            headers=headers,
            params=params,
            json=metadata,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        doc_id = data["id"]
        data["url"] = f"https://docs.google.com/document/d/{doc_id}/edit"
        logger.info("Created Google Doc: %s (%s)", title, doc_id)

        if initial_content:
            self.update_doc(doc_id, initial_content)

        return data

    # ──── Document Reading ───────────────────────────────────────────────────

    def get_doc(self, doc_id: str) -> Dict[str, Any]:
        """Retrieve document metadata and content summary.

        Uses the Drive API to get file metadata and the Docs export to get
        text content.

        Args:
            doc_id: The Google Docs document ID.

        Returns:
            Dict with id, title, content (plain text), and metadata.
        """
        headers = self._get_headers({"Content-Type": "application/json"})

        # Get metadata via Drive API
        meta_resp = self._session.get(
            f"{_DRIVE_BASE}/files/{doc_id}",
            headers=headers,
            params={"fields": "id,name,mimeType,modifiedTime,size"},
            timeout=30,
        )
        meta_resp.raise_for_status()
        metadata = meta_resp.json()

        # Get text content via export
        content = self.export_doc(doc_id, fmt="text")

        return {
            "id": doc_id,
            "title": metadata.get("name", ""),
            "content": content,
            "metadata": metadata,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    def get_doc_content(self, doc_id: str) -> str:
        """Get the plain text content of a document.

        Args:
            doc_id: The Google Docs document ID.

        Returns:
            Document content as plain text string.
        """
        return self.export_doc(doc_id, fmt="text")

    # ──── Document Writing ───────────────────────────────────────────────────

    def update_doc(self, doc_id: str, content: str) -> Dict[str, Any]:
        """Replace document content with new text.

        Uploads the content as plain text which Drive converts to Docs format.
        This replaces the entire document content.

        Args:
            doc_id: The Google Docs document ID.
            content: New text content for the document.

        Returns:
            Updated file metadata dict.
        """
        headers = self._get_headers({"Content-Type": "text/plain"})
        params = {
            "uploadType": "media",
            "fields": "id,name,mimeType",
        }
        resp = self._session.patch(
            f"{_DRIVE_UPLOAD_BASE}/files/{doc_id}",
            headers=headers,
            params=params,
            data=content.encode("utf-8"),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug("Updated Google Doc: %s", doc_id)
        return data

    def append_to_doc(self, doc_id: str, content: str) -> Dict[str, Any]:
        """Append content to an existing document.

        Reads current content, appends new content, and writes back.

        Args:
            doc_id: The Google Docs document ID.
            content: Text content to append.

        Returns:
            Updated file metadata dict.
        """
        existing = self.get_doc_content(doc_id)
        combined = existing.rstrip() + "\n\n" + content if existing.strip() else content
        return self.update_doc(doc_id, combined)

    # ──── Document Export ────────────────────────────────────────────────────

    def export_doc(
        self,
        doc_id: str,
        fmt: str = "text",
    ) -> str:
        """Export a Google Doc to the specified format.

        Args:
            doc_id: The Google Docs document ID.
            fmt: Export format key: text, html, pdf, docx, rtf, md.

        Returns:
            Exported content as a string (text/html/md) or empty string on
            error.  Binary formats (pdf, docx) are returned as raw bytes
            cast to string — use ``export_doc_bytes`` for binary output.
        """
        mime = _EXPORT_MIMES.get(fmt, _EXPORT_MIMES["text"])
        headers = self._get_headers()

        try:
            resp = self._session.get(
                f"{_DRIVE_BASE}/files/{doc_id}/export",
                headers=headers,
                params={"mimeType": mime},
                timeout=60,
            )
            resp.raise_for_status()

            if fmt in ("text", "html", "md", "rtf"):
                return resp.text
            return resp.text
        except requests.RequestException as exc:
            logger.error("Doc export failed for %s: %s", doc_id, exc)
            return ""

    def export_doc_bytes(
        self,
        doc_id: str,
        fmt: str = "pdf",
    ) -> bytes:
        """Export a Google Doc as raw bytes (for binary formats).

        Args:
            doc_id: The Google Docs document ID.
            fmt: Export format key: pdf, docx.

        Returns:
            Raw bytes of the exported document.
        """
        mime = _EXPORT_MIMES.get(fmt, _EXPORT_MIMES["pdf"])
        headers = self._get_headers()

        resp = self._session.get(
            f"{_DRIVE_BASE}/files/{doc_id}/export",
            headers=headers,
            params={"mimeType": mime},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.content

    # ──── Document Management ────────────────────────────────────────────────

    def delete_doc(self, doc_id: str) -> bool:
        """Delete a Google Doc by moving it to trash.

        Args:
            doc_id: The Google Docs document ID.

        Returns:
            True if successfully deleted.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        resp = self._session.patch(
            f"{_DRIVE_BASE}/files/{doc_id}",
            headers=headers,
            json={"trashed": True},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Trashed Google Doc: %s", doc_id)
        return True

    def list_docs(
        self,
        folder_id: Optional[str] = None,
        query: Optional[str] = None,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """List Google Docs documents in Drive.

        Args:
            folder_id: Optional folder ID to filter by.
            query: Optional additional Drive query string.
            page_size: Maximum number of results.

        Returns:
            List of document metadata dicts.
        """
        q_parts = [f"mimeType='{_DOCS_MIME}'", "trashed=false"]
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        if query:
            q_parts.append(query)

        headers = self._get_headers({"Content-Type": "application/json"})
        params = {
            "fields": "files(id,name,mimeType,modifiedTime,size)",
            "pageSize": page_size,
            "q": " and ".join(q_parts),
        }

        try:
            resp = self._session.get(
                f"{_DRIVE_BASE}/files",
                headers=headers,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("files", [])
        except requests.RequestException as exc:
            logger.error("list_docs failed: %s", exc)
            return []

    # ──── Gemini Integration ─────────────────────────────────────────────────

    def generate_content(
        self,
        doc_id: str,
        prompt: str,
        append: bool = True,
    ) -> Dict[str, Any]:
        """Generate content for a doc using Workspace Gemini.

        Uses the WorkspaceGeminiClient's streamGenerate endpoint with the
        document context bound to the specified doc.

        Args:
            doc_id: The Google Docs document ID to generate content for.
            prompt: The generation prompt (e.g. "Help me create a project plan").
            append: If True, append generated content to the doc.  If False,
                only return the generated text without modifying the doc.

        Returns:
            Dict with ``text`` (generated content), ``doc_id``, ``appended``
            flag, and full generation result.
        """
        from engine.integrations.workspace_gemini_client import (
            WorkspaceGeminiClient,
        )

        gemini = WorkspaceGeminiClient(account=self._account)
        existing_content = self.get_doc_content(doc_id)

        result = gemini.stream_generate(
            prompt=prompt,
            context=existing_content[:8000] if existing_content else None,
            document_id=doc_id,
            document_type="docs",
        )

        if append and result.get("text"):
            self.append_to_doc(doc_id, result["text"])

        return {
            "text": result.get("text", ""),
            "doc_id": doc_id,
            "appended": append and bool(result.get("text")),
            "model": result.get("model", ""),
            "usage": result.get("usage", {}),
        }

    def create_with_gemini(
        self,
        title: str,
        prompt: str,
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new document and populate it with Gemini-generated content.

        Combines document creation with content generation in a single call.

        Args:
            title: Document title.
            prompt: Content generation prompt.
            folder_id: Optional parent folder ID.

        Returns:
            Dict with doc metadata, generated text, and generation result.
        """
        doc = self.create_doc(title=title, folder_id=folder_id)
        doc_id = doc["id"]

        gen_result = self.generate_content(
            doc_id=doc_id,
            prompt=prompt,
            append=True,
        )

        return {
            "doc": doc,
            "generated": gen_result,
        }


# ──── Factory ────────────────────────────────────────────────────────────────


def get_docs_client(
    account_name: Optional[str] = None,
) -> GoogleDocsClient:
    """Create a GoogleDocsClient with an account from the pool.

    Args:
        account_name: Optional account name to select from pool.

    Returns:
        Configured GoogleDocsClient instance.

    Raises:
        RuntimeError: If no suitable account is available.
    """
    pool = get_account_pool()
    if account_name:
        account = pool.get_account(account_name)
    else:
        account = pool.get_best_account(service="docs")
    if not account:
        raise RuntimeError("No Google account available for Docs client")
    return GoogleDocsClient(account=account)
