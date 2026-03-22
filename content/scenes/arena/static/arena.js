/**
 * THE COLOSSEUM — Arena Scene JavaScript
 * CosySim v0.68 "Dark Renaissance"
 *
 * ArenaScene class wires Socket.IO events to DOM updates:
 *   - Fighter HP bars, cards, reasoning panels
 *   - Commentary feed with live play-by-play
 *   - Clash animations (flash + particle burst)
 *   - Betting sidebar
 *   - Auto-play toggle
 *   - BenchHUD integration (fighter response times)
 */

"use strict";

/* ═══════════════════════════════════════════════════════════════════
   ArenaScene
   ═══════════════════════════════════════════════════════════════════ */

class ArenaScene {
  constructor() {
    /** @type {string|null} Active match ID */
    this.matchId = null;
    /** @type {boolean} Auto-play state */
    this.autoPlay = false;
    /** @type {string|null} Selected bet type */
    this.betType = "match_winner";
    /** @type {string|null} Selected bet target */
    this.betTarget = null;
    /** @type {Array} Active bets for display */
    this.activeBets = [];

    /** Socket.IO instance */
    this.socket = null;
  }

  /* ── Boot ─────────────────────────────────────────────────────── */

  /**
   * Initialise the scene: connect socket, bind DOM events.
   */
  init() {
    this._setupSocket();
    this._bindControls();
    this._appendCommentary("The Colosseum awaits its champions…", "intro");
    console.debug("[Arena] ArenaScene initialised");
  }

  /* ── Socket.IO ───────────────────────────────────────────────── */

  /**
   * Connect to Socket.IO and register event handlers.
   * @private
   */
  _setupSocket() {
    const port = window.location.port || "5561";
    const host = `${window.location.protocol}//${window.location.hostname}:${port}`;
    this.socket = io(host, { transports: ["websocket", "polling"] });

    this.socket.on("connect", () => {
      console.debug("[Arena] Socket connected:", this.socket.id);
    });

    this.socket.on("disconnect", () => {
      console.warn("[Arena] Socket disconnected");
      this._appendCommentary("Connection lost. Reconnecting…", "system");
    });

    // v1.49.2 [2026-03-22] — Socket.IO reconnect feedback
    this.socket.io.on("reconnect", (attempt) => {
      console.debug("[Arena] Reconnected after " + attempt + " attempt(s)");
    });
    this.socket.io.on("reconnect_attempt", (attempt) => {
      if (attempt % 3 === 0) console.debug("[Arena] Reconnecting... (attempt " + attempt + ")");
    });

    this.socket.on("arena_welcome", (data) => {
      this._appendCommentary(data.message || "Welcome.", "system");
    });

    this.socket.on("match_created", (data) => {
      this._renderMatch(data.match);
      this._appendCommentary(
        `⚔ Match created: ${data.match.fighter_a.name} vs ${data.match.fighter_b.name}`,
        "round"
      );
      this._enableRoundButton(true);
    });

    this.socket.on("round_result", (data) => {
      this._renderRound(data.round_outcome);
      this._renderFighter("a", data.fighter_a);
      this._renderFighter("b", data.fighter_b);

      // BenchHUD: fighter response times
      const msA = data.fighter_a?.stats?.last_response_ms ?? 0;
      const msB = data.fighter_b?.stats?.last_response_ms ?? 0;
      if (typeof BenchHUD !== "undefined") {
        BenchHUD.update({ response_ms: Math.max(msA, msB) });
      }
    });

    this.socket.on("match_complete", (data) => {
      const winnerName = this._winnerName(data.match, data.winner);
      this._appendCommentary(`🏆 MATCH OVER — ${winnerName} wins!`, "round");
      this._setStatus("COMPLETE", "complete");
      this._enableRoundButton(false);
      if (this.autoPlay) {
        this.toggleAutoPlay(); // turn off
      }
      if (data.bets_resolved?.length) {
        this._renderResolvedBets(data.bets_resolved);
      }
    });

    this.socket.on("fighters_list", (data) => {
      this._populateFighterSelects(data.fighters);
    });

    this.socket.on("bet_placed", (data) => {
      if (data.bet) {
        this.activeBets.push(data.bet);
        this._renderActiveBets();
      }
      if (data.balance != null) {
        this.updateCredits(data.balance);
      }
    });

    this.socket.on("match_state", (data) => {
      if (data.match) {
        this._renderMatch(data.match);
      }
    });

    this.socket.on("arena_error", (data) => {
      console.error("[Arena] Server error:", data.error);
      this._appendCommentary(`⚠ ${data.error}`, "system");
    });

    // Request fighter list on load
    this.socket.emit("get_fighters");
  }

  /* ── Controls ────────────────────────────────────────────────── */

  /**
   * Bind button click handlers.
   * @private
   */
  _bindControls() {
    // New match
    const createBtn = document.getElementById("create-match-btn");
    if (createBtn) {
      createBtn.addEventListener("click", () => {
        const fighterA = document.getElementById("select-fighter-a")?.value || "shadow";
        const fighterB = document.getElementById("select-fighter-b")?.value || "blaze";
        this.createMatch(fighterA, fighterB);
      });
    }

    // Play round
    const playBtn = document.getElementById("play-round-btn");
    if (playBtn) {
      playBtn.addEventListener("click", () => this.playRound());
    }

    // Auto-play toggle
    const autoBtn = document.getElementById("auto-play-btn");
    if (autoBtn) {
      autoBtn.addEventListener("click", () => this.toggleAutoPlay());
    }

    // Bet panel open/close
    const betPanelBtn = document.getElementById("bet-panel-btn");
    const betPanel = document.getElementById("arena-bet-panel");
    const betCloseBtn = document.getElementById("bet-panel-close");

    if (betPanelBtn && betPanel) {
      betPanelBtn.addEventListener("click", () => {
        const isHidden = betPanel.hasAttribute("hidden");
        if (isHidden) {
          betPanel.removeAttribute("hidden");
        } else {
          betPanel.setAttribute("hidden", "");
        }
      });
    }
    if (betCloseBtn && betPanel) {
      betCloseBtn.addEventListener("click", () => betPanel.setAttribute("hidden", ""));
    }

    // Bet type buttons
    document.querySelectorAll(".arena-bet-type").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".arena-bet-type").forEach((b) =>
          b.classList.remove("arena-bet-type--active")
        );
        btn.classList.add("arena-bet-type--active");
        this.betType = btn.dataset.type;
      });
    });

    // Bet target buttons
    document.querySelectorAll(".arena-bet-target").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".arena-bet-target").forEach((b) =>
          b.classList.remove("arena-bet-target--active")
        );
        btn.classList.add("arena-bet-target--active");
        this.betTarget = btn.dataset.target;
        // Update button labels with actual names
        this._syncBetTargetLabels();
      });
    });

    // Place bet
    const placeBetBtn = document.getElementById("place-bet-btn");
    if (placeBetBtn) {
      placeBetBtn.addEventListener("click", () => {
        const amount = parseInt(document.getElementById("bet-amount")?.value || "100", 10);
        if (!this.betTarget) {
          this._appendCommentary("Select a fighter to bet on first.", "system");
          return;
        }
        this.placeBet(this.betType, this.betTarget, amount);
      });
    }
  }

  /* ── Public API ──────────────────────────────────────────────── */

  /**
   * Emit create_match with the given fighter IDs.
   *
   * @param {string} fighterAId
   * @param {string} fighterBId
   */
  createMatch(fighterAId, fighterBId) {
    this.activeBets = [];
    this._renderActiveBets();
    this.socket.emit("create_match", {
      fighter_a: fighterAId,
      fighter_b: fighterBId,
      auto_play: this.autoPlay,
    });
    this._setStatus("IN PROGRESS");
    this._appendCommentary(`Creating match: ${fighterAId} vs ${fighterBId}…`, "system");
  }

  /**
   * Emit play_round for the active match.
   */
  playRound() {
    if (!this.matchId) {
      this._appendCommentary("Create a match first.", "system");
      return;
    }
    this.socket.emit("play_round", { match_id: this.matchId });
  }

  /**
   * Toggle auto-play mode on/off.
   */
  toggleAutoPlay() {
    this.autoPlay = !this.autoPlay;
    const btn = document.getElementById("auto-play-btn");
    if (btn) {
      btn.setAttribute("aria-pressed", String(this.autoPlay));
      btn.classList.toggle("cs-glass-btn--accent", this.autoPlay);
      btn.title = this.autoPlay ? "Auto-play ON" : "Auto-play OFF";
    }
    if (this.autoPlay && this.matchId) {
      this._appendCommentary("⚡ Auto-play enabled.", "system");
    } else if (!this.autoPlay) {
      this._appendCommentary("⚡ Auto-play disabled.", "system");
    }
  }

  /**
   * Emit place_bet.
   *
   * @param {string} betType  - "match_winner" | "round_winner"
   * @param {string} target   - "fighter_a" | "fighter_b"
   * @param {number} amount
   */
  placeBet(betType, target, amount) {
    if (!this.matchId) {
      this._appendCommentary("No active match to bet on.", "system");
      return;
    }
    this.socket.emit("place_bet", {
      match_id: this.matchId,
      bet_type: betType,
      target,
      amount,
    });
  }

  /**
   * Update the credits display.
   *
   * @param {number} balance
   */
  updateCredits(balance) {
    const el = document.getElementById("arena-credits");
    if (el) {
      el.textContent = `₵ ${balance.toLocaleString()}`;
    }
  }

  /* ── Render ──────────────────────────────────────────────────── */

  /**
   * Render full match state (typically on match_created / match_state).
   *
   * @param {Object} match
   * @private
   */
  _renderMatch(match) {
    this.matchId = match.id;
    this._renderFighter("a", match.fighter_a);
    this._renderFighter("b", match.fighter_b);

    const roundNum = match.rounds?.length ?? 0;
    document.getElementById("arena-round").textContent =
      `Round ${roundNum} / ${match.max_rounds}`;
    this._setStatus(match.status);
  }

  /**
   * Render the outcome of a single round.
   *
   * @param {Object} outcome - RoundOutcome.to_dict()
   * @private
   */
  _renderRound(outcome) {
    // Round counter
    document.getElementById("arena-round").textContent =
      `Round ${outcome.round_num} / 7`;

    // Cards
    this._renderCard("a", outcome.fighter_a_card);
    this._renderCard("b", outcome.fighter_b_card);

    // Reasoning
    const reasonA = document.getElementById("fighter-a-reason-text");
    const reasonB = document.getElementById("fighter-b-reason-text");
    if (reasonA) reasonA.textContent = outcome.fighter_a_reasoning || "…";
    if (reasonB) reasonB.textContent = outcome.fighter_b_reasoning || "…";

    // Commentary line
    let commentClass = "round";
    if (outcome.special_triggered) commentClass = "special";
    this._appendCommentary(
      `R${outcome.round_num}: ${outcome.commentary}`,
      commentClass
    );

    if (outcome.special_triggered) {
      this._appendCommentary(`⚡ SPECIAL: ${outcome.special_triggered}`, "special");
    }

    // Clash animation
    this._playClash(outcome);
  }

  /**
   * Render a single fighter's state into the left (a) or right (b) column.
   *
   * @param {"a"|"b"} side
   * @param {Object}  fighter - Fighter.to_dict()
   * @private
   */
  _renderFighter(side, fighter) {
    const pfx = `fighter-${side}`;

    // Name
    const nameEl = document.getElementById(`${pfx}-name`);
    if (nameEl) nameEl.textContent = fighter.name || "—";

    // HP bar
    const hpPct = Math.max(0, (fighter.hp / fighter.max_hp) * 100);
    const hpBar = document.getElementById(`${pfx}-hp`);
    if (hpBar) {
      hpBar.style.width = `${hpPct}%`;
      hpBar.classList.toggle("cs-stat-bar__fill--critical", hpPct < 25);
    }

    // Stats text
    const statsEl = document.getElementById(`${pfx}-stats`);
    if (statsEl) {
      statsEl.textContent = `HP: ${fighter.hp} / ${fighter.max_hp}`;
    }

    // Sync bet target labels
    this._syncBetTargetLabels();
  }

  /**
   * Render a card onto a fighter's card display slot.
   *
   * @param {"a"|"b"} side
   * @param {Object}  card - Card.to_dict()
   * @private
   */
  _renderCard(side, card) {
    const el = document.getElementById(`fighter-${side}-card-display`);
    if (!el) return;

    // Set type for CSS coloring
    el.dataset.type = (card.card_type || "attack").toLowerCase();

    const nameEl = el.querySelector(".cs-arena-card__name");
    const powerEl = el.querySelector(".cs-arena-card__power");
    const flavorEl = el.querySelector(".cs-arena-card__flavor");

    if (nameEl) nameEl.textContent = card.name;
    if (powerEl) powerEl.textContent = `PWR ${card.power}`;
    if (flavorEl) flavorEl.textContent = card.flavor_text || "";

    // Replay animation
    el.classList.remove("cs-arena-card--played");
    void el.offsetWidth; // reflow
    el.classList.add("cs-arena-card--played");
  }

  /* ── Clash Animation ─────────────────────────────────────────── */

  /**
   * Trigger clash flash + particles for a round outcome.
   *
   * @param {Object} outcome
   * @private
   */
  _playClash(outcome) {
    const flash = document.getElementById("arena-clash-flash");
    if (flash) {
      flash.classList.remove("arena-clash-flash--active");
      void flash.offsetWidth;
      flash.classList.add("arena-clash-flash--active");
    }

    // Particles
    const isBigDamage = (outcome.damage_a > 12 || outcome.damage_b > 12);
    const isSpecial   = !!outcome.special_triggered;

    if (typeof CosyParticles3D !== "undefined") {
      const container = document.getElementById("arena-particles");
      if (container) {
        if (isBigDamage) {
          CosyParticles3D.burst(container, {
            type: "blood_mist",
            count: 28,
            color: "#dc2626",
            duration: 900,
          });
        } else if (isSpecial) {
          CosyParticles3D.burst(container, {
            type: "sparks",
            count: 20,
            color: "#a855f7",
            duration: 700,
          });
        } else {
          CosyParticles3D.burst(container, {
            type: "sparks",
            count: 12,
            color: "#f97316",
            duration: 500,
          });
        }
      }
    }
  }

  /* ── Commentary ──────────────────────────────────────────────── */

  /**
   * Append a line to the commentary feed and auto-scroll.
   *
   * @param {string} text
   * @param {"intro"|"round"|"special"|"system"} type
   * @private
   */
  _appendCommentary(text, type = "round") {
    const feed = document.getElementById("commentary-feed");
    if (!feed) return;

    const p = document.createElement("p");
    p.className = `arena-commentary__line arena-commentary__line--${type}`;
    p.textContent = text;
    feed.appendChild(p);

    // Trim old lines (keep last 60)
    const lines = feed.querySelectorAll(".arena-commentary__line");
    if (lines.length > 60) {
      lines[0].remove();
    }

    feed.scrollTop = feed.scrollHeight;
  }

  /* ── Betting Helpers ─────────────────────────────────────────── */

  /**
   * Sync bet-target button labels with current fighter names.
   * @private
   */
  _syncBetTargetLabels() {
    const nameA = document.getElementById("fighter-a-name")?.textContent?.trim() || "Fighter A";
    const nameB = document.getElementById("fighter-b-name")?.textContent?.trim() || "Fighter B";
    const btnA = document.getElementById("bet-target-a");
    const btnB = document.getElementById("bet-target-b");
    if (btnA && nameA !== "—") btnA.textContent = nameA;
    if (btnB && nameB !== "—") btnB.textContent = nameB;
  }

  /**
   * Render the active bets list in the sidebar.
   * @private
   */
  _renderActiveBets() {
    const container = document.getElementById("arena-active-bets");
    if (!container) return;

    const label = container.querySelector(".arena-bet-label");
    container.innerHTML = "";
    if (label) container.appendChild(label);

    this.activeBets.forEach((bet) => {
      const row = document.createElement("div");
      row.className = "arena-active-bet-row";
      row.innerHTML = `
        <span>${bet.bet_type.replace("_", " ")} → ${bet.target}</span>
        <span>₵${bet.amount}</span>
      `;
      container.appendChild(row);
    });
  }

  /**
   * Display resolved bet outcomes in commentary.
   *
   * @param {Array} resolved
   * @private
   */
  _renderResolvedBets(resolved) {
    resolved.forEach((bet) => {
      if (bet.won) {
        this._appendCommentary(`💰 Bet WON! +₵${bet.payout}`, "round");
      } else {
        this._appendCommentary(`💸 Bet lost. -₵${bet.amount}`, "system");
      }
    });
  }

  /* ── Fighter Selects ─────────────────────────────────────────── */

  /**
   * Populate the fighter-select dropdowns with server profiles.
   *
   * @param {Array} fighters
   * @private
   */
  _populateFighterSelects(fighters) {
    if (!fighters?.length) return;
    ["select-fighter-a", "select-fighter-b"].forEach((id, idx) => {
      const sel = document.getElementById(id);
      if (!sel) return;
      sel.innerHTML = "";
      fighters.forEach((f) => {
        const opt = document.createElement("option");
        opt.value = f.id;
        opt.textContent = f.name;
        if (idx === 0 && f.id === "shadow") opt.selected = true;
        if (idx === 1 && f.id === "blaze")  opt.selected = true;
        sel.appendChild(opt);
      });
    });
  }

  /* ── Status ──────────────────────────────────────────────────── */

  /**
   * Update the match-status chip text and CSS modifier.
   *
   * @param {string} text
   * @param {string} [mod] - CSS modifier suffix appended to base class
   * @private
   */
  _setStatus(text, mod = "") {
    const el = document.getElementById("arena-match-status");
    if (!el) return;
    el.textContent = text;
    el.className = "arena-match-status cs-chip";
    if (mod) el.classList.add(`arena-match-status--${mod}`);
  }

  /**
   * Enable or disable the "Play Round" button.
   *
   * @param {boolean} enabled
   * @private
   */
  _enableRoundButton(enabled) {
    const btn = document.getElementById("play-round-btn");
    if (btn) btn.disabled = !enabled;
  }

  /**
   * Resolve winner ID to display name.
   *
   * @param {Object} match
   * @param {string} winnerId
   * @returns {string}
   * @private
   */
  _winnerName(match, winnerId) {
    if (winnerId === "fighter_a") return match.fighter_a?.name || "Fighter A";
    if (winnerId === "fighter_b") return match.fighter_b?.name || "Fighter B";
    return "DRAW";
  }
}

/* ── Bootstrap on DOMContentLoaded ───────────────────────────────── */

const arenaScene = new ArenaScene();
document.addEventListener("DOMContentLoaded", () => arenaScene.init());

/* Export for console access during development */
if (typeof window !== "undefined") {
  window.arenaScene = arenaScene;
}
