/**
 * THE RUSTY ANCHOR — Kit Scene Controller
 * ========================================
 *
 * Socket.IO connection, stat bar updaters, chat log, button wiring,
 * toast notifications, and scene lifecycle. Generated from
 * tavern_rebuild.json layout via Creation Kit pattern.
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Initial Kit-generated controller for Tavern rebuild.
 *                            TavernScene class with _initExtensions hook for tavern_ext.js.
 *
 * CONNECTS: Socket.IO, DOM elements, tavern_ext.js
 * CALLED BY: DOMContentLoaded
 */

'use strict';

// ── TavernScene Class ─────────────────────────────────────────────────

class TavernScene {
  constructor() {
    /** @type {SocketIO.Socket|null} */
    this.socket = null;
    /** @type {Object|null} Current scene state snapshot */
    this.state = null;
    /** @type {number|null} Toast dismiss timer */
    this._toastTimer = null;
  }

  // ── Lifecycle ─────────────────────────────────────────────────────

  // v1.50.0 [2026-03-22] — Extension hook: tavern_ext.js adds methods via
  // TavernScene.prototype._initExtensions = function() { ... }
  init() {
    this._setupSocket();
    this._setupUI();
    this._loadInitialState();
    if (typeof this._initExtensions === 'function') this._initExtensions();
  }

  // ── Socket.IO Setup ───────────────────────────────────────────────
  // CONNECTS: Flask-SocketIO server
  // EMITS: get_tavern_state on connect

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      this._addChatLine('Connected to The Rusty Anchor.', 'system');
      this._loadInitialState();
    });

    this.socket.on('disconnect', () => {
      this._addChatLine('Lost connection. Reconnecting...', 'system');
    });

    // Full state sync
    this.socket.on('state_update', (data) => this._applyState(data));
    this.socket.on('tavern_state', (data) => this._applyState(data));

    // Generic error handler
    this.socket.on('error', (data) => {
      this._showToast(data.message || 'Error', 'danger');
    });

    // Generic event feed
    this.socket.on('event', ({ text }) => {
      if (text) this._addChatLine(text, 'system');
    });

    // Consequence events
    this.socket.on('consequence', ({ description }) => {
      if (description) this._addChatLine(`Consequence: ${description}`, 'system');
    });
  }

  // ── Initial State Load ────────────────────────────────────────────
  // CONNECTS: /api/status REST endpoint, Socket.IO get_tavern_state
  // CALLED BY: init(), _setupSocket on connect

  _loadInitialState() {
    // Socket.IO request
    if (this.socket) this.socket.emit('get_tavern_state');

    // REST fallback
    fetch('/api/status')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) this._applyState(data); })
      .catch(() => {});
  }

  // ── State Application ─────────────────────────────────────────────
  // CONNECTS: stat bars, HUD badges, economy panel, atmosphere banner
  // CALLED BY: state_update / tavern_state socket events, _loadInitialState

  _applyState(state) {
    if (!state || typeof state !== 'object') return;
    this.state = { ...this.state, ...state };

    // Economy — gold display
    this._setText('gold-val', state.gold);

    // Stat bars — warmth, courage, clarity, charm
    const stats = { warmth: state.warmth, courage: state.courage, clarity: state.clarity, charm: state.charm };
    for (const [key, val] of Object.entries(stats)) {
      if (val === undefined || val === null) continue;
      const barEl = document.getElementById(`stat-${key}`);
      if (barEl) {
        const fill = barEl.querySelector('.ck-stat-fill, .stat-fill');
        const valEl = barEl.querySelector('.ck-stat-val, .stat-val');
        if (fill) fill.style.width = `${Math.min(100, Math.max(0, val))}%`;
        if (valEl) valEl.textContent = Math.round(val);
      }
    }

    // Atmosphere banner
    if (state.atmosphere) {
      const banner = document.getElementById('atm-banner');
      if (banner) {
        const atmText = {
          quiet: 'The tavern is quiet. Only a few patrons murmur.',
          lively: 'The tavern buzzes with laughter and clinking mugs.',
          rowdy: 'Voices rise, tables shake — the crowd is rowdy!',
          brawl: 'Chairs fly! A brawl has broken out!'
        };
        const textEl = banner.querySelector('.ck-alert-text, .alert-text');
        if (textEl) textEl.textContent = atmText[state.atmosphere] || state.atmosphere;
      }
    }

    // HUD badge updates (ck-hud-badge pattern)
    document.querySelectorAll('.ck-hud-badge span').forEach(el => {
      const key = el.id?.replace('badge-val-', '');
      if (key && state[key] !== undefined) el.textContent = state[key];
    });

    // Progress tracker — quest progress
    if (state.quest_step !== undefined) {
      const tracker = document.getElementById('quest-progress');
      if (tracker) {
        const steps = tracker.querySelectorAll('.ck-step, .step');
        steps.forEach((step, i) => {
          step.classList.toggle('active', i <= state.quest_step);
          step.classList.toggle('current', i === state.quest_step);
        });
      }
    }
  }

  // ── UI Wiring ─────────────────────────────────────────────────────
  // CONNECTS: Chat form, button click handlers
  // CALLED BY: init()

  _setupUI() {
    // Chat input form — delegate to _sendMessage
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
      chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          const text = chatInput.value.trim();
          if (text) {
            this._sendMessage(text);
            chatInput.value = '';
          }
        }
      });
    }

    // Generic button wiring — buttons with data-action emit action events
    document.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        const payload = {};
        // Collect data-* attributes as payload
        for (const [key, val] of Object.entries(btn.dataset)) {
          if (key !== 'action') payload[key] = val;
        }
        this._action(action, payload);
      });
    });
  }

  // ── Action Dispatcher ─────────────────────────────────────────────
  // CONNECTS: Socket.IO action event
  // CALLED BY: _setupUI, extension methods

  _action(action, data = {}) {
    if (this.socket) {
      this.socket.emit('action', { action, ...data });
    }
  }

  // ── Chat ──────────────────────────────────────────────────────────
  // CONNECTS: #chat-feed DOM element, Socket.IO chat action
  // CALLED BY: _setupUI, extension methods, socket event handlers

  _sendMessage(text) {
    this._addChatLine(`> ${text}`, 'user');
    if (this.socket) {
      this.socket.emit('action', { action: 'message', text });
    }
  }

  _addChatLine(text, type = 'result') {
    const feed = document.getElementById('chat-feed');
    if (!feed) {
      console.log(`[${type}] ${text}`);
      return;
    }
    const div = document.createElement('div');
    div.className = `chat-line ${type}`;
    div.textContent = text;
    feed.appendChild(div);

    // Auto-scroll to bottom
    feed.scrollTop = feed.scrollHeight;

    // Trim old lines to prevent DOM bloat
    while (feed.children.length > 100) {
      feed.removeChild(feed.firstChild);
    }
  }

  // ── Toast Notifications ───────────────────────────────────────────
  // CONNECTS: .ck-toast-container DOM element
  // CALLED BY: Extension methods, socket error handlers

  _showToast(text, severity = 'info') {
    // Try Kit-style toast container first
    const container = document.querySelector('.ck-toast-container');
    if (container) {
      const toast = document.createElement('div');
      toast.className = 'ck-toast';
      toast.textContent = text;
      const colors = {
        danger: '#ef4444',
        success: '#22c55e',
        warning: '#f59e0b',
        info: 'var(--scene-accent, #92400e)'
      };
      toast.style.borderLeftColor = colors[severity] || colors.info;
      container.appendChild(toast);
      setTimeout(() => toast.remove(), 4000);
      return;
    }

    // Fallback — legacy toast element
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = text;
    toast.classList.remove('hidden');
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => toast.classList.add('hidden'), 4000);
  }

  // ── Helpers ───────────────────────────────────────────────────────

  _setText(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== null) {
      el.textContent = value;
    }
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Global SceneApp instance, auto-init on DOMContentLoaded
const SceneApp = new TavernScene();
document.addEventListener('DOMContentLoaded', () => SceneApp.init());
