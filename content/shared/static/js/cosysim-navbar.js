/**
 * CosySim Navigation Bar
 * ======================
 * Floating scene navigation overlay auto-injected into every Flask scene.
 * Provides cross-scene navigation, scene selector, and keyboard shortcuts.
 *
 * Depends on: cosysim-core.js (optional, for toast notifications)
 *
 * Auto-initializes on DOMContentLoaded. Discovers scenes from a hardcoded
 * registry matching engine/port_registry.py defaults.
 */
(function () {
  'use strict';

  // ── Scene Registry (mirrors engine/port_registry.py) ──────────
  const SCENES = [
    { id: 'hub',       port: 8500, label: 'CosySim Hub',          icon: '🏠', group: 'tools' },
    { id: 'phone',     port: 5555, label: 'CosyPhone',            icon: '📱', group: 'core' },
    { id: 'penthouse',   port: 5556, label: 'The penthouse',          icon: '🛏️', group: 'core' },
    { id: 'lounge',    port: 5557, label: 'The Velvet Lounge',    icon: '🎵', group: 'core' },
    { id: 'tavern',    port: 5558, label: "Dragon's Flagon",      icon: '🍺', group: 'core' },
    { id: 'casino',    port: 5559, label: 'Midnight Casino',      icon: '🎰', group: 'core' },
    { id: 'gallery',   port: 5560, label: 'The Gallery',          icon: '🎨', group: 'core' },
    { id: 'warzone',   port: 5561, label: 'Global Strike',        icon: '⚔️', group: 'core' },
    { id: 'realm',     port: 5562, label: 'The Realm',            icon: '🏰', group: 'core' },
    { id: 'neoncity',  port: 5563, label: 'NeonCity',             icon: '🌃', group: 'core' },
    { id: 'coders',    port: 5564, label: 'The Coders Room',      icon: '💻', group: 'core' },
    { id: 'heist',     port: 5565, label: 'The Heist',            icon: '🔓', group: 'core' },
    { id: 'games',     port: 5567, label: 'Games Arcade',         icon: '🎮', group: 'core' },
    { id: 'nexus_panel', port: 5570, label: 'Nexus Control',      icon: '🧠', group: 'tools' },
    { id: 'command_center', port: 5566, label: 'Command Center',  icon: '📡', group: 'tools' },
    { id: 'dashboard', port: 8501, label: 'Dashboard',            icon: '📊', group: 'tools' },
  ];

  const HUB_PORT = 8500;

  // ── State ─────────────────────────────────────────────────────
  let currentPort = parseInt(window.location.port, 10) || 80;
  let currentScene = SCENES.find(s => s.port === currentPort);
  let sceneStatus = {};  // port → 'online' | 'offline' | 'unknown'
  let navHistory = JSON.parse(sessionStorage.getItem('cs-nav-history') || '[]');
  let navIndex = parseInt(sessionStorage.getItem('cs-nav-index') || '-1', 10);
  let dropdownOpen = false;
  let collapsed = localStorage.getItem('cs-navbar-collapsed') === 'true';

  // ── Health Check ──────────────────────────────────────────────
  async function checkHealth(port) {
    try {
      const ctrl = new AbortController();
      setTimeout(() => ctrl.abort(), 2000);
      const resp = await fetch(`http://localhost:${port}/api/health`, { signal: ctrl.signal });
      return resp.ok ? 'online' : 'offline';
    } catch {
      return 'offline';
    }
  }

  async function refreshAllHealth() {
    const checks = SCENES.map(async (s) => {
      sceneStatus[s.port] = await checkHealth(s.port);
    });
    await Promise.all(checks);
    renderDropdown();
  }

  // ── Navigation ────────────────────────────────────────────────
  function navigateTo(port) {
    if (port === currentPort) return;
    // Record in history
    if (navIndex < navHistory.length - 1) {
      navHistory = navHistory.slice(0, navIndex + 1);
    }
    navHistory.push(currentPort);
    navIndex = navHistory.length - 1;
    sessionStorage.setItem('cs-nav-history', JSON.stringify(navHistory));
    sessionStorage.setItem('cs-nav-index', String(navIndex));
    window.location.href = `http://localhost:${port}/`;
  }

  function goBack() {
    if (navIndex <= 0) return;
    navIndex--;
    sessionStorage.setItem('cs-nav-index', String(navIndex));
    window.location.href = `http://localhost:${navHistory[navIndex]}/`;
  }

  function goForward() {
    if (navIndex >= navHistory.length - 1) return;
    navIndex++;
    sessionStorage.setItem('cs-nav-index', String(navIndex));
    window.location.href = `http://localhost:${navHistory[navIndex]}/`;
  }

  function goHome() {
    navigateTo(HUB_PORT);
  }

  // ── Track current page in history ─────────────────────────────
  function recordCurrentPage() {
    if (navHistory.length === 0 || navHistory[navIndex] !== currentPort) {
      navHistory.push(currentPort);
      navIndex = navHistory.length - 1;
      sessionStorage.setItem('cs-nav-history', JSON.stringify(navHistory));
      sessionStorage.setItem('cs-nav-index', String(navIndex));
    }
  }

  // ── Toggle ────────────────────────────────────────────────────
  function toggleCollapse() {
    collapsed = !collapsed;
    localStorage.setItem('cs-navbar-collapsed', String(collapsed));
    const bar = document.getElementById('cs-navbar');
    if (bar) bar.classList.toggle('collapsed', collapsed);
    document.body.classList.toggle('cs-navbar-active', !collapsed);
  }

  function toggleDropdown() {
    dropdownOpen = !dropdownOpen;
    const panel = document.getElementById('cs-nav-dropdown-panel');
    if (panel) panel.classList.toggle('open', dropdownOpen);
    if (dropdownOpen) refreshAllHealth();
  }

  // ── Render Dropdown ───────────────────────────────────────────
  function renderDropdown() {
    const panel = document.getElementById('cs-nav-dropdown-panel');
    if (!panel) return;

    const groups = { core: [], tools: [] };
    for (const s of SCENES) {
      const g = groups[s.group] || groups.core;
      g.push(s);
    }

    let html = '';
    const groupLabels = { core: 'Scenes', tools: 'Tools & Admin' };
    for (const [key, scenes] of Object.entries(groups)) {
      if (scenes.length === 0) continue;
      html += `<div class="cs-nav-section">${groupLabels[key] || key}</div>`;
      for (const s of scenes) {
        const status = sceneStatus[s.port] || 'unknown';
        const isCurrent = s.port === currentPort;
        html += `
          <a class="cs-nav-scene-card ${isCurrent ? 'current' : ''}"
             href="http://localhost:${s.port}/"
             onclick="event.preventDefault(); window._csNav.navigateTo(${s.port})"
             title="${s.label} (port ${s.port})">
            <span class="scene-icon">${s.icon}</span>
            <span class="scene-info">
              <span class="scene-label">${s.label}</span>
              <span class="scene-port">:${s.port}</span>
            </span>
            <span class="cs-status-dot ${status}"></span>
          </a>`;
      }
    }
    panel.innerHTML = html;
  }

  // ── Build DOM ─────────────────────────────────────────────────
  function createNavbar() {
    // Inject CSS
    if (!document.getElementById('cs-navbar-css')) {
      const link = document.createElement('link');
      link.id = 'cs-navbar-css';
      link.rel = 'stylesheet';
      link.href = '/shared/css/cosysim-navbar.css';
      document.head.appendChild(link);
    }

    const sceneName = currentScene ? currentScene.label : `Port ${currentPort}`;
    const sceneIcon = currentScene ? currentScene.icon : '🔌';
    const canBack = navIndex > 0;
    const canFwd = navIndex < navHistory.length - 1;

    // Navbar
    const bar = document.createElement('div');
    bar.id = 'cs-navbar';
    bar.className = `cs-navbar${collapsed ? ' collapsed' : ''}`;
    bar.innerHTML = `
      <button class="cs-nav-btn" onclick="window._csNav.goBack()" title="Back (Ctrl+Shift+←)" ${canBack ? '' : 'disabled'}>◀</button>
      <button class="cs-nav-btn" onclick="window._csNav.goHome()" title="Hub (Ctrl+Shift+H)">🏠</button>
      <button class="cs-nav-btn" onclick="window._csNav.goForward()" title="Forward (Ctrl+Shift+→)" ${canFwd ? '' : 'disabled'}>▶</button>
      <span class="cs-nav-sep"></span>
      <span class="cs-nav-scene-name">${sceneIcon} ${sceneName}</span>
      <span class="cs-nav-spacer"></span>
      <div class="cs-nav-dropdown">
        <button class="cs-nav-btn" onclick="window._csNav.toggleDropdown()" title="Scene Selector">
          🗂️ Scenes
        </button>
        <div id="cs-nav-dropdown-panel" class="cs-nav-dropdown-panel"></div>
      </div>
      <span class="cs-nav-sep"></span>
      <button class="cs-nav-btn cs-nav-minimize" onclick="window._csNav.toggleCollapse()" title="Minimize navbar">✕</button>
    `;
    document.body.prepend(bar);

    // Toggle tab (for restoring collapsed navbar)
    const toggle = document.createElement('button');
    toggle.className = 'cs-navbar-toggle';
    toggle.onclick = toggleCollapse;
    toggle.title = 'Show navigation bar';
    document.body.appendChild(toggle);

    // Add body padding
    if (!collapsed) {
      document.body.classList.add('cs-navbar-active');
    }

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
      if (dropdownOpen && !e.target.closest('.cs-nav-dropdown')) {
        dropdownOpen = false;
        const panel = document.getElementById('cs-nav-dropdown-panel');
        if (panel) panel.classList.remove('open');
      }
    });
  }

  // ── Keyboard Shortcuts ────────────────────────────────────────
  function setupKeyboard() {
    document.addEventListener('keydown', (e) => {
      // Ctrl+Shift combos
      if (e.ctrlKey && e.shiftKey) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); goBack(); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); goForward(); }
        else if (e.key === 'H' || e.key === 'h') { e.preventDefault(); goHome(); }
        else if (e.key === 'N' || e.key === 'n') { e.preventDefault(); toggleCollapse(); }
      }
    });
  }

  // ── Public API ────────────────────────────────────────────────
  window._csNav = {
    navigateTo,
    goBack,
    goForward,
    goHome,
    toggleCollapse,
    toggleDropdown,
    refreshHealth: refreshAllHealth,
    scenes: SCENES,
    getCurrentScene: () => currentScene,
  };

  // ── Init ──────────────────────────────────────────────────────
  function init() {
    recordCurrentPage();
    createNavbar();
    setupKeyboard();
    // Initial health check (async, non-blocking)
    refreshAllHealth();
    // Periodic refresh every 30s
    setInterval(refreshAllHealth, 30000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
