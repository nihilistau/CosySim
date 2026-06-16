/**
 * THE GRID — Extension Module
 * ============================
 *
 * Game logic extensions for the Kit-generated GridScene class.
 * Adds: zone switching, market buy/sell, SVG city map, faction cards,
 * intel broker, 0xGH0ST terminal, Socket.IO world event handlers.
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Refactored from grid.js to extension pattern.
 *                            GridScene.prototype methods, _initExtensions hook.
 *   v1.49.2 [2026-03-21] — API-first: market items + faction cards rendered
 *                            client-side via fetch. No Jinja2 data dependencies.
 *   v0.75   [2026-03-20] — Initial Grid scene JS
 *
 * CONNECTS: GridScene (grid_kit.js), Socket.IO, REST APIs
 * CALLED BY: GridScene.init() → _initExtensions()
 */

'use strict';

// ── Utilities ────────────────────────────────────────────────────────

const $  = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function fmt(n) {
  return Number(n).toLocaleString('en-US');
}

function setFeedback(id, msg, color = 'var(--grid-accent)') {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.style.color = color; }
}

// ── Extension entry point ────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Hooked by Kit-generated init() via _initExtensions

GridScene.prototype._initExtensions = function() {
  this._initZoneSwitching();
  this._initMarket();
  this._initStation();
  this._initDen();
  this._initBroker();
  this._initWorldSocket();
};

// ── Zone Switching ───────────────────────────────────────────────────

GridScene.prototype._initZoneSwitching = function() {
  $$('.grid-tab').forEach(btn => {
    btn.addEventListener('click', () => this._activateZone(btn.dataset.zone));
  });
};

GridScene.prototype._activateZone = function(zoneKey) {
  $$('.grid-tab').forEach(t => {
    const active = t.dataset.zone === zoneKey;
    t.classList.toggle('grid-tab--active', active);
    t.setAttribute('aria-selected', String(active));
  });
  $$('.grid-zone').forEach(z => {
    z.classList.toggle('grid-zone--active', z.id === `zone-${zoneKey}`);
  });
  // Lazy-load zone content on first activation
  if (zoneKey === 'station') this._loadStationMap();
  if (zoneKey === 'den')     this._loadFactionData();
  if (zoneKey === 'broker')  this._loadIntelFeed();
};

// ── MARKET ZONE ──────────────────────────────────────────────────────
// v1.49.2 [2026-03-21] — Client-side market item renderer (API-first)
// CONNECTS: /api/market/items, #market-grid
// CALLED BY: _initMarket on page load
// EMITS: DOM for .market-item cards with buy buttons

GridScene.prototype._initMarket = function() {
  this._loadMarketItems();
  this._loadInventory_ext();

  // v1.63.0 [2026-06-16] — D-T1 "The Exchange": poll the live engine Market so
  // Grid prices (and ▲/▼ trend) move as the economy ticks / NPCs trade, even
  // when no Socket.IO push arrives. Re-renders silently in the background.
  if (this._marketPollTimer) clearInterval(this._marketPollTimer);
  this._marketPollTimer = setInterval(() => { this._loadMarketItems(); }, 15000);

  // Vendor filter tabs
  $$('.vendor-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.vendor-tab').forEach(b => b.classList.remove('vendor-tab--active'));
      btn.classList.add('vendor-tab--active');
      const vendor = btn.dataset.vendor;
      $$('.market-item').forEach(item => {
        item.style.display = (vendor === 'all' || item.dataset.vendor === vendor) ? '' : 'none';
      });
    });
  });

  // Buy button (delegated)
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn--buy');
    if (!btn) return;
    btn.disabled = true;
    try {
      const res = await fetch('/api/market/buy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: btn.dataset.item, quantity: 1 }),
      });
      const data = await res.json();
      if (data.success) {
        this._showToast(`Bought ${data.item} for \u20B5${fmt(data.paid)}`);
        this._updateStockDisplay(btn.dataset.item, data.remaining_stock);
        this._loadInventory_ext();
      } else {
        this._showToast(`\u274C ${data.error}`, 'danger');
      }
    } catch {
      this._showToast('Network error', 'danger');
    } finally {
      btn.disabled = false;
    }
  });
};

GridScene.prototype._loadMarketItems = async function() {
  try {
    const res = await fetch('/api/market/items');
    const data = await res.json();
    this._renderMarketItems(data.items || []);
    this._renderInventory_ext(data.inventory || []);
  } catch {
    const grid = document.getElementById('market-grid');
    if (grid) grid.innerHTML = '<p class="inventory-empty">Failed to load market.</p>';
  }
};

GridScene.prototype._renderMarketItems = function(items) {
  const grid = document.getElementById('market-grid');
  if (!grid) return;
  if (!items || !items.length) {
    grid.innerHTML = '<p class="inventory-empty">Market is empty.</p>';
    return;
  }
  grid.innerHTML = items.map(item => {
    const trendCls = item.trend === 'rising' ? ' price--rising' : item.trend === 'falling' ? ' price--falling' : '';
    const trendIcon = item.trend === 'rising' ? '\u25B2' : item.trend === 'falling' ? '\u25BC' : '\u2501';
    return `<div class="market-item" data-vendor="${item.vendor}" data-id="${item.id}" data-rarity="${item.rarity}">
      <div class="market-item__header">
        <span class="market-item__name">${item.name}</span>
        <span class="market-item__rarity rarity--${item.rarity}">${item.rarity}</span>
      </div>
      <div class="market-item__body">
        <div class="market-item__price${trendCls}">
          <span class="price-symbol">\u20B5</span>
          <span class="price-val" data-item="${item.id}">${fmt(item.price)}</span>
          <span class="price-trend">${trendIcon}</span>
        </div>
        <div class="market-item__stock">Stock: ${item.stock}</div>
      </div>
      <div class="market-item__actions">
        <button class="btn btn--buy" data-item="${item.id}" data-price="${item.price}" ${item.stock === 0 ? 'disabled' : ''}>
          BUY \u20B5${fmt(item.price)}
        </button>
      </div>
    </div>`;
  }).join('');
};

GridScene.prototype._updateStockDisplay = function(itemId, stock) {
  const card = $(`.market-item[data-id="${itemId}"]`);
  if (!card) return;
  const stockEl = card.querySelector('.market-item__stock');
  if (stockEl) stockEl.textContent = `Stock: ${stock}`;
  const buyBtn = card.querySelector('.btn--buy');
  if (buyBtn && stock === 0) buyBtn.disabled = true;
};

GridScene.prototype._loadInventory_ext = async function() {
  try {
    const res = await fetch('/api/market/items');
    const data = await res.json();
    this._renderInventory_ext(data.inventory || []);
  } catch {}
};

GridScene.prototype._renderInventory_ext = function(inventory) {
  const list = document.getElementById('inventory-list');
  if (!list) return;
  if (!inventory.length) {
    list.innerHTML = '<p class="inventory-empty">Your inventory is empty.</p>';
    return;
  }
  const grouped = {};
  inventory.forEach(e => {
    if (!grouped[e.item_id]) grouped[e.item_id] = { name: e.name, qty: 0 };
    grouped[e.item_id].qty += e.qty;
  });
  list.innerHTML = Object.entries(grouped)
    .map(([id, g]) =>
      `<div class="inventory-item" data-item="${id}">
         ${g.name} \u00D7 ${g.qty}
         <button class="btn" style="font-size:9px;padding:2px 6px;margin-left:6px;" data-sell="${id}">SELL</button>
       </div>`
    ).join('');
  // Sell handler
  list.querySelectorAll('[data-sell]').forEach(b => {
    b.addEventListener('click', async () => {
      const res = await fetch('/api/market/sell', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: b.dataset.sell, quantity: 1 }),
      });
      const data = await res.json();
      if (data.success) {
        this._showToast(`Sold ${data.item} for \u20B5${fmt(data.earned)}`);
        this._loadInventory_ext();
      } else {
        this._showToast(`\u274C ${data.error}`, 'danger');
      }
    });
  });
};

// ── STATION ZONE — SVG city map ──────────────────────────────────────

GridScene.prototype._stationLoaded = false;

GridScene.prototype._initStation = function() {
  document.getElementById('btn-refresh-map')?.addEventListener('click', () => {
    this._stationLoaded = false;
    this._loadStationMap();
  });
};

GridScene.prototype._loadStationMap = async function() {
  if (this._stationLoaded) return;
  this._stationLoaded = true;
  const listEl = document.getElementById('station-node-list');
  try {
    const res = await fetch('/api/station/map');
    const data = await res.json();
    this._renderCityMap(data.nodes);
    this._renderNodeList(data.nodes, listEl);
  } catch {
    if (listEl) listEl.innerHTML = '<p class="station-loading">Map unavailable.</p>';
  }
};

GridScene.prototype._renderCityMap = function(nodes) {
  const g = document.getElementById('map-nodes');
  if (!g) return;
  g.innerHTML = '';
  nodes.forEach(node => {
    const r = node.is_current ? 3.5 : (node.online ? 2.8 : 2.2);
    const opacity = node.online || node.is_current ? 1 : 0.4;
    const accent = node.accent || '#00ff88';

    const wrapper = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    wrapper.classList.add('map-node');
    wrapper.setAttribute('data-key', node.key);
    wrapper.style.opacity = opacity;
    if (!node.is_current && node.online) {
      wrapper.style.cursor = 'pointer';
      wrapper.addEventListener('click', () => {
        window.location.href = `http://localhost:${node.port}`;
      });
    }

    if (node.online || node.is_current) {
      const pulse = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      pulse.setAttribute('cx', node.x);
      pulse.setAttribute('cy', node.y);
      pulse.setAttribute('r', r + 2);
      pulse.setAttribute('fill', 'none');
      pulse.setAttribute('stroke', accent);
      pulse.setAttribute('stroke-width', '0.5');
      pulse.setAttribute('opacity', '0.3');
      pulse.style.animation = `mapPulse ${1.5 + Math.random()}s ease-in-out infinite alternate`;
      wrapper.appendChild(pulse);
    }

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', node.x);
    circle.setAttribute('cy', node.y);
    circle.setAttribute('r', r);
    circle.setAttribute('fill', node.online || node.is_current ? accent : '#374151');
    if (node.online || node.is_current) {
      circle.style.filter = `drop-shadow(0 0 ${r}px ${accent})`;
    }
    wrapper.appendChild(circle);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', node.x);
    text.setAttribute('y', node.y + r + 4);
    text.setAttribute('text-anchor', 'middle');
    text.classList.add('map-node-label');
    text.textContent = node.label.split(' ').slice(-1)[0];
    wrapper.appendChild(text);

    g.appendChild(wrapper);
  });

  if (!document.getElementById('map-pulse-style')) {
    const style = document.createElement('style');
    style.id = 'map-pulse-style';
    style.textContent = '@keyframes mapPulse { from { opacity:0.1; r:3; } to { opacity:0.4; r:5; } }';
    document.head.appendChild(style);
  }
};

GridScene.prototype._renderNodeList = function(nodes, listEl) {
  if (!listEl) return;
  const html = nodes.map(node => {
    const statusClass = node.is_current ? 'current' : (node.online ? 'online' : 'offline');
    const dotClass    = node.is_current ? 'dot--current' : (node.online ? 'dot--online' : 'dot--offline');
    const href = node.online && !node.is_current ? `http://localhost:${node.port}` : '#';
    const tag = node.online && !node.is_current ? 'a' : 'div';
    return `<${tag} class="station-node station-node--${statusClass}" href="${href}">
      <span class="station-node__dot ${dotClass}"></span>
      <span class="station-node__label">${node.label}</span>
      <span class="station-node__port">${node.port}</span>
    </${tag}>`;
  }).join('');
  listEl.innerHTML = html || '<p class="station-loading">No nodes found.</p>';
};

// ── DEN ZONE — factions ──────────────────────────────────────────────
// v1.49.2 [2026-03-21] — Client-side faction card renderer (API-first)

GridScene.prototype._denLoaded = false;

GridScene.prototype._initDen = function() {
  // Pledge (delegated)
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn--pledge');
    if (!btn) return;
    const faction = btn.dataset.faction;
    btn.disabled = true;
    try {
      const res = await fetch('/api/faction/pledge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ faction_id: faction }),
      });
      const data = await res.json();
      setFeedback('den-feedback', data.success ? data.message : `\u274C ${data.error}`, data.success ? '#34d399' : '#f87171');
    } finally {
      btn.disabled = false;
    }
  });

  // Quest toggle (delegated)
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn--quest');
    if (!btn) return;
    const faction = btn.dataset.faction;
    const panel = document.getElementById(`quest-${faction}`);
    if (panel) {
      panel.style.display = panel.style.display === 'none' ? '' : 'none';
      if (panel.style.display !== 'none') {
        const res = await fetch('/api/faction/quest/accept', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ faction_id: faction }),
        });
        const data = await res.json();
        if (!data.success) {
          setFeedback('den-feedback', data.error, '#f87171');
        }
      }
    }
  });
};

GridScene.prototype._loadFactionData = async function() {
  if (this._denLoaded) return;
  this._denLoaded = true;
  try {
    const res = await fetch('/api/faction/standings');
    const data = await res.json();
    this._renderFactionCards(data.factions || [], data.quests || []);
  } catch {}
};

GridScene.prototype._renderFactionCards = function(factions, quests) {
  const grid = document.getElementById('den-grid');
  if (!grid) return;
  if (!factions || !factions.length) {
    grid.innerHTML = '<p class="inventory-empty">No faction data available.</p>';
    return;
  }
  grid.innerHTML = factions.map(f => `
    <div class="faction-card" data-faction="${f.id}" style="--faction-accent:${f.accent || '#00ff88'};">
      <div class="faction-card__header">
        <span class="faction-card__name">${f.label || f.id}</span>
        <span class="faction-card__arch">${f.archetype || ''}</span>
      </div>
      <div class="faction-card__power-wrap">
        <div class="faction-card__power-bar">
          <div class="faction-card__power-fill" data-faction="${f.id}" style="width:${f.power || 50}%"></div>
        </div>
        <span class="faction-card__power-val" id="fp-${f.id}">${Math.round(f.power || 50)}</span>
      </div>
      <div class="faction-card__actions">
        <button class="btn btn--pledge" data-faction="${f.id}">PLEDGE \u2191</button>
        <button class="btn btn--quest" data-faction="${f.id}">QUEST \u25B6</button>
      </div>
      <div class="faction-quest-panel" id="quest-${f.id}" style="display:none">
        <p class="quest-loading">Loading quest\u2026</p>
      </div>
    </div>
  `).join('');

  if (quests) {
    quests.forEach(q => {
      const panel = document.getElementById(`quest-${q.faction}`);
      if (!panel) return;
      panel.innerHTML = `
        <p class="quest-title">${q.title}</p>
        <p class="quest-desc">${q.desc}</p>
        <p class="quest-reward">Reward: \u20B5${fmt(q.reward_credits)} + ${q.reward_rep} REP${q.heat_cost ? ` (heat +${q.heat_cost})` : ''}</p>
      `;
    });
  }
};

// ── BROKER ZONE — intel feed + ghost terminal ────────────────────────

GridScene.prototype._brokerLoaded = false;

GridScene.prototype._initBroker = function() {
  // Sell info
  document.getElementById('btn-sell-info')?.addEventListener('click', async () => {
    const ta = document.getElementById('sell-info-text');
    const text = ta?.value.trim();
    if (!text) { setFeedback('sell-info-feedback', 'Enter some intel first.', '#f87171'); return; }
    try {
      const res = await fetch('/api/broker/sell_info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      setFeedback('sell-info-feedback', data.success ? data.message : `\u274C ${data.error}`, data.success ? '#4ade80' : '#f87171');
      if (data.success && ta) ta.value = '';
    } catch {
      setFeedback('sell-info-feedback', 'Network error.', '#f87171');
    }
  });

  // Ghost terminal
  document.getElementById('btn-ghost-msg')?.addEventListener('click', async () => {
    const output = document.getElementById('ghost-output');
    if (!output) return;
    output.innerHTML = '<p class="ghost-line ghost-line--typing">Decrypting transmission\u2026</p>';
    try {
      const res = await fetch('/api/broker/ghost_message');
      const data = await res.json();
      const messages = data.messages || ['No signal.'];
      output.innerHTML = messages.map(m => `<p class="ghost-line">${m}</p>`).join('');
    } catch {
      output.innerHTML = '<p class="ghost-line">Signal lost.</p>';
    }
  });
};

GridScene.prototype._loadIntelFeed = async function() {
  if (this._brokerLoaded) return;
  this._brokerLoaded = true;
  try {
    const res = await fetch('/api/broker/intel');
    const data = await res.json();
    this._renderIntelFeed(data.intel || []);
  } catch {}
};

GridScene.prototype._renderIntelFeed = function(entries) {
  const feed = document.getElementById('intel-feed');
  if (!feed) return;
  if (!entries.length) {
    feed.innerHTML = '<p class="intel-empty">No active intel\u2026</p>';
    return;
  }
  feed.innerHTML = entries.map(e => `
    <div class="intel-entry">
      <div class="intel-entry__type">${e.type || 'intel'} \u00B7 ${e.source || 'unknown'}</div>
      <div class="intel-entry__title">${e.title || 'Unnamed'}</div>
      <div class="intel-entry__desc">${(e.desc || '').substring(0, 120)}</div>
    </div>
  `).join('');
};

// ── Socket.IO — world events + real-time price updates ───────────────
// v1.50.0 [2026-03-22] — Uses Kit-provided this.socket instead of standalone

GridScene.prototype._initWorldSocket = function() {
  if (!this.socket) return;

  this.socket.on('price_update', (data) => {
    if (!data.changes) return;
    data.changes.forEach(({ id, price, trend }) => {
      const val = document.querySelector(`.price-val[data-item="${id}"]`);
      if (!val) return;
      val.textContent = fmt(price);
      const priceEl = val.closest('.market-item__price');
      if (priceEl) {
        priceEl.className = `market-item__price${trend === 'rising' ? ' price--rising' : trend === 'falling' ? ' price--falling' : ''}`;
        const arrow = priceEl.querySelector('.price-trend');
        if (arrow) arrow.textContent = trend === 'rising' ? '\u25B2' : trend === 'falling' ? '\u25BC' : '\u2501';
      }
      const buyBtn = document.querySelector(`.btn--buy[data-item="${id}"]`);
      if (buyBtn) buyBtn.textContent = `BUY \u20B5${fmt(price)}`;
    });
  });

  this.socket.on('intel_update', (data) => {
    if (data.intel) this._renderIntelFeed(data.intel);
  });

  this.socket.on('faction_update', () => {
    this._denLoaded = false;
    this._loadFactionData();
  });

  this.socket.on('inventory_update', (data) => {
    if (data.inventory) this._renderInventory_ext(data.inventory);
  });

  this.socket.on('world_event', (data) => {
    const title = data.title || 'City Event';
    this._showToast(`\u26A1 ${title}`);
  });

  this.socket.on('hud_update', (data) => {
    if (data.credits !== undefined) {
      const el = document.getElementById('badge-val-credits');
      if (el) el.textContent = fmt(data.credits);
    }
    if (data.heat !== undefined) {
      const el = document.getElementById('badge-val-heat');
      if (el) el.textContent = Math.round(data.heat) + '%';
    }
    if (data.reputation !== undefined) {
      const el = document.getElementById('badge-val-rep');
      if (el) el.textContent = Math.round(data.reputation);
    }
    if (data.active_location) {
      const el = document.getElementById('badge-val-location');
      if (el) el.textContent = data.active_location;
    }
  });
};
