/**
 * navbar_v2.js — Universal Navbar v2 (B1 track)
 * ==============================================
 *
 * Self-contained controller for the CosySim global navbar.
 * Manages scene navigation, health-check pings, pillar filtering,
 * TTS voice toggle, credit display, and mobile hamburger menu.
 *
 * Instantiated automatically by the navbar_v2.html partial:
 *   window.cosyNavbar = new CosyNavbar({ currentScene, sceneAccent });
 *   window.cosyNavbar.init();
 *
 * Public API:
 *   updateCredits(balance)        — update credits display (flashes gold)
 *   updatePhoneBadge(count)       — update notification badge count
 *   toggleVoice()                 — toggle TTS, persist to localStorage
 *   openPhone()                   — navigate/open phone panel
 *   openAria()                    — open Aria assistant widget
 *   openAdmin()                   — open admin overlay
 *   setConnectionStatus(bool)     — update own-scene connection dot
 *   loadPillarRegistry()          — fetch pillar data and inject toggle pills
 *
 * Custom Events emitted on document:
 *   navbar:voice_toggled  { detail: { enabled: bool } }
 *   navbar:panel_request  { detail: { panel: 'phone'|'aria'|'admin' } }
 *
 * @version v1.42.1 [2026-03-21]
 * @author  CosySim Team
 *
 * Change Log:
 *   v1.42.1 [2026-03-21] — Extensive documentation, section dividers, version stamps
 *   v1.42.0 [2026-03-21] — Pillar wiring, hub modernization
 *   v0.68   [prior]      — Initial B1 track implementation
 */

'use strict';

// =====================================================================
// Constants
// =====================================================================

/** Port map for scene health-check pings. */
const SCENE_PORTS = {
    penthouse:  5556,
    phone:    5555,
    lounge:   5557,
    tavern:   5558,
    casino:   5559,
    gallery:  5560,
    arena:    5561,
    realm:    5562,
    neoncity: 5563,
    coders:   5564,
    games:    5567,
    intel:    5580,
    hub:      8500,
    admin:    8505,
    warzone:  5565,
};

/** Interval (ms) between automatic health pings. */
const PING_INTERVAL_MS = 30_000;

/** localStorage key for TTS voice preference. */
const VOICE_KEY = 'cosysim.voice.enabled';

// =====================================================================
// CosyNavbar Class
// =====================================================================

class CosyNavbar {

    // -----------------------------------------------------------------
    // Class Properties & Constructor
    // -----------------------------------------------------------------

    /**
     * @param {object} options
     * @param {string} [options.currentScene='']     Machine key of the active scene.
     * @param {string} [options.sceneAccent='#00e5ff'] CSS colour for the active scene.
     */
    constructor(options = {}) {
        this.currentScene = options.currentScene || '';
        this.sceneAccent  = options.sceneAccent  || '#00e5ff';

        /** @type {boolean} Whether TTS voice is currently enabled. */
        this._voiceEnabled = false;

        /** @type {Map<string, boolean>} Cached online/offline state per scene key. */
        this._sceneStatus = new Map();

        /** @type {number|null} Timer handle for health-ping loop. */
        this._pingTimer = null;

        /** @type {'game'|'service'|'creation'} Active pillar filter for scene nav. */
        this._activePillar = 'game';

        /** @type {object|null} Pillar registry data fetched from /api/scene-registry. */
        this._pillarData = null;

        // DOM refs — populated in init()
        this._el = {
            navbar:      null,
            ownDot:      null,
            creditsVal:  null,
            creditsDisp: null,
            phoneBadge:  null,
            voiceBtn:    null,
            hamburger:   null,
            nav:         null,
            moreBtn:     null,
            moreDropdown:null,
        };
    }

    // -----------------------------------------------------------------
    // Public: Initialization
    // -----------------------------------------------------------------

    /**
     * Bind all event listeners, read persisted state, start pinging.
     * Safe to call multiple times (idempotent via _initialised guard).
     */
    init() {
        if (this._initialised) return;
        this._initialised = true;

        // Cache DOM references
        this._el.navbar       = document.getElementById('cs-navbar');
        this._el.ownDot       = document.getElementById('navbar-own-dot');
        this._el.creditsVal   = document.getElementById('navbar-credits');
        this._el.creditsDisp  = document.getElementById('navbar-credits-display');
        this._el.phoneBadge   = document.getElementById('navbar-phone-badge');
        this._el.voiceBtn     = document.getElementById('navbar-voice-btn');
        this._el.hamburger    = document.getElementById('navbar-hamburger');
        this._el.nav          = document.getElementById('navbar-scene-nav');
        this._el.moreBtn      = document.getElementById('navbar-more-btn');
        this._el.moreDropdown = document.getElementById('navbar-more-dropdown');

        this._setupActionButtons();
        this._setupKeyboard();
        this._setupVoiceToggle();
        this._setupHamburger();
        this._setupMoreDropdown();
        this._setupSocketListeners();
        this._startPingLoop();
        // v1.44.0 — Intercept scene nav clicks to use city_map travel API
        this._setupTravelInterceptor();
    }

    // -----------------------------------------------------------------
    // Public: Data Updates
    // -----------------------------------------------------------------

    /**
     * Update the credit balance display and trigger a gold flash.
     *
     * @param {number|string} balance  The new balance value.
     */
    updateCredits(balance) {
        const val  = this._el.creditsVal;
        const disp = this._el.creditsDisp;
        if (!val || !disp) return;

        val.textContent = typeof balance === 'number'
            ? balance.toLocaleString()
            : String(balance);

        // Trigger flash — remove then re-add class to restart CSS animation.
        // Reading offsetWidth between remove/add forces a browser reflow,
        // which resets the animation timeline so it plays again.
        disp.classList.remove('cs-credits-display--flash');
        void disp.offsetWidth; // eslint-disable-line no-void — force reflow
        disp.classList.add('cs-credits-display--flash');

        // Clean up class after animation completes (0.6 s)
        setTimeout(() => disp.classList.remove('cs-credits-display--flash'), 700);
    }

    /**
     * Update the phone notification badge.
     *
     * @param {number} count  Badge count; 0 hides the badge.
     */
    updatePhoneBadge(count) {
        const badge = this._el.phoneBadge;
        if (!badge) return;

        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : String(count);
            badge.setAttribute('aria-label', `${count} notification${count !== 1 ? 's' : ''}`);
            badge.hidden = false;
        } else {
            badge.hidden = true;
        }
    }

    /**
     * Toggle the TTS voice on/off, persist the preference, and
     * emit a ``navbar:voice_toggled`` CustomEvent.
     */
    toggleVoice() {
        this._voiceEnabled = !this._voiceEnabled;
        this._persistVoice();
        this._applyVoiceState();
        document.dispatchEvent(
            new CustomEvent('navbar:voice_toggled', {
                bubbles: true,
                detail: { enabled: this._voiceEnabled },
            }),
        );
    }

    /** Open the phone panel (port 5555) or emit panel request event. */
    openPhone() {
        this._emitPanelRequest('phone');
    }

    /** Trigger the Aria assistant widget to open. */
    openAria() {
        this._emitPanelRequest('aria');
    }

    /** Trigger the admin overlay to open. */
    openAdmin() {
        this._emitPanelRequest('admin');
    }

    /**
     * Update the own-scene connection status dot.
     *
     * @param {boolean} connected  True if Socket.IO is connected.
     */
    setConnectionStatus(connected) {
        const dot = this._el.ownDot;
        if (!dot) return;
        dot.classList.toggle('cs-navbar__dot--connected', connected);
        dot.title = connected ? 'Connected' : 'Disconnected';
    }

    // -----------------------------------------------------------------
    // Private: Setup Helpers
    // -----------------------------------------------------------------

    /** Bind click handlers on the four action buttons. */
    _setupActionButtons() {
        const map = {
            'navbar-phone-btn': () => this.openPhone(),
            'navbar-aria-btn':  () => this.openAria(),
            'navbar-voice-btn': () => this.toggleVoice(),
            'navbar-admin-btn': () => this.openAdmin(),
        };
        for (const [id, handler] of Object.entries(map)) {
            const btn = document.getElementById(id);
            if (btn) btn.addEventListener('click', handler);
        }
    }

    /**
     * Bind keyboard shortcuts.
     * Ctrl+P → phone  |  Ctrl+I → aria  |  Ctrl+V → voice  |  Ctrl+K → admin
     */
    _setupKeyboard() {
        document.addEventListener('keydown', (e) => {
            if (!e.ctrlKey) return;
            // Skip when typing in an input/textarea
            const tag = document.activeElement && document.activeElement.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA') return;

            switch (e.key.toLowerCase()) {
                case 'p':
                    e.preventDefault();
                    this.openPhone();
                    break;
                case 'i':
                    e.preventDefault();
                    this.openAria();
                    break;
                case 'v':
                    e.preventDefault();
                    this.toggleVoice();
                    break;
                case 'k':
                    e.preventDefault();
                    this.openAdmin();
                    break;
                default:
                    break;
            }
        });
    }

    /**
     * Read the persisted voice preference from localStorage and
     * apply the correct button state.
     */
    _setupVoiceToggle() {
        try {
            const saved = localStorage.getItem(VOICE_KEY);
            this._voiceEnabled = saved === 'true';
        } catch (_) {
            this._voiceEnabled = false;
        }
        this._applyVoiceState();
    }

    /** Wire up Socket.IO connection events if socket is present on window. */
    _setupSocketListeners() {
        // Scenes attach their socket to window.socket (convention)
        const attach = (socket) => {
            socket.on('connect',    () => this.setConnectionStatus(true));
            socket.on('disconnect', () => this.setConnectionStatus(false));
            // Optional: scenes may emit 'credits:update' with { balance }
            socket.on('credits:update', (data) => {
                if (data && data.balance !== undefined) {
                    this.updateCredits(data.balance);
                }
            });
            // Optional: scenes may emit 'phone:badge' with { count }
            socket.on('phone:badge', (data) => {
                if (data && data.count !== undefined) {
                    this.updatePhoneBadge(data.count);
                }
            });
            // Apply initial connection state
            this.setConnectionStatus(socket.connected);
        };

        if (window.socket) {
            attach(window.socket);
        } else {
            // Socket may not exist yet — wait for it
            const tid = setInterval(() => {
                if (window.socket) {
                    clearInterval(tid);
                    attach(window.socket);
                }
            }, 500);
        }
    }

    /** Toggle mobile nav visibility when hamburger is clicked. */
    _setupHamburger() {
        const btn = this._el.hamburger;
        const nav = this._el.nav;
        if (!btn || !nav) return;

        btn.addEventListener('click', () => {
            const open = nav.classList.toggle('cs-navbar__nav--open');
            btn.setAttribute('aria-expanded', String(open));
        });
    }

    /** Toggle MORE dropdown open/close on click + keyboard. */
    _setupMoreDropdown() {
        const btn = this._el.moreBtn;
        if (!btn) return;

        const toggle = () => {
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            btn.setAttribute('aria-expanded', String(!expanded));
        };

        btn.addEventListener('click', toggle);
        btn.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggle();
            }
            if (e.key === 'Escape') {
                btn.setAttribute('aria-expanded', 'false');
            }
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!btn.contains(e.target)) {
                btn.setAttribute('aria-expanded', 'false');
            }
        });
    }

    // -----------------------------------------------------------------
    // Private: Scene Health Pings
    // -----------------------------------------------------------------

    /** Start auto-pinging all scene health endpoints. */
    _startPingLoop() {
        this._pingAllScenes();
        this._pingTimer = setInterval(
            () => this._pingAllScenes(),
            PING_INTERVAL_MS,
        );
    }

    /** Ping every known scene's /api/health endpoint in parallel. */
    _pingAllScenes() {
        for (const [sceneKey, port] of Object.entries(SCENE_PORTS)) {
            this._pingScene(sceneKey, port);
        }
    }

    /**
     * Fire a fetch against the scene health endpoint.
     * Uses a 4-second timeout; updates the status dot on result.
     *
     * @param {string} sceneKey  Machine key, e.g. "penthouse".
     * @param {number} port      HTTP port the scene listens on.
     */
    _pingScene(sceneKey, port) {
        const url = `http://localhost:${port}/api/health`;
        const controller = new AbortController();
        const tid = setTimeout(() => controller.abort(), 4000);

        fetch(url, { signal: controller.signal, mode: 'cors' })
            .then((res) => {
                clearTimeout(tid);
                this._setSceneStatus(sceneKey, res.ok);
            })
            .catch(() => {
                clearTimeout(tid);
                this._setSceneStatus(sceneKey, false);
            });
    }

    /**
     * Update all status dots for a given scene key.
     *
     * @param {string}  sceneKey  Machine key.
     * @param {boolean} online    Whether the scene responded OK.
     */
    _setSceneStatus(sceneKey, online) {
        this._sceneStatus.set(sceneKey, online);

        // Update every dot with matching data-status-dot attribute
        const dots = document.querySelectorAll(
            `[data-status-dot="${sceneKey}"]`,
        );
        dots.forEach((dot) => {
            dot.classList.toggle('cs-navbar__nav-dot--online', online);
            dot.title = online ? `${sceneKey}: online` : `${sceneKey}: offline`;
        });
    }

    // -----------------------------------------------------------------
    // Private: Helpers
    // -----------------------------------------------------------------

    /** Apply voice button active/inactive visual state. */
    _applyVoiceState() {
        const btn = this._el.voiceBtn;
        if (!btn) return;
        btn.classList.toggle('cs-navbar__action-btn--active', this._voiceEnabled);
        btn.setAttribute('aria-pressed', String(this._voiceEnabled));
        btn.title = this._voiceEnabled
            ? 'Voice TTS: ON  Ctrl+V'
            : 'Voice TTS: OFF  Ctrl+V';
    }

    /** Persist voice preference to localStorage (best-effort). */
    _persistVoice() {
        try {
            localStorage.setItem(VOICE_KEY, String(this._voiceEnabled));
        } catch (_) {
            // Ignore storage errors (private browsing, etc.)
        }
    }

    /**
     * Emit ``navbar:panel_request`` CustomEvent.
     *
     * @param {'phone'|'aria'|'admin'} panel  Which panel to open.
     */
    _emitPanelRequest(panel) {
        document.dispatchEvent(
            new CustomEvent('navbar:panel_request', {
                bubbles: true,
                detail: { panel },
            }),
        );
    }
    // -----------------------------------------------------------------
    // Public: Pillar Registry                          [v1.42.1]
    // -----------------------------------------------------------------

    /**
     * Fetch the scene registry from the API and enable pillar filtering.
     * Falls back gracefully to the hardcoded scene list if the API is
     * unavailable.
     *
     * @version v1.42.1 [2026-03-21]
     */
    async loadPillarRegistry() {
        try {
            const resp = await fetch('/api/scene-registry', {
                signal: AbortSignal.timeout(4000),
            });
            if (!resp.ok) return;
            const data = await resp.json();
            if (data && data.pillars) {
                this._pillarData = data.pillars;
                this._injectPillarToggle();
            }
        } catch (_) {
            // API unavailable — keep hardcoded scenes
        }
    }

    /**
     * Inject a pillar toggle (pill buttons) into the navbar left cluster.
     * Clicking a pill re-renders the scene nav with that pillar's scenes.
     */
    _injectPillarToggle() {
        if (!this._pillarData) return;
        const navbar = this._el.navbar;
        if (!navbar) return;

        // Don't inject twice
        if (navbar.querySelector('.cs-navbar__pillar-toggle')) return;

        const wrap = document.createElement('div');
        wrap.className = 'cs-navbar__pillar-toggle';
        wrap.setAttribute('role', 'tablist');
        wrap.setAttribute('aria-label', 'Pillar filter');

        const pills = [
            { id: 'game',     label: 'NEONCITY',      icon: '' },
            { id: 'service',  label: 'SERVICES',      icon: '' },
            { id: 'creation', label: 'CREATION KIT',  icon: '' },
        ];

        pills.forEach(p => {
            const btn = document.createElement('button');
            btn.className = 'cs-navbar__pillar-pill' +
                (p.id === this._activePillar ? ' cs-navbar__pillar-pill--active' : '');
            btn.setAttribute('role', 'tab');
            btn.setAttribute('aria-selected', String(p.id === this._activePillar));
            btn.dataset.pillar = p.id;
            btn.textContent = p.label;
            const count = (this._pillarData[p.id] || []).length;
            if (count) {
                const badge = document.createElement('span');
                badge.className = 'cs-navbar__pillar-badge';
                badge.textContent = String(count);
                btn.appendChild(badge);
            }
            btn.addEventListener('click', () => this._switchPillar(p.id));
            wrap.appendChild(btn);
        });

        // Insert after logo/scene name, before the nav
        const leftCluster = navbar.querySelector('.cs-navbar__left');
        if (leftCluster) {
            leftCluster.after(wrap);
        }
    }

    /**
     * Switch the active pillar and re-render scene links.
     * Updates pill active states and triggers a full re-render of the
     * scene nav for the selected pillar.
     *
     * @param {'game'|'service'|'creation'} pillar
     * @version v1.42.1 [2026-03-21]
     */
    _switchPillar(pillar) {
        if (pillar === this._activePillar && this._pillarData) return;
        this._activePillar = pillar;

        // Update pill active state
        const pills = document.querySelectorAll('.cs-navbar__pillar-pill');
        pills.forEach(p => {
            const active = p.dataset.pillar === pillar;
            p.classList.toggle('cs-navbar__pillar-pill--active', active);
            p.setAttribute('aria-selected', String(active));
        });

        // Re-render scene nav
        this._renderPillarScenes(pillar);
    }

    /**
     * Replace the scene nav links with scenes from the given pillar.
     * Clears existing nav items, builds inline links for up to 8 scenes,
     * and creates a MORE dropdown for any overflow scenes.
     *
     * @param {string} pillar
     * @version v1.42.1 [2026-03-21]
     */
    _renderPillarScenes(pillar) {
        const nav = this._el.nav;
        if (!nav || !this._pillarData) return;
        const scenes = this._pillarData[pillar] || [];

        // Remove existing nav items and MORE dropdown
        nav.querySelectorAll('.cs-navbar__nav-item, .cs-navbar__nav-item--more, .cs-navbar__nav-shortcut')
            .forEach(el => el.remove());

        const inline = scenes.slice(0, 8);
        const more = scenes.slice(8);

        inline.forEach(scene => {
            nav.appendChild(this._createNavItem(scene));
        });

        if (more.length) {
            const moreBtn = document.createElement('div');
            moreBtn.className = 'cs-navbar__nav-item cs-navbar__nav-item--more';
            moreBtn.tabIndex = 0;
            moreBtn.setAttribute('role', 'button');
            moreBtn.setAttribute('aria-haspopup', 'true');
            moreBtn.setAttribute('aria-expanded', 'false');

            const moreLabel = document.createElement('span');
            moreLabel.className = 'cs-navbar__nav-label';
            moreLabel.textContent = 'MORE \u25BC';
            moreBtn.appendChild(moreLabel);

            const dropdown = document.createElement('ul');
            dropdown.className = 'cs-navbar__more-dropdown';
            dropdown.setAttribute('role', 'menu');
            more.forEach(scene => {
                const li = document.createElement('li');
                li.setAttribute('role', 'none');
                const a = this._createNavItem(scene, true);
                a.setAttribute('role', 'menuitem');
                li.appendChild(a);
                dropdown.appendChild(li);
            });
            moreBtn.appendChild(dropdown);

            moreBtn.addEventListener('click', () => {
                const expanded = moreBtn.getAttribute('aria-expanded') === 'true';
                moreBtn.setAttribute('aria-expanded', String(!expanded));
            });

            nav.appendChild(moreBtn);
            this._el.moreBtn = moreBtn;
            this._el.moreDropdown = dropdown;
        }
    }

    /**
     * Create a single scene nav link element.
     *
     * @param {object}  scene       Scene data from registry.
     * @param {boolean} [isDropdown=false]  Use dropdown item class.
     * @returns {HTMLElement}
     */
    _createNavItem(scene, isDropdown = false) {
        const a = document.createElement('a');
        const isCurrent = scene.key === this.currentScene;
        a.className = isDropdown
            ? 'cs-navbar__more-item' + (isCurrent ? ' cs-navbar__nav-item--active' : '')
            : 'cs-navbar__nav-item' + (isCurrent ? ' cs-navbar__nav-item--active' : '');
        // v1.58.0 [2026-06-11] — hub root is now the landing page; in-game
        // navigation goes straight to the catalogue at /terminal.
        a.href = scene.key === 'hub'
            ? `http://localhost:${scene.port}/terminal`
            : `http://localhost:${scene.port}/`;
        a.setAttribute('data-scene-nav', '');
        a.setAttribute('data-scene-key', scene.key);
        a.setAttribute('data-scene-port', String(scene.port));
        if (scene.accent) {
            a.setAttribute('data-scene-accent', scene.accent);
            a.style.setProperty('--item-accent', scene.accent);
        }
        a.setAttribute('aria-current', isCurrent ? 'page' : 'false');

        const dot = document.createElement('span');
        dot.className = 'cs-navbar__nav-dot' +
            (scene.status === 'up' ? ' cs-navbar__nav-dot--online' : '');
        dot.setAttribute('data-status-dot', scene.key);
        dot.setAttribute('aria-hidden', 'true');

        const label = document.createElement('span');
        label.className = isDropdown ? '' : 'cs-navbar__nav-label';
        label.textContent = scene.label;

        const statusDot = document.createElement('span');
        statusDot.className = 'scene-dot';
        statusDot.setAttribute('aria-hidden', 'true');

        a.appendChild(dot);
        a.appendChild(label);
        a.appendChild(statusDot);

        return a;
    }

    // -----------------------------------------------------------------
    // v1.44.0 — City Map Travel Integration
    // -----------------------------------------------------------------

    /**
     * Intercept scene navigation clicks to route through the city map
     * travel API. Applies energy/heat costs and tracks player location.
     * Falls back to direct navigation if the travel API is unavailable.
     */
    _setupTravelInterceptor() {
        // Scene key → city map node name mapping
        const SCENE_TO_NODE = {
            'phone':          'SIGNAL',
            'penthouse':      'THE PENTHOUSE',
            'lounge':         'THE VELVET PIT',
            'tavern':         'THE RUSTY ANCHOR',
            'casino':         'CLUB NOIR',
            'gallery':        'THE OBSCURA',
            'arena':          'THE COLOSSEUM',
            'realm':          'THE SHATTERED THRONE',
            'neoncity':       'NEON CITY',
            'coders':         'THE LAB',
            'heist':          'THE SCORE',
            'games':          'THE ARCADE',
            'grid':           'THE GRID',
            'intel':          'THE BRIEFING ROOM',
            'command_center': 'Command Center',
            'asset_studio':   'ASSET STUDIO',
        };

        document.addEventListener('click', (e) => {
            const link = e.target.closest('[data-scene-nav]');
            if (!link) return;

            const sceneKey = link.getAttribute('data-scene-key');
            const scenePort = link.getAttribute('data-scene-port');
            if (!sceneKey || !scenePort) return;

            // Skip if clicking current scene
            if (sceneKey === this.currentScene) return;

            // Skip system scenes (admin, nexus, hub) — direct nav
            const systemScenes = ['admin', 'nexus_panel', 'system_control', 'command_center', 'hub', 'canvas'];
            if (systemScenes.includes(sceneKey)) return;

            const destination = SCENE_TO_NODE[sceneKey];
            if (!destination) return; // Unknown scene — let default nav handle it

            e.preventDefault();
            this._travelTo(destination, `http://localhost:${scenePort}/`, link);
        });
    }

    /**
     * Execute travel via the city map API.
     * Shows travel cost, applies energy/heat, then navigates.
     *
     * @param {string} destination - City map node name.
     * @param {string} url - Target URL to navigate to.
     * @param {HTMLElement} link - The clicked nav link (for visual feedback).
     */
    async _travelTo(destination, url, link) {
        // Add travelling indicator
        if (link) link.classList.add('cs-navbar__nav-item--travelling');

        try {
            const res = await fetch('/api/city/travel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ destination }),
            });
            const data = await res.json();

            if (data.success) {
                // Show travel cost notification
                const costs = [];
                if (data.energy_cost) costs.push(`-${data.energy_cost} energy`);
                if (data.heat_add)    costs.push(`+${data.heat_add} heat`);
                if (data.travel_time) costs.push(`${data.travel_time_min || data.travel_time} min`);
                const costStr = costs.length ? costs.join(' | ') : 'Free travel';

                this._showTravelToast(destination, costStr);

                // Navigate after brief delay for toast visibility
                setTimeout(() => { window.location.href = url; }, 800);
            } else {
                // Travel failed (not enough energy, no route, etc.)
                this._showTravelToast(destination, data.message || 'Travel blocked', true);
                if (link) link.classList.remove('cs-navbar__nav-item--travelling');
            }
        } catch (err) {
            // API unavailable — fall back to direct navigation
            console.warn('[Navbar] Travel API unavailable, navigating directly:', err.message);
            window.location.href = url;
        }
    }

    /**
     * Show a travel notification toast.
     * @param {string} destination - Where the player is going.
     * @param {string} detail - Cost/status text.
     * @param {boolean} [isError=false] - Red styling for failures.
     */
    _showTravelToast(destination, detail, isError = false) {
        const toast = document.createElement('div');
        toast.className = 'cs-travel-toast' + (isError ? ' cs-travel-toast--error' : '');
        toast.innerHTML = `
            <div class="cs-travel-toast__title">${isError ? 'TRAVEL BLOCKED' : 'TRAVELLING'}</div>
            <div class="cs-travel-toast__dest">${destination}</div>
            <div class="cs-travel-toast__detail">${detail}</div>
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), isError ? 4000 : 1500);
    }
}

// =====================================================================
// Global Exports — available for console debugging and scene scripts
// =====================================================================
window.CosyNavbar = CosyNavbar;
window.SCENE_PORTS = SCENE_PORTS;
