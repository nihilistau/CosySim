"""CDP Live Probe — attach to running NLM tab and inject fetch calls.

Uses the browser's own auth context so x-browser-validation is included.
v1.50.1 [2026-03-22]
"""
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

CDP_PORT = 9223


async def main():
    import websockets

    tabs = json.loads(urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json", timeout=3).read())
    nlm_tab = next((t for t in tabs if "notebooklm" in t.get("url", "") and t.get("type") == "page"), None)
    if not nlm_tab:
        print("No NLM tab found")
        return

    ws_url = nlm_tab["webSocketDebuggerUrl"]
    print(f"Attached: {nlm_tab['title'][:60]}")

    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        _mid = 0

        async def cmd(method, params=None):
            nonlocal _mid
            _mid += 1
            await ws.send(json.dumps({"id": _mid, "method": method, "params": params or {}}))
            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if r.get("id") == _mid:
                    return r.get("result", {})

        await cmd("Runtime.enable")

        # Extract session
        r = await cmd("Runtime.evaluate", {
            "expression": (
                "JSON.stringify({"
                "bl: (() => { const w=window.WIZ_global_data||{};"
                "for(const v of Object.values(w)) if(typeof v==='string'&&v.startsWith('boq_labs-tailwind-frontend_')) return v;"
                "return ''; })(),"
                "f_sid: (window.WIZ_global_data&&(window.WIZ_global_data.IxjpMA||window.WIZ_global_data.FdrFJe))||'',"
                "at: (window.WIZ_global_data&&window.WIZ_global_data.SNlM0e)||'',"
                "url: location.href,"
                "})"
            ),
            "returnByValue": True,
        })
        session = json.loads(r.get("result", {}).get("value", "{}"))
        bl = session.get("bl", "")
        f_sid = session.get("f_sid", "")
        at = session.get("at", "")
        nb_url = session.get("url", "")
        nb_id = nb_url.rstrip("/").split("/")[-1] if "/notebook/" in nb_url else ""

        print(f"BL: {bl}")
        print(f"f.sid: {f_sid}")
        print(f"at: {'present' if at else 'MISSING'}")
        print(f"notebook: {nb_id}")

        # Check DOM
        r = await cmd("Runtime.evaluate", {
            "expression": (
                "JSON.stringify({"
                "query_box: !!document.querySelector('[aria-label=\"Query box\"]'),"
                "submit_btn: !!document.querySelector('[aria-label=\"Submit\"]'),"
                "})"
            ),
            "returnByValue": True,
        })
        dom = json.loads(r.get("result", {}).get("value", "{}"))
        print(f"Query box: {dom.get('query_box')}")
        print(f"Submit btn: {dom.get('submit_btn')}")

        # Inject fetch for list_sources via browser context
        source_path = f"/notebook/{nb_id}"
        rpc_payload = json.dumps([[["wXbhsf", "[null,1,null,[2]]", None, "generic"]]])

        js = (
            "(async () => {"
            "  const body = new URLSearchParams();"
            f"  body.set('f.req', {json.dumps(rpc_payload)});"
            f"  body.set('at', {json.dumps(at)});"
            f"  const url = '/_/LabsTailwindUi/data/batchexecute?rpcids=wXbhsf"
            f"&source-path=' + encodeURIComponent({json.dumps(source_path)})"
            f" + '&f.sid={f_sid}&bl=' + encodeURIComponent({json.dumps(bl)})"
            " + '&hl=en-US&_reqid=100000&rt=c';"
            "  const resp = await fetch(url, {"
            "    method: 'POST',"
            "    headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},"
            "    body: body.toString(),"
            "    credentials: 'include',"
            "  });"
            "  const text = await resp.text();"
            "  return JSON.stringify({status: resp.status, length: text.length, preview: text.slice(0, 500)});"
            "})()"
        )

        print("\nFetching list_sources (wXbhsf) via browser...")
        r = await cmd("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        raw = r.get("result", {}).get("value", "{}")
        result = json.loads(raw)
        print(f"Status: {result.get('status')}")
        print(f"Length: {result.get('length')}")
        preview = result.get("preview", "")
        print(f"Preview: {preview[:300]}")

        if result.get("status") == 200 and result.get("length", 0) > 200:
            print("\n=== BROWSER FETCH WORKS! Now trying chat... ===\n")

            # Get ALL source IDs — fetch the full response
            full_js = (
                "(async () => {"
                "  const body = new URLSearchParams();"
                f"  body.set('f.req', {json.dumps(rpc_payload)});"
                f"  body.set('at', {json.dumps(at)});"
                f"  const url = '/_/LabsTailwindUi/data/batchexecute?rpcids=wXbhsf"
                f"&source-path=' + encodeURIComponent({json.dumps(source_path)})"
                f" + '&f.sid={f_sid}&bl=' + encodeURIComponent({json.dumps(bl)})"
                " + '&hl=en-US&_reqid=150000&rt=c';"
                "  const resp = await fetch(url, {"
                "    method: 'POST',"
                "    headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},"
                "    body: body.toString(),"
                "    credentials: 'include',"
                "  });"
                "  const text = await resp.text();"
                "  // Extract all UUIDs from the response"
                "  const uuids = [...new Set(text.match(/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/g) || [])];"
                f"  return JSON.stringify({{count: uuids.length, uuids: uuids.filter(u => u !== '{nb_id}')}});"
                "})()"
            )
            r = await cmd("Runtime.evaluate", {"expression": full_js, "awaitPromise": True, "returnByValue": True})
            uuid_data = json.loads(r.get("result", {}).get("value", "{}"))
            source_ids = uuid_data.get("uuids", [])
            print(f"Source IDs from full response: {len(source_ids)}")

            # Build chat payload — use HAR-confirmed v2 format
            source_list = [[[sid]] for sid in source_ids]
            question = "What is this notebook about? Answer in exactly 2 sentences."
            # HAR format: [sources, question, history, config, thread, null, null, nb_id, 1]
            inner = [source_list, question, [], [2, None, [1], [1]], None, None, None, nb_id, 1]
            inner_json = json.dumps(inner, ensure_ascii=False, separators=(",", ":"))
            outer = [None, inner_json]
            outer_json = json.dumps(outer, ensure_ascii=False, separators=(",", ":"))

            chat_js = (
                "(async () => {"
                "  const body = new URLSearchParams();"
                f"  body.set('f.req', {json.dumps(outer_json)});"
                f"  body.set('at', {json.dumps(at)});"
                "  const url = '/_/LabsTailwindUi/data/"
                "google.internal.labs.tailwind.orchestration.v1."
                "LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
                f"?bl=' + encodeURIComponent({json.dumps(bl)})"
                f" + '&f.sid={f_sid}&hl=en-US&_reqid=200000&rt=c';"
                "  const resp = await fetch(url, {"
                "    method: 'POST',"
                "    headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},"
                "    body: body.toString(),"
                "    credentials: 'include',"
                "  });"
                "  const text = await resp.text();"
                "  return JSON.stringify({status: resp.status, length: text.length, preview: text.slice(0, 1000)});"
                "})()"
            )

            print("Fetching chat (GenerateFreeFormStreamed) via browser...")
            r = await cmd("Runtime.evaluate", {"expression": chat_js, "awaitPromise": True, "returnByValue": True, "timeout": 30000})
            raw = r.get("result", {}).get("value", "{}")
            chat_result = json.loads(raw)
            print(f"Status: {chat_result.get('status')}")
            print(f"Length: {chat_result.get('length')}")
            chat_preview = chat_result.get("preview", "")
            print(f"Response: {chat_preview[:500]}")


if __name__ == "__main__":
    asyncio.run(main())
