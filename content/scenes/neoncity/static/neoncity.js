/**
 * NeonCity — v1.57.3 "Polish Pass"
 * Living World Hub client-side controller.
 *
 * Handles Socket.IO state sync, district navigation, faction bars,
 * the world ticker, NPC chat, particle effects, mission CRUD,
 * crew operations, inventory context menu, heat warnings,
 * and rich event feed with color-coded cards.
 *
 * Version: v1.57.3 [2026-05-12]
 * Change Log:
 *   v1.57.3 [2026-05-12] — animateBarFill helper, stat/faction bar fill
 *                            animations on load, border-trace on district select
 *   v1.52.0 [2026-03-22] — Three Pillars: district online/offline detection,
 *                            exchange_credits result handler, credit flash
 *                            animations, NPC typing indicator, enhanced
 *                            _renderDistricts with NPC/desc updates, same-scene
 *                            district travel handling
 *   v1.46.0 [2026-03-21] — Rich event feed (color-coded cards, type icons,
 *                            severity dots, impact badges, click-to-expand)
 *   v1.45.0 [2026-03-21] — Mission detail modal, crew ops launcher,
 *                            active op timers, inventory context menu,
 *                            fixed crew rendering (to_dict format)
 *   v1.44.0 [2026-03-21] — HUD sidebar panels, 3-column layout
 *   v0.68   [2026-03-20] — Initial Socket.IO + district controller
 */

'use strict';

// ────────────────────────────────────────────────────────────────────────────
// Utility helpers
// ────────────────────────────────────────────────────────────────────────────

// v1.57.3 [2026-05-12] — Animate bar from 0 to target
/**
 * Smoothly animate a bar element from 0% to a target percentage.
 * @param {HTMLElement|null} el - The bar fill element.
 * @param {number} targetPct - Target width as a percentage (0–100).
 * @param {number} [delayMs=0] - Optional stagger delay in milliseconds.
 */
function animateBarFill(el, targetPct, delayMs = 0) {
  if (!el) return;
  el.style.width = '0%';
  el.style.transition = 'none';
  setTimeout(() => {
    el.style.transition = `width 0.8s cubic-bezier(0.4, 0, 0.2, 1) ${delayMs}ms`;
    el.style.width = targetPct + '%';
  }, 20);
}

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

        // v1.45.0 — Mission detail + crew ops state
        /** @type {string|null} Mission ID shown in detail modal */
        this._activeMissionId = null;

        /** @type {Object|null} Full mission data for detail modal */
        this._activeMissionData = null;

        /** @type {string|null} Selected crew operation type */
        this._selectedOpType = null;

        /** @type {Set<string>} Selected crew member IDs for operation */
        this._selectedCrewIds = new Set();

        /** @type {number|null} Interval ID for crew op countdown timers */
        this._opTimerInterval = null;

        /** @type {Object|null} Item context menu element ref */
        this._contextMenu = null;
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
            console.debug('[NeonCity] Socket connected.');
            this.loadCityState();
        });

        this.socket.on('disconnect', () => {
            console.debug('[NeonCity] Socket disconnected.');
        });

        // v1.49.2 [2026-03-22] — Socket.IO reconnect feedback
        this.socket.io.on('reconnect', (attempt) => {
            console.debug('[NeonCity] Reconnected after ' + attempt + ' attempt(s)');
        });
        this.socket.io.on('reconnect_attempt', (attempt) => {
            if (attempt % 3 === 0) console.debug('[NeonCity] Reconnecting... (attempt ' + attempt + ')');
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
        // v1.52.0 — Exchange credits result handler
        this.socket.on('exchange_result', (data) => this._onExchangeResult(data));
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

        // v1.57.3 [2026-05-12] — Border trace on selected card
        document.querySelectorAll('.nc-district').forEach(el => el.classList.remove('tracing'));
        const card = document.querySelector(`.nc-district[data-district="${districtKey}"]`);
        if (card) {
            card.classList.add('anim-border-trace');
            card.classList.remove('tracing');
            void card.offsetWidth;
            card.classList.add('tracing');
        }

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

        // v1.52.0 — NPCs with recruit buttons
        const npcContainer = document.getElementById('modal-npc-list');
        if (npcContainer) {
            const ROLE_MAP = {
                'FIXER': 'fixer', 'ARMORER': 'tech', 'INFO_BROKER': 'lookout',
                'EXEC': 'face', 'SEC_AGENT': 'muscle', 'CORP_LIAISON': 'face',
                'BARTENDER': 'supplier', 'DANCER': 'face', 'CONTACT': 'fixer',
                '0xGH0ST': 'hacker', 'NETRUNNER': 'hacker', 'SYSOP': 'tech',
                'STREET_KID': 'lookout', 'GANGER': 'muscle', 'INFORMANT': 'lookout',
            };
            npcContainer.innerHTML = (d.npcs || [])
                .map(n => {
                    const role = ROLE_MAP[n] || 'unknown';
                    return `<div class="modal-npc-card">
                        <span class="modal-npc-tag">${this._esc(n)}</span>
                        <button class="nc-btn nc-btn--xs nc-btn--gift" onclick="event.stopPropagation();NeonCityApp.giftNpc('${this._esc(n)}')">GIFT</button>
                        <button class="nc-btn nc-btn--xs" onclick="event.stopPropagation();NeonCityApp.recruitNpc('${this._esc(n)}', '${role}')">RECRUIT</button>
                    </div>`;
                })
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

    // v1.46.0 [2026-03-21] — Rich event cards with type colors, impacts, expand
    // CONNECTS: WorldSim events, _esc(), events-list DOM
    // CALLED BY: Socket.IO 'world_events' handler
    // EMITS: DOM updates to #events-list

    /**
     * Handle world events list — renders color-coded event cards.
     * @param {Object} data - World events payload with rich metadata.
     */
    _onWorldEvents(data) {
        const list = document.getElementById('events-list');
        if (!list) return;
        const events = data.events || [];
        if (events.length === 0) {
            list.innerHTML = '<div class="event-item system">No active events detected.</div>';
            return;
        }
        list.innerHTML = events.map(ev => this._renderEventCard(ev)).join('');
    }

    /**
     * Render a single rich event card with type icon, severity, impacts.
     * @param {Object} ev - Event object from backend.
     * @returns {string} HTML string for the event card.
     */
    _renderEventCard(ev) {
        const typeMap = {
            npc_action:      { icon: '&#9670;', cls: 'npc',     label: 'NPC' },
            faction_shift:   { icon: '&#9876;', cls: 'faction',  label: 'FACTION' },
            scene_ambient:   { icon: '&#9788;', cls: 'ambient',  label: 'AMBIENT' },
            hacker_message:  { icon: '&#9000;', cls: 'hacker',   label: 'GHOST' },
            arena_match:     { icon: '&#9876;', cls: 'arena',    label: 'ARENA' },
            world_event:     { icon: '&#9888;', cls: 'world',    label: 'WORLD' },
            economy_tick:    { icon: '&#8354;', cls: 'economy',  label: 'ECON' },
        };
        const info = typeMap[ev.event_type] || { icon: '&#9673;', cls: 'unknown', label: ev.event_type || '???' };

        // Severity dots: 0–3 scale
        const intensity = Math.min(3, Math.max(0, Math.round(ev.intensity || 1)));
        const dots = '<span class="ev-dot active"></span>'.repeat(intensity)
                   + '<span class="ev-dot"></span>'.repeat(3 - intensity);

        // Impact badges — only show non-zero
        let badges = '';
        if (ev.economy_impact) {
            const sign = ev.economy_impact > 0 ? '+' : '';
            badges += `<span class="ev-badge econ">${sign}${ev.economy_impact}&#8354;</span>`;
        }
        if (ev.heat_impact) {
            const sign = ev.heat_impact > 0 ? '+' : '';
            badges += `<span class="ev-badge heat">${sign}${ev.heat_impact} HT</span>`;
        }
        if (ev.rep_impact) {
            const sign = ev.rep_impact > 0 ? '+' : '';
            badges += `<span class="ev-badge rep">${sign}${ev.rep_impact} REP</span>`;
        }

        // Actor tag
        const actor = ev.actor
            ? `<span class="ev-actor">${this._esc(ev.actor)}</span>` : '';

        // Faction tag
        const faction = ev.faction
            ? `<span class="ev-faction">${this._esc(ev.faction)}</span>` : '';

        const title = this._esc(ev.title || ev.description || ev.id);
        const desc = this._esc(ev.description || '');
        const time = ev.created_at ? `<span class="ev-time">${this._esc(ev.created_at)}</span>` : '';
        const cardId = `ev-${ev.id || Math.random().toString(36).slice(2, 8)}`;

        return `<div class="event-card ev-${info.cls}" id="${cardId}"
                     onclick="this.classList.toggle('expanded')">
            <div class="ev-header">
                <span class="ev-type-icon">${info.icon}</span>
                <span class="ev-type-label">${info.label}</span>
                <span class="ev-severity">${dots}</span>
                ${time}
            </div>
            <div class="ev-title">${title}</div>
            <div class="ev-details">
                <div class="ev-desc">${desc}</div>
                <div class="ev-meta">
                    ${actor}${faction}${badges}
                </div>
            </div>
        </div>`;
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
     * v1.52.0 [2026-03-22] — Remove typing indicator on NPC reply
     * @param {Object} data - City event payload.
     */
    _onCityEvent(data) {
        this._removeTypingIndicator();
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
     * v1.52.0 [2026-03-22] — Also updates NPC tags and descriptions
     * @param {Object} state - City state object.
     * CONNECTS: _build_city_state(), district card DOM
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

            // v1.52.0 — Update NPC tags dynamically
            const npcEl = document.getElementById(`npcs-${key}`);
            if (npcEl && d.npcs && Array.isArray(d.npcs)) {
                npcEl.innerHTML = d.npcs
                    .map(n => `<span class="nc-npc-tag">${this._esc(n)}</span>`)
                    .join('');
            }
        });
    }

    // v1.52.0 [2026-03-22] — District scene online/offline status polling
    // CONNECTS: /api/district/scene_status, district card DOM
    // CALLED BY: DOMContentLoaded, 60s interval

    /**
     * Fetch district scene statuses and update indicators on cards.
     */
    async _updateDistrictStatuses() {
        try {
            const res = await fetch('/api/district/scene_status');
            const statuses = await res.json();
            this._districtSceneStatuses = statuses;
            Object.entries(statuses).forEach(([key, info]) => {
                const statusEl = document.getElementById(`status-${key}`);
                if (!statusEl) return;
                const dot = statusEl.querySelector('.status-dot');
                const label = statusEl.querySelector('.status-label');
                const card = statusEl.closest('.nc-district');
                if (info.is_running) {
                    if (dot) dot.className = 'status-dot online';
                    if (label) { label.textContent = 'ONLINE'; label.className = 'status-label online'; }
                    if (card) card.classList.remove('district-offline');
                } else {
                    if (dot) dot.className = 'status-dot offline';
                    if (label) { label.textContent = 'OFFLINE'; label.className = 'status-label offline'; }
                    if (card) card.classList.add('district-offline');
                }
            });
        } catch (e) {
            console.warn('[NeonCity] district scene_status fetch failed:', e);
        }
    }

    /**
     * Render faction tension bars.
     * @param {Array<Object>} factions - Array of faction data objects.
     */
    _renderFactionBars(factions) {
        const standings = (this._districtStatus || {}).faction_standings || {};
        // v1.57.3 [2026-05-12] — Animate faction bars in with stagger
        factions.forEach((f, idx) => {
            const bar = document.getElementById(`bar-${f.name}`);
            if (bar) {
                bar.style.background = f.color || '#06b6d4';
                animateBarFill(bar, f.power, idx * 100);
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
     * Update the credit balance display with optional flash animation.
     * v1.52.0 [2026-03-22] — Added flash animation on value change
     * @param {number} balance - Current credit balance.
     */
    _updateCredits(balance) {
        if (balance === undefined || balance === null) return;
        const el1 = document.getElementById('credit-balance');
        const el2 = document.getElementById('econ-balance');
        // Detect direction of change for flash animation
        const prev = this._lastCredits ?? balance;
        this._lastCredits = balance;
        const flashClass = balance > prev ? 'flash-up' : balance < prev ? 'flash-down' : '';
        if (el1) {
            el1.textContent = balance.toLocaleString();
            if (flashClass) {
                el1.classList.remove('flash-up', 'flash-down');
                void el1.offsetWidth; // force reflow to restart animation
                el1.classList.add(flashClass);
            }
        }
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

    /**
     * Send a chat message to the active district.
     * v1.52.0 [2026-03-22] — Added typing indicator while waiting for NPC reply
     */
    sendMessage() {
        const input = document.getElementById('chat-input');
        if (!input) return;
        const text = input.value.trim();
        if (!text) return;
        input.value = '';

        this._appendChatEntry('player', '[YOU]', text);

        // Emit to server — show typing indicator while waiting
        if (this.socket && this.activeDistrict) {
            this._showTypingIndicator();
            this.socket.emit('district_chat', {
                district: this.activeDistrict,
                message: text,
            });
        }
    }

    // v1.52.0 [2026-03-22] — NPC typing indicator
    /** Show a typing indicator in the chat log. */
    _showTypingIndicator() {
        this._removeTypingIndicator();
        const log = document.getElementById('chat-log');
        if (!log) return;
        const div = document.createElement('div');
        div.className = 'chat-entry npc nc-typing-entry';
        div.id = 'npc-typing';
        div.innerHTML = '<span class="entry-src">[NPC]</span><span class="nc-typing"><span class="nc-typing__dot"></span><span class="nc-typing__dot"></span><span class="nc-typing__dot"></span></span>';
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
    }

    /** Remove the typing indicator from the chat log. */
    _removeTypingIndicator() {
        const existing = document.getElementById('npc-typing');
        if (existing) existing.remove();
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

    // v1.52.0 [2026-03-22] — Exchange credits result handler
    // CONNECTS: exchange_credits Socket.IO handler
    // CALLED BY: Socket.IO 'exchange_result' event
    /**
     * Handle exchange credits result from server.
     * @param {Object} data - Exchange result payload.
     */
    _onExchangeResult(data) {
        if (data.success) {
            this._showToast('EXCHANGE', data.message || 'Exchange complete.', 4000);
            this._appendChatEntry('system', '[BANK]', data.message || `${data.action} ₵${data.amount}`);
            if (data.wallet !== undefined) this._updateCredits(data.wallet);
            if (data.balance !== undefined) {
                const econ = document.getElementById('econ-balance');
                if (econ) econ.textContent = `₢ ${data.balance.toLocaleString()}`;
            }
        } else {
            this._showToast('EXCHANGE FAILED', data.error || 'Unknown error.', 5000);
            this._appendChatEntry('system', '[BANK]', data.error || 'Exchange failed.');
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
        if (data.skills)    { this._renderSkillProgression(data.skills); }
        if (data.balance !== undefined) this._updateCredits(data.balance);
        // v1.45.0 — Apply heat warnings
        if (data.player && data.player.heat !== undefined) this._applyHeatWarnings(data.player.heat);
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
        // v1.45.0 — Heat warnings on incremental updates
        if (data.heat !== undefined) this._applyHeatWarnings(data.heat);
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
        // v1.57.3 [2026-05-12] — Animate bars in with stagger on each load
        stats.forEach((s, index) => {
            const val = ps[s.key] ?? 0;
            const bar = document.getElementById(`stat-${s.id}`);
            const txt = document.getElementById(`val-${s.id}`);
            animateBarFill(bar, Math.min(100, Math.max(0, val)), index * 80);
            if (txt) txt.textContent = Math.round(val);
        });

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
                html += `<div class="inv-slot filled ${rarity}" title="${this._esc(item.name || item.id)}" onclick="NeonCityApp.onItemClick('${this._esc(item.id)}', event)">
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
     * v1.45.0 — Updated to handle CrewManager.to_dict() format with members
     *           array, role icons, availability badges, and dismiss buttons.
     * @param {Object|Array} crew - Crew data (to_dict object or legacy array).
     * CONNECTS: CrewManager.to_dict(), /api/hud, /api/crew
     */
    _renderCrew(crew) {
        const roster = document.getElementById('crew-roster');
        const countEl = document.getElementById('crew-count');
        if (!roster) return;

        // Handle both to_dict() {members:[...]} and legacy flat array
        const members = Array.isArray(crew) ? crew : (crew.members || []);
        const maxSize = crew.max_size || 8;
        if (countEl) countEl.textContent = `${members.length}/${maxSize}`;

        if (members.length === 0) {
            roster.innerHTML = '<div class="crew-empty">No crew recruited yet.</div>';
            this._renderCrewOps([]);
            return;
        }

        const ROLE_ICONS = {
            fixer: '\u{1F91D}', hacker: '\u{1F4BB}', muscle: '\u{1F4AA}',
            medic: '\u{1FA7A}', driver: '\u{1F697}', tech: '\u{1F527}',
            lookout: '\u{1F441}', face: '\u{1F3AD}', supplier: '\u{1F4E6}',
            unknown: '\u2753',
        };

        // v1.52.0 — Crew cards with dismiss button and ops count
        roster.innerHTML = members.map(m => {
            const icon = m.role_icon || ROLE_ICONS[m.role] || '\u2753';
            const name = m.character_id || m.name || m.id || 'Unknown';
            const avail = m.available !== false;
            const availClass = avail ? 'available' : 'unavailable';
            const availLabel = avail ? 'READY' : 'DEPLOYED';
            const opsCount = m.operations_count || 0;
            return `
            <div class="crew-card ${availClass}" data-crew-id="${this._esc(name)}">
                <div class="crew-left">
                    <span class="crew-icon">${icon}</span>
                    <div>
                        <div class="crew-name">${this._esc(name)}</div>
                        <div class="crew-role">${this._esc(m.role_label || m.role || 'unknown')}${opsCount ? ` \u00b7 ${opsCount} ops` : ''}</div>
                    </div>
                </div>
                <div class="crew-right">
                    <span class="crew-avail ${availClass}">${availLabel}</span>
                    <span class="crew-level">LV${m.level || 1}</span>
                    <button class="nc-btn nc-btn--xs nc-btn--ghost crew-dismiss" onclick="event.stopPropagation();NeonCityApp.dismissCrewMember('${this._esc(name)}')" title="Dismiss ${this._esc(name)}">\u2715</button>
                </div>
                <div class="crew-loyalty-bar">
                    <div class="crew-loyalty-fill" style="width:${m.loyalty || 50}%"></div>
                </div>
            </div>`;
        }).join('');

        // Render active operations timers
        const ops = crew.active_operations || [];
        this._renderCrewOps(ops);
    }

    /**
     * Render active crew operations with countdown timers.
     * v1.45.0 [2026-03-21]
     * @param {Array} ops - Active operations from CrewManager.to_dict().
     * CONNECTS: CrewManager, crew-active-ops div
     */
    _renderCrewOps(ops) {
        const container = document.getElementById('crew-active-ops');
        if (!container) return;

        if (!ops || ops.length === 0) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = ops.map(op => {
            const remaining = op.time_remaining || 0;
            const mins = Math.floor(remaining / 60);
            const secs = remaining % 60;
            const pct = op.duration_secs > 0
                ? Math.max(0, 100 - (remaining / op.duration_secs * 100))
                : 100;
            return `
            <div class="crew-op-card" data-op-id="${this._esc(op.op_id)}">
                <div class="cop-header">
                    <span class="cop-label">${this._esc(op.label)}</span>
                    <span class="cop-timer">${mins}:${String(secs).padStart(2, '0')}</span>
                </div>
                <div class="cop-bar-track">
                    <div class="cop-bar-fill" style="width:${pct}%"></div>
                </div>
                <div class="cop-crew-tags">${op.assigned_crew.map(c =>
                    `<span class="cop-crew-tag">${this._esc(c)}</span>`
                ).join('')}</div>
            </div>`;
        }).join('');

        // Start countdown timer if not already running
        this._startOpTimers();
    }

    /** Start interval to tick down crew operation timers every second. */
    _startOpTimers() {
        if (this._opTimerInterval) return;
        this._opTimerInterval = setInterval(() => {
            const cards = document.querySelectorAll('.crew-op-card');
            if (cards.length === 0) {
                clearInterval(this._opTimerInterval);
                this._opTimerInterval = null;
                return;
            }
            cards.forEach(card => {
                const timerEl = card.querySelector('.cop-timer');
                if (!timerEl) return;
                const parts = timerEl.textContent.split(':');
                let total = parseInt(parts[0]) * 60 + parseInt(parts[1]) - 1;
                if (total <= 0) {
                    timerEl.textContent = 'DONE!';
                    timerEl.classList.add('cop-done');
                    card.classList.add('op-complete');
                } else {
                    const m = Math.floor(total / 60);
                    const s = total % 60;
                    timerEl.textContent = `${m}:${String(s).padStart(2, '0')}`;
                }
            });
        }, 1000);
    }

    // ── Mission rendering + interaction ─────────────────────────────
    // v1.45.0 [2026-03-21] — Clickable cards, detail modal, CRUD
    // CONNECTS: MissionManager, /api/missions/*, mission-detail-modal

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
            const mId = m.id || m.mission_id || '';
            const typeClass = (m.type || m.mission_type || '').toLowerCase();
            const stars = '\u2605'.repeat(m.difficulty || 1) + '\u2606'.repeat(5 - (m.difficulty || 1));
            const reward = m.reward || m.rewards || {};
            const rewardStr = [];
            if (reward.credits)    rewardStr.push(`\u20B4${reward.credits}`);
            if (reward.xp)         rewardStr.push(`${reward.xp} XP`);
            if (reward.reputation) rewardStr.push(`+${reward.reputation} REP`);

            const isActive = this._missionTab === 'active';
            const progress = m.progress || {};
            const pctBar = isActive && progress.pct !== undefined
                ? `<div class="mission-mini-bar"><div class="mission-mini-fill" style="width:${progress.pct}%"></div></div>`
                : '';

            return `
                <div class="mission-card clickable" onclick="NeonCityApp.openMissionDetail('${this._esc(mId)}')">
                    <div class="mission-title">${this._esc(m.title || m.name || 'Unknown')}</div>
                    <div class="mission-meta">
                        <span class="mission-type ${typeClass}">${this._esc(typeClass || 'misc')}</span>
                        <span class="mission-difficulty">${stars}</span>
                    </div>
                    ${rewardStr.length ? `<div class="mission-reward">${this._esc(rewardStr.join(' / '))}</div>` : ''}
                    ${pctBar}
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
     * Open mission detail modal for a given mission.
     * Fetches full mission data from /api/missions/<id>.
     * v1.45.0 [2026-03-21]
     * @param {string} missionId
     * CONNECTS: MissionManager.get_mission(), mission-detail-modal
     */
    async openMissionDetail(missionId) {
        try {
            const res = await fetch(`/api/missions/${encodeURIComponent(missionId)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const m = await res.json();
            this._activeMissionId = missionId;
            this._activeMissionData = m;
            this._renderMissionModal(m);
            document.getElementById('mission-modal').style.display = '';
        } catch (err) {
            this._showToast('ERROR', `Failed to load mission: ${err.message}`, 5000);
        }
    }

    /**
     * Populate mission detail modal with data.
     * @param {Object} m - Full mission dict from API.
     */
    _renderMissionModal(m) {
        const typeEl = document.getElementById('mm-type');
        const titleEl = document.getElementById('mm-title');
        const diffEl = document.getElementById('mm-difficulty');
        const giverEl = document.getElementById('mm-giver');
        const locEl = document.getElementById('mm-location');
        const descEl = document.getElementById('mm-description');
        const objList = document.getElementById('mm-objectives-list');
        const progFill = document.getElementById('mm-progress-fill');
        const progPct = document.getElementById('mm-progress-pct');
        const rewardsEl = document.getElementById('mm-rewards');
        const crewSection = document.getElementById('mm-crew-section');
        const crewList = document.getElementById('mm-crew-list');
        const timeSection = document.getElementById('mm-time-section');
        const timeVal = document.getElementById('mm-time-value');
        const btnComplete = document.getElementById('mm-btn-complete');
        const btnAbandon = document.getElementById('mm-btn-abandon');
        const btnAccept = document.getElementById('mm-btn-accept');

        const type = (m.type || '').toUpperCase();
        if (typeEl) typeEl.textContent = type;
        if (titleEl) titleEl.textContent = m.title || 'Unknown';
        if (diffEl) {
            const d = m.difficulty || 1;
            diffEl.textContent = '\u2605'.repeat(d) + '\u2606'.repeat(5 - d);
        }
        if (giverEl) giverEl.textContent = `Given by: ${m.giver || '???'}`;
        if (locEl) locEl.textContent = `\u25C9 ${m.location || '???'}`;
        if (descEl) descEl.textContent = m.description || '';

        // v1.52.0 — Clickable objectives: mark complete via /api/missions/objective
        // CONNECTS: MissionManager.complete_objective(), progress bar
        if (objList) {
            const objs = m.objectives || [];
            const missionId = this._activeMissionId;
            const isActive = (m.status || '') === 'active';
            objList.innerHTML = objs.map((o, idx) => {
                const done = o.completed ? 'checked' : '';
                const opt = o.optional ? ' <span class="obj-optional">[OPTIONAL]</span>' : '';
                const clickable = isActive && !o.completed ? 'clickable' : '';
                const objId = o.id || `obj_${idx}`;
                const onclick = (isActive && !o.completed)
                    ? `onclick="NeonCityApp.completeObjective('${this._esc(missionId)}', '${this._esc(objId)}')"`
                    : '';
                return `<div class="mm-obj-row ${done} ${clickable}" ${onclick} title="${isActive && !o.completed ? 'Click to mark complete' : ''}">
                    <span class="mm-obj-check">${o.completed ? '\u2611' : '\u2610'}</span>
                    <span class="mm-obj-desc">${this._esc(o.description)}${opt}</span>
                </div>`;
            }).join('');
        }

        // Progress bar
        const progress = m.progress || { done: 0, total: 0, pct: 0 };
        if (progFill) progFill.style.width = `${progress.pct}%`;
        if (progPct) progPct.textContent = `${progress.pct}%`;

        // Rewards grid
        const r = m.reward || {};
        if (rewardsEl) {
            const chips = [];
            if (r.credits)    chips.push(`<span class="mm-reward-chip credits">\u20B4 ${r.credits}</span>`);
            if (r.xp)         chips.push(`<span class="mm-reward-chip xp">${r.xp} XP</span>`);
            if (r.reputation) chips.push(`<span class="mm-reward-chip rep">+${r.reputation} REP</span>`);
            if (r.faction && r.faction_rep) {
                const sign = r.faction_rep > 0 ? '+' : '';
                chips.push(`<span class="mm-reward-chip faction">${sign}${r.faction_rep} ${r.faction}</span>`);
            }
            if (r.items && r.items.length) {
                r.items.forEach(i => chips.push(`<span class="mm-reward-chip item">${this._esc(i)}</span>`));
            }
            rewardsEl.innerHTML = chips.join('');
        }

        // Assigned crew
        if (crewSection) {
            if (m.assigned_crew && m.assigned_crew.length > 0) {
                crewSection.style.display = '';
                if (crewList) crewList.innerHTML = m.assigned_crew
                    .map(c => `<span class="mm-crew-tag">${this._esc(c)}</span>`).join('');
            } else {
                crewSection.style.display = 'none';
            }
        }

        // Time limit
        if (timeSection) {
            if (m.time_limit_min) {
                timeSection.style.display = '';
                if (timeVal) timeVal.textContent = `${m.time_limit_min} min time limit`;
            } else {
                timeSection.style.display = 'none';
            }
        }

        // Action buttons — show based on mission status
        const status = m.status || '';
        if (btnAccept)  btnAccept.style.display  = status === 'available' ? '' : 'none';
        if (btnComplete) btnComplete.style.display = (status === 'active' && progress.pct === 100) ? '' : 'none';
        if (btnAbandon) btnAbandon.style.display  = status === 'active' ? '' : 'none';
    }

    /** Close mission detail modal. */
    closeMissionModal() {
        document.getElementById('mission-modal').style.display = 'none';
        this._activeMissionId = null;
        this._activeMissionData = null;
    }

    /**
     * Accept a mission (from board list or from detail modal).
     * @param {string} [missionId] - If omitted, uses modal's active mission.
     */
    async acceptMission(missionId) {
        const id = missionId || this._activeMissionId;
        if (!id) return;
        try {
            const res = await fetch('/api/missions/accept', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mission_id: id }),
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('MISSION ACCEPTED', data.message || 'Good luck.', 4000);
                this._appendChatEntry('system', '[MISSIONS]', data.message || 'Mission accepted!');
                this.closeMissionModal();
                this.refreshHud();
            } else {
                this._showToast('FAILED', data.error || data.message || 'Unknown error', 5000);
            }
        } catch (err) {
            this._appendChatEntry('system', '[MISSIONS]', `Error: ${err.message}`);
        }
    }

    /** Accept mission from the detail modal. */
    acceptMissionFromModal() {
        this.acceptMission(this._activeMissionId);
    }

    /**
     * Complete the currently viewed active mission.
     * v1.45.0 [2026-03-21]
     * CONNECTS: MissionManager.complete(), /api/missions/complete
     */
    async completeMission() {
        const id = this._activeMissionId;
        if (!id) return;
        try {
            const res = await fetch('/api/missions/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mission_id: id }),
            });
            const data = await res.json();
            if (data.ok) {
                const rewards = data.rewards || {};
                const parts = [];
                if (rewards.credits)    parts.push(`\u20B4${rewards.credits}`);
                if (rewards.xp)         parts.push(`${rewards.xp} XP`);
                if (rewards.reputation) parts.push(`+${rewards.reputation} REP`);
                this._showToast('MISSION COMPLETE!', parts.join(' / ') || 'Rewards applied.', 6000);
                this._appendChatEntry('event', '[MISSIONS]', data.message || 'Mission completed!');
                this.closeMissionModal();
                this.refreshHud();
            } else {
                this._showToast('CANNOT COMPLETE', data.message || data.error || 'Check objectives.', 5000);
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 5000);
        }
    }

    /**
     * Abandon the currently viewed active mission.
     * v1.45.0 [2026-03-21]
     * CONNECTS: MissionManager.abandon(), /api/missions/abandon
     */
    async abandonMission() {
        const id = this._activeMissionId;
        if (!id) return;
        if (!confirm('Abandon this mission? You will lose 3 reputation.')) return;
        try {
            const res = await fetch('/api/missions/abandon', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mission_id: id }),
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('MISSION ABANDONED', data.message || '-3 REP', 5000);
                this._appendChatEntry('system', '[MISSIONS]', data.message || 'Mission abandoned.');
                this.closeMissionModal();
                this.refreshHud();
            } else {
                this._showToast('ERROR', data.message || data.error, 5000);
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 5000);
        }
    }

    // ── Mission Objective Completion ─────────────────────────────────
    // v1.52.0 [2026-03-22] — Click objectives to mark them complete
    // CONNECTS: /api/missions/objective, MissionManager.complete_objective()

    /**
     * Mark a mission objective as complete.
     * @param {string} missionId
     * @param {string} objectiveId - Objective identifier string.
     */
    async completeObjective(missionId, objectiveId) {
        try {
            const res = await fetch('/api/missions/objective', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mission_id: missionId, objective_id: objectiveId }),
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('OBJECTIVE COMPLETE', data.message || 'Objective marked done.', 4000);
                this._appendChatEntry('event', '[MISSIONS]', data.message || 'Objective completed!');
                // Refresh the mission detail modal to show updated progress
                this.openMissionDetail(missionId);
                this.refreshHud();
            } else {
                this._showToast('FAILED', data.error || data.message || 'Cannot complete objective.', 4000);
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 4000);
        }
    }

    // ── Crew operations ──────────────────────────────────────────────
    // v1.45.0 [2026-03-21] — Launch ops modal, check ops, dismiss
    // CONNECTS: CrewManager, /api/crew/*, crew-ops-modal

    /**
     * Check crew operations — resolve completed ones, show results.
     * v1.45.0 [2026-03-21]
     */
    async checkCrewOps() {
        try {
            const res = await fetch('/api/crew/check_ops', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            const data = await res.json();
            if (data.ok && data.completed && data.completed.length > 0) {
                for (const op of data.completed) {
                    const parts = [];
                    if (op.credits_earned) parts.push(`\u20B4${op.credits_earned}`);
                    if (op.xp_earned) parts.push(`${op.xp_earned} XP`);
                    this._showToast('OP COMPLETE!', `${op.label}: ${parts.join(' + ')}`, 6000);
                    this._appendChatEntry('event', '[CREW]', `${op.label} completed! ${parts.join(' + ')}`);
                }
            } else {
                this._appendChatEntry('system', '[CREW]', 'No completed operations.');
            }
            this.refreshHud();
        } catch (err) {
            this._appendChatEntry('system', '[CREW]', `Error: ${err.message}`);
        }
    }

    /**
     * Open the crew operations modal.
     * v1.45.0 [2026-03-21]
     * CONNECTS: OPERATION_TYPES, CrewManager.get_available()
     */
    openCrewOpsModal() {
        this._selectedOpType = null;
        this._selectedCrewIds = new Set();

        const OP_TYPES = {
            recon:      { label: 'Recon',      icon: '\u{1F50D}', min: 1, desc: 'Gather intel' },
            heist:      { label: 'Heist',      icon: '\u{1F4B0}', min: 3, desc: 'Steal item/credits' },
            extraction: { label: 'Extraction',  icon: '\u{1F6A8}', min: 2, desc: 'Extract person/data' },
            deal:       { label: 'Deal',        icon: '\u{1F91D}', min: 1, desc: 'Negotiate a trade' },
            hit:        { label: 'Hit',         icon: '\u{1F3AF}', min: 2, desc: 'Neutralise target' },
            hack:       { label: 'Hack',        icon: '\u{1F4BB}', min: 1, desc: 'Cyberspace intrusion' },
        };

        // Render operation type selector
        const typeGrid = document.getElementById('cop-type-grid');
        if (typeGrid) {
            typeGrid.innerHTML = Object.entries(OP_TYPES).map(([key, op]) => `
                <div class="cop-type-card" data-op="${key}" onclick="NeonCityApp._selectOpType('${key}')">
                    <div class="cop-type-icon">${op.icon}</div>
                    <div class="cop-type-label">${op.label}</div>
                    <div class="cop-type-desc">${op.desc}</div>
                    <div class="cop-type-min">Min ${op.min} crew</div>
                </div>
            `).join('');
        }

        // Render available crew for selection
        this._renderCrewSelector();

        // Reset summary
        document.getElementById('cop-summary').style.display = 'none';
        document.getElementById('btn-launch-op').disabled = true;

        document.getElementById('crew-ops-modal').style.display = '';
    }

    /** Close crew operations modal. */
    closeCrewOpsModal() {
        document.getElementById('crew-ops-modal').style.display = 'none';
    }

    /**
     * Select an operation type in the modal.
     * @param {string} opType
     */
    _selectOpType(opType) {
        this._selectedOpType = opType;
        document.querySelectorAll('.cop-type-card').forEach(card => {
            card.classList.toggle('selected', card.dataset.op === opType);
        });

        const OP_MIN = { recon: 1, heist: 3, extraction: 2, deal: 1, hit: 2, hack: 1 };
        const minLabel = document.getElementById('cop-min-label');
        if (minLabel) minLabel.textContent = `(min ${OP_MIN[opType] || 1})`;

        this._updateOpSummary();
    }

    /**
     * Render the crew member checkboxes in the ops modal.
     * Uses crewData from last HUD fetch.
     */
    _renderCrewSelector() {
        const listEl = document.getElementById('cop-crew-list');
        if (!listEl) return;

        const members = this.crewData
            ? (Array.isArray(this.crewData) ? this.crewData : (this.crewData.members || []))
            : [];

        if (members.length === 0) {
            listEl.innerHTML = '<div class="crew-empty">No crew to assign. Recruit first!</div>';
            return;
        }

        const ROLE_ICONS = {
            fixer: '\u{1F91D}', hacker: '\u{1F4BB}', muscle: '\u{1F4AA}',
            medic: '\u{1FA7A}', driver: '\u{1F697}', tech: '\u{1F527}',
            lookout: '\u{1F441}', face: '\u{1F3AD}', supplier: '\u{1F4E6}',
            unknown: '\u2753',
        };

        listEl.innerHTML = members.map(m => {
            const name = m.character_id || m.name || m.id || 'Unknown';
            const icon = m.role_icon || ROLE_ICONS[m.role] || '\u2753';
            const avail = m.available !== false;
            return `
            <label class="cop-crew-row ${avail ? '' : 'disabled'}" data-crew-id="${this._esc(name)}">
                <input type="checkbox" ${avail ? '' : 'disabled'}
                       onchange="NeonCityApp._toggleCrewSelection('${this._esc(name)}', this.checked)">
                <span class="cop-crew-icon">${icon}</span>
                <span class="cop-crew-name">${this._esc(name)}</span>
                <span class="cop-crew-role">${this._esc(m.role_label || m.role || '')}</span>
                <span class="cop-crew-lv">LV${m.level || 1}</span>
                ${!avail ? '<span class="cop-crew-busy">DEPLOYED</span>' : ''}
            </label>`;
        }).join('');
    }

    /**
     * Toggle a crew member in/out of the operation selection.
     * @param {string} crewId
     * @param {boolean} checked
     */
    _toggleCrewSelection(crewId, checked) {
        if (checked) {
            this._selectedCrewIds.add(crewId);
        } else {
            this._selectedCrewIds.delete(crewId);
        }
        this._updateOpSummary();
    }

    /** Update the operation summary and enable/disable launch button. */
    _updateOpSummary() {
        const summary = document.getElementById('cop-summary');
        const launchBtn = document.getElementById('btn-launch-op');
        const OP_MIN = { recon: 1, heist: 3, extraction: 2, deal: 1, hit: 2, hack: 1 };

        const opType = this._selectedOpType;
        const count = this._selectedCrewIds.size;

        if (!opType || count === 0) {
            if (summary) summary.style.display = 'none';
            if (launchBtn) launchBtn.disabled = true;
            return;
        }

        const min = OP_MIN[opType] || 1;
        const canLaunch = count >= min;

        // Duration scales inversely with crew count (base 60 min, -10 per extra)
        const baseDuration = 60;
        const durationMin = Math.max(15, baseDuration - (count - min) * 10);
        const rewardCredits = 500 + count * 200;
        const rewardXp = 25 + count * 10;

        if (summary) {
            summary.style.display = '';
            document.getElementById('cop-duration-val').textContent = `${durationMin} min`;
            document.getElementById('cop-reward-val').textContent =
                `\u20B4${rewardCredits} + ${rewardXp} XP each`;
        }
        if (launchBtn) launchBtn.disabled = !canLaunch;
    }

    /**
     * Launch a crew operation from the modal.
     * v1.45.0 [2026-03-21]
     * CONNECTS: CrewManager.start_operation(), /api/crew/start_op
     */
    async launchOperation() {
        const opType = this._selectedOpType;
        const crewIds = [...this._selectedCrewIds];
        if (!opType || crewIds.length === 0) return;

        const OP_MIN = { recon: 1, heist: 3, extraction: 2, deal: 1, hit: 2, hack: 1 };
        const min = OP_MIN[opType] || 1;
        const durationMin = Math.max(15, 60 - (crewIds.length - min) * 10);
        const rewardCredits = 500 + crewIds.length * 200;
        const rewardXp = 25 + crewIds.length * 10;

        try {
            const res = await fetch('/api/crew/start_op', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    op_type: opType,
                    crew_ids: crewIds,
                    duration_secs: durationMin * 60,
                    reward_credits: rewardCredits,
                    reward_xp: rewardXp,
                }),
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('OPERATION LAUNCHED!', data.message, 5000);
                this._appendChatEntry('event', '[CREW]', data.message);
                this.closeCrewOpsModal();
                this.refreshHud();
            } else {
                this._showToast('FAILED', data.message || data.error, 5000);
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 5000);
        }
    }

    /**
     * Dismiss a crew member.
     * v1.45.0 [2026-03-21]
     * @param {string} charId
     */
    async dismissCrewMember(charId) {
        if (!confirm(`Dismiss ${charId} from your crew?`)) return;
        try {
            const res = await fetch('/api/crew/dismiss', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ character_id: charId }),
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('CREW UPDATE', data.message, 4000);
                this.refreshHud();
            } else {
                this._showToast('ERROR', data.error, 4000);
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 4000);
        }
    }

    // ── Crew Recruitment ─────────────────────────────────────────────
    // v1.52.0 [2026-03-22] — Recruit NPCs from district modal
    // CONNECTS: /api/crew/recruit, CrewManager
    // CALLED BY: District modal NPC recruit buttons

    /**
     * Recruit an NPC from a district to the player's crew.
     * @param {string} npcId - NPC identifier (e.g. 'FIXER', '0xGH0ST')
     * @param {string} role - Crew role (fixer, hacker, muscle, etc.)
     */
    async recruitNpc(npcId, role) {
        try {
            const res = await fetch('/api/crew/recruit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ character_id: npcId, role }),
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('CREW RECRUITED!', data.message || `${npcId} joined your crew as ${role}.`, 5000);
                this._appendChatEntry('event', '[CREW]', data.message || `${npcId} recruited!`);
                this.refreshHud();
            } else {
                this._showToast('RECRUIT FAILED', data.error || data.message || 'Cannot recruit.', 5000);
                this._appendChatEntry('system', '[CREW]', data.error || data.message || 'Recruitment failed.');
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 4000);
        }
    }

    /**
     * Gift an inventory item to an NPC to build relationship.
     * v1.52.0 [2026-03-22]
     * @param {string} npcId - NPC identifier
     * CONNECTS: /api/npc/gift, ReputationManager
     */
    async giftNpc(npcId) {
        // Use the first non-equipped item in inventory
        const item = (this.inventory || []).find(i => i && i.id);
        if (!item) {
            this._showToast('NO ITEMS', 'You have nothing to gift.', 3000);
            return;
        }
        if (!confirm(`Gift ${item.name || item.id} to ${npcId}?`)) return;
        try {
            const res = await fetch('/api/npc/gift', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ npc_id: npcId, item_id: item.id }),
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('GIFT ACCEPTED', data.message, 5000);
                this._appendChatEntry('event', `[${npcId}]`, data.message);
                if (data.can_recruit) {
                    this._showToast('RECRUIT READY', `${npcId} is now willing to join your crew!`, 6000);
                }
                this.refreshHud();
                this.loadRelationships();
            } else {
                this._showToast('GIFT FAILED', data.error || 'Cannot gift.', 4000);
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 4000);
        }
    }

    // ── Inventory interaction ────────────────────────────────────────
    // v1.45.0 [2026-03-21] — Context menu for use/equip/sell
    // CONNECTS: Inventory, /api/inventory/use

    /**
     * Handle inventory item click — show context menu with actions.
     * v1.45.0 — Replaced toast-only with full context menu.
     * @param {string} itemId
     * @param {MouseEvent} [event]
     */
    onItemClick(itemId, event) {
        const item = (this.inventory || []).find(i => i.id === itemId);
        if (!item) return;

        // Close any existing context menu
        this._closeContextMenu();

        const menu = document.createElement('div');
        menu.className = 'item-context-menu';

        // Position near click or near the item slot
        const x = event ? event.clientX : window.innerWidth / 2;
        const y = event ? event.clientY : window.innerHeight / 2;
        menu.style.left = `${Math.min(x, window.innerWidth - 180)}px`;
        menu.style.top = `${Math.min(y, window.innerHeight - 200)}px`;

        const cat = (item.category || '').toLowerCase();
        const isConsumable = ['drug', 'food'].includes(cat);
        const isEquipment = ['weapon', 'cyberware', 'cyberdeck', 'clothing', 'tool'].includes(cat);

        // v1.52.0 — Rich context menu with description, price, rarity
        let html = `<div class="ctx-title">${this._esc(item.name || itemId)}</div>`;
        html += `<div class="ctx-desc">${this._esc(item.description || '')}</div>`;
        html += `<div class="ctx-meta">`;
        html += `<span>${this._esc(cat)}${item.rarity ? ' / ' + item.rarity : ''}</span>`;
        if (item.sell_price) html += `<span class="ctx-price">Sell: ₵${item.sell_price}</span>`;
        if (item.quantity > 1) html += `<span class="ctx-qty">x${item.quantity}</span>`;
        html += `</div>`;
        html += '<div class="ctx-actions">';

        if (isConsumable) {
            html += `<button class="ctx-btn use" onclick="NeonCityApp._useItem('${this._esc(itemId)}', 'use')">USE</button>`;
        }
        if (isEquipment) {
            html += `<button class="ctx-btn equip" onclick="NeonCityApp._useItem('${this._esc(itemId)}', 'equip')">EQUIP</button>`;
        }
        html += `<button class="ctx-btn sell" onclick="NeonCityApp._useItem('${this._esc(itemId)}', 'sell')">SELL</button>`;
        html += '</div>';

        menu.innerHTML = html;
        document.body.appendChild(menu);
        this._contextMenu = menu;

        // Close on outside click
        const closer = (e) => {
            if (!menu.contains(e.target)) {
                this._closeContextMenu();
                document.removeEventListener('click', closer, true);
            }
        };
        setTimeout(() => document.addEventListener('click', closer, true), 10);
    }

    /** Close the item context menu if open. */
    _closeContextMenu() {
        if (this._contextMenu) {
            this._contextMenu.remove();
            this._contextMenu = null;
        }
    }

    /**
     * Use/equip/sell an inventory item.
     * v1.52.0 [2026-03-22] — Show consumable effect feedback with stat changes
     * @param {string} itemId
     * @param {string} action - 'use', 'equip', 'unequip', 'sell'
     * CONNECTS: /api/inventory/use, _apply_consumable_effect()
     */
    async _useItem(itemId, action) {
        this._closeContextMenu();
        try {
            const res = await fetch('/api/inventory/use', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: itemId, action }),
            });
            const data = await res.json();
            if (!data.ok) {
                this._showToast('FAILED', data.error || 'Action failed.', 4000);
                return;
            }
            // v1.52.0 — Show consumable effect details
            if (action === 'use' && data.effect) {
                const effect = data.effect;
                const changes = effect.changes || {};
                const parts = [];
                if (changes.health) parts.push(`HP ${changes.health > 0 ? '+' : ''}${changes.health}`);
                if (changes.energy) parts.push(`EN ${changes.energy > 0 ? '+' : ''}${changes.energy}`);
                if (changes.heat)   parts.push(`HT ${changes.heat > 0 ? '+' : ''}${changes.heat}`);
                const detail = parts.length ? parts.join(' / ') : '';
                this._showToast('USED', `${effect.message || itemId}${detail ? '\n' + detail : ''}`, 5000);
                this._appendChatEntry('system', '[ITEM]', effect.message || `Used ${itemId}`);
            } else {
                const msg = data.message || data.result || `${action} ${itemId}`;
                this._showToast(action.toUpperCase(), msg, 4000);
            }
            this.refreshHud();
        } catch (err) {
            this._showToast('ERROR', err.message, 4000);
        }
    }

    // ── NPC Relationships ──────────────────────────────────────────────
    // v1.52.0 [2026-03-22] — Faction/NPC standing display
    // CONNECTS: /api/relationships, ReputationManager

    /** Load and render NPC/faction relationship standings. */
    async loadRelationships() {
        try {
            const res = await fetch('/api/relationships');
            const data = await res.json();
            this._renderRelationships(data.relationships || []);
        } catch (e) {
            console.warn('[NeonCity] relationships fetch failed:', e);
        }
    }

    /**
     * Render relationship standings in the right sidebar.
     * @param {Array} rels - Relationship entries from API.
     */
    _renderRelationships(rels) {
        const el = document.getElementById('relationship-list');
        if (!el) return;
        if (!rels.length) {
            el.innerHTML = '<div class="nc-empty">No standings recorded yet.</div>';
            return;
        }
        const TIER_COLORS = {
            'Revered': '#22c55e', 'Honored': '#22c55e', 'Friendly': '#3b82f6',
            'Warm': '#06b6d4', 'Neutral': '#4a5568', 'Cool': '#f59e0b',
            'Unfriendly': '#f97316', 'Hostile': '#ef4444', 'Nemesis': '#dc2626',
        };
        el.innerHTML = rels.slice(0, 8).map(r => {
            const color = TIER_COLORS[r.label] || '#4a5568';
            const sign = r.standing >= 0 ? '+' : '';
            return `<div class="nc-rep-row">
                <span class="nc-rep-name">${this._esc(r.name || r.id)}</span>
                <span class="nc-rep-label" style="color:${color}">${this._esc(r.label)}</span>
                <span class="nc-rep-val" style="color:${color}">${sign}${r.standing}</span>
            </div>`;
        }).join('');
    }

    // ── Dynamic Mission Generation ────────────────────────────────────
    // v1.52.0 [2026-03-22] — Territory-based dynamic missions
    // CONNECTS: /api/missions/generate, TerritoryManager

    /** Generate a new territory mission from current faction state. */
    async generateMission() {
        try {
            const res = await fetch('/api/missions/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            const data = await res.json();
            if (data.ok) {
                this._showToast('NEW MISSION', data.message || 'Territory mission generated.', 5000);
                this._appendChatEntry('event', '[MISSIONS]', data.message || 'New mission available!');
                this.refreshHud();
            } else {
                this._showToast('FAILED', data.error || 'Could not generate mission.', 4000);
            }
        } catch (err) {
            this._showToast('ERROR', err.message, 4000);
        }
    }

    // ── Skill Progression ─────────────────────────────────────────────
    // v1.45.0 [2026-03-21] — XP bars per skill, global level display
    // CONNECTS: SkillManager, /api/skills, #player-skills

    /**
     * Render the skill progression panel in the left sidebar.
     * Replaces the simple skill chips with XP progress bars.
     * @param {Object} skillData - From SkillManager.to_dict().
     */
    _renderSkillProgression(skillData) {
        const container = document.getElementById('player-skills');
        if (!container) return;

        const skills = skillData.skills || {};
        const globalLevel = skillData.global_level || 1;
        const totalXp = skillData.total_xp || 0;

        const SKILL_ICONS = {
            hacking: '\u{1F4BB}', combat: '\u2694\uFE0F', stealth: '\u{1F977}',
            social: '\u{1F3AD}', tech: '\u{1F527}', driving: '\u{1F697}',
            medicine: '\u{1FA7A}', trading: '\u{1F4B0}',
        };
        const LEVEL_NAMES = ['Untrained', 'Novice', 'Competent', 'Skilled', 'Expert', 'Master'];
        const LEVEL_THRESHOLDS = [0, 100, 300, 600, 1000, 2000];
        const LEVEL_COLORS = ['#4a5568', '#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ef4444'];

        let html = `<div class="skill-global-level">
            <span class="skill-global-lv">LV ${globalLevel}</span>
            <span class="skill-global-xp">${totalXp.toLocaleString()} total XP</span>
        </div>`;

        for (const [name, data] of Object.entries(skills)) {
            const icon = SKILL_ICONS[name] || '\u2753';
            const level = data.level || 0;
            const xp = data.xp || 0;
            const levelName = LEVEL_NAMES[level] || 'Untrained';
            const color = LEVEL_COLORS[level] || '#4a5568';

            // Calculate progress within current level
            const current = LEVEL_THRESHOLDS[level] || 0;
            const next = level < 5 ? (LEVEL_THRESHOLDS[level + 1] || 2000) : 2000;
            const span = next - current;
            const progress = span > 0 ? Math.min(100, ((xp - current) / span) * 100) : 100;

            html += `
            <div class="skill-bar-row">
                <span class="skill-bar-icon">${icon}</span>
                <span class="skill-bar-name">${name.toUpperCase()}</span>
                <div class="skill-bar-track">
                    <div class="skill-bar-fill" style="width:${progress}%; background:${color}"></div>
                </div>
                <span class="skill-bar-level" style="color:${color}">Lv${level}</span>
                <span class="skill-bar-xp">${xp}/${next}</span>
            </div>`;
        }

        container.innerHTML = html;
    }

    // ── Heat warnings ────────────────────────────────────────────────
    // v1.45.0 [2026-03-21] — Visual urgency at heat thresholds
    // CONNECTS: PlayerState.heat, stat-heat bar, neoncity-header

    /**
     * Apply visual heat warnings based on current heat level.
     * @param {number} heat - Current heat value (0-100).
     */
    _applyHeatWarnings(heat) {
        const header = document.querySelector('.neoncity-header');
        const heatBar = document.getElementById('stat-heat');
        const layout = document.querySelector('.neoncity-layout');

        // Remove all heat classes first
        if (layout) {
            layout.classList.remove('heat-low', 'heat-medium', 'heat-high', 'heat-critical');
        }

        if (heat >= 80) {
            if (layout) layout.classList.add('heat-critical');
            // Show WANTED indicator
            this._ensureWantedBadge(true);
        } else if (heat >= 60) {
            if (layout) layout.classList.add('heat-high');
            this._ensureWantedBadge(true);
        } else if (heat >= 30) {
            if (layout) layout.classList.add('heat-medium');
            this._ensureWantedBadge(false);
        } else {
            this._ensureWantedBadge(false);
        }
    }

    /**
     * Show or hide the WANTED badge in the header.
     * @param {boolean} show
     */
    _ensureWantedBadge(show) {
        let badge = document.getElementById('wanted-badge');
        if (show && !badge) {
            badge = document.createElement('span');
            badge.id = 'wanted-badge';
            badge.className = 'wanted-badge';
            badge.textContent = '\u26A0 WANTED';
            const header = document.querySelector('.header-center');
            if (header) header.appendChild(badge);
        } else if (!show && badge) {
            badge.remove();
        }
    }

    // ── Hacking trigger ──────────────────────────────────────────────
    // v1.45.0 [2026-03-21] — Wire hack minigame into dashboard
    // CONNECTS: CosyHack (cosysim-hack-minigame.js), /api/hack/*

    /**
     * Open the hacking targets browser.
     * Fetches available targets from /api/hack/targets, renders overlay.
     */
    async openHackTargets() {
        try {
            const res = await fetch('/api/hack/targets');
            const data = await res.json();
            const targets = data.targets || data || [];
            if (targets.length === 0) {
                this._showToast('NETRUNNER', 'No hackable targets nearby.', 3000);
                return;
            }
            this._renderHackTargets(targets);
        } catch (err) {
            this._showToast('ERROR', `Hack targets: ${err.message}`, 4000);
        }
    }

    /**
     * Render hack targets as a toast overlay with clickable cards.
     * @param {Array} targets
     */
    _renderHackTargets(targets) {
        // Remove existing overlay if any
        const existing = document.getElementById('hack-targets-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'hack-targets-overlay';
        overlay.className = 'hack-targets-panel';
        overlay.innerHTML = `
            <div class="htp-header">
                <h4>\u{1F4BB} HACKABLE TARGETS</h4>
                <button class="htp-close" onclick="document.getElementById('hack-targets-overlay').remove()">\u2715</button>
            </div>
            <div class="htp-list">
                ${targets.map(t => `
                    <div class="hack-target-card" onclick="NeonCityApp.startHack('${this._esc(t.id || t.target_id || '')}')">
                        <div class="htc-name">${this._esc(t.name || t.label || 'Unknown')}</div>
                        <div class="htc-meta">
                            <span class="htc-security">Security: ${'\u2605'.repeat(t.difficulty || t.security || 1)}</span>
                            ${t.reward ? `<span class="htc-reward">\u20B4${t.reward}</span>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
        document.body.appendChild(overlay);
    }

    /**
     * Start a hack minigame for a target.
     * @param {string} targetId
     */
    startHack(targetId) {
        const overlay = document.getElementById('hack-targets-overlay');
        if (overlay) overlay.remove();

        if (typeof CosyHack !== 'undefined') {
            CosyHack.open(targetId);
        } else {
            this._showToast('HACK', 'Hack module not loaded.', 3000);
        }
    }

    // ── Shop ─────────────────────────────────────────────────────────────
    // v1.45.0 [2026-03-21] — Wire shared shop component
    // CONNECTS: CosyShop (cosysim-shop.js), /api/shop/*

    /** Open the Black Market shop modal. */
    openShop() {
        if (typeof CosyShop !== 'undefined') {
            CosyShop.open({ title: 'BLACK MARKET', apiBase: '/api/shop' });
        } else {
            this._showToast('SHOP', 'Shop module not loaded.', 3000);
        }
    }

    // ── Private helpers ───────────────────────────────────────────────────

    /**
     * Enter a district — handles offline scenes, same-scene travel, redirects.
     * v1.52.0 [2026-03-22] — Offline scene detection, same-scene handling
     * @param {string} districtKey
     * CONNECTS: /api/district/enter, _port_check()
     */
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

            if (!data.success) {
                this._appendChatEntry('system', '[CITY]',
                    `Travel failed: ${data.message || data.error || 'Unknown error'}`);
                return;
            }

            // v1.52.0 — Same-scene travel (street_level → NEON CITY)
            if (data.same_scene) {
                this._appendChatEntry('system', '[CITY]', 'You are already in Neon City.');
                this.refreshHud();
                this._loadCityMap();
                return;
            }

            // v1.52.0 — Offline scene detection
            if (!data.is_running) {
                this._showToast('SCENE OFFLINE',
                    `${data.scene} is not running (port ${data.port}). Launch it via the TUI or launcher.`, 6000);
                this._appendChatEntry('system', '[CITY]',
                    `Cannot travel to ${data.scene} — scene is offline. Start it with: python launcher.py ${data.scene.toLowerCase().replace(/ /g, '_')}`);
                return;
            }

            // Scene is online — proceed with travel
            const cost = [];
            if (data.energy_cost) cost.push(`-${data.energy_cost} energy`);
            if (data.heat_add)    cost.push(`+${data.heat_add} heat`);
            const costStr = cost.length ? ` (${cost.join(', ')})` : '';
            this._appendChatEntry('system', '[CITY]',
                `Arrived at ${data.scene}.${costStr} Redirecting...`);
            setTimeout(() => { window.location.href = data.url; }, 1500);
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

    // v1.52.0 — Fetch district scene online/offline status on load and every 60 s
    NeonCityApp._updateDistrictStatuses();
    setInterval(() => NeonCityApp._updateDistrictStatuses(), 60_000);

    // v1.52.0 — Load NPC relationship standings
    NeonCityApp.loadRelationships();
    setInterval(() => NeonCityApp.loadRelationships(), 60_000);

    // Refresh faction status every 30 s
    setInterval(() => {
        if (NeonCityApp.socket) NeonCityApp.socket.emit('get_faction_status');
    }, 30_000);

    // v1.44.0 — Refresh HUD sidebars every 30 s
    setInterval(() => NeonCityApp.refreshHud(), 30_000);
});
