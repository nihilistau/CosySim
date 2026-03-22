/**
 * THE BRIEFING ROOM — BriefingRoomScene
 * CosySim v0.68 "Dark Renaissance"
 * Mission control above the hacker loft — cyan/blue hybrid accent.
 */

'use strict';

// ──────────────────────────────────────────────────────────
// DATA STREAM PARTICLES
// ──────────────────────────────────────────────────────────

class DataStreamParticles {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.particles = [];
    this.raf = null;
    this._resize();
    window.addEventListener('resize', () => this._resize());
  }

  _resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
    this._initParticles();
  }

  _initParticles() {
    const count = Math.floor(this.canvas.width / 18);
    this.particles = Array.from({ length: count }, () => this._createParticle(true));
  }

  _createParticle(randomY = false) {
    const h = this.canvas.height;
    return {
      x:    -Math.random() * this.canvas.width,
      y:    randomY ? Math.random() * h : Math.random() * h,
      len:  40 + Math.random() * 120,
      spd:  3 + Math.random() * 8,
      alpha: 0.15 + Math.random() * 0.55,
      w:    0.5 + Math.random() * 1.2,
    };
  }

  start() {
    const loop = () => {
      this._draw();
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    if (this.raf) cancelAnimationFrame(this.raf);
  }

  _draw() {
    const { ctx, canvas } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of this.particles) {
      const grad = ctx.createLinearGradient(p.x, p.y, p.x + p.len, p.y);
      grad.addColorStop(0,   `rgba(6,182,212,0)`);
      grad.addColorStop(0.4, `rgba(6,182,212,${p.alpha * 0.5})`);
      grad.addColorStop(1,   `rgba(6,182,212,${p.alpha})`);
      ctx.strokeStyle = grad;
      ctx.lineWidth = p.w;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(p.x + p.len, p.y);
      ctx.stroke();
      p.x += p.spd;
      if (p.x > canvas.width + p.len) {
        Object.assign(p, this._createParticle());
        p.x = -p.len;
      }
    }
  }
}

// ──────────────────────────────────────────────────────────
// BRIEFING ROOM SCENE
// ──────────────────────────────────────────────────────────

class BriefingRoomScene {
  constructor() {
    this.socket = null;
    this.particles = null;
    this._pollTimer = null;
    this._clockTimer = null;
    this._pollCount = 0;
    this.operatorTargets = [];
  }

  /** Bootstrap everything */
  init() {
    this._setupParticles();
    this._setupSocket();
    this._setupClock();
    this._setupTickerRating();
    this._bindOperatorConsole();
    this._connectNotifications();
    this.loadDashboard();
    this._pollLoop();
    this._refreshRatingStats();
    console.debug('[BriefingRoom] Online — v0.77 The First Mind');
  }

  /** Wire ticker click → rating toast */
  _setupTickerRating() {
    const tickerItems = document.getElementById('news-ticker-items');
    if (!tickerItems) return;
    tickerItems.addEventListener('click', e => {
      const item = e.target.closest('.news-ticker-item');
      if (!item || item.classList.contains('news-ticker-item--loading')) return;
      this._showRatingToast({
        item_id: item.dataset.itemId || '',
        title:   item.textContent.trim(),
        content: item.title || '',
        category: item.dataset.category || 'news',
      });
    });
  }

  // ── Particles ──────────────────────────────────────────

  _setupParticles() {
    const canvas = document.getElementById('data-stream-canvas');
    if (!canvas) return;
    this.particles = new DataStreamParticles(canvas);
    this.particles.start();
  }

  // ── Socket.IO ──────────────────────────────────────────

  _setupSocket() {
    try {
      this.socket = io({ transports: ['websocket', 'polling'] });

      this.socket.on('connect', () => {
        console.debug('[BriefingRoom] Socket connected:', this.socket.id);
      });

      this.socket.on('disconnect', () => {
        console.debug('[BriefingRoom] Socket disconnected');
      });

      this.socket.on('metrics_update', (data) => {
        this._renderSystemStats(data.system || {});
        this._updateStatusLights(data);
        this._updateEconomy(data);
        this._updateConsequences(data);
      });

      this.socket.on('activity_item', (item) => {
        this._appendActivity(item);
      });

      this.socket.on('activity', (items) => {
        if (Array.isArray(items)) {
          items.slice(0, 8).reverse().forEach(i => this._appendActivity(i));
        }
      });

      this.socket.on('world_event', (evt) => {
        this._onWorldEvent(evt);
      });
    } catch (e) {
      console.warn('[BriefingRoom] Socket.IO unavailable:', e.message);
    }
  }

  // ── System clock ───────────────────────────────────────

  _setupClock() {
    const el = document.getElementById('briefing-clock');
    if (!el) return;
    const tick = () => {
      const now = new Date();
      el.textContent = now.toLocaleTimeString('en-GB', { hour12: false });
    };
    tick();
    this._clockTimer = setInterval(tick, 1000);
  }

  // ── Dashboard load ─────────────────────────────────────

  async loadDashboard() {
    try {
      await Promise.allSettled([
        this._loadOverview(),
        this._loadNews(),
        this._loadWorldEvents(),
        this._loadSceneHealth(),
        this._loadScheduler(),
        this._loadNlm(),
        this._loadOperator(),
        this._loadFlywheelPanel(),
      ]);
    } catch (e) {
      console.warn('[BriefingRoom] loadDashboard error:', e);
    }
  }

  async _loadOverview() {
    try {
      const data = await _api('/api/overview');
      this._renderSystemStats(data.system || {});
      this._updateStatusLights(data);
      this._updateEconomy(data);
    } catch (_) { /* silent */ }
  }

  async _loadNews() {
    try {
      const data = await _api('/api/news/latest?limit=15');
      const items = data.items || data.articles || [];
      this._renderNewsFeed('news-feed', items, 'INTEL');
    } catch (_) {
      _setHtml('news-feed', '<div class="feed-placeholder">Feed unavailable.</div>');
    }
  }

  async _loadWorldEvents() {
    const data = await _safeApi('/api/world/events?limit=12', { events: [] });
    this._renderWorldEvents(data.events || []);
  }

  _refreshSceneHealth() { this._loadSceneHealth(); }
  _refreshNlm() { this._loadNlm(); }

  async _loadSceneHealth() {
    const data = await _safeApi('/api/scenes/health', { scenes: [] });
    this._renderSceneHealth(data.scenes || []);
  }

  async _loadScheduler() {
    try {
      const data = await _api('/api/scheduler/tasks');
      const tasks = data.tasks || [];
      const running = data.running ?? false;
      const stateEl = document.getElementById('sched-state');
      if (stateEl) {
        stateEl.textContent = running ? 'RUNNING' : 'STOPPED';
        stateEl.dataset.running = running;
        _setText('scheduler-badge', `${tasks.length} tasks`);
      }
      const listEl = document.getElementById('scheduler-task-list');
      if (listEl) {
        if (!tasks.length) {
          listEl.innerHTML = '<div class="feed-placeholder">No scheduled tasks.</div>';
          return;
        }
        listEl.innerHTML = tasks.slice(0, 6).map(t => `
          <div class="task-item" role="listitem">
            <div class="task-item__status task-item__status--${t.status || 'pending'}"></div>
            <span class="task-item__name">${_esc(t.name || t.id || 'Unknown task')}</span>
          </div>`).join('');
      }
    } catch (_) { /* silent */ }
  }

  async _loadNlm() {
    try {
      const data = await _api('/api/cache/status');
      const last = data.last_cycle || {};
      const gaps = data.gaps || [];
      const hitRate = last.hit_rate != null
        ? `${Math.round(last.hit_rate * 100)}%`
        : '—';
      _setText('nlm-hit-rate', hitRate);
      _setText('nlm-qa-pairs', last.qa_pairs ?? '—');
      _setText('nlm-last-cycle', last.timestamp ? last.timestamp.slice(0, 16) : '—');
      _setText('nlm-gaps', gaps.length);
    } catch (_) { /* silent */ }
  }

  async _loadFlywheelPanel() {
    try {
      const data = await _api('/api/flywheel/stats');
      const r = data.router || {};
      const t = data.training || {};
      const n = data.nexus || {};
      const s = data.scheduler || {};

      const hitRate = r.hit_rate != null ? `${Math.round(r.hit_rate * 100)}%` : (r.total_queries ? '0%' : '—');
      _setText('fw-hit-rate', hitRate);
      _setText('fw-queries', r.total_queries ?? '—');
      _setText('fw-tokens-saved', r.total_tokens_saved != null ? r.total_tokens_saved.toLocaleString() : '—');
      _setText('fw-examples', t.total_examples ?? '—');
      _setText('fw-quality', t.avg_quality != null ? `${Math.round(t.avg_quality * 100)}%` : '—');
      _setText('fw-entries', n.entries ?? '—');
      _setText('fw-qa', n.qa_pairs ?? '—');
      _setText('fw-rules', n.rules ?? '—');

      const healthy = !n.error && !s.error;
      _setText('flywheel-badge', healthy ? (s.running ? 'ACTIVE' : 'IDLE') : 'DEGRADED');
    } catch (_) { /* silent */ }
  }

  _bindOperatorConsole() {
    const form = document.getElementById('operator-form');
    if (form) {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        this._submitOperatorForm();
      });
    }

    const refreshBtn = document.getElementById('operator-refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => this._loadOperator());
    }

    const processBtn = document.getElementById('operator-process-btn');
    if (processBtn) {
      processBtn.addEventListener('click', () => this._processOperatorInbox());
    }
  }

  async _loadOperator() {
    const data = await _safeApi('/api/operator/status?limit=12', {});
    this.operatorTargets = data.command_targets || [];
    this._populateOperatorTargets(this.operatorTargets);
    this._renderOperatorSummary(data);
    this._renderOperatorInbox(data.inbox || {});
    this._renderOperatorQueue(data.queue || {});
    this._renderOperatorActivity(data.activity || {});
    this._renderOperatorGit(data.git || {});
  }

  async _submitOperatorForm() {
    const payload = {
      title: (document.getElementById('operator-title')?.value || '').trim(),
      item_type: document.getElementById('operator-item-type')?.value || 'note',
      priority: Number(document.getElementById('operator-priority')?.value || 60),
      dispatch_mode: document.getElementById('operator-dispatch-mode')?.value || 'queue',
      scene_id: document.getElementById('operator-scene-id')?.value || '',
      character_id: (document.getElementById('operator-character-id')?.value || '').trim(),
      author: (document.getElementById('operator-author')?.value || 'operator').trim() || 'operator',
      tags: (document.getElementById('operator-tags')?.value || '')
        .split(',')
        .map(tag => tag.trim())
        .filter(Boolean),
      content: (document.getElementById('operator-content')?.value || '').trim(),
      create_task: Boolean(document.getElementById('operator-create-task')?.checked),
      turns: Number(document.getElementById('operator-turns')?.value || 1),
    };

    if (!payload.title || !payload.content) {
      this._showOperatorToast('Title and content are required.', 'error');
      return;
    }

    const submitBtn = document.querySelector('#operator-form button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
      const result = await _api('/api/operator/inbox', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      const dispatch = result.dispatch;
      const processing = result.processing;
      let message = 'Saved to operator inbox.';
      if (dispatch && dispatch.mode && dispatch.mode !== 'queue') {
        message = dispatch.ok
          ? `Saved + live ${dispatch.mode} dispatch succeeded.`
          : `Saved, but live ${dispatch.mode} dispatch failed.`;
      } else if (processing && processing.created_tasks) {
        message = `Saved + queued ${processing.created_tasks} task.`;
      }
      this._showOperatorToast(message, dispatch && dispatch.ok === false ? 'error' : 'info');
      ['operator-title', 'operator-tags', 'operator-content', 'operator-character-id'].forEach((id) => {
        const field = document.getElementById(id);
        if (field) field.value = '';
      });
      await this._loadOperator();
    } catch (error) {
      this._showOperatorToast(`Submit failed: ${error.message}`, 'error');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  async _processOperatorInbox() {
    const processBtn = document.getElementById('operator-process-btn');
    if (processBtn) processBtn.disabled = true;
    try {
      const result = await _api('/api/operator/inbox/process', {
        method: 'POST',
        body: JSON.stringify({ limit: 10 }),
      });
      this._showOperatorToast(
        result.processed
          ? `Processed ${result.processed} inbox item(s).`
          : 'No pending operator items to process.',
      );
      await this._loadOperator();
    } catch (error) {
      this._showOperatorToast(`Process failed: ${error.message}`, 'error');
    } finally {
      if (processBtn) processBtn.disabled = false;
    }
  }

  _populateOperatorTargets(targets) {
    const select = document.getElementById('operator-scene-id');
    if (!select) return;
    const current = select.value;
    const options = ['<option value="">Select target scene</option>']
      .concat((targets || []).map(target => {
        const label = `${target.label || target.id} :${target.port || '—'}`;
        return `<option value="${_esc(target.id || '')}">${_esc(label)}</option>`;
      }))
      .join('');
    select.innerHTML = options;
    if (current) select.value = current;
  }

  _renderOperatorSummary(data) {
    const inboxSummary = data.inbox?.summary || {};
    const queueSummary = data.queue?.summary || {};
    const git = data.git || {};
    const activity = data.activity || {};
    _setText('operator-summary-pending', inboxSummary.pending ?? 0);
    _setText('operator-summary-queued', queueSummary.pending ?? 0);
    _setText('operator-summary-active', activity.active_count ?? 0);
    _setText('operator-summary-branch', git.branch || '—');
    const badge = document.getElementById('operator-status-badge');
    if (badge) {
      badge.textContent = `P${inboxSummary.pending ?? 0} • Q${queueSummary.pending ?? 0}`;
    }
    _setText('operator-submit-hint', git.dirty ? 'repo has local changes' : 'repo clean');
  }

  _renderOperatorInbox(inbox) {
    const items = inbox.items || [];
    const summary = inbox.summary || {};
    _setText('operator-inbox-meta', `${summary.pending ?? 0} pending / ${summary.total ?? 0} total`);
    const container = document.getElementById('operator-inbox-list');
    if (!container) return;
    if (!items.length) {
      container.innerHTML = '<div class="feed-placeholder">No operator items yet.</div>';
      return;
    }
    container.innerHTML = items.map(item => `
      <article class="operator-item">
        <div class="operator-item__header">
          <span class="operator-item__title">${_esc(item.title || 'Untitled')}</span>
          <span class="operator-badge operator-badge--${_esc(item.status || 'pending')}">${_esc(item.status || 'pending')}</span>
        </div>
        <div class="operator-item__meta">
          <span>${_esc(item.item_type || 'note')} • p${_esc(item.priority ?? 0)}</span>
          <span>${_relTime(item.created_at)}</span>
        </div>
        <div class="operator-item__body">${_esc((item.content || '').slice(0, 280))}</div>
        <div class="operator-item__footer">
          ${(item.task_id ? `task ${_esc(item.task_id)}` : 'no task yet')}
          ${(item.metadata?.dispatch_mode && item.metadata.dispatch_mode !== 'queue') ? ` • ${_esc(item.metadata.dispatch_mode)}` : ''}
        </div>
      </article>
    `).join('');
  }

  _renderOperatorQueue(queue) {
    const tasks = queue.tasks || [];
    const summary = queue.summary || {};
    _setText(
      'operator-queue-meta',
      `${summary.pending ?? 0} pending / ${summary.in_progress ?? 0} active / ${summary.completed ?? 0} done`,
    );
    const container = document.getElementById('operator-queue-list');
    if (!container) return;
    if (!tasks.length) {
      container.innerHTML = '<div class="feed-placeholder">Queue is empty.</div>';
      return;
    }
    container.innerHTML = tasks.slice(0, 12).map(task => `
      <article class="operator-item">
        <div class="operator-item__header">
          <span class="operator-item__title">${_esc(task.title || task.id || 'Untitled task')}</span>
          <span class="operator-badge operator-badge--${_esc((task.status || 'pending').toLowerCase())}">${_esc(task.status || 'pending')}</span>
        </div>
        <div class="operator-item__meta">
          <span>priority ${_esc(task.priority ?? 0)}</span>
          <span>${_relTime(task.created_at)}</span>
        </div>
        <div class="operator-item__body">${_esc((task.description || '').slice(0, 220))}</div>
      </article>
    `).join('');
  }

  _renderOperatorActivity(activity) {
    const active = activity.active || [];
    const recent = activity.recent || [];
    _setText('operator-activity-meta', `${activity.active_count ?? 0} active / ${activity.recent_count ?? 0} recent`);
    const container = document.getElementById('operator-activity-list');
    if (!container) return;
    const rows = [];
    active.forEach(item => {
      rows.push({
        title: `[LIVE] ${item.label || item.kind || 'activity'}`,
        meta: `${item.scene || 'system'} • ${item.elapsed_ms || 0}ms`,
      });
    });
    recent.forEach(item => {
      rows.push({
        title: item.label || item.kind || 'activity',
        meta: `${item.agent_id || 'system'} • ${item.duration_ms || 0}ms`,
      });
    });
    if (!rows.length) {
      container.innerHTML = '<div class="feed-placeholder">No active work reported.</div>';
      return;
    }
    container.innerHTML = rows.slice(0, 14).map(item => `
      <article class="operator-item">
        <div class="operator-item__title">${_esc(item.title)}</div>
        <div class="operator-item__meta"><span>${_esc(item.meta)}</span></div>
      </article>
    `).join('');
  }

  _renderOperatorGit(git) {
    _setText('operator-git-dirty', git.dirty ? 'DIRTY TREE' : 'TREE CLEAN');
    const card = document.getElementById('operator-git-card');
    if (!card) return;
    if (!git.available) {
      card.innerHTML = '<div class="feed-placeholder">Git summary unavailable.</div>';
      return;
    }
    const changes = Array.isArray(git.changes) ? git.changes.slice(0, 6) : [];
    const latest = git.latest_commit || {};
    card.innerHTML = `
      <div class="operator-detail-row">
        <span class="operator-detail-row__key">Branch</span>
        <span class="operator-detail-row__val operator-detail-row__val--mono">${_esc(git.branch || '—')}</span>
      </div>
      <div class="operator-detail-row">
        <span class="operator-detail-row__key">Latest commit</span>
        <span class="operator-detail-row__val">${_esc(latest.sha || '—')} ${_esc(latest.relative_time || '')}</span>
      </div>
      <div class="operator-detail-row">
        <span class="operator-detail-row__key">Subject</span>
        <span class="operator-detail-row__val">${_esc(latest.subject || '—')}</span>
      </div>
      <div class="operator-detail-row">
        <span class="operator-detail-row__key">Changed files</span>
        <span class="operator-detail-row__val">${_esc(git.change_count ?? 0)}</span>
      </div>
      ${changes.length ? `<div class="operator-item__body">${_esc(changes.join('\n'))}</div>` : '<div class="operator-item__body">No pending file changes.</div>'}
    `;
  }

  _showOperatorToast(message, kind = 'info') {
    const toast = document.getElementById('operator-toast');
    if (!toast) return;
    toast.hidden = false;
    toast.dataset.kind = kind;
    toast.textContent = message;
    clearTimeout(this._operatorToastTimer);
    this._operatorToastTimer = setTimeout(() => {
      toast.hidden = true;
    }, 3500);
  }

  // ── Render helpers ─────────────────────────────────────

  /** @param {object} stats — system resources */
  _renderSystemStats(stats) {
    _setGauge('gauge-cpu-fill', 'gauge-cpu-val', stats.cpu_percent ?? 0);
    _setGauge('gauge-ram-fill', 'gauge-ram-val', stats.ram_percent ?? 0);
    const gpuPct = stats.gpu_vram_total_mb
      ? Math.round((stats.gpu_vram_used_mb / stats.gpu_vram_total_mb) * 100)
      : (stats.gpu_percent ?? 0);
    _setGauge('gauge-gpu-fill', 'gauge-gpu-val', gpuPct);
    _setText('stat-ram-used', stats.ram_used_gb != null ? `${stats.ram_used_gb} GB` : '—');
    _setText('stat-vram-used', stats.gpu_vram_used_mb ? `${stats.gpu_vram_used_mb} MB` : '—');
  }

  /** @param {Array} events — world sim events */
  _renderWorldEvents(events) {
    const el = document.getElementById('world-events-feed');
    if (!el) return;
    if (!events.length) {
      el.innerHTML = '<div class="feed-placeholder">No world events yet.</div>';
      return;
    }
    el.innerHTML = events.map(e => `
      <article class="news-item news-item--classified" role="article">
        <div class="news-item__header">
          <span class="news-item__tag">CLASSIFIED</span>
          <span class="news-item__time">${_relTime(e.timestamp || e.ts)}</span>
        </div>
        <div class="news-item__title">${_esc(e.headline || e.title || e.name || 'Unknown Event')}</div>
        ${e.description || e.body ? `<div class="news-item__summary">${_esc(e.description || e.body)}</div>` : ''}
      </article>`).join('');
  }

  /** @param {Array} scenes */
  _renderSceneHealth(scenes) {
    const el = document.getElementById('scene-health-grid');
    if (!el) return;
    if (!scenes.length) {
      el.innerHTML = '<div class="feed-placeholder">No scene data.</div>';
      return;
    }
    el.innerHTML = scenes.map(s => {
      const cls = s.status === 'online' ? 'online' : s.status === 'offline' ? 'offline' : 'unknown';
      const lat = s.latency_ms != null ? `${s.latency_ms}ms` : '';
      return `
        <div class="scene-card scene-card--${cls}" role="listitem">
          <div class="scene-card__dot"></div>
          <div class="scene-card__info">
            <span class="scene-card__name">${_esc(s.display || s.name)}</span>
            <span class="scene-card__port">:${s.port}</span>
          </div>
          ${lat ? `<span class="scene-card__latency">${lat}</span>` : ''}
        </div>`;
    }).join('');
  }

  _renderNewsFeed(containerId, items, defaultTag = 'NEWS') {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!items.length) {
      el.innerHTML = '<div class="feed-placeholder">No articles.</div>';
      return;
    }
    el.innerHTML = items.map((item, idx) => {
      const title   = item.title || item.headline || 'Untitled';
      const summary = item.summary || item.description || '';
      const tag     = item.category || item.source || defaultTag;
      const ts      = item.published_at || item.created_at || item.ts || '';
      const itemId  = item.id || item.item_id || String(idx);
      const content = item.content || summary;
      return `
        <article class="news-item" role="article">
          <div class="news-item__header">
            <span class="news-item__tag">${_esc(String(tag).toUpperCase().slice(0, 12))}</span>
            <span class="news-item__time">${_relTime(ts)}</span>
            <span class="news-item__ratings">
              <button class="news-rating-btn news-rating-btn--up"
                data-item-id="${_esc(itemId)}"
                data-title="${_esc(title)}"
                data-content="${_esc(content.slice(0, 400))}"
                data-category="${_esc(tag)}"
                data-source="feed"
                title="Relevant — use as training signal"
                aria-label="Thumbs up">👍</button>
              <button class="news-rating-btn news-rating-btn--down"
                data-item-id="${_esc(itemId)}"
                data-title="${_esc(title)}"
                data-content="${_esc(content.slice(0, 400))}"
                data-category="${_esc(tag)}"
                data-source="feed"
                title="Not relevant — negative training signal"
                aria-label="Thumbs down">👎</button>
            </span>
          </div>
          <div class="news-item__title">${_esc(title)}</div>
          ${summary ? `<div class="news-item__summary">${_esc(summary)}</div>` : ''}
        </article>`;
    }).join('');

    // Wire rating buttons
    el.querySelectorAll('.news-rating-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const rating = btn.classList.contains('news-rating-btn--up') ? 1 : -1;
        this._rateNewsItem(
          btn.dataset.itemId,
          btn.dataset.title,
          btn.dataset.content,
          btn.dataset.category,
          rating,
          btn.dataset.source || 'feed',
          btn,
        );
      });
    });
  }

  /** POST a rating to /api/news/rate and give visual feedback. */
  _rateNewsItem(itemId, title, content, category, rating, source, btn) {
    fetch('/api/news/rate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, title, content, category, rating, source }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.status === 'ok') {
          // Flash the article container
          const article = btn ? btn.closest('article, .news-item') : null;
          if (article) {
            article.classList.add(rating === 1 ? 'news-item--rated-up' : 'news-item--rated-down');
            setTimeout(() => article.classList.remove('news-item--rated-up', 'news-item--rated-down'), 1200);
          }
          // Lock both buttons briefly
          if (btn) {
            const parent = btn.closest('.news-item__ratings');
            if (parent) parent.querySelectorAll('.news-rating-btn').forEach(b => {
              b.disabled = true;
              setTimeout(() => { b.disabled = false; }, 3000);
            });
          }
          // Update stats display
          this._refreshRatingStats();
        }
      })
      .catch(() => {});
  }

  /** Pull rating stats and update the HUD badge. */
  _refreshRatingStats() {
    fetch('/api/news/ratings/stats')
      .then(r => r.json())
      .then(data => {
        const el = document.getElementById('news-rating-stats');
        if (el && data.status === 'ok') {
          el.textContent = `👍 ${data.relevant}  👎 ${data.not_relevant}  total ${data.total}`;
        }
      })
      .catch(() => {});
  }

  /** Show a compact rating toast for ticker items. */
  _showRatingToast(item) {
    // Remove any existing toast
    const existing = document.getElementById('cs-rating-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'cs-rating-toast';
    toast.className = 'cs-rating-toast';
    toast.innerHTML = `
      <div class="cs-rating-toast__title">${_esc(item.title.slice(0, 80))}</div>
      <div class="cs-rating-toast__actions">
        <button class="news-rating-btn news-rating-btn--up" title="Relevant">👍 Relevant</button>
        <button class="news-rating-btn news-rating-btn--down" title="Not relevant">👎 Skip</button>
        <button class="cs-rating-toast__close" title="Dismiss">✕</button>
      </div>`;
    document.body.appendChild(toast);

    const close = () => toast.remove();
    toast.querySelector('.cs-rating-toast__close').addEventListener('click', close);

    toast.querySelector('.news-rating-btn--up').addEventListener('click', () => {
      this._rateNewsItem(item.item_id || '', item.title, item.content || '', item.category || 'news', 1, 'ticker', null);
      toast.classList.add('cs-rating-toast--rated');
      setTimeout(close, 800);
    });
    toast.querySelector('.news-rating-btn--down').addEventListener('click', () => {
      this._rateNewsItem(item.item_id || '', item.title, item.content || '', item.category || 'news', -1, 'ticker', null);
      toast.classList.add('cs-rating-toast--rated');
      setTimeout(close, 800);
    });

    // Auto-dismiss after 6s
    const autoClose = setTimeout(close, 6000);
    toast.addEventListener('mouseenter', () => clearTimeout(autoClose));
  }

  // ── Economy & status ───────────────────────────────────

  _updateStatusLights(data) {
    _setLight('status-nexus',    data.nexus?.available);
    _setLight('status-lmstudio', data.lmstudio?.available);
    _setLight('status-scheduler', data.scheduler?.running);
    // TTS: assume online if we can reach the server
    _setLight('status-tts', true);
    // Model name
    if (data.lmstudio?.models?.length) {
      _setText('stat-model', data.lmstudio.models[0]);
    }
  }

  _updateEconomy(data) {
    if (data.nexus) {
      _setText('econ-nexus-entries', data.nexus.entries ?? '—');
      _setText('econ-qa-pairs', data.nexus.qa_pairs ?? '—');
      _setText('stat-nexus-entries', data.nexus.entries ?? '—');
    }
    if (data.lmstudio) {
      _setText('econ-models', data.lmstudio.models?.length ?? '—');
    }
    if (data.scheduler) {
      _setText('econ-tasks', data.scheduler.task_count ?? '—');
    }
  }

  _updateConsequences(data) {
    if (data.world_time) _setText('world-time', data.world_time);
    if (data.active_events != null) _setText('active-events', data.active_events);
  }

  _appendActivity(item) {
    const el = document.getElementById('activity-log');
    if (!el) return;
    const placeholder = el.querySelector('.feed-placeholder');
    if (placeholder) placeholder.remove();
    const entry = document.createElement('div');
    entry.className = 'activity-entry';
    entry.innerHTML = `
      <span class="activity-entry__cat">${_esc((item.cat || 'sys').toUpperCase())}</span>
      <span>${_esc(item.msg || item.message || '')}</span>`;
    el.insertBefore(entry, el.firstChild);
    // Keep max 20 entries
    while (el.children.length > 20) el.removeChild(el.lastChild);
  }

  _onWorldEvent(evt) {
    // Surface world events in the Intel Hub activity log
    const typeLabels = {
      economy: '💹 ECONOMY', faction: '⚔️ FACTION', npc: '🧍 NPC',
      crime: '🚨 CRIME', weather: '🌩️ WEATHER', political: '🏛️ POLITICAL',
      social: '👥 SOCIAL', disaster: '💥 DISASTER', rumour: '📢 RUMOUR', combat: '⚔️ COMBAT',
    };
    const label = typeLabels[evt.event_type] || evt.event_type.toUpperCase();
    const summary = evt.data?.summary || evt.data?.description || evt.event_type;
    this._appendActivity({ cat: label, msg: `[${evt.source}] ${summary}` });
    // Inject into bottom ticker (live feed)
    if (typeof window._tickerInjectWorldEvent === 'function') {
      window._tickerInjectWorldEvent(evt);
    }
    // Also update world events panel if visible
    const panel = document.getElementById('world-events-feed');
    if (panel) {
      const row = document.createElement('div');
      row.className = 'world-event-row';
      row.innerHTML = `<span class="we-type">${_esc(label)}</span> <span>${_esc(summary)}</span>`;
      panel.insertBefore(row, panel.firstChild);
      while (panel.children.length > 30) panel.removeChild(panel.lastChild);
    }
  }

  // ── Aria ───────────────────────────────────────────────

  /** Ask Aria a question — called by scene skill or input form */
  async askAria(question) {
    if (!question.trim()) return;
    this._setAriaStatus('thinking');
    this._appendAriaMsg('user', question);
    try {
      const data = await _api('/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: question }),
      });
      const reply = data.response || data.text || data.reply || 'No response.';
      this._appendAriaMsg('aria', reply);
      this._setAriaStatus('talking');
      setTimeout(() => this._setAriaStatus('idle'), 2000);
    } catch (e) {
      this._appendAriaMsg('aria', `[Error: ${e.message}]`);
      this._setAriaStatus('idle');
    }
  }

  /** Send message from the input box */
  sendMessage() {
    const input = document.getElementById('aria-input');
    if (!input) return false;
    const text = input.value.trim();
    if (!text) return false;
    input.value = '';
    this.askAria(text);
    return false; // prevent form submit
  }

  _appendAriaMsg(who, text) {
    const history = document.getElementById('aria-chat-history');
    if (!history) return;
    const msg = document.createElement('div');
    msg.className = `aria-msg aria-msg--${who}`;
    msg.innerHTML = `
      <div class="aria-msg__who">${who === 'aria' ? 'ARIA ▸' : 'YOU ▸'}</div>
      <div>${_esc(text)}</div>`;
    history.appendChild(msg);
    history.scrollTop = history.scrollHeight;
  }

  _setAriaStatus(status) {
    const ring = document.getElementById('aria-ring');
    const label = document.getElementById('aria-status-text');
    if (ring) ring.dataset.status = status;
    if (label) label.textContent = status.toUpperCase();
  }

  // ── Polling ────────────────────────────────────────────

  // ── SSE Notifications ──────────────────────────────────────────────────
  _connectNotifications() {
    const container = document.getElementById('notification-container');
    if (!container) return;
    const port = window.SCENE_PORT || 5580;
    const url = `http://localhost:${port}/api/notifications/stream`;
    let es;
    const connect = () => {
      es = new EventSource(url);
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'connected') return;
          if (data.type === 'notification') this._showNotificationToast(data, container);
        } catch (_) { /* ignore parse errors */ }
      };
      es.onerror = () => {
        es.close();
        setTimeout(connect, 10000);
      };
    };
    connect();
    this._notifSource = es;
  }

  _showNotificationToast(data, container) {
    const ICONS = { info: 'ℹ️', success: '✅', warning: '⚠️', error: '❌' };
    const severity = data.severity || 'info';
    const toast = document.createElement('div');
    toast.className = `notification-toast notification-toast--${severity}`;
    toast.innerHTML = `
      <span class="notification-toast__icon">${ICONS[severity] || ICONS.info}</span>
      <div class="notification-toast__body">
        <div class="notification-toast__title">${this._esc(data.title || data.category || 'System')}</div>
        <div class="notification-toast__message">${this._esc(data.message || '')}</div>
      </div>
      <span class="notification-toast__time">${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span>`;
    container.prepend(toast);
    toast.addEventListener('click', () => {
      toast.classList.add('is-dismissing');
      setTimeout(() => toast.remove(), 300);
    });
    setTimeout(() => {
      if (toast.parentNode) {
        toast.classList.add('is-dismissing');
        setTimeout(() => toast.remove(), 300);
      }
    }, 6000);
    while (container.children.length > 5) container.removeChild(container.lastChild);
  }

  _pollLoop() {
    this._pollTimer = setInterval(() => {
      this._loadOverview();
      this._pollCount += 1;
      if (this._pollCount % 2 === 0) {
        this._loadOperator();
      }
    }, 8000);
  }

  destroy() {
    if (this._pollTimer) clearInterval(this._pollTimer);
    if (this._clockTimer) clearInterval(this._clockTimer);
    if (this._notifSource) this._notifSource.close();
    if (this.particles) this.particles.stop();
  }
}

// ──────────────────────────────────────────────────────────
// UTILITY HELPERS
// ──────────────────────────────────────────────────────────

async function _api(path, opts = {}) {
  const defaults = { headers: { 'Content-Type': 'application/json' } };
  if (opts.body instanceof FormData) delete defaults.headers['Content-Type'];
  const res = await fetch(path, { ...defaults, ...opts });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}

async function _safeApi(path, fallback = {}) {
  try { return await _api(path); } catch (_) { return fallback; }
}

function _setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? '—';
}

function _setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function _setLight(rowId, online) {
  const row = document.getElementById(rowId);
  if (!row) return;
  const dot = row.querySelector('.status-light');
  if (!dot) return;
  dot.className = 'status-light';
  if (online === true)  dot.classList.add('status-light--online');
  else if (online === false) dot.classList.add('status-light--offline');
  else dot.classList.add('status-light--checking');
}

function _setGauge(fillId, valId, pct) {
  const fill = document.getElementById(fillId);
  const val  = document.getElementById(valId);
  const circ = 2 * Math.PI * 22; // r=22
  if (fill) fill.setAttribute('stroke-dasharray', `${(pct / 100) * circ} ${circ}`);
  if (val)  val.textContent = `${Math.round(pct)}%`;
}

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _relTime(ts) {
  if (!ts) return '';
  try {
    const diff = (Date.now() - new Date(ts)) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return new Date(ts).toLocaleDateString();
  } catch (_) { return ts; }
}

// ──── Benchmark Dashboard ────
(function initBenchmarks() {
  const grid = document.getElementById('benchmark-grid');
  if (!grid) return;

  const refreshBtn = document.getElementById('benchmark-refresh-btn');
  const detailPanel = document.getElementById('benchmark-detail');
  const detailName = document.getElementById('benchmark-detail-name');
  const runBtn = document.getElementById('benchmark-run-btn');
  let selectedWorkflow = null;

  function scoreClass(score) {
    if (score === null || score === undefined) return 'benchmark-score--none';
    if (score >= 0.8) return 'benchmark-score--high';
    if (score >= 0.6) return 'benchmark-score--mid';
    return 'benchmark-score--low';
  }

  function sparklineSVG(trend) {
    if (!trend || trend.length < 2) return '';
    const scores = trend.map(t => t.mean_score || 0);
    const min = Math.min(...scores);
    const max = Math.max(...scores) || 1;
    const w = 80, h = 24;
    const points = scores.map((s, i) => {
      const x = (i / (scores.length - 1)) * w;
      const y = h - ((s - min) / (max - min || 1)) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `<svg class="benchmark-sparkline" viewBox="0 0 ${w} ${h}">
      <polyline fill="none" stroke="var(--cs-scene-accent,#06b6d4)" stroke-width="1.5" points="${points}"/>
    </svg>`;
  }

  function renderCard(wf) {
    const score = wf.latest_score;
    const cls = scoreClass(score);
    const displayScore = score !== null && score !== undefined ? (score * 100).toFixed(0) : '—';
    return `<div class="benchmark-card" data-workflow="${wf.name}" onclick="selectWorkflow('${wf.name}')">
      <div class="benchmark-card-name">${wf.name.replace(/_/g, ' ')}</div>
      <div class="benchmark-score ${cls}">${displayScore}${score !== null ? '%' : ''}</div>
      ${sparklineSVG(wf.trend)}
    </div>`;
  }

  window.selectWorkflow = function(name) {
    selectedWorkflow = name;
    if (detailName) detailName.textContent = name.replace(/_/g, ' ').toUpperCase();
    if (detailPanel) detailPanel.style.display = 'block';
  };

  function loadBenchmarks() {
    grid.innerHTML = '<div class="benchmark-loading">Loading...</div>';
    fetch('/api/benchmark/workflows')
      .then(r => r.json())
      .then(data => {
        if (!data.workflows || data.workflows.length === 0) {
          grid.innerHTML = '<div class="benchmark-loading">No benchmark data. Run a benchmark to see results.</div>';
          return;
        }
        grid.innerHTML = data.workflows.map(renderCard).join('');
      })
      .catch(() => {
        grid.innerHTML = '<div class="benchmark-loading">Benchmark service unavailable.</div>';
      });
  }

  if (refreshBtn) refreshBtn.addEventListener('click', loadBenchmarks);

  if (runBtn) {
    runBtn.addEventListener('click', () => {
      if (!selectedWorkflow) return;
      runBtn.textContent = '⏳ Running...';
      runBtn.disabled = true;
      fetch('/api/benchmark/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({workflow: selectedWorkflow}),
      })
        .then(r => r.json())
        .then(() => {
          setTimeout(() => {
            runBtn.textContent = '▶ RUN NOW';
            runBtn.disabled = false;
            loadBenchmarks();
          }, 2000);
        })
        .catch(() => {
          runBtn.textContent = '▶ RUN NOW';
          runBtn.disabled = false;
        });
    });
  }

  loadBenchmarks();
  setInterval(loadBenchmarks, 10 * 60 * 1000); // auto-refresh every 10 min
})();

// ──────────────────────────────────────────────────────────
// BOOT
// ──────────────────────────────────────────────────────────

const briefingRoom = new BriefingRoomScene();
window.briefingRoom = briefingRoom;

document.addEventListener('DOMContentLoaded', () => {
  briefingRoom.init();
});

// ──────────────────────────────────────────────────────────
// CITY PULSE PANEL
// ──────────────────────────────────────────────────────────
(function initCityPulse() {
  const feedEl   = document.getElementById('city-pulse-feed');
  const filters  = document.getElementById('city-pulse-filters');
  const refreshB = document.getElementById('cp-refresh-btn');
  if (!feedEl) return;

  let _currentCat = '';
  const _MAX = 50;
  const _liveBuffer = [];

  const CAT_ICONS = {
    npc: '🧍', faction: '⚔️', economy: '💹',
    hacker: '💻', world: '🌐', system: '⚙️',
  };

  function _esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _badge(cat) {
    const cls = ['npc','faction','economy','hacker','world'].includes(cat) ? `cp-event__badge--${cat}` : '';
    const icon = CAT_ICONS[cat] || '📡';
    return `<span class="cp-event__badge ${cls}">${icon} ${_esc((cat||'unknown').toUpperCase())}</span>`;
  }

  function _renderEvent(e) {
    const cat  = (e.category || e.type || '').toLowerCase();
    const ts   = e.timestamp || e.created_at || '';
    const title = e.title || e.event_type || '';
    const desc  = e.description || e.body || '';
    const scene = e.scene || '';
    return `<div class="cp-event" data-cat="${_esc(cat)}">
      <span class="cp-event__time">${_esc(ts.slice(11,16)||ts.slice(0,5))}</span>
      ${_badge(cat)}
      <div class="cp-event__body">
        <div class="cp-event__title">${_esc(title)}</div>
        ${desc ? `<div class="cp-event__desc">${_esc(desc)}</div>` : ''}
        ${scene ? `<div class="cp-event__scene-tag">[ ${_esc(scene.toUpperCase())} ]</div>` : ''}
      </div>
    </div>`;
  }

  function _render(events) {
    if (!events || !events.length) {
      feedEl.innerHTML = '<div class="feed-placeholder">No city signals detected.</div>';
      return;
    }
    feedEl.innerHTML = events.slice(0, _MAX).map(_renderEvent).join('');
  }

  async function _load(cat) {
    _currentCat = cat;
    try {
      const url = `/api/world/events?limit=${_MAX}${cat ? '&category=' + encodeURIComponent(cat) : ''}`;
      const data = await fetch(url).then(r => r.json());
      const events = data.events || [];
      // Merge with live buffer, sort newest first
      const combined = [..._liveBuffer, ...events];
      const seen = new Set();
      const deduped = combined.filter(e => {
        const key = e.id || (e.title + e.created_at);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      deduped.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
      _render(deduped);
    } catch (_) {
      feedEl.innerHTML = '<div class="feed-placeholder">Feed unavailable.</div>';
    }
  }

  // Filter buttons
  if (filters) {
    filters.addEventListener('click', e => {
      const btn = e.target.closest('.cp-filter-btn');
      if (!btn) return;
      filters.querySelectorAll('.cp-filter-btn').forEach(b => b.classList.remove('cp-filter-btn--active'));
      btn.classList.add('cp-filter-btn--active');
      _load(btn.dataset.cat || '');
    });
  }

  if (refreshB) refreshB.addEventListener('click', () => _load(_currentCat));

  // Socket.IO live injection
  if (window.io) {
    const sock = window.io(`http://localhost:${window.SCENE_PORT || 5580}`, { transports: ['websocket', 'polling'] });
    sock.on('city_pulse', evt => {
      _liveBuffer.unshift(evt);
      if (_liveBuffer.length > _MAX) _liveBuffer.pop();
      const cat = (evt.category || evt.type || '').toLowerCase();
      if (!_currentCat || _currentCat === cat) {
        const entry = document.createElement('div');
        entry.innerHTML = _renderEvent(evt);
        const child = entry.firstElementChild;
        if (child) {
          feedEl.prepend(child);
          // Keep at most _MAX items in DOM
          while (feedEl.children.length > _MAX) feedEl.removeChild(feedEl.lastChild);
        }
      }
    });
  }

  // Initial load + auto-refresh 30s
  _load('');
  setInterval(() => _load(_currentCat), 30000);
})();
