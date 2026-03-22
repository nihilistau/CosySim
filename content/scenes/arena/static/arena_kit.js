/**
 * THE COLOSSEUM — Kit Scene Controller
 * =====================================
 *
 * Socket.IO connection, state application, toast system,
 * and extension hook for arena_ext.js. Generated from
 * arena_rebuild.json layout via Creation Kit pattern.
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Initial Kit-generated controller for Arena rebuild.
 *                            ArenaScene class with _initExtensions hook for arena_ext.js.
 *
 * CONNECTS: Socket.IO, DOM elements, arena_ext.js
 * CALLED BY: DOMContentLoaded
 */

'use strict';

// ── ArenaScene Class ──────────────────────────────────────────────────

class ArenaScene {
  constructor() {
    /** @type {SocketIO.Socket|null} */
    this.socket = null;
    /** @type {Object|null} Current scene state snapshot */
    this.state = null;
    /** @type {string|null} Active match ID */
    this.matchId = null;
    /** @type {number|null} Toast dismiss timer */
    this._toastTimer = null;
  }

  // ── Lifecycle ───────────────────────────────────────────────────────

  // v1.50.0 [2026-03-22] — Extension hook: arena_ext.js adds methods via
  // ArenaScene.prototype._initExtensions = function() { ... }
  init() {
    this._setupSocket();
    this._setupUI();
    this._loadInitialState();
    if (typeof this._initExtensions === 'function') this._initExtensions();
  }

  // ── Socket.IO Setup ─────────────────────────────────────────────────
  // CONNECTS: Flask-SocketIO server on current host
  // EMITS: get_fighters on connect

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      this._log('Connected to THE COLOSSEUM.', 'system');
      this._loadInitialState();
    });

    this.socket.on('disconnect', () => {
      this._log('Connection lost. Reconnecting...', 'system');
    });

    // v1.49.2 [2026-03-22] — Socket.IO reconnect feedback
    this.socket.io.on('reconnect', (attempt) => {
      console.debug('[ArenaKit] Reconnected after ' + attempt + ' attempt(s)');
    });
    this.socket.io.on('reconnect_attempt', (attempt) => {
      if (attempt % 3 === 0) console.debug('[ArenaKit] Reconnecting... (attempt ' + attempt + ')');
    });

    // Full state sync
    this.socket.on('state_update', (data) => this._applyState(data));

    // Generic error handler
    this.socket.on('error', (data) => {
      this._showToast(data.message || 'Error', 'danger');
    });

    // Arena-specific error handler
    this.socket.on('arena_error', (data) => {
      console.error('[Arena] Server error:', data.error);
      this._showToast(data.error || 'Arena error', 'danger');
    });
  }

  // ── Initial State Load ──────────────────────────────────────────────
  // CONNECTS: /api/fighters REST endpoint, Socket.IO get_fighters
  // CALLED BY: init(), _setupSocket on connect

  _loadInitialState() {
    // Request fighters via Socket.IO
    if (this.socket) this.socket.emit('get_fighters');

    // REST fallback — fetch fighter list
    fetch('/api/fighters')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) this._applyState(data);
      })
      .catch(() => {});
  }

  // ── State Application ───────────────────────────────────────────────
  // CONNECTS: HUD badges, fighter selects
  // CALLED BY: state_update socket event, _loadInitialState

  _applyState(state) {
    if (!state || typeof state !== 'object') return;
    this.state = { ...this.state, ...state };

    // HUD badge updates (ck-hud-badge pattern)
    document.querySelectorAll('.ck-hud-badge span').forEach(el => {
      const key = el.id?.replace('badge-val-', '');
      if (key && state[key] !== undefined) el.textContent = state[key];
    });
  }

  // ── UI Wiring ───────────────────────────────────────────────────────
  // CONNECTS: Generic button handlers with data-action
  // CALLED BY: init()

  _setupUI() {
    // Generic button wiring -- buttons with data-action emit action events
    document.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        const payload = {};
        for (const [key, val] of Object.entries(btn.dataset)) {
          if (key !== 'action') payload[key] = val;
        }
        this._action(action, payload);
      });
    });
  }

  // ── Action Dispatcher ───────────────────────────────────────────────
  // CONNECTS: Socket.IO action event
  // CALLED BY: _setupUI, extension methods

  _action(action, data = {}) {
    if (this.socket) {
      this.socket.emit('action', { action, ...data });
    }
  }

  // ── Commentary Log ──────────────────────────────────────────────────
  // CONNECTS: #commentary-feed DOM element
  // CALLED BY: Extension methods, socket event handlers

  _log(text, type = 'round') {
    this._appendCommentary(text, type);
  }

  _appendCommentary(text, type = 'round') {
    const feed = document.getElementById('commentary-feed');
    if (!feed) {
      console.debug(`[${type}] ${text}`);
      return;
    }

    const p = document.createElement('p');
    p.className = `arena-commentary__line arena-commentary__line--${type}`;
    p.textContent = text;
    feed.appendChild(p);

    // Trim old lines (keep last 60)
    const lines = feed.querySelectorAll('.arena-commentary__line');
    if (lines.length > 60) {
      lines[0].remove();
    }

    // Auto-scroll to bottom
    feed.scrollTop = feed.scrollHeight;
  }

  // ── Toast Notifications ─────────────────────────────────────────────
  // CONNECTS: .ck-toast-container DOM element
  // CALLED BY: Extension methods, socket error handlers

  _showToast(text, severity = 'info') {
    // Kit-style toast container
    const container = document.querySelector('.ck-toast-container');
    if (container) {
      const toast = document.createElement('div');
      toast.className = 'ck-toast';
      toast.textContent = text;
      const colors = {
        danger: '#ef4444',
        success: '#22c55e',
        warning: '#f59e0b',
        info: 'var(--scene-accent, #dc2626)'
      };
      toast.style.borderLeftColor = colors[severity] || colors.info;
      container.appendChild(toast);
      setTimeout(() => toast.remove(), 4000);
      return;
    }

    // Fallback -- console
    console.debug(`[toast:${severity}] ${text}`);
  }

  // ── Helpers ─────────────────────────────────────────────────────────

  _setText(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== null) {
      el.textContent = value;
    }
  }
}

// ── Bootstrap ───────────────────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Global SceneApp instance, auto-init on DOMContentLoaded
const SceneApp = new ArenaScene();
document.addEventListener('DOMContentLoaded', () => SceneApp.init());
