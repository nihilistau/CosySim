/**
 * admin_training.js — CosySim v0.78 Training Dashboard
 *
 * Renders model cards for all MODEL_ZOO types in the [TRAINING] admin tab.
 * Connects to /api/admin/training/stats and /api/admin/training/trigger/:model_type
 *
 * Auto-loads when the TRAINING tab is activated.
 * Cards show: dataset size, status badge, trigger button, last-update timestamp.
 */

(function () {
  'use strict';

  const MODEL_TYPES = [
    { id: 'coder',            label: 'Coder',              icon: '🧠', color: '#6366f1' },
    { id: 'tool_dispatch',    label: 'Tool Dispatch',      icon: '🔧', color: '#f59e0b' },
    { id: 'conversational',   label: 'Conversational',     icon: '💬', color: '#10b981' },
    { id: 'grammar_scanner',  label: 'Grammar Scanner',    icon: '📝', color: '#ef4444' },
    { id: 'output_evaluator', label: 'Output Evaluator',   icon: '⭐', color: '#8b5cf6' },
    { id: 'router',           label: 'Router (270M)',       icon: '🔀', color: '#06b6d4' },
    { id: 'voice_encoder',    label: 'Voice Encoder',      icon: '🎙️', color: '#f97316' },
    { id: 'voice_decoder',    label: 'Voice Decoder',      icon: '🔊', color: '#84cc16' },
    { id: 'speculative',      label: 'Spec Decoder',       icon: '⚡', color: '#ec4899' },
  ];

  function esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderCard(model, stats) {
    const liveKey  = `${model.id}_live`;
    const trainKey = `${model.id}_train`;
    const liveCount  = stats[liveKey]  !== undefined ? stats[liveKey]  : '—';
    const trainCount = stats[trainKey] !== undefined ? stats[trainKey] : '—';

    return `
      <div class="cs-train-card" data-model="${esc(model.id)}" style="border-left: 3px solid ${esc(model.color)}">
        <div class="cs-train-card__header">
          <span class="cs-train-card__icon">${esc(model.icon)}</span>
          <span class="cs-train-card__label">${esc(model.label)}</span>
          <span class="cs-train-card__badge cs-train-card__badge--idle">idle</span>
        </div>
        <div class="cs-train-card__stats">
          <div class="cs-train-card__stat">
            <span class="cs-train-card__stat-label">Live buffer</span>
            <span class="cs-train-card__stat-val">${esc(String(liveCount))}</span>
          </div>
          <div class="cs-train-card__stat">
            <span class="cs-train-card__stat-label">Training set</span>
            <span class="cs-train-card__stat-val">${esc(String(trainCount))}</span>
          </div>
        </div>
        <button
          class="cs-glass-btn cs-train-card__trigger"
          data-model="${esc(model.id)}"
          title="Trigger training for ${esc(model.label)}"
        >▶ Train</button>
      </div>`;
  }

  function renderGrid(stats) {
    return `
      <div class="cs-train-grid">
        ${MODEL_TYPES.map(m => renderCard(m, stats)).join('')}
      </div>
      <div class="cs-train-summary">
        <span>Total live examples: <strong>${esc(String(stats.total_live || 0))}</strong></span>
        <span>Active types: <strong>${esc(String(stats.model_types || 0))}</strong></span>
      </div>`;
  }

  function triggerTraining(modelType, btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Queued…';
    const card = btn.closest('.cs-train-card');
    const badge = card ? card.querySelector('.cs-train-card__badge') : null;
    if (badge) {
      badge.textContent = 'training';
      badge.className = 'cs-train-card__badge cs-train-card__badge--training';
    }

    fetch(`/api/admin/training/trigger/${encodeURIComponent(modelType)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          btn.textContent = '✓ Submitted';
          if (badge) {
            badge.textContent = 'queued';
            badge.className = 'cs-train-card__badge cs-train-card__badge--queued';
          }
        } else {
          btn.textContent = '✗ Error';
          btn.title = data.error || 'Unknown error';
          if (badge) {
            badge.textContent = 'error';
            badge.className = 'cs-train-card__badge cs-train-card__badge--error';
          }
        }
      })
      .catch(() => {
        btn.textContent = '✗ Failed';
        if (badge) {
          badge.textContent = 'error';
          badge.className = 'cs-train-card__badge cs-train-card__badge--error';
        }
      })
      .finally(() => {
        setTimeout(() => { btn.disabled = false; btn.textContent = '▶ Train'; }, 5000);
      });
  }

  function loadTrainingDashboard() {
    const statsEl = document.getElementById('cs-training-stats');
    if (!statsEl) return;
    statsEl.innerHTML = '<div class="cs-admin-loading">Loading training data…</div>';

    fetch('/api/admin/training/stats')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) {
          statsEl.innerHTML = '<div class="cs-admin-loading">Training stats unavailable.</div>';
          return;
        }
        statsEl.innerHTML = renderGrid(data);

        // Wire trigger buttons
        statsEl.querySelectorAll('.cs-train-card__trigger').forEach(btn => {
          btn.addEventListener('click', () => triggerTraining(btn.dataset.model, btn));
        });
      })
      .catch(() => {
        statsEl.innerHTML = '<div class="cs-admin-loading">Training unavailable.</div>';
      });
  }

  // Expose for admin_overlay.js to call
  window.CosyTraining = { load: loadTrainingDashboard };

  // Also hook into tab activation if admin overlay fires a custom event
  document.addEventListener('cs-admin-tab', (e) => {
    if (e.detail && e.detail.tab === 'training') {
      loadTrainingDashboard();
    }
  });
})();
