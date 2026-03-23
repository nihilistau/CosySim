/**
 * cosysim-neon-hud.js — Universal Neon City HUD
 * ================================================
 * Polls /api/hud/state every 30 seconds and listens to Socket.IO
 * world_event + hud_update events to keep the HUD strip current.
 *
 * Exposes: window.NeonHUD (instance on DOMContentLoaded)
 *
 * Dependencies:
 *   - Socket.IO (window.io — assumed loaded by scene templates)
 *   - /api/hud/state endpoint (registered by BaseScene._register_hud_route)
 */

'use strict';

(function () {
  // ── Constants ──────────────────────────────────────────────────────────
  const POLL_INTERVAL_MS = 30_000;
  const MAX_EVENTS       = 50;
  const HUD_ENDPOINT     = '/api/hud/state';

  const WEATHER_ICONS = {
    clear:       '☀️',
    overcast:    '🌥️',
    neon_rain:   '🌧️',
    heavy_rain:  '⛈️',
    fog:         '🌫️',
    storm:       '⚡',
    blackout:    '🌑',
  };

  const FACTION_COLORS = {
    OmniCorp:    '#06b6d4',
    NeoTech:     '#8b5cf6',
    BlackMarket: '#f59e0b',
    Ghost_Net:   '#4ade80',
    SynthSec:    '#f43f5e',
    DeepState:   '#94a3b8',
  };

  // ── NeonHUD class ──────────────────────────────────────────────────────

  class NeonHUD {
    constructor () {
      this._state    = null;
      this._events   = [];      // rolling event history
      this._pollTid  = null;
      this._expanded = false;
      this._leftOpen  = false;
      this._rightOpen = false;
      this._phoneOpen = false;
      this._activePopup = null;  // v1.43.0 — active item/crew popup reference
      this._missionBoardOpen = false;
      this._shopOpen = false;

      // DOM refs — resolved after DOMContentLoaded
      this._els = {};
    }

    // ── Init ────────────────────────────────────────────────────────────

    init () {
      this._resolveEls();
      this._bindEvents();
      this._connectSocket();
      this._poll();
      this._pollTid = setInterval(() => this._poll(), POLL_INTERVAL_MS);
    }

    _resolveEls () {
      const $ = id => document.getElementById(id);
      this._els = {
        hud:         $('#cs-hud'),
        panel:       $('#cs-hud-panel'),
        backdrop:    $('#cs-hud-backdrop'),
        closeBtn:    $('#hud-panel-close'),
        weather:     $('#hud-weather'),
        location:    $('#hud-location'),
        time:        $('#hud-time'),
        ticker:      $('#hud-ticker'),
        credits:     $('#hud-credits'),
        repFill:     $('#hud-rep-fill'),
        repBar:      $('#hud-rep-bar'),
        repValue:    $('#hud-rep-value'),
        heatIcon:    $('#hud-heat-icon'),
        heat:        $('#hud-heat'),
        // panel
        panelCredits:  $('#panel-credits'),
        panelRep:      $('#panel-rep'),
        panelHeat:     $('#panel-heat'),
        panelLocation: $('#panel-location'),
        factions:      $('#panel-factions'),
        eventList:     $('#hud-event-list'),
      };
    }

    _bindEvents () {
      const { hud, panel, backdrop, closeBtn } = this._els;

      // Center click opens event feed (but not on toggle buttons)
      const centerEl = document.getElementById('hud-center-click');
      if (centerEl) {
        centerEl.addEventListener('click', () => this._togglePanel());
      } else if (hud) {
        // Fallback: old behaviour
        hud.addEventListener('click', e => {
          if (!e.target.closest('#hud-panel-close') &&
              !e.target.closest('.cs-hud__toggle') &&
              !e.target.closest('.cs-hud__right-actions')) {
            this._togglePanel();
          }
        });
      }
      if (closeBtn) closeBtn.addEventListener('click', () => this._closePanel());
      if (backdrop) backdrop.addEventListener('click', () => {
        this._closePanel();
        this._closeLeftPanel();
        this._closeRightPanel();
      });

      // Left panel toggle
      const toggleLeft = document.getElementById('hud-toggle-left');
      if (toggleLeft) toggleLeft.addEventListener('click', () => this._toggleLeftPanel());

      const leftClose = document.getElementById('hud-left-close');
      if (leftClose) leftClose.addEventListener('click', () => this._closeLeftPanel());

      // Right panel toggle
      const toggleRight = document.getElementById('hud-toggle-right');
      if (toggleRight) toggleRight.addEventListener('click', () => this._toggleRightPanel());

      const rightClose = document.getElementById('hud-right-close');
      if (rightClose) rightClose.addEventListener('click', () => this._closeRightPanel());

      // Phone toggle
      const togglePhone = document.getElementById('hud-toggle-phone');
      if (togglePhone) togglePhone.addEventListener('click', () => this._togglePhoneOverlay());

      const phoneLaunch = document.getElementById('hud-phone-launch');
      if (phoneLaunch) phoneLaunch.addEventListener('click', () => this._openPhoneOverlay());

      const phoneClose = document.getElementById('phone-overlay-close');
      if (phoneClose) phoneClose.addEventListener('click', () => this._closePhoneOverlay());

      const phoneDetach = document.getElementById('phone-overlay-detach');
      if (phoneDetach) phoneDetach.addEventListener('click', () => {
        window.open(window.COSYSIM?.services?.phone || 'http://localhost:5555', '_blank');
      });

      // Nexus search
      const searchInput = document.getElementById('hud-nexus-search');
      const searchBtn   = document.getElementById('hud-nexus-search-btn');
      if (searchInput) {
        searchInput.addEventListener('keydown', e => {
          if (e.key === 'Enter') this._nexusSearch(searchInput.value.trim());
        });
      }
      if (searchBtn) {
        searchBtn.addEventListener('click', () => {
          const val = document.getElementById('hud-nexus-search')?.value.trim();
          if (val) this._nexusSearch(val);
        });
      }

      document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
          if (this._activePopup)       this._closePopup();
          else if (this._missionBoardOpen) this._closeMissionBoard();
          else if (this._shopOpen)     this._closeShop();
          else if (this._phoneOpen)    this._closePhoneOverlay();
          else if (this._rightOpen)    this._closeRightPanel();
          else if (this._leftOpen)     this._closeLeftPanel();
          else if (this._expanded)     this._closePanel();
        }
        if (e.key === 'i' || e.key === 'I') {
          if (!e.target.matches('input, textarea, [contenteditable]'))
            this._toggleLeftPanel();
        }
        if (e.key === 'c' || e.key === 'C') {
          if (!e.target.matches('input, textarea, [contenteditable]'))
            this._toggleRightPanel();
        }
        if (e.key === 'p' || e.key === 'P') {
          if (!e.target.matches('input, textarea, [contenteditable]'))
            this._togglePhoneOverlay();
        }
        // v1.43.0 — Mission board (M) and Shop (B)
        if (e.key === 'm' || e.key === 'M') {
          if (!e.target.matches('input, textarea, [contenteditable]'))
            this._toggleMissionBoard();
        }
        if (e.key === 'b' || e.key === 'B') {
          if (!e.target.matches('input, textarea, [contenteditable]'))
            this._toggleShop();
        }
      });
    }

    // ── Socket.IO ───────────────────────────────────────────────────────

    _connectSocket () {
      if (typeof io === 'undefined') return;
      try {
        // Reuse scene socket if available, otherwise create one
        const socket = window.socket || io();
        this.socket = socket;
        socket.on('world_event', data => this._onWorldEvent(data));
        socket.on('hud_update',  data => this._onHudUpdate(data));
      } catch (err) {
        console.debug('[NeonHUD] Socket.IO not available:', err.message);
      }
    }

    _onWorldEvent (data) {
      const title = data.title || data.event_type || 'World event';
      this._addEventToHistory({
        title,
        scene: data.scene || '',
        ts:    Date.now(),
      });
      this._flashTicker(title);

      // If world_event carries a weather field, update weather icon
      if (data.weather) this._setWeather(data.weather);

      // Apply data-weather on body for CSS FX reactions
      if (data.event_type === 'blackout') {
        document.body.setAttribute('data-weather', 'blackout');
      } else if (data.event_type === 'festival') {
        document.body.setAttribute('data-weather', 'clear');
      }
    }

    _onHudUpdate (data) {
      if (!data) return;
      // Merge delta into cached state
      if (this._state) {
        const d = data._delta || {};
        if ('credits_delta' in d) {
          const gain = d.credits_delta > 0;
          this._state.credits = data.credits ?? this._state.credits;
          this._animateCredits(gain);
          this._showCreditChange(d.credits_delta);
        }
        if ('level_up' in d || 'level_change' in d) {
          this._showLevelUp(data.level ?? d.level_up ?? d.level_change);
        }
        if ('rep_delta' in d) this._state.reputation = data.reputation ?? this._state.reputation;
        if ('heat_delta' in d || 'heat' in d) this._state.heat = data.heat ?? this._state.heat;
        if ('location' in d) this._state.active_location = d.location;
        if (data.faction_standings) this._state.faction_standings = data.faction_standings;
      } else {
        this._state = data;
      }
      this._render(this._state);
    }

    // ── Polling ─────────────────────────────────────────────────────────

    async _poll () {
      try {
        const res = await fetch(HUD_ENDPOINT, { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        this._state = data;
        this._render(data);
      } catch (err) {
        console.debug('[NeonHUD] poll failed:', err.message);
      }
    }

    // ── Rendering ───────────────────────────────────────────────────────

    _render (state) {
      if (!state) return;
      const { els } = this;

      // Credits
      const cStr = Number(state.credits || 0).toLocaleString();
      if (this._els.credits) this._els.credits.textContent = cStr;

      // Reputation
      const rep = Math.max(0, Math.min(100, state.reputation ?? 50));
      if (this._els.repFill)  this._els.repFill.style.width = rep + '%';
      if (this._els.repBar)   this._els.repBar.setAttribute('aria-valuenow', rep);
      if (this._els.repValue) this._els.repValue.textContent = rep;

      // Heat
      const heat     = Math.max(0, Math.min(100, state.heat ?? 0));
      const heatCls  = heat >= 75 ? 'critical' : heat >= 50 ? 'high' : heat >= 25 ? 'medium' : 'low';
      if (this._els.heat) {
        this._els.heat.textContent = heat + '%';
        this._els.heat.className   = `cs-hud__heat cs-hud__heat--${heatCls}`;
      }
      if (this._els.heatIcon) {
        const critical = heat >= 75;
        this._els.heatIcon.classList.toggle('cs-hud__heat-icon--critical', critical);
      }

      // Location
      if (this._els.location && state.active_location) {
        this._els.location.textContent = state.active_location.toUpperCase();
      }

      // Panel stats
      if (this._els.panelCredits) this._els.panelCredits.textContent = '₵ ' + cStr;
      if (this._els.panelRep)     this._els.panelRep.textContent     = rep + ' / 100';
      if (this._els.panelHeat)    this._els.panelHeat.textContent    = heat + '%';
      if (this._els.panelLocation && state.active_location) {
        this._els.panelLocation.textContent = state.active_location.toUpperCase();
      }

      // World time from payload
      if (state.world_time && this._els.time) {
        this._els.time.textContent = state.world_time;
      }

      // Weather
      if (state.weather) this._setWeather(state.weather);

      // Faction standings
      if (state.faction_standings) this._renderFactions(state.faction_standings);

      // Event history from state
      if (state.event_history && state.event_history.length > 0) {
        const newEvents = state.event_history.map(e => ({
          title: e.title,
          scene: e.scene || '',
          ts:    e.ts ? e.ts * 1000 : Date.now(),
        }));
        // Merge (avoid dupes by title+ts proximity)
        newEvents.forEach(ev => this._addEventToHistory(ev, false));
        this._renderEventList();
      }

      // Left panel stats
      this._renderLeftPanel(state);
      // Right panel (crew + missions)
      this._renderRightPanel(state);
    }

    _setWeather (weather) {
      const icon = WEATHER_ICONS[weather] || '🌐';
      if (this._els.weather) this._els.weather.textContent = icon;
      document.body.setAttribute('data-weather', weather);
    }

    _renderFactions (standings) {
      const wrap = this._els.factions;
      if (!wrap) return;

      // Keep title row, rebuild rest
      const title = wrap.querySelector('.cs-hud__faction-title');
      wrap.innerHTML = '';
      if (title) wrap.appendChild(title);

      const titleEl = title || document.createElement('div');
      titleEl.className   = 'cs-hud__faction-title';
      titleEl.textContent = 'FACTION STANDINGS';
      if (!title) wrap.appendChild(titleEl);

      Object.entries(standings).forEach(([faction, value]) => {
        const val  = Math.max(-100, Math.min(100, value));
        const sign = val >= 0 ? 'positive' : 'negative';
        const pct  = Math.abs(val);
        const color = FACTION_COLORS[faction] || '#94a3b8';

        const row = document.createElement('div');
        row.className = `cs-hud__faction-row cs-hud__faction-row--${sign}`;
        row.innerHTML = `
          <span class="cs-hud__faction-name" style="color:${color}">${faction}</span>
          <div class="cs-hud__faction-bar-wrap">
            <div class="cs-hud__faction-bar-fill cs-hud__faction-bar-fill--${sign}"
                 style="width:${pct / 2}%; background:${color}; opacity:0.7"></div>
          </div>
          <span class="cs-hud__faction-value">${val > 0 ? '+' : ''}${val}</span>
        `;
        wrap.appendChild(row);
      });
    }

    _renderEventList () {
      const list = this._els.eventList;
      if (!list) return;

      list.innerHTML = '';
      if (this._events.length === 0) {
        const li = document.createElement('li');
        li.className = 'cs-hud__event-item cs-hud__event-item--placeholder';
        li.textContent = 'No events yet.';
        list.appendChild(li);
        return;
      }

      // Newest first, max 20 in the visible list
      const recent = [...this._events].reverse().slice(0, 20);
      recent.forEach(ev => {
        const li  = document.createElement('li');
        li.className = 'cs-hud__event-item';

        const tsStr = new Date(ev.ts).toLocaleTimeString('en-GB', {
          hour: '2-digit', minute: '2-digit',
        });

        li.innerHTML = `
          <span class="cs-hud__event-ts">${tsStr}</span>
          <span class="cs-hud__event-title">${_esc(ev.title)}</span>
          ${ev.scene ? `<span class="cs-hud__event-scene">${_esc(ev.scene.toUpperCase())}</span>` : ''}
        `;
        list.appendChild(li);
      });
    }

    // ── Event history ────────────────────────────────────────────────────

    _addEventToHistory (ev, render = true) {
      // Dedup: don't add if same title within 5 seconds
      const recent = this._events.slice(-5);
      const isDupe = recent.some(
        r => r.title === ev.title && Math.abs(r.ts - ev.ts) < 5000
      );
      if (isDupe) return;

      this._events.push(ev);
      if (this._events.length > MAX_EVENTS) this._events.shift();

      if (render && this._expanded) this._renderEventList();
    }

    // ── Ticker ───────────────────────────────────────────────────────────

    _flashTicker (text) {
      const el = this._els.ticker;
      if (!el) return;

      // Pause scroll, show new text, flash, restart
      el.textContent = '⚡ ' + text;
      el.classList.remove('cs-hud__ticker--flash');
      // Force reflow
      void el.offsetWidth;
      el.classList.add('cs-hud__ticker--flash');

      setTimeout(() => {
        el.classList.remove('cs-hud__ticker--flash');
      }, 700);
    }

    // ── Credits animation ────────────────────────────────────────────────

    _animateCredits (isGain) {
      const el = this._els.credits;
      if (!el) return;
      const cls = isGain ? 'cs-hud__credits--gain' : 'cs-hud__credits--spend';
      el.classList.remove('cs-hud__credits--gain', 'cs-hud__credits--spend');
      void el.offsetWidth;
      el.classList.add(cls);
      setTimeout(() => el.classList.remove(cls), 700);
    }

    // ── Floating credit change text ──────────────────────────────────────

    _showCreditChange (delta) {
      const el = document.getElementById('hud-credits');
      if (!el || !delta) return;
      // Flash class
      el.classList.add(delta > 0 ? 'cs-hud__credits--gain' : 'cs-hud__credits--spend');
      setTimeout(() => el.classList.remove('cs-hud__credits--gain', 'cs-hud__credits--spend'), 700);
      // Floating text
      const float = document.createElement('span');
      float.className = 'cs-hud__credit-float';
      float.textContent = (delta > 0 ? '+' : '') + delta.toLocaleString();
      float.style.color = delta > 0 ? '#22c55e' : '#f43f5e';
      const rect = el.getBoundingClientRect();
      float.style.cssText += `position:fixed;left:${rect.left}px;top:${rect.top - 4}px;font-size:11px;font-weight:700;pointer-events:none;z-index:999;animation:cs-float-up 1.2s ease-out forwards;`;
      document.body.appendChild(float);
      setTimeout(() => float.remove(), 1200);
    }

    // ── Level-up celebration banner ───────────────────────────────────────

    _showLevelUp (level) {
      const banner = document.createElement('div');
      banner.className = 'cs-hud-levelup';
      banner.innerHTML = `<span>LEVEL UP!</span> <strong>Level ${level}</strong>`;
      document.body.appendChild(banner);
      setTimeout(() => banner.remove(), 2500);
    }

    // ── Panel ────────────────────────────────────────────────────────────

    _togglePanel () {
      if (this._expanded) this._closePanel();
      else                this._openPanel();
    }

    _openPanel () {
      this._expanded = true;
      const { panel, backdrop } = this._els;
      if (panel)    { panel.classList.add('cs-hud__panel--visible');       panel.setAttribute('aria-hidden', 'false'); }
      if (backdrop) { backdrop.classList.add('cs-hud__backdrop--visible'); backdrop.setAttribute('aria-hidden', 'false'); }
      this._renderEventList();
      // Refresh state
      this._poll();
    }

    _closePanel () {
      this._expanded = false;
      const { panel, backdrop } = this._els;
      if (panel)    { panel.classList.remove('cs-hud__panel--visible');       panel.setAttribute('aria-hidden', 'true'); }
      if (backdrop) {
        backdrop.classList.remove('cs-hud__backdrop--visible');
        backdrop.setAttribute('aria-hidden', 'true');
      }
    }

    // ── Left Panel ───────────────────────────────────────────────────────

    _toggleLeftPanel () {
      if (this._leftOpen) this._closeLeftPanel();
      else                this._openLeftPanel();
    }

    _openLeftPanel () {
      this._leftOpen = true;
      const el  = document.getElementById('cs-hud-left-panel');
      const btn = document.getElementById('hud-toggle-left');
      const bd  = this._els.backdrop;
      if (el)  el.setAttribute('aria-hidden', 'false');
      if (btn) btn.classList.add('cs-hud__toggle--active');
      if (bd)  { bd.classList.add('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'false'); }
      if (this._rightOpen) this._closeRightPanel();
      this._poll();
    }

    _closeLeftPanel () {
      this._leftOpen = false;
      const el  = document.getElementById('cs-hud-left-panel');
      const btn = document.getElementById('hud-toggle-left');
      const bd  = this._els.backdrop;
      if (el)  el.setAttribute('aria-hidden', 'true');
      if (btn) btn.classList.remove('cs-hud__toggle--active');
      if (!this._rightOpen && !this._expanded) {
        if (bd) { bd.classList.remove('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'true'); }
      }
    }

    // ── Right Panel ──────────────────────────────────────────────────────

    _toggleRightPanel () {
      if (this._rightOpen) this._closeRightPanel();
      else                 this._openRightPanel();
    }

    _openRightPanel () {
      this._rightOpen = true;
      const el  = document.getElementById('cs-hud-right-panel');
      const btn = document.getElementById('hud-toggle-right');
      const bd  = this._els.backdrop;
      if (el)  el.setAttribute('aria-hidden', 'false');
      if (btn) btn.classList.add('cs-hud__toggle--active');
      if (bd)  { bd.classList.add('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'false'); }
      if (this._leftOpen) this._closeLeftPanel();
      this._pollServiceStatus();
    }

    _closeRightPanel () {
      this._rightOpen = false;
      const el  = document.getElementById('cs-hud-right-panel');
      const btn = document.getElementById('hud-toggle-right');
      const bd  = this._els.backdrop;
      if (el)  el.setAttribute('aria-hidden', 'true');
      if (btn) btn.classList.remove('cs-hud__toggle--active');
      if (!this._leftOpen && !this._expanded) {
        if (bd) { bd.classList.remove('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'true'); }
      }
    }

    // ── Phone Overlay ────────────────────────────────────────────────────

    _togglePhoneOverlay () {
      if (this._phoneOpen) this._closePhoneOverlay();
      else                 this._openPhoneOverlay();
    }

    _openPhoneOverlay () {
      this._phoneOpen = true;
      const overlay  = document.getElementById('cs-phone-overlay');
      const frame    = document.getElementById('cs-phone-frame');
      const phoneDot = document.querySelector('.cs-hud__phone-dot');
      const btn      = document.getElementById('hud-toggle-phone');
      // Lazy-load iframe — only set src once to preserve state across toggles
      if (frame && (!frame.src || frame.src === '' || frame.src === 'about:blank')) {
        frame.src = window.COSYSIM?.services?.phone || 'http://localhost:5555';
      }
      if (overlay) {
        overlay.setAttribute('aria-hidden', 'false');
        overlay.classList.add('open');  // v1.43.0 — phone-panel.css uses .open class
        overlay.classList.toggle('cs-phone-overlay--edge', !this._rightOpen);
      }
      if (phoneDot) phoneDot.classList.add('cs-hud__phone-dot--active');
      if (btn) btn.classList.add('cs-hud__toggle--active');
    }

    _closePhoneOverlay () {
      this._phoneOpen = false;
      const overlay  = document.getElementById('cs-phone-overlay');
      const phoneDot = document.querySelector('.cs-hud__phone-dot');
      const btn      = document.getElementById('hud-toggle-phone');
      // Hide overlay but keep iframe loaded to preserve phone state + badge
      if (overlay) {
        overlay.setAttribute('aria-hidden', 'true');
        overlay.classList.remove('open');  // v1.43.0 — phone-panel.css .open class
      }
      if (phoneDot) phoneDot.classList.remove('cs-hud__phone-dot--active');
      if (btn) btn.classList.remove('cs-hud__toggle--active');
    }

    // ── Service status ────────────────────────────────────────────────────

    // v1.43.0 — Proxy service checks through local backend (avoids CORS/auth issues)
    async _pollServiceStatus () {
      const checks = [
        // Use local scene endpoints that proxy or don't need cross-origin auth
        { id: 'sys-nexus',    url: '/api/hud/state' },  // local, always works
        { id: 'sys-tts',      url: (window.COSYSIM?.services?.tts || 'http://localhost:8600') + '/health' },
        { id: 'sys-comfy',    url: (window.COSYSIM?.services?.comfyui || 'http://localhost:8188') + '/history' },
      ];
      // LMStudio check: use local /api/hud/state response (already polled)
      const lmsDot = document.getElementById('sys-lmstudio');
      if (lmsDot && this._state) {
        // If we got a valid HUD state, LMStudio was reachable (agents use it)
        lmsDot.classList.add('cs-hud-slide__sys-dot--online');
        lmsDot.classList.remove('cs-hud-slide__sys-dot--offline');
      }
      // Nexus check: use the HUD state response existence
      const nexusDot = document.getElementById('sys-nexus');
      if (nexusDot && this._state) {
        nexusDot.classList.add('cs-hud-slide__sys-dot--online');
        nexusDot.classList.remove('cs-hud-slide__sys-dot--offline');
      }
      // TTS and ComfyUI: direct check (same-origin not required, no auth)
      for (const { id, url } of checks.slice(1)) {
        const dot = document.getElementById(id);
        if (!dot) continue;
        try {
          const ctrl = new AbortController();
          const tid  = setTimeout(() => ctrl.abort(), 2000);
          const res  = await fetch(url, { method: 'GET', cache: 'no-store', signal: ctrl.signal });
          clearTimeout(tid);
          dot.classList.toggle('cs-hud-slide__sys-dot--online',  res.ok);
          dot.classList.toggle('cs-hud-slide__sys-dot--offline', !res.ok);
        } catch {
          dot.classList.remove('cs-hud-slide__sys-dot--online');
          dot.classList.add('cs-hud-slide__sys-dot--offline');
        }
      }
    }

    // ── Nexus quick search ────────────────────────────────────────────────

    async _nexusSearch (query) {
      if (!query) return;
      const el = document.getElementById('hud-nexus-results');
      if (!el) return;
      el.innerHTML = '<div class="cs-hud-slide__search-result" style="opacity:0.4">Searching…</div>';
      try {
        const res  = await fetch(`/api/nexus/search?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        const items = (data.results || []).slice(0, 5);
        if (!items.length) {
          el.innerHTML = '<div class="cs-hud-slide__search-result" style="opacity:0.4">No results.</div>';
          return;
        }
        el.innerHTML = items.map(r =>
          `<div class="cs-hud-slide__search-result" title="${_esc(r.content || '')}"><strong>${_esc(r.title || 'Result')}</strong></div>`
        ).join('');
      } catch {
        el.innerHTML = '<div class="cs-hud-slide__search-result" style="color:#f87171">Search unavailable.</div>';
      }
    }

    // ── Left panel rendering ──────────────────────────────────────────────

    _renderLeftPanel (state) {
      if (!state) return;
      const cStr = Number(state.credits || 0).toLocaleString();
      _setText('left-credits', '₵ ' + cStr);
      _setText('left-rep', (state.reputation ?? 50) + '/100');
      _setText('left-heat', (state.heat ?? 0) + '%');
      if (state.health  !== undefined) { _setBar('left-health-bar',  state.health);  _setText('left-health-val',  state.health);  }
      if (state.hunger  !== undefined) { _setBar('left-hunger-bar',  state.hunger);  _setText('left-hunger-val',  state.hunger);  }
      if (state.energy  !== undefined) { _setBar('left-energy-bar',  state.energy);  _setText('left-energy-val',  state.energy);  }
      if (state.inventory) this._renderInventory(state.inventory);
      if (state.skills)    this._renderSkills(state.skills);
      if (state.faction_standings) this._renderFactions(state.faction_standings);
    }

    // v1.43.0 [2026-03-21] — Interactive inventory with item action popup
    _renderInventory (items) {
      const grid = document.getElementById('left-inventory');
      const cntEl = document.getElementById('left-inv-count');
      if (!grid) return;
      const slots = grid.querySelectorAll('.cs-hud-slide__inv-slot');
      // Clear all slots first
      slots.forEach(s => {
        s.textContent = '';
        s.title = '';
        s.classList.remove('cs-hud-slide__inv-slot--occupied');
        s.removeAttribute('data-item-id');
        s.onclick = null;
      });
      items.slice(0, slots.length).forEach((item, i) => {
        slots[i].textContent = item.icon || '📦';
        slots[i].title       = `${item.name || 'Item'} (${item.rarity || 'common'}) x${item.qty || 1}`;
        slots[i].classList.add('cs-hud-slide__inv-slot--occupied');
        slots[i].dataset.itemId = item.id;
        slots[i].dataset.rarity = item.rarity || 'common';
        slots[i].onclick = () => this._showItemPopup(item, slots[i]);
      });
      if (cntEl) cntEl.textContent = `${items.length}/${slots.length}`;
    }

    /** Show item action popup anchored to a slot element. */
    _showItemPopup (item, anchorEl) {
      this._closePopup();
      const popup = document.createElement('div');
      popup.className = 'cs-hud-popup cs-hud-popup--item';
      popup.innerHTML = `
        <button class="cs-hud-popup__close" data-action="close">✕</button>
        <div class="cs-hud-popup__header">
          <span class="cs-hud-popup__icon">${item.icon || '📦'}</span>
          <span class="cs-hud-popup__title">${_esc(item.name)}</span>
          <span class="cs-hud-popup__rarity cs-hud-popup__rarity--${item.rarity || 'common'}">${_esc(item.rarity || 'common')}</span>
        </div>
        <div class="cs-hud-popup__qty">Qty: ${item.qty || 1}</div>
        <div class="cs-hud-popup__actions">
          ${item.equipped
            ? '<button class="cs-hud-popup__btn cs-hud-popup__btn--secondary" data-action="unequip">Unequip</button>'
            : '<button class="cs-hud-popup__btn cs-hud-popup__btn--primary" data-action="equip">Equip</button>'
          }
          <button class="cs-hud-popup__btn cs-hud-popup__btn--danger" data-action="drop">Drop</button>
        </div>`;
      // Position: centered in viewport, above everything
      popup.style.position = 'fixed';
      popup.style.top = '50%';
      popup.style.left = '50%';
      popup.style.transform = 'translate(-50%, -50%)';
      popup.style.zIndex = '400';
      document.body.appendChild(popup);
      this._activePopup = popup;

      popup.addEventListener('click', async (e) => {
        const action = e.target.dataset?.action || e.target.closest('[data-action]')?.dataset?.action;
        if (!action) return;
        if (action === 'close') { this._closePopup(); return; }
        try {
          if (action === 'equip') {
            await fetch('/api/inventory/equip', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ item_id: item.id, slot: 'auto' }),
            });
          } else if (action === 'unequip') {
            await fetch('/api/inventory/unequip', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ item_id: item.id }),
            });
          } else if (action === 'drop') {
            await fetch('/api/inventory/remove', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ item_id: item.id, quantity: 1 }),
            });
          }
          this._closePopup();
          this._poll();  // Refresh state
        } catch (err) {
          console.error('[HUD] Item action failed:', err);
        }
      });
    }

    _renderSkills (skills) {
      const list = document.getElementById('left-skills');
      if (!list) return;
      list.innerHTML = Object.entries(skills).slice(0, 6).map(([name, level]) => {
        const pips = Array.from({ length: 5 }, (_, i) =>
          `<span class="pip ${i < level ? 'pip--active' : ''}"></span>`).join('');
        return `<div class="cs-hud-slide__skill-row">
          <span class="cs-hud-slide__skill-name">${_esc(name)}</span>
          <div class="cs-hud-slide__skill-pips">${pips}</div>
        </div>`;
      }).join('');
    }

    // ── Right panel rendering ─────────────────────────────────────────────

    _renderRightPanel (state) {
      if (!state) return;
      if (state.crew)     this._renderCrew(state.crew);
      if (state.missions) this._renderMissions(state.missions);
    }

    // v1.43.0 [2026-03-21] — Interactive crew rows with detail popup
    _renderCrew (crew) {
      const list = document.getElementById('hud-crew-list');
      if (!list) return;
      if (!crew || crew.length === 0) {
        list.innerHTML = '<div class="cs-hud-slide__crew-empty">No crew yet. Build relationships to recruit.</div>';
        return;
      }
      const TIER_ICONS  = { fixer: '🔧', hacker: '💻', muscle: '💪', thief: '🗡️', tech: '⚙️', medic: '🩺', driver: '🏎️', lookout: '👁️', face: '🎭', supplier: '📦' };
      const LOYALTY_COLOR = (l) => l >= 80 ? '#00e5ff' : l >= 60 ? '#22c55e' : l >= 40 ? '#f97316' : '#f43f5e';
      list.innerHTML = crew.map(m => {
        const roleIcon  = m.role_icon || TIER_ICONS[m.role] || '👤';
        const loyalty   = Math.max(0, Math.min(100, m.loyalty ?? 50));
        const loyaltyClr = LOYALTY_COLOR(loyalty);
        const tier      = loyalty >= 80 ? '★★★' : loyalty >= 60 ? '★★' : loyalty >= 40 ? '★' : '·';
        const available = m.available ? '' : ' cs-hud-slide__crew-row--busy';
        return `<div class="cs-hud-slide__crew-row${available}" data-crew-id="${_esc(m.id)}" title="${_esc(m.id)} — ${m.role || '?'} (Loyalty ${loyalty})">
          <span class="cs-hud-slide__crew-icon">${roleIcon}</span>
          <span class="cs-hud-slide__crew-name">${_esc(m.id)}</span>
          <span class="cs-hud-slide__crew-role">${_esc(m.role || '?')}</span>
          <div class="cs-hud-slide__crew-loyalty-bar">
            <div class="cs-hud-slide__crew-loyalty-fill" style="width:${loyalty}%;background:${loyaltyClr}"></div>
          </div>
          <span class="cs-hud-slide__crew-tier" style="color:${loyaltyClr}">${tier}</span>
        </div>`;
      }).join('');

      // Attach click handlers for crew detail popup
      list.querySelectorAll('.cs-hud-slide__crew-row').forEach(row => {
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => {
          const crewId = row.dataset.crewId;
          const member = crew.find(m => m.id === crewId);
          if (member) this._showCrewPopup(member, row);
        });
      });
    }

    /** Show crew member detail popup anchored to a row element. */
    _showCrewPopup (member, anchorEl) {
      this._closePopup();
      const loyalty = Math.max(0, Math.min(100, member.loyalty ?? 50));
      const LOYALTY_COLOR = (l) => l >= 80 ? '#00e5ff' : l >= 60 ? '#22c55e' : l >= 40 ? '#f97316' : '#f43f5e';
      const popup = document.createElement('div');
      popup.className = 'cs-hud-popup cs-hud-popup--crew';
      popup.innerHTML = `
        <button class="cs-hud-popup__close" data-action="close">✕</button>
        <div class="cs-hud-popup__header">
          <span class="cs-hud-popup__icon">${member.role_icon || '👤'}</span>
          <span class="cs-hud-popup__title">${_esc(member.id)}</span>
        </div>
        <div class="cs-hud-popup__detail">
          <div>Role: <strong>${_esc(member.role || '?')}</strong></div>
          <div>Level: <strong>${member.level || 1}</strong></div>
          <div>Loyalty: <strong style="color:${LOYALTY_COLOR(loyalty)}">${loyalty}%</strong></div>
          <div>Status: ${member.available ? '<span style="color:#22c55e">Available</span>' : '<span style="color:#f97316">On Assignment</span>'}</div>
        </div>
        <div class="cs-hud-popup__actions">
          <button class="cs-hud-popup__btn cs-hud-popup__btn--danger" data-action="dismiss">Dismiss</button>
        </div>`;
      popup.style.position = 'fixed';
      popup.style.top = '50%';
      popup.style.left = '50%';
      popup.style.transform = 'translate(-50%, -50%)';
      popup.style.zIndex = '400';
      document.body.appendChild(popup);
      this._activePopup = popup;

      popup.addEventListener('click', async (e) => {
        const action = e.target.dataset?.action || e.target.closest('[data-action]')?.dataset?.action;
        if (!action) return;
        if (action === 'close') { this._closePopup(); return; }
        if (action === 'dismiss') {
          if (!confirm(`Dismiss ${member.id} from crew?`)) return;
          try {
            await fetch('/api/crew/dismiss', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ character_id: member.id }),
            });
            this._closePopup();
            this._poll();
          } catch (err) {
            console.error('[HUD] Crew dismiss failed:', err);
          }
        }
      });
    }

    /** Close any active popup. */
    _closePopup () {
      if (this._activePopup) {
        this._activePopup.remove();
        this._activePopup = null;
      }
    }

    // v1.43.0 [2026-03-21] — Mission rendering for right panel
    _renderMissions (missions) {
      const list = document.getElementById('hud-mission-list');
      const countEl = document.getElementById('hud-mission-count');
      if (!list) return;
      if (countEl) countEl.textContent = missions.length;

      if (!missions || missions.length === 0) {
        list.innerHTML = '<div class="cs-hud-slide__mission-empty">No active missions.</div>';
        return;
      }
      list.innerHTML = missions.map(m => {
        const stars = '★'.repeat(m.difficulty || 1) + '☆'.repeat(5 - (m.difficulty || 1));
        const pct = m.progress?.pct || 0;
        return `<div class="cs-hud-slide__mission-row" data-mission-id="${_esc(m.id)}">
          <div class="cs-hud-slide__mission-header">
            <span class="cs-hud-slide__mission-title">${_esc(m.title)}</span>
            <span class="cs-hud-slide__mission-diff" title="Difficulty">${stars}</span>
          </div>
          <div class="cs-hud-slide__mission-bar">
            <div class="cs-hud-slide__mission-fill" style="width:${pct}%"></div>
          </div>
          <div class="cs-hud-slide__mission-objectives">
            ${(m.objectives || []).map(obj => `
              <label class="cs-hud-slide__mission-obj ${obj.completed ? 'cs-hud-slide__mission-obj--done' : ''}"
                     data-obj-id="${_esc(obj.id)}" data-mission-id="${_esc(m.id)}">
                <input type="checkbox" ${obj.completed ? 'checked disabled' : ''}>
                ${_esc(obj.description)}${obj.optional ? ' <em>(optional)</em>' : ''}
              </label>
            `).join('')}
          </div>
          <div class="cs-hud-slide__mission-reward">
            Reward: ₵${m.reward?.credits || 0} · ${m.reward?.xp || 0} XP
          </div>
          <button class="cs-hud-popup__btn cs-hud-popup__btn--danger cs-hud-slide__mission-abandon"
                  data-abandon="${_esc(m.id)}">Abandon</button>
        </div>`;
      }).join('');

      // Wire objective checkboxes and abandon buttons
      list.querySelectorAll('.cs-hud-slide__mission-obj input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', async () => {
          const label = cb.closest('.cs-hud-slide__mission-obj');
          const missionId = label.dataset.missionId;
          const objId = label.dataset.objId;
          try {
            await fetch('/api/mission/objective', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ mission_id: missionId, objective_id: objId }),
            });
            cb.disabled = true;
            label.classList.add('cs-hud-slide__mission-obj--done');
            this._poll();
          } catch (err) { console.error('[HUD] Objective update failed:', err); }
        });
      });
      list.querySelectorAll('.cs-hud-slide__mission-abandon').forEach(btn => {
        btn.addEventListener('click', async () => {
          const missionId = btn.dataset.abandon;
          if (!confirm('Abandon this mission?')) return;
          try {
            await fetch('/api/mission/abandon', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ mission_id: missionId }),
            });
            this._poll();
          } catch (err) { console.error('[HUD] Mission abandon failed:', err); }
        });
      });
    }

    // v1.43.0 [2026-03-21] — Faction reputation bars for left panel
    _renderFactions (factionStandings) {
      const container = document.getElementById('left-factions');
      if (!container || !factionStandings) return;
      container.innerHTML = Object.entries(factionStandings).map(([name, standing]) => {
        const color = FACTION_COLORS[name] || '#94a3b8';
        const pct = Math.abs(standing);
        const dir = standing >= 0 ? 'right' : 'left';
        return `<div class="cs-hud-slide__faction-row">
          <span class="cs-hud-slide__faction-name" style="color:${color}">${_esc(name)}</span>
          <div class="cs-hud-slide__faction-bar">
            <div class="cs-hud-slide__faction-center"></div>
            <div class="cs-hud-slide__faction-fill cs-hud-slide__faction-fill--${dir}"
                 style="width:${pct / 2}%;background:${color}"></div>
          </div>
          <span class="cs-hud-slide__faction-val" style="color:${color}">${standing > 0 ? '+' : ''}${standing}</span>
        </div>`;
      }).join('');
    }

    // ── Mission Board Overlay ──────────────────────────────────────────────

    _toggleMissionBoard () {
      if (this._missionBoardOpen) this._closeMissionBoard();
      else                        this._openMissionBoard();
    }

    async _openMissionBoard () {
      this._missionBoardOpen = true;
      const overlay = document.getElementById('cs-mission-board');
      const bd = this._els.backdrop;
      if (overlay) {
        overlay.setAttribute('aria-hidden', 'false');
        overlay.style.display = '';
      }
      if (bd) { bd.classList.add('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'false'); }

      // Close other overlays
      if (this._shopOpen) this._closeShop();
      if (this._leftOpen) this._closeLeftPanel();
      if (this._rightOpen) this._closeRightPanel();

      // Wire tab switching
      const tabs = overlay?.querySelectorAll('.cs-mission__tab');
      if (tabs) {
        tabs.forEach(tab => {
          tab.onclick = () => {
            tabs.forEach(t => t.classList.remove('cs-mission__tab--active'));
            tab.classList.add('cs-mission__tab--active');
            const tabName = tab.dataset.tab;
            ['available', 'active', 'completed'].forEach(t => {
              const el = document.getElementById(`mission-tab-${t}`);
              if (el) el.classList.toggle('cs-mission__content--hidden', t !== tabName);
            });
          };
        });
      }

      // Wire close button
      const closeBtn = document.getElementById('mission-board-close');
      if (closeBtn) closeBtn.onclick = () => this._closeMissionBoard();

      // Fetch mission board data
      try {
        const res = await fetch('/api/mission/board', { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        this._renderMissionBoardTab('available', data.available || []);
        this._renderMissionBoardTab('active', data.active || []);
        this._renderMissionBoardTab('completed', data.completed || []);
      } catch (err) {
        console.debug('[HUD] Mission board fetch failed:', err.message);
      }
    }

    _closeMissionBoard () {
      this._missionBoardOpen = false;
      const overlay = document.getElementById('cs-mission-board');
      const bd = this._els.backdrop;
      if (overlay) {
        overlay.setAttribute('aria-hidden', 'true');
      }
      if (!this._shopOpen && !this._leftOpen && !this._rightOpen && !this._expanded) {
        if (bd) { bd.classList.remove('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'true'); }
      }
    }

    _renderMissionBoardTab (tab, missions) {
      if (tab === 'available') {
        const grid = document.querySelector('#mission-tab-available .cs-mission__grid');
        const emptyEl = document.querySelector('#mission-tab-available .cs-mission__card--placeholder');
        if (!grid) return;
        grid.innerHTML = '';
        if (!missions.length) {
          grid.innerHTML = `<div class="cs-mission__card cs-mission__card--placeholder">
            <div class="cs-mission__card-header"><span class="cs-mission__card-title">No missions available</span></div>
            <p class="cs-mission__card-empty">Check back later — the city never sleeps.</p>
          </div>`;
          return;
        }
        missions.forEach(m => {
          const stars = '\u2605'.repeat(m.difficulty || 1) + '\u2606'.repeat(5 - (m.difficulty || 1));
          const typeClass = m.type ? `cs-mission__card-type--${m.type}` : '';
          const card = document.createElement('div');
          card.className = 'cs-mission__card';
          card.innerHTML = `
            <div class="cs-mission__card-header">
              <span class="cs-mission__card-title">${_esc(m.title)}</span>
              <span class="cs-mission__card-difficulty">${stars}</span>
            </div>
            ${m.type ? `<span class="cs-mission__card-type ${typeClass}">${_esc(m.type)}</span>` : ''}
            ${m.description ? `<p style="font-size:11px;color:rgba(255,255,255,0.5);margin:0">${_esc(m.description)}</p>` : ''}
            <div class="cs-mission__card-reward">
              Reward: <strong>\u20B5${(m.reward?.credits || 0).toLocaleString()}</strong> · ${m.reward?.xp || 0} XP
              ${m.reward?.rep ? ` · +${m.reward.rep} REP` : ''}
            </div>
            <div class="cs-mission__card-meta">
              ${m.faction ? `<span>${_esc(m.faction)}</span>` : ''}
              ${m.time_limit ? `<span>${m.time_limit}</span>` : ''}
              ${m.crew_required ? `<span>Crew: ${m.crew_required}</span>` : ''}
            </div>
            <button class="cs-mission__card-accept" data-mission-id="${_esc(m.id)}">ACCEPT</button>`;
          grid.appendChild(card);

          // Wire accept button
          const acceptBtn = card.querySelector('.cs-mission__card-accept');
          if (acceptBtn) {
            acceptBtn.addEventListener('click', async () => {
              try {
                const res = await fetch('/api/mission/accept', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ mission_id: m.id }),
                });
                if (res.ok) {
                  acceptBtn.textContent = 'ACCEPTED';
                  acceptBtn.disabled = true;
                  acceptBtn.style.opacity = '0.5';
                  // Refresh board after a short delay
                  setTimeout(() => this._openMissionBoard(), 500);
                }
              } catch (err) { console.error('[HUD] Mission accept failed:', err); }
            });
          }
        });

      } else if (tab === 'active') {
        const list = document.querySelector('#mission-tab-active .cs-mission__list');
        if (!list) return;
        list.innerHTML = '';
        if (!missions.length) {
          list.innerHTML = '<div class="cs-mission__active-empty">No active missions. Pick one from the board.</div>';
          return;
        }
        missions.forEach(m => {
          const pct = m.progress?.pct || 0;
          const item = document.createElement('div');
          item.className = 'cs-mission__active-item';
          item.innerHTML = `
            <div class="cs-mission__active-header">
              <span class="cs-mission__active-title">${_esc(m.title)}</span>
              <span style="color:#f59e0b;font-size:10px">${'\u2605'.repeat(m.difficulty || 1)}</span>
            </div>
            <div class="cs-mission__progress">
              <div class="cs-mission__progress-fill" style="width:${pct}%"></div>
            </div>
            <div class="cs-mission__progress-label">${pct}% complete</div>
            <ul class="cs-mission__objectives">
              ${(m.objectives || []).map(obj => `
                <li class="cs-mission__objective ${obj.completed ? 'cs-mission__objective--done' : ''}">
                  <input type="checkbox" ${obj.completed ? 'checked disabled' : ''} readonly>
                  ${_esc(obj.description)}${obj.optional ? ' <em>(opt)</em>' : ''}
                </li>
              `).join('')}
            </ul>
            ${m.assigned_crew?.length ? `
              <div class="cs-mission__crew">
                ${m.assigned_crew.map(c => `<span class="cs-mission__crew-badge">${_esc(c)}</span>`).join('')}
              </div>` : ''}
            <div style="font-size:10px;color:#f59e0b">
              Reward: \u20B5${(m.reward?.credits || 0).toLocaleString()} · ${m.reward?.xp || 0} XP
            </div>
            <button class="cs-mission__abandon" data-mission-id="${_esc(m.id)}">ABANDON</button>`;
          list.appendChild(item);

          // Wire abandon button
          const abandonBtn = item.querySelector('.cs-mission__abandon');
          if (abandonBtn) {
            abandonBtn.addEventListener('click', async () => {
              if (!confirm(`Abandon mission: ${m.title}?`)) return;
              try {
                await fetch('/api/mission/abandon', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ mission_id: m.id }),
                });
                setTimeout(() => this._openMissionBoard(), 300);
                this._poll();
              } catch (err) { console.error('[HUD] Mission abandon failed:', err); }
            });
          }
        });

      } else if (tab === 'completed') {
        const list = document.querySelector('#mission-tab-completed .cs-mission__list--completed');
        if (!list) return;
        list.innerHTML = '';
        if (!missions.length) {
          list.innerHTML = '<div class="cs-mission__completed-empty">No completed missions yet.</div>';
          return;
        }
        missions.forEach(m => {
          const item = document.createElement('div');
          item.className = 'cs-mission__completed-item';
          const ts = m.completed_at ? new Date(m.completed_at * 1000).toLocaleDateString('en-GB', {
            day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
          }) : '';
          item.innerHTML = `
            <span class="cs-mission__completed-title">${_esc(m.title)}</span>
            <span class="cs-mission__completed-reward">\u20B5${(m.reward?.credits || 0).toLocaleString()}</span>
            <span class="cs-mission__completed-time">${ts}</span>`;
          list.appendChild(item);
        });
      }
    }

    // ── Shop Overlay ───────────────────────────────────────────────────────

    _toggleShop () {
      if (this._shopOpen) this._closeShop();
      else                this._openShop();
    }

    async _openShop () {
      this._shopOpen = true;
      const overlay = document.getElementById('cs-shop-overlay');
      const bd = this._els.backdrop;
      if (overlay) {
        overlay.setAttribute('aria-hidden', 'false');
        overlay.style.display = '';
      }
      if (bd) { bd.classList.add('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'false'); }

      // Close other overlays
      if (this._missionBoardOpen) this._closeMissionBoard();
      if (this._leftOpen) this._closeLeftPanel();
      if (this._rightOpen) this._closeRightPanel();

      // Wire tab switching
      const tabs = overlay?.querySelectorAll('.cs-shop__tab');
      if (tabs) {
        tabs.forEach(tab => {
          tab.onclick = () => {
            tabs.forEach(t => t.classList.remove('cs-shop__tab--active'));
            tab.classList.add('cs-shop__tab--active');
            const tabName = tab.dataset.shopTab;
            const buyPanel  = document.getElementById('shop-tab-buy');
            const sellPanel = document.getElementById('shop-tab-sell');
            if (buyPanel)  buyPanel.classList.toggle('cs-shop__content--hidden', tabName !== 'buy');
            if (sellPanel) sellPanel.classList.toggle('cs-shop__content--hidden', tabName !== 'sell');
          };
        });
      }

      // Wire close button
      const closeBtn = document.getElementById('shop-close');
      if (closeBtn) closeBtn.onclick = () => this._closeShop();

      // Fetch shop catalog and inventory in parallel
      try {
        const [catalogRes, invRes] = await Promise.all([
          fetch('/api/shop/catalog', { cache: 'no-store' }),
          fetch('/api/inventory', { cache: 'no-store' }),
        ]);
        const catalog = catalogRes.ok ? await catalogRes.json() : {};
        const inv     = invRes.ok ? await invRes.json() : {};
        const balance = catalog.balance ?? inv.credits ?? this._state?.credits ?? 0;

        // Update balance display
        const balEl = document.getElementById('shop-balance');
        if (balEl) balEl.textContent = Number(balance).toLocaleString();

        this._renderShopBuy(catalog.items || [], balance);
        this._renderShopSell(inv.items || inv.inventory || []);
      } catch (err) {
        console.debug('[HUD] Shop fetch failed:', err.message);
      }
    }

    _closeShop () {
      this._shopOpen = false;
      const overlay = document.getElementById('cs-shop-overlay');
      const bd = this._els.backdrop;
      if (overlay) {
        overlay.setAttribute('aria-hidden', 'true');
      }
      if (!this._missionBoardOpen && !this._leftOpen && !this._rightOpen && !this._expanded) {
        if (bd) { bd.classList.remove('cs-hud__backdrop--visible'); bd.setAttribute('aria-hidden', 'true'); }
      }
    }

    _renderShopBuy (items, balance) {
      const grid  = document.querySelector('#shop-tab-buy .cs-shop__grid');
      const empty = document.getElementById('shop-buy-empty');
      if (!grid) return;
      grid.innerHTML = '';

      if (!items.length) {
        if (empty) empty.style.display = '';
        return;
      }
      if (empty) empty.style.display = 'none';

      items.forEach(item => {
        const price = item.price || 0;
        const canAfford = balance >= price;
        const rarityClass = item.rarity ? `cs-shop__item-rarity--${item.rarity}` : '';
        const lockedClass = !canAfford ? ' cs-shop__item--locked' : '';
        const el = document.createElement('div');
        el.className = `cs-shop__item${lockedClass}`;
        el.dataset.itemId = item.id;
        el.innerHTML = `
          <span class="cs-shop__item-icon">${item.icon || '\uD83D\uDCE6'}</span>
          <div class="cs-shop__item-info">
            <span class="cs-shop__item-name">${_esc(item.name)}</span>
            <span class="cs-shop__item-meta">
              <span class="cs-shop__item-price">\u20B5 ${Number(price).toLocaleString()}</span>
              ${item.rarity ? `<span class="cs-shop__item-rarity ${rarityClass}">${_esc(item.rarity.toUpperCase())}</span>` : ''}
              ${item.category ? `<span class="cs-shop__item-category">${_esc(item.category.toUpperCase())}</span>` : ''}
            </span>
          </div>
          <button class="cs-shop__buy-btn" data-item-id="${_esc(item.id)}" type="button"
                  ${!canAfford ? 'disabled' : ''}>BUY</button>`;
        grid.appendChild(el);

        // Wire buy button
        const buyBtn = el.querySelector('.cs-shop__buy-btn');
        if (buyBtn && canAfford) {
          buyBtn.addEventListener('click', async () => {
            try {
              const res = await fetch('/api/shop/buy', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: item.id, quantity: 1 }),
              });
              if (res.ok) {
                const result = await res.json();
                buyBtn.textContent = '\u2713';
                buyBtn.disabled = true;
                // Update balance
                const balEl = document.getElementById('shop-balance');
                if (balEl && result.balance !== undefined) {
                  balEl.textContent = Number(result.balance).toLocaleString();
                }
                // Refresh after brief feedback
                setTimeout(() => this._openShop(), 600);
                this._poll();
              } else {
                buyBtn.textContent = 'FAIL';
                setTimeout(() => { buyBtn.textContent = 'BUY'; }, 1500);
              }
            } catch (err) {
              console.error('[HUD] Shop buy failed:', err);
              buyBtn.textContent = 'ERR';
              setTimeout(() => { buyBtn.textContent = 'BUY'; }, 1500);
            }
          });
        }
      });
    }

    _renderShopSell (items) {
      const grid  = document.querySelector('#shop-tab-sell .cs-shop__grid');
      const empty = document.getElementById('shop-sell-empty');
      if (!grid) return;
      grid.innerHTML = '';

      if (!items.length) {
        if (empty) empty.style.display = '';
        return;
      }
      if (empty) empty.style.display = 'none';

      items.forEach(item => {
        const sellPrice = item.sell_price || Math.floor((item.price || 0) / 2);
        const el = document.createElement('div');
        el.className = 'cs-shop__item';
        el.dataset.itemId = item.id;
        el.innerHTML = `
          <span class="cs-shop__item-icon">${item.icon || '\uD83D\uDCE6'}</span>
          <div class="cs-shop__item-info">
            <span class="cs-shop__item-name">${_esc(item.name)}</span>
            <span class="cs-shop__item-meta">
              <span class="cs-shop__item-price">\u20B5 ${Number(sellPrice).toLocaleString()}</span>
              <span class="cs-shop__item-qty">x${item.qty || 1}</span>
            </span>
          </div>
          <button class="cs-shop__sell-btn" data-item-id="${_esc(item.id)}" type="button">SELL</button>`;
        grid.appendChild(el);

        // Wire sell button
        const sellBtn = el.querySelector('.cs-shop__sell-btn');
        if (sellBtn) {
          sellBtn.addEventListener('click', async () => {
            try {
              const res = await fetch('/api/shop/sell', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: item.id, quantity: 1 }),
              });
              if (res.ok) {
                const result = await res.json();
                sellBtn.textContent = '\u2713';
                sellBtn.disabled = true;
                const balEl = document.getElementById('shop-balance');
                if (balEl && result.balance !== undefined) {
                  balEl.textContent = Number(result.balance).toLocaleString();
                }
                setTimeout(() => this._openShop(), 600);
                this._poll();
              } else {
                sellBtn.textContent = 'FAIL';
                setTimeout(() => { sellBtn.textContent = 'SELL'; }, 1500);
              }
            } catch (err) {
              console.error('[HUD] Shop sell failed:', err);
              sellBtn.textContent = 'ERR';
              setTimeout(() => { sellBtn.textContent = 'SELL'; }, 1500);
            }
          });
        }
      });
    }
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  function _esc (str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _setText (id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(val);
  }

  function _setBar (id, pct) {
    const el = document.getElementById(id);
    if (el) el.style.width = Math.max(0, Math.min(100, pct)) + '%';
  }

  // ── Boot ─────────────────────────────────────────────────────────────────

  function _boot () {
    const hud = new NeonHUD();
    hud.init();
    window.NeonHUD = hud;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _boot);
  } else {
    _boot();
  }
})();
