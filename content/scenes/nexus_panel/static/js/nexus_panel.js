/* ── Nexus Control Panel — Client Logic ──────────────────────────── */
'use strict';

const API = '';
let pollTimer = null;
const artifacts = [];

// ── Tab Navigation ──────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = document.getElementById('panel-' + btn.dataset.panel);
    if (panel) panel.classList.add('active');

    // Lazy-load panel data
    const name = btn.dataset.panel;
    if (name === 'dashboard') loadDashboard();
    else if (name === 'explorer') loadEntries();
    else if (name === 'copilot') loadCopilotPanel();
    else if (name === 'workflows') loadResearchSessions();
    else if (name === 'ingestion') loadIngestionPanel();
    else if (name === 'nlmlab') loadNLMLabPanel();
  });
});

// ── Clock ───────────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('clock');
  if (el) el.textContent = new Date().toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

// ── Fetch Helper ────────────────────────────────────────────────────
async function api(path, opts = {}) {
  try {
    const res = await fetch(API + path, opts);
    return await res.json();
  } catch (e) {
    console.error('API error:', path, e);
    return { error: e.message };
  }
}

// ── Status Check ────────────────────────────────────────────────────
async function checkStatus() {
  const badge = document.getElementById('nexus-status');
  const data = await api('/api/stats');
  if (data.nexus_available) {
    badge.textContent = '● Online';
    badge.className = 'status-badge online';
  } else {
    badge.textContent = '● Offline';
    badge.className = 'status-badge offline';
  }
  updateQuickStats(data.panel_stats || {});
  return data;
}

function updateQuickStats(s) {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('qs-searches', s.searches || 0);
  set('qs-qa', s.qa_answered || 0);
  set('qs-added', s.entries_added || 0);
  set('qs-maint', s.maintenance_runs || 0);
  set('qs-chats', s.librarian_chats || 0);
  set('qs-tokens', (s.tokens_saved_est || 0).toLocaleString());
}

// ── Activity Feed ───────────────────────────────────────────────────
async function loadActivity() {
  const data = await api('/api/activity?limit=30');
  const feed = document.getElementById('activity-feed');
  if (!Array.isArray(data) || data.length === 0) {
    feed.innerHTML = '<p class="muted" style="padding:8px;font-size:12px">No activity yet</p>';
    return;
  }
  feed.innerHTML = data.map(a => {
    const time = a.ts ? new Date(a.ts).toLocaleTimeString() : '';
    return `<div class="activity-item ${a.level || 'info'}">
      <span class="act-time">${time}</span>
      <span class="act-action">${esc(a.action)}</span>
      <div class="act-detail">${esc(a.detail)}</div>
    </div>`;
  }).join('');
}

document.getElementById('clear-activity').addEventListener('click', () => {
  document.getElementById('activity-feed').innerHTML =
    '<p class="muted" style="padding:8px;font-size:12px">Cleared</p>';
});

// ── Dashboard ───────────────────────────────────────────────────────
async function loadDashboard() {
  const data = await checkStatus();
  const ns = data.nexus_stats || {};
  const ps = data.panel_stats || {};

  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('dash-entries', ns.total_entries ?? '—');
  set('dash-qa', ns.total_qa ?? '—');
  set('dash-sessions', ns.total_sessions ?? '—');
  set('dash-rules', ns.total_rules ?? '—');
  set('dash-prompts', ns.total_prompts ?? '—');
  set('dash-tokens', (ps.tokens_saved_est || 0).toLocaleString());

  // Health
  const healthEl = document.getElementById('health-details');
  if (data.nexus_available) {
    const h = await api('/api/maintain/health', { method: 'POST' });
    if (h.error) {
      healthEl.innerHTML = `<p style="color:var(--danger)">${esc(h.error)}</p>`;
    } else {
      const issues = (h.issues || []).map(i => `<li style="color:var(--warning)">${esc(i)}</li>`).join('');
      const recs = (h.recommendations || []).map(r => `<li>${esc(r)}</li>`).join('');
      healthEl.innerHTML = `
        <div style="display:flex;gap:24px;flex-wrap:wrap">
          <div><strong>Status:</strong> <span style="color:var(--success)">${esc(h.status || 'unknown')}</span></div>
          <div><strong>Duplicates:</strong> ${h.metrics?.potential_duplicates || 0}</div>
        </div>
        ${issues ? `<div style="margin-top:8px"><strong>Issues:</strong><ul style="padding-left:16px">${issues}</ul></div>` : ''}
        ${recs ? `<div style="margin-top:8px"><strong>Recommendations:</strong><ul style="padding-left:16px;color:var(--text-secondary)">${recs}</ul></div>` : ''}
      `;
    }
  } else {
    healthEl.innerHTML = '<p style="color:var(--danger)">Nexus is offline</p>';
  }

  // Recent entries
  const recentEl = document.getElementById('recent-entries');
  const entries = await api('/api/entries?limit=8');
  if (Array.isArray(entries) && entries.length > 0) {
    recentEl.innerHTML = entries.map(e => `
      <div class="entry-item" style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <span class="entry-type">${esc(e.content_type || 'note')}</span>
          <span style="margin-left:8px;font-weight:500">${esc(e.title || 'Untitled')}</span>
        </div>
        <span style="font-size:11px;color:var(--text-muted)">${esc(e.category || '')}</span>
      </div>
    `).join('');
  } else {
    recentEl.innerHTML = '<p class="muted">No entries yet</p>';
  }

  loadActivity();
}

// ── Knowledge Explorer ──────────────────────────────────────────────
let currentEntries = [];

async function loadEntries() {
  const type = document.getElementById('filter-type').value;
  const cat = document.getElementById('filter-category').value;
  const params = new URLSearchParams();
  if (type) params.set('type', type);
  if (cat) params.set('category', cat);
  params.set('limit', '50');

  const data = await api('/api/entries?' + params);
  currentEntries = Array.isArray(data) ? data : [];
  renderEntryList(currentEntries);
}

async function searchEntries() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) { loadEntries(); return; }
  const data = await api('/api/search?q=' + encodeURIComponent(q) + '&limit=30');
  currentEntries = Array.isArray(data) ? data : [];
  renderEntryList(currentEntries);
}

function renderEntryList(entries) {
  const el = document.getElementById('entry-list');
  const bulkBtn = document.getElementById('bulk-delete-btn');
  if (entries.length === 0) {
    el.innerHTML = '<p class="muted center" style="padding:20px">No entries found</p>';
    bulkBtn?.classList.add('hidden');
    return;
  }
  el.innerHTML = entries.map((e, i) => `
    <div class="entry-item" data-idx="${i}">
      <input type="checkbox" class="entry-check" data-id="${esc(e.id || '')}" onclick="event.stopPropagation(); toggleBulkBtn()">
      <div style="flex:1">
        <div class="entry-title">${esc(e.title || 'Untitled')}</div>
        <div class="entry-meta">
          <span class="entry-type">${esc(e.content_type || 'note')}</span>
          ${e.category ? `<span style="margin-left:6px">${esc(e.category)}</span>` : ''}
        </div>
      </div>
    </div>
  `).join('');

  el.querySelectorAll('.entry-item').forEach(item => {
    item.addEventListener('click', () => {
      el.querySelectorAll('.entry-item').forEach(x => x.classList.remove('selected'));
      item.classList.add('selected');
      showEntry(currentEntries[parseInt(item.dataset.idx)]);
    });
  });
}

function showEntry(e) {
  const el = document.getElementById('entry-detail');
  const tags = (e.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
  const isCode = (e.content_type === 'code');
  const contentClass = isCode ? 'detail-content code-content' : 'detail-content';
  el.innerHTML = `
    <h2>${esc(e.title || 'Untitled')}</h2>
    <div class="detail-meta">
      <span class="entry-type">${esc(e.content_type || 'note')}</span>
      ${e.category ? ` · ${esc(e.category)}` : ''}
      ${e.id ? ` · ID: ${esc(e.id)}` : ''}
      ${e.created_at ? ` · ${new Date(e.created_at).toLocaleString()}` : ''}
      <span style="float:right;display:flex;gap:4px">
        <button class="btn primary" style="font-size:11px;padding:2px 8px"
                onclick="editEntry('${esc(e.id || '')}')">Edit</button>
        <button class="btn danger" style="font-size:11px;padding:2px 8px"
                onclick="deleteEntry('${esc(e.id || '')}')">Delete</button>
      </span>
    </div>
    <div class="${contentClass}" id="entry-content-view">${esc(e.content || '')}</div>
    <div id="entry-edit-area" class="hidden">
      <textarea id="edit-content" class="textarea-full" rows="10">${esc(e.content || '')}</textarea>
      <div style="margin-top:8px;display:flex;gap:8px">
        <button class="btn primary" onclick="saveEditedEntry('${esc(e.id || '')}')">Save</button>
        <button class="btn" onclick="cancelEdit()">Cancel</button>
      </div>
    </div>
    ${tags ? `<div class="detail-tags">${tags}</div>` : ''}
  `;
}

function editEntry(id) {
  document.getElementById('entry-content-view')?.classList.add('hidden');
  document.getElementById('entry-edit-area')?.classList.remove('hidden');
}

function cancelEdit() {
  document.getElementById('entry-content-view')?.classList.remove('hidden');
  document.getElementById('entry-edit-area')?.classList.add('hidden');
}

async function saveEditedEntry(id) {
  const content = document.getElementById('edit-content')?.value;
  if (!id || content == null) return;
  const result = await api(`/api/entry/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content })
  });
  if (result.error) {
    alert('Save failed: ' + result.error);
  } else {
    cancelEdit();
    document.getElementById('entry-content-view').textContent = content;
    const idx = currentEntries.findIndex(e => e.id === id);
    if (idx >= 0) currentEntries[idx].content = content;
  }
}

async function deleteEntry(id) {
  if (!id || !confirm('Delete this entry?')) return;
  await api('/api/entry/' + id, { method: 'DELETE' });
  loadEntries();
  document.getElementById('entry-detail').innerHTML =
    '<p class="muted center">Entry deleted</p>';
}

function toggleBulkBtn() {
  const checked = document.querySelectorAll('.entry-check:checked');
  const btn = document.getElementById('bulk-delete-btn');
  if (checked.length > 0) {
    btn?.classList.remove('hidden');
    btn.textContent = `Delete Selected (${checked.length})`;
  } else {
    btn?.classList.add('hidden');
  }
}

document.getElementById('bulk-delete-btn')?.addEventListener('click', async () => {
  const checked = document.querySelectorAll('.entry-check:checked');
  if (checked.length === 0) return;
  if (!confirm(`Delete ${checked.length} entries?`)) return;
  for (const cb of checked) {
    await api('/api/entry/' + cb.dataset.id, { method: 'DELETE' });
  }
  loadEntries();
  document.getElementById('entry-detail').innerHTML =
    '<p class="muted center">Entries deleted</p>';
  document.getElementById('bulk-delete-btn')?.classList.add('hidden');
});

document.getElementById('search-btn').addEventListener('click', searchEntries);
document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') searchEntries();
});
document.getElementById('filter-type').addEventListener('change', loadEntries);
document.getElementById('filter-category').addEventListener('change', loadEntries);

// Add Entry Modal
document.getElementById('add-entry-btn').addEventListener('click', () => {
  document.getElementById('add-entry-modal').classList.remove('hidden');
});
document.getElementById('cancel-entry').addEventListener('click', () => {
  document.getElementById('add-entry-modal').classList.add('hidden');
});
document.getElementById('save-entry').addEventListener('click', async () => {
  const title = document.getElementById('new-title').value.trim();
  const content = document.getElementById('new-content').value.trim();
  if (!title || !content) { alert('Title and content required'); return; }
  const tags = document.getElementById('new-tags').value.split(',').map(t => t.trim()).filter(Boolean);
  await api('/api/entry', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title,
      content,
      content_type: document.getElementById('new-type').value,
      category: document.getElementById('new-category').value,
      tags,
    }),
  });
  document.getElementById('add-entry-modal').classList.add('hidden');
  document.getElementById('new-title').value = '';
  document.getElementById('new-content').value = '';
  document.getElementById('new-tags').value = '';
  loadEntries();
});

// ── Librarian Chat ──────────────────────────────────────────────────
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');

async function sendChat() {
  const message = chatInput.value.trim();
  if (!message) return;
  chatInput.value = '';

  appendMsg('user', message);

  // Handle quick commands
  if (message.startsWith('/')) {
    const cmd = message.split(' ')[0].toLowerCase();
    const arg = message.slice(cmd.length).trim();

    if (cmd === '/stats') {
      appendMsg('assistant', '<div class="spinner"></div> Loading stats...');
      const data = await api('/api/stats');
      const ns = data.nexus_stats || {};
      const lines = Object.entries(ns).map(([k, v]) => `**${k}:** ${v}`);
      replaceLastMsg('assistant', lines.join('\n'));
      return;
    }
    if (cmd === '/health') {
      appendMsg('assistant', '<div class="spinner"></div> Running health check...');
      const h = await api('/api/maintain/health', { method: 'POST' });
      replaceLastMsg('assistant', '```\n' + JSON.stringify(h, null, 2) + '\n```');
      return;
    }
    if (cmd === '/recent') {
      appendMsg('assistant', '<div class="spinner"></div> Loading recent entries...');
      const entries = await api('/api/entries?limit=10');
      if (Array.isArray(entries)) {
        const lines = entries.map(e => `• **${e.title}** (${e.content_type})`);
        replaceLastMsg('assistant', 'Recent entries:\n' + lines.join('\n'));
      } else {
        replaceLastMsg('assistant', 'Could not load entries.');
      }
      return;
    }
    if (cmd === '/research') {
      if (!arg) { appendMsg('assistant', 'Usage: /research [question]'); return; }
      appendMsg('assistant', '<div class="spinner"></div> Starting research...');
      const r = await api('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: arg }),
      });
      replaceLastMsg('assistant', r.research_id
        ? `Research session started: **${r.research_id}**\nUse the Workflows tab to follow up.`
        : `Error: ${r.error || 'Unknown'}`);
      return;
    }
  }

  // Normal chat — ask the Librarian
  appendMsg('assistant', '<div class="spinner"></div> Thinking...');
  const result = await api('/api/librarian/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });

  const response = result.response || result.error || 'No response';
  const meta = result.source ? `Source: ${result.source}` : '';
  const conf = result.confidence != null ? ` · Confidence: ${Math.round(result.confidence * 100)}%` : '';
  replaceLastMsg('assistant', response, meta + conf);
}

function appendMsg(role, content, meta = '') {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerHTML = `<div class="msg-content">${formatText(content)}</div>
    ${meta ? `<div class="msg-meta">${esc(meta)}</div>` : ''}`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function replaceLastMsg(role, content, meta = '') {
  const msgs = chatMessages.querySelectorAll(`.msg.${role}`);
  if (msgs.length > 0) {
    const last = msgs[msgs.length - 1];
    last.innerHTML = `<div class="msg-content">${formatText(content)}</div>
      ${meta ? `<div class="msg-meta">${esc(meta)}</div>` : ''}`;
  }
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function formatText(text) {
  // Basic markdown-like formatting
  return text
    .replace(/```([\s\S]*?)```/g, '<pre style="background:var(--bg-primary);padding:8px;border-radius:4px;font-size:12px;overflow-x:auto">$1</pre>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');
}

document.getElementById('chat-send').addEventListener('click', sendChat);
chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });

// Quick command buttons
document.querySelectorAll('.cmd-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    chatInput.value = btn.dataset.cmd;
    sendChat();
  });
});

// ── Maintenance ─────────────────────────────────────────────────────
document.querySelectorAll('.maint-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const action = btn.dataset.action;
    const output = document.getElementById('maint-output');
    output.textContent = `Running ${action}...`;
    btn.disabled = true;

    const result = await api('/api/maintain/' + action, { method: 'POST' });
    output.textContent = JSON.stringify(result, null, 2);
    btn.disabled = false;
    checkStatus();
  });
});

// ── Workflows ───────────────────────────────────────────────────────
document.getElementById('start-research').addEventListener('click', async () => {
  const q = document.getElementById('research-question').value.trim();
  if (!q) return;
  const r = await api('/api/research', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: q }),
  });
  document.getElementById('research-question').value = '';
  loadResearchSessions();
});

async function loadResearchSessions() {
  const data = await api('/api/research/list');
  const el = document.getElementById('research-sessions');
  if (!Array.isArray(data) || data.length === 0) {
    el.innerHTML = '<p class="muted">No research sessions yet</p>';
    return;
  }
  el.innerHTML = data.map(s => `
    <div class="research-item">
      <strong>${esc(s.question || s.title || 'Research')}</strong>
      <span style="float:right;font-size:11px;color:var(--text-muted)">${esc(s.status || '')}</span>
    </div>
  `).join('');
}

// YouTube Import
document.getElementById('import-youtube').addEventListener('click', async () => {
  const url = document.getElementById('youtube-url').value.trim();
  if (!url) return;
  const status = document.getElementById('youtube-status');
  status.innerHTML = '<div class="spinner"></div> Importing...';
  const r = await api('/api/youtube', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  status.innerHTML = r.error
    ? `<span style="color:var(--danger)">${esc(r.error)}</span>`
    : '<span style="color:var(--success)">Imported successfully!</span>';
  document.getElementById('youtube-url').value = '';
});

// Training Data
document.getElementById('extract-training').addEventListener('click', async () => {
  const status = document.getElementById('training-status');
  status.innerHTML = '<div class="spinner"></div> Extracting Q&A pairs from knowledge entries...';
  const entries = await api('/api/entries?limit=100');
  if (!Array.isArray(entries)) {
    status.innerHTML = '<span style="color:var(--danger)">Failed to load entries</span>';
    return;
  }
  // Extract Q&A pairs from entries that have enough content
  let pairs = 0;
  for (const e of entries) {
    if ((e.content || '').length > 100 && e.title) {
      const q = `What is ${e.title}?`;
      const a = (e.content || '').substring(0, 500);
      try {
        await api('/api/entry', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: `Training QA: ${e.title}`,
            content: `Q: ${q}\nA: ${a}`,
            content_type: 'code',
            category: 'training',
            tags: ['training', 'qa', 'auto-generated'],
          }),
        });
        pairs++;
      } catch (ex) { /* skip */ }
    }
  }
  status.innerHTML = `<span style="color:var(--success)">Generated ${pairs} training Q&A pairs</span>`;
});

// Knowledge Generation
document.getElementById('generate-doc').addEventListener('click', async () => {
  const type = document.getElementById('gen-type').value;
  const task = document.getElementById('gen-task').value;
  const el = document.getElementById('generated-artifacts');

  if (type === 'context_primer') {
    el.innerHTML = '<div class="spinner"></div> Generating context primer...';
    const r = await api('/api/copilot/config');
    const content = `# Context Primer — CosySim\n\nGenerated: ${new Date().toISOString()}\n\n` +
      `## Configuration\n${JSON.stringify(r, null, 2)}`;
    artifacts.push({ title: 'Context Primer', content, time: new Date().toISOString() });
    renderArtifacts();
    el.innerHTML = '<span style="color:var(--success)">Context primer generated → see Artifacts sidebar</span>';
  } else if (type === 'local_guide') {
    el.innerHTML = '<div class="spinner"></div> Generating local model guide...';
    const guide = `# Local Model Guide — ${task}\n\nGenerated: ${new Date().toISOString()}\n\n` +
      `Task type: ${task}\n\nUse this guide to configure local LMStudio models for ${task} tasks.\n` +
      'Always use the Nexus Q&A pipeline before making LLM calls.\n' +
      'Store results back to Nexus for future use.';
    artifacts.push({ title: `Local Guide: ${task}`, content: guide, time: new Date().toISOString() });
    renderArtifacts();
    el.innerHTML = '<span style="color:var(--success)">Guide generated → see Artifacts sidebar</span>';
  }
});

// ── Copilot Panel ───────────────────────────────────────────────────
async function loadCopilotPanel() {
  // Config
  const config = await api('/api/copilot/config');
  const configEl = document.getElementById('copilot-config');
  if (config && !config.error) {
    let html = '';
    for (const [section, vals] of Object.entries(config)) {
      html += `<div class="config-section"><h4>${esc(section)}</h4>`;
      if (typeof vals === 'object' && vals !== null) {
        for (const [k, v] of Object.entries(vals)) {
          html += `<div class="config-item"><span class="key">${esc(k)}</span><span class="val">${esc(String(v))}</span></div>`;
        }
      } else {
        html += `<div class="config-item"><span class="val">${esc(String(vals))}</span></div>`;
      }
      html += '</div>';
    }
    configEl.innerHTML = html;
  }

  // Skills
  const skills = await api('/api/copilot/skills');
  const skillsEl = document.getElementById('copilot-skills');
  if (skills && !skills.error) {
    let html = '';
    for (const [pack, items] of Object.entries(skills)) {
      html += `<div class="skill-pack"><div class="skill-pack-name">${esc(pack)} (${items.length})</div>`;
      for (const s of items.slice(0, 8)) {
        html += `<div class="skill-item"><strong>${esc(s.name)}</strong> — ${esc(s.description || '').substring(0, 80)}</div>`;
      }
      if (items.length > 8) {
        html += `<div class="skill-item muted">... and ${items.length - 8} more</div>`;
      }
      html += '</div>';
    }
    skillsEl.innerHTML = html || '<p class="muted">No skills registered</p>';
  }

  // Rules
  const rules = await api('/api/rules');
  const rulesEl = document.getElementById('copilot-rules');
  if (Array.isArray(rules)) {
    rulesEl.innerHTML = rules.length > 0
      ? rules.map(r => `<div class="prompt-item"><div class="prompt-name">${esc(r.name || 'Rule')}</div><div class="prompt-category">${esc(r.scope || '')} · ${esc(r.rule_type || '')}</div></div>`).join('')
      : '<p class="muted">No governance rules defined</p>';
  }

  // Sessions
  const sessions = await api('/api/sessions');
  const sessEl = document.getElementById('copilot-sessions');
  if (Array.isArray(sessions)) {
    sessEl.innerHTML = sessions.length > 0
      ? sessions.slice(0, 10).map(s => `<div class="session-item"><strong>${esc(s.project || 'Session')}</strong> <span class="muted">${esc(s.status || '')}</span></div>`).join('')
      : '<p class="muted">No sessions logged</p>';
  }
}

// Load/Refresh prompts
document.getElementById('load-prompts').addEventListener('click', async () => {
  const el = document.getElementById('copilot-prompts');
  el.innerHTML = '<div class="spinner"></div>';
  const prompts = await api('/api/prompts');
  if (Array.isArray(prompts) && prompts.length > 0) {
    el.innerHTML = prompts.map(p => `
      <div class="prompt-item">
        <div class="prompt-name">${esc(p.title || p.name || 'Prompt')}</div>
        <div class="prompt-category">${esc(p.category || '')} · v${esc(p.version || '1')}</div>
      </div>
    `).join('');
  } else {
    el.innerHTML = '<p class="muted">No prompts stored</p>';
  }
});

// ── Artifacts Sidebar ───────────────────────────────────────────────
document.getElementById('toggle-artifacts').addEventListener('click', () => {
  document.getElementById('artifacts-sidebar').classList.toggle('collapsed');
});

function renderArtifacts() {
  const el = document.getElementById('artifacts-list');
  if (artifacts.length === 0) {
    el.innerHTML = '<p class="muted">No artifacts yet</p>';
    return;
  }
  el.innerHTML = artifacts.map((a, i) => `
    <div class="artifact-item" data-idx="${i}">
      <strong>${esc(a.title)}</strong>
      <div style="font-size:10px;color:var(--text-muted)">${new Date(a.time).toLocaleTimeString()}</div>
    </div>
  `).join('');

  el.querySelectorAll('.artifact-item').forEach(item => {
    item.addEventListener('click', () => {
      const a = artifacts[parseInt(item.dataset.idx)];
      showArtifactModal(a);
    });
  });
}

function showArtifactModal(a) {
  const modal = document.getElementById('add-entry-modal');
  document.getElementById('new-title').value = a.title;
  document.getElementById('new-content').value = a.content;
  document.getElementById('new-type').value = 'document';
  document.getElementById('new-category').value = 'general';
  modal.classList.remove('hidden');
}

// ── Ingestion Panel ─────────────────────────────────────────────────
let harTmpPath = '';

function loadIngestionPanel() {
  loadNotebooks();
}

// HAR Upload
const dropzone = document.getElementById('har-dropzone');
const harInput = document.getElementById('har-file-input');

if (dropzone) {
  dropzone.addEventListener('click', () => harInput?.click());
  dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) uploadHAR(e.dataTransfer.files[0]);
  });
}
if (harInput) {
  harInput.addEventListener('change', () => {
    if (harInput.files.length) uploadHAR(harInput.files[0]);
  });
}

async function uploadHAR(file) {
  const form = new FormData();
  form.append('file', file);
  const preview = document.getElementById('har-preview');
  const nbList = document.getElementById('har-notebooks');
  nbList.innerHTML = '<p class="muted">Uploading & parsing...</p>';
  preview.classList.remove('hidden');

  const data = await fetch('/api/ingest/har', { method: 'POST', body: form }).then(r => r.json());
  if (data.error) {
    nbList.innerHTML = `<p style="color:var(--danger)">${esc(data.error)}</p>`;
    return;
  }
  harTmpPath = data.tmp_path;
  nbList.innerHTML = (data.notebooks || []).map(nb => `
    <div class="har-notebook-card">
      <strong>${esc(nb.name || nb.id)}</strong>
      <div class="har-counts">
        <span>📄 ${(nb.sources || []).length} sources</span>
        <span>📝 ${(nb.notes || []).length} notes</span>
        <span>💬 ${(nb.conversations || []).length} conversations</span>
        <span>📚 ${(nb.documents || []).length} docs</span>
      </div>
    </div>
  `).join('') || '<p class="muted">No notebooks found in HAR file.</p>';
}

document.getElementById('har-commit-btn')?.addEventListener('click', async () => {
  if (!harTmpPath) return;
  const items = [];
  if (document.getElementById('har-sources')?.checked) items.push('sources');
  if (document.getElementById('har-documents')?.checked) items.push('documents');
  if (document.getElementById('har-notes')?.checked) items.push('notes');
  if (document.getElementById('har-convos')?.checked) items.push('conversations');

  const resultEl = document.getElementById('har-result');
  resultEl.innerHTML = '<p class="muted">Committing...</p>';
  const data = await api('/api/ingest/har/commit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tmp_path: harTmpPath, items })
  });
  if (data.error) {
    resultEl.innerHTML = `<p style="color:var(--danger)">${esc(data.error)}</p>`;
  } else {
    resultEl.innerHTML = (data.results || []).map(r =>
      `<div class="result-row">✅ <strong>${esc(r.name)}</strong> — ${r.stored}/${r.total} items stored</div>`
    ).join('');
  }
});

// Codebase Indexer
document.getElementById('codebase-index-btn')?.addEventListener('click', async () => {
  const name = document.getElementById('codebase-name')?.value.trim();
  const filesText = document.getElementById('codebase-files')?.value.trim();
  const resultEl = document.getElementById('codebase-result');
  if (!name || !filesText) {
    resultEl.innerHTML = '<p style="color:var(--danger)">Name and files required.</p>';
    return;
  }
  const files = filesText.split('\n').map(f => f.trim()).filter(Boolean);
  resultEl.innerHTML = '<p class="muted">Creating notebook...</p>';
  const data = await api('/api/ingest/codebase', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, files })
  });
  if (data.error) {
    resultEl.innerHTML = `<p style="color:var(--danger)">${esc(data.error)}</p>`;
  } else {
    resultEl.innerHTML = `<div class="result-row">✅ Notebook created: <strong>${esc(data.notebook_id || data.id || 'OK')}</strong></div>`;
  }
});

// Notebook Browser
async function loadNotebooks() {
  const listEl = document.getElementById('notebook-list');
  if (!listEl) return;
  listEl.innerHTML = '<p class="muted">Loading...</p>';
  const data = await api('/api/nlm/status');
  if (data.error) {
    listEl.innerHTML = `<p style="color:var(--danger)">${esc(data.error)}</p>`;
    return;
  }
  const notebooks = data.notebooks || [];
  if (notebooks.length === 0) {
    listEl.innerHTML = '<p class="muted">No notebooks found.</p>';
    return;
  }
  listEl.innerHTML = notebooks.map(nb => `
    <div class="notebook-card">
      <strong>${esc(nb.name || nb.id)}</strong>
      <span class="muted">${esc(nb.id || '')}</span>
      <button class="btn-icon btn-danger nb-delete" data-id="${esc(nb.id)}" title="Delete">🗑</button>
    </div>
  `).join('');
  listEl.querySelectorAll('.nb-delete').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm('Delete this notebook?')) return;
      await api(`/api/nlm/notebook/${btn.dataset.id}`, { method: 'DELETE' });
      loadNotebooks();
    });
  });
}

document.getElementById('refresh-notebooks-btn')?.addEventListener('click', loadNotebooks);

// ── NLM Lab Panel ───────────────────────────────────────────────────
function loadNLMLabPanel() {
  loadSavings();
}

// NLM Ask
document.getElementById('nlm-ask-btn')?.addEventListener('click', async () => {
  const question = document.getElementById('nlm-question')?.value.trim();
  const nbId = document.getElementById('nlm-notebook-id')?.value.trim();
  if (!question) return;

  const answerEl = document.getElementById('nlm-answer');
  const textEl = document.getElementById('nlm-answer-text');
  const tierEl = document.getElementById('nlm-tier');
  const metaEl = document.getElementById('nlm-meta');

  textEl.textContent = 'Thinking...';
  answerEl.classList.remove('hidden');

  const data = await api('/api/nlm/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, notebook_id: nbId })
  });

  if (data.error) {
    textEl.textContent = data.error;
    tierEl.textContent = '❌';
    tierEl.className = 'tier-badge error';
  } else {
    textEl.textContent = data.answer || 'No answer';
    const tier = data.source_tier || 'unknown';
    const tierLabels = { cache: '⚡ Cache', fts: '🔍 FTS', nlm: '🧠 NLM', llm: '🤖 LLM', none: '❓ None' };
    tierEl.textContent = tierLabels[tier] || tier;
    tierEl.className = `tier-badge tier-${tier}`;
    const ms = data.query_time_ms ? `${data.query_time_ms.toFixed(0)}ms` : '';
    const cached = data.was_cached ? ' (cached)' : '';
    metaEl.textContent = `${ms}${cached} | confidence: ${((data.confidence || 0) * 100).toFixed(0)}%`;
  }
});

// Batch Q&A
document.getElementById('batch-generate-btn')?.addEventListener('click', async () => {
  const topic = document.getElementById('batch-topic')?.value.trim();
  const count = parseInt(document.getElementById('batch-count')?.value || '10');
  if (!topic) return;
  const data = await api('/api/questions/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, count })
  });
  if (data.questions) {
    document.getElementById('batch-questions').value = data.questions.join('\n');
  }
});

document.getElementById('batch-send-btn')?.addEventListener('click', async () => {
  const text = document.getElementById('batch-questions')?.value.trim();
  const nbId = document.getElementById('batch-nb-id')?.value.trim();
  if (!text) return;
  const questions = text.split('\n').map(q => q.trim()).filter(Boolean);
  const progress = document.getElementById('batch-progress');
  const resultsEl = document.getElementById('batch-results');
  const listEl = document.getElementById('batch-results-list');

  progress.textContent = `Sending ${questions.length} questions...`;
  const data = await api('/api/nlm/ask-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ questions, notebook_id: nbId })
  });

  if (data.error) {
    progress.textContent = data.error;
    return;
  }

  progress.textContent = `Done — ${data.count} answers received.`;
  resultsEl.classList.remove('hidden');
  const tierLabels = { cache: '⚡ Cache', fts: '🔍 FTS', nlm: '🧠 NLM', llm: '🤖 LLM', none: '❓ None' };
  listEl.innerHTML = (data.results || []).map((r, i) => `
    <div class="batch-result-row">
      <div class="batch-q"><strong>Q${i + 1}:</strong> ${esc(questions[i] || '')}</div>
      <div class="batch-a"><span class="tier-badge tier-${r.source_tier}">${tierLabels[r.source_tier] || r.source_tier}</span> ${esc(r.answer || 'No answer')}</div>
    </div>
  `).join('');
  loadSavings();
});

// Plan Decomposer
document.getElementById('decompose-btn')?.addEventListener('click', async () => {
  const plan = document.getElementById('decompose-plan')?.value.trim();
  const resultEl = document.getElementById('decompose-result');
  if (!plan) return;
  resultEl.innerHTML = '<p class="muted">Decomposing...</p>';
  const data = await api('/api/nlm/decompose', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan })
  });
  if (data.error) {
    resultEl.innerHTML = `<p style="color:var(--danger)">${esc(data.error)}</p>`;
  } else {
    const steps = data.steps || [];
    resultEl.innerHTML = steps.length
      ? `<ol class="step-list">${steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>`
      : '<p class="muted">No steps returned.</p>';
  }
});

// Code Analyzer
document.getElementById('analyze-btn')?.addEventListener('click', async () => {
  const filesText = document.getElementById('analyze-files')?.value.trim();
  const qText = document.getElementById('analyze-questions')?.value.trim();
  const resultEl = document.getElementById('analyze-result');
  if (!filesText) return;
  const files = filesText.split('\n').map(f => f.trim()).filter(Boolean);
  const questions = qText ? qText.split('\n').map(q => q.trim()).filter(Boolean) : undefined;
  resultEl.innerHTML = '<p class="muted">Analyzing...</p>';
  const data = await api('/api/nlm/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ files, questions })
  });
  if (data.error) {
    resultEl.innerHTML = `<p style="color:var(--danger)">${esc(data.error)}</p>`;
  } else {
    const insights = data.insights || [];
    resultEl.innerHTML = insights.length
      ? insights.map(i => `<div class="insight-card"><strong>${esc(i.question)}</strong><p>${esc(i.answer)}</p></div>`).join('')
      : '<p class="muted">No insights returned.</p>';
  }
});

// Topic Builder
document.getElementById('topic-build-btn')?.addEventListener('click', async () => {
  const topic = document.getElementById('topic-name')?.value.trim();
  const srcText = document.getElementById('topic-sources')?.value.trim();
  const count = parseInt(document.getElementById('topic-count')?.value || '30');
  const resultEl = document.getElementById('topic-result');
  if (!topic) return;
  const sources = srcText ? srcText.split('\n').map(s => s.trim()).filter(Boolean) : undefined;
  resultEl.innerHTML = '<p class="muted">Building topic knowledge (this may take a while)...</p>';
  const data = await api('/api/nlm/build-topic', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, sources, count })
  });
  if (data.error) {
    resultEl.innerHTML = `<p style="color:var(--danger)">${esc(data.error)}</p>`;
  } else {
    resultEl.innerHTML = `
      <div class="result-row">
        ${data.success ? '✅' : '⚠️'} <strong>${esc(topic)}</strong> —
        ${data.qa_count || 0} Q&A pairs stored,
        notebook: ${esc(data.notebook_id || 'n/a')},
        took ${(data.duration || 0).toFixed(1)}s
      </div>
      ${(data.errors || []).map(e => `<p style="color:var(--warning)">${esc(e)}</p>`).join('')}
    `;
  }
  loadSavings();
});

// Savings
async function loadSavings() {
  const data = await api('/api/nlm/router/stats');
  if (data.error) return;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('sav-cache', data.cache_hits || 0);
  set('sav-fts', data.fts_hits || 0);
  set('sav-nlm', data.nlm_hits || 0);
  set('sav-llm', data.llm_fallbacks || 0);
  const pct = data.compute_saved_pct != null ? (data.compute_saved_pct * 100).toFixed(1) : '0';
  set('sav-pct', pct + '%');
}

document.getElementById('refresh-savings-btn')?.addEventListener('click', loadSavings);

// ── Utilities ───────────────────────────────────────────────────────
function esc(str) {
  if (str == null) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

// ── Init ────────────────────────────────────────────────────────────
loadDashboard();
pollTimer = setInterval(() => {
  checkStatus();
  loadActivity();
}, 15000);
