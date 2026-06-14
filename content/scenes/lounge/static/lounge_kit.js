/**
 * THE VELVET PIT — Kit Scene Controller
 * ======================================
 *
 * Socket.IO connection, state application, heat meter, trust meter,
 * seating map, chat system, toast notifications, smoke particles,
 * and scene lifecycle. Rebuilt from lounge.js via Creation Kit pattern.
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Initial Kit-generated controller for Lounge rebuild.
 *                            LoungeScene class with _initExtensions hook for lounge_ext.js.
 *                            Ported core Socket.IO setup, state application, heat/trust meters,
 *                            seating map, smoke particles, toast system from VelvetPitScene.
 *
 * CONNECTS: Socket.IO, DOM elements, lounge_ext.js
 * CALLED BY: DOMContentLoaded
 */

'use strict';

// ── LoungeScene Class ─────────────────────────────────────────────────

class LoungeScene {
  constructor() {
    /** @type {SocketIO.Socket|null} */
    this.socket = null;
    /** @type {Object} Current scene state snapshot */
    this.state = {
      trust: 10,
      heat: 0,
      turn: 0,
      inBackRoom: false,
      currentSong: null,
      chatTarget: 'lola',
      credits: 0
    };
    /** @type {Array<{role:string, content:string}>} Chat history for context window */
    this._chatHistory = [];
    /** @type {number|null} Song progress interval timer */
    this._songTimer = null;
    /** @type {ParticleSystem3D|null} 3D smoke particle system */
    this.particles = null;
  }

  // ── Lifecycle ─────────────────────────────────────────────────────

  // v1.50.0 [2026-03-22] — Extension hook: lounge_ext.js adds methods via
  // LoungeScene.prototype._initExtensions = function() { ... }
  init() {
    this._setupSocket();
    this._setupUI();
    this._initParticles();
    this._loadInitialState();
    if (typeof this._initExtensions === 'function') this._initExtensions();
    console.debug('[VelvetPit] Initialised — Kit Rebuild v1.50.0');
  }

  // ── Socket.IO Setup ─────────────────────────────────────────────
  // CONNECTS: Flask-SocketIO server
  // EMITS: get_lounge_state on connect

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      this._addChatLine('Connected to The Velvet Pit.', 'system');
      this._loadInitialState();
    });

    this.socket.on('disconnect', () => {
      this._addChatLine('Lost connection. Reconnecting...', 'system');
    });

    // v1.49.1 [2026-03-22] — Socket.IO reconnect feedback
    this.socket.io.on('reconnect', (attempt) => {
      this._addChatLine('Reconnected after ' + attempt + ' attempt(s).', 'system');
    });
    this.socket.io.on('reconnect_attempt', (attempt) => {
      if (attempt % 3 === 0) {
        this._addChatLine('Reconnecting... (attempt ' + attempt + ')', 'system');
      }
    });
    this.socket.io.on('reconnect_error', () => {
      this._addChatLine('Reconnection failed. Retrying...', 'system');
    });

    // Full state sync
    this.socket.on('state_update', (data) => this._applyState(data));
    this.socket.on('lounge_state', (data) => {
      this._applyState(data);
      if (data.seating) this._renderSeatingMap(data.seating);
      if (data.current_event) this._renderCurrentEvent(data.current_event);
    });

    // Welcome message from server
    this.socket.on('welcome', (data) => {
      this._addChatLine(data.message || 'Welcome to The Velvet Pit.', 'system');
      if (data.state) this._applyState(data.state);
    });

    // Generic error handler
    this.socket.on('error', (data) => {
      this._showToast(data.message || 'Error', 'danger');
    });
  }

  // ── Initial State Load ──────────────────────────────────────────
  // CONNECTS: /api/status REST endpoint, Socket.IO get_lounge_state
  // CALLED BY: init(), _setupSocket on connect

  _loadInitialState() {
    // Socket.IO request
    if (this.socket) this.socket.emit('get_lounge_state');

    // REST fallback — economy balance
    fetch('/api/bench/metrics')
      .then(r => r.json())
      .then(data => {
        const bal = data.economy_balance;
        const el = document.getElementById('econ-value');
        if (el && bal !== null && bal !== undefined) el.textContent = bal;
      })
      .catch(() => {});
  }

  // ── State Application ───────────────────────────────────────────
  // CONNECTS: trust meter, heat meter, NPC moods, back room button, song display, debug panel
  // CALLED BY: state_update / lounge_state / welcome socket events

  // v1.50.0 [2026-03-22] — Unified state application from VelvetPitScene._applyState
  _applyState(data) {
    if (!data || typeof data !== 'object') return;
    this.state = { ...this.state, ...data };

    // Trust meter
    if (data.trust !== undefined) {
      const fill = document.getElementById('trust-fill');
      const val = document.getElementById('trust-value');
      if (fill) fill.style.width = `${data.trust}%`;
      if (val) val.textContent = data.trust;
    }

    // Heat meter
    if (data.heat !== undefined) this._updateHeatMeter(data.heat);

    // Turn counter
    if (data.turn !== undefined) this.state.turn = data.turn;

    // NPC moods
    if (data.lola_mood) {
      const el = document.getElementById('lola-mood');
      if (el) el.textContent = data.lola_mood;
    }
    if (data.viktor_mood) {
      const el = document.getElementById('viktor-mood');
      if (el) el.textContent = data.viktor_mood;
    }

    // Back room availability
    if (data.back_room_avail) {
      const btn = document.getElementById('btn-back-room');
      if (btn) {
        btn.disabled = false;
        btn.classList.add('unlocked');
      }
    }

    // Current song display
    if (data.current_song && data.current_song.title) {
      const el = document.getElementById('stage-song');
      if (el) el.textContent = `\u266a ${data.current_song.title}`;
    }

    // HUD badge updates (ck-hud-badge pattern)
    document.querySelectorAll('.ck-hud-badge span').forEach(el => {
      const key = el.id?.replace('badge-val-', '');
      if (key && data[key] !== undefined) el.textContent = data[key];
    });

    // Debug state panel
    const debug = document.getElementById('debug-body');
    if (debug) debug.textContent = JSON.stringify(data, null, 2);
  }

  // ── Heat Meter ──────────────────────────────────────────────────
  // CONNECTS: #heat-meter, #heat-meter-label DOM elements
  // CALLED BY: _applyState, heat_update socket handler

  /**
   * Update the heat meter bar, blending amber to crimson.
   * @param {number} level - Heat level 0-100.
   */
  // v1.50.0 [2026-03-22] — Ported from VelvetPitScene._updateHeatMeter
  _updateHeatMeter(level) {
    this.state.heat = level;
    const bar = document.getElementById('heat-meter');
    const label = document.getElementById('heat-meter-label');
    if (bar) bar.style.width = `${level}%`;
    if (label) label.textContent = `HEAT ${level}`;
    // Color shift: amber at 0, crimson at 100
    if (bar) {
      const t = level / 100;
      // Interpolate: amber #f59e0b to crimson #dc2626
      const r = Math.round(245 + (220 - 245) * t);
      const g = Math.round(158 + (38 - 158) * t);
      const b = Math.round(11 + (38 - 11) * t);
      bar.style.background = `linear-gradient(90deg, rgb(${r},${g},${b}) 0%, #dc2626 100%)`;
      bar.style.boxShadow = `0 0 ${6 + level * 0.1}px rgba(${r},${g},${b},0.6)`;
    }
  }

  // ── Seating Map ─────────────────────────────────────────────────
  // CONNECTS: .table-node DOM elements
  // CALLED BY: lounge_state / seating_update socket events

  /**
   * Render the seating map by updating table node states.
   * @param {Array<{id:string, occupied:boolean, npc:string|null, faction:string|null}>} tables
   */
  // v1.50.0 [2026-03-22] — Ported from VelvetPitScene._renderSeatingMap
  _renderSeatingMap(tables) {
    tables.forEach(t => {
      const node = document.getElementById(t.id);
      if (!node) return;
      node.classList.toggle('table-occupied', !!t.occupied);
      const lbl = node.querySelector('.table-label');
      if (lbl) {
        lbl.textContent = t.npc
          ? t.npc.slice(0, 3).toUpperCase()
          : t.label || t.id.replace('table_', 'T');
      }
      node.title = t.npc ? `${t.id}: ${t.npc}` : t.id;
      // Faction border coloring
      if (t.faction) {
        const factionColors = {
          police: '#3b82f6', gang: '#ef4444',
          neutral: '#6b7280', vip: '#f59e0b'
        };
        node.style.borderColor = factionColors[t.faction] || '';
      }
    });
  }

  // ── Current Event Renderer ──────────────────────────────────────
  // CONNECTS: #events-list DOM element
  // CALLED BY: lounge_state socket event

  _renderCurrentEvent(evt) {
    const list = document.getElementById('events-list');
    if (!list) return;
    list.innerHTML = `<div class="ck-event-item">
      <strong>${evt.title || evt.id || '\u2014'}</strong> \u2014 ${evt.desc || evt.description || ''}
    </div>`;
  }

  // ── Smoke Particles ─────────────────────────────────────────────
  // CONNECTS: ParticleSystem3D (cosysim-particles3d.js), #smoke-canvas DOM
  // CALLED BY: init()

  // v1.50.0 [2026-03-22] — Ported from VelvetPitScene._initParticles
  _initParticles() {
    const container = document.getElementById('smoke-canvas');
    if (!container) return;
    if (typeof ParticleSystem3D === 'undefined') {
      // Fallback CSS wisps when 3D unavailable
      this._addSmokeWisps(container);
      return;
    }
    try {
      this.particles = new ParticleSystem3D(container, 'smoke');
      this.particles.start();
    } catch (e) {
      console.warn('[VelvetPit] ParticleSystem3D failed, using CSS fallback:', e);
      this._addSmokeWisps(container);
    }
  }

  // v1.50.0 [2026-03-22] — CSS fallback smoke wisps
  _addSmokeWisps(container) {
    for (let i = 0; i < 4; i++) {
      const w = document.createElement('div');
      w.className = 'smoke-wisp';
      w.style.left = `${15 + i * 22}%`;
      w.style.bottom = `${10 + (i % 2) * 15}%`;
      w.style.animationDelay = `${i * 2.1}s`;
      w.style.animationDuration = `${7 + i * 1.5}s`;
      container.appendChild(w);
    }
  }

  // ── UI Wiring ───────────────────────────────────────────────────
  // CONNECTS: Chat input, target buttons, data-action buttons
  // CALLED BY: init()

  _setupUI() {
    // Chat input — Enter key sends message
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
      chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          const text = chatInput.value.trim();
          if (text) {
            this.sendMessage(text);
            chatInput.value = '';
          }
        }
      });
    }

    // Send button
    const sendBtn = document.getElementById('btn-send');
    if (sendBtn) {
      sendBtn.addEventListener('click', () => {
        const input = document.getElementById('chat-input');
        if (input) {
          const text = input.value.trim();
          if (text) {
            this.sendMessage(text);
            input.value = '';
          }
        }
      });
    }

    // Target selector buttons (Lola / Viktor)
    document.querySelectorAll('.btn-target').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.target;
        if (target) this.setTarget(target);
      });
    });

    // Generic data-action buttons
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

  // ── Action Dispatcher ───────────────────────────────────────────
  // CONNECTS: Socket.IO action event
  // CALLED BY: _setupUI, extension methods

  _action(action, data = {}) {
    if (this.socket) {
      this.socket.emit('action', { action, ...data });
    }
  }

  // ── Chat Target ─────────────────────────────────────────────────
  // CONNECTS: .btn-target DOM elements, state.chatTarget
  // CALLED BY: _setupUI click handlers, extension methods

  /** Set active chat target ('lola' or 'viktor'). */
  // v1.50.0 [2026-03-22] — Ported from VelvetPitScene.setTarget
  setTarget(target) {
    this.state.chatTarget = target;
    document.querySelectorAll('.btn-target').forEach(b => b.classList.remove('active'));
    const btn = document.querySelector(`.btn-target[data-target="${target}"]`);
    if (btn) btn.classList.add('active');
  }

  // ── Chat Messaging ──────────────────────────────────────────────
  // CONNECTS: /api/message REST endpoint, chat feed DOM, _chatHistory
  // CALLED BY: _setupUI, extension methods
  // EMITS: Chat lines, trust/heat state updates

  /** Send a chat message to the active target NPC. */
  // v1.50.0 [2026-03-22] — Ported from VelvetPitScene.sendMessage
  sendMessage(text) {
    const trimmed = (text || '').trim();
    if (!trimmed) return;

    this._addChatLine(`YOU: ${trimmed}`, 'user');
    this._chatHistory.push({ role: 'user', content: trimmed });

    fetch('/api/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: trimmed,
        target: this.state.chatTarget,
        history: this._chatHistory.slice(-10),
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.reply) {
          const speaker = data.from === 'viktor' ? 'VIKTOR' : 'LOLA';
          this._addChatLine(`${speaker}: ${data.reply}`, `from-${data.from || 'lola'}`);
          this._chatHistory.push({ role: 'assistant', content: data.reply });
        }
        if (data.trust !== undefined) {
          this._applyState({
            trust: data.trust,
            heat: data.heat,
            turn: data.turn
          });
        }
        if (data.random_event) {
          this._addEventLine(data.random_event.text || '', 'type-random');
        }
      })
      .catch(err => {
        this._addChatLine(`ERROR: ${err.message}`, 'system');
      });
  }

  // ── Chat Log ────────────────────────────────────────────────────
  // CONNECTS: #chat-feed DOM element
  // CALLED BY: sendMessage, socket event handlers, extension methods

  // v1.50.0 [2026-03-22] — Kit-standard chat line adder
  _addChatLine(text, type = 'result') {
    const feed = document.getElementById('chat-feed');
    if (!feed) {
      console.debug(`[${type}] ${text}`);
      return;
    }
    const div = document.createElement('div');
    div.className = `chat-line ${type}`;
    div.textContent = text;
    feed.appendChild(div);

    // Auto-scroll to bottom
    feed.scrollTop = feed.scrollHeight;

    // Trim old lines to prevent DOM bloat
    while (feed.children.length > 120) {
      feed.removeChild(feed.firstChild);
    }
  }

  // ── Event Feed ──────────────────────────────────────────────────
  // CONNECTS: #event-feed DOM element
  // CALLED BY: socket event handlers, extension methods

  // v1.50.0 [2026-03-22] — Ported from VelvetPitScene._addEvent
  _addEventLine(text, cls = '') {
    const feed = document.getElementById('event-feed');
    if (!feed) return;
    const div = document.createElement('div');
    div.className = `event-entry ${cls}`;
    div.textContent = text;
    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;
    if (feed.children.length > 120) feed.removeChild(feed.firstChild);
  }

  // ── Song Progress ───────────────────────────────────────────────
  // CONNECTS: #song-progress-fill DOM element, _songTimer
  // CALLED BY: song_started socket handler (in extension)

  // v1.50.0 [2026-03-22] — Ported from VelvetPitScene._startSongProgress
  _startSongProgress(durationSecs) {
    clearInterval(this._songTimer);
    const start = Date.now();
    const fill = document.getElementById('song-progress-fill');
    if (!fill) return;
    this._songTimer = setInterval(() => {
      const elapsed = (Date.now() - start) / 1000;
      const pct = Math.min(100, (elapsed / durationSecs) * 100);
      fill.style.width = `${pct}%`;
      if (pct >= 100) clearInterval(this._songTimer);
    }, 1000);
  }

  // ── Toast Notifications ─────────────────────────────────────────
  // CONNECTS: .ck-toast-container DOM element
  // CALLED BY: Extension methods, socket error handlers

  // v1.50.0 [2026-03-22] — Kit-standard toast system with severity colors
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
        info: 'var(--scene-accent, #f59e0b)'
      };
      toast.style.borderLeftColor = colors[severity] || colors.info;
      container.appendChild(toast);
      setTimeout(() => toast.remove(), 4000);
      return;
    }

    // Fallback — legacy toast container
    const legacyContainer = document.getElementById('toastContainer');
    if (!legacyContainer) return;
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = text;
    if (severity === 'danger') t.style.borderColor = '#dc2626';
    legacyContainer.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  // ── Helpers ─────────────────────────────────────────────────────

  _setText(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== null) {
      el.textContent = value;
    }
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Global SceneApp instance, auto-init on DOMContentLoaded
const SceneApp = new LoungeScene();
document.addEventListener('DOMContentLoaded', () => SceneApp.init());
