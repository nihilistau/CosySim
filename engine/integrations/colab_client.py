"""Colab direct HTTP client — reverse-engineered from HAR + V8 heap analysis.

Provides access to:
- Colab AI Agent (AgentCreateTask / AgentUpdateTask / AgentQueryTask)
- AIService: CompleteCode, SmartPaste, AgentQuerySuggestions
- RuntimeService (ListAssignments, GetRuntimeProxyToken, tunnel management)
- Jupyter kernel execution via WebSocket
- UserInfoService (quota, hardware tiers / GetUserInfo)

All endpoints confirmed from colab.research.google.com HAR captures and
V8 heap snapshot analysis (heap_deep_parser.py).

Colab tunnel JWT format (ES256, kid=B7PekA):
  {"aud": "<tunnel-id>", "exp": <unix-ts>, "port": 8080}
  Tunnel URL: https://colab.research.google.com/tun/m/<tunnel-id>
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_COLAB_RPC_BASE = "https://colab.clients6.google.com"
_COLAB_RESEARCH_BASE = "https://colab.research.google.com"
_COLAB_ORIGIN = "https://colab.research.google.com"
_COLAB_REFERER = "https://colab.research.google.com/"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


# ──── Client ─────────────────────────────────────────────────────────────────

class ColabClient:
    """Direct Colab API client using browser session cookies.

    Args:
        account: Authenticated GoogleAccount from the pool.
    """

    def __init__(self, account: GoogleAccount) -> None:
        self._account = account
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _sapisidhash(self, sapisid: str, origin: str) -> str:
        """Compute SAPISIDHASH for Authorization header.

        Args:
            sapisid: SAPISID cookie value.
            origin: Request origin URL.

        Returns:
            Authorization header value string.
        """
        ts = str(int(time.time()))
        digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
        return f"SAPISIDHASH {ts}_{digest}"

    def _get_headers(
        self,
        origin: str = _COLAB_ORIGIN,
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

        auth_parts = []
        if sapisid:
            auth_parts.append(_hash(sapisid))
        if sapisid1p:
            auth_parts.append(f"SAPISID1PHASH {ts}_{hashlib.sha1(f'{ts} {sapisid1p} {origin}'.encode()).hexdigest()}")
        if sapisid3p:
            auth_parts.append(f"SAPISID3PHASH {ts}_{hashlib.sha1(f'{ts} {sapisid3p} {origin}'.encode()).hexdigest()}")

        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json+protobuf",
            "Cookie": cookie_header,
            "Origin": origin,
            "Referer": _COLAB_REFERER,
            "X-Goog-Authuser": str(self._account.authuser),
            "X-Same-Domain": "1",
        }
        if auth_parts:
            headers["Authorization"] = " ".join(auth_parts)
        if extra:
            headers.update(extra)
        return headers

    # ──── UserInfoService ─────────────────────────────────────────────────────

    def get_user_info(self) -> Dict[str, Any]:
        """Fetch Colab hardware tiers and quota information.

        Returns:
            Dict with keys: free_tiers, pro_tiers, compute_units, expires_at.
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.UserInfoService/GetUserInfo"
        headers = self._get_headers()
        resp = self._session.post(url, headers=headers, json=[None, 1], timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response: [tier, 0, [[1, ["T4"]], [2, ["V5E1"]]], [[1, [...pro...]], [2, [...]]], 0, 0, ["6000", ts]]
        result: Dict[str, Any] = {"raw": data}
        try:
            result["free_tiers"] = {
                item[0]: item[1] for item in (data[2] or [])
            }
            result["pro_tiers"] = {
                item[0]: item[1] for item in (data[3] or [])
            }
            if len(data) > 6 and data[6]:
                result["compute_units"] = data[6][0]
                result["expires_at"] = data[6][1]
        except (IndexError, TypeError, KeyError) as exc:
            logger.debug("Could not parse user info detail: %s", exc)
        return result

    # ──── RuntimeService ──────────────────────────────────────────────────────

    def list_assignments(self) -> List[Dict[str, Any]]:
        """List active Colab runtime assignments.

        Returns:
            List of runtime dicts with: runtime_id, proxy_token, runtime_url, ttl.
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.RuntimeService/ListAssignments"
        headers = self._get_headers()
        resp = self._session.post(url, headers=headers, json=[], timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response: [[["runtime-id", 0, 1, "NONE", ["jwt-token", ["3600"], "https://..."]]]]
        runtimes = []
        try:
            for runtime_list in data:
                for item in runtime_list:
                    runtime_id = item[0]
                    proxy_info = item[4] if len(item) > 4 else None
                    proxy_token = None
                    runtime_url = None
                    ttl = None
                    if proxy_info:
                        proxy_token = proxy_info[0]
                        ttl = proxy_info[1][0] if proxy_info[1] else None
                        runtime_url = proxy_info[2] if len(proxy_info) > 2 else None
                    runtimes.append({
                        "runtime_id": runtime_id,
                        "proxy_token": proxy_token,
                        "runtime_url": runtime_url,
                        "ttl": ttl,
                    })
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse assignments: %s", exc)
        return runtimes

    def get_or_assign_runtime(self) -> Tuple[str, str]:
        """Get the first available runtime URL and proxy token.

        Returns:
            Tuple of (runtime_url, proxy_token).

        Raises:
            RuntimeError: If no runtime is available.
        """
        assignments = self.list_assignments()
        for rt in assignments:
            if rt.get("runtime_url") and rt.get("proxy_token"):
                logger.info("Using existing runtime: %s", rt["runtime_url"])
                return rt["runtime_url"], rt["proxy_token"]
        raise RuntimeError(
            "No active Colab runtime found. Start a runtime in the Colab UI first."
        )

    # ──── AI Agent ────────────────────────────────────────────────────────────

    def create_task(self) -> str:
        """Create a new Colab AI agent task.

        Returns:
            task_id UUID string.
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.AIService/AgentCreateTask"
        headers = self._get_headers()
        body = [None, None, [None, None, None, None, None, None, [25, 5]], 2]
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        task_id: str = data[0]
        logger.debug("Created Colab task: %s", task_id)
        return task_id

    def update_task(self, task_id: str, context: str) -> None:
        """Update a task with context/notebook content.

        Args:
            task_id: UUID from create_task().
            context: Context string (notebook content, code, etc.).
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.AIService/AgentUpdateTask"
        headers = self._get_headers()
        body = [task_id, None, None, [[[[[[context]]]]]]
        ]
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        logger.debug("Updated task %s with %d chars context", task_id, len(context))

    def query_task(self, task_id: str) -> Optional[str]:
        """Poll an AI task for its response.

        Args:
            task_id: UUID from create_task().

        Returns:
            Response text string if task is complete, or None if still processing.
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.AIService/AgentQueryTask"
        headers = self._get_headers()
        body = [task_id, None, 2]
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response when processing: ["task-uuid", null, null, 2]
        # Response when done: ["task-uuid", null, [[...response...]]]
        if len(data) >= 3 and data[2] is not None:
            return self._extract_task_text(data[2])
        return None

    def _extract_task_text(self, payload: Any) -> str:
        """Extract text content from a completed AgentQueryTask response.

        Args:
            payload: The third element of the query response array.

        Returns:
            Extracted text, falling back to JSON dump if parsing fails.
        """
        try:
            # payload: [[null,null,null,null,null,null,[null,[[null,["text here"]]]]]]
            outer = payload[0]
            if outer and len(outer) >= 7 and outer[6]:
                inner_list = outer[6][1]
                if inner_list:
                    for item in inner_list:
                        if item and len(item) >= 2 and item[1]:
                            return str(item[1][0])
        except (IndexError, TypeError, KeyError):
            pass
        # Fallback: stringify
        return json.dumps(payload)

    def ask(
        self,
        prompt: str,
        context: str = "",
        timeout: int = 120,
    ) -> str:
        """Ask the Colab AI agent a question.

        Handles the full create → update → poll cycle.

        Args:
            prompt: The question or prompt to send.
            context: Optional notebook/code context.
            timeout: Maximum seconds to wait for response.

        Returns:
            AI response text.

        Raises:
            TimeoutError: If the agent doesn't respond within timeout.
        """
        task_id = self.create_task()
        full_context = f"{context}\n\n{prompt}" if context else prompt
        self.update_task(task_id, full_context)

        deadline = time.time() + timeout
        poll_interval = 2.0
        max_interval = 10.0

        while time.time() < deadline:
            result = self.query_task(task_id)
            if result is not None:
                logger.debug("Colab task %s completed", task_id)
                return result
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, max_interval)

        raise TimeoutError(
            f"Colab task {task_id} did not complete within {timeout}s"
        )

    def get_suggestions(self, context: str) -> List[str]:
        """Get AI-suggested follow-up prompts for a context.

        Args:
            context: Current notebook or conversation context.

        Returns:
            List of suggestion strings (up to 3).
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.AIService/AgentQuerySuggestions"
        headers = self._get_headers()
        body = [[[[[[ context ]]]]]
        ]
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response: [[["suggestion 1"], ["suggestion 2"], ["suggestion 3"]]]
        suggestions = []
        try:
            for item in data[0]:
                if item and item[0]:
                    suggestions.append(item[0])
        except (IndexError, TypeError):
            pass
        return suggestions

    def get_runtime_proxy_token(self, runtime_id: str) -> Optional[str]:
        """Fetch a fresh proxy JWT token for a specific Colab runtime.

        Args:
            runtime_id: Runtime identifier string from list_assignments().

        Returns:
            JWT proxy token string, or None if unavailable.
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.RuntimeService/GetRuntimeProxyToken"
        headers = self._get_headers()
        body = [runtime_id]
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response: ["jwt-token", ["3600"]]  — same format as ListAssignments proxy_info
        try:
            return data[0] if data else None
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse proxy token: %s", exc)
            return None

    def complete_code(
        self, code: str, cursor_pos: int, notebook_id: str = ""
    ) -> List[str]:
        """Request AI code completion suggestions.

        Args:
            code: Current code cell content.
            cursor_pos: Cursor position in the code string.
            notebook_id: Optional notebook identifier for context.

        Returns:
            List of completion strings.
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.AIService/CompleteCode"
        headers = self._get_headers()
        body = [code, cursor_pos, notebook_id or None]
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response: [["completion1", "completion2"]] or similar
        completions: List[str] = []
        try:
            if data and data[0]:
                completions = [c for c in data[0] if c]
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse completions: %s", exc)
        return completions

    def smart_paste(self, code: str, notebook_id: str = "") -> str:
        """Request AI-cleaned/reformatted paste suggestion for code.

        Args:
            code: Pasted code to reformat or explain.
            notebook_id: Optional notebook identifier.

        Returns:
            Reformatted or annotated code string.
        """
        url = f"{_COLAB_RPC_BASE}/$rpc/google.internal.colab.v1.AIService/SmartPaste"
        headers = self._get_headers()
        body = [code, notebook_id or None]
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response: ["reformatted code"] or [["code", "explanation"]]
        try:
            if data and data[0]:
                return str(data[0]) if not isinstance(data[0], list) else str(data[0][0])
        except (IndexError, TypeError) as exc:
            logger.debug("Could not parse smart_paste: %s", exc)
        return code

    # ──── Kernel execution ────────────────────────────────────────────────────

    def create_kernel_session(
        self,
        runtime_url: str,
        proxy_token: str,
        notebook_name: str = "cosysim.ipynb",
    ) -> Tuple[str, str]:
        """Create a Jupyter kernel session on a Colab runtime.

        Args:
            runtime_url: Runtime base URL from list_assignments().
            proxy_token: JWT proxy token for authentication.
            notebook_name: Name for the notebook session.

        Returns:
            Tuple of (session_id, kernel_id).
        """
        url = (
            f"{runtime_url}/api/sessions"
            f"?backend_version=next&authuser={self._account.authuser}"
            f"&colab-runtime-proxy-token={proxy_token}"
        )
        headers = {
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        }
        body = {
            "name": notebook_name,
            "path": notebook_name,
            "type": "notebook",
            "kernel": {"name": "python3"},
        }
        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        session_id: str = data["id"]
        kernel_id: str = data["kernel"]["id"]
        logger.info("Created kernel session %s / kernel %s", session_id, kernel_id)
        return session_id, kernel_id

    def execute_code(
        self,
        runtime_url: str,
        kernel_id: str,
        proxy_token: str,
        code: str,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """Execute Python code in a Colab kernel via WebSocket.

        Uses the standard Jupyter messaging protocol (ZMQ-over-WebSocket).

        Args:
            runtime_url: Runtime base URL.
            kernel_id: Kernel UUID from create_kernel_session().
            proxy_token: JWT proxy token.
            code: Python source code to execute.
            timeout: Seconds to wait for execution to finish.

        Returns:
            Dict with keys: output (str), error (Optional[str]), status (str).
        """
        return asyncio.run(
            self._execute_code_async(runtime_url, kernel_id, proxy_token, code, timeout)
        )

    async def _execute_code_async(
        self,
        runtime_url: str,
        kernel_id: str,
        proxy_token: str,
        code: str,
        timeout: int,
    ) -> Dict[str, Any]:
        """Async implementation of code execution via Jupyter WebSocket protocol."""
        import websockets
        from datetime import datetime, timezone

        # Convert https:// → wss://
        ws_base = runtime_url.replace("https://", "wss://", 1)
        ws_url = (
            f"{ws_base}/api/kernels/{kernel_id}/channels"
            f"?colab-runtime-proxy-token={proxy_token}"
        )

        session_id = str(uuid.uuid4())
        msg_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        msg = {
            "header": {
                "msg_type": "execute_request",
                "msg_id": msg_id,
                "username": "colab",
                "session": session_id,
                "date": now_iso,
                "version": "5.3",
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False,
            },
            "buffers": [],
            "channel": "shell",
        }

        output_parts: List[str] = []
        error_text: Optional[str] = None
        status = "ok"

        ssl_context = True  # use default SSL verification

        try:
            async with websockets.connect(
                ws_url,
                additional_headers={"User-Agent": _USER_AGENT},
                open_timeout=15,
                ping_interval=None,
            ) as ws:
                await ws.send(json.dumps(msg))

                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    except asyncio.TimeoutError:
                        continue

                    frame = json.loads(raw)
                    msg_type = frame.get("header", {}).get("msg_type", "")
                    content = frame.get("content", {})

                    if msg_type == "stream":
                        output_parts.append(content.get("text", ""))
                    elif msg_type == "execute_result":
                        data = content.get("data", {})
                        output_parts.append(data.get("text/plain", ""))
                    elif msg_type == "error":
                        error_text = "\n".join(content.get("traceback", []))
                        if not error_text:
                            error_text = f"{content.get('ename')}: {content.get('evalue')}"
                        status = "error"
                    elif msg_type == "status":
                        execution_state = content.get("execution_state", "")
                        if execution_state == "idle":
                            break
        except Exception as exc:
            logger.error("WebSocket execution failed: %s", exc)
            return {"output": "", "error": str(exc), "status": "error"}

        return {
            "output": "".join(output_parts),
            "error": error_text,
            "status": status,
        }

    def close_session(
        self,
        runtime_url: str,
        session_id: str,
        proxy_token: str,
    ) -> None:
        """Close a Jupyter kernel session.

        Args:
            runtime_url: Runtime base URL.
            session_id: Session UUID from create_kernel_session().
            proxy_token: JWT proxy token.
        """
        url = (
            f"{runtime_url}/api/sessions/{session_id}"
            f"?colab-runtime-proxy-token={proxy_token}"
        )
        try:
            resp = self._session.delete(url, timeout=15)
            resp.raise_for_status()
            logger.debug("Closed session %s", session_id)
        except Exception as exc:
            logger.warning("Failed to close session %s: %s", session_id, exc)

    # ──── High-level ──────────────────────────────────────────────────────────

    def run_python(self, code: str, timeout: int = 60) -> Dict[str, Any]:
        """Execute Python code, managing the runtime lifecycle automatically.

        Gets or creates a runtime, executes the code, and cleans up.

        Args:
            code: Python source code to execute.
            timeout: Execution timeout in seconds.

        Returns:
            Dict with keys: output (str), error (Optional[str]), status (str).
        """
        try:
            runtime_url, proxy_token = self.get_or_assign_runtime()
        except RuntimeError as exc:
            return {"output": "", "error": str(exc), "status": "error"}

        session_id, kernel_id = self.create_kernel_session(runtime_url, proxy_token)
        try:
            return self.execute_code(runtime_url, kernel_id, proxy_token, code, timeout)
        finally:
            self.close_session(runtime_url, session_id, proxy_token)


# ──── Factory ─────────────────────────────────────────────────────────────────

def get_colab_client(
    account_name: Optional[str] = None,
) -> Optional[ColabClient]:
    """Get a ColabClient for the named account or the next available one.

    Args:
        account_name: Specific account name, or None for round-robin.

    Returns:
        ColabClient, or None if no account is available.
    """
    pool = get_account_pool()

    if account_name:
        account = pool.get_by_name(account_name)
    else:
        account = pool.get_account("colab")

    if account is None:
        logger.warning(
            "No Colab account available (requested: %s). "
            "Import an account with: pool.import_from_har(har_path, name, ['colab'])",
            account_name,
        )
        return None

    return ColabClient(account)
