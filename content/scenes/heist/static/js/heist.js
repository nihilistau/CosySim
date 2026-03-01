/**
 * THE SCORE — Client scene controller.
 * v0.68 "Dark Renaissance" — Grimy planning room for criminal jobs.
 * Port 5565 | Accent #e11d48 crimson.
 */
'use strict';

class TheScoreScene {
  constructor() {
    this.socket       = null;
    this.state        = null;
    this.jobs         = [];
    this.selectedJob  = null;
    this.particles    = null;
    // Tension meter state
    this.tensionPoints    = new Array(7).fill(30);
    this.tensionAnimTimer = null;
    // DOM element cache
    this.els = {};
  }

  // ── Lifecycle ──────────────────────────────────────────────────
  init() {
    this.els = {
      jobName:     document.getElementById('job-name'),
      heatBar:     document.getElementById('heat-bar'),
      heatValue:   document.getElementById('heat-value'),
      timerValue:  document.getElementById('timer-value'),
      phaseBadge:  document.getElementById('phase-badge'),
      jobBriefing: document.getElementById('job-briefing'),
      jobsList:    document.getElementById('jobs-list'),
      investBoard: document.getElementById('investigation-board'),
      boardHint:   document.getElementById('board-hint'),
      crewList:    document.getElementById('crew-list'),
      chatLog:     document.getElementById('chat-log'),
      crewTarget:  document.getElementById('crew-target'),
      chatInput:   document.getElementById('chat-input'),
      btnSend:     document.getElementById('btn-send'),
      btnAdvance:  document.getElementById('btn-advance'),
      btnAbort:    document.getElementById('btn-abort'),
      btnTick:     document.getElementById('btn-tick'),
      tensionLine: document.getElementById('tension-line'),
      tensionGlow: document.getElementById('tension-glow'),
      phaseStepper:document.getElementById('phase-stepper'),
      particlesEl: document.getElementById('heist-particles'),
    };

    this._setupSocket();
    this._initParticles();
    this._bindButtons();
    this._startTensionAnimation();
    this.loadState();
  }

  // ── Socket.IO ──────────────────────────────────────────────────
  _setupSocket() {
    this.socket = io();

    this.socket.on('connect', () => {
      console.debug('[TheScore] socket connected');
      this.socket.emit('get_heist_state');
      this.socket.emit('get_available_jobs');
    });

    this.socket.on('disconnect', () => {
      console.debug('[TheScore] socket disconnected');
    });

    this.socket.on('heist_state', (data) => {
      this.state = data;
      this._applyState(data);
    });

    // Backward-compat: old game_state event
    this.socket.on('game_state', (data) => {
      this.state = data;
      this._applyState(data);
    });

    this.socket.on('available_jobs', (data) => {
      this.jobs = data.jobs || [];
      this._renderJobsList(this.jobs);
    });

    this.socket.on('job_selected', (data) => {
      this.selectedJob = data;
      this._renderBriefing(data);
      if (this.els.jobName && data.venue) {
        this.els.jobName.textContent = data.venue.name || data.job_id;
      }
    });

    this.socket.on('crew_assigned', (data) => {
      this._updateCrewRole(data.crew_member, data.role);
    });

    this.socket.on('phase_executed', (data) => {
      if (data.state) {
        this.state = data.state;
        this._applyState(this.state);
      }
      if (data.blown)    this._onHeistBlown();
      if (data.complete) this._onHeistComplete();
    });

    this.socket.on('heist_aborted', (data) => {
      this._showAlert('\u26a0 ABORT \u2014 ' + data.message, 'abort');
      this._setPhaseBadge('BLOWN');
    });

    this.socket.on('investigation_state', (data) => {
      this._renderInvestigationBoard(data.board || {});
    });

    this.socket.on('crew_message', (data) => {
      this._appendChatMessage(data.name, data.message, 'crew');
      this._pulseCrewCard(data.character_id);
      if (data.mood) this._spikeTension(4);
    });

    this.socket.on('typing', (data) => {
      if (data.typing) {
        this._appendChatMessage(data.character_id, '\u2026 typing', 'typing');
      } else {
        this.els.chatLog && this.els.chatLog.querySelector('.typing')?.remove();
      }
    });

    this.socket.on('complication', (data) => {
      this._showAlert('\u26a1 COMPLICATION: ' + data.message, 'complication');
      this._spikeTension(22);
    });

    this.socket.on('game_event', (data) => {
      if (data.complication) this._showAlert('\u26a1 ' + data.complication, 'complication');
    });

    this.socket.on('error', (data) => {
      console.warn('[TheScore] server error:', data.msg);
    });
  }

  loadState() {
    this.socket.emit('get_heist_state');
    this.socket.emit('get_available_jobs');
    this.socket.emit('get_investigation');
  }

  getJobs() {
    this.socket.emit('get_available_jobs');
  }

  selectJob(jobId) {
    if (!jobId) return;
    this.socket.emit('select_job', { job_id: jobId });
    document.querySelectorAll('.job-option-card').forEach(el => {
      el.classList.toggle('selected', el.dataset.jobId === jobId);
    });
  }

  assignCrew(member, role) {
    if (!member || !role) return;
    this.socket.emit('assign_crew', { crew_member: member, role: role });
  }

  executePhase(phase) {
    this.socket.emit('execute_phase', { phase: phase });
  }

  sendMessage(text) {
    text = (text || '').trim();
    if (!text) return;
    const target = this.els.crewTarget ? this.els.crewTarget.value : '';
    if (!target) {
      this._showAlert('Select a crew member to contact.', 'warn');
      return;
    }
    this._appendChatMessage('Mastermind', text, 'mastermind');
    this.socket.emit('chat_message', { character_id: target, message: text });
    if (this.els.chatInput) this.els.chatInput.value = '';
    this._spikeTension(6);
  }

  // ── State rendering ────────────────────────────────────────────
  _applyState(state) {
    if (!state) return;

    // Heat / suspicion
    const heat = state.suspicion || state.heat || 0;
    this._setHeat(heat);

    // Phase
    const phase = (state.phase || 'planning').toLowerCase();
    this._setPhaseBadge(phase.toUpperCase());
    this._renderPhases(phase);

    // Job name from venue
    if (state.venue && this.els.jobName) {
      this.els.jobName.textContent = state.venue.name || state.job_id || '— SELECT JOB —';
    }

    // Crew cards
    if (state.crew) this._renderCrew(state.crew);

    // Timer (time pressure 0-100)
    if (this.els.timerValue && state.time_pressure != null) {
      this.els.timerValue.textContent = 'T\u2212' + state.time_pressure;
      this.els.timerValue.classList.toggle('urgent', state.time_pressure > 70);
    }

    // Spike tension proportionally to heat
    if (heat > 55) this._spikeTension(heat * 0.25);
  }

  _setHeat(value) {
    const pct = Math.min(100, Math.max(0, value));
    if (this.els.heatBar) {
      this.els.heatBar.style.width = pct + '%';
      this.els.heatBar.style.setProperty('--heat-pct', pct);
    }
    if (this.els.heatValue) this.els.heatValue.textContent = pct;
  }

  _setPhaseBadge(phase) {
    if (this.els.phaseBadge) this.els.phaseBadge.textContent = phase;
  }

  _renderJobsList(jobs) {
    if (!this.els.jobsList) return;
    this.els.jobsList.innerHTML = '';
    jobs.forEach(job => {
      const risk      = job.difficulty > 2 ? 'HIGH' : job.difficulty > 1 ? 'MEDIUM' : 'LOW';
      const riskCls   = risk.toLowerCase();
      const payout    = (job.payout || job.loot_value || 0).toLocaleString();
      const card      = document.createElement('div');
      card.className  = 'job-option-card';
      card.dataset.jobId = job.id;
      card.setAttribute('role', 'listitem');
      card.innerHTML = `
        <div class="job-option-name">${job.name || job.id}</div>
        <div class="job-option-tags">
          <span class="tag">$${payout}</span>
          <span class="tag">${job.guards || 0} guards</span>
          <span class="tag risk-${riskCls}">${risk}</span>
        </div>`;
      card.addEventListener('click', () => this.selectJob(job.id));
      this.els.jobsList.appendChild(card);
    });
  }

  _renderBriefing(data) {
    if (!this.els.jobBriefing) return;
    const venue      = data.venue || {};
    const payout     = (venue.loot_value || data.payout || 0).toLocaleString();
    const diff       = venue.difficulty || 1;
    const riskClass  = diff > 2 ? 'risk-high' : diff > 1 ? 'risk-medium' : 'risk-low';
    const riskLabel  = diff > 2 ? 'HIGH'       : diff > 1 ? 'MEDIUM'     : 'LOW';
    const obstacles  = venue.obstacles || [];
    this.els.jobBriefing.innerHTML = `
      <div class="job-target">${venue.name || data.job_id || 'Unknown Target'}</div>
      <div class="job-meta">
        <div class="job-meta-item">
          <span class="job-meta-label">Payout</span>
          <span class="job-meta-value payout">$${payout}</span>
        </div>
        <div class="job-meta-item">
          <span class="job-meta-label">Risk</span>
          <span class="job-meta-value ${riskClass}">${riskLabel}</span>
        </div>
        <div class="job-meta-item">
          <span class="job-meta-label">Guards</span>
          <span class="job-meta-value">${venue.guards || '?'}</span>
        </div>
      </div>
      <div class="job-objectives">
        <div class="objectives-label">Objectives</div>
        ${obstacles.map(ob =>
          `<div class="objective-item">${ob.replace(/_/g,' ')}</div>`
        ).join('')}
      </div>`;
  }

  _renderCrew(crewData) {
    if (!this.els.crewList) return;
    const members = Object.entries(crewData || {});
    if (!members.length) return;

    this.els.crewList.innerHTML = '';

    // Repopulate target select
    if (this.els.crewTarget) {
      const prev = this.els.crewTarget.value;
      this.els.crewTarget.innerHTML = '<option value="">— crew —</option>';
      members.forEach(([id, m]) => {
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = m.name;
        this.els.crewTarget.appendChild(opt);
      });
      if (prev) this.els.crewTarget.value = prev;
    }

    const AVATARS = {
      hacker: '\uD83D\uDCBB', muscle: '\uD83D\uDCAA',
      talker: '\uD83D\uDDE3', driver: '\uD83D\uDE97',
      wildcard: '\uD83C\uDCCF',
    };

    members.forEach(([id, member]) => {
      const isArrested  = !!member.arrested;
      const isInjured   = !!member.injured;
      const status      = isArrested ? 'arrested' : isInjured ? 'injured' : 'ready';
      const statusLabel = isArrested ? 'ARRESTED' : isInjured ? 'INJURED' : 'READY';
      const avatar      = AVATARS[member.specialty] || '\uD83D\uDC64';
      const hp          = Math.round(member.health  || 100);
      const morale      = Math.round(member.morale  || 75);

      const card = document.createElement('div');
      card.className = 'crew-card';
      card.dataset.crewId = id;
      card.setAttribute('role', 'listitem');
      card.innerHTML = `
        <div class="crew-card-header">
          <div class="crew-avatar">${avatar}</div>
          <span class="crew-name">${member.name}</span>
          <span class="status-badge ${status}">${statusLabel}</span>
        </div>
        <div class="crew-role-badge">${(member.specialty || '').toUpperCase()}</div>
        <div class="crew-stats">
          <div class="crew-stat">
            <span class="stat-label">HP</span>
            <div class="stat-bar-wrap">
              <div class="stat-bar health" style="width:${hp}%"></div>
            </div>
          </div>
          <div class="crew-stat">
            <span class="stat-label">MORALE</span>
            <div class="stat-bar-wrap">
              <div class="stat-bar morale" style="width:${morale}%"></div>
            </div>
          </div>
        </div>`;
      this.els.crewList.appendChild(card);
    });
  }

  _renderPhases(currentPhase) {
    const ORDER = ['planning', 'approach', 'execution', 'escape', 'complete', 'failed'];
    const idx   = ORDER.indexOf(currentPhase);
    document.querySelectorAll('.phase-step').forEach((el, i) => {
      el.classList.remove('active', 'done');
      if      (i < idx)  el.classList.add('done');
      else if (i === idx) el.classList.add('active');
    });
  }

  _renderInvestigationBoard(board) {
    if (!this.els.investBoard) return;
    const nodes = board.nodes || [];
    if (!nodes.length) return;

    if (this.els.boardHint) this.els.boardHint.style.display = 'none';
    this.els.investBoard.innerHTML =
      '<svg class="board-connections" id="board-svg"></svg>';

    const bRect  = this.els.investBoard.getBoundingClientRect();
    const bW     = bRect.width  || 400;
    const bH     = bRect.height || 300;
    const cols   = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
    const cellW  = bW / cols;
    const cellH  = bH / Math.ceil(nodes.length / cols);
    const positions = [];

    nodes.forEach((node, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x   = 20 + col * cellW + (Math.random() - 0.5) * 16;
      const y   = 14 + row * cellH + (Math.random() - 0.5) * 10;
      positions.push({ x, y });

      const card = document.createElement('div');
      card.className = `pin-card${node.cleared ? ' cleared' : ''}`;
      card.style.left = x + 'px';
      card.style.top  = y + 'px';
      card.innerHTML = `
        <div class="pin-card-label">${node.type || 'intel'}</div>
        <div class="pin-card-title">${(node.label || node.id).replace(/_/g,' ')}</div>
        <span class="pin-card-type-badge ${node.type || 'obstacle'}">${node.type || 'obstacle'}</span>`;
      this._makeDraggable(card);
      this.els.investBoard.appendChild(card);
    });

    // Draw dashed connection lines between adjacent nodes
    const svg = document.getElementById('board-svg');
    if (svg && positions.length > 1) {
      for (let i = 0; i < positions.length - 1; i++) {
        const a    = positions[i];
        const b    = positions[i + 1];
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', a.x + 60);
        line.setAttribute('y1', a.y + 40);
        line.setAttribute('x2', b.x + 60);
        line.setAttribute('y2', b.y + 40);
        svg.appendChild(line);
      }
    }
  }

  _makeDraggable(el) {
    el.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT') return;
      e.preventDefault();
      const ox = el.offsetLeft - e.clientX;
      const oy = el.offsetTop  - e.clientY;
      const onMove = (ev) => {
        el.style.left = (ev.clientX + ox) + 'px';
        el.style.top  = (ev.clientY + oy) + 'px';
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup',   onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
  }

  // ── Chat ───────────────────────────────────────────────────────
  _appendChatMessage(name, text, type) {
    if (!this.els.chatLog) return;
    if (type !== 'typing') {
      this.els.chatLog.querySelector('.typing')?.remove();
    }
    const msg       = document.createElement('div');
    msg.className   = 'chat-message ' + (type || 'crew');
    msg.innerHTML   = `<span class="msg-name">${name}</span>${text}`;
    this.els.chatLog.appendChild(msg);
    this.els.chatLog.scrollTop = this.els.chatLog.scrollHeight;
    // Cap log at 60 messages
    while (this.els.chatLog.children.length > 60) {
      this.els.chatLog.firstChild.remove();
    }
  }

  _pulseCrewCard(crewId) {
    const card = document.querySelector(`.crew-card[data-crew-id="${crewId}"]`);
    if (!card) return;
    card.style.borderColor = 'var(--score-accent)';
    setTimeout(() => { card.style.borderColor = ''; }, 2200);
  }

  _updateCrewRole(member, role) {
    const card = document.querySelector(`.crew-card[data-crew-id="${member}"]`);
    if (!card) return;
    const rb = card.querySelector('.crew-role-badge');
    if (rb) rb.textContent = role.toUpperCase();
  }

  // ── Alerts ─────────────────────────────────────────────────────
  _showAlert(msg, type) {
    const el       = document.createElement('div');
    el.textContent = msg;
    el.style.cssText = [
      'position:fixed', 'bottom:72px', 'left:50%', 'transform:translateX(-50%)',
      'background:var(--score-surface)', 'border:1px solid var(--score-accent)',
      'color:var(--score-text)', 'padding:8px 20px', 'border-radius:3px',
      'font-size:12px', 'font-weight:600', 'letter-spacing:.06em',
      'z-index:200', 'animation:score-fadein .2s ease',
      'white-space:nowrap', 'pointer-events:none',
    ].join(';');
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  // ── Particles ──────────────────────────────────────────────────
  _initParticles() {
    const container = this.els.particlesEl;
    if (!container || typeof ParticleSystem3D === 'undefined') return;
    try {
      this.particles = new ParticleSystem3D(container, 'embers');
      this.particles.start();
    } catch (e) {
      console.debug('[TheScore] particles unavailable:', e.message);
    }
  }

  // ── Tension Meter SVG animation ────────────────────────────────
  _startTensionAnimation() {
    const tick = () => {
      this.tensionPoints.shift();
      const last  = this.tensionPoints[this.tensionPoints.length - 1];
      const drift = (Math.random() - 0.5) * 3.5;
      this.tensionPoints.push(Math.max(6, Math.min(54, last + drift)));
      this._drawTensionLine();
      this.tensionAnimTimer = setTimeout(tick, 130);
    };
    tick();
  }

  _spikeTension(amount) {
    const last  = this.tensionPoints[this.tensionPoints.length - 1] || 30;
    const spike = Math.min(54, last + amount);
    for (let i = 0; i < 3; i++) {
      this.tensionPoints.push(spike - i * (amount / 3));
      if (this.tensionPoints.length > 7) this.tensionPoints.shift();
    }
    this._drawTensionLine();
  }

  _drawTensionLine() {
    const { tensionLine: line, tensionGlow: glow } = this.els;
    if (!line) return;
    const pts    = this.tensionPoints;
    const step   = 300 / (pts.length - 1);
    const str    = pts.map((y, i) => `${(i * step).toFixed(1)},${y.toFixed(1)}`).join(' ');
    line.setAttribute('points', str);
    if (glow) glow.setAttribute('points', str);
  }

  // ── Button bindings ────────────────────────────────────────────
  _bindButtons() {
    const send = () => {
      const text = (this.els.chatInput?.value || '').trim();
      if (text) this.sendMessage(text);
    };

    this.els.btnSend?.addEventListener('click', send);
    this.els.chatInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') send();
    });

    this.els.btnAdvance?.addEventListener('click', () => {
      const phase = (this.state?.phase || 'planning').toLowerCase();
      this.executePhase(phase);
      this._spikeTension(10);
    });

    this.els.btnAbort?.addEventListener('click', () => {
      if (confirm('Abort the heist? Heat will linger for 48 hours.')) {
        this.socket.emit('abort_heist');
      }
    });

    this.els.btnTick?.addEventListener('click', () => {
      fetch('/api/crew/tick', { method: 'POST' }).catch(() => {});
      this._spikeTension(8);
    });
  }

  // ── Outcome handlers ───────────────────────────────────────────
  _onHeistBlown() {
    this._showAlert('\uD83D\uDEA8 BLOWN \u2014 Scatter! Every man for himself.', 'abort');
    this._spikeTension(32);
    if (this.particles) {
      try { this.particles.setIntensity?.(3.0); } catch (_) {}
    }
  }

  _onHeistComplete() {
    this._showAlert('\u2713 THE SCORE \u2014 Clean exit. Payout pending 24h.', 'success');
    this._setPhaseBadge('COMPLETE');
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  window._theScore = new TheScoreScene();
  window._theScore.init();
});
