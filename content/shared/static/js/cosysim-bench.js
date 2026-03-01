/**
 * CosySim Benchmark HUD — v0.68 "Dark Renaissance"
 * ==================================================
 * Live performance strip rendered at the bottom of every scene.
 * Connects to /api/bench/metrics via Socket.IO (bench:update event)
 * and periodic polling.
 *
 * Usage:
 *   // Auto-init on DOMContentLoaded:
 *   <script src="/static/js/cosysim-bench.js"></script>
 *
 *   // Manual init:
 *   const hud = new BenchHUD({ collapsed: false, poll: 5000 });
 *   hud.mount(document.body);
 *
 *   // Feed data manually (e.g., after agent reply):
 *   BenchHUD.update({ response_ms: 420, model_id: 'qwen3-4b', nexus_tier: 'cache' });
 */

(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.BenchHUD = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ── Constants ─────────────────────────────────────────────────────────────

  const TIER_COLORS = {
    cache: { bg: 'var(--cs-bench-cache, #22c55e)',  label: '⚡ CACHE' },
    fts:   { bg: 'var(--cs-bench-fts,   #f59e0b)',  label: '🔍 FTS'   },
    nlm:   { bg: 'var(--cs-bench-nlm,   #f97316)',  label: '📓 NLM'   },
    llm:   { bg: 'var(--cs-bench-llm,   #ef4444)',  label: '🤖 LLM'   },
    none:  { bg: 'var(--cs-bench-ok,    #64748b)',  label: '—'         },
  };

  const MS_THRESHOLDS = {
    fast: 2000,
    ok:   5000,
  };

  function msColor(ms) {
    if (!ms || ms <= 0) return 'var(--cs-bench-ok, #64748b)';
    if (ms < MS_THRESHOLDS.fast) return 'var(--cs-bench-fast, #22c55e)';
    if (ms < MS_THRESHOLDS.ok)   return 'var(--cs-bench-ok,   #f59e0b)';
    return 'var(--cs-bench-slow, #ef4444)';
  }

  function fmt(ms) {
    if (!ms || ms <= 0) return '—';
    if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
    return ms + 'ms';
  }

  // ── State ─────────────────────────────────────────────────────────────────

  let _instance = null;
  let _data = {
    response_ms: 0,
    model_id: null,
    tts_ms: 0,
    nexus_tier: 'none',
    tokens_in: 0,
    tokens_out: 0,
    consequences_pending: 0,
    economy_balance: null,
    world_time: null,
    active_events: [],
    scene: null,
    updated_at: null,
  };

  // ── BenchHUD Class ────────────────────────────────────────────────────────

  class BenchHUD {
    /**
     * @param {object} options
     * @param {boolean} [options.collapsed=false]
     * @param {number}  [options.poll=5000] - polling interval ms, 0 = disabled
     * @param {boolean} [options.socket=true] - connect to Socket.IO bench:update
     * @param {string}  [options.endpoint='/api/bench/metrics'] - metrics URL
     */
    constructor(options = {}) {
      this._opts = {
        collapsed: false,
        poll: 5000,
        socket: true,
        endpoint: '/api/bench/metrics',
        ...options,
      };
      this._collapsed = this._opts.collapsed;
      this._el = null;
      this._pollTimer = null;
      this._io = null;
      _instance = this;
    }

    // ── Public API ─────────────────────────────────────────────────────────

    mount(parent = document.body) {
      if (!parent) return this;
      this._build();
      parent.appendChild(this._el);
      this._connectSocket();
      this._startPolling();
      this._render(_data);
      return this;
    }

    unmount() {
      this._stopPolling();
      this._disconnectSocket();
      if (this._el && this._el.parentNode) {
        this._el.parentNode.removeChild(this._el);
      }
    }

    update(data) {
      _data = { ..._data, ...data, updated_at: Date.now() };
      this._render(_data);
    }

    show() {
      if (this._el) this._el.style.display = '';
    }

    hide() {
      if (this._el) this._el.style.display = 'none';
    }

    collapse() {
      this._collapsed = true;
      this._applyCollapsed();
    }

    expand() {
      this._collapsed = false;
      this._applyCollapsed();
    }

    // ── Build DOM ──────────────────────────────────────────────────────────

    _build() {
      const el = document.createElement('div');
      el.className = 'cs-bench-hud';
      el.id = 'cs-bench-hud';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-label', 'Performance metrics');

      el.innerHTML = `
        <button class="cs-bench-toggle" id="cs-bench-toggle" aria-label="Toggle benchmark HUD" title="Toggle metrics">
          <span class="cs-bench-toggle-icon">◀</span>
        </button>
        <div class="cs-bench-content" id="cs-bench-content">
          <div class="cs-bench-row" id="cs-bench-row">

            <!-- Agent latency -->
            <div class="cs-bench-metric" id="bm-response">
              <span class="cs-bench-label">Agent</span>
              <span class="cs-bench-value" id="bm-response-val">—</span>
            </div>

            <!-- Model -->
            <div class="cs-bench-metric" id="bm-model">
              <span class="cs-bench-label">Model</span>
              <span class="cs-agent-tag cs-agent-tag--small" id="bm-model-val">—</span>
            </div>

            <!-- Nexus tier -->
            <div class="cs-bench-metric" id="bm-nexus">
              <span class="cs-bench-label">Nexus</span>
              <span class="cs-bench-tier" id="bm-nexus-val">—</span>
            </div>

            <!-- TTS latency -->
            <div class="cs-bench-metric" id="bm-tts">
              <span class="cs-bench-label">TTS</span>
              <span class="cs-bench-value" id="bm-tts-val">—</span>
            </div>

            <!-- Tokens -->
            <div class="cs-bench-metric" id="bm-tokens">
              <span class="cs-bench-label">Tokens</span>
              <span class="cs-bench-value" id="bm-tokens-val">—</span>
            </div>

            <!-- Economy balance -->
            <div class="cs-bench-metric" id="bm-credits" style="display:none">
              <span class="cs-bench-label">Credits</span>
              <span class="cs-bench-value cs-bench-credits" id="bm-credits-val">₵ —</span>
            </div>

            <!-- World time -->
            <div class="cs-bench-metric" id="bm-worldtime" style="display:none">
              <span class="cs-bench-label">World</span>
              <span class="cs-bench-value" id="bm-worldtime-val">—</span>
            </div>

            <!-- Consequences -->
            <div class="cs-bench-metric" id="bm-consequences" style="display:none">
              <span class="cs-bench-label">Events</span>
              <span class="cs-bench-value cs-bench-consequences" id="bm-consequences-val">0</span>
            </div>

          </div>
        </div>
      `;

      // Toggle click
      el.querySelector('#cs-bench-toggle').addEventListener('click', () => {
        this._collapsed = !this._collapsed;
        this._applyCollapsed();
      });

      this._el = el;
      if (this._collapsed) this._applyCollapsed();

      // Inject minimal styles if cosysim-components.css isn't loaded
      this._ensureStyles();
    }

    // ── Render ─────────────────────────────────────────────────────────────

    _render(d) {
      if (!this._el) return;

      // Agent response time
      const responseEl = this._el.querySelector('#bm-response-val');
      if (responseEl) {
        responseEl.textContent = fmt(d.response_ms);
        responseEl.style.color = msColor(d.response_ms);
      }

      // Model badge
      const modelEl = this._el.querySelector('#bm-model-val');
      if (modelEl && d.model_id) {
        const name = this._shortModel(d.model_id);
        modelEl.textContent = name;
        modelEl.className = `cs-agent-tag cs-agent-tag--small ${this._modelClass(d.model_id)}`;
      }

      // Nexus tier
      const nexusEl = this._el.querySelector('#bm-nexus-val');
      if (nexusEl) {
        const tier = TIER_COLORS[d.nexus_tier] || TIER_COLORS.none;
        nexusEl.textContent = tier.label;
        nexusEl.style.background = tier.bg;
      }

      // TTS
      const ttsEl = this._el.querySelector('#bm-tts-val');
      if (ttsEl) {
        ttsEl.textContent = d.tts_ms > 0 ? fmt(d.tts_ms) : '—';
        ttsEl.style.color = d.tts_ms > 0 ? msColor(d.tts_ms) : '';
      }

      // Tokens
      const tokensEl = this._el.querySelector('#bm-tokens-val');
      if (tokensEl && (d.tokens_in || d.tokens_out)) {
        tokensEl.textContent = `${d.tokens_in || 0}↑ ${d.tokens_out || 0}↓`;
      }

      // Credits
      const creditsEl = this._el.querySelector('#bm-credits-val');
      const creditsWrap = this._el.querySelector('#bm-credits');
      if (creditsEl && d.economy_balance !== null && d.economy_balance !== undefined) {
        creditsWrap.style.display = '';
        const bal = parseInt(d.economy_balance, 10);
        creditsEl.textContent = `₵ ${bal.toLocaleString()}`;
        creditsEl.style.color = bal >= 0 ? 'var(--cs-neon-green, #22c55e)' : 'var(--cs-neon-red, #ef4444)';
      }

      // World time
      const worldEl = this._el.querySelector('#bm-worldtime-val');
      const worldWrap = this._el.querySelector('#bm-worldtime');
      if (worldEl && d.world_time) {
        worldWrap.style.display = '';
        worldEl.textContent = d.world_time;
      }

      // Consequences
      const consEl = this._el.querySelector('#bm-consequences-val');
      const consWrap = this._el.querySelector('#bm-consequences');
      if (consEl && d.consequences_pending > 0) {
        consWrap.style.display = '';
        consEl.textContent = `${d.consequences_pending} ⚡`;
        consEl.style.color = 'var(--cs-neon-amber, #f59e0b)';
      }

      // Pulse animation on update
      if (this._el.classList) {
        this._el.classList.remove('cs-bench-pulse');
        void this._el.offsetWidth; // force reflow
        this._el.classList.add('cs-bench-pulse');
      }
    }

    // ── Networking ─────────────────────────────────────────────────────────

    _startPolling() {
      if (!this._opts.poll) return;
      this._pollTimer = setInterval(() => this._fetchMetrics(), this._opts.poll);
      // Initial fetch
      setTimeout(() => this._fetchMetrics(), 500);
    }

    _stopPolling() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    }

    _fetchMetrics() {
      fetch(this._opts.endpoint)
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) this.update(data); })
        .catch(() => {}); // silent fail
    }

    _connectSocket() {
      if (!this._opts.socket) return;
      // Wait for Socket.IO to be available
      const tryConnect = () => {
        if (typeof io === 'undefined') {
          setTimeout(tryConnect, 1000);
          return;
        }
        try {
          // Re-use existing socket if available
          const sock = window._csSocket || (window._csSocket = io());
          sock.on('bench:update', (data) => this.update(data));
          this._io = sock;
        } catch (e) {
          // Socket.IO not available — polling only
        }
      };
      setTimeout(tryConnect, 200);
    }

    _disconnectSocket() {
      if (this._io) {
        this._io.off('bench:update');
        this._io = null;
      }
    }

    // ── Helpers ────────────────────────────────────────────────────────────

    _applyCollapsed() {
      if (!this._el) return;
      const content = this._el.querySelector('#cs-bench-content');
      const icon = this._el.querySelector('.cs-bench-toggle-icon');
      if (this._collapsed) {
        this._el.classList.add('cs-bench-hud--collapsed');
        if (content) content.style.display = 'none';
        if (icon) icon.textContent = '▶';
      } else {
        this._el.classList.remove('cs-bench-hud--collapsed');
        if (content) content.style.display = '';
        if (icon) icon.textContent = '◀';
      }
    }

    _shortModel(modelId) {
      if (!modelId) return '?';
      // "qwen3-4b-q4_k_m" → "qwen3-4b"
      return modelId.replace(/[-_](q[0-9]+|gguf|fp16|int8).*/i, '').replace(/^.*[/\\]/, '');
    }

    _modelClass(modelId) {
      if (!modelId) return '';
      const id = modelId.toLowerCase();
      if (id.includes('qwen') && id.match(/0\.6|600m|0\.5/)) return 'cs-agent-tag--router';
      if (id.includes('qwen') || id.includes('phi') || id.includes('gemma')) return 'cs-agent-tag--small';
      if (id.includes('mistral') || id.includes('llama') || id.includes('7b') || id.includes('8b')) return 'cs-agent-tag--medium';
      if (id.includes('70b') || id.includes('72b') || id.includes('large')) return 'cs-agent-tag--large';
      return 'cs-agent-tag--small';
    }

    _ensureStyles() {
      if (document.getElementById('cs-bench-inline-styles')) return;
      const style = document.createElement('style');
      style.id = 'cs-bench-inline-styles';
      style.textContent = `
        .cs-bench-hud {
          position: fixed;
          bottom: 0; right: 0;
          display: flex;
          align-items: center;
          background: rgba(5, 8, 15, 0.85);
          backdrop-filter: blur(12px);
          border-top: 1px solid rgba(0, 229, 255, 0.15);
          border-left: 1px solid rgba(0, 229, 255, 0.15);
          border-radius: 8px 0 0 0;
          padding: 4px 8px;
          z-index: 9990;
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          font-size: 11px;
          color: rgba(200, 220, 255, 0.8);
          gap: 4px;
          transition: all 0.2s ease;
        }
        .cs-bench-hud--collapsed .cs-bench-content { display: none; }
        .cs-bench-toggle {
          background: none; border: none; cursor: pointer;
          color: rgba(0, 229, 255, 0.5); padding: 0 4px;
          font-size: 10px; line-height: 1;
          flex-shrink: 0;
        }
        .cs-bench-toggle:hover { color: rgba(0, 229, 255, 1); }
        .cs-bench-row {
          display: flex; align-items: center; gap: 12px; padding: 2px 4px;
        }
        .cs-bench-metric {
          display: flex; flex-direction: column; align-items: center; gap: 1px;
          min-width: 48px;
        }
        .cs-bench-label {
          font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em;
          color: rgba(100, 120, 160, 0.7);
        }
        .cs-bench-value {
          font-size: 12px; font-weight: 600; letter-spacing: 0.03em;
          transition: color 0.3s ease;
        }
        .cs-bench-tier {
          font-size: 10px; font-weight: 700; padding: 1px 5px;
          border-radius: 3px; color: #fff;
        }
        .cs-agent-tag--small { font-size: 10px; padding: 1px 6px; border-radius: 3px;
          background: rgba(59, 130, 246, 0.2); border: 1px solid rgba(59, 130, 246, 0.4);
          color: #93c5fd; white-space: nowrap; }
        .cs-agent-tag--medium { background: rgba(139, 92, 246, 0.2); border-color: rgba(139, 92, 246, 0.4); color: #c4b5fd; }
        .cs-agent-tag--large  { background: rgba(236, 72, 153, 0.2); border-color: rgba(236, 72, 153, 0.4); color: #f9a8d4; }
        .cs-agent-tag--router { background: rgba(34, 197, 94, 0.15); border-color: rgba(34, 197, 94, 0.4); color: #86efac; }
        @keyframes cs-bench-pulse-anim {
          0%   { border-top-color: rgba(0, 229, 255, 0.6); }
          100% { border-top-color: rgba(0, 229, 255, 0.15); }
        }
        .cs-bench-pulse {
          animation: cs-bench-pulse-anim 0.5s ease-out;
        }
      `;
      document.head.appendChild(style);
    }
  }

  // ── Static API ─────────────────────────────────────────────────────────────

  /**
   * Feed a metrics update to the global HUD instance.
   * Call this after any agent reply completes.
   * @param {object} data - partial metrics object
   */
  BenchHUD.update = function (data) {
    if (_instance) _instance.update(data);
  };

  /**
   * Get the singleton instance.
   * @returns {BenchHUD|null}
   */
  BenchHUD.instance = function () {
    return _instance;
  };

  /**
   * Create and mount a HUD if not already present.
   * Called automatically on DOMContentLoaded.
   * @param {object} [options]
   * @returns {BenchHUD}
   */
  BenchHUD.init = function (options = {}) {
    if (_instance && _instance._el) return _instance;
    const hud = new BenchHUD(options);
    hud.mount(document.body);
    return hud;
  };

  // ── Auto-init ─────────────────────────────────────────────────────────────

  if (typeof document !== 'undefined') {
    const doInit = () => {
      // Only auto-init if data-bench-hud="true" on <body> or the script tag
      const scriptEl = document.currentScript;
      const autoInit = scriptEl && scriptEl.getAttribute('data-auto-init') !== 'false';
      const bodyFlag = document.body && document.body.getAttribute('data-bench-hud');
      if (autoInit !== false && bodyFlag !== 'false') {
        const collapsed = bodyFlag === 'collapsed' ||
          (scriptEl && scriptEl.getAttribute('data-collapsed') === 'true');
        BenchHUD.init({ collapsed });
      }
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', doInit);
    } else {
      doInit();
    }
  }

  return BenchHUD;
}));
