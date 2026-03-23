"""ARGUS gRPC Discovery — scan NLM tab for all gRPC + batchexecute calls.

Connects to Chrome via CDP, navigates through NLM UI features,
captures all LabsTailwindOrchestrationService gRPC calls and batchexecute rpcids.

v1.50.2 [2026-03-23]
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import urlopen

CDP_PORT = 9223


async def discover_grpc():
    import websockets

    tabs = json.loads(urlopen(f"http://localhost:{CDP_PORT}/json", timeout=3).read())
    nlm = next(
        (t for t in tabs if "notebooklm" in t.get("url", "") and t["type"] == "page"),
        None,
    )
    if not nlm:
        print("No NLM tab found")
        return

    print("=== ARGUS gRPC Discovery ===")
    print(f"Tab: {nlm['title']} — {nlm['url']}")

    captured = []

    async with websockets.connect(
        nlm["webSocketDebuggerUrl"], max_size=50 * 1024 * 1024
    ) as ws:
        _mid = 0

        async def cmd(method, params=None):
            nonlocal _mid
            _mid += 1
            await ws.send(
                json.dumps({"id": _mid, "method": method, "params": params or {}})
            )
            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if r.get("id") == _mid:
                    return r.get("result", {})
                # Capture network events while waiting for our response
                _process_event(r)

        def _process_event(msg):
            if msg.get("method") == "Network.requestWillBeSent":
                req = msg["params"].get("request", {})
                url = req.get("url", "")
                if "LabsTailwind" in url or "batchexecute" in url:
                    rpcid_match = re.search(r"rpcids=([^&]+)", url)
                    grpc_match = re.search(r"OrchestrationService/(\w+)", url)
                    captured.append(
                        {
                            "url": url[:200],
                            "method": req.get("method"),
                            "rpcids": rpcid_match.group(1) if rpcid_match else None,
                            "grpc_method": grpc_match.group(1) if grpc_match else None,
                            "type": "grpc" if grpc_match else "batchexecute",
                            "requestId": msg["params"].get("requestId"),
                            "trigger": "pending",
                        }
                    )

        async def drain_events(seconds, trigger="unknown"):
            deadline = time.time() + seconds
            while time.time() < deadline:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    _process_event(msg)
                    # Tag the trigger
                    if captured and captured[-1]["trigger"] == "pending":
                        captured[-1]["trigger"] = trigger
                except asyncio.TimeoutError:
                    continue

        # ──── Enable monitoring ──────────────────────────────────
        await cmd("Network.enable")
        await cmd("Runtime.enable")
        print("Network + Runtime enabled")

        # ──── Extract session ────────────────────────────────────
        r = await cmd(
            "Runtime.evaluate",
            {
                "expression": (
                    "JSON.stringify({"
                    "bl: (() => { const w=window.WIZ_global_data||{};"
                    "for(const v of Object.values(w))"
                    "  if(typeof v==='string'&&v.startsWith('boq_labs-tailwind-frontend_')) return v;"
                    "return '';})(),"
                    "fsid: (() => { const w=window.WIZ_global_data||{};"
                    "return w.FdrFJe||w.IxjpMA||'';})(),"
                    "at: (() => { const w=window.WIZ_global_data||{};"
                    "return w.SNlM0e||'';})(),"
                    "url: location.href,"
                    "nbId: (() => {"
                    "  const m=location.href.match(/notebook\\/([a-f0-9-]+)/);"
                    "  return m?m[1]:'';})(),"
                    "})"
                )
            },
        )

        session = json.loads(r.get("result", {}).get("value", "{}"))
        print(f"BL: {session.get('bl', '?')[:50]}")
        print(f"f.sid: {str(session.get('fsid', '?'))[:20]}...")
        print(f"at: {'present' if session.get('at') else 'missing'}")
        print(f"Notebook: {session.get('nbId', 'not in notebook')}")

        # ──── Navigate to notebook if on homepage ────────────────
        if not session.get("nbId"):
            print()
            print("On homepage — fetching notebook list...")
            bl = session["bl"]
            fsid = session["fsid"]
            at = session.get("at", "")

            fetch_js = (
                "(async () => {"
                "  const body = new URLSearchParams();"
                '  body.set("f.req", JSON.stringify([[["wXbhsf", "[null,1,null,[2]]", null, "generic"]]]));\n'
                + (f'  body.set("at", "{at}");\n' if at else "")
                + "  const r = await fetch("
                f"    'https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute?rpcids=wXbhsf&source-path=/&bl={bl}&f.sid={fsid}&hl=en&_reqid={int(time.time()) % 100000 * 100}&rt=c',"
                "    { method: 'POST', credentials: 'include', body: body,"
                "      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' } }"
                "  );"
                "  return await r.text();"
                "})()"
            )
            r = await cmd(
                "Runtime.evaluate", {"expression": fetch_js, "awaitPromise": True}
            )
            raw = r.get("result", {}).get("value", "")

            nb_ids = re.findall(
                r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", raw
            )
            unique_nbs = list(dict.fromkeys(nb_ids))[:5]
            print(f"Found {len(unique_nbs)} notebook UUIDs")
            for i, nb in enumerate(unique_nbs):
                print(f"  [{i}] {nb}")

            if unique_nbs:
                target_nb = unique_nbs[0]
                print(f"\nNavigating to notebook: {target_nb}")
                captured.clear()

                await cmd(
                    "Page.navigate",
                    {
                        "url": f"https://notebooklm.google.com/notebook/{target_nb}"
                    },
                )

                print("Capturing page load traffic for 15s...")
                await drain_events(15, "page_load")

        # ──── Click through UI to trigger gRPC ───────────────────
        print()
        print("Triggering UI features...")

        # Survey available clickable elements first
        r = await cmd(
            "Runtime.evaluate",
            {
                "expression": (
                    "JSON.stringify(Array.from(document.querySelectorAll("
                    "'button, [role=tab], [role=menuitem], [aria-label]'"
                    ")).filter(e => e.offsetParent !== null).map(e => ({"
                    "tag: e.tagName, text: e.textContent.trim().substring(0,60),"
                    "aria: e.getAttribute('aria-label'),"
                    "role: e.getAttribute('role')"
                    "})).filter(e => e.text || e.aria))"
                )
            },
        )
        elements = json.loads(r.get("result", {}).get("value", "[]"))
        print(f"Found {len(elements)} interactive elements:")
        for e in elements[:30]:
            label = e.get("aria") or e.get("text", "")
            print(f"  [{e['role'] or e['tag']}] {label[:60]}")

        # Click each tab/button and capture traffic
        click_targets = [
            ("Notes/Artifacts", "[aria-label*='Note'], [data-tab*='note']"),
            ("Study Guide", "[aria-label*='Study'], [aria-label*='Guide'], [aria-label*='guide']"),
            ("Audio Overview", "[aria-label*='Audio'], [aria-label*='audio'], [data-tab*='audio']"),
            ("Sources panel", "[aria-label*='Source'], [aria-label*='source']"),
            ("Chat panel", "[aria-label*='Chat'], [aria-label*='chat']"),
            ("Discover sources", "[aria-label*='Discover'], [aria-label*='discover'], [aria-label*='Suggest']"),
            ("Share notebook", "[aria-label*='Share'], [aria-label*='share']"),
            ("Settings/More", "[aria-label*='More'], [aria-label*='Settings'], [aria-label*='setting']"),
            ("Model selector", "[aria-label*='Model'], [aria-label*='model']"),
        ]

        for name, selector in click_targets:
            try:
                r = await cmd(
                    "Runtime.evaluate",
                    {
                        "expression": (
                            f"(() => {{ const el = document.querySelector(\"{selector}\");"
                            "if (el) { el.click(); return 'clicked'; } return 'not_found'; }})()"
                        )
                    },
                )
                status = r.get("result", {}).get("value", "not_found")
                if status == "clicked":
                    print(f"  Clicked: {name}")
                    await drain_events(4, name)
                else:
                    print(f"  Skip: {name} (not found)")
            except Exception as e:
                print(f"  Error: {name} — {e}")

        # ──── Report ─────────────────────────────────────────────
        print()
        print(f"=== CAPTURED {len(captured)} REQUESTS ===")
        print()

        seen_rpcids = {}
        seen_grpc = {}

        for c in captured:
            if c.get("rpcids"):
                for rid in c["rpcids"].split(","):
                    rid = rid.strip()
                    if rid and rid not in seen_rpcids:
                        seen_rpcids[rid] = c.get("trigger", "?")
            if c.get("grpc_method"):
                m = c["grpc_method"]
                if m not in seen_grpc:
                    seen_grpc[m] = c.get("trigger", "?")

        print("BATCHEXECUTE RPCIDS:")
        for rid, trigger in sorted(seen_rpcids.items()):
            print(f"  {rid:12s}  trigger={trigger}")

        print()
        print("GRPC METHODS:")
        for method, trigger in sorted(seen_grpc.items()):
            print(f"  {method:40s}  trigger={trigger}")

        print()
        print(f"Total unique rpcids: {len(seen_rpcids)}")
        print(f"Total unique gRPC methods: {len(seen_grpc)}")

        # ──── Save ───────────────────────────────────────────────
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rpcids": {k: v for k, v in sorted(seen_rpcids.items())},
            "grpc_methods": {k: v for k, v in sorted(seen_grpc.items())},
            "raw_capture_count": len(captured),
        }

        out_path = Path("data/argus/grpc_discovery_latest.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2))
        print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    asyncio.run(discover_grpc())
