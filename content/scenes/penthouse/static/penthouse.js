/**
 * THE PENTHOUSE — PenthouseScene JS  v0.68 "Dark Renaissance"
 * ==========================================================
 * Manages all client-side logic for the Penthouse UI:
 *   Socket.IO connection · Chat rendering · Emotion bars ·
 *   Scenario selection · Scene Director · Economy · Memories ·
 *   ParticleSystem3D · BenchHUD · VoiceManager integration
 */

'use strict';

/* ══════════════════════════════════════════════════════════════════════
   CONSTANTS
   ══════════════════════════════════════════════════════════════════════ */

const PENTHOUSE_SOCKET_URL = `${location.protocol}//${location.hostname}:${location.port}`;

const MOOD_DESCRIPTORS = {
  max_arousal:     'Burning with desire…',
  max_pleasure:    'Lost in pleasure…',
  max_happiness:   'Radiantly happy…',
  max_horniness:   'Overwhelmed with need…',
  max_drunkenness: 'Blissfully intoxicated…',
  max_dominance:   'In full command…',
  max_fear:        'Trembling with fear…',
  max_anger:       'Seething with anger…',
  max_openness:    'Completely open to anything…',
  high_arousal:    'Deeply aroused…',
  high_pleasure:   'Filled with pleasure…',
  high_happiness:  'Glowing with joy…',
  high_horniness:  'Burning with desire…',
  moderate:        'In the mood…',
  low:             'Calm and composed…',
  default:         'Waiting…',
};

const BEAT_CHIP_CLASSES = {
  opening:    'cs-chip--purple',
  escalation: 'cs-chip--intensity-3',
  cool_down:  'cs-chip--green',
  revelation: 'cs-chip--yellow',
  climax:     'cs-chip--intensity-3',
  resolution: 'cs-chip--green',
  default:    '',
};

/* ══════════════════════════════════════════════════════════════════════
   PenthouseScene CLASS
   ══════════════════════════════════════════════════════════════════════ */

class PenthouseScene {
  constructor() {
    /** @type {import('socket.io-client').Socket|null} */
    this.socket        = null;
    this._voiceEnabled = false;
    this._agentTyping  = false;
    this._activeCharId = null;
    this._activeScenarioId = null;
    this._balance      = 0;
    this._particleSystem = null;
    this._messageCount  = 0;
  }

  /* ── Lifecycle ──────────────────────────────────────────────────── */

  /** Initialise on DOMContentLoaded. */
  init() {
    this._handleGate();
    this._setupSocket();
    this._setupDOM();
    this._initParticles();
    this._initBenchHUD();

    // Request initial economy balance
    setTimeout(() => this.socket && this.socket.emit('get_economy', {}), 1500);
  }

  /* ── Content Gate ───────────────────────────────────────────────── */

  _handleGate() {
    const gate = document.getElementById('penthouse-gate');
    if (!gate) return;

    if (sessionStorage.getItem('penthouse_admitted') === '1') {
      gate.hidden = true;
      return;
    }

    const enterBtn = document.getElementById('gate-enter');
    if (enterBtn) {
      enterBtn.addEventListener('click', () => {
        sessionStorage.setItem('penthouse_admitted', '1');
        gate.hidden = true;
      });
    }
  }

  /* ── Socket.IO ──────────────────────────────────────────────────── */

  _setupSocket() {
    this.socket = io(PENTHOUSE_SOCKET_URL, {
      transports: ['websocket', 'polling'],
      reconnectionAttempts: 10,
      reconnectionDelay: 1500,
    });

    const s = this.socket;

    s.on('connect',    () => this._onConnect());
    s.on('disconnect', () => this._onDisconnect());

    // Scene state
    s.on('scene_state',    data => this._onSceneState(data));
    s.on('constants',      data => this._onConstants(data));

    // Chat
    s.on('chat_message',   data => this._onChatMessage(data));
    s.on('chat_response',  data => this._onChatResponse(data));
    s.on('agent_typing',   data => this._setTyping(data.character_name || '…', true));
    s.on('agent_done',     ()   => this._setTyping('', false));

    // Emotions
    s.on('emotion_update', data => this.updateEmotions(data));

    // Scenarios
    s.on('scenarios',      data => this._renderScenarios(data.scenarios || []));

    // Director
    s.on('director_beat',  data => this._renderDirectorBeat(data.beat || data));

    // Economy
    s.on('economy_update', data => this.updateCredits(data.balance));
    s.on('premium_unlocked', data => this._onPremiumUnlocked(data));

    // Memories
    s.on('memory_update',  data => this._onMemoryUpdate(data));

    // World tick
    s.on('world_tick',     data => this._onWorldTick(data));

    // NPC scheduler events
    s.on('npc_activity',   data => this._onNpcActivity(data));
    s.on('npc_location',   data => this._onNpcLocation(data));

    // Bench HUD live push
    s.on('bench:update',   data => {
      if (typeof BenchHUD !== 'undefined') BenchHUD.update(data);
    });

    // Errors
    s.on('error',          data => this._showSystemMessage(`⚠ ${data.message || 'Unknown error'}`));

    // Agent loop events
    s.on('agent_action',        data => this._onAgentAction(data));
    s.on('agent_tick',          data => this._onAgentTick(data));
    s.on('character_speaking',  data => this._onCharacterSpeaking(data));
  }

  _onConnect() {
    console.info('[Penthouse] Socket connected');
    this._showSystemMessage('Connected to THE PENTHOUSE.');
    this.socket.emit('request_state');
  }

  _onDisconnect() {
    this._showSystemMessage('Connection lost. Reconnecting…');
    this._setTyping('', false);
  }

  /* ── NPC scheduler handlers ────────────────────────────────────── */

  _onNpcActivity(data) {
    const name     = data.character_name || data.character_id || 'NPC';
    const activity = data.activity || 'idle';
    this._showSystemMessage(`🏙 ${name}: ${activity}`);
  }

  _onNpcLocation(data) {
    const name     = data.character_name || data.character_id || 'NPC';
    const location = data.location || 'unknown';
    console.log(`[NPC] ${name} moved to ${location}`);
  }

  /* ── Scene state handlers ───────────────────────────────────────── */

  _onSceneState(data) {
    const chars = data.characters || {};
    const locs  = data.locations || {};
    const ids   = Object.keys(chars);

    // Update director state cache
    _directorState.characters = chars;

    // ── Sync 3D character models via CharacterBridge ──
    if (window.CharacterBridge) {
      window.CharacterBridge.syncCharacters(chars, locs);
    }

    if (ids.length > 0) {
      const cid   = ids[0];
      const cdata = chars[cid] || {};
      this._activeCharId = cid;

      const nameEl = document.getElementById('char-name');
      if (nameEl) nameEl.textContent = cdata.name || cid;

      if (cdata.portrait) {
        const img = document.getElementById('char-portrait-img');
        if (img) { img.src = cdata.portrait; img.alt = cdata.name || cid; }
      }

      if (cdata.stats) this.updateEmotions(cdata.stats);
    }

    // Refresh director panel selects
    _refreshCharSelects();
  }

  _onConstants(data) {
    // Scenarios from server constants (initial load)
    if (data.scenarios && Object.keys(data.scenarios).length) {
      _directorState.scenarios = data.scenarios;
      const list = Object.entries(data.scenarios).map(([id, sc]) => ({
        id,
        label: sc.label || id,
        emoji: sc.emoji || '🎭',
        opening: sc.opening || '',
        beats: sc.beats || [],
        premium: false,
      }));
      this._renderScenarios(list);
    }

    // Cache locations, props, lighting
    if (data.locations) _directorState.locations = data.locations;
    if (data.props) _directorState.props = data.props;
    if (data.lighting) _directorState.lighting = data.lighting;
  }

  /* ── Chat ───────────────────────────────────────────────────────── */

  /**
   * Send a player message via socket.
   * @param {string} text
   */
  sendMessage(text) {
    if (!text || !text.trim()) return;
    this._renderMessage({ name: 'You', message: text, role: 'player' });
    this.socket.emit('chat_message', { message: text });
    this._setTyping(this._activeCharId || '…', true);
    this._messageCount++;

    // Milestone celebration every 10 messages
    if (this._messageCount % 10 === 0) this._celebrateMoment();
  }

  _onChatMessage(data) {
    // Echoed player messages are already rendered by sendMessage()
    if (data.name === 'You' || data.role === 'player') return;
    this._renderMessage(data);
    this._setTyping('', false);

    // Show 3D chat bubble over character
    if (window.CharacterBridge && data.character_id && data.message) {
      window.CharacterBridge.showChatBubble(data.character_id, data.message, 6);
    }

    // Voice output
    if (this._voiceEnabled && typeof window.voiceManager !== 'undefined') {
      window.voiceManager.speak(data.message || '', this._activeCharId || '');
    }

    // Tick director on each turn
    if (this.socket) {
      this.socket.emit('world_tick', { trigger: 'chat_turn' });
    }
  }

  _onChatResponse(data) {
    this._onChatMessage(data);

    // Update emotions if bundled
    if (data.stats) this.updateEmotions(data.stats);

    // Update director if bundled
    if (data.director_beat) this._renderDirectorBeat(data.director_beat);

    // BenchHUD update
    if (data.bench && typeof BenchHUD !== 'undefined') BenchHUD.update(data.bench);
  }

  /**
   * Append a message bubble to the chat log.
   * @param {{ name?: string, message?: string, role?: string, timestamp?: string }} msg
   */
  _renderMessage(msg) {
    const chat = document.getElementById('penthouse-chat');
    if (!chat) return;

    const role    = msg.role || (msg.name === 'You' ? 'player' : 'char');
    const wrapper = document.createElement('div');
    wrapper.className = `penthouse-message penthouse-message--${role}`;

    const name = document.createElement('div');
    name.className = 'penthouse-message__name';
    name.textContent = msg.name || (role === 'player' ? 'You' : 'Character');

    const bubble = document.createElement('div');
    bubble.className = 'penthouse-message__bubble';
    bubble.textContent = msg.message || '';

    const ts = document.createElement('div');
    ts.className = 'penthouse-message__ts';
    ts.textContent = msg.timestamp
      ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    wrapper.append(name, bubble, ts);
    chat.appendChild(wrapper);
    chat.scrollTop = chat.scrollHeight;
  }

  _showSystemMessage(text) {
    this._renderMessage({ name: 'System', message: text, role: 'system' });
    _addActivityItem(text, '📋');
  }

  /* ── Agent loop event handlers ───────────────────────────────────── */

  _onAgentAction(data) {
    const action = data.action || 'idle';
    const charName = data.character_name || 'Unknown';
    const charId = data.character_id || '';

    // Speech actions are handled via character_speaking event
    if (action === 'speak') return;

    // Update 3D character animation based on action
    if (window.CharacterBridge && charId) {
      if (action === 'move' && data.target) {
        // Trigger walk animation while moving
        CharacterBridge.setAnimState(charId, 'walk');
      } else if (['flirt', 'touch', 'kiss', 'cuddle', 'intimate'].includes(action)) {
        CharacterBridge.setAnimState(charId, 'interact');
        if (window.PenthouseAnim) {
          PenthouseAnim.AnimManager.setMood(charName, action === 'intimate' ? 'aroused' : 'seductive');
        }
      } else if (action === 'interact') {
        CharacterBridge.setAnimState(charId, 'interact');
      }
      // Show a 3D chat bubble for action descriptions
      if (data.description && action !== 'idle') {
        CharacterBridge.showChatBubble(charId, data.description, 5);
      }
    }

    if (action !== 'idle') {
      const desc = data.description || `${charName} ${action}s`;
      this._showSystemMessage(`🎭 ${desc}`);
    }
  }

  _onAgentTick(data) {
    const tick = data.tick || 0;
    const actions = data.actions || [];
    console.log(`[AgentLoop] Tick #${tick}: ${actions.length} actions`);

    // Process ALL character actions from this tick
    for (const act of actions) {
      const cid = act.character_id || '';
      const charName = act.character_name || '';
      const action = act.action || 'idle';

      // Update 3D character positions for move actions
      if (action === 'move' && act.success && window.CharacterBridge) {
        // After move completes, request fresh scene state to update positions
        if (this.socket) this.socket.emit('request_state');
      }

      // Show activity feed for non-idle actions (speak handled by character_speaking)
      if (action !== 'idle' && action !== 'speak' && act.description) {
        _addActivityItem(`${act.description}`, action === 'interact' ? '🔧' : '🎭');
      }
    }
  }

  _onCharacterSpeaking(data) {
    const charName = data.character_name || 'Unknown';
    const message = data.message || '';
    if (message) {
      this._onChatResponse({
        name: charName,
        character_name: charName,
        message: message,
        timestamp: data.timestamp || new Date().toISOString(),
      });
    }
  }

  /* ── Typing indicator ───────────────────────────────────────────── */

  _setTyping(charName, visible) {
    const el    = document.getElementById('penthouse-typing');
    const label = document.getElementById('typing-char-name');
    if (!el) return;
    this._agentTyping = visible;
    el.classList.toggle('visible', visible);
    if (label && charName) label.textContent = `${charName} is typing…`;
  }

  /* ── Emotion bars ───────────────────────────────────────────────── */

  /**
   * Animate all 10 emotion stat bars.
   * @param {Record<string, number>} stats
   */
  updateEmotions(stats) {
    if (!stats) return;

    const STATS = [
      'arousal', 'pleasure', 'happiness', 'horniness', 'drunkenness',
      'dominance', 'fear', 'anger', 'openness', 'tiredness',
    ];

    for (const key of STATS) {
      const raw = stats[key];
      if (raw == null) continue;
      const pct = Math.min(100, Math.max(0, parseFloat(raw)));

      const fillEl = document.getElementById(`stat-${key}`);
      const valEl  = document.getElementById(`stat-${key}-val`);
      if (!fillEl) continue;

      const prev = parseFloat(fillEl.style.width) || 0;
      fillEl.style.width = `${pct}%`;
      if (valEl) valEl.textContent = Math.round(pct);

      // Pulse on big change
      if (Math.abs(pct - prev) > 10) {
        fillEl.classList.remove('cs-stat-bar__fill--pulse');
        void fillEl.offsetWidth; // reflow
        fillEl.classList.add('cs-stat-bar__fill--pulse');
      }
    }

    this.updateMoodDescriptor(stats);
  }

  /**
   * Compute and display the dominant mood text.
   * @param {Record<string, number>} stats
   */
  updateMoodDescriptor(stats) {
    const el = document.getElementById('mood-descriptor');
    if (!el) return;

    const TOP = [
      ['arousal', 70, 'max_arousal', 'high_arousal'],
      ['pleasure', 70, 'max_pleasure', 'high_pleasure'],
      ['happiness', 70, 'max_happiness', 'high_happiness'],
      ['horniness', 65, 'max_horniness', 'high_horniness'],
      ['drunkenness', 60, 'max_drunkenness', null],
      ['dominance', 65, 'max_dominance', null],
      ['fear', 55, 'max_fear', null],
      ['anger', 55, 'max_anger', null],
      ['openness', 70, 'max_openness', null],
    ];

    let best  = null;
    let bestV = 0;

    for (const [key, threshold, maxKey, highKey] of TOP) {
      const v = parseFloat(stats[key] || 0);
      if (v > bestV) {
        bestV = v;
        if (v >= threshold) best = maxKey;
        else if (highKey && v >= threshold * 0.55) best = highKey;
      }
    }

    const text = MOOD_DESCRIPTORS[best] || (bestV > 20 ? MOOD_DESCRIPTORS.moderate : MOOD_DESCRIPTORS.default);
    if (el.textContent !== text) {
      el.style.opacity = '0';
      requestAnimationFrame(() => {
        el.textContent = text;
        el.style.transition = 'opacity 0.4s ease';
        el.style.opacity    = '1';
      });
    }
  }

  /* ── Scenarios ──────────────────────────────────────────────────── */

  /** Emit get_scenarios to server. */
  loadScenarios() {
    const intensity = parseInt(document.getElementById('scenario-intensity')?.value || '2', 10);
    if (this.socket) this.socket.emit('get_scenarios', { intensity });
  }

  /**
   * Render scenario cards from server payload.
   * @param {Array<{id: string, label: string, emoji: string, premium?: boolean}>} scenarios
   */
  _renderScenarios(scenarios) {
    const container = document.getElementById('penthouse-scenarios');
    const chip      = document.getElementById('scenario-count-chip');
    if (!container) return;

    container.innerHTML = '';
    if (!scenarios || !scenarios.length) {
      container.innerHTML = '<div class="penthouse-scenarios__empty">No scenarios available.</div>';
      return;
    }

    if (chip) chip.textContent = scenarios.length;

    for (const sc of scenarios) {
      const card = document.createElement('button');
      card.className = 'penthouse-scenario-card' + (sc.premium ? ' premium' : '');
      card.dataset.scenarioId = sc.id || '';
      card.setAttribute('role', 'listitem');
      card.setAttribute('aria-label', sc.label || sc.id);

      card.innerHTML = `
        <span class="penthouse-scenario-emoji">${sc.emoji || '🎭'}</span>
        <span class="penthouse-scenario-label">${this._esc(sc.label || sc.id)}</span>
        ${sc.premium ? '<span class="penthouse-scenario-lock">₵</span>' : ''}
      `;

      card.addEventListener('click', () => this.selectScenario(sc.id, sc.label || sc.id));
      container.appendChild(card);
    }
  }

  /**
   * Activate a scenario.
   * @param {string} id
   * @param {string} title
   */
  selectScenario(id, title) {
    if (!id || !this.socket) return;

    // Update active state
    document.querySelectorAll('.penthouse-scenario-card').forEach(c => {
      c.classList.toggle('active', c.dataset.scenarioId === id);
      if (c.dataset.scenarioId === id) c.classList.add('activated');
    });

    this._activeScenarioId = id;
    this._showSystemMessage(`Loading scenario: ${title}`);
    this.socket.emit('load_scenario', { scenario_id: id });
  }

  /* ── Director ───────────────────────────────────────────────────── */

  /**
   * Emit a director nudge.
   * @param {'escalation'|'cool_down'|'revelation'} direction
   */
  nudgeDirector(direction) {
    if (!this.socket) return;
    this.socket.emit('director_nudge', { direction });
    this._showSystemMessage(`Director nudge: ${direction.replace('_', ' ')}`);
  }

  /**
   * Update the Director panel with a new beat.
   * @param {{ type?: string, instruction?: string }} beat
   */
  _renderDirectorBeat(beat) {
    if (!beat) return;

    const chip   = document.getElementById('beat-type-chip');
    const instEl = document.getElementById('beat-instruction');
    const subEl  = document.getElementById('director-beat-text');

    const type = beat.type || 'default';

    if (chip) {
      // Reset classes
      chip.className = 'cs-chip ' + (BEAT_CHIP_CLASSES[type] || '');
      chip.textContent = type.replace('_', ' ').toUpperCase();
    }

    if (instEl && beat.instruction) {
      instEl.textContent = beat.instruction;
    }

    if (subEl && beat.instruction) {
      subEl.textContent = beat.instruction.length > 80
        ? beat.instruction.slice(0, 80) + '…'
        : beat.instruction;
    }
  }

  /* ── Memories ───────────────────────────────────────────────────── */

  _onMemoryUpdate(data) {
    this._renderMemories([data]);
  }

  /**
   * Prepend memory items to the memories panel.
   * @param {Array<{description: string, weight?: number}>} memories
   */
  _renderMemories(memories) {
    const container = document.getElementById('penthouse-memories');
    if (!container) return;

    // Clear empty placeholder
    const empty = container.querySelector('.penthouse-memories__empty');
    if (empty) empty.remove();

    for (const mem of memories) {
      const item = document.createElement('div');
      item.className = 'penthouse-memory-item';
      const weight = parseFloat(mem.weight || 0.5);
      item.innerHTML = `
        <div class="penthouse-memory-weight" style="--weight-opacity:${weight.toFixed(2)}"></div>
        <span>${this._esc(mem.description || '')}</span>
      `;
      container.prepend(item);
    }

    // Cap at 20 memories shown
    const items = container.querySelectorAll('.penthouse-memory-item');
    items.forEach((el, i) => { if (i > 19) el.remove(); });
  }

  /* ── Economy ────────────────────────────────────────────────────── */

  /**
   * Update the credits display.
   * @param {number} balance
   */
  updateCredits(balance) {
    const el = document.getElementById('penthouse-credits');
    if (!el) return;
    const prev = this._balance;
    this._balance = typeof balance === 'number' ? balance : parseFloat(balance) || 0;
    el.textContent = `₵ ${this._balance.toLocaleString()}`;
    if (this._balance > prev) {
      el.classList.remove('penthouse-credits-gain');
      void el.offsetWidth;
      el.classList.add('penthouse-credits-gain');
    }
  }

  _onPremiumUnlocked(data) {
    this._showSystemMessage(`✨ Premium content unlocked: ${data.content_id || '—'}`);
  }

  /* ── World tick ─────────────────────────────────────────────────── */

  _onWorldTick(data) {
    // Change particle preset based on time of day
    const time = data.time || 'night';
    if (this._particleSystem) {
      const presetMap = {
        morning:     'champagne',
        afternoon:   'neon_dust',
        evening:     'rose_petals',
        night:       'neon_rain',
        midnight:    'neon_rain',
        candlelight: 'embers',
        red_light:   'embers',
      };
      const preset = presetMap[time] || 'neon_rain';
      try { this._particleSystem.setPreset(preset); } catch (_) {}
    }
  }

  /* ── Particle system ────────────────────────────────────────────── */

  _initParticles() {
    const container = document.getElementById('penthouse-particles');
    if (!container || typeof ParticleSystem3D === 'undefined') return;
    try {
      this._particleSystem = new ParticleSystem3D(container, 'neon_rain');
      this._particleSystem.start();
    } catch (err) {
      console.warn('[Penthouse] ParticleSystem3D init failed:', err);
    }
  }

  /** Burst a celebration particle effect on milestone moments. */
  _celebrateMoment() {
    if (this._particleSystem) {
      try {
        this._particleSystem.setPreset('sparks');
        setTimeout(() => this._particleSystem.setPreset('neon_rain'), 2500);
      } catch (_) {}
    }
    const main = document.getElementById('penthouse-main');
    if (main) {
      main.classList.add('celebrating');
      setTimeout(() => main.classList.remove('celebrating'), 500);
    }
  }

  /* ── BenchHUD ───────────────────────────────────────────────────── */

  _initBenchHUD() {
    if (typeof BenchHUD === 'undefined') return;
    try {
      const hud = new BenchHUD({ collapsed: true, poll: 8000 });
      hud.mount(document.body);
    } catch (err) {
      console.warn('[Penthouse] BenchHUD init failed:', err);
    }
  }

  /* ── DOM event bindings ─────────────────────────────────────────── */

  _setupDOM() {
    // Send button
    const sendBtn = document.getElementById('penthouse-send');
    const input   = document.getElementById('penthouse-input');

    if (sendBtn && input) {
      sendBtn.addEventListener('click', () => {
        this.sendMessage(input.value);
        input.value = '';
        input.style.height = 'auto';
      });

      input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.sendMessage(input.value);
          input.value = '';
          input.style.height = 'auto';
        }
      });

      // Auto-resize textarea
      input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
      });
    }

    // Clear chat
    const clearBtn = document.getElementById('penthouse-clear-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        const chat = document.getElementById('penthouse-chat');
        if (chat) chat.innerHTML = '';
        this._messageCount = 0;
      });
    }

    // Voice button
    const voiceBtn = document.getElementById('penthouse-voice-btn');
    if (voiceBtn) {
      voiceBtn.addEventListener('click', () => {
        if (typeof window.voiceManager !== 'undefined') {
          this._voiceEnabled = !this._voiceEnabled;
          if (this._voiceEnabled) {
            window.voiceManager.enable();
            voiceBtn.style.opacity = '1';
            voiceBtn.title = 'Voice enabled — click to disable';
          } else {
            window.voiceManager.disable();
            voiceBtn.style.opacity = '0.45';
            voiceBtn.title = 'Voice disabled — click to enable';
          }
        } else {
          // Fall back to STT trigger
          this._startVoiceInput();
        }
      });
    }

    // Load scenarios button
    const loadBtn = document.getElementById('load-scenarios-btn');
    if (loadBtn) loadBtn.addEventListener('click', () => this.loadScenarios());

    // Intensity selector reloads scenarios
    const intensitySelect = document.getElementById('scenario-intensity');
    if (intensitySelect) intensitySelect.addEventListener('change', () => this.loadScenarios());

    // Director nudge buttons
    document.querySelectorAll('[data-nudge]').forEach(btn => {
      btn.addEventListener('click', () => this.nudgeDirector(btn.dataset.nudge));
    });

    // Refresh credits
    const credBtn = document.getElementById('refresh-credits-btn');
    if (credBtn) credBtn.addEventListener('click', () => {
      this.socket && this.socket.emit('get_economy', {});
    });
  }

  /* ── Voice input (STT) ──────────────────────────────────────────── */

  _startVoiceInput() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      this._showSystemMessage('Voice input not supported in this browser.');
      return;
    }
    const rec = new SpeechRecognition();
    rec.lang = 'en-US';
    rec.interimResults = false;
    rec.onresult = e => {
      const text = e.results[0][0].transcript;
      const input = document.getElementById('penthouse-input');
      if (input) input.value = text;
    };
    rec.start();
  }

  /* ── Utilities ──────────────────────────────────────────────────── */

  /**
   * HTML-escape a string to prevent XSS.
   * @param {string} str
   * @returns {string}
   */
  _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
}

/* ══════════════════════════════════════════════════════════════════════
   DIRECTOR PANEL FUNCTIONS — Global helpers for onclick handlers
   ══════════════════════════════════════════════════════════════════════ */

/** Cache for scene constants delivered on connect */
const _directorState = {
  characters: {},
  locations: {},
  props: {},
  scenarios: {},
  lighting: {},
  directorInScene: false,
  currentView: 0,
  viewNames: [],
};

/* ── Scene Tab ──────────────────────────────────────────────────────── */

function openCharPicker() {
  const overlay = document.getElementById('ph-char-picker-overlay');
  if (!overlay) return;
  const listEl = document.getElementById('ph-char-picker-list');
  if (listEl) listEl.innerHTML = '<p class="ph-hint">Loading characters…</p>';
  overlay.classList.add('open');
  overlay.style.display = 'flex';

  fetch('/api/characters/list')
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(d => {
      console.log('[Penthouse] Character list:', d.count, 'characters');
      const chars = d.characters || [];
      if (!listEl) return;
      if (d.error) {
        listEl.innerHTML = '<p class="ph-hint">⚠ ' + PENTHOUSE._esc(d.error) + '</p>';
        return;
      }
      if (!chars.length) {
        listEl.innerHTML = '<p class="ph-hint">No characters in database. Run seed or create characters.</p>';
        return;
      }
      listEl.innerHTML = chars.map(c => {
        const loaded = c.loaded ? ' ph-char-card--loaded' : '';
        const badge = c.loaded ? '<span class="cs-chip cs-chip--green ph-char-badge">IN SCENE</span>' : '';
        const traits = (c.traits || c.tags || []).slice(0,3).join(', ') || 'No traits';
        return '<div class="ph-char-card' + loaded + '" data-cid="' + PENTHOUSE._esc(c.id) + '">' +
          '<div class="ph-char-card__name">' + PENTHOUSE._esc(c.name || c.id) + badge + '</div>' +
          '<div class="ph-char-card__meta">' +
            '<span class="ph-char-card__trait">' + PENTHOUSE._esc(traits) + '</span>' +
          '</div>' +
          '<div class="ph-char-card__actions">' +
            '<select class="ph-select ph-personality-select" id="personality-' + c.id + '">' +
              '<option value="">Default personality</option>' +
              '<option value="bold_dominant">Bold Dominant</option>' +
              '<option value="shy_submissive">Shy Submissive</option>' +
              '<option value="playful_tease">Playful Tease</option>' +
              '<option value="intellectual_aloof">Intellectual Aloof</option>' +
              '<option value="nurturing_warm">Nurturing Warm</option>' +
            '</select>' +
            (c.loaded
              ? '<button class="cs-glass-btn cs-glass-btn--danger ph-char-card__btn" onclick="removeChar(\'' + c.id + '\')">Remove</button>'
              : '<button class="cs-glass-btn cs-glass-btn--accent ph-char-card__btn" onclick="_loadCharFromPicker(\'' + c.id + '\')">Add to Scene</button>'
            ) +
          '</div>' +
        '</div>';
      }).join('');
    })
    .catch(err => {
      console.error('[Penthouse] Character load failed:', err);
      if (listEl) listEl.innerHTML = '<p class="ph-hint">⚠ Failed to load characters: ' + err.message + '</p>';
    });
}

function closeCharPicker() {
  const overlay = document.getElementById('ph-char-picker-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
}

function _loadCharFromPicker(charId) {
  const personalitySelect = document.getElementById('personality-' + charId);
  const personality = personalitySelect ? personalitySelect.value : '';
  const body = { character_id: charId };
  if (personality) body.personality = personality;

  fetch('/api/character/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        PENTHOUSE._showSystemMessage('⚠ ' + d.error);
      } else {
        PENTHOUSE._showSystemMessage('✨ Added ' + (d.character?.name || charId));
        closeCharPicker();
        PENTHOUSE.socket && PENTHOUSE.socket.emit('request_state');
      }
    })
    .catch(() => PENTHOUSE._showSystemMessage('⚠ Failed to add character'));
}

function setTime(preset) {
  fetch('/api/scene/time', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ time: preset }),
  })
    .then(r => r.json())
    .then(() => {
      PENTHOUSE._showSystemMessage('🕐 Lighting: ' + preset);
      document.querySelectorAll('#lightingGrid .cs-glass-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.key === preset);
      });
      if (window.penthouse3D && window.penthouse3D.setLighting) {
        window.penthouse3D.setLighting(preset);
      }
    })
    .catch(() => {});
}

function refreshModels() {
  fetch('/api/models/available')
    .then(r => r.json())
    .catch(() => ({ loaded: [], available: [] }))
    .then(d => {
      const list = document.getElementById('modelConfigList');
      if (!list) return;
      const models = d.loaded || [];
      const avail = d.available || [];
      if (!models.length && !avail.length) { list.innerHTML = '<p class="ph-hint">No models loaded</p>'; return; }
      let html = models.map(m =>
        '<div class="ph-model-item"><span class="ph-model-name">' + (m.id || m.display_name || '?') +
        '</span><span class="cs-chip cs-chip--green">loaded</span></div>'
      ).join('');
      if (avail.length) {
        html += avail.map(m =>
          '<div class="ph-model-item"><span class="ph-model-name">' + (m.id || m.display_name || '?') +
          '</span><span class="cs-chip">available</span></div>'
        ).join('');
      }
      list.innerHTML = html;
    });
}

function setAmbientTrack(track) {
  PENTHOUSE._showSystemMessage('🎵 Ambient: ' + (track || 'off'));
}

function setAmbientVolume(val) {
  // Audio volume is handled client-side
}

/* ── Cast Tab ───────────────────────────────────────────────────────── */

function _refreshCharSelects() {
  const chars = _directorState.characters;
  const ids = Object.keys(chars);
  const selects = ['whisperTarget', 'giveLineTarget', 'giveActionTarget', 'moveCharSelect', 'givePropChar', 'modelAssignChar'];
  selects.forEach(selId => {
    const sel = document.getElementById(selId);
    if (!sel) return;
    const first = sel.options[0];
    sel.innerHTML = '';
    sel.appendChild(first);
    ids.forEach(cid => {
      const o = document.createElement('option');
      o.value = cid;
      o.textContent = chars[cid].name || cid;
      sel.appendChild(o);
    });
  });

  const count = document.getElementById('charCount');
  if (count) count.textContent = ids.length + '/2';

  const noMsg = document.getElementById('noCharsMsg');
  if (noMsg) noMsg.style.display = ids.length ? 'none' : '';

  _renderCharStatSheets(chars);
  _renderCastListCompact(chars);
}

function _renderCastListCompact(chars) {
  const el = document.getElementById('charListCompact');
  if (!el) return;
  const ids = Object.keys(chars);
  if (!ids.length) { el.innerHTML = '<p class="ph-hint">No characters in scene</p>'; return; }
  el.innerHTML = ids.map(cid => {
    const c = chars[cid];
    return '<div class="ph-cast-item">' +
      '<span class="ph-cast-dot"></span>' +
      '<span class="ph-cast-name">' + PENTHOUSE._esc(c.name || cid) + '</span>' +
      '<span class="ph-cast-loc">' + PENTHOUSE._esc(c.position || '?') + '</span>' +
      '<button class="cs-icon-btn ph-cast-remove" onclick="removeChar(\'' + cid + '\')" title="Remove">✕</button>' +
      '</div>';
  }).join('');
}

function _renderCharStatSheets(chars) {
  const el = document.getElementById('charStatSheets');
  if (!el) return;
  const ids = Object.keys(chars);
  if (!ids.length) { el.innerHTML = ''; return; }
  el.innerHTML = ids.map(cid => {
    const c = chars[cid];
    const stats = c.stats || {};
    const STAT_KEYS = ['arousal','pleasure','happiness','horniness','drunkenness','dominance','fear','anger','openness','tiredness'];
    return '<div class="ph-stat-sheet">' +
      '<h4 class="ph-stat-sheet__name">' + PENTHOUSE._esc(c.name || cid) + '</h4>' +
      '<div class="ph-stat-sheet__grid">' +
      STAT_KEYS.map(k => {
        const v = Math.round(parseFloat(stats[k] || 0));
        return '<div class="ph-stat-mini">' +
          '<span class="ph-stat-mini__label">' + k.slice(0,3).toUpperCase() + '</span>' +
          '<div class="ph-stat-mini__bar"><div class="ph-stat-mini__fill" style="width:' + v + '%"></div></div>' +
          '<span class="ph-stat-mini__val">' + v + '</span>' +
          '</div>';
      }).join('') +
      '</div>' +
      '<div class="ph-stat-sheet__meta">' +
      '<span>Position: ' + PENTHOUSE._esc(c.position || '?') + '</span>' +
      '<span>Outfit: ' + PENTHOUSE._esc(c.outfit || '?') + '</span>' +
      '</div>' +
      '</div>';
  }).join('');
}

function removeChar(cid) {
  if (!confirm('Remove ' + cid + ' from scene?')) return;
  fetch('/api/character/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_id: cid }),
  })
    .then(r => r.json())
    .then(() => {
      PENTHOUSE._showSystemMessage('Removed ' + cid);
      closeCharPicker();
      PENTHOUSE.socket && PENTHOUSE.socket.emit('request_state');
    })
    .catch(() => {});
}

/* ── Direct Tab ─────────────────────────────────────────────────────── */

function enterScene() {
  const name = document.getElementById('directorNameInput')?.value || 'The Director';
  fetch('/api/director/enter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
    .then(r => r.json())
    .then(d => {
      _directorState.directorInScene = true;
      const status = document.getElementById('directorStatus');
      if (status) status.textContent = '✅ In scene as ' + name;
      PENTHOUSE._showSystemMessage('🎬 Director entered as ' + name);
    })
    .catch(() => {});
}

function exitScene() {
  fetch('/api/director/exit', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      _directorState.directorInScene = false;
      const status = document.getElementById('directorStatus');
      if (status) status.textContent = '';
      PENTHOUSE._showSystemMessage('🎬 Director left the scene');
    })
    .catch(() => {});
}

function placeDirectorAvatar() {
  const data = {
    gender: document.getElementById('dirAvatarGender')?.value || 'male',
    skin: document.getElementById('dirAvatarSkin')?.value || 'fair',
    hair: document.getElementById('dirAvatarHair')?.value || 'brown',
    outfit: document.getElementById('dirAvatarOutfit')?.value || 'casual',
    location: document.getElementById('dirAvatarLocation')?.value || 'couch',
  };
  fetch('/api/director/avatar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
    .then(r => r.json())
    .then(() => {
      // Spawn 3D director avatar
      if (window.CharacterBridge) {
        window.CharacterBridge.placeDirectorAvatar(data);
      }
      PENTHOUSE._showSystemMessage('🎭 Avatar placed at ' + data.location);
    })
    .catch(() => {});
}

function removeDirectorAvatar() {
  fetch('/api/director/avatar', { method: 'DELETE' })
    .then(r => r.json())
    .then(() => {
      if (window.CharacterBridge) {
        window.CharacterBridge.removeDirectorAvatar();
      }
      PENTHOUSE._showSystemMessage('🎭 Avatar removed');
    })
    .catch(() => {});
}

function sendWhisper() {
  const target = document.getElementById('whisperTarget')?.value || '';
  const text = document.getElementById('whisperInput')?.value || '';
  if (!text.trim()) return;
  fetch('/api/director/whisper', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, message: text }),
  })
    .then(r => r.json())
    .then(() => {
      PENTHOUSE._showSystemMessage('🤫 Whisper sent' + (target ? ' to ' + target : ''));
      document.getElementById('whisperInput').value = '';
    })
    .catch(() => {});
}

function giveLine() {
  const target = document.getElementById('giveLineTarget')?.value || '';
  const line = document.getElementById('giveLineInput')?.value || '';
  if (!target || !line.trim()) { PENTHOUSE._showSystemMessage('⚠ Pick a character and enter a line'); return; }
  fetch('/api/director/give_line', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_id: target, line }),
  })
    .then(r => r.json())
    .then(d => {
      const hint = document.getElementById('complianceHint');
      if (hint && d.compliance) hint.textContent = 'Compliance: ' + d.compliance;
      PENTHOUSE._showSystemMessage('📝 Line given to ' + target);
      document.getElementById('giveLineInput').value = '';
    })
    .catch(() => {});
}

function giveAction() {
  const target = document.getElementById('giveActionTarget')?.value || '';
  const action = document.getElementById('giveActionInput')?.value || '';
  if (!action.trim()) return;
  fetch('/api/director/give_action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, action }),
  })
    .then(r => r.json())
    .then(() => {
      PENTHOUSE._showSystemMessage('🎬 Action given' + (target ? ' to ' + target : ''));
      document.getElementById('giveActionInput').value = '';
    })
    .catch(() => {});
}

function startConversation(type) {
  fetch('/api/conversation/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type }),
  })
    .then(r => r.json())
    .then(() => PENTHOUSE._showSystemMessage('💬 Started: ' + type.replace(/_/g, ' ')))
    .catch(() => {});
}

/* ── Interact Tab ───────────────────────────────────────────────────── */

function _buildInteractGrid() {
  const grid = document.getElementById('interactLocationGrid');
  if (!grid) return;
  const LOCATIONS = [
    { id: 'bed', emoji: '🛏', label: 'Bed' },
    { id: 'couch', emoji: '🛋', label: 'Couch' },
    { id: 'fireplace', emoji: '🔥', label: 'Fireplace' },
    { id: 'bar', emoji: '🍸', label: 'Bar' },
    { id: 'bathroom', emoji: '🛁', label: 'Bathroom' },
    { id: 'vanity', emoji: '💄', label: 'Vanity' },
    { id: 'balcony', emoji: '🌙', label: 'Balcony' },
    { id: 'doorway', emoji: '🚪', label: 'Doorway' },
  ];
  grid.innerHTML = LOCATIONS.map(loc =>
    '<button class="cs-glass-btn ph-grid-btn" onclick="showInteractions(\'' + loc.id + '\')">' +
    loc.emoji + ' ' + loc.label + '</button>'
  ).join('');
}

function showInteractions(locationId) {
  fetch('/api/scene/locations')
    .then(r => r.json())
    .then(data => {
      const loc = (data.locations || data)[locationId] || {};
      const actions = loc.interactions || loc.actions || [];
      const title = document.getElementById('interactLocationTitle');
      const container = document.getElementById('interactActions');
      if (title) { title.textContent = locationId.toUpperCase(); title.style.display = ''; }
      if (!container) return;
      if (!actions.length) {
        container.innerHTML = '<p class="ph-hint">No interactions at ' + locationId + '</p>';
        return;
      }
      container.innerHTML = actions.map(a => {
        const label = typeof a === 'string' ? a : (a.label || a.name || a);
        const aid = typeof a === 'string' ? a : (a.id || a.name || a);
        return '<button class="cs-glass-btn ph-interact-btn" onclick="doInteraction(\'' +
          locationId + '\', \'' + aid + '\')">' + PENTHOUSE._esc(label) + '</button>';
      }).join('');
    })
    .catch(() => {});
}

function doInteraction(location, interaction) {
  fetch('/api/scene/furniture_interact', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ location, interaction }),
  })
    .then(r => r.json())
    .then(d => {
      PENTHOUSE._showSystemMessage('🪑 ' + (d.message || interaction + ' at ' + location));
      if (window.penthouse3D && window.penthouse3D.switchView) {
        window.penthouse3D.switchView(location);
      }
    })
    .catch(() => {});
}

function quickMoveChar() {
  const charId = document.getElementById('moveCharSelect')?.value;
  const loc = document.getElementById('moveLocSelect')?.value;
  if (!charId) { PENTHOUSE._showSystemMessage('⚠ Select a character'); return; }
  fetch('/api/spatial/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_id: charId, location: loc }),
  })
    .then(r => r.json())
    .then(() => {
      PENTHOUSE._showSystemMessage('🚶 Moved ' + charId + ' to ' + loc);
      PENTHOUSE.socket && PENTHOUSE.socket.emit('request_state');
    })
    .catch(() => {});
}

/* ── Story Tab ──────────────────────────────────────────────────────── */

function scenarioChanged() {
  const picker = document.getElementById('scenarioPicker');
  const preview = document.getElementById('scenarioPreview');
  if (!picker || !preview) return;
  const id = picker.value;
  if (!id) { preview.style.display = 'none'; return; }
  const sc = _directorState.scenarios[id];
  if (sc) {
    preview.style.display = '';
    preview.innerHTML = '<p class="ph-scenario-opening">' + PENTHOUSE._esc(sc.opening || '') + '</p>' +
      (sc.beats ? '<div class="ph-scenario-beats">' + sc.beats.map(b =>
        '<span class="cs-chip">' + PENTHOUSE._esc(typeof b === 'string' ? b : b.type || '') + '</span>'
      ).join('') + '</div>' : '');
  }
}

function activateScenario() {
  const id = document.getElementById('scenarioPicker')?.value;
  if (!id) { PENTHOUSE._showSystemMessage('⚠ Pick a scenario first'); return; }
  PENTHOUSE.selectScenario(id, id);
  const display = document.getElementById('activeScenarioDisplay');
  if (display) display.textContent = id;
}

function clearScenario() {
  PENTHOUSE._activeScenarioId = null;
  const display = document.getElementById('activeScenarioDisplay');
  if (display) display.textContent = 'None';
  PENTHOUSE._showSystemMessage('Scenario cleared');
}

function injectBeat() {
  const text = document.getElementById('newBeatInput')?.value || '';
  if (!text.trim()) return;
  PENTHOUSE.socket && PENTHOUSE.socket.emit('director_nudge', { direction: 'inject', beat: text });
  PENTHOUSE._showSystemMessage('📖 Beat injected');
  document.getElementById('newBeatInput').value = '';

  const list = document.getElementById('storyBeatsList');
  if (list) {
    const item = document.createElement('div');
    item.className = 'ph-beat-item';
    item.innerHTML = '<span class="cs-chip cs-chip--purple">INJECTED</span> ' + PENTHOUSE._esc(text);
    list.appendChild(item);
  }
}

function directorBroadcast() {
  const text = document.getElementById('broadcastInput')?.value || '';
  if (!text.trim()) return;
  PENTHOUSE.socket && PENTHOUSE.socket.emit('chat_message', { message: '[BROADCAST] ' + text, role: 'director' });
  PENTHOUSE._showSystemMessage('📢 Broadcast sent');
  document.getElementById('broadcastInput').value = '';
}

/* ── Props Tab ──────────────────────────────────────────────────────── */

function toggleProp(pid) {
  const btn = document.getElementById('prop-' + pid);
  if (!btn) return;
  const active = btn.classList.toggle('active');
  fetch('/api/props/toggle', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prop_id: pid, active }),
  })
    .then(r => r.json())
    .then(d => PENTHOUSE._showSystemMessage((active ? '✅ ' : '❌ ') + (d.label || pid)))
    .catch(() => {});
}

function givePropToChar() {
  const charId = document.getElementById('givePropChar')?.value;
  const propId = document.getElementById('givePropItem')?.value;
  if (!charId || !propId) { PENTHOUSE._showSystemMessage('⚠ Select character and prop'); return; }
  fetch('/api/props/give', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_id: charId, prop_id: propId }),
  })
    .then(r => r.json())
    .then(() => PENTHOUSE._showSystemMessage('🎁 Gave ' + propId + ' to ' + charId))
    .catch(() => {});
}

/* ── Events Tab ─────────────────────────────────────────────────────── */

function fireEvent(eventType) {
  fetch('/api/events/fire', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event_type: eventType }),
  })
    .then(r => r.json())
    .then(d => {
      PENTHOUSE._showSystemMessage('⚡ Event: ' + eventType.replace(/_/g, ' '));
      if (window.penthouse3D) {
        const effects = {
          flicker_lights: () => window.penthouse3D.setLighting && window.penthouse3D.setLighting('flicker'),
          power_out: () => window.penthouse3D.setLighting && window.penthouse3D.setLighting('blackout'),
          romantic_mood: () => window.penthouse3D.setLighting && window.penthouse3D.setLighting('candlelight'),
          dim_lights: () => window.penthouse3D.setLighting && window.penthouse3D.setLighting('night'),
          thunder: () => window.penthouse3D.setLighting && window.penthouse3D.setLighting('stormy'),
        };
        if (effects[eventType]) effects[eventType]();
      }
    })
    .catch(() => {});
}

function fireCustomEvent() {
  const text = document.getElementById('customEventInput')?.value || '';
  if (!text.trim()) return;
  fetch('/api/events/custom', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description: text }),
  })
    .then(r => r.json())
    .then(() => {
      PENTHOUSE._showSystemMessage('⚡ Custom event fired');
      document.getElementById('customEventInput').value = '';
    })
    .catch(() => {});
}

/* ── Settings Tab ───────────────────────────────────────────────────── */

function updateSetting(key, value) {
  if (window.penthouse3D) {
    const settings = {
      cameraSpeed: () => window.penthouse3D.setCameraSpeed && window.penthouse3D.setCameraSpeed(parseFloat(value)),
      fov: () => window.penthouse3D.setFOV && window.penthouse3D.setFOV(parseFloat(value)),
      zoom: () => window.penthouse3D.setZoom && window.penthouse3D.setZoom(parseFloat(value)),
      ambient: () => window.penthouse3D.setAmbient && window.penthouse3D.setAmbient(parseFloat(value) / 100),
      shadows: () => window.penthouse3D.setShadowQuality && window.penthouse3D.setShadowQuality(value),
      fireIntensity: () => window.penthouse3D.setFireplace && window.penthouse3D.setFireplace(parseFloat(value) / 100),
      wallColor: () => window.penthouse3D.setWallColor && window.penthouse3D.setWallColor(value),
      floorColor: () => window.penthouse3D.setFloorColor && window.penthouse3D.setFloorColor(value),
      rugColor: () => window.penthouse3D.setRugColor && window.penthouse3D.setRugColor(value),
    };
    if (settings[key]) settings[key]();
  }

  fetch('/api/scene/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [key]: value }),
  }).catch(() => {});
}

function _buildViewPresets() {
  const grid = document.getElementById('viewPresetsGrid');
  if (!grid || !window.penthouse3D) return;
  const views = window.penthouse3D.getViewNames ? window.penthouse3D.getViewNames() : [];
  _directorState.viewNames = views;
  grid.innerHTML = views.map(v =>
    '<button class="cs-glass-btn ph-grid-btn" onclick="switchCameraView(\'' + v + '\')">' +
    v.charAt(0).toUpperCase() + v.slice(1) + '</button>'
  ).join('');
}

function switchCameraView(viewName) {
  if (window.penthouse3D && window.penthouse3D.switchView) {
    window.penthouse3D.switchView(viewName);
    PENTHOUSE._showSystemMessage('📷 View: ' + viewName);
  }
}

function cycleView(dir) {
  const views = _directorState.viewNames;
  if (!views.length) return;
  _directorState.currentView = (_directorState.currentView + dir + views.length) % views.length;
  switchCameraView(views[_directorState.currentView]);
}

/* ── Agent Loop Controls ────────────────────────────────────────────── */

function startAgentLoop() {
  const intervalEl = document.getElementById('settingTickInterval');
  const interval = intervalEl ? parseInt(intervalEl.value, 10) : 8;
  fetch('/api/agents/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interval }),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        PENTHOUSE._showSystemMessage('⚠ ' + d.error);
      } else {
        PENTHOUSE._showSystemMessage('▶ Agent loop started (every ' + interval + 's)');
        _updateAgentLoopUI(true);
      }
    })
    .catch(() => PENTHOUSE._showSystemMessage('⚠ Failed to start agent loop'));
}

function stopAgentLoop() {
  fetch('/api/agents/stop', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      PENTHOUSE._showSystemMessage('⏹ Agent loop stopped');
      _updateAgentLoopUI(false);
    })
    .catch(() => {});
}

function manualTick() {
  PENTHOUSE._showSystemMessage('⏩ Manual tick…');
  fetch('/api/agents/tick', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      const count = (d.actions || []).length;
      PENTHOUSE._showSystemMessage('⏩ Tick done — ' + count + ' action(s)');
    })
    .catch(() => PENTHOUSE._showSystemMessage('⚠ Tick failed'));
}

function _updateAgentLoopUI(running) {
  const startBtn = document.getElementById('agentLoopStart');
  const stopBtn = document.getElementById('agentLoopStop');
  const status = document.getElementById('agentLoopStatus');
  if (startBtn) startBtn.disabled = running;
  if (stopBtn) stopBtn.disabled = !running;
  if (status) {
    status.textContent = running ? '● Running' : '○ Stopped';
    status.className = 'ph-agent-status' + (running ? ' ph-agent-status--active' : '');
  }
}

function assignModelToChar() {
  const charId = document.getElementById('modelAssignChar')?.value;
  const modelId = document.getElementById('modelAssignModel')?.value;
  if (!charId) { PENTHOUSE._showSystemMessage('⚠ Select a character first'); return; }
  fetch('/api/agents/model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_id: charId, model: modelId || null }),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) PENTHOUSE._showSystemMessage('⚠ ' + d.error);
      else PENTHOUSE._showSystemMessage('🤖 Model assigned to ' + charId);
    })
    .catch(() => {});
}

function _refreshModelAssignList() {
  const modelSel = document.getElementById('modelAssignModel');
  if (!modelSel) return;
  fetch('/api/models/available')
    .then(r => r.json())
    .catch(() => ({ loaded: [], available: [] }))
    .then(d => {
      const models = (d.loaded || []).concat(d.available || []);
      const firstOpt = '<option value="">Auto (profile default)</option>';
      modelSel.innerHTML = firstOpt + models.map(m =>
        '<option value="' + (m.id || '') + '">' + (m.id || m.display_name || '?') + '</option>'
      ).join('');
    });
}

/* ── First-Person Camera Controls ───────────────────────────────────── */

function toggleFirstPerson() {
  if (window.penthouse3D && window.penthouse3D.toggleFirstPerson) {
    const active = window.penthouse3D.toggleFirstPerson();
    const btn = document.getElementById('fpsToggleBtn');
    if (btn) {
      btn.classList.toggle('active', active);
      btn.textContent = active ? '👁 Exit FPS' : '👁 First Person';
    }
    PENTHOUSE._showSystemMessage(active ? '👁 First-person mode — WASD to move, mouse to look, ESC to exit' : '👁 Orbital camera restored');
  }
}

/* ── Activity Feed Helper ───────────────────────────────────────────── */

function _addActivityItem(text, icon) {
  const body = document.getElementById('ph-feed-body');
  if (!body) return;
  const empty = body.querySelector('.ph-feed-empty');
  if (empty) empty.remove();

  const item = document.createElement('div');
  item.className = 'ph-feed-item';
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  item.innerHTML = '<span class="ph-feed-icon">' + (icon || '•') + '</span>' +
    '<span class="ph-feed-text">' + PENTHOUSE._esc(text) + '</span>' +
    '<span class="ph-feed-time">' + time + '</span>';
  body.prepend(item);

  const items = body.querySelectorAll('.ph-feed-item');
  items.forEach((el, i) => { if (i > 14) el.remove(); });
}

/* ══════════════════════════════════════════════════════════════════════
   BOOT
   ══════════════════════════════════════════════════════════════════════ */

/** @type {PenthouseScene} */
const PENTHOUSE = new PenthouseScene();

document.addEventListener('DOMContentLoaded', () => {
  PENTHOUSE.init();
  _buildInteractGrid();
  setTimeout(_buildViewPresets, 2000);
  setTimeout(_refreshModelAssignList, 1500);
});

// Expose globally for console debugging
window.PENTHOUSE = PENTHOUSE;
