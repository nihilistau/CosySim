/**
 * CosySim World Announcer — Street Radio / Faction News Feed
 * ===========================================================
 * A floating radio widget that delivers faction rumours, world events,
 * scene news, and NPC commentary to the player. Fetches from
 * /api/announcer/feed (served by BaseScene) or falls back to
 * world events from the HUD state.
 *
 * Exposed as window.CosyAnnouncer for external control.
 */

(function () {
  'use strict';

  // ── Constants ────────────────────────────────────────────────────────────

  const POLL_INTERVAL_MS    = 45_000;   // 45 s between feed refreshes
  const AUTO_ADVANCE_MS     = 12_000;   // 12 s per item when playing
  const COLLAPSED_CLASS     = 'cs-announcer--collapsed';
  const PINNED_CLASS        = 'cs-announcer--pinned';
  const VISIBLE_CLASS       = 'cs-announcer--visible';
  const FLASH_CLASS         = 'cs-announcer__led--flash';

  // Station display names and frequencies
  const STATIONS = [
    { name: 'NEON CITY RADIO', freq: '99.7 FM', color: '#00f5ff' },
    { name: 'GHOST NET UNDERGROUND', freq: '88.1 FM', color: '#bf00ff' },
    { name: 'OMNICORP INFOCHANNEL', freq: '104.3 FM', color: '#ff6600' },
    { name: 'STREET PULSE', freq: '92.5 FM', color: '#00ff88' },
    { name: 'DEEPSTATE DISPATCH', freq: '66.6 FM', color: '#ff0040' },
  ];

  // Badge styles per category
  const BADGE_MAP = {
    world:    { label: 'WORLD',   css: 'cs-announcer__badge--world'   },
    faction:  { label: 'FACTION', css: 'cs-announcer__badge--faction' },
    event:    { label: 'EVENT',   css: 'cs-announcer__badge--event'   },
    npc:      { label: 'INTEL',   css: 'cs-announcer__badge--npc'     },
    crime:    { label: 'CRIME',   css: 'cs-announcer__badge--crime'   },
    market:   { label: 'MARKET',  css: 'cs-announcer__badge--market'  },
    system:   { label: 'SYS',     css: 'cs-announcer__badge--system'  },
  };

  // Fallback content when API is unavailable
  const FALLBACK_MESSAGES = [
    { category: 'world',   text: 'Neon City pulse: district power grid at 94% capacity.' },
    { category: 'faction', text: 'OmniCorp security patrols increased in the Commercial District.' },
    { category: 'crime',   text: 'Three data couriers reported missing near the Grid nexus.' },
    { category: 'market',  text: 'Black market eCred exchange rate favours buyers tonight.' },
    { category: 'npc',     text: 'Street rumour: someone cracked the NeoTech vault last cycle.' },
    { category: 'world',   text: 'Weather advisory: acid rain expected in the lower districts.' },
    { category: 'faction', text: 'Ghost Net operatives active. Keep your comms encrypted.' },
    { category: 'event',   text: 'Arena tournament bracket opens at midnight. Cash prizes.' },
    { category: 'world',   text: 'Synthetic curfew lifted in Sector 7. Normal operations resume.' },
    { category: 'npc',     text: 'Lola says: "Trust no one who smiles without a reason."' },
    { category: 'crime',   text: 'StreetWatch reports spike in cyber-jacking near the Velvet Pit.' },
    { category: 'market',  text: 'Rare cyberware shipment detected at the docks. Move fast.' },
  ];

  // ── CosyAnnouncer ────────────────────────────────────────────────────────

  const CosyAnnouncer = {
    _items:        [],
    _index:        0,
    _pinned:       false,
    _hasLiveData:  false,
    _stationIdx:   0,
    _timer:        null,
    _pollTimer:    null,
    _collapsed:    true,

    // ── Lifecycle ─────────────────────────────────────────────────────────

    init () {
      this._els = {
        root:     document.getElementById('cs-announcer'),
        toggle:   document.getElementById('announcer-toggle'),
        body:     document.getElementById('announcer-body'),
        text:     document.getElementById('announcer-text'),
        badge:    document.getElementById('announcer-current')?.querySelector('.cs-announcer__badge'),
        current:  document.getElementById('announcer-current'),
        list:     document.getElementById('announcer-list'),
        station:  document.getElementById('announcer-station'),
        led:      document.querySelector('.cs-announcer__led'),
        prev:     document.getElementById('announcer-prev'),
        next:     document.getElementById('announcer-next'),
        pin:      document.getElementById('announcer-pin'),
        close:    document.getElementById('announcer-close'),
      };

      if (!this._els.root) return;

      this._bindEvents();
      this._loadItems().then(() => {
        // Only show when live data arrived (not just fallback filler)
        if (this._hasLiveData) {
          this._show();
          this._startAutoAdvance();
        }
      });

      // Periodic refresh
      this._pollTimer = setInterval(() => this._loadItems(), POLL_INTERVAL_MS);

      // Listen to socket world events if HUD socket is available
      if (window.NeonHUD && window.NeonHUD.socket) {
        this._attachSocket(window.NeonHUD.socket);
      } else {
        // Retry after HUD boots
        const check = setInterval(() => {
          if (window.NeonHUD && window.NeonHUD.socket) {
            this._attachSocket(window.NeonHUD.socket);
            clearInterval(check);
          }
        }, 1000);
      }
    },

    _attachSocket (socket) {
      socket.on('world_event',    d => this._onWorldEvent(d));
      socket.on('faction_update', d => this._onFactionEvent(d));
      socket.on('npc_broadcast',  d => this._onNPCBroadcast(d));
      socket.on('game_event',     d => this._onGameEvent(d));
    },

    // ── Events ───────────────────────────────────────────────────────────

    _bindEvents () {
      const { toggle, prev, next, pin, close } = this._els;

      if (toggle) toggle.onclick = () => this._toggle();
      if (prev)   prev.onclick   = () => { this._stopAutoAdvance(); this._step(-1); };
      if (next)   next.onclick   = () => { this._stopAutoAdvance(); this._step(1); };
      if (pin)    pin.onclick    = () => this._togglePin();
      if (close)  close.onclick  = () => this._collapse();

      // Keyboard: A = toggle announcer
      document.addEventListener('keydown', e => {
        if (['INPUT', 'TEXTAREA'].includes(e.target.tagName) || e.target.isContentEditable) return;
        if (e.key === 'a' || e.key === 'A') this._toggle();
      });

      // Auto-collapse if clicking outside (when not pinned)
      document.addEventListener('click', e => {
        if (this._pinned || this._collapsed) return;
        if (this._els.root && !this._els.root.contains(e.target)) {
          this._collapse();
        }
      });
    },

    // ── Data ─────────────────────────────────────────────────────────────

    async _loadItems () {
      try {
        const r = await fetch('/api/announcer/feed', { signal: AbortSignal.timeout(5000) });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        const items = (data.items || []).map(i => ({
          category: i.category || 'world',
          text:     i.text || i.message || '',
          ts:       i.ts || Date.now(),
        })).filter(i => i.text);

        if (items.length) {
          this._items = items;
          this._hasLiveData = true;
          if (!this._els.root.classList.contains(VISIBLE_CLASS)) {
            this._show();
            this._startAutoAdvance();
          }
          this._stationIdx = (data.station_index ?? 0) % STATIONS.length;
          this._updateStation();
          this._renderList();
          this._flash();
        }
      } catch (_e) {
        // Fallback: try to get events from HUD state
        try {
          const r2 = await fetch('/api/hud/state', { signal: AbortSignal.timeout(3000) });
          if (r2.ok) {
            const state = await r2.json();
            const events = (state.active_events || []).map(e => ({
              category: 'event',
              text: e.title || e.name || '',
              ts: Date.now(),
            })).filter(e => e.text);
            if (events.length) {
              this._items = [...events, ...FALLBACK_MESSAGES.slice(0, 5)];
              this._hasLiveData = true;
              if (!this._els.root.classList.contains(VISIBLE_CLASS)) {
                this._show();
                this._startAutoAdvance();
              }
              this._renderList();
              return;
            }
          }
        } catch (_e2) {}

        if (!this._items.length) {
          this._items = [...FALLBACK_MESSAGES];
          this._renderList();
        }
      }
    },

    _onWorldEvent (data) {
      this._pushItem({ category: 'world', text: data.title || data.description || data.text || '', ts: Date.now() });
    },

    _onFactionEvent (data) {
      const faction = data.faction || 'UNKNOWN';
      const msg = data.message || data.text || '';
      if (msg) this._pushItem({ category: 'faction', text: `[${faction}] ${msg}`, ts: Date.now() });
    },

    _onNPCBroadcast (data) {
      const npc = data.name || data.character || 'NPC';
      const msg = data.message || data.text || '';
      if (msg) this._pushItem({ category: 'npc', text: `${npc}: "${msg}"`, ts: Date.now() });
    },

    _onGameEvent (data) {
      const msg = data.title || data.description || data.text || '';
      if (msg) this._pushItem({ category: 'event', text: msg, ts: Date.now() });
    },

    _pushItem (item) {
      if (!item.text) return;
      this._items.unshift(item);
      if (this._items.length > 30) this._items.length = 30;
      this._index = 0;
      this._hasLiveData = true;
      // Auto-show on first live event if not already visible
      if (!this._els.root.classList.contains(VISIBLE_CLASS)) {
        this._show();
        this._startAutoAdvance();
      }
      this._renderCurrent();
      this._renderList();
      this._flash();
      if (this._collapsed) this._peekTicker();
    },

    // ── Rendering ────────────────────────────────────────────────────────

    _renderCurrent () {
      const item = this._items[this._index];
      if (!item || !this._els.text) return;
      const badge = this._els.badge;
      const info  = BADGE_MAP[item.category] || BADGE_MAP.world;
      if (badge) {
        badge.textContent = info.label;
        badge.className = 'cs-announcer__badge ' + info.css;
      }
      this._els.text.textContent = item.text;
      // Animate text swap
      this._els.current?.classList.remove('cs-announcer__item--enter');
      void this._els.current?.offsetWidth;
      this._els.current?.classList.add('cs-announcer__item--enter');
    },

    _renderList () {
      const list = this._els.list;
      if (!list) return;
      list.innerHTML = '';
      this._items.slice(0, 8).forEach((item, i) => {
        const info = BADGE_MAP[item.category] || BADGE_MAP.world;
        const div = document.createElement('div');
        div.className = 'cs-announcer__list-item' + (i === this._index ? ' cs-announcer__list-item--active' : '');
        div.innerHTML = `<span class="cs-announcer__badge ${info.css}">${info.label}</span><span class="cs-announcer__list-text">${_esc(item.text)}</span>`;
        div.onclick = () => { this._index = i; this._renderCurrent(); this._renderList(); };
        list.appendChild(div);
      });
    },

    _updateStation () {
      const s = STATIONS[this._stationIdx % STATIONS.length];
      if (this._els.station) {
        this._els.station.textContent = s.name;
        this._els.station.style.color = s.color;
      }
      const freq = this._els.root?.querySelector('.cs-announcer__freq');
      if (freq) freq.textContent = s.freq;
    },

    // ── Visibility / Animation ────────────────────────────────────────────

    _show () {
      if (this._els.root) {
        this._els.root.classList.add(VISIBLE_CLASS);
        this._els.root.classList.add(COLLAPSED_CLASS);
      }
      this._renderCurrent();
    },

    _toggle () {
      if (this._collapsed) this._expand();
      else this._collapse();
    },

    _expand () {
      this._collapsed = false;
      this._els.root?.classList.remove(COLLAPSED_CLASS);
      this._renderList();
    },

    _collapse () {
      if (this._pinned) return;
      this._collapsed = true;
      this._els.root?.classList.add(COLLAPSED_CLASS);
    },

    _togglePin () {
      this._pinned = !this._pinned;
      this._els.root?.classList.toggle(PINNED_CLASS, this._pinned);
      if (this._els.pin) {
        this._els.pin.classList.toggle('cs-announcer__ctrl--active', this._pinned);
        this._els.pin.title = this._pinned ? 'Unpin' : 'Pin open';
      }
    },

    // Brief peek: show a sliver of the body then collapse
    _peekTicker () {
      if (!this._collapsed) return;
      const root = this._els.root;
      if (!root) return;
      root.classList.add('cs-announcer--peek');
      setTimeout(() => root.classList.remove('cs-announcer--peek'), 4000);
    },

    _flash () {
      const led = this._els.led;
      if (!led) return;
      led.classList.add(FLASH_CLASS);
      setTimeout(() => led.classList.remove(FLASH_CLASS), 800);
    },

    // ── Navigation ───────────────────────────────────────────────────────

    _step (dir) {
      if (!this._items.length) return;
      this._index = (this._index + dir + this._items.length) % this._items.length;
      this._renderCurrent();
      this._renderList();
    },

    _startAutoAdvance () {
      this._stopAutoAdvance();
      this._timer = setInterval(() => {
        if (!document.hidden && !this._pinned) {
          this._step(1);
        }
      }, AUTO_ADVANCE_MS);
    },

    _stopAutoAdvance () {
      if (this._timer) { clearInterval(this._timer); this._timer = null; }
    },
  };

  // ── Helpers ───────────────────────────────────────────────────────────────

  function _esc (str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Boot ──────────────────────────────────────────────────────────────────

  function boot () {
    if (document.getElementById('cs-announcer')) {
      CosyAnnouncer.init();
      window.CosyAnnouncer = CosyAnnouncer;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();
