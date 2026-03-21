/**
 * cosysim-telemetry.js — Browser-Side Telemetry Collector
 * ========================================================
 *
 * Captures JS errors, user interactions, network failures, and
 * performance metrics. POSTs batches to /api/telemetry for server-side
 * persistence via StructuredLogger.
 *
 * @version v1.43.0 [2026-03-21]
 * @author  CosySim Team
 *
 * Change Log:
 *   v1.43.0 [2026-03-21] — Created. Error capture, click tracking, network monitoring.
 */

'use strict';

(function () {
  // ── Config ──────────────────────────────────────────────────────────
  const FLUSH_INTERVAL_MS = 10_000;  // Flush every 10s
  const MAX_BUFFER_SIZE   = 100;     // Max events before forced flush
  const ENDPOINT          = '/api/telemetry';
  const ENABLED           = true;

  // ── Buffer ──────────────────────────────────────────────────────────
  const _buffer = [];
  let _flushTid = null;
  let _sessionId = `tel_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;

  function _push(event) {
    if (!ENABLED) return;
    event.timestamp = new Date().toISOString();
    event.session_id = _sessionId;
    event.url = window.location.pathname;
    event.scene = document.querySelector('meta[name="scene-key"]')?.content || 'unknown';
    _buffer.push(event);
    if (_buffer.length >= MAX_BUFFER_SIZE) _flush();
  }

  async function _flush() {
    if (_buffer.length === 0) return;
    const batch = _buffer.splice(0);
    try {
      await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: batch }),
      });
    } catch (err) {
      // Re-buffer on failure (but don't grow forever)
      if (_buffer.length < MAX_BUFFER_SIZE * 2) {
        _buffer.push(...batch);
      }
    }
  }

  // ── Error Capture ───────────────────────────────────────────────────

  // Unhandled JS errors
  window.addEventListener('error', (e) => {
    _push({
      type: 'js_error',
      level: 'error',
      message: e.message || 'Unknown error',
      source: e.filename || '',
      line: e.lineno || 0,
      col: e.colno || 0,
      stack: e.error?.stack || '',
    });
  });

  // Unhandled promise rejections
  window.addEventListener('unhandledrejection', (e) => {
    _push({
      type: 'promise_rejection',
      level: 'error',
      message: String(e.reason?.message || e.reason || 'Unknown rejection'),
      stack: e.reason?.stack || '',
    });
  });

  // Console.error capture (non-destructive)
  const _origConsoleError = console.error;
  console.error = function (...args) {
    _push({
      type: 'console_error',
      level: 'error',
      message: args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ').slice(0, 500),
    });
    _origConsoleError.apply(console, args);
  };

  // ── Network Failure Capture ─────────────────────────────────────────

  // Capture fetch failures (only actual errors, not 404s from stopped scenes)
  const _origFetch = window.fetch;
  window.fetch = function (...args) {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    return _origFetch.apply(this, args).then(
      resp => {
        if (!resp.ok && resp.status >= 500) {
          _push({
            type: 'fetch_error',
            level: 'warning',
            message: `${resp.status} ${resp.statusText}`,
            request_url: url.slice(0, 200),
          });
        }
        return resp;
      },
      err => {
        // Only log if it's not a scene health ping (those spam when scenes are down)
        if (!url.includes('/api/health') && !url.includes('/api/contacts')) {
          _push({
            type: 'fetch_network_error',
            level: 'error',
            message: err.message || 'Network error',
            request_url: url.slice(0, 200),
          });
        }
        throw err;
      }
    );
  };

  // ── Click Tracking ──────────────────────────────────────────────────

  document.addEventListener('click', (e) => {
    const target = e.target.closest('button, a, [data-action], [onclick], .cs-hud-slide__inv-slot, .cs-hud-slide__crew-row, .district-card');
    if (!target) return;
    _push({
      type: 'click',
      level: 'info',
      message: `Click: ${target.tagName} ${target.id || target.className?.split(' ')[0] || ''}`.trim(),
      element_id: target.id || '',
      element_class: (target.className || '').toString().slice(0, 100),
      element_text: (target.textContent || '').trim().slice(0, 50),
      data_action: target.dataset?.action || target.dataset?.tab || '',
    });
  });

  // ── Keyboard Shortcut Tracking ──────────────────────────────────────

  document.addEventListener('keydown', (e) => {
    if (['i', 'c', 'm', 'b', 'p', 'a', 'Escape'].includes(e.key) &&
        !e.target.matches('input, textarea, [contenteditable]')) {
      _push({
        type: 'hotkey',
        level: 'info',
        message: `Hotkey: ${e.key}`,
        key: e.key,
      });
    }
  });

  // ── Page Load Metrics ───────────────────────────────────────────────

  window.addEventListener('load', () => {
    const perf = performance.getEntriesByType('navigation')[0];
    if (perf) {
      _push({
        type: 'page_load',
        level: 'info',
        message: `Page loaded in ${Math.round(perf.loadEventEnd - perf.startTime)}ms`,
        dns_ms: Math.round(perf.domainLookupEnd - perf.domainLookupStart),
        connect_ms: Math.round(perf.connectEnd - perf.connectStart),
        ttfb_ms: Math.round(perf.responseStart - perf.requestStart),
        dom_ms: Math.round(perf.domContentLoadedEventEnd - perf.startTime),
        load_ms: Math.round(perf.loadEventEnd - perf.startTime),
      });
    }
  });

  // ── Flush Loop ──────────────────────────────────────────────────────

  _flushTid = setInterval(_flush, FLUSH_INTERVAL_MS);
  window.addEventListener('beforeunload', _flush);

  // ── Public API ──────────────────────────────────────────────────────

  window.CosyTelemetry = {
    push: _push,
    flush: _flush,
    getBuffer: () => [..._buffer],
    getSessionId: () => _sessionId,
  };

  console.log(`[Telemetry] Session ${_sessionId} — capturing errors, clicks, network`);
})();
