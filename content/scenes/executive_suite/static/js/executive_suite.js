/**
 * executive_suite.js — NeonOS OS core (window manager + app registry).
 * ===================================================================
 * v1.62.0 [2026-06-15] — ES-T4 live system tray: polls /api/state (~10s) so the
 * taskbar clock + WorldState heat advance live; the in-game clock drives both
 * the taskbar time and date lines.
 * v1.62.0 [2026-06-15] — OS desktop shell (ES-T2). The OS core for the
 * Executive Suite scene: Socket.IO connection, a draggable/focusable window
 * manager, dock + taskbar wiring, desktop-icon drag-drop, a live clock, the
 * ⌘K command palette, toasts, and the canonical `window.ES` APP REGISTRY API
 * that all app modules build against.
 *
 * ───────────────────────────────────────────────────────────────────
 *  APP REGISTRY API CONTRACT (the public surface — apps depend on this)
 * ───────────────────────────────────────────────────────────────────
 * App modules live in SEPARATE files: `static/js/apps/<id>.js`, loaded by
 * `templates/executive_suite.html` AFTER this file. Each module registers
 * itself by calling `ES.registerApp(...)` at load time. The dock pre-registers
 * stub entries for every planned app, so an app that hasn't been built yet
 * still appears in the dock and opens a graceful "coming soon" window.
 *
 * ── ES.registerApp(id, spec) ──
 *   id   {string}  unique app id, e.g. 'mail'. Re-registering an id REPLACES
 *                  the stub/previous definition (apps override their dock stub).
 *   spec {object}:
 *     title   {string}            window + dock title, e.g. 'Mail'
 *     icon    {string}            dock glyph: an emoji, or inline SVG markup
 *     color   {string}            accent: 'cy'|'am'|'pk'|'vi'|'gr'|'sl' OR a
 *                                 CSS color (hex/rgb) applied to the icon
 *     badge   {string|number=}    optional dock badge (e.g. unread count)
 *     pinned  {boolean=}          show in the taskbar pinned strip (default false)
 *     width   {number=}           initial window width px  (default 560)
 *     height  {number=}           initial window height px (default 400)
 *     chips   {Array<{text,color?}>=}  titlebar chips, e.g. [{text:'7 UNREAD'}]
 *     singleton {boolean=}        only one window instance (default true)
 *     render  {function(bodyEl, win)}   REQUIRED. Populate the window body.
 *                                 `bodyEl` is the empty `.es-win__body` div you
 *                                 own. `win` is the Window handle (see below).
 *                                 May be async; return value ignored.
 *     onOpen  {function(win)=}    called after the window is mounted + focused
 *     onClose {function(win)=}    called right before the window is destroyed
 *
 * ── Window handle (passed to render/onOpen/onClose; also ES.openApp returns it) ──
 *     win.id        {string}      app id
 *     win.el        {HTMLElement} the `.es-win` root element
 *     win.body      {HTMLElement} the `.es-win__body` element (same as bodyEl)
 *     win.setTitle(text)          update the titlebar text
 *     win.setChips(chips)         replace titlebar chips
 *     win.setBadge(value)         set/clear the dock badge for this app
 *     win.focus()                 raise + focus this window
 *     win.minimize()              hide to taskbar (state preserved)
 *     win.restore()               un-minimize
 *     win.close()                 close + destroy (fires onClose)
 *     win.minimized {boolean}     current minimized state
 *
 * ── Lifecycle helpers ──
 *   ES.openApp(id)   → Window  opens (or focuses if singleton + already open).
 *                              For an unregistered id, opens a stub window.
 *   ES.closeApp(id)             closes the (first) window for id
 *   ES.focusApp(id)  → Window?  focuses an existing window for id (or null)
 *   ES.isOpen(id)    → boolean
 *
 * ── Shared utilities apps may use ──
 *   ES.socket                   the shared Socket.IO client (may be null if
 *                               socket.io failed to load — always null-check)
 *   ES.state                    last `/api/state` snapshot received
 *   ES.toast(msg, type?)        type ∈ 'info'|'success'|'warn'|'error'
 *   ES.el(tag, attrs?, kids?)   DOM helper. attrs: {class,style,onClick,html,
 *                               text,dataset,...attrs}. kids: node|string|array.
 *   ES.on(event, fn)            subscribe to ES events: 'open','close','focus',
 *                               'state' — fn receives (payload).
 *
 * ── BACKEND ROUTE CONVENTION (for app modules adding server routes) ──
 *   Register routes in `executive_suite_scene.py` under the app's own
 *   namespace: `/api/<app>/...` (e.g. `/api/mail/threads`). Keep the shell's
 *   `/api/state` minimal (clock + tray only). Emit live updates over the
 *   shared Socket.IO connection with `<app>_*` event names (e.g. `mail_new`).
 * ───────────────────────────────────────────────────────────────────
 */
(function () {
  'use strict';

  // ════════════════════════════════════════════════════════════
  // DOM helper
  // ════════════════════════════════════════════════════════════
  /**
   * Create a DOM element. Lightweight hyperscript-style helper.
   * @param {string} tag
   * @param {Object} [attrs] - class/style/text/html/dataset/onX/...attrs
   * @param {(Node|string|Array)} [kids]
   * @returns {HTMLElement}
   */
  function el(tag, attrs, kids) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        const v = attrs[k];
        if (v == null) continue;
        if (k === 'class' || k === 'className') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k === 'html') node.innerHTML = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
        else if (k === 'dataset' && typeof v === 'object') Object.assign(node.dataset, v);
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') {
          node.addEventListener(k.slice(2).toLowerCase(), v);
        } else node.setAttribute(k, v);
      }
    }
    appendKids(node, kids);
    return node;
  }
  function appendKids(node, kids) {
    if (kids == null) return;
    if (Array.isArray(kids)) { kids.forEach((k) => appendKids(node, k)); return; }
    node.appendChild(kids instanceof Node ? kids : document.createTextNode(String(kids)));
  }

  const ACCENT_CLASSES = { cy: 1, am: 1, pk: 1, vi: 1, gr: 1, sl: 1 };

  // ════════════════════════════════════════════════════════════
  // Internal registries / state
  // ════════════════════════════════════════════════════════════
  const apps = new Map();        // id -> spec
  const windows = new Map();     // id -> Window (singleton apps); multi -> array
  const listeners = {};          // event -> fn[]
  let zCounter = 30;             // window z-index counter (matches --es-z-window-base)
  let openOffset = 0;            // cascade offset for new windows

  function emit(event, payload) {
    (listeners[event] || []).forEach((fn) => {
      try { fn(payload); } catch (err) { console.error('[ES] listener error', event, err); }
    });
  }

  // ════════════════════════════════════════════════════════════
  // Toasts
  // ════════════════════════════════════════════════════════════
  function toast(msg, type) {
    const host = document.getElementById('es-toasts');
    if (!host) return;
    const t = el('div', { class: 'es-toast es-toast--' + (type || 'info'), text: msg });
    host.appendChild(t);
    setTimeout(() => {
      t.classList.add('es-toast--out');
      setTimeout(() => t.remove(), 280);
    }, 3200);
  }

  // ════════════════════════════════════════════════════════════
  // Window manager
  // ════════════════════════════════════════════════════════════
  function createWindow(spec) {
    const winsHost = document.getElementById('es-windows');
    const root = el('div', { class: 'es-win', 'data-win': spec.id });

    // Titlebar
    const traffic = el('div', { class: 'es-traffic' }, [
      el('span', { class: 'es-traffic--close', title: 'Close' }),
      el('span', { class: 'es-traffic--min', title: 'Minimize' }),
      el('span', { class: 'es-traffic--max', title: 'Maximize' }),
    ]);
    const titleEl = el('div', { class: 'es-win__title' });
    titleEl.appendChild(iconNode(spec.icon, true));
    const titleText = el('span', { text: spec.title || spec.id });
    titleEl.appendChild(titleText);
    const chipsEl = el('div', { class: 'es-win__chips' });
    const bar = el('div', { class: 'es-win__bar' }, [traffic, titleEl, chipsEl]);

    // Body + resize handle
    const body = el('div', { class: 'es-win__body' });
    const resize = el('div', { class: 'es-win__resize', title: 'Resize' });
    root.append(bar, body, resize);

    // Geometry (cascade so stacked windows don't fully overlap)
    const w = spec.width || 560;
    const h = spec.height || 400;
    root.style.width = w + 'px';
    root.style.height = h + 'px';
    root.style.left = (120 + openOffset) + 'px';
    root.style.top = (70 + openOffset) + 'px';
    openOffset = (openOffset + 28) % 140;

    winsHost.appendChild(root);

    // ── Window handle ──
    const win = {
      id: spec.id,
      el: root,
      body: body,
      minimized: false,
      setTitle(text) { titleText.textContent = text; },
      setChips(chips) { renderChips(chipsEl, chips); },
      setBadge(value) { setDockBadge(spec.id, value); },
      focus() { focusWindow(root); },
      minimize() { minimizeWindow(win); },
      restore() { restoreWindow(win); },
      close() { closeWindow(win); },
    };
    win._spec = spec;
    root.__esWin = win;

    renderChips(chipsEl, spec.chips);

    // Wire titlebar interactions
    traffic.children[0].addEventListener('click', (e) => { e.stopPropagation(); win.close(); });
    traffic.children[1].addEventListener('click', (e) => { e.stopPropagation(); win.minimize(); });
    traffic.children[2].addEventListener('click', (e) => { e.stopPropagation(); win.focus(); });
    makeDraggable(root, bar);
    makeResizable(root, resize);
    root.addEventListener('mousedown', () => focusWindow(root));

    focusWindow(root);
    return win;
  }

  function iconNode(icon, small) {
    // icon may be inline SVG markup or an emoji/text glyph.
    if (icon && icon.trim().slice(0, 4) === '<svg') {
      const span = el('span', { html: icon });
      return span.firstChild || span;
    }
    return document.createTextNode(icon || '▢');
  }

  function renderChips(chipsEl, chips) {
    chipsEl.innerHTML = '';
    (chips || []).forEach((c) => {
      const chip = el('span', { class: 'es-win__chip', text: c.text });
      const color = c.color || 'var(--es)';
      chip.style.color = color;
      chip.style.background = 'rgba(6,182,212,.15)';
      chipsEl.appendChild(chip);
    });
  }

  function focusWindow(root) {
    zCounter++;
    root.style.zIndex = zCounter;
    document.querySelectorAll('.es-win').forEach((w) => w.classList.remove('focused'));
    root.classList.add('focused');
    const win = root.__esWin;
    if (win) {
      syncTaskbar();
      emit('focus', win);
    }
  }

  function minimizeWindow(win) {
    win.minimized = true;
    win.el.style.display = 'none';
    syncTaskbar();
    syncDock();
  }
  function restoreWindow(win) {
    win.minimized = false;
    win.el.style.display = 'flex';
    focusWindow(win.el);
    syncDock();
  }
  function closeWindow(win) {
    const spec = win._spec;
    if (spec && typeof spec.onClose === 'function') {
      try { spec.onClose(win); } catch (err) { console.error('[ES] onClose error', spec.id, err); }
    }
    win.el.style.transition = 'transform .16s, opacity .16s';
    win.el.style.transform = 'scale(0.96)';
    win.el.style.opacity = '0';
    setTimeout(() => win.el.remove(), 160);
    // Drop from registry
    const cur = windows.get(win.id);
    if (Array.isArray(cur)) {
      const next = cur.filter((w) => w !== win);
      if (next.length) windows.set(win.id, next); else windows.delete(win.id);
    } else if (cur === win) {
      windows.delete(win.id);
    }
    syncTaskbar();
    syncDock();
    emit('close', win);
  }

  // ── Dragging (titlebar) ──
  function makeDraggable(root, handle) {
    let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
    function move(e) {
      if (!dragging) return;
      root.style.left = (ox + e.clientX - sx) + 'px';
      root.style.top = (oy + e.clientY - sy) + 'px';
      root.style.right = 'auto';
      root.style.bottom = 'auto';
    }
    function up() { dragging = false; document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); }
    handle.addEventListener('mousedown', (e) => {
      if (e.target.closest('.es-traffic')) return;
      dragging = true;
      const r = root.getBoundingClientRect();
      const pr = root.offsetParent.getBoundingClientRect();
      ox = r.left - pr.left; oy = r.top - pr.top;
      sx = e.clientX; sy = e.clientY;
      root.style.left = ox + 'px'; root.style.top = oy + 'px';
      root.style.right = 'auto'; root.style.bottom = 'auto';
      focusWindow(root);
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
      e.preventDefault();
    });
  }

  // ── Resizing (bottom-right handle) ──
  function makeResizable(root, handle) {
    let sx = 0, sy = 0, ow = 0, oh = 0, resizing = false;
    function move(e) {
      if (!resizing) return;
      root.style.width = Math.max(320, ow + e.clientX - sx) + 'px';
      root.style.height = Math.max(200, oh + e.clientY - sy) + 'px';
    }
    function up() { resizing = false; document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); }
    handle.addEventListener('mousedown', (e) => {
      resizing = true;
      const r = root.getBoundingClientRect();
      ow = r.width; oh = r.height; sx = e.clientX; sy = e.clientY;
      focusWindow(root);
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
      e.preventDefault(); e.stopPropagation();
    });
  }

  // ════════════════════════════════════════════════════════════
  // App registry API
  // ════════════════════════════════════════════════════════════
  function registerApp(id, spec) {
    if (!id || typeof id !== 'object' && !spec) {
      // allow registerApp(spec) with spec.id
    }
    if (typeof id === 'object') { spec = id; id = spec.id; }
    if (!id) { console.error('[ES] registerApp requires an id'); return; }
    spec = Object.assign({}, spec, { id });
    if (spec.singleton === undefined) spec.singleton = true;
    apps.set(id, spec);
    syncDock();
    syncTaskbar();
  }

  function openApp(id) {
    const spec = apps.get(id);
    if (!spec) return openStub(id);

    // Singleton: focus existing
    if (spec.singleton && windows.has(id)) {
      const existing = firstWindow(id);
      if (existing) {
        if (existing.minimized) existing.restore(); else existing.focus();
        return existing;
      }
    }

    const win = createWindow(spec);
    trackWindow(id, win, spec.singleton);

    // Render body (stub-safe)
    if (typeof spec.render === 'function') {
      try { spec.render(win.body, win); }
      catch (err) { console.error('[ES] render error', id, err); renderStubBody(win.body, spec.title, 'failed to load'); }
    } else {
      renderStubBody(win.body, spec.title, 'no renderer');
    }
    if (typeof spec.onOpen === 'function') {
      try { spec.onOpen(win); } catch (err) { console.error('[ES] onOpen error', id, err); }
    }
    syncDock();
    syncTaskbar();
    emit('open', win);
    return win;
  }

  function openStub(id) {
    const spec = { id, title: id, icon: '▢', singleton: true,
      render(bodyEl) { renderStubBody(bodyEl, id, 'coming soon'); } };
    const win = createWindow(spec);
    trackWindow(id, win, true);
    spec.render(win.body, win);
    syncTaskbar();
    emit('open', win);
    return win;
  }

  function renderStubBody(bodyEl, title, msg) {
    bodyEl.innerHTML = '';
    bodyEl.appendChild(el('div', { class: 'es-win__stub' }, [
      el('div', { class: 'es-win__stub-glyph', text: '🛰' }),
      el('div', { class: 'es-win__stub-title', text: (title || 'App') + '' }),
      el('div', { class: 'es-win__stub-msg', text: msg || 'coming soon' }),
    ]));
  }

  function trackWindow(id, win, singleton) {
    if (singleton) { windows.set(id, win); return; }
    const cur = windows.get(id);
    if (Array.isArray(cur)) cur.push(win);
    else if (cur) windows.set(id, [cur, win]);
    else windows.set(id, win);
  }
  function firstWindow(id) {
    const cur = windows.get(id);
    return Array.isArray(cur) ? cur[0] : cur || null;
  }
  function closeApp(id) { const w = firstWindow(id); if (w) w.close(); }
  function focusApp(id) { const w = firstWindow(id); if (w) { w.restore(); return w; } return null; }
  function isOpen(id) { return windows.has(id); }

  // ════════════════════════════════════════════════════════════
  // Dock (left rail) + taskbar
  // ════════════════════════════════════════════════════════════
  function setDockBadge(id, value) {
    const spec = apps.get(id);
    if (spec) spec.badge = value;
    syncDock();
  }

  function syncDock() {
    const dock = document.getElementById('es-dock');
    if (!dock) return;
    dock.innerHTML = '';
    apps.forEach((spec, id) => {
      const open = isOpen(id) && (firstWindow(id) && !firstWindow(id).minimized);
      const appEl = el('div', { class: 'es-app' + (open ? ' active' : ''), 'data-app': id, title: spec.title });
      const iconEl = el('div', { class: 'es-app__icon' + accentClass(spec.color) });
      applyColor(iconEl, spec.color);
      iconEl.appendChild(iconNode(spec.icon));
      appEl.appendChild(iconEl);
      appEl.appendChild(el('div', { class: 'es-app__label', text: spec.title || id }));
      if (spec.badge != null && spec.badge !== '' && spec.badge !== 0) {
        appEl.appendChild(el('div', { class: 'es-app__badge', text: String(spec.badge) }));
      }
      if (isOpen(id)) appEl.appendChild(el('div', { class: 'es-app__dot' }));
      appEl.addEventListener('click', () => toggleApp(id));
      dock.appendChild(appEl);
    });
  }

  function toggleApp(id) {
    const w = firstWindow(id);
    if (!w) { openApp(id); return; }
    if (w.minimized) { w.restore(); return; }
    if (w.el.classList.contains('focused')) { w.minimize(); return; }
    w.focus();
  }

  function accentClass(color) {
    return color && ACCENT_CLASSES[color] ? ' ' + color : '';
  }
  function applyColor(iconEl, color) {
    if (color && !ACCENT_CLASSES[color]) {
      iconEl.style.color = color;
      iconEl.style.borderColor = color;
    }
  }

  function syncTaskbar() {
    const strip = document.getElementById('es-tb-pinned');
    if (!strip) return;
    strip.innerHTML = '';
    // Pinned apps + any open app get a taskbar button.
    const ids = new Set();
    apps.forEach((spec, id) => { if (spec.pinned || isOpen(id)) ids.add(id); });
    ids.forEach((id) => {
      const spec = apps.get(id) || {};
      const w = firstWindow(id);
      const active = w && !w.minimized && w.el.classList.contains('focused');
      const pin = el('div', {
        class: 'es-tb-pin' + (isOpen(id) ? ' active' : '') + (active ? ' focused' : ''),
        title: spec.title || id,
      });
      pin.appendChild(iconNode(spec.icon || '▢'));
      pin.addEventListener('click', () => toggleApp(id));
      strip.appendChild(pin);
    });
  }

  // ════════════════════════════════════════════════════════════
  // Desktop-icon drag-drop (icons → desktop shortcuts)
  // ════════════════════════════════════════════════════════════
  function wireDesktopDnD() {
    const desktop = document.getElementById('es-desktop');
    const dtIcons = document.getElementById('es-dt-icons');
    const hint = document.getElementById('es-drop-hint');
    if (!desktop || !dtIcons) return;

    function wireIcon(elem) {
      elem.addEventListener('dragstart', (e) => {
        const name = elem.dataset.name || 'item';
        e.dataTransfer.setData('text/plain', name);
        e.dataTransfer.effectAllowed = 'move';
        elem.classList.add('dragging');
        if (hint) hint.classList.add('show');
      });
      elem.addEventListener('dragend', () => {
        elem.classList.remove('dragging');
        if (hint) hint.classList.remove('show');
      });
    }
    dtIcons.querySelectorAll('.es-dt-icon').forEach(wireIcon);

    desktop.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    desktop.addEventListener('drop', (e) => {
      e.preventDefault();
      const name = e.dataTransfer.getData('text/plain');
      if (!name) return;
      if ([...dtIcons.children].some((c) => c.dataset.name === name)) return;
      const ext = name.split('.').pop().toLowerCase();
      const glyph = (ext === 'pdf' || ext === 'doc' || ext === 'csv') ? '📄'
        : (ext === 'gph' || ext === 'png' || ext === 'jpg') ? '🖼'
        : (ext === 'wav' || ext === 'mp3') ? '🎵'
        : (ext === 'sh' || ext === 'bin' || ext === 'key') ? '⌬'
        : (ext === 'heist') ? '🎯' : '📄';
      const icon = el('div', { class: 'es-dt-icon', draggable: 'true', dataset: { name } }, [
        el('div', { class: 'es-dt-icon__glyph', text: glyph }),
        el('div', { class: 'es-dt-icon__name', text: name }),
      ]);
      wireIcon(icon);
      dtIcons.appendChild(icon);
      toast('Added "' + name + '" to desktop', 'success');
    });
  }

  // ════════════════════════════════════════════════════════════
  // ⌘K command palette
  // ════════════════════════════════════════════════════════════
  function wirePalette() {
    const palette = document.getElementById('es-palette');
    const input = document.getElementById('es-palette-input');
    const results = document.getElementById('es-palette-results');
    const search = document.getElementById('es-tb-search');
    const start = document.getElementById('es-tb-start');
    if (!palette || !input || !results) return;
    let activeIdx = 0, matches = [];

    function openPalette() { palette.hidden = false; input.value = ''; render(''); input.focus(); }
    function closePalette() { palette.hidden = true; }
    function render(q) {
      q = (q || '').toLowerCase();
      matches = [...apps.values()].filter((s) => (s.title || s.id).toLowerCase().includes(q));
      activeIdx = 0;
      results.innerHTML = '';
      matches.forEach((s, i) => {
        const row = el('div', { class: 'es-palette__row' + (i === 0 ? ' active' : '') }, [
          el('span', { class: 'ic' }, iconNode(s.icon)),
          el('span', { text: s.title || s.id }),
        ]);
        row.addEventListener('click', () => { openApp(s.id); closePalette(); });
        results.appendChild(row);
      });
    }
    function highlight() {
      [...results.children].forEach((r, i) => r.classList.toggle('active', i === activeIdx));
    }

    if (search) search.addEventListener('click', openPalette);
    if (start) start.addEventListener('click', openPalette);
    input.addEventListener('input', () => render(input.value));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closePalette();
      else if (e.key === 'ArrowDown') { activeIdx = Math.min(matches.length - 1, activeIdx + 1); highlight(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { activeIdx = Math.max(0, activeIdx - 1); highlight(); e.preventDefault(); }
      else if (e.key === 'Enter') { const m = matches[activeIdx]; if (m) { openApp(m.id); closePalette(); } }
    });
    palette.addEventListener('mousedown', (e) => { if (e.target === palette) closePalette(); });

    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
    });
  }

  // ════════════════════════════════════════════════════════════
  // Live clock + system tray
  // ════════════════════════════════════════════════════════════
  function pad(n) { return String(n).padStart(2, '0'); }
  function updateClock() {
    // v1.62.0 [2026-06-15] — ES-T4: once the live game clock is driving the tray,
    // don't overwrite it with the wall clock.
    if (gameClockActive) return;
    const d = new Date();
    const t = document.getElementById('es-clock-time');
    const dt = document.getElementById('es-clock-date');
    if (t) t.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes());
    if (dt) dt.textContent = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' · ' + ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  }

  function applyState(state) {
    if (!state) return;
    ES.state = state;
    const tray = state.tray || {};
    const heat = document.getElementById('es-tray-heat-val');
    const batt = document.getElementById('es-tray-battery-val');
    if (heat && tray.heat != null) heat.textContent = tray.heat + '%';
    if (batt && tray.battery != null) batt.textContent = tray.battery + '%';
    // v1.62.0 [2026-06-15] — ES-T4 live tray: the in-game clock drives BOTH the
    // taskbar time and date lines so the tray reflects real WorldState time
    // (not the wall clock). Falls back to the wall clock when no game clock.
    const clk = state.clock || {};
    const tEl = document.getElementById('es-clock-time');
    const dEl = document.getElementById('es-clock-date');
    if (clk.display) {
      gameClockActive = true;
      // display looks like "Monday, 00:00 (Night)" — pull HH:MM for the big line.
      const m = /(\d{1,2}:\d{2})/.exec(clk.display);
      if (tEl && m) tEl.textContent = m[1];
      else if (tEl && clk.game_hour != null) tEl.textContent = pad(clk.game_hour) + ':00';
      if (dEl) dEl.textContent = clk.display;
    }
    emit('state', state);
  }

  // v1.62.0 [2026-06-15] — ES-T4: poll /api/state so the tray (game clock +
  // live WorldState heat) keeps advancing even without socket pushes. Stops
  // the wall-clock from clobbering the game clock once real state arrives.
  let gameClockActive = false;
  function pollState() {
    fetch('/api/state')
      .then((r) => r.json())
      .then(applyState)
      .catch(() => { /* offline — keep last known tray */ });
  }

  // ════════════════════════════════════════════════════════════
  // Socket.IO
  // ════════════════════════════════════════════════════════════
  function connectSocket() {
    if (typeof io !== 'function') {
      console.warn('[executive_suite] Socket.IO not available — running offline');
      return null;
    }
    const socket = io();
    socket.on('connect', () => { console.log('[executive_suite] connected', socket.id); socket.emit('request_state'); });
    socket.on('state_update', applyState);
    socket.on('disconnect', () => console.log('[executive_suite] disconnected'));
    return socket;
  }

  // ════════════════════════════════════════════════════════════
  // Pre-register planned apps as dock STUBS (apps override on load)
  // ════════════════════════════════════════════════════════════
  function registerStubs() {
    const planned = [
      { id: 'files',     title: 'Files',     icon: '📁', color: 'am', pinned: true },
      { id: 'mail',      title: 'Mail',      icon: '✉', color: 'cy', pinned: true, badge: 7 },
      { id: 'notes',     title: 'Notes',     icon: '📝', color: 'vi', pinned: true },
      { id: 'music',     title: 'Music',     icon: '🎵', color: 'pk', pinned: true },
      { id: 'code',      title: 'Code',      icon: '⌬', color: 'gr', pinned: true },
      { id: 'terminal',  title: 'Term',      icon: '▶', color: 'sl' },
      { id: 'browser',   title: 'Browser',   icon: '🌐', color: 'cy' },
      { id: 'settings',  title: 'Settings',  icon: '⚙', color: 'sl' },
      { id: 'assistant', title: 'Assistant', icon: '🤖', color: 'cy' },
    ];
    planned.forEach((p) => {
      registerApp(p.id, Object.assign({}, p, {
        render(bodyEl, win) { renderStubBody(bodyEl, win._spec.title, 'coming soon'); },
      }));
    });
  }

  // ════════════════════════════════════════════════════════════
  // Public API
  // ════════════════════════════════════════════════════════════
  const ES = {
    registerApp, openApp, closeApp, focusApp, isOpen,
    toast, el,
    socket: null,
    state: null,
    on(event, fn) { (listeners[event] = listeners[event] || []).push(fn); },
    // exposed for app modules / debugging
    _apps: apps,
    _windows: windows,
  };
  window.ES = ES;

  // ════════════════════════════════════════════════════════════
  // Boot
  // ════════════════════════════════════════════════════════════
  function boot() {
    registerStubs();
    wireDesktopDnD();
    wirePalette();
    updateClock();
    setInterval(updateClock, 30000);
    ES.socket = connectSocket();
    // v1.62.0 [2026-06-15] — ES-T4 live tray: prime + poll real state (~10s).
    pollState();
    setInterval(pollState, 10000);
    // User profile click → assistant
    const user = document.getElementById('es-user');
    if (user) user.addEventListener('click', () => openApp('assistant'));
    console.log('[executive_suite] OS core ready');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
