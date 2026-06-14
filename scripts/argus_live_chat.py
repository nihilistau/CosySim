"""ARGUS Live Chat — Launch Chrome, inject query into NLM, capture traffic.

v1.50.1 [2026-03-22] — Uses proven nlm_query.js injection + CDP network capture.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("argus_live")

CDP_PORT = 9224
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# The proven Angular-compatible query injection from data/argus/nlm_query.js
INJECT_QUERY_JS = """
(() => {
    const box = document.querySelector('[aria-label="Query box"]');
    if (!box) return JSON.stringify({ok: false, error: 'no query box',
        visible: [...document.querySelectorAll('textarea,input,[contenteditable]')]
            .filter(e=>e.offsetParent).map(e=>e.getAttribute('aria-label')||e.placeholder||e.tagName).join(', ')
    });
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(box, 'QUESTION_PLACEHOLDER');
    box.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: 'x'}));
    const btn = document.querySelector('[aria-label="Submit"]');
    if (btn && !btn.disabled) {
        btn.click();
        return JSON.stringify({ok: true, msg: 'Query sent!'});
    }
    return JSON.stringify({ok: false, submit_disabled: btn ? String(btn.disabled) : 'btn not found'});
})()
"""


async def main():
    import websockets
    from engine.integrations.google_account_pool import get_account_pool
    from scripts.har_capture import CDPSession

    pool = get_account_pool()
    acct = pool.get_by_name("knack112358")

    import tempfile
    profile = Path(tempfile.mkdtemp(prefix="nlm_probe_"))
    logger.info("Using temp profile: %s", profile)
    nb_id = "44ff1449-8b8a-4a2b-9986-fe7f14b26cdc"
    nb_url = f"https://notebooklm.google.com/notebook/{nb_id}"

    proc = subprocess.Popen(
        [CHROME, f"--remote-debugging-port={CDP_PORT}",
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

    await asyncio.sleep(4)
    tabs = json.loads(urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json").read())
    ws_url = next((t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page"), None)

    if not ws_url:
        proc.terminate()
        logger.error("No page tab found")
        return

    try:
        async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
            cdp = CDPSession(ws)
            await cdp.send("Network.enable")

            # Inject cookies
            for n, v in acct.cookies.items():
                await cdp.send("Network.setCookie", {
                    "name": n, "value": v,
                    "domain": ".google.com", "path": "/", "secure": True,
                })
            logger.info("Injected %d cookies", len(acct.cookies))

            await cdp.send("Page.enable")
            await cdp.send("Runtime.enable")
            await cdp.send("Page.navigate", {"url": nb_url})
            logger.info("Navigating to %s", nb_url)
            await asyncio.sleep(12)

            r = await cdp.send("Runtime.evaluate", {
                "expression": "document.title",
                "returnByValue": True,
            })
            title = r.get("result", {}).get("value", "")
            logger.info("Title: %s", title)

            # Inject the query
            question = "What is this notebook about? Answer in exactly 2 sentences."
            js = INJECT_QUERY_JS.replace("QUESTION_PLACEHOLDER", question)

            r = await cdp.send("Runtime.evaluate", {
                "expression": js,
                "returnByValue": True,
            })
            inject_raw = r.get("result", {}).get("value", "{}")
            logger.info("Inject result: %s", inject_raw)

            try:
                inject = json.loads(inject_raw)
            except Exception:
                inject = {"ok": False, "raw": inject_raw}

            if not inject.get("ok"):
                logger.warning("Injection failed: %s", inject)
                proc.terminate()
                return

            # Capture traffic for 30s
            logger.info("Capturing traffic for 30s...")
            captured = []
            deadline = asyncio.get_event_loop().time() + 30

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

                            logger.info("CAPTURED: %s (%d bytes)", rpcids or "streaming", len(post))

                            freq_params = urllib.parse.parse_qs(post)
                            freq_raw = freq_params.get("f.req", [""])[0]
                            entry = {"rpcid": rpcids, "url": url[:200]}
                            if freq_raw:
                                try:
                                    entry["freq"] = json.loads(freq_raw)
                                except json.JSONDecodeError:
                                    entry["raw"] = freq_raw[:1000]
                            captured.append(entry)

                            if "GenerateFreeForm" in url:
                                # Wait a bit more for the response
                                await asyncio.sleep(3)
                                break
                except asyncio.TimeoutError:
                    pass

            print(f"\n{'='*60}")
            print(f"Captured {len(captured)} requests")
            print(f"{'='*60}")
            for c in captured:
                print(f"\nrpcid: {c.get('rpcid', '(streaming)')}")
                print(f"url: {c.get('url', '')}")
                if "freq" in c:
                    print(json.dumps(c["freq"], indent=2, ensure_ascii=False)[:800])
                elif "raw" in c:
                    print(c["raw"][:500])

            out = ROOT / "data" / "argus" / "live_chat_capture.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(captured, f, indent=2, default=str)
            print(f"\nSaved to {out}")

    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
