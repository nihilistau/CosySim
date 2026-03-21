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

        // v1.44.0 — HUD state for sidebars
        /** @type {Object|null} Player state snapshot */
        this.playerState = null;

        /** @type {Array} Inventory items */
        this.inventory = [];

        /** @type {Object} Equipped items by slot */
        this.equipped = {};

        /** @type {Object} Crew roster */
        this.crewData = null;

        /** @type {Object} Missions data */
        this.missionData = { available: [], active: [] };

        /** @type {string} Active mission tab */
        this._missionTab = 'available';
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────

    /** Initialise the scene: particles, socket, initial data fetch. */
    init() {
        this._initParticles();
        this._setupSocket();
        this._loadHudData();
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
        this.socket.on('district_alert', (data) => this._onDistrictAlert(data));
        this.socket.on('hud_state', (data) => this._onHudState(data));
        this.socket.on('hud_update', (data) => this._onHudUpdate(data));
        this.socket.on('error', (data) => {
            console.warn('[NeonCity] Server error:', data.message || data);
        });
    }

    // ── Data loaders ─────────────────────────────────────────────────────

    /** Request full city state from server. */
    loadCityState() {
        if (this.socket) this.socket.emit('get_city_state');
    }

    /** Fetch living-world district status from REST and update alerts ticker. */
    fetchDistrictStatus() {
        fetch('/api/world/district_status')
            .then(r => r.json())
            .then(data => {
                this._districtStatus = data;
                this._updateDistrictAlerts(data.district_alerts || []);
                // Re-render faction bars to apply territory indicators
                if (this.cityState) {
                    this._renderFactionBars(this.cityState.factions || []);
                }
            })
            .catch(e => console.warn('[NeonCity] district_status fetch failed:', e));
    }

    /**
     * Update the DISTRICT ALERTS ticker with living-world event titles.
     * @param {string[]} titles - Alert titles from /api/world/district_status.
     */
    _updateDistrictAlerts(titles) {
        const bar = document.getElementById('district-alerts-bar');
        const inner = document.getElementById('district-alerts-inner');
        if (!inner || !bar) return;
        if (!titles || titles.length === 0) {
            bar.style.display = 'none';
            return;
        }
        bar.style.display = '';
        const all = [...titles, ...titles];
        inner.innerHTML = all
            .map(t => `<span class="ticker-item">${this._esc(t)}</span>`)
            .join('');
        const totalChars = all.reduce((n, t) => n + t.length, 0);
        const duration = Math.max(20, totalChars * 0.08);
        inner.style.animationDuration = `${duration}s`;
    }

    /**
     * Handle a district_alert Socket.IO event (e.g. Corp Raid).
     * @param {Object} data - Alert payload with type, title, payload.
     */
    _onDistrictAlert(data) {
        const title = data.title || 'District Alert';
        const payload = data.payload || {};
        const desc = payload.description || payload.label || title;
        this._showToast('⚠ DISTRICT ALERT', desc, 8000);
        this._appendChatEntry('event', '[DISTRICT ALERT]', desc);
        // Refresh district status so alerts ticker stays current
        this.fetchDistrictStatus();
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
        const standings = (this._districtStatus || {}).faction_standings || {};
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

            // Territory indicator based on PlayerState faction_standings
            const terrEl = document.getElementById(`territory-${f.name}`);
            if (terrEl) {
                const ps = standings[f.name] || 0;
                if (ps > 10) {
                    terrEl.style.color = '#22c55e';
                    terrEl.textContent = '▲';
                    terrEl.title = `Territory: +${ps}`;
                } else if (ps < -10) {
                    terrEl.style.color = '#ef4444';
                    terrEl.textContent = '▼';
                    terrEl.title = `Territory: ${ps}`;
                } else {
                    terrEl.style.color = '#4a5568';
                    terrEl.textContent = '—';
                    terrEl.title = `Territory: ${ps >= 0 ? '+' : ''}${ps}`;
                }
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

    // ── v1.44.0 — HUD Sidebar Methods ─────────────────────────────────────

    /** Load combined HUD data from REST API (initial load). */
    _loadHudData() {
        fetch('/api/hud')
            .then(r => r.json())
            .then(data => {
                if (data.error) return;
                this._onHudState(data);
            })
            .catch(e => console.warn('[NeonCity] HUD data fetch failed:', e));

        // Also load city map neighbors
        this._loadCityMap();
    }

    /** Fetch city map location + neighbors for the map panel. */
    _loadCityMap() {
        fetch('/api/city/neighbors')
            .then(r => r.json())
            .then(data => this._renderCityMap(data))
            .catch(e => console.warn('[NeonCity] City map fetch failed:', e));
    }

    /**
     * Render city map panel with current location and neighbors.
     * @param {Object} data - { location, neighbors: [...] }
     */
    _renderCityMap(data) {
        const locName = document.getElementById('map-loc-name');
        const districtEl = document.getElementById('map-district');
        const neighborsEl = document.getElementById('map-neighbors');
        if (!neighborsEl) return;

        if (locName) locName.textContent = data.location || 'Unknown';
        if (districtEl) {
            // Find district from neighbor data or set generic
            const firstNeighbor = (data.neighbors || [])[0];
            districtEl.textContent = firstNeighbor ? firstNeighbor.district || '' : '';
        }

        const neighbors = data.neighbors || [];
        if (neighbors.length === 0) {
            neighborsEl.innerHTML = '<div style="font-size:0.6rem;color:rgba(255,255,255,0.3);text-align:center;padding:8px">No connections</div>';
            return;
        }

        neighborsEl.innerHTML = neighbors.map(n => `
            <div class="map-neighbor" onclick="NeonCityApp.travelTo('${this._esc(n.name)}', ${n.port || 0})" title="Travel to ${this._esc(n.name)}">
                <span class="map-neighbor-name">${this._esc(n.name)}</span>
                <span class="map-neighbor-cost">
                    <span class="cost-energy">-${n.energy_cost}E</span>
                    ${n.heat_add > 0 ? `<span class="cost-heat">+${n.heat_add}H</span>` : ''}
                </span>
            </div>
        `).join('');
    }

    /**
     * Travel to a city map node via the travel API.
     * @param {string} destination - City node name.
     * @param {number} port - Target scene port (for redirect URL).
     */
    async travelTo(destination, port) {
        this._appendChatEntry('system', '[CITY]', `Travelling to ${destination}...`);
        try {
            const res = await fetch('/api/city/travel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ destination }),
            });
            const data = await res.json();
            if (data.success) {
                const costs = [];
                if (data.energy_cost) costs.push(`-${data.energy_cost} energy`);
                if (data.heat_add)    costs.push(`+${data.heat_add} heat`);
                const costStr = costs.length ? ` (${costs.join(', ')})` : '';
                this._appendChatEntry('system', '[CITY]', `Arrived at ${data.to}.${costStr}`);
                if (port > 0) {
                    setTimeout(() => { window.location.href = `http://localhost:${port}/`; }, 1200);
                } else {
                    // Same scene (e.g. NEON CITY → NEON CITY) — just refresh
                    this._loadCityMap();
                    this.refreshHud();
                }
            } else {
                this._appendChatEntry('system', '[CITY]', `Travel blocked: ${data.message || 'Unknown'}`);
            }
        } catch (err) {
            this._appendChatEntry('system', '[CITY]', `Travel error: ${err.message}`);
        }
    }

    /** Request HUD state via Socket.IO. */
    refreshHud() {
        if (this.socket) this.socket.emit('get_hud');
    }

    /**
     * Handle full HUD state from Socket.IO or REST.
     * @param {Object} data - Combined player/inventory/crew/missions.
     */
    _onHudState(data) {
        if (data.player)    { this.playerState = data.player;   this._renderPlayerStats(data.player); }
        if (data.inventory) { this.inventory = data.inventory;  this._renderInventory(data.inventory); }
        if (data.equipped)  { this.equipped = data.equipped;    this._renderEquipped(data.equipped); }
        if (data.crew)      { this.crewData = data.crew;        this._renderCrew(data.crew); }
        if (data.missions)  { this.missionData = data.missions; this._renderMissions(); }
        if (data.balance !== undefined) this._updateCredits(data.balance);
    }

    /**
     * Handle incremental HUD update (e.g. from PlayerState auto-emit).
     * @param {Object} data - Partial player state update.
     */
    _onHudUpdate(data) {
        if (!this.playerState) this.playerState = {};
        Object.assign(this.playerState, data);
        this._renderPlayerStats(this.playerState);
        if (data.credits !== undefined) this._updateCredits(data.credits);
    }

    /**
     * Render player stat bars in the left sidebar.
     * @param {Object} ps - Player state dict.
     */
    _renderPlayerStats(ps) {
        const stats = [
            { key: 'health',     id: 'health',     max: 100 },
            { key: 'energy',     id: 'energy',     max: 100 },
            { key: 'heat',       id: 'heat',       max: 100 },
            { key: 'reputation', id: 'reputation', max: 100 },
        ];
        for (const s of stats) {
            const val = ps[s.key] ?? 0;
            const bar = document.getElementById(`stat-${s.id}`);
            const txt = document.getElementById(`val-${s.id}`);
            if (bar) bar.style.width = `${Math.min(100, Math.max(0, val))}%`;
            if (txt) txt.textContent = Math.round(val);
        }

        // Player skills chips
        const skillsEl = document.getElementById('player-skills');
        if (skillsEl && ps.skills) {
            skillsEl.innerHTML = Object.entries(ps.skills)
                .filter(([, v]) => v > 0)
                .map(([k, v]) => `<span class="skill-chip">${this._esc(k)} ${v}</span>`)
                .join('');
        }

        // Location
        const locEl = document.getElementById('loc-name');
        if (locEl && ps.active_location) locEl.textContent = ps.active_location;
    }

    /**
     * Render inventory grid.
     * @param {Array} items - Array of item objects from to_hud_dict().
     */
    _renderInventory(items) {
        const grid = document.getElementById('inventory-grid');
        if (!grid) return;

        const ITEM_ICONS = {
            'neural_jack': '&#129504;', 'reflex_booster': '&#9889;', 'subdermal_armor': '&#128737;',
            'stim_pack': '&#128138;', 'health_booster': '&#10084;', 'nano_blade': '&#128481;',
            'rail_pistol': '&#128299;', 'netrunner_mk1': '&#128187;', 'encrypted_file': '&#128196;',
            'corp_keycard': '&#128273;', 'ghost_net_token': '&#128123;', 'synth_ramen': '&#127836;',
            'black_lotus': '&#127800;', 'ice_breaker_v1': '&#10052;',
        };
        const RARITY_MAP = { 'common': '', 'uncommon': '', 'rare': 'rarity-rare', 'epic': 'rarity-epic', 'legendary': 'rarity-legendary' };

        let html = '';
        const slots = 12;
        for (let i = 0; i < slots; i++) {
            const item = items[i];
            if (item) {
                const icon = ITEM_ICONS[item.id] || '&#9670;';
                const rarity = RARITY_MAP[item.rarity] || '';
                const qty = (item.quantity > 1) ? `<span class="item-qty">x${item.quantity}</span>` : '';
                html += `<div class="inv-slot filled ${rarity}" title="${this._esc(item.name || item.id)}" onclick="NeonCityApp.onItemClick('${this._esc(item.id)}')">
                    <span class="item-icon">${icon}</span>${qty}
                </div>`;
            } else {
                html += '<div class="inv-slot empty"></div>';
            }
        }
        grid.innerHTML = html;
    }

    /**
     * Render equipped items tags.
     * @param {Object} equipped - Slot → item_id mapping.
     */
    _renderEquipped(equipped) {
        const row = document.getElementById('equipped-row');
        if (!row) return;
        const entries = Object.entries(equipped).filter(([, v]) => v);
        if (entries.length === 0) {
            row.innerHTML = '<span style="font-size:0.55rem;color:rgba(255,255,255,0.3)">No items equipped</span>';
            return;
        }
        row.innerHTML = entries
            .map(([slot, id]) => `<span class="equipped-tag" title="${slot}">${this._esc(id)}</span>`)
            .join('');
    }

    /**
     * Render crew roster in right sidebar.
     * @param {Object} crew - Crew data from to_hud_dict().
     */
    _renderCrew(crew) {
        const roster = document.getElementById('crew-roster');
        const countEl = document.getElementById('crew-count');
        if (!roster) return;

        const members = crew.members || crew.crew || [];
        if (countEl) countEl.textContent = `${members.length}/8`;

        if (members.length === 0) {
            roster.innerHTML = '<div class="crew-empty">No crew recruited yet.</div>';
            return;
        }

        roster.innerHTML = members.map(m => `
            <div class="crew-card">
                <div>
                    <div class="crew-name">${this._esc(m.name || m.character_id)}</div>
                    <div class="crew-role">${this._esc(m.role || 'unknown')}</div>
                </div>
                <div class="crew-level">LV${m.level || 1}</div>
                <div class="crew-loyalty-bar">
                    <div class="crew-loyalty-fill" style="width:${m.loyalty || 50}%"></div>
                </div>
            </div>
        `).join('');
    }

    /** Render mission list based on active tab. */
    _renderMissions() {
        const list = document.getElementById('mission-list');
        const countEl = document.getElementById('mission-count');
        if (!list) return;

        const missions = this._missionTab === 'active'
            ? (this.missionData.active || [])
            : (this.missionData.available || []);

        if (countEl) {
            const total = (this.missionData.available || []).length + (this.missionData.active || []).length;
            countEl.textContent = total > 0 ? total : '';
        }

        if (missions.length === 0) {
            list.innerHTML = `<div class="mission-empty">${this._missionTab === 'active' ? 'No active missions.' : 'No missions available.'}</div>`;
            return;
        }

        list.innerHTML = missions.map(m => {
            const typeClass = (m.type || m.mission_type || '').toLowerCase();
            const btn = this._missionTab === 'available'
                ? `<button class="mission-btn" onclick="NeonCityApp.acceptMission('${this._esc(m.id || m.mission_id)}')">ACCEPT</button>`
                : `<div class="mission-reward">&#9889; IN PROGRESS</div>`;
            const reward = m.rewards
                ? Object.entries(m.rewards).map(([k, v]) => `${v} ${k}`).join(', ')
                : '';
            return `
                <div class="mission-card">
                    <div class="mission-title">${this._esc(m.title || m.name || 'Unknown')}</div>
                    <div class="mission-meta">
                        <span class="mission-type ${typeClass}">${this._esc(typeClass || 'misc')}</span>
                        <span class="mission-difficulty">&#9733;${m.difficulty || 1}</span>
                    </div>
                    ${reward ? `<div class="mission-reward">&#8354; ${this._esc(reward)}</div>` : ''}
                    ${btn}
                </div>
            `;
        }).join('');
    }

    /**
     * Switch between available/active mission tabs.
     * @param {string} tab - 'available' or 'active'.
     */
    switchMissionTab(tab) {
        this._missionTab = tab;
        document.querySelectorAll('.mission-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.tab === tab);
        });
        this._renderMissions();
    }

    /**
     * Accept a mission from the board.
     * @param {string} missionId
     */
    async acceptMission(missionId) {
        try {
            const res = await fetch('/api/missions/accept', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mission_id: missionId }),
            });
            const data = await res.json();
            if (data.ok) {
                this._appendChatEntry('system', '[MISSIONS]', 'Mission accepted!');
                this.refreshHud();
            } else {
                this._appendChatEntry('system', '[MISSIONS]', `Failed: ${data.error || 'Unknown error'}`);
            }
        } catch (err) {
            this._appendChatEntry('system', '[MISSIONS]', `Error: ${err.message}`);
        }
    }

    /** Check crew operations (complete ready ones). */
    async checkCrewOps() {
        try {
            const res = await fetch('/api/crew');
            const data = await res.json();
            if (data.operations) {
                const ready = (data.operations || []).filter(op => op.status === 'completed');
                if (ready.length > 0) {
                    this._appendChatEntry('system', '[CREW]', `${ready.length} operation(s) completed!`);
                } else {
                    this._appendChatEntry('system', '[CREW]', 'No completed operations.');
                }
            }
            this.refreshHud();
        } catch (err) {
            this._appendChatEntry('system', '[CREW]', `Error: ${err.message}`);
        }
    }

    /**
     * Handle inventory item click (show tooltip or use).
     * @param {string} itemId
     */
    onItemClick(itemId) {
        const item = (this.inventory || []).find(i => i.id === itemId);
        if (!item) return;
        this._showToast(
            item.name || itemId,
            `${item.description || 'No description'}${item.category ? ` [${item.category}]` : ''}`,
            4000
        );
    }

    // ── Private helpers ───────────────────────────────────────────────────

    /**
     * Enter a district (placeholder for future scene navigation).
     * @param {string} districtKey
     */
    // v1.43.0 [2026-03-21] — Wire district entry to CityMap travel API
    async _enterDistrict(districtKey) {
        this.closeModal();
        const label = districtKey.replace(/_/g, ' ').toUpperCase();
        this._appendChatEntry('system', '[CITY]', `Initiating travel to ${label}...`);

        try {
            const res = await fetch('/api/district/enter', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ district: districtKey }),
            });
            const data = await res.json();

            if (data.success && data.url) {
                const cost = [];
                if (data.energy_cost) cost.push(`-${data.energy_cost} energy`);
                if (data.heat_add)    cost.push(`+${data.heat_add} heat`);
                const costStr = cost.length ? ` (${cost.join(', ')})` : '';
                this._appendChatEntry('system', '[CITY]',
                    `Arrived at ${data.scene}.${costStr} Redirecting...`);
                setTimeout(() => { window.location.href = data.url; }, 1500);
            } else {
                this._appendChatEntry('system', '[CITY]',
                    `Travel failed: ${data.message || data.error || 'Unknown error'}`);
            }
        } catch (err) {
            this._appendChatEntry('system', '[CITY]', `Network error: ${err.message}`);
        }
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

    // Fetch living-world district status on load and every 60 s
    NeonCityApp.fetchDistrictStatus();
    setInterval(() => NeonCityApp.fetchDistrictStatus(), 60_000);

    // Refresh faction status every 30 s
    setInterval(() => {
        if (NeonCityApp.socket) NeonCityApp.socket.emit('get_faction_status');
    }, 30_000);

    // v1.44.0 — Refresh HUD sidebars every 30 s
    setInterval(() => NeonCityApp.refreshHud(), 30_000);
});
