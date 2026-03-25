/**
 * cosysim-desktop.js — NeonOS Desktop Window Manager + App Launcher
 * ==================================================================
 *
 * Full window-manager for the NeonOS virtual desktop scene.  Fetches the
 * app list from /api/apps, renders an icon grid launcher, and opens each
 * app inside a draggable, resizable, focus-managed iframe window.
 *
 * Version: v1.51.0 [2026-03-25]
 * Author:  CosySim Team
 *
 * Change Log:
 *   v1.51.0 [2026-03-25] — Initial implementation: launcher grid, window
 *                           manager, taskbar, drag/resize, z-index focus
 *
 * CONNECTS: NeonosScene /api/apps endpoint
 * CALLED BY: neonos.html inline <script>
 * EMITS: DOM manipulation (windows, taskbar buttons, clock)
 */

'use strict';

// ──── NeonWindow ─────────────────────────────────────────────────────────

/**
 * A single desktop window wrapping an iframe to a CosySim scene/service.
 *
 * @param {Object} app - App descriptor from /api/apps.
 * @param {NeonDesktop} desktop - Parent desktop instance.
 */
class NeonWindow {
  constructor(app, desktop) {
    this.app = app;
    this.desktop = desktop;
    this.id = `neon-win-${app.id}`;
    this.el = null;
    this.taskbarBtn = null;
    this.isMinimized = false;
    this.isMaximized = false;
    this._prevBounds = null;  // stored bounds before maximize
    this._dragState = null;
    this._resizeState = null;
    this._build();
  }

  // ── DOM Construction ─────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Build window DOM with titlebar, iframe, resize handle
  _build() {
    const win = document.createElement('div');
    win.className = 'neon-window';
    win.id = this.id;
    win.style.zIndex = this.desktop._nextZIndex();
    win.style.borderColor = this.app.accent_color;

    // Position: offset each window slightly so they don't stack exactly
    const offset = (this.desktop.windows.length % 8) * 30;
    win.style.left = `${80 + offset}px`;
    win.style.top = `${60 + offset}px`;
    win.style.width = '900px';
    win.style.height = '600px';

    // ── Titlebar ──
    const titlebar = document.createElement('div');
    titlebar.className = 'neon-window__titlebar';
    titlebar.style.background = `linear-gradient(90deg, ${this.app.accent_color}22, ${this.app.accent_color}08)`;
    titlebar.style.borderBottom = `1px solid ${this.app.accent_color}44`;

    const titleLabel = document.createElement('span');
    titleLabel.className = 'neon-window__title';
    titleLabel.textContent = this.app.display_name;
    titleLabel.style.color = this.app.accent_color;

    const statusDot = document.createElement('span');
    statusDot.className = `neon-window__status neon-window__status--${this.app.status}`;

    const btnGroup = document.createElement('div');
    btnGroup.className = 'neon-window__buttons';

    const btnMin = this._makeBtn('minimize', '\u2013', () => this.minimize());
    const btnMax = this._makeBtn('maximize', '\u25A1', () => this.maximize());
    const btnClose = this._makeBtn('close', '\u2715', () => this.close());

    btnGroup.append(btnMin, btnMax, btnClose);
    titlebar.append(statusDot, titleLabel, btnGroup);

    // Drag via titlebar
    titlebar.addEventListener('mousedown', (e) => this._startDrag(e));

    // ── Content iframe ──
    const content = document.createElement('div');
    content.className = 'neon-window__content';

    const iframe = document.createElement('iframe');
    iframe.className = 'neon-window__iframe';
    iframe.src = this.app.url;
    iframe.setAttribute('loading', 'lazy');
    iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups');
    content.appendChild(iframe);

    // ── Resize handle ──
    const resizeHandle = document.createElement('div');
    resizeHandle.className = 'neon-window__resize';
    resizeHandle.addEventListener('mousedown', (e) => this._startResize(e));

    // ── Assemble ──
    win.append(titlebar, content, resizeHandle);

    // Focus on click
    win.addEventListener('mousedown', () => this.focus());

    this.el = win;
    document.getElementById('neon-desktop').appendChild(win);

    // Taskbar button
    this._createTaskbarBtn();
  }

  _makeBtn(role, label, handler) {
    const btn = document.createElement('button');
    btn.className = `neon-window__btn neon-window__btn--${role}`;
    btn.textContent = label;
    btn.title = role.charAt(0).toUpperCase() + role.slice(1);
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      handler();
    });
    return btn;
  }

  // ── Taskbar Button ──────────────────────────────────────────────

  _createTaskbarBtn() {
    const btn = document.createElement('button');
    btn.className = 'neon-taskbar__app-btn';
    btn.style.borderBottom = `2px solid ${this.app.accent_color}`;
    btn.textContent = this.app.display_name;
    btn.title = this.app.display_name;
    btn.addEventListener('click', () => {
      if (this.isMinimized) {
        this.minimize(); // toggle — restore
      } else {
        this.focus();
      }
    });
    this.taskbarBtn = btn;

    const container = document.getElementById('taskbar-apps');
    if (container) container.appendChild(btn);
  }

  // ── Window Actions ──────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Minimize/maximize/close/focus
  minimize() {
    if (this.isMinimized) {
      // Restore
      this.el.style.display = '';
      this.isMinimized = false;
      if (this.taskbarBtn) this.taskbarBtn.classList.remove('neon-taskbar__app-btn--minimized');
      this.focus();
    } else {
      this.el.style.display = 'none';
      this.isMinimized = true;
      if (this.taskbarBtn) this.taskbarBtn.classList.add('neon-taskbar__app-btn--minimized');
    }
  }

  maximize() {
    if (this.isMaximized) {
      // Restore previous bounds
      if (this._prevBounds) {
        this.el.style.left = this._prevBounds.left;
        this.el.style.top = this._prevBounds.top;
        this.el.style.width = this._prevBounds.width;
        this.el.style.height = this._prevBounds.height;
      }
      this.el.classList.remove('neon-window--maximized');
      this.isMaximized = false;
    } else {
      // Save current bounds and go fullscreen within desktop
      this._prevBounds = {
        left: this.el.style.left,
        top: this.el.style.top,
        width: this.el.style.width,
        height: this.el.style.height,
      };
      this.el.style.left = '0';
      this.el.style.top = '0';
      this.el.style.width = '100%';
      // Leave room for taskbar (48px)
      this.el.style.height = 'calc(100% - 48px)';
      this.el.classList.add('neon-window--maximized');
      this.isMaximized = true;
    }
    this.focus();
  }

  close() {
    if (this.el) this.el.remove();
    if (this.taskbarBtn) this.taskbarBtn.remove();
    this.desktop.windows = this.desktop.windows.filter((w) => w !== this);
  }

  focus() {
    this.el.style.zIndex = this.desktop._nextZIndex();
    // Highlight taskbar button
    const allBtns = document.querySelectorAll('.neon-taskbar__app-btn');
    allBtns.forEach((b) => b.classList.remove('neon-taskbar__app-btn--active'));
    if (this.taskbarBtn) this.taskbarBtn.classList.add('neon-taskbar__app-btn--active');
  }

  // ── Drag Logic ──────────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Mouse drag on titlebar
  _startDrag(e) {
    // Only drag from titlebar, not from buttons
    if (e.target.closest('.neon-window__buttons')) return;
    if (this.isMaximized) return;

    e.preventDefault();
    this.focus();

    const rect = this.el.getBoundingClientRect();
    this._dragState = {
      startX: e.clientX,
      startY: e.clientY,
      origLeft: rect.left,
      origTop: rect.top,
    };

    // Overlay to prevent iframe from stealing mouse events
    this._addOverlay();

    const onMove = (ev) => {
      const dx = ev.clientX - this._dragState.startX;
      const dy = ev.clientY - this._dragState.startY;
      this.el.style.left = `${this._dragState.origLeft + dx}px`;
      this.el.style.top = `${this._dragState.origTop + dy}px`;
    };

    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      this._removeOverlay();
      this._dragState = null;
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // ── Resize Logic ────────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Mouse resize from bottom-right handle
  _startResize(e) {
    if (this.isMaximized) return;

    e.preventDefault();
    e.stopPropagation();
    this.focus();

    const rect = this.el.getBoundingClientRect();
    this._resizeState = {
      startX: e.clientX,
      startY: e.clientY,
      origW: rect.width,
      origH: rect.height,
    };

    this._addOverlay();

    const onMove = (ev) => {
      const dx = ev.clientX - this._resizeState.startX;
      const dy = ev.clientY - this._resizeState.startY;
      const newW = Math.max(320, this._resizeState.origW + dx);
      const newH = Math.max(200, this._resizeState.origH + dy);
      this.el.style.width = `${newW}px`;
      this.el.style.height = `${newH}px`;
    };

    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      this._removeOverlay();
      this._resizeState = null;
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // ── Overlay helpers (prevent iframe from eating mouse events) ───

  _addOverlay() {
    if (this._overlay) return;
    const ov = document.createElement('div');
    ov.className = 'neon-window__drag-overlay';
    this.el.appendChild(ov);
    this._overlay = ov;
  }

  _removeOverlay() {
    if (this._overlay) {
      this._overlay.remove();
      this._overlay = null;
    }
  }
}


// ──── NeonDesktop ────────────────────────────────────────────────────────

/**
 * Desktop window manager and app launcher for NeonOS.
 *
 * CONNECTS: NeonosScene /api/apps, NeonWindow instances
 * CALLED BY: neonos.html inline bootstrap
 * EMITS: DOM manipulation (app grid, taskbar clock)
 */
class NeonDesktop {
  constructor() {
    this.windows = [];
    this._zIndex = 100;
    this._apps = [];
    this._clockInterval = null;
  }

  // ── Z-Index Manager ─────────────────────────────────────────────

  _nextZIndex() {
    this._zIndex += 1;
    return this._zIndex;
  }

  // ── App Loading ─────────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Fetch app list from /api/apps and render launcher grid
  async loadApps() {
    try {
      const resp = await fetch('/api/apps');
      const data = await resp.json();
      if (data.ok && Array.isArray(data.apps)) {
        this._apps = data.apps;
        this._renderLauncher(data.apps);
      } else {
        console.warn('[NeonOS] Failed to load apps:', data);
      }
    } catch (err) {
      console.error('[NeonOS] Error fetching apps:', err);
    }

    // Start taskbar clock
    this._startClock();
  }

  // ── Launcher Grid ───────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Render app icon grid sorted by pillar
  _renderLauncher(apps) {
    const container = document.getElementById('neon-app-launcher');
    if (!container) return;
    container.innerHTML = '';

    // Group by pillar
    const groups = { game: [], service: [], creation: [] };
    for (const app of apps) {
      const pillar = app.pillar || 'service';
      if (!groups[pillar]) groups[pillar] = [];
      groups[pillar].push(app);
    }

    const pillarLabels = {
      game: 'Game Scenes',
      service: 'Services',
      creation: 'Creation Tools',
    };

    for (const [pillar, label] of Object.entries(pillarLabels)) {
      const pillarApps = groups[pillar];
      if (!pillarApps || pillarApps.length === 0) continue;

      const section = document.createElement('div');
      section.className = 'neon-app-launcher__section';

      const heading = document.createElement('h2');
      heading.className = 'neon-app-launcher__heading';
      heading.textContent = label;
      section.appendChild(heading);

      const grid = document.createElement('div');
      grid.className = 'neon-app-launcher__grid';

      for (const app of pillarApps) {
        const tile = this._createAppTile(app);
        grid.appendChild(tile);
      }

      section.appendChild(grid);
      container.appendChild(section);
    }
  }

  _createAppTile(app) {
    const tile = document.createElement('button');
    tile.className = 'neon-app-tile';
    tile.dataset.appId = app.id;
    tile.dataset.status = app.status;

    const icon = document.createElement('div');
    icon.className = 'neon-app-tile__icon';
    icon.style.color = app.accent_color;
    icon.style.borderColor = `${app.accent_color}44`;
    icon.style.boxShadow = `0 0 20px ${app.accent_color}22, inset 0 0 20px ${app.accent_color}11`;
    // Use first letter as icon (unicode icon would require a font library)
    icon.textContent = app.display_name.charAt(0);

    const label = document.createElement('span');
    label.className = 'neon-app-tile__label';
    label.textContent = app.display_name;

    const status = document.createElement('span');
    status.className = `neon-app-tile__status neon-app-tile__status--${app.status}`;
    status.textContent = app.status === 'up' ? 'ONLINE' : 'OFFLINE';

    tile.append(icon, label, status);

    tile.addEventListener('click', () => this.openApp(app));
    tile.addEventListener('dblclick', () => this.openApp(app));

    return tile;
  }

  // ── Open App ────────────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Create NeonWindow for an app
  openApp(app) {
    // Check if window already exists — focus it instead
    const existing = this.windows.find((w) => w.app.id === app.id);
    if (existing) {
      if (existing.isMinimized) existing.minimize(); // restore
      existing.focus();
      return;
    }

    const win = new NeonWindow(app, this);
    this.windows.push(win);
  }

  // ── Taskbar Clock ───────────────────────────────────────────────

  // v1.51.0 [2026-03-25] — Real-time clock in taskbar
  _startClock() {
    const clockEl = document.getElementById('taskbar-clock');
    if (!clockEl) return;

    const update = () => {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, '0');
      const m = String(now.getMinutes()).padStart(2, '0');
      const s = String(now.getSeconds()).padStart(2, '0');
      clockEl.textContent = `${h}:${m}:${s}`;
    };

    update();
    this._clockInterval = setInterval(update, 1000);
  }
}
