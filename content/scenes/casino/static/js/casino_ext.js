/**
 * CLUB NOIR — Extension Module
 * ==============================
 *
 * Game logic extensions for the Kit-generated CasinoScene class.
 * Adds: blackjack game mechanics (dealing, betting, hand evaluation),
 * chip management, NPC dealer/Mira interaction, card rendering,
 * win/loss effects with particle sparks, world status HUD,
 * and all casino-specific Socket.IO handlers.
 *
 * Ported from casino.js v0.68 (ClubNoirScene) to prototype extension
 * pattern matching grid_ext.js and tavern_ext.js.
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Full refactor from casino.js to extension pattern.
 *                            CasinoScene.prototype methods, _initExtensions hook.
 *                            Complete implementations: blackjack, betting, cards,
 *                            NPC speech, win/loss effects, sparks, world status,
 *                            consequence system, bench HUD, chat replies.
 *
 * CONNECTS: CasinoScene (casino_kit.js), Socket.IO, REST APIs
 * CALLED BY: CasinoScene.init() -> _initExtensions()
 */

'use strict';

// ── Utilities ────────────────────────────────────────────────────────

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function fmt(n) {
  return Number(n).toLocaleString('en-US');
}

// ── Extension Entry Point ────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Hooked by Kit-generated init() via _initExtensions
// CONNECTS: All casino subsystems
// CALLED BY: CasinoScene.init()

CasinoScene.prototype._initExtensions = function() {
  /** @type {number|null} Active sparks animation frame ID */
  this._sparksAnim = null;

  this._initBlackjackSocket();
  this._initBetControls();
  this._initActionButtons();
  this._initChatSocket();
  this._initWorldStatus();
};


// ═════════════════════════════════════════════════════════════════════
// BLACKJACK — Socket.IO Event Handlers
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — All blackjack-specific Socket.IO handlers
// CONNECTS: Socket.IO server events, card rendering, balance, NPC speech
// CALLED BY: _initExtensions
// EMITS: join_table, place_bet, deal_cards, make_decision, cash_out

CasinoScene.prototype._initBlackjackSocket = function() {
  if (!this.socket) return;

  // ── Blackjack state update ──────────────────────────────────────
  // Full blackjack state sync — phase, hands, pot, result
  this.socket.on('blackjack_update', (d) => {
    this._onBlackjackUpdate(d);
  });

  // ── Join table confirmed ────────────────────────────────────────
  this.socket.on('join_table_ok', (d) => {
    this._setHeaderTable(d.game.toUpperCase());
    this._showDealerSpeech(d.dealer_says);
    this._updateBalance(d.balance, null);
    this._onBlackjackUpdate(d.state);
    this._showToast(`Joined ${d.game} table`, 'success');
  });

  // ── Bet placed confirmed ────────────────────────────────────────
  this.socket.on('bet_placed', (d) => {
    this._updatePot(d.bet);
    this._onBlackjackUpdate(d.state);
    const dealBtn = document.getElementById('deal-btn');
    if (dealBtn) dealBtn.style.display = 'inline-flex';
  });

  // ── Cards dealt ─────────────────────────────────────────────────
  this.socket.on('cards_dealt', (d) => {
    this._showDealerSpeech(d.dealer_says);
    this._onBlackjackUpdate(d.state);
    const dealBtn = document.getElementById('deal-btn');
    if (dealBtn) dealBtn.style.display = 'none';
  });

  // ── Decision result (hit/stand/double/fold) ─────────────────────
  this.socket.on('decision_result', (d) => {
    this._showDealerSpeech(d.dealer_says || '');
    this._onBlackjackUpdate(d.state);
    // Trigger win/loss visual effects
    if (d.state.result === 'win' || d.state.result === 'blackjack') {
      this._triggerWinEffect(d.state.winnings);
    } else if (d.state.result === 'bust' || d.state.result === 'loss') {
      this._triggerLossEffect(Math.abs(d.state.winnings));
    }
  });

  // ── Cash out confirmed ──────────────────────────────────────────
  this.socket.on('cash_out_ok', (d) => {
    this._updateBalance(d.balance, null);
    this._showMiraSpeech(d.mira_says || '');
    this._renderTransactions(d.transactions || []);
    this._setHeaderTable('LOBBY');
    this._setPhase('LOBBY');
    this._syncActionButtons('idle');
    this._syncBetControls('idle', false);
    this._showToast('Cashed out successfully', 'success');
  });

  // ── Game update (dealer/Mira comments, chip updates) ────────────
  this.socket.on('game_update', (d) => {
    if (d.player_chips !== undefined) this._updateBalance(d.player_chips, null);
    if (d.dealer_comment) this._showDealerSpeech(d.dealer_comment);
    if (d.mira_comment) this._showMiraSpeech(d.mira_comment);
  });
};


// ═════════════════════════════════════════════════════════════════════
// BLACKJACK — State Application
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Override _applyBlackjackState with full impl
// CONNECTS: Card rendering, pot, action buttons, hand values, result banner
// CALLED BY: casino_state handler, blackjack_update handler

// Override the Kit stub with full implementation
CasinoScene.prototype._applyBlackjackState = function(d) {
  if (!d) return;
  this.state = { ...this.state, ...d };
  this._updateBalance(d.balance, null);
  this._setPhase(d.phase.toUpperCase());
  this._renderCards(d.player_hand || [], 'player-hand');
  this._renderCards(d.dealer_hand || [], 'dealer-hand');
  this._updateHandValue('player-value', d.player_value || 0, d.player_hand || []);
  this._updateHandValue('dealer-value', d.dealer_value || 0, d.dealer_hand || []);
  this._updatePot(d.bet || 0);
  this._renderTransactions(d.transactions || []);
  this._updateConsequences(d.consequences_pending || 0);
  this._syncActionButtons(d.phase);
  this._syncBetControls(d.phase, d.active);
  if (d.result) this._showResult(d);
};

// v1.50.0 [2026-03-22] — Wrapper for blackjack_update handler
// CONNECTS: _applyBlackjackState
// CALLED BY: blackjack_update socket event
CasinoScene.prototype._onBlackjackUpdate = function(d) {
  this._applyBlackjackState(d);
};


// ═════════════════════════════════════════════════════════════════════
// CARD RENDERING
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Render playing cards with flip animation,
// suit coloring, and face-down card backs
// CONNECTS: #player-hand, #dealer-hand DOM elements
// CALLED BY: _applyBlackjackState

CasinoScene.prototype._renderCards = function(hand, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  el.innerHTML = '';
  if (!hand || !hand.length) return;

  hand.forEach((cardStr, i) => {
    const div = document.createElement('div');
    div.className = 'card card-flip';
    div.style.animationDelay = `${i * 0.08}s`;

    // Face-down card (hidden card back)
    if (cardStr === '\uD83C\uDCA0' || cardStr === 'back') {
      div.classList.add('face-down');
    } else {
      // Parse suit and rank from card string (e.g., "K\u2660", "10\u2665")
      const suit = cardStr.slice(-1);
      const rank = cardStr.slice(0, -1);

      // Red suits get special coloring
      if (suit === '\u2665') div.classList.add('hearts');
      if (suit === '\u2666') div.classList.add('diamonds');

      const rankEl = document.createElement('div');
      rankEl.className = 'card-rank';
      rankEl.textContent = rank;

      const suitEl = document.createElement('div');
      suitEl.className = 'card-suit';
      suitEl.textContent = suit;

      div.appendChild(rankEl);
      div.appendChild(suitEl);
    }
    el.appendChild(div);
  });
};


// ═════════════════════════════════════════════════════════════════════
// HAND VALUE DISPLAY
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Show hand total with bust/blackjack markers
// CONNECTS: #player-value, #dealer-value DOM elements
// CALLED BY: _applyBlackjackState

CasinoScene.prototype._updateHandValue = function(id, value, hand) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!hand || !hand.length) {
    el.textContent = '';
    return;
  }
  const suffix = value > 21 ? ' BUST' : value === 21 ? ' \u2605' : '';
  el.textContent = `${value}${suffix}`;
};


// ═════════════════════════════════════════════════════════════════════
// POT DISPLAY & CHIP ANIMATION
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Update pot display with chip spin animation
// CONNECTS: #pot-display, #chip-spin DOM elements
// CALLED BY: _applyBlackjackState, bet_placed handler

CasinoScene.prototype._updatePot = function(amount) {
  const el = document.getElementById('pot-display');
  if (el) el.textContent = amount > 0 ? `$${amount}` : '\u2014';

  // Chip spin animation on non-zero bets
  if (amount > 0) {
    const chip = document.getElementById('chip-spin');
    if (chip) {
      chip.classList.remove('spinning');
      void chip.offsetWidth; // Force reflow to retrigger animation
      chip.classList.add('spinning');
      setTimeout(() => chip.classList.remove('spinning'), 700);
    }
  }
};


// ═════════════════════════════════════════════════════════════════════
// NPC SPEECH — Dealer Jack & Mira Chen
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Speech bubble updates with ring glow animation
// CONNECTS: #dealer-speech, #mira-speech, #dealer-ring, #mira-ring DOM
// CALLED BY: Various socket handlers (join_table_ok, cards_dealt, etc.)

CasinoScene.prototype._showDealerSpeech = function(text) {
  if (!text) return;
  const el = document.getElementById('dealer-speech');
  if (el) el.textContent = text;
  const ring = document.getElementById('dealer-ring');
  if (ring) {
    ring.classList.add('speaking');
    setTimeout(() => ring.classList.remove('speaking'), 2500);
  }
};

CasinoScene.prototype._showMiraSpeech = function(text) {
  if (!text) return;
  const el = document.getElementById('mira-speech');
  if (el) el.textContent = text;
  const ring = document.getElementById('mira-ring');
  if (ring) {
    ring.classList.add('speaking');
    setTimeout(() => ring.classList.remove('speaking'), 2500);
  }
};


// ═════════════════════════════════════════════════════════════════════
// RESULT BANNER
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Show win/loss/push/blackjack result banner
// CONNECTS: #result-banner DOM element
// CALLED BY: _applyBlackjackState when state.result is set

CasinoScene.prototype._showResult = function(state) {
  const banner = document.getElementById('result-banner');
  if (!banner) return;

  const map = {
    win:       { cls: 'win',  text: `WIN  +$${state.winnings}` },
    blackjack: { cls: 'win',  text: `BLACKJACK  +$${state.winnings}` },
    loss:      { cls: 'loss', text: `LOSS  -$${Math.abs(state.winnings)}` },
    bust:      { cls: 'loss', text: `BUST  -$${Math.abs(state.winnings)}` },
    push:      { cls: 'push', text: 'PUSH \u2014 Bet returned' },
    surrender: { cls: 'loss', text: `SURRENDER  -$${Math.abs(state.winnings)}` },
  };
  const info = map[state.result] || { cls: '', text: state.result };

  banner.className = `cn-result-banner ${info.cls}`;
  banner.textContent = info.text;
  banner.style.display = 'block';
  setTimeout(() => { banner.style.display = 'none'; }, 5000);
};

// v1.50.0 [2026-03-22] — Generic flash banner (for errors, announcements)
CasinoScene.prototype._flashBanner = function(text, type = 'loss') {
  const banner = document.getElementById('result-banner');
  if (!banner) return;
  banner.className = `cn-result-banner ${type}`;
  banner.textContent = text;
  banner.style.display = 'block';
  setTimeout(() => { banner.style.display = 'none'; }, 3500);
};


// ═════════════════════════════════════════════════════════════════════
// BET CONTROLS & TABLE JOIN
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Bet input, quick bets, join table, deal cards
// CONNECTS: #join-controls, #bet-controls, Socket.IO table events
// CALLED BY: _initExtensions
// EMITS: join_table, place_bet, deal_cards socket events

CasinoScene.prototype._initBetControls = function() {
  // Quick bet buttons — set bet input value
  $$('.cn-quick-bets .cn-btn--sm').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById('bet-input');
      if (!input) return;
      // MAX button has data-max attribute
      if (btn.dataset.max) {
        input.value = this.state.buy_in || 100;
      }
    });
  });
};

// v1.50.0 [2026-03-22] — Join a table via Socket.IO
// CONNECTS: Socket.IO join_table event
// EMITS: join_table { game, buy_in }
CasinoScene.prototype.joinTable = function() {
  const game = document.getElementById('game-select')?.value || 'blackjack';
  const buyIn = parseInt(document.getElementById('buy-in-input')?.value || '200', 10);
  if (this.socket) {
    this.socket.emit('join_table', { game, buy_in: buyIn });
  }
};

// v1.50.0 [2026-03-22] — Place a bet via Socket.IO
// CONNECTS: Socket.IO place_bet event
// EMITS: place_bet { amount, target }
CasinoScene.prototype.placeBet = function() {
  const amount = parseInt(document.getElementById('bet-input')?.value || '50', 10);
  if (this.socket) {
    this.socket.emit('place_bet', { amount, target: 'player_win' });
  }
};

// v1.50.0 [2026-03-22] — Quick-set bet amount
// CONNECTS: #bet-input DOM element
CasinoScene.prototype.quickBet = function(amount, useMax = false) {
  const input = document.getElementById('bet-input');
  if (!input) return;
  input.value = useMax ? (this.state.buy_in || 100) : amount;
};

// v1.50.0 [2026-03-22] — Deal cards via Socket.IO
// CONNECTS: Socket.IO deal_cards event
// EMITS: deal_cards
CasinoScene.prototype.dealCards = function() {
  if (this.socket) {
    this.socket.emit('deal_cards');
  }
};

// v1.50.0 [2026-03-22] — Make a blackjack decision (hit/stand/double/fold)
// CONNECTS: Socket.IO make_decision event
// EMITS: make_decision { action }
CasinoScene.prototype.makeDecision = function(action) {
  if (this.socket) {
    this.socket.emit('make_decision', { action });
  }
};

// v1.50.0 [2026-03-22] — Cash out and leave the table
// CONNECTS: Socket.IO cash_out event
// EMITS: cash_out
CasinoScene.prototype.cashOut = function() {
  if (this.socket) {
    this.socket.emit('cash_out');
  }
};


// ═════════════════════════════════════════════════════════════════════
// ACTION BUTTON SYNC
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Sync action button enabled/disabled state
// based on game phase. Wire onclick handlers.
// CONNECTS: #btn-hit, #btn-stand, #btn-double, #btn-fold, #btn-cashout
// CALLED BY: _initExtensions, _applyBlackjackState

CasinoScene.prototype._initActionButtons = function() {
  // Wire action buttons — these can't use data-action because they
  // need specific casino game logic, not generic action dispatch
  const wireBtn = (id, fn) => {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener('click', () => fn.call(this));
  };

  wireBtn('btn-hit', function() { this.makeDecision('hit'); });
  wireBtn('btn-stand', function() { this.makeDecision('stand'); });
  wireBtn('btn-double', function() { this.makeDecision('double'); });
  wireBtn('btn-fold', function() { this.makeDecision('fold'); });
  wireBtn('btn-cashout', function() { this.cashOut(); });
  wireBtn('join-btn', function() { this.joinTable(); });
  wireBtn('deal-btn', function() { this.dealCards(); });
  wireBtn('place-bet-btn', function() { this.placeBet(); });
  wireBtn('chat-send-btn', function() { this.sendMessage(); });
};

// v1.50.0 [2026-03-22] — Enable/disable action buttons based on game phase
// CONNECTS: Hit/Stand/Double/Fold/CashOut button DOM
// CALLED BY: _applyBlackjackState
CasinoScene.prototype._syncActionButtons = function(phase) {
  const active = phase === 'playing';
  ['btn-hit', 'btn-stand', 'btn-double', 'btn-fold'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = !active;
  });
  const co = document.getElementById('btn-cashout');
  if (co) co.style.display = (phase === 'result' || phase === 'idle') ? 'inline-flex' : 'none';
};

// v1.50.0 [2026-03-22] — Toggle between join controls and bet controls
// CONNECTS: #join-controls, #bet-controls DOM
// CALLED BY: _applyBlackjackState
CasinoScene.prototype._syncBetControls = function(phase, active) {
  const join = document.getElementById('join-controls');
  const bet = document.getElementById('bet-controls');
  if (!join || !bet) return;

  if (!active || phase === 'idle') {
    join.style.display = 'flex';
    bet.style.display = 'none';
  } else {
    join.style.display = 'none';
    bet.style.display = 'flex';
  }
};


// ═════════════════════════════════════════════════════════════════════
// CHAT — NPC Replies & Streaming
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Socket.IO chat message handlers, NPC responses,
// dealer/Mira speech bubble routing
// CONNECTS: Socket.IO chat_reply event, speech bubbles, chat log
// CALLED BY: _initExtensions

CasinoScene.prototype._initChatSocket = function() {
  if (!this.socket) return;

  // ── Chat reply from NPC ─────────────────────────────────────────
  this.socket.on('chat_reply', (d) => {
    const who = (d.character || 'NPC')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
    const text = d.message || '';
    this._appendChat(who, text);

    // Route to appropriate speech bubble
    if (d.character && d.character.includes('dealer')) {
      this._showDealerSpeech(text);
    } else if (d.character && (d.character.includes('mira') || d.character.includes('hustler'))) {
      this._showMiraSpeech(text);
    }
  });

  // ── Generic chat message (from server-side agent processing) ────
  this.socket.on('chat_message', (data) => {
    const sender = data.sender || data.character || 'NPC';
    const text = data.text || data.message || '';
    if (text) this._appendChat(sender, text);
  });

  // ── Streamed response chunks ────────────────────────────────────
  this.socket.on('stream_chunk', (data) => {
    const text = data.text || data.chunk || '';
    if (text) this._appendToLastLine(text);
  });

  // ── Stream end — finalize the line ──────────────────────────────
  this.socket.on('stream_end', () => {
    // Mark any streaming line as complete
    const log = document.getElementById('chat-log');
    if (!log) return;
    const streaming = log.querySelector('.streaming');
    if (streaming) streaming.classList.remove('streaming');
  });
};

// v1.50.0 [2026-03-22] — Append text to the last chat line (for streaming)
// CONNECTS: #chat-log DOM
CasinoScene.prototype._appendToLastLine = function(text) {
  const log = document.getElementById('chat-log');
  if (!log) return;

  let lastLine = log.lastElementChild;
  if (!lastLine || !lastLine.classList.contains('streaming')) {
    lastLine = document.createElement('div');
    lastLine.className = 'cn-chat-entry streaming';
    log.appendChild(lastLine);
  }
  lastLine.textContent += text;
  log.scrollTop = log.scrollHeight;
};


// ═════════════════════════════════════════════════════════════════════
// WIN / LOSS VISUAL EFFECTS
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Full-screen flash overlays with particle sparks
// CONNECTS: #flash-win, #flash-loss, #sparks-canvas DOM
// CALLED BY: decision_result socket handler

// v1.50.0 [2026-03-22] — Win effect: green flash + particle sparks + chip spin
// CONNECTS: #flash-win overlay, #sparks-canvas, #chip-spin
CasinoScene.prototype._triggerWinEffect = function(amount = 0) {
  const el = document.getElementById('flash-win');
  const amt = document.getElementById('flash-win-amount');
  if (el) {
    if (amt) amt.textContent = `+$${amount}`;
    el.style.display = 'flex';
    el.style.animation = 'none';
    void el.offsetWidth; // Force reflow for animation retrigger
    el.style.animation = 'flash-fade 2s ease-out forwards';
    setTimeout(() => { el.style.display = 'none'; }, 2100);
  }

  // Launch particle sparks
  this._launchSparks();

  // Chip celebration spin
  const chip = document.getElementById('chip-spin');
  if (chip) {
    chip.classList.remove('spinning');
    void chip.offsetWidth;
    chip.classList.add('spinning');
  }
};

// v1.50.0 [2026-03-22] — Loss effect: red flash + consequence warning
// CONNECTS: #flash-loss overlay, #consequence-toast
CasinoScene.prototype._triggerLossEffect = function(amount = 0) {
  const el = document.getElementById('flash-loss');
  const amt = document.getElementById('flash-loss-amount');
  if (el) {
    if (amt) amt.textContent = `-$${amount}`;
    el.style.display = 'flex';
    el.style.animation = 'none';
    void el.offsetWidth;
    el.style.animation = 'flash-fade 2s ease-out forwards';
    setTimeout(() => { el.style.display = 'none'; }, 2100);
  }

  // Show Mira consequence warning on big losses
  if (amount >= 100) {
    const toast = document.getElementById('consequence-toast');
    const msg = document.getElementById('consequence-msg');
    if (toast) {
      if (msg) msg.textContent = 'Mira will call in 24 hours.';
      toast.style.display = 'flex';
      setTimeout(() => { toast.style.display = 'none'; }, 6000);
    }
  }
};

// v1.50.0 [2026-03-22] — Canvas particle spark burst for win celebrations
// CONNECTS: #sparks-canvas DOM element
// CALLED BY: _triggerWinEffect
CasinoScene.prototype._launchSparks = function() {
  const canvas = document.getElementById('sparks-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  // Generate 80 particles radiating from center
  const particles = Array.from({ length: 80 }, () => ({
    x:     canvas.width * 0.5 + (Math.random() - 0.5) * 200,
    y:     canvas.height * 0.4 + (Math.random() - 0.5) * 100,
    vx:    (Math.random() - 0.5) * 12,
    vy:    Math.random() * -16 - 4,
    r:     Math.random() * 5 + 2,
    life:  1,
    decay: Math.random() * 0.02 + 0.015,
    color: ['#f97316', '#fbbf24', '#22c55e'][Math.floor(Math.random() * 3)],
  }));

  const animate = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let alive = false;
    particles.forEach(p => {
      if (p.life <= 0) return;
      alive = true;
      p.x += p.vx;
      p.vy += 0.4;     // Gravity
      p.y += p.vy;
      p.life -= p.decay;
      ctx.save();
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillStyle = p.color;
      ctx.shadowBlur = 8;
      ctx.shadowColor = p.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    });
    if (alive) {
      requestAnimationFrame(animate);
    } else {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  };
  requestAnimationFrame(animate);
};


// ═════════════════════════════════════════════════════════════════════
// WORLD STATUS HUD
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Periodic world status polling + Socket.IO push
// CONNECTS: /api/world/status REST, Socket.IO world_event,
//           #ws-credits, #ws-rep, #ws-heat, #vip-badge, #heat-lock-overlay
// CALLED BY: _initExtensions
// EMITS: world status DOM updates

CasinoScene.prototype._initWorldStatus = function() {
  // Initial load + periodic polling
  this._fetchWorldStatus();
  setInterval(() => this._fetchWorldStatus(), 60000);

  // Socket.IO push updates
  if (this.socket) {
    this.socket.on('world_event', () => {
      this._fetchWorldStatus();
    });

    // HUD update from world engine
    this.socket.on('hud_update', (data) => {
      if (data.credits !== undefined) {
        this._updateBalance(data.credits, null);
        const wsEl = document.getElementById('ws-credits');
        if (wsEl) wsEl.textContent = '\u20B5' + fmt(data.credits);
      }
      if (data.heat !== undefined) {
        const wsEl = document.getElementById('ws-heat');
        if (wsEl) {
          wsEl.textContent = Math.round(data.heat) + '/100';
          wsEl.style.color = data.heat >= 60 ? '#f00' : data.heat >= 40 ? '#f97316' : '#0f0';
        }
      }
      if (data.reputation !== undefined) {
        const wsEl = document.getElementById('ws-rep');
        if (wsEl) wsEl.textContent = Math.round(data.reputation) + '/100';
      }
    });
  }
};

// v1.50.0 [2026-03-22] — Fetch world status from REST API
// CONNECTS: /api/world/status endpoint
CasinoScene.prototype._fetchWorldStatus = function() {
  fetch('/api/world/status')
    .then(r => r.ok ? r.json() : null)
    .then(data => { if (data) this._applyWorldStatus(data); })
    .catch(e => console.debug('world status fetch failed', e));
};

// v1.50.0 [2026-03-22] — Apply world status data to DOM elements
// CONNECTS: World status DOM elements, VIP badge, heat lock overlay
CasinoScene.prototype._applyWorldStatus = function(data) {
  const safe = (v) => (v !== undefined && v !== null) ? v : '\u2014';

  const wsCredits = document.getElementById('ws-credits');
  const wsRep = document.getElementById('ws-rep');
  const wsHeat = document.getElementById('ws-heat');
  const vipBadge = document.getElementById('vip-badge');
  const heatOverlay = document.getElementById('heat-lock-overlay');

  if (wsCredits) wsCredits.textContent = '\u20B5' + safe(data.credits);
  if (wsRep) wsRep.textContent = safe(data.reputation) + '/100';
  if (wsHeat) {
    wsHeat.textContent = safe(data.heat) + '/100';
    wsHeat.style.color = data.heat >= 60 ? '#f00' : data.heat >= 40 ? '#f97316' : '#0f0';
  }

  // VIP badge visibility
  if (vipBadge) {
    vipBadge.style.display = data.vip_access ? 'inline-flex' : 'none';
  }

  // Heat lock overlay — blocks access when heat is too high
  if (heatOverlay) {
    if (data.heat_locked) {
      heatOverlay.style.display = 'flex';
      const heatVal = document.getElementById('heat-lock-value');
      if (heatVal) heatVal.textContent = 'HEAT: ' + data.heat + ' / 100';
    } else {
      heatOverlay.style.display = 'none';
    }
  }
};
