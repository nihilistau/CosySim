/* THE ARCADE — v0.68 Dark Renaissance
 * TheArcadeScene: Socket.IO client, game logic, sparks, bench HUD.
 */
'use strict';

// v1.49.1 [2026-03-22] — XSS escape helper for dynamic content
function _esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

class TheArcadeScene {
  constructor() {
    this.socket      = null;
    this.currentGame = null;   // active game type string
    this.player      = 'player';
    this.selectedDiceSides = 6;
    this._chatOpen   = false;
    this._sparksCtx  = null;
    this._sparksRaf  = null;
    this._particles  = [];
    this._benchSocket = null;
    this._benchData  = {};
  }

  // ── Init ───────────────────────────────────────────────────────────

  init() {
    this._setupSparks();
    this._setupSocket();
    this._setupDiceSelector();
    this._loadLeaderboard();
    console.debug('[TheArcade] init complete');
  }

  // ── Socket.IO ──────────────────────────────────────────────────────

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      this._setConnectionStatus(true);
      this.socket.emit('get_games_state', { player: this.player });
    });

    this.socket.on('disconnect', () => this._setConnectionStatus(false));
    this.socket.on('reconnect', () => {
      this._setConnectionStatus(true);
      this.loadState();
    });

    this.socket.on('game_update',         d => this._onGameUpdate(d));
    this.socket.on('games_state',         d => this._onGamesState(d));
    this.socket.on('game_started',        d => this._onGameStarted(d));

    // Mystery
    this.socket.on('mystery_started',     d => this._onMysteryStarted(d));
    this.socket.on('clue_revealed',       d => this._onClueRevealed(d));
    this.socket.on('accusation_result',   d => this._onAccusationResult(d));

    // Dice
    this.socket.on('dice_result',         d => this._onDiceResult(d));

    // Truth or Dare
    this.socket.on('tod_started',         d => this._onTodStarted(d));
    this.socket.on('tod_prompt',          d => this._onTodPrompt(d));
    this.socket.on('tod_scored',          d => this._onTodScored(d));
    this.socket.on('tod_complete',        d => this._onTodComplete(d));

    // Leaderboard
    this.socket.on('leaderboard_update',  d => this._renderLeaderboard(d.leaderboard || []));

    // Chat
    this.socket.on('chat_reply',          d => this._addChat('gm', d.message));

    // Errors
    this.socket.on('error',               d => this._addChat('gm', '\u26a0\ufe0f ' + d.message));
  }

  // ── State ──────────────────────────────────────────────────────────

  loadState() {
    this.socket.emit('get_games_state', { player: this.player });
  }

  // ── Game start ─────────────────────────────────────────────────────

  startGame(gameType) {
    this.currentGame = gameType;
    document.querySelectorAll('.game-card').forEach(c => {
      c.classList.toggle('active', c.dataset.game === gameType);
    });

    if (gameType === 'mystery') {
      this.socket.emit('mystery_start', { player: this.player });
    } else if (gameType === 'truth_or_dare') {
      this.socket.emit('tod_start', { player: this.player });
    } else {
      // Generic start for dice_challenge, trivia, word_game
      this.socket.emit('start_game', { game: gameType, player: this.player });
    }
  }

  // ── Answer submission ──────────────────────────────────────────────

  submitAnswer(answer) {
    if (this.currentGame === 'truth_or_dare') {
      const resp = (answer || '').trim();
      this.socket.emit('tod_answer', {
        player: this.player,
        response: resp,
        completed: resp.length > 0,
      });
    } else {
      this.socket.emit('submit_answer', { player: this.player, answer: answer || '' });
    }
  }

  // ── Dice ───────────────────────────────────────────────────────────

  rollDice(sides) {
    const s = sides || this.selectedDiceSides;
    const dice = document.getElementById('dice-3d');
    if (dice) {
      dice.classList.remove('rolling');
      void dice.offsetWidth; // reflow
      dice.classList.add('rolling');
    }
    document.getElementById('btn-roll-dice').disabled = true;
    this.socket.emit('roll_dice', { sides: s, player: this.player });
  }

  _setupDiceSelector() {
    const sel = document.getElementById('dice-selector');
    if (!sel) return;
    sel.querySelectorAll('.dice-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        sel.querySelectorAll('.dice-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.selectedDiceSides = parseInt(btn.dataset.sides, 10);
      });
    });
  }

  // ── Leaderboard ────────────────────────────────────────────────────

  _loadLeaderboard() {
    if (this.socket && this.socket.connected) {
      this.socket.emit('get_leaderboard', {});
    }
  }

  // ── Exit game ──────────────────────────────────────────────────────

  exitGame() {
    this.currentGame = null;
    document.querySelectorAll('.game-card').forEach(c => c.classList.remove('active'));
    this._renderGameArea(null, null);
  }

  // ── Socket event handlers ──────────────────────────────────────────

  _onGameUpdate(d) {
    if (d.leaderboard) this._renderLeaderboard(d.leaderboard);
    if (d.scores && d.scores[this.player]) {
      const s = d.scores[this.player];
      const el = document.getElementById('score-ticker');
      if (el) el.textContent = `${s.total_points || 0} pts`;
    }
  }

  _onGamesState(d) {
    if (d.leaderboard) this._renderLeaderboard(d.leaderboard);
    const el = document.getElementById('economy-balance');
    if (el && d.scores) el.textContent = `${d.scores.total_points || 0} pts`;
  }

  _onGameStarted(d) {
    this._renderGameArea(d.game, null);
    this._addChat('gm', d.message || 'Game started!');
    if (d.game === 'dice_challenge') {
      this._showPanel('dice-panel');
      this._typeText(document.getElementById('dice-narration'), d.message || 'Roll the dice!');
    } else if (d.game === 'trivia') {
      this._showPanel('trivia-panel');
    } else if (d.game === 'word_game') {
      this._showPanel('word-panel');
    }
  }

  // Mystery
  _onMysteryStarted(d) {
    this._showPanel('mystery-panel');
    document.getElementById('mystery-title').textContent = '\uD83D\uDD0D ' + d.case_title;
    document.getElementById('mystery-setting').textContent = d.setting || '';
    this._typeText(document.getElementById('mystery-narration'), d.narration || '');
    document.getElementById('clue-cards-grid').innerHTML = '';
    document.getElementById('board-strings').innerHTML = '';
    document.getElementById('clue-count').textContent = '0 / 5 clues';
    document.getElementById('clue-fill').style.width = '0%';
    document.getElementById('btn-clue').disabled = false;
    document.getElementById('btn-clue').style.display = '';
    document.getElementById('btn-accuse').style.display = 'none';
    document.getElementById('accuse-form').style.display = 'none';
    document.getElementById('mystery-result').style.display = 'none';
    this._addChat('gm', d.narration || 'The mystery begins...');
  }

  _onClueRevealed(d) {
    const pct = (d.clue_number / d.total) * 100;
    document.getElementById('clue-fill').style.width = pct + '%';
    document.getElementById('clue-count').textContent = `${d.clue_number} / ${d.total} clues`;

    if (d.clue) this._addCluePinToBoard(d.clue_number, d.clue);
    if (d.narration) {
      this._typeText(document.getElementById('mystery-narration'), d.narration);
      this._addChat('gm', d.narration);
    }

    if (d.all_found) {
      document.getElementById('btn-clue').style.display = 'none';
      document.getElementById('btn-accuse').style.display = '';
      this._addChat('gm', 'All clues found! Time to accuse...');
    }
    document.getElementById('btn-clue').disabled = false;
  }

  _onAccusationResult(d) {
    const box = document.getElementById('mystery-result');
    box.style.display = 'block';
    box.className = 'result-box ' + (d.correct ? 'result-win' : 'result-loss');
    box.innerHTML = d.correct
      ? `\uD83C\uDF89 <strong>CASE SOLVED!</strong> The culprit was ${d.real_culprit}!`
      : `\u274C <strong>Wrong!</strong> You said "${d.suspect}" but it was ${d.real_culprit}.`;
    this._typeText(document.getElementById('mystery-narration'), d.reaction || '');
    this._addChat('gm', d.reaction || (d.correct ? 'Brilliant!' : 'Not quite...'));
    document.getElementById('accuse-form').style.display = 'none';
    document.getElementById('btn-accuse').style.display = 'none';
    if (d.correct) this._launchSparks();
  }

  // Dice
  _onDiceResult(d) {
    const dice = document.getElementById('dice-3d');
    if (dice) {
      setTimeout(() => dice.classList.remove('rolling'), 800);
    }
    const numEl = document.getElementById('dice-number');
    const lblEl = document.getElementById('dice-label-result');
    const resEl = document.getElementById('dice-result-display');
    if (numEl) numEl.textContent = d.roll;
    if (lblEl) lblEl.textContent = `d${d.sides}${d.is_max ? ' \u2b50 MAX ROLL!' : ''}`;
    if (resEl) resEl.style.display = 'block';

    this._typeText(document.getElementById('dice-narration'), d.narration || `Rolled ${d.roll}!`);
    this._addChat('gm', d.narration || `Rolled ${d.roll} on a d${d.sides}!`);
    document.getElementById('btn-roll-dice').disabled = false;
    if (d.is_max) this._launchSparks();
  }

  // Truth or Dare
  _onTodStarted(d) {
    this._showPanel('tod-panel');
    this._typeText(document.getElementById('tod-narration'), d.message || 'Truth or Dare begins!');
    document.getElementById('tod-score').textContent = '0';
    document.getElementById('tod-prompt-area').style.display = 'none';
    document.getElementById('tod-result').style.display = 'none';
    this._addChat('gm', d.message || 'Truth or Dare begins!');
  }

  _onTodPrompt(d) {
    document.getElementById('tod-type').textContent = d.type === 'truth' ? '\uD83D\uDCAC TRUTH' : '\uD83D\uDD25 DARE';
    document.getElementById('tod-type').className = 'tod-badge ' + d.type;
    document.getElementById('tod-prompt-text').textContent = d.prompt;
    document.getElementById('tod-prompt-area').style.display = 'block';
    document.getElementById('tod-response').value = '';
    document.getElementById('btn-tod-roll').disabled = false;
    if (d.narration) {
      this._typeText(document.getElementById('tod-narration'), d.narration);
      this._addChat('gm', d.narration);
    }
  }

  _onTodScored(d) {
    document.getElementById('tod-score').textContent = d.score;
    document.getElementById('tod-prompt-area').style.display = 'none';
    document.getElementById('btn-tod-roll').disabled = false;
  }

  _onTodComplete(d) {
    document.getElementById('tod-score').textContent = d.score;
    document.getElementById('tod-prompt-area').style.display = 'none';
    const box = document.getElementById('tod-result');
    box.style.display = 'block';
    box.className = 'result-box result-win';
    box.innerHTML = `\uD83C\uDF89 <strong>YOU WIN!</strong> Final score: ${d.score}`;
    this._typeText(document.getElementById('tod-narration'), d.reaction || '');
    this._addChat('gm', d.reaction || 'You win!');
    this._launchSparks();
  }

  // ── Internal game area helpers ─────────────────────────────────────

  _renderGameArea(game, state) {
    const panels = ['game-idle', 'mystery-panel', 'dice-panel', 'tod-panel', 'trivia-panel', 'word-panel'];
    panels.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });

    const map = {
      mystery:       'mystery-panel',
      dice_challenge: 'dice-panel',
      truth_or_dare: 'tod-panel',
      trivia:        'trivia-panel',
      word_game:     'word-panel',
    };

    const target = game ? map[game] : 'game-idle';
    const el = document.getElementById(target || 'game-idle');
    if (el) el.style.display = 'block';
  }

  _showPanel(panelId) {
    this._renderGameArea(null, null); // hide all
    const el = document.getElementById(panelId);
    if (el) el.style.display = 'block';
  }

  // ── Mystery sub-actions ────────────────────────────────────────────

  _mysteryClue() {
    document.getElementById('btn-clue').disabled = true;
    this.socket.emit('mystery_clue', { player: this.player });
  }

  _mysteryAccuse() {
    const suspect = (document.getElementById('suspect-input').value || '').trim();
    if (!suspect) return;
    this.socket.emit('mystery_accuse', { player: this.player, suspect });
  }

  // ── ToD sub-action ─────────────────────────────────────────────────

  _todRoll() {
    document.getElementById('btn-tod-roll').disabled = true;
    this.socket.emit('tod_roll', { player: this.player });
  }

  // ── Investigation board pin ────────────────────────────────────────

  _addCluePinToBoard(num, text) {
    const grid = document.getElementById('clue-cards-grid');
    const svg  = document.getElementById('board-strings');
    if (!grid) return;

    const pin = document.createElement('div');
    pin.className = 'clue-pin';
    pin.id = `clue-pin-${num}`;
    pin.innerHTML = `<div class="clue-pin__num">Clue #${num}</div>${_esc(text)}`;
    grid.appendChild(pin);

    // Draw strings to previous pins
    if (num > 1 && svg) {
      const prev = document.getElementById(`clue-pin-${num - 1}`);
      if (prev) {
        const r1 = prev.getBoundingClientRect();
        const r2 = pin.getBoundingClientRect();
        const boardRect = svg.getBoundingClientRect();
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', r1.left + r1.width / 2 - boardRect.left);
        line.setAttribute('y1', r1.top  + r1.height / 2 - boardRect.top);
        line.setAttribute('x2', r2.left + r2.width / 2 - boardRect.left);
        line.setAttribute('y2', r2.top  + r2.height / 2 - boardRect.top);
        svg.appendChild(line);
      }
    }
  }

  // ── Leaderboard rendering ──────────────────────────────────────────

  _renderLeaderboard(entries) {
    const list = document.getElementById('leaderboard-list');
    if (!list) return;
    if (!entries || !entries.length) {
      list.innerHTML = '<li class="lb-empty">No scores yet</li>';
      return;
    }
    const medals = ['\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'];
    list.innerHTML = entries.map((e, i) => `
      <li class="lb-entry ${i < 3 ? 'lb-entry--top' : ''}">
        <span class="lb-rank">${medals[i] || (i + 1) + '.'}</span>
        <span class="lb-name">${e.player || 'Unknown'}</span>
        <span class="lb-score">${e.points || 0} pts</span>
      </li>
    `).join('');
  }

  // ── Chat ───────────────────────────────────────────────────────────

  sendMessage(text) {
    const t = (text || '').trim();
    if (!t) return;
    this._addChat('you', t);
    this.socket.emit('chat_message', { message: t });
    const inp = document.getElementById('chat-input');
    if (inp) inp.value = '';
  }

  _addChat(who, text) {
    const msgs = document.getElementById('chat-messages');
    if (!msgs) return;
    const msg = document.createElement('div');
    msg.className = 'chat-msg ' + (who === 'you' ? 'chat-you' : 'chat-gm');
    msg.innerHTML = `<strong>${who === 'you' ? 'You' : '\uD83C\uDFAD GameMaster'}:</strong> ${_esc(text)}`;
    msgs.appendChild(msg);
    msgs.scrollTop = msgs.scrollHeight;
  }

  _toggleChat() {
    this._chatOpen = !this._chatOpen;
    const msgs = document.getElementById('chat-messages');
    const row  = document.getElementById('chat-input-row');
    const icon = document.getElementById('chat-toggle-icon');
    if (msgs) msgs.style.display = this._chatOpen ? 'flex' : 'none';
    if (row)  row.style.display  = this._chatOpen ? 'flex' : 'none';
    if (icon) icon.textContent   = this._chatOpen ? '\u25bc' : '\u25b2';
  }

  // ── Status ─────────────────────────────────────────────────────────

  _setConnectionStatus(online) {
    const el = document.getElementById('connection-status');
    if (!el) return;
    el.textContent = online ? '\uD83D\uDFE2 Connected' : '\uD83D\uDD34 Disconnected';
    el.className   = 'status-dot ' + (online ? 'connected' : 'disconnected');
  }

  // ── Type-writer effect ─────────────────────────────────────────────

  _typeText(el, text, speed = 16) {
    if (!el) return;
    el.textContent = '';
    let i = 0;
    const tick = () => {
      if (i < text.length) {
        el.textContent += text[i++];
        setTimeout(tick, speed);
      }
    };
    tick();
  }

  // ── Sparks particle system ─────────────────────────────────────────

  _setupSparks() {
    const canvas = document.getElementById('sparks-canvas');
    if (!canvas) return;
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    this._sparksCtx = canvas.getContext('2d');
    window.addEventListener('resize', () => {
      canvas.width  = window.innerWidth;
      canvas.height = window.innerHeight;
    });
  }

  _launchSparks(cx, cy) {
    const canvas = document.getElementById('sparks-canvas');
    if (!canvas || !this._sparksCtx) return;
    const x = cx !== undefined ? cx : canvas.width  / 2;
    const y = cy !== undefined ? cy : canvas.height / 2;

    for (let i = 0; i < 80; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = Math.random() * 6 + 2;
      this._particles.push({
        x, y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - Math.random() * 3,
        life: 1,
        decay: Math.random() * 0.025 + 0.01,
        size: Math.random() * 3 + 1,
        // violet hues
        hue: 260 + Math.random() * 40,
      });
    }
    if (!this._sparksRaf) this._animateSparks();
  }

  _animateSparks() {
    const ctx = this._sparksCtx;
    const canvas = ctx.canvas;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    this._particles = this._particles.filter(p => p.life > 0);
    for (const p of this._particles) {
      p.x    += p.vx;
      p.y    += p.vy;
      p.vy   += 0.12; // gravity
      p.life -= p.decay;
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillStyle   = `hsl(${p.hue}, 90%, 65%)`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    if (this._particles.length > 0) {
      this._sparksRaf = requestAnimationFrame(() => this._animateSparks());
    } else {
      this._sparksRaf = null;
    }
  }
}

// ── Bootstrap ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  window._arcade = new TheArcadeScene();
  window._arcade.init();
});