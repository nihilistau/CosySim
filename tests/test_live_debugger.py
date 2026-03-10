"""Tests for ARGUS LiveDebugger and debugger skills.

Mocks CDP connections to verify:
- Console log capture and filtering
- Network error detection
- JS exception handling
- DOM inspection queries
- Scene health checks
- Z-index stack analysis
- Click target testing
- Screenshot capture
- Diagnostic report generation
- MCP skill wrappers
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.argus.live_debugger import (
    ConsoleEntry,
    DiagnosticReport,
    JSException,
    LiveDebugger,
    NetworkEntry,
)


def _run(coro):
    """Run an async coroutine synchronously for tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_session():
    """Create a mock CDPSession that satisfies LiveDebugger needs."""
    session = AsyncMock()
    session.evaluate = AsyncMock(return_value=None)
    session.send = AsyncMock(return_value={})
    session.enable_network = AsyncMock()
    session.enable_runtime = AsyncMock()
    session.on = MagicMock()
    session.off = MagicMock()
    session.disconnect = AsyncMock()
    session.get_response_body = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_bridge():
    """Create a mock CDPBridge."""
    bridge = MagicMock()
    bridge.get_tabs.return_value = [
        {"id": "tab1", "url": "http://localhost:5556/", "title": "Penthouse",
         "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/tab1"},
    ]
    bridge.get_tab_by_url.return_value = {
        "id": "tab1",
        "url": "http://localhost:5556/",
        "title": "Penthouse",
        "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/tab1",
    }
    bridge.open_session = AsyncMock()
    return bridge


@pytest.fixture
def debugger(mock_bridge, mock_session):
    """Create a LiveDebugger with mocked bridge and session."""
    mock_bridge.open_session.return_value = mock_session

    with patch("scripts.argus.live_debugger.CDPBridge", return_value=mock_bridge):
        dbg = LiveDebugger("localhost:5556")
        dbg._bridge = mock_bridge
    return dbg


# ── Data Class Tests ─────────────────────────────────────────────────

class TestConsoleEntry:
    def test_str_basic(self):
        entry = ConsoleEntry(level="error", text="Something failed")
        assert "[ERROR] Something failed" in str(entry)

    def test_str_with_location(self):
        entry = ConsoleEntry(level="warning", text="Deprecation", url="app.js", line=42)
        result = str(entry)
        assert "WARNING" in result
        assert "app.js:42" in result

    def test_str_without_location(self):
        entry = ConsoleEntry(level="log", text="Hello")
        assert "app.js" not in str(entry)


class TestNetworkEntry:
    def test_is_error_status(self):
        entry = NetworkEntry(request_id="1", url="/api/test", status=500)
        assert entry.is_error is True

    def test_is_error_load_failure(self):
        entry = NetworkEntry(request_id="2", url="/api/test", error_text="net::ERR_FAILED")
        assert entry.is_error is True

    def test_not_error(self):
        entry = NetworkEntry(request_id="3", url="/api/test", status=200)
        assert entry.is_error is False

    def test_str_error(self):
        entry = NetworkEntry(request_id="4", url="/api/fail", error_text="net::ERR_TIMEOUT")
        assert "NET ERR" in str(entry)

    def test_str_response(self):
        entry = NetworkEntry(request_id="5", url="/api/ok", method="POST", status=201)
        assert "[201]" in str(entry)
        assert "POST" in str(entry)


class TestJSException:
    def test_str_basic(self):
        exc = JSException(text="TypeError: x is not a function")
        assert "EXCEPTION" in str(exc)
        assert "TypeError" in str(exc)

    def test_str_with_location(self):
        exc = JSException(text="ReferenceError", url="main.js", line=10, column=5)
        assert "main.js:10:5" in str(exc)


# ── Console Capture Tests ────────────────────────────────────────────

class TestConsoleLogs:
    def test_get_console_logs_empty(self, debugger):
        logs = debugger.get_console_logs()
        assert logs == []

    def test_get_console_logs_basic(self, debugger):
        debugger._console_logs.append(ConsoleEntry(level="log", text="Hello"))
        debugger._console_logs.append(ConsoleEntry(level="error", text="Fail"))
        logs = debugger.get_console_logs()
        assert len(logs) == 2

    def test_filter_by_level(self, debugger):
        debugger._console_logs.append(ConsoleEntry(level="log", text="Hello"))
        debugger._console_logs.append(ConsoleEntry(level="error", text="Fail"))
        debugger._console_logs.append(ConsoleEntry(level="error", text="Crash"))
        errors = debugger.get_console_logs(level="error")
        assert len(errors) == 2
        assert all(e.level == "error" for e in errors)

    def test_filter_by_pattern(self, debugger):
        debugger._console_logs.append(ConsoleEntry(level="log", text="Loading scene"))
        debugger._console_logs.append(ConsoleEntry(level="log", text="Ready"))
        debugger._console_logs.append(ConsoleEntry(level="error", text="Failed to load scene"))
        filtered = debugger.get_console_logs(pattern="scene")
        assert len(filtered) == 2

    def test_filter_case_insensitive(self, debugger):
        debugger._console_logs.append(ConsoleEntry(level="log", text="THREE.js loaded"))
        filtered = debugger.get_console_logs(pattern="three")
        assert len(filtered) == 1

    def test_limit(self, debugger):
        for i in range(20):
            debugger._console_logs.append(ConsoleEntry(level="log", text=f"Msg {i}"))
        logs = debugger.get_console_logs(limit=5)
        assert len(logs) == 5
        assert logs[-1].text == "Msg 19"

    def test_get_errors(self, debugger):
        debugger._console_logs.append(ConsoleEntry(level="log", text="Ok"))
        debugger._console_logs.append(ConsoleEntry(level="error", text="Bad"))
        assert len(debugger.get_errors()) == 1
        assert debugger.get_errors()[0].text == "Bad"

    def test_get_warnings(self, debugger):
        debugger._console_logs.append(ConsoleEntry(level="warning", text="Warn"))
        debugger._console_logs.append(ConsoleEntry(level="error", text="Err"))
        assert len(debugger.get_warnings()) == 1

    def test_clear_console(self, debugger):
        debugger._console_logs.append(ConsoleEntry(level="log", text="Test"))
        debugger.clear_console()
        assert len(debugger.get_console_logs()) == 0


# ── Network Capture Tests ────────────────────────────────────────────

class TestNetworkLog:
    def test_get_network_log_empty(self, debugger):
        assert debugger.get_network_log() == []

    def test_get_network_errors(self, debugger):
        debugger._network_log.append(
            NetworkEntry(request_id="1", url="/ok", status=200)
        )
        debugger._network_log.append(
            NetworkEntry(request_id="2", url="/fail", status=500)
        )
        debugger._network_log.append(
            NetworkEntry(request_id="3", url="/not-found", status=404)
        )
        errors = debugger.get_network_errors()
        assert len(errors) == 2

    def test_filter_by_pattern(self, debugger):
        debugger._network_log.append(
            NetworkEntry(request_id="1", url="/api/health", status=200)
        )
        debugger._network_log.append(
            NetworkEntry(request_id="2", url="/api/state", status=200)
        )
        debugger._network_log.append(
            NetworkEntry(request_id="3", url="/static/app.js", status=200)
        )
        entries = debugger.get_network_log(pattern="/api/")
        assert len(entries) == 2

    def test_clear_network(self, debugger):
        debugger._network_log.append(
            NetworkEntry(request_id="1", url="/test", status=200)
        )
        debugger.clear_network()
        assert debugger.get_network_log() == []


# ── Event Handler Tests ──────────────────────────────────────────────

class TestEventHandlers:
    def test_on_console(self, debugger):
        params = {
            "type": "error",
            "args": [{"type": "string", "value": "Test error"}],
            "stackTrace": {"callFrames": [{"url": "app.js", "lineNumber": 10}]},
            "timestamp": time.time(),
        }
        debugger._on_console(params)
        assert len(debugger._console_logs) == 1
        assert debugger._console_logs[0].level == "error"
        assert debugger._console_logs[0].text == "Test error"
        assert debugger._console_logs[0].url == "app.js"

    def test_on_console_multiple_args(self, debugger):
        params = {
            "type": "log",
            "args": [
                {"type": "string", "value": "Count:"},
                {"type": "number", "value": 42},
            ],
            "stackTrace": {"callFrames": []},
        }
        debugger._on_console(params)
        assert "Count: 42" in debugger._console_logs[0].text

    def test_on_exception(self, debugger):
        params = {
            "exceptionDetails": {
                "text": "Uncaught TypeError",
                "exception": {"description": "TypeError: x is not a function"},
                "url": "main.js",
                "lineNumber": 25,
                "columnNumber": 8,
                "stackTrace": {"callFrames": [
                    {"functionName": "init", "url": "main.js", "lineNumber": 25},
                ]},
            },
        }
        debugger._on_exception(params)
        assert len(debugger._js_exceptions) == 1
        assert "TypeError" in debugger._js_exceptions[0].text

    def test_on_request(self, debugger):
        params = {
            "requestId": "req1",
            "request": {"url": "http://localhost:5556/api/health", "method": "GET"},
            "timestamp": time.time(),
        }
        debugger._on_request(params)
        assert "req1" in debugger._network_entries

    def test_on_response(self, debugger):
        debugger._network_entries["req1"] = NetworkEntry(
            request_id="req1", url="/api/health"
        )
        params = {
            "requestId": "req1",
            "response": {"status": 200, "statusText": "OK", "mimeType": "application/json"},
        }
        debugger._on_response(params)
        assert len(debugger._network_log) == 1
        assert debugger._network_log[0].status == 200

    def test_on_load_failed(self, debugger):
        debugger._network_entries["req2"] = NetworkEntry(
            request_id="req2", url="/missing.js"
        )
        params = {
            "requestId": "req2",
            "errorText": "net::ERR_ABORTED",
        }
        debugger._on_load_failed(params)
        assert len(debugger._network_log) == 1
        assert debugger._network_log[0].error_text == "net::ERR_ABORTED"


# ── Diagnostic Report Tests ──────────────────────────────────────────

class TestDiagnosticReport:
    def test_summary_empty(self):
        report = DiagnosticReport(
            url="http://localhost:5556/",
            title="Test",
            timestamp=time.time(),
            console_errors=[],
            console_warnings=[],
            network_errors=[],
            js_exceptions=[],
            dom_stats={},
            performance={},
            scene_health={},
        )
        summary = report.summary()
        assert "SCENE DIAGNOSTIC" in summary
        assert "Console Errors:   0" in summary

    def test_summary_with_errors(self):
        report = DiagnosticReport(
            url="http://localhost:5556/",
            title="Test",
            timestamp=time.time(),
            console_errors=[ConsoleEntry(level="error", text="Fail")],
            console_warnings=[],
            network_errors=[NetworkEntry(request_id="1", url="/bad", status=500)],
            js_exceptions=[JSException(text="TypeError")],
            dom_stats={"total_elements": 100},
            performance={"fps": 60},
            scene_health={"threejs_loaded": True, "socket_connected": False},
        )
        summary = report.summary()
        assert "Console Errors:   1" in summary
        assert "Network Errors:   1" in summary
        assert "JS Exceptions:    1" in summary
        assert "✅ threejs_loaded" in summary
        assert "❌ socket_connected" in summary

    def test_summary_with_vision(self):
        report = DiagnosticReport(
            url="http://localhost:5556/",
            title="Test",
            timestamp=time.time(),
            console_errors=[],
            console_warnings=[],
            network_errors=[],
            js_exceptions=[],
            dom_stats={},
            performance={},
            scene_health={},
            vision_analysis="The page shows a 3D penthouse scene.",
        )
        assert "Vision Analysis" in report.summary()
        assert "penthouse" in report.summary()


# ── LiveDebugger Method Tests ────────────────────────────────────────

class TestLiveDebuggerMethods:
    def test_connect_no_target(self):
        """Connect without target raises ValueError."""
        dbg = LiveDebugger()
        with pytest.raises(ValueError, match="No target URL"):
            _run(dbg.connect())

    def test_ensure_connected_raises(self, debugger):
        """Calling methods before connect raises RuntimeError."""
        with pytest.raises(RuntimeError, match="not connected"):
            debugger._ensure_connected()

    def test_list_tabs(self):
        """list_tabs returns tab info."""
        with patch("scripts.argus.live_debugger.CDPBridge") as MockBridge:
            MockBridge.return_value.get_tabs.return_value = [
                {"url": "http://localhost:5556/", "title": "Scene", "id": "t1"},
            ]
            tabs = LiveDebugger.list_tabs()
            assert len(tabs) == 1
            assert tabs[0]["url"] == "http://localhost:5556/"

    def test_get_tab_info_empty(self, debugger):
        assert debugger.get_tab_info() == {}

    def test_max_buffer(self):
        """Buffer respects max_buffer limit."""
        dbg = LiveDebugger("test", max_buffer=3)
        for i in range(10):
            dbg._console_logs.append(ConsoleEntry(level="log", text=f"Msg {i}"))
        assert len(dbg._console_logs) == 3
        assert dbg._console_logs[0].text == "Msg 7"


# ── Async Method Tests ───────────────────────────────────────────────

class TestAsyncMethods:
    def test_eval_js(self, debugger, mock_session):
        """eval_js delegates to session.evaluate."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.return_value = "Hello World"

        result = _run(debugger.eval_js("document.title"))
        assert result == "Hello World"
        mock_session.evaluate.assert_called_once_with("document.title")

    def test_eval_js_safe_success(self, debugger, mock_session):
        """eval_js_safe returns {ok, value} on success."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.return_value = 42

        result = _run(debugger.eval_js_safe("1 + 41"))
        assert result["ok"] is True
        assert result["value"] == 42

    def test_eval_js_safe_error(self, debugger, mock_session):
        """eval_js_safe returns {ok: false, error} on failure."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.side_effect = RuntimeError("JS error")

        result = _run(debugger.eval_js_safe("bad.code()"))
        assert result["ok"] is False
        assert "JS error" in result["error"]

    def test_click(self, debugger, mock_session):
        """click dispatches a JS click."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.return_value = True

        result = _run(debugger.click("#btn-test"))
        assert result is True

    def test_take_screenshot(self, debugger, mock_session, tmp_path):
        """take_screenshot saves PNG file."""
        debugger._session = mock_session
        debugger._connected = True

        import base64
        fake_png = base64.b64encode(b"fake-png-data").decode()
        mock_session.send.return_value = {"data": fake_png}

        save_path = str(tmp_path / "test_screenshot.png")
        result = _run(debugger.take_screenshot(save_path=save_path))
        assert result == save_path
        assert (tmp_path / "test_screenshot.png").exists()

    def test_query_selector(self, debugger, mock_session):
        """query_selector returns element info."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.return_value = {
            "tag": "div",
            "id": "test",
            "classes": ["panel"],
            "visible": True,
            "rect": {"x": 0, "y": 0, "w": 100, "h": 50},
            "zIndex": "100",
            "pointerEvents": "auto",
        }

        result = _run(debugger.query_selector("#test"))
        assert result["tag"] == "div"
        assert result["visible"] is True

    def test_query_selector_not_found(self, debugger, mock_session):
        """query_selector returns None for missing elements."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.return_value = None

        result = _run(debugger.query_selector("#nonexistent"))
        assert result is None

    def test_get_dom_stats(self, debugger, mock_session):
        """get_dom_stats returns page statistics."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.return_value = {
            "total_elements": 150,
            "visible_elements": 80,
            "canvases": 1,
            "scripts": 5,
        }

        stats = _run(debugger.get_dom_stats())
        assert stats["total_elements"] == 150
        assert stats["canvases"] == 1

    def test_check_scene_health(self, debugger, mock_session):
        """check_scene_health runs all checks."""
        debugger._session = mock_session
        debugger._connected = True

        async def mock_evaluate(expr):
            return True

        mock_session.evaluate = mock_evaluate

        health = _run(debugger.check_scene_health())
        assert isinstance(health, dict)
        assert "socketio_loaded" in health

    def test_navigate(self, debugger, mock_session):
        """navigate sends Page.navigate command."""
        debugger._session = mock_session
        debugger._connected = True

        _run(debugger.navigate("http://localhost:5556/"))
        mock_session.send.assert_called_with("Page.navigate", {"url": "http://localhost:5556/"})

    def test_reload(self, debugger, mock_session):
        """reload sends Page.reload command."""
        debugger._session = mock_session
        debugger._connected = True

        _run(debugger.reload())
        mock_session.send.assert_called_with("Page.reload", {"ignoreCache": True})

    def test_get_memory_info(self, debugger, mock_session):
        """get_memory_info returns heap stats."""
        debugger._session = mock_session
        debugger._connected = True
        mock_session.evaluate.return_value = {
            "used_heap_mb": 25,
            "total_heap_mb": 50,
            "heap_limit_mb": 2048,
        }

        mem = _run(debugger.get_memory_info())
        assert mem["used_heap_mb"] == 25


# ── Skill Tests ──────────────────────────────────────────────────────

class TestDebuggerSkills:
    def test_debug_list_tabs_no_chrome(self):
        """debug_list_tabs handles missing Chrome gracefully."""
        with patch("scripts.argus.live_debugger.CDPBridge") as MockBridge:
            MockBridge.return_value.get_tabs.side_effect = ConnectionError("No Chrome")
            from engine.skills.builtin.debugger_skills import debug_list_tabs
            result = debug_list_tabs()
            assert "ERROR" in result or "Cannot connect" in result

    def test_debug_scene_no_chrome(self):
        """debug_scene handles missing Chrome gracefully."""
        with patch("scripts.argus.live_debugger.CDPBridge") as MockBridge:
            MockBridge.return_value.get_tab_by_url.return_value = None
            MockBridge.return_value.get_tabs.return_value = []
            from engine.skills.builtin.debugger_skills import debug_scene
            result = debug_scene(port=9999)
            assert "ERROR" in result

    def test_debug_click_test_no_selectors(self):
        """debug_click_test requires selectors."""
        from engine.skills.builtin.debugger_skills import debug_click_test
        result = debug_click_test(selectors="")
        assert "ERROR" in result

    def test_debug_navigate_no_url(self):
        """debug_navigate requires URL."""
        from engine.skills.builtin.debugger_skills import debug_navigate
        result = debug_navigate(url="")
        assert "ERROR" in result

    def test_debug_click_no_selector(self):
        """debug_click requires selector."""
        from engine.skills.builtin.debugger_skills import debug_click
        result = debug_click(selector="")
        assert "ERROR" in result


# ── Integration Smoke Tests ──────────────────────────────────────────

class TestIntegrationSmoke:
    def test_debugger_import(self):
        """LiveDebugger imports cleanly."""
        from scripts.argus.live_debugger import LiveDebugger, quick_diagnose
        assert LiveDebugger is not None
        assert quick_diagnose is not None

    def test_skills_import(self):
        """All debugger skills import cleanly."""
        from engine.skills.builtin.debugger_skills import (
            debug_click,
            debug_click_test,
            debug_console,
            debug_dom,
            debug_eval,
            debug_health,
            debug_list_tabs,
            debug_navigate,
            debug_network,
            debug_perf,
            debug_scene,
            debug_screenshot,
            debug_watch,
            debug_z_stack,
        )
        assert debug_scene is not None
        assert debug_watch is not None
        assert debug_console is not None
        assert debug_network is not None
        assert debug_eval is not None
        assert debug_dom is not None
        assert debug_z_stack is not None
        assert debug_click_test is not None
        assert debug_screenshot is not None
        assert debug_click is not None
        assert debug_navigate is not None
        assert debug_perf is not None
        assert debug_list_tabs is not None
        assert debug_health is not None

    def test_cli_module(self):
        """CLI module imports cleanly."""
        from scripts.argus.tools.debug_scene import main
        assert main is not None
