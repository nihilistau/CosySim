/* ══════════════════════════════════════════════════════════════════════
   THE VELVET PIT — Frontend v0.68 'Dark Renaissance'
   VelvetPitScene class wires SocketIO, particles, heat meter, seating map.
══════════════════════════════════════════════════════════════════════ */

'use strict';

class VelvetPitScene {
  /**
   * Main controller for The Velvet Pit lounge scene.
   * Owns SocketIO connection, ParticleSystem3D smoke, heat meter,
   * seating map rendering, and NPC chat.
   */
  constructor() {
    this.socket     = null;
    this.particles  = null;
    this.state      = {
      trust       : 10,
      heat        : 0,
      turn        : 0,
      inBackRoom  : false,
      currentSong : null,
      chatTarget  : 'lola',
    };
    this._chatHistory = [];
    this._songTimer   = null;
  }

  /** Initialise scene — call once DOM is ready. */
  init() {
    this._setupSocket();
    this._initParticles();
    this.loadState();
    this._loadDrinkMenu();
    this._loadEventsTonight();
    this._initEconomy();
    console.log('[VelvetPit] Initialised — Dark Renaissance v0.68');
  }

  // ── Socket.IO ────────────────────────────────────────────────────────

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      console.log('[VelvetPit] connected');
      this.socket.emit('get_lounge_state');
    });

    this.socket.on('welcome', (data) => {
      this._addChat('VELVET PIT', data.message, 'system');
      if (data.state) this._applyState(data.state);
    });

    this.socket.on('lounge_state', (data) => {
      this._applyState(data);
      if (data.seating)       this._renderSeatingMap(data.seating);
      if (data.current_event) this._renderEvent(data.current_event);
    });

    this.socket.on('state_update', (data) => this._applyState(data));

    this.socket.on('heat_update', (data) => {
      if (data.heat !== undefined) this._updateHeatMeter(data.heat);
    });

    this.socket.on('song_started', (data) => {
      const song = data.song || {};
      const el = document.getElementById('stageSong');
      if (el) el.textContent = `\u266a ${song.title || '\u2014'}`;
      this._addEvent(`\u266a ${song.title} \u2014 ${song.note || ''}`, 'type-random');
      this.state.currentSong = song;
      this._startSongProgress(song.duration || 120);
    });

    this.socket.on('song_ended', (data) => {
      this._addEvent(`\u266a "${data.title}" ends.`, 'type-random');
      clearInterval(this._songTimer);
      const fill = document.getElementById('songProgressFill');
      if (fill) fill.style.width = '0%';
    });

    this.socket.on('lounge_event', (data) => {
      this._addEvent(data.text || '', `type-${data.event_type || 'random'}`);
    });

    this.socket.on('back_room_unlocked', () => {
      const btn = document.getElementById('btnBackRoom');
      if (btn) { btn.disabled = false; btn.classList.add('unlocked'); }
      this._toast('The back room is now available.', false);
    });

    this.socket.on('seating_update', (data) => {
      if (data.tables) this._renderSeatingMap(data.tables);
    });

    this.socket.on('table_response', (data) => {
      if (data.message) this._addEvent(data.message, 'type-random');
    });

    this.socket.on('drink_response', (data) => {
      if (data.ok) {
        this._addEvent(`\ud83e\udc43 ${data.drink} \u2014 "${data.viktor}"`, 'type-drink_served');
        this._toast(data.drink, false);
      } else {
        this._addEvent(data.error || 'Order refused.', 'type-rule');
      }
    });

    this.socket.on('events_tonight', (data) => {
      if (data.events) this._renderEventsTonight(data.events);
    });

    this.socket.on('narrative_update', (data) => {
      if (data.text) this._addEvent(data.text, 'type-rule');
    });
  }

  // ── Particles ────────────────────────────────────────────────────────

  _initParticles() {
    const container = document.getElementById('smokeCanvas');
    if (!container) return;
    if (typeof ParticleSystem3D === 'undefined') {
      // Fallback CSS wisps
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

  // ── State ─────────────────────────────────────────────────────────────

  /** Load full lounge state from server. */
  loadState() {
    this.socket.emit('get_lounge_state');
  }

  _applyState(data) {
    if (data.trust !== undefined) {
      this.state.trust = data.trust;
      const fill = document.getElementById('trustFill');
      const val  = document.getElementById('trustValue');
      if (fill) fill.style.width = `${data.trust}%`;
      if (val)  val.textContent  = data.trust;
    }
    if (data.heat !== undefined) this._updateHeatMeter(data.heat);
    if (data.turn !== undefined) this.state.turn = data.turn;
    if (data.lola_mood)   { const el = document.getElementById('lolaMood');   if (el) el.textContent = data.lola_mood;   }
    if (data.viktor_mood) { const el = document.getElementById('viktorMood'); if (el) el.textContent = data.viktor_mood; }
    if (data.back_room_avail) {
      const btn = document.getElementById('btnBackRoom');
      if (btn) btn.disabled = false;
    }
    if (data.current_song) {
      const el = document.getElementById('stageSong');
      if (el && data.current_song.title) el.textContent = `\u266a ${data.current_song.title}`;
    }
    const debug = document.getElementById('debugBody');
    if (debug) debug.textContent = JSON.stringify(data, null, 2);
  }

  // ── Heat Meter ────────────────────────────────────────────────────────

  /**
   * Update the heat meter bar, blending amber to crimson.
   * @param {number} level - Heat level 0-100.
   */
  _updateHeatMeter(level) {
    this.state.heat = level;
    const bar   = document.getElementById('heatMeter');
    const label = document.getElementById('heatMeterLabel');
    if (bar)   bar.style.width = `${level}%`;
    if (label) label.textContent = `HEAT ${level}`;
    // Color shift: amber at 0, crimson at 100
    if (bar) {
      const t = level / 100;
      // interpolate: amber #f59e0b to crimson #dc2626
      const r = Math.round(245 + (220 - 245) * t);
      const g = Math.round(158 + ( 38 - 158) * t);
      const b = Math.round( 11 + ( 38 -  11) * t);
      bar.style.background = `linear-gradient(90deg, rgb(${r},${g},${b}) 0%, #dc2626 100%)`;
      bar.style.boxShadow  = `0 0 ${6 + level * 0.1}px rgba(${r},${g},${b},0.6)`;
    }
  }

  // ── Seating Map ───────────────────────────────────────────────────────

  /**
   * Render the seating map by updating table node states.
   * @param {Array<{id:string, occupied:boolean, npc:string|null, faction:string|null}>} tables
   */
  _renderSeatingMap(tables) {
    tables.forEach(t => {
      const node = document.getElementById(t.id);
      if (!node) return;
      node.classList.toggle('table-occupied', !!t.occupied);
      const lbl = node.querySelector('.table-label');
      if (lbl) lbl.textContent = t.npc ? t.npc.slice(0, 3).toUpperCase() : t.label || t.id.replace('table_', 'T');
      node.title = t.npc ? `${t.id}: ${t.npc}` : t.id;
      if (t.faction) {
        const factionColors = { police: '#3b82f6', gang: '#ef4444', neutral: '#6b7280', vip: '#f59e0b' };
        node.style.borderColor = factionColors[t.faction] || '';
      }
    });
  }

  // ── Table approach ────────────────────────────────────────────────────

  /** Emit approach_table via SocketIO. */
  approachTable(tableId) {
    this.socket.emit('approach_table', { table_id: tableId });
  }

  // ── Drinks ────────────────────────────────────────────────────────────

  /** Order a drink via SocketIO. */
  orderDrink(drink) {
    this.socket.emit('order_drink', { drink });
  }

  _loadDrinkMenu() {
    fetch('/api/menu')
      .then(r => r.json())
      .then(data => {
        const menu = document.getElementById('drinkMenu');
        if (!menu) return;
        menu.innerHTML = '';
        (data.cocktails || []).forEach(c => {
          const card = document.createElement('div');
          card.className = 'drink-card' + (c.locked ? ' locked' : '');
          card.innerHTML = `<div class="drink-card-name">${c.name}</div><div class="drink-card-price">$${c.price}</div>`;
          if (!c.locked) card.onclick = () => this.orderDrink(c.id || c.name.toLowerCase().replace(' ', '_'));
          menu.appendChild(card);
        });
      })
      .catch(() => {});
  }

  // ── Events tonight ────────────────────────────────────────────────────

  _loadEventsTonight() {
    this.socket.emit('get_events_tonight');
  }

  _renderEvent(evt) {
    const list = document.getElementById('eventsList');
    if (!list) return;
    list.innerHTML = `<div class="event-item"><strong>${evt.title || evt.id || '\u2014'}</strong> \u2014 ${evt.desc || evt.description || ''}</div>`;
  }

  _renderEventsTonight(events) {
    const list = document.getElementById('eventsList');
    if (!list) return;
    if (!events.length) { list.innerHTML = '<div class="event-item">Nothing on the board yet.</div>'; return; }
    list.innerHTML = events.map(e =>
      `<div class="event-item"><strong>${e.title || e.id}</strong>${e.desc ? ' \u2014 ' + e.desc : ''}</div>`
    ).join('');
  }

  // ── Economy ───────────────────────────────────────────────────────────

  _initEconomy() {
    fetch('/api/bench/metrics')
      .then(r => r.json())
      .then(data => {
        const bal = data.economy_balance;
        const el  = document.getElementById('econValue');
        if (el && bal !== null && bal !== undefined) el.textContent = bal;
      })
      .catch(() => {});
  }

  // ── Chat ──────────────────────────────────────────────────────────────

  /** Set active chat target ('lola' or 'viktor'). */
  setTarget(target) {
    this.state.chatTarget = target;
    document.querySelectorAll('.btn-target').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById(target === 'lola' ? 'btnTargetLola' : 'btnTargetViktor');
    if (btn) btn.classList.add('active');
  }

  /** Send a chat message to the active target NPC. */
  sendMessage(text) {
    const trimmed = (text || '').trim();
    if (!trimmed) return;
    const input = document.getElementById('chatInput');
    if (input) input.value = '';

    this._addChat('YOU', trimmed, 'from-guest');
    this._chatHistory.push({ role: 'user', content: trimmed });

    fetch('/api/message', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        message: trimmed,
        target:  this.state.chatTarget,
        history: this._chatHistory.slice(-10),
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.reply) {
          const speaker = data.from === 'viktor' ? 'VIKTOR' : 'LOLA';
          this._addChat(speaker, data.reply, `from-${data.from || 'lola'}`);
          this._chatHistory.push({ role: 'assistant', content: data.reply });
        }
        if (data.trust !== undefined) this._applyState({ trust: data.trust, heat: data.heat, turn: data.turn });
        if (data.random_event) this._addEvent(data.random_event.text || '', 'type-random');
      })
      .catch(err => { this._addChat('ERROR', err.message, 'type-rule'); });
  }

  // ── Song progress ─────────────────────────────────────────────────────

  _startSongProgress(durationSecs) {
    clearInterval(this._songTimer);
    const start = Date.now();
    const fill  = document.getElementById('songProgressFill');
    if (!fill) return;
    this._songTimer = setInterval(() => {
      const elapsed = (Date.now() - start) / 1000;
      const pct     = Math.min(100, (elapsed / durationSecs) * 100);
      fill.style.width = `${pct}%`;
      if (pct >= 100) clearInterval(this._songTimer);
    }, 1000);
  }

  // ── Helpers ───────────────────────────────────────────────────────────

  _addChat(speaker, text, cls) {
    const win = document.getElementById('chatWindow');
    if (!win) return;
    const div = document.createElement('div');
    div.className = `chat-line ${cls}`;
    div.innerHTML = `<div class="chat-speaker">${speaker}</div><div>${_escapeHtml(text)}</div>`;
    win.appendChild(div);
    win.scrollTop = win.scrollHeight;
  }

  _addEvent(text, cls) {
    const feed = document.getElementById('eventFeed');
    if (!feed) return;
    const div = document.createElement('div');
    div.className = `event-entry ${cls}`;
    div.textContent = text;
    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;
    if (feed.children.length > 120) feed.removeChild(feed.firstChild);
  }

  _toast(msg, isError) {
    const c = document.getElementById('toastContainer');
    if (!c) return;
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    if (isError) t.style.borderColor = '#dc2626';
    c.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }
}

// ── Globals (kept for onclick= compatibility) ───────────────────────

function askSecret(target) {
  fetch('/api/ask_secret', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ character: target }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        document.getElementById('secretTitle').textContent   = data.secret;
        document.getElementById('secretContent').textContent = data.content;
        document.getElementById('secretOverlay').style.display = 'flex';
      } else {
        scene._toast(data.error || 'Not now.', true);
      }
    })
    .catch(() => {});
}

function enterBackRoom() {
  fetch('/api/back_room', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        document.getElementById('backRoomOverlay').style.display = 'flex';
      } else {
        scene._toast(data.error || 'Access denied.', true);
      }
    })
    .catch(() => {});
}

function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Boot ──────────────────────────────────────────────────────────────

const scene = new VelvetPitScene();
document.addEventListener('DOMContentLoaded', () => scene.init());
