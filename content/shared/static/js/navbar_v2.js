/**
 * navbar_v2.js — Universal Navbar v2 (B1 track)
 * ===============================================
 * Self-contained controller for the CosySim global navbar.
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
 *
 * Custom Events emitted on document:
 *   navbar:voice_toggled  { detail: { enabled: bool } }
 *   navbar:panel_request  { detail: { panel: 'phone'|'aria'|'admin' } }
 */

'use strict';

/** Port map for scene health-check pings. */
const SCENE_PORTS = {
    bedroom:  5556,
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

class CosyNavbar {
    /**
     * @param {object} options
     * @param {string} [options.currentScene='']     Machine key of the active scene.
     * @param {string} [options.sceneAccent='#00e5ff'] CSS colour for the active scene.
     */
    constructor(options = {}) {
        this.currentScene = options.currentScene || '';
        this.sceneAccent  = options.sceneAccent  || '#00e5ff';

        /** @type {boolean} */
        this._voiceEnabled = false;

        /** @type {Map<string, boolean>} */
        this._sceneStatus = new Map();

        /** @type {number|null} Timer handle for health-ping loop. */
        this._pingTimer = null;

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

    // ─────────────────────────────────────────────────────────────────
    // Public: init
    // ─────────────────────────────────────────────────────────────────

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
    }

    // ─────────────────────────────────────────────────────────────────
    // Public: data updates
    // ─────────────────────────────────────────────────────────────────

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

        // Trigger flash — remove then re-add class to restart animation
        disp.classList.remove('cs-credits-display--flash');
        // Force reflow
        void disp.offsetWidth; // eslint-disable-line no-void
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

    // ─────────────────────────────────────────────────────────────────
    // Private: setup helpers
    // ─────────────────────────────────────────────────────────────────

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

    // ─────────────────────────────────────────────────────────────────
    // Private: scene health pings
    // ─────────────────────────────────────────────────────────────────

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
     * @param {string} sceneKey  Machine key, e.g. "bedroom".
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

    // ─────────────────────────────────────────────────────────────────
    // Private: helpers
    // ─────────────────────────────────────────────────────────────────

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
}

// Expose globally for console debugging
window.CosyNavbar = CosyNavbar;
window.SCENE_PORTS = SCENE_PORTS;
