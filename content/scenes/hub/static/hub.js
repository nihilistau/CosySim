/**
 * THE TERMINAL — hub.js  |  v0.68 Dark Renaissance
 * Blue accent: #3b82f6
 *
 * Main controller class: TheTerminalHub
 * Handles scene grid, world clock, economy panel, and data-stream particles.
 */

'use strict';

// ── TheTerminalHub ──────────────────────────────────────────────────

class TheTerminalHub {
  constructor() {
    /** @type {number|null} */
    this._clockTimer = null;
    /** @type {number|null} */
    this._sceneTimer = null;
    /** @type {number|null} */
    this._ecoTimer   = null;
    /** @type {number|null} */
    this._worldTimer = null;

    /** @type {Array<object>} */
    this._scenes = [];

    /** Canvas animation handles */
    this._dsCanvas  = null;
    this._dsCtx     = null;
    this._dsParticles = [];
    this._dsRaf     = null;
  }

  // ── Public API ─────────────────────────────────────────────────────

  /** Boot the hub: particles → data → clock. */
  init() {
    this._initDataStream();
    this._updateWorldClock();
    this._clockTimer = setInterval(() => this._updateWorldClock(), 1000);

    this.loadScenes();
    this.loadWorldState();
    this.loadEconomy();

    // Periodic refresh intervals
    this._sceneTimer = setInterval(() => this.loadScenes(), 30_000);
    this._worldTimer = setInterval(() => this.loadWorldState(), 60_000);
    this._ecoTimer   = setInterval(() => this.loadEconomy(), 45_000);
  }

  /** Fetch all scenes and render the scene grid. */
  async loadScenes() {
    try {
      const res    = await fetch('/api/scenes');
      const scenes = await res.json();
      this._scenes = scenes;
      this._renderSceneGrid(scenes);
      this._updateScenesBadge(scenes);
    } catch (err) {
      console.warn('[TheTerminal] loadScenes failed:', err);
    }
  }

  /** Fetch world state and update the world panel. */
  async loadWorldState() {
    try {
      const res  = await fetch('/api/world_state');
      const data = await res.json();
      this._renderWorldState(data);
    } catch (err) {
      console.warn('[TheTerminal] loadWorldState failed:', err);
    }
  }

  /** Fetch economy data and render the economy panel. */
  async loadEconomy() {
    try {
      const res  = await fetch('/api/economy');
      const data = await res.json();
      this._renderEconomy(data);
    } catch (err) {
      console.warn('[TheTerminal] loadEconomy failed:', err);
    }
  }

  /**
   * Navigate to a scene URL.
   * @param {string} url
   */
  navigateTo(url) {
    window.location.href = url;
  }

  // ── Scene grid renderer ─────────────────────────────────────────

  /**
   * Build and inject scene cards grouped by category.
   * @param {Array<object>} scenes
   */
  _renderSceneGrid(scenes) {
    const groups = ['neon_world', 'action', 'system'];
    groups.forEach(groupId => {
      const container = document.getElementById(`scene-grid-${groupId}`);
      if (!container) return;

      const groupScenes = scenes.filter(s => s.group === groupId);
      if (!groupScenes.length) {
        container.innerHTML = '<div class="loading-placeholder">NO SCENES AVAILABLE</div>';
        return;
      }

      container.innerHTML = groupScenes.map(s => this._sceneCardHTML(s)).join('');

      // Scene cards are now <a> elements with data-scene-nav — the shared
      // cosysim-transitions.js handler picks up clicks automatically and
      // applies the fade-through-black transition.  No extra wiring needed.
    });
  }

  /**
   * Build HTML for one scene card.
   * @param {object} s  Scene data from /api/scenes
   * @returns {string}
   */
  _sceneCardHTML(s) {
    const accent   = this._escHtml(s.accent  || '#3b82f6');
    const label    = this._escHtml(s.label   || s.id);
    const subtitle = this._escHtml(s.subtitle || '');
    const icon     = this._escHtml(s.icon    || '◆');
    const desc     = this._escHtml(s.desc    || '');
    const port     = s.port || '';
    const status   = s.status === 'online' ? 'online' : 'offline';
    const url      = `http://localhost:${port}/`;

    return `
<a class="scene-card ${status}" style="--scene-accent:${accent}"
     href="${this._escHtml(url)}" data-scene-nav
     data-url="${this._escHtml(url)}" data-scene="${this._escHtml(s.id)}"
     tabindex="0" role="button" aria-label="Open ${label}">
  <div class="scene-card-header">
    <span class="scene-card-icon">${icon}</span>
    <span class="status-dot ${status}" title="${status}"></span>
  </div>
  <div class="scene-card-name">${label}</div>
  ${subtitle ? `<div class="scene-card-subtitle">${subtitle}</div>` : ''}
  <div class="scene-card-desc">${desc}</div>
  <div class="scene-card-footer">
    <span class="scene-card-port">:${port}</span>
    <span class="scene-card-chars" id="chars-${this._escHtml(s.id)}"></span>
  </div>
</a>`.trim();
  }

  // ── World clock ─────────────────────────────────────────────────

  /** Tick the live world clock display using real time. */
  _updateWorldClock() {
    const now   = new Date();
    const hh    = String(now.getHours()).padStart(2, '0');
    const mm    = String(now.getMinutes()).padStart(2, '0');
    const ss    = String(now.getSeconds()).padStart(2, '0');
    const cycle = (now.getHours() >= 20 || now.getHours() < 6) ? 'NIGHT CYCLE' : 'DAY CYCLE';

    const timeEl = document.getElementById('world-clock-time');
    const dayEl  = document.getElementById('world-clock-day');
    if (timeEl) timeEl.textContent = `${cycle} ${hh}:${mm}:${ss}`;
    if (dayEl)  dayEl.textContent  = now.toLocaleDateString('en-US', {
      weekday: 'long', year: 'numeric', month: 'short', day: 'numeric',
    }).toUpperCase();
  }

  // ── World state renderer ─────────────────────────────────────────

  /**
   * Render world state panel.
   * @param {object} data  API response from /api/world_state
   */
  _renderWorldState(data) {
    // Large time display (from server game-time if available)
    if (data.ok && data.time) {
      const t = data.time;
      const h = String(t.hour ?? 0).padStart(2, '0');
      const m = String(t.minute ?? 0).padStart(2, '0');
      const cycle = ((t.hour ?? 0) >= 20 || (t.hour ?? 0) < 6) ? 'NIGHT CYCLE' : 'DAY CYCLE';
      const timeEl = document.getElementById('world-time-display');
      if (timeEl) timeEl.textContent = `${cycle} ${h}:${m}`;
      const dayEl = document.getElementById('world-day-display');
      if (dayEl) dayEl.textContent = `DAY ${t.day ?? 0} · ${(t.day_name ?? '').toUpperCase()}`;
    }

    // Active events
    const listEl = document.getElementById('world-events-list');
    if (!listEl) return;

    const events = data.events || [];
    if (!events.length) {
      listEl.innerHTML = '<div class="no-events">No active world events</div>';
      return;
    }
    listEl.innerHTML = events.slice(0, 4).map(ev => {
      const name = typeof ev === 'string' ? ev : (ev.name || JSON.stringify(ev));
      return `
<div class="world-event-item">
  <span class="world-event-dot"></span>
  <span class="world-event-name">${this._escHtml(name)}</span>
</div>`.trim();
    }).join('');
  }

  // ── Economy renderer ─────────────────────────────────────────────

  /**
   * Render economy summary panel.
   * @param {object} data  API response from /api/economy
   */
  _renderEconomy(data) {
    // Balance
    const balEl = document.getElementById('economy-balance');
    if (balEl) {
      balEl.textContent = data.balance != null
        ? `¢${Number(data.balance).toLocaleString()}`
        : '¢—';
    }

    // Credit chip in header
    const chipEl = document.getElementById('header-credits');
    if (chipEl && data.balance != null) {
      chipEl.textContent = `¢${Number(data.balance).toLocaleString()}`;
    }

    // Transaction list
    const txnEl = document.getElementById('txn-list');
    if (!txnEl) return;

    const txns = data.transactions || [];
    if (!txns.length) {
      txnEl.innerHTML = '<div class="no-events">No recent transactions</div>';
      return;
    }

    txnEl.innerHTML = txns.map(t => {
      const sign    = t.amount >= 0 ? '+' : '';
      const cls     = t.amount >= 0 ? 'positive' : 'negative';
      const desc    = this._escHtml(t.description || t.type || 'transaction');
      const scene   = this._escHtml((t.scene || '').toUpperCase());
      const amount  = `${sign}${t.amount}`;
      return `
<div class="txn-item">
  <span class="txn-desc">${desc}</span>
  <span class="txn-scene">${scene}</span>
  <span class="txn-amount ${cls}">${amount}</span>
</div>`.trim();
    }).join('');
  }

  // ── Scenes badge ─────────────────────────────────────────────────

  _updateScenesBadge(scenes) {
    const online  = scenes.filter(s => s.status === 'online').length;
    const total   = scenes.length;
    const countEl = document.getElementById('scenes-badge-count');
    if (countEl) countEl.textContent = `${online}/${total}`;
  }

  // ── Data stream particles ─────────────────────────────────────────

  /** Initialise the 3-D data-stream background particle canvas. */
  _initDataStream() {
    this._dsCanvas = document.getElementById('data-stream-canvas');
    if (!this._dsCanvas) return;

    this._dsCtx = this._dsCanvas.getContext('2d');
    this._dsResize();
    window.addEventListener('resize', () => this._dsResize());

    // Spawn particles
    const COUNT = 60;
    for (let i = 0; i < COUNT; i++) {
      this._dsParticles.push(this._dsNewParticle(true));
    }
    this._dsLoop();
  }

  _dsResize() {
    if (!this._dsCanvas) return;
    this._dsCanvas.width  = window.innerWidth;
    this._dsCanvas.height = window.innerHeight;
  }

  _dsNewParticle(randomY = false) {
    const w = this._dsCanvas?.width  || window.innerWidth;
    const h = this._dsCanvas?.height || window.innerHeight;
    return {
      x:       Math.random() * w,
      y:       randomY ? Math.random() * h : -10,
      vy:      0.3 + Math.random() * 0.9,
      vx:      (Math.random() - 0.5) * 0.2,
      alpha:   0.1 + Math.random() * 0.6,
      size:    1 + Math.random() * 2,
      char:    this._dsRandomChar(),
      charAge: 0,
      charTTL: 20 + Math.floor(Math.random() * 40),
    };
  }

  _dsRandomChar() {
    const chars = '01ABCDEF█▓▒░◆◇▪□■';
    return chars[Math.floor(Math.random() * chars.length)];
  }

  _dsLoop() {
    const ctx = this._dsCtx;
    const cnv = this._dsCanvas;
    if (!ctx || !cnv) return;

    ctx.clearRect(0, 0, cnv.width, cnv.height);
    ctx.font = '11px "Courier New", monospace';

    this._dsParticles.forEach((p, i) => {
      // Rotate char periodically
      p.charAge++;
      if (p.charAge >= p.charTTL) {
        p.char    = this._dsRandomChar();
        p.charAge = 0;
        p.charTTL = 20 + Math.floor(Math.random() * 40);
      }

      ctx.globalAlpha = p.alpha;
      ctx.fillStyle   = '#3b82f6';
      ctx.fillText(p.char, p.x, p.y);

      p.x += p.vx;
      p.y += p.vy;

      // Reset particle when it exits screen
      if (p.y > cnv.height + 10) {
        this._dsParticles[i] = this._dsNewParticle(false);
      }
    });

    ctx.globalAlpha = 1;
    this._dsRaf = requestAnimationFrame(() => this._dsLoop());
  }

  // ── Helpers ──────────────────────────────────────────────────────

  /**
   * Escape HTML special characters to prevent XSS.
   * @param {string} str
   * @returns {string}
   */
  _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
}

// ── Bootstrap ────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const hub = new TheTerminalHub();
  hub.init();
  window._theTerminalHub = hub; // Expose for debugging
});
