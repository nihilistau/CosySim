/**
 * NeonCity — v0.68 "Dark Renaissance"
 * Living World Hub client-side controller.
 *
 * Handles Socket.IO state sync, district navigation, faction bars,
 * the world ticker, NPC chat, and particle effects via ParticleSystem3D.
 */

'use strict';

// ────────────────────────────────────────────────────────────────────────────
// NeonCityScene class
// ────────────────────────────────────────────────────────────────────────────

class NeonCityScene {
    /**
     * @param {string} [socketUrl=''] - Socket.IO server URL (defaults to origin)
     */
    constructor(socketUrl = '') {
        /** @type {import('socket.io-client').Socket|null} */
        this.socket = null;
        this.socketUrl = socketUrl;

        /** @type {Object|null} Current full city state */
        this.cityState = null;

        /** @type {string|null} Currently visited district key */
        this.activeDistrict = null;

        /** @type {string[]} Ticker items queue */
        this._tickerItems = [];

        /** @type {Object|null} ParticleSystem3D instance */
        this._particles = null;

        /** @type {number|null} Ticker restart timer */
        this._tickerTimer = null;
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────

    /** Initialise the scene: particles, socket, initial data fetch. */
    init() {
        this._initParticles();
        this._setupSocket();
        // Navbar mount (navbar_v2.js)
        if (typeof initNavbar === 'function') {
            initNavbar('navbar-mount', { scene: 'neoncity', accent: '#06b6d4' });
        }
    }

    // ── Particle system ──────────────────────────────────────────────────

    _initParticles() {
        const canvas = document.getElementById('particle-canvas');
        if (!canvas || typeof ParticleSystem3D === 'undefined') return;
        try {
            this._particles = new ParticleSystem3D(canvas, {
                background: 'transparent',
                presets: ['neon_rain', 'neon_dust'],
                color: '#06b6d4',
                secondaryColor: '#22c55e',
                density: 0.6,
                speed: 0.4,
            });
            this._particles.start();
        } catch (e) {
            console.warn('[NeonCity] ParticleSystem3D init failed:', e);
        }
    }

    // ── Socket.IO ────────────────────────────────────────────────────────

    _setupSocket() {
        this.socket = io(this.socketUrl, { transports: ['websocket', 'polling'] });

        this.socket.on('connect', () => {
            console.log('[NeonCity] Socket connected.');
            this.loadCityState();
        });

        this.socket.on('disconnect', () => {
            console.log('[NeonCity] Socket disconnected.');
        });

        this.socket.on('city_state', (data) => this._onCityState(data));
        this.socket.on('ticker_update', (data) => this._updateTicker(data.items || []));
        this.socket.on('district_info', (data) => this._onDistrictInfo(data));
        this.socket.on('world_events', (data) => this._onWorldEvents(data));
        this.socket.on('faction_status', (data) => this._onFactionStatus(data));
        this.socket.on('faction_update', (data) => this._onFactionUpdate(data));
        this.socket.on('world_major_event', (data) => this._onWorldMajorEvent(data));
        this.socket.on('city_event', (data) => this._onCityEvent(data));
        this.socket.on('intel_result', (data) => this._onIntelResult(data));
        this.socket.on('error', (data) => {
            console.warn('[NeonCity] Server error:', data.message || data);
        });
    }

    // ── Data loaders ─────────────────────────────────────────────────────

    /** Request full city state from server. */
    loadCityState() {
        if (this.socket) this.socket.emit('get_city_state');
    }

    /** Request world events for the news feed. */
    loadWorldEvents() {
        if (this.socket) this.socket.emit('get_world_events');
    }

    /**
     * Visit a district and request its detail panel.
     * @param {string} districtKey - District identifier key.
     */
    visitDistrict(districtKey) {
        this.activeDistrict = districtKey;
        // Highlight selected card
        document.querySelectorAll('.district-card').forEach(card => {
            card.classList.toggle('active', card.dataset.district === districtKey);
        });
        // Update chat header
        const chatLabel = document.getElementById('chat-district-label');
        if (chatLabel) chatLabel.textContent = `— ${districtKey.replace('_', ' ').toUpperCase()}`;

        if (this.socket) this.socket.emit('visit_district', { district: districtKey });
    }

    // ── Socket event handlers ─────────────────────────────────────────────

    /**
     * Handle full city state update.
     * @param {Object} data - City state from server.
     */
    _onCityState(data) {
        this.cityState = data;
        this._renderDistricts(data);
        this._renderFactionBars(data.factions || []);
        this._updateClock(data.world_time || {});
        this._updateCredits(data.credits);
    }

    /**
     * Handle district detail info.
     * @param {Object} data - District info payload.
     */
    _onDistrictInfo(data) {
        const d = data.district || {};
        const modal = document.getElementById('district-modal');
        if (!modal) return;

        document.getElementById('modal-icon').textContent = d.icon || '?';
        document.getElementById('modal-title').textContent = d.name || data.district_key;
        document.getElementById('modal-desc').textContent = d.description || '';

        // Faction
        document.getElementById('modal-faction-name').textContent =
            d.controlling_faction || '—';
        document.getElementById('modal-faction-name').style.color =
            data.faction_color || '#06b6d4';
        const power = data.faction_power || 0;
        document.getElementById('modal-faction-fill').style.width = `${power}%`;
        document.getElementById('modal-faction-fill').style.background =
            data.faction_color || '#06b6d4';

        // NPCs
        const npcContainer = document.getElementById('modal-npc-list');
        if (npcContainer) {
            npcContainer.innerHTML = (d.npcs || [])
                .map(n => `<span class="modal-npc-tag">${n}</span>`)
                .join('');
        }

        // Ticker excerpt
        const tickerEl = document.getElementById('modal-ticker');
        if (tickerEl) {
            tickerEl.textContent = (data.ticker || []).join('\n');
        }

        // Enter button
        const enterBtn = document.getElementById('btn-enter-district');
        if (enterBtn) {
            enterBtn.onclick = () => this._enterDistrict(data.district_key);
        }

        modal.style.display = 'flex';
    }

    /**
     * Handle world events list.
     * @param {Object} data - World events payload.
     */
    _onWorldEvents(data) {
        const list = document.getElementById('events-list');
        if (!list) return;
        const events = data.events || [];
        if (events.length === 0) {
            list.innerHTML = '<div class="event-item system">No active events detected.</div>';
            return;
        }
        list.innerHTML = events
            .map(ev => `<div class="event-item active">${this._esc(ev.description || ev.id)}</div>`)
            .join('');
    }

    /**
     * Handle faction status update.
     * @param {Object} data - Faction status payload.
     */
    _onFactionStatus(data) {
        this._renderFactionBars(data.factions || []);
    }

    /**
     * Handle live faction shift event.
     * @param {Object} data - Faction update payload.
     */
    _onFactionUpdate(data) {
        // Flash affected faction bars
        const payload = data.payload || {};
        const factionName = payload.faction || '';
        if (factionName) {
            const row = document.querySelector(`.faction-row[data-faction="${factionName}"]`);
            if (row) {
                row.classList.add('shifting');
                setTimeout(() => row.classList.remove('shifting'), 1500);
            }
        }
        // Refresh faction data
        if (this.socket) this.socket.emit('get_faction_status');
    }

    /**
     * Handle major world event broadcast.
     * @param {Object} data - World event payload.
     */
    _onWorldMajorEvent(data) {
        const payload = data.payload || {};
        const desc = payload.description || payload.label || JSON.stringify(data);
        this._showToast('⚡ WORLD EVENT', desc);
        this._appendChatEntry('event', '[CITY ALERT]', desc);
    }

    /**
     * Handle NPC action city event.
     * @param {Object} data - City event payload.
     */
    _onCityEvent(data) {
        const payload = data.payload || {};
        const desc = payload.description || payload.action || JSON.stringify(payload);
        this._appendChatEntry('event', `[${(payload.npc_id || 'NPC').toUpperCase()}]`, desc);
    }

    /**
     * Handle intel purchase result.
     * @param {Object} data - Intel result payload.
     */
    _onIntelResult(data) {
        const el = document.getElementById('intel-result');
        if (!el) return;
        if (data.error) {
            el.textContent = data.error;
            el.style.borderLeftColor = '#ef4444';
        } else {
            el.textContent = data.lore || '';
            el.style.borderLeftColor = '#06b6d4';
        }
        if (data.balance !== undefined) this._updateCredits(data.balance);
    }

    // ── Render helpers ────────────────────────────────────────────────────

    /**
     * Update district cards with live state.
     * @param {Object} state - City state object.
     */
    _renderDistricts(state) {
        const districts = state.districts || {};
        Object.entries(districts).forEach(([key, d]) => {
            const fEl = document.getElementById(`faction-${key}`);
            if (fEl) fEl.textContent = d.controlling_faction || '—';

            const aEl = document.getElementById(`activity-${key}`);
            if (aEl) {
                const level = d.activity_level || 'quiet';
                const dot = aEl.querySelector('.activity-dot');
                if (dot) {
                    dot.className = `activity-dot ${level}`;
                }
                aEl.lastChild.textContent = ` ${level.toUpperCase()}`;
            }
        });
    }

    /**
     * Render faction tension bars.
     * @param {Array<Object>} factions - Array of faction data objects.
     */
    _renderFactionBars(factions) {
        factions.forEach(f => {
            const bar = document.getElementById(`bar-${f.name}`);
            if (bar) {
                bar.style.width = `${f.power}%`;
                bar.style.background = f.color || '#06b6d4';
            }
            const powerEl = document.getElementById(`power-${f.name}`);
            if (powerEl) powerEl.textContent = f.power;

            const standingEl = document.getElementById(`standing-${f.name}`);
            if (standingEl) {
                const label = f.label || 'Neutral';
                const sign = (f.standing >= 0) ? '+' : '';
                standingEl.textContent = `${label} (${sign}${f.standing || 0})`;
            }
        });

        // Update tension summary
        const avgPower = factions.length
            ? Math.round(factions.reduce((s, f) => s + f.power, 0) / factions.length)
            : 0;
        const tensionEl = document.getElementById('tension-val');
        if (tensionEl) tensionEl.textContent = `${avgPower}%`;
    }

    /**
     * Update the world clock display.
     * @param {Object} worldTime - World time object from server.
     */
    _updateClock(worldTime) {
        const el = document.getElementById('clock-display');
        if (el) el.textContent = worldTime.display || 'NIGHT CYCLE';
    }

    /**
     * Update the credit balance display.
     * @param {number} balance - Current credit balance.
     */
    _updateCredits(balance) {
        if (balance === undefined || balance === null) return;
        const el1 = document.getElementById('credit-balance');
        const el2 = document.getElementById('econ-balance');
        if (el1) el1.textContent = balance.toLocaleString();
        if (el2) el2.textContent = `₢ ${balance.toLocaleString()}`;
    }

    /**
     * Populate and restart the world ticker.
     * @param {string[]} items - Array of ticker strings.
     */
    _updateTicker(items) {
        if (!items || items.length === 0) return;
        this._tickerItems = items;
        const inner = document.getElementById('ticker-inner');
        if (!inner) return;

        // Build doubled array for seamless loop
        const all = [...items, ...items];
        inner.innerHTML = all
            .map(t => `<span class="ticker-item">${this._esc(t)}</span>`)
            .join('');

        // Recalculate animation duration based on content length
        const totalChars = all.reduce((n, t) => n + t.length, 0);
        const duration = Math.max(30, totalChars * 0.08);
        inner.style.animationDuration = `${duration}s`;
    }

    // ── User actions ──────────────────────────────────────────────────────

    /** Send a chat message to the active district. */
    sendMessage() {
        const input = document.getElementById('chat-input');
        if (!input) return;
        const text = input.value.trim();
        if (!text) return;
        input.value = '';

        this._appendChatEntry('player', '[YOU]', text);

        // Emit to server (future: NPC response via agent loop)
        if (this.socket && this.activeDistrict) {
            this.socket.emit('district_chat', {
                district: this.activeDistrict,
                message: text,
            });
        }
    }

    /** Buy intel from information broker. */
    buyIntel() {
        const topic = (document.getElementById('intel-topic')?.value || '').trim();
        const cost = parseInt(document.getElementById('intel-cost')?.value || '50', 10);
        if (!topic) return;
        if (this.socket) this.socket.emit('buy_info', { topic, cost });
    }

    /** Perform credit exchange. */
    doExchange() {
        const amount = parseInt(document.getElementById('exchange-amount')?.value || '0', 10);
        const direction = document.getElementById('exchange-dir')?.value || 'in';
        if (amount <= 0) return;
        if (this.socket) {
            this.socket.emit('exchange_credits', { amount, direction });
        }
    }

    /** Close the district detail modal. */
    closeModal() {
        const modal = document.getElementById('district-modal');
        if (modal) modal.style.display = 'none';
    }

    // ── Private helpers ───────────────────────────────────────────────────

    /**
     * Enter a district (placeholder for future scene navigation).
     * @param {string} districtKey
     */
    _enterDistrict(districtKey) {
        this.closeModal();
        this._appendChatEntry(
            'system', '[CITY]',
            `Entering ${districtKey.replace('_', ' ').toUpperCase()}…`
        );
    }

    /**
     * Append an entry to the chat log.
     * @param {string} type   - CSS class: 'system', 'player', 'npc', 'event'.
     * @param {string} source - Source label, e.g. '[SYSTEM]'.
     * @param {string} text   - Message text.
     */
    _appendChatEntry(type, source, text) {
        const log = document.getElementById('chat-log');
        if (!log) return;
        const div = document.createElement('div');
        div.className = `chat-entry ${type}`;
        div.innerHTML = `<span class="entry-src">${this._esc(source)}</span>${this._esc(text)}`;
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
    }

    /**
     * Show a temporary toast notification.
     * @param {string} title
     * @param {string} body
     * @param {number} [duration=5000] ms before auto-dismiss.
     */
    _showToast(title, body, duration = 5000) {
        const toast = document.createElement('div');
        toast.className = 'world-event-toast';
        toast.innerHTML = `
            <div class="toast-title">${this._esc(title)}</div>
            <div class="toast-body">${this._esc(body)}</div>
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), duration);
    }

    /**
     * Escape HTML special characters to prevent XSS.
     * @param {string} str
     * @returns {string}
     */
    _esc(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}


// ────────────────────────────────────────────────────────────────────────────
// Bootstrap
// ────────────────────────────────────────────────────────────────────────────

/** Global singleton — accessible from HTML onclick attributes. */
const NeonCityApp = new NeonCityScene();

document.addEventListener('DOMContentLoaded', () => {
    NeonCityApp.init();

    // Kick off periodic world-event fetch every 60 s
    NeonCityApp.loadWorldEvents();
    setInterval(() => NeonCityApp.loadWorldEvents(), 60_000);

    // Refresh faction status every 30 s
    setInterval(() => {
        if (NeonCityApp.socket) NeonCityApp.socket.emit('get_faction_status');
    }, 30_000);
});
