/**
 * THE LAB — coders.js
 * v0.68 Dark Renaissance · Matrix-green terminal hacker scene
 *
 * Exposes: window.TheLab (TheLabScene instance)
 */

/* ═══════════════════════════════════════════════════════════════════
   Matrix Rain Canvas
   ═══════════════════════════════════════════════════════════════════ */
class MatrixRain {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.chars = '01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン'.split('');
    this.fontSize = 13;
    this.drops = [];
    this._init();
    this._frame = null;
    window.addEventListener('resize', () => this._init());
  }

  _init() {
    if (!this.canvas) return;
    this.canvas.width  = window.innerWidth;
    this.canvas.height = window.innerHeight;
    const cols = Math.floor(this.canvas.width / this.fontSize);
    this.drops = Array.from({ length: cols }, () => Math.random() * -50);
  }

  _tick() {
    const { ctx, canvas, fontSize, chars, drops } = this;
    ctx.fillStyle = 'rgba(5, 10, 7, 0.05)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#4ade80';
    ctx.font = `${fontSize}px "Cascadia Code", "Fira Code", monospace`;
    drops.forEach((y, i) => {
      const char = chars[Math.floor(Math.random() * chars.length)];
      const x = i * fontSize;
      // Brightest character at head
      ctx.fillStyle = (y > 0 && Math.random() > 0.95) ? '#ffffff' : '#4ade80';
      ctx.fillText(char, x, y * fontSize);
      if (y * fontSize > canvas.height && Math.random() > 0.975) {
        drops[i] = 0;
      }
      drops[i] += 0.5;
    });
  }

  start() {
    if (!this.canvas) return;
    const loop = () => {
      this._tick();
      this._frame = requestAnimationFrame(loop);
    };
    this._frame = requestAnimationFrame(loop);
  }

  stop() {
    if (this._frame) cancelAnimationFrame(this._frame);
  }
}

/* ═══════════════════════════════════════════════════════════════════
   Velocity Mini-Chart
   ═══════════════════════════════════════════════════════════════════ */
class VelocityChart {
  constructor(canvasId, maxPoints = 30) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
    this.maxPoints = maxPoints;
    this.data = [];
  }

  push(value) {
    this.data.push(value);
    if (this.data.length > this.maxPoints) this.data.shift();
    this._draw();
  }

  _draw() {
    if (!this.ctx) return;
    const { ctx, canvas, data } = this;
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    if (data.length < 2) return;
    const max = Math.max(...data, 1);
    const step = W / (data.length - 1);
    // Gradient fill
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0,   'rgba(74,222,128,0.5)');
    grad.addColorStop(1,   'rgba(74,222,128,0.0)');
    ctx.beginPath();
    ctx.moveTo(0, H);
    data.forEach((v, i) => {
      const x = i * step;
      const y = H - (v / max) * (H - 4);
      if (i === 0) ctx.lineTo(x, y);
      else         ctx.lineTo(x, y);
    });
    ctx.lineTo((data.length - 1) * step, H);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
    // Line
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = i * step;
      const y = H - (v / max) * (H - 4);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = '#4ade80';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}

/* ═══════════════════════════════════════════════════════════════════
   TheLabScene — Main Scene Controller
   ═══════════════════════════════════════════════════════════════════ */
class TheLabScene {
  constructor() {
    this.socket   = null;
    this.state    = null;
    this.matrix   = null;
    this.velChart = null;
    this._lineHistory = 0;  // for velocity delta
    this._agentColours = {
      Ada:    '#fbbf24',
      Linus:  '#4ade80',
      Grace:  '#60a5fa',
      Alan:   '#a78bfa',
      System: '#f87171',
    };
    this._agentRoles = {};   // name → role
  }

  /* ── Initialization ─────────────────────────────────────────── */

  init() {
    this.matrix   = new MatrixRain('matrix-canvas');
    this.velChart = new VelocityChart('velocity-chart');
    this.matrix.start();
    this._setupSocket();
    this._bindUI();
    this.loadState();
  }

  /* ── Socket.IO ──────────────────────────────────────────────── */

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      this._setFooterStatus('CONNECTED', true);
    });

    this.socket.on('disconnect', () => {
      this._setFooterStatus('OFFLINE', false);
    });

    // v1.49.2 [2026-03-22] — Socket.IO reconnect feedback
    this.socket.io.on('reconnect', (attempt) => {
      console.debug('[Coders] Reconnected after ' + attempt + ' attempt(s)');
    });
    this.socket.io.on('reconnect_attempt', (attempt) => {
      if (attempt % 3 === 0) console.debug('[Coders] Reconnecting... (attempt ' + attempt + ')');
    });

    this.socket.on('state_update', (data) => {
      if (data) this._applyState(data);
    });

    this.socket.on('agent_chat', (data) => {
      if (data) this._appendFeedMsg(data.agent, data.message, data.timestamp);
    });

    this.socket.on('terminal_output', (data) => {
      if (data) this._appendTerminal(data.agent, data.output);
    });

    // Bench HUD updates
    this.socket.on('bench:update', (data) => {
      if (data) this._updateBenchHud(data);
    });
  }

  /* ── State Loading ──────────────────────────────────────────── */

  async loadState() {
    try {
      const res  = await fetch('/api/state');
      const data = await res.json();
      if (data && data.active !== undefined) this._applyState(data);
    } catch (_) { /* server not yet started */ }
  }

  /* ── Task Control ───────────────────────────────────────────── */

  async startTask(description) {
    if (!description || !description.trim()) return;
    try {
      const res = await fetch('/api/feature/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: description.slice(0, 80), description }),
      });
      const data = await res.json();
      if (data.success) {
        this._appendFeedMsg('System', `📋 Task queued: "${data.feature?.title}"`, Date.now() / 1000);
      }
    } catch (e) {
      this._appendFeedMsg('System', `⚠️ Failed to queue task: ${e.message}`, Date.now() / 1000);
    }
  }

  async _bootLab() {
    try {
      const res  = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval: 15 }),
      });
      const data = await res.json();
      if (data.success) {
        document.getElementById('start-overlay').style.display = 'none';
        this._setFooterStatus('RUNNING', true);
        this._setPillActive(true);
      }
    } catch (e) {
      console.error('Boot failed', e);
    }
  }

  async _shutdown() {
    await fetch('/api/stop', { method: 'POST' });
    this._setFooterStatus('HALTED', false);
    this._setPillActive(false);
  }

  async _manualTick() {
    try {
      const res  = await fetch('/api/tick', { method: 'POST' });
      const data = await res.json();
      if (data.agents) this._applyState(data);
    } catch (_) {}
  }

  /* ── State Application ──────────────────────────────────────── */

  _applyState(s) {
    this.state = s;

    // Header stats
    this._setText('stat-ticks',   s.tick_count   ?? 0);
    this._setText('stat-lines',   s.total_lines  ?? 0);
    this._setText('stat-tests',   s.total_tests  ?? 0);
    this._setText('stat-shipped', s.completed    ?? (s.completed_features?.length ?? 0));
    this._setText('stat-agents',  s.agents?.length ?? 0);

    // Pill
    if (s.active) {
      this._setPillActive(true);
      this._setFooterStatus('RUNNING', true);
    }

    // Pipeline stepper
    const feature = (s.features || [])[0];
    if (feature) this._updatePipeline(feature.phase);

    // Task queue
    this._renderTaskQueue(s.features || [], s.completed_features?.length ?? s.completed ?? 0);

    // Agent roster in metrics
    if (s.agents) this._renderAgentRoster(s.agents);

    // Velocity chart
    const delta = (s.total_lines ?? 0) - this._lineHistory;
    if (delta >= 0) {
      this.velChart.push(delta);
      this._lineHistory = s.total_lines ?? 0;
    }

    // Velocity metrics
    const ticks = Math.max(1, s.tick_count ?? 1);
    this._setText('m-lpt', ((s.total_lines ?? 0) / ticks).toFixed(1));
    this._setText('m-tpt', ((s.total_tests ?? 0) / ticks).toFixed(2));

    // Sync show/hide start+stop buttons
    if (s.active) {
      this._show('btn-stop');
      this._hide('btn-start');
    }
  }

  /* ── Agent Feed Rendering ───────────────────────────────────── */

  _renderAgentFeed(messages) {
    const feed = document.getElementById('agent-feed');
    if (!feed) return;
    feed.innerHTML = '';
    messages.forEach(m => this._appendFeedMsg(m.agent, m.message, m.timestamp, feed));
  }

  _appendFeedMsg(agent, message, timestamp, container) {
    const feed = container || document.getElementById('agent-feed');
    if (!feed) return;

    // Remove placeholder on first real message
    const placeholder = feed.querySelector('.feed-placeholder');
    if (placeholder) placeholder.remove();

    const time = timestamp
      ? new Date(timestamp * 1000).toLocaleTimeString('en', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : new Date().toLocaleTimeString('en', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const div = document.createElement('div');
    div.className = 'feed-msg';
    div.innerHTML = `
      <div class="feed-msg-meta">
        <span class="agent-tag" data-agent="${this._esc(agent)}">${this._esc(agent)}</span>
        <span class="feed-msg-time">${time}</span>
      </div>
      <div class="feed-msg-body">${this._esc(message)}</div>
    `;
    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;

    // Cap at 150 messages
    while (feed.children.length > 150) feed.removeChild(feed.firstChild);
  }

  /* ── Pipeline Stepper Update ────────────────────────────────── */

  _updatePipeline(phase) {
    const phaseOrder = ['feature', 'design', 'coding', 'review', 'testing', 'complete'];
    const phaseToStep = { feature: 0, design: 0, coding: 1, review: 2, testing: 3, complete: 4, failed: -1 };
    const activeIdx = phaseToStep[phase] ?? -1;
    const steps = document.querySelectorAll('.pipeline-stepper .step');
    const connectors = document.querySelectorAll('.step-connector');
    steps.forEach((s, i) => {
      s.classList.toggle('active', i === activeIdx);
      s.classList.toggle('done', i < activeIdx);
    });
    connectors.forEach((c, i) => {
      c.classList.toggle('lit', i < activeIdx);
    });
  }

  /* ── Task Queue Rendering ───────────────────────────────────── */

  _renderTaskQueue(features, completedCount) {
    const list = document.getElementById('task-queue-list');
    const badge = document.getElementById('queue-count');
    if (!list) return;
    list.innerHTML = '';
    features.forEach(f => {
      const card = document.createElement('div');
      card.className = `task-card phase-${f.phase || 'feature'}`;
      card.innerHTML = `
        <div class="task-card-title">${this._esc(f.title)}</div>
        <div class="task-card-phase phase-${f.phase || 'feature'}">${(f.phase || 'QUEUED').toUpperCase()}</div>
      `;
      list.appendChild(card);
    });
    if (completedCount > 0) {
      const done = document.createElement('div');
      done.className = 'task-card phase-complete';
      done.innerHTML = `
        <div class="task-card-title">✓ ${completedCount} shipped</div>
        <div class="task-card-phase phase-complete">COMPLETE</div>
      `;
      list.appendChild(done);
    }
    if (badge) badge.textContent = features.length;
  }

  /* ── Agent Roster (Metrics Panel) ──────────────────────────── */

  _renderAgentRoster(agents) {
    const roster = document.getElementById('agent-roster');
    const legend = document.getElementById('agent-legend');
    if (!roster) return;
    roster.innerHTML = '';

    const maxLines = Math.max(1, ...agents.map(a => a.lines_written || 0));
    const legendHtml = [];

    agents.forEach(a => {
      const pct = Math.round((a.lines_written || 0) / maxLines * 100);
      const div = document.createElement('div');
      div.className = 'roster-agent';
      div.innerHTML = `
        <div class="roster-name">
          <span class="agent-tag agent-tag--xs" data-agent="${this._esc(a.name)}">${this._esc(a.name)}</span>
        </div>
        <div class="roster-status ${a.status || 'idle'}">${(a.status || 'idle').toUpperCase()}</div>
        <div class="roster-bar">
          <div class="roster-bar-fill" style="width:${pct}%"></div>
        </div>
      `;
      roster.appendChild(div);

      legendHtml.push(
        `<span class="agent-tag" data-agent="${this._esc(a.name)}">${this._esc(a.name)}</span>`
      );

      // Store role
      if (a.role) this._agentRoles[a.name] = a.role;
    });

    if (legend) legend.innerHTML = legendHtml.join('');
  }

  /* ── Terminal Output ─────────────────────────────────────────── */

  _appendTerminal(agent, output) {
    const el = document.getElementById('terminal-output');
    if (!el) return;
    const lines = (output || '').split('\n');
    lines.forEach((line, i) => {
      const div = document.createElement('div');
      div.className = 't-line';
      div.style.animationDelay = `${i * 0.04}s`;
      div.textContent = `[${agent}] ${line}`;
      el.appendChild(div);
    });
    el.scrollTop = el.scrollHeight;
    // Cap at 500 lines
    while (el.children.length > 500) el.removeChild(el.firstChild);
  }

  clearTerminal() {
    const el = document.getElementById('terminal-output');
    if (el) el.innerHTML = '';
  }

  /* ── Bench HUD ──────────────────────────────────────────────── */

  _updateBenchHud(data) {
    if (data.response_ms) this._setText('bench-response', `${data.response_ms}ms`);
    if (data.tokens_per_sec) this._setText('bench-tps', data.tokens_per_sec.toFixed(1));
    if (data.model) this._setText('bench-model', data.model.slice(0, 20));
  }

  /* ── Terminal Input ─────────────────────────────────────────── */

  sendMessage(text) {
    if (!text || !text.trim()) return;
    const t = text.trim();
    if (t.startsWith('/tick')) {
      this._manualTick();
    } else if (t.startsWith('/stop')) {
      this._shutdown();
    } else if (t.startsWith('/start')) {
      this._bootLab();
    } else {
      // Treat as a task description
      this.startTask(t);
    }
  }

  /* ── UI Binding ─────────────────────────────────────────────── */

  _bindUI() {
    // Overlay start button
    const overlayBtn = document.getElementById('start-btn-overlay');
    if (overlayBtn) overlayBtn.addEventListener('click', () => this._bootLab());

    // Header start/stop buttons
    const btnStart = document.getElementById('btn-start');
    const btnStop  = document.getElementById('btn-stop');
    if (btnStart) btnStart.addEventListener('click', () => this._bootLab());
    if (btnStop)  btnStop.addEventListener('click', () => this._shutdown());

    // Add task button
    const btnAdd = document.getElementById('btn-add-task');
    if (btnAdd) {
      btnAdd.addEventListener('click', () => {
        const desc = prompt('Enter task description:');
        if (desc && desc.trim()) this.startTask(desc.trim());
      });
    }

    // Manual tick
    const btnTick = document.getElementById('btn-manual-tick');
    if (btnTick) btnTick.addEventListener('click', () => this._manualTick());

    // Terminal footer input
    const input = document.getElementById('terminal-input');
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          this.sendMessage(input.value);
          input.value = '';
        }
      });
    }
  }

  /* ── Helpers ─────────────────────────────────────────────────── */

  _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  _show(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = '';
  }

  _hide(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  }

  _setPillActive(active) {
    const dot   = document.getElementById('sim-dot');
    const label = document.getElementById('sim-label');
    if (dot)   dot.classList.toggle('active', active);
    if (label) label.textContent = active ? 'RUNNING' : 'OFFLINE';
  }

  _setFooterStatus(text, active) {
    this._setText('footer-status', text);
    const dot = document.getElementById('footer-dot');
    if (dot) dot.classList.toggle('active', active);
  }

  _esc(str) {
    const d = document.createElement('div');
    d.textContent = String(str || '');
    return d.innerHTML;
  }
}

/* ── Bootstrap ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  window.TheLab = new TheLabScene();
  window.TheLab.init();
});
