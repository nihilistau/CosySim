"""Google Drive API client via clients6.google.com.

Provides file upload, download, folder management, and permission control
using the same Google session cookies used for Colab and NotebookLM.

All endpoints confirmed from Google Drive HAR captures using clients6.google.com.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Union

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_DRIVE_BASE = "https://clients6.google.com/drive/v3"
_DRIVE_V2_BASE = "https://clients6.google.com/drive/v2beta"
_DRIVE_V2INT_BASE = "https://clients6.google.com/drive/v2internal"
_DRIVE_V2INT_UPLOAD_BASE = "https://clients6.google.com/upload/drive/v2internal"
_DRIVE_UPLOAD_BASE = "https://clients6.google.com/upload/drive/v3"
_DRIVE_ORIGIN = "https://drive.google.com"
_DRIVE_REFERER = "https://drive.google.com/"

_FOLDER_MIME = "application/vnd.google-apps.folder"

# v2internal API keys — different keys for different operation categories
_V2INT_KEY_READ = "AIzaSyAGzWfHQsxTHRSNkBG0DVRYon-iLYCkzCc"
_V2INT_KEY_UPLOAD = "AIzaSyBWdFphCtg4EBuxpHu9EhAjyIiY9C-4Uq4"
_V2INT_KEY_PERMS = "AIzaSyCdvSDZmdqokt5jTUat-x7mWlUoDCZzHHc"

_V2INT_COMMON_PARAMS: Dict[str, Any] = {
    "supportsTeamDrives": "true",
    "includeTeamDriveItems": "true",
    "enforceSingleParent": "true",
    "supportsAllDrives": "true",
}

# Export MIME type shortcuts
_EXPORT_MIMES: Dict[str, str] = {
    "text": "text/plain",
    "html": "text/html",
    "pdf": "application/pdf",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


# ──── Client ─────────────────────────────────────────────────────────────────

class GoogleDriveClient:
    """Google Drive API client using browser session cookies.

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
        origin = _DRIVE_ORIGIN

        def _hash(key: str, prefix: str = "SAPISIDHASH") -> str:
            digest = hashlib.sha1(f"{ts} {key} {origin}".encode()).hexdigest()
            return f"{prefix} {ts}_{digest}"

        auth_parts = []
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
            "Referer": _DRIVE_REFERER,
            "X-Goog-Authuser": str(self._account.authuser),
            "X-Same-Domain": "1",
        }
        if auth_parts:
            headers["Authorization"] = " ".join(auth_parts)
        if extra:
            headers.update(extra)
        return headers

    # ──── File listing ────────────────────────────────────────────────────────

    def list_files(
        self,
        folder_id: Optional[str] = None,
        query: Optional[str] = None,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """List files in a folder or matching a query.

        Args:
            folder_id: Optional folder ID to list contents of.
            query: Optional Drive query string (q parameter).
            page_size: Maximum number of results to return.

        Returns:
            List of file metadata dicts with id, name, mimeType, size, modifiedTime.
        """
        params: Dict[str, Any] = {
            "fields": "files(id,name,mimeType,size,modifiedTime,parents)",
            "pageSize": page_size,
        }
        q_parts = []
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        if query:
            q_parts.append(query)
        if q_parts:
            params["q"] = " and ".join(q_parts)

        headers = self._get_headers({"Content-Type": "application/json"})
        resp = self._session.get(
            f"{_DRIVE_BASE}/files", headers=headers, params=params, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("files", [])

    def get_file_metadata(self, file_id: str) -> Dict[str, Any]:
        """Get metadata for a specific file.

        Args:
            file_id: The Drive file ID.

        Returns:
            File metadata dict.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        resp = self._session.get(
            f"{_DRIVE_V2_BASE}/files/{file_id}", headers=headers, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    # ──── Download ────────────────────────────────────────────────────────────

    def download_file(self, file_id: str) -> bytes:
        """Download a file's raw bytes.

        Args:
            file_id: The Drive file ID.

        Returns:
            Raw file content as bytes.
        """
        headers = self._get_headers()
        params = {"alt": "media"}
        resp = self._session.get(
            f"{_DRIVE_BASE}/files/{file_id}",
            headers=headers,
            params=params,
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()
        return resp.content

    def download_text(self, file_id: str) -> str:
        """Download a file and decode as UTF-8 text.

        Args:
            file_id: The Drive file ID.

        Returns:
            File content as a string.
        """
        return self.download_file(file_id).decode("utf-8")

    # ──── Upload ──────────────────────────────────────────────────────────────

    def upload_file(
        self,
        name: str,
        content: Union[str, bytes],
        mime_type: str = "text/plain",
        folder_id: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload or update a file in Drive.

        If file_id is provided, updates the existing file content.
        Otherwise, creates a new file using multipart upload.

        Args:
            name: File name.
            content: File content as string or bytes.
            mime_type: MIME type of the file.
            folder_id: Optional parent folder ID.
            file_id: If set, update this existing file instead of creating.

        Returns:
            File metadata dict with id, name, mimeType.
        """
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content

        if file_id:
            return self._update_file(file_id, content_bytes, mime_type)

        return self._create_file(name, content_bytes, mime_type, folder_id)

    def _create_file(
        self,
        name: str,
        content: bytes,
        mime_type: str,
        folder_id: Optional[str],
    ) -> Dict[str, Any]:
        """Create a new file using multipart upload."""
        import email.mime.multipart
        import email.mime.base
        import email.mime.application

        metadata: Dict[str, Any] = {"name": name, "mimeType": mime_type}
        if folder_id:
            metadata["parents"] = [folder_id]

        metadata_json = json.dumps(metadata).encode("utf-8")

        boundary = "cosysim_boundary_" + str(int(time.time()))
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        ).encode("utf-8")
        body += metadata_json
        body += f"\r\n--{boundary}\r\n".encode("utf-8")
        body += f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8")
        body += content
        body += f"\r\n--{boundary}--".encode("utf-8")

        headers = self._get_headers(
            {
                "Content-Type": f"multipart/related; boundary={boundary}",
            }
        )

        params = {
            "uploadType": "multipart",
            "fields": "id,name,mimeType",
        }

        resp = self._session.post(
            f"{_DRIVE_UPLOAD_BASE}/files",
            headers=headers,
            params=params,
            data=body,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug("Created Drive file: %s (%s)", data.get("name"), data.get("id"))
        return data

    def _update_file(
        self,
        file_id: str,
        content: bytes,
        mime_type: str,
    ) -> Dict[str, Any]:
        """Update an existing file's content."""
        headers = self._get_headers({"Content-Type": mime_type})
        params = {
            "uploadType": "media",
            "fields": "id,name,mimeType",
        }
        resp = self._session.patch(
            f"{_DRIVE_UPLOAD_BASE}/files/{file_id}",
            headers=headers,
            params=params,
            data=content,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug("Updated Drive file: %s", file_id)
        return data

    # ──── Folder management ───────────────────────────────────────────────────

    def create_folder(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new folder in Drive.

        Args:
            name: Folder name.
            parent_id: Optional parent folder ID.

        Returns:
            Folder metadata dict with id, name, mimeType.
        """
        metadata: Dict[str, Any] = {
            "name": name,
            "mimeType": _FOLDER_MIME,
        }
        if parent_id:
            metadata["parents"] = [parent_id]

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
        logger.info("Created Drive folder: %s (%s)", data.get("name"), data.get("id"))
        return data

    def delete_file(self, file_id: str) -> bool:
        """Delete a file or folder from Drive.

        Args:
            file_id: The Drive file/folder ID.

        Returns:
            True if deleted successfully, False otherwise.
        """
        headers = self._get_headers()
        try:
            resp = self._session.delete(
                f"{_DRIVE_BASE}/files/{file_id}", headers=headers, timeout=30
            )
            resp.raise_for_status()
            logger.debug("Deleted Drive file: %s", file_id)
            return True
        except Exception as exc:
            logger.warning("Failed to delete Drive file %s: %s", file_id, exc)
            return False

    def find_or_create_folder(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> str:
        """Find a folder by name, creating it if it doesn't exist.

        Args:
            name: Folder name to find or create.
            parent_id: Optional parent folder ID to search within.

        Returns:
            The folder ID.
        """
        q_parts = [
            f"name='{name}'",
            f"mimeType='{_FOLDER_MIME}'",
            "trashed=false",
        ]
        if parent_id:
            q_parts.append(f"'{parent_id}' in parents")

        query = " and ".join(q_parts)
        files = self.list_files(query=query, page_size=1)

        if files:
            folder_id = files[0]["id"]
            logger.debug("Found existing folder '%s': %s", name, folder_id)
            return folder_id

        folder = self.create_folder(name, parent_id=parent_id)
        return folder["id"]

    # ──── Gemini Integration ─────────────────────────────────────────────────

    def ai_overview_search(
        self,
        query: str,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """Semantic search across Drive using AI Overviews.

        Uses Cloud Search to perform intent-based file discovery that goes
        beyond keyword matching.  Powers the "AI Overviews" feature in Drive.

        Args:
            query: Natural language search query (e.g. "the document mentioning
                last year's revenue numbers").
            page_size: Number of results to return.

        Returns:
            Dict with results list and search metadata.
        """
        from engine.integrations.workspace_gemini_client import (
            WorkspaceGeminiClient,
        )

        gemini = WorkspaceGeminiClient(account=self._account)
        return gemini.cloud_search(query=query, page_size=page_size)

    def ask_gemini(
        self,
        question: str,
        file_ids: Optional[List[str]] = None,
        max_context_files: int = 10,
    ) -> Dict[str, Any]:
        """Ask Gemini a question about Drive files.

        Mirrors the "Ask Gemini in Drive" feature that synthesises answers
        across multiple files.  If ``file_ids`` is provided, only those files
        are used as context.  Otherwise, Drive search finds relevant files.

        Args:
            question: The question to ask about the files.
            file_ids: Optional list of specific file IDs to use as context.
            max_context_files: Maximum files to include in context when
                searching (default: 10).

        Returns:
            Dict with ``answer`` (synthesised text), ``sources`` (files used),
            and ``model`` information.
        """
        from engine.integrations.workspace_gemini_client import (
            WorkspaceGeminiClient,
        )

        context_parts: List[str] = []
        sources: List[Dict[str, Any]] = []

        if file_ids:
            for fid in file_ids[:max_context_files]:
                try:
                    meta = self.get_file_metadata(fid)
                    content = self.download_text(fid)
                    context_parts.append(
                        f"--- File: {meta.get('title', fid)} ---\n{content[:4000]}"
                    )
                    sources.append({"id": fid, "name": meta.get("title", fid)})
                except Exception as exc:
                    logger.warning("Could not read file %s for context: %s", fid, exc)
        else:
            search_results = self.ai_overview_search(question, page_size=max_context_files)
            for item in search_results.get("results", []):
                metadata = item.get("metadata", {})
                fid = metadata.get("objectId", "")
                name = metadata.get("displayName", fid)
                if fid:
                    try:
                        content = self.download_text(fid)
                        context_parts.append(
                            f"--- File: {name} ---\n{content[:4000]}"
                        )
                        sources.append({"id": fid, "name": name})
                    except Exception:
                        pass

        full_context = "\n\n".join(context_parts) if context_parts else None

        gemini = WorkspaceGeminiClient(account=self._account)
        result = gemini.stream_generate(
            prompt=question,
            context=full_context,
            document_type="docs",
        )

        return {
            "answer": result.get("text", ""),
            "sources": sources,
            "model": result.get("model", ""),
            "usage": result.get("usage", {}),
        }

    # ──── CosySim helpers ─────────────────────────────────────────────────────

    def upload_text_to_cosysim_folder(
        self,
        name: str,
        content: str,
        subfolder: str = "nexus",
    ) -> Dict[str, Any]:
        """Upload a text file to the CosySim/subfolder directory in Drive.

        Finds or creates CosySim root folder, then finds or creates the
        named subfolder within it, then uploads the file there.

        Args:
            name: File name.
            content: Text content to upload.
            subfolder: Subfolder name inside CosySim (default: "nexus").

        Returns:
            File metadata dict including id, name, mimeType, and shareable_link.
        """
        root_id = self.find_or_create_folder("CosySim")
        sub_id = self.find_or_create_folder(subfolder, parent_id=root_id)
        result = self.upload_file(name, content, folder_id=sub_id)
        result["shareable_link"] = self.get_shareable_link(result["id"])
        return result

    def get_shareable_link(self, file_id: str) -> str:
        """Build a shareable Drive link for a file.

        Args:
            file_id: The Drive file ID.

        Returns:
            Shareable URL string.
        """
        return f"https://drive.google.com/file/d/{file_id}/view"

    def make_file_accessible_to_notebooklm(self, file_id: str) -> bool:
        """Set a file's permission so anyone with the link can read it.

        Required for NotebookLM to be able to ingest Drive files as sources.

        Args:
            file_id: The Drive file ID.

        Returns:
            True if permission was set, False on failure.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        body = {"type": "anyone", "role": "reader"}
        try:
            resp = self._session.post(
                f"{_DRIVE_BASE}/files/{file_id}/permissions",
                headers=headers,
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("Made file %s accessible to anyone with link", file_id)
            return True
        except Exception as exc:
            logger.warning("Failed to set permission on %s: %s", file_id, exc)
            return False

    # ──── Drive v2internal API ────────────────────────────────────────────────

    def _v2int_params(
        self,
        api_key: str,
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Build query params for v2internal requests.

        Args:
            api_key: The API key for this operation category.
            extra: Additional params to merge in.

        Returns:
            Complete query params dict.
        """
        params: Dict[str, str] = {"key": api_key}
        params.update(_V2INT_COMMON_PARAMS)
        if extra:
            params.update(extra)
        return params

    def v2_copy_file(
        self,
        file_id: str,
        title: Optional[str] = None,
        parent_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Copy a file using the v2internal API.

        Uses the internal copy endpoint which supports template duplication
        and preserves sharing settings that the public API may not.

        Args:
            file_id: Source file ID to copy.
            title: Title for the new copy. If None, uses original title.
            parent_id: Parent folder ID for the copy.
            description: Optional description for the copy.

        Returns:
            File metadata dict with id, title, alternateLink.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        params = self._v2int_params(
            _V2INT_KEY_READ,
            {"fields": "id,title,alternateLink,mimeType,parents"},
        )

        body: Dict[str, Any] = {}
        if title:
            body["title"] = title
        if parent_id:
            body["parents"] = [{"id": parent_id}]
        if description:
            body["description"] = description

        resp = self._session.post(
            f"{_DRIVE_V2INT_BASE}/files/{file_id}/copy",
            headers=headers,
            params=params,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "Copied Drive file %s → %s (%s)",
            file_id,
            data.get("id"),
            data.get("title"),
        )
        return data

    def v2_trash_file(self, file_id: str) -> Dict[str, Any]:
        """Move a file to trash using the v2internal API.

        Unlike ``delete_file`` which permanently deletes, this moves the file
        to the user's trash where it can be recovered within 30 days.

        Args:
            file_id: Drive file ID to trash.

        Returns:
            File metadata dict with labels.trashed = True.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        params = self._v2int_params(_V2INT_KEY_READ)

        resp = self._session.post(
            f"{_DRIVE_V2INT_BASE}/files/{file_id}/trash",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("Trashed Drive file %s", file_id)
        return data

    def v2_export_file(
        self,
        file_id: str,
        mime_type: str = "text/plain",
    ) -> bytes:
        """Export a Google Workspace file to a different format.

        Only works on Google-native file types (Docs, Sheets, Slides).
        For non-native files, use ``download_file`` instead.

        The ``mime_type`` can be a shortcut name (text, html, pdf, csv,
        docx, xlsx) or a full MIME type string.

        Args:
            file_id: Drive file ID (must be a Google Workspace file).
            mime_type: Target format — a MIME type or shortcut name.

        Returns:
            Exported file content as bytes.
        """
        resolved_mime = _EXPORT_MIMES.get(mime_type, mime_type)
        headers = self._get_headers()
        params = self._v2int_params(
            _V2INT_KEY_READ,
            {"mimeType": resolved_mime},
        )

        resp = self._session.get(
            f"{_DRIVE_V2INT_BASE}/files/{file_id}/export",
            headers=headers,
            params=params,
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()
        logger.debug(
            "Exported Drive file %s as %s (%d bytes)",
            file_id,
            resolved_mime,
            len(resp.content),
        )
        return resp.content

    def v2_get_permissions(self, file_id: str) -> List[Dict[str, Any]]:
        """List permissions on a file using the v2internal API.

        Returns richer permission data than the public API, including
        internal IDs and team drive membership info.

        Args:
            file_id: Drive file ID.

        Returns:
            List of permission dicts with emailAddress, role, type, id.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        params = self._v2int_params(
            _V2INT_KEY_PERMS,
            {"fields": "items(emailAddress,role,type,id,domain,withLink)"},
        )

        resp = self._session.get(
            f"{_DRIVE_V2INT_BASE}/files/{file_id}/permissions",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        logger.debug("Got %d permissions for file %s", len(items), file_id)
        return items

    def v2_insert_permission(
        self,
        file_id: str,
        role: str = "reader",
        perm_type: str = "anyone",
        email: Optional[str] = None,
        with_link: bool = True,
        send_notification: bool = False,
    ) -> Dict[str, Any]:
        """Add or modify sharing permissions using the v2internal API.

        Supports all v2internal permission roles: owner, organizer,
        fileOrganizer, writer, commenter, reader.

        Args:
            file_id: Drive file ID.
            role: Permission role — owner, organizer, fileOrganizer,
                writer, commenter, or reader.
            perm_type: Permission type — user, group, domain, or anyone.
            email: Email address (required when perm_type is user or group).
            with_link: Whether the permission requires the link to access.
            send_notification: Whether to send notification emails.

        Returns:
            Created permission dict.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        params = self._v2int_params(
            _V2INT_KEY_PERMS,
            {"sendNotificationEmails": str(send_notification).lower()},
        )

        body: Dict[str, Any] = {
            "role": role,
            "type": perm_type,
            "withLink": with_link,
        }
        if email and perm_type in ("user", "group"):
            body["emailAddress"] = email

        resp = self._session.post(
            f"{_DRIVE_V2INT_BASE}/files/{file_id}/permissions",
            headers=headers,
            params=params,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "Inserted %s/%s permission on file %s",
            role,
            perm_type,
            file_id,
        )
        return data

    def v2_update_metadata(
        self,
        file_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        starred: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update file metadata using the v2internal API.

        Args:
            file_id: Drive file ID.
            title: New title for the file.
            description: New description.
            parent_id: Move file to this parent folder.
            starred: Star or unstar the file.

        Returns:
            Updated file metadata dict.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        params = self._v2int_params(
            _V2INT_KEY_READ,
            {"fields": "id,title,modifiedDate,description,labels"},
        )

        body: Dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if parent_id is not None:
            body["parents"] = [{"id": parent_id}]
        if starred is not None:
            body["labels"] = {"starred": starred}

        if not body:
            logger.warning("v2_update_metadata called with no fields to update")
            return self.get_file_metadata(file_id)

        resp = self._session.put(
            f"{_DRIVE_V2INT_BASE}/files/{file_id}",
            headers=headers,
            params=params,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("Updated metadata for Drive file %s", file_id)
        return data


# ──── Factory ─────────────────────────────────────────────────────────────────

def get_drive_client(
    account_name: Optional[str] = None,
) -> Optional[GoogleDriveClient]:
    """Get a GoogleDriveClient for the named account or the next available one.

    Args:
        account_name: Specific account name, or None for round-robin selection.

    Returns:
        GoogleDriveClient, or None if no account is available.
    """
    pool = get_account_pool()

    if account_name:
        account = pool.get_by_name(account_name)
    else:
        account = pool.get_account("drive") or pool.get_account("colab") or pool.get_account("notebooklm")

    if account is None:
        logger.warning(
            "No Drive account available (requested: %s). "
            "Import an account with: pool.import_from_har(har_path, name, ['drive'])",
            account_name,
        )
        return None

    return GoogleDriveClient(account)
