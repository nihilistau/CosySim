/* The Midnight Casino — Client Logic */

const socket = io();

// ── State ──────────────────────────────────────────────────────
let gameState = {};

// ── Socket handlers ────────────────────────────────────────────
socket.on('game_update', (data) => {
    gameState = data;
    renderState(data);
});

socket.on('chat_reply', (data) => {
    appendChat(data.character, data.message);
});

socket.on('casino_event', (event) => {
    appendEvent(event.text || JSON.stringify(event));
});

socket.on('story_beat', (data) => {
    appendEvent('📖 ' + (data.beat || ''));
});

socket.on('mood_update', (data) => {
    appendEvent('💭 Mood shift: ' + (data.mood || ''));
});

socket.on('environment_update', (data) => {
    appendEvent('🌆 ' + (data.description || ''));
});

// ── Rendering ──────────────────────────────────────────────────
function renderState(s) {
    // Chips
    document.getElementById('player-chips').textContent = s.player_chips;
    document.getElementById('mira-chips').textContent = s.mira_chips;
    document.getElementById('pot-amount').textContent = s.pot;

    // Comments
    document.getElementById('dealer-comment').textContent = s.dealer_comment || '...';
    document.getElementById('mira-comment').textContent = s.mira_comment || '...';

    // Cards
    renderCards('player-hand', s.player_hand || []);
    renderCards('community-cards', s.community_cards || []);

    // Tell
    const tellArea = document.getElementById('tell-area');
    if (s.current_tell) {
        tellArea.style.display = 'block';
        document.getElementById('current-tell').textContent = 'Mira ' + s.current_tell;
    } else {
        tellArea.style.display = 'none';
    }

    // Stats
    for (const [stat, val] of Object.entries(s.player_stats || {})) {
        const el = document.getElementById('stat-' + stat);
        if (el) el.style.width = val + '%';
    }

    // Phase-based action visibility
    const phases = ['lobby', 'bet', 'showdown', 'result'];
    for (const p of phases) {
        const el = document.getElementById(p + '-actions');
        if (el) el.style.display = (s.phase === p) ? 'flex' : 'none';
    }

    // Drinks
    renderDrinks(s.drinks || {});

    // History
    if (s.hand_history && s.hand_history.length > 0) {
        const last = s.hand_history[s.hand_history.length - 1];
        appendEvent(`Round ${last.round}: ${last.winner} wins (${last.player_eval} vs ${last.mira_eval})`);
    }
}

function renderCards(containerId, cards) {
    const container = document.getElementById(containerId);
    if (!cards || cards.length === 0) {
        container.innerHTML = '<div class="card-placeholder">' +
            (containerId === 'player-hand' ? 'Your Hand' : 'Community Cards') + '</div>';
        return;
    }
    container.innerHTML = cards.map(card => {
        if (card === '🂠') return '<div class="card face-down">🂠</div>';
        const isRed = card.includes('♥') || card.includes('♦');
        return `<div class="card${isRed ? ' red' : ''}">${card}</div>`;
    }).join('');
}

function renderDrinks(drinks) {
    const grid = document.getElementById('drink-grid');
    grid.innerHTML = Object.entries(drinks).map(([id, d]) =>
        `<div class="drink-item" onclick="orderDrink('${id}')">
            <span class="drink-name">${d.emoji} ${d.name}</span>
            <span class="drink-cost">${d.cost}🪙</span>
        </div>`
    ).join('');
}

// ── Actions ────────────────────────────────────────────────────
async function newHand() {
    const r = await fetch('/api/new-hand', { method: 'POST' });
    const data = await r.json();
    renderState(data);
}

async function placeBet(amount) {
    const r = await fetch('/api/bet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount }),
    });
    const data = await r.json();
    renderState(data);
}

async function goAllIn() {
    placeBet(gameState.player_chips || 0);
}

async function attemptBluff() {
    const r = await fetch('/api/bluff', { method: 'POST' });
    const data = await r.json();
    renderState(data);
}

async function showdown() {
    const r = await fetch('/api/showdown', { method: 'POST' });
    const data = await r.json();
    renderState(data);
}

async function fold() {
    const r = await fetch('/api/fold', { method: 'POST' });
    const data = await r.json();
    renderState(data);
}

async function orderDrink(drinkId) {
    const r = await fetch('/api/drink', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ drink_id: drinkId }),
    });
    const data = await r.json();
    if (data.error) {
        appendEvent('❌ ' + data.error);
    } else {
        appendEvent('🍸 Ordered ' + data.drink.name);
    }
}

async function triggerEvent() {
    const r = await fetch('/api/random-event', { method: 'POST' });
    const data = await r.json();
    appendEvent(data.text || 'Something happened...');
}

function sendChat() {
    const input = document.getElementById('chat-message');
    const target = document.getElementById('chat-target').value;
    const msg = input.value.trim();
    if (!msg) return;
    appendChat('You', msg);
    socket.emit('chat_message', { message: msg, target });
    input.value = '';
}

async function refreshFramework() {
    try {
        const r = await fetch('/api/framework-status');
        const data = await r.json();
        document.getElementById('framework-status').textContent = JSON.stringify(data, null, 2);
    } catch (e) {
        document.getElementById('framework-status').textContent = 'Error: ' + e.message;
    }
}

// ── Helpers ────────────────────────────────────────────────────
function appendEvent(text) {
    const list = document.getElementById('event-list');
    const entry = document.createElement('div');
    entry.className = 'event-entry';
    entry.textContent = text;
    list.insertBefore(entry, list.firstChild);
    while (list.children.length > 20) list.removeChild(list.lastChild);
}

function appendChat(name, message) {
    const log = document.getElementById('chat-log');
    const entry = document.createElement('div');
    entry.className = 'chat-entry';
    entry.innerHTML = `<span class="name">${name}:</span> ${message}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

// ── Init ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    try {
        const r = await fetch('/api/state');
        const data = await r.json();
        renderState(data);
    } catch (e) {
        console.error('Failed to load initial state:', e);
    }
    refreshFramework();
});
