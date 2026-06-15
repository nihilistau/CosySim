/**
 * war_room.js — THE WAR ROOM faction command center (C-T3 UI).
 * =================================================================
 * v1.63.0 [2026-06-16] — Command-center dashboard renderer (C-T3). Replaces the
 * C-T1/C-T2 "booting…" placeholder. Two top-level views, driven entirely by the
 * server's dashboard state:
 *   - Allegiance picker (state.allegiance === null): renders the 6 factions as
 *     selectable crest cards (color / power / territory / traits / relation);
 *     clicking one POSTs /api/warroom/allegiance {faction} and flips to the
 *     dashboard once the server confirms (the broadcast warroom_update re-paints).
 *   - Dashboard (state.allegiance set): my-faction header (crest / power / rank
 *     ladder / territory + crew counts), a territory panel (your districts,
 *     contested flagged), a crew roster, a rivals panel (power bars + relation
 *     badges) and a live intel feed (recent FactionAI decisions, newest-first,
 *     capped). The command bar is an inert placeholder (commands ship in C-T4).
 *
 * Data sources:
 *   - GET  /api/warroom/state            → full dashboard state (seeds the view)
 *   - POST /api/warroom/allegiance {faction} → set allegiance, returns new state
 *   - Socket.IO: `warroom_update` (full state → re-render everything; on connect)
 *                `state_update`  (scene identity / clock for the HUD)
 *
 * Defensive throughout: missing/empty data degrades to graceful empty states and
 * never throws — the goal is 0 uncaught console errors.
 */
(function () {
  'use strict';

  /** Faction → neon color (mirrors --fac-* in war_room.css / the Sprawl). */
  var FACTION_COLORS = {
    OmniCorp: '#06b6d4',
    NeoTech: '#39ff14',
    BlackMarket: '#f97316',
    Ghost_Net: '#d500f9',
    SynthSec: '#ef4444',
    DeepState: '#a855f7',
    none: '#6b7280'
  };

  var INTEL_CAP = 60;

  var $ = function (id) { return document.getElementById(id); };

  function setText(id, value) {
    var el = $(id);
    if (el) el.textContent = value;
  }

  function facColor(faction) {
    if (faction && FACTION_COLORS.hasOwnProperty(faction)) return FACTION_COLORS[faction];
    return FACTION_COLORS.none;
  }

  /** Render a faction name for display (Ghost_Net → "Ghost Net"). */
  function facLabel(faction) {
    return String(faction || '').replace(/_/g, ' ');
  }

  /** Two-letter crest initials from a faction id ("BlackMarket" → "BM"). */
  function crestInitials(faction) {
    var s = String(faction || '?');
    var caps = s.replace(/[^A-Z]/g, '');
    if (caps.length >= 2) return caps.slice(0, 2);
    return s.slice(0, 2).toUpperCase();
  }

  /**
   * Map a player-standing int (-100..100) to a relation descriptor.
   * Mirrors the ally/war/neutral language called for by the dashboard.
   */
  function relationOf(standing) {
    var n = (typeof standing === 'number') ? standing : 0;
    if (n >= 25) return { key: 'ally', cls: 'is-ally', label: 'Ally' };
    if (n <= -25) return { key: 'war', cls: 'is-enemy', label: 'At War' };
    return { key: 'neutral', cls: 'is-neutral', label: 'Neutral' };
  }

  function clearChildren(el) {
    if (el) el.innerHTML = '';
  }

  // ── State cache (last full dashboard state) ──────────────────────────────
  var lastState = null;
  var pendingFaction = null; // faction the player just clicked (optimistic UI)

  // ════════════════════════════════════════════════════════════════════════
  //  View switching
  // ════════════════════════════════════════════════════════════════════════

  function showView(name) {
    var picker = $('war-picker');
    var dash = $('war-dash');
    var change = $('war-change');
    if (picker) picker.hidden = (name !== 'picker');
    if (dash) dash.hidden = (name !== 'dash');
    if (change) change.hidden = (name !== 'dash');
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Allegiance picker
  // ════════════════════════════════════════════════════════════════════════

  function renderPicker(factions) {
    var grid = $('war-picker-grid');
    if (!grid) return;
    clearChildren(grid);

    if (!factions || !factions.length) {
      var empty = document.createElement('div');
      empty.className = 'war-empty';
      empty.textContent = 'no faction data';
      grid.appendChild(empty);
      return;
    }

    factions.forEach(function (f) {
      grid.appendChild(makeFactionCard(f));
    });
  }

  function makeFactionCard(f) {
    var color = facColor(f.faction);
    var card = document.createElement('button');
    card.type = 'button';
    card.className = 'fac-card';
    card.style.setProperty('--fc', color);
    card.setAttribute('data-faction', f.faction);
    if (pendingFaction === f.faction) card.classList.add('is-busy');

    // Head: crest + name + relation badge.
    var head = document.createElement('div');
    head.className = 'fac-card__head';
    var crest = document.createElement('div');
    crest.className = 'fac-card__crest';
    crest.textContent = crestInitials(f.faction);
    var name = document.createElement('h3');
    name.className = 'fac-card__name';
    name.textContent = facLabel(f.faction);
    head.appendChild(crest);
    head.appendChild(name);
    var rel = relationOf(f.relations);
    var badge = document.createElement('span');
    badge.className = 'war-relbadge fac-card__rel '
      + (rel.key === 'ally' ? 'is-ally' : rel.key === 'war' ? 'is-enemy' : 'is-neutral');
    badge.textContent = rel.label;
    head.appendChild(badge);
    card.appendChild(head);

    // Stats: power + territory count.
    var stats = document.createElement('div');
    stats.className = 'fac-card__stats';
    stats.appendChild(makeStat(fmtPower(f.power), 'POWER'));
    var terrCount = Array.isArray(f.territory) ? f.territory.length : 0;
    stats.appendChild(makeStat(String(terrCount), 'DISTRICTS'));
    card.appendChild(stats);

    // Traits (chips).
    var traitNames = traitList(f.traits);
    if (traitNames.length) {
      var traits = document.createElement('div');
      traits.className = 'fac-card__traits';
      traitNames.slice(0, 4).forEach(function (t) {
        var chip = document.createElement('span');
        chip.className = 'fac-trait';
        chip.textContent = t;
        traits.appendChild(chip);
      });
      card.appendChild(traits);
    }

    // CTA.
    var cta = document.createElement('div');
    cta.className = 'fac-card__cta';
    cta.textContent = pendingFaction === f.faction ? 'pledging…' : '▸ Pledge allegiance';
    card.appendChild(cta);

    card.addEventListener('click', function () { onPickFaction(f.faction, card); });
    return card;
  }

  function makeStat(value, label) {
    var wrap = document.createElement('div');
    wrap.className = 'fac-card__stat';
    var b = document.createElement('b');
    b.textContent = value;
    var s = document.createElement('span');
    s.textContent = label;
    wrap.appendChild(b);
    wrap.appendChild(s);
    return wrap;
  }

  // Trait keys that read as long prose / structural data — surfaced specially or
  // skipped rather than rendered as chips.
  var TRAIT_SKIP = { description: 1, preferred_districts: 1, allied_with: 1, hostile_to: 1 };

  /**
   * Extract a short list of concise trait-chip labels from the (free-form)
   * traits dict. Numeric personality knobs (aggression / diplomacy / …) render
   * as "key N%"; boolean flags render as the key; the verbose description and
   * structural lists are skipped (kept off the small cards).
   */
  function traitList(traits) {
    if (!traits || typeof traits !== 'object') return [];
    var out = [];
    Object.keys(traits).forEach(function (k) {
      if (TRAIT_SKIP[k]) return;
      var v = traits[k];
      var label = k.replace(/_/g, ' ');
      if (typeof v === 'boolean') {
        if (v) out.push(label);
      } else if (typeof v === 'string') {
        out.push(v.replace(/_/g, ' '));
      } else if (typeof v === 'number') {
        // Personality knobs are 0..1 — show as a percent for readability.
        var pct = (v >= 0 && v <= 1) ? Math.round(v * 100) + '%' : String(v);
        out.push(label + ' ' + pct);
      } else if (Array.isArray(v)) {
        v.forEach(function (item) {
          if (typeof item === 'string') out.push(item.replace(/_/g, ' '));
        });
      }
    });
    return out;
  }

  function onPickFaction(faction, card) {
    if (pendingFaction) return; // one at a time
    pendingFaction = faction;
    if (card) {
      card.classList.add('is-busy');
      var cta = card.querySelector('.fac-card__cta');
      if (cta) cta.textContent = 'pledging…';
    }
    postJson('/api/warroom/allegiance', { faction: faction })
      .then(function (res) {
        res = res || {};
        if (res.ok && res.allegiance) {
          toast('Allegiance pledged to ' + facLabel(res.allegiance), true);
          applyState(res); // flips to dashboard; warroom_update also re-paints
        } else {
          toast((res.error ? 'Rejected: ' + res.error : 'Could not set allegiance'), false);
          pendingFaction = null;
          renderPicker((lastState && lastState.factions) || []);
        }
      })
      .catch(function (err) {
        console.warn('[war_room] allegiance POST failed', err);
        toast('Could not set allegiance', false);
        pendingFaction = null;
        renderPicker((lastState && lastState.factions) || []);
      });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Dashboard — my faction header
  // ════════════════════════════════════════════════════════════════════════

  // Rank ladder labels (display order; matches war_room_scene rank bands).
  var RANK_LADDER = ['Unknown', 'Street Crew', 'Contender', 'Power Player', 'Kingpin'];

  function fmtPower(p) {
    var n = (typeof p === 'number') ? p : parseFloat(p);
    if (isNaN(n)) return '—';
    return (Math.round(n * 10) / 10).toString();
  }

  function renderMyHead(my) {
    my = my || {};
    var color = facColor(my.faction);
    var head = $('war-myhead');
    if (head) head.style.setProperty('--fc', color);

    var crest = $('my-crest');
    if (crest) crest.textContent = crestInitials(my.faction);
    setText('my-name', facLabel(my.faction) || '—');
    setText('my-rank', my.rank || '—');
    setText('my-power', fmtPower(my.power));

    var terr = Array.isArray(my.territory) ? my.territory.length : 0;
    setText('my-territory', String(terr));
    var crews = Array.isArray(my.crews) ? my.crews.length : 0;
    setText('my-crewcount', String(crews));

    renderRankLadder(my.rank);
  }

  function renderRankLadder(rank) {
    var wrap = $('my-rankladder');
    if (!wrap) return;
    clearChildren(wrap);
    var idx = RANK_LADDER.indexOf(rank);
    if (idx < 0) idx = 0;
    for (var i = 0; i < RANK_LADDER.length; i++) {
      var pip = document.createElement('i');
      if (i <= idx) pip.className = 'is-on';
      pip.title = RANK_LADDER[i];
      wrap.appendChild(pip);
    }
  }

  // ── Territory panel ──────────────────────────────────────────────────────
  function renderTerritory(my, wars) {
    var ul = $('war-territory');
    if (!ul) return;
    clearChildren(ul);
    var color = facColor(my && my.faction);
    var districts = (my && Array.isArray(my.territory)) ? my.territory : [];
    var contested = contestedSet(wars);

    if (!districts.length) {
      ul.appendChild(emptyLi('no districts held'));
      return;
    }
    districts.forEach(function (d) {
      var isContested = contested.hasOwnProperty(String(d).toUpperCase()) ||
        contested.hasOwnProperty(String(d));
      var li = document.createElement('li');
      li.className = 'terr-row' + (isContested ? ' is-contested' : '');
      li.style.setProperty('--fc', color);
      var name = document.createElement('span');
      name.className = 'terr-row__name';
      name.textContent = facLabel(d);
      var tag = document.createElement('span');
      tag.className = 'terr-row__tag';
      tag.textContent = isContested ? 'contested' : 'held';
      li.appendChild(name);
      li.appendChild(tag);
      ul.appendChild(li);
    });
  }

  /** Build a lookup of districts that appear in any active war (best-effort). */
  function contestedSet(wars) {
    var set = {};
    if (!wars) return set;
    try {
      var entries = Array.isArray(wars) ? wars : Object.keys(wars).map(function (k) { return wars[k]; });
      entries.forEach(function (w) {
        if (!w) return;
        var ds = w.districts || w.territory || w.contested || [];
        if (typeof ds === 'string') ds = [ds];
        if (Array.isArray(ds)) {
          ds.forEach(function (d) {
            set[String(d)] = true;
            set[String(d).toUpperCase()] = true;
          });
        }
      });
    } catch (e) { /* graceful: nothing flagged contested */ }
    return set;
  }

  // ── Crew roster ──────────────────────────────────────────────────────────
  function renderCrew(crews) {
    var ul = $('war-crew');
    if (!ul) return;
    clearChildren(ul);
    if (!crews || !crews.length) {
      ul.appendChild(emptyLi('no crew recruited'));
      return;
    }
    crews.forEach(function (c) {
      c = c || {};
      var name = c.name || c.character_id || c.id || 'Operative';
      var role = c.role || c.archetype || c.specialty || '';
      var loyalty = (typeof c.loyalty === 'number') ? c.loyalty
        : (typeof c.morale === 'number') ? c.morale : null;

      var li = document.createElement('li');
      li.className = 'crew-row';

      var av = document.createElement('div');
      av.className = 'crew-row__avatar';
      av.textContent = crestInitials(name.replace(/\s+/g, ''));

      var body = document.createElement('div');
      body.className = 'crew-row__body';
      var nm = document.createElement('div');
      nm.className = 'crew-row__name';
      nm.textContent = name;
      body.appendChild(nm);
      if (role) {
        var rl = document.createElement('div');
        rl.className = 'crew-row__role';
        rl.textContent = role;
        body.appendChild(rl);
      }

      li.appendChild(av);
      li.appendChild(body);

      if (loyalty !== null) {
        var loy = document.createElement('div');
        loy.className = 'crew-row__loyalty';
        loy.textContent = Math.round(loyalty);
        var lbl = document.createElement('span');
        lbl.textContent = 'LOYALTY';
        loy.appendChild(lbl);
        li.appendChild(loy);
      }
      ul.appendChild(li);
    });
  }

  // ── Rivals panel ─────────────────────────────────────────────────────────
  function renderRivals(rivals) {
    var ul = $('war-rivals');
    if (!ul) return;
    clearChildren(ul);
    if (!rivals || !rivals.length) {
      ul.appendChild(emptyLi('no rival data'));
      return;
    }
    var max = rivals.reduce(function (m, r) {
      return Math.max(m, (typeof r.power === 'number') ? r.power : 0);
    }, 0) || 1;

    rivals.forEach(function (r) {
      r = r || {};
      var color = facColor(r.faction);
      var li = document.createElement('li');
      li.className = 'rival-row';
      li.style.setProperty('--fc', color);

      var name = document.createElement('div');
      name.className = 'rival-row__name';
      var sw = document.createElement('span');
      sw.className = 'rival-row__swatch';
      name.appendChild(sw);
      name.appendChild(document.createTextNode(facLabel(r.faction)));

      var rel = relationOf(r.relation);
      var badge = document.createElement('span');
      badge.className = 'war-relbadge ' + rel.cls;
      badge.textContent = rel.label;

      var bar = document.createElement('div');
      bar.className = 'rival-row__bar';
      var fill = document.createElement('div');
      fill.className = 'rival-row__fill';
      var pwr = (typeof r.power === 'number') ? r.power : 0;
      fill.style.width = Math.max(2, (pwr / max) * 100) + '%';
      bar.appendChild(fill);

      var pwrLabel = document.createElement('div');
      pwrLabel.className = 'rival-row__power';
      pwrLabel.textContent = fmtPower(pwr) + ' pwr';

      li.appendChild(name);
      li.appendChild(badge);
      li.appendChild(bar);
      li.appendChild(pwrLabel);
      ul.appendChild(li);
    });
  }

  // ── Intel feed ───────────────────────────────────────────────────────────
  function fmtTs(ts) {
    try {
      var d;
      if (typeof ts === 'number') d = new Date(ts > 1e12 ? ts : ts * 1000);
      else if (typeof ts === 'string' && ts) d = new Date(ts);
      else return '';
      if (isNaN(d.getTime())) return '';
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) { return ''; }
  }

  function decisionColor(dec) {
    if (dec && FACTION_COLORS.hasOwnProperty(dec.faction)) return facColor(dec.faction);
    if (dec && FACTION_COLORS.hasOwnProperty(dec.actor)) return facColor(dec.actor);
    return FACTION_COLORS.none;
  }

  function decisionSummary(dec) {
    if (!dec) return '';
    if (dec.summary) return dec.summary;
    if (dec.description) return dec.description;
    var bits = [];
    if (dec.action) bits.push(String(dec.action).replace(/_/g, ' '));
    if (dec.target) bits.push('→ ' + facLabel(dec.target));
    if (dec.district) bits.push('@ ' + facLabel(dec.district));
    return bits.join(' ');
  }

  function makeIntelItem(dec) {
    dec = dec || {};
    var color = decisionColor(dec);
    var li = document.createElement('li');
    li.className = 'intel-item';
    li.style.setProperty('--fc', color);

    var bar = document.createElement('div');
    bar.className = 'intel-item__bar';

    var main = document.createElement('div');
    main.className = 'intel-item__main';

    var top = document.createElement('div');
    top.className = 'intel-item__top';
    var kind = document.createElement('span');
    kind.className = 'intel-item__kind';
    kind.textContent = String(dec.kind || dec.action || dec.type || 'move').replace(/_/g, ' ');
    var ts = document.createElement('span');
    ts.className = 'intel-item__ts';
    ts.textContent = fmtTs(dec.ts || dec.timestamp || dec.time);
    top.appendChild(kind);
    top.appendChild(ts);

    var summary = document.createElement('div');
    summary.className = 'intel-item__summary';
    var actor = dec.faction || dec.actor;
    if (actor) {
      var a = document.createElement('span');
      a.className = 'intel-item__actor';
      a.textContent = facLabel(actor) + ' ';
      summary.appendChild(a);
    }
    summary.appendChild(document.createTextNode(decisionSummary(dec)));

    main.appendChild(top);
    main.appendChild(summary);
    li.appendChild(bar);
    li.appendChild(main);
    return li;
  }

  function renderIntel(decisions) {
    var ul = $('war-intel');
    if (!ul) return;
    clearChildren(ul);
    if (!decisions || !decisions.length) {
      ul.appendChild(emptyLi('listening for rival moves…'));
      return;
    }
    // Server returns recent decisions; render newest-first, capped.
    decisions.slice(0, INTEL_CAP).forEach(function (dec) {
      ul.appendChild(makeIntelItem(dec));
    });
  }

  function emptyLi(text) {
    var li = document.createElement('li');
    li.className = 'war-empty';
    li.textContent = text;
    return li;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Full state apply
  // ════════════════════════════════════════════════════════════════════════

  function applyState(state) {
    if (!state) return;
    lastState = state;

    // HUD: clock + allegiance label.
    var clock = state.clock || {};
    setText('hud-clock', clock.display || '--:--');
    setText('hud-allegiance', state.allegiance ? facLabel(state.allegiance) : 'NONE');

    if (!state.allegiance) {
      // Picker view.
      pendingFaction = null;
      renderPicker(state.factions || []);
      showView('picker');
      return;
    }

    // Dashboard view.
    pendingFaction = null;
    renderMyHead(state.my || {});
    renderTerritory(state.my || {}, state.wars);
    renderCrew((state.my && state.my.crews) || []);
    renderRivals(state.rivals || []);
    renderIntel(state.recent_decisions || []);
    showView('dash');
  }

  // ── Change allegiance affordance ──────────────────────────────────────────
  // The server owns allegiance; this UI just re-shows the picker overlaid with
  // the current factions so the player can re-pledge (the POST overwrites it).
  function onChangeAllegiance() {
    var factions = (lastState && lastState.rivals)
      ? buildPickerFromDashboard(lastState)
      : (lastState && lastState.factions) || [];
    pendingFaction = null;
    renderPicker(factions);
    setText('hud-allegiance', 'CHOOSING…');
    showView('picker');
    // Also pull a fresh factions list so the picker reflects live power/relations.
    fetch('/api/warroom/factions')
      .then(function (r) { return r.json(); })
      .then(function (data) { if (data && data.factions) renderPicker(data.factions); })
      .catch(function () { /* graceful: keep the derived list */ });
  }

  /** Derive a picker-shaped faction list from a dashboard state (fallback). */
  function buildPickerFromDashboard(state) {
    var list = [];
    if (state.my) {
      list.push({
        faction: state.my.faction,
        power: state.my.power,
        territory: state.my.territory,
        relations: 100
      });
    }
    (state.rivals || []).forEach(function (r) {
      list.push({ faction: r.faction, power: r.power, territory: [], relations: r.relation });
    });
    return list;
  }

  // ── Toasts ────────────────────────────────────────────────────────────────
  function toast(message, ok) {
    var wrap = $('war-toasts');
    if (!wrap || !message) return;
    var t = document.createElement('div');
    t.className = 'war-toast ' + (ok ? 'is-ok' : 'is-bad');
    t.textContent = message;
    wrap.appendChild(t);
    setTimeout(function () { t.classList.add('is-out'); }, 3200);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 3700);
  }

  // ── POST helper ─────────────────────────────────────────────────────────────
  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }

  // ── Link status ───────────────────────────────────────────────────────────
  function setLink(text, cls) {
    var el = $('hud-link');
    if (!el) return;
    el.textContent = text;
    el.classList.remove('is-live', 'is-down');
    if (cls) el.classList.add(cls);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Boot
  // ════════════════════════════════════════════════════════════════════════

  function seedFromRest() {
    fetch('/api/warroom/state')
      .then(function (r) { return r.json(); })
      .then(applyState)
      .catch(function (err) {
        console.warn('[war_room] /api/warroom/state fetch failed', err);
      });
  }

  function init() {
    var change = $('war-change');
    if (change) change.addEventListener('click', onChangeAllegiance);

    if (typeof io !== 'function') {
      console.warn('[war_room] Socket.IO client unavailable');
      setLink('offline', 'is-down');
      seedFromRest();
      return;
    }

    var socket = io();

    socket.on('connect', function () {
      console.log('[war_room] socket connected');
      setLink('online', 'is-live');
    });

    socket.on('disconnect', function () {
      console.log('[war_room] socket disconnected');
      setLink('reconnecting…', 'is-down');
    });

    // Full live dashboard state → re-render everything.
    socket.on('warroom_update', function (state) {
      applyState(state);
    });

    // Scene identity / clock (boot-page legacy event) — refresh the HUD clock.
    socket.on('state_update', function (s) {
      if (s && s.clock) setText('hud-clock', s.clock.display || '--:--');
    });

    // Seed REST in parallel so the UI paints immediately even before the first
    // socket push.
    seedFromRest();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
