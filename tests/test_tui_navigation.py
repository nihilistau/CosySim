"""
TUI Navigation Tests
====================

Headless Textual Pilot tests for the CosySim TUI keyboard navigation:
arrow-key selection, panel focus hops (left/right), and launch-target
resolution from both the target list and the services table.

Version: v1.58.0 [2026-06-11]
Author:  CosySim Team

Change Log:
    v1.58.0 [2026-06-11] — Initial coverage for the arrow-key navigation
                            overhaul (left/right focus, focus-aware up/down,
                            services-table launch resolution)
"""
from __future__ import annotations

import asyncio

import pytest

from textual.widgets import DataTable

from tui import CosySimTUI, TargetRow


# ──── Helpers ─────────────────────────────────────────────────────────────


def _run(coro) -> None:
    """Run an async pilot scenario from a sync pytest test (no pytest-asyncio)."""
    asyncio.run(coro)


def _make_app() -> CosySimTUI:
    """App instance with autostart disabled — tests must never spawn targets."""
    return CosySimTUI(autostart=False)


# ──── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_arrow_down_moves_selection() -> None:
    async def scenario() -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            assert app._rows, "target list should not be empty"
            assert app.selected_index == 0
            await pilot.press("down", "down")
            assert app.selected_index == 2
            await pilot.press("up")
            assert app.selected_index == 1
            # Focus follows selection so the focused row is visible
            assert isinstance(app.focused, TargetRow)
            assert app.focused is app._rows[1]

    _run(scenario())


@pytest.mark.unit
def test_selection_clamps_at_bounds() -> None:
    async def scenario() -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.press("up")  # already at 0 — must not go negative
            assert app.selected_index == 0
            for _ in range(len(app._rows) + 5):
                await pilot.press("down")
            assert app.selected_index == len(app._rows) - 1

    _run(scenario())


@pytest.mark.unit
def test_right_focuses_services_table_and_left_returns() -> None:
    async def scenario() -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.press("down")  # selection at index 1
            await pilot.press("right")
            table = app.query_one("#svc-table", DataTable)
            assert app.focused is table, "→ should focus the services table"

            # ↑/↓ now drive the table cursor, not the target list
            before = app.selected_index
            await pilot.press("down")
            assert table.cursor_row == 1
            assert app.selected_index == before

            await pilot.press("left")
            assert isinstance(app.focused, TargetRow), "← should refocus the target list"
            assert app.focused is app._rows[app.selected_index]

    _run(scenario())


@pytest.mark.unit
def test_current_target_resolves_from_both_panels() -> None:
    async def scenario() -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            # From the target list
            await pilot.press("down")
            target = app._current_target()
            assert target is not None
            name, info = target
            assert name == app._rows[1].target_name
            assert info["port"] == app._rows[1].info["port"]

            # From the services table (cursor row 0)
            await pilot.press("right")
            table = app.query_one("#svc-table", DataTable)
            target = app._current_target()
            assert target is not None
            name, info = target
            assert name == str(table.get_row_at(0)[0])

    _run(scenario())


@pytest.mark.unit
def test_click_selects_row() -> None:
    async def scenario() -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            row = app._rows[2]
            await pilot.click(row)
            assert app.selected_index == 2
            assert app.focused is row

    _run(scenario())
