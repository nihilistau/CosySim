/* System Control Panel — JavaScript */
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let currentConfigFile = null;
let currentLogFile = null;
const BASE = '';

// ── Tab navigation ─────────────────────────────────────────────────────────
document.querySelectorAll('.sc-nav-item').forEach(item => {
  item.addEventListener('click', () => {
    const tab = item.dataset.tab;
    document.querySelectorAll('.sc-nav-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.sc-tab').forEach(t => t.classList.remove('active'));
    item.classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
    loadTab(tab);
  });
});

function loadTab(tab) {
  switch (tab) {
    case 'overview':   refreshOverview(); break;
    case 'services':   loadServices(); break;
    case 'config':     loadConfigList(); break;
    case 'launcher':   loadLauncher(); break;
    case 'nlm':        loadNlmStatus(); break;
    case 'nexus':      loadNexusStatus(); break;
    case 'lmstudio':   loadLMStudio(); break;
    case 'logs':       loadLogList(); break;
    case 'git':        loadGit(); break;
  }
}

// ── Overview ───────────────────────────────────────────────────────────────
async function refreshOverview() {
  document.getElementById('last-refresh').textContent = 'Refreshing...';
  const [metrics, nexus, nlm, lms] = await Promise.allSettled([
    fetch(`${BASE}/api/metrics`).then(r => r.json()),
    fetch(`${BASE}/api/nexus/status`).then(r => r.json()),
    fetch(`${BASE}/api/nlm/status`).then(r => r.json()),
    fetch(`${BASE}/api/lmstudio`).then(r => r.json()),
  ]);

  if (metrics.status === 'fulfilled') {
    const m = metrics.value;
    document.getElementById('cpu-val').textContent = m.cpu_percent != null ? `${m.cpu_percent}%` : '—';
    document.getElementById('ram-val').textContent = m.ram_percent != null ? `${m.ram_used_gb}GB (${m.ram_percent}%)` : '—';
    document.getElementById('gpu-val').textContent = m.gpu_vram_used_mb != null
      ? `${m.gpu_vram_used_mb}MB / ${m.gpu_vram_total_mb}MB`
      : '—';
    document.getElementById('disk-val').textContent = m.disk_percent != null ? `${m.disk_percent}%` : '—';
  }

  updateQs('qs-nexus', nexus.status === 'fulfilled' ? nexus.value.online : false, 'Nexus');
  updateQs('qs-nlm', nlm.status === 'fulfilled' ? nlm.value.online : false, 'NLM Proxy');
  updateQs('qs-lmstudio', lms.status === 'fulfilled' ? lms.value.online : false, 'LMStudio');

  // Hub check
  const hub = await fetch(`${BASE}/api/services/hub`).then(r => r.json()).catch(() => ({ online: false }));
  updateQs('qs-hub', hub.online, 'Hub');

  document.getElementById('last-refresh').textContent = `Last: ${new Date().toLocaleTimeString()}`;
}

function updateQs(id, online, label) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<span class="sc-dot ${online ? 'online' : 'offline'}"></span> ${label}`;
}

// ── Services ───────────────────────────────────────────────────────────────
async function loadServices() {
  document.getElementById('services-summary').textContent = 'Checking...';
  document.getElementById('services-tbody').innerHTML = '<tr><td colspan="4" class="sc-loading">Checking all services...</td></tr>';
  const data = await fetch(`${BASE}/api/services`).then(r => r.json()).catch(() => ({ services: [] }));
  const tbody = document.getElementById('services-tbody');
  tbody.innerHTML = '';
  (data.services || []).forEach(svc => {
    const tr = document.createElement('tr');
    const badge = svc.online
      ? '<span class="sc-badge sc-badge-online">● Online</span>'
      : '<span class="sc-badge sc-badge-offline">✕ Offline</span>';
    const detail = svc.online && svc.data ? JSON.stringify(svc.data).substring(0, 80) + '…' : '';
    tr.innerHTML = `
      <td>${svc.name}</td>
      <td><a href="http://localhost:${svc.port}" target="_blank" class="sc-link">:${svc.port}</a></td>
      <td>${badge}</td>
      <td class="sc-hint">${detail}</td>
    `;
    tbody.appendChild(tr);
  });
  document.getElementById('services-summary').textContent = `${data.online || 0} / ${data.total || 0} online`;
}

// ── Config Editor ──────────────────────────────────────────────────────────
async function loadConfigList() {
  const data = await fetch(`${BASE}/api/config`).then(r => r.json()).catch(() => ({ configs: [] }));
  const list = document.getElementById('config-list');
  list.innerHTML = '';
  (data.configs || []).forEach(cfg => {
    const div = document.createElement('div');
    div.className = 'sc-config-item';
    div.dataset.filename = cfg.name;
    div.innerHTML = `<span class="sc-dot ${cfg.exists ? 'online' : 'offline'}"></span>${cfg.name}`;
    div.addEventListener('click', () => loadConfig(cfg.name, div));
    list.appendChild(div);
  });
}

async function loadConfig(filename, el) {
  document.querySelectorAll('.sc-config-item').forEach(i => i.classList.remove('active'));
  if (el) el.classList.add('active');
  currentConfigFile = filename;
  const data = await fetch(`${BASE}/api/config/${filename}`).then(r => r.json()).catch(e => ({ error: e.message }));
  const editor = document.getElementById('config-editor');
  const hint = document.getElementById('config-hint');
  const toolbar = document.getElementById('config-toolbar');
  if (data.error) {
    hint.textContent = `Error: ${data.error}`;
    hint.style.display = 'block';
    editor.style.display = 'none';
    toolbar.style.display = 'none';
    return;
  }
  document.getElementById('config-filename').textContent = filename;
  editor.value = data.content;
  editor.style.display = 'block';
  hint.style.display = 'none';
  toolbar.style.display = 'flex';
  setConfigStatus('');
}

async function saveConfig() {
  if (!currentConfigFile) return;
  const content = document.getElementById('config-editor').value;
  setConfigStatus('Saving...');
  const res = await fetch(`${BASE}/api/config/${currentConfigFile}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content })
  }).then(r => r.json()).catch(e => ({ error: e.message }));
  if (res.ok) {
    setConfigStatus(`✓ Saved (${res.size} chars)`, 'ok');
  } else {
    setConfigStatus(`✕ ${res.error || res.detail || 'Failed'}`, 'err');
  }
}

async function restoreConfig() {
  if (!currentConfigFile) return;
  if (!confirm(`Restore ${currentConfigFile} from backup?`)) return;
  const res = await fetch(`${BASE}/api/config/${currentConfigFile}/restore`, { method: 'POST' }).then(r => r.json()).catch(e => ({ error: e.message }));
  if (res.ok) {
    setConfigStatus('✓ Restored from backup', 'ok');
    await loadConfig(currentConfigFile, null);
  } else {
    setConfigStatus(`✕ ${res.error || 'Failed'}`, 'err');
  }
}

function setConfigStatus(msg, cls) {
  const el = document.getElementById('config-status');
  el.textContent = msg;
  el.className = `sc-config-status ${cls || ''}`;
}

// ── Launcher ───────────────────────────────────────────────────────────────
async function loadLauncher() {
  const data = await fetch(`${BASE}/api/launcher`).then(r => r.json()).catch(() => ({}));
  const container = document.getElementById('launcher-content');
  container.innerHTML = '';
  ['services', 'scenes'].forEach(section => {
    if (!data[section]) return;
    const div = document.createElement('div');
    div.className = 'sc-launcher-section';
    div.innerHTML = `<h3>${section}</h3><div class="sc-launcher-grid" id="launcher-${section}"></div>`;
    container.appendChild(div);
    const grid = div.querySelector(`#launcher-${section}`);
    Object.entries(data[section]).forEach(([key, val]) => {
      const checked = val.auto_start ? 'checked' : '';
      const item = document.createElement('div');
      item.className = 'sc-launcher-item';
      item.innerHTML = `
        <label>
          <label class="sc-toggle">
            <input type="checkbox" ${checked} onchange="setLauncherAutoStart('${section}', '${key}', this.checked)" />
            <span class="sc-toggle-slider"></span>
          </label>
          ${key}
        </label>
      `;
      grid.appendChild(item);
    });
  });
}

async function setLauncherAutoStart(section, target, value) {
  await fetch(`${BASE}/api/launcher/${section}/${target}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_start: value })
  });
}

// ── NLM Proxy ──────────────────────────────────────────────────────────────
async function loadNlmStatus() {
  const data = await fetch(`${BASE}/api/nlm/status`).then(r => r.json()).catch(() => ({ online: false }));
  const card = document.getElementById('nlm-status-card');
  if (!data.online) {
    card.innerHTML = `<div class="sc-dot offline" style="margin-right:8px"></div> NLM Proxy offline — start with <code>python launcher.py nlm_proxy</code>`;
    return;
  }
  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
      <span class="sc-dot online"></span>
      <strong>NLM Proxy Online</strong>
    </div>
    <table class="sc-table">
      <tr><td>Cookies</td><td>${data.has_cookies ? `✓ ${data.cookie_count} cookies` : '✗ None'}</td></tr>
      <tr><td>BL Label</td><td style="font-family:monospace;font-size:11px">${data.bl || '—'}</td></tr>
      <tr><td>BL Age</td><td>${data.bl_age_days != null ? `${data.bl_age_days} days${data.bl_stale ? ' ⚠️ STALE' : ''}` : '—'}</td></tr>
      <tr><td>RPC Catalog</td><td>${data.rpc_catalog_version} (${data.known_rpcs} RPCs)</td></tr>
    </table>
  `;
}

async function importNlmHar() {
  const harPath = document.getElementById('nlm-har-path').value.trim();
  if (!harPath) { showNlmStatus('import', 'Enter a HAR file path first'); return; }
  showNlmStatus('import', 'Importing...');
  const res = await fetch(`${BASE}/api/nlm/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ har_path: harPath })
  }).then(r => r.json()).catch(e => ({ error: e.message }));
  if (res.error) {
    showNlmStatus('import', `✕ ${res.error}`);
  } else {
    showNlmStatus('import', `✓ Imported ${res.imported_cookies || 0} cookies. Total: ${res.total_cookies || 0}`);
    loadNlmStatus();
  }
}

async function captureNlmCookies() {
  showNlmStatus('capture', '⏳ Launching Chrome... (may take 30s)');
  const res = await fetch(`${BASE}/api/nlm/capture`, { method: 'POST' }).then(r => r.json()).catch(e => ({ error: e.message }));
  if (res.error) {
    showNlmStatus('capture', `✕ ${res.error}`);
  } else {
    showNlmStatus('capture', `✓ Captured ${res.imported_cookies || 0} cookies`);
    loadNlmStatus();
  }
}

async function loadNlmNotebooks() {
  const list = document.getElementById('nlm-notebooks-list');
  list.innerHTML = '<div class="sc-loading">Loading notebooks...</div>';
  const data = await fetch(`${BASE}/api/nlm/notebooks`).then(r => r.json()).catch(e => ({ error: e.message }));
  if (data.error) {
    list.innerHTML = `<div class="sc-hint">✕ ${data.error}</div>`;
    return;
  }
  const notebooks = data.notebooks || [];
  if (!notebooks.length) { list.innerHTML = '<div class="sc-hint">No notebooks found</div>'; return; }
  list.innerHTML = notebooks.map(nb => `
    <div class="sc-notebook-card">
      <div class="sc-nb-name">${nb.name || 'Unnamed'}</div>
      <div class="sc-nb-id">${nb.id || '—'}</div>
    </div>
  `).join('');
}

function showNlmStatus(which, msg) {
  const el = document.getElementById(`nlm-${which}-status`);
  if (el) el.textContent = msg;
}

// ── Nexus ──────────────────────────────────────────────────────────────────
async function loadNexusStatus() {
  const data = await fetch(`${BASE}/api/nexus/status`).then(r => r.json()).catch(() => ({ online: false }));
  const card = document.getElementById('nexus-status-card');
  if (!data.online) {
    card.innerHTML = `<span class="sc-dot offline"></span> Nexus offline — start with <code>cd C:\\Files\\Nexus && python -m nexus</code>`;
    return;
  }
  const stats = data.stats || {};
  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
      <span class="sc-dot online"></span><strong>Nexus Online</strong>
    </div>
    <table class="sc-table">
      <tr><td>Entries</td><td>${stats.total_entries || data.total_entries || '—'}</td></tr>
      <tr><td>Q&amp;A Pairs</td><td>${stats.qa_pairs || data.qa_pairs || '—'}</td></tr>
      <tr><td>Rules</td><td>${stats.rules || data.rules || '—'}</td></tr>
    </table>
  `;
}

async function nexusSearch() {
  const q = document.getElementById('nexus-query').value.trim();
  if (!q) return;
  const resultsEl = document.getElementById('nexus-results');
  resultsEl.innerHTML = '<div class="sc-loading">Searching...</div>';
  const data = await fetch(`${BASE}/api/nexus/search?q=${encodeURIComponent(q)}&limit=10`)
    .then(r => r.json()).catch(e => ({ error: e.message }));
  if (data.error) { resultsEl.innerHTML = `<div class="sc-hint">✕ ${data.error}</div>`; return; }
  const items = data.results || data.entries || [];
  if (!items.length) { resultsEl.innerHTML = '<div class="sc-hint">No results</div>'; return; }
  resultsEl.innerHTML = items.map(item => `
    <div class="sc-card" style="padding:10px;margin-bottom:8px">
      <div style="font-weight:600;font-size:13px;margin-bottom:4px">${item.title || '—'}</div>
      <div class="sc-hint" style="font-size:11px">${(item.content || item.answer || '').substring(0, 200)}</div>
    </div>
  `).join('');
}

// ── LMStudio ───────────────────────────────────────────────────────────────
async function loadLMStudio() {
  const data = await fetch(`${BASE}/api/lmstudio`).then(r => r.json()).catch(() => ({ online: false }));
  const card = document.getElementById('lmstudio-status-card');
  if (!data.online) {
    card.innerHTML = '<span class="sc-dot offline"></span> LMStudio offline or no models loaded.';
    return;
  }
  const models = data.models || [];
  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
      <span class="sc-dot online"></span>
      <strong>LMStudio Online</strong>
      <span class="sc-hint">${models.length} model(s) loaded</span>
    </div>
    ${models.length ? `<table class="sc-table">
      <thead><tr><th>Model ID</th><th>Type</th></tr></thead>
      <tbody>${models.map(m => `<tr><td style="font-family:monospace;font-size:11px">${m.id}</td><td>${m.type || '—'}</td></tr>`).join('')}</tbody>
    </table>` : '<div class="sc-hint">No models currently loaded</div>'}
  `;
}

// ── Logs ───────────────────────────────────────────────────────────────────
async function loadLogList() {
  const data = await fetch(`${BASE}/api/logs`).then(r => r.json()).catch(() => ({ logs: [] }));
  const list = document.getElementById('log-list');
  list.innerHTML = '';
  if (!data.logs || !data.logs.length) {
    list.innerHTML = '<div class="sc-loading">No log files</div>';
    return;
  }
  data.logs.forEach(log => {
    const div = document.createElement('div');
    div.className = 'sc-log-item';
    div.textContent = log.name;
    div.addEventListener('click', () => loadLog(log.name, div));
    list.appendChild(div);
  });
}

async function loadLog(filename, el) {
  document.querySelectorAll('.sc-log-item').forEach(i => i.classList.remove('active'));
  if (el) el.classList.add('active');
  currentLogFile = filename;
  document.getElementById('log-filename-label').textContent = filename;
  document.getElementById('log-toolbar').style.display = 'flex';
  refreshCurrentLog();
}

async function refreshCurrentLog() {
  if (!currentLogFile) return;
  const lines = document.getElementById('log-lines-input').value || 200;
  const data = await fetch(`${BASE}/api/logs/${currentLogFile}?lines=${lines}`).then(r => r.json()).catch(e => ({ error: e.message }));
  const viewer = document.getElementById('log-viewer');
  if (data.error) { viewer.textContent = `Error: ${data.error}`; return; }
  viewer.textContent = (data.lines || []).join('\n');
  viewer.scrollTop = viewer.scrollHeight;
}

// ── Git ────────────────────────────────────────────────────────────────────
async function loadGit() {
  const data = await fetch(`${BASE}/api/git`).then(r => r.json()).catch(e => ({ error: e.message }));
  const card = document.getElementById('git-card');
  if (data.error) { card.innerHTML = `<div class="sc-hint">✕ ${data.error}</div>`; return; }
  card.innerHTML = `
    <div style="margin-bottom:12px">
      <strong>Branch:</strong> <code>${data.branch}</code>
    </div>
    <div style="margin-bottom:8px"><strong>Recent commits:</strong></div>
    <div class="sc-git-log">${(data.log || []).join('\n')}</div>
    ${data.status && data.status.length ? `
      <div style="margin:12px 0 8px"><strong>Uncommitted changes:</strong></div>
      <div class="sc-git-status">${data.status.join('\n')}</div>
    ` : '<div class="sc-hint" style="margin-top:12px">✓ Working tree clean</div>'}
  `;
}

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  refreshOverview();
  // Auto-refresh overview every 30s
  setInterval(refreshOverview, 30000);
});
