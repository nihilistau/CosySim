/**
 * THE PENTHOUSE — BedroomScene JS  v0.68 "Dark Renaissance"
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

const BEDROOM_SOCKET_URL = `${location.protocol}//${location.hostname}:${location.port}`;

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
   BedroomScene CLASS
   ══════════════════════════════════════════════════════════════════════ */

class BedroomScene {
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
    this.socket = io(BEDROOM_SOCKET_URL, {
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

    // Bench HUD live push
    s.on('bench:update',   data => {
      if (typeof BenchHUD !== 'undefined') BenchHUD.update(data);
    });

    // Errors
    s.on('error',          data => this._showSystemMessage(`⚠ ${data.message || 'Unknown error'}`));
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

  /* ── Scene state handlers ───────────────────────────────────────── */

  _onSceneState(data) {
    const chars = data.characters || {};
    const ids   = Object.keys(chars);
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
  }

  _onConstants(data) {
    // Scenarios from server constants (initial load)
    if (data.scenarios && Object.keys(data.scenarios).length) {
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
    const chat = document.getElementById('bedroom-chat');
    if (!chat) return;

    const role    = msg.role || (msg.name === 'You' ? 'player' : 'char');
    const wrapper = document.createElement('div');
    wrapper.className = `bedroom-message bedroom-message--${role}`;

    const name = document.createElement('div');
    name.className = 'bedroom-message__name';
    name.textContent = msg.name || (role === 'player' ? 'You' : 'Character');

    const bubble = document.createElement('div');
    bubble.className = 'bedroom-message__bubble';
    bubble.textContent = msg.message || '';

    const ts = document.createElement('div');
    ts.className = 'bedroom-message__ts';
    ts.textContent = msg.timestamp
      ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    wrapper.append(name, bubble, ts);
    chat.appendChild(wrapper);
    chat.scrollTop = chat.scrollHeight;
  }

  _showSystemMessage(text) {
    this._renderMessage({ name: 'System', message: text, role: 'system' });
  }

  /* ── Typing indicator ───────────────────────────────────────────── */

  _setTyping(charName, visible) {
    const el    = document.getElementById('bedroom-typing');
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
    const container = document.getElementById('bedroom-scenarios');
    const chip      = document.getElementById('scenario-count-chip');
    if (!container) return;

    container.innerHTML = '';
    if (!scenarios || !scenarios.length) {
      container.innerHTML = '<div class="bedroom-scenarios__empty">No scenarios available.</div>';
      return;
    }

    if (chip) chip.textContent = scenarios.length;

    for (const sc of scenarios) {
      const card = document.createElement('button');
      card.className = 'bedroom-scenario-card' + (sc.premium ? ' premium' : '');
      card.dataset.scenarioId = sc.id || '';
      card.setAttribute('role', 'listitem');
      card.setAttribute('aria-label', sc.label || sc.id);

      card.innerHTML = `
        <span class="bedroom-scenario-emoji">${sc.emoji || '🎭'}</span>
        <span class="bedroom-scenario-label">${this._esc(sc.label || sc.id)}</span>
        ${sc.premium ? '<span class="bedroom-scenario-lock">₵</span>' : ''}
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
    document.querySelectorAll('.bedroom-scenario-card').forEach(c => {
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
    const container = document.getElementById('bedroom-memories');
    if (!container) return;

    // Clear empty placeholder
    const empty = container.querySelector('.bedroom-memories__empty');
    if (empty) empty.remove();

    for (const mem of memories) {
      const item = document.createElement('div');
      item.className = 'bedroom-memory-item';
      const weight = parseFloat(mem.weight || 0.5);
      item.innerHTML = `
        <div class="bedroom-memory-weight" style="--weight-opacity:${weight.toFixed(2)}"></div>
        <span>${this._esc(mem.description || '')}</span>
      `;
      container.prepend(item);
    }

    // Cap at 20 memories shown
    const items = container.querySelectorAll('.bedroom-memory-item');
    items.forEach((el, i) => { if (i > 19) el.remove(); });
  }

  /* ── Economy ────────────────────────────────────────────────────── */

  /**
   * Update the credits display.
   * @param {number} balance
   */
  updateCredits(balance) {
    const el = document.getElementById('bedroom-credits');
    if (!el) return;
    const prev = this._balance;
    this._balance = typeof balance === 'number' ? balance : parseFloat(balance) || 0;
    el.textContent = `₵ ${this._balance.toLocaleString()}`;
    if (this._balance > prev) {
      el.classList.remove('bedroom-credits-gain');
      void el.offsetWidth;
      el.classList.add('bedroom-credits-gain');
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
    const container = document.getElementById('bedroom-particles');
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
    const main = document.getElementById('bedroom-main');
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
    const sendBtn = document.getElementById('bedroom-send');
    const input   = document.getElementById('bedroom-input');

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
    const clearBtn = document.getElementById('bedroom-clear-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        const chat = document.getElementById('bedroom-chat');
        if (chat) chat.innerHTML = '';
        this._messageCount = 0;
      });
    }

    // Voice button
    const voiceBtn = document.getElementById('bedroom-voice-btn');
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
      const input = document.getElementById('bedroom-input');
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
   BOOT
   ══════════════════════════════════════════════════════════════════════ */

/** @type {BedroomScene} */
const PENTHOUSE = new BedroomScene();

document.addEventListener('DOMContentLoaded', () => PENTHOUSE.init());

// Expose globally for console debugging
window.PENTHOUSE = PENTHOUSE;
