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

      if (hud) {
        hud.addEventListener('click', e => {
          // Don't open panel on close button
          if (!e.target.closest('#hud-panel-close')) {
            this._togglePanel();
          }
        });
      }
      if (closeBtn) closeBtn.addEventListener('click', () => this._closePanel());
      if (backdrop) backdrop.addEventListener('click', () => this._closePanel());

      document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && this._expanded) this._closePanel();
      });
    }

    // ── Socket.IO ───────────────────────────────────────────────────────

    _connectSocket () {
      if (typeof io === 'undefined') return;
      try {
        const socket = io();
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
      if (backdrop) { backdrop.classList.remove('cs-hud__backdrop--visible'); backdrop.setAttribute('aria-hidden', 'true'); }
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
