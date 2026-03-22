"""Debug NLM response chunks — show all wrb.fr items to understand structure."""
import asyncio, json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def main():
    import websockets
    tabs = json.loads(urllib.request.urlopen("http://localhost:9223/json", timeout=3).read())
    nlm_tab = next((t for t in tabs if "notebooklm" in t.get("url", "") and t.get("type") == "page"), None)

    async with websockets.connect(nlm_tab["webSocketDebuggerUrl"], max_size=20 * 1024 * 1024) as ws:
        _mid = 0
        async def cmd(method, params=None):
            nonlocal _mid; _mid += 1
            await ws.send(json.dumps({"id": _mid, "method": method, "params": params or {}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == _mid:
                    return r.get("result", {})

        await cmd("Runtime.enable")
        r = await cmd("Runtime.evaluate", {
            "expression": (
                "JSON.stringify({bl:(() => {const w=window.WIZ_global_data||{};"
                "for(const v of Object.values(w))if(typeof v==='string'&&v.startsWith('boq_labs-tailwind-frontend_'))return v;"
                "return '';})(),"
                "f_sid:(window.WIZ_global_data&&(window.WIZ_global_data.IxjpMA||window.WIZ_global_data.FdrFJe))||'',"
                "at:(window.WIZ_global_data&&window.WIZ_global_data.SNlM0e)||'',"
                "url:location.href})"
            ),
            "returnByValue": True,
        })
        s = json.loads(r.get("result", {}).get("value", "{}"))
        nb_id = s["url"].rstrip("/").split("/")[-1]

        inner = json.dumps(
            [[], "What is CosySim? One sentence only.", [], [2, None, [1], [1]], None, None, None, nb_id, 1],
            ensure_ascii=False, separators=(",", ":"),
        )
        outer = json.dumps([None, inner], ensure_ascii=False, separators=(",", ":"))

        js = (
            "(async()=>{"
            "const b=new URLSearchParams();"
            "b.set('f.req'," + json.dumps(outer) + ");"
            "b.set('at'," + json.dumps(s["at"]) + ");"
            "const r=await fetch("
            "'/_/LabsTailwindUi/data/"
            "google.internal.labs.tailwind.orchestration.v1."
            "LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
            "?bl='+encodeURIComponent(" + json.dumps(s["bl"]) + ")"
            "+'&f.sid=" + s["f_sid"] + "&hl=en-US&_reqid=700000&rt=c'"
            ",{method:'POST',"
            "headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},"
            "body:b.toString(),credentials:'include'});"
            "return await r.text();})()"
        )

        r = await cmd("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        raw = r.get("result", {}).get("value", "")
        if not isinstance(raw, str):
            print(f"Error: {r.get('result', {})}")
            return

        # Parse ALL wrb.fr chunks
        chunks = []
        for line in raw.replace(")]}'", "").split("\n"):
            line = line.strip()
            if not line or not line.startswith("["):
                continue
            try:
                for item in json.loads(line):
                    if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                        chunks.append({"raw_item": item})
            except Exception:
                pass

        print(f"Total wrb.fr chunks: {len(chunks)}")
        for i, chunk in enumerate(chunks):
            item = chunk["raw_item"]
            inner_str = item[2] if len(item) > 2 else None
            # item[4] often has error/status info
            extra = item[5] if len(item) > 5 else None

            if inner_str:
                try:
                    d = json.loads(inner_str)
                    # Walk the structure
                    if isinstance(d, list) and d:
                        first = d[0]
                        if isinstance(first, list) and first and isinstance(first[0], str):
                            text = first[0]
                            print(f"\nChunk {i}: TEXT [{len(text)} chars]")
                            print(f"  {text[:300]}")
                        elif isinstance(first, str):
                            print(f"\nChunk {i}: TEXT [{len(first)} chars]")
                            print(f"  {first[:300]}")
                        else:
                            print(f"\nChunk {i}: DATA {json.dumps(d)[:200]}")
                    else:
                        print(f"\nChunk {i}: OTHER {json.dumps(d)[:200]}")
                except Exception:
                    print(f"\nChunk {i}: UNPARSEABLE inner ({len(inner_str)} chars)")
            elif extra:
                print(f"\nChunk {i}: STATUS {json.dumps(extra)[:200]}")
            else:
                print(f"\nChunk {i}: EMPTY")


if __name__ == "__main__":
    asyncio.run(main())
