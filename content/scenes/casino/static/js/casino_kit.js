/**
 * CLUB NOIR — Kit Scene Controller
 * ==================================
 *
 * Socket.IO connection, state application, balance/phase updaters,
 * chat log, toast notifications, bench HUD, and scene lifecycle.
 * Generated from casino_rebuild.json layout via Creation Kit pattern.
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Initial Kit-generated controller for Casino rebuild.
 *                            CasinoScene class with _initExtensions hook for casino_ext.js.
 *
 * CONNECTS: Socket.IO, DOM elements, casino_ext.js
 * CALLED BY: DOMContentLoaded
 */

'use strict';

// ── CasinoScene Class ─────────────────────────────────────────────────

class CasinoScene {
  constructor() {
    /** @type {SocketIO.Socket|null} */
    this.socket = null;
    /** @type {Object} Current scene state snapshot */
    this.state = {};
    /** @type {number|null} Previous balance for delta display */
    this._prevBalance = null;
    /** @type {number|null} Toast dismiss timer */
    this._toastTimer = null;
    /** @type {number|null} Flash overlay dismiss timer */
    this._flashTimer = null;
  }

  // ── Lifecycle ─────────────────────────────────────────────────────

  // v1.50.0 [2026-03-22] — Extension hook: casino_ext.js adds methods via
  // CasinoScene.prototype._initExtensions = function() { ... }
  init() {
    this._setupSocket();
    this._setupUI();
    this._setupBenchPolling();
    this._loadInitialState();
    if (typeof this._initExtensions === 'function') this._initExtensions();
    console.log('[ClubNoir] Scene initialised (Kit v1.50)');
  }

  // ── Socket.IO Setup ───────────────────────────────────────────────
  // CONNECTS: Flask-SocketIO server
  // EMITS: get_casino_state on connect

  // v1.50.0 [2026-03-22] — Kit Socket.IO setup with core event wiring
  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      this._addChatLine('Connected to Club Noir.', 'system');
      this._loadInitialState();
    });

    this.socket.on('disconnect', () => {
      this._addChatLine('Lost connection. Reconnecting...', 'system');
      this._setPhase('DISCONNECTED');
    });

    // Full state sync
    this.socket.on('state_update', (data) => this._applyState(data));
    this.socket.on('casino_state', (data) => this._applyCasinoState(data));

    // Generic error handler
    this.socket.on('error', (data) => {
      const msg = data.message || data.error || 'An error occurred';
      console.warn('[ClubNoir] Server error:', msg);
      this._showToast(msg, 'danger');
    });
  }

  // ── Initial State Load ────────────────────────────────────────────
  // CONNECTS: Socket.IO get_casino_state, /api/status REST fallback
  // CALLED BY: init(), _setupSocket on connect

  // v1.50.0 [2026-03-22] — Socket.IO + REST fallback state load
  _loadInitialState() {
    // Socket.IO request
    if (this.socket) this.socket.emit('get_casino_state');

    // REST fallback
    fetch('/api/status')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) this._applyState(data); })
      .catch(() => {});
  }

  // ── State Application ─────────────────────────────────────────────
  // CONNECTS: HUD badges, balance display, phase badge
  // CALLED BY: state_update / casino_state socket events, _loadInitialState

  // v1.50.0 [2026-03-22] — Generic state application (HUD badges)
  _applyState(state) {
    if (!state || typeof state !== 'object') return;
    this.state = { ...this.state, ...state };

    // HUD badge updates (ck-hud-badge pattern)
    document.querySelectorAll('.ck-hud-badge span').forEach(el => {
      const key = el.id?.replace('badge-val-', '');
      if (key && state[key] !== undefined) el.textContent = state[key];
    });

    // Balance updates
    if (state.balance !== undefined) {
      this._updateBalance(state.balance, null);
    }
  }

  // v1.50.0 [2026-03-22] — Casino-specific state application
  // CONNECTS: balance, blackjack state, transactions, consequences
  // CALLED BY: casino_state socket event
  _applyCasinoState(data) {
    if (!data) return;
    this._updateBalance(data.balance, null);
    if (data.blackjack) this._applyBlackjackState(data.blackjack);
    this._renderTransactions(data.transactions || []);
    this._updateConsequences(data.consequences_pending || 0);
    this._setHeaderTable(data.active_game || 'LOBBY');
  }

  // v1.50.0 [2026-03-22] — Blackjack state application stub
  // Overridden by casino_ext.js with full implementation
  // CONNECTS: card rendering, pot, action buttons
  _applyBlackjackState(data) {
    // Extension provides full implementation via prototype override
    if (data.phase) this._setPhase(data.phase.toUpperCase());
  }

  // ── UI Wiring ─────────────────────────────────────────────────────
  // CONNECTS: Chat form, generic button handlers
  // CALLED BY: init()

  // v1.50.0 [2026-03-22] — Chat input wiring
  _setupUI() {
    // Chat input — Enter key sends message
    const chatInput = document.getElementById('chat-msg');
    if (chatInput) {
      chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.sendMessage();
        }
      });
    }

    // Generic button wiring — buttons with data-action emit action events
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

  // ── Bench HUD Polling ─────────────────────────────────────────────
  // CONNECTS: /api/bench/metrics REST, bench DOM elements
  // CALLED BY: init()

  // v1.50.0 [2026-03-22] — Periodic bench metrics polling
  _setupBenchPolling() {
    const poll = () => {
      fetch('/api/bench/metrics')
        .then(r => r.ok ? r.json() : null)
        .then(d => d && this._updateBench(d))
        .catch(() => {});
    };
    poll();
    setInterval(poll, 4000);
  }

  // v1.50.0 [2026-03-22] — Update bench HUD display elements
  _updateBench(d) {
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    set('bench-ms', d.response_ms ? `${d.response_ms}ms` : '--ms');
    set('bench-model', d.model_id || '--');
    set('bench-tokens', d.tokens_out ? `${d.tokens_out} tok` : '--');
    set('bench-nexus', d.nexus_tier || '--');
  }

  // ── Action Dispatcher ─────────────────────────────────────────────
  // CONNECTS: Socket.IO action event
  // CALLED BY: _setupUI, extension methods

  // v1.50.0 [2026-03-22] — Generic action emitter
  _action(action, data = {}) {
    if (this.socket) {
      this.socket.emit('action', { action, ...data });
    }
  }

  // ── Balance Display ───────────────────────────────────────────────
  // CONNECTS: #credits-main, #balance-display, #credits-delta DOM
  // CALLED BY: _applyCasinoState, extension event handlers

  // v1.50.0 [2026-03-22] — Animate balance updates with delta flash
  _updateBalance(amount, delta) {
    if (amount === null || amount === undefined) return;
    const formatted = `$${Number(amount).toLocaleString()}`;

    // Update all balance display elements
    ['credits-main', 'balance-display'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = formatted;
    });

    // Delta flash animation
    const deltaEl = document.getElementById('credits-delta');
    if (deltaEl && delta !== null && delta !== undefined) {
      deltaEl.textContent = delta > 0 ? `+$${delta}` : `-$${Math.abs(delta)}`;
      deltaEl.className = 'cn-credits-delta ' + (delta >= 0 ? 'positive' : 'negative');
      setTimeout(() => {
        deltaEl.textContent = '';
        deltaEl.className = 'cn-credits-delta';
      }, 3000);
    }
    this._prevBalance = amount;
  }

  // ── Phase & Header ────────────────────────────────────────────────
  // CONNECTS: #phase-badge, #table-name-display DOM
  // CALLED BY: _applyBlackjackState, extension event handlers

  // v1.50.0 [2026-03-22] — Phase badge updater
  _setPhase(phase) {
    const badge = document.getElementById('phase-badge');
    if (badge) badge.textContent = phase;
  }

  // v1.50.0 [2026-03-22] — Header table name updater
  _setHeaderTable(name) {
    const el = document.getElementById('table-name-display');
    if (el) el.textContent = name;
  }

  // ── Transactions & Consequences ───────────────────────────────────
  // CONNECTS: #tx-list, #consequence-area DOM
  // CALLED BY: _applyCasinoState, extension event handlers

  // v1.50.0 [2026-03-22] — Render transaction ledger
  _renderTransactions(txs) {
    const list = document.getElementById('tx-list');
    if (!list || !txs || !txs.length) return;
    list.innerHTML = '';
    [...txs].reverse().forEach(tx => {
      const li = document.createElement('li');
      li.className = `cn-tx cn-tx--${tx.type}`;
      const sign = tx.type === 'credit' ? '+' : '-';
      li.innerHTML =
        `<span>${(tx.reason || '').split(':')[0]}</span><span>${sign}$${tx.amount}</span>`;
      list.appendChild(li);
    });
  }

  // v1.50.0 [2026-03-22] — Update consequences/debts display
  _updateConsequences(count) {
    const area = document.getElementById('consequence-area');
    if (!area) return;
    area.innerHTML = count > 0
      ? `<span class="consequence-badge">\u26A0 ${count} PENDING</span>`
      : '<span class="cn-no-debts">All clear\u2026 for now.</span>';
  }

  // ── Chat ──────────────────────────────────────────────────────────
  // CONNECTS: #chat-log DOM element, Socket.IO chat_message action
  // CALLED BY: _setupUI, extension methods, socket event handlers

  // v1.50.0 [2026-03-22] — Send chat message to server
  sendMessage(text) {
    const inp = document.getElementById('chat-msg');
    const msg = text || (inp ? inp.value.trim() : '');
    if (!msg) return;
    const target = document.getElementById('chat-target')?.value || 'dealer_jack';
    this.socket.emit('chat_message', { message: msg, target });
    this._appendChat('You', msg);
    if (inp) inp.value = '';
  }

  // v1.50.0 [2026-03-22] — Append formatted chat entry to log
  _appendChat(who, text) {
    const log = document.getElementById('chat-log');
    if (!log) return;
    const entry = document.createElement('div');
    entry.className = 'cn-chat-entry';
    entry.innerHTML =
      `<span class="cn-chat-who">${who}:</span> <span class="cn-chat-text">${text}</span>`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;

    // Trim old entries to prevent DOM bloat
    while (log.children.length > 100) {
      log.removeChild(log.firstChild);
    }
  }

  // v1.50.0 [2026-03-22] — Add typed chat line (system, action, result, user)
  _addChatLine(text, type = 'result') {
    const log = document.getElementById('chat-log');
    if (!log) {
      console.log(`[${type}] ${text}`);
      return;
    }
    const div = document.createElement('div');
    div.className = `cn-chat-entry cn-chat-entry--${type}`;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;

    while (log.children.length > 100) {
      log.removeChild(log.firstChild);
    }
  }

  // ── Toast Notifications ───────────────────────────────────────────
  // CONNECTS: .ck-toast-container DOM element
  // CALLED BY: Extension methods, socket error handlers

  // v1.50.0 [2026-03-22] — Kit-style toast notifications
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
        info: 'var(--scene-accent, #f97316)'
      };
      toast.style.borderLeftColor = colors[severity] || colors.info;
      container.appendChild(toast);
      setTimeout(() => toast.remove(), 4000);
      return;
    }

    // Fallback — consequence toast element
    const fallback = document.getElementById('consequence-toast');
    if (!fallback) return;
    const msg = document.getElementById('consequence-msg');
    if (msg) msg.textContent = text;
    fallback.style.display = 'flex';
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      fallback.style.display = 'none';
    }, 4000);
  }

  // ── Helpers ───────────────────────────────────────────────────────

  // v1.50.0 [2026-03-22] — Safe text setter
  _setText(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== null) {
      el.textContent = value;
    }
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Global SceneApp + window._casino for onclick compat
const SceneApp = new CasinoScene();
window._casino = SceneApp;
document.addEventListener('DOMContentLoaded', () => SceneApp.init());
