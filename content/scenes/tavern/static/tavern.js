/**
 * THE RUSTY ANCHOR — tavern.js
 * =============================
 *
 * Standalone RustyAnchorScene class — Socket.IO client, dice animation,
 * quest board, embers particle system.
 *
 * NOTE: The active scene template (tavern.html) uses TavernScene (tavern_kit.js)
 * + extensions (tavern_ext.js). This file is retained as a fallback/reference
 * implementation. Visual polish changes (stat bars, dice wow, rumor stagger)
 * are applied in tavern_ext.js for the live scene.
 *
 * Version: v1.57.3 [2026-05-12]
 * Change Log:
 *   v1.57.3 [2026-05-12] — Header updated; stat bar CSS var approach,
 *                           dice wow (screen shake + bloom), rumor stagger.
 *                           Functional polish applied in tavern_ext.js.
 *   v0.68   [2026-03-22] — "Dark Renaissance". Embers, quest board, dice.
 */

"use strict";

class RustyAnchorScene {
  constructor() {
    /** @type {SocketIO.Socket|null} */
    this.socket = null;
    /** @type {Object} Current tavern state snapshot */
    this.state = {};
    /** @type {string|null} Quest ID staged for acceptance */
    this._pendingQuestId = null;
    /** @type {ReturnType<setInterval>|null} */
    this._embersTimer = null;
    /** @type {CanvasRenderingContext2D|null} */
    this._embersCtx = null;
    /** @type {Array<Ember>} */
    this._embers = [];
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Init
  // ─────────────────────────────────────────────────────────────────────────

  init() {
    this._setupSocket();
    this._setupUI();
    this._startEmbers();
    this.loadState();
    this.getQuestBoard();
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Socket.IO
  // ─────────────────────────────────────────────────────────────────────────

  _setupSocket() {
    this.socket = io({ transports: ["websocket", "polling"] });

    this.socket.on("connect", () => {
      this._addChatLine("⚓ Connected to The Rusty Anchor.", "system");
      this.loadState();
    });

    this.socket.on("disconnect", () => {
      this._addChatLine("⚠️ Lost connection. Reconnecting…", "system");
    });

    // Full state sync
    this.socket.on("state_update", (data) => this._applyState(data));
    this.socket.on("tavern_state", (data) => this._applyState(data));

    // Quest board
    this.socket.on("quest_board", ({ quests }) => {
      this._renderQuestBoard(quests || []);
    });

    // Quest accepted
    this.socket.on("quest_started", (data) => {
      this._addChatLine(
        `📜 Quest started: ${data.title} — ${data.objective}  (Reward: ${data.reward_gold}g)`,
        "action"
      );
      this._setActiveQuest(data);
      this._showToast(`⚔️ Quest accepted!\n${data.title}`);
    });

    // Dice result
    this.socket.on("dice_result", (data) => {
      this._animateDiceRoll(data);
    });

    // Drink
    this.socket.on("drink_result", ({ result }) => {
      this._addChatLine(result.split("\n")[0], "result");
      this._showToast(result);
      // Re-fetch full state
      this.loadState();
    });

    // Rumor / investigation
    this.socket.on("rumor_investigated", ({ rumor_id, clues }) => {
      this._addChatLine(`🔍 Rumor "${rumor_id}" added to investigation board. Clues: ${clues}`, "action");
      const countEl = document.getElementById("investigation-count");
      const clueEl = document.getElementById("clue-count");
      if (countEl) countEl.classList.remove("hidden");
      if (clueEl) clueEl.textContent = clues;
    });

    // Generic event feed
    this.socket.on("event", ({ text }) => {
      if (text) this._addChatLine(text, "system");
    });

    this.socket.on("consequence", ({ description }) => {
      if (description) this._addChatLine(`⚡ ${description}`, "system");
    });

    this.socket.on("error", ({ message }) => {
      this._showToast(`⚠️ ${message}`);
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // UI wiring
  // ─────────────────────────────────────────────────────────────────────────

  _setupUI() {
    // Roll dice button
    const btnRoll = document.getElementById("btn-roll");
    if (btnRoll) {
      btnRoll.addEventListener("click", () => {
        const sides = parseInt(document.getElementById("dice-sides")?.value || "20", 10);
        const reason = document.getElementById("dice-reason")?.value.trim() || "skill check";
        this.rollDice(sides, reason);
      });
    }

    // Drink buttons
    document.querySelectorAll(".drink-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const drink = btn.dataset.drink;
        if (drink) this._orderDrink(drink);
      });
    });

    // Refresh quests
    const refreshBtn = document.getElementById("refresh-quests");
    if (refreshBtn) refreshBtn.addEventListener("click", () => this.getQuestBoard());

    // Investigate button
    const investigateBtn = document.getElementById("btn-investigate");
    if (investigateBtn) {
      investigateBtn.addEventListener("click", () => {
        // Investigate the first rumor card visible
        const rumorEl = document.querySelector(".rumor-card");
        const rumor_id = rumorEl?.dataset.rumorId || `rumor_${Date.now()}`;
        this.socket?.emit("investigate_rumor", { rumor_id });
      });
    }

    // Chat form
    const chatForm = document.getElementById("chat-form");
    if (chatForm) {
      chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const input = document.getElementById("chat-input");
        const text = input?.value.trim();
        if (text) {
          this.sendMessage(text);
          if (input) input.value = "";
        }
      });
    }

    // Quest modal close
    const modalClose = document.getElementById("modal-close");
    if (modalClose) modalClose.addEventListener("click", () => this._closeModal());

    // Accept quest button in modal
    const btnAccept = document.getElementById("btn-accept-quest");
    if (btnAccept) {
      btnAccept.addEventListener("click", () => {
        if (this._pendingQuestId) {
          this.acceptQuest(this._pendingQuestId);
          this._closeModal();
        }
      });
    }

    // Close modal on backdrop click
    const modal = document.getElementById("quest-modal");
    if (modal) {
      modal.addEventListener("click", (e) => {
        if (e.target === modal) this._closeModal();
      });
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // State management
  // ─────────────────────────────────────────────────────────────────────────

  loadState() {
    this.socket?.emit("get_tavern_state");
    // Also do a REST fetch as fallback
    fetch("/api/status")
      .then((r) => r.json())
      .then((data) => this._applyState(data))
      .catch(() => {});
  }

  _applyState(s) {
    if (!s || typeof s !== "object") return;
    this.state = { ...this.state, ...s };

    // Header HUD
    this._setText("turn-val", s.turn);
    this._setText("gold-val", s.gold);
    this._setText("heat-val", s.heat);

    // Time badge
    const timeBadge = document.getElementById("time-badge");
    if (timeBadge && s.time_of_day) {
      const timeMap = {
        morning: "🌅 MORNING",
        afternoon: "☀️ MIDDAY",
        midday: "☀️ MIDDAY",
        evening: "🌆 DUSK",
        dusk: "🌆 DUSK",
        midnight: "🌙 MIDNIGHT",
      };
      timeBadge.textContent = timeMap[s.time_of_day] || s.time_of_day.toUpperCase();
      timeBadge.dataset.time = s.time_of_day;
    }

    // Atmosphere pill
    const atmPill = document.getElementById("atm-pill");
    if (atmPill && s.atmosphere) {
      atmPill.textContent = s.atmosphere.toUpperCase();
      atmPill.className = `atm-pill ${s.atmosphere}`;
    }

    // Atmosphere ring
    const ring = document.getElementById("atm-ring");
    if (ring && s.atmosphere) {
      ring.className = `atmosphere-ring ${s.atmosphere}`;
    }

    // Bench metrics
    this._setText("atm-label", s.atmosphere || "—");
    this._setText("drinks-count", (s.drinks_consumed || []).length);
    this._setText("npc-count", (s.npcs_present || []).length);

    // Active quest
    if (s.quests) {
      const active = Object.entries(s.quests).find(([, q]) => q.status === "active");
      if (active) {
        const [qid, q] = active;
        this._setActiveQuest({
          quest_id: qid,
          title: q.title,
          progress: q.progress,
          max: q.max,
          objective: q.objective,
        });
      }
    }

    // Adjust ember intensity by heat
    if (typeof s.heat === "number") {
      this._setEmbersIntensity(s.heat);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Quest board
  // ─────────────────────────────────────────────────────────────────────────

  getQuestBoard() {
    this.socket?.emit("get_quest_board");
  }

  _renderQuestBoard(quests) {
    const board = document.getElementById("quest-board");
    if (!board) return;

    if (!quests.length) {
      board.innerHTML = '<div class="quest-board-empty">No quests posted. Check back at nightfall.</div>';
      return;
    }

    board.innerHTML = "";
    quests.forEach((q, i) => {
      const card = document.createElement("div");
      card.className = "quest-card";
      card.style.setProperty("--card-index", i);
      card.dataset.questId = q.id;

      const typeTags = (q.tags || []).slice(0, 2).join(", ") || q.type || "QUEST";
      const reward = q.reward ? `${q.reward}g` : q.reward_gold ? `${q.reward_gold}g` : "—";

      card.innerHTML = `
        <div class="quest-card-front">
          <div class="quest-type-tag">${typeTags.toUpperCase()}</div>
          <div class="quest-card-name">${q.title || q.id}</div>
          <div class="quest-reward">⚔️ Reward: ${reward}</div>
        </div>`;

      card.addEventListener("click", () => this._openQuestModal(q));
      board.appendChild(card);
    });
  }

  acceptQuest(questId) {
    this.socket?.emit("accept_quest", { quest_id: questId });
    this._addChatLine(`⚔️ Accepting quest: ${questId}…`, "action");
  }

  _openQuestModal(q) {
    this._pendingQuestId = q.id;

    const typeTags = (q.tags || []).join(", ") || q.type || "QUEST";
    const reward = q.reward ? `${q.reward}g` : q.reward_gold ? `${q.reward_gold}g` : "—";

    this._setText("modal-type-tag", typeTags.toUpperCase());
    this._setText("modal-title", q.title || q.id);
    this._setText("modal-description", q.content || q.description || "A mysterious quest awaits…");
    this._setText("modal-reward", `Reward: ${reward}`);

    const modal = document.getElementById("quest-modal");
    if (modal) modal.classList.remove("hidden");
  }

  _closeModal() {
    this._pendingQuestId = null;
    const modal = document.getElementById("quest-modal");
    if (modal) modal.classList.add("hidden");
  }

  _setActiveQuest(data) {
    const panel = document.getElementById("active-quest-content");
    if (!panel) return;
    const progress = data.progress !== undefined && data.max
      ? `<div class="active-quest-progress">Progress: ${data.progress}/${data.max}</div>`
      : "";
    panel.innerHTML = `
      <div class="active-quest-title">${data.title || data.quest_id}</div>
      <div class="active-quest-progress">${data.objective || ""}</div>
      ${progress}
    `;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Dice
  // ─────────────────────────────────────────────────────────────────────────

  rollDice(sides = 20, reason = "skill check") {
    this._addChatLine(`🎲 Rolling d${sides} — ${reason}…`, "action");
    const diceEl = document.getElementById("dice-3d");
    if (diceEl) diceEl.classList.add("rolling");
    document.getElementById("dice-result")?.classList.add("hidden");
    this.socket?.emit("roll_dice", { sides, reason });
  }

  _animateDiceRoll(data) {
    const { total, sides, rolls, reason, critical, fumble } = data;

    // Spin animation
    const diceEl = document.getElementById("dice-3d");
    if (diceEl) {
      diceEl.classList.add("rolling");
      setTimeout(() => diceEl.classList.remove("rolling"), 650);
    }

    // Show result after spin completes
    setTimeout(() => {
      const resultEl = document.getElementById("dice-result");
      const totalEl = document.getElementById("dice-total");
      const labelEl = document.getElementById("dice-label");

      if (totalEl) {
        totalEl.textContent = total;
        totalEl.className = "dice-total" + (critical ? " critical" : fumble ? " fumble" : "");
      }
      if (labelEl) {
        const rollsStr = rolls ? `[${rolls.join(", ")}] ` : "";
        labelEl.textContent = `${rollsStr}${reason || ""}`;
      }
      if (resultEl) {
        resultEl.classList.remove("hidden");
        // Re-trigger animation
        resultEl.style.animation = "none";
        void resultEl.offsetWidth;
        resultEl.style.animation = "";
      }

      const suffix = critical ? " ✨ CRITICAL!" : fumble ? " 💀 FUMBLE!" : "";
      this._addChatLine(`🎲 ${reason}: ${total}/${sides * 3}${suffix}`, "result");
    }, 660);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Drinks
  // ─────────────────────────────────────────────────────────────────────────

  _orderDrink(drink) {
    this._addChatLine(`🍺 Ordering ${drink}…`, "action");
    this.socket?.emit("order_drink", { drink });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Chat
  // ─────────────────────────────────────────────────────────────────────────

  sendMessage(text) {
    this._addChatLine(`> ${text}`, "action");
    this.socket?.emit("action", { type: "chat", text });
  }

  _addChatLine(text, type = "result") {
    const feed = document.getElementById("chat-feed");
    if (!feed) return;
    const div = document.createElement("div");
    div.className = `chat-line ${type}`;
    div.textContent = text;
    feed.appendChild(div);
    // Auto-scroll
    feed.scrollTop = feed.scrollHeight;
    // Trim old lines
    while (feed.children.length > 80) {
      feed.removeChild(feed.firstChild);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Toast
  // ─────────────────────────────────────────────────────────────────────────

  _showToast(text) {
    const toast = document.getElementById("toast");
    if (!toast) return;
    toast.textContent = text;
    toast.classList.remove("hidden");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => toast.classList.add("hidden"), 4000);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Embers particle system (fire sparks)
  // ─────────────────────────────────────────────────────────────────────────

  _startEmbers() {
    const canvas = document.getElementById("embers-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    this._embersCtx = ctx;
    this._embers = [];

    const resize = () => {
      canvas.width  = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    // Spawn initial embers
    for (let i = 0; i < 25; i++) this._spawnEmber(true);

    const loop = () => {
      this._updateEmbers();
      this._embersTimer = requestAnimationFrame(loop);
    };
    loop();
  }

  _spawnEmber(random = false) {
    const canvas = document.getElementById("embers-canvas");
    if (!canvas) return;
    const w = canvas.width;
    const h = canvas.height;
    this._embers.push({
      x: w * (0.3 + Math.random() * 0.4),  // center-ish
      y: random ? Math.random() * h : h,
      vx: (Math.random() - 0.5) * 0.8,
      vy: -(0.5 + Math.random() * 1.5),
      life: random ? Math.random() : 1.0,
      decay: 0.003 + Math.random() * 0.006,
      size: 1 + Math.random() * 2.5,
      hue: 20 + Math.floor(Math.random() * 30),  // amber to orange
    });
  }

  _updateEmbers() {
    const ctx = this._embersCtx;
    const canvas = document.getElementById("embers-canvas");
    if (!ctx || !canvas) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const intensity = this._embersIntensity || 0.4;
    const maxEmbers = Math.floor(10 + intensity * 50);

    // Spawn if needed
    if (this._embers.length < maxEmbers && Math.random() < 0.25 + intensity * 0.5) {
      this._spawnEmber();
    }

    // Draw & update
    this._embers = this._embers.filter((e) => {
      e.x  += e.vx;
      e.y  += e.vy;
      e.vx += (Math.random() - 0.5) * 0.05;
      e.life -= e.decay;

      if (e.life <= 0 || e.y < -5) return false;

      const alpha = Math.min(e.life * 2, 1) * 0.85;
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.size, 0, Math.PI * 2);
      ctx.fillStyle = `hsla(${e.hue}, 90%, 65%, ${alpha})`;
      ctx.fill();

      // Tiny glow
      if (e.size > 1.5) {
        ctx.beginPath();
        ctx.arc(e.x, e.y, e.size * 2.5, 0, Math.PI * 2);
        const g = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, e.size * 2.5);
        g.addColorStop(0, `hsla(${e.hue}, 90%, 70%, ${alpha * 0.3})`);
        g.addColorStop(1, "transparent");
        ctx.fillStyle = g;
        ctx.fill();
      }

      return true;
    });
  }

  _setEmbersIntensity(heat) {
    // heat 0–100 → intensity 0.1–1.0
    this._embersIntensity = 0.1 + (heat / 100) * 0.9;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────────────────

  _setText(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== null) {
      el.textContent = value;
    }
  }
}
