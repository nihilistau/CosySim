/**
 * Heist Scene — Client-side game controller.
 */
(function() {
    'use strict';

    const socket = io();
    let gameState = null;
    let selectedVenue = 'diamond_exchange';

    // ── DOM refs ────────────────────────────────────────────────────────
    const chatArea = document.getElementById('chat-area');
    const chatInput = document.getElementById('chat-input');
    const targetCrew = document.getElementById('target-crew');
    const crewList = document.getElementById('crew-list');
    const obstaclesList = document.getElementById('obstacles-list');
    const eventsList = document.getElementById('events-list');
    const suspicionFill = document.getElementById('suspicion-fill');
    const suspicionVal = document.getElementById('suspicion-val');
    const lootFill = document.getElementById('loot-fill');
    const lootVal = document.getElementById('loot-val');
    const phaseBadge = document.getElementById('phase-badge');
    const setupModal = document.getElementById('setup-modal');

    // ── Init ────────────────────────────────────────────────────────────
    async function init() {
        const res = await fetch('/api/game');
        const data = await res.json();
        if (data.active) {
            setupModal.classList.add('hidden');
            updateState(data);
        } else {
            loadVenues();
        }
    }

    async function loadVenues() {
        const res = await fetch('/api/venues');
        const venues = await res.json();
        const grid = document.getElementById('venue-grid');
        grid.innerHTML = '';
        for (const [key, v] of Object.entries(venues)) {
            const card = document.createElement('div');
            card.className = 'venue-card' + (key === selectedVenue ? ' selected' : '');
            card.innerHTML = `
                <div class="vname">${v.name}</div>
                <div class="vdiff">${v.difficulty.toUpperCase()} • ${v.guards} guards</div>
                <div class="vloot">💰 $${(v.loot_value).toLocaleString()}</div>
            `;
            card.onclick = () => {
                selectedVenue = key;
                grid.querySelectorAll('.venue-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
            };
            grid.appendChild(card);
        }
    }

    // ── State updates ───────────────────────────────────────────────────
    function updateState(state) {
        gameState = state;

        // Meters
        suspicionFill.style.width = state.suspicion + '%';
        suspicionVal.textContent = state.suspicion;
        const lootPct = Math.min(100, (state.loot_collected / state.loot_target) * 100);
        lootFill.style.width = lootPct + '%';
        lootVal.textContent = '$' + state.loot_collected.toLocaleString();
        phaseBadge.textContent = state.phase.toUpperCase();

        // Crew
        crewList.innerHTML = '';
        targetCrew.innerHTML = '<option value="">Select crew...</option>';
        for (const [id, m] of Object.entries(state.crew)) {
            const card = document.createElement('div');
            card.className = 'crew-card';
            const status = m.arrested ? '🚔 Arrested' : (m.injured ? '🩹 Injured' : '✅ OK');
            card.innerHTML = `
                <div class="name">${m.name}</div>
                <div class="specialty">${m.specialty}</div>
                <div class="stats">HP: ${m.health} | Morale: ${m.morale} | ${status}</div>
            `;
            crewList.appendChild(card);
            const opt = document.createElement('option');
            opt.value = id;
            opt.textContent = m.name;
            targetCrew.appendChild(opt);
        }

        // Obstacles
        obstaclesList.innerHTML = '';
        for (const obs of (state.obstacles_cleared || [])) {
            const el = document.createElement('div');
            el.className = 'obstacle cleared';
            el.textContent = '✓ ' + obs.replace(/_/g, ' ');
            obstaclesList.appendChild(el);
        }
        for (const obs of (state.obstacles_remaining || [])) {
            const el = document.createElement('div');
            el.className = 'obstacle';
            el.textContent = '🔒 ' + obs.replace(/_/g, ' ');
            obstaclesList.appendChild(el);
        }

        // Events
        eventsList.innerHTML = '';
        for (const evt of (state.events || []).slice(-10).reverse()) {
            const el = document.createElement('div');
            el.className = 'event-item';
            el.textContent = `T${evt.turn}: ${evt.message}`;
            eventsList.appendChild(el);
        }
    }

    // ── Chat ────────────────────────────────────────────────────────────
    function addMessage(name, text, type, mood) {
        const msg = document.createElement('div');
        msg.className = 'chat-msg ' + type;
        let html = '';
        if (name) html += `<div class="sender">${name}</div>`;
        html += `<div>${text}</div>`;
        if (mood) html += `<div class="mood">${mood}</div>`;
        msg.innerHTML = html;
        chatArea.appendChild(msg);
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function sendMessage() {
        const msg = chatInput.value.trim();
        const charId = targetCrew.value;
        if (!msg || !charId) return;
        addMessage('You', msg, 'player');
        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character_id: charId, message: msg }),
        });
        chatInput.value = '';
    }

    // ── Button handlers ─────────────────────────────────────────────────
    document.getElementById('btn-send').onclick = sendMessage;
    chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });

    document.getElementById('btn-start').onclick = async () => {
        const res = await fetch('/api/game/new', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ venue: selectedVenue }),
        });
        const data = await res.json();
        if (data.success) {
            setupModal.classList.add('hidden');
            updateState(data.game);
            addMessage(null, `Heist started at ${data.game.venue.name}!`, 'system');
        }
    };

    document.getElementById('btn-advance').onclick = async () => {
        const res = await fetch('/api/game/advance', { method: 'POST' });
        const data = await res.json();
        addMessage(null, `Phase advanced to: ${data.phase}`, 'system');
    };

    document.getElementById('btn-loot').onclick = async () => {
        const res = await fetch('/api/game/loot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount: 50000 }),
        });
        const data = await res.json();
        addMessage(null, `Grabbed $50,000! Total: $${data.total.toLocaleString()}`, 'system');
    };

    document.getElementById('btn-tick').onclick = async () => {
        addMessage(null, '🎲 Crew discussing...', 'system');
        await fetch('/api/crew/tick', { method: 'POST' });
    };

    // ── Socket events ───────────────────────────────────────────────────
    socket.on('game_state', updateState);

    socket.on('crew_message', data => {
        const mood = data.mood ? `Mood: ${data.mood}` : '';
        addMessage(`${data.name} [${data.specialty}]`, data.message, 'crew', mood);
    });

    socket.on('game_event', data => {
        const icon = data.success ? '✅' : '❌';
        addMessage(null, `${icon} ${data.message}`, 'system');
    });

    socket.on('complication', data => {
        addMessage(null, `⚠️ COMPLICATION: ${data.message}`, 'system');
    });

    socket.on('typing', data => {
        // Could show typing indicator per character
    });

    // ── Start ───────────────────────────────────────────────────────────
    init();
})();
