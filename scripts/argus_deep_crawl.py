"""ARGUS Deep Crawl — systematic NLM UI crawl + direct RPC verification.

Clicks every button in the notebook UI, then directly tests RPCs via
browser fetch to verify which ones are live.

v1.50.2 [2026-03-23]
"""
import asyncio
import json
import re
import time
from pathlib import Path
from urllib.request import urlopen

CDP_PORT = 9223


async def deep_crawl():
    import websockets

    tabs = json.loads(urlopen(f"http://localhost:{CDP_PORT}/json", timeout=3).read())
    nlm = next(
        (t for t in tabs if "notebooklm" in t.get("url", "") and t["type"] == "page"),
        None,
    )
    if not nlm:
        print("No NLM tab found")
        return

    all_captured = []

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
                if r.get("method") == "Network.requestWillBeSent":
                    req = r["params"].get("request", {})
                    url = req.get("url", "")
                    if "LabsTailwind" in url or "batchexecute" in url:
                        rpcid_m = re.search(r"rpcids=([^&]+)", url)
                        grpc_m = re.search(r"OrchestrationService/(\w+)", url)
                        all_captured.append(
                            {
                                "rpcids": rpcid_m.group(1) if rpcid_m else None,
                                "grpc_method": grpc_m.group(1) if grpc_m else None,
                                "trigger": "pending",
                            }
                        )

        async def drain(seconds, trigger="unknown"):
            deadline = time.time() + seconds
            while time.time() < deadline:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if msg.get("method") == "Network.requestWillBeSent":
                        req = msg["params"].get("request", {})
                        url = req.get("url", "")
                        if "LabsTailwind" in url or "batchexecute" in url:
                            rpcid_m = re.search(r"rpcids=([^&]+)", url)
                            grpc_m = re.search(r"OrchestrationService/(\w+)", url)
                            all_captured.append(
                                {
                                    "rpcids": rpcid_m.group(1) if rpcid_m else None,
                                    "grpc_method": grpc_m.group(1) if grpc_m else None,
                                    "trigger": trigger,
                                }
                            )
                except asyncio.TimeoutError:
                    continue

        async def click_text(text, wait=3):
            js = (
                "(() => {"
                '  const btns = Array.from(document.querySelectorAll("button, [role=tab], [role=menuitem], a"));'
                '  const btn = btns.find(b => b.textContent.trim().includes("'
                + text
                + '") && b.offsetParent !== null);'
                '  if (btn) { btn.click(); return "clicked"; }'
                '  return "not_found";'
                "})()"
            )
            r = await cmd("Runtime.evaluate", {"expression": js})
            status = r.get("result", {}).get("value", "?")
            if status == "clicked":
                print(f"  [+] {text}")
                await drain(wait, text)
            else:
                print(f"  [-] {text}")
            return status == "clicked"

        async def press_escape():
            await cmd(
                "Runtime.evaluate",
                {
                    "expression": (
                        'document.dispatchEvent(new KeyboardEvent("keydown",'
                        ' {key: "Escape", bubbles: true}));'
                    )
                },
            )
            await asyncio.sleep(0.5)

        await cmd("Network.enable")
        await cmd("Runtime.enable")
        print("=== DEEP ARGUS CRAWL ===")
        print(f"Tab: {nlm['title'][:60]}")
        print()

        # ──── Phase 1: Top-level buttons ─────────────────────────
        print("Phase 1: Top-level buttons")
        await click_text("Analytics", 4)
        await press_escape()
        await click_text("Share notebook", 4)
        await press_escape()
        await click_text("Settings", 4)
        await press_escape()
        await click_text("Create notebook", 3)
        await press_escape()

        # ──── Phase 2: Source panel ──────────────────────────────
        print()
        print("Phase 2: Source panel")
        await click_text("Add source", 3)
        await press_escape()
        await click_text("Select all", 2)
        await click_text("AGENT_ONBOARDING.md", 4)
        await press_escape()

        # Click first "More" button (source context menu)
        r = await cmd(
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => {"
                    '  const mores = Array.from(document.querySelectorAll("button"))'
                    '    .filter(b => b.textContent.trim() === "More" && b.offsetParent !== null);'
                    '  if (mores.length > 0) { mores[0].click(); return "clicked"; }'
                    '  return "not_found";'
                    "})()"
                )
            },
        )
        if r.get("result", {}).get("value") == "clicked":
            print("  [+] More (source context menu)")
            await drain(3, "source_more_menu")
            await press_escape()

        # ──── Phase 3: Research features ─────────────────────────
        print()
        print("Phase 3: Research features")
        await click_text("Fast research", 4)
        await press_escape()

        # ──── Phase 4: Direct RPC verification via browser fetch ─
        print()
        print("Phase 4: Direct RPC verification")

        # Get session params
        r = await cmd(
            "Runtime.evaluate",
            {
                "expression": (
                    "JSON.stringify({"
                    "bl: (() => { const w=window.WIZ_global_data||{};"
                    "for(const v of Object.values(w))"
                    '  if(typeof v==="string"&&v.startsWith("boq_labs-tailwind-frontend_")) return v;'
                    'return "";})(),'
                    "at: (() => { const w=window.WIZ_global_data||{};"
                    'return w.SNlM0e||"";})(),'
                    "nbId: (() => {"
                    '  const m=location.href.match(/notebook\\/([a-f0-9-]+)/);'
                    '  return m?m[1]:"";})(),'
                    "})"
                )
            },
        )
        sess = json.loads(r.get("result", {}).get("value", "{}"))
        bl = sess["bl"]
        at = sess.get("at", "")
        nb_id = sess["nbId"]

        if not nb_id:
            print("  Not in a notebook — skipping RPC tests")
        else:
            # Test RPCs we want to verify
            test_rpcs = [
                ("generate_guide", "xqEXEf", json.dumps([nb_id, [2]])),
                ("generate_mind_map", "yyryJe", json.dumps([nb_id, [2]])),
                ("get_locale", "DYBcR", json.dumps([])),
                ("get_chat_history", "GzgSEd", json.dumps([[], None, nb_id, 50])),
                ("feature_flags", "ozz5Z", json.dumps([])),
                ("user_profile", "JFMDGd", json.dumps([nb_id, [2]])),
                ("ai_summary", "VfAZjd", json.dumps([nb_id, [2]])),
                ("list_artifacts", "gArtLc", json.dumps([[2], nb_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"'])),
                ("share_notebook", "dI5Y8", json.dumps([nb_id])),
                ("analytics", "AUrzMb", json.dumps([nb_id])),
            ]

            for op_name, rpcid, args in test_rpcs:
                at_part = f'body.set("at", "{at}");' if at else ""
                reqid = int(time.time()) % 100000 * 100

                fetch_js = (
                    "(async () => {"
                    "  const body = new URLSearchParams();"
                    f'  body.set("f.req", JSON.stringify([[[\"{rpcid}\", {json.dumps(args)}, null, \"generic\"]]]));'
                    f"  {at_part}"
                    "  try {"
                    "    const r = await fetch("
                    f'      "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute'
                    f"?rpcids={rpcid}&source-path=/notebook/{nb_id}&bl={bl}"
                    f'&f.sid=-1&hl=en&_reqid={reqid}&rt=c",'
                    '      { method: "POST", credentials: "include", body: body,'
                    '        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" } }'
                    "    );"
                    "    const text = await r.text();"
                    '    return JSON.stringify({status: r.status, len: text.length, has_data: text.includes("wrb.fr")});'
                    "  } catch(e) { return JSON.stringify({error: e.message}); }"
                    "})()"
                )

                r = await cmd(
                    "Runtime.evaluate",
                    {"expression": fetch_js, "awaitPromise": True},
                )
                result = json.loads(r.get("result", {}).get("value", "{}"))
                status = result.get("status", "?")
                has_data = result.get("has_data", False)
                length = result.get("len", 0)
                if has_data:
                    marker = "OK"
                elif status == 200:
                    marker = "EMPTY"
                else:
                    marker = f"ERR:{status}"
                print(
                    f"  {op_name:25s} {rpcid}  status={status}  "
                    f"len={length:>8d}  {marker}"
                )
                await asyncio.sleep(1.5)  # rate limit

        # ──── Report ─────────────────────────────────────────────
        print()
        seen_rpc = {}
        seen_grpc = {}
        for c in all_captured:
            if c.get("rpcids"):
                for rid in c["rpcids"].split(","):
                    rid = rid.strip()
                    if rid not in seen_rpc:
                        seen_rpc[rid] = c.get("trigger", "?")
            if c.get("grpc_method"):
                m = c["grpc_method"]
                if m not in seen_grpc:
                    seen_grpc[m] = c.get("trigger", "?")

        print(f"=== DEEP CRAWL RESULTS ({len(all_captured)} requests) ===")
        print()
        print("BATCHEXECUTE RPCIDS (from UI clicks):")
        for rid, trigger in sorted(seen_rpc.items()):
            print(f"  {rid:12s}  trigger={trigger}")
        print()
        print("GRPC METHODS (from UI clicks):")
        for method, trigger in sorted(seen_grpc.items()):
            print(f"  {method:40s}  trigger={trigger}")
        print()
        print(f"Total: {len(seen_rpc)} rpcids, {len(seen_grpc)} gRPC methods")

        # Save
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "notebook": nb_id,
            "rpcids_from_ui": seen_rpc,
            "grpc_methods_from_ui": seen_grpc,
            "raw_count": len(all_captured),
        }
        out = Path("data/argus/deep_crawl_latest.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        print(f"\nSaved to {out}")


if __name__ == "__main__":
    asyncio.run(deep_crawl())
