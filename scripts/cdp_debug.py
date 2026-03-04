"""CDP debug — navigate to a scene and capture network/console events."""
import json
import asyncio
import sys
import time

async def debug(url: str, tab_id: str) -> None:
    import websockets
    ws_url = f"ws://localhost:9222/devtools/page/{tab_id}"
    async with websockets.connect(ws_url, max_size=10_000_000) as ws:
        _id = 0

        async def send(method, params=None):
            nonlocal _id
            _id += 1
            await ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
            return _id

        await send("Network.enable")
        await send("Console.enable")
        await send("Runtime.enable")
        await send("Page.enable")
        # Drain acks
        for _ in range(4):
            await asyncio.wait_for(ws.recv(), timeout=2)

        await send("Page.navigate", {"url": url})

        events = []
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                e = json.loads(msg)
                method = e.get("method", "")
                if any(x in method for x in [
                    "Network.response", "Network.loadingFailed",
                    "Console.message", "Runtime.exception"
                ]):
                    events.append(e)
            except asyncio.TimeoutError:
                pass

        print(f"\n=== {url} ===\n")
        net404 = []
        net_ok = []
        for e in events:
            m = e.get("method", "")
            p = e.get("params", {})
            if m == "Network.responseReceived":
                r = p.get("response", {})
                status = r.get("status", "?")
                u = r.get("url", "")
                if status >= 400:
                    net404.append(f"  [{status}] {u}")
                elif "/shared/" in u:
                    net_ok.append(f"  [{status}] {u}")
            elif m == "Network.loadingFailed":
                net404.append(f"  [FAIL] {p.get('errorText')} req={p.get('requestId')}")
            elif m == "Console.messageAdded":
                msg = p.get("message", {})
                lvl = msg.get("level", "")
                if lvl in ("error", "warning"):
                    print(f"CON [{lvl}] {msg.get('text', '')[:150]}")
            elif m == "Runtime.exceptionThrown":
                exc = p.get("exceptionDetails", {})
                print(f"EXC {exc.get('text', '')} @ {exc.get('url', '')}:{exc.get('lineNumber', '')}")

        if net404:
            print("\n404/FAIL:")
            for x in net404:
                print(x)
        if net_ok:
            print("\nShared OK:")
            for x in net_ok:
                print(x)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5569/"
    tab = sys.argv[2] if len(sys.argv) > 2 else "DB2C4D070C400902370DA988BEA8D834"
    asyncio.run(debug(target, tab))
