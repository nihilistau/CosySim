/**
 * THE VELVET PIT — Extension Module
 * ===================================
 *
 * Game logic extensions for the Kit-generated LoungeScene class.
 * Adds: cocktail ordering with stat effects, performance/song system,
 * trust gating for secrets/back room, NPC interaction (Lola Voss,
 * Viktor Marlowe), seating map interaction, events tonight,
 * and all Socket.IO handlers for lounge-specific events.
 *
 * All functionality ported from the original lounge.js (VelvetPitScene).
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Initial extension module, refactored from lounge.js.
 *                            LoungeScene.prototype methods, _initExtensions hook.
 *                            Full implementations: cocktails, song/performance system,
 *                            trust gating, NPC chat, seating map, back room, secrets,
 *                            economy, events tonight, all Socket.IO handlers.
 *
 * CONNECTS: LoungeScene (lounge_kit.js), Socket.IO, REST APIs
 * CALLED BY: LoungeScene.init() -> _initExtensions()
 */

'use strict';

// ── Utilities ────────────────────────────────────────────────────────

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

/**
 * HTML-escape a string to prevent XSS in chat output.
 * @param {string} str — Raw string to escape.
 * @returns {string} Escaped HTML-safe string.
 */
function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Extension Entry Point ────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Hooked by Kit-generated init() via _initExtensions
// CONNECTS: All lounge subsystems
// CALLED BY: LoungeScene.init()

LoungeScene.prototype._initExtensions = function() {
  this._initDrinkOrdering();
  this._initPerformanceSystem();
  this._initTrustGating();
  this._initSeatingInteraction();
  this._initEventsTonight();
  this._initLoungeSocket();
};

// ═════════════════════════════════════════════════════════════════════
// COCKTAIL ORDERING
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Drink menu loaded from /api/menu, rendered as
// clickable cards. Orders sent via Socket.IO order_drink event.
// CONNECTS: Socket.IO order_drink, drink_response, /api/menu REST
// CALLED BY: _initExtensions
// EMITS: order_drink socket event, chat lines, toast

LoungeScene.prototype._initDrinkOrdering = function() {
  this._loadDrinkMenu();
};

// v1.50.0 [2026-03-22] — Fetch cocktail menu from REST API and render cards
// CONNECTS: /api/menu endpoint, #drink-menu DOM
// CALLED BY: _initDrinkOrdering
LoungeScene.prototype._loadDrinkMenu = async function() {
  const menu = document.getElementById('drink-menu');
  if (!menu) return;

  try {
    const res = await fetch('/api/menu');
    const data = await res.json();
    this._renderDrinkMenu(data.cocktails || []);
  } catch {
    // Render default cocktails if API unavailable
    this._renderDefaultDrinkMenu();
  }
};

// v1.50.0 [2026-03-22] — Render cocktail cards into the drink menu
// CONNECTS: #drink-menu DOM element
// CALLED BY: _loadDrinkMenu
LoungeScene.prototype._renderDrinkMenu = function(cocktails) {
  const menu = document.getElementById('drink-menu');
  if (!menu) return;

  if (!cocktails.length) {
    this._renderDefaultDrinkMenu();
    return;
  }

  menu.innerHTML = '';
  cocktails.forEach(c => {
    const card = document.createElement('div');
    card.className = 'ck-drink-card' + (c.locked ? ' locked' : '');
    card.innerHTML = `<div class="ck-drink-card-name">${_escapeHtml(c.name)}</div>
      <div class="ck-drink-card-price">$${c.price}</div>`;

    if (!c.locked) {
      card.addEventListener('click', () => {
        this._orderDrink(c.id || c.name.toLowerCase().replace(/\s+/g, '_'));
      });
    }
    menu.appendChild(card);
  });
};

// v1.50.0 [2026-03-22] — Default cocktail menu when API is unavailable
// CONNECTS: #drink-menu DOM
LoungeScene.prototype._renderDefaultDrinkMenu = function() {
  const defaults = [
    { id: 'velvet_noir',    name: 'Velvet Noir',    price: 12, locked: false },
    { id: 'amber_smoke',    name: 'Amber Smoke',    price: 8,  locked: false },
    { id: 'crimson_tide',   name: 'Crimson Tide',   price: 15, locked: false },
    { id: 'midnight_jazz',  name: 'Midnight Jazz',  price: 10, locked: false },
    { id: 'the_informant',  name: 'The Informant',  price: 20, locked: true },
    { id: 'lolas_special',  name: "Lola's Special", price: 25, locked: true }
  ];
  this._renderDrinkMenu(defaults);
};

// v1.50.0 [2026-03-22] — Order a cocktail via Socket.IO
// CONNECTS: Socket.IO order_drink event
// EMITS: order_drink { drink }
LoungeScene.prototype._orderDrink = function(drinkId) {
  this._addChatLine(`Ordering ${drinkId.replace(/_/g, ' ')}...`, 'action');
  if (this.socket) {
    this.socket.emit('order_drink', { drink: drinkId });
  }
};

// ═════════════════════════════════════════════════════════════════════
// PERFORMANCE / SONG SYSTEM
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Song progress bar, song started/ended events,
// stage display updates. Lola performs songs that affect mood.
// CONNECTS: Socket.IO song_started / song_ended, #stage-song, song progress DOM
// CALLED BY: _initExtensions
// EMITS: Event feed entries

LoungeScene.prototype._initPerformanceSystem = function() {
  // Performance system is primarily driven by Socket.IO events
  // registered in _initLoungeSocket. This method sets up any
  // UI interaction for requesting songs.

  const requestBtn = document.getElementById('btn-request-song');
  if (requestBtn) {
    requestBtn.addEventListener('click', () => this._requestSong());
  }
};

// v1.50.0 [2026-03-22] — Request a song from Lola via Socket.IO
// CONNECTS: Socket.IO request_song event
// EMITS: request_song event
LoungeScene.prototype._requestSong = function() {
  if (this.state.trust < 30) {
    this._showToast('Lola barely notices you. Earn more trust.', 'warning');
    return;
  }
  this._addChatLine('You signal Lola for a special number...', 'action');
  if (this.socket) {
    this.socket.emit('request_song');
  }
};

// v1.50.0 [2026-03-22] — Handle a song starting event
// CONNECTS: #stage-song DOM, song progress bar, event feed
// CALLED BY: song_started socket handler
LoungeScene.prototype._handleSongStarted = function(data) {
  const song = data.song || {};
  const el = document.getElementById('stage-song');
  if (el) el.textContent = `\u266a ${song.title || '\u2014'}`;
  this._addEventLine(
    `\u266a ${song.title || 'Unknown'} \u2014 ${song.note || ''}`,
    'type-random'
  );
  this.state.currentSong = song;
  this._startSongProgress(song.duration || 120);
};

// v1.50.0 [2026-03-22] — Handle a song ending event
// CONNECTS: song progress bar, event feed
// CALLED BY: song_ended socket handler
LoungeScene.prototype._handleSongEnded = function(data) {
  this._addEventLine(`\u266a "${data.title || 'Unknown'}" ends.`, 'type-random');
  clearInterval(this._songTimer);
  const fill = document.getElementById('song-progress-fill');
  if (fill) fill.style.width = '0%';
  this.state.currentSong = null;
};

// ═════════════════════════════════════════════════════════════════════
// TRUST GATING — SECRETS & BACK ROOM
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Trust-gated interactions: ask for secrets
// (requires trust >= threshold), enter back room (requires explicit unlock).
// CONNECTS: /api/ask_secret, /api/back_room REST, overlays
// CALLED BY: _initExtensions
// EMITS: Toast, overlay display

LoungeScene.prototype._initTrustGating = function() {
  // Ask Secret button
  const secretBtn = document.getElementById('btn-ask-secret');
  if (secretBtn) {
    secretBtn.addEventListener('click', () => this._askSecret('lola'));
  }

  // Back Room button
  const backRoomBtn = document.getElementById('btn-back-room');
  if (backRoomBtn) {
    backRoomBtn.addEventListener('click', () => this._enterBackRoom());
  }

  // Overlay dismiss buttons
  $$('.ck-overlay .ck-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const overlay = btn.closest('.ck-overlay');
      if (overlay) overlay.classList.add('hidden');
    });
  });
};

// v1.50.0 [2026-03-22] — Ask an NPC for a secret
// CONNECTS: /api/ask_secret REST endpoint, #secret-overlay DOM
// EMITS: Overlay display, toast on failure
LoungeScene.prototype._askSecret = async function(target) {
  try {
    const res = await fetch('/api/ask_secret', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character: target }),
    });
    const data = await res.json();
    if (data.ok) {
      this._setText('secret-title', data.secret || 'A Secret');
      this._setText('secret-content', data.content || '...');
      const overlay = document.getElementById('secret-overlay');
      if (overlay) overlay.classList.remove('hidden');
    } else {
      this._showToast(data.error || 'Not now.', 'warning');
    }
  } catch {
    this._showToast('Failed to ask for secret.', 'danger');
  }
};

// v1.50.0 [2026-03-22] — Enter the back room (trust-gated)
// CONNECTS: /api/back_room REST endpoint, #back-room-overlay DOM
// EMITS: Overlay display, toast on failure
LoungeScene.prototype._enterBackRoom = async function() {
  try {
    const res = await fetch('/api/back_room', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      const overlay = document.getElementById('back-room-overlay');
      if (overlay) overlay.classList.remove('hidden');
      this.state.inBackRoom = true;
    } else {
      this._showToast(data.error || 'Access denied.', 'danger');
    }
  } catch {
    this._showToast('Failed to enter back room.', 'danger');
  }
};

// ═════════════════════════════════════════════════════════════════════
// SEATING MAP INTERACTION
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Table approach via Socket.IO. Clicking a table
// node emits approach_table with the table ID.
// CONNECTS: Socket.IO approach_table event, .table-node DOM elements
// CALLED BY: _initExtensions
// EMITS: approach_table socket event

LoungeScene.prototype._initSeatingInteraction = function() {
  // Wire table click handlers (replace inline onclick from original)
  $$('.table-node').forEach(node => {
    node.addEventListener('click', () => {
      const tableId = node.dataset.id || node.id;
      this._approachTable(tableId);
    });
  });
};

// v1.50.0 [2026-03-22] — Approach a table via Socket.IO
// CONNECTS: Socket.IO approach_table event
// EMITS: approach_table { table_id }
LoungeScene.prototype._approachTable = function(tableId) {
  this._addChatLine(`Approaching ${tableId}...`, 'action');
  if (this.socket) {
    this.socket.emit('approach_table', { table_id: tableId });
  }
};

// ═════════════════════════════════════════════════════════════════════
// EVENTS TONIGHT
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Load and render tonight's scheduled events.
// CONNECTS: Socket.IO get_events_tonight / events_tonight
// CALLED BY: _initExtensions
// EMITS: get_events_tonight socket event

LoungeScene.prototype._initEventsTonight = function() {
  if (this.socket) {
    this.socket.emit('get_events_tonight');
  }
};

// v1.50.0 [2026-03-22] — Render tonight's events into the events list
// CONNECTS: #events-list DOM element
// CALLED BY: events_tonight socket handler
LoungeScene.prototype._renderEventsTonight = function(events) {
  const list = document.getElementById('events-list');
  if (!list) return;

  if (!events || !events.length) {
    list.innerHTML = '<div class="ck-event-item">Nothing on the board yet.</div>';
    return;
  }

  list.innerHTML = events.map(e =>
    `<div class="ck-event-item">
      <strong>${_escapeHtml(e.title || e.id)}</strong>${e.desc ? ' \u2014 ' + _escapeHtml(e.desc) : ''}
    </div>`
  ).join('');
};

// ═════════════════════════════════════════════════════════════════════
// SOCKET.IO — LOUNGE-SPECIFIC EVENT HANDLERS
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — All lounge-specific Socket.IO handlers.
// Ported from VelvetPitScene._setupSocket event bindings.
// CONNECTS: Socket.IO server events
// CALLED BY: _initExtensions

LoungeScene.prototype._initLoungeSocket = function() {
  if (!this.socket) return;

  // ── Heat update ──────────────────────────────────────────
  this.socket.on('heat_update', (data) => {
    if (data.heat !== undefined) this._updateHeatMeter(data.heat);
  });

  // ── Song lifecycle ───────────────────────────────────────
  this.socket.on('song_started', (data) => {
    this._handleSongStarted(data);
  });

  this.socket.on('song_ended', (data) => {
    this._handleSongEnded(data);
  });

  // ── Lounge ambient events ────────────────────────────────
  this.socket.on('lounge_event', (data) => {
    this._addEventLine(
      data.text || '',
      `type-${data.event_type || 'random'}`
    );
  });

  // ── Back room unlock ─────────────────────────────────────
  this.socket.on('back_room_unlocked', () => {
    const btn = document.getElementById('btn-back-room');
    if (btn) {
      btn.disabled = false;
      btn.classList.add('unlocked');
    }
    this._showToast('The back room is now available.', 'success');
  });

  // ── Seating map update ───────────────────────────────────
  this.socket.on('seating_update', (data) => {
    if (data.tables) this._renderSeatingMap(data.tables);
  });

  // ── Table approach response ──────────────────────────────
  this.socket.on('table_response', (data) => {
    if (data.message) this._addEventLine(data.message, 'type-random');
  });

  // ── Drink order response ─────────────────────────────────
  // CONNECTS: Drink ordering system, event feed, toast
  this.socket.on('drink_response', (data) => {
    if (data.ok) {
      this._addEventLine(
        `\u2193 ${_escapeHtml(data.drink)} \u2014 "${_escapeHtml(data.viktor || '')}"`,
        'type-drink_served'
      );
      this._showToast(data.drink, 'success');

      // Apply stat effects if provided
      if (data.effects && typeof data.effects === 'object') {
        for (const [stat, delta] of Object.entries(data.effects)) {
          const current = this.state[stat] ?? 0;
          this.state[stat] = Math.min(100, Math.max(0, current + delta));
        }
        // Trust effect is common
        if (data.effects.trust !== undefined) {
          const newTrust = Math.min(100, Math.max(0, this.state.trust + data.effects.trust));
          this.state.trust = newTrust;
          this._applyState({ trust: newTrust });
        }
      }
    } else {
      this._addEventLine(data.error || 'Order refused.', 'type-rule');
      this._showToast(data.error || 'Order refused.', 'warning');
    }
  });

  // ── Events tonight response ──────────────────────────────
  this.socket.on('events_tonight', (data) => {
    if (data.events) this._renderEventsTonight(data.events);
  });

  // ── Narrative update ─────────────────────────────────────
  this.socket.on('narrative_update', (data) => {
    if (data.text) this._addEventLine(data.text, 'type-rule');
  });

  // ── NPC chat message (from server-side agent processing) ──
  this.socket.on('chat_message', (data) => {
    const sender = data.sender || data.character || 'NPC';
    const text = data.text || data.message || '';
    if (text) {
      this._addChatLine(`${sender}: ${text}`, 'result');
    }
  });

  // ── Streamed response chunks ─────────────────────────────
  this.socket.on('stream_chunk', (data) => {
    const text = data.text || data.chunk || '';
    if (text) this._appendToLastLine(text);
  });

  this.socket.on('stream_end', () => {
    // No-op — the line is already complete from chunks
  });

  // ── Character action tags (from stream processor) ────────
  this.socket.on('action_tag', (data) => {
    if (data.action) {
      this._addChatLine(`* ${data.action} *`, 'system');
    }
  });

  // ── HUD update (credits, heat, etc.) ─────────────────────
  this.socket.on('hud_update', (data) => {
    if (data.credits !== undefined) {
      this._setText('econ-value', data.credits);
      if (this.state) this.state.credits = data.credits;
    }
    if (data.heat !== undefined) {
      this._updateHeatMeter(Math.round(data.heat));
    }
    if (data.trust !== undefined) {
      this._applyState({ trust: data.trust });
    }
  });

  // ── World event (from global sim) ────────────────────────
  this.socket.on('world_event', (data) => {
    const title = data.title || 'City Event';
    this._showToast(`\u26A1 ${title}`);
    this._addEventLine(`\u26A1 ${title}: ${data.text || ''}`, 'type-rule');
  });
};

// ── Streaming helper ─────────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Append text to the last chat line (for streaming)
// CONNECTS: #chat-feed DOM
// CALLED BY: stream_chunk socket handler

LoungeScene.prototype._appendToLastLine = function(text) {
  const feed = document.getElementById('chat-feed');
  if (!feed) return;

  let lastLine = feed.lastElementChild;
  if (!lastLine || !lastLine.classList.contains('streaming')) {
    // Create a new streaming line
    lastLine = document.createElement('div');
    lastLine.className = 'chat-line result streaming';
    feed.appendChild(lastLine);
  }
  lastLine.textContent += text;
  feed.scrollTop = feed.scrollHeight;
};
