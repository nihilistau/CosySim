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
