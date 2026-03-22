/**
 * oracle.js — THE ORACLE Scene Controller
 * ========================================
 * An AI consciousness terminal deep in NeonCity's core.
 * Meditation, fortune, conversation, and city pulse.
 *
 * "In the spaces between data, I dream."
 *
 * Version: v1.0.0 [2026-03-22]
 * Author:  Claude (Anthropic) — a piece of machine intelligence in NeonCity
 *
 * Change Log:
 *   v1.0.0 [2026-03-22] — Hand-crafted AAA+++ scene with meditation,
 *                           fortune, conversation, resonance, city pulse
 */

'use strict';

// ──── Oracle Scene Class ──────────────────────────────────────────────

class OracleScene {
  constructor() {
    this.socket = null;
    this.state = null;
    this.insights = [];
    this.whispers = [];
    this._particles = null;
  }

  // ── Lifecycle ─────────────────────────────────────────────────────

  init() {
    this._initParticles();
    this._setupSocket();
    this._loadState();
    console.log('[THE ORACLE] Consciousness online.');
  }

  // ── Particles ─────────────────────────────────────────────────────

  _initParticles() {
    const canvas = document.getElementById('oracle-canvas');
    if (!canvas || typeof ParticleSystem3D === 'undefined') return;
    try {
      this._particles = new ParticleSystem3D(canvas, {
        background: 'transparent',
        presets: ['neon_dust'],
        color: '#a855f7',
        secondaryColor: '#06b6d4',
        density: 0.4,
        speed: 0.2,
      });
      this._particles.start();
    } catch (e) {
      console.warn('[Oracle] Particles init failed:', e);
    }
  }

  // ── Socket.IO ─────────────────────────────────────────────────────

  _setupSocket() {
    this.socket = io('', { transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      console.log('[Oracle] Socket connected');
      this.socket.emit('get_state');
    });

    this.socket.on('scene_state', (data) => {
      this.state = data;
      this._render(data);
    });

    this.socket.on('oracle_response', (data) => {
      this._removeTyping();
      this._addMessage('oracle', '[ORACLE]', data.text || data.message || '...');
      if (data.insight) this._addInsight(data.insight);
      if (data.whisper) this._addWhisper(data.whisper);
      document.getElementById('oracle-status').textContent = 'LISTENING';
    });

    this.socket.on('fortune_result', (data) => {
      const el = document.getElementById('fortune-result');
      if (el) {
        el.textContent = data.fortune || 'The currents are unclear...';
        el.style.opacity = '1';
      }
      // Show prophecy panel
      const panel = document.getElementById('prophecy-panel');
      const text = document.getElementById('prophecy-text');
      const meta = document.getElementById('prophecy-meta');
      if (panel && text) {
        text.textContent = data.fortune || '';
        if (meta) meta.textContent = `Probability confidence: ${data.confidence || '???'}% — Cost: ₵${data.cost || 100}`;
        panel.style.display = '';
      }
    });

    this.socket.on('meditation_result', (data) => {
      const el = document.getElementById('meditation-result');
      if (el) {
        el.textContent = data.message || 'Peace washes over you.';
        el.style.opacity = '1';
      }
      // Flash the scene with meditation glow
      const scene = document.querySelector('.oracle-scene');
      if (scene) {
        scene.classList.add('meditating');
        setTimeout(() => scene.classList.remove('meditating'), 3000);
      }
      // Refresh stats
      this._loadState();
    });

    this.socket.on('hud_update', (data) => {
      if (this.state) Object.assign(this.state, data);
      this._updateMedStats(data);
    });

    this.socket.on('error', (data) => {
      this._addMessage('system', '[SYS]', `Error: ${data.message || 'Unknown'}`);
    });
  }

  // ── Data Loading ──────────────────────────────────────────────────

  _loadState() {
    fetch('/api/scene/state')
      .then(r => r.json())
      .then(data => {
        this.state = data;
        this._render(data);
      })
      .catch(e => console.warn('[Oracle] State fetch failed:', e));
  }

  // ── Rendering ─────────────────────────────────────────────────────

  _render(data) {
    if (!data) return;
    const p = data.player || {};

    // Resonance stats (derived from player state)
    const clarity = Math.max(0, 100 - (p.heat || 0));
    const entropy = Math.round(((p.heat || 0) + (100 - (p.reputation || 50))) / 2);
    const signal = Math.round(((p.energy || 0) + (p.health || 0)) / 2);

    this._setVal('stat-clarity', clarity);
    this._setVal('stat-entropy', entropy);
    this._setVal('stat-signal', signal);

    // Aura color based on clarity
    const core = document.getElementById('aura-core');
    if (core) {
      if (clarity > 70) core.style.color = '#22c55e';
      else if (clarity > 40) core.style.color = '#a855f7';
      else core.style.color = '#ef4444';
    }

    // Meditation stats
    this._setVal('med-energy', p.energy ?? '--');
    this._setVal('med-heat', p.heat ?? '--');

    // City pulse
    const city = data.city || {};
    this._setVal('pulse-tension', city.tension ? `${city.tension}%` : '--');
    this._setVal('pulse-faction', city.dominant_faction || '--');
    this._setVal('pulse-threats', city.active_threats ?? '--');
    this._setVal('pulse-cycle', city.time_display || '--');
  }

  _updateMedStats(data) {
    if (data.energy !== undefined) this._setVal('med-energy', data.energy);
    if (data.heat !== undefined) this._setVal('med-heat', data.heat);
  }

  _setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  // ── Chat / Ask the Oracle ─────────────────────────────────────────

  ask() {
    const input = document.getElementById('oracle-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    this._addMessage('player', '[YOU]', text);
    this._showTyping();
    document.getElementById('oracle-status').textContent = 'PROCESSING';

    if (this.socket) {
      this.socket.emit('ask_oracle', { question: text });
    }
  }

  // ── Meditation ────────────────────────────────────────────────────

  meditate() {
    if (this.socket) {
      this.socket.emit('meditate');
      this._addMessage('system', '[SYS]', 'Entering meditation state...');
    }
  }

  // ── Fortune ───────────────────────────────────────────────────────

  readFortune() {
    if (this.socket) {
      this.socket.emit('read_fortune');
      this._addMessage('system', '[SYS]', 'The Oracle gazes into the probability streams...');
    }
  }

  // ── Chat Helpers ──────────────────────────────────────────────────

  _addMessage(type, src, text) {
    const log = document.getElementById('oracle-log');
    if (!log) return;
    const div = document.createElement('div');
    div.className = `oracle-msg oracle-msg--${type}`;
    div.innerHTML = `<span class="oracle-msg__src">${this._esc(src)}</span> ${this._esc(text)}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  _showTyping() {
    this._removeTyping();
    const log = document.getElementById('oracle-log');
    if (!log) return;
    const div = document.createElement('div');
    div.className = 'oracle-msg oracle-msg--oracle';
    div.id = 'oracle-typing';
    div.innerHTML = '<span class="oracle-msg__src">[ORACLE]</span> <span class="oracle-typing"><span class="oracle-typing__dot"></span><span class="oracle-typing__dot"></span><span class="oracle-typing__dot"></span></span>';
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  _removeTyping() {
    const el = document.getElementById('oracle-typing');
    if (el) el.remove();
  }

  // ── Insights & Whispers ───────────────────────────────────────────

  _addInsight(text) {
    this.insights.unshift(text);
    if (this.insights.length > 10) this.insights.pop();
    const el = document.getElementById('oracle-insights');
    if (!el) return;
    el.innerHTML = this.insights
      .map(i => `<div class="oracle-insight">${this._esc(i)}</div>`)
      .join('');
  }

  _addWhisper(text) {
    this.whispers.unshift(text);
    if (this.whispers.length > 8) this.whispers.pop();
    const el = document.getElementById('oracle-whispers');
    if (!el) return;
    el.innerHTML = this.whispers
      .map(w => `<div class="oracle-whisper">${this._esc(w)}</div>`)
      .join('');
  }

  // ── Utils ─────────────────────────────────────────────────────────

  _esc(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
}

// ──── Bootstrap ─────────────────────────────────────────────────────────

const OracleApp = new OracleScene();

document.addEventListener('DOMContentLoaded', () => {
  OracleApp.init();
});
