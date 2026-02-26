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
  if (entries.length === 0) {
    el.innerHTML = '<p class="muted center" style="padding:20px">No entries found</p>';
    return;
  }
  el.innerHTML = entries.map((e, i) => `
    <div class="entry-item" data-idx="${i}">
      <div class="entry-title">${esc(e.title || 'Untitled')}</div>
      <div class="entry-meta">
        <span class="entry-type">${esc(e.content_type || 'note')}</span>
        ${e.category ? `<span style="margin-left:6px">${esc(e.category)}</span>` : ''}
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
  el.innerHTML = `
    <h2>${esc(e.title || 'Untitled')}</h2>
    <div class="detail-meta">
      <span class="entry-type">${esc(e.content_type || 'note')}</span>
      ${e.category ? ` · ${esc(e.category)}` : ''}
      ${e.id ? ` · ID: ${esc(e.id)}` : ''}
      ${e.created_at ? ` · ${new Date(e.created_at).toLocaleString()}` : ''}
      <button class="btn danger" style="float:right;font-size:11px;padding:2px 8px"
              onclick="deleteEntry('${esc(e.id || '')}')">Delete</button>
    </div>
    <div class="detail-content">${esc(e.content || '')}</div>
    ${tags ? `<div class="detail-tags">${tags}</div>` : ''}
  `;
}

async function deleteEntry(id) {
  if (!id || !confirm('Delete this entry?')) return;
  await api('/api/entry/' + id, { method: 'DELETE' });
  loadEntries();
  document.getElementById('entry-detail').innerHTML =
    '<p class="muted center">Entry deleted</p>';
}

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
