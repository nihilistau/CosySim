"""
CosySim CDP Monitor — persistent live browser watcher with timeline support.

Streams all Chrome DevTools events to logs/cdp.log.
Watches for file changes and auto-inserts timeline markers.
You can manually insert markers to track exactly what you changed and when.

Usage
─────────────────────────────────────────────────────────────────────────────
  Start monitor (background, logs to logs/cdp.log):
    python scripts/cdp_monitor.py start

  Start + print to terminal too:
    python scripts/cdp_monitor.py start --follow

  Insert a manual timeline marker:
    python scripts/cdp_monitor.py mark "removed aria_widget.js from bedroom.html"
    python scripts/cdp_monitor.py mark "restarted bedroom scene"
    python scripts/cdp_monitor.py mark "deployed commit abc123"

  Read recent log (last N lines):
    python scripts/cdp_monitor.py tail 80

  Show only errors since last marker:
    python scripts/cdp_monitor.py errors

  Show full timeline of markers with error counts between them:
    python scripts/cdp_monitor.py timeline

  Watch a single scene port:
    python scripts/cdp_monitor.py start --port 5556

  Errors only mode:
    python scripts/cdp_monitor.py start --errors-only

  PowerShell tailing:
    Get-Content logs\\cdp.log -Wait -Tail 60
    Select-String -Path logs\\cdp.log -Pattern "✗|💥|MARK"
    Select-String -Path logs\\cdp.log -Pattern "MARK" | Select-Object -Last 5

  MCP skill (agents):
    cdp_tail(lines=50)          — read recent log
    cdp_mark(message)           — insert timeline marker
    cdp_errors(since_last=True) — errors since last marker
    cdp_timeline()              — markers + error counts
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import websockets

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).resolve().parent.parent
LOG_PATH    = ROOT / "logs" / "cdp.log"
EVENTS_PATH = ROOT / "logs" / "cdp_events.jsonl"   # machine-readable parallel log
MARKER_PATH = ROOT / "logs" / "cdp_markers.jsonl"  # timeline marker index

CDP_PORT = 9223

# ── Scene port map ────────────────────────────────────────────────────────────

SCENE_PORTS = {
    5555: "phone",       5556: "bedroom",    5557: "lounge",
    5558: "tavern",      5559: "casino",     5560: "gallery",
    5561: "arena",       5562: "realm",      5563: "neoncity",
    5564: "coders",      5565: "games",      5566: "heist",
    5567: "asset_studio",5568: "command",    5569: "grid",
    5570: "nexus_panel", 5572: "intel",      8500: "hub",
    8700: "nexus_kms",   1234: "lmstudio",
}

# ── Watch these paths for auto file-change markers ───────────────────────────

WATCH_GLOBS = [
    "content/scenes/**/*.py",
    "content/scenes/**/*.html",
    "content/scenes/**/*.js",
    "content/scenes/**/*.css",
    "content/shared/static/js/*.js",
    "content/shared/static/css/*.css",
    "content/shared/templates/*.html",
    "engine/**/*.py",
]

# ── Noise filters (suppressed unless --verbose) ───────────────────────────────

NOISE = [
    re.compile(r"/api/health"),
    re.compile(r"favicon\.ico"),
    re.compile(r"ERR_CONNECTION_REFUSED.*:\d+/api/health"),
    re.compile(r"localhost:\d+/api/health.*ERR_CONNECTION_REFUSED"),
    re.compile(r"GET http://localhost:\d+/api/health"),
]

# ── Error patterns (always logged, highlighted) ───────────────────────────────

ERRORS = [
    re.compile(r"already been declared"),
    re.compile(r"\bis not defined\b"),
    re.compile(r"\bis not a function\b"),
    re.compile(r"Failed to fetch"),
    re.compile(r"CORS policy"),
    re.compile(r"\b(404|500|502|503)\b"),
    re.compile(r"TypeError|ReferenceError|SyntaxError|RangeError"),
    re.compile(r"\bUncaught\b"),
    re.compile(r"aria_widget.*fallback", re.I),
    re.compile(r"Invalid model identifier"),
    re.compile(r"model.*not.*found", re.I),
    re.compile(r"register_shared_assets"),
    re.compile(r"CosyNavbar is not defined"),
    re.compile(r"net::ERR_"),
]

SEP_THIN  = "─" * 72
SEP_THICK = "═" * 72


# ── Formatting ────────────────────────────────────────────────────────────────

_SESSION_START = time.time()
_LAST_MARKER   = time.time()


def ts_abs() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def ts_rel() -> str:
    """Seconds since session start and since last marker."""
    since_start  = time.time() - _SESSION_START
    since_marker = time.time() - _LAST_MARKER
    return f"+{since_start:7.1f}s  Δ{since_marker:6.1f}s"


def scene_for(url: str) -> str:
    m = re.search(r"localhost:(\d+)", url)
    if m:
        port = int(m.group(1))
        return SCENE_PORTS.get(port, f":{port}")
    return url[:20] if url else "unknown"


def is_noise(text: str) -> bool:
    return any(p.search(text) for p in NOISE)


def is_error(text: str) -> bool:
    return any(p.search(text) for p in ERRORS)


ICONS = {
    "ERR":  "✗",
    "EXC":  "💥",
    "WARN": "⚠",
    "NET":  "⬡",
    "NAV":  "→",
    "JS":   "⚡",
    "FILE": "📝",
    "MARK": "┤ MARK ├",
    "INFO": "·",
    "SYS":  "⚙",
}


def log_line(level: str, scene: str, msg: str) -> str:
    icon = ICONS.get(level, "·")
    abs_ = ts_abs()
    rel_ = ts_rel()
    return f"{abs_}  {rel_}  {icon}  [{scene:<12}]  {level:<4}  {msg}"


def write_event(log_file, event_file, level: str, scene: str, msg: str, raw: dict | None = None):
    line = log_line(level, scene, msg)
    log_file.write(line + "\n")
    log_file.flush()
    # Machine-readable parallel log
    record = {
        "ts":    ts_abs(),
        "rel":   round(time.time() - _SESSION_START, 2),
        "delta": round(time.time() - _LAST_MARKER, 2),
        "level": level,
        "scene": scene,
        "msg":   msg,
    }
    if raw:
        record["raw"] = raw
    event_file.write(json.dumps(record) + "\n")
    event_file.flush()


# ── File watcher ──────────────────────────────────────────────────────────────

class FileWatcher:
    """Watches project files, emits a marker when any file changes."""

    def __init__(self, log_file, event_file):
        self._lf = log_file
        self._ef = event_file
        self._mtimes: dict[str, float] = {}
        self._scan()  # seed initial mtimes

    def _scan(self):
        import glob as _glob
        for pattern in WATCH_GLOBS:
            for path in _glob.glob(str(ROOT / pattern), recursive=True):
                try:
                    self._mtimes[path] = os.path.getmtime(path)
                except OSError:
                    pass

    def check(self):
        global _LAST_MARKER
        import glob as _glob
        changed = []
        for pattern in WATCH_GLOBS:
            for path in _glob.glob(str(ROOT / pattern), recursive=True):
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                prev = self._mtimes.get(path)
                if prev is None or mtime > prev + 0.5:
                    rel = str(Path(path).relative_to(ROOT))
                    changed.append(rel)
                    self._mtimes[path] = mtime

        if changed:
            _LAST_MARKER = time.time()
            for rel in changed:
                msg = f"FILE CHANGED: {rel}"
                write_event(self._lf, self._ef, "FILE", "watcher", msg)
                _append_marker(f"file_change: {rel}")
            self._lf.write(SEP_THIN + "\n")
            self._lf.flush()


# ── Marker helpers ────────────────────────────────────────────────────────────

def _append_marker(message: str):
    MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts":  ts_abs(),
        "rel": round(time.time() - _SESSION_START, 2),
        "msg": message,
    }
    with open(MARKER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def insert_marker(message: str, log_file=None, event_file=None):
    global _LAST_MARKER
    _LAST_MARKER = time.time()
    _append_marker(message)
    line = (
        f"\n{SEP_THICK}\n"
        f"  {ts_abs()}  {ICONS['MARK']}  {message}\n"
        f"{SEP_THICK}\n"
    )
    if log_file:
        log_file.write(line)
        log_file.flush()
        record = {"ts": ts_abs(), "rel": round(time.time() - _SESSION_START, 2),
                  "level": "MARK", "scene": "timeline", "msg": message}
        event_file.write(json.dumps(record) + "\n")
        event_file.flush()
    else:
        # Called from CLI mark subcommand — just append to log file
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
            record = {"ts": ts_abs(), "level": "MARK", "scene": "timeline", "msg": message}
            f.write(json.dumps(record) + "\n")
        print(f"Marker inserted: {message}")


# ── Tab watcher ───────────────────────────────────────────────────────────────

class TabWatcher:
    def __init__(self, tab: dict, log_file, event_file, verbose: bool, errors_only: bool):
        self.tab         = tab
        self._lf         = log_file
        self._ef         = event_file
        self.verbose     = verbose
        self.errors_only = errors_only
        self.scene       = scene_for(tab.get("url", ""))
        self._alive      = True

    def emit(self, level: str, msg: str, raw: dict | None = None):
        noisy = is_noise(msg)
        error = is_error(msg) or level in ("ERR", "EXC")
        if self.errors_only and not error and level != "MARK":
            return
        if not self.verbose and noisy and not error:
            return
        write_event(self._lf, self._ef, level, self.scene, msg, raw)

    async def run(self):
        ws_url = f"ws://localhost:{CDP_PORT}/devtools/page/{self.tab['id']}"
        self.emit("SYS", f"Attached to tab: {self.tab.get('url','')[:80]}")
        _id = 0

        async def send(ws, method, params=None):
            nonlocal _id
            _id += 1
            await ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))

        try:
            async with websockets.connect(ws_url, max_size=10_000_000, ping_interval=15) as ws:
                for domain in ("Network", "Console", "Runtime", "Page", "Log"):
                    await send(ws, f"{domain}.enable")
                # drain ACKs
                for _ in range(6):
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=0.3)
                    except asyncio.TimeoutError:
                        break

                while self._alive:
                    try:
                        raw_str = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        self.emit("SYS", "Tab closed / navigated away")
                        return

                    msg    = json.loads(raw_str)
                    method = msg.get("method", "")
                    params = msg.get("params", {})

                    # ── Page navigation ──
                    if method == "Page.frameNavigated":
                        url = params.get("frame", {}).get("url", "")
                        if url and not url.startswith("about:"):
                            self.scene = scene_for(url)
                            self.emit("NAV", f"→ {url[:100]}")

                    # ── Network responses ──
                    elif method == "Network.responseReceived":
                        resp   = params.get("response", {})
                        status = resp.get("status", 0)
                        url    = resp.get("url", "")
                        mime   = resp.get("mimeType", "")
                        if status >= 400:
                            self.emit("ERR", f"HTTP {status}  {url[:100]}")
                        elif self.verbose:
                            self.emit("NET", f"HTTP {status}  {url[:100]}")

                    # ── Network load failures ──
                    elif method == "Network.loadingFailed":
                        err = params.get("errorText", "")
                        url = params.get("documentURL", "")
                        if err and not is_noise(err + url):
                            self.emit("ERR", f"LOAD FAILED  {err}  {url[:80]}")

                    # ── Console messages ──
                    elif method in ("Console.messageAdded",):
                        cmsg  = params.get("message", {})
                        level = cmsg.get("level", "log")
                        text  = cmsg.get("text", "")
                        src   = cmsg.get("url", "").split("/")[-1]
                        line  = cmsg.get("line", "")
                        tag   = {"error": "ERR", "warning": "WARN"}.get(level, "INFO")
                        self.emit(tag, f"[console.{level}]  {text[:150]}  ({src}:{line})")

                    # ── Log entries ──
                    elif method == "Log.entryAdded":
                        entry = params.get("entry", {})
                        level = entry.get("level", "info")
                        text  = entry.get("text", "")
                        src   = entry.get("url", "").split("/")[-1]
                        tag   = {"error": "ERR", "warning": "WARN"}.get(level, "INFO")
                        self.emit(tag, f"[log.{level}]  {text[:150]}  ({src})")

                    # ── JS exceptions ──
                    elif method == "Runtime.exceptionThrown":
                        detail = params.get("exceptionDetails", {})
                        desc   = detail.get("exception", {}).get("description", "")
                        url    = detail.get("url", "").split("/")[-1]
                        line   = detail.get("lineNumber", "")
                        col    = detail.get("columnNumber", "")
                        self.emit("EXC", f"{desc[:150]}  @{url}:{line}:{col}")

                    # ── Runtime console ──
                    elif method == "Runtime.consoleAPICalled":
                        ctype = params.get("type", "log")
                        args  = params.get("args", [])
                        text  = " ".join(
                            str(a.get("value", a.get("description", "")))
                            for a in args
                        )[:150]
                        if ctype in ("error",):
                            self.emit("ERR", f"[console.error]  {text}")
                        elif ctype in ("warn",):
                            self.emit("WARN", f"[console.warn]   {text}")
                        elif self.verbose:
                            self.emit("JS", f"[console.{ctype}]  {text}")

        except Exception as exc:
            self.emit("ERR", f"TabWatcher crashed: {exc}")


# ── Monitor loop ──────────────────────────────────────────────────────────────

async def monitor_loop(verbose: bool, errors_only: bool, port_filter: Optional[int]):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    log_file   = open(LOG_PATH,    "a", encoding="utf-8", buffering=1)
    event_file = open(EVENTS_PATH, "a", encoding="utf-8", buffering=1)

    insert_marker("SESSION START", log_file, event_file)
    log_file.write(f"  Watching: {'all scenes' if not port_filter else f'port {port_filter}'}\n")
    log_file.write(f"  Verbose: {verbose}  Errors-only: {errors_only}\n")
    log_file.write(SEP_THIN + "\n")
    log_file.flush()

    file_watcher = FileWatcher(log_file, event_file)
    watchers: dict[str, asyncio.Task] = {}
    check_interval = 0

    while True:
        # File change check every 2s
        check_interval += 1
        if check_interval % 2 == 0:
            file_watcher.check()

        # Tab discovery every 3s
        try:
            raw  = urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json", timeout=2).read()
            tabs = json.loads(raw)
        except Exception:
            await asyncio.sleep(3)
            continue

        alive_ids = set()
        for tab in tabs:
            if tab.get("type") != "page":
                continue
            if tab["url"].startswith("devtools://"):
                continue
            if port_filter and f":{port_filter}/" not in tab["url"]:
                continue
            tid = tab["id"]
            alive_ids.add(tid)
            if tid not in watchers or watchers[tid].done():
                w    = TabWatcher(tab, log_file, event_file, verbose, errors_only)
                task = asyncio.create_task(w.run())
                watchers[tid] = task

        # Prune gone tabs
        for tid in list(watchers):
            if tid not in alive_ids and watchers[tid].done():
                del watchers[tid]

        await asyncio.sleep(1)


# ── Read commands ─────────────────────────────────────────────────────────────

def cmd_tail(n: int = 60):
    if not LOG_PATH.exists():
        print("No log yet. Start the monitor first.")
        return
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    for line in lines[-n:]:
        print(line)


def cmd_errors(since_last: bool = True):
    if not EVENTS_PATH.exists():
        print("No events log yet.")
        return
    events = [json.loads(l) for l in EVENTS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    if since_last:
        # Find last MARK
        for i in range(len(events) - 1, -1, -1):
            if events[i].get("level") == "MARK":
                events = events[i:]
                print(f"Since marker: {events[0].get('msg','')!r}  ({events[0].get('ts','')})\n")
                break
    errs = [e for e in events if e.get("level") in ("ERR", "EXC", "WARN")]
    if not errs:
        print("No errors since last marker. ✓")
    for e in errs:
        print(f"  {e['ts']}  {e['level']}  [{e['scene']}]  {e['msg']}")


def cmd_timeline():
    if not MARKER_PATH.exists():
        print("No markers yet.")
        return
    if not EVENTS_PATH.exists():
        print("No events yet.")
        return

    markers = [json.loads(l) for l in MARKER_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    events  = [json.loads(l) for l in EVENTS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]

    print(f"\n{SEP_THICK}")
    print("  TIMELINE")
    print(SEP_THICK)

    for i, mark in enumerate(markers):
        ts_start = mark["ts"]
        ts_end   = markers[i + 1]["ts"] if i + 1 < len(markers) else "now"
        # Count events in this window
        window = [e for e in events if ts_start <= e.get("ts", "") < (ts_end if ts_end != "now" else "9")]
        errs   = [e for e in window if e.get("level") in ("ERR", "EXC")]
        warns  = [e for e in window if e.get("level") == "WARN"]
        print(f"\n  ┤ {ts_start}  {mark['msg']}")
        print(f"    Window: {len(window)} events  ✗ {len(errs)} errors  ⚠ {len(warns)} warnings")
        for e in errs[:5]:
            print(f"      ✗  [{e['scene']}]  {e['msg'][:90]}")
        if len(errs) > 5:
            print(f"      … {len(errs) - 5} more errors")

    print(f"\n{SEP_THIN}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="CosySim CDP Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # start
    st = sub.add_parser("start", help="Start the monitor daemon")
    st.add_argument("--port",        type=int,            help="Watch only this scene port")
    st.add_argument("--verbose",     action="store_true", help="Log all events including noise")
    st.add_argument("--errors-only", action="store_true", help="Errors and exceptions only")
    st.add_argument("--follow",      action="store_true", help="Also echo to stdout")

    # mark
    mk = sub.add_parser("mark", help="Insert a timeline marker")
    mk.add_argument("message", nargs="+", help="Marker text")

    # tail
    tl = sub.add_parser("tail", help="Print last N log lines")
    tl.add_argument("n", nargs="?", type=int, default=60)

    # errors
    sub.add_parser("errors", help="Show errors since last marker")

    # timeline
    sub.add_parser("timeline", help="Show timeline with error counts per section")

    args = p.parse_args()

    if args.cmd == "start":
        print(f"CDP Monitor  →  {LOG_PATH}")
        print(f"  Follow log:  Get-Content {LOG_PATH} -Wait -Tail 60")
        print(f"  Errors only: Select-String -Path {LOG_PATH} -Pattern '✗|💥'")
        print(f"  Add marker:  python scripts/cdp_monitor.py mark \"your note here\"")
        print()

        if args.follow:
            # Tee to stdout by opening log in follow mode after starting
            import threading

            def tail():
                import time as _t
                with open(LOG_PATH, "a", encoding="utf-8"):
                    pass  # ensure exists
                with open(LOG_PATH, "r", encoding="utf-8") as f:
                    f.seek(0, 2)  # seek to end
                    while True:
                        line = f.readline()
                        if line:
                            print(line, end="")
                        else:
                            _t.sleep(0.1)

            threading.Thread(target=tail, daemon=True).start()

        try:
            asyncio.run(monitor_loop(
                verbose=args.verbose,
                errors_only=args.errors_only,
                port_filter=args.port,
            ))
        except KeyboardInterrupt:
            print("\nMonitor stopped.")

    elif args.cmd == "mark":
        message = " ".join(args.message)
        insert_marker(message)

    elif args.cmd == "tail":
        cmd_tail(args.n)

    elif args.cmd == "errors":
        cmd_errors(since_last=True)

    elif args.cmd == "timeline":
        cmd_timeline()


if __name__ == "__main__":
    main()
