"""CLI entry point for ARGUS scene debugging.

Quick scene diagnostic from the command line::

    python -m scripts.argus.tools.debug_scene --port 5556
    python -m scripts.argus.tools.debug_scene --port 5556 --watch 30
    python -m scripts.argus.tools.debug_scene --port 5556 --vision
    python -m scripts.argus.tools.debug_scene --port 5556 --eval "document.title"
    python -m scripts.argus.tools.debug_scene --port 5556 --dom "#ph-director-panel"
    python -m scripts.argus.tools.debug_scene --port 5556 --click-test "#btn-send,.side-panel"
    python -m scripts.argus.tools.debug_scene --port 5556 --z-stack
    python -m scripts.argus.tools.debug_scene --port 5556 --perf
    python -m scripts.argus.tools.debug_scene --tabs
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root on path
project_root = str(Path(__file__).resolve().parents[3])
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def cmd_diagnose(args: argparse.Namespace) -> None:
    """Full diagnostic scan."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    print(f"🔍 Connecting to {target}...")

    async with LiveDebugger(target) as dbg:
        await asyncio.sleep(2)
        report = await dbg.diagnose_scene(include_vision=args.vision)
        print(report.summary())

        if args.save:
            import time
            save_dir = Path("data/argus/reports")
            save_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = save_dir / f"diag_{args.port}_{ts}.json"
            data = {
                "url": report.url,
                "title": report.title,
                "timestamp": report.timestamp,
                "console_errors": [str(e) for e in report.console_errors],
                "console_warnings": [str(e) for e in report.console_warnings],
                "network_errors": [str(e) for e in report.network_errors],
                "js_exceptions": [str(e) for e in report.js_exceptions],
                "dom_stats": report.dom_stats,
                "performance": report.performance,
                "scene_health": report.scene_health,
                "vision_analysis": report.vision_analysis,
            }
            path.write_text(json.dumps(data, indent=2, default=str))
            print(f"📄 Report saved: {path}")


async def cmd_watch(args: argparse.Namespace) -> None:
    """Watch mode — monitor for errors over time."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    print(f"👁️ Watching {target} for {args.watch}s...")

    def on_error(msg: str) -> None:
        print(f"  🔴 {msg}")

    def on_net_error(entry: object) -> None:
        print(f"  🌐 {entry}")

    async with LiveDebugger(target) as dbg:
        report = await dbg.watch(
            duration_seconds=args.watch,
            on_error=on_error,
            on_network_error=on_net_error,
        )
        print("\n" + report.summary())


async def cmd_eval(args: argparse.Namespace) -> None:
    """Evaluate JavaScript."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    async with LiveDebugger(target) as dbg:
        result = await dbg.eval_js_safe(args.eval)
        if result["ok"]:
            try:
                formatted = json.dumps(result["value"], indent=2, default=str)
            except (TypeError, ValueError):
                formatted = str(result["value"])
            print(f"Result:\n{formatted}")
        else:
            print(f"Error: {result['error']}")


async def cmd_dom(args: argparse.Namespace) -> None:
    """Inspect a DOM element."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    async with LiveDebugger(target) as dbg:
        info = await dbg.query_selector(args.dom)
        if info:
            print(json.dumps(info, indent=2))
        else:
            print(f"Element not found: {args.dom}")


async def cmd_z_stack(args: argparse.Namespace) -> None:
    """Show z-index stacking order."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    async with LiveDebugger(target) as dbg:
        stack = await dbg.check_z_index_stack()
        if not stack:
            print("No positioned elements with z-index found")
            return
        print("Z-Index Stack (highest first):")
        for el in stack:
            vis = "✅" if el.get("visible") else "❌"
            pe = el.get("pointerEvents", "auto")
            pe_flag = " ⚠️pointer-events:none" if pe == "none" else ""
            ident = el.get("id", "") or el.get("classes", "")
            print(f"  z={el['zIndex']:>5}  {vis} {el['tag']}#{ident}  [{el.get('position')}]{pe_flag}")


async def cmd_click_test(args: argparse.Namespace) -> None:
    """Test click targets."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    selectors = [s.strip() for s in args.click_test.split(",") if s.strip()]

    async with LiveDebugger(target) as dbg:
        results = await dbg.check_click_targets(selectors)
        print("Click Target Report:")
        for sel, info in results.items():
            if not info["exists"]:
                print(f"  ❌ {sel} — NOT FOUND")
            elif info["clickable"]:
                print(f"  ✅ {sel} — clickable (z={info.get('zIndex', '?')})")
            else:
                print(f"  🚫 {sel} — BLOCKED: {info['reason']}")


async def cmd_perf(args: argparse.Namespace) -> None:
    """Show performance metrics."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    async with LiveDebugger(target) as dbg:
        mem = await dbg.get_memory_info()
        fps = await dbg.get_fps_estimate(1000)

        print("Performance:")
        print(f"  FPS: {fps}")
        if mem:
            for k, v in mem.items():
                print(f"  {k}: {v}")


async def cmd_screenshot(args: argparse.Namespace) -> None:
    """Take a screenshot with optional vision analysis."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    async with LiveDebugger(target) as dbg:
        path = await dbg.take_screenshot()
        print(f"📸 Screenshot saved: {path}")

        if args.vision:
            print("🧠 Analyzing with vision model...")
            analysis = await dbg.vision_analyze()
            print(f"\n{analysis}")


def cmd_tabs() -> None:
    """List available Chrome tabs."""
    from scripts.argus.live_debugger import LiveDebugger

    tabs = LiveDebugger.list_tabs()
    if not tabs:
        print("No Chrome tabs found. Is Chrome running with --remote-debugging-port=9223?")
        return
    print("Open Chrome tabs:")
    for i, tab in enumerate(tabs):
        print(f"  {i+1}. {tab['title'][:60]} — {tab['url'][:100]}")


async def cmd_console(args: argparse.Namespace) -> None:
    """Stream console logs."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    seconds = args.console_listen or 10
    print(f"📡 Listening to console on {target} for {seconds}s...")

    async with LiveDebugger(target) as dbg:
        await asyncio.sleep(seconds)
        logs = dbg.get_console_logs(limit=100)
        if not logs:
            print("  (no console output captured)")
        else:
            for entry in logs:
                print(f"  {entry}")


async def cmd_health(args: argparse.Namespace) -> None:
    """Scene health check."""
    from scripts.argus.live_debugger import LiveDebugger

    target = f"localhost:{args.port}"
    async with LiveDebugger(target) as dbg:
        health = await dbg.check_scene_health()
        print("Scene Health Check:")
        for check, passed in health.items():
            icon = "✅" if passed else "❌"
            print(f"  {icon} {check}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARGUS Scene Debugger — Real-time CDP diagnostics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.argus.tools.debug_scene --port 5556
  python -m scripts.argus.tools.debug_scene --port 5556 --watch 30
  python -m scripts.argus.tools.debug_scene --port 5556 --vision
  python -m scripts.argus.tools.debug_scene --port 5556 --eval "document.title"
  python -m scripts.argus.tools.debug_scene --port 5556 --dom "#my-panel"
  python -m scripts.argus.tools.debug_scene --port 5556 --z-stack
  python -m scripts.argus.tools.debug_scene --port 5556 --click-test "#btn,.panel"
  python -m scripts.argus.tools.debug_scene --port 5556 --perf
  python -m scripts.argus.tools.debug_scene --port 5556 --health
  python -m scripts.argus.tools.debug_scene --tabs
        """,
    )

    parser.add_argument("--port", type=int, default=5556, help="Scene port (default: 5556)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--save", action="store_true", help="Save report to data/argus/reports/")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--watch", type=int, metavar="SECONDS", help="Watch mode — monitor for N seconds")
    group.add_argument("--eval", type=str, metavar="JS", help="Evaluate JavaScript expression")
    group.add_argument("--dom", type=str, metavar="SELECTOR", help="Inspect a DOM element")
    group.add_argument("--z-stack", action="store_true", help="Show z-index stacking order")
    group.add_argument("--click-test", type=str, metavar="SELECTORS", help="Test click targets (comma-separated)")
    group.add_argument("--perf", action="store_true", help="Show performance metrics")
    group.add_argument("--tabs", action="store_true", help="List available Chrome tabs")
    group.add_argument("--console-listen", type=int, metavar="SECONDS", help="Stream console logs for N seconds")
    group.add_argument("--health", action="store_true", help="Quick scene health check")
    group.add_argument("--screenshot", action="store_true", help="Take a screenshot")

    parser.add_argument("--vision", action="store_true", help="Include vision model analysis (with --screenshot or default diagnostic)")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.tabs:
        cmd_tabs()
        return

    if args.watch:
        asyncio.run(cmd_watch(args))
    elif args.eval:
        asyncio.run(cmd_eval(args))
    elif args.dom:
        asyncio.run(cmd_dom(args))
    elif args.z_stack:
        asyncio.run(cmd_z_stack(args))
    elif args.click_test:
        asyncio.run(cmd_click_test(args))
    elif args.perf:
        asyncio.run(cmd_perf(args))
    elif args.console_listen:
        asyncio.run(cmd_console(args))
    elif args.health:
        asyncio.run(cmd_health(args))
    elif args.screenshot:
        asyncio.run(cmd_screenshot(args))
    else:
        asyncio.run(cmd_diagnose(args))


if __name__ == "__main__":
    main()
