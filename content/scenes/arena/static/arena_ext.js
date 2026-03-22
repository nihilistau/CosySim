/**
 * THE COLOSSEUM — Extension Module
 * ==================================
 *
 * Game logic extensions for the Kit-generated ArenaScene class.
 * Adds: match lifecycle (create, rounds, resolution), fighter card
 * animations, HP bar updates, betting system, auto-play wiring,
 * commentary feed updates, leaderboard, clash effects.
 *
 * Ports ALL functionality from the original arena.js into the
 * Kit extension pattern (ArenaScene.prototype methods).
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Initial extension module, refactored from arena.js.
 *                            ArenaScene.prototype methods, _initExtensions hook.
 *                            Full implementations: match lifecycle, fighter cards,
 *                            HP bars, betting panel, auto-play, commentary,
 *                            clash animations, leaderboard, BenchHUD integration.
 *
 * CONNECTS: ArenaScene (arena_kit.js), Socket.IO, REST APIs
 * CALLED BY: ArenaScene.init() -> _initExtensions()
 */

'use strict';

// ── Utilities ────────────────────────────────────────────────────────

const $  = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function fmt(n) {
  return Number(n).toLocaleString('en-US');
}

// ── Extension Entry Point ────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Hooked by Kit-generated init() via _initExtensions
// CONNECTS: All arena subsystems
// CALLED BY: ArenaScene.init()

ArenaScene.prototype._initExtensions = function() {
  /** @type {boolean} Auto-play state */
  this.autoPlay = false;
  /** @type {string} Selected bet type */
  this.betType = 'match_winner';
  /** @type {string|null} Selected bet target */
  this.betTarget = null;
  /** @type {Array} Active bets for display */
  this.activeBets = [];
  /** @type {number|null} Auto-play interval ID */
  this._autoPlayInterval = null;

  this._initMatchControls();
  this._initBettingPanel();
  this._initFighterSelects();
  this._initArenaSocket();

  // Load initial fighter list and economy
  this._loadFighters();
  this._loadEconomy();

  this._appendCommentary('The Colosseum awaits its champions...', 'intro');
};


// ═════════════════════════════════════════════════════════════════════
// MATCH CONTROLS
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Create match, play round, auto-play toggle
// CONNECTS: Socket.IO create_match / play_round, control buttons
// CALLED BY: _initExtensions
// EMITS: create_match, play_round socket events

ArenaScene.prototype._initMatchControls = function() {
  // New match button
  const createBtn = document.getElementById('create-match-btn');
  if (createBtn) {
    createBtn.addEventListener('click', () => {
      const fighterA = document.getElementById('select-fighter-a')?.value || 'shadow';
      const fighterB = document.getElementById('select-fighter-b')?.value || 'blaze';
      this.createMatch(fighterA, fighterB);
    });
  }

  // Play round button
  const playBtn = document.getElementById('play-round-btn');
  if (playBtn) {
    playBtn.addEventListener('click', () => this.playRound());
  }

  // Auto-play toggle button
  const autoBtn = document.getElementById('auto-play-btn');
  if (autoBtn) {
    autoBtn.addEventListener('click', () => this.toggleAutoPlay());
  }
};


// ═════════════════════════════════════════════════════════════════════
// MATCH LIFECYCLE — create, play, auto-play
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Full match lifecycle via Socket.IO
// CONNECTS: Socket.IO create_match / play_round events
// CALLED BY: _initMatchControls button handlers
// EMITS: create_match { fighter_a, fighter_b, auto_play },
//        play_round { match_id }

// v1.50.0 [2026-03-22] — Create a new match between two fighters
// CONNECTS: Socket.IO, match status display
// EMITS: create_match event
ArenaScene.prototype.createMatch = function(fighterAId, fighterBId) {
  // Reset bet state for new match
  this.activeBets = [];
  this._renderActiveBets();

  this.socket.emit('create_match', {
    fighter_a: fighterAId,
    fighter_b: fighterBId,
    auto_play: this.autoPlay,
  });

  this._setStatus('IN PROGRESS');
  this._appendCommentary(
    `Creating match: ${fighterAId} vs ${fighterBId}...`, 'system'
  );
};

// v1.50.0 [2026-03-22] — Play one round of the active match
// CONNECTS: Socket.IO play_round event
// EMITS: play_round { match_id }
ArenaScene.prototype.playRound = function() {
  if (!this.matchId) {
    this._appendCommentary('Create a match first.', 'system');
    return;
  }
  this.socket.emit('play_round', { match_id: this.matchId });
};

// v1.50.0 [2026-03-22] — Toggle auto-play on/off
// CONNECTS: auto-play button UI state
ArenaScene.prototype.toggleAutoPlay = function() {
  this.autoPlay = !this.autoPlay;

  const btn = document.getElementById('auto-play-btn');
  if (btn) {
    btn.setAttribute('aria-pressed', String(this.autoPlay));
    btn.classList.toggle('ck-btn--accent', this.autoPlay);
    btn.title = this.autoPlay ? 'Auto-play ON' : 'Auto-play OFF';
  }

  if (this.autoPlay && this.matchId) {
    this._appendCommentary('Auto-play enabled.', 'system');
  } else if (!this.autoPlay) {
    this._appendCommentary('Auto-play disabled.', 'system');
  }
};


// ═════════════════════════════════════════════════════════════════════
// BETTING PANEL
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Betting sidebar with type/target selection,
// amount input, active bet display, payout resolution
// CONNECTS: Socket.IO place_bet, bet_placed events, betting panel DOM
// CALLED BY: _initExtensions
// EMITS: place_bet socket event

ArenaScene.prototype._initBettingPanel = function() {
  // Bet panel open/close toggle
  const betPanelBtn = document.getElementById('bet-panel-btn');
  const betPanel = document.getElementById('arena-bet-panel');
  const betCloseBtn = document.getElementById('bet-panel-close');

  if (betPanelBtn && betPanel) {
    betPanelBtn.addEventListener('click', () => {
      const isHidden = betPanel.hasAttribute('hidden');
      if (isHidden) {
        betPanel.removeAttribute('hidden');
      } else {
        betPanel.setAttribute('hidden', '');
      }
    });
  }

  if (betCloseBtn && betPanel) {
    betCloseBtn.addEventListener('click', () => {
      betPanel.setAttribute('hidden', '');
    });
  }

  // Bet type toggle buttons
  $$('.arena-bet-type').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.arena-bet-type').forEach(b => {
        b.classList.remove('arena-bet-type--active');
      });
      btn.classList.add('arena-bet-type--active');
      this.betType = btn.dataset.type;
    });
  });

  // Bet target toggle buttons
  $$('.arena-bet-target').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.arena-bet-target').forEach(b => {
        b.classList.remove('arena-bet-target--active');
      });
      btn.classList.add('arena-bet-target--active');
      this.betTarget = btn.dataset.target;
      this._syncBetTargetLabels();
    });
  });

  // Place bet button
  const placeBetBtn = document.getElementById('place-bet-btn');
  if (placeBetBtn) {
    placeBetBtn.addEventListener('click', () => {
      const amount = parseInt(
        document.getElementById('bet-amount')?.value || '100', 10
      );
      if (!this.betTarget) {
        this._appendCommentary('Select a fighter to bet on first.', 'system');
        return;
      }
      this.placeBet(this.betType, this.betTarget, amount);
    });
  }
};

// v1.50.0 [2026-03-22] — Place a bet on the active match
// CONNECTS: Socket.IO place_bet event
// EMITS: place_bet { match_id, bet_type, target, amount }
ArenaScene.prototype.placeBet = function(betType, target, amount) {
  if (!this.matchId) {
    this._appendCommentary('No active match to bet on.', 'system');
    return;
  }
  this.socket.emit('place_bet', {
    match_id: this.matchId,
    bet_type: betType,
    target: target,
    amount: amount,
  });
};

// v1.50.0 [2026-03-22] — Update credits display from economy
// CONNECTS: #arena-credits DOM element
ArenaScene.prototype.updateCredits = function(balance) {
  const el = document.getElementById('arena-credits');
  if (el) {
    el.textContent = `\u20B5 ${fmt(balance)}`;
  }
};

// v1.50.0 [2026-03-22] — Sync bet target button labels with fighter names
// CONNECTS: fighter name elements, bet target buttons
ArenaScene.prototype._syncBetTargetLabels = function() {
  const nameA = document.getElementById('fighter-a-name')?.textContent?.trim() || 'Fighter A';
  const nameB = document.getElementById('fighter-b-name')?.textContent?.trim() || 'Fighter B';
  const btnA = document.getElementById('bet-target-a');
  const btnB = document.getElementById('bet-target-b');
  if (btnA && nameA !== '\u2014') btnA.textContent = nameA;
  if (btnB && nameB !== '\u2014') btnB.textContent = nameB;
};

// v1.50.0 [2026-03-22] — Render active bets list in betting sidebar
// CONNECTS: #arena-active-bets DOM element
ArenaScene.prototype._renderActiveBets = function() {
  const container = document.getElementById('arena-active-bets');
  if (!container) return;

  const label = container.querySelector('.arena-bet-label');
  container.innerHTML = '';
  if (label) container.appendChild(label);

  this.activeBets.forEach(bet => {
    const row = document.createElement('div');
    row.className = 'arena-active-bet-row';
    row.innerHTML = `
      <span>${(bet.bet_type || '').replace('_', ' ')} \u2192 ${bet.target}</span>
      <span>\u20B5${fmt(bet.amount)}</span>
    `;
    container.appendChild(row);
  });
};

// v1.50.0 [2026-03-22] — Display resolved bet payouts in commentary
// CONNECTS: Commentary feed
// CALLED BY: match_complete socket handler
ArenaScene.prototype._renderResolvedBets = function(resolved) {
  resolved.forEach(bet => {
    if (bet.won) {
      this._appendCommentary(`Bet WON! +\u20B5${fmt(bet.payout)}`, 'round');
    } else {
      this._appendCommentary(`Bet lost. -\u20B5${fmt(bet.amount)}`, 'system');
    }
  });
};


// ═════════════════════════════════════════════════════════════════════
// FIGHTER SELECT DROPDOWNS
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Populate fighter selects from server profiles
// CONNECTS: /api/fighters REST, Socket.IO fighters_list, select DOM
// CALLED BY: _initExtensions

ArenaScene.prototype._initFighterSelects = function() {
  // Nothing to wire here -- selects are populated by _populateFighterSelects
  // when fighters_list arrives via Socket.IO or REST
};

// v1.50.0 [2026-03-22] — Load fighters from REST API
// CONNECTS: /api/fighters endpoint
ArenaScene.prototype._loadFighters = function() {
  // v1.49.1 [2026-03-22] — Add error handling for fetch calls
  fetch('/api/fighters')
    .then(r => r.ok ? r.json() : { fighters: [] })
    .then(data => {
      if (data.fighters) this._populateFighterSelects(data.fighters);
    })
    .catch(err => console.warn('[Arena] Failed to load fighters:', err.message));
};

// v1.50.0 [2026-03-22] — Populate fighter select dropdowns with profiles
// CONNECTS: #select-fighter-a, #select-fighter-b DOM elements
// CALLED BY: fighters_list socket event, _loadFighters
ArenaScene.prototype._populateFighterSelects = function(fighters) {
  if (!fighters?.length) return;

  ['select-fighter-a', 'select-fighter-b'].forEach((id, idx) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = '';
    fighters.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f.id;
      opt.textContent = f.name;
      // Default: shadow for A, blaze for B
      if (idx === 0 && f.id === 'shadow') opt.selected = true;
      if (idx === 1 && f.id === 'blaze') opt.selected = true;
      sel.appendChild(opt);
    });
  });
};


// ═════════════════════════════════════════════════════════════════════
// ECONOMY
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Fetch player balance from economy API
// CONNECTS: /api/economy REST endpoint, credits display
// CALLED BY: _initExtensions

ArenaScene.prototype._loadEconomy = function() {
  fetch('/api/economy')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data && data.balance !== undefined) {
        this.updateCredits(data.balance);
      }
    })
    .catch(err => console.warn('[Arena] Failed to load economy:', err.message));
};


// ═════════════════════════════════════════════════════════════════════
// RENDER — MATCH STATE
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Render full match state on match_created / match_state
// CONNECTS: Fighter panels, round counter, status chip
// CALLED BY: match_created, match_state socket handlers

ArenaScene.prototype._renderMatch = function(match) {
  this.matchId = match.id;
  this._renderFighter('a', match.fighter_a);
  this._renderFighter('b', match.fighter_b);

  const roundNum = match.rounds?.length ?? 0;
  const maxRounds = match.max_rounds || 7;
  this._setText('arena-round', `Round ${roundNum} / ${maxRounds}`);
  this._setStatus(match.status);

  // Update round progress tracker
  this._updateRoundProgress(roundNum, maxRounds);
};


// ═════════════════════════════════════════════════════════════════════
// RENDER — ROUND OUTCOME
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Render a single round outcome: cards, reasoning,
// commentary, clash effects, round counter
// CONNECTS: Card displays, reasoning panels, commentary feed, clash flash
// CALLED BY: round_result socket handler

ArenaScene.prototype._renderRound = function(outcome) {
  // Round counter
  const maxRounds = 7;
  this._setText('arena-round', `Round ${outcome.round_num} / ${maxRounds}`);

  // Cards
  this._renderCard('a', outcome.fighter_a_card);
  this._renderCard('b', outcome.fighter_b_card);

  // Reasoning text
  this._setText('fighter-a-reason-text', outcome.fighter_a_reasoning || '...');
  this._setText('fighter-b-reason-text', outcome.fighter_b_reasoning || '...');

  // Commentary
  let commentClass = 'round';
  if (outcome.special_triggered) commentClass = 'special';
  this._appendCommentary(
    `R${outcome.round_num}: ${outcome.commentary}`, commentClass
  );

  if (outcome.special_triggered) {
    this._appendCommentary(
      `SPECIAL: ${outcome.special_triggered}`, 'special'
    );
  }

  // Clash animation
  this._playClash(outcome);

  // Update round progress tracker
  this._updateRoundProgress(outcome.round_num, maxRounds);
};


// ═════════════════════════════════════════════════════════════════════
// RENDER — FIGHTER STATE
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Render fighter name, HP bar, stats for one side
// CONNECTS: Fighter panel DOM elements (name, HP bar, stats)
// CALLED BY: _renderMatch, round_result socket handler

ArenaScene.prototype._renderFighter = function(side, fighter) {
  const pfx = `fighter-${side}`;

  // Name
  const nameEl = document.getElementById(`${pfx}-name`);
  if (nameEl) nameEl.textContent = fighter.name || '\u2014';

  // HP bar -- use Kit stat bar if present, fall back to arena stat bar
  const hpPct = Math.max(0, (fighter.hp / fighter.max_hp) * 100);

  // Kit-style stat bar (ck-stat-fill)
  const kitHpFill = document.getElementById(`${pfx}-hp-fill`);
  if (kitHpFill) {
    kitHpFill.style.width = `${hpPct}%`;
    // Critical state when HP < 25%
    if (hpPct < 25) {
      kitHpFill.style.background = 'linear-gradient(90deg, #d97706 0%, #fbbf24 100%)';
    } else {
      kitHpFill.style.background = '';
    }
  }

  // Original-style stat bar (cs-stat-bar__fill)
  const origHpBar = document.getElementById(`${pfx}-hp`);
  if (origHpBar) {
    origHpBar.style.width = `${hpPct}%`;
    origHpBar.classList.toggle('cs-stat-bar__fill--critical', hpPct < 25);
  }

  // HP value text
  const hpValEl = document.getElementById(`${pfx}-hp-val`);
  if (hpValEl) hpValEl.textContent = `${fighter.hp}`;

  // Stats text
  const statsEl = document.getElementById(`${pfx}-stats`);
  if (statsEl) {
    statsEl.textContent = `HP: ${fighter.hp} / ${fighter.max_hp}`;
  }

  // Sync bet target labels with current fighter names
  this._syncBetTargetLabels();
};


// ═════════════════════════════════════════════════════════════════════
// RENDER — CARD DISPLAY
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Render a played card onto a fighter's card slot
// with type-based coloring and flip-in animation
// CONNECTS: Fighter card display DOM elements
// CALLED BY: _renderRound

ArenaScene.prototype._renderCard = function(side, card) {
  const el = document.getElementById(`fighter-${side}-card-display`);
  if (!el) return;

  // Set data-type for CSS card coloring
  el.dataset.type = (card.card_type || 'attack').toLowerCase();

  const nameEl = el.querySelector('.cs-arena-card__name');
  const powerEl = el.querySelector('.cs-arena-card__power');
  const flavorEl = el.querySelector('.cs-arena-card__flavor');

  if (nameEl) nameEl.textContent = card.name;
  if (powerEl) powerEl.textContent = `PWR ${card.power}`;
  if (flavorEl) flavorEl.textContent = card.flavor_text || '';

  // Replay card flip-in animation
  el.classList.remove('cs-arena-card--played');
  void el.offsetWidth; // reflow trigger
  el.classList.add('cs-arena-card--played');
};


// ═════════════════════════════════════════════════════════════════════
// CLASH ANIMATION
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Flash overlay + particle burst on round resolve
// CONNECTS: #arena-clash-flash, #arena-particles, CosyParticles3D
// CALLED BY: _renderRound

ArenaScene.prototype._playClash = function(outcome) {
  // Flash overlay
  const flash = document.getElementById('arena-clash-flash');
  if (flash) {
    flash.classList.remove('arena-clash-flash--active');
    void flash.offsetWidth; // reflow trigger
    flash.classList.add('arena-clash-flash--active');
  }

  // Particle effects -- scale with damage magnitude
  const isBigDamage = (outcome.damage_a > 12 || outcome.damage_b > 12);
  const isSpecial = !!outcome.special_triggered;

  if (typeof CosyParticles3D !== 'undefined') {
    const container = document.getElementById('arena-particles');
    if (container) {
      if (isBigDamage) {
        CosyParticles3D.burst(container, {
          type: 'blood_mist',
          count: 28,
          color: '#dc2626',
          duration: 900,
        });
      } else if (isSpecial) {
        CosyParticles3D.burst(container, {
          type: 'sparks',
          count: 20,
          color: '#a855f7',
          duration: 700,
        });
      } else {
        CosyParticles3D.burst(container, {
          type: 'sparks',
          count: 12,
          color: '#f97316',
          duration: 500,
        });
      }
    }
  }
};


// ═════════════════════════════════════════════════════════════════════
// ROUND PROGRESS TRACKER
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Update Kit progress tracker steps for rounds
// CONNECTS: #round-progress .ck-step DOM elements
// CALLED BY: _renderMatch, _renderRound

ArenaScene.prototype._updateRoundProgress = function(currentRound, maxRounds) {
  const tracker = document.getElementById('round-progress');
  if (!tracker) return;

  const steps = tracker.querySelectorAll('.ck-step');
  steps.forEach((step, i) => {
    const roundIdx = i + 1;
    step.classList.toggle('active', roundIdx <= currentRound);
    step.classList.toggle('current', roundIdx === currentRound);
  });
};


// ═════════════════════════════════════════════════════════════════════
// STATUS & UI HELPERS
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Status chip, round button enable/disable,
// winner name resolution

// v1.50.0 [2026-03-22] — Update match status chip
// CONNECTS: #arena-match-status DOM element
ArenaScene.prototype._setStatus = function(text, mod) {
  const el = document.getElementById('arena-match-status');
  if (!el) return;
  el.textContent = text;
  el.className = 'arena-match-status cs-chip';
  if (mod) el.classList.add(`arena-match-status--${mod}`);
};

// v1.50.0 [2026-03-22] — Enable/disable play round button
// CONNECTS: #play-round-btn DOM element
ArenaScene.prototype._enableRoundButton = function(enabled) {
  const btn = document.getElementById('play-round-btn');
  if (btn) btn.disabled = !enabled;
};

// v1.50.0 [2026-03-22] — Resolve winner ID to display name
ArenaScene.prototype._winnerName = function(match, winnerId) {
  if (winnerId === 'fighter_a') return match.fighter_a?.name || 'Fighter A';
  if (winnerId === 'fighter_b') return match.fighter_b?.name || 'Fighter B';
  return 'DRAW';
};


// ═════════════════════════════════════════════════════════════════════
// LEADERBOARD
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Fetch and render fighter leaderboard
// CONNECTS: /api/leaderboard REST, #leaderboard-list DOM
// CALLED BY: Leaderboard button click

ArenaScene.prototype._loadLeaderboard = function() {
  fetch('/api/leaderboard')
    .then(r => r.ok ? r.json() : { leaderboard: [] })
    .then(data => this._renderLeaderboard(data.leaderboard || []))
    .catch(() => {
      const list = document.getElementById('leaderboard-list');
      if (list) list.innerHTML = '<p class="arena-empty">Failed to load leaderboard.</p>';
    });
};

// v1.50.0 [2026-03-22] — Render leaderboard rows
// CONNECTS: #leaderboard-list DOM element
ArenaScene.prototype._renderLeaderboard = function(board) {
  const list = document.getElementById('leaderboard-list');
  if (!list) return;

  if (!board || !board.length) {
    list.innerHTML = '<p class="arena-empty">No fighters registered yet.</p>';
    return;
  }

  list.innerHTML = board.map((f, i) => `
    <div class="arena-leader-row">
      <span class="arena-leader-rank">${i + 1}.</span>
      <span class="arena-leader-name">${f.name}</span>
      <span class="arena-leader-record">W:${f.wins} L:${f.losses} D:${f.draws}</span>
    </div>
  `).join('');
};


// ═════════════════════════════════════════════════════════════════════
// SOCKET.IO — arena-specific event handlers
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — All arena Socket.IO handlers
// CONNECTS: Socket.IO server events
// CALLED BY: _initExtensions

ArenaScene.prototype._initArenaSocket = function() {
  if (!this.socket) return;

  // ── Welcome message ────────────────────────────────────────────
  this.socket.on('arena_welcome', (data) => {
    this._appendCommentary(data.message || 'Welcome.', 'system');
  });

  // ── Match created ──────────────────────────────────────────────
  this.socket.on('match_created', (data) => {
    this._renderMatch(data.match);
    const nameA = data.match.fighter_a?.name || 'Fighter A';
    const nameB = data.match.fighter_b?.name || 'Fighter B';
    this._appendCommentary(
      `Match created: ${nameA} vs ${nameB}`, 'round'
    );
    this._enableRoundButton(true);
  });

  // ── Round result ───────────────────────────────────────────────
  this.socket.on('round_result', (data) => {
    this._renderRound(data.round_outcome);
    this._renderFighter('a', data.fighter_a);
    this._renderFighter('b', data.fighter_b);

    // BenchHUD integration -- track fighter response times
    const msA = data.fighter_a?.stats?.last_response_ms ?? 0;
    const msB = data.fighter_b?.stats?.last_response_ms ?? 0;
    if (typeof BenchHUD !== 'undefined') {
      BenchHUD.update({ response_ms: Math.max(msA, msB) });
    }
  });

  // ── Match complete ─────────────────────────────────────────────
  this.socket.on('match_complete', (data) => {
    const winnerName = this._winnerName(data.match, data.winner);
    this._appendCommentary(
      `MATCH OVER -- ${winnerName} wins!`, 'round'
    );
    this._setStatus('COMPLETE', 'complete');
    this._enableRoundButton(false);

    // Turn off auto-play if active
    if (this.autoPlay) {
      this.toggleAutoPlay();
    }

    // Render resolved bets
    if (data.bets_resolved?.length) {
      this._renderResolvedBets(data.bets_resolved);
    }

    // Refresh leaderboard
    this._loadLeaderboard();
  });

  // ── Fighters list ──────────────────────────────────────────────
  this.socket.on('fighters_list', (data) => {
    this._populateFighterSelects(data.fighters);
  });

  // ── Bet placed ─────────────────────────────────────────────────
  this.socket.on('bet_placed', (data) => {
    if (data.bet) {
      this.activeBets.push(data.bet);
      this._renderActiveBets();
      this._showToast(`Bet placed: \u20B5${fmt(data.bet.amount)}`, 'success');
    }
    if (data.balance != null) {
      this.updateCredits(data.balance);
    }
  });

  // ── Match state (full sync) ────────────────────────────────────
  this.socket.on('match_state', (data) => {
    if (data.match) {
      this._renderMatch(data.match);
    }
  });

  // ── HUD update (economy) ──────────────────────────────────────
  this.socket.on('hud_update', (data) => {
    if (data.balance !== undefined) {
      this.updateCredits(data.balance);
    }
    if (data.credits !== undefined) {
      this.updateCredits(data.credits);
    }
  });

  // ── Framework status / world events ────────────────────────────
  this.socket.on('world_event', (data) => {
    const title = data.title || 'Arena Event';
    this._showToast(title);
  });
};
