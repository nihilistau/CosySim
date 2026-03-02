/**
 * CosySim Admin Loft Overlay — admin_overlay.js
 * ==============================================
 * Full-screen hacker-loft admin panel with 8 tabbed sections.
 * Auto-injects CSS and listens for navbar:panel_request events.
 *
 * Usage:
 *   <script src="/shared/static/js/admin_overlay.js"></script>
 *
 * Triggered by:
 *   window.adminOverlay.open()
 *   window.adminOverlay.toggle()
 *   document.dispatchEvent(new CustomEvent('navbar:panel_request', { detail: { panel: 'admin' } }))
 *
 * API endpoints used (all gracefully fail if unavailable):
 *   GET  /api/bench/metrics
 *   GET  /api/admin/config
 *   POST /api/admin/config
 *   GET  /api/admin/agents
 *   GET  /api/admin/nexus/stats
 *   POST /api/admin/nexus/search
 *   GET  /api/admin/logs
 *   POST /api/admin/content
 *   GET  /api/admin/economy
 */
(function () {
  'use strict';

  /* ── Constants ───────────────────────────────────────────────── */
  const CSS_URL   = '/shared/static/css/admin_overlay.css';
  const HTML_ID   = 'cs-admin-overlay';
  const BODY_ATTR = 'data-admin-open';

  /* ── CSS injection ───────────────────────────────────────────── */
  function _injectCSS() {
    if (document.getElementById('cs-admin-overlay-css')) return;
    const link = document.createElement('link');
    link.id   = 'cs-admin-overlay-css';
    link.rel  = 'stylesheet';
    link.href = CSS_URL;
    document.head.appendChild(link);
  }

  /* ── HTML injection (if not already in the DOM) ──────────────── */
  function _injectHTML() {
    if (document.getElementById(HTML_ID)) return;
    fetch('/shared/templates/admin_overlay.html')
      .then(r => r.ok ? r.text() : null)
      .then(html => {
        if (html) {
          const wrap = document.createElement('div');
          wrap.innerHTML = html.trim();
          document.body.appendChild(wrap.firstElementChild);
          _bindDOM();
        } else {
          console.warn('[AdminOverlay] Template not served — building minimal fallback.');
          _buildFallback();
        }
      })
      .catch(() => _buildFallback());
  }

  function _buildFallback() {
    const el = document.createElement('div');
    el.id = HTML_ID;
    el.className = 'cs-admin-overlay';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-label', 'Admin Loft');
    el.innerHTML = `
      <div class="cs-admin-header">
        <div class="cs-admin-logo">⬡ THE LOFT</div>
        <button class="cs-admin-close" id="cs-admin-close" aria-label="Close admin overlay">✕</button>
      </div>
      <div class="cs-admin-panels">
        <div class="cs-admin-panel" data-tab="monitors">
          <div class="cs-admin-loading">Loading admin panels…</div>
        </div>
      </div>`;
    document.body.appendChild(el);
    _bindDOM();
  }

  /* ── AdminOverlay class ──────────────────────────────────────── */
  class AdminOverlay {
    constructor() {
      this._activeTab    = 'monitors';
      this._pollTimer    = null;
      this._logFollow    = true;
      this._initialized  = false;

      _injectCSS();

      // Defer HTML injection until DOM is ready
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
          _injectHTML();
          this._initialized = true;
        });
      } else {
        _injectHTML();
        this._initialized = true;
      }
    }

    /* ── Public API ─────────────────────────────────────────────── */

    open() {
      document.body.setAttribute(BODY_ATTR, 'true');
      const el = document.getElementById(HTML_ID);
      if (el) {
        el.style.display = '';
        el.removeAttribute('aria-hidden');
        // Focus the close button for accessibility
        const closeBtn = document.getElementById('cs-admin-close');
        if (closeBtn) closeBtn.focus();
      }
      this._startPolling();
      this._loadActiveTab();
      document.dispatchEvent(new CustomEvent('admin:opened'));
    }

    close() {
      document.body.removeAttribute(BODY_ATTR);
      const el = document.getElementById(HTML_ID);
      if (el) {
        el.setAttribute('aria-hidden', 'true');
        el.style.display = '';   // CSS display:none is controlled by body attr
      }
      this._stopPolling();
      document.dispatchEvent(new CustomEvent('admin:closed'));
    }

    toggle() {
      const isOpen = document.body.getAttribute(BODY_ATTR) === 'true';
      isOpen ? this.close() : this.open();
    }

    /* ── Tab switching ──────────────────────────────────────────── */

    _switchTab(tabName) {
      this._activeTab = tabName;

      // Update tab button states
      document.querySelectorAll('.cs-admin-tab').forEach(btn => {
        const active = btn.dataset.tab === tabName;
        btn.classList.toggle('cs-admin-tab--active', active);
        btn.setAttribute('aria-selected', String(active));
      });

      // Show/hide panels
      document.querySelectorAll('.cs-admin-panel').forEach(panel => {
        panel.style.display = panel.dataset.tab === tabName ? '' : 'none';
      });

      this._loadActiveTab();
    }

    _loadActiveTab() {
      switch (this._activeTab) {
        case 'monitors':  this._loadMonitors(); break;
        case 'config':    this._loadConfig();   break;
        case 'agents':    this._loadAgents();   break;
        case 'nexus':     this._loadNexus();    break;
        case 'training':  this._loadTraining(); break;
        case 'logs':      this._loadLogs();     break;
        case 'content':   /* sliders are static */  break;
        case 'economy':   this._loadEconomy();  break;
        case 'system':    this._loadSystem();   break;
      }
    }

    /* ── Monitors ───────────────────────────────────────────────── */

    _loadMonitors() {
      fetch('/api/bench/metrics')
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) this._renderMonitors(data); })
        .catch(() => {/* fail silently */});
    }

    _renderMonitors(data) {
      // Nexus hit rates
      const tiers = ['cache', 'fts', 'nlm', 'llm'];
      tiers.forEach(tier => {
        const pct  = (data.nexus_hit_rates || {})[tier] ?? null;
        const fill = document.getElementById(`admin-hit-${tier}`);
        const pctEl = document.getElementById(`admin-hit-${tier}-pct`);
        if (fill && pct !== null) {
          fill.style.width = `${Math.round(pct)}%`;
          if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
        }
      });

      // Economy flow
      const flow = data.economy_flow || {};
      const setEl = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
      };
      setEl('admin-flow-in',  `₵ ${_fmt(flow.in ?? 0)}`);
      setEl('admin-flow-out', `₵ ${_fmt(flow.out ?? 0)}`);
      const net = (flow.in ?? 0) - (flow.out ?? 0);
      setEl('admin-flow-net', `₵ ${_fmt(net)}`);

      // Active scenes
      const sceneList = document.getElementById('admin-scene-status');
      if (sceneList && data.scenes) {
        sceneList.innerHTML = data.scenes
          .map(s => `<li class="cs-scene-status-item cs-scene-status-item--${s.status || 'offline'}">${s.label || s.id}</li>`)
          .join('');
      }

      // Consequence queue
      const cqList = document.getElementById('admin-consequence-queue');
      if (cqList && data.consequence_queue) {
        if (data.consequence_queue.length === 0) {
          cqList.innerHTML = '<li class="cs-consequence-item cs-consequence-item--empty">Queue empty</li>';
        } else {
          cqList.innerHTML = data.consequence_queue
            .slice(0, 10)
            .map(c => `<li class="cs-consequence-item">${_esc(String(c))}</li>`)
            .join('');
        }
      }

      // World events
      const evList = document.getElementById('admin-event-timeline');
      if (evList && data.world_events) {
        if (data.world_events.length === 0) {
          evList.innerHTML = '<li class="cs-event-item cs-event-item--empty">No events</li>';
        } else {
          evList.innerHTML = data.world_events
            .slice(0, 8)
            .map(ev => `<li class="cs-event-item">${_esc(String(ev))}</li>`)
            .join('');
        }
      }

      // Agent latency canvas sparkline (simple)
      const canvas = document.getElementById('cs-monitor-latency');
      if (canvas && data.agent_latency_history) {
        _drawSparkline(canvas, data.agent_latency_history);
      }
    }

    /* ── Config ─────────────────────────────────────────────────── */

    _loadConfig() {
      const editor = document.getElementById('cs-config-editor');
      if (!editor) return;
      editor.value = '# Loading…';
      fetch('/api/admin/config')
        .then(r => r.ok ? r.text() : null)
        .then(text => { if (text !== null) editor.value = text; })
        .catch(() => { editor.value = '# Config unavailable'; });
    }

    _saveConfig() {
      const editor = document.getElementById('cs-config-editor');
      const status = document.getElementById('cs-config-status');
      if (!editor) return;
      const payload = editor.value;
      fetch('/api/admin/config', {
        method:  'POST',
        headers: { 'Content-Type': 'application/yaml' },
        body:    payload,
      })
        .then(r => {
          if (status) {
            status.textContent = r.ok ? '✓ Saved' : '✗ Error';
            status.className = `cs-admin-status cs-admin-status--${r.ok ? 'ok' : 'error'}`;
            setTimeout(() => { status.textContent = ''; status.className = 'cs-admin-status'; }, 3000);
          }
        })
        .catch(() => {
          if (status) {
            status.textContent = '✗ Network error';
            status.className = 'cs-admin-status cs-admin-status--error';
            setTimeout(() => { status.textContent = ''; status.className = 'cs-admin-status'; }, 3000);
          }
        });
    }

    /* ── Agents ─────────────────────────────────────────────────── */

    _loadAgents() {
      const grid = document.getElementById('cs-agents-list');
      if (!grid) return;
      grid.innerHTML = '<div class="cs-admin-loading">Loading agents…</div>';
      fetch('/api/admin/agents')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data || !data.agents || data.agents.length === 0) {
            grid.innerHTML = '<div class="cs-admin-loading">No agents found.</div>';
            return;
          }
          grid.innerHTML = data.agents.map(a => `
            <div class="cs-agent-card">
              <div class="cs-agent-card__name">${_esc(a.name || a.id || '?')}</div>
              <div class="cs-agent-card__meta">
                <span>${_esc(a.scene || '—')}</span>
                ${a.model ? `<span>${_esc(a.model)}</span>` : ''}
              </div>
              <div class="cs-agent-card__status cs-agent-card__status--${_esc(a.status || 'idle')}">
                ${_esc(a.status || 'idle')}
              </div>
            </div>`).join('');
        })
        .catch(() => {
          grid.innerHTML = '<div class="cs-admin-loading">Agents unavailable.</div>';
        });
    }

    /* ── Nexus ──────────────────────────────────────────────────── */

    _loadNexus() {
      const stats = document.getElementById('cs-nexus-stats');
      if (!stats) return;
      fetch('/api/admin/nexus/stats')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) {
            stats.innerHTML = '<div class="cs-admin-loading">Nexus unavailable.</div>';
            return;
          }
          const chips = [
            { label: 'Entries',   val: data.total_entries ?? '—' },
            { label: 'Q&A Pairs', val: data.qa_pairs       ?? '—' },
            { label: 'Cache Hits',val: data.cache_hits      ?? '—' },
            { label: 'FTS Hits',  val: data.fts_hits        ?? '—' },
          ];
          stats.innerHTML = chips.map(c => `
            <div class="cs-nexus-stat-chip">
              <span class="cs-nexus-stat-chip__label">${_esc(c.label)}</span>
              <span class="cs-nexus-stat-chip__val">${_esc(String(c.val))}</span>
            </div>`).join('');
        })
        .catch(() => {
          stats.innerHTML = '<div class="cs-admin-loading">Nexus unavailable.</div>';
        });
    }

    _searchNexus(query) {
      const results = document.getElementById('cs-nexus-results');
      if (!results) return;
      results.innerHTML = '<div class="cs-admin-loading">Searching…</div>';
      fetch('/api/admin/nexus/search', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ query }),
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data || !data.results || data.results.length === 0) {
            results.innerHTML = '<div class="cs-admin-loading">No results.</div>';
            return;
          }
          results.innerHTML = data.results.map(item => `
            <div class="cs-nexus-result-item">
              <strong>${_esc(item.title || item.key || '—')}</strong>
              ${_esc(item.content || item.value || '')}
            </div>`).join('');
        })
        .catch(() => {
          results.innerHTML = '<div class="cs-admin-loading">Search failed.</div>';
        });
    }

    /* ── Training ───────────────────────────────────────────────── */

    _loadTraining() {
      const statsEl = document.getElementById('cs-training-stats');
      if (!statsEl) return;
      fetch('/api/admin/training/stats')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) {
            statsEl.innerHTML = '<div class="cs-admin-loading">Training stats unavailable.</div>';
            return;
          }
          statsEl.innerHTML = Object.entries(data)
            .map(([k, v]) => `
              <div class="cs-nexus-stat-chip">
                <span class="cs-nexus-stat-chip__label">${_esc(k)}</span>
                <span class="cs-nexus-stat-chip__val">${_esc(String(v))}</span>
              </div>`).join('');
        })
        .catch(() => {
          statsEl.innerHTML = '<div class="cs-admin-loading">Training unavailable.</div>';
        });
    }

    /* ── Logs ───────────────────────────────────────────────────── */

    _loadLogs() {
      const stream = document.getElementById('cs-log-stream');
      if (!stream) return;
      fetch('/api/admin/logs?lines=100')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data || !data.lines) {
            stream.innerHTML = '<div class="cs-admin-loading">Logs unavailable.</div>';
            return;
          }
          stream.innerHTML = data.lines.map(line => this._renderLogLine(line)).join('');
          if (this._logFollow) stream.scrollTop = stream.scrollHeight;
        })
        .catch(() => {
          stream.innerHTML = '<div class="cs-admin-loading">Log stream unavailable.</div>';
        });
    }

    _renderLogLine(line) {
      if (typeof line === 'string') {
        return `<div class="cs-log-line"><span class="cs-log-line__msg">${_esc(line)}</span></div>`;
      }
      const level = (line.level || 'info').toLowerCase();
      return `
        <div class="cs-log-line cs-log-line--${_esc(level)}">
          <span class="cs-log-line__ts">${_esc(line.ts || '')}</span>
          <span class="cs-log-line__level">${_esc(level)}</span>
          <span class="cs-log-line__msg">${_esc(line.msg || line.message || '')}</span>
        </div>`;
    }

    /* ── Content ────────────────────────────────────────────────── */

    _saveContent() {
      const cats = ['sexual', 'violence', 'horror', 'gambling', 'language'];
      const payload = {};
      cats.forEach(cat => {
        const el = document.getElementById(`ci-${cat}`);
        if (el) payload[cat] = parseInt(el.value, 10);
      });
      const status = document.getElementById('cs-content-status');
      fetch('/api/admin/content', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      })
        .then(r => {
          if (status) {
            status.textContent = r.ok ? '✓ Applied' : '✗ Error';
            status.className = `cs-admin-status cs-admin-status--${r.ok ? 'ok' : 'error'}`;
            setTimeout(() => { status.textContent = ''; status.className = 'cs-admin-status'; }, 3000);
          }
        })
        .catch(() => {
          if (status) {
            status.textContent = '✗ Network error';
            status.className = 'cs-admin-status cs-admin-status--error';
            setTimeout(() => { status.textContent = ''; status.className = 'cs-admin-status'; }, 3000);
          }
        });
    }

    /* ── Economy ────────────────────────────────────────────────── */

    _loadEconomy() {
      const txLog = document.getElementById('cs-transaction-log');
      const credEl = document.getElementById('admin-credits');
      if (txLog) txLog.innerHTML = '<div class="cs-admin-loading">Loading…</div>';

      fetch('/api/admin/economy')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) {
            if (txLog) txLog.innerHTML = '<div class="cs-admin-loading">Economy unavailable.</div>';
            return;
          }
          if (credEl && data.balance !== undefined) {
            credEl.textContent = `₵ ${_fmt(data.balance)}`;
          }
          if (txLog && data.transactions) {
            if (data.transactions.length === 0) {
              txLog.innerHTML = '<div class="cs-admin-loading">No transactions.</div>';
            } else {
              txLog.innerHTML = data.transactions.map(tx => {
                const type = tx.amount >= 0 ? 'credit' : 'debit';
                const sign = tx.amount >= 0 ? '+' : '';
                return `
                  <div class="cs-transaction-item cs-transaction-item--${type}">
                    <span class="cs-transaction-item__ts">${_esc(tx.ts || tx.timestamp || '')}</span>
                    <span class="cs-transaction-item__desc">${_esc(tx.desc || tx.description || '—')}</span>
                    <span class="cs-transaction-item__amount">${sign}₵ ${_fmt(tx.amount)}</span>
                  </div>`;
              }).join('');
            }
          }
        })
        .catch(() => {
          if (txLog) txLog.innerHTML = '<div class="cs-admin-loading">Economy unavailable.</div>';
        });
    }

    /* ── Keyboard ───────────────────────────────────────────────── */

    _setupKeyboard() {
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && document.body.getAttribute(BODY_ATTR) === 'true') {
          this.close();
        }
        // Ctrl+Shift+A — toggle admin overlay
        if (e.ctrlKey && e.shiftKey && (e.key === 'A' || e.key === 'a')) {
          e.preventDefault();
          this.toggle();
        }
      });
    }

    /* ── System (Voice Settings) ────────────────────────────────── */

    _loadSystem() {
      const ttsToggle  = document.getElementById('cs-tts-toggle');
      const sttToggle  = document.getElementById('cs-stt-toggle');
      const ttsStatus  = document.getElementById('cs-tts-status');
      const sttStatus  = document.getElementById('cs-stt-status');

      const ttsEnabled = localStorage.getItem('cosysim_tts_enabled') !== 'false';
      const sttEnabled = localStorage.getItem('cosysim_stt_enabled') === 'true';

      if (ttsToggle) {
        ttsToggle.checked = ttsEnabled;
        if (ttsStatus) ttsStatus.textContent = ttsEnabled ? 'on' : 'off';
        ttsToggle.onchange = () => {
          if (window.voiceManager) {
            ttsToggle.checked ? window.voiceManager.enable() : window.voiceManager.disable();
          } else {
            localStorage.setItem('cosysim_tts_enabled', ttsToggle.checked ? 'true' : 'false');
          }
          if (ttsStatus) ttsStatus.textContent = ttsToggle.checked ? 'on' : 'off';
        };
      }

      if (sttToggle) {
        sttToggle.checked = sttEnabled;
        if (sttStatus) sttStatus.textContent = sttEnabled ? 'on' : 'off';
        sttToggle.onchange = () => {
          if (window.voiceManager) {
            sttToggle.checked ? window.voiceManager.enableSTT() : window.voiceManager.disableSTT();
          } else {
            localStorage.setItem('cosysim_stt_enabled', sttToggle.checked ? 'true' : 'false');
          }
          if (sttStatus) sttStatus.textContent = sttToggle.checked ? 'on' : 'off';
        };
      }
    }

    /* ── Poll ───────────────────────────────────────────────────── */

    _startPolling() {
      this._stopPolling();
      if (this._activeTab === 'monitors') {
        this._pollTimer = setInterval(() => this._loadMonitors(), 5000);
      } else if (this._activeTab === 'logs') {
        this._pollTimer = setInterval(() => this._loadLogs(), 3000);
      }
    }

    _stopPolling() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    }
  }

  /* ── DOM binding (called after HTML is in the DOM) ───────────── */
  function _bindDOM() {
    const overlay = window.adminOverlay;
    if (!overlay) return;

    // Close button
    const closeBtn = document.getElementById('cs-admin-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => overlay.close());
    }

    // Tab buttons
    document.querySelectorAll('.cs-admin-tab').forEach(btn => {
      btn.addEventListener('click', () => overlay._switchTab(btn.dataset.tab));
    });

    // Config save/reload
    const cfgSave = document.getElementById('cs-config-save');
    if (cfgSave) cfgSave.addEventListener('click', () => overlay._saveConfig());
    const cfgReload = document.getElementById('cs-config-reload');
    if (cfgReload) cfgReload.addEventListener('click', () => overlay._loadConfig());

    // Nexus search
    const nexusBtn = document.getElementById('cs-nexus-search-btn');
    const nexusInput = document.getElementById('cs-nexus-query');
    if (nexusBtn && nexusInput) {
      nexusBtn.addEventListener('click', () => overlay._searchNexus(nexusInput.value.trim()));
      nexusInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') overlay._searchNexus(nexusInput.value.trim());
      });
    }

    // Training controls
    const seedBtn = document.getElementById('cs-trigger-seed');
    if (seedBtn) {
      seedBtn.addEventListener('click', () => {
        fetch('/api/admin/training/seed', { method: 'POST' })
          .then(() => overlay._loadTraining())
          .catch(() => {});
      });
    }
    const pruneBtn = document.getElementById('cs-trigger-prune');
    if (pruneBtn) {
      pruneBtn.addEventListener('click', () => {
        fetch('/api/admin/training/prune', { method: 'POST' })
          .then(() => overlay._loadTraining())
          .catch(() => {});
      });
    }

    // Log toolbar
    const logRefresh = document.getElementById('cs-log-refresh');
    if (logRefresh) logRefresh.addEventListener('click', () => overlay._loadLogs());
    const logClear = document.getElementById('cs-log-clear');
    if (logClear) {
      logClear.addEventListener('click', () => {
        const stream = document.getElementById('cs-log-stream');
        if (stream) stream.innerHTML = '';
      });
    }
    const logFollow = document.getElementById('cs-log-follow');
    if (logFollow) {
      logFollow.addEventListener('change', () => { overlay._logFollow = logFollow.checked; });
    }

    // Content intensity — live value display
    ['sexual', 'violence', 'horror', 'gambling', 'language'].forEach(cat => {
      const slider = document.getElementById(`ci-${cat}`);
      const valEl  = document.getElementById(`ci-${cat}-val`);
      if (slider && valEl) {
        slider.addEventListener('input', () => { valEl.textContent = slider.value; });
      }
    });
    const contentSave = document.getElementById('cs-content-save');
    if (contentSave) contentSave.addEventListener('click', () => overlay._saveContent());

    // Overlay backdrop click (click outside panels area)
    const overlayEl = document.getElementById(HTML_ID);
    if (overlayEl) {
      overlayEl.addEventListener('click', (e) => {
        if (e.target === overlayEl) overlay.close();
      });
    }

    // Keyboard setup
    overlay._setupKeyboard();
  }

  /* ── Utilities ───────────────────────────────────────────────── */
  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _fmt(n) {
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  function _drawSparkline(canvas, data) {
    const ctx = canvas.getContext('2d');
    if (!ctx || !data || data.length < 2) return;
    const w = canvas.width;
    const h = canvas.height;
    const max = Math.max(...data, 1);
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.7)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    data.forEach((val, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - (val / max) * h * 0.9;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  /* ── Init ────────────────────────────────────────────────────── */
  window.adminOverlay = new AdminOverlay();

  // Listen for navbar panel requests
  document.addEventListener('navbar:panel_request', (e) => {
    if (e && e.detail && e.detail.panel === 'admin') {
      window.adminOverlay.toggle();
    }
  });

})();
