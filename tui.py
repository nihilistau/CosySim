#!/usr/bin/env python3
"""
CosySim TUI
===========

Interactive terminal launcher and system dashboard built on Textual.  Provides
a three-panel interface (target list, details/logs, external services health)
with real-time port monitoring, HAR import wizard, and priority-sorted autostart.

Usage:
    python tui.py                   # full TUI
    python tui.py --no-autostart    # open TUI without auto-launching

Keyboard shortcuts:
    Space / Enter  — launch selected target
    S              — stop selected target  (kills thread; port goes down)
    A              — launch all auto-start targets
    O              — open selected in browser
    C              — open Nexus Canvas in browser
    I              — HAR import wizard (scans all HAR directories)
    R              — refresh all port statuses
    H              — show system health summary
    L              — show log panel
    Q / Ctrl+C     — quit (stops launched subprocesses)

Version: v1.49.1 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.1 [2026-03-22] — Version stamp sync, HAR_REAL_ROOT via env var
    v1.42.1 [2026-03-21] — External type handler in _start_one, priority-sorted
                            autostart via start_priority field
    v1.42.0 [2026-03-21] — Three-pillar architecture (game/service/creation)
    v1.41.0 [2026-03-20] — ARGUS Deep Polish, HAR import wizard
"""
from __future__ import annotations

import importlib
import json as _json_mod
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

from launcher import SERVICES, SCENES, ALL_TARGETS, VERSION, _port_up  # noqa: E402
from engine.control_plane_registry import PILLAR_IDS  # noqa: E402
from engine.port_registry import TUI_EXTERNAL_TARGETS, build_target_listing  # noqa: E402

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

# ──── HAR Directory Roots ─────────────────────────────────────────────────
# v1.49.1 [2026-03-22] — Use env var instead of hardcoded Windows path
HAR_REAL_ROOT = Path(os.environ.get("COSYSIM_HAR_ROOT", r"C:\Files\Models\HAR_Files"))
HAR_LOCAL_ROOT = PROJECT_ROOT / "data" / "har_files"
ACCOUNTS_COOKIES_DIR = PROJECT_ROOT / "data" / "accounts"    # {acct}_cookies.json
ACCOUNTS_LEGACY_DIR = PROJECT_ROOT / "data" / "google_accounts"  # {acct}/cookies.json

# ──── External Services (Health Panel) ────────────────────────────────────
EXTERNAL_SERVICES = [
    (target["label"], target["port"], target["health_url"])
    for target in build_target_listing(TUI_EXTERNAL_TARGETS)
] + [("GitHub Copilot", 0, "")]

# ──── Colour Scheme ───────────────────────────────────────────────────────
# v1.52.0 [2026-03-22] — Cyberpunk TUI theme: deeper void, cyan/magenta accents,
#                         neon borders, color-coded pillar sections
TUI_CSS = """
Screen {
    background: #050710;
    color: #c0c8d8;
}

Header {
    background: #0a0e18;
    color: #06b6d4;
    text-style: bold;
    height: 3;
}

Footer {
    background: #0a0e18;
    color: #4a5568;
    height: 1;
}

#left-panel {
    width: 42;
    background: #080a12;
    border-right: tall #162032;
    overflow-y: auto;
}

#center-panel {
    background: #050710;
}

#right-panel {
    width: 36;
    background: #080a12;
    border-left: tall #162032;
}

.panel-title {
    background: #0a1628;
    color: #06b6d4;
    text-style: bold;
    padding: 0 1;
    height: 1;
}

.section-title {
    color: #a855f7;
    text-style: bold;
    padding: 0 1;
    height: 1;
}

TargetRow {
    height: 1;
    padding: 0 1;
}

TargetRow:hover {
    background: #0f1724;
}

TargetRow.-selected {
    background: #0c1a2e;
    color: #06b6d4;
    text-style: bold;
}

TargetRow.-running {
    color: #22c55e;
}

TargetRow.-stopped {
    color: #4a5568;
}

TargetRow.-autostart {
    color: #a855f7;
}

ServiceStatus {
    height: 1;
    padding: 0 1;
}

.status-up {
    color: #22c55e;
}

.status-down {
    color: #ef4444;
}

#log-panel {
    border: tall #162032;
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
    color: #64748b;
}

#details-bar {
    height: 3;
    background: #080a12;
    border-top: tall #162032;
    padding: 0 1;
    color: #64748b;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 0;
}

Rule {
    color: #162032;
}

DataTable {
    background: #050710;
}

DataTable > .datatable--header {
    background: #0a0e18;
    color: #06b6d4;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #0c1a2e;
    color: #06b6d4;
}
"""


# ──── Target Row Widget ───────────────────────────────────────────────────

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
        # v1.52.0 — Enhanced status indicators with color hints
        icon = "[green]●[/]" if self._is_up else "[dim]○[/]"
        auto = "[magenta]★[/]" if self.info.get("auto_start") else " "
        label = self.info["label"][:20]
        port = self.info["port"]
        port_str = f"[dim]:{port}[/]"
        return f" {icon} {auto} {label:<20} {port_str}"

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


# ──── Main TUI App ────────────────────────────────────────────────────────

class CosySimTUI(App[None]):
    """CosySim interactive TUI launcher."""

    TITLE = f"CosySim v{VERSION} — NEXUS CONTROL"
    SUB_TITLE = "Terminal Launcher & System Dashboard"
    CSS = TUI_CSS

    BINDINGS = [
        Binding("space",   "launch_selected",   "Launch",       show=True,  priority=True),
        Binding("enter",   "launch_selected",   "Launch",       show=False, priority=True),
        Binding("s",       "stop_selected",     "Stop",         show=True,  priority=True),
        Binding("a",       "launch_autostart",  "Auto-start",   show=True,  priority=True),
        Binding("o",       "open_browser",      "Open",         show=True,  priority=True),
        Binding("c",       "open_canvas",       "Canvas",       show=True,  priority=True),
        Binding("h",       "show_health",       "Health",       show=True,  priority=True),
        Binding("l",       "show_log",          "Log",          show=True,  priority=True),
        Binding("r",       "refresh_status",    "Refresh",      show=True,  priority=True),
        Binding("g",       "launch_game",       "Game",         show=True,  priority=True),
        Binding("v",       "launch_services",   "Services",     show=False, priority=True),
        Binding("k",       "launch_creation",   "Creation",     show=False, priority=True),
        Binding("i",       "import_har",        "Import HAR",   show=False, priority=True),
        Binding("up",      "cursor_up",         "Up",           show=False, priority=True),
        Binding("down",    "cursor_down",       "Down",         show=False, priority=True),
        Binding("q",       "quit",              "Quit",         show=True,  priority=True),
    ]

    selected_index: reactive[int] = reactive(0)

    def __init__(self, autostart: bool = True, pillar_filter: str | None = None) -> None:
        super().__init__()
        self._autostart = autostart
        self._pillar_filter = pillar_filter  # v1.50.0 — optional pillar filter
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
                # Three pillar sections (filtered if --pillar is set)
                # v1.50.0 [2026-03-22] — Pillar filter support
                all_pillars = [
                    ("  NEONCITY", "game"),
                    ("  SERVICES", "service"),
                    ("  CREATION KIT", "creation"),
                ]
                pillar_sections = (
                    [(l, p) for l, p in all_pillars if p == self._pillar_filter]
                    if self._pillar_filter else all_pillars
                )
                for idx, (section_label, pillar) in enumerate(pillar_sections):
                    if idx > 0:
                        yield Rule()
                    yield Static(section_label, classes="section-title")
                    for tid in PILLAR_IDS.get(pillar, ()):
                        info = ALL_TARGETS.get(tid)
                        if not info:
                            continue
                        group = "service" if tid in SERVICES else "scene"
                        row = TargetRow(tid, info, group)
                        self._rows.append(row)
                        yield row

            # Center panel — tabbed content
            with Vertical(id="center-panel"):
                with TabbedContent():
                    with TabPane("🌐 Services", id="tab-services"):
                        yield self._build_services_table()
                    with TabPane("📋 Log", id="tab-log"):
                        yield RichLog(id="log-panel", highlight=True, markup=True,
                                      wrap=True, auto_scroll=True)
                    with TabPane("🔑 Accounts", id="tab-accounts"):
                        with ScrollableContainer(id="account-list"):
                            yield from self._accounts_widgets()
                    with TabPane("📡 HAR Files", id="tab-har"):
                        with ScrollableContainer(id="har-list"):
                            yield from self._har_widgets()

                yield Static(id="details-bar")

            # Right panel — external services + system health
            with Vertical(id="right-panel"):
                yield Static(
                    f"  [bold]CosySim[/] [cyan]v{VERSION}[/]",
                    classes="panel-title",
                )
                yield Rule()
                yield Static("  EXTERNAL SERVICES", classes="section-title")
                for label, port, url in EXTERNAL_SERVICES:
                    yield self._ext_row(label, port, url)
                yield Rule()
                yield Static("  SYSTEM HEALTH", classes="section-title")
                yield Static(id="nexus-health", classes="account-row")
                yield Static(id="lmstudio-health", classes="account-row")
                yield Static(id="lmstudio-model", classes="account-row")
                yield Rule()
                yield Static("  QUICK STATS", classes="section-title")
                yield Static(id="stats-label", classes="account-row")

        yield Footer()

    def _ext_row(self, label: str, port: int, url: str) -> Static:
        if port == 0:
            # Token-based service — check for ANY account cookies file
            ok = any(ACCOUNTS_COOKIES_DIR.glob("*_cookies.json")) if ACCOUNTS_COOKIES_DIR.exists() else False
            icon = "[green]●[/]" if ok else "[yellow]○[/]"
            suffix = "[dim](cookie)[/]"
            return Static(
                f" {icon} [bold]{label}[/] {suffix}",
                id=f"ext-copilot",
                classes="ServiceStatus",
            )
        up = _port_up(port)
        icon = "[green]●[/]" if up else "[red]○[/]"
        return Static(
            f" {icon} [bold]{label}[/] [dim]:{port}[/]",
            id=f"ext-{port}",
            classes="ServiceStatus",
        )

    def _build_services_table(self) -> DataTable:
        """Return a DataTable of all services/scenes (status populated async)."""
        table = DataTable(id="svc-table")
        table.add_columns("Name", "Port", "Status", "Label")
        for name, info in {**SERVICES, **SCENES}.items():
            table.add_row(
                name,
                str(info["port"]),
                "[dim]…[/]",  # filled in by first background refresh
                info["label"],
            )
        return table

    def _accounts_widgets(self):
        """Yield account row widgets for the Accounts tab."""
        account_names: List[str] = []

        for har_root in (HAR_REAL_ROOT, HAR_LOCAL_ROOT):
            if har_root.exists():
                for d in sorted(har_root.iterdir()):
                    if d.is_dir() and not d.name.startswith(".") and d.name not in account_names:
                        account_names.append(d.name)

        if ACCOUNTS_COOKIES_DIR.exists():
            for f in sorted(ACCOUNTS_COOKIES_DIR.glob("*_cookies.json")):
                acct = f.stem.removesuffix("_cookies")
                if acct not in account_names:
                    account_names.append(acct)

        if not account_names:
            yield Static(
                " No accounts found. Press [bold]I[/] to import a HAR.",
                classes="account-row",
            )
            return

        for acct in account_names:
            new_cookies = ACCOUNTS_COOKIES_DIR / f"{acct}_cookies.json"
            legacy_cookies = ACCOUNTS_LEGACY_DIR / acct / "cookies.json"
            has_cookies = new_cookies.exists() or legacy_cookies.exists()
            icon = "[green]✓[/]" if has_cookies else "[yellow]○[/]"

            har_count = 0
            for har_root in (HAR_REAL_ROOT, HAR_LOCAL_ROOT):
                har_dir = har_root / acct
                if har_dir.exists():
                    har_count += sum(1 for _ in har_dir.glob("*.har"))

            services: List[str] = []
            if new_cookies.exists():
                try:
                    import json as _json
                    data = _json.loads(new_cookies.read_text(encoding="utf-8"))
                    if any("github" in k for k in data):
                        services.append("github")
                    if any("google" in k for k in data):
                        services.append("google")
                except Exception:
                    pass

            svc_label = (" [dim]" + ",".join(services) + "[/]") if services else ""
            yield Static(
                f" {icon} [bold]{acct}[/]{svc_label} [dim]({har_count} HARs)[/]",
                classes="account-row",
            )

    def _har_widgets(self):
        """Yield HAR file list widgets for the HAR Files tab."""
        all_files: Dict[str, List[Path]] = {}

        for har_root in (HAR_REAL_ROOT, HAR_LOCAL_ROOT):
            if not har_root.exists():
                continue
            for d in sorted(har_root.iterdir()):
                if not d.is_dir() or d.name.startswith("."):
                    continue
                hars = sorted(d.glob("*.har"))
                if hars:
                    all_files.setdefault(d.name, []).extend(hars)

        if not all_files:
            yield Static(
                " No HAR files found. Capture via Canvas browser or press I to import.",
                classes="account-row",
            )
            return

        total = sum(len(v) for v in all_files.values())
        yield Static(
            f" [bold cyan]{total} HAR files[/] across [bold]{len(all_files)}[/] accounts"
            f"  [dim]Press I to import[/]",
            classes="account-row",
        )
        yield Static("", classes="account-row")
        for acct, files in sorted(all_files.items()):
            total_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)
            yield Static(
                f" [bold]{acct}[/] [dim]({len(files)} files · {total_mb:.1f} MB)[/]",
                classes="account-row",
            )
            for f in files:
                size_mb = f.stat().st_size / (1024 * 1024)
                yield Static(
                    f"   [dim]└ {f.name}  ({size_mb:.1f} MB)[/]",
                    classes="account-row",
                )

    # ── On mount ──────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        # v1.50.0 [2026-03-22] — Set subtitle based on pillar filter
        if self._pillar_filter:
            pillar_labels = {"game": "Game Scenes", "service": "System Services", "creation": "Creation Kit"}
            self.sub_title = pillar_labels.get(self._pillar_filter, self._pillar_filter.title())
        self._select(0)
        self._do_refresh()
        self._refresh_timer = self.set_interval(10, self._do_refresh)
        total = len(self._rows)
        scenes = sum(1 for r in self._rows if r.group == "scene")
        svcs = sum(1 for r in self._rows if r.group == "service")
        self._log(
            f"[bold cyan]CosySim v{VERSION}[/] ready — "
            f"[dim]{scenes} scenes · {svcs} services · {total} targets[/]"
        )
        self._log(
            "[dim]Keys:[/] [bold]↑↓[/]=nav  [bold]Space[/]=launch  "
            "[bold]A[/]=autostart  [bold]S[/]=stop  [bold]O[/]=open  "
            "[bold]C[/]=canvas  [bold]H[/]=health  [bold]R[/]=refresh  "
            "[bold]I[/]=HAR  [bold]Q[/]=quit"
        )
        if self._autostart:
            self.call_after_refresh(self.action_launch_autostart)

    # ── Status refresh ────────────────────────────────────────────────────

    def _refresh_all_status(self) -> None:
        """Called from timer — dispatches threaded refresh to avoid blocking event loop."""
        self._do_refresh()

    @work(thread=True)
    def _do_refresh(self) -> None:
        """All socket checks run in a worker thread — never blocks the UI."""
        # Check CosySim rows
        results: Dict[str, bool] = {}
        for row in self._rows:
            results[row.target_name] = _port_up(row.info["port"])

        def _apply_rows() -> None:
            for row in self._rows:
                up = results.get(row.target_name, False)
                row._is_up = up
                if up:
                    row.remove_class("-stopped"); row.add_class("-running")
                else:
                    row.remove_class("-running"); row.add_class("-stopped")
                row.refresh()

        self.call_from_thread(_apply_rows)

        # Check external services
        ext_results: Dict[str, tuple[str, bool]] = {}
        for label, port, _ in EXTERNAL_SERVICES:
            if port == 0:
                ok = any(ACCOUNTS_COOKIES_DIR.glob("*_cookies.json")) if ACCOUNTS_COOKIES_DIR.exists() else False
                ext_results[label] = ("copilot", ok)
            else:
                ext_results[label] = (str(port), _port_up(port))

        def _apply_ext() -> None:
            for label, (key, ok) in ext_results.items():
                icon = "[green]●[/]" if ok else "[red]○[/]"
                try:
                    if key == "copilot":
                        w = self.query_one("#ext-copilot", Static)
                        w.update(f" {icon} [bold]{label}[/] [dim](cookie)[/]")
                    else:
                        w = self.query_one(f"#ext-{key}", Static)
                        w.update(f" {icon} [bold]{label}[/] [dim]:{key}[/]")
                except NoMatches:
                    pass
            self._update_stats()

        self.call_from_thread(_apply_ext)

        # Fetch system health (Nexus + LMStudio)
        health_info = self._fetch_system_health()

        def _apply_health() -> None:
            try:
                nexus_w = self.query_one("#nexus-health", Static)
                nexus_w.update(health_info.get("nexus_line", " [dim]Nexus: unknown[/]"))
            except NoMatches:
                pass
            try:
                lms_w = self.query_one("#lmstudio-health", Static)
                lms_w.update(health_info.get("lmstudio_line", " [dim]LMStudio: unknown[/]"))
            except NoMatches:
                pass
            try:
                model_w = self.query_one("#lmstudio-model", Static)
                model_w.update(health_info.get("model_line", ""))
            except NoMatches:
                pass

        self.call_from_thread(_apply_health)

    def _fetch_system_health(self) -> Dict[str, str]:
        """Probe Nexus and LMStudio for health info (runs in worker thread)."""
        import urllib.request
        info: Dict[str, str] = {}

        # Nexus health
        try:
            from engine.port_registry import get_service_url
            req = urllib.request.Request(
                get_service_url("nexus", "/api/health"),
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = _json_mod.loads(resp.read())
                entries = data.get("entries", data.get("entry_count", "?"))
                qa = data.get("qa_pairs", data.get("qa_count", "?"))
                rules = data.get("rules", data.get("rule_count", "?"))
                info["nexus_line"] = (
                    f" [green]●[/] [bold]Nexus[/]  "
                    f"[cyan]{entries}[/] entries  "
                    f"[cyan]{qa}[/] Q&A  "
                    f"[cyan]{rules}[/] rules"
                )
        except Exception:
            info["nexus_line"] = " [red]○[/] [bold]Nexus[/] [dim]offline[/]"

        # LMStudio health + loaded model (with bearer auth)
        try:
            headers: Dict[str, str] = {"Accept": "application/json"}
            try:
                from engine.config import get_config
                token = get_config().get("lmstudio.api_token", "")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
            except Exception:
                pass

            from engine.port_registry import get_service_url
            req = urllib.request.Request(
                get_service_url("lmstudio", "/api/v1/models"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = _json_mod.loads(resp.read())
                models = data.get("data", [])
                if models:
                    model_id = models[0].get("id", "unknown")
                    short = model_id.split("/")[-1] if "/" in model_id else model_id
                    if len(short) > 30:
                        short = short[:27] + "…"
                    info["lmstudio_line"] = (
                        f" [green]●[/] [bold]LMStudio[/]  "
                        f"[cyan]{len(models)}[/] model(s)"
                    )
                    info["model_line"] = f"   [dim]└ {short}[/]"
                else:
                    info["lmstudio_line"] = " [yellow]●[/] [bold]LMStudio[/] [dim]no models[/]"
                    info["model_line"] = ""
        except Exception:
            info["lmstudio_line"] = " [red]○[/] [bold]LMStudio[/] [dim]offline[/]"
            info["model_line"] = ""

        return info

    def _update_stats(self) -> None:
        try:
            widget = self.query_one("#stats-label", Static)
            up_scenes = sum(1 for r in self._rows if r.group == "scene" and r._is_up)
            up_svcs = sum(1 for r in self._rows if r.group == "service" and r._is_up)
            total_scenes = sum(1 for r in self._rows if r.group == "scene")
            total_svcs = sum(1 for r in self._rows if r.group == "service")
            auto_count = sum(1 for r in self._rows if r.info.get("auto_start"))
            widget.update(
                f" [green]{up_svcs}[/][dim]/{total_svcs}[/] services  "
                f"[green]{up_scenes}[/][dim]/{total_scenes}[/] scenes\n"
                f" [dim]{auto_count} auto-start targets[/]"
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

    def action_show_log(self) -> None:
        """Switch the center panel to the Log tab."""
        try:
            tc = self.query_one(TabbedContent)
            tc.active = "tab-log"
        except NoMatches:
            pass

    def action_show_health(self) -> None:
        """Log a system health summary to the log panel."""
        try:
            tc = self.query_one(TabbedContent)
            tc.active = "tab-log"
        except NoMatches:
            pass
        self._log("[bold cyan]───── System Health Summary ─────[/]")
        up_scenes = sum(1 for r in self._rows if r.group == "scene" and r._is_up)
        up_svcs = sum(1 for r in self._rows if r.group == "service" and r._is_up)
        total_scenes = sum(1 for r in self._rows if r.group == "scene")
        total_svcs = sum(1 for r in self._rows if r.group == "service")
        auto_count = sum(1 for r in self._rows if r.info.get("auto_start"))
        self._log(
            f"  Services: [green]{up_svcs}[/]/{total_svcs}  "
            f"Scenes: [green]{up_scenes}[/]/{total_scenes}  "
            f"Auto-start: {auto_count}"
        )
        for label, port, _ in EXTERNAL_SERVICES:
            if port == 0:
                ok = any(ACCOUNTS_COOKIES_DIR.glob("*_cookies.json")) if ACCOUNTS_COOKIES_DIR.exists() else False
                icon = "[green]●[/]" if ok else "[red]○[/]"
                self._log(f"  {icon} {label}")
            else:
                up = _port_up(port)
                icon = "[green]●[/]" if up else "[red]○[/]"
                self._log(f"  {icon} {label} :{port}")
        # Show up/down scenes
        down_scenes = [r.info["label"] for r in self._rows if r.group == "scene" and not r._is_up]
        if down_scenes and len(down_scenes) < total_scenes:
            self._log(f"  [dim]Down: {', '.join(down_scenes[:8])}{'…' if len(down_scenes) > 8 else ''}[/]")
        self._log(f"  Version: [bold]{VERSION}[/]")
        self._log("[bold cyan]────────────────────────────────[/]")

    # ── Launch / Stop ─────────────────────────────────────────────────────

    def action_launch_selected(self) -> None:
        if not self._rows:
            return
        row = self._rows[self.selected_index]
        self._launch_target(row.target_name, row.info)

    def action_launch_autostart(self) -> None:
        """Trigger auto-start in a background thread (never blocks the event loop)."""
        # Switch to log tab so user sees startup progress
        self.action_show_log()
        threading.Thread(target=self._autostart_worker, daemon=True, name="cosysim-autostart").start()

    def action_launch_game(self) -> None:
        """Launch all game pillar targets."""
        self._launch_pillar("game")

    def action_launch_services(self) -> None:
        """Launch all service pillar targets."""
        self._launch_pillar("service")

    def action_launch_creation(self) -> None:
        """Launch all creation pillar targets."""
        self._launch_pillar("creation")

    def _launch_pillar(self, pillar: str) -> None:
        """Launch all targets in a pillar via background thread."""
        self.action_show_log()
        threading.Thread(
            target=self._pillar_worker, args=(pillar,),
            daemon=True, name=f"cosysim-{pillar}",
        ).start()

    def _pillar_worker(self, pillar: str) -> None:
        """Worker: start all targets in the given pillar."""
        target_ids = PILLAR_IDS.get(pillar, ())
        self._log_ts(f"[{pillar}] launching {len(target_ids)} targets")
        for tid in target_ids:
            info = ALL_TARGETS.get(tid)
            if not info:
                continue
            if _port_up(info["port"]):
                self._log_ts(f"[{pillar}] {tid} already up")
                continue
            try:
                self._start_one(tid, info)
                self._log_ts(f"[{pillar}] started {tid}")
            except Exception as exc:
                self._log_ts(f"[{pillar}] FAILED {tid}: {exc}")
            time.sleep(0.5)
        time.sleep(5)
        self.call_from_thread(self._refresh_all_status)

    def _autostart_worker(self) -> None:
        """Worker: start all auto_start targets sequentially with stagger."""
        import traceback as _tb

        _dbg = open(PROJECT_ROOT / "tui_autostart.log", "w", buffering=1)
        def dbg(msg: str) -> None:
            _dbg.write(msg + "\n")
            self._log_ts(msg)

        dbg("[autostart] worker started")
        try:
            # v1.42.1 [2026-03-21] — Priority-sorted autostart (external deps first)
            # Targets with start_priority=0 (e.g. Nexus KMS) launch before scenes
            sorted_targets = sorted(
                ALL_TARGETS.items(),
                key=lambda kv: kv[1].get("start_priority", 50),
            )
            for name, info in sorted_targets:
                if not info.get("auto_start"):
                    continue
                port = info["port"]
                label = info["label"]
                dbg(f"[autostart] checking {name} ({label}) port={port}")
                if _port_up(port):
                    dbg(f"[autostart] {name} already up")
                    continue
                dbg(f"[autostart] starting {name} type={info['type']}")
                try:
                    self._start_one(name, info)
                    dbg(f"[autostart] _start_one({name}) returned OK")
                except Exception as exc:
                    dbg(f"[autostart] _start_one({name}) FAILED: {exc}\n{_tb.format_exc()}")
                time.sleep(0.5)
            # v1.51.0 [2026-03-22] — Start world daemons after services, before checking
            dbg("[autostart] starting world infrastructure...")
            for d_label, d_mod, d_getter, d_method in [
                ("WorldSim",       "engine.world.world_sim",          "get_world_sim",        "start"),
                ("CrossSceneRelay","engine.events.cross_scene_relay", "get_cross_scene_relay", "start"),
                ("EventCascade",   "engine.world.event_cascade",      "get_event_cascade",     "start"),
            ]:
                try:
                    import importlib as _il
                    _m = _il.import_module(d_mod)
                    getattr(getattr(_m, d_getter)(), d_method)()
                    dbg(f"[autostart] {d_label} OK")
                except Exception as _exc:
                    dbg(f"[autostart] {d_label}: {_exc}")
            for d_label, d_mod, d_getter, d_setup in [
                ("Scheduler", "engine.nexus.scheduler_daemon",  "get_scheduler_daemon",  "start"),
                ("AutoLoop",  "engine.nexus.auto_loop",         "get_auto_loop",         "register_tasks"),
                ("ConvSync",  "engine.nexus.conversation_sync", "get_conversation_sync", "register_task"),
            ]:
                try:
                    import importlib as _il
                    _m = _il.import_module(d_mod)
                    getattr(getattr(_m, d_getter)(), d_setup)()
                    dbg(f"[autostart] {d_label} OK")
                except Exception as _exc:
                    dbg(f"[autostart] {d_label}: {_exc}")

            dbg("[autostart] loop done, waiting 8s for ports")
            time.sleep(8)
            for name, info in ALL_TARGETS.items():
                if info.get("auto_start"):
                    up = _port_up(info["port"])
                    dbg(f"[autostart] final check {name}:{info['port']} up={up}")
        except Exception as exc:
            dbg(f"[autostart] WORKER CRASHED: {exc}\n{_tb.format_exc()}")
        finally:
            _dbg.close()
        self.call_from_thread(self._refresh_all_status)

    def _start_one(self, name: str, info: Dict[str, Any]) -> None:
        """Start a single target (called from background thread)."""
        t = info["type"]
        if t == "flask":
            mod, cls_name = info["cls"].rsplit(".", 1)
            scene_cls = getattr(importlib.import_module(mod), cls_name)
            instance = scene_cls()
            _log_path = str(PROJECT_ROOT / "tui_autostart.log")

            def _flask_target() -> None:
                # Textual owns the real stdout/stderr; redirect this thread's
                # stdio to a per-service log so Werkzeug startup output doesn't
                # crash with Bad file descriptor.
                import sys as _sys, os as _os
                _svc_log = open(PROJECT_ROOT / "logs" / f"{name}.log", "a", buffering=1)
                _sys.stdout = _svc_log
                _sys.stderr = _svc_log
                try:
                    instance.start()
                except Exception as _exc:
                    import traceback as _tb2
                    with open(_log_path, "a", buffering=1) as _f:
                        _f.write(f"[thread] {name} CRASHED: {_exc}\n{_tb2.format_exc()}\n")

            thread = threading.Thread(target=_flask_target, daemon=True, name=f"cosysim-{name}")
            thread.start()
            self._launched_threads[name] = thread
        elif t == "streamlit":
            script = PROJECT_ROOT / info["script"]
            proc = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", str(script),
                 f"--server.port={info['port']}", "--server.headless=true",
                 "--server.address=0.0.0.0", "--browser.gatherUsageStats=false",
                 "--logger.level=warning"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._launched_procs[name] = proc
        elif t == "fastapi":
            import uvicorn  # type: ignore
            mod2, fn = info["factory"].rsplit(".", 1)
            factory = getattr(importlib.import_module(mod2), fn)
            thread = threading.Thread(
                target=uvicorn.run,
                args=(factory(),),
                kwargs={"host": "0.0.0.0", "port": info["port"], "log_level": "warning"},
                daemon=True, name=f"cosysim-{name}",
            )
            thread.start()
            self._launched_threads[name] = thread
        elif t == "node":
            script_dir = PROJECT_ROOT / info["script"]
            proc = subprocess.Popen(
                "npm run dev", cwd=str(script_dir), shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._launched_procs[name] = proc
        elif t == "external":  # v1.42.1 [2026-03-21] — external type handler for managed services
            cwd = info.get("cwd", ".")
            cmd = info.get("cmd", [])
            if cmd and Path(cwd).is_dir():
                proc = subprocess.Popen(
                    cmd, cwd=cwd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._launched_procs[name] = proc

    def _log_ts(self, msg: str) -> None:
        """Thread-safe log helper (can be called from any thread)."""
        try:
            self.call_from_thread(self._log, msg)
        except Exception:
            pass  # app may not be mounted yet

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
            self._start_one(name, info)
        except Exception as exc:
            self.call_from_thread(self._log, f"[red]✗[/] {info['label']}: {exc}")
            return
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

    # ── Explicit key handlers (fallback if BINDINGS priority doesn't fire) ──

    def key_a(self) -> None:
        self.action_launch_autostart()

    def key_o(self) -> None:
        self.action_open_browser()

    def key_s(self) -> None:
        self.action_stop_selected()

    def key_r(self) -> None:
        self.action_refresh_status()

    def key_c(self) -> None:
        self.action_open_canvas()

    def key_l(self) -> None:
        self.action_show_log()

    def key_i(self) -> None:
        self.action_import_har()

    def key_space(self) -> None:
        self.action_launch_selected()

    # ── Browser ───────────────────────────────────────────────────────────

    def action_open_browser(self) -> None:
        if not self._rows:
            return
        row = self._rows[self.selected_index]
        url = f"http://localhost:{row.info['port']}"
        self._log(f"[dim]Opening[/] {url}")
        webbrowser.open(url)

    def action_open_canvas(self) -> None:
        try:
            from engine.port_registry import get_service_url
            url = get_service_url("canvas")
        except Exception:
            url = "http://localhost:5590"
        self._log(f"[cyan]Opening Nexus Canvas[/] {url}")
        webbrowser.open(url)

    # ── HAR Import ────────────────────────────────────────────────────────

    def action_import_har(self) -> None:
        self._log("[cyan]HAR import:[/] scanning all HAR directories...")
        self._run_har_import()

    @work(thread=True)
    def _run_har_import(self) -> None:
        """Scan both HAR directories and import all accounts."""
        # Collect all (account, har_file) pairs
        pairs: List[tuple[str, Path]] = []
        for har_root in (HAR_REAL_ROOT, HAR_LOCAL_ROOT):
            if not har_root.exists():
                continue
            for account_dir in sorted(har_root.iterdir()):
                if not account_dir.is_dir() or account_dir.name.startswith("."):
                    continue
                account_id = account_dir.name
                for har_file in sorted(account_dir.glob("*.har")):
                    pairs.append((account_id, har_file))

        if not pairs:
            self.call_from_thread(self._log, "[yellow]No HAR files found in any directory[/]")
            return

        self.call_from_thread(
            self._log,
            f"[dim]Found {len(pairs)} HAR file(s) across "
            f"{len(set(a for a, _ in pairs))} account(s)[/]"
        )

        # Try har_parser import_har_to_pool first (works for all service types)
        try:
            from engine.integrations.har_parser import import_har_to_pool
            _use_har_parser = True
        except ImportError:
            _use_har_parser = False

        # Fallback: GoogleAccountManager (Google-only)
        manager = None
        if not _use_har_parser:
            try:
                from engine.nexus.google_account_manager import GoogleAccountManager
                manager = GoogleAccountManager()
            except Exception as exc:
                self.call_from_thread(self._log, f"[red]AccountManager unavailable: {exc}[/]")
                return

        imported = 0
        for account_id, har_file in pairs:
            # Detect service type from filename
            name_lower = har_file.name.lower()
            if "github" in name_lower or "copilot" in name_lower:
                service = "github"
            elif "aistudio" in name_lower:
                service = "aistudio"
            elif "notebooklm" in name_lower:
                service = "notebooklm"
            elif "drive" in name_lower:
                service = "drive"
            elif "colab" in name_lower:
                service = "colab"
            else:
                service = "google"

            try:
                if _use_har_parser:
                    ok = import_har_to_pool(str(har_file), account_id, service)
                else:
                    ok = manager.import_from_har(str(har_file), account_id, service)
                icon = "[green]✓[/]" if ok else "[yellow]○[/]"
                self.call_from_thread(
                    self._log,
                    f" {icon} [dim]{account_id}/{service}[/] ← {har_file.name}"
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
            f"[green bold]HAR import complete.[/] {imported}/{len(pairs)} file(s) imported."
        )

    # ── Refresh ───────────────────────────────────────────────────────────

    def action_refresh_status(self) -> None:
        self._do_refresh()
        self._log("[dim]Refreshing status...[/]")

    # ── Logging ───────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        try:
            log = self.query_one("#log-panel", RichLog)
            log.write(f"[dim]{ts}[/]  {msg}")
        except NoMatches:
            pass

    # ── Cleanup on quit ───────────────────────────────────────────────────

    # v1.51.1 [2026-03-22] — Force-exit on quit (daemon threads block normal shutdown)
    def on_unmount(self) -> None:
        # Stop world daemons
        for d_mod, d_getter, d_method in [
            ("engine.world.world_sim", "get_world_sim", "stop"),
            ("engine.world.event_cascade", "get_event_cascade", "stop"),
            ("engine.events.cross_scene_relay", "get_cross_scene_relay", "stop"),
        ]:
            try:
                import importlib as _il
                _m = _il.import_module(d_mod)
                getattr(getattr(_m, d_getter)(), d_method)()
            except Exception:
                pass
        # Terminate subprocess-based targets
        for proc in self._launched_procs.values():
            try:
                proc.terminate()
            except Exception:
                pass
        # Force exit — daemon threads (Flask/SocketIO servers) won't release
        import os
        os._exit(0)


# ──── Entry Point ─────────────────────────────────────────────────────────

def main(pillar: str | None = None) -> None:
    """TUI entry point.

    Args:
        pillar: Optional pillar filter ('service', 'game', 'creation').
                If provided, only that pillar's targets are shown.
    """
    import argparse
    parser = argparse.ArgumentParser(description="CosySim TUI Launcher")
    parser.add_argument("--no-autostart", dest="autostart", action="store_false",
                        help="Open TUI without auto-launching targets")
    # v1.50.0 [2026-03-22] — Pillar filter for focused TUI views
    parser.add_argument("--pillar", choices=["service", "game", "creation"],
                        default=pillar,
                        help="Show only targets from this pillar")
    parser.set_defaults(autostart=True)
    args = parser.parse_args()

    # v1.51.1 [2026-03-22] — Fallback Ctrl+C handler in case Textual's event loop
    # is stuck and on_unmount never fires. Forces process exit.
    import signal as _sig
    def _force_exit(sig, frame):
        import os
        os._exit(1)
    _sig.signal(_sig.SIGINT, _force_exit)

    app = CosySimTUI(autostart=args.autostart, pillar_filter=args.pillar)
    app.run()


if __name__ == "__main__":
    main()
