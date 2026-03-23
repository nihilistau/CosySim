"""CDP-based Google auth recovery — engine/nexus/cdp_auth_recovery.py

Diagnoses and auto-fixes Google service authentication (NLM cookies +
Gemini API keys) by connecting to the Chrome DevTools Protocol endpoint
at localhost:9223.  No interactive browser window required — works with
the headless Chrome instance already running for ARGUS/NLM automation.

Version: v1.50.1 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.50.1 [2026-03-22] — BL extraction, session tokens, pool sync, async-safe public API
    v1.50.0 [2026-03-21] — Initial CDP auth recovery module

Recovery procedure
------------------
1. Detect Chrome CDP at localhost:9223.
2. Open a disposable Chrome tab for navigation.
3. Inject saved cookies (data/nlm_cookies.json) via Network.setCookie.
4. Navigate to NotebookLM → verify login.
5. Extract BL + f.sid + at token from WIZ_global_data → data/nlm_meta.json.
6. Extract all fresh Google cookies and save back to data/nlm_cookies.json.
7. Sync cookies + session tokens to GoogleAccountPool via token_harvester.
8. Navigate to AI Studio → check login.
9. Validate each Gemini API key in engine/integrations/aistudio_client.py.
10. If any key is dead or no working key exists: intercept AI Studio
    network traffic during page load to harvest full key values.
11. Test harvested keys, update aistudio_client.py + config/nlm_rpcids.yaml.

Usage
-----
    python -m engine.nexus.cdp_auth_recovery            # full check + recover
    python -m engine.nexus.cdp_auth_recovery --check    # read-only health check
    python -m engine.nexus.cdp_auth_recovery --keys     # API key rotation only

Programmatic
------------
    from engine.nexus.cdp_auth_recovery import run_check, run_recovery, AuthStatus
    status = run_check()
    if not status.healthy:
        status = run_recovery()
    print(status.summary())
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
NLM_COOKIES_PATH = _ROOT / "data" / "nlm_cookies.json"
NLM_META_PATH = _ROOT / "data" / "nlm_meta.json"
AISTUDIO_CLIENT_PATH = _ROOT / "engine" / "integrations" / "aistudio_client.py"
RPCIDS_YAML_PATH = _ROOT / "config" / "nlm_rpcids.yaml"

# ── Constants ──────────────────────────────────────────────────────────────────
def _get_cdp_config() -> Dict[str, Any]:
    """Read cdp: section from config with sensible defaults."""
    try:
        from engine.config import get_config
        cfg = get_config()
        return {
            "port": cfg.get("cdp.port", 9223),
            "navigation_wait_s": cfg.get("cdp.navigation_wait_s", 6),
            "harvest_timeout_s": cfg.get("cdp.harvest_timeout_s", 18),
            "account_name": cfg.get("cdp.account_name", "nihilistcod"),
        }
    except Exception:
        return {
            "port": 9223,
            "navigation_wait_s": 6,
            "harvest_timeout_s": 18,
            "account_name": "nihilistcod",
        }

def _cdp_host() -> str:
    return f"http://localhost:{_get_cdp_config()['port']}"
GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta"
    "/models/gemini-embedding-001:embedContent"
)
_AIKEY_RE = re.compile(r"AIza[a-zA-Z0-9_\-]{35}")
_HARVEST_URL_HINT = "alkalimakersuite-pa.clients6.google.com"
_NLM_URL = "https://notebooklm.google.com/"
_AISTUDIO_URL = "https://aistudio.google.com/"
_AISTUDIO_APIKEY_URL = "https://aistudio.google.com/app/apikey"


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class AuthStatus:
    """Result object from a check or recovery run."""

    cdp_available: bool = False
    chrome_version: str = ""
    nlm_logged_in: bool = False
    aistudio_logged_in: bool = False
    cookies_injected: int = 0
    cookies_saved: int = 0
    working_api_keys: List[str] = field(default_factory=list)
    dead_api_keys: List[str] = field(default_factory=list)
    harvested_keys: List[str] = field(default_factory=list)
    keys_updated: bool = False
    # v1.50.1 — BL + session token tracking
    bl_refreshed: bool = False
    bl_value: str = ""
    session_tokens_refreshed: bool = False
    pool_synced: bool = False
    errors: List[str] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def healthy(self) -> bool:
        """True when NLM is logged in and at least one API key works."""
        return self.nlm_logged_in and bool(self.working_api_keys)

    def summary(self) -> str:
        parts = [
            f"CDP={'ok' if self.cdp_available else 'DOWN'}",
            f"NLM={'in' if self.nlm_logged_in else 'OUT'}",
            f"AIStudio={'in' if self.aistudio_logged_in else 'OUT'}",
            f"keys={len(self.working_api_keys)}ok/{len(self.dead_api_keys)}dead",
        ]
        if self.bl_value:
            parts.append(f"BL={'ok' if self.bl_refreshed else 'stale'}")
        if self.pool_synced:
            parts.append("pool=synced")
        parts += [
            f"t={self.duration_s:.1f}s",
        ]
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        return " | ".join(parts)


# ── CDP REST helpers ───────────────────────────────────────────────────────────

def _cdp_get(path: str, timeout: int = 5) -> Any:
    """GET a CDP REST endpoint and return parsed JSON, or None on failure."""
    try:
        with urllib.request.urlopen(f"{_cdp_host()}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _open_new_tab() -> Optional[Dict[str, Any]]:
    """Open a new blank tab via CDP and return its descriptor."""
    try:
        req = urllib.request.Request(
            f"{_cdp_host()}/json/new",
            data=b"",
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _close_tab(tab_id: str) -> None:
    try:
        urllib.request.urlopen(f"{_cdp_host()}/json/close/{tab_id}", timeout=3)
    except Exception:
        pass


# ── Async CDP command helper ───────────────────────────────────────────────────

async def _cmd(ws: Any, method: str, params: Dict = None, msg_id: int = 1) -> Dict:
    """Send one CDP command and await its matching response."""
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=15)
        msg = json.loads(raw)
        if msg.get("id") == msg_id:
            return msg


# ── Cookie helpers ─────────────────────────────────────────────────────────────

_HTTPONLY_NAMES = frozenset({
    "SID", "HSID", "SSID",
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC",
})


async def _inject_cookies(ws: Any, cookies: Dict[str, str], base_id: int = 10) -> int:
    """Inject {name: value} cookie dict into Chrome via Network.setCookie."""
    await _cmd(ws, "Network.enable", {}, msg_id=base_id)
    injected = 0
    for i, (name, value) in enumerate(cookies.items(), start=base_id + 1):
        r = await _cmd(ws, "Network.setCookie", {
            "name": name,
            "value": value,
            "domain": ".google.com",
            "path": "/",
            "secure": True,
            "httpOnly": name in _HTTPONLY_NAMES,
        }, msg_id=i)
        if r.get("result", {}).get("success"):
            injected += 1
    return injected


async def _extract_cookies(ws: Any, msg_id: int = 200) -> Dict[str, str]:
    """Return all Google cookies from the current Chrome session."""
    r = await _cmd(ws, "Network.getAllCookies", {}, msg_id=msg_id)
    return {
        c["name"]: c["value"]
        for c in r.get("result", {}).get("cookies", [])
        if "google" in c.get("domain", "") and c.get("value")
    }


# ── Navigation + login check ───────────────────────────────────────────────────

async def _navigate_and_check(
    ws: Any,
    url: str,
    ok_title: str,
    base_id: int = 100,
) -> bool:
    """Navigate to url; return True if page title contains ok_title and we're not on a sign-in page."""
    await _cmd(ws, "Page.navigate", {"url": url}, msg_id=base_id)
    nav_wait = _get_cdp_config()["navigation_wait_s"]
    await asyncio.sleep(nav_wait)
    r = await _cmd(ws, "Runtime.evaluate", {
        "expression": "JSON.stringify({title: document.title, url: location.href})"
    }, msg_id=base_id + 1)
    try:
        data = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
        title = data.get("title", "")
        cur_url = data.get("url", "")
        blocked = any(x in cur_url for x in ("accounts.google.com", "CookieMismatch", "signin"))
        return ok_title.lower() in title.lower() and not blocked
    except Exception:
        return False


# ── API key helpers ────────────────────────────────────────────────────────────

def _test_key(key: str) -> bool:
    """Return True if key can reach the Gemini embedding endpoint."""
    try:
        resp = requests.post(
            f"{GEMINI_EMBED_URL}?key={key}",
            json={"model": "models/gemini-embedding-001",
                  "content": {"parts": [{"text": "test"}]}},
            timeout=8,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _load_current_keys() -> List[str]:
    """Read API_KEYS list from aistudio_client.py."""
    try:
        src = AISTUDIO_CLIENT_PATH.read_text(encoding="utf-8")
        m = re.search(r"API_KEYS\s*=\s*\[(.*?)\]", src, re.DOTALL)
        if m:
            return _AIKEY_RE.findall(m.group(1))
    except Exception:
        pass
    return []


async def _harvest_keys(ws: Any) -> List[str]:
    """Navigate to AI Studio API keys page and intercept network responses to collect full key values."""
    await _cmd(ws, "Network.enable", {}, msg_id=400)
    await _cmd(ws, "Page.navigate", {"url": _AISTUDIO_APIKEY_URL}, msg_id=401)

    seen: Dict[str, str] = {}  # requestId -> url
    found: List[str] = []
    next_id = 500
    harvest_timeout = _get_cdp_config()["harvest_timeout_s"]
    deadline = asyncio.get_event_loop().time() + harvest_timeout

    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            if found:
                break
            continue

        msg = json.loads(raw)
        method = msg.get("method", "")

        if method == "Network.responseReceived":
            rid = msg["params"]["requestId"]
            url = msg["params"]["response"]["url"]
            mime = msg["params"]["response"].get("mimeType", "")
            if any(x in mime for x in ("json", "text", "javascript")):
                seen[rid] = url

        elif method == "Network.loadingFinished":
            rid = msg["params"]["requestId"]
            if rid not in seen:
                continue
            call_id = next_id
            next_id += 1
            await ws.send(json.dumps({
                "id": call_id,
                "method": "Network.getResponseBody",
                "params": {"requestId": rid},
            }))
            for _ in range(30):
                try:
                    r = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                except asyncio.TimeoutError:
                    break
                if r.get("id") == call_id:
                    body = r.get("result", {}).get("body", "")
                    keys = _AIKEY_RE.findall(body)
                    if keys and _HARVEST_URL_HINT in seen[rid]:
                        found.extend(keys)
                        logger.info(
                            "Harvested %d keys from %s", len(keys), seen[rid][:70]
                        )
                    break

    return list(dict.fromkeys(found))  # dedupe, preserve order


# ── Session extraction (BL, f.sid, at) ────────────────────────────────────────
# v1.50.1 [2026-03-22] — Reuses WIZ_global_data expression from har_capture.py:232-247

_WIZ_EXTRACT_JS = (
    "JSON.stringify({"
    "  bl: (() => {"
    "    const wiz = window.WIZ_global_data || {};"
    "    const explicit = wiz.QrtxK || wiz.cfb2h || wiz.bl || '';"
    "    if (typeof explicit === 'string' && explicit.startsWith('boq_labs-tailwind-frontend_')) return explicit;"
    "    for (const value of Object.values(wiz)) {"
    "      if (typeof value === 'string' && value.startsWith('boq_labs-tailwind-frontend_')) return value;"
    "    }"
    "    return '';"
    "  })(),"
    "  f_sid: (window.WIZ_global_data && (window.WIZ_global_data.IxjpMA || window.WIZ_global_data.FdrFJe)) || '',"
    "  at: (window.WIZ_global_data && window.WIZ_global_data.SNlM0e) || '',"
    "  href: location.href"
    "})"
)


async def _extract_nlm_session(ws: Any, base_id: int = 130) -> Dict[str, str]:
    """Extract BL, f.sid, and at token from the NLM page via Runtime.evaluate."""
    try:
        r = await _cmd(ws, "Runtime.evaluate", {
            "expression": _WIZ_EXTRACT_JS,
            "returnByValue": True,
        }, msg_id=base_id)
        raw = r.get("result", {}).get("result", {}).get("value", "{}")
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("Failed to extract NLM session: %s", exc)
        return {}
    meta: Dict[str, str] = {}
    bl = data.get("bl", "")
    if isinstance(bl, str) and bl.startswith("boq_labs-tailwind-frontend_"):
        meta["bl"] = bl
    f_sid = data.get("f_sid")
    if f_sid not in (None, ""):
        meta["f_sid"] = str(f_sid)
    at = data.get("at")
    if isinstance(at, str) and at:
        meta["at"] = at
    href = data.get("href", "")
    if isinstance(href, str) and href:
        meta["href"] = href
    return meta


def _save_nlm_meta(session: Dict[str, str]) -> None:
    """Write session metadata (BL, f.sid, at) to data/nlm_meta.json."""
    try:
        existing: Dict[str, Any] = {}
        if NLM_META_PATH.exists():
            existing = json.loads(NLM_META_PATH.read_text(encoding="utf-8"))
        existing.update(session)
        existing["refreshed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        NLM_META_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        logger.info("Wrote NLM meta to %s", NLM_META_PATH)
    except Exception as exc:
        logger.warning("Failed to write nlm_meta.json: %s", exc)


def _sync_to_account_pool(cookies: Dict[str, str], nlm_session: Dict[str, str]) -> bool:
    """Sync fresh cookies + session tokens to GoogleAccountPool."""
    try:
        from scripts.argus.tools.token_harvester import update_account_pool
        account_name = _get_cdp_config()["account_name"]
        service_sessions: Dict[str, Dict[str, str]] = {}
        if nlm_session:
            service_sessions["notebooklm"] = dict(nlm_session)
        update_account_pool(
            cookies, account_name,
            session=nlm_session,
            at_token=nlm_session.get("at"),
            service_sessions=service_sessions,
        )
        logger.info("[cdp_auth_recovery] Pool synced for '%s' (%d cookies, BL=%s) (operation=pool_sync)",
                    account_name, len(cookies), nlm_session.get("bl", "none")[:30])
        return True
    except Exception as exc:
        logger.warning("[cdp_auth_recovery] Pool sync failed (operation=pool_sync): %s", exc)
        return False


# ── Config writers ─────────────────────────────────────────────────────────────

def _write_aistudio_client(keys: List[str]) -> bool:
    """Rewrite API_KEYS list in aistudio_client.py."""
    try:
        src = AISTUDIO_CLIENT_PATH.read_text(encoding="utf-8")
        key_lines = "\n".join(f'    "{k}",' for k in keys)
        new_block = f"API_KEYS = [\n{key_lines}\n]"
        new_src = re.sub(r"API_KEYS\s*=\s*\[.*?\]", new_block, src, flags=re.DOTALL)
        if new_src != src:
            AISTUDIO_CLIENT_PATH.write_text(new_src, encoding="utf-8")
            logger.info("Updated aistudio_client.py with %d keys", len(keys))
            return True
    except Exception as exc:
        logger.warning("Failed to update aistudio_client.py: %s", exc)
    return False


def _write_rpcids_yaml(keys: List[str]) -> bool:
    """Rewrite known_api_keys block in nlm_rpcids.yaml."""
    try:
        src = RPCIDS_YAML_PATH.read_text(encoding="utf-8")
        key_lines = "\n".join(f"    - {k}" for k in keys)
        new_block = f"    known_api_keys: &id001\n{key_lines}"
        new_src = re.sub(
            r"    known_api_keys: &id001\n(?:    - AIza[a-zA-Z0-9_\-]{35}\n)+",
            new_block + "\n",
            src,
        )
        if new_src != src:
            RPCIDS_YAML_PATH.write_text(new_src, encoding="utf-8")
            logger.info("Updated nlm_rpcids.yaml with %d keys", len(keys))
            return True
    except Exception as exc:
        logger.warning("Failed to update nlm_rpcids.yaml: %s", exc)
    return False


def _update_configs(keys: List[str]) -> bool:
    a = _write_aistudio_client(keys)
    b = _write_rpcids_yaml(keys)
    return a or b


# ── Core async flows ───────────────────────────────────────────────────────────

async def _async_check() -> AuthStatus:
    """Read-only health check — no writes, no navigation."""
    status = AuthStatus()
    version_data = _cdp_get("/json/version")
    if not version_data:
        status.errors.append("Chrome CDP not reachable at localhost:9223")
        return status
    status.cdp_available = True
    status.chrome_version = version_data.get("Browser", "")

    # Cookie file
    if not NLM_COOKIES_PATH.exists():
        status.errors.append("data/nlm_cookies.json missing")

    # API keys
    for key in _load_current_keys():
        (status.working_api_keys if _test_key(key) else status.dead_api_keys).append(key)

    logger.info(
        "Health check: keys=%d ok / %d dead",
        len(status.working_api_keys),
        len(status.dead_api_keys),
    )
    return status


async def _async_recover(keys_only: bool = False) -> AuthStatus:
    """Full cookie + key recovery using a disposable Chrome tab."""
    import websockets

    t0 = time.time()
    status = AuthStatus()

    # 1. CDP available?
    version_data = _cdp_get("/json/version")
    if not version_data:
        status.errors.append("Chrome CDP not reachable at localhost:9223")
        status.duration_s = time.time() - t0
        return status
    status.cdp_available = True
    status.chrome_version = version_data.get("Browser", "")
    logger.info("CDP: %s", status.chrome_version)

    # 2. Open a fresh tab (so we never clobber user tabs)
    tab = _open_new_tab()
    if not tab:
        status.errors.append("Could not open new Chrome tab")
        status.duration_s = time.time() - t0
        return status
    tab_id = tab["id"]
    ws_url = tab["webSocketDebuggerUrl"]

    try:
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:

            if not keys_only:
                # 3. Load + inject saved cookies
                saved: Dict[str, str] = {}
                if NLM_COOKIES_PATH.exists():
                    try:
                        saved = json.loads(NLM_COOKIES_PATH.read_text(encoding="utf-8"))
                    except Exception as exc:
                        status.errors.append(f"Cookie load error: {exc}")

                if saved:
                    status.cookies_injected = await _inject_cookies(ws, saved, base_id=10)
                    logger.info("Injected %d cookies", status.cookies_injected)

                # 4. Navigate to NLM → check login
                status.nlm_logged_in = await _navigate_and_check(
                    ws, _NLM_URL, "NotebookLM", base_id=100
                )
                logger.info("NLM: %s", "logged in" if status.nlm_logged_in else "FAILED")

                # 5. Extract BL + session tokens from WIZ_global_data
                nlm_session: Dict[str, str] = {}
                if status.nlm_logged_in:
                    nlm_session = await _extract_nlm_session(ws, base_id=130)
                    if nlm_session.get("bl"):
                        status.bl_refreshed = True
                        status.bl_value = nlm_session["bl"]
                        logger.info("BL: %s", status.bl_value)
                    if nlm_session.get("f_sid") or nlm_session.get("at"):
                        status.session_tokens_refreshed = True
                        logger.info("Session: f_sid=%s at=%s",
                                    "ok" if nlm_session.get("f_sid") else "MISSING",
                                    "ok" if nlm_session.get("at") else "MISSING")
                    if nlm_session:
                        _save_nlm_meta(nlm_session)

                # 6. Extract fresh cookies + save
                fresh = await _extract_cookies(ws, msg_id=200)
                if fresh:
                    NLM_COOKIES_PATH.write_text(json.dumps(fresh, indent=2), encoding="utf-8")
                    status.cookies_saved = len(fresh)
                    logger.info("Saved %d fresh cookies", len(fresh))
                    # 7. Sync cookies + session to GoogleAccountPool
                    status.pool_synced = _sync_to_account_pool(fresh, nlm_session)

                # 8. Navigate to AI Studio → check login
                status.aistudio_logged_in = await _navigate_and_check(
                    ws, _AISTUDIO_URL, "Google AI Studio", base_id=110
                )
                logger.info(
                    "AI Studio: %s",
                    "logged in" if status.aistudio_logged_in else "FAILED",
                )

            # 9. Validate existing API keys
            for key in _load_current_keys():
                (status.working_api_keys if _test_key(key) else status.dead_api_keys).append(key)
            logger.info(
                "Keys: %d working, %d dead",
                len(status.working_api_keys),
                len(status.dead_api_keys),
            )

            # 10. Harvest fresh keys if any are dead or none work
            needs_harvest = not status.working_api_keys or status.dead_api_keys
            if needs_harvest:
                logger.info("Harvesting fresh API keys from AI Studio...")
                harvested = await _harvest_keys(ws)
                status.harvested_keys = harvested
                logger.info("Harvested %d candidate keys", len(harvested))

                for key in harvested:
                    if _test_key(key):
                        if key not in status.working_api_keys:
                            status.working_api_keys.append(key)
                    else:
                        if key not in status.dead_api_keys:
                            status.dead_api_keys.append(key)

                if status.working_api_keys:
                    working = list(dict.fromkeys(status.working_api_keys))
                    status.keys_updated = _update_configs(working)

    except Exception as exc:
        status.errors.append(f"Recovery error: {exc}")
        logger.exception("Recovery error")
    finally:
        _close_tab(tab_id)

    status.duration_s = time.time() - t0
    logger.info("Recovery complete in %.1fs: %s", status.duration_s, status.summary())
    return status


# ── Public synchronous API ─────────────────────────────────────────────────────

def _run_async(coro: Any) -> Any:
    """Run an async coroutine safely from any context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="cdp_auth") as pool:
        return pool.submit(asyncio.run, coro).result(timeout=120)

def run_check() -> AuthStatus:
    """Synchronous health check. Safe to call from any context."""
    return _run_async(_async_check())


def run_recovery(keys_only: bool = False) -> AuthStatus:
    """Synchronous full recovery. Safe to call from any context."""
    return _run_async(_async_recover(keys_only=keys_only))


def check_and_recover_if_needed() -> AuthStatus:
    """Check health; run full recovery only if unhealthy. Used by scheduler."""
    status = run_check()
    if not status.healthy:
        logger.warning(
            "Auth unhealthy (%s), running recovery...", status.summary()
        )
        status = run_recovery()
        if status.healthy:
            logger.info("Auth recovery succeeded")
        else:
            logger.error("Auth recovery FAILED: %s", status.summary())
    return status


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="Google auth recovery via Chrome DevTools Protocol"
    )
    ap.add_argument(
        "--check", action="store_true", help="Health check only — no writes"
    )
    ap.add_argument(
        "--keys", action="store_true", help="API key harvest and rotation only"
    )
    args = ap.parse_args()

    if args.check:
        status = run_check()
    elif args.keys:
        status = run_recovery(keys_only=True)
    else:
        status = run_recovery()

    print(status.summary())
    if status.working_api_keys:
        print(f"Working keys: {[k[-4:] for k in status.working_api_keys]}")
    if status.dead_api_keys:
        print(f"Dead keys:    {[k[-4:] for k in status.dead_api_keys]}")
    if status.errors:
        for err in status.errors:
            print(f"ERROR: {err}", file=sys.stderr)

    sys.exit(0 if status.healthy else 1)


if __name__ == "__main__":
    main()
