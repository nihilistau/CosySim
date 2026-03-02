/**
 * THE GRID — grid.js  |  CosySim v0.75
 *
 * Handles: zone switching, market buy/sell, SVG city map, faction cards,
 * intel broker, 0xGH0ST terminal.  All Socket.IO world events routed here.
 */

"use strict";

/* ────────────────────────────────────────────────────────────────────────────
   Utilities
   ──────────────────────────────────────────────────────────────────────────── */

const $  = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function fmt(n) {
  return Number(n).toLocaleString("en-US");
}

function toast(msg, duration = 2500) {
  const el = document.getElementById("tx-toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("tx-toast--show");
  setTimeout(() => el.classList.remove("tx-toast--show"), duration);
}

function setFeedback(id, msg, color = "var(--grid-accent)") {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.style.color = color; }
}

/* ────────────────────────────────────────────────────────────────────────────
   Zone switching
   ──────────────────────────────────────────────────────────────────────────── */

function activateZone(zoneKey) {
  $$(".grid-tab").forEach(t => {
    const active = t.dataset.zone === zoneKey;
    t.classList.toggle("grid-tab--active", active);
    t.setAttribute("aria-selected", String(active));
  });
  $$(".grid-zone").forEach(z => {
    const active = z.id === `zone-${zoneKey}`;
    z.classList.toggle("grid-zone--active", active);
  });
  // Lazy-load zone content on first activation
  if (zoneKey === "station") loadStationMap();
  if (zoneKey === "den")     loadFactionData();
  if (zoneKey === "broker")  loadIntelFeed();
}

$$(".grid-tab").forEach(btn => {
  btn.addEventListener("click", () => activateZone(btn.dataset.zone));
});

/* ────────────────────────────────────────────────────────────────────────────
   MARKET ZONE
   ──────────────────────────────────────────────────────────────────────────── */

// Vendor filter
$$(".vendor-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".vendor-tab").forEach(b => b.classList.remove("vendor-tab--active"));
    btn.classList.add("vendor-tab--active");
    const vendor = btn.dataset.vendor;
    $$(".market-item").forEach(item => {
      item.style.display = (vendor === "all" || item.dataset.vendor === vendor) ? "" : "none";
    });
  });
});

// Buy button
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn--buy");
  if (!btn) return;
  btn.disabled = true;
  try {
    const res = await fetch("/api/market/buy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: btn.dataset.item, quantity: 1 }),
    });
    const data = await res.json();
    if (data.success) {
      toast(`Bought ${data.item} for ₵${fmt(data.paid)}`);
      updateStockDisplay(btn.dataset.item, data.remaining_stock);
      refreshInventory(data);
    } else {
      toast(`❌ ${data.error}`, 3000);
    }
  } catch (err) {
    toast("Network error", 2000);
  } finally {
    btn.disabled = false;
  }
});

function updateStockDisplay(itemId, stock) {
  const card = $(`.market-item[data-id="${itemId}"]`);
  if (!card) return;
  const stockEl = card.querySelector(".market-item__stock");
  if (stockEl) stockEl.textContent = `Stock: ${stock}`;
  const buyBtn = card.querySelector(".btn--buy");
  if (buyBtn && stock === 0) buyBtn.disabled = true;
}

function refreshInventory(/* optionally pass updated inventory */) {
  fetch("/api/market/items")
    .then(r => r.json())
    .then(data => renderInventory(data.inventory || []))
    .catch(() => {});
}

function renderInventory(inventory) {
  const list = document.getElementById("inventory-list");
  if (!list) return;
  if (!inventory.length) {
    list.innerHTML = `<p class="inventory-empty">Your inventory is empty.</p>`;
    return;
  }
  // Group by item_id
  const grouped = {};
  inventory.forEach(e => {
    if (!grouped[e.item_id]) grouped[e.item_id] = { name: e.name, qty: 0 };
    grouped[e.item_id].qty += e.qty;
  });
  list.innerHTML = Object.entries(grouped)
    .map(([id, g]) =>
      `<div class="inventory-item" data-item="${id}">
         ${g.name} × ${g.qty}
         <button class="btn" style="font-size:9px;padding:2px 6px;margin-left:6px;" data-sell="${id}">SELL</button>
       </div>`
    ).join("");
  // Sell handler
  list.querySelectorAll("[data-sell]").forEach(b => {
    b.addEventListener("click", async () => {
      const res = await fetch("/api/market/sell", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: b.dataset.sell, quantity: 1 }),
      });
      const data = await res.json();
      if (data.success) {
        toast(`Sold ${data.item} for ₵${fmt(data.earned)}`);
        refreshInventory();
      } else {
        toast(`❌ ${data.error}`, 3000);
      }
    });
  });
}

// On load, fetch inventory
refreshInventory();

/* ────────────────────────────────────────────────────────────────────────────
   STATION ZONE — SVG city map
   ──────────────────────────────────────────────────────────────────────────── */

let mapLoaded = false;

async function loadStationMap() {
  if (mapLoaded) return;
  mapLoaded = true;
  const listEl = document.getElementById("station-node-list");
  try {
    const res = await fetch("/api/station/map");
    const data = await res.json();
    renderCityMap(data.nodes);
    renderNodeList(data.nodes, listEl);
  } catch {
    if (listEl) listEl.innerHTML = `<p class="station-loading">Map unavailable.</p>`;
  }
}

function renderCityMap(nodes) {
  const g = document.getElementById("map-nodes");
  if (!g) return;
  g.innerHTML = "";
  nodes.forEach(node => {
    const status = node.is_current ? "current" : (node.online ? "online" : "offline");
    const r = node.is_current ? 3.5 : (node.online ? 2.8 : 2.2);
    const opacity = node.online || node.is_current ? 1 : 0.4;
    const accent = node.accent || "#00ff88";

    // Draw node
    const wrapper = document.createElementNS("http://www.w3.org/2000/svg", "g");
    wrapper.classList.add("map-node");
    wrapper.setAttribute("data-key", node.key);
    wrapper.style.opacity = opacity;
    if (!node.is_current && node.online) {
      wrapper.style.cursor = "pointer";
      wrapper.addEventListener("click", () => {
        window.location.href = `http://localhost:${node.port}`;
      });
    }

    // Pulse ring for online nodes
    if (node.online || node.is_current) {
      const pulse = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      pulse.setAttribute("cx", node.x);
      pulse.setAttribute("cy", node.y);
      pulse.setAttribute("r", r + 2);
      pulse.setAttribute("fill", "none");
      pulse.setAttribute("stroke", accent);
      pulse.setAttribute("stroke-width", "0.5");
      pulse.setAttribute("opacity", "0.3");
      pulse.style.animation = `mapPulse ${1.5 + Math.random()}s ease-in-out infinite alternate`;
      wrapper.appendChild(pulse);
    }

    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", node.x);
    circle.setAttribute("cy", node.y);
    circle.setAttribute("r", r);
    circle.setAttribute("fill", node.online || node.is_current ? accent : "#374151");
    if (node.online || node.is_current) {
      circle.style.filter = `drop-shadow(0 0 ${r}px ${accent})`;
    }
    wrapper.appendChild(circle);

    // Label
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", node.x);
    text.setAttribute("y", node.y + r + 4);
    text.setAttribute("text-anchor", "middle");
    text.classList.add("map-node-label");
    text.textContent = node.label.split(" ").slice(-1)[0]; // last word only
    wrapper.appendChild(text);

    g.appendChild(wrapper);
  });

  // Inject pulse keyframes if not already present
  if (!document.getElementById("map-pulse-style")) {
    const style = document.createElement("style");
    style.id = "map-pulse-style";
    style.textContent = `@keyframes mapPulse { from { opacity:0.1; r:3; } to { opacity:0.4; r:5; } }`;
    document.head.appendChild(style);
  }
}

function renderNodeList(nodes, listEl) {
  if (!listEl) return;
  const html = nodes.map(node => {
    const statusClass = node.is_current ? "current" : (node.online ? "online" : "offline");
    const dotClass    = node.is_current ? "dot--current" : (node.online ? "dot--online" : "dot--offline");
    const href = node.online && !node.is_current ? `http://localhost:${node.port}` : "#";
    const tag = node.online && !node.is_current ? "a" : "div";
    return `<${tag} class="station-node station-node--${statusClass}" href="${href}">
      <span class="station-node__dot ${dotClass}"></span>
      <span class="station-node__label">${node.label}</span>
      <span class="station-node__port">${node.port}</span>
    </${tag}>`;
  }).join("");
  listEl.innerHTML = html || `<p class="station-loading">No nodes found.</p>`;
}

document.getElementById("btn-refresh-map")?.addEventListener("click", () => {
  mapLoaded = false;
  loadStationMap();
});

/* ────────────────────────────────────────────────────────────────────────────
   DEN ZONE — factions
   ──────────────────────────────────────────────────────────────────────────── */

let denLoaded = false;

async function loadFactionData() {
  if (denLoaded) return;
  denLoaded = true;
  try {
    const res = await fetch("/api/faction/standings");
    const data = await res.json();
    renderFactionStandings(data.factions, data.quests);
  } catch {}
}

function renderFactionStandings(factions, quests) {
  factions.forEach(f => {
    const card = $(`.faction-card[data-faction="${f.id}"]`);
    if (!card) return;
    const fill = card.querySelector(`.faction-card__power-fill[data-faction="${f.id}"]`);
    const val  = document.getElementById(`fp-${f.id}`);
    if (fill) fill.style.width = `${f.power}%`;
    if (val)  val.textContent  = Math.round(f.power);
  });
  // Wire quest panels
  quests.forEach(q => {
    const panel = document.getElementById(`quest-${q.faction}`);
    if (!panel) return;
    panel.innerHTML = `
      <p class="quest-title">${q.title}</p>
      <p class="quest-desc">${q.desc}</p>
      <p class="quest-reward">Reward: ₵${fmt(q.reward_credits)} + ${q.reward_rep} REP${q.heat_cost ? ` (heat +${q.heat_cost})` : ""}</p>
    `;
  });
}

// Pledge
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn--pledge");
  if (!btn) return;
  const faction = btn.dataset.faction;
  btn.disabled = true;
  try {
    const res = await fetch("/api/faction/pledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ faction_id: faction }),
    });
    const data = await res.json();
    setFeedback("den-feedback", data.success ? data.message : `❌ ${data.error}`, data.success ? "#34d399" : "#f87171");
  } finally {
    btn.disabled = false;
  }
});

// Quest accept
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn--quest");
  if (!btn) return;
  const faction = btn.dataset.faction;
  const panel   = document.getElementById(`quest-${faction}`);
  if (panel) {
    panel.style.display = panel.style.display === "none" ? "" : "none";
    if (panel.style.display !== "none") {
      // Try to accept
      const res = await fetch("/api/faction/quest/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ faction_id: faction }),
      });
      const data = await res.json();
      if (!data.success) {
        setFeedback("den-feedback", data.error, "#f87171");
      }
    }
  }
});

/* ────────────────────────────────────────────────────────────────────────────
   BROKER ZONE — intel feed + ghost terminal
   ──────────────────────────────────────────────────────────────────────────── */

let brokerLoaded = false;

async function loadIntelFeed() {
  if (brokerLoaded) return;
  brokerLoaded = true;
  try {
    const res = await fetch("/api/broker/intel");
    const data = await res.json();
    renderIntelFeed(data.intel || []);
  } catch {}
}

function renderIntelFeed(entries) {
  const feed = document.getElementById("intel-feed");
  if (!feed) return;
  if (!entries.length) {
    feed.innerHTML = `<p class="intel-empty">No active intel…</p>`;
    return;
  }
  feed.innerHTML = entries.map(e => `
    <div class="intel-entry">
      <div class="intel-entry__type">${e.type || "intel"} · ${e.source || "unknown"}</div>
      <div class="intel-entry__title">${e.title || "Unnamed"}</div>
      <div class="intel-entry__desc">${(e.desc || "").substring(0, 120)}</div>
    </div>
  `).join("");
}

// Sell info
document.getElementById("btn-sell-info")?.addEventListener("click", async () => {
  const ta = document.getElementById("sell-info-text");
  const text = ta?.value.trim();
  if (!text) { setFeedback("sell-info-feedback", "Enter some intel first.", "#f87171"); return; }
  try {
    const res = await fetch("/api/broker/sell_info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    setFeedback("sell-info-feedback", data.success ? data.message : `❌ ${data.error}`, data.success ? "#4ade80" : "#f87171");
    if (data.success && ta) ta.value = "";
  } catch {
    setFeedback("sell-info-feedback", "Network error.", "#f87171");
  }
});

// Ghost terminal
document.getElementById("btn-ghost-msg")?.addEventListener("click", async () => {
  const output = document.getElementById("ghost-output");
  if (!output) return;
  output.innerHTML = `<p class="ghost-line ghost-line--typing">Decrypting transmission…</p>`;
  try {
    const res = await fetch("/api/broker/ghost_message");
    const data = await res.json();
    const messages = data.messages || ["No signal."];
    output.innerHTML = messages.map(m => `<p class="ghost-line">${m}</p>`).join("");
  } catch {
    output.innerHTML = `<p class="ghost-line">Signal lost.</p>`;
  }
});

/* ────────────────────────────────────────────────────────────────────────────
   Socket.IO — world events + real-time price updates
   ──────────────────────────────────────────────────────────────────────────── */

(function initSocket() {
  if (typeof io === "undefined") return;
  const socket = io({ reconnectionDelay: 2000 });

  socket.on("price_update", (data) => {
    if (!data.changes) return;
    data.changes.forEach(({ id, price, trend }) => {
      const val = document.querySelector(`.price-val[data-item="${id}"]`);
      if (!val) return;
      val.textContent = fmt(price);
      const priceEl = val.closest(".market-item__price");
      if (priceEl) {
        priceEl.className = `market-item__price${trend === "rising" ? " price--rising" : trend === "falling" ? " price--falling" : ""}`;
        const arrow = priceEl.querySelector(".price-trend");
        if (arrow) arrow.textContent = trend === "rising" ? "▲" : trend === "falling" ? "▼" : "━";
      }
      const buyBtn = document.querySelector(`.btn--buy[data-item="${id}"]`);
      if (buyBtn) buyBtn.textContent = `BUY ₵${fmt(price)}`;
    });
  });

  socket.on("intel_update", (data) => {
    if (data.intel) renderIntelFeed(data.intel);
  });

  socket.on("faction_update", () => {
    denLoaded = false;
    loadFactionData();
  });

  socket.on("inventory_update", (data) => {
    if (data.inventory) renderInventory(data.inventory);
  });

  socket.on("world_event", (data) => {
    const title = data.title || "City Event";
    toast(`⚡ ${title}`, 4000);
  });

  socket.on("hud_update", (data) => {
    if (data.credits !== undefined) {
      const el = document.getElementById("gs-credits");
      if (el) el.textContent = fmt(data.credits);
    }
    if (data.heat !== undefined) {
      const el = document.getElementById("gs-heat-val");
      if (el) el.textContent = Math.round(data.heat);
    }
    if (data.reputation !== undefined) {
      const el = document.getElementById("gs-rep");
      if (el) el.textContent = Math.round(data.reputation);
    }
    if (data.active_location) {
      const el = document.getElementById("gs-location");
      if (el) el.textContent = `📍 ${data.active_location}`;
    }
  });
})();
