/**
 * hub.js — THE TERMINAL Hub Controller
 * =====================================
 *
 * Main controller for THE TERMINAL (CosySim navigation hub, port 8500).
 * Handles scene grid rendering (pillar-based + legacy fallback), world
 * clock, economy panel, world-state events, faction territory bars,
 * Nexus health, and data-stream background particle animation.
 *
 * Blue accent: #3b82f6
 *
 * Version: v1.64.0 [2026-06-27]
 * Author:  CosySim Team
 *
 * Change Log:
 *   v1.64.0 [2026-06-27] — Premium glow-up: faction territory bars, section
 *                           count badges, Nexus tier bench stat, gold credit
 *                           chip via ₵, event timestamps, Orbitron card names
 *   v1.42.1 [2026-03-21] — Extensive documentation, section dividers, version stamps
 *   v1.42.0 [2026-03-21] — Pillar grid rendering, hub modernization
 *   v0.68   [prior]      — Dark Renaissance initial implementation
 */

'use strict';

// =====================================================================
// TheTerminalHub Class
// =====================================================================

class TheTerminalHub {

  // -------------------------------------------------------------------
  // Constructor & Properties
  // -------------------------------------------------------------------

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

    /** v1.64.0 — Faction color palette */
    this._factionColors = {
      'omnicorp':       '#3b82f6',
      'ghost_net':      '#06b6d4',
      'iron_syndicate': '#ef4444',
      'neon_dragons':   '#f59e0b',
      'street_rats':    '#22c55e',
      'void_runners':   '#a855f7',
    };
  }

  // -------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------

  /** Boot the hub: particles → data → clock. */
  init() {
    this._initDataStream();
    this._updateWorldClock();
    this._clockTimer = setInterval(() => this._updateWorldClock(), 1000);

    this.loadScenes();
    this.loadWorldState();
    this.loadEconomy();
    this._loadNexusHealth();

    // Periodic refresh intervals
    this._sceneTimer = setInterval(() => this.loadScenes(), 30_000);
    this._worldTimer = setInterval(() => this.loadWorldState(), 60_000);
    this._ecoTimer   = setInterval(() => this.loadEconomy(), 45_000);
  }

  // -------------------------------------------------------------------
  // Scene Grid Renderer                                 [v1.64.0]
  // -------------------------------------------------------------------

  /**
   * Fetch all scenes via pillar registry and render the scene grid.
   * Falls back to the legacy /api/scenes endpoint if the pillar
   * registry is unavailable.
   *
   * CONNECTS: /api/scene-registry, /api/scenes
   * CALLED BY: init(), setInterval
   * EMITS: DOM updates to scene-grid-{pillarId}, section-count-{pillarId}
   */
  async loadScenes() {
    try {
      const res  = await fetch('/api/scene-registry');
      const data = await res.json();
      if (data && data.pillars) {
        this._renderPillarGrid(data.pillars);
        this._updateScenesBadgePillar(data.pillars);
        this._updateSectionCounts(data.pillars);
      }
    } catch (err) {
      try {
        const res    = await fetch('/api/scenes');
        const scenes = await res.json();
        this._scenes = scenes;
        this._renderSceneGrid(scenes);
        this._updateScenesBadge(scenes);
      } catch (err2) {
        console.warn('[TheTerminal] loadScenes failed:', err2);
      }
    }
  }

  /**
   * Build and inject scene cards grouped by pillar (game/service/creation).
   * Each pillar maps to a DOM container with id="scene-grid-{pillarId}".
   *
   * @param {object} pillars  Pillar data from /api/scene-registry
   */
  _renderPillarGrid(pillars) {
    const pillarIds = ['game', 'service', 'creation'];
    pillarIds.forEach(pillarId => {
      const container = document.getElementById(`scene-grid-${pillarId}`);
      if (!container) return;

      const scenes = pillars[pillarId] || [];
      if (!scenes.length) {
        container.innerHTML = '<div class="loading-placeholder">NO SCENES AVAILABLE</div>';
        return;
      }

      container.innerHTML = scenes.map(s => this._sceneCardHTML({
        id: s.key,
        port: s.port,
        label: s.label,
        subtitle: s.subtitle || '',
        icon: s.icon || '',
        accent: s.accent || '#3b82f6',
        desc: s.desc || '',
        status: s.status === 'up' ? 'online' : 'offline',
      })).join('');
    });
  }

  /**
   * Update the scenes-online badge counter from pillar data.
   * @param {object} pillars
   */
  _updateScenesBadgePillar(pillars) {
    let online = 0;
    let total = 0;
    for (const scenes of Object.values(pillars)) {
      for (const s of scenes) {
        total++;
        if (s.status === 'up') online++;
      }
    }
    const countEl = document.getElementById('scenes-badge-count');
    if (countEl) countEl.textContent = `${online}/${total}`;
  }

  /**
   * v1.64.0 [2026-06-27] — Update per-pillar scene count badges.
   * @param {object} pillars
   */
  _updateSectionCounts(pillars) {
    const pillarMap = { game: 'game', service: 'service', creation: 'creation' };
    for (const [pillarId, key] of Object.entries(pillarMap)) {
      const el = document.getElementById(`section-count-${pillarId}`);
      if (!el) continue;
      const scenes = pillars[key] || [];
      const online = scenes.filter(s => s.status === 'up').length;
      el.textContent = `${online}/${scenes.length} SCENES`;
    }
  }

  /**
   * Build and inject scene cards grouped by category (legacy fallback).
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
    });
  }

  /**
   * Build HTML for one scene card.
   * v1.64.0 — Orbitron card names, JetBrains Mono meta
   *
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

  // -------------------------------------------------------------------
  // World Clock
  // -------------------------------------------------------------------

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

  // -------------------------------------------------------------------
  // World State Renderer                                [v1.64.0]
  // -------------------------------------------------------------------

  /**
   * Fetch world state and update the world panel + faction territory.
   *
   * CONNECTS: /api/world_state
   * CALLED BY: init(), setInterval
   * EMITS: DOM updates to world-time-display, world-events-list, faction-bars
   */
  async loadWorldState() {
    try {
      const res  = await fetch('/api/world_state');
      const data = await res.json();
      this._renderWorldState(data);
      this._renderFactionTerritory(data);
    } catch (err) {
      console.warn('[TheTerminal] loadWorldState failed:', err);
    }
  }

  /**
   * Render world state panel.
   * v1.64.0 — event timestamps
   * @param {object} data  API response from /api/world_state
   */
  _renderWorldState(data) {
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

    const listEl = document.getElementById('world-events-list');
    if (!listEl) return;

    const events = data.events || [];
    if (!events.length) {
      listEl.innerHTML = '<div class="no-events">No active world events</div>';
      return;
    }
    listEl.innerHTML = events.slice(0, 5).map(ev => {
      const name = typeof ev === 'string' ? ev : (ev.name || JSON.stringify(ev));
      const time = (typeof ev === 'object' && ev.time) ? ev.time : '';
      return `
<div class="world-event-item">
  <span class="world-event-dot"></span>
  <span class="world-event-name">${this._escHtml(name)}</span>
  ${time ? `<span class="world-event-time">${this._escHtml(time)}</span>` : ''}
</div>`.trim();
    }).join('');
  }

  /**
   * v1.64.0 [2026-06-27] — Render faction territory power bars.
   * @param {object} data  API response from /api/world_state
   */
  _renderFactionTerritory(data) {
    const barsEl = document.getElementById('faction-bars');
    if (!barsEl) return;

    const factions = data.factions || data.faction_territory || [];
    if (!factions.length) {
      barsEl.innerHTML = '<div class="no-events">No faction data</div>';
      return;
    }

    barsEl.innerHTML = factions.map(f => {
      const name = this._escHtml(f.name || f.id || 'Unknown');
      const pct  = Math.min(100, Math.max(0, f.territory ?? f.power ?? 0));
      const key  = (f.id || f.name || '').toLowerCase().replace(/\s+/g, '_');
      const color = this._factionColors[key] || f.color || '#3b82f6';
      return `
<div class="faction-bar">
  <span class="faction-bar__name">${name}</span>
  <div class="faction-bar__track">
    <div class="faction-bar__fill" style="width:${pct}%;--faction-color:${this._escHtml(color)}"></div>
  </div>
  <span class="faction-bar__pct">${pct}%</span>
</div>`.trim();
    }).join('');
  }

  // -------------------------------------------------------------------
  // Economy Renderer
  // -------------------------------------------------------------------

  /**
   * Fetch economy data and render the economy panel.
   *
   * CONNECTS: /api/economy
   * CALLED BY: init(), setInterval
   * EMITS: DOM updates to economy-balance, header-credits, txn-list
   */
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
   * Render economy summary panel.
   * v1.64.0 — ₵ symbol for credit display
   * @param {object} data  API response from /api/economy
   */
  _renderEconomy(data) {
    const balEl = document.getElementById('economy-balance');
    if (balEl) {
      balEl.textContent = data.balance != null
        ? `₵${Number(data.balance).toLocaleString()}`
        : '₵—';
    }

    const chipEl = document.getElementById('header-credits');
    if (chipEl && data.balance != null) {
      chipEl.textContent = `${Number(data.balance).toLocaleString()}`;
    }

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

  // -------------------------------------------------------------------
  // Nexus Health                                        [v1.64.0]
  // -------------------------------------------------------------------

  /**
   * v1.64.0 [2026-06-27] — Fetch Nexus health for bench HUD.
   *
   * CONNECTS: Nexus KMS /health endpoint
   * EMITS: DOM update to bench-nexus
   */
  async _loadNexusHealth() {
    const el = document.getElementById('bench-nexus');
    if (!el) return;
    try {
      const nexusUrl = (window.COSYSIM?.services?.nexus) || 'http://localhost:8700';
      const start = performance.now();
      const res = await fetch(`${nexusUrl}/health`, { signal: AbortSignal.timeout(3000) });
      const ms = Math.round(performance.now() - start);
      if (res.ok) {
        el.textContent = `online · ${ms}ms`;
      } else {
        el.textContent = 'degraded';
      }
    } catch {
      el.textContent = 'offline';
    }
  }

  // -------------------------------------------------------------------
  // Scenes Badge (Legacy)
  // -------------------------------------------------------------------

  _updateScenesBadge(scenes) {
    const online  = scenes.filter(s => s.status === 'online').length;
    const total   = scenes.length;
    const countEl = document.getElementById('scenes-badge-count');
    if (countEl) countEl.textContent = `${online}/${total}`;
  }

  // -------------------------------------------------------------------
  // Data Stream Particles (Background Canvas Animation)
  // -------------------------------------------------------------------

  /** Initialise the 3-D data-stream background particle canvas. */
  _initDataStream() {
    this._dsCanvas = document.getElementById('data-stream-canvas');
    if (!this._dsCanvas) return;

    this._dsCtx = this._dsCanvas.getContext('2d');
    this._dsResize();
    window.addEventListener('resize', () => this._dsResize());

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
    ctx.font = '11px "JetBrains Mono", "Courier New", monospace';

    this._dsParticles.forEach((p, i) => {
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

      if (p.y > cnv.height + 10) {
        this._dsParticles[i] = this._dsNewParticle(false);
      }
    });

    ctx.globalAlpha = 1;
    this._dsRaf = requestAnimationFrame(() => this._dsLoop());
  }

  // -------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------

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

// =====================================================================
// Bootstrap — DOMContentLoaded entry point
// =====================================================================

document.addEventListener('DOMContentLoaded', () => {
  const hub = new TheTerminalHub();
  hub.init();
  window._theTerminalHub = hub;
});

// =====================================================================
// System poll (bench HUD stats)                        [v1.64.0]
// =====================================================================

(function () {
  async function pollSystem() {
    try {
      const res  = await fetch('/api/system');
      const data = await res.json();
      const agEl = document.getElementById('bench-agents');
      const vmEl = document.getElementById('bench-vram');
      const scEl = document.getElementById('bench-scenes');
      if (agEl) agEl.textContent = data.agent_count ?? '0';
      if (vmEl) {
        vmEl.textContent = data.vram_total_mb
          ? `${Math.round(data.vram_used_mb)}/${Math.round(data.vram_total_mb)} MB`
          : 'N/A';
      }
      if (scEl) {
        const active = (data.active_scenes || []).length;
        scEl.textContent = active ? `${active} active` : '—';
      }
    } catch { /* silent */ }
  }
  pollSystem();
  setInterval(pollSystem, 30_000);
})();
