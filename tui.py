#!/usr/bin/env python3
"""CosySim TUI — Interactive terminal launcher and system dashboard.

Usage:
    python tui.py                   # full TUI
    python tui.py --no-autostart    # open TUI without auto-launching

Keyboard shortcuts:
    Space / Enter  — launch selected target
    S              — stop selected target  (kills thread; port goes down)
    A              — launch all auto-start targets
    O              — open selected in browser
    I              — HAR import wizard
    R              — refresh all port statuses
    Q / Ctrl+C     — quit (stops launched subprocesses)
"""
from __future__ import annotations

import importlib
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# ── Import launcher catalogue without executing main() ─────────────────────
from launcher import SERVICES, SCENES, ALL_TARGETS, VERSION, _port_up  # noqa: E402

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    DataTable, Footer, Header, Label, ListItem, ListView,
    Log, ProgressBar, RichLog, Rule, Static, TabbedContent, TabPane,
)
from textual.timer import Timer

# ── External services checked in the panel ─────────────────────────────────
EXTERNAL_SERVICES = [
    ("LMStudio",     1234, "http://localhost:1234/v1/models"),
    ("Nexus KMS",    8700, "http://localhost:8700/api/health"),
    ("ComfyUI",      8188, "http://localhost:8188"),
    ("TTS Server",   8600, "http://localhost:8600/health"),
    ("NLM Proxy",    8800, "http://localhost:8800/health"),
    ("Nexus Canvas", 5590, "http://localhost:5590"),
]

# ── Colour scheme ───────────────────────────────────────────────────────────
TUI_CSS = """
Screen {
    background: #0a0a0f;
    color: #e2e8f0;
}

Header {
    background: #1e1b4b;
    color: #a5b4fc;
    text-style: bold;
    height: 3;
}

Footer {
    background: #1e1b4b;
    color: #6366f1;
    height: 1;
}

#left-panel {
    width: 38;
    background: #0f0f1a;
    border-right: tall #1e293b;
}

#center-panel {
    background: #0a0a0f;
}

#right-panel {
    width: 36;
    background: #0f0f1a;
    border-left: tall #1e293b;
}

.panel-title {
    background: #1e1b4b;
    color: #818cf8;
    text-style: bold;
    padding: 0 1;
    height: 1;
}

.section-title {
    color: #475569;
    text-style: bold;
    padding: 0 1;
    height: 1;
}

TargetRow {
    height: 1;
    padding: 0 1;
}

TargetRow:hover {
    background: #1e293b;
}

TargetRow.-selected {
    background: #312e81;
    color: #e2e8f0;
}

TargetRow.-running {
    color: #34d399;
}

TargetRow.-stopped {
    color: #64748b;
}

TargetRow.-autostart {
    color: #a5b4fc;
}

ServiceStatus {
    height: 1;
    padding: 0 1;
}

.status-up {
    color: #34d399;
}

.status-down {
    color: #ef4444;
}

#log-panel {
    border: tall #1e293b;
    margin: 0 1;
    height: 1fr;
}

#account-list {
    height: 1fr;
    padding: 0 1;
}

.account-row {
    height: 1;
    padding: 0 1;
    color: #94a3b8;
}

#details-bar {
    height: 3;
    background: #111827;
    border-top: tall #1e293b;
    padding: 0 1;
    color: #94a3b8;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 0;
}
"""


# ── Target row widget ───────────────────────────────────────────────────────

class TargetRow(Static):
    """One row per scene/service in the left panel."""

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "selected", "running", "stopped", "autostart",
    }

    def __init__(self, name: str, info: Dict[str, Any], group: str) -> None:
        super().__init__()
        self.target_name = name
        self.info = info
        self.group = group
        self._is_up = False
        self._selected = False

    def render_row(self) -> str:
        icon = "●" if self._is_up else "○"
        auto = "★" if self.info.get("auto_start") else " "
        label = self.info["label"][:20]
        port = self.info["port"]
        return f" {icon} {auto} {label:<20} :{port}"

    def render(self) -> str:
        return self.render_row()

    def refresh_status(self) -> None:
        self._is_up = _port_up(self.info["port"])
        if self._is_up:
            self.remove_class("-stopped")
            self.add_class("-running")
        else:
            self.remove_class("-running")
            self.add_class("-stopped")
        self.refresh()

    def select(self) -> None:
        self._selected = True
        self.add_class("-selected")

    def deselect(self) -> None:
        self._selected = False
        self.remove_class("-selected")


# ── Main TUI App ────────────────────────────────────────────────────────────

class CosySimTUI(App[None]):
    """CosySim interactive TUI launcher."""

    TITLE = f"CosySim v{VERSION} — NEXUS CONTROL"
    SUB_TITLE = "Terminal Launcher & System Dashboard"
    CSS = TUI_CSS

    BINDINGS = [
        Binding("space",   "launch_selected",   "Launch",       show=True),
        Binding("s",       "stop_selected",     "Stop",         show=True),
        Binding("a",       "launch_autostart",  "Auto-start",   show=True),
        Binding("o",       "open_browser",      "Open",         show=True),
        Binding("r",       "refresh_status",    "Refresh",      show=True),
        Binding("i",       "import_har",        "Import HAR",   show=True),
        Binding("up",      "cursor_up",         "Up",           show=False),
        Binding("down",    "cursor_down",        "Down",         show=False),
        Binding("q",       "quit",              "Quit",         show=True),
    ]

    selected_index: reactive[int] = reactive(0)

    def __init__(self, autostart: bool = False) -> None:
        super().__init__()
        self._autostart = autostart
        self._rows: List[TargetRow] = []
        self._launched_threads: Dict[str, threading.Thread] = {}
        self._launched_procs: Dict[str, subprocess.Popen] = {}
        self._refresh_timer: Optional[Timer] = None
        self._log_lines: List[str] = []

    # ── Layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal():
            # Left panel — target list
            with Vertical(id="left-panel"):
                yield Static("  SERVICES", classes="section-title")
                for name, info in SERVICES.items():
                    row = TargetRow(name, info, "service")
                    self._rows.append(row)
                    yield row
                yield Rule()
                yield Static("  SCENES", classes="section-title")
                for name, info in SCENES.items():
                    row = TargetRow(name, info, "scene")
                    self._rows.append(row)
                    yield row

            # Center panel — tabbed content
            with Vertical(id="center-panel"):
                with TabbedContent():
                    with TabPane("📋 Log", id="tab-log"):
                        yield RichLog(id="log-panel", highlight=True, markup=True,
                                      wrap=True, auto_scroll=True)
                    with TabPane("🌐 Services", id="tab-services"):
                        yield self._build_services_pane()
                    with TabPane("🔑 Accounts", id="tab-accounts"):
                        yield self._build_accounts_pane()

                yield Static(id="details-bar")

            # Right panel — external services
            with Vertical(id="right-panel"):
                yield Static("  EXTERNAL SERVICES", classes="panel-title")
                for label, port, url in EXTERNAL_SERVICES:
                    yield self._ext_row(label, port, url)
                yield Rule()
                yield Static("  QUICK STATS", classes="panel-title")
                yield Static(id="stats-label", classes="account-row")

        yield Footer()

    def _ext_row(self, label: str, port: int, url: str) -> Static:
        up = _port_up(port)
        icon = "[green]●[/]" if up else "[red]○[/]"
        return Static(
            f" {icon} [bold]{label}[/] [dim]:{port}[/]",
            id=f"ext-{port}",
            classes="ServiceStatus",
        )

    def _build_services_pane(self) -> Widget:
        with Vertical() as v:
            table = DataTable(id="svc-table")
            table.add_columns("Name", "Port", "Status", "Label")
            for name, info in {**SERVICES, **SCENES}.items():
                up = _port_up(info["port"])
                table.add_row(
                    name,
                    str(info["port"]),
                    "[green]UP[/]" if up else "[red]down[/]",
                    info["label"],
                )
        return v  # type: ignore[return-value]

    def _build_accounts_pane(self) -> Widget:
        with ScrollableContainer(id="account-list") as sc:
            har_root = PROJECT_ROOT / "data" / "har_files"
            accounts_dir = PROJECT_ROOT / "data" / "google_accounts"
            account_names: List[str] = []

            # Discover accounts from har_files folder structure
            if har_root.exists():
                for d in sorted(har_root.iterdir()):
                    if d.is_dir() and not d.name.startswith("."):
                        account_names.append(d.name)

            if not account_names:
                yield Static(" No accounts found. Press [bold]I[/] to import a HAR.", classes="account-row")
            else:
                for acct in account_names:
                    acct_dir = accounts_dir / acct / "cookies.json"
                    has_cookies = acct_dir.exists()
                    icon = "[green]✓[/]" if has_cookies else "[yellow]○[/]"
                    har_count = 0
                    har_dir = har_root / acct
                    if har_dir.exists():
                        har_count = len(list(har_dir.glob("*.har")))
                    yield Static(
                        f" {icon} [bold]{acct}[/] [dim]({har_count} HARs)[/]",
                        classes="account-row",
                    )
        return sc  # type: ignore[return-value]

    # ── On mount ──────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._select(0)
        self._refresh_all_status()
        self._update_stats()
        self._refresh_timer = self.set_interval(8, self._refresh_all_status)
        self._log("CosySim TUI started. [dim]Space[/]=launch [dim]A[/]=autostart [dim]Q[/]=quit")
        if self._autostart:
            self.call_after_refresh(self.action_launch_autostart)

    # ── Status refresh ────────────────────────────────────────────────────

    def _refresh_all_status(self) -> None:
        for row in self._rows:
            row.refresh_status()
        # Refresh external service indicators
        for label, port, _ in EXTERNAL_SERVICES:
            try:
                widget = self.query_one(f"#ext-{port}", Static)
                up = _port_up(port)
                icon = "[green]●[/]" if up else "[red]○[/]"
                widget.update(f" {icon} [bold]{label}[/] [dim]:{port}[/]")
            except NoMatches:
                pass
        self._update_stats()

    def _update_stats(self) -> None:
        try:
            widget = self.query_one("#stats-label", Static)
            up_scenes = sum(1 for r in self._rows if r.group == "scene" and r._is_up)
            up_svcs = sum(1 for r in self._rows if r.group == "service" and r._is_up)
            total_scenes = sum(1 for r in self._rows if r.group == "scene")
            total_svcs = sum(1 for r in self._rows if r.group == "service")
            widget.update(
                f" [green]{up_svcs}[/][dim]/{total_svcs}[/] services  "
                f"[green]{up_scenes}[/][dim]/{total_scenes}[/] scenes"
            )
        except NoMatches:
            pass

    # ── Selection navigation ──────────────────────────────────────────────

    def _select(self, index: int) -> None:
        if not self._rows:
            return
        index = max(0, min(index, len(self._rows) - 1))
        for i, row in enumerate(self._rows):
            if i == index:
                row.select()
            else:
                row.deselect()
        self.selected_index = index
        self._update_details()

    def _update_details(self) -> None:
        try:
            bar = self.query_one("#details-bar", Static)
        except NoMatches:
            return
        if not self._rows:
            return
        row = self._rows[self.selected_index]
        info = row.info
        up = row._is_up
        status = "[green]● UP[/]" if up else "[red]○ DOWN[/]"
        auto = "[yellow]★ auto-start[/]" if info.get("auto_start") else ""
        bar.update(
            f" {status}  [bold]{info['label']}[/]  [dim]:{info['port']}[/]  {auto}\n"
            f" [dim]http://localhost:{info['port']}[/]"
        )

    def action_cursor_up(self) -> None:
        self._select(self.selected_index - 1)

    def action_cursor_down(self) -> None:
        self._select(self.selected_index + 1)

    # ── Launch / Stop ─────────────────────────────────────────────────────

    def action_launch_selected(self) -> None:
        if not self._rows:
            return
        row = self._rows[self.selected_index]
        self._launch_target(row.target_name, row.info)

    def action_launch_autostart(self) -> None:
        self._log("[bold cyan]Launching all auto-start targets...[/]")
        for name, info in ALL_TARGETS.items():
            if info.get("auto_start"):
                self._launch_target(name, info)
                time.sleep(0.3)

    @work(thread=True)
    def _launch_target(self, name: str, info: Dict[str, Any]) -> None:
        if _port_up(info["port"]):
            self.call_from_thread(
                self._log, f"[yellow]{info['label']}[/] already running on :{info['port']}"
            )
            return

        self.call_from_thread(
            self._log, f"[cyan]Starting[/] [bold]{info['label']}[/] → :{info['port']}"
        )

        try:
            t = info["type"]
            if t == "flask":
                mod, cls = info["cls"].rsplit(".", 1)
                scene_cls = getattr(importlib.import_module(mod), cls)
                thread = threading.Thread(
                    target=scene_cls().start,
                    daemon=True,
                    name=f"cosysim-{name}",
                )
                thread.start()
                self._launched_threads[name] = thread

            elif t == "streamlit":
                script = PROJECT_ROOT / info["script"]
                proc = subprocess.Popen(
                    [sys.executable, "-m", "streamlit", "run", str(script),
                     f"--server.port={info['port']}",
                     "--server.headless=true",
                     "--server.address=0.0.0.0",
                     "--browser.gatherUsageStats=false",
                     "--logger.level=warning"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._launched_procs[name] = proc

            elif t == "fastapi":
                import uvicorn  # type: ignore
                mod, fn = info["factory"].rsplit(".", 1)
                factory = getattr(importlib.import_module(mod), fn)
                thread = threading.Thread(
                    target=uvicorn.run,
                    args=(factory(),),
                    kwargs={"host": "0.0.0.0", "port": info["port"], "log_level": "warning"},
                    daemon=True,
                    name=f"cosysim-{name}",
                )
                thread.start()
                self._launched_threads[name] = thread

        except Exception as exc:
            self.call_from_thread(
                self._log, f"[red]✗[/] {info['label']}: {exc}"
            )
            return

        # Wait and confirm
        time.sleep(3)
        up = _port_up(info["port"])
        if up:
            self.call_from_thread(
                self._log, f"[green]✓[/] [bold]{info['label']}[/] [dim]:{info['port']}[/]"
            )
        else:
            self.call_from_thread(
                self._log, f"[yellow]⚠[/] {info['label']} started but port not responding yet"
            )
        self.call_from_thread(self._refresh_all_status)

    def action_stop_selected(self) -> None:
        if not self._rows:
            return
        row = self._rows[self.selected_index]
        name = row.target_name
        info = row.info

        stopped = False
        if name in self._launched_procs:
            try:
                self._launched_procs[name].terminate()
                del self._launched_procs[name]
                stopped = True
            except Exception:
                pass

        if stopped:
            self._log(f"[red]◼[/] Stopped [bold]{info['label']}[/]")
        else:
            self._log(f"[yellow]⚠[/] Cannot stop [bold]{info['label']}[/] — not a subprocess target")

        self._refresh_all_status()

    # ── Browser ───────────────────────────────────────────────────────────

    def action_open_browser(self) -> None:
        if not self._rows:
            return
        row = self._rows[self.selected_index]
        url = f"http://localhost:{row.info['port']}"
        self._log(f"[dim]Opening[/] {url}")
        webbrowser.open(url)

    # ── HAR Import ────────────────────────────────────────────────────────

    def action_import_har(self) -> None:
        self._log("[cyan]HAR import:[/] scanning data/har_files/ for new account HARs...")
        self._run_har_import()

    @work(thread=True)
    def _run_har_import(self) -> None:
        har_root = PROJECT_ROOT / "data" / "har_files"
        if not har_root.exists():
            self.call_from_thread(self._log, "[red]data/har_files/ not found[/]")
            return

        try:
            from engine.nexus.google_account_manager import GoogleAccountManager
            manager = GoogleAccountManager()
        except Exception as exc:
            self.call_from_thread(self._log, f"[red]AccountManager unavailable: {exc}[/]")
            return

        imported = 0
        for account_dir in sorted(har_root.iterdir()):
            if not account_dir.is_dir():
                continue
            account_id = account_dir.name
            # Skip top-level legacy folders
            if account_id in ("aistudio", "notebooklm", "cosysim"):
                continue
            for har_file in sorted(account_dir.glob("*.har")):
                service = "google"
                if "aistudio" in har_file.name:
                    service = "aistudio"
                elif "notebooklm" in har_file.name:
                    service = "notebooklm"
                elif "drive" in har_file.name:
                    service = "drive"
                try:
                    ok = manager.import_from_har(str(har_file), account_id, service)
                    icon = "[green]✓[/]" if ok else "[yellow]○[/]"
                    self.call_from_thread(
                        self._log,
                        f" {icon} [dim]{account_id}[/] ← {har_file.name}"
                    )
                    if ok:
                        imported += 1
                except Exception as exc:
                    self.call_from_thread(
                        self._log,
                        f" [red]✗[/] {har_file.name}: {exc}"
                    )

        self.call_from_thread(
            self._log,
            f"[green bold]HAR import complete.[/] {imported} file(s) imported."
        )

    # ── Refresh ───────────────────────────────────────────────────────────

    def action_refresh_status(self) -> None:
        self._refresh_all_status()
        self._log("[dim]Status refreshed[/]")

    # ── Logging ───────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        try:
            log = self.query_one("#log-panel", RichLog)
            log.write(f"[dim]{ts}[/]  {msg}")
        except NoMatches:
            pass

    # ── Cleanup on quit ───────────────────────────────────────────────────

    def on_unmount(self) -> None:
        for proc in self._launched_procs.values():
            try:
                proc.terminate()
            except Exception:
                pass


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="CosySim TUI Launcher")
    parser.add_argument("--autostart", action="store_true",
                        help="Auto-launch all auto_start targets on open")
    args = parser.parse_args()
    app = CosySimTUI(autostart=args.autostart)
    app.run()


if __name__ == "__main__":
    main()
