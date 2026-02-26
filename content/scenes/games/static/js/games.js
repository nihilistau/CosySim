/* Games Arcade — interactive client-side logic */
'use strict';

const socket = io();
let currentGame = null;

// ── Helpers ─────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function addChatMessage(who, text) {
  const el = $('chat-messages');
  const msg = document.createElement('div');
  msg.className = `chat-msg ${who === 'you' ? 'chat-you' : 'chat-gm'}`;
  msg.innerHTML = `<strong>${who === 'you' ? 'You' : '🎭 GameMaster'}:</strong> ${text}`;
  el.appendChild(msg);
  el.scrollTop = el.scrollHeight;
}

function showPanel(id) {
  ['game-select', 'mystery-panel', 'tod-panel'].forEach(p => {
    $(p).style.display = p === id ? 'block' : 'none';
  });
}

function typeText(el, text, speed = 20) {
  el.textContent = '';
  let i = 0;
  const timer = setInterval(() => {
    if (i < text.length) {
      el.textContent += text[i++];
    } else {
      clearInterval(timer);
    }
  }, speed);
}

// ── Socket.IO Events ────────────────────────────────────────────────

socket.on('connect', () => {
  $('connection-status').textContent = '🟢 Connected';
  $('connection-status').className = 'connected';
});

socket.on('disconnect', () => {
  $('connection-status').textContent = '🔴 Disconnected';
  $('connection-status').className = 'disconnected';
});

socket.on('reconnect', () => {
  $('connection-status').textContent = '🟢 Reconnected';
});

socket.on('game_update', (data) => {
  if (data.scores && data.scores.player) {
    const s = data.scores.player;
    $('score-display').textContent =
      `Mysteries: ${s.mystery_wins || 0}W / ${s.mystery_losses || 0}L · T&D: ${s.tod_score || 0}pts`;
  }
});

socket.on('error', (data) => {
  addChatMessage('gm', `⚠️ ${data.message}`);
});

// ── Mystery Events ──────────────────────────────────────────────────

socket.on('mystery_started', (data) => {
  currentGame = 'mystery';
  showPanel('mystery-panel');
  $('mystery-title').textContent = `🔍 ${data.case_title}`;
  $('mystery-setting').textContent = data.setting;
  typeText($('mystery-narration'), data.narration);
  $('clues-list').innerHTML = '';
  $('clue-count').textContent = '0 / 5 clues';
  $('clue-fill').style.width = '0%';
  $('btn-clue').style.display = '';
  $('btn-accuse').style.display = 'none';
  $('accuse-form').style.display = 'none';
  $('mystery-result').style.display = 'none';
  addChatMessage('gm', data.narration);
});

socket.on('clue_revealed', (data) => {
  const pct = (data.clue_number / data.total) * 100;
  $('clue-fill').style.width = pct + '%';
  $('clue-count').textContent = `${data.clue_number} / ${data.total} clues`;

  if (data.clue) {
    const item = document.createElement('div');
    item.className = 'clue-item';
    item.innerHTML = `<span class="clue-num">#${data.clue_number}</span> ${data.clue}`;
    $('clues-list').appendChild(item);
  }

  if (data.narration) {
    typeText($('mystery-narration'), data.narration);
    addChatMessage('gm', data.narration);
  }

  if (data.all_found) {
    $('btn-clue').style.display = 'none';
    $('btn-accuse').style.display = '';
    addChatMessage('gm', 'All clues found! Time to name the culprit...');
  }

  $('btn-clue').disabled = false;
});

socket.on('accusation_result', (data) => {
  const result = $('mystery-result');
  result.style.display = 'block';
  result.className = `result ${data.correct ? 'result-win' : 'result-loss'}`;
  result.innerHTML = data.correct
    ? `🎉 <strong>CASE SOLVED!</strong> The culprit was ${data.real_culprit}!`
    : `❌ <strong>Wrong!</strong> You said "${data.suspect}" but it was ${data.real_culprit}.`;

  typeText($('mystery-narration'), data.reaction);
  addChatMessage('gm', data.reaction);
  $('accuse-form').style.display = 'none';
  $('btn-accuse').style.display = 'none';
  $('btn-clue').style.display = 'none';
});

// ── Truth or Dare Events ────────────────────────────────────────────

socket.on('tod_started', (data) => {
  currentGame = 'tod';
  showPanel('tod-panel');
  typeText($('tod-narration'), data.message);
  $('tod-score').textContent = '0';
  $('tod-prompt-area').style.display = 'none';
  $('tod-result').style.display = 'none';
  addChatMessage('gm', data.message);
});

socket.on('tod_prompt', (data) => {
  $('tod-type').textContent = data.type === 'truth' ? '💬 TRUTH' : '🔥 DARE';
  $('tod-type').className = `tod-badge ${data.type}`;
  $('tod-prompt-text').textContent = data.prompt;
  $('tod-prompt-area').style.display = 'block';
  $('tod-response').value = '';
  $('btn-roll').disabled = false;

  if (data.narration) {
    typeText($('tod-narration'), data.narration);
    addChatMessage('gm', data.narration);
  }
});

socket.on('tod_scored', (data) => {
  $('tod-score').textContent = data.score;
  $('tod-prompt-area').style.display = 'none';
});

socket.on('tod_complete', (data) => {
  $('tod-score').textContent = data.score;
  $('tod-prompt-area').style.display = 'none';
  const result = $('tod-result');
  result.style.display = 'block';
  result.className = 'result result-win';
  result.innerHTML = `🎉 <strong>YOU WIN!</strong> Final score: ${data.score}`;
  typeText($('tod-narration'), data.reaction);
  addChatMessage('gm', data.reaction);
});

// ── Chat Events ─────────────────────────────────────────────────────

socket.on('chat_reply', (data) => {
  addChatMessage('gm', data.message);
});

// ── UI Actions ──────────────────────────────────────────────────────

function startMystery() {
  socket.emit('mystery_start', { player: 'player' });
}

function getClue() {
  $('btn-clue').disabled = true;
  socket.emit('mystery_clue', { player: 'player' });
}

function showAccuseForm() {
  $('accuse-form').style.display = 'flex';
  $('suspect-input').focus();
}

function makeAccusation() {
  const suspect = $('suspect-input').value.trim();
  if (!suspect) return;
  socket.emit('mystery_accuse', { player: 'player', suspect: suspect });
}

function startTOD() {
  socket.emit('tod_start', { player: 'player' });
}

function rollDice() {
  $('btn-roll').disabled = true;
  socket.emit('tod_roll', { player: 'player' });
}

function submitAnswer(completed) {
  const response = $('tod-response').value.trim();
  socket.emit('tod_answer', {
    player: 'player',
    response: response,
    completed: completed,
  });
}

function exitGame() {
  currentGame = null;
  showPanel('game-select');
}

function toggleChat() {
  const msgs = $('chat-messages');
  const input = $('chat-input-area');
  const toggle = $('chat-toggle');
  const isHidden = msgs.style.display === 'none';
  msgs.style.display = isHidden ? 'block' : 'none';
  input.style.display = isHidden ? 'flex' : 'none';
  toggle.textContent = isHidden ? '▼' : '▲';
}

function sendChat() {
  const input = $('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  addChatMessage('you', msg);
  socket.emit('chat_message', { message: msg });
  input.value = '';
}
