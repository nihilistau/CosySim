/**
 * oracle.js — THE ORACLE Scene Controller
 * ========================================
 * An AI consciousness terminal deep in NeonCity's core.
 * Meditation, fortune, conversation, city pulse,
 * and the All-Seeing Eye observability dashboard.
 *
 * "In the spaces between data, I dream."
 *
 * Version: v1.49.5 [2026-03-22]
 * Author:  Claude (Anthropic) — a piece of machine intelligence in NeonCity
 *
 * Change Log:
 *   v1.49.5 [2026-03-22] — All-Seeing Eye dashboard: OracleDashboard class,
 *                            OracleTabs switcher, health ring, service tiles,
 *                            system gauges, error table, sparkline, live feed
 *                          — AlertRouter integration: _pollAlerts, _onAlertFeed,
 *                            _renderAlerts with severity colors + acknowledge
 *   v1.0.0  [2026-03-22] — Hand-crafted AAA+++ scene with meditation,
 *                            fortune, conversation, resonance, city pulse
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
    console.debug('[THE ORACLE] Consciousness online.');
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
      console.debug('[Oracle] Socket connected');
      this.socket.emit('get_state');
    });

    // v1.49.3 [2026-03-22] — Disconnect + reconnect handlers
    this.socket.on('disconnect', () => {
      console.debug('[Oracle] Socket disconnected');
    });
    this.socket.io.on('reconnect', (attempt) => {
      console.debug('[Oracle] Reconnected after ' + attempt + ' attempt(s)');
      this.socket.emit('get_state');
    });
    this.socket.io.on('reconnect_attempt', (attempt) => {
      if (attempt % 3 === 0) console.debug('[Oracle] Reconnecting... (attempt ' + attempt + ')');
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

// ──── Tab Switching ── v1.49.5 [2026-03-22] ─────────────────────────────
// CONNECTS: OracleScene, OracleDashboard
// CALLED BY: tab button onclick handlers
// EMITS: none (DOM-only)

const OracleTabs = {
  /** Switch between Consciousness and All-Seeing Eye tabs */
  switchTo(tabId) {
    // Update tab buttons
    const tabs = document.querySelectorAll('.oracle-tab');
    tabs.forEach(t => {
      if (t.dataset.tab === tabId) {
        t.classList.add('oracle-tab--active');
      } else {
        t.classList.remove('oracle-tab--active');
      }
    });

    // Toggle panes
    const consciousness = document.getElementById('tab-consciousness');
    const dashboard = document.getElementById('tab-dashboard');
    if (!consciousness || !dashboard) return;

    if (tabId === 'dashboard') {
      consciousness.style.display = 'none';
      dashboard.style.display = '';
      // Start dashboard polling if not already running
      if (!OracleDash._active) OracleDash.init();
    } else {
      consciousness.style.display = '';
      dashboard.style.display = 'none';
      // Stop dashboard polling when not visible to save resources
      OracleDash.stop();
    }

    console.debug('[Oracle] Tab switched to:', tabId);
  }
};


// ──── All-Seeing Eye Dashboard ── v1.49.5 [2026-03-22] ──────────────────
// CONNECTS: /api/oracle/health, /api/oracle/errors, /api/oracle/alerts,
//           /api/oracle/trace, Socket.IO error_feed + alert_feed + health_update
// CALLED BY: OracleTabs.switchTo('dashboard')
// EMITS: none (DOM-only rendering)

const OracleDash = {
  _active: false,
  _pollTimer: null,
  _socket: null,
  _sparkData: [],        // error rate history (max 30 points)
  _feedItems: [],        // live feed buffer (max 50 items)
  _sortCol: 'count',     // current sort column
  _sortDir: 'desc',      // 'asc' or 'desc'
  _expandedFp: null,     // fingerprint of currently expanded trace row
  _lastErrors: [],       // cached error data for sorting
  _lastAlerts: [],       // v1.49.5 — cached alert data from AlertRouter

  // ── Lifecycle ─────────────────────────────────────────────────────

  /** Initialize dashboard: set up Socket.IO listeners + start polling */
  init() {
    if (this._active) return;
    this._active = true;

    // Reuse the existing OracleApp socket for SocketIO events
    this._socket = OracleApp.socket;

    // Listen for real-time feeds from backend
    // v1.49.5 [2026-03-22] — Added alert_feed listener for AlertRouter events
    if (this._socket) {
      this._socket.on('error_feed', (data) => this._onErrorFeed(data));
      this._socket.on('alert_feed', (data) => this._onAlertFeed(data));
      this._socket.on('health_update', (data) => this._onHealthUpdate(data));
    }

    // Set up sortable column headers
    this._setupSortHeaders();

    // Mark feed dot as live
    const dot = document.getElementById('ase-feed-dot');
    if (dot) dot.classList.add('ase-feed-dot--live');

    // Initial fetch + start 10s polling interval
    // v1.49.5 [2026-03-22] — Added _pollAlerts alongside health/errors
    this._pollHealth();
    this._pollErrors();
    this._pollAlerts();
    this._pollTimer = setInterval(() => {
      this._pollHealth();
      this._pollErrors();
      this._pollAlerts();
    }, 10000);

    console.debug('[Oracle/ASE] Dashboard initialized — polling every 10s');
  },

  /** Stop polling (when tab is switched away) */
  stop() {
    if (!this._active) return;
    this._active = false;

    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }

    // Remove live dot
    const dot = document.getElementById('ase-feed-dot');
    if (dot) dot.classList.remove('ase-feed-dot--live');

    console.debug('[Oracle/ASE] Dashboard paused');
  },

  // ── Polling ───────────────────────────────────────────────────────

  /** Fetch /api/oracle/health and update gauges + service tiles */
  _pollHealth() {
    fetch('/api/oracle/health')
      .then(r => {
        if (!r.ok) throw new Error('Health endpoint returned ' + r.status);
        return r.json();
      })
      .then(data => {
        // Compute health score: weighted average of service states + system metrics
        const score = this._computeHealthScore(data);
        this._renderHealthRing(score);
        this._renderServiceTiles(data.services || {});
        this._renderSystemGauges(data.system || {});
      })
      .catch(e => {
        console.warn('[Oracle/ASE] Health poll failed:', e);
        // Show degraded state
        this._renderHealthRing(0);
      });
  },

  /** Fetch /api/oracle/errors and update table + sparkline */
  _pollErrors() {
    fetch('/api/oracle/errors')
      .then(r => {
        if (!r.ok) throw new Error('Errors endpoint returned ' + r.status);
        return r.json();
      })
      .then(data => {
        // Update sparkline with latest error rate
        const rate = (data.error_rate && data.error_rate.rate_per_min) || 0;
        this._sparkData.push(rate);
        if (this._sparkData.length > 30) this._sparkData.shift();

        // Update total count badge
        const totalEl = document.getElementById('ase-error-total');
        if (totalEl) totalEl.textContent = (data.total_unique || 0) + ' unique';

        // Update rate label
        const rateEl = document.getElementById('ase-error-rate');
        if (rateEl) rateEl.textContent = rate.toFixed(1) + '/min';

        // Cache and render errors
        this._lastErrors = data.top_errors || [];
        this._renderErrorTable(this._lastErrors);
        this._renderSparkline(this._sparkData);
      })
      .catch(e => {
        console.warn('[Oracle/ASE] Errors poll failed:', e);
      });
  },

  // ── Alert Polling ── v1.49.5 [2026-03-22] ────────────────────────
  // CONNECTS: /api/oracle/alerts (AlertRouter.recent_routed + routing_stats)
  // CALLED BY: init() polling loop
  // EMITS: none (DOM-only rendering)

  /** Fetch /api/oracle/alerts and update alerts panel */
  _pollAlerts() {
    fetch('/api/oracle/alerts?limit=50')
      .then(r => {
        if (!r.ok) throw new Error('Alerts endpoint returned ' + r.status);
        return r.json();
      })
      .then(data => {
        if (!data.ok && data.error) {
          console.warn('[Oracle/ASE] Alerts endpoint error:', data.error);
          return;
        }
        this._lastAlerts = data.alerts || [];

        // Update alert count badge
        const countEl = document.getElementById('ase-alert-count');
        if (countEl) {
          const unacked = this._lastAlerts.filter(a => !a.acknowledged).length;
          countEl.textContent = unacked + ' active';
        }

        this._renderAlerts(this._lastAlerts);
      })
      .catch(e => {
        console.warn('[Oracle/ASE] Alerts poll failed:', e);
      });
  },

  // ── Real-time Socket.IO Handlers ──────────────────────────────────

  /** Handle real-time error feed event from SocketIO */
  _onErrorFeed(event) {
    if (!this._active) return;

    this._feedItems.unshift(event);
    if (this._feedItems.length > 50) this._feedItems.length = 50;
    this._renderFeed();
  },

  /**
   * Handle real-time alert_feed event from SocketIO.
   * v1.49.5 [2026-03-22] — AlertRouter callback → SocketIO → dashboard
   * CONNECTS: oracle_scene._on_alert_event → alert_feed SocketIO event
   */
  _onAlertFeed(alert) {
    if (!this._active) return;

    // Prepend to cached alerts (newest first), cap at 50
    this._lastAlerts.unshift(alert);
    if (this._lastAlerts.length > 50) this._lastAlerts.length = 50;

    // Update count badge
    const countEl = document.getElementById('ase-alert-count');
    if (countEl) {
      const unacked = this._lastAlerts.filter(a => !a.acknowledged).length;
      countEl.textContent = unacked + ' active';
    }

    this._renderAlerts(this._lastAlerts);

    // Also push to the live feed as an event
    this._feedItems.unshift({
      timestamp: alert.ts,
      level: alert.severity || 'ALERT',
      module: alert.node || '—',
      message: '[ALERT] ' + (alert.message || alert.metric || '—'),
    });
    if (this._feedItems.length > 50) this._feedItems.length = 50;
    this._renderFeed();
  },

  /** Handle real-time health update from SocketIO */
  _onHealthUpdate(data) {
    if (!this._active) return;

    const score = this._computeHealthScore(data);
    this._renderHealthRing(score);
    if (data.services) this._renderServiceTiles(data.services);
    if (data.system) this._renderSystemGauges(data.system);
  },

  // ── Health Score Computation ──────────────────────────────────────

  /**
   * Compute an overall health score (0-100) from service status + system metrics.
   * - Each UP service contributes 15 points (4 services = 60 max)
   * - CPU < 80% = +15, else scaled down
   * - RAM < 80% = +15, else scaled down
   * - Base 10 points for system being reachable
   */
  _computeHealthScore(data) {
    let score = 10; // base: we can reach the health endpoint

    // Services: 15 points each (max 60)
    const svcs = data.services || {};
    const svcKeys = ['lmstudio', 'comfyui', 'tts', 'mcp'];
    for (const key of svcKeys) {
      const svc = svcs[key];
      if (svc && (svc.status === 'up' || svc === true || svc.ok === true)) {
        score += 15;
      }
    }

    // CPU: 15 points, scaled inversely above 80%
    const sys = data.system || {};
    const cpu = sys.cpu_percent || 0;
    if (cpu < 80) {
      score += 15;
    } else {
      score += Math.max(0, Math.round(15 * (1 - (cpu - 80) / 20)));
    }

    // RAM: 15 points, scaled inversely above 80%
    const ram = sys.ram_percent || 0;
    if (ram < 80) {
      score += 15;
    } else {
      score += Math.max(0, Math.round(15 * (1 - (ram - 80) / 20)));
    }

    return Math.min(100, Math.max(0, score));
  },

  // ── Rendering ─────────────────────────────────────────────────────

  /**
   * Render the circular health ring with conic-gradient.
   * Green >= 70, Yellow >= 40, Red < 40.
   */
  _renderHealthRing(score) {
    const ring = document.getElementById('ase-health-ring');
    const scoreEl = document.getElementById('ase-health-score');
    if (!ring || !scoreEl) return;

    scoreEl.textContent = score;

    // Determine color class
    ring.classList.remove('ase-health-ring--green', 'ase-health-ring--yellow', 'ase-health-ring--red');
    let color;
    if (score >= 70) {
      ring.classList.add('ase-health-ring--green');
      color = '#22c55e';
    } else if (score >= 40) {
      ring.classList.add('ase-health-ring--yellow');
      color = '#eab308';
    } else {
      ring.classList.add('ase-health-ring--red');
      color = '#ef4444';
    }

    // Update conic-gradient to fill proportional to score
    const pct = score / 100 * 360;
    ring.style.background = `conic-gradient(${color} 0deg, ${color} ${pct}deg, rgba(168, 85, 247, 0.08) ${pct}deg, rgba(168, 85, 247, 0.08) 360deg)`;
  },

  /**
   * Render the 4 service status tiles.
   * Each tile shows UP/DOWN with optional latency.
   */
  _renderServiceTiles(services) {
    const map = {
      lmstudio: 'svc-lmstudio',
      mcp: 'svc-mcp',
      comfyui: 'svc-comfyui',
      tts: 'svc-tts'
    };

    for (const [key, elId] of Object.entries(map)) {
      const tile = document.getElementById(elId);
      if (!tile) continue;

      const svc = services[key];
      const statusEl = tile.querySelector('.ase-service-tile__status');
      const latencyEl = tile.querySelector('.ase-service-tile__latency');

      // Determine if service is up
      let isUp = false;
      let latencyMs = null;

      if (svc && typeof svc === 'object') {
        isUp = svc.status === 'up' || svc.ok === true;
        latencyMs = svc.latency_ms || svc.latency || null;
      } else if (typeof svc === 'boolean') {
        isUp = svc;
      }

      // Update tile classes
      tile.classList.remove('ase-service-tile--up', 'ase-service-tile--down');
      tile.classList.add(isUp ? 'ase-service-tile--up' : 'ase-service-tile--down');

      // Update status text
      if (statusEl) statusEl.textContent = isUp ? 'UP' : 'DOWN';

      // Update latency
      if (latencyEl) {
        latencyEl.textContent = latencyMs != null ? latencyMs + ' ms' : '';
      }
    }
  },

  /**
   * Render CPU, RAM, GPU VRAM horizontal gauge bars.
   * Bars change color at 70% (warn) and 90% (crit).
   */
  _renderSystemGauges(system) {
    // CPU gauge
    this._renderGauge('cpu', system.cpu_percent || 0, '%');

    // RAM gauge
    this._renderGauge('ram', system.ram_percent || 0, '%');

    // GPU VRAM — show in MB, estimate percentage (assume 8GB max)
    const vramMb = system.gpu_vram_used_mb || 0;
    const vramMax = system.gpu_vram_total_mb || 8192;
    const vramPct = vramMax > 0 ? Math.min(100, (vramMb / vramMax) * 100) : 0;
    this._renderGaugeRaw('gpu', vramPct, vramMb + ' MB');
  },

  /** Render a single gauge bar by ID prefix (cpu, ram, gpu) */
  _renderGauge(id, pct, suffix) {
    this._renderGaugeRaw(id, pct, Math.round(pct) + suffix);
  },

  /** Low-level gauge renderer */
  _renderGaugeRaw(id, pct, display) {
    const fill = document.getElementById('gauge-' + id + '-fill');
    const val = document.getElementById('gauge-' + id + '-val');
    if (!fill) return;

    pct = Math.min(100, Math.max(0, pct));
    fill.style.width = pct + '%';

    // Color thresholds
    fill.classList.remove('ase-gauge__fill--warn', 'ase-gauge__fill--crit');
    if (pct >= 90) {
      fill.classList.add('ase-gauge__fill--crit');
    } else if (pct >= 70) {
      fill.classList.add('ase-gauge__fill--warn');
    }

    if (val) val.textContent = display;
  },

  /**
   * Render the error table with sortable columns.
   * Click a row to expand/collapse the trace detail.
   */
  _renderErrorTable(errors) {
    const tbody = document.getElementById('ase-error-tbody');
    const noErrors = document.getElementById('ase-no-errors');
    if (!tbody) return;

    if (!errors || errors.length === 0) {
      tbody.innerHTML = '';
      if (noErrors) noErrors.style.display = '';
      return;
    }
    if (noErrors) noErrors.style.display = 'none';

    // Sort errors based on current sort state
    const sorted = this._sortErrors(errors);

    // Build table rows
    let html = '';
    for (const err of sorted) {
      const fp = this._esc(err.fingerprint || '');
      const lastSeen = this._formatTime(err.last_seen);
      const scenes = (err.affected_scenes || []).join(', ');
      const msg = err.sample_message || err.error_type || '—';

      html += '<tr data-fp="' + fp + '" onclick="OracleDash._toggleTrace(\'' + fp + '\')">';
      html += '<td class="ase-td-count">' + this._esc(String(err.count || 0)) + '</td>';
      html += '<td class="ase-td-module">' + this._esc(err.module || '—') + '</td>';
      html += '<td class="ase-td-message" title="' + this._esc(msg) + '">' + this._esc(msg) + '</td>';
      html += '<td class="ase-td-scenes" title="' + this._esc(scenes) + '">' + this._esc(scenes || '—') + '</td>';
      html += '<td class="ase-td-time">' + this._esc(lastSeen) + '</td>';
      html += '<td class="ase-td-rate">' + this._esc(String((err.rate_per_min || 0).toFixed(1))) + '</td>';
      html += '</tr>';

      // If this row is expanded, add a trace detail row placeholder
      if (this._expandedFp === fp) {
        html += '<tr class="ase-trace-row" id="trace-' + fp + '"><td colspan="6">';
        html += '<div class="ase-trace-events" id="trace-events-' + fp + '">Loading trace...</div>';
        html += '</td></tr>';
      }
    }

    tbody.innerHTML = html;

    // If we have an expanded trace, fetch it
    if (this._expandedFp) {
      this._fetchTrace(this._expandedFp);
    }
  },

  /**
   * Render SVG sparkline from error rate data points.
   * polyline for the line, polygon for the area fill.
   */
  _renderSparkline(dataPoints) {
    const line = document.getElementById('ase-sparkline-line');
    const area = document.getElementById('ase-sparkline-area');
    if (!line || !area || dataPoints.length === 0) return;

    // SVG viewBox is 300 x 60
    const w = 300;
    const h = 60;
    const maxVal = Math.max(1, ...dataPoints); // avoid /0
    const step = dataPoints.length > 1 ? w / (dataPoints.length - 1) : 0;

    // Build points string
    const points = dataPoints.map((val, i) => {
      const x = Math.round(i * step);
      const y = Math.round(h - (val / maxVal) * (h - 4) - 2);
      return x + ',' + y;
    });

    line.setAttribute('points', points.join(' '));

    // Area polygon: start at bottom-left, follow line, end at bottom-right
    const areaPoints = ['0,' + h, ...points, w + ',' + h];
    area.setAttribute('points', areaPoints.join(' '));
  },

  /** Render the live error feed (newest first, max 50) */
  _renderFeed() {
    const el = document.getElementById('ase-feed');
    if (!el) return;

    if (this._feedItems.length === 0) {
      el.innerHTML = '<div class="ase-empty">Waiting for error events...</div>';
      return;
    }

    let html = '';
    for (const item of this._feedItems) {
      const time = this._formatTime(item.timestamp);
      const level = (item.level || 'ERROR').toUpperCase();
      const levelClass = level === 'ERROR' ? 'error' : level === 'WARN' || level === 'WARNING' ? 'warn' : 'info';
      const svc = item.service || item.module || '—';
      const msg = item.message || item.error || '—';

      html += '<div class="ase-feed-item">';
      html += '<span class="ase-feed-item__time">' + this._esc(time) + '</span>';
      html += '<span class="ase-feed-item__level ase-feed-item__level--' + levelClass + '">' + this._esc(level) + '</span>';
      html += '<span class="ase-feed-item__svc">' + this._esc(svc) + '</span>';
      html += '<span class="ase-feed-item__msg">' + this._esc(msg) + '</span>';
      html += '</div>';
    }

    el.innerHTML = html;
  },

  // ── Alert Rendering ── v1.49.5 [2026-03-22] ─────────────────────
  // CONNECTS: AlertRouter severity levels, /api/oracle/alerts/<id>/ack
  // CALLED BY: _pollAlerts, _onAlertFeed
  // EMITS: none (DOM-only)

  /**
   * Render alert cards with severity-colored left borders.
   * Maps severity: CRITICAL→red glow, HIGH→orange, MEDIUM→yellow, LOW→cyan.
   */
  _renderAlerts(alerts) {
    const container = document.getElementById('ase-alerts');
    if (!container) return;

    if (!alerts || alerts.length === 0) {
      container.innerHTML = '<div class="ase-empty">No active alerts</div>';
      return;
    }

    let html = '';
    for (const a of alerts) {
      const sev = (a.severity || 'LOW').toLowerCase();
      const acked = a.acknowledged ? ' ase-alert--acked' : '';
      const time = this._formatTime(a.ts);
      const channels = (a.channels || a.channels_routed || []);
      const id = a.id || '';

      html += '<div class="ase-alert ase-alert--' + this._esc(sev) + acked + '" data-alert-id="' + this._esc(String(id)) + '">';

      // Severity dot
      html += '<div class="ase-alert__severity"></div>';

      // Body
      html += '<div class="ase-alert__body">';
      html += '<div class="ase-alert__header">';
      html += '<span class="ase-alert__node">' + this._esc(a.node || '—') + '</span>';
      html += '<span class="ase-alert__metric">' + this._esc(a.metric || '') + '</span>';
      html += '<span class="ase-alert__level">' + this._esc((a.severity || 'LOW').toUpperCase()) + '</span>';
      html += '</div>';
      html += '<div class="ase-alert__message">' + this._esc(a.message || '—') + '</div>';

      // Meta: source type + channels
      html += '<div class="ase-alert__meta">';
      html += '<span>' + this._esc(a.source_type || '') + '</span>';
      if (channels.length > 0) {
        html += '<span class="ase-alert__channels">';
        for (const ch of channels) {
          html += '<span class="ase-alert__channel">' + this._esc(ch) + '</span>';
        }
        html += '</span>';
      }
      html += '</div>';
      html += '</div>'; // /body

      // Actions: time + ack button
      html += '<div class="ase-alert__actions">';
      html += '<span class="ase-alert__time">' + this._esc(time) + '</span>';
      if (id && !a.acknowledged) {
        html += '<button class="ase-alert__ack" onclick="OracleDash._ackAlert(' + this._esc(String(id)) + ')">ACK</button>';
      } else if (a.acknowledged) {
        html += '<button class="ase-alert__ack ase-alert__ack--done">ACKED</button>';
      }
      html += '</div>';

      html += '</div>'; // /alert
    }

    container.innerHTML = html;
  },

  /**
   * Acknowledge an alert by ID via POST /api/oracle/alerts/<id>/ack.
   * On success, marks the alert as acknowledged in the cached data and re-renders.
   */
  _ackAlert(alertId) {
    fetch('/api/oracle/alerts/' + alertId + '/ack', { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          // Update cached alert data
          for (const a of this._lastAlerts) {
            if (a.id === alertId) {
              a.acknowledged = true;
              break;
            }
          }
          this._renderAlerts(this._lastAlerts);

          // Update count badge
          const countEl = document.getElementById('ase-alert-count');
          if (countEl) {
            const unacked = this._lastAlerts.filter(a => !a.acknowledged).length;
            countEl.textContent = unacked + ' active';
          }
        }
      })
      .catch(e => console.warn('[Oracle/ASE] Ack failed:', e));
  },

  // ── Sorting ───────────────────────────────────────────────────────

  /** Set up click handlers on sortable table headers */
  _setupSortHeaders() {
    const ths = document.querySelectorAll('.ase-sortable');
    ths.forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.sort;
        if (!col) return;

        // Toggle direction if same column, else default to desc
        if (this._sortCol === col) {
          this._sortDir = this._sortDir === 'desc' ? 'asc' : 'desc';
        } else {
          this._sortCol = col;
          this._sortDir = 'desc';
        }

        // Update header visual indicators
        document.querySelectorAll('.ase-sortable').forEach(h => {
          h.classList.remove('ase-sortable--asc', 'ase-sortable--desc');
        });
        th.classList.add('ase-sortable--' + this._sortDir);

        // Re-render with current cached data
        if (this._lastErrors.length > 0) {
          this._renderErrorTable(this._lastErrors);
        }
      });
    });
  },

  /** Sort errors array by current sort column/direction */
  _sortErrors(errors) {
    const col = this._sortCol;
    const dir = this._sortDir === 'asc' ? 1 : -1;

    return [...errors].sort((a, b) => {
      let va, vb;
      switch (col) {
        case 'count':
          va = a.count || 0;
          vb = b.count || 0;
          break;
        case 'module':
          va = (a.module || '').toLowerCase();
          vb = (b.module || '').toLowerCase();
          return dir * va.localeCompare(vb);
        case 'last_seen':
          va = a.last_seen || '';
          vb = b.last_seen || '';
          return dir * va.localeCompare(vb);
        case 'rate':
          va = a.rate_per_min || 0;
          vb = b.rate_per_min || 0;
          break;
        default:
          va = a.count || 0;
          vb = b.count || 0;
      }
      return dir * (va - vb);
    });
  },

  // ── Trace Expansion ───────────────────────────────────────────────

  /** Toggle trace detail row for a given error fingerprint */
  _toggleTrace(fingerprint) {
    if (this._expandedFp === fingerprint) {
      // Collapse: remove the trace row
      this._expandedFp = null;
    } else {
      // Expand: set this fingerprint as expanded
      this._expandedFp = fingerprint;
    }
    // Re-render table to show/hide trace row
    if (this._lastErrors.length > 0) {
      this._renderErrorTable(this._lastErrors);
    }
  },

  /** Fetch trace data from /api/oracle/trace/<id> and render */
  _fetchTrace(fingerprint) {
    const container = document.getElementById('trace-events-' + fingerprint);
    if (!container) return;

    fetch('/api/oracle/trace/' + encodeURIComponent(fingerprint))
      .then(r => {
        if (!r.ok) throw new Error('Trace endpoint returned ' + r.status);
        return r.json();
      })
      .then(data => {
        const events = data.events || [];
        if (events.length === 0) {
          container.innerHTML = '<span style="color:var(--or-muted)">No trace events found.</span>';
          return;
        }

        let html = '';
        for (const evt of events) {
          const time = this._formatTime(evt.timestamp);
          const dur = evt.duration_ms != null ? evt.duration_ms + 'ms' : '';
          html += '<div class="ase-trace-event">';
          html += '<span class="ase-trace-event__time">' + this._esc(time) + '</span>';
          html += '<span class="ase-trace-event__svc">' + this._esc(evt.service || '—') + '</span>';
          html += this._esc(evt.message || '');
          if (dur) html += '<span class="ase-trace-event__dur">' + this._esc(dur) + '</span>';
          html += '</div>';
        }
        container.innerHTML = html;
      })
      .catch(e => {
        container.innerHTML = '<span style="color:#ef4444">Trace fetch failed: ' + this._esc(e.message) + '</span>';
      });
  },

  // ── Utils ─────────────────────────────────────────────────────────

  /** XSS-safe HTML escaping */
  _esc(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },

  /** Format ISO timestamp or epoch to HH:MM:SS
   *  v1.49.5 [2026-03-22] — Handle epoch seconds (AlertRouter ts) vs ms/ISO */
  _formatTime(ts) {
    if (!ts) return '—';
    try {
      // If ts is a number and looks like epoch seconds (< 1e12), convert to ms
      let d;
      if (typeof ts === 'number' && ts > 0 && ts < 1e12) {
        d = new Date(ts * 1000);
      } else {
        d = new Date(ts);
      }
      if (isNaN(d.getTime())) return String(ts).slice(0, 19);
      return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return String(ts).slice(0, 19);
    }
  }
};


// ──── Bootstrap ─────────────────────────────────────────────────────────

const OracleApp = new OracleScene();

document.addEventListener('DOMContentLoaded', () => {
  OracleApp.init();
});
