"""ARGUS Chat Capture — type into NLM chat UI and capture the real batchexecute payload.

v1.50.1 [2026-03-22] — Discovers new chat rpcid payload format after deployment rotation.
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

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("argus_chat_capture")

CDP_PORT = 9223


async def cmd(ws, method, params=None):
    """Send CDP command and return result."""
    if not hasattr(cmd, "_mid"):
        cmd._mid = 0
    cmd._mid += 1
    mid = cmd._mid
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        r = json.loads(await asyncio.wait_for(ws.recv(), 30))
        if r.get("id") == mid:
            return r.get("result", {})


async def main():
    import websockets
    from engine.integrations.google_account_pool import get_account_pool

    pool = get_account_pool()
    acct = pool.get_by_name("knack112358")
    cookies = acct.cookies

    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    profile = ROOT / "data" / "chrome_probe_profile"
    profile.mkdir(parents=True, exist_ok=True)
    nb_id = "933ba855-50b9-446e-946b-ae439375d850"
    nb_url = f"https://notebooklm.google.com/notebook/{nb_id}"

    proc = subprocess.Popen(
        [chrome, f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={profile}", "--no-first-run", nb_url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    for _ in range(15):
        await asyncio.sleep(1)
        try:
            urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json", timeout=2)
            break
        except Exception:
            pass

    await asyncio.sleep(3)
    tabs = json.loads(urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json").read())
    ws_url = next((t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page"), None)

    if not ws_url:
        proc.terminate()
        print("No page tab found")
        return

    try:
        async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
            cmd._mid = 0

            # Inject cookies
            await cmd(ws, "Network.enable")
            for n, v in cookies.items():
                await cmd(ws, "Network.setCookie", {
                    "name": n, "value": v, "domain": ".google.com",
                    "path": "/", "secure": True,
                })
            logger.info("Injected %d cookies", len(cookies))

            # Navigate to NLM home first (cookie injection sticks better on home page)
            await cmd(ws, "Page.enable")
            await cmd(ws, "Page.navigate", {"url": "https://notebooklm.google.com/"})
            logger.info("Loading NLM home (for cookie activation)...")
            await asyncio.sleep(5)

            # Re-inject cookies after first navigation (they stick now)
            for n, v in cookies.items():
                await cmd(ws, "Network.setCookie", {
                    "name": n, "value": v, "domain": ".google.com",
                    "path": "/", "secure": True,
                })

            # Now navigate to the specific notebook
            await cmd(ws, "Page.navigate", {"url": nb_url})
            logger.info("Navigating to %s", nb_url)
            await asyncio.sleep(10)

            # Find visible input elements
            r = await cmd(ws, "Runtime.evaluate", {
                "expression": """
                    (() => {
                        const els = document.querySelectorAll(
                            'textarea, input[type=text], div[contenteditable], [role=textbox]'
                        );
                        return JSON.stringify([...els].filter(e => e.offsetParent !== null).map(e => ({
                            tag: e.tagName,
                            placeholder: e.placeholder || '',
                            aria: e.getAttribute('aria-label') || '',
                            role: e.getAttribute('role') || '',
                        })));
                    })()
                """,
                "returnByValue": True,
            })
            inputs = json.loads(r.get("result", {}).get("value", "[]"))
            logger.info("Visible inputs: %d", len(inputs))
            for inp in inputs:
                logger.info("  %s placeholder=%r aria=%r", inp["tag"], inp["placeholder"], inp["aria"])

            # Type into the chat textarea using native setter (bypasses framework guards)
            r = await cmd(ws, "Runtime.evaluate", {
                "expression": """
                    (() => {
                        const textareas = document.querySelectorAll('textarea');
                        for (const ta of textareas) {
                            if (ta.offsetParent !== null) {
                                const nativeSetter = Object.getOwnPropertyDescriptor(
                                    window.HTMLTextAreaElement.prototype, 'value'
                                ).set;
                                nativeSetter.call(ta, 'What is this notebook about?');
                                ta.dispatchEvent(new Event('input', {bubbles: true}));
                                ta.dispatchEvent(new Event('change', {bubbles: true}));
                                return 'typed into: ' + (ta.placeholder || ta.getAttribute('aria-label') || 'textarea');
                            }
                        }
                        return 'no visible textarea';
                    })()
                """,
                "returnByValue": True,
            })
            type_result = r.get("result", {}).get("value", "")
            logger.info("Type: %s", type_result)
            await asyncio.sleep(1)

            # Find and click the send button
            r = await cmd(ws, "Runtime.evaluate", {
                "expression": """
                    (() => {
                        const selectors = [
                            'button[aria-label*="Send"]',
                            'button[aria-label*="send"]',
                            'button[aria-label*="Submit"]',
                        ];
                        for (const sel of selectors) {
                            const btn = document.querySelector(sel);
                            if (btn && btn.offsetParent !== null) {
                                btn.click();
                                return 'clicked: ' + sel;
                            }
                        }
                        // Fallback: find button near the textarea
                        const buttons = [...document.querySelectorAll('button')].filter(b => b.offsetParent);
                        const info = buttons.map(b => (b.innerText || b.getAttribute('aria-label') || '?').trim().slice(0, 30));
                        return 'no send button. visible buttons: ' + info.join(' | ');
                    })()
                """,
                "returnByValue": True,
            })
            send_result = r.get("result", {}).get("value", "")
            logger.info("Send: %s", send_result)

            # Capture network for 20s
            logger.info("Capturing traffic for 20s...")
            captured = []
            deadline = asyncio.get_event_loop().time() + 20

            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg = json.loads(raw)
                    method = msg.get("method", "")
                    params = msg.get("params", {})

                    if method == "Network.requestWillBeSent":
                        url = params.get("request", {}).get("url", "")
                        if "batchexecute" in url or "GenerateFreeForm" in url:
                            post = params.get("request", {}).get("postData", "")
                            qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                            rpcids = qs.get("rpcids", [""])[0]
                            logger.info("CAPTURED: %s (%d bytes)", rpcids, len(post))

                            decoded = urllib.parse.unquote(post)
                            freq = re.search(r"f\.req=(.+?)(?:&|$)", decoded)
                            if freq:
                                try:
                                    parsed = json.loads(freq.group(1))
                                    captured.append({"rpcid": rpcids, "payload": parsed, "url": url[:200]})
                                except json.JSONDecodeError:
                                    captured.append({"rpcid": rpcids, "raw": freq.group(1)[:500], "url": url[:200]})
                            else:
                                captured.append({"rpcid": rpcids, "body": decoded[:500], "url": url[:200]})
                except asyncio.TimeoutError:
                    pass

            print(f"\n{'='*60}")
            print(f"Captured {len(captured)} batchexecute/gRPC requests")
            print(f"{'='*60}")
            for c in captured:
                print(f"\nrpcid: {c.get('rpcid', '?')}")
                if "payload" in c:
                    print(json.dumps(c["payload"], indent=2, ensure_ascii=False)[:600])
                elif "raw" in c:
                    print(c["raw"][:400])
                else:
                    print(c.get("body", "")[:400])

            # Save
            out = ROOT / "data" / "argus" / "chat_capture_result.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(captured, f, indent=2, default=str)
            print(f"\nSaved to {out}")

    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
