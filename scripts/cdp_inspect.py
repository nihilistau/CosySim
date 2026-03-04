"""
CosySim CDP Debugger — permanent live browser inspection tool.

Usage
-----
    python scripts/cdp.py tabs                        # list open tabs
    python scripts/cdp.py dom    [tab] [--url URL]    # full DOM/z-index/hit-test report
    python scripts/cdp.py css    [tab] SELECTOR       # computed CSS for element
    python scripts/cdp.py net    [tab] [--url URL]    # capture network + console for 8s
    python scripts/cdp.py api    [tab] PATH           # fetch an API route from within the page
    python scripts/cdp.py js     [tab] EXPR           # evaluate JS expression, return value
    python scripts/cdp.py snap   [tab] [FILE]         # screenshot to PNG
    python scripts/cdp.py trace  [tab] [--url URL]    # DOM + CSS + net + console all at once

    tab   = tab ID prefix (auto-selects first non-devtools page if omitted)
    --url = navigate to this URL first before inspecting

Examples
--------
    python scripts/cdp.py tabs
    python scripts/cdp.py dom
    python scripts/cdp.py dom --url http://localhost:5556/
    python scripts/cdp.py css "#cs-announcer"
    python scripts/cdp.py api /api/bedroom/state
    python scripts/cdp.py api /api/hud/state
    python scripts/cdp.py js "document.querySelectorAll('[class*=announcer]').length"
    python scripts/cdp.py net --url http://localhost:5569/
    python scripts/cdp.py snap /tmp/bedroom.png
    python scripts/cdp.py trace --url http://localhost:5556/
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import urllib.request
from typing import Any

CDP_PORT = 9222
SEP = "─" * 72


# ── helpers ──────────────────────────────────────────────────────────────────

def _tabs() -> list[dict]:
    raw = urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json").read()
    return json.loads(raw)


def _pick_tab(prefix: str | None) -> dict:
    tabs = _tabs()
    for t in tabs:
        if t.get("type") != "page":
            continue
        if prefix and not t["id"].startswith(prefix):
            continue
        if not prefix and t["url"].startswith("devtools://"):
            continue
        return t
    raise SystemExit(f"No matching tab (prefix={prefix!r}). Run: python scripts/cdp.py tabs")


class CDP:
    def __init__(self, ws):
        self._ws = ws
        self._id = 0

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        cid = self._id
        await self._ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        while True:
            raw = await self._ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == cid:
                if "error" in msg:
                    print(f"  [CDP ERROR] {msg['error']}", file=sys.stderr)
                return msg.get("result") or {}

    async def js(self, expr: str, await_promise: bool = False) -> Any:
        r = await self.send("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": await_promise,
        })
        res = r.get("result", {})
        if res.get("type") == "string":
            return res["value"]
        return res.get("value")

    async def js_json(self, expr: str, await_promise: bool = False) -> Any:
        v = await self.js(f"JSON.stringify({expr})", await_promise)
        try:
            return json.loads(v) if v else None
        except Exception:
            return v

    async def navigate(self, url: str):
        await self.send("Page.enable")
        await self.send("Page.navigate", {"url": url})
        print(f"  → navigated to {url} (waiting 3s for load)")
        await asyncio.sleep(3)


# ── commands ─────────────────────────────────────────────────────────────────

async def cmd_tabs(_args):
    tabs = _tabs()
    print(SEP)
    print("OPEN CHROME TABS")
    print(SEP)
    for t in tabs:
        mark = "✓" if t.get("type") == "page" and not t["url"].startswith("devtools://") else " "
        print(f"  {mark} {t['id'][:8]}…  {t.get('type','?'):6}  {t['url'][:90]}")


async def cmd_dom(args, cdp: CDP):
    """Full DOM stacking + hit-test + widget + API report."""
    if args.url:
        await cdp.navigate(args.url)

    # ── 1. high-z stacking elements ──
    print(f"\n{SEP}")
    print("HIGH Z-INDEX ELEMENTS  (z > 50, non-static position, pointer-events != none)")
    print(SEP)
    els = await cdp.js_json("""(function(){
  var out=[];
  document.querySelectorAll("*").forEach(function(el){
    var cs=window.getComputedStyle(el);
    var zi=parseInt(cs.zIndex)||0;
    if(zi>50 && cs.position!="static"){
      var r=el.getBoundingClientRect();
      out.push({
        zi:zi, pos:cs.position, pe:cs.pointerEvents, op:parseFloat(cs.opacity),
        id:el.id, cls:el.className.toString().substring(0,70),
        tag:el.tagName, txt:el.innerText?el.innerText.trim().substring(0,40):"",
        w:Math.round(r.width), h:Math.round(r.height), x:Math.round(r.x), y:Math.round(r.y)
      });
    }
  });
  out.sort(function(a,b){return b.zi-a.zi;});
  return out.slice(0,30);
})()""")
    if not els:
        print("  (none found)")
    for e in els or []:
        active = "BLOCKS" if e["pe"] != "none" and e["op"] > 0 else "inert "
        ident  = f"#{e['id']}" if e["id"] else f".{e['cls'][:50]}"
        print(f"  z={e['zi']:6}  {active}  {e['pos']:8}  {e['tag']:<8}  {ident}")
        print(f"           rect {e['w']}×{e['h']} @({e['x']},{e['y']})  pe={e['pe']}  op={e['op']}")
        if e["txt"]:
            print(f"           text: \"{e['txt']}\"")

    # ── 2. hit-test grid ──
    print(f"\n{SEP}")
    print("HIT-TEST — which element receives clicks at these screen coordinates")
    print(SEP)
    points = [
        (100,  400, "left panel"),
        (960,  400, "center"),
        (1700, 400, "right panel"),
        (960,  900, "lower center"),
        (1820, 950, "bottom-right corner"),
        (960,  50,  "navbar"),
    ]
    for x, y, label in points:
        info = await cdp.js_json(f"""(function(){{
  var el=document.elementFromPoint({x},{y});
  if(!el) return null;
  var cs=window.getComputedStyle(el);
  return {{tag:el.tagName,id:el.id,cls:el.className.toString().substring(0,60),
           zi:cs.zIndex,pe:cs.pointerEvents,txt:el.innerText?el.innerText.trim().substring(0,30):""}};
}})()""")
        if info:
            ident = f"#{info['id']}" if info["id"] else f".{info['cls'][:45]}"
            print(f"  ({x:4},{y:3})  {label:<18}  {info['tag']:<8}  {ident}  z={info['zi']}  \"{info['txt']}\"")
        else:
            print(f"  ({x:4},{y:3})  {label:<18}  null")

    # ── 3. floating widgets ──
    print(f"\n{SEP}")
    print("FLOATING WIDGETS  (announcer, aria, modals, overlays)")
    print(SEP)
    widgets = await cdp.js_json("""(function(){
  var selectors=["[class*='announcer']","[class*='aria-']","[id*='aria']",
    "[class*='modal']","[class*='overlay']","[class*='gate']","[class*='toast']",
    "[class*='portal']","[id='penthouse-gate']"];
  var seen=new Set(), out=[];
  selectors.forEach(function(sel){
    document.querySelectorAll(sel).forEach(function(el){
      if(seen.has(el)) return; seen.add(el);
      var cs=window.getComputedStyle(el);
      var r=el.getBoundingClientRect();
      out.push({
        sel:sel, id:el.id, tag:el.tag, cls:el.className.toString().substring(0,70),
        display:cs.display, vis:cs.visibility, op:cs.opacity,
        pe:cs.pointerEvents, zi:cs.zIndex,
        w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)
      });
    });
  });
  return out;
})()""")
    if not widgets:
        print("  (none found)")
    for w in widgets or []:
        ident  = f"#{w['id']}" if w["id"] else f".{w['cls'][:55]}"
        blocks = w["pe"] != "none" and float(w["op"]) > 0 and w["display"] != "none"
        print(f"  {'BLOCKING' if blocks else 'inert  '}  {ident}")
        print(f"    display={w['display']}  vis={w['vis']}  op={w['op']}  pe={w['pe']}  z={w['zi']}")
        print(f"    rect {w['w']}×{w['h']} @({w['x']},{w['y']})")

    # ── 4. selects / dropdowns ──
    print(f"\n{SEP}")
    print("SELECT / INPUT ELEMENTS  (character selectors, dropdowns)")
    print(SEP)
    selects = await cdp.js_json("""(function(){
  var out=[];
  document.querySelectorAll("select,input[list]").forEach(function(el){
    var cs=window.getComputedStyle(el);
    out.push({
      tag:el.tagName, id:el.id, cls:el.className.toString().substring(0,50),
      display:cs.display, disabled:el.disabled, value:el.value,
      opts:Array.from(el.options||[]).slice(0,8).map(function(o){return o.value||o.text;})
    });
  });
  return out;
})()""")
    if not selects:
        print("  (none found)")
    for s in selects or []:
        dis = " DISABLED" if s["disabled"] else ""
        print(f"  <{s['tag']}> #{s['id']} .{s['cls'][:40]}  display={s['display']}{dis}")
        print(f"    value={s['value']!r}  options({len(s['opts'])}): {s['opts']}")

    # ── 5. console errors collected so far ──
    print(f"\n{SEP}")
    print("CURRENT PAGE TITLE / URL")
    print(SEP)
    title = await cdp.js("document.title")
    url   = await cdp.js("location.href")
    print(f"  {title}  —  {url}")


async def cmd_css(args, cdp: CDP):
    """Print computed CSS for a selector."""
    sel = args.selector
    print(f"\n{SEP}")
    print(f"COMPUTED CSS — {sel}")
    print(SEP)
    props = await cdp.js_json(f"""(function(){{
  var el=document.querySelector({json.dumps(sel)});
  if(!el) return null;
  var cs=window.getComputedStyle(el);
  var r=el.getBoundingClientRect();
  var keys=["position","zIndex","display","visibility","opacity","pointerEvents",
    "overflow","width","height","top","right","bottom","left","transform",
    "backgroundColor","color","fontSize","fontFamily","padding","margin",
    "border","boxShadow","cursor","transition","animation","flex","grid"];
  var out={{rect:{{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}}}};
  keys.forEach(function(k){{ out[k]=cs[k]; }});
  out.classes=el.className.toString();
  out.id=el.id;
  out.tag=el.tagName;
  return out;
}})()""")
    if not props:
        print(f"  ✗ No element matched selector: {sel!r}")
        return
    print(f"  <{props.pop('tag','')}> #{props.pop('id','')} .{props.pop('classes','')[:60]}")
    rect = props.pop("rect", {})
    print(f"  rect: {rect['w']}×{rect['h']} @({rect['x']},{rect['y']})")
    for k, v in props.items():
        if v and v not in ("0px", "none", "normal", "auto", "rgba(0, 0, 0, 0)", ""):
            print(f"  {k:<22} {v}")


async def cmd_net(args, cdp: CDP):
    """Capture network requests + console messages for N seconds."""
    if args.url:
        await cdp.navigate(args.url)

    wait = getattr(args, "wait", 6)
    print(f"\n{SEP}")
    print(f"NETWORK + CONSOLE  (capturing {wait}s)")
    print(SEP)

    await cdp.send("Network.enable")
    await cdp.send("Console.enable")
    await cdp.send("Runtime.enable")

    requests: list[dict] = []
    errors:   list[str]  = []

    async def drain():
        deadline = asyncio.get_event_loop().time() + wait
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(cdp._ws.recv(), timeout=0.3)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            method = msg.get("method", "")
            params = msg.get("params", {})
            if method == "Network.responseReceived":
                resp = params.get("response", {})
                status = resp.get("status", 0)
                url    = resp.get("url", "")
                mime   = resp.get("mimeType", "")
                flag   = "✗" if status >= 400 else "✓"
                requests.append({"flag": flag, "status": status, "url": url, "mime": mime})
            elif method in ("Console.messageAdded",):
                lvl = params.get("message", {}).get("level", "")
                txt = params.get("message", {}).get("text", "")
                if lvl in ("error", "warning"):
                    errors.append(f"  [{lvl.upper()}] {txt[:120]}")
            elif method == "Runtime.exceptionThrown":
                desc = params.get("exceptionDetails", {}).get("exception", {}).get("description", "")
                errors.append(f"  [EXCEPTION] {desc[:120]}")

    await drain()

    errors_only = [r for r in requests if r["flag"] == "✗"]
    ok_count    = sum(1 for r in requests if r["flag"] == "✓")
    print(f"  Total requests: {len(requests)}  OK: {ok_count}  Errors: {len(errors_only)}")
    if errors_only:
        print("\n  FAILED REQUESTS:")
        for r in errors_only:
            print(f"    ✗ {r['status']}  {r['url'][:90]}")
    if errors:
        print("\n  CONSOLE ERRORS:")
        for e in errors:
            print(e)


async def cmd_api(args, cdp: CDP):
    """Fetch an API route from within the page context."""
    path = args.path
    print(f"\n{SEP}")
    print(f"API FETCH — {path}")
    print(SEP)
    result = await cdp.js(
        f"fetch({json.dumps(path)}).then(r=>r.text()).catch(e=>'ERROR: '+e)",
        await_promise=True,
    )
    try:
        parsed = json.loads(result)
        print(json.dumps(parsed, indent=2)[:2000])
    except Exception:
        print(str(result)[:2000])


async def cmd_js(args, cdp: CDP):
    """Evaluate a JS expression."""
    result = await cdp.js(args.expr)
    print(result)


async def cmd_snap(args, cdp: CDP):
    """Take a screenshot."""
    out_file = getattr(args, "file", None) or "screenshot.png"
    r = await cdp.send("Page.enable")
    r = await cdp.send("Page.captureScreenshot", {"format": "png", "quality": 90})
    data = r.get("data", "")
    with open(out_file, "wb") as f:
        f.write(base64.b64decode(data))
    print(f"Screenshot saved to: {out_file}  ({len(data) // 1024} KB)")


async def cmd_trace(args, cdp: CDP):
    """Run dom + net + console together — the full diagnostic."""
    await cmd_dom(args, cdp)
    await cmd_net(args, cdp)


# ── entry point ───────────────────────────────────────────────────────────────

async def main(argv: list[str]):
    import websockets as _ws_mod

    p = argparse.ArgumentParser(description="CosySim CDP debugger")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("tabs", help="List open Chrome tabs")

    dom_p = sub.add_parser("dom", help="Full DOM stacking / hit-test report")
    dom_p.add_argument("tab",   nargs="?")
    dom_p.add_argument("--url", default=None)

    css_p = sub.add_parser("css", help="Computed CSS for a selector")
    css_p.add_argument("tab",      nargs="?")
    css_p.add_argument("selector", help="CSS selector, e.g. '#cs-announcer'")

    net_p = sub.add_parser("net", help="Network + console capture")
    net_p.add_argument("tab",    nargs="?")
    net_p.add_argument("--url",  default=None)
    net_p.add_argument("--wait", type=int, default=6)

    api_p = sub.add_parser("api", help="Fetch API path from page context")
    api_p.add_argument("tab",  nargs="?")
    api_p.add_argument("path", help="e.g. /api/bedroom/state")

    js_p = sub.add_parser("js", help="Evaluate JS expression")
    js_p.add_argument("tab",  nargs="?")
    js_p.add_argument("expr", help="JS expression")

    snap_p = sub.add_parser("snap", help="Screenshot")
    snap_p.add_argument("tab",   nargs="?")
    snap_p.add_argument("file",  nargs="?", default="screenshot.png")

    trace_p = sub.add_parser("trace", help="Full trace: dom + net + console")
    trace_p.add_argument("tab",   nargs="?")
    trace_p.add_argument("--url", default=None)

    args = p.parse_args(argv)

    if not args.cmd or args.cmd == "tabs":
        await cmd_tabs(args)
        return

    tab = _pick_tab(getattr(args, "tab", None))
    print(f"[CDP] Tab: {tab['id'][:12]}…  {tab['url'][:70]}")

    async with _ws_mod.connect(
        f"ws://localhost:{CDP_PORT}/devtools/page/{tab['id']}",
        max_size=10_000_000,
    ) as ws:
        cdp = CDP(ws)
        await cdp.send("Runtime.enable")
        await cdp.send("Console.enable")
        cmds = {
            "dom":   cmd_dom,
            "css":   cmd_css,
            "net":   cmd_net,
            "api":   cmd_api,
            "js":    cmd_js,
            "snap":  cmd_snap,
            "trace": cmd_trace,
        }
        await cmds[args.cmd](args, cdp)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
