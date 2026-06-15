/**
 * the_sprawl.js — THE SPRAWL living-city map renderer (B-T3 UI).
 * =============================================================
 * v1.63.0 [2026-06-16] — Living-city map UI (B-T3). Renders the real-time city:
 * an SVG district map shaded by each district's dominant faction (contested
 * zones pulse + hatch), NPC tokens clustered per district, a faction
 * leaderboard, a live City Pulse event feed and a player HUD strip.
 *
 * Data sources:
 *   - GET /api/sprawl/state  → {districts, factions, npcs, player, ts}
 *   - GET /api/sprawl/events?since=0 → {events, since}  (seeds the feed)
 *   - Socket.IO: `sprawl_update` (full state → re-render map/NPCs/leaderboard/HUD)
 *                `sprawl_event`  (one event → prepend feed + flash its district)
 *                `state_update`  (scene identity / clock for the HUD)
 *
 * Defensive throughout: missing/empty data degrades to graceful empty states
 * and never throws — the goal is 0 uncaught console errors.
 */
(function () {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';

  /** Faction → neon color (mirrors --fac-* in the_sprawl.css). */
  var FACTION_COLORS = {
    OmniCorp: '#06b6d4',
    NeoTech: '#39ff14',
    BlackMarket: '#f97316',
    Ghost_Net: '#d500f9',
    SynthSec: '#ef4444',
    DeepState: '#a855f7',
    none: '#6b7280'
  };

  /**
   * Static layout for the 6 districts on the 1000×760 SVG canvas — a stylized
   * city-block grid (each zone a rounded rect "block"); non-overlapping, packed
   * to read as a map. NPC tokens cluster inside each zone's inner box.
   */
  var DISTRICT_LAYOUT = {
    DOWNTOWN:      { x: 40,  y: 40,  w: 290, h: 330, label: 'DOWNTOWN' },
    HIGHRISE:      { x: 355, y: 40,  w: 290, h: 200, label: 'HIGHRISE' },
    TECH_DISTRICT: { x: 670, y: 40,  w: 290, h: 445, label: 'TECH DISTRICT' },
    COMBAT_ZONE:   { x: 355, y: 265, w: 290, h: 220, label: 'COMBAT ZONE' },
    UNDERWORLD:    { x: 40,  y: 395, w: 290, h: 325, label: 'UNDERWORLD' },
    OUTSKIRTS:     { x: 355, y: 510, w: 605, h: 210, label: 'OUTSKIRTS' }
  };

  var $ = function (id) { return document.getElementById(id); };

  function setText(id, value) {
    var el = $(id);
    if (el) el.textContent = value;
  }

  function facColor(faction) {
    if (faction && FACTION_COLORS.hasOwnProperty(faction)) return FACTION_COLORS[faction];
    return FACTION_COLORS.none;
  }

  function el(tag, attrs) {
    var node = document.createElementNS(SVGNS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (attrs.hasOwnProperty(k)) node.setAttribute(k, attrs[k]);
      }
    }
    return node;
  }

  // ── State cache (so NPC re-render can read latest district map) ──────────
  var lastState = { districts: [], factions: [], npcs: [], player: {} };
  var zoneById = {}; // district id → {group, layout} for flashing/lookups

  // ════════════════════════════════════════════════════════════════════════
  //  District map
  // ════════════════════════════════════════════════════════════════════════

  function renderDistricts(districts) {
    var g = $('sprawl-districts');
    if (!g) return;
    g.innerHTML = '';
    zoneById = {};

    var empty = $('sprawl-map-empty');
    if (empty) empty.hidden = !!(districts && districts.length);

    (districts || []).forEach(function (d) {
      var layout = DISTRICT_LAYOUT[d.id];
      if (!layout) return;

      var dom = Array.isArray(d.dominant) ? d.dominant : ['none', 0];
      var domFaction = dom[0] || 'none';
      var domPct = (typeof dom[1] === 'number') ? dom[1] : 0;
      var color = facColor(domFaction);

      var group = el('g', { class: 'district-zone' + (d.contested ? ' is-contested' : '') });
      group.setAttribute('data-district', d.id);
      group.style.color = color; // for flash drop-shadow currentColor

      // Tinted fill (semi-transparent so the backdrop bleeds through).
      var fill = el('rect', {
        class: 'district-zone__fill',
        x: layout.x, y: layout.y, width: layout.w, height: layout.h,
        rx: 14, fill: color, 'fill-opacity': 0.26
      });
      group.appendChild(fill);

      // Contested hatch overlay.
      if (d.contested) {
        group.appendChild(el('rect', {
          x: layout.x, y: layout.y, width: layout.w, height: layout.h,
          rx: 14, fill: 'url(#sprawl-hatch)'
        }));
      }

      // Edge (glow border, pulses when contested).
      group.appendChild(el('rect', {
        class: 'district-zone__edge',
        x: layout.x, y: layout.y, width: layout.w, height: layout.h,
        rx: 14, fill: 'none', stroke: color, 'stroke-width': 2,
        'stroke-opacity': d.contested ? 0.6 : 0.85
      }));

      // Labels.
      var label = el('text', {
        class: 'district-zone__label',
        x: layout.x + 14, y: layout.y + 26, 'font-size': 18
      });
      label.textContent = layout.label;
      group.appendChild(label);

      var domText = el('text', {
        class: 'district-zone__dom',
        x: layout.x + 14, y: layout.y + 48, 'font-size': 13, fill: color
      });
      domText.textContent = domFaction === 'none' ? 'uncontrolled' : domFaction;
      group.appendChild(domText);

      var pctText = el('text', {
        class: 'district-zone__pct',
        x: layout.x + 14, y: layout.y + 66, 'font-size': 12
      });
      pctText.textContent = domPct.toFixed(1) + '% control'
        + (d.contested ? '  · CONTESTED' : '');
      group.appendChild(pctText);

      g.appendChild(group);
      zoneById[d.id] = { group: group, layout: layout };
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  NPC tokens (clustered within their district zone)
  // ════════════════════════════════════════════════════════════════════════

  function renderNpcs(npcs) {
    var g = $('sprawl-npcs');
    if (!g) return;
    g.innerHTML = '';

    // Group NPCs per district to lay out clusters deterministically.
    var byDistrict = {};
    (npcs || []).forEach(function (n) {
      var d = (n.district && DISTRICT_LAYOUT[n.district]) ? n.district : null;
      if (!d) return; // unknown/offscreen districts skipped (graceful)
      (byDistrict[d] = byDistrict[d] || []).push(n);
    });

    Object.keys(byDistrict).forEach(function (district) {
      var layout = DISTRICT_LAYOUT[district];
      var list = byDistrict[district];
      // Cluster area: lower portion of the zone, inset from edges.
      var pad = 18;
      var areaX = layout.x + pad;
      var areaY = layout.y + 82;
      var areaW = layout.w - pad * 2;
      var areaH = layout.h - 82 - pad;
      if (areaH < 30) { areaY = layout.y + 40; areaH = layout.h - 50; }

      var cols = Math.max(1, Math.ceil(Math.sqrt(list.length * (areaW / Math.max(areaH, 1)))));
      var rows = Math.max(1, Math.ceil(list.length / cols));
      var stepX = areaW / cols;
      var stepY = areaH / rows;

      list.forEach(function (n, i) {
        var col = i % cols;
        var row = Math.floor(i / cols);
        var cx = areaX + stepX * (col + 0.5);
        var cy = areaY + stepY * (row + 0.5);
        var color = facColor(n.faction);

        var dot = el('circle', {
          class: 'npc-token',
          cx: cx, cy: cy, r: 5,
          fill: color
        });
        dot.setAttribute('data-name', n.name || n.id || '');
        dot.setAttribute('data-sex', n.sex || '');
        dot.setAttribute('data-faction', n.faction || 'unaligned');
        dot.setAttribute('data-activity', n.activity || 'idle');
        dot.addEventListener('mouseenter', onTokenEnter);
        dot.addEventListener('mousemove', onTokenMove);
        dot.addEventListener('mouseleave', onTokenLeave);
        g.appendChild(dot);
      });
    });
  }

  // ── NPC tooltip ──────────────────────────────────────────────────────────
  function onTokenEnter(ev) {
    var t = ev.target;
    var tip = $('sprawl-tip');
    if (!tip) return;
    var faction = t.getAttribute('data-faction');
    var color = facColor(faction === 'unaligned' ? 'none' : faction);
    tip.innerHTML = '';
    var name = document.createElement('div');
    name.className = 'sprawl-tip__name';
    name.textContent = t.getAttribute('data-name');
    var fac = document.createElement('div');
    fac.className = 'sprawl-tip__row';
    var facSpan = document.createElement('span');
    facSpan.className = 'sprawl-tip__fac';
    facSpan.style.color = color;
    facSpan.textContent = faction;
    fac.appendChild(document.createTextNode('faction · '));
    fac.appendChild(facSpan);
    var meta = document.createElement('div');
    meta.className = 'sprawl-tip__row';
    meta.textContent = (t.getAttribute('data-sex') || '—') + ' · '
      + (t.getAttribute('data-activity') || 'idle');
    tip.appendChild(name);
    tip.appendChild(fac);
    tip.appendChild(meta);
    tip.hidden = false;
    onTokenMove(ev);
  }
  function onTokenMove(ev) {
    var tip = $('sprawl-tip');
    var map = document.querySelector('.sprawl-map');
    if (!tip || !map) return;
    var rect = map.getBoundingClientRect();
    tip.style.left = (ev.clientX - rect.left) + 'px';
    tip.style.top = (ev.clientY - rect.top) + 'px';
  }
  function onTokenLeave() {
    var tip = $('sprawl-tip');
    if (tip) tip.hidden = true;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Faction leaderboard
  // ════════════════════════════════════════════════════════════════════════

  function renderLeaderboard(factions) {
    var ol = $('sprawl-leaderboard');
    if (!ol) return;
    ol.innerHTML = '';
    if (!factions || !factions.length) {
      var li = document.createElement('li');
      li.className = 'sprawl-empty';
      li.textContent = 'no faction data';
      ol.appendChild(li);
      return;
    }
    var max = factions.reduce(function (m, f) {
      return Math.max(m, f.total || 0);
    }, 0) || 1;

    factions.forEach(function (f, i) {
      var color = facColor(f.faction);
      var row = document.createElement('li');
      row.className = 'lb-row';

      var rank = document.createElement('span');
      rank.className = 'lb-row__rank';
      rank.textContent = (i + 1);

      var body = document.createElement('div');
      body.className = 'lb-row__body';
      var name = document.createElement('div');
      name.className = 'lb-row__name';
      var sw = document.createElement('span');
      sw.className = 'lb-row__swatch';
      sw.style.background = color;
      name.appendChild(sw);
      name.appendChild(document.createTextNode(f.faction));
      var barWrap = document.createElement('div');
      barWrap.className = 'lb-row__bar';
      var fill = document.createElement('div');
      fill.className = 'lb-row__fill';
      fill.style.width = Math.max(2, ((f.total || 0) / max) * 100) + '%';
      fill.style.background = color;
      fill.style.boxShadow = '0 0 8px ' + color;
      barWrap.appendChild(fill);
      body.appendChild(name);
      body.appendChild(barWrap);

      var total = document.createElement('span');
      total.className = 'lb-row__total';
      total.textContent = (f.total || 0).toFixed(0);

      row.appendChild(rank);
      row.appendChild(body);
      row.appendChild(total);
      ol.appendChild(row);
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  City Pulse feed
  // ════════════════════════════════════════════════════════════════════════

  var FEED_CAP = 60;
  var feedSeeded = false;

  function fmtTs(ts) {
    try {
      var d;
      if (typeof ts === 'number') d = new Date(ts * 1000);
      else if (typeof ts === 'string' && ts) d = new Date(ts);
      else return '';
      if (isNaN(d.getTime())) return '';
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) { return ''; }
  }

  function makeFeedItem(ev) {
    var district = ev.district || '';
    // Tint by district's dominant faction if known, else by actor name match.
    var color = FACTION_COLORS.none;
    if (district) {
      var d = (lastState.districts || []).filter(function (x) { return x.id === district; })[0];
      if (d && Array.isArray(d.dominant)) color = facColor(d.dominant[0]);
    }
    if (FACTION_COLORS.hasOwnProperty(ev.actor)) color = facColor(ev.actor);

    var li = document.createElement('li');
    li.className = 'feed-item';

    var bar = document.createElement('div');
    bar.className = 'feed-item__bar';
    bar.style.background = color;

    var main = document.createElement('div');
    main.className = 'feed-item__main';

    var top = document.createElement('div');
    top.className = 'feed-item__top';
    var kind = document.createElement('span');
    kind.className = 'feed-item__kind';
    kind.textContent = (ev.kind || 'event').replace(/_/g, ' ');
    kind.style.color = color;
    var ts = document.createElement('span');
    ts.className = 'feed-item__ts';
    ts.textContent = fmtTs(ev.ts);
    top.appendChild(kind);
    top.appendChild(ts);

    var summary = document.createElement('div');
    summary.className = 'feed-item__summary';
    if (ev.actor) {
      var actor = document.createElement('span');
      actor.className = 'feed-item__actor';
      actor.textContent = ev.actor + ' ';
      summary.appendChild(actor);
    }
    summary.appendChild(document.createTextNode(ev.summary || ''));

    main.appendChild(top);
    main.appendChild(summary);
    li.appendChild(bar);
    li.appendChild(main);
    return li;
  }

  function clearFeedEmpty() {
    var empty = $('sprawl-feed-empty');
    if (empty && empty.parentNode) empty.parentNode.removeChild(empty);
  }

  function prependEvent(ev) {
    var ul = $('sprawl-feed');
    if (!ul || !ev) return;
    clearFeedEmpty();
    ul.insertBefore(makeFeedItem(ev), ul.firstChild);
    while (ul.children.length > FEED_CAP) ul.removeChild(ul.lastChild);
  }

  function seedFeed(events) {
    var ul = $('sprawl-feed');
    if (!ul) return;
    if (!events || !events.length) return;
    clearFeedEmpty();
    // Events arrive newest-first; append in order so newest stays on top.
    events.slice(0, FEED_CAP).forEach(function (ev) {
      ul.appendChild(makeFeedItem(ev));
    });
    feedSeeded = true;
  }

  function flashDistrict(district) {
    if (!district || !zoneById[district]) return;
    var grp = zoneById[district].group;
    grp.classList.remove('is-flash');
    // force reflow to restart the animation
    void grp.getBBox;
    grp.classList.add('is-flash');
    setTimeout(function () { grp.classList.remove('is-flash'); }, 1200);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  HUD
  // ════════════════════════════════════════════════════════════════════════

  function renderPlayer(player) {
    player = player || {};
    setText('hud-location', player.location || '—');
    setText('hud-credits',
      (typeof player.credits === 'number') ? player.credits.toLocaleString() : '—');
    var heatEl = $('hud-heat');
    if (heatEl) {
      var heat = (typeof player.heat === 'number') ? player.heat : null;
      heatEl.textContent = (heat === null) ? '—' : heat;
      heatEl.classList.toggle('is-hot', heat !== null && heat >= 50);
    }
  }

  function setLink(text, cls) {
    var el2 = $('hud-link');
    if (!el2) return;
    el2.textContent = text;
    el2.classList.remove('is-live', 'is-down');
    if (cls) el2.classList.add(cls);
  }

  // Live wall clock (independent of socket cadence).
  function startClock() {
    function tick() {
      var d = new Date();
      setText('hud-clock', d.toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      }));
    }
    tick();
    setInterval(tick, 1000);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Full state apply
  // ════════════════════════════════════════════════════════════════════════

  function applySprawlState(state) {
    if (!state) return;
    lastState = {
      districts: state.districts || [],
      factions: state.factions || [],
      npcs: state.npcs || [],
      player: state.player || {}
    };
    renderDistricts(lastState.districts);
    renderNpcs(lastState.npcs);
    renderLeaderboard(lastState.factions);
    renderPlayer(lastState.player);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Boot
  // ════════════════════════════════════════════════════════════════════════

  function seedFromRest() {
    fetch('/api/sprawl/state')
      .then(function (r) { return r.json(); })
      .then(applySprawlState)
      .catch(function (err) {
        console.warn('[the_sprawl] /api/sprawl/state fetch failed', err);
      });

    fetch('/api/sprawl/events?since=0')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.events) seedFeed(data.events);
      })
      .catch(function (err) {
        console.warn('[the_sprawl] /api/sprawl/events fetch failed', err);
      });
  }

  function init() {
    startClock();

    if (typeof io !== 'function') {
      console.warn('[the_sprawl] Socket.IO client unavailable');
      setLink('offline', 'is-down');
      seedFromRest();
      return;
    }

    var socket = io();

    socket.on('connect', function () {
      console.log('[the_sprawl] socket connected');
      setLink('online', 'is-live');
    });

    socket.on('disconnect', function () {
      console.log('[the_sprawl] socket disconnected');
      setLink('reconnecting…', 'is-down');
    });

    // Full live world-state → re-render everything.
    socket.on('sprawl_update', function (state) {
      applySprawlState(state);
    });

    // Single normalized event → prepend feed + flash its district.
    socket.on('sprawl_event', function (ev) {
      prependEvent(ev);
      if (ev && ev.district) flashDistrict(ev.district);
    });

    // Seed REST in parallel so the UI paints immediately even before the first
    // socket push (and seeds the historical event feed).
    seedFromRest();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
