/**
 * CosySim Stats Overlay
 * ====================
 * Polls /api/stats/live and renders a floating HUD with:
 *   - CPU / RAM / GPU VRAM usage with mini bar graphs
 *   - GPU temperature
 *   - Loaded model chip
 *   - Live activity feed (thinking / tool_call / tts / etc.)
 *
 * Usage: inject this script into any scene template.
 * The overlay injects its own CSS link automatically.
 *
 *   <script src="/static/js/stats_overlay.js"></script>
 *   or
 *   <script src="/shared/js/stats_overlay.js"></script>
 *
 * The poll URL is detected from the page origin.
 */
(function () {
  'use strict';

  /* ── Config ─────────────────────────────────────────────────────── */
  const POLL_MS        = 2000;
  const STATS_ENDPOINT = '/api/stats/live';
  const CSS_URL        = '/static/css/stats_overlay.css';

  /* ── State ───────────────────────────────────────────────────────── */
  let collapsed  = localStorage.getItem('cosysim_overlay_collapsed') === '1';
  let pollTimer  = null;
  let lastStats  = null;

  /* ── Build DOM ───────────────────────────────────────────────────── */
  function injectCSS() {
    if (document.querySelector('link[data-cosysim-overlay]')) return;
    const link = document.createElement('link');
    link.rel               = 'stylesheet';
    link.href              = CSS_URL;
    link.dataset.cosysimOverlay = '1';
    document.head.appendChild(link);
  }

  function buildOverlay() {
    const el = document.createElement('div');
    el.id = 'cosysim-overlay';
    if (collapsed) el.classList.add('collapsed');

    el.innerHTML = `
      <div id="cosysim-overlay-header">
        <div class="cosysim-activity-dot" id="cosysim-dot"></div>
        <span class="cosysim-logo">CosySim</span>
        <span class="cosysim-toggle" id="cosysim-toggle-btn">
          ${collapsed ? '▼' : '▲'}
        </span>
      </div>
      <div id="cosysim-overlay-body">
        <div class="cosysim-stat-row" id="cosysim-model-row">
          <span class="cosysim-stat-label">Model</span>
          <span class="cosysim-stat-value" id="cosysim-model">—</span>
        </div>
        <div class="cosysim-stat-row">
          <span class="cosysim-stat-label">VRAM</span>
          <span class="cosysim-stat-value" id="cosysim-vram">—</span>
          <div class="cosysim-bar-wrap"><div class="cosysim-bar-fill" id="cosysim-vram-bar" style="width:0%"></div></div>
        </div>
        <div class="cosysim-stat-row">
          <span class="cosysim-stat-label">CPU</span>
          <span class="cosysim-stat-value" id="cosysim-cpu">—</span>
          <div class="cosysim-bar-wrap"><div class="cosysim-bar-fill" id="cosysim-cpu-bar" style="width:0%"></div></div>
        </div>
        <div class="cosysim-stat-row">
          <span class="cosysim-stat-label">RAM</span>
          <span class="cosysim-stat-value" id="cosysim-ram">—</span>
          <div class="cosysim-bar-wrap"><div class="cosysim-bar-fill" id="cosysim-ram-bar" style="width:0%"></div></div>
        </div>
        <div class="cosysim-stat-row" id="cosysim-gpu-temp-row">
          <span class="cosysim-stat-label">GPU °C</span>
          <span class="cosysim-stat-value" id="cosysim-gputemp">—</span>
        </div>
        <div class="cosysim-activities" id="cosysim-activities">
          <div class="cosysim-activity-label">Activity</div>
          <div id="cosysim-activity-list">
            <span class="cosysim-idle-text">● Idle</span>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(el);

    document.getElementById('cosysim-toggle-btn').addEventListener('click', toggleCollapse);
    document.getElementById('cosysim-overlay-header').addEventListener('click', toggleCollapse);

    return el;
  }

  function toggleCollapse(e) {
    e.stopPropagation();
    const el = document.getElementById('cosysim-overlay');
    if (!el) return;
    collapsed = !collapsed;
    el.classList.toggle('collapsed', collapsed);
    document.getElementById('cosysim-toggle-btn').textContent = collapsed ? '▼' : '▲';
    localStorage.setItem('cosysim_overlay_collapsed', collapsed ? '1' : '0');
  }

  /* ── Helpers ─────────────────────────────────────────────────────── */
  function pct(used, total) {
    if (!used || !total) return 0;
    return Math.min(100, Math.round((used / total) * 100));
  }

  function barClass(p) {
    if (p >= 85) return 'crit';
    if (p >= 65) return 'warn';
    return '';
  }

  function valClass(p) {
    if (p >= 85) return 'crit';
    if (p >= 65) return 'warn';
    if (p <= 25) return 'good';
    return '';
  }

  function setEl(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className   = 'cosysim-stat-value ' + (cls || '');
  }

  function setBar(id, pct, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.width = pct + '%';
    el.className   = 'cosysim-bar-fill ' + (cls || '');
  }

  /* ── Render ──────────────────────────────────────────────────────── */
  function render(data) {
    const sys      = data.system || {};
    const activity = data.activity || {};
    const active   = activity.active || [];

    /* Dot */
    const dot = document.getElementById('cosysim-dot');
    if (dot) {
      const isIdle = activity.idle !== false && active.length === 0;
      const kind   = active.length ? (active[0].kind || '') : '';
      dot.className = 'cosysim-activity-dot' + (
        isIdle ? '' : kind === 'thinking' ? ' thinking' : ' busy'
      );
    }

    /* Model */
    const model = sys.loaded_model || data.loaded_model || '';
    const modelEl = document.getElementById('cosysim-model');
    if (modelEl) {
      if (model) {
        const short = model.split('/').pop().split('-').slice(0, 3).join('-');
        modelEl.innerHTML = `<span class="cosysim-model-chip" title="${model}">${short}</span>`;
      } else {
        modelEl.innerHTML = '<span style="color:#554">none loaded</span>';
      }
    }

    /* VRAM */
    const vramUsed  = sys.gpu_vram_used_mb;
    const vramTotal = sys.gpu_vram_total_mb;
    const vramPct   = pct(vramUsed, vramTotal);
    if (vramUsed != null) {
      const label = `${Math.round(vramUsed)}/${Math.round(vramTotal)} MB`;
      setEl('cosysim-vram', label, valClass(vramPct));
      setBar('cosysim-vram-bar', vramPct, barClass(vramPct));
    }

    /* CPU */
    const cpuPct = sys.cpu_percent;
    if (cpuPct != null) {
      setEl('cosysim-cpu', cpuPct.toFixed(0) + '%', valClass(cpuPct));
      setBar('cosysim-cpu-bar', cpuPct, barClass(cpuPct));
    }

    /* RAM */
    const ramUsed  = sys.ram_used_gb;
    const ramTotal = sys.ram_total_gb;
    const ramPct   = pct(ramUsed, ramTotal);
    if (ramUsed != null) {
      const label = `${ramUsed.toFixed(1)}/${ramTotal.toFixed(0)} GB`;
      setEl('cosysim-ram', label, valClass(ramPct));
      setBar('cosysim-ram-bar', ramPct, barClass(ramPct));
    }

    /* GPU temp */
    const gpuTemp = sys.gpu_temp_c;
    if (gpuTemp != null) {
      const tempClass = gpuTemp >= 85 ? 'crit' : gpuTemp >= 75 ? 'warn' : '';
      setEl('cosysim-gputemp', gpuTemp + '°C', tempClass);
    }

    /* Activities */
    const listEl = document.getElementById('cosysim-activity-list');
    if (listEl) {
      if (active.length === 0) {
        listEl.innerHTML = '<span class="cosysim-idle-text">● Idle</span>';
      } else {
        listEl.innerHTML = active.map(act => {
          const elapsed = act.elapsed_ms ? ` <span style="color:#446;font-size:9px">${Math.round(act.elapsed_ms)}ms</span>` : '';
          return `
            <div class="cosysim-activity-item">
              <span class="cosysim-activity-kind ${act.kind}">${act.kind}</span>
              <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${act.label}</span>
              ${elapsed}
            </div>`;
        }).join('');
      }
    }
  }

  /* ── Poll ────────────────────────────────────────────────────────── */
  async function poll() {
    try {
      const res = await fetch(STATS_ENDPOINT, { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      lastStats = data;
      render(data);
    } catch (_) { /* server might be starting up */ }
  }

  /* ── Init ────────────────────────────────────────────────────────── */
  function init() {
    injectCSS();
    buildOverlay();
    poll();
    pollTimer = setInterval(poll, POLL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* Expose for external use */
  window.CosySimOverlay = {
    refresh: poll,
    destroy: () => {
      clearInterval(pollTimer);
      const el = document.getElementById('cosysim-overlay');
      if (el) el.remove();
    },
  };
})();
