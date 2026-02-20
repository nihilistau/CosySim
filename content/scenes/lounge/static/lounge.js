/* ══════════════════════════════════════════════════════════════════════
   THE VELVET LOUNGE — Frontend Logic
   Connects via SocketIO to the LoungeScene Flask/SocketIO server.
   Manages: state display, chat, drinks, songs, secrets, heat/trust meters.
══════════════════════════════════════════════════════════════════════ */

'use strict';

// ── SOCKET ───────────────────────────────────────────────────────────────
const socket = io({ transports: ['websocket', 'polling'] });

// ── STATE ─────────────────────────────────────────────────────────────────
let state = {
  trust       : 10,
  heat        : 0,
  turn        : 0,
  inBackRoom  : false,
  backRoomAvail: false,
  currentSong : null,
  lolaChat    : [],
  viktorChat  : [],
};

let songProgressInterval = null;

// ═════════════════════════════════════════════════════════════════════════
//  SOCKET EVENTS
// ═════════════════════════════════════════════════════════════════════════

socket.on('connect', () => console.log('[lounge] connected'));

socket.on('welcome', (data) => {
  appendAtmosphere(data.message);
  applyStateSnapshot(data.state || {});
});

socket.on('state_update', (data) => {
  applyStateSnapshot(data);
});

socket.on('heat_update', (data) => {
  setHeat(data.heat || 0);
});

socket.on('song_started', (data) => {
  const song = data.song || {};
  startSongUI(song);
  addEventEntry(`♩ ${song.title} — ${song.note || ''}`, 'type-random');
});

socket.on('song_ended', (data) => {
  addEventEntry(`♩ "${data.title}" ends.`, 'type-random');
});

socket.on('lounge_event', (data) => {
  addEventEntry(data.text, `type-${data.event_type || 'random'}`);
});

socket.on('back_room_unlocked', () => {
  const btn = document.getElementById('btnBackRoom');
  if (btn) {
    btn.disabled = false;
    btn.textContent = '▼ ENTER BACK ROOM';
    btn.classList.add('unlocked');
  }
  toast('The back room is now available.', false);
});

socket.on('narrative_update', (data) => {
  if (data.text) addEventEntry(data.text, 'type-rule');
});

socket.on('random_event', (data) => {
  if (data.text) addEventEntry(data.text, 'type-random');
});

// ═════════════════════════════════════════════════════════════════════════
//  STATE
// ═════════════════════════════════════════════════════════════════════════

function applyStateSnapshot(snap) {
  if (!snap) return;
  if (snap.trust    !== undefined) setTrust(snap.trust);
  if (snap.heat     !== undefined) setHeat(snap.heat);
  if (snap.turn     !== undefined) setTurn(snap.turn);
  if (snap.lola_mood)  setMood('lola',   snap.lola_mood);
  if (snap.viktor_mood)setMood('viktor', snap.viktor_mood);
  if (snap.current_song) {
    startSongUI(snap.current_song);
  }
  if (snap.atmosphere)  setAtmosphere(snap.atmosphere);
  if (snap.narrative)   snap.narrative.forEach(t => addEventEntry(t, 'type-random'));
  if (snap.active_rules) renderRules(snap.active_rules);
  if (snap.back_room_avail) {
    const btn = document.getElementById('btnBackRoom');
    if (btn && !snap.in_back_room) {
      btn.disabled = false;
      btn.classList.add('unlocked');
    }
  }
  state.trust       = snap.trust || state.trust;
  state.heat        = snap.heat  || state.heat;
  state.turn        = snap.turn  || state.turn;
  state.inBackRoom  = !!snap.in_back_room;
  state.currentSong = snap.current_song || null;

  const debugEl = document.getElementById('debugBody');
  if (debugEl && debugEl.style.display !== 'none') {
    debugEl.textContent = JSON.stringify(snap, null, 2);
  }
}

function setTrust(v) {
  state.trust = v;
  const fill  = document.getElementById('trustFill');
  const val   = document.getElementById('trustValue');
  if (fill) fill.style.width = Math.min(100, v) + '%';
  if (val)  val.textContent  = v;
}

function setHeat(v) {
  state.heat = v;
  const fill = document.getElementById('heatFill');
  const val  = document.getElementById('heatValue');
  if (fill) fill.style.width = Math.min(100, v) + '%';
  if (val)  val.textContent  = v;
  // Pulse body at high heat
  if (v >= 65) document.body.classList.add('heat-warning');
  else          document.body.classList.remove('heat-warning');
}

function setTurn(v) {
  state.turn = v;
  const el = document.getElementById('turnValue');
  if (el) el.textContent = v;
}

function setMood(char, mood) {
  const id = char === 'lola' ? 'lolaMood' : 'viktorMood';
  const el = document.getElementById(id);
  if (el) el.textContent = mood;
}

function setAtmosphere(atm) {
  if (!atm) return;
  const parts = Object.entries(atm)
    .filter(([,v]) => v)
    .map(([k,v]) => `${v}`)
    .slice(0, 3);
  if (parts.length) appendAtmosphere(parts.join(' · '));
}

function appendAtmosphere(text) {
  const el = document.getElementById('atmosphereLine');
  if (el) el.textContent = text;
}

// ═════════════════════════════════════════════════════════════════════════
//  SONG UI
// ═════════════════════════════════════════════════════════════════════════

function startSongUI(song) {
  if (!song) return;
  const titleEl = document.getElementById('songTitle');
  const timerEl = document.getElementById('songTimer');
  const fillEl  = document.getElementById('songProgressFill');

  if (titleEl) titleEl.textContent = song.title || '—';

  state.currentSong = song;

  if (songProgressInterval) clearInterval(songProgressInterval);

  const duration  = song.duration || 180;
  const startedAt = Date.now() - (song.elapsed || 0) * 1000;

  songProgressInterval = setInterval(() => {
    const elapsed   = (Date.now() - startedAt) / 1000;
    const remaining = Math.max(0, duration - elapsed);
    const pct       = Math.min(100, (elapsed / duration) * 100);

    if (fillEl) fillEl.style.width = pct + '%';
    if (timerEl) timerEl.textContent = formatTime(remaining);

    if (remaining <= 0) clearInterval(songProgressInterval);
  }, 500);
}

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ═════════════════════════════════════════════════════════════════════════
//  EVENTS
// ═════════════════════════════════════════════════════════════════════════

function addEventEntry(text, cls) {
  const feed = document.getElementById('eventFeed');
  if (!feed) return;
  const div = document.createElement('div');
  div.className = `event-entry ${cls || ''}`;
  div.textContent = text;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
  // Cap entries
  while (feed.children.length > 60) feed.removeChild(feed.firstChild);
}

// ═════════════════════════════════════════════════════════════════════════
//  DRINK MENU
// ═════════════════════════════════════════════════════════════════════════

async function loadMenu() {
  try {
    const res  = await fetch('/api/menu');
    const data = await res.json();
    renderDrinkList(data.cocktails || []);
  } catch (e) { console.warn('loadMenu failed', e); }
}

function renderDrinkList(cocktails) {
  const el = document.getElementById('drinkList');
  if (!el) return;
  el.innerHTML = '';
  cocktails.forEach(c => {
    const locked = c.locked;
    const item   = document.createElement('div');
    item.className = 'drink-item' + (locked ? ' locked' : '');
    item.title     = locked ? `Requires trust ${c.trust_req}` : c.note;
    item.innerHTML = `
      <div>
        <div class="drink-name">${c.name}</div>
        <div class="drink-note">${locked ? `Trust ${c.trust_req} required` : c.note}</div>
      </div>
      ${c.trust_req > 0 ? `<div class="drink-trust">${c.trust_req}</div>` : ''}
    `;
    if (!locked) {
      item.onclick = () => orderDrink(c.id, c.name);
    }
    el.appendChild(item);
  });
}

async function orderDrink(drinkId, name) {
  try {
    const res  = await fetch('/api/order', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ drink_id: drinkId }),
    });
    const data = await res.json();
    if (data.ok) {
      toast(`Viktor serves the ${data.drink}.`);
      addEventEntry(`You order ${name}. ${data.viktor || ''}`, 'type-drink');
      if (data.drink === 'The Velvet') {
        addEventEntry('The Velvet. A drink you will remember.', 'type-secret');
      }
    } else {
      toast(data.error || 'Order failed.', true);
    }
  } catch (e) {
    toast('Could not reach the bar.', true);
  }
}

// ═════════════════════════════════════════════════════════════════════════
//  SONG REQUESTS
// ═════════════════════════════════════════════════════════════════════════

async function loadSongs() {
  try {
    const res  = await fetch('/api/songs');
    const data = await res.json();
    renderSongList(data.songs || []);
  } catch (e) { console.warn('loadSongs failed', e); }
}

function renderSongList(songs) {
  const el = document.getElementById('songRequestList');
  if (!el) return;
  el.innerHTML = '';
  songs.forEach(s => {
    const item = document.createElement('div');
    item.className = 'song-item';
    item.innerHTML = `
      <div>
        <div class="song-item-title">"${s.title}"</div>
        <div class="song-item-note">${s.note}</div>
      </div>
    `;
    item.onclick = () => requestSong(s.id, s.title);
    el.appendChild(item);
  });
}

async function requestSong(songId, title) {
  try {
    const res  = await fetch('/api/request_song', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ song_id: songId }),
    });
    const data = await res.json();
    if (data.ok) {
      toast(`Lola begins "${data.song}".`);
    } else {
      toast(data.error || 'Not now.', true);
    }
  } catch (e) {
    toast('The request did not reach the stage.', true);
  }
}

// ═════════════════════════════════════════════════════════════════════════
//  CHAT
// ═════════════════════════════════════════════════════════════════════════

const chatHistories = { lola: [], viktor: [] };

async function sendMessage(target) {
  const inputId = target === 'lola' ? 'lolaInput' : 'viktorInput';
  const input   = document.getElementById(inputId);
  if (!input) return;
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';

  // Show in UI
  if (target === 'lola') {
    addChatBubble('lolaChat', msg, 'from-guest', 'You');
  } else {
    addMiniChatLine('viktorChat', `You: "${msg}"`);
  }

  chatHistories[target].push({ role: 'user', content: msg });

  try {
    const res  = await fetch('/api/message', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({
        message: msg,
        target ,
        history: chatHistories[target].slice(-10),
      }),
    });
    const data = await res.json();

    const reply = data.reply || '';
    chatHistories[target].push({ role: 'assistant', content: reply });

    if (target === 'lola') {
      addChatBubble('lolaChat', reply, 'from-lola', 'Lola');
    } else {
      addMiniChatLine('viktorChat', `Viktor: "${reply}"`);
    }

    // Update meters
    if (data.trust !== undefined) setTrust(data.trust);
    if (data.heat  !== undefined) setHeat(data.heat);
    if (data.turn  !== undefined) setTurn(data.turn);
    if (data.song)                startSongUI(data.song);
    if (data.random_event)        addEventEntry(data.random_event.text, 'type-random');

    // Refresh menu after each turn (trust may have changed)
    loadMenu();

  } catch (e) {
    const fallback = target === 'lola'
      ? "She tilts her head. A pause. Her eyes don't leave yours."
      : "Viktor sets a glass down slowly. Says nothing.";
    if (target === 'lola') {
      addChatBubble('lolaChat', fallback, 'from-lola', 'Lola');
    } else {
      addMiniChatLine('viktorChat', `Viktor: "${fallback}"`);
    }
  }
}

function addChatBubble(containerId, text, cls, speaker) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${cls}`;
  bubble.innerHTML = `<div class="bubble-speaker">${speaker}</div>${escapeHtml(text)}`;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

function addMiniChatLine(containerId, text) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const div = document.createElement('div');
  div.textContent = text;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  while (el.children.length > 20) el.removeChild(el.firstChild);
}

// ═════════════════════════════════════════════════════════════════════════
//  BACK ROOM
// ═════════════════════════════════════════════════════════════════════════

async function enterBackRoom() {
  try {
    const res  = await fetch('/api/back_room', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      document.getElementById('backRoomText').textContent = data.note || '';
      document.getElementById('backRoomOverlay').style.display = 'flex';
    } else {
      toast(data.error || 'Not permitted.', true);
    }
  } catch (e) {
    toast('Something stopped you at the curtain.', true);
  }
}

// ═════════════════════════════════════════════════════════════════════════
//  SECRETS
// ═════════════════════════════════════════════════════════════════════════

async function askSecret(character) {
  try {
    const res  = await fetch('/api/ask_secret', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ character }),
    });
    const data = await res.json();
    if (data.ok) {
      document.getElementById('secretTitle').textContent   = data.secret || '···';
      document.getElementById('secretContent').textContent = data.content || '';
      document.getElementById('secretOverlay').style.display = 'flex';
      addEventEntry(`Secret revealed: "${data.secret}"`, 'type-secret');
      if (data.effect && data.effect.trust) setTrust(state.trust + data.effect.trust);
    } else {
      toast(data.error || 'Nothing to share. Not yet.', true);
    }
  } catch (e) {
    toast('The question hangs in the air. No answer.', true);
  }
}

// ═════════════════════════════════════════════════════════════════════════
//  RULES
// ═════════════════════════════════════════════════════════════════════════

function renderRules(rules) {
  const el = document.getElementById('rulesList');
  if (!el) return;
  el.innerHTML = '';
  (rules || []).slice(0, 5).forEach(r => {
    const li = document.createElement('li');
    li.textContent = r.label || r.id;
    el.appendChild(li);
  });
}

async function loadRules() {
  try {
    const res  = await fetch('/api/rules');
    const data = await res.json();
    renderRules(data.rules || []);
  } catch (e) { /* silent */ }
}

// ═════════════════════════════════════════════════════════════════════════
//  OVERLAYS
// ═════════════════════════════════════════════════════════════════════════

function closeOverlay(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

// ═════════════════════════════════════════════════════════════════════════
//  DEBUG
// ═════════════════════════════════════════════════════════════════════════

function toggleDebug() {
  const body = document.getElementById('debugBody');
  if (!body) return;
  const visible = body.style.display !== 'none';
  body.style.display = visible ? 'none' : 'block';
  if (!visible) {
    fetch('/api/state')
      .then(r => r.json())
      .then(d => { body.textContent = JSON.stringify(d, null, 2); })
      .catch(() => { body.textContent = '(unavailable)'; });
  }
}

// ═════════════════════════════════════════════════════════════════════════
//  TOAST
// ═════════════════════════════════════════════════════════════════════════

function toast(msg, isError) {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const t = document.createElement('div');
  t.className = 'toast' + (isError ? ' toast-error' : '');
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => { if (t.parentNode) t.parentNode.removeChild(t); }, 3200);
}

// ═════════════════════════════════════════════════════════════════════════
//  KEYBOARD SHORTCUTS
// ═════════════════════════════════════════════════════════════════════════

document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const active = document.activeElement;
    if (active && active.id === 'lolaInput')   { e.preventDefault(); sendMessage('lola'); }
    if (active && active.id === 'viktorInput') { e.preventDefault(); sendMessage('viktor'); }
  }
});

// ═════════════════════════════════════════════════════════════════════════
//  HELPERS
// ═════════════════════════════════════════════════════════════════════════

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ═════════════════════════════════════════════════════════════════════════
//  INIT
// ═════════════════════════════════════════════════════════════════════════

(async function init() {
  // Load initial state
  try {
    const res  = await fetch('/api/state');
    const data = await res.json();
    applyStateSnapshot(data);
  } catch (e) { /* will be populated by socket welcome */ }

  await loadMenu();
  await loadSongs();
  await loadRules();

  // Refresh menu every 30s (trust may change)
  setInterval(loadMenu,  30000);
  setInterval(loadSongs, 60000);
  setInterval(loadRules, 60000);
})();
