/**
 * THE SHATTERED THRONE — realm.js
 * v0.68 "Dark Renaissance"
 *
 * ShatteredThroneScene — Socket.IO client, typewriter narrative,
 * stat bar transitions, sparks/smoke particles, spell casting.
 */

"use strict";

/* ═══════════════════════════════════════════════════════════════
   PARTICLE ENGINE — sparks + smoke
   ═══════════════════════════════════════════════════════════════ */
class RealmParticleEngine {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx    = canvas.getContext("2d");
    this.particles = [];
    this._resize();
    window.addEventListener("resize", () => this._resize());
  }

  _resize() {
    this.canvas.width  = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  /** Spawn emerald sparks at screen-center for level-up. */
  spawnSparks(count = 80) {
    const cx = this.canvas.width  / 2;
    const cy = this.canvas.height / 2;
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 2 + Math.random() * 6;
      this.particles.push({
        type: "spark",
        x: cx, y: cy,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - Math.random() * 3,
        life: 1.0,
        decay: 0.012 + Math.random() * 0.018,
        size: 2 + Math.random() * 3,
        color: `hsl(${150 + Math.random() * 30}, 90%, ${55 + Math.random() * 20}%)`,
        gravity: 0.12,
      });
    }
    if (!this._running) this._loop();
  }

  /** Spawn slow smoke wisps from bottom — atmospheric. */
  spawnSmoke(count = 6) {
    const w = this.canvas.width;
    const h = this.canvas.height;
    for (let i = 0; i < count; i++) {
      this.particles.push({
        type: "smoke",
        x: w * 0.1 + Math.random() * w * 0.8,
        y: h + 10,
        vx: (Math.random() - 0.5) * 0.4,
        vy: -(0.3 + Math.random() * 0.5),
        life: 0.45,
        decay: 0.0018 + Math.random() * 0.001,
        size: 18 + Math.random() * 30,
        color: "5,150,105",
      });
    }
    if (!this._running) this._loop();
  }

  _loop() {
    this._running = true;
    const tick = () => {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

      this.particles = this.particles.filter(p => p.life > 0.01);
      if (!this.particles.length) { this._running = false; return; }

      for (const p of this.particles) {
        p.x += p.vx;
        p.y += p.vy;
        p.life -= p.decay;

        if (p.type === "spark") {
          p.vy += p.gravity;
          this.ctx.save();
          this.ctx.globalAlpha = p.life;
          this.ctx.fillStyle   = p.color;
          this.ctx.shadowColor = p.color;
          this.ctx.shadowBlur  = 8;
          this.ctx.beginPath();
          this.ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
          this.ctx.fill();
          this.ctx.restore();
        } else {
          // smoke
          this.ctx.save();
          this.ctx.globalAlpha = p.life * 0.12;
          const grad = this.ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size);
          grad.addColorStop(0, `rgba(${p.color},0.8)`);
          grad.addColorStop(1, `rgba(${p.color},0)`);
          this.ctx.fillStyle = grad;
          this.ctx.beginPath();
          this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
          this.ctx.fill();
          this.ctx.restore();
        }
      }

      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}


/* ═══════════════════════════════════════════════════════════════
   SHATTERED THRONE SCENE
   ═══════════════════════════════════════════════════════════════ */
class ShatteredThroneScene {
  constructor() {
    this.socket     = null;
    this.state      = null;
    this.particles  = null;

    // Typewriter state
    this._twQueue   = [];
    this._twRunning = false;

    // DOM cache (populated in init)
    this.$  = {};
  }

  /* ── Bootstrap ──────────────────────────────────────────── */

  init() {
    this._cacheDOM();
    this._setupParticles();
    this._setupSocket();
    this._startSmokeAmbiance();
    console.info("[ShatteredThrone] Initialised — v0.68 Dark Renaissance");
  }

  _cacheDOM() {
    const ids = [
      "narrative-text", "narrative-cursor",
      "realm-choices",
      "stat-hp", "stat-hp-val",
      "stat-mp", "stat-mp-val",
      "stat-xp", "stat-xp-val",
      "stat-sanity", "stat-sanity-val",
      "sanity-stat-wrap",
      "active-arc-name", "arc-progress-fill",
      "player-title", "turn-counter",
      "patience-pip",
      "portrait-ring", "portrait-name", "portrait-location",
      "gold-val",
      "inventory-grid",
      "quest-title", "quest-objective", "quest-progress-bar", "quest-progress-label",
      "timeline-list",
      "level-up-overlay", "level-up-level",
      "scene-art", "scene-art-img", "scene-art-placeholder",
      "custom-input",
      "realm-bench-hud",
    ];
    ids.forEach(id => {
      this.$[id] = document.getElementById(id);
    });
    this.$.body = document.body;
  }

  _setupParticles() {
    const canvas = document.getElementById("realm-fx-canvas");
    if (canvas) this.particles = new RealmParticleEngine(canvas);
  }

  /* ── Socket.IO ──────────────────────────────────────────── */

  _setupSocket() {
    this.socket = io({ transports: ["websocket", "polling"] });

    this.socket.on("connect",       () => this._onConnect());
    this.socket.on("disconnect",    () => console.warn("[ShatteredThrone] Disconnected"));
    // v1.49.2 [2026-03-22] — Socket.IO reconnect feedback
    this.socket.io.on("reconnect", (attempt) => {
      console.debug("[ShatteredThrone] Reconnected after " + attempt + " attempt(s)");
    });
    this.socket.io.on("reconnect_attempt", (attempt) => {
      if (attempt % 3 === 0) console.debug("[ShatteredThrone] Reconnecting... (attempt " + attempt + ")");
    });
    this.socket.on("game_state",    d  => this._onFullState(d));
    this.socket.on("realm_state",   d  => this._onFullState(d));
    this.socket.on("turn_update",   d  => this._onFullState(d));

    this.socket.on("arc_started",   d  => this._onArcStarted(d));
    this.socket.on("arc_error",     d  => this._onError(d.error, "arc"));

    this.socket.on("choice_result", d  => this._onChoiceResult(d));
    this.socket.on("choice_error",  d  => this._onError(d.error, "choice"));

    this.socket.on("spell_cast",    d  => this._onSpellCast(d));
    this.socket.on("spell_error",   d  => this._onError(d.error, "spell"));

    this.socket.on("inventory_result", d => this._onInventoryResult(d));
    this.socket.on("inventory_error",  d => this._onError(d.error, "inventory"));

    this.socket.on("story_arcs",    d  => this._onStoryArcs(d));
    this.socket.on("level_up",      d  => this._onLevelUp(d));
    this.socket.on("player_death",  d  => this._onDeath(d));
    this.socket.on("game_started",  d  => this._onFullState(d.state || d));

    this.socket.on("combat_started", d => this._addTimeline("⚔ Combat begun!", "combat"));
    this.socket.on("combat_victory", d => this._addTimeline("🏆 Victory!", "combat"));
    this.socket.on("mutiny_started", () => this._addTimeline("⚡ MUTINY — Director gone rogue!", "arc"));
  }

  _onConnect() {
    console.info("[ShatteredThrone] Socket connected");
    this.loadState();
  }

  /* ── Public API ─────────────────────────────────────────── */

  loadState() {
    this.socket.emit("get_realm_state");
  }

  startArc(arcId) {
    if (!arcId) return;
    this.socket.emit("start_arc", { arc_id: arcId });
    this._addTimeline(`🌑 Arc started: ${arcId.replace(/_/g, " ")}`, "arc");
  }

  makeChoice(choiceId) {
    if (!choiceId) return;
    this._setChoicesDisabled(true);
    this.socket.emit("player_choice", { choice_id: choiceId });
  }

  castSpell(spellName) {
    const name = (spellName || "").trim();
    if (!name) return;
    // Visual feedback
    document.querySelectorAll(".spell-btn").forEach(b => {
      if (b.dataset.spell === name) b.classList.add("casting");
    });
    setTimeout(() => {
      document.querySelectorAll(".spell-btn").forEach(b => b.classList.remove("casting"));
    }, 1200);
    this.socket.emit("cast_spell", { spell: name });

    // Clear custom input
    const inp = document.getElementById("spell-custom-input");
    if (inp && inp.value === name) inp.value = "";
  }

  sendMessage(text) {
    const msg = (text || this.$["custom-input"]?.value || "").trim();
    if (!msg) return;
    this.socket.emit("player_choice", { choice_id: "__custom__", custom_text: msg });
    if (this.$["custom-input"]) this.$["custom-input"].value = "";
  }

  /** Inventory slot click handler (called from HTML). */
  static onSlotClick(slotEl) {
    const itemId = slotEl.dataset.itemId;
    if (!itemId) return;
    window.ShatteredThrone?.socket.emit("inventory_action", {
      action: "inspect",
      item_id: itemId,
    });
  }

  /* ── Socket event handlers ──────────────────────────────── */

  _onFullState(data) {
    if (!data) return;
    this.state = data;

    const ps = data.player_stats || {};
    this._updateStats(ps, data.sanity ?? 100);
    this._updateArc(data.arc);
    this._updateTurnCounter(data.turn_number || 0);
    this._updatePatience(data.director_patience ?? 100);
    this._updateLocation(data.current_location || "Unknown Lands");
    this._updateGold(ps.gold || 0);
    this._updateInventory(data.inventory || []);
    this._updateQuest(data.active_quest || (data.active_quests && data.active_quests[0]));
    this._updateWorldEvents(data.world_events || data.history || []);
  }

  _onArcStarted(data) {
    const arc = data.arc || {};
    this._updateArc(arc.id);
    this._addTimeline(`${arc.icon || "🌑"} ${arc.title || arc.id}`, "arc");
    if (data.narration) {
      this._typewriterReveal(data.narration, this.$["narrative-text"]);
    }
    if (data.choices?.length) {
      this._renderChoices(data.choices);
    }
    if (data.state) this._onFullState(data.state);
  }

  _onChoiceResult(data) {
    this._setChoicesDisabled(false);
    if (data.narration) {
      this._typewriterReveal(data.narration, this.$["narrative-text"]);
    }
    if (data.choices?.length) {
      this._renderChoices(data.choices);
    }
    if (data.state) this._onFullState(data.state);
  }

  _onSpellCast(data) {
    const note = `✦ ${data.spell} cast (${data.mp_cost} MP)`;
    this._addTimeline(note, "magic");
    if (data.narration) {
      this._typewriterReveal(data.narration, this.$["narrative-text"]);
    }
    if (data.choices?.length) {
      this._renderChoices(data.choices);
    }
    if (data.state) this._onFullState(data.state);
    // Sanity update
    if (typeof data.sanity === "number") {
      this._updateSanityBar(data.sanity);
    }
  }

  _onInventoryResult(data) {
    if (data.action === "inspect" && data.item) {
      console.info("[Inventory] Inspect:", data.item);
    }
  }

  _onStoryArcs(data) {
    console.info("[ShatteredThrone] Story arcs:", data.arcs);
  }

  _onLevelUp(data) {
    const lvl = data?.level || (this.state?.player_stats?.level ?? "?");
    if (this.$["level-up-level"]) this.$["level-up-level"].textContent = `Level ${lvl}`;
    if (this.$["level-up-overlay"]) {
      this.$["level-up-overlay"].classList.add("active");
      setTimeout(() => this.$["level-up-overlay"].classList.remove("active"), 3200);
    }
    if (this.particles) this.particles.spawnSparks(90);
    this._addTimeline(`🌟 Level up → ${lvl}!`, "arc");
  }

  _onDeath(data) {
    const msg = data?.cause ? `💀 Death: ${data.cause.slice(0, 60)}` : "💀 You have fallen…";
    this._addTimeline(msg, "combat");
    this._typewriterReveal("You have fallen… Darkness swallows you whole.", this.$["narrative-text"]);
  }

  _onError(message, context) {
    console.warn(`[ShatteredThrone:${context}] ${message}`);
  }

  /* ── UI Updaters ────────────────────────────────────────── */

  /**
   * Update all stat bars with transition + pop animation.
   * @param {Object} ps player_stats dict
   * @param {number} sanity 0-100
   */
  _updateStats(ps, sanity = 100) {
    const hp    = ps.hp    || 0;
    const maxHp = ps.max_hp || 100;
    const mp    = ps.mp    || 0;
    const maxMp = ps.max_mp || 50;
    const xp    = ps.xp    || 0;
    const xpNext = ps.xp_next || 100;

    this._setBar("stat-hp", hp, maxHp, `${hp} / ${maxHp}`);
    this._setBar("stat-mp", mp, maxMp, `${mp} / ${maxMp}`);
    this._setBar("stat-xp", xp, xpNext, `${xp} / ${xpNext}`);
    this._updateSanityBar(sanity);

    // Attributes
    this._setAttr("attr-str", ps.strength  || 10);
    this._setAttr("attr-agi", ps.agility   || 10);
    this._setAttr("attr-int", ps.intellect || 10);
    this._setAttr("attr-cha", ps.charisma  || 10);
    this._setAttr("attr-lck", ps.luck      || 10);
  }

  _setBar(barId, val, max, label) {
    const bar   = this.$[barId];
    const valEl = this.$[`${barId}-val`];
    if (!bar) return;
    const pct = max > 0 ? Math.min(100, Math.max(0, (val / max) * 100)) : 0;
    const prev = parseFloat(bar.style.width) || 0;
    bar.style.width = `${pct}%`;
    // Pop animation when value changes
    if (Math.abs(pct - prev) > 1) {
      bar.classList.remove("pop");
      void bar.offsetWidth; // reflow
      bar.classList.add("pop");
      setTimeout(() => bar.classList.remove("pop"), 400);
    }
    if (valEl) valEl.textContent = label;
  }

  _updateSanityBar(sanity) {
    this._setBar("stat-sanity", sanity, 100, `${sanity} / 100`);
    // Low sanity effect
    if (this.$.body) {
      this.$.body.classList.toggle("sanity-low", sanity < 30);
    }
  }

  _setAttr(elId, val) {
    const el = this.$[elId];
    if (el) el.querySelector("b").textContent = val;
  }

  _updateArc(arcId) {
    if (!arcId) return;
    const label = arcId.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
    if (this.$["active-arc-name"]) this.$["active-arc-name"].textContent = label;
    // Simulate progress (aesthetic)
    if (this.$["arc-progress-fill"]) {
      const pct = Math.min(100, ((this.state?.turn_number || 0) / 30) * 100);
      this.$["arc-progress-fill"].style.width = `${pct}%`;
    }
  }

  _updateTurnCounter(turn) {
    if (this.$["turn-counter"]) this.$["turn-counter"].textContent = `Turn ${turn}`;
  }

  _updatePatience(patience) {
    const pip = this.$["patience-pip"];
    if (!pip) return;
    pip.classList.toggle("danger",  patience < 25);
    pip.classList.toggle("warning", patience >= 25 && patience < 55);
    pip.title = `Director Patience: ${Math.round(patience)}/100`;
  }

  _updateLocation(location) {
    if (this.$["portrait-location"]) this.$["portrait-location"].textContent = location;
  }

  _updateGold(gold) {
    if (this.$["gold-val"]) this.$["gold-val"].textContent = gold;
  }

  _updateInventory(items) {
    const grid = this.$["inventory-grid"];
    if (!grid) return;
    const slots = grid.querySelectorAll(".inventory-slot");
    slots.forEach((slot, i) => {
      const item = items[i];
      if (item) {
        slot.classList.add("occupied");
        slot.dataset.itemId = item.id || item.name;
        const iconEl = slot.querySelector(".inventory-slot__icon");
        if (iconEl) iconEl.textContent = this._itemEmoji(item.type || "misc");
        // Tooltip
        let tip = slot.querySelector(".inventory-slot__tooltip");
        if (!tip) {
          tip = document.createElement("span");
          tip.className = "inventory-slot__tooltip";
          slot.appendChild(tip);
        }
        tip.textContent = item.name;
      } else {
        slot.classList.remove("occupied");
        delete slot.dataset.itemId;
        const iconEl = slot.querySelector(".inventory-slot__icon");
        if (iconEl) iconEl.textContent = "·";
        const tip = slot.querySelector(".inventory-slot__tooltip");
        if (tip) tip.remove();
      }
    });
  }

  _itemEmoji(type) {
    const map = {
      weapon: "⚔",  armor: "🛡",   potion: "🧪",
      scroll: "📜",  key: "🗝",     gold: "🪙",
      food: "🍞",    misc: "💎",    quest: "📋",
      magic: "✨",   cursed: "☠",   relic: "🏺",
    };
    return map[type] || "💎";
  }

  _updateQuest(quest) {
    if (!quest) return;
    if (this.$["quest-title"])         this.$["quest-title"].textContent = quest.title || "Unknown";
    if (this.$["quest-objective"])     this.$["quest-objective"].textContent = quest.objective || "—";
    const progress = quest.progress || 0;
    const target   = quest.target   || 1;
    const pct = Math.min(100, (progress / target) * 100);
    if (this.$["quest-progress-bar"])   this.$["quest-progress-bar"].style.width = `${pct}%`;
    if (this.$["quest-progress-label"]) this.$["quest-progress-label"].textContent = `${progress} / ${target}`;
  }

  _updateWorldEvents(events) {
    const list = this.$["timeline-list"];
    if (!list || !events?.length) return;
    // Keep newest 8 events
    const recent = events.slice(-8).reverse();
    // Only update if changed
    const newHtml = recent.map(e => {
      const text = typeof e === "string" ? e : (e.narration || e.text || JSON.stringify(e)).slice(0, 80);
      return `<li class="timeline-item">${this._escapeHtml(text)}</li>`;
    }).join("");
    if (list.innerHTML !== newHtml) list.innerHTML = newHtml;
  }

  /* ── Typewriter ─────────────────────────────────────────── */

  /**
   * Reveal text character-by-character into `element`.
   * Queues multiple reveals — runs sequentially.
   */
  _typewriterReveal(text, element) {
    if (!text || !element) return;
    this._twQueue.push({ text, element });
    if (!this._twRunning) this._twStep();
  }

  _twStep() {
    if (!this._twQueue.length) {
      this._twRunning = false;
      return;
    }
    this._twRunning = true;
    const { text, element } = this._twQueue.shift();

    // Show cursor
    const cursor = this.$["narrative-cursor"];
    if (cursor) cursor.classList.remove("hidden");

    // Place portrait ring into speaking mode
    const ring = this.$["portrait-ring"];
    if (ring) ring.classList.add("speaking");

    // Clear existing text (preserve cursor node)
    while (element.firstChild && element.firstChild !== cursor) {
      element.removeChild(element.firstChild);
    }

    let i = 0;
    const SPEED = 22; // ms per char

    const type = () => {
      if (i < text.length) {
        const char = text[i++];
        const node = document.createTextNode(char);
        element.insertBefore(node, cursor);
        element.parentElement?.scrollTo({ top: element.parentElement.scrollHeight, behavior: "smooth" });
        setTimeout(type, SPEED + (char === "." || char === "!" || char === "?" ? 200 : 0));
      } else {
        // Done
        if (cursor) cursor.classList.add("hidden");
        if (ring)   ring.classList.remove("speaking");
        setTimeout(() => this._twStep(), 120);
      }
    };
    type();
  }

  /* ── Choice Rendering ───────────────────────────────────── */

  _renderChoices(choices) {
    const container = this.$["realm-choices"];
    if (!container) return;
    container.innerHTML = "";
    choices.forEach(choice => {
      const btn = document.createElement("button");
      btn.className = "choice-btn";
      btn.dataset.choiceId = choice.id;

      const mainText = document.createTextNode(choice.text || choice.id);
      btn.appendChild(mainText);

      if (choice.hint || choice.consequence) {
        const hint = document.createElement("span");
        hint.className = "choice-hint";
        hint.textContent = choice.hint || choice.consequence;
        btn.appendChild(hint);
      }

      btn.addEventListener("click", () => this.makeChoice(choice.id));
      container.appendChild(btn);
    });
  }

  _setChoicesDisabled(disabled) {
    const container = this.$["realm-choices"];
    if (!container) return;
    container.querySelectorAll(".choice-btn").forEach(b => {
      b.disabled = disabled;
      b.style.opacity = disabled ? "0.5" : "1";
    });
  }

  /* ── Timeline ───────────────────────────────────────────── */

  _addTimeline(text, type = "") {
    const list = this.$["timeline-list"];
    if (!list) return;
    const li = document.createElement("li");
    li.className = `timeline-item${type ? ` timeline-item--${type}` : ""}`;
    li.textContent = text;
    list.insertBefore(li, list.firstChild);
    // Cap at 10 items
    while (list.children.length > 10) list.removeChild(list.lastChild);
  }

  /* ── Smoke ambiance ─────────────────────────────────────── */

  _startSmokeAmbiance() {
    if (!this.particles) return;
    const spawnSmoke = () => {
      if (this.particles) this.particles.spawnSmoke(3);
      setTimeout(spawnSmoke, 4000 + Math.random() * 3000);
    };
    setTimeout(spawnSmoke, 2000);
  }

  /* ── Helpers ────────────────────────────────────────────── */

  _escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

/* ─── Export for inline onclick handlers ─── */
window.ShatteredThroneScene = ShatteredThroneScene;
