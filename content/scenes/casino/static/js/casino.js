/**
 * CLUB NOIR — casino.js  v0.68 Dark Renaissance
 * ClubNoirScene: Socket.IO client + blackjack UI + particle effects
 */
'use strict';

class ClubNoirScene {
  constructor() {
    this.socket       = null;
    this.state        = {};
    this._prevBalance = null;
    this._sparksAnim  = null;
    this._flashTimer  = null;
  }

  // ── Lifecycle ─────────────────────────────────────────────────

  init() {
    this._setupSocket();
    this._setupBenchSocket();
    console.log('[ClubNoir] Scene initialised');
  }

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect',         ()   => this._onConnect());
    this.socket.on('casino_state',    (d)  => this._onCasinoState(d));
    this.socket.on('blackjack_update',(d)  => this._onBlackjackUpdate(d));
    this.socket.on('join_table_ok',   (d)  => this._onJoinTableOk(d));
    this.socket.on('bet_placed',      (d)  => this._onBetPlaced(d));
    this.socket.on('cards_dealt',     (d)  => this._onCardsDealt(d));
    this.socket.on('decision_result', (d)  => this._onDecisionResult(d));
    this.socket.on('cash_out_ok',     (d)  => this._onCashOutOk(d));
    this.socket.on('chat_reply',      (d)  => this._onChatReply(d));
    this.socket.on('game_update',     (d)  => this._onGameUpdate(d));
    this.socket.on('error',           (d)  => this._onError(d));
    this.socket.on('disconnect',      ()   => this._setPhase('DISCONNECTED'));
  }

  _setupBenchSocket() {
    setInterval(() => {
      fetch('/api/bench/metrics')
        .then(r => r.ok ? r.json() : null)
        .then(d => d && this._updateBench(d))
        .catch(() => {});
    }, 4000);
  }

  // ── Socket events ─────────────────────────────────────────────

  _onConnect() {
    this.socket.emit('get_casino_state');
  }

  _onCasinoState(d) {
    this._updateBalance(d.balance, null);
    if (d.blackjack) this._onBlackjackUpdate(d.blackjack);
    this._renderTransactions(d.transactions || []);
    this._updateConsequences(d.consequences_pending || 0);
    this._setHeaderTable(d.active_game || 'LOBBY');
  }

  _onBlackjackUpdate(d) {
    this.state = d;
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
  }

  _onJoinTableOk(d) {
    this._setHeaderTable(d.game.toUpperCase());
    this._showDealerSpeech(d.dealer_says);
    this._updateBalance(d.balance, null);
    this._onBlackjackUpdate(d.state);
  }

  _onBetPlaced(d) {
    this._updatePot(d.bet);
    this._onBlackjackUpdate(d.state);
    const dealBtn = document.getElementById('deal-btn');
    if (dealBtn) dealBtn.style.display = 'inline-flex';
  }

  _onCardsDealt(d) {
    this._showDealerSpeech(d.dealer_says);
    this._onBlackjackUpdate(d.state);
    const dealBtn = document.getElementById('deal-btn');
    if (dealBtn) dealBtn.style.display = 'none';
  }

  _onDecisionResult(d) {
    this._showDealerSpeech(d.dealer_says || '');
    this._onBlackjackUpdate(d.state);
    if (d.state.result === 'win' || d.state.result === 'blackjack') {
      this._triggerWinEffect(d.state.winnings);
    } else if (d.state.result === 'bust' || d.state.result === 'loss') {
      this._triggerLossEffect(Math.abs(d.state.winnings));
    }
  }

  _onCashOutOk(d) {
    this._updateBalance(d.balance, null);
    this._showMiraSpeech(d.mira_says || '');
    this._renderTransactions(d.transactions || []);
    this._setHeaderTable('LOBBY');
    this._setPhase('LOBBY');
    this._syncActionButtons('idle');
    this._syncBetControls('idle', false);
  }

  _onChatReply(d) {
    const who  = d.character.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    const text = d.message;
    this._appendChat(who, text);
    if (d.character.includes('dealer')) this._showDealerSpeech(text);
    else if (d.character.includes('mira') || d.character.includes('hustler')) this._showMiraSpeech(text);
  }

  _onGameUpdate(d) {
    if (d.player_chips !== undefined) this._updateBalance(d.player_chips, null);
    if (d.dealer_comment) this._showDealerSpeech(d.dealer_comment);
    if (d.mira_comment)   this._showMiraSpeech(d.mira_comment);
  }

  _onError(d) {
    const msg = d.message || d.error || 'An error occurred';
    console.warn('[ClubNoir] Server error:', msg);
    this._flashBanner(msg, 'loss');
  }

  // ── Public API ────────────────────────────────────────────────

  loadState() {
    this.socket.emit('get_casino_state');
  }

  joinTable() {
    const game  = document.getElementById('game-select')?.value  || 'blackjack';
    const buyIn = parseInt(document.getElementById('buy-in-input')?.value || '200', 10);
    this.socket.emit('join_table', { game, buy_in: buyIn });
  }

  placeBet() {
    const amount = parseInt(document.getElementById('bet-input')?.value || '50', 10);
    this.socket.emit('place_bet', { amount, target: 'player_win' });
  }

  quickBet(amount, useMax = false) {
    const input = document.getElementById('bet-input');
    if (!input) return;
    input.value = useMax ? (this.state.buy_in || 100) : amount;
  }

  dealCards() {
    this.socket.emit('deal_cards');
  }

  makeDecision(action) {
    this.socket.emit('make_decision', { action });
  }

  cashOut() {
    this.socket.emit('cash_out');
  }

  sendMessage(text) {
    const inp = document.getElementById('chat-msg');
    const msg = text || (inp ? inp.value.trim() : '');
    if (!msg) return;
    const target = document.getElementById('chat-target')?.value || 'dealer_jack';
    this.socket.emit('chat_message', { message: msg, target });
    this._appendChat('You', msg);
    if (inp) inp.value = '';
  }

  // ── Rendering ─────────────────────────────────────────────────

  _renderCards(hand, targetId) {
    const el = document.getElementById(targetId);
    if (!el) return;
    el.innerHTML = '';
    if (!hand || !hand.length) return;
    hand.forEach((cardStr, i) => {
      const div = document.createElement('div');
      div.className = 'card card-flip';
      div.style.animationDelay = `${i * 0.08}s`;
      if (cardStr === '🂠' || cardStr === 'back') {
        div.classList.add('face-down');
      } else {
        const suit = cardStr.slice(-1);
        const rank = cardStr.slice(0, -1);
        if (suit === '♥') div.classList.add('hearts');
        if (suit === '♦') div.classList.add('diamonds');
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
  }

  _updateBalance(amount, delta) {
    if (amount === null || amount === undefined) return;
    ['credits-main', 'balance-display'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = `$${Number(amount).toLocaleString()}`;
    });
    const deltaEl = document.getElementById('credits-delta');
    if (deltaEl && delta !== null && delta !== undefined) {
      deltaEl.textContent = delta > 0 ? `+$${delta}` : `-$${Math.abs(delta)}`;
      deltaEl.className = 'cn-credits-delta ' + (delta >= 0 ? 'positive' : 'negative');
      setTimeout(() => { deltaEl.textContent = ''; deltaEl.className = 'cn-credits-delta'; }, 3000);
    }
    this._prevBalance = amount;
  }

  _updatePot(amount) {
    const el = document.getElementById('pot-display');
    if (el) el.textContent = amount > 0 ? `$${amount}` : '—';
    if (amount > 0) {
      const chip = document.getElementById('chip-spin');
      if (chip) {
        chip.classList.remove('spinning');
        void chip.offsetWidth;
        chip.classList.add('spinning');
        setTimeout(() => chip.classList.remove('spinning'), 700);
      }
    }
  }

  _updateHandValue(id, value, hand) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!hand || !hand.length) { el.textContent = ''; return; }
    const suffix = value > 21 ? ' BUST' : value === 21 ? ' ★' : '';
    el.textContent = `${value}${suffix}`;
  }

  _setPhase(phase) {
    const badge = document.getElementById('phase-badge');
    if (badge) badge.textContent = phase;
  }

  _setHeaderTable(name) {
    const el = document.getElementById('table-name-display');
    if (el) el.textContent = name;
  }

  _showDealerSpeech(text) {
    if (!text) return;
    const el = document.getElementById('dealer-speech');
    if (el) el.textContent = text;
    const ring = document.getElementById('dealer-ring');
    if (ring) {
      ring.classList.add('speaking');
      setTimeout(() => ring.classList.remove('speaking'), 2500);
    }
  }

  _showMiraSpeech(text) {
    if (!text) return;
    const el = document.getElementById('mira-speech');
    if (el) el.textContent = text;
    const ring = document.getElementById('mira-ring');
    if (ring) {
      ring.classList.add('speaking');
      setTimeout(() => ring.classList.remove('speaking'), 2500);
    }
  }

  _showResult(state) {
    const banner = document.getElementById('result-banner');
    if (!banner) return;
    const map = {
      win:       { cls: 'win',  text: `WIN  +$${state.winnings}` },
      blackjack: { cls: 'win',  text: `BLACKJACK  +$${state.winnings}` },
      loss:      { cls: 'loss', text: `LOSS  -$${Math.abs(state.winnings)}` },
      bust:      { cls: 'loss', text: `BUST  -$${Math.abs(state.winnings)}` },
      push:      { cls: 'push', text: 'PUSH — Bet returned' },
      surrender: { cls: 'loss', text: `SURRENDER  -$${Math.abs(state.winnings)}` },
    };
    const info = map[state.result] || { cls: '', text: state.result };
    banner.className = `cn-result-banner ${info.cls}`;
    banner.textContent = info.text;
    banner.style.display = 'block';
    setTimeout(() => { banner.style.display = 'none'; }, 5000);
  }

  _flashBanner(text, type = 'loss') {
    const banner = document.getElementById('result-banner');
    if (!banner) return;
    banner.className = `cn-result-banner ${type}`;
    banner.textContent = text;
    banner.style.display = 'block';
    setTimeout(() => { banner.style.display = 'none'; }, 3500);
  }

  _renderTransactions(txs) {
    const list = document.getElementById('tx-list');
    if (!list || !txs || !txs.length) return;
    list.innerHTML = '';
    [...txs].reverse().forEach(tx => {
      const li = document.createElement('li');
      li.className = `cn-tx cn-tx--${tx.type}`;
      const sign = tx.type === 'credit' ? '+' : '-';
      li.innerHTML = `<span>${tx.reason.split(':')[0]}</span><span>${sign}$${tx.amount}</span>`;
      list.appendChild(li);
    });
  }

  _updateConsequences(count) {
    const area = document.getElementById('consequence-area');
    if (!area) return;
    area.innerHTML = count > 0
      ? `<span class="consequence-badge">⚠ ${count} PENDING</span>`
      : '<span class="cn-no-debts">All clear… for now.</span>';
  }

  _updateBench(d) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('bench-ms',     d.response_ms ? `${d.response_ms}ms` : '—ms');
    set('bench-model',  d.model_id || '—');
    set('bench-tokens', d.tokens_out  ? `${d.tokens_out} tok` : '—');
    set('bench-nexus',  d.nexus_tier || '—');
  }

  _syncActionButtons(phase) {
    const active = phase === 'playing';
    ['btn-hit','btn-stand','btn-double','btn-fold'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = !active;
    });
    const co = document.getElementById('btn-cashout');
    if (co) co.style.display = (phase === 'result' || phase === 'idle') ? 'inline-flex' : 'none';
  }

  _syncBetControls(phase, active) {
    const join = document.getElementById('join-controls');
    const bet  = document.getElementById('bet-controls');
    if (!join || !bet) return;
    if (!active || phase === 'idle') {
      join.style.display = 'flex';
      bet.style.display  = 'none';
    } else {
      join.style.display = 'none';
      bet.style.display  = 'flex';
    }
  }

  _appendChat(who, text) {
    const log = document.getElementById('chat-log');
    if (!log) return;
    const entry = document.createElement('div');
    entry.className = 'cn-chat-entry';
    entry.innerHTML =
      `<span class="cn-chat-who">${who}:</span> <span class="cn-chat-text">${text}</span>`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
  }

  // ── Effects ───────────────────────────────────────────────────

  _triggerWinEffect(amount = 0) {
    const el  = document.getElementById('flash-win');
    const amt = document.getElementById('flash-win-amount');
    if (el) {
      if (amt) amt.textContent = `+$${amount}`;
      el.style.display    = 'flex';
      el.style.animation  = 'none';
      void el.offsetWidth;
      el.style.animation  = 'flash-fade 2s ease-out forwards';
      setTimeout(() => { el.style.display = 'none'; }, 2100);
    }
    this._launchSparks();
    const chip = document.getElementById('chip-spin');
    if (chip) {
      chip.classList.remove('spinning');
      void chip.offsetWidth;
      chip.classList.add('spinning');
    }
  }

  _triggerLossEffect(amount = 0) {
    const el  = document.getElementById('flash-loss');
    const amt = document.getElementById('flash-loss-amount');
    if (el) {
      if (amt) amt.textContent = `-$${amount}`;
      el.style.display   = 'flex';
      el.style.animation = 'none';
      void el.offsetWidth;
      el.style.animation = 'flash-fade 2s ease-out forwards';
      setTimeout(() => { el.style.display = 'none'; }, 2100);
    }
    if (amount >= 100) {
      const toast = document.getElementById('consequence-toast');
      const msg   = document.getElementById('consequence-msg');
      if (toast) {
        if (msg) msg.textContent = 'Mira will call in 24 hours.';
        toast.style.display = 'flex';
        setTimeout(() => { toast.style.display = 'none'; }, 6000);
      }
    }
  }

  _launchSparks() {
    const canvas = document.getElementById('sparks-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    const particles = Array.from({ length: 80 }, () => ({
      x:    canvas.width  * 0.5 + (Math.random() - 0.5) * 200,
      y:    canvas.height * 0.4 + (Math.random() - 0.5) * 100,
      vx:   (Math.random() - 0.5) * 12,
      vy:   Math.random() * -16 - 4,
      r:    Math.random() * 5 + 2,
      life: 1,
      decay: Math.random() * 0.02 + 0.015,
      color: ['#f97316','#fbbf24','#22c55e'][Math.floor(Math.random() * 3)],
    }));
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      let alive = false;
      particles.forEach(p => {
        if (p.life <= 0) return;
        alive   = true;
        p.x    += p.vx;
        p.vy   += 0.4;
        p.y    += p.vy;
        p.life -= p.decay;
        ctx.save();
        ctx.globalAlpha = Math.max(0, p.life);
        ctx.fillStyle   = p.color;
        ctx.shadowBlur  = 8;
        ctx.shadowColor = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      });
      if (alive) requestAnimationFrame(animate);
      else ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
    requestAnimationFrame(animate);
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  window._casino = new ClubNoirScene();
  window._casino.init();
});
