"""Google Apps Script SDK for CosySim.

Uses the AppsPlatformConsoleUi batchexecute API, reverse-engineered by ARGUS.
Auth: SAPISIDHASH from Google account pool cookies.

Service: AppsPlatformConsoleUi
Batch URL: https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute

Confirmed rpcid registry (26-call HAR analysis):
    OOPYjd  GetProjectState      — main project loader (26 calls)
    OQOG2e  GetScriptFiles       — editor + settings + history
    AJ6bre  GetDeployments       — deployments list
    pEig0e  RunFunction          — execute a named function
    ivJzse  CodeIntelligence     — editor autocomplete
    toGAmc  SaveScript           — save file content
    LuHlxe  CompileScript        — validate/compile
    UvGaob  UpdateProjectSettings
    KKLVD   ListTriggers
    qqL5ld  GetVersionContent
    zzomTc  CreateVersion
    yFXSbd  GetVersionDiff
    NFMk7c  CreateProject
    GXx9jd  GetProjectMetadata
    AvwHP   ListProjects
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

GAS_BASE_URL = "https://script.google.com"
GAS_BATCH_URL = "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute"
GAS_HOME_URL = f"{GAS_BASE_URL}/home"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

# ──── rpcid registry ──────────────────────────────────────────────────────────

GAS_RPCIDS: Dict[str, str] = {
    "OOPYjd": "GetProjectState",
    "OQOG2e": "GetScriptFiles",
    "AJ6bre": "GetDeployments",
    "pEig0e": "RunFunction",
    "ivJzse": "CodeIntelligence",
    "toGAmc": "SaveScript",
    "LuHlxe": "CompileScript",
    "UvGaob": "UpdateProjectSettings",
    "KKLVD":  "ListTriggers",
    "qqL5ld": "GetVersionContent",
    "zzomTc": "CreateVersion",
    "yFXSbd": "GetVersionDiff",
    "NFMk7c": "CreateProject",
    "GXx9jd": "GetProjectMetadata",
    "AvwHP":  "ListProjects",
}


# ──── Data models ─────────────────────────────────────────────────────────────

@dataclass
class GASProject:
    """Metadata for a Google Apps Script project.

    Attributes:
        script_id: Unique project/script ID.
        title: Display name.
        owner: Owner email or display name.
        created_time: ISO-8601 creation timestamp.
        updated_time: ISO-8601 last-modified timestamp.
    """

    script_id: str
    title: str
    owner: str = ""
    created_time: str = ""
    updated_time: str = ""


@dataclass
class GASFile:
    """A single script file inside a GAS project.

    Attributes:
        name: File name (without extension).
        file_type: ``"SERVER_JS"``, ``"HTML"``, or ``"JSON"``.
        source: Source code content.
        last_modified_user: Email of the last editor.
    """

    name: str
    file_type: str
    source: str = ""
    last_modified_user: str = ""


@dataclass
class GASDeployment:
    """A GAS deployment (web app, API executable, or add-on).

    Attributes:
        deployment_id: Unique deployment ID.
        deployment_type: ``"WEB_APP"``, ``"API_EXECUTABLE"``, or ``"ADD_ON"``.
        version: Deployed version number.
        url: Public URL for web app deployments.
        description: Human-readable description.
    """

    deployment_id: str
    deployment_type: str
    version: int = 0
    url: str = ""
    description: str = ""


@dataclass
class GASTrigger:
    """An installable or simple trigger on a GAS project.

    Attributes:
        trigger_id: Unique trigger ID.
        handler_function: Name of the function called when triggered.
        event_type: ``"ON_EDIT"``, ``"ON_OPEN"``, ``"CLOCK"``, or ``"ON_FORM_SUBMIT"``.
        source_type: Triggering source (e.g. ``"SPREADSHEET"``, ``"CLOCK"``).
    """

    trigger_id: str
    handler_function: str
    event_type: str
    source_type: str = ""


# ──── Client ──────────────────────────────────────────────────────────────────

class GASClient:
    """Google Apps Script client using AppsPlatformConsoleUi batchexecute API.

    Reverse-engineered from a 39 MB HAR capture of script.google.com.
    All operations go through the batchexecute endpoint with SAPISIDHASH auth.

    Args:
        account: Authenticated GoogleAccount from the pool.
    """

    def __init__(self, account: GoogleAccount) -> None:
        self._account = account
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._bl: str = ""
        self._fsid: str = ""
        self._reqid: int = 1_000_000
        self._init_session()

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _sapisidhash(self, sapisid: str) -> str:
        """Compute SAPISIDHASH token for Authorization header.

        Args:
            sapisid: Value of the SAPISID (or __Secure-1PAPISID) cookie.

        Returns:
            Formatted ``SAPISIDHASH {ts}_{digest}`` string.
        """
        now = int(time.time())
        digest = hashlib.sha1(
            f"{now} {sapisid} {GAS_BASE_URL}".encode()
        ).hexdigest()
        return f"SAPISIDHASH {now}_{digest}"

    def _headers(self) -> Dict[str, str]:
        """Build request headers with SAPISIDHASH authorization.

        Returns:
            Headers dict suitable for batchexecute requests.
        """
        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)
        sapisid = self._account.cookies.get(
            "__Secure-1PAPISID",
            self._account.cookies.get("SAPISID", ""),
        )

        auth_parts: List[str] = []
        if sapisid:
            auth_parts.append(self._sapisidhash(sapisid))

        sapisid3p = self._account.cookies.get("__Secure-3PAPISID", "")
        if sapisid3p:
            ts = int(time.time())
            d3 = hashlib.sha1(
                f"{ts} {sapisid3p} {GAS_BASE_URL}".encode()
            ).hexdigest()
            auth_parts.append(f"SAPISID3PHASH {ts}_{d3}")

        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Cookie": cookie_header,
            "Origin": GAS_BASE_URL,
            "Referer": f"{GAS_BASE_URL}/",
            "X-Goog-Authuser": str(self._account.authuser),
            "X-Same-Domain": "1",
        }
        if auth_parts:
            headers["Authorization"] = " ".join(auth_parts)
        return headers

    # ──── Session initialisation ──────────────────────────────────────────────

    def _init_session(self) -> None:
        """Fetch the GAS home page to extract bl and f.sid session tokens.

        Looks for ``FdrFJe`` (f.sid) and ``cfb2h`` / ``"bl":`` (build label)
        embedded in the page HTML — the same patterns used by NLM and Colab.
        """
        try:
            pool = get_account_pool()
            cookie_header = pool.get_cookie_header(self._account)
            headers = {
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cookie": cookie_header,
                "User-Agent": _USER_AGENT,
            }
            resp = self._session.get(GAS_HOME_URL, headers=headers, timeout=30)
            resp.raise_for_status()
            html = resp.text
            self._bl, self._fsid = self._extract_page_params(html)
            logger.debug("GAS session params: bl=%s f.sid=%s", self._bl, self._fsid)
        except Exception as exc:
            logger.warning("GAS _init_session failed: %s — will use fallback params", exc)
            if not self._bl:
                self._bl = "boq_apps-platform-console-frontend_20260301.03_p0"
            if not self._fsid:
                self._fsid = str(int(time.time() * 1000))

    def _extract_page_params(self, html: str) -> Tuple[str, str]:
        """Parse bl and f.sid from an Apps Script page HTML blob.

        Args:
            html: Raw HTML from script.google.com.

        Returns:
            Tuple of ``(bl, f_sid)``.  Falls back to timestamp strings if
            patterns are not found.
        """
        bl: str = ""
        fsid: str = ""

        # Build label — several possible patterns
        for pattern in [
            r'"bl"\s*:\s*"([^"]+)"',
            r'cfb2h["\s:]+(["\'])([^"\']+)\1',
            r'"cfb_data"[^}]*"bl"\s*:\s*"([^"]+)"',
        ]:
            m = re.search(pattern, html)
            if m:
                bl = m.group(2) if pattern.startswith("cfb2h") else m.group(1)
                break

        # Session fingerprint
        for pattern in [
            r'"FdrFJe"\s*:\s*"([^"]+)"',
            r'"SNlM0e"\s*:\s*"([^"]+)"',
        ]:
            m = re.search(pattern, html)
            if m:
                fsid = m.group(1)
                break

        if not bl:
            bl = "boq_apps-platform-console-frontend_20260301.03_p0"
            logger.warning("GAS: could not extract bl, using default")
        if not fsid:
            fsid = str(int(time.time() * 1000))
            logger.warning("GAS: could not extract f.sid, using timestamp")

        return bl, fsid

    # ──── Core RPC ────────────────────────────────────────────────────────────

    def _rpc_call(
        self,
        rpcid: str,
        payload: List[Any],
        source_path: str = "/home",
        timeout: int = 30,
    ) -> Any:
        """Execute a single batchexecute RPC call against Apps Script.

        Wraps the payload using the standard Google batchexecute envelope:
        ``[[[ rpcid, json(payload), None, "generic" ]]]``

        Args:
            rpcid: The Apps Script rpcid string (e.g. ``"OOPYjd"``).
            payload: Python list to serialize as the inner payload.
            source_path: Value for the ``source-path`` query param.
            timeout: HTTP timeout in seconds.

        Returns:
            Parsed inner response object (list/dict), or ``None`` on failure.
        """
        if not self._bl or not self._fsid:
            self._init_session()

        self._reqid += 100_000

        params = {
            "rpcids": rpcid,
            "source-path": source_path,
            "f.sid": self._fsid,
            "bl": self._bl,
            "hl": "en",
            "soc-app": "779",
            "soc-platform": "1",
            "soc-device": "1",
            "_reqid": str(self._reqid),
            "rt": "c",
        }

        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        f_req = json.dumps(
            [[[rpcid, payload_json, None, "generic"]]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        body = urllib.parse.urlencode({"f.req": f_req, "": ""})

        try:
            resp = self._session.post(
                GAS_BATCH_URL,
                params=params,
                data=body,
                headers=self._headers(),
                timeout=timeout,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.error("GAS RPC %s HTTP error: %s", rpcid, exc)
            return None

        return self._parse_wrb_response(resp.text, rpcid)

    def _parse_wrb_response(self, body: str, rpcid: str = "") -> Any:
        """Extract the inner payload from a batchexecute wrb.fr response.

        Strips the XSSI ``)]}'`` prefix, splits on chunk-size lines, and
        finds the ``wrb.fr`` item whose second element matches *rpcid*.

        Args:
            body: Raw response text.
            rpcid: Expected rpcid to match in the wrb.fr item.

        Returns:
            Parsed inner response (list/dict/str), or ``None``.
        """
        stripped = body.replace(")]}'", "")
        for line in stripped.splitlines():
            line = line.strip()
            if not line or line.isdigit() or not line.startswith("["):
                continue
            try:
                parsed = json.loads(line)
                for item in parsed:
                    if (
                        isinstance(item, list)
                        and len(item) >= 3
                        and item[0] == "wrb.fr"
                    ):
                        if rpcid and item[1] != rpcid:
                            continue
                        inner_str = item[2]
                        if not inner_str:
                            return None
                        return json.loads(inner_str)
            except (json.JSONDecodeError, IndexError, TypeError):
                continue
        logger.debug(
            "GAS: could not parse wrb.fr response for rpcid=%s (body len=%d)",
            rpcid,
            len(body),
        )
        return None

    # ──── Project management ──────────────────────────────────────────────────

    def list_projects(self) -> List[GASProject]:
        """List all Apps Script projects owned by or shared with this account.

        Uses rpcid ``AvwHP`` (ListProjects) observed on the home page.

        Returns:
            List of GASProject objects, or empty list on error.
        """
        # Payload: [null, null, null, null, null, 1] — page 1, no filter
        result = self._rpc_call("AvwHP", [None, None, None, None, None, 1], source_path="/home")
        projects: List[GASProject] = []
        if not result or not isinstance(result, list):
            return projects
        try:
            # Expected shape: [[project_entry, ...], ...] — first item is the project list
            entries = result[0] if isinstance(result[0], list) else result
            for entry in entries:
                if not isinstance(entry, list) or len(entry) < 2:
                    continue
                script_id = _safe_str(entry, 0)
                title = _safe_str(entry, 1)
                if not script_id:
                    continue
                projects.append(
                    GASProject(
                        script_id=script_id,
                        title=title,
                        owner=_safe_str(entry, 2),
                        created_time=_safe_str(entry, 4),
                        updated_time=_safe_str(entry, 5),
                    )
                )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS list_projects parse error: %s", exc)
        logger.info("GAS list_projects: found %d projects", len(projects))
        return projects

    def get_project_metadata(self, script_id: str) -> Optional[GASProject]:
        """Fetch metadata for a specific Apps Script project.

        Uses rpcid ``GXx9jd`` (GetProjectMetadata).

        Args:
            script_id: The script/project ID.

        Returns:
            GASProject, or None on error.
        """
        result = self._rpc_call("GXx9jd", [script_id], source_path=f"/d/{script_id}/edit")
        if not result or not isinstance(result, list):
            return None
        try:
            return GASProject(
                script_id=script_id,
                title=_safe_str(result, 1),
                owner=_safe_str(result, 2),
                created_time=_safe_str(result, 4),
                updated_time=_safe_str(result, 5),
            )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS get_project_metadata parse error: %s", exc)
            return GASProject(script_id=script_id, title="")

    def get_project_state(self, script_id: str) -> Dict[str, Any]:
        """Load the full project state object (editor bootstrap).

        Uses rpcid ``OOPYjd`` (GetProjectState) — the most-called RPC, 26 times
        per page load. Returns the raw parsed response dict for flexibility.

        Args:
            script_id: The script/project ID.

        Returns:
            Raw state dict, or empty dict on error.
        """
        result = self._rpc_call(
            "OOPYjd",
            [script_id, None, None, None, 1],
            source_path=f"/d/{script_id}/edit",
            timeout=45,
        )
        if result is None:
            return {}
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"raw": result}
        return {}

    def create_project(self, title: str) -> Optional[GASProject]:
        """Create a new Apps Script project.

        Uses rpcid ``NFMk7c`` (CreateProject).

        Args:
            title: Display name for the new project.

        Returns:
            GASProject with the new script_id, or None on failure.
        """
        # Payload: [title, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 1]
        result = self._rpc_call(
            "NFMk7c",
            [title, None, None, None, None, None, None, None, None, None,
             None, None, None, None, None, None, None, None, None, 1],
            source_path="/home",
        )
        if not result or not isinstance(result, list):
            logger.warning("GAS create_project: no result for title=%s", title)
            return None
        try:
            script_id = _safe_str(result, 0)
            if not script_id:
                return None
            logger.info("GAS created project '%s' → %s", title, script_id)
            return GASProject(
                script_id=script_id,
                title=_safe_str(result, 1) or title,
                owner=_safe_str(result, 2),
                created_time=_safe_str(result, 4),
                updated_time=_safe_str(result, 5),
            )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS create_project parse error: %s", exc)
            return None

    # ──── Script file management ───────────────────────────────────────────────

    def get_files(self, script_id: str) -> List[GASFile]:
        """Retrieve all script files in a project.

        Uses rpcid ``OQOG2e`` (GetScriptFiles).

        Args:
            script_id: The script/project ID.

        Returns:
            List of GASFile objects, or empty list on error.
        """
        result = self._rpc_call(
            "OQOG2e",
            [script_id],
            source_path=f"/d/{script_id}/edit",
        )
        files: List[GASFile] = []
        if not result or not isinstance(result, list):
            return files
        try:
            file_list = result[0] if isinstance(result[0], list) else result
            for entry in file_list:
                if not isinstance(entry, list):
                    continue
                files.append(
                    GASFile(
                        name=_safe_str(entry, 0),
                        file_type=_safe_str(entry, 1) or "SERVER_JS",
                        source=_safe_str(entry, 2),
                        last_modified_user=_safe_str(entry, 5),
                    )
                )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS get_files parse error: %s", exc)
        return files

    def save_script(self, script_id: str, files: List[GASFile]) -> bool:
        """Save script file contents to a project.

        Uses rpcid ``toGAmc`` (SaveScript).  Serialises files as a list of
        ``[name, file_type, source]`` entries.

        Args:
            script_id: The script/project ID.
            files: List of GASFile objects to save.

        Returns:
            True if the server accepted the save, False otherwise.
        """
        file_entries = [
            [f.name, f.file_type, f.source] for f in files
        ]
        result = self._rpc_call(
            "toGAmc",
            [script_id, file_entries],
            source_path=f"/d/{script_id}/edit",
        )
        success = result is not None
        if success:
            logger.info("GAS save_script: saved %d files to %s", len(files), script_id)
        else:
            logger.warning("GAS save_script: no confirmation from server for %s", script_id)
        return success

    def compile_script(self, script_id: str) -> Dict[str, Any]:
        """Validate and compile a script project.

        Uses rpcid ``LuHlxe`` (CompileScript).  Returns a dict with an
        ``errors`` key (list of error dicts) and a ``success`` bool.

        Args:
            script_id: The script/project ID.

        Returns:
            Dict with ``success`` and ``errors`` keys.
        """
        result = self._rpc_call(
            "LuHlxe",
            [script_id],
            source_path=f"/d/{script_id}/edit",
            timeout=60,
        )
        if result is None:
            return {"success": False, "errors": [], "raw": None}
        try:
            if isinstance(result, list) and len(result) >= 1:
                errors = result[0] if isinstance(result[0], list) else []
                return {"success": len(errors) == 0, "errors": errors, "raw": result}
        except (IndexError, TypeError):
            pass
        return {"success": True, "errors": [], "raw": result}

    # ──── Execution ───────────────────────────────────────────────────────────

    def run_function(
        self,
        script_id: str,
        function_name: str,
        args: Optional[List[Any]] = None,
    ) -> Any:
        """Execute a named function in a script project.

        Uses rpcid ``pEig0e`` (RunFunction).  The function must be deployed
        or runnable from the editor context.

        Args:
            script_id: The script/project ID.
            function_name: Name of the Apps Script function to call.
            args: Optional list of arguments to pass to the function.

        Returns:
            Return value from the function (parsed from the response), or None.
        """
        result = self._rpc_call(
            "pEig0e",
            [script_id, function_name, args or []],
            source_path=f"/d/{script_id}/edit",
            timeout=120,
        )
        if result is None:
            logger.warning(
                "GAS run_function: no result for %s.%s", script_id, function_name
            )
            return None
        try:
            # Expected: [[return_value], status, ...]
            if isinstance(result, list) and result:
                inner = result[0]
                return inner[0] if isinstance(inner, list) and inner else inner
        except (IndexError, TypeError):
            pass
        return result

    # ──── Deployments ─────────────────────────────────────────────────────────

    def get_deployments(self, script_id: str) -> List[GASDeployment]:
        """List all deployments for a script project.

        Uses rpcid ``AJ6bre`` (GetDeployments).

        Args:
            script_id: The script/project ID.

        Returns:
            List of GASDeployment objects.
        """
        result = self._rpc_call(
            "AJ6bre",
            [script_id],
            source_path=f"/d/{script_id}/edit",
        )
        deployments: List[GASDeployment] = []
        if not result or not isinstance(result, list):
            return deployments
        try:
            dep_list = result[0] if isinstance(result[0], list) else result
            for entry in dep_list:
                if not isinstance(entry, list):
                    continue
                dep_id = _safe_str(entry, 0)
                if not dep_id:
                    continue
                deployments.append(
                    GASDeployment(
                        deployment_id=dep_id,
                        deployment_type=_safe_str(entry, 1) or "WEB_APP",
                        version=int(entry[2]) if len(entry) > 2 and isinstance(entry[2], (int, float)) else 0,
                        url=_safe_str(entry, 3),
                        description=_safe_str(entry, 4),
                    )
                )
        except (IndexError, TypeError, ValueError) as exc:
            logger.warning("GAS get_deployments parse error: %s", exc)
        return deployments

    def create_web_app_deployment(
        self,
        script_id: str,
        description: str = "",
        access: str = "ANYONE_ANONYMOUS",
    ) -> Optional[GASDeployment]:
        """Create a new web app deployment for a script.

        First creates a version snapshot, then deploys it as a web app.
        The *access* parameter maps to the GAS ``Who has access`` setting.

        Args:
            script_id: The script/project ID.
            description: Deployment description shown in the console.
            access: Access level. ``"ANYONE_ANONYMOUS"`` (no login),
                ``"ANYONE"`` (Google account required), or
                ``"DOMAIN"`` (same Google Workspace domain).

        Returns:
            GASDeployment with the web app URL, or None on failure.
        """
        # Step 1: create a version to deploy
        version = self.create_version(script_id, description or "CosySim deploy")
        if version <= 0:
            logger.warning("GAS create_web_app_deployment: version creation failed for %s", script_id)
            version = 1  # fall back to HEAD

        # Step 2: deploy the version as a web app
        # Payload structure inferred from GAS batchexecute patterns:
        # [script_id, version, description, access_enum, execute_as_enum]
        # access: 1=ANYONE_ANONYMOUS, 2=ANYONE, 3=DOMAIN
        access_map = {"ANYONE_ANONYMOUS": 1, "ANYONE": 2, "DOMAIN": 3}
        access_int = access_map.get(access, 1)

        result = self._rpc_call(
            "AJ6bre",
            [script_id, version, description, access_int, 1],
            source_path=f"/d/{script_id}/edit",
            timeout=60,
        )
        if not result or not isinstance(result, list):
            logger.warning("GAS create_web_app_deployment: no result for %s", script_id)
            return None

        try:
            entry = result[0] if isinstance(result[0], list) else result
            dep_id = _safe_str(entry, 0)
            url = _safe_str(entry, 3)
            return GASDeployment(
                deployment_id=dep_id or "new",
                deployment_type="WEB_APP",
                version=version,
                url=url,
                description=description,
            )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS create_web_app_deployment parse error: %s", exc)
            return None

    def get_web_app_url(self, script_id: str) -> Optional[str]:
        """Return the public URL of the first WEB_APP deployment for a script.

        Convenience wrapper around :meth:`get_deployments`.

        Args:
            script_id: The script/project ID.

        Returns:
            Web app URL string, or None if no web app deployment exists.
        """
        for dep in self.get_deployments(script_id):
            if dep.deployment_type == "WEB_APP" and dep.url:
                return dep.url
        return None

    # ──── Triggers ────────────────────────────────────────────────────────────

    def list_triggers(self, script_id: str) -> List[GASTrigger]:
        """List all installable triggers for a script project.

        Uses rpcid ``KKLVD`` (ListTriggers).

        Args:
            script_id: The script/project ID.

        Returns:
            List of GASTrigger objects.
        """
        result = self._rpc_call(
            "KKLVD",
            [script_id],
            source_path=f"/d/{script_id}/triggers",
        )
        triggers: List[GASTrigger] = []
        if not result or not isinstance(result, list):
            return triggers
        try:
            trig_list = result[0] if isinstance(result[0], list) else result
            for entry in trig_list:
                if not isinstance(entry, list):
                    continue
                trig_id = _safe_str(entry, 0)
                if not trig_id:
                    continue
                triggers.append(
                    GASTrigger(
                        trigger_id=trig_id,
                        handler_function=_safe_str(entry, 1),
                        event_type=_safe_str(entry, 2) or "CLOCK",
                        source_type=_safe_str(entry, 3),
                    )
                )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS list_triggers parse error: %s", exc)
        return triggers

    def create_time_trigger(
        self,
        script_id: str,
        function_name: str,
        interval_hours: int = 1,
    ) -> Optional[GASTrigger]:
        """Create an installable time-driven (clock) trigger.

        Registers a trigger that fires *function_name* every *interval_hours*
        hours.  Uses the ``UvGaob`` (UpdateProjectSettings) rpcid as a proxy
        since no dedicated CreateTrigger rpcid was observed in the HAR; the
        GAS console uses project-settings mutations to add triggers.

        Args:
            script_id: The script/project ID.
            function_name: Name of the handler function.
            interval_hours: Interval in hours (1, 2, 4, 6, 8, 12, or 24).

        Returns:
            GASTrigger placeholder, or None on failure.
        """
        # Payload: [script_id, [[function_name, "CLOCK", interval_hours * 60 * 60 * 1000]]]
        interval_ms = interval_hours * 3_600_000
        result = self._rpc_call(
            "UvGaob",
            [script_id, [[function_name, "CLOCK", interval_ms]]],
            source_path=f"/d/{script_id}/triggers",
        )
        if result is None:
            logger.warning(
                "GAS create_time_trigger: no response for %s.%s", script_id, function_name
            )
            return None
        try:
            entry = result[0] if isinstance(result, list) and result else result
            if isinstance(entry, list):
                trig_id = _safe_str(entry, 0) or f"clock_{function_name}"
            else:
                trig_id = f"clock_{function_name}"
            logger.info(
                "GAS created CLOCK trigger %s on %s every %dh",
                function_name, script_id, interval_hours,
            )
            return GASTrigger(
                trigger_id=trig_id,
                handler_function=function_name,
                event_type="CLOCK",
                source_type="CLOCK",
            )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS create_time_trigger parse error: %s", exc)
            return None

    # ──── Version history ─────────────────────────────────────────────────────

    def create_version(self, script_id: str, description: str = "") -> int:
        """Snapshot the current HEAD state as a named version.

        Uses rpcid ``zzomTc`` (CreateVersion).

        Args:
            script_id: The script/project ID.
            description: Human-readable description for this version.

        Returns:
            New version number (>0), or 0 on failure.
        """
        result = self._rpc_call(
            "zzomTc",
            [script_id, description],
            source_path=f"/d/{script_id}/history",
        )
        if not result:
            return 0
        try:
            if isinstance(result, list) and result:
                v = result[0]
                if isinstance(v, (int, float)):
                    return int(v)
                if isinstance(v, list) and v:
                    return int(v[0])
        except (IndexError, TypeError, ValueError) as exc:
            logger.warning("GAS create_version parse error: %s", exc)
        return 0

    def get_version_content(
        self, script_id: str, version: int
    ) -> List[GASFile]:
        """Retrieve script file contents at a specific version.

        Uses rpcid ``qqL5ld`` (GetVersionContent).

        Args:
            script_id: The script/project ID.
            version: Version number to retrieve.

        Returns:
            List of GASFile objects at that version.
        """
        result = self._rpc_call(
            "qqL5ld",
            [script_id, version],
            source_path=f"/d/{script_id}/history",
        )
        files: List[GASFile] = []
        if not result or not isinstance(result, list):
            return files
        try:
            file_list = result[0] if isinstance(result[0], list) else result
            for entry in file_list:
                if not isinstance(entry, list):
                    continue
                files.append(
                    GASFile(
                        name=_safe_str(entry, 0),
                        file_type=_safe_str(entry, 1) or "SERVER_JS",
                        source=_safe_str(entry, 2),
                    )
                )
        except (IndexError, TypeError) as exc:
            logger.warning("GAS get_version_content parse error: %s", exc)
        return files

    # ──── High-level helpers ──────────────────────────────────────────────────

    def create_webhook_script(
        self, title: str, handler_code: str
    ) -> Optional[GASDeployment]:
        """Create a new project, write handler code, and deploy as a web app.

        Full pipeline: create project → write Code.gs → save → deploy.
        Returns the GASDeployment with the public URL on success.

        Args:
            title: Project display name.
            handler_code: Complete Apps Script source code string.

        Returns:
            GASDeployment with public web app URL, or None on failure.
        """
        project = self.create_project(title)
        if not project:
            logger.error("GAS create_webhook_script: failed to create project '%s'", title)
            return None

        script_id = project.script_id
        files = [GASFile(name="Code", file_type="SERVER_JS", source=handler_code)]
        if not self.save_script(script_id, files):
            logger.warning(
                "GAS create_webhook_script: save may not have been confirmed for %s", script_id
            )

        deployment = self.create_web_app_deployment(
            script_id,
            description=f"{title} — deployed by CosySim",
            access="ANYONE_ANONYMOUS",
        )
        if deployment:
            logger.info(
                "GAS create_webhook_script: '%s' deployed at %s",
                title,
                deployment.url or "(no URL in response)",
            )
        return deployment

    def create_cosysim_bridge(
        self, cosysim_url: str = "http://localhost:8700"
    ) -> Optional[GASDeployment]:
        """Deploy a GAS script that bridges HTTP events to CosySim.

        The deployed web app accepts POST requests and forwards them to the
        CosySim webhook endpoint at ``{cosysim_url}/api/gas/webhook``.

        Args:
            cosysim_url: Base URL of the running CosySim instance.

        Returns:
            GASDeployment with the public web app URL, or None on failure.
        """
        bridge_code = (
            "function doPost(e) {\n"
            "  var payload = JSON.parse(e.postData.contents);\n"
            f'  var url = "{cosysim_url}/api/gas/webhook";\n'
            "  var options = {\n"
            '    method: "post",\n'
            '    contentType: "application/json",\n'
            "    payload: JSON.stringify(payload),\n"
            "    muteHttpExceptions: true\n"
            "  };\n"
            "  try {\n"
            "    var resp = UrlFetchApp.fetch(url, options);\n"
            "    return ContentService.createTextOutput(resp.getContentText())\n"
            "      .setMimeType(ContentService.MimeType.JSON);\n"
            "  } catch(err) {\n"
            "    return ContentService.createTextOutput(JSON.stringify({error: err.message}))\n"
            "      .setMimeType(ContentService.MimeType.JSON);\n"
            "  }\n"
            "}\n"
            "\n"
            "function doGet(e) {\n"
            '  return ContentService.createTextOutput(JSON.stringify({status: "ok"}))\n'
            "    .setMimeType(ContentService.MimeType.JSON);\n"
            "}\n"
        )
        return self.create_webhook_script("CosySim Bridge", bridge_code)


# ──── Helpers ─────────────────────────────────────────────────────────────────

def _safe_str(lst: List[Any], idx: int) -> str:
    """Safely extract a string from a list at index *idx*.

    Args:
        lst: Source list.
        idx: Index to retrieve.

    Returns:
        String value, or empty string if the index is out of bounds or the
        value is not a string-compatible type.
    """
    try:
        v = lst[idx]
        return str(v) if v is not None else ""
    except (IndexError, TypeError):
        return ""


# ──── Factory ─────────────────────────────────────────────────────────────────

def get_gas_client(account_name: Optional[str] = None) -> Optional[GASClient]:
    """Get a GASClient using an account from the pool.

    Tries service tags in priority order: ``"gas"`` → ``"notebooklm"`` →
    ``"colab"`` → any available account.

    Args:
        account_name: Specific account name, or None for automatic selection.

    Returns:
        GASClient ready to use, or None if no account is available.
    """
    pool = get_account_pool()

    account: Optional[GoogleAccount] = None
    if account_name:
        account = pool.get_by_name(account_name)
    else:
        account = (
            pool.get_account("gas")
            or pool.get_account("notebooklm")
            or pool.get_account("colab")
            or pool.get_account("drive")
        )

    if account is None:
        logger.warning(
            "GAS: no account available (requested: %s). "
            "Import an account with: pool.import_from_har(har_path, name, ['gas'])",
            account_name,
        )
        return None

    return GASClient(account)
