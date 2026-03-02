/**
 * Asset Studio — main frontend JS
 * Handles tab navigation, generation forms, library display, presets, settings.
 */
'use strict';

// ── SocketIO connection ───────────────────────────────────────────────────────

const socket = io();
socket.on('studio_health', (data) => updateHealth(data));
socket.on('asset_generated', (data) => onAssetGenerated(data));
socket.on('asset_error', (data) => toast(data.error || 'Generation failed', 'error'));

// ── State ─────────────────────────────────────────────────────────────────────

let _presets = [];
let _libOffset = 0;
const LIB_PAGE_SIZE = 40;
let _libTotal = 0;

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  loadPresets();
  loadLibrary();
  loadVoices();
  loadFlags();
  loadBackendStatus();
  bindForms();
  bindLibraryControls();
  bindSettings();
  initTuning();
});

// ── Tab navigation ────────────────────────────────────────────────────────────

function initTabs() {
  document.querySelectorAll('.cs-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
}

function switchTab(tabId) {
  document.querySelectorAll('.cs-tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabId);
    b.setAttribute('aria-selected', b.dataset.tab === tabId);
  });
  document.querySelectorAll('.cs-tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tabId}`);
  });
  // Reload relevant data when switching
  if (tabId === 'library') loadLibrary();
  if (tabId === 'settings') { loadFlags(); loadBackendStatus(); loadPresetList(); }
  if (tabId === 'voice') loadVoices();
  if (tabId === 'tuning') { loadTuningProfiles(); loadTuningMetrics(); loadTuningWorkflows(); }
}

// ── Presets ───────────────────────────────────────────────────────────────────

async function loadPresets() {
  try {
    const res = await fetch('/api/presets');
    const data = await res.json();
    _presets = data.presets || [];
    populatePresetSelects();
  } catch (e) {
    console.warn('loadPresets failed', e);
  }
}

function populatePresetSelects() {
  document.querySelectorAll('.cs-preset-select').forEach(sel => {
    const cur = sel.value;
    sel.innerHTML = _presets.map(p =>
      `<option value="${p.id}">${p.name}${p.builtin ? '' : ' ✦'}</option>`
    ).join('');
    if (cur) sel.value = cur;
  });
}

// ── Library ───────────────────────────────────────────────────────────────────

async function loadLibrary(reset = true) {
  if (reset) _libOffset = 0;
  const typeFilter = document.getElementById('lib-filter-type')?.value || '';
  const sceneFilter = document.getElementById('lib-filter-scene')?.value || '';
  const search = document.getElementById('lib-search')?.value || '';
  const favOnly = document.getElementById('lib-favorites-only')?.checked ? '1' : '';

  const params = new URLSearchParams({
    limit: LIB_PAGE_SIZE,
    offset: _libOffset,
    ...(typeFilter  && { type: typeFilter }),
    ...(sceneFilter && { scene: sceneFilter }),
    ...(search      && { search }),
    ...(favOnly     && { favorites: favOnly }),
  });

  const grid = document.getElementById('lib-grid');
  grid.innerHTML = '<div class="cs-grid-loading">Loading…</div>';

  try {
    const res = await fetch(`/api/library?${params}`);
    const data = await res.json();
    renderGrid(data.assets || []);
    renderStats(data.stats || {});
    _libTotal = (data.stats || {}).total || 0;
    updatePagination();
  } catch (e) {
    grid.innerHTML = '<div class="cs-grid-loading">Failed to load library</div>';
  }
}

function renderGrid(assets) {
  const grid = document.getElementById('lib-grid');
  if (!assets.length) {
    grid.innerHTML = '<div class="cs-grid-loading">No assets found</div>';
    return;
  }
  grid.innerHTML = assets.map(a => assetCardHTML(a)).join('');
}

function assetCardHTML(a) {
  const thumb = thumbHTML(a);
  const fav = a.favorite ? '★' : '☆';
  return `
    <div class="cs-asset-card ${a.favorite ? 'cs-asset-card--favorited' : ''}" data-id="${a.id}">
      ${thumb}
      <div class="cs-asset-info">
        <div class="cs-asset-title" title="${escapeHtml(a.title)}">${escapeHtml(a.title)}</div>
        <span class="cs-asset-type-badge">${a.asset_type}</span>
      </div>
      <div class="cs-asset-actions">
        <button class="cs-asset-btn" onclick="openAsset('${a.id}','${a.asset_type}','${escapeHtml(a.url)}')" title="View">👁</button>
        <button class="cs-asset-btn" onclick="downloadAsset('${escapeHtml(a.url)}','${a.asset_type}')" title="Download">⬇</button>
        <button class="cs-asset-btn" onclick="favoriteAsset('${a.id}')" title="Favorite">${fav}</button>
        <button class="cs-asset-btn cs-asset-btn--del" onclick="deleteAsset('${a.id}')" title="Delete">✕</button>
      </div>
    </div>`;
}

function thumbHTML(a) {
  const t = a.asset_type;
  if (t === 'voice' || t === 'audio') {
    const icon = t === 'voice' ? '🎙' : '♪';
    return `<div class="cs-asset-thumb cs-asset-thumb--${t}" style="height:120px">${icon}</div>`;
  }
  if (t === 'svg') {
    const svg = a.metadata?.svg_content || '';
    return `<div class="cs-asset-thumb cs-asset-thumb--svg" style="height:120px">${svg || '◇'}</div>`;
  }
  if (t === 'item') {
    const url = a.url || '/static/img/placeholder.png';
    return `<img class="cs-asset-thumb" src="${url}" alt="${escapeHtml(a.title)}" loading="lazy" style="height:120px;object-fit:cover">`;
  }
  if (a.url && a.url !== '/static/img/placeholder.png') {
    return `<img class="cs-asset-thumb" src="${a.url}" alt="${escapeHtml(a.title)}" loading="lazy" style="height:120px;object-fit:cover" onerror="this.src='/static/img/placeholder.png'">`;
  }
  return `<div class="cs-asset-thumb" style="height:120px;background:rgba(5,5,10,0.8);display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,0.2)">${t}</div>`;
}

function renderStats(stats) {
  const el = document.getElementById('lib-stats');
  if (!el) return;
  const byType = stats.by_type || {};
  const parts = Object.entries(byType).map(([k, v]) => `${k}: ${v}`).join(' · ');
  el.textContent = `Total: ${stats.total || 0} assets${parts ? ' · ' + parts : ''}`;
}

function updatePagination() {
  const prev = document.getElementById('lib-prev-btn');
  const next = document.getElementById('lib-next-btn');
  const info = document.getElementById('lib-page-info');
  const page = Math.floor(_libOffset / LIB_PAGE_SIZE) + 1;
  const total = Math.ceil(_libTotal / LIB_PAGE_SIZE) || 1;
  if (info) info.textContent = `Page ${page} / ${total}`;
  if (prev) prev.disabled = _libOffset === 0;
  if (next) next.disabled = _libOffset + LIB_PAGE_SIZE >= _libTotal;
}

function bindLibraryControls() {
  document.getElementById('lib-refresh-btn')?.addEventListener('click', () => loadLibrary());
  document.getElementById('lib-filter-type')?.addEventListener('change', () => loadLibrary());
  document.getElementById('lib-filter-scene')?.addEventListener('change', () => loadLibrary());
  document.getElementById('lib-favorites-only')?.addEventListener('change', () => loadLibrary());

  let searchTimer;
  document.getElementById('lib-search')?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadLibrary(), 350);
  });

  document.getElementById('lib-prev-btn')?.addEventListener('click', () => {
    _libOffset = Math.max(0, _libOffset - LIB_PAGE_SIZE);
    loadLibrary(false);
  });
  document.getElementById('lib-next-btn')?.addEventListener('click', () => {
    _libOffset += LIB_PAGE_SIZE;
    loadLibrary(false);
  });
}

// ── Asset actions ──────────────────────────────────────────────────────────────

window.openAsset = function(id, type, url) {
  if (type === 'voice' || type === 'audio') {
    const a = document.createElement('audio');
    a.controls = true;
    a.src = url;
    const win = window.open('', '_blank');
    win.document.body.style.background = '#000';
    win.document.body.style.display = 'flex';
    win.document.body.style.alignItems = 'center';
    win.document.body.style.justifyContent = 'center';
    win.document.body.style.minHeight = '100vh';
    win.document.body.appendChild(a);
    return;
  }
  if (url) window.open(url, '_blank');
};

window.downloadAsset = function(url, type) {
  if (!url) { toast('No file to download', 'error'); return; }
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  a.click();
};

window.favoriteAsset = async function(id) {
  const res = await fetch(`/api/library/${id}/favorite`, { method: 'POST' });
  const data = await res.json();
  toast(data.favorite ? '★ Favorited' : '☆ Unfavorited', 'info');
  loadLibrary(false);
};

window.deleteAsset = async function(id) {
  if (!confirm('Delete this asset?')) return;
  await fetch(`/api/library/${id}`, { method: 'DELETE' });
  toast('Deleted', 'info');
  loadLibrary(false);
};

// ── Generation forms ──────────────────────────────────────────────────────────

function bindForms() {
  // Images
  document.getElementById('img-generate-btn')?.addEventListener('click', async () => {
    const params = {
      asset_type: 'image',
      subject: document.getElementById('img-subject').value.trim(),
      scene: document.getElementById('img-scene').value,
      mood: document.getElementById('img-mood').value,
      preset_id: document.getElementById('img-preset').value,
      width: parseInt(document.getElementById('img-width').value) || 512,
      height: parseInt(document.getElementById('img-height').value) || 512,
      steps: parseInt(document.getElementById('img-steps').value) || 20,
      cfg_scale: parseFloat(document.getElementById('img-cfg').value) || 7.0,
      extra_positive: document.getElementById('img-extra-pos').value,
      extra_negative: document.getElementById('img-extra-neg').value,
    };
    if (!params.subject) { toast('Enter a subject description', 'error'); return; }
    const result = await generate(params);
    if (result && !result.error) showImagePreview('image-preview', result);
  });

  // Portraits
  document.getElementById('por-generate-btn')?.addEventListener('click', async () => {
    const charId = document.getElementById('por-char').value.trim();
    if (!charId) { toast('Enter a character ID', 'error'); return; }
    const params = {
      asset_type: 'portrait',
      character_id: charId,
      mood: document.getElementById('por-mood').value,
      scene: document.getElementById('por-scene').value,
      preset_id: document.getElementById('por-preset').value,
      width: parseInt(document.getElementById('por-width').value) || 512,
      height: parseInt(document.getElementById('por-height').value) || 768,
      adult_allowed: document.getElementById('por-adult').checked,
    };
    const result = await generate(params);
    if (result && !result.error) showImagePreview('portrait-preview', result);
  });

  // Voice
  document.getElementById('voice-generate-btn')?.addEventListener('click', async () => {
    const text = document.getElementById('voice-text').value.trim();
    if (!text) { toast('Enter text to synthesise', 'error'); return; }
    const params = {
      asset_type: 'voice',
      text,
      character_id: document.getElementById('voice-char').value.trim(),
      backend: document.getElementById('voice-backend').value,
      description: document.getElementById('voice-desc').value.trim(),
    };
    const result = await generate(params);
    if (result && result.url) showVoicePlayer('voice-player', 'voice-audio', 'voice-meta', result);
  });

  // Voice design save
  document.getElementById('vd-save-btn')?.addEventListener('click', async () => {
    const char = document.getElementById('vd-char').value.trim();
    const desc = document.getElementById('vd-desc').value.trim();
    if (!char || !desc) { toast('Fill in character ID and description', 'error'); return; }
    const res = await fetch('/api/voices/design', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: char, description: desc,
        model_size: document.getElementById('vd-size').value }),
    });
    const data = await res.json();
    toast(data.saved ? `Voice design saved for ${char}` : 'Save failed', data.saved ? 'success' : 'error');
    if (data.saved) loadVoices();
  });

  // Video
  document.getElementById('vid-generate-btn')?.addEventListener('click', async () => {
    const subject = document.getElementById('vid-subject').value.trim();
    if (!subject) { toast('Enter a scene description', 'error'); return; }
    const params = {
      asset_type: 'video',
      subject,
      scene: document.getElementById('vid-scene').value,
      mood: document.getElementById('vid-mood').value,
      motion: document.getElementById('vid-motion').value,
      frames: parseInt(document.getElementById('vid-frames').value) || 16,
      fps: parseInt(document.getElementById('vid-fps').value) || 8,
      preset_id: document.getElementById('vid-preset').value,
    };
    const result = await generate(params);
    if (result && result.url) {
      const preview = document.getElementById('video-preview');
      preview.innerHTML = `<video controls autoplay loop style="max-width:100%;border-radius:8px"><source src="${result.url}"></video>
        <div class="cs-preview-meta">Duration: ${result.duration_ms}ms | Frames: ${result.frames}</div>`;
    }
  });

  // Items
  document.getElementById('item-generate-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('item-name').value.trim();
    if (!name) { toast('Enter an item name', 'error'); return; }
    const params = {
      asset_type: 'item',
      item_name: name,
      archetype: document.getElementById('item-arch').value,
      scene: document.getElementById('item-scene').value,
      rarity: document.getElementById('item-rarity').value,
      generate_icon: document.getElementById('item-icon').checked,
      preset_id: document.getElementById('item-preset').value,
    };
    const result = await generate(params);
    if (result && result.item_data) showItemResult(result);
  });

  // SVG
  document.getElementById('svg-generate-btn')?.addEventListener('click', async () => {
    const subject = document.getElementById('svg-subject').value.trim();
    if (!subject) { toast('Enter a subject', 'error'); return; }
    const colorsRaw = document.getElementById('svg-colors').value.trim();
    const colors = colorsRaw ? colorsRaw.split(',').map(c => c.trim()).filter(Boolean) : null;
    const params = {
      asset_type: 'svg',
      subject,
      style: document.getElementById('svg-style').value,
      scene: document.getElementById('svg-scene').value,
      colors,
    };
    const result = await generate(params);
    if (result && result.svg_content) showSvgResult(result);
  });

  document.getElementById('svg-copy-btn')?.addEventListener('click', () => {
    const code = document.getElementById('svg-output-code')?.value;
    if (code) { navigator.clipboard.writeText(code); toast('SVG copied', 'success'); }
  });

  // Audio
  document.getElementById('aud-generate-btn')?.addEventListener('click', async () => {
    const params = {
      asset_type: 'audio',
      audio_type: document.getElementById('aud-type').value,
      scene: document.getElementById('aud-scene').value,
      duration: parseFloat(document.getElementById('aud-duration').value) || 5,
      description: document.getElementById('aud-desc').value.trim(),
    };
    const result = await generate(params);
    if (result && result.url) showVoicePlayer('audio-player', 'audio-element', 'audio-meta', result);
  });
}

// ── Generation helper ─────────────────────────────────────────────────────────

async function generate(params) {
  showSpinner(`Generating ${params.asset_type}…`);
  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    const data = await res.json();
    if (data.error) {
      toast(`Error: ${data.error}`, 'error');
      return null;
    }
    toast(`Generated in ${data.duration_ms || 0}ms`, 'success');
    // Refresh library count
    setTimeout(() => renderLibStats(), 500);
    return data;
  } catch (e) {
    toast(`Request failed: ${e.message}`, 'error');
    return null;
  } finally {
    hideSpinner();
  }
}

function onAssetGenerated(data) {
  if (!data.error && data.asset_type) {
    // Silently refresh library if library tab is active
    const libPanel = document.getElementById('tab-library');
    if (libPanel?.classList.contains('active')) loadLibrary(false);
  }
}

// ── Preview helpers ────────────────────────────────────────────────────────────

function showImagePreview(containerId, result) {
  const c = document.getElementById(containerId);
  if (!c) return;
  const url = result.url || '/static/img/placeholder.png';
  c.innerHTML = `
    <img src="${url}" alt="Generated" style="max-width:100%;max-height:560px;border-radius:8px"
      onerror="this.src='/static/img/placeholder.png'">
    <div class="cs-preview-meta">
      ${url !== '/static/img/placeholder.png' ? `<a href="${url}" target="_blank" class="cs-btn cs-btn--ghost" style="font-size:0.68rem;padding:4px 10px">⬇ Open</a>` : ''}
      ${result.duration_ms ? ` · ${result.duration_ms}ms` : ''}
      ${result.cached ? ' · (cached)' : ''}
    </div>`;
}

function showVoicePlayer(playerId, audioId, metaId, result) {
  const player = document.getElementById(playerId);
  const audio = document.getElementById(audioId);
  const meta = document.getElementById(metaId);
  if (!player || !audio) return;
  player.style.display = 'block';
  audio.src = result.url;
  audio.load();
  if (meta) meta.textContent = `Backend: ${result.backend || 'unknown'} · ${result.duration_ms || 0}ms`;
}

function showItemResult(result) {
  const c = document.getElementById('item-result');
  if (!c) return;
  const d = result.item_data || {};
  const rarity = d.rarity || 'common';
  const stats = Object.entries(d.stats || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'No stats';
  c.innerHTML = `
    <div class="cs-item-card">
      <img class="cs-item-icon" src="${result.icon_url || '/static/img/placeholder.png'}"
        alt="${escapeHtml(d.name || '')}" onerror="this.src='/static/img/placeholder.png'">
      <div class="cs-item-details">
        <div class="cs-item-name">${escapeHtml(d.name || 'Unknown Item')}</div>
        <div class="cs-item-rarity-${rarity}">${rarity.toUpperCase()}</div>
        <div class="cs-item-desc">${escapeHtml(d.description || '')}</div>
        <div class="cs-item-stats">${escapeHtml(stats)}</div>
        <div class="cs-item-lore">${escapeHtml(d.lore || '')}</div>
      </div>
    </div>`;
}

function showSvgResult(result) {
  const c = document.getElementById('svg-result');
  const codeBlock = document.getElementById('svg-code-block');
  const codeArea = document.getElementById('svg-output-code');
  const dl = document.getElementById('svg-download-btn');
  if (!c) return;

  // Insert SVG preview
  let previewBox = c.querySelector('.cs-svg-preview-box');
  if (!previewBox) {
    previewBox = document.createElement('div');
    previewBox.className = 'cs-svg-preview-box';
    c.insertBefore(previewBox, c.firstChild);
  }
  previewBox.innerHTML = result.svg_content || '<span style="color:rgba(255,255,255,0.2)">No SVG</span>';

  if (codeBlock) codeBlock.style.display = 'block';
  if (codeArea) codeArea.value = result.svg_content || '';
  if (dl && result.url) {
    dl.href = result.url;
  }
}

async function renderLibStats() {
  try {
    const res = await fetch('/api/library?limit=1&offset=0');
    const data = await res.json();
    renderStats(data.stats || {});
  } catch (e) { /* ignore */ }
}

// ── Voices ────────────────────────────────────────────────────────────────────

async function loadVoices() {
  try {
    const res = await fetch('/api/voices');
    const data = await res.json();
    renderVoiceList(data);
  } catch (e) {
    const el = document.getElementById('voice-list-content');
    if (el) el.textContent = 'Could not load voices';
  }
}

function renderVoiceList(data) {
  const el = document.getElementById('voice-list-content');
  if (!el) return;
  let html = '';
  for (const [backend, voices] of Object.entries(data)) {
    if (!voices.length) continue;
    html += `<div style="margin-bottom:8px;font-size:0.65rem;text-transform:uppercase;color:rgba(255,255,255,0.3);letter-spacing:0.1em">${backend}</div>`;
    for (const v of voices) {
      html += `<div class="cs-voice-entry">
        <div><span class="cs-voice-entry-name">${escapeHtml(v.id)}</span></div>
        <span class="cs-voice-entry-meta">${escapeHtml(v.description?.slice(0, 40) || '')}</span>
      </div>`;
    }
  }
  el.innerHTML = html || 'No voices registered';
}

// ── Health / status ───────────────────────────────────────────────────────────

function updateHealth(data) {
  const dot = document.getElementById('studio-status-dot');
  const text = document.getElementById('studio-status-text');
  if (!dot) return;

  const backends = data.backends || {};
  const statuses = Object.values(backends).map(b => b.status);
  const allOnline = statuses.every(s => s === 'online');
  const anyOnline = statuses.some(s => s === 'online');

  dot.className = 'cs-status-dot ' + (
    statuses.length === 0 ? '' :
    allOnline ? 'online' :
    anyOnline ? 'partial' : 'offline'
  );
  if (text) text.textContent = allOnline ? 'Online' : anyOnline ? 'Partial' : 'Offline';
}

async function loadBackendStatus() {
  try {
    const res = await fetch('/api/studio/health');
    const data = await res.json();
    updateHealth(data);
    renderBackendStatus(data.backends || {});
  } catch (e) { /* ignore */ }
}

function renderBackendStatus(backends) {
  const el = document.getElementById('backend-status-list');
  if (!el) return;
  if (!Object.keys(backends).length) { el.textContent = 'No backends checked'; return; }
  el.innerHTML = Object.entries(backends).map(([name, info]) => {
    const cls = `cs-backend-${info.status || 'unknown'}`;
    const detail = info.error ? ` — ${escapeHtml(info.error.slice(0, 60))}` : '';
    return `<div class="cs-backend-row">
      <span class="cs-backend-name">${name}</span>
      <span class="${cls}">${info.status || 'unknown'}${detail}</span>
    </div>`;
  }).join('');
}

// ── Feature Flags ─────────────────────────────────────────────────────────────

const FLAG_LABELS = {
  'asset_studio.comfyui_enabled':     { label: 'ComfyUI (Images/Portraits/Video)', desc: 'Enable ComfyUI image generation' },
  'asset_studio.tts_enabled':         { label: 'TTS (Voice)', desc: 'Enable text-to-speech generation' },
  'asset_studio.lms_enabled':         { label: 'LMStudio (Items/SVG)', desc: 'Enable LLM-assisted generation' },
  'asset_studio.video_enabled':       { label: 'AnimateDiff (Video)', desc: 'Enable animated video clips' },
  'asset_studio.nexus_cache_enabled': { label: 'Nexus Cache', desc: 'Store asset metadata in Nexus' },
  'asset_studio.adult_enabled':       { label: 'Adult Content', desc: 'Allow suggestive content in prompts' },
};

async function loadFlags() {
  try {
    const res = await fetch('/api/flags');
    const data = await res.json();
    renderFlags(data);
  } catch (e) { /* ignore */ }
}

function renderFlags(flags) {
  const el = document.getElementById('flags-list');
  if (!el) return;
  el.innerHTML = Object.entries(flags).map(([key, val]) => {
    const meta = FLAG_LABELS[key] || { label: key, desc: '' };
    const checked = val ? 'checked' : '';
    return `<div class="cs-flag-row">
      <div>
        <div class="cs-flag-name">${meta.label}</div>
        <div class="cs-flag-desc">${meta.desc}</div>
      </div>
      <label class="cs-switch" title="${key}">
        <input type="checkbox" data-flag="${key}" ${checked} onchange="setFlag('${key}', this.checked)">
        <span class="cs-switch-slider"></span>
      </label>
    </div>`;
  }).join('');
}

window.setFlag = async function(key, value) {
  try {
    await fetch('/api/flags', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value }),
    });
    toast(`${key} = ${value}`, 'info');
  } catch (e) {
    toast('Failed to update flag', 'error');
  }
};

// ── Preset manager (settings tab) ─────────────────────────────────────────────

async function loadPresetList() {
  const el = document.getElementById('preset-list');
  if (!el) return;
  try {
    const res = await fetch('/api/presets');
    const data = await res.json();
    _presets = data.presets || [];
    populatePresetSelects();
    el.innerHTML = _presets.map(p => {
      const del = p.builtin ? '' :
        `<button class="cs-preset-delete-btn" onclick="deletePreset('${p.id}')">✕</button>`;
      return `<span class="cs-preset-chip ${p.builtin ? '' : 'cs-preset-chip--custom'}">
        ${escapeHtml(p.name)}${del}
      </span>`;
    }).join('');
  } catch (e) { el.textContent = 'Failed to load presets'; }
}

window.deletePreset = async function(id) {
  if (!confirm(`Delete preset "${id}"?`)) return;
  await fetch(`/api/presets/${id}`, { method: 'DELETE' });
  toast('Preset deleted', 'info');
  loadPresetList();
  loadPresets();
};

function bindSettings() {
  document.getElementById('settings-refresh-btn')?.addEventListener('click', loadBackendStatus);

  document.getElementById('preset-save-btn')?.addEventListener('click', async () => {
    const id = document.getElementById('preset-id-input').value.trim();
    const name = document.getElementById('preset-name-input').value.trim();
    if (!id || !name) { toast('Preset ID and Name are required', 'error'); return; }

    const tagsRaw = document.getElementById('preset-tags-input').value;
    const negRaw  = document.getElementById('preset-neg-input').value;

    const payload = {
      id,
      name,
      description: document.getElementById('preset-desc-input').value.trim(),
      style_tags: tagsRaw.split(',').map(s => s.trim()).filter(Boolean),
      negative_tags: negRaw.split(',').map(s => s.trim()).filter(Boolean),
      width:  parseInt(document.getElementById('preset-w').value) || 512,
      height: parseInt(document.getElementById('preset-h').value) || 768,
      steps:  parseInt(document.getElementById('preset-steps').value) || 20,
      cfg_scale: parseFloat(document.getElementById('preset-cfg').value) || 7.0,
    };

    try {
      const res = await fetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.error) { toast(data.error, 'error'); return; }
      toast(`Preset "${name}" saved`, 'success');
      loadPresetList();
      loadPresets();
    } catch (e) {
      toast('Failed to save preset', 'error');
    }
  });
}

// ── Spinner ────────────────────────────────────────────────────────────────────

function showSpinner(label = 'Generating…') {
  const s = document.getElementById('gen-spinner');
  const l = document.getElementById('gen-spinner-label');
  if (s) s.style.display = 'flex';
  if (l) l.textContent = label;
}

function hideSpinner() {
  const s = document.getElementById('gen-spinner');
  if (s) s.style.display = 'none';
}

// ── Toast ──────────────────────────────────────────────────────────────────────

function toast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `cs-toast cs-toast--${type}`;
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => { el.classList.add('show'); });
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 250);
  }, 3500);
}

// ── Utilities ──────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Tuning & Benchmarking ─────────────────────────────────────────────────────

let _tuningSelectedProfile = null;
let _tuningCurrentJob = null;
let _tuningResults = [];
let _elapsedTimer = null;
let _jobStartTime = null;

function initTuning() {
  document.getElementById('tuning-add-sweep-btn')?.addEventListener('click', addSweepRow);
  document.getElementById('tuning-run-btn')?.addEventListener('click', runBenchmark);
  document.getElementById('tuning-cancel-btn')?.addEventListener('click', cancelBenchmark);
  document.getElementById('tuning-apply-best-btn')?.addEventListener('click', applyBestToForms);
  document.getElementById('tuning-export-btn')?.addEventListener('click', exportResultsCSV);
  document.getElementById('tuning-save-profile-btn')?.addEventListener('click', saveCurrentAsProfile);
  document.getElementById('tuning-delete-profile-btn')?.addEventListener('click', deleteSelectedProfile);
  document.getElementById('tuning-metrics-refresh')?.addEventListener('click', loadTuningMetrics);
  document.getElementById('tuning-metrics-workflow')?.addEventListener('change', loadTuningMetrics);

  // Update variant count when sweep changes
  document.getElementById('tuning-sweep-rows')?.addEventListener('input', updateVariantCount);

  // Socket.IO progress
  socket.on('tuning_progress', onTuningProgress);
}

// ── Workflow list ─────────────────────────────────────────────────────────────

async function loadTuningWorkflows() {
  try {
    const res = await fetch('/api/workflows');
    const data = await res.json();
    const sel = document.getElementById('tuning-workflow');
    if (!sel) return;
    sel.innerHTML = (data.workflows || []).map(w =>
      `<option value="${w.id}">${w.label}</option>`
    ).join('');
    // Also populate metrics workflow filter
    const mSel = document.getElementById('tuning-metrics-workflow');
    if (mSel) {
      mSel.innerHTML = '<option value="">All Workflows</option>' +
        (data.workflows || []).map(w => `<option value="${w.id}">${w.label}</option>`).join('');
    }
  } catch(e) { console.warn('loadTuningWorkflows failed', e); }
}

// ── Profiles ──────────────────────────────────────────────────────────────────

async function loadTuningProfiles() {
  try {
    const res = await fetch('/api/tuning/profiles');
    const data = await res.json();
    renderTuningProfiles(data.profiles || []);
  } catch(e) {
    const el = document.getElementById('tuning-profiles-list');
    if (el) el.textContent = 'Could not load profiles';
  }
}

function renderTuningProfiles(profiles) {
  const el = document.getElementById('tuning-profiles-list');
  if (!el) return;
  if (!profiles.length) { el.textContent = 'No profiles'; return; }
  el.innerHTML = profiles.map(p => `
    <div class="cs-profile-item ${p.builtin ? 'cs-profile-item--builtin' : ''} ${_tuningSelectedProfile === (p.profile_id || p.workflow) ? 'cs-profile-item--selected' : ''}"
         data-profile-id="${p.profile_id || p.workflow}"
         onclick="selectTuningProfile('${p.profile_id || p.workflow}')">
      <span class="cs-profile-icon">${p.builtin ? '&#9889;' : '&#10022;'}</span>
      <div class="cs-profile-info">
        <div class="cs-profile-label">${escapeHtml(p.label || p.profile_id || '')}</div>
        <div class="cs-profile-desc">${escapeHtml((p.description || '').slice(0, 70))}</div>
      </div>
      ${p.vl_score != null ? `<span class="cs-profile-badge">VL ${p.vl_score.toFixed(1)}</span>` : ''}
      ${p.builtin ? '' : `<span class="cs-profile-badge" style="background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.3)">custom</span>`}
    </div>
  `).join('');
}

function selectTuningProfile(profileId) {
  _tuningSelectedProfile = profileId;
  document.querySelectorAll('.cs-profile-item').forEach(el => {
    el.classList.toggle('cs-profile-item--selected', el.dataset.profileId === profileId);
  });
  // Load profile params into form
  fetch(`/api/tuning/profiles/${profileId}`)
    .then(r => r.json())
    .then(data => {
      const p = data.profile;
      if (!p) return;
      const params = p.params || {};

      // Set workflow selector
      const wfSel = document.getElementById('tuning-workflow');
      if (wfSel && (p.workflow || p.workflow_id)) {
        wfSel.value = p.workflow || p.workflow_id;
      }
      // Apply params to form fields
      if (params.steps !== undefined) setVal('tuning-steps', params.steps);
      if (params.cfg !== undefined) setVal('tuning-cfg', params.cfg);
      if (params.sampler_name) setVal('tuning-sampler', params.sampler_name);
      if (params.scheduler) setVal('tuning-scheduler', params.scheduler);
      if (params.width !== undefined) setVal('tuning-width', params.width);
      if (params.height !== undefined) setVal('tuning-height', params.height);

      // Set prompt from profile source hint
      const promptEl = document.getElementById('tuning-prompt');
      if (promptEl && !promptEl.value) {
        promptEl.value = 'masterpiece, best quality, portrait photograph, sharp focus, cinematic lighting';
      }

      toast(`Profile loaded: ${p.label || profileId}`, 'success');

      // Enable delete for custom profiles
      const delBtn = document.getElementById('tuning-delete-profile-btn');
      if (delBtn) delBtn.disabled = !!p.builtin;
      const saveBtn = document.getElementById('tuning-save-profile-btn');
      if (saveBtn) saveBtn.disabled = false;
    })
    .catch(e => toast('Failed to load profile: ' + e.message, 'error'));
}

async function saveCurrentAsProfile() {
  const profileId = prompt('Enter profile ID (slug, no spaces):');
  if (!profileId) return;
  const label = prompt('Profile label:') || profileId;
  const workflow_id = document.getElementById('tuning-workflow')?.value || 'portrait_fast';
  const params = gatherBaseParams();
  try {
    const res = await fetch('/api/tuning/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: profileId, label, workflow_id, description: '', params }),
    });
    const data = await res.json();
    if (data.error) { toast(data.error, 'error'); return; }
    toast(`Saved profile: ${label}`, 'success');
    loadTuningProfiles();
  } catch(e) { toast('Save failed: ' + e.message, 'error'); }
}

async function deleteSelectedProfile() {
  if (!_tuningSelectedProfile) return;
  if (!confirm(`Delete profile "${_tuningSelectedProfile}"?`)) return;
  await fetch(`/api/tuning/profiles/${_tuningSelectedProfile}`, { method: 'DELETE' });
  toast('Profile deleted', 'info');
  _tuningSelectedProfile = null;
  loadTuningProfiles();
}

// ── Sweep config ──────────────────────────────────────────────────────────────

function addSweepRow() {
  const container = document.getElementById('tuning-sweep-rows');
  if (!container) return;
  const id = 'sweep-' + Date.now();
  const row = document.createElement('div');
  row.className = 'cs-sweep-row';
  row.id = id;
  row.innerHTML = `
    <select class="cs-select cs-select--sm sweep-param-name">
      <option value="cfg">cfg</option>
      <option value="steps">steps</option>
      <option value="sampler_name">sampler</option>
      <option value="scheduler">scheduler</option>
      <option value="denoise">denoise</option>
      <option value="width">width</option>
      <option value="height">height</option>
    </select>
    <input type="text" class="cs-input cs-input--sm sweep-param-values"
      placeholder="1.0, 1.5, 2.0">
    <button class="cs-btn cs-btn--ghost cs-btn--sm" onclick="document.getElementById('${id}').remove(); updateVariantCount()">&#10005;</button>
  `;
  container.appendChild(row);
  updateVariantCount();
}

function updateVariantCount() {
  const sweep = buildSweep();
  let count = 1;
  for (const vals of Object.values(sweep)) count *= vals.length;
  const el = document.getElementById('tuning-variant-count');
  if (el) {
    el.textContent = count === 1
      ? 'Variants: 1 (no sweep)'
      : `Variants: ${count} (${Object.keys(sweep).map(k => `${k}\u00d7${sweep[k].length}`).join(', ')})`;
    el.style.color = count > 10 ? '#f87171' : count > 5 ? '#fbbf24' : 'rgba(255,255,255,0.4)';
  }
}

function buildSweep() {
  const sweep = {};
  document.querySelectorAll('.cs-sweep-row').forEach(row => {
    const name = row.querySelector('.sweep-param-name')?.value;
    const raw = row.querySelector('.sweep-param-values')?.value || '';
    if (!name || !raw.trim()) return;
    const values = raw.split(',').map(v => {
      const t = v.trim();
      const n = parseFloat(t);
      return isNaN(n) ? t : n;
    }).filter(v => v !== '' && v !== null);
    if (values.length) sweep[name] = values;
  });
  return sweep;
}

function gatherBaseParams() {
  return {
    steps:        parseInt(document.getElementById('tuning-steps')?.value) || 20,
    cfg:          parseFloat(document.getElementById('tuning-cfg')?.value) || 1.5,
    sampler_name: document.getElementById('tuning-sampler')?.value || 'lcm',
    scheduler:    document.getElementById('tuning-scheduler')?.value || 'exponential',
    width:        parseInt(document.getElementById('tuning-width')?.value) || 512,
    height:       parseInt(document.getElementById('tuning-height')?.value) || 512,
    batch_size:   parseInt(document.getElementById('tuning-batch')?.value) || 1,
  };
}

// ── Run benchmark ─────────────────────────────────────────────────────────────

async function runBenchmark() {
  const workflow_id = document.getElementById('tuning-workflow')?.value;
  const prompt = document.getElementById('tuning-prompt')?.value?.trim();
  if (!workflow_id) { toast('Select a workflow', 'error'); return; }
  if (!prompt) { toast('Enter a test prompt', 'error'); return; }

  const base_params = gatherBaseParams();
  const sweep = buildSweep();

  // Validate max variants
  let variantCount = 1;
  for (const vals of Object.values(sweep)) variantCount *= vals.length;
  if (variantCount > 20) { toast('Max 20 variants. Reduce sweep range.', 'error'); return; }

  _tuningResults = [];
  renderResultsTable([]);
  showTuningSection('progress', true);
  showTuningSection('results', true);

  // Start elapsed timer
  _jobStartTime = Date.now();
  startElapsedTimer();

  document.getElementById('tuning-run-btn').style.display = 'none';
  document.getElementById('tuning-cancel-btn').style.display = 'inline-flex';
  setLiveMetric('lm-status', 'starting\u2026', '#fbbf24');

  try {
    const res = await fetch('/api/tuning/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workflow_id, prompt, base_params, sweep,
        use_vl_qc: document.getElementById('tuning-use-vl')?.checked !== false,
      }),
    });
    const data = await res.json();
    if (data.error) { toast(data.error, 'error'); resetRunButtons(); return; }
    _tuningCurrentJob = data.job_id;
    setLiveMetric('lm-status', `running (${data.variants} variants)`, '#34d399');
  } catch(e) {
    toast('Failed to start benchmark: ' + e.message, 'error');
    resetRunButtons();
  }
}

async function cancelBenchmark() {
  await fetch('/api/tuning/cancel', { method: 'POST' });
  stopElapsedTimer();
  setLiveMetric('lm-status', 'cancelling\u2026', '#f87171');
}

function onTuningProgress(job) {
  if (!job) return;
  _tuningCurrentJob = job.job_id || _tuningCurrentJob;

  const done = job.current_variant || 0;
  const total = job.total_variants || 1;
  const pct = total > 0 ? (done / total) * 100 : 0;

  // Progress bar
  const bar = document.getElementById('tuning-progress-bar');
  if (bar) bar.style.width = pct.toFixed(1) + '%';

  // Live metrics
  setLiveMetric('lm-variant', `${done} / ${total}`);
  if (job.eta_ms > 0) setLiveMetric('lm-eta', fmtTime(job.eta_ms), '#fbbf24');

  // Avg time
  const variants = job.variants || [];
  const doneV = variants.filter(v => v.status === 'done');
  if (doneV.length > 0) {
    const avg = doneV.reduce((s, v) => s + (v.gen_time_ms || 0), 0) / doneV.length;
    setLiveMetric('lm-avg-time', (avg / 1000).toFixed(1) + 's');
  }

  // Running detail
  const currentV = variants[done - 1] || variants.find(v => v.status === 'running');
  const detailEl = document.getElementById('tuning-running-detail');
  if (detailEl && currentV) {
    const p = currentV.params || {};
    detailEl.textContent = `\u25b6 ${currentV.variant_id} \u2014 cfg=${p.cfg} steps=${p.steps} sampler=${p.sampler_name || '\u2014'} scheduler=${p.scheduler || '\u2014'}`;
  }

  // Status
  const statusColor = { running: '#34d399', done: '#f59e0b', cancelled: '#f87171', failed: '#f87171' };
  setLiveMetric('lm-status', job.status, statusColor[job.status] || '#fff');

  // Render results table incrementally
  if (variants.length) {
    _tuningResults = variants;
    renderResultsTable(variants, job.best_variant_id);
  }

  if (['done', 'cancelled', 'failed'].includes(job.status)) {
    stopElapsedTimer();
    resetRunButtons();
    if (job.status === 'done') {
      toast(`Benchmark complete. ${doneV.length} variants done.`, 'success');
      loadTuningMetrics();
    }
    if (job.best_variant_id) {
      const btn = document.getElementById('tuning-apply-best-btn');
      if (btn) btn.disabled = false;
    }
  }
}

function renderResultsTable(variants, bestId) {
  const tbody = document.getElementById('tuning-results-body');
  if (!tbody) return;
  showTuningSection('results', true);

  tbody.innerHTML = variants.map((v, i) => {
    const p = v.params || {};
    const isBest = v.variant_id === bestId;
    const score = v.vl_score >= 0 ? v.vl_score : null;
    const scoreBadge = score != null
      ? `<span class="cs-score-badge ${score >= 7 ? 'cs-score-badge--high' : score >= 5 ? 'cs-score-badge--mid' : 'cs-score-badge--low'}">${score.toFixed(1)}</span>`
      : `<span class="cs-score-badge cs-score-badge--none">${v.status === 'running' ? '\u2026' : '\u2014'}</span>`;

    const thumb = v.image_path
      ? `<img class="cs-result-thumb" src="${v.image_path}" alt="result" onclick="window.open('${v.image_path}','_blank')" onerror="this.style.display='none'">`
      : `<div class="cs-result-thumb--placeholder">${v.status === 'running' ? '\u2026' : '?'}</div>`;

    const timeStr = v.gen_time_ms ? (v.gen_time_ms / 1000).toFixed(1) + 's' : '\u2014';
    const statusColor = { done: '#34d399', failed: '#f87171', running: '#fbbf24', pending: 'rgba(255,255,255,0.3)' };

    return `
      <tr class="${isBest ? 'cs-row--best' : ''}" data-vid="${v.variant_id}">
        <td>${isBest ? '&#9733;' : i + 1}</td>
        <td>${thumb}</td>
        <td>${p.steps ?? '\u2014'}</td>
        <td>${p.cfg ?? '\u2014'}</td>
        <td>${p.sampler_name || '\u2014'}</td>
        <td>${p.scheduler || '\u2014'}</td>
        <td>${timeStr}</td>
        <td>${scoreBadge}</td>
        <td style="color:${statusColor[v.status] || '#fff'}">${v.status}</td>
        <td>
          ${v.vl_score >= 0 ? `<button class="cs-btn cs-btn--ghost cs-btn--sm" onclick="showVLDetail('${v.variant_id}')">&#128203; VL</button>` : ''}
          ${v.status === 'done' && v.params ? `<button class="cs-btn cs-btn--ghost cs-btn--sm" onclick="applyVariantToForms('${v.variant_id}')">&#8593; Apply</button>` : ''}
        </td>
      </tr>`;
  }).join('');
}

window.showVLDetail = function(variantId) {
  const v = _tuningResults.find(x => x.variant_id === variantId);
  if (!v) return;
  const el = document.getElementById('tuning-vl-detail');
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML = `
    <h4>VL Quality Report \u2014 ${variantId} (score: ${v.vl_score?.toFixed(1) ?? '\u2014'}/10)</h4>
    ${v.vl_strengths?.length ? `<div class="cs-vl-strengths">&#10003; ${v.vl_strengths.join(' \u00b7 ')}</div>` : ''}
    ${v.vl_issues?.length ? `<div class="cs-vl-issues">&#10007; ${v.vl_issues.join(' \u00b7 ')}</div>` : ''}
    ${v.vl_suggestion ? `<div class="cs-vl-suggestion">"${escapeHtml(v.vl_suggestion)}"</div>` : ''}
  `;
};

window.applyVariantToForms = function(variantId) {
  const v = _tuningResults.find(x => x.variant_id === variantId);
  if (!v?.params) return;
  applyParamsToForms(v.params);
  toast(`Applied settings from ${variantId} to generation forms`, 'success');
};

function applyBestToForms() {
  const best = _tuningResults.filter(v => v.vl_score >= 0).sort((a, b) => b.vl_score - a.vl_score)[0];
  if (!best?.params) { toast('No best result yet', 'error'); return; }
  applyParamsToForms(best.params);
  toast(`Best settings (VL ${best.vl_score?.toFixed(1)}) applied to generation forms`, 'success');
}

function applyParamsToForms(params) {
  // Apply to image form
  if (params.steps !== undefined) { setVal('img-steps', params.steps); }
  if (params.cfg !== undefined) { setVal('img-cfg', params.cfg); }
  if (params.width !== undefined) { setVal('img-width', params.width); setVal('por-width', params.width); }
  if (params.height !== undefined) { setVal('img-height', params.height); setVal('por-height', params.height); }
}

function exportResultsCSV() {
  if (!_tuningResults.length) { toast('No results to export', 'error'); return; }
  const headers = ['variant_id','steps','cfg','sampler_name','scheduler','width','height','gen_time_ms','vl_score','status','strengths','issues'];
  const rows = _tuningResults.map(v => {
    const p = v.params || {};
    return [
      v.variant_id, p.steps, p.cfg, p.sampler_name, p.scheduler, p.width, p.height,
      v.gen_time_ms, v.vl_score >= 0 ? v.vl_score.toFixed(2) : '',
      v.status, (v.vl_strengths||[]).join(';'), (v.vl_issues||[]).join(';'),
    ].map(x => `"${x ?? ''}"`).join(',');
  });
  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `benchmark_${Date.now()}.csv`;
  a.click();
  toast('CSV exported', 'success');
}

// ── Metrics history ───────────────────────────────────────────────────────────

async function loadTuningMetrics() {
  const wf = document.getElementById('tuning-metrics-workflow')?.value || '';
  try {
    const params = new URLSearchParams({ limit: 50 });
    if (wf) params.set('workflow_id', wf);
    const res = await fetch(`/api/tuning/metrics?${params}`);
    const data = await res.json();
    renderMetricsSummary(data.summary || {});
    renderMetricsTable(data.runs || []);
    drawSparkline(data.sparkline || []);
  } catch(e) { console.warn('loadTuningMetrics failed', e); }
}

function renderMetricsSummary(summary) {
  const el = document.getElementById('tuning-metrics-summary');
  if (!el) return;
  const fmt = (v, decimals = 1) => v != null ? Number(v).toFixed(decimals) : '\u2014';
  el.innerHTML = `
    <div class="cs-metric-card">
      <div class="cs-metric-card-label">Total Runs</div>
      <div class="cs-metric-card-value">${summary.total_runs || 0}</div>
    </div>
    <div class="cs-metric-card">
      <div class="cs-metric-card-label">Avg VL Score</div>
      <div class="cs-metric-card-value">${fmt(summary.avg_score)}</div>
    </div>
    <div class="cs-metric-card">
      <div class="cs-metric-card-label">Best Score</div>
      <div class="cs-metric-card-value" style="color:#34d399">${fmt(summary.best_score)}</div>
    </div>
    <div class="cs-metric-card">
      <div class="cs-metric-card-label">Avg Time</div>
      <div class="cs-metric-card-value">${summary.avg_time_ms ? (summary.avg_time_ms/1000).toFixed(1)+'s' : '\u2014'}</div>
    </div>
    <div class="cs-metric-card">
      <div class="cs-metric-card-label">Fastest</div>
      <div class="cs-metric-card-value">${summary.fastest_ms ? (summary.fastest_ms/1000).toFixed(1)+'s' : '\u2014'}</div>
    </div>
  `;
}

function renderMetricsTable(runs) {
  const tbody = document.getElementById('tuning-metrics-body');
  if (!tbody) return;
  if (!runs.length) { tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:rgba(255,255,255,0.3);padding:16px">No runs yet</td></tr>'; return; }
  tbody.innerHTML = runs.map(r => {
    const p = r.params || {};
    const score = r.vl_score != null ? r.vl_score.toFixed(1) : '\u2014';
    const date = r.created_at ? new Date(r.created_at * 1000).toLocaleDateString() : '\u2014';
    return `<tr>
      <td>${escapeHtml(r.workflow_id || '')}</td>
      <td>${p.steps ?? '\u2014'}</td>
      <td>${p.cfg ?? '\u2014'}</td>
      <td>${p.sampler_name || '\u2014'}</td>
      <td>${r.gen_time_ms ? (r.gen_time_ms/1000).toFixed(1)+'s' : '\u2014'}</td>
      <td>${r.vl_score != null ? `<span class="cs-score-badge ${r.vl_score >= 7 ? 'cs-score-badge--high' : r.vl_score >= 5 ? 'cs-score-badge--mid' : 'cs-score-badge--low'}">${score}</span>` : '<span class="cs-score-badge cs-score-badge--none">\u2014</span>'}</td>
      <td>${date}</td>
    </tr>`;
  }).join('');
}

function drawSparkline(scores) {
  const canvas = document.getElementById('tuning-sparkline');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  if (!scores.length) {
    ctx.fillStyle = 'rgba(255,255,255,0.1)';
    ctx.font = '11px monospace';
    ctx.fillText('No data yet', 10, H/2 + 4);
    return;
  }

  const max = 10, min = 0;
  const range = max - min;
  const padX = 8, padY = 8;
  const plotW = W - padX * 2, plotH = H - padY * 2;

  // Grid line at 5 and 8
  [5, 8].forEach(v => {
    const y = padY + plotH - ((v - min) / range) * plotH;
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth = 1;
    ctx.moveTo(padX, y);
    ctx.lineTo(W - padX, y);
    ctx.stroke();
  });

  // Area fill
  ctx.beginPath();
  scores.forEach((s, i) => {
    const x = padX + (i / Math.max(scores.length - 1, 1)) * plotW;
    const y = padY + plotH - ((s - min) / range) * plotH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.lineTo(padX + plotW, padY + plotH);
  ctx.lineTo(padX, padY + plotH);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, padY, 0, padY + plotH);
  grad.addColorStop(0, 'rgba(245, 158, 11, 0.3)');
  grad.addColorStop(1, 'rgba(245, 158, 11, 0.02)');
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  scores.forEach((s, i) => {
    const x = padX + (i / Math.max(scores.length - 1, 1)) * plotW;
    const y = padY + plotH - ((s - min) / range) * plotH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#f59e0b';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Dots
  scores.forEach((s, i) => {
    const x = padX + (i / Math.max(scores.length - 1, 1)) * plotW;
    const y = padY + plotH - ((s - min) / range) * plotH;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = s >= 8 ? '#34d399' : s >= 6 ? '#f59e0b' : '#f87171';
    ctx.fill();
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function setLiveMetric(id, val, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = val;
  if (color) el.style.color = color;
}

function showTuningSection(name, show) {
  const el = document.getElementById(`tuning-${name}-section`);
  if (el) el.style.display = show ? '' : 'none';
}

function fmtTime(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
}

function startElapsedTimer() {
  stopElapsedTimer();
  _elapsedTimer = setInterval(() => {
    if (!_jobStartTime) return;
    const el = document.getElementById('lm-elapsed');
    if (el) el.textContent = fmtTime(Date.now() - _jobStartTime);
  }, 1000);
}

function stopElapsedTimer() {
  if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
}

function resetRunButtons() {
  const runBtn = document.getElementById('tuning-run-btn');
  const cancelBtn = document.getElementById('tuning-cancel-btn');
  if (runBtn) runBtn.style.display = '';
  if (cancelBtn) cancelBtn.style.display = 'none';
}
