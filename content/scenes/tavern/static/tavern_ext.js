/**
 * THE RUSTY ANCHOR — Extension Module
 * =====================================
 *
 * Game logic extensions for the Kit-generated TavernScene class.
 * Adds: drink ordering, dice rolling (d4-d100), quest board,
 * rumor investigation, NPC chat wiring, atmosphere meter, stats.
 *
 * Version: v1.50.0 [2026-03-22]
 * Change Log:
 *   v1.50.0 [2026-03-22] — Initial extension module, refactored from tavern.js.
 *                            TavernScene.prototype methods, _initExtensions hook.
 *                            Full implementations: drinks, dice, quests, rumors,
 *                            atmosphere, chat, stats (warmth/courage/clarity/charm).
 *
 * CONNECTS: TavernScene (tavern_kit.js), Socket.IO, REST APIs
 * CALLED BY: TavernScene.init() -> _initExtensions()
 */

'use strict';

// ── Utilities ────────────────────────────────────────────────────────

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

// ── Extension Entry Point ────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Hooked by Kit-generated init() via _initExtensions
// CONNECTS: All tavern subsystems
// CALLED BY: TavernScene.init()

TavernScene.prototype._initExtensions = function() {
  this._pendingQuestId = null;
  this._diceRolling = false;

  this._initDrinkOrdering();
  this._initDiceRolling();
  this._initQuestBoard();
  this._initRumorInvestigation();
  this._initNpcChat();
  this._initAtmosphere();
  this._initTavernSocket();

  // Initial data loads
  this._loadQuestBoard();
  this._loadRumors();
};

// ═════════════════════════════════════════════════════════════════════
// DRINK ORDERING
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Drink buttons emit order_drink action with name + cost
// CONNECTS: Socket.IO order_drink, drink_result, stat bars
// CALLED BY: _initExtensions
// EMITS: order_drink socket event, chat lines, toast

TavernScene.prototype._initDrinkOrdering = function() {
  // Drink menu — map button IDs to drink data
  const drinkMenu = {
    'drink-ale':     { name: 'Ale',     cost: 3  },
    'drink-wine':    { name: 'Wine',    cost: 8  },
    'drink-mead':    { name: 'Mead',    cost: 5  },
    'drink-spirits': { name: 'Spirits', cost: 12 },
    'drink-tea':     { name: 'Tea',     cost: 2  },
    'drink-mystery': { name: 'Mystery', cost: 15 }
  };

  // Wire up each drink button
  for (const [btnId, drink] of Object.entries(drinkMenu)) {
    const btn = document.getElementById(btnId);
    if (btn) {
      btn.addEventListener('click', () => this._orderDrink(drink.name, drink.cost));
    }
  }
};

// v1.50.0 [2026-03-22] — Order a drink via Socket.IO
// CONNECTS: Socket.IO, gold display
// EMITS: order_drink event
TavernScene.prototype._orderDrink = function(name, cost) {
  // Check gold (client-side validation — server validates too)
  const gold = this.state?.gold ?? 50;
  if (gold < cost) {
    this._showToast(`Not enough gold for ${name} (need ${cost}g, have ${gold}g)`, 'warning');
    return;
  }

  this._addChatLine(`Ordering ${name} (${cost}g)...`, 'action');
  if (this.socket) {
    this.socket.emit('order_drink', { drink: name.toLowerCase(), cost });
  }
};

// ═════════════════════════════════════════════════════════════════════
// DICE ROLLING
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Dice visualization with d4-d100, spin animation,
// critical/fumble detection, chat output
// CONNECTS: Socket.IO roll_dice / dice_result, dice DOM elements
// CALLED BY: _initExtensions
// EMITS: roll_dice socket event

TavernScene.prototype._initDiceRolling = function() {
  const rollBtn = document.getElementById('btn-roll');
  if (rollBtn) {
    rollBtn.addEventListener('click', () => this._rollDice());
  }

  // Build dice selector if not already present
  this._buildDiceSelector();
};

// v1.50.0 [2026-03-22] — Build dice type selector + reason input
// CONNECTS: #dice-controls DOM area
TavernScene.prototype._buildDiceSelector = function() {
  const panel = document.getElementById('dice-controls');
  if (!panel) return;

  // Only build if the select doesn't already exist
  if (document.getElementById('dice-sides')) return;

  const selectHtml = `
    <select class="ck-dice-select" id="dice-sides">
      <option value="4">d4</option>
      <option value="6">d6</option>
      <option value="8">d8</option>
      <option value="10">d10</option>
      <option value="12">d12</option>
      <option value="20" selected>d20</option>
      <option value="100">d100</option>
    </select>
    <input class="ck-dice-reason" id="dice-reason" type="text"
           value="skill check" placeholder="Reason..." />
  `;
  panel.insertAdjacentHTML('afterbegin', selectHtml);
};

// v1.50.0 [2026-03-22] — Roll dice with selected type and reason
// CONNECTS: Socket.IO roll_dice event
// EMITS: roll_dice { sides, reason }
TavernScene.prototype._rollDice = function() {
  if (this._diceRolling) return;

  const sides = parseInt(document.getElementById('dice-sides')?.value || '20', 10);
  const reason = document.getElementById('dice-reason')?.value.trim() || 'skill check';

  this._diceRolling = true;
  this._addChatLine(`Rolling d${sides} -- ${reason}...`, 'action');

  // Start visual spin
  const diceVisual = document.getElementById('dice-visual');
  if (diceVisual) {
    diceVisual.classList.add('rolling');
    diceVisual.textContent = '?';
  }

  if (this.socket) {
    this.socket.emit('roll_dice', { sides, reason });
  }

  // Safety timeout — if server doesn't respond, stop rolling state
  setTimeout(() => {
    this._diceRolling = false;
    if (diceVisual) diceVisual.classList.remove('rolling');
  }, 5000);
};

// v1.50.0 [2026-03-22] — Animate and display dice result
// CONNECTS: dice DOM elements, chat feed
// CALLED BY: dice_result socket handler
TavernScene.prototype._showDiceResult = function(data) {
  this._diceRolling = false;
  const { total, sides, rolls, reason, critical, fumble } = data;

  const diceVisual = document.getElementById('dice-visual');
  if (diceVisual) {
    // Spin then reveal
    setTimeout(() => {
      diceVisual.classList.remove('rolling');
      diceVisual.textContent = total;
      diceVisual.className = 'dice-visual';
      if (critical) diceVisual.classList.add('dice-critical');
      if (fumble) diceVisual.classList.add('dice-fumble');
    }, 600);
  }

  // Display result text
  const resultEl = document.getElementById('dice-result-text');
  if (resultEl) {
    resultEl.classList.remove('hidden');
    const rollsStr = rolls ? `[${rolls.join(', ')}] ` : '';
    const suffix = critical ? ' -- CRITICAL!' : fumble ? ' -- FUMBLE!' : '';
    resultEl.textContent = `${rollsStr}d${sides}: ${total}${suffix}`;
    resultEl.className = 'dice-result-text';
    if (critical) resultEl.classList.add('dice-text-critical');
    if (fumble) resultEl.classList.add('dice-text-fumble');

    // Pop-in animation retrigger
    resultEl.style.animation = 'none';
    void resultEl.offsetWidth;
    resultEl.style.animation = '';
  }

  // Chat output
  const suffix = critical ? ' CRITICAL!' : fumble ? ' FUMBLE!' : '';
  this._addChatLine(`d${sides} (${reason}): ${total}${suffix}`, 'result');
};

// ═════════════════════════════════════════════════════════════════════
// QUEST BOARD
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Load quests from /api/quests, render cards,
// accept/progress/complete via Socket.IO
// CONNECTS: /api/quests REST, Socket.IO quest events, #quest-board DOM
// CALLED BY: _initExtensions
// EMITS: accept_quest, get_quest_board socket events

TavernScene.prototype._initQuestBoard = function() {
  // Refresh button — if present
  const refreshBtn = document.getElementById('btn-refresh-quests');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => this._loadQuestBoard());
  }

  // Quest modal — close on backdrop click
  document.addEventListener('click', (e) => {
    const modal = document.getElementById('quest-modal');
    if (modal && e.target === modal) this._closeQuestModal();
  });

  // Accept quest button inside modal
  const acceptBtn = document.getElementById('btn-accept-quest');
  if (acceptBtn) {
    acceptBtn.addEventListener('click', () => {
      if (this._pendingQuestId) {
        this._acceptQuest(this._pendingQuestId);
        this._closeQuestModal();
      }
    });
  }

  // Modal close button
  const closeBtn = document.getElementById('modal-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => this._closeQuestModal());
  }
};

// v1.50.0 [2026-03-22] — Fetch quest list from REST API
// CONNECTS: /api/quests endpoint
TavernScene.prototype._loadQuestBoard = function() {
  // Try REST first
  fetch('/api/quests')
    .then(r => r.ok ? r.json() : { quests: [] })
    .then(data => this._renderQuestBoard(data.quests || []))
    .catch(() => {
      // Fallback: request via Socket.IO
      if (this.socket) this.socket.emit('get_quest_board');
    });
};

// v1.50.0 [2026-03-22] — Render quest cards into the mission board
// CONNECTS: #quest-board DOM element
// CALLED BY: _loadQuestBoard, quest_board socket event
TavernScene.prototype._renderQuestBoard = function(quests) {
  const board = document.getElementById('quest-board');
  if (!board) return;

  if (!quests || !quests.length) {
    board.innerHTML = '<div class="ck-mission-empty">No quests posted. Check back at nightfall.</div>';
    return;
  }

  board.innerHTML = quests.map(q => {
    const tags = (q.tags || []).slice(0, 2).join(', ') || q.type || 'QUEST';
    const reward = q.reward ? `${q.reward}g` : q.reward_gold ? `${q.reward_gold}g` : '--';
    return `
      <div class="ck-mission-card" data-quest-id="${q.id}">
        <span class="ck-mission-tag">${tags.toUpperCase()}</span>
        <div class="ck-mission-name">${q.title || q.id}</div>
        <div class="ck-mission-reward">Reward: ${reward}</div>
      </div>`;
  }).join('');

  // Click handler — open quest detail modal
  board.querySelectorAll('.ck-mission-card').forEach(card => {
    card.addEventListener('click', () => {
      const questId = card.dataset.questId;
      const quest = quests.find(q => q.id === questId);
      if (quest) this._openQuestModal(quest);
    });
  });
};

// v1.50.0 [2026-03-22] — Open quest detail modal
// CONNECTS: #quest-modal DOM
TavernScene.prototype._openQuestModal = function(quest) {
  this._pendingQuestId = quest.id;

  const tags = (quest.tags || []).join(', ') || quest.type || 'QUEST';
  const reward = quest.reward ? `${quest.reward}g` : quest.reward_gold ? `${quest.reward_gold}g` : '--';

  this._setText('modal-type-tag', tags.toUpperCase());
  this._setText('modal-title', quest.title || quest.id);
  this._setText('modal-description', quest.content || quest.description || 'A mysterious quest awaits...');
  this._setText('modal-reward', `Reward: ${reward}`);

  const modal = document.getElementById('quest-modal');
  if (modal) modal.classList.remove('hidden');
};

// v1.50.0 [2026-03-22] — Close quest modal
TavernScene.prototype._closeQuestModal = function() {
  this._pendingQuestId = null;
  const modal = document.getElementById('quest-modal');
  if (modal) modal.classList.add('hidden');
};

// v1.50.0 [2026-03-22] — Accept a quest via Socket.IO
// CONNECTS: Socket.IO accept_quest event
// EMITS: accept_quest { quest_id }
TavernScene.prototype._acceptQuest = function(questId) {
  this._addChatLine(`Accepting quest: ${questId}...`, 'action');
  if (this.socket) {
    this.socket.emit('accept_quest', { quest_id: questId });
  }
};

// v1.50.0 [2026-03-22] — Update active quest display in progress tracker
// CONNECTS: #quest-progress, active quest panel
// CALLED BY: quest_started socket handler
TavernScene.prototype._setActiveQuest = function(data) {
  // Update progress tracker step
  const tracker = document.getElementById('quest-progress');
  if (tracker) {
    const steps = tracker.querySelectorAll('.ck-step');
    // Set first step (Accept) as active
    steps.forEach((step, i) => {
      step.classList.toggle('active', i <= 0);
      step.classList.toggle('current', i === 0);
    });
  }

  this._addChatLine(`Quest started: ${data.title || data.quest_id}`, 'action');
  this._showToast(`Quest accepted: ${data.title || data.quest_id}`, 'success');
};

// ═════════════════════════════════════════════════════════════════════
// RUMOR INVESTIGATION
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Load rumors from API, investigate clues,
// display rumor cards in event feed
// CONNECTS: /api/rumors REST, Socket.IO investigate_rumor, #rumor-stack DOM
// CALLED BY: _initExtensions
// EMITS: investigate_rumor socket event

TavernScene.prototype._initRumorInvestigation = function() {
  const investigateBtn = document.getElementById('btn-investigate');
  if (investigateBtn) {
    investigateBtn.addEventListener('click', () => this._investigateTopRumor());
  }
};

// v1.50.0 [2026-03-22] — Fetch rumors from REST API
// CONNECTS: /api/rumors endpoint, rumor feed DOM
TavernScene.prototype._loadRumors = function() {
  fetch('/api/rumors')
    .then(r => r.ok ? r.json() : { rumors: [] })
    .then(data => this._renderRumors(data.rumors || []))
    .catch(() => {
      // Populate with default rumors if API unavailable
      this._renderDefaultRumors();
    });
};

// v1.50.0 [2026-03-22] — Render rumor cards into event feed
// CONNECTS: #rumor-stack DOM element
TavernScene.prototype._renderRumors = function(rumors) {
  const feed = document.getElementById('rumor-stack');
  if (!feed) return;

  if (!rumors || !rumors.length) {
    this._renderDefaultRumors();
    return;
  }

  this._rumorsData = rumors;
  feed.innerHTML = rumors.map((r, i) => `
    <div class="ck-event-item" data-rumor-id="${r.id || 'rumor_' + i}" data-index="${i}">
      <em>${r.text || r.content || 'A whispered rumor...'}</em>
      <span class="ck-event-source">-- ${r.source || 'Unknown'}</span>
    </div>
  `).join('');
};

// v1.50.0 [2026-03-22] — Default rumors when API is unavailable
TavernScene.prototype._renderDefaultRumors = function() {
  const defaults = [
    { id: 'rumor_lighthouse', text: 'The old lighthouse blinks three times at midnight. No keeper lives there.', source: 'A fisherman' },
    { id: 'rumor_shadows', text: "Captain Marlowe's crew doesn't cast shadows. Been that way since the fog.", source: 'The barkeep' },
    { id: 'rumor_cargo', text: "Something's been eating the cargo. Not rats. Too big. Too quiet.", source: 'Dock worker' }
  ];
  this._rumorsData = defaults;

  const feed = document.getElementById('rumor-stack');
  if (!feed) return;
  feed.innerHTML = defaults.map((r, i) => `
    <div class="ck-event-item" data-rumor-id="${r.id}" data-index="${i}">
      <em>${r.text}</em>
      <span class="ck-event-source">-- ${r.source}</span>
    </div>
  `).join('');
};

// v1.50.0 [2026-03-22] — Investigate the topmost rumor
// CONNECTS: Socket.IO investigate_rumor event
// EMITS: investigate_rumor { rumor_id }
TavernScene.prototype._investigateTopRumor = function() {
  const firstRumor = document.querySelector('#rumor-stack .ck-event-item');
  if (!firstRumor) {
    this._showToast('No rumors to investigate.', 'warning');
    return;
  }

  const rumorId = firstRumor.dataset.rumorId || `rumor_${Date.now()}`;
  this._addChatLine(`Investigating rumor: ${rumorId}...`, 'action');

  if (this.socket) {
    this.socket.emit('investigate_rumor', { rumor_id: rumorId });
  }

  // Visual feedback — highlight the card
  firstRumor.style.borderColor = 'var(--scene-accent-light)';
  firstRumor.style.boxShadow = '0 0 12px rgba(146, 64, 14, 0.4)';
  setTimeout(() => {
    firstRumor.style.borderColor = '';
    firstRumor.style.boxShadow = '';
  }, 1500);
};

// ═════════════════════════════════════════════════════════════════════
// NPC CHAT WIRING
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Socket.IO chat message handlers, NPC responses,
// streamed replies
// CONNECTS: Socket.IO chat events, chat feed DOM
// CALLED BY: _initExtensions

TavernScene.prototype._initNpcChat = function() {
  if (!this.socket) return;

  // NPC chat message (from server-side agent processing)
  this.socket.on('chat_message', (data) => {
    const sender = data.sender || data.character || 'NPC';
    const text = data.text || data.message || '';
    if (text) {
      this._addChatLine(`${sender}: ${text}`, 'result');
    }
  });

  // Streamed response chunks
  this.socket.on('stream_chunk', (data) => {
    const text = data.text || data.chunk || '';
    if (text) {
      this._appendToLastLine(text);
    }
  });

  // Stream end — finalize the line
  this.socket.on('stream_end', () => {
    // No-op — the line is already complete from chunks
  });

  // Character action tags (from stream processor)
  this.socket.on('action_tag', (data) => {
    if (data.action) {
      this._addChatLine(`* ${data.action} *`, 'system');
    }
  });
};

// v1.50.0 [2026-03-22] — Append text to the last chat line (for streaming)
// CONNECTS: #chat-feed DOM
TavernScene.prototype._appendToLastLine = function(text) {
  const feed = document.getElementById('chat-feed');
  if (!feed) return;

  let lastLine = feed.lastElementChild;
  if (!lastLine || !lastLine.classList.contains('streaming')) {
    // Create a new streaming line
    lastLine = document.createElement('div');
    lastLine.className = 'chat-line result streaming';
    feed.appendChild(lastLine);
  }
  lastLine.textContent += text;
  feed.scrollTop = feed.scrollHeight;
};

// ═════════════════════════════════════════════════════════════════════
// ATMOSPHERE METER
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — Track and display tavern atmosphere level
// CONNECTS: atmosphere_update socket event, #atm-banner DOM
// CALLED BY: _initExtensions

TavernScene.prototype._initAtmosphere = function() {
  if (!this.socket) return;

  this.socket.on('atmosphere_update', (data) => {
    if (data.atmosphere) {
      this._updateAtmosphere(data.atmosphere, data.heat);
    }
  });
};

// v1.50.0 [2026-03-22] — Update atmosphere display elements
// CONNECTS: #atm-banner, atmosphere-related DOM
TavernScene.prototype._updateAtmosphere = function(atmosphere, heat) {
  // Update alert banner text
  const banner = document.getElementById('atm-banner');
  if (banner) {
    const textMap = {
      quiet: 'The tavern is quiet. Only a few patrons murmur.',
      lively: 'The tavern buzzes with laughter and clinking mugs.',
      rowdy: 'Voices rise, tables shake -- the crowd is rowdy!',
      brawl: 'Chairs fly! A brawl has broken out!'
    };
    const textEl = banner.querySelector('.ck-alert-text');
    if (textEl) textEl.textContent = textMap[atmosphere] || atmosphere;

    // Severity mapping
    const severityMap = { quiet: 'info', lively: 'info', rowdy: 'warning', brawl: 'danger' };
    banner.dataset.severity = severityMap[atmosphere] || 'info';
  }

  // Update state for stat sync
  if (this.state) {
    this.state.atmosphere = atmosphere;
    if (heat !== undefined) this.state.heat = heat;
  }
};

// ═════════════════════════════════════════════════════════════════════
// TAVERN SOCKET.IO — game-specific event handlers
// ═════════════════════════════════════════════════════════════════════
// v1.50.0 [2026-03-22] — All tavern-specific Socket.IO handlers
// CONNECTS: Socket.IO server events
// CALLED BY: _initExtensions

TavernScene.prototype._initTavernSocket = function() {
  if (!this.socket) return;

  // ── Quest board response ──────────────────────────────────────
  this.socket.on('quest_board', ({ quests }) => {
    this._renderQuestBoard(quests || []);
  });

  // ── Quest started (accepted) ──────────────────────────────────
  this.socket.on('quest_started', (data) => {
    this._setActiveQuest(data);
  });

  // ── Quest progress update ─────────────────────────────────────
  this.socket.on('quest_progress', (data) => {
    const tracker = document.getElementById('quest-progress');
    if (tracker && data.step !== undefined) {
      const steps = tracker.querySelectorAll('.ck-step');
      steps.forEach((step, i) => {
        step.classList.toggle('active', i <= data.step);
        step.classList.toggle('current', i === data.step);
      });
    }
    if (data.text) this._addChatLine(data.text, 'action');
  });

  // ── Quest completed ───────────────────────────────────────────
  this.socket.on('quest_complete', (data) => {
    const reward = data.reward_gold || data.reward || 0;
    this._addChatLine(`Quest complete! Reward: ${reward}g`, 'result');
    this._showToast(`Quest complete! +${reward}g`, 'success');

    // Reset progress tracker
    const tracker = document.getElementById('quest-progress');
    if (tracker) {
      const steps = tracker.querySelectorAll('.ck-step');
      steps.forEach(step => {
        step.classList.add('active');
        step.classList.remove('current');
      });
      // Mark last step as current
      if (steps.length) steps[steps.length - 1].classList.add('current');
    }
  });

  // ── Dice result ───────────────────────────────────────────────
  this.socket.on('dice_result', (data) => {
    this._showDiceResult(data);
  });

  // ── Drink result ──────────────────────────────────────────────
  this.socket.on('drink_result', ({ result, effects }) => {
    const firstLine = (result || '').split('\n')[0];
    if (firstLine) this._addChatLine(firstLine, 'result');
    this._showToast(result || 'Drink served!');

    // Apply stat effects if provided
    if (effects && typeof effects === 'object') {
      for (const [stat, delta] of Object.entries(effects)) {
        const barEl = document.getElementById(`stat-${stat}`);
        if (!barEl) continue;
        const fill = barEl.querySelector('.ck-stat-fill, .stat-fill');
        const valEl = barEl.querySelector('.ck-stat-val, .stat-val');
        const current = this.state?.[stat] ?? 50;
        const newVal = Math.min(100, Math.max(0, current + delta));
        if (this.state) this.state[stat] = newVal;
        if (fill) fill.style.width = `${newVal}%`;
        if (valEl) valEl.textContent = Math.round(newVal);
      }
    }

    // Re-fetch full state to sync
    this._loadInitialState();
  });

  // ── Rumor investigated ────────────────────────────────────────
  this.socket.on('rumor_investigated', ({ rumor_id, clues, text }) => {
    this._addChatLine(`Rumor "${rumor_id}" investigated. Clues: ${clues || 0}`, 'action');
    if (text) this._addChatLine(text, 'result');
    this._showToast(`Investigation: ${clues || 0} clue(s) found`);
  });

  // ── Stat update (individual stat changes) ─────────────────────
  this.socket.on('stat_update', (data) => {
    if (!data) return;
    for (const [stat, val] of Object.entries(data)) {
      if (typeof val !== 'number') continue;
      const barEl = document.getElementById(`stat-${stat}`);
      if (!barEl) continue;
      const fill = barEl.querySelector('.ck-stat-fill, .stat-fill');
      const valEl = barEl.querySelector('.ck-stat-val, .stat-val');
      if (fill) fill.style.width = `${Math.min(100, Math.max(0, val))}%`;
      if (valEl) valEl.textContent = Math.round(val);
      if (this.state) this.state[stat] = val;
    }
  });

  // ── HUD update (gold, etc.) ───────────────────────────────────
  this.socket.on('hud_update', (data) => {
    if (data.gold !== undefined) {
      this._setText('gold-val', data.gold);
      if (this.state) this.state.gold = data.gold;
    }
  });
};
