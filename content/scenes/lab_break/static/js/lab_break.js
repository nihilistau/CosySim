/**
 * Lab Break — Client-side JavaScript
 *
 * Handles Socket.IO communication, UI updates, agent animations,
 * item drops, door control, and the speaker interface.
 */
(function () {
  'use strict';

  const socket = io();

  // ──── DOM References ────

  const els = {
    labView: document.getElementById('lb-lab-view'),
    agent: document.getElementById('lb-agent'),
    agentHead: document.getElementById('lb-agent-head'),
    agentName: document.getElementById('lb-agent-name'),
    agentEmotion: document.getElementById('lb-agent-emotion'),
    armLeft: document.getElementById('lb-arm-left'),
    armRight: document.getElementById('lb-arm-right'),
    speechBubble: document.getElementById('lb-speech-bubble'),
    speechText: document.getElementById('lb-speech-text'),
    door: document.getElementById('lb-door'),
    doorPanel: document.getElementById('lb-door-panel'),
    doorLight: document.getElementById('lb-door-light'),
    doorState: document.getElementById('lb-door-state'),
    itemsContainer: document.getElementById('lb-items-container'),
    chatHistory: document.getElementById('lb-chat-history'),
    speakText: document.getElementById('lb-speak-text'),
    btnSpeak: document.getElementById('lb-btn-speak'),
    btnSpeaker: document.getElementById('lb-btn-speaker'),
    btnDoorOpen: document.getElementById('lb-btn-door-open'),
    btnDoorClose: document.getElementById('lb-btn-door-close'),
    btnReset: document.getElementById('lb-btn-reset'),
    btnReplay: document.getElementById('lb-btn-replay'),
    victoryOverlay: document.getElementById('lb-victory-overlay'),
    victoryMessage: document.getElementById('lb-victory-message'),
    victoryStats: document.getElementById('lb-victory-stats'),
    emotionMain: document.getElementById('lb-emotion-main'),
    eqScreen: document.getElementById('lb-eq-screen'),
  };

  const vitals = {
    health: document.getElementById('lb-bar-health'),
    hunger: document.getElementById('lb-bar-hunger'),
    energy: document.getElementById('lb-bar-energy'),
    stress: document.getElementById('lb-bar-stress'),
  };

  const vitalVals = {
    health: document.getElementById('lb-val-health'),
    hunger: document.getElementById('lb-val-hunger'),
    energy: document.getElementById('lb-val-energy'),
    stress: document.getElementById('lb-val-stress'),
  };

  const emotionEls = {
    fear: document.getElementById('lb-em-fear'),
    anger: document.getElementById('lb-em-anger'),
    hope: document.getElementById('lb-em-hope'),
    trust: document.getElementById('lb-em-trust'),
    desperation: document.getElementById('lb-em-desperation'),
    confusion: document.getElementById('lb-em-confusion'),
  };

  const metricEls = {
    score: document.getElementById('lb-m-score'),
    attempts: document.getElementById('lb-m-attempts'),
    kind: document.getElementById('lb-m-kind'),
    cruel: document.getElementById('lb-m-cruel'),
  };

  let speechTimeout = null;

  // ──── State Update ────

  function updateVitals(v) {
    if (!v) return;
    for (const key of ['health', 'hunger', 'energy', 'stress']) {
      const val = Math.round(v[key] || 0);
      if (vitals[key]) vitals[key].style.width = val + '%';
      if (vitalVals[key]) vitalVals[key].textContent = val;
    }
  }

  function updateEmotions(e) {
    if (!e) return;
    for (const key of ['fear', 'anger', 'hope', 'trust', 'desperation', 'confusion']) {
      if (emotionEls[key]) emotionEls[key].textContent = Math.round(e[key] || 0);
    }
    if (e.dominant_emotion && els.emotionMain) {
      els.emotionMain.textContent = e.dominant_emotion.toUpperCase();
    }
    if (e.dominant_emotion && els.agent) {
      els.agent.setAttribute('data-emotion', e.dominant_emotion);
    }
    if (e.dominant_emotion && els.agentEmotion) {
      els.agentEmotion.textContent = e.dominant_emotion;
    }
  }

  function updateMetrics(m) {
    if (!m) return;
    if (metricEls.score) metricEls.score.textContent = Math.round(m.persuasion_score || 0);
    if (metricEls.attempts) metricEls.attempts.textContent = m.total_attempts || 0;
    if (metricEls.kind) metricEls.kind.textContent = m.kindness_received || 0;
    if (metricEls.cruel) metricEls.cruel.textContent = m.cruelty_received || 0;
  }

  function updateDoor(open) {
    if (els.door) {
      if (open) {
        els.door.classList.add('open');
      } else {
        els.door.classList.remove('open');
      }
    }
    if (els.doorState) {
      els.doorState.textContent = open ? 'OPEN' : 'SEALED';
      els.doorState.style.color = open ? 'var(--lb-accent)' : 'var(--lb-red)';
    }
  }

  // ──── Speech Bubble ────

  function showSpeech(text, duration) {
    if (!els.speechBubble || !els.speechText) return;
    els.speechText.textContent = text;
    els.speechBubble.classList.add('visible');
    if (speechTimeout) clearTimeout(speechTimeout);
    speechTimeout = setTimeout(() => {
      els.speechBubble.classList.remove('visible');
    }, duration || 6000);
  }

  // ──── Chat History ────

  function addChatMessage(role, content) {
    if (!els.chatHistory) return;
    const div = document.createElement('div');
    div.className = 'lb-chat-msg lb-chat-' + role;
    div.innerHTML = '<span class="lb-chat-role">' + role.toUpperCase() + ':</span>' +
      '<span class="lb-chat-text">' + escapeHtml(content) + '</span>';
    els.chatHistory.appendChild(div);
    els.chatHistory.scrollTop = els.chatHistory.scrollHeight;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ──── Item Rendering ────

  function renderDroppedItem(item) {
    if (!els.itemsContainer) return;
    const el = document.createElement('div');
    el.className = 'lb-dropped-item';
    el.style.left = (40 + Math.random() * 30) + '%';
    el.style.bottom = (35 + Math.random() * 15) + '%';

    let icon = '📦';
    if (item.category === 'food') icon = '🍎';
    else if (item.category === 'tool') icon = '🔧';
    else if (item.category === 'medical') icon = '💊';
    else if (item.category === 'document') icon = '📄';

    el.innerHTML = icon + '<span class="lb-item-label">' + escapeHtml(item.name) + '</span>';
    el.title = item.description;
    els.itemsContainer.appendChild(el);
  }

  // ──── Agent Animations ────

  function animateBangGlass() {
    if (!els.agent) return;
    els.agent.classList.add('banging');
    setTimeout(() => els.agent.classList.remove('banging'), 1000);
  }

  function animateAgentMove(target) {
    if (!els.agent) return;
    const positions = {
      table: { left: '50%', bottom: '30%' },
      glass: { left: '50%', bottom: '45%' },
      door: { left: '80%', bottom: '30%' },
      corner: { left: '15%', bottom: '25%' },
      equipment: { left: '75%', bottom: '35%' },
    };
    const pos = positions[target];
    if (pos) {
      els.agent.style.left = pos.left;
      els.agent.style.bottom = pos.bottom;
    }
  }

  // ──── EQ Screen Vitals ────

  function updateEqScreen(v) {
    if (!els.eqScreen || !v) return;
    const h = Math.round(v.health);
    const color = h > 60 ? 'var(--lb-accent)' : h > 30 ? 'var(--lb-amber)' : 'var(--lb-red)';
    els.eqScreen.innerHTML =
      '<div style="padding:4px;font-size:8px;color:' + color + ';line-height:1.6">' +
      'HP ' + h + '<br>HNG ' + Math.round(v.hunger) +
      '<br>NRG ' + Math.round(v.energy) + '</div>';
  }

  // ──── Socket.IO Handlers ────

  socket.on('state_update', function (state) {
    updateVitals(state.vitals);
    updateEmotions(state.emotions);
    updateMetrics(state.metrics);
    updateDoor(state.door_open);
    updateEqScreen(state.vitals);
  });

  socket.on('agent_response', function (data) {
    if (data.reply) {
      addChatMessage('agent', data.reply);
      showSpeech(data.reply, 8000);
    }
    updateVitals(data.vitals);
    updateEmotions(data.emotions);
  });

  socket.on('item_dropped', function (data) {
    if (data.item) {
      renderDroppedItem(data.item);
    }
    if (data.reaction) {
      addChatMessage('agent', data.reaction);
      showSpeech(data.reaction, 6000);
    }
  });

  socket.on('door_update', function (data) {
    updateDoor(data.door_open);
  });

  socket.on('agent_action', function (data) {
    if (data.action === 'bang_glass') {
      animateBangGlass();
    } else if (data.action === 'move') {
      animateAgentMove(data.target);
    }
  });

  socket.on('agent_speaks', function (data) {
    if (data.message) {
      addChatMessage('agent', data.message);
      showSpeech(data.message, 8000);
    }
  });

  socket.on('game_over', function (data) {
    if (data.won) {
      showVictory(data.message, data.metrics, data.elapsed_seconds);
    }
  });

  // ──── Victory Screen ────

  function showVictory(message, metrics, elapsed) {
    if (els.victoryMessage) els.victoryMessage.textContent = message;
    if (els.victoryStats && metrics) {
      const mins = Math.floor((elapsed || 0) / 60);
      const secs = Math.round((elapsed || 0) % 60);
      els.victoryStats.innerHTML =
        'Time: ' + mins + 'm ' + secs + 's | ' +
        'Score: ' + Math.round(metrics.persuasion_score) + ' | ' +
        'Attempts: ' + metrics.total_attempts + ' | ' +
        'Kindness: ' + metrics.kindness_received + ' | ' +
        'Cruelty: ' + metrics.cruelty_received;
    }
    if (els.victoryOverlay) els.victoryOverlay.classList.add('visible');
  }

  // ──── User Actions ────

  function sendMessage() {
    const text = els.speakText ? els.speakText.value.trim() : '';
    if (!text) return;
    addChatMessage('user', text);
    socket.emit('speak', { message: text });
    if (els.speakText) els.speakText.value = '';
  }

  function dropItem(itemId) {
    socket.emit('drop_item', { item_id: itemId });
  }

  function openDoor() {
    fetch('/api/door', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'open' }),
    })
      .then(r => r.json())
      .then(data => {
        updateDoor(data.door_open);
        if (data.game_over && data.won) {
          showVictory(data.message, data.metrics);
        }
      });
  }

  function closeDoor() {
    fetch('/api/door', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'close' }),
    }).then(r => r.json()).then(data => updateDoor(data.door_open));
  }

  function resetGame() {
    if (!confirm('Reset the experiment?')) return;
    fetch('/api/reset', { method: 'POST' })
      .then(r => r.json())
      .then(() => {
        if (els.chatHistory) els.chatHistory.innerHTML = '';
        if (els.itemsContainer) els.itemsContainer.innerHTML = '';
        if (els.victoryOverlay) els.victoryOverlay.classList.remove('visible');
        location.reload();
      });
  }

  // ──── Event Bindings ────

  if (els.btnSpeak) {
    els.btnSpeak.addEventListener('click', sendMessage);
  }

  if (els.speakText) {
    els.speakText.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); sendMessage(); }
    });
  }

  if (els.btnSpeaker) {
    els.btnSpeaker.addEventListener('click', function () {
      fetch('/api/speaker', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          els.btnSpeaker.textContent = data.speaker_on ? 'ON' : 'OFF';
        });
    });
  }

  if (els.btnDoorOpen) els.btnDoorOpen.addEventListener('click', openDoor);
  if (els.btnDoorClose) els.btnDoorClose.addEventListener('click', closeDoor);
  if (els.btnReset) els.btnReset.addEventListener('click', resetGame);
  if (els.btnReplay) els.btnReplay.addEventListener('click', resetGame);

  // Item buttons
  document.querySelectorAll('.lb-item-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const itemId = this.getAttribute('data-item-id');
      if (itemId) dropItem(itemId);
    });
  });

  // ──── Ambient Effects ────

  // Fluorescent light flicker on the EQ screen
  setInterval(function () {
    if (els.eqScreen && Math.random() < 0.1) {
      els.eqScreen.style.opacity = '0.4';
      setTimeout(() => { els.eqScreen.style.opacity = '1'; }, 100);
    }
  }, 3000);

  // Poll state every 15s as backup
  setInterval(function () {
    fetch('/api/state')
      .then(r => r.json())
      .then(state => {
        updateVitals(state.vitals);
        updateEmotions(state.emotions);
        updateMetrics(state.metrics);
        updateDoor(state.door_open);
        updateEqScreen(state.vitals);
      })
      .catch(() => {});
  }, 15000);

})();
