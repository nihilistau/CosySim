"""Apps Script batchexecute client — reverse-engineered from HAR captures.

Provides access to the Apps Script IDE/editor backend via batchexecute RPCs:
- Project management (files, metadata, settings, history, versions)
- Code editing (save code, editor state, cursor position)
- Execution (run functions, list executions, triggers)
- Page initialization

All endpoints confirmed from script.google.com HAR captures and
batchexecute protocol analysis.
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

_APPSCRIPT_BASE = "https://script.google.com"
_APPSCRIPT_ORIGIN = "https://script.google.com"
_APPSCRIPT_REFERER = "https://script.google.com/"

_BUILD_LABEL = "boq_appsplatformconsoleuiserver_20260224.06_p2"
_SOC_APP = "779"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

# ──── RPC IDs ─────────────────────────────────────────────────────────────────

_RPCID_LIST_EXECUTIONS = "OOPYjd"
_RPCID_RUN_FUNCTION = "pEig0e"
_RPCID_GET_PROJECT_FILES = "OQOG2e"
_RPCID_GET_PROJECT_INFO = "NFMk7c"
_RPCID_GET_PROJECT_METADATA = "AvwHP"
_RPCID_SAVE_PROJECT = "GXx9jd"
_RPCID_SAVE_CODE = "toGAmc"
_RPCID_GET_PROJECT_SETTINGS = "UvGaob"
_RPCID_GET_EDITOR_STATE = "LuHlxe"
_RPCID_UPDATE_CURSOR = "ivJzse"
_RPCID_PAGE_INIT = "AJ6bre"
_RPCID_LIST_TRIGGERS = "KKLVD"
_RPCID_LIST_VERSIONS = "zzomTc"
_RPCID_GET_PROJECT_HISTORY = "yFXSbd"


# ──── Client ─────────────────────────────────────────────────────────────────


class AppsScriptClient:
    """Direct Apps Script IDE client using browser session cookies.

    Uses the batchexecute protocol to interact with the Apps Script editor
    backend, mirroring the browser's own RPC calls.

    Args:
        account: Authenticated GoogleAccount from the pool.
    """

    def __init__(self, account: GoogleAccount) -> None:
        self._account = account
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _get_headers(
        self,
        origin: str = _APPSCRIPT_ORIGIN,
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Build request headers with SAPISIDHASH auth.

        Args:
            origin: Origin URL for SAPISIDHASH computation.
            extra: Additional headers to merge in.

        Returns:
            Complete headers dict.
        """
        from engine.integrations.google_account_pool import get_account_pool

        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)
        sapisid = self._account.cookies.get("SAPISID", "")
        sapisid1p = self._account.cookies.get("__Secure-1PAPISID", sapisid)
        sapisid3p = self._account.cookies.get("__Secure-3PAPISID", sapisid)

        ts = str(int(time.time()))

        def _hash(key: str) -> str:
            digest = hashlib.sha1(f"{ts} {key} {origin}".encode()).hexdigest()
            return f"SAPISIDHASH {ts}_{digest}"

        auth_parts: List[str] = []
        if sapisid:
            auth_parts.append(_hash(sapisid))
        if sapisid1p:
            digest_1p = hashlib.sha1(
                f"{ts} {sapisid1p} {origin}".encode()
            ).hexdigest()
            auth_parts.append(f"SAPISID1PHASH {ts}_{digest_1p}")
        if sapisid3p:
            digest_3p = hashlib.sha1(
                f"{ts} {sapisid3p} {origin}".encode()
            ).hexdigest()
            auth_parts.append(f"SAPISID3PHASH {ts}_{digest_3p}")

        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Cookie": cookie_header,
            "Origin": origin,
            "Referer": _APPSCRIPT_REFERER,
            "X-Goog-Authuser": str(self._account.authuser),
            "X-Same-Domain": "1",
        }
        if auth_parts:
            headers["Authorization"] = " ".join(auth_parts)
        if extra:
            headers.update(extra)
        return headers

    # ──── batchexecute Protocol ───────────────────────────────────────────────

    def _batchexecute(
        self,
        rpcid: str,
        payload: list,
        project_id: str = "",
    ) -> Any:
        """Execute a batchexecute RPC against the Apps Script backend.

        Args:
            rpcid: The RPC identifier (e.g., ``'OOPYjd'``).
            payload: JSON-serializable payload array.
            project_id: Apps Script project ID (determines URL path).

        Returns:
            Parsed JSON response from the inner envelope.

        Raises:
            requests.HTTPError: On non-2xx HTTP status.
        """
        payload_json = json.dumps(payload, separators=(",", ":"))
        envelope = json.dumps([[rpcid, payload_json, None, "generic"]])

        if project_id:
            url = f"{_APPSCRIPT_BASE}/macros/d/{project_id}/data/batchexecute"
            source_path = f"/macros/d/{project_id}/edit"
        else:
            url = f"{_APPSCRIPT_BASE}/data/batchexecute"
            source_path = "/"

        params: Dict[str, str] = {
            "rpcids": rpcid,
            "source-path": source_path,
            "bl": _BUILD_LABEL,
            "soc-app": _SOC_APP,
            "soc-device": "1",
            "soc-platform": "1",
            "rt": "c",
        }

        headers = self._get_headers()
        resp = self._session.post(
            url,
            params=params,
            data={"f.req": envelope},
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        return self._parse_batchexecute(resp.text)

    def _parse_batchexecute(self, raw: str) -> Any:
        """Parse a batchexecute response envelope.

        Strips the anti-XSSI prefix ``)]}'`` and extracts the inner JSON
        payload from the ``wrb.fr`` wrapper.

        Args:
            raw: Raw response body text.

        Returns:
            Parsed inner JSON, or the full outer array as fallback.
        """
        text = raw
        if text.startswith(")]}'"):
            text = text[4:].lstrip("\n")

        try:
            outer = json.loads(text)
        except json.JSONDecodeError:
            logger.error("Failed to parse batchexecute response: %.200s", text)
            return None

        if not isinstance(outer, list):
            return outer

        for item in outer:
            if (
                isinstance(item, list)
                and len(item) >= 3
                and item[0] == "wrb.fr"
            ):
                inner_json = item[2]
                if isinstance(inner_json, str):
                    try:
                        return json.loads(inner_json)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Inner wrb.fr payload is not valid JSON: %.200s",
                            inner_json,
                        )
                        return inner_json
                return inner_json

        return outer

    # ──── Execution Management ────────────────────────────────────────────────

    def list_executions(
        self,
        project_id: str,
        status_filters: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """List script execution history for a project.

        Args:
            project_id: Apps Script project ID.
            status_filters: Optional list of status codes to filter by.
                Common values: 1 = completed, 2 = error, 3 = running.

        Returns:
            List of execution dicts with keys: execution_id, function,
            status, start_time, duration_ms (where parseable).
        """
        filters = status_filters if status_filters is not None else []
        payload = [
            [project_id, None, 0, 0, None, None, filters],
            2,
        ]
        data = self._batchexecute(_RPCID_LIST_EXECUTIONS, payload, project_id)
        executions: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            logger.debug("Unexpected list_executions response type: %s", type(data))
            return executions
        try:
            items = data[0] if data and isinstance(data[0], list) else data
            for item in items:
                if not isinstance(item, list):
                    continue
                entry: Dict[str, Any] = {"raw": item}
                if len(item) > 0:
                    entry["execution_id"] = item[0]
                if len(item) > 1:
                    entry["function"] = item[1]
                if len(item) > 2:
                    entry["status"] = item[2]
                if len(item) > 3:
                    entry["start_time"] = item[3]
                if len(item) > 4:
                    entry["duration_ms"] = item[4]
                executions.append(entry)
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse executions: %s", exc)
        return executions

    def run_function(
        self,
        project_id: str,
        function_name: str,
    ) -> Dict[str, Any]:
        """Execute a named function in an Apps Script project.

        Args:
            project_id: Apps Script project ID.
            function_name: Name of the function to execute.

        Returns:
            Dict with keys: execution_id, result, error (where available).
        """
        payload = [
            None,
            None,
            None,
            None,
            None,
            0,
            [project_id, function_name],
        ]
        data = self._batchexecute(_RPCID_RUN_FUNCTION, payload, project_id)
        result: Dict[str, Any] = {"raw": data}
        try:
            if isinstance(data, list):
                if len(data) > 0:
                    result["execution_id"] = data[0]
                if len(data) > 1 and data[1] is not None:
                    result["result"] = data[1]
                if len(data) > 2 and data[2] is not None:
                    result["error"] = data[2]
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse run_function response: %s", exc)
        logger.info(
            "Executed function '%s' in project %s",
            function_name,
            project_id,
        )
        return result

    # ──── Project Files & Code ────────────────────────────────────────────────

    def get_project_files(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all files in an Apps Script project.

        Args:
            project_id: Apps Script project ID.

        Returns:
            List of file dicts with keys: file_id, name, type, source
            (where parseable from the response).
        """
        payload = [project_id]
        data = self._batchexecute(_RPCID_GET_PROJECT_FILES, payload, project_id)
        files: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            logger.debug("Unexpected get_project_files response type: %s", type(data))
            return files
        try:
            file_list = data[0] if data and isinstance(data[0], list) else data
            for item in file_list:
                if not isinstance(item, list):
                    continue
                entry: Dict[str, Any] = {"raw": item}
                if len(item) > 0:
                    entry["file_id"] = item[0]
                if len(item) > 1:
                    entry["name"] = item[1]
                if len(item) > 2:
                    entry["type"] = item[2]
                if len(item) > 3:
                    entry["source"] = item[3]
                files.append(entry)
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse project files: %s", exc)
        return files

    def save_code(self, encoded_content: str, project_id: str = "") -> Any:
        """Save code content to the active editor buffer.

        Args:
            encoded_content: The encoded code content string to save.
                Typically a serialized representation of the project files.
            project_id: Optional project ID for URL routing.

        Returns:
            Parsed server response (confirmation payload).
        """
        payload = [encoded_content]
        data = self._batchexecute(_RPCID_SAVE_CODE, payload, project_id)
        logger.info(
            "Saved code content (%d chars) to project %s",
            len(encoded_content),
            project_id or "(default)",
        )
        return data

    # ──── Project Metadata ────────────────────────────────────────────────────

    def get_project_info(self, project_id: str) -> Dict[str, Any]:
        """Get project metadata (name, owner, timestamps).

        Args:
            project_id: Apps Script project ID.

        Returns:
            Dict with keys: project_id, title, owner, create_time,
            update_time (where parseable).
        """
        payload = [project_id]
        data = self._batchexecute(_RPCID_GET_PROJECT_INFO, payload, project_id)
        result: Dict[str, Any] = {"raw": data, "project_id": project_id}
        try:
            if isinstance(data, list):
                if len(data) > 0:
                    result["title"] = data[0]
                if len(data) > 1:
                    result["owner"] = data[1]
                if len(data) > 2:
                    result["create_time"] = data[2]
                if len(data) > 3:
                    result["update_time"] = data[3]
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse project info: %s", exc)
        return result

    def get_project_metadata(self, project_id: str) -> Dict[str, Any]:
        """Get extended project metadata including container info.

        This provides richer metadata than ``get_project_info``, including
        bound container details (Sheets, Docs, Forms, etc.) and deployment
        information.

        Args:
            project_id: Apps Script project ID.

        Returns:
            Dict with keys: project_id, title, container_type,
            container_id, parent_id, deployment_info (where parseable).
        """
        payload = [project_id]
        data = self._batchexecute(
            _RPCID_GET_PROJECT_METADATA, payload, project_id
        )
        result: Dict[str, Any] = {"raw": data, "project_id": project_id}
        try:
            if isinstance(data, list):
                if len(data) > 0:
                    result["title"] = data[0]
                if len(data) > 1:
                    result["container_type"] = data[1]
                if len(data) > 2:
                    result["container_id"] = data[2]
                if len(data) > 3:
                    result["parent_id"] = data[3]
                if len(data) > 4:
                    result["deployment_info"] = data[4]
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse project metadata: %s", exc)
        return result

    def save_project(
        self,
        project_id: str,
        title: str,
        files: List[Dict[str, Any]],
        settings: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Save/update full project metadata and file structure.

        Constructs the complex nested payload expected by the GXx9jd RPC.

        Args:
            project_id: Apps Script project ID.
            title: Project title.
            files: List of file dicts, each with keys:
                ``name`` (str), ``type`` (str, e.g. ``'server_js'``),
                ``source`` (str, the code content),
                ``id`` (str, optional file ID).
            settings: Optional project settings dict with keys like
                ``timezone``, ``runtime_version``, ``dependencies``.

        Returns:
            Parsed server response (confirmation payload).
        """
        file_entries = []
        for f in files:
            file_entry = [
                f.get("id"),
                f.get("name", "Untitled"),
                f.get("type", "server_js"),
                f.get("source", ""),
            ]
            file_entries.append(file_entry)

        settings_entry: Optional[list] = None
        if settings:
            settings_entry = [
                settings.get("timezone", "America/New_York"),
                settings.get("runtime_version"),
                settings.get("dependencies"),
            ]

        payload = [
            project_id,
            title,
            file_entries,
            settings_entry,
        ]
        data = self._batchexecute(_RPCID_SAVE_PROJECT, payload, project_id)
        logger.info(
            "Saved project '%s' (%s) with %d files",
            title,
            project_id,
            len(files),
        )
        return data

    def get_project_settings(self, project_id: str) -> Dict[str, Any]:
        """Get project settings (timezone, runtime version, dependencies).

        Args:
            project_id: Apps Script project ID.

        Returns:
            Dict with keys: timezone, runtime_version, dependencies,
            exception_logging (where parseable).
        """
        payload = [project_id]
        data = self._batchexecute(
            _RPCID_GET_PROJECT_SETTINGS, payload, project_id
        )
        result: Dict[str, Any] = {"raw": data, "project_id": project_id}
        try:
            if isinstance(data, list):
                if len(data) > 0:
                    result["timezone"] = data[0]
                if len(data) > 1:
                    result["runtime_version"] = data[1]
                if len(data) > 2:
                    result["dependencies"] = data[2]
                if len(data) > 3:
                    result["exception_logging"] = data[3]
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse project settings: %s", exc)
        return result

    # ──── Editor State ────────────────────────────────────────────────────────

    def get_editor_state(self, project_id: str = "") -> Dict[str, Any]:
        """Get the current editor state (open files, cursor, etc.).

        Args:
            project_id: Optional project ID for URL routing.

        Returns:
            Dict with keys: active_file, open_files, cursor_position
            (where parseable).
        """
        payload = ["s"]
        data = self._batchexecute(
            _RPCID_GET_EDITOR_STATE, payload, project_id
        )
        result: Dict[str, Any] = {"raw": data}
        try:
            if isinstance(data, list):
                if len(data) > 0:
                    result["active_file"] = data[0]
                if len(data) > 1:
                    result["open_files"] = data[1]
                if len(data) > 2:
                    result["cursor_position"] = data[2]
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse editor state: %s", exc)
        return result

    def update_cursor(
        self,
        cursor_start: int,
        cursor_end: int,
        viewport_width: int = 80,
        project_id: str = "",
    ) -> Any:
        """Update cursor position in the editor.

        Args:
            cursor_start: Start offset of cursor/selection.
            cursor_end: End offset of cursor/selection.
            viewport_width: Editor viewport width in columns.
            project_id: Optional project ID for URL routing.

        Returns:
            Parsed server response (typically acknowledgement).
        """
        payload = [cursor_start, cursor_end, None, viewport_width]
        data = self._batchexecute(_RPCID_UPDATE_CURSOR, payload, project_id)
        logger.debug(
            "Updated cursor: start=%d end=%d width=%d",
            cursor_start,
            cursor_end,
            viewport_width,
        )
        return data

    # ──── Page Initialization ─────────────────────────────────────────────────

    def page_init(self, project_id: str = "") -> Any:
        """Initialize the page/view for the Apps Script editor.

        Called when the editor page loads to establish the session context.
        Typically the first RPC in an editor session.

        Args:
            project_id: Optional project ID for URL routing.

        Returns:
            Parsed server response containing initial editor configuration.
        """
        payload: list = []
        data = self._batchexecute(_RPCID_PAGE_INIT, payload, project_id)
        logger.debug("Page initialized for project %s", project_id or "(root)")
        return data

    # ──── Triggers ────────────────────────────────────────────────────────────

    def list_triggers(self, project_id: str) -> List[Dict[str, Any]]:
        """List triggers configured for a project.

        Args:
            project_id: Apps Script project ID.

        Returns:
            List of trigger dicts with keys: trigger_id, function,
            event_type, source (where parseable).
        """
        payload = [project_id]
        data = self._batchexecute(_RPCID_LIST_TRIGGERS, payload, project_id)
        triggers: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            logger.debug("Unexpected list_triggers response type: %s", type(data))
            return triggers
        try:
            items = data[0] if data and isinstance(data[0], list) else data
            for item in items:
                if not isinstance(item, list):
                    continue
                entry: Dict[str, Any] = {"raw": item}
                if len(item) > 0:
                    entry["trigger_id"] = item[0]
                if len(item) > 1:
                    entry["function"] = item[1]
                if len(item) > 2:
                    entry["event_type"] = item[2]
                if len(item) > 3:
                    entry["source"] = item[3]
                triggers.append(entry)
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse triggers: %s", exc)
        return triggers

    # ──── Versions & History ──────────────────────────────────────────────────

    def list_versions(self, project_id: str) -> List[Dict[str, Any]]:
        """List saved versions of a project.

        Args:
            project_id: Apps Script project ID.

        Returns:
            List of version dicts with keys: version_number, description,
            create_time (where parseable).
        """
        payload = [project_id]
        data = self._batchexecute(_RPCID_LIST_VERSIONS, payload, project_id)
        versions: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            logger.debug("Unexpected list_versions response type: %s", type(data))
            return versions
        try:
            items = data[0] if data and isinstance(data[0], list) else data
            for item in items:
                if not isinstance(item, list):
                    continue
                entry: Dict[str, Any] = {"raw": item}
                if len(item) > 0:
                    entry["version_number"] = item[0]
                if len(item) > 1:
                    entry["description"] = item[1]
                if len(item) > 2:
                    entry["create_time"] = item[2]
                versions.append(entry)
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse versions: %s", exc)
        return versions

    def get_project_history(self, project_id: str) -> List[Dict[str, Any]]:
        """Get the edit history for a project.

        Args:
            project_id: Apps Script project ID.

        Returns:
            List of history entry dicts with keys: revision_id, author,
            timestamp, change_type (where parseable).
        """
        payload = [project_id]
        data = self._batchexecute(
            _RPCID_GET_PROJECT_HISTORY, payload, project_id
        )
        history: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            logger.debug(
                "Unexpected get_project_history response type: %s", type(data)
            )
            return history
        try:
            items = data[0] if data and isinstance(data[0], list) else data
            for item in items:
                if not isinstance(item, list):
                    continue
                entry: Dict[str, Any] = {"raw": item}
                if len(item) > 0:
                    entry["revision_id"] = item[0]
                if len(item) > 1:
                    entry["author"] = item[1]
                if len(item) > 2:
                    entry["timestamp"] = item[2]
                if len(item) > 3:
                    entry["change_type"] = item[3]
                history.append(entry)
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse project history: %s", exc)
        return history


# ──── Factory ─────────────────────────────────────────────────────────────────


def get_appscript_client(
    account_name: Optional[str] = None,
) -> Optional[AppsScriptClient]:
    """Get an AppsScriptClient from the account pool.

    Args:
        account_name: Specific account name, or None for round-robin.

    Returns:
        AppsScriptClient, or None if no account is available.
    """
    pool = get_account_pool()

    if account_name:
        account = pool.get_by_name(account_name)
    else:
        account = pool.get_account("appscript")

    if account is None:
        logger.warning(
            "No Apps Script account available (requested: %s). "
            "Import an account with: pool.import_from_har(har_path, name, ['appscript'])",
            account_name,
        )
        return None

    return AppsScriptClient(account)
