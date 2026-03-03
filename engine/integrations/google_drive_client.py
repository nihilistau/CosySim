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
_DRIVE_UPLOAD_BASE = "https://clients6.google.com/upload/drive/v3"
_DRIVE_ORIGIN = "https://drive.google.com"
_DRIVE_REFERER = "https://drive.google.com/"

_FOLDER_MIME = "application/vnd.google-apps.folder"
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
