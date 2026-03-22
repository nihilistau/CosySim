"""NLM Ask — query NotebookLM via CDP browser fetch.

Attaches to a running Chrome NLM tab and injects fetch() calls
so the browser handles all auth headers (x-browser-validation etc).

Usage:
    python scripts/nlm_ask.py "What is this about?"
    python scripts/nlm_ask.py "Explain the architecture" --port 9223
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

CDP_PORT = 9223


async def cmd(ws, method, params=None, timeout=60):
    """Send CDP command with configurable timeout."""
    if not hasattr(cmd, "_mid"):
        cmd._mid = 0
    cmd._mid += 1
    mid = cmd._mid
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        r = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if r.get("id") == mid:
            return r.get("result", {})


async def ask(question: str, port: int = CDP_PORT) -> str:
    """Ask NLM a question via CDP browser fetch. Returns answer text."""
    import websockets

    tabs = json.loads(urllib.request.urlopen(f"http://localhost:{port}/json", timeout=3).read())
    nlm_tab = next((t for t in tabs if "notebooklm" in t.get("url", "") and t.get("type") == "page"), None)
    if not nlm_tab:
        return "[ERROR: No NLM tab found]"

    async with websockets.connect(nlm_tab["webSocketDebuggerUrl"], max_size=20 * 1024 * 1024) as ws:
        cmd._mid = 0
        await cmd(ws, "Runtime.enable")

        # Get session params
        r = await cmd(ws, "Runtime.evaluate", {
            "expression": (
                "JSON.stringify({"
                "bl:(() => {const w=window.WIZ_global_data||{};"
                "for(const v of Object.values(w))"
                "if(typeof v==='string'&&v.startsWith('boq_labs-tailwind-frontend_'))return v;"
                "return '';})(),"
                "f_sid:(window.WIZ_global_data&&(window.WIZ_global_data.IxjpMA||window.WIZ_global_data.FdrFJe))||'',"
                "at:(window.WIZ_global_data&&window.WIZ_global_data.SNlM0e)||'',"
                "url:location.href})"
            ),
            "returnByValue": True,
        })
        s = json.loads(r.get("result", {}).get("value", "{}"))
        nb_id = s["url"].rstrip("/").split("/")[-1] if "/notebook/" in s.get("url", "") else ""
        if not nb_id:
            return "[ERROR: Not on a notebook page]"

        # Build payload — HAR-confirmed v2 format, empty sources = all
        inner = json.dumps(
            [[], question, [], [2, None, [1], [1]], None, None, None, nb_id, 1],
            ensure_ascii=False, separators=(",", ":"),
        )
        outer = json.dumps([None, inner], ensure_ascii=False, separators=(",", ":"))

        # Inject fetch via browser context
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
            "+'&f.sid=" + s["f_sid"] + "&hl=en-US&_reqid=500000&rt=c'"
            ",{method:'POST',"
            "headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},"
            "body:b.toString(),credentials:'include'});"
            "return await r.text();})()"
        )

        # Use longer timeout — Gemini can take 30-45s for complex questions
        r = await cmd(ws, "Runtime.evaluate", {
            "expression": js,
            "awaitPromise": True,
            "returnByValue": True,
        }, timeout=90)
        result_obj = r.get("result", {})
        raw = result_obj.get("value", "")
        if not isinstance(raw, str):
            # awaitPromise may return an exception description
            desc = result_obj.get("description", "")
            if desc:
                return f"[ERROR: {desc[:200]}]"
            raw = json.dumps(result_obj)[:2000]

        # Parse wrb.fr chunks — extract the final answer, skip thinking traces.
        # Response structure (streaming):
        #   Chunks 0-N: Thinking traces (bold headers like "**Analyzing...**\n\n")
        #   Chunks N+1..M: Answer building progressively (each adds more text)
        #   Last chunks: Final answer (stabilized, repeated)
        # Strategy: take the last chunk, skip if it looks like a thinking trace.
        texts = []
        for line in raw.replace(")]}'", "").split("\n"):
            line = line.strip()
            if not line or not line.startswith("["):
                continue
            try:
                for item in json.loads(line):
                    if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr" and item[2]:
                        d = json.loads(item[2])
                        if isinstance(d, list) and d:
                            txt = d[0][0] if isinstance(d[0], list) and d[0] else d[0] if isinstance(d[0], str) else ""
                            if isinstance(txt, str) and txt.strip():
                                texts.append(txt)
            except Exception:
                pass

        if not texts:
            return "[No answer parsed from response]"

        # The final answer is the last text. If all chunks are thinking traces,
        # fall back to the longest non-trace chunk.
        answer = texts[-1]

        # If the last chunk is a thinking trace (starts with **Bold**\n),
        # walk backwards to find the actual answer
        import re
        if re.match(r"\*\*[A-Z].*\*\*\s*\n", answer):
            for txt in reversed(texts):
                if not re.match(r"\*\*[A-Z].*\*\*\s*\n", txt):
                    answer = txt
                    break

        return answer


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Ask NotebookLM via CDP browser fetch")
    ap.add_argument("question", help="Question to ask")
    ap.add_argument("--port", type=int, default=CDP_PORT, help="CDP port")
    args = ap.parse_args()

    answer = asyncio.run(ask(args.question, args.port))
    print(answer)


if __name__ == "__main__":
    main()
