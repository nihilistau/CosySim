"""ARGUS Chat Probe — discover the current NLM chat rpcid payload format.

Launches a fresh Chrome with CDP, navigates to a NotebookLM notebook,
sends a chat message via the UI, and captures the batchexecute traffic
to extract the exact rpcid and payload structure.

Version: v1.50.1 [2026-03-22]
Author:  CosySim Team

Usage:
    python scripts/argus_chat_probe.py
    python scripts/argus_chat_probe.py --notebook <uuid>
    python scripts/argus_chat_probe.py --account knack112358
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("argus_chat_probe")

CDP_PORT = 9223  # Separate from user's Chrome
NLM_BASE = "https://notebooklm.google.com"
BATCHEXECUTE_PATTERN = "batchexecute"
GRPC_PATTERN = "GenerateFreeFormStreamed"

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


# ──── CDP helpers ─────────────────────────────────────────────────────────────

def _find_chrome() -> Optional[str]:
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


def _cdp_get(path: str) -> Any:
    try:
        with urllib.request.urlopen(f"http://localhost:{CDP_PORT}{path}", timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


class CDPSession:
    def __init__(self, ws):
        self._ws = ws
        self._id = 0

    async def send(self, method: str, params: dict = None) -> dict:
        self._id += 1
        cid = self._id
        await self._ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=30)
            msg = json.loads(raw)
            if msg.get("id") == cid:
                return msg.get("result", {})

    async def recv_event(self, timeout: float = 1.0) -> Optional[dict]:
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            return json.loads(raw)
        except asyncio.TimeoutError:
            return None


# ──── Main probe ──────────────────────────────────────────────────────────────

async def probe_chat(notebook_id: str, account_name: str = "knack112358") -> Dict[str, Any]:
    """Launch Chrome, navigate to notebook, inject a chat message, capture traffic."""
    import websockets

    # Load cookies from pool
    from engine.integrations.google_account_pool import get_account_pool
    pool = get_account_pool()
    acct = pool.get_by_name(account_name)
    if not acct:
        return {"error": f"Account '{account_name}' not found in pool"}

    cookies = acct.cookies
    logger.info("Loaded %d cookies for %s", len(cookies), account_name)

    # Launch Chrome
    chrome = _find_chrome()
    if not chrome:
        return {"error": "Chrome not found"}

    profile_dir = ROOT / "data" / "chrome_probe_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    nb_url = f"{NLM_BASE}/notebook/{notebook_id}"
    cmd = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        nb_url,
    ]

    logger.info("Launching Chrome on port %d → %s", CDP_PORT, nb_url)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for CDP
    for _ in range(15):
        await asyncio.sleep(1)
        if _cdp_get("/json"):
            break
    else:
        proc.terminate()
        return {"error": "Chrome CDP did not start"}

    await asyncio.sleep(3)
    tabs = _cdp_get("/json") or []
    ws_url = None
    for tab in tabs:
        if tab.get("type") == "page":
            ws_url = tab.get("webSocketDebuggerUrl")
            break

    if not ws_url:
        proc.terminate()
        return {"error": "No page tab found"}

    captured_requests: List[Dict[str, Any]] = []

    try:
        async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
            cdp = CDPSession(ws)

            # Inject cookies
            await cdp.send("Network.enable")
            injected = 0
            for name, value in cookies.items():
                r = await cdp.send("Network.setCookie", {
                    "name": name, "value": value,
                    "domain": ".google.com", "path": "/", "secure": True,
                })
                if r.get("success"):
                    injected += 1
            logger.info("Injected %d cookies", injected)

            # Navigate to the notebook
            await cdp.send("Page.enable")
            await cdp.send("Page.navigate", {"url": nb_url})
            logger.info("Navigating to %s", nb_url)
            await asyncio.sleep(8)  # Wait for NLM SPA to fully load

            # Check if we're logged in
            title_result = await cdp.send("Runtime.evaluate", {
                "expression": "document.title",
                "returnByValue": True,
            })
            title = title_result.get("result", {}).get("value", "")
            logger.info("Page title: %s", title)

            if "sign in" in title.lower() or "accounts.google" in title.lower():
                return {"error": "Not logged in — cookie injection failed"}

            # Type a chat message using DOM interaction
            logger.info("Typing chat message...")

            # Find and click the chat input
            await cdp.send("Runtime.evaluate", {
                "expression": """
                    (function() {
                        // Find chat input — try multiple selectors
                        const selectors = [
                            'textarea[aria-label*="chat"]',
                            'textarea[placeholder*="Type"]',
                            'textarea[placeholder*="Ask"]',
                            'div[contenteditable="true"]',
                            'textarea',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.offsetParent !== null) {
                                el.focus();
                                el.value = 'What is this notebook about?';
                                el.dispatchEvent(new Event('input', {bubbles: true}));
                                return 'found: ' + sel;
                            }
                        }
                        return 'no input found';
                    })()
                """,
                "returnByValue": True,
            })

            await asyncio.sleep(1)

            # Press Enter to submit
            await cdp.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
            })
            await cdp.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
            })

            logger.info("Message sent, capturing traffic for 15s...")

            # Capture network traffic for 15 seconds
            request_bodies: Dict[str, str] = {}  # requestId -> postData
            deadline = asyncio.get_event_loop().time() + 15

            while asyncio.get_event_loop().time() < deadline:
                event = await cdp.recv_event(timeout=1.0)
                if not event:
                    continue

                method = event.get("method", "")
                params = event.get("params", {})

                # Capture request with body
                if method == "Network.requestWillBeSent":
                    url = params.get("request", {}).get("url", "")
                    if BATCHEXECUTE_PATTERN in url or GRPC_PATTERN in url:
                        req_id = params.get("requestId", "")
                        post_data = params.get("request", {}).get("postData", "")
                        http_method = params.get("request", {}).get("method", "")

                        # Parse rpcids from URL
                        parsed_url = urllib.parse.urlparse(url)
                        qs = urllib.parse.parse_qs(parsed_url.query)
                        rpcids = qs.get("rpcids", [""])[0]

                        entry = {
                            "url": url[:200],
                            "method": http_method,
                            "rpcids": rpcids,
                            "post_data_length": len(post_data),
                            "timestamp": time.time(),
                        }

                        # Parse f.req payload
                        if post_data:
                            request_bodies[req_id] = post_data
                            decoded = urllib.parse.unquote(post_data)
                            # Extract rpcid + inner payload from f.req
                            freq_match = re.search(r'f\.req=(.+?)(?:&|$)', decoded)
                            if freq_match:
                                try:
                                    freq_data = json.loads(freq_match.group(1))
                                    entry["f_req_parsed"] = freq_data
                                except json.JSONDecodeError:
                                    entry["f_req_raw"] = freq_match.group(1)[:500]

                        captured_requests.append(entry)
                        logger.info(
                            "CAPTURED: %s %s (rpcids=%s, body=%d bytes)",
                            http_method, url[:80], rpcids, len(post_data),
                        )

                # Also capture response bodies for batchexecute
                elif method == "Network.responseReceived":
                    url = params.get("response", {}).get("url", "")
                    if BATCHEXECUTE_PATTERN in url or GRPC_PATTERN in url:
                        req_id = params.get("requestId", "")
                        status = params.get("response", {}).get("status", 0)
                        # Try to get response body
                        try:
                            body_result = await cdp.send("Network.getResponseBody", {"requestId": req_id})
                            body = body_result.get("body", "")
                            if body:
                                for req in captured_requests:
                                    if req.get("rpcids") and req["rpcids"] in url:
                                        req["response_status"] = status
                                        req["response_body_preview"] = body[:500]
                                        break
                        except Exception:
                            pass

    except Exception as exc:
        logger.error("Probe error: %s", exc)
        return {"error": str(exc), "captured": captured_requests}
    finally:
        proc.terminate()

    return {
        "notebook_id": notebook_id,
        "captured_count": len(captured_requests),
        "requests": captured_requests,
    }


# ──── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="ARGUS Chat Probe — discover NLM chat rpcid format")
    ap.add_argument("--notebook", default="933ba855-50b9-446e-946b-ae439375d850",
                     help="Notebook UUID to probe")
    ap.add_argument("--account", default="knack112358", help="Account name from pool")
    args = ap.parse_args()

    result = asyncio.run(probe_chat(args.notebook, args.account))

    print(f"\n{'='*60}")
    print(f"Captured {result.get('captured_count', 0)} batchexecute/gRPC requests")
    print(f"{'='*60}")

    for req in result.get("requests", []):
        print(f"\n--- {req.get('rpcids', '?')} ({req.get('method', '?')}) ---")
        print(f"  URL: {req.get('url', '')[:120]}")
        if req.get("f_req_parsed"):
            print(f"  Payload: {json.dumps(req['f_req_parsed'], indent=2)[:500]}")
        elif req.get("f_req_raw"):
            print(f"  Raw: {req['f_req_raw'][:300]}")
        if req.get("response_body_preview"):
            print(f"  Response: {req['response_body_preview'][:200]}")

    # Save results
    output_path = ROOT / "data" / "argus" / "chat_probe_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nSaved to {output_path}")

    if result.get("error"):
        print(f"\nERROR: {result['error']}")


if __name__ == "__main__":
    main()
