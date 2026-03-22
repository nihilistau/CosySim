/**
 * Dashboard Scene — Frontend Controller
 * ======================================
 *
 * Vanilla JS frontend for the character & system management dashboard.
 * Communicates exclusively via fetch() to the dashboard REST API.
 *
 * Version: v1.49.2 [2026-03-22]
 * Author:  CosySim Team
 *
 * Change Log:
 *     v1.49.2 [2026-03-22] — Initial Flask migration from Streamlit dashboard_v2
 */

/* global fetch */

// ──── State ──────────────────────────────────────────────────────────────
const state = {
  characters: [],
  personalities: [],
  roles: [],
  selectedCharId: null,
};

// ──── DOM Helpers ────────────────────────────────────────────────────────

/**
 * Short alias for document.getElementById.
 * @param {string} id
 * @returns {HTMLElement|null}
 */
const $ = (id) => document.getElementById(id);

/**
 * Show a toast message at the bottom-right of the screen.
 * @param {string} msg — Text to display.
 * @param {boolean} [isError=false] — If true, style as an error toast.
 */
function toast(msg, isError = false) {
  const el = $('dash-toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle('error', isError);
  el.classList.add('show');
  clearTimeout(el._tid);
  el._tid = setTimeout(() => el.classList.remove('show'), 3000);
}

/**
 * Generic JSON fetch wrapper with error handling.
 * @param {string} url
 * @param {object} [opts]
 * @returns {Promise<any>}
 */
async function api(url, opts = {}) {
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
    const data = await res.json();
    if (!res.ok) {
      const errMsg = data.error || `HTTP ${res.status}`;
      toast(errMsg, true);
      throw new Error(errMsg);
    }
    return data;
  } catch (err) {
    if (!err.message.startsWith('HTTP')) {
      toast('Network error: ' + err.message, true);
    }
    throw err;
  }
}

/**
 * Format an ISO date string to a short human-readable form.
 * @param {string} iso
 * @returns {string}
 */
function fmtDate(iso) {
  if (!iso) return '-';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

/**
 * Render a trait bar with label, progress fill, and numeric value.
 * @param {string} label
 * @param {number} value — 0 to 1.
 * @returns {string} HTML string.
 */
function traitBar(label, value) {
  const pct = Math.round((value || 0) * 100);
  return `
    <div class="trait-bar">
      <span class="trait-bar__label">${label}</span>
      <div class="trait-bar__track">
        <div class="trait-bar__fill" style="width: ${pct}%"></div>
      </div>
      <span class="trait-bar__value">${pct}%</span>
    </div>`;
}

/**
 * Parse a comma-separated string into a trimmed array (empty strings removed).
 * @param {string} str
 * @returns {string[]}
 */
function csvToArr(str) {
  return (str || '').split(',').map(s => s.trim()).filter(Boolean);
}

// ──── Tab Navigation ─────────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Tab switching with panel activation
// CONNECTS: all dash-panel sections
// CALLED BY: click on .dash-tab buttons
function initTabs() {
  const tabs = document.querySelectorAll('.dash-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      // Deactivate all
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.dash-panel').forEach(p => p.classList.remove('active'));

      // Activate selected
      tab.classList.add('active');
      const panelId = 'panel-' + tab.dataset.tab;
      const panel = $(panelId);
      if (panel) panel.classList.add('active');

      // Load data for the activated tab
      const tabKey = tab.dataset.tab;
      if (tabKey === 'overview') loadOverview();
      else if (tabKey === 'characters') loadCharacters();
      else if (tabKey === 'personalities') loadPersonalities();
      else if (tabKey === 'roles') loadRoles();
      else if (tabKey === 'memories') loadMemoryCharSelect();
    });
  });
}

// ──── Overview Panel ─────────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Dashboard overview with stat cards and recent chars
// CONNECTS: /api/dashboard/stats, /api/characters
async function loadOverview() {
  try {
    const stats = await api('/api/dashboard/stats');
    $('stat-characters').textContent = stats.characters;
    $('stat-personalities').textContent = stats.personalities;
    $('stat-roles').textContent = stats.roles;
    $('stat-memories').textContent = stats.memories;
  } catch { /* toast already shown */ }

  try {
    const chars = await api('/api/characters');
    state.characters = chars;
    const body = $('overview-chars-body');
    if (!body) return;
    // Show last 10 characters sorted by created_at descending
    const recent = [...chars]
      .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
      .slice(0, 10);
    if (recent.length === 0) {
      body.innerHTML = '<tr><td colspan="5" class="empty-state">No characters yet.</td></tr>';
      return;
    }
    body.innerHTML = recent.map(c => `
      <tr>
        <td>${esc(c.name)}</td>
        <td>${c.age || '-'}</td>
        <td>${esc(c.mood || 'neutral')}</td>
        <td>${Math.round((c.relationship_level || 0) * 100)}%</td>
        <td>${fmtDate(c.created_at)}</td>
      </tr>`).join('');
  } catch { /* handled */ }
}

/**
 * Escape HTML entities to prevent XSS.
 * @param {string} str
 * @returns {string}
 */
function esc(str) {
  const el = document.createElement('span');
  el.textContent = str || '';
  return el.innerHTML;
}

// ──── Characters Panel ───────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Character list, create, edit, detail views
// CONNECTS: /api/characters, /api/personalities
// EMITS: table rows, form bindings

async function loadCharacters() {
  showCharView('list');
  try {
    const chars = await api('/api/characters');
    state.characters = chars;
    renderCharTable(chars);
  } catch { /* handled */ }
}

function renderCharTable(chars) {
  const body = $('char-table-body');
  if (!body) return;
  if (chars.length === 0) {
    body.innerHTML = '<tr><td colspan="6" class="empty-state">No characters yet. Click "+ New Character" to create one.</td></tr>';
    return;
  }
  body.innerHTML = chars.map(c => `
    <tr>
      <td><a href="#" class="char-link" data-id="${esc(c.id)}" style="color: #667eea; text-decoration: none;">${esc(c.name)}</a></td>
      <td>${c.age || '-'}</td>
      <td>${esc(c.sex || '-')}</td>
      <td>${esc(c.mood || 'neutral')}</td>
      <td>${Math.round((c.relationship_level || 0) * 100)}%</td>
      <td>
        <button class="btn btn-ghost btn-sm char-edit-btn" data-id="${esc(c.id)}">Edit</button>
        <button class="btn btn-danger btn-sm char-del-btn" data-id="${esc(c.id)}">Del</button>
      </td>
    </tr>`).join('');

  // Bind row actions
  body.querySelectorAll('.char-link').forEach(a => {
    a.addEventListener('click', (e) => { e.preventDefault(); showCharDetail(a.dataset.id); });
  });
  body.querySelectorAll('.char-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => openCharForm(btn.dataset.id));
  });
  body.querySelectorAll('.char-del-btn').forEach(btn => {
    btn.addEventListener('click', () => deleteChar(btn.dataset.id));
  });
}

function showCharView(view) {
  $('char-list-view').style.display = view === 'list' ? '' : 'none';
  $('char-form-view').style.display = view === 'form' ? '' : 'none';
  $('char-detail-view').style.display = view === 'detail' ? '' : 'none';
}

async function openCharForm(charId) {
  showCharView('form');
  // Populate personality dropdown
  await loadPersonalityOptions();

  if (charId) {
    // Edit mode
    $('char-form-title').textContent = 'EDIT CHARACTER';
    $('char-form-id').value = charId;
    try {
      const c = await api('/api/characters/' + charId);
      $('cf-name').value = c.name || '';
      $('cf-age').value = c.age || '';
      $('cf-sex').value = c.sex || '';
      $('cf-personality').value = c.personality_id || '';
      $('cf-hair').value = c.hair_color || '';
      $('cf-eyes').value = c.eye_color || '';
      $('cf-height').value = c.height || '';
      $('cf-body').value = c.body_type || '';
      $('cf-tags').value = (c.tags || []).join(', ');
    } catch { /* handled */ }
  } else {
    // Create mode
    $('char-form-title').textContent = 'NEW CHARACTER';
    $('char-form-id').value = '';
    $('char-form').reset();
  }
}

async function loadPersonalityOptions() {
  try {
    const personalities = await api('/api/personalities');
    state.personalities = personalities;
    const sel = $('cf-personality');
    // Keep the first empty option
    sel.innerHTML = '<option value="">None</option>';
    personalities.forEach(p => {
      sel.innerHTML += `<option value="${esc(p.id)}">${esc(p.name)}</option>`;
    });
  } catch { /* handled */ }
}

async function saveChar() {
  const charId = $('char-form-id').value;
  const name = $('cf-name').value.trim();
  if (!name) {
    toast('Name is required', true);
    return;
  }

  const payload = {
    name,
    age: $('cf-age').value ? parseInt($('cf-age').value, 10) : null,
    sex: $('cf-sex').value || null,
    personality_id: $('cf-personality').value || null,
    hair_color: $('cf-hair').value.trim() || null,
    eye_color: $('cf-eyes').value.trim() || null,
    height: $('cf-height').value.trim() || null,
    body_type: $('cf-body').value.trim() || null,
    tags: csvToArr($('cf-tags').value),
  };

  try {
    if (charId) {
      await api('/api/characters/' + charId, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      toast('Character updated');
    } else {
      await api('/api/characters', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      toast('Character created');
    }
    loadCharacters();
  } catch { /* handled */ }
}

async function deleteChar(charId) {
  if (!confirm('Delete this character? This cannot be undone.')) return;
  try {
    await api('/api/characters/' + charId, { method: 'DELETE' });
    toast('Character deleted');
    loadCharacters();
  } catch { /* handled */ }
}

async function showCharDetail(charId) {
  showCharView('detail');
  state.selectedCharId = charId;
  try {
    const c = await api('/api/characters/' + charId);
    $('char-detail-name').textContent = (c.name || 'Unknown').toUpperCase();

    // Identity panel
    const identity = $('char-detail-identity');
    identity.innerHTML = `
      <table class="dash-table" style="font-size: 0.82rem;">
        <tr><td style="color: rgba(255,255,255,0.45); width: 110px;">Name</td><td>${esc(c.name)}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Age</td><td>${c.age || '-'}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Sex</td><td>${esc(c.sex || '-')}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Hair</td><td>${esc(c.hair_color || '-')}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Eyes</td><td>${esc(c.eye_color || '-')}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Height</td><td>${esc(c.height || '-')}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Build</td><td>${esc(c.body_type || '-')}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Mood</td><td>${esc(c.mood || 'neutral')}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Relationship</td><td>${Math.round((c.relationship_level || 0) * 100)}%</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Energy</td><td>${Math.round((c.energy || 0) * 100)}%</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Tags</td><td>${(c.tags || []).map(t => esc(t)).join(', ') || '-'}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Personality</td><td>${c.personality ? esc(c.personality.name) : '-'}</td></tr>
        <tr><td style="color: rgba(255,255,255,0.45);">Created</td><td>${fmtDate(c.created_at)}</td></tr>
      </table>`;

    // Traits panel
    const traits = $('char-detail-traits');
    traits.innerHTML =
      traitBar('Warmth', c.warmth) +
      traitBar('Formality', c.formality) +
      traitBar('Humor', c.humor) +
      traitBar('Flirtiness', c.flirtiness) +
      traitBar('Intelligence', c.intelligence) +
      traitBar('Creativity', c.creativity) +
      traitBar('Arousal', c.arousal);
  } catch { /* handled */ }
}

// ──── Personalities Panel ────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Personality CRUD
// CONNECTS: /api/personalities, /api/personalities/init

async function loadPersonalities() {
  try {
    const personalities = await api('/api/personalities');
    state.personalities = personalities;
    const body = $('pers-table-body');
    if (!body) return;
    if (personalities.length === 0) {
      body.innerHTML = '<tr><td colspan="4" class="empty-state">No personalities. Click "Initialize Defaults" to create templates.</td></tr>';
      return;
    }
    body.innerHTML = personalities.map(p => {
      const traits = Array.isArray(p.traits) ? p.traits.join(', ') : (p.traits || '-');
      return `
        <tr>
          <td>${esc(p.name)}</td>
          <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${esc(traits)}</td>
          <td>${(p.sexual_openness != null) ? p.sexual_openness.toFixed(1) : '-'}</td>
          <td>${fmtDate(p.created_at)}</td>
        </tr>`;
    }).join('');
  } catch { /* handled */ }
}

async function initPersonalities() {
  try {
    const result = await api('/api/personalities/init', { method: 'POST' });
    toast('Initialized ' + result.created + ' default personalities');
    loadPersonalities();
  } catch { /* handled */ }
}

async function savePersonality() {
  const name = $('pf-name').value.trim();
  const prompt = $('pf-prompt').value.trim();
  if (!name || !prompt) {
    toast('Name and system prompt are required', true);
    return;
  }

  const payload = {
    name,
    system_prompt: prompt,
    traits: csvToArr($('pf-traits').value),
    sexual_openness: parseFloat($('pf-openness').value) || 0.5,
    values: csvToArr($('pf-values').value),
  };

  try {
    await api('/api/personalities', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('Personality created');
    $('pers-form-view').style.display = 'none';
    $('pers-form').reset();
    loadPersonalities();
  } catch { /* handled */ }
}

// ──── Roles Panel ────────────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Role CRUD
// CONNECTS: /api/roles, /api/roles/init

async function loadRoles() {
  try {
    const roles = await api('/api/roles');
    state.roles = roles;
    const body = $('role-table-body');
    if (!body) return;
    if (roles.length === 0) {
      body.innerHTML = '<tr><td colspan="4" class="empty-state">No roles. Click "Initialize Defaults" to create templates.</td></tr>';
      return;
    }
    body.innerHTML = roles.map(r => {
      const traits = Array.isArray(r.required_traits) ? r.required_traits.join(', ') : (r.required_traits || '-');
      return `
        <tr>
          <td>${esc(r.name)}</td>
          <td style="max-width: 350px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${esc(r.description || '-')}</td>
          <td>${esc(traits)}</td>
          <td>${fmtDate(r.created_at)}</td>
        </tr>`;
    }).join('');
  } catch { /* handled */ }
}

async function initRoles() {
  try {
    const result = await api('/api/roles/init', { method: 'POST' });
    toast('Initialized ' + result.created + ' default roles');
    loadRoles();
  } catch { /* handled */ }
}

async function saveRole() {
  const name = $('rf-name').value.trim();
  const desc = $('rf-desc').value.trim();
  if (!name || !desc) {
    toast('Name and description are required', true);
    return;
  }

  const payload = {
    name,
    description: desc,
    required_traits: csvToArr($('rf-traits').value),
    context: $('rf-context').value.trim(),
    scenario: $('rf-scenario').value.trim(),
  };

  try {
    await api('/api/roles', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('Role created');
    $('role-form-view').style.display = 'none';
    $('role-form').reset();
    loadRoles();
  } catch { /* handled */ }
}

// ──── Memories Panel ─────────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Memory browser, search, add
// CONNECTS: /api/characters, /api/characters/<id>/memories, /api/characters/<id>/memories/search

async function loadMemoryCharSelect() {
  try {
    const chars = await api('/api/characters');
    state.characters = chars;
    const sel = $('mem-char-select');
    sel.innerHTML = '<option value="">Select a character...</option>';
    chars.forEach(c => {
      sel.innerHTML += `<option value="${esc(c.id)}">${esc(c.name)}</option>`;
    });
  } catch { /* handled */ }
}

async function loadMemories(charId) {
  const list = $('mem-list');
  if (!charId) {
    list.innerHTML = '<div class="empty-state">Select a character to view memories.</div>';
    $('mem-add-form').style.display = 'none';
    return;
  }
  $('mem-add-form').style.display = '';
  try {
    const memories = await api('/api/characters/' + charId + '/memories');
    renderMemories(memories, charId);
  } catch { /* handled */ }
}

function renderMemories(memories, charId) {
  const list = $('mem-list');
  if (!memories || memories.length === 0) {
    list.innerHTML = '<div class="empty-state">No memories found.</div>';
    return;
  }
  list.innerHTML = memories.map(m => `
    <div class="memory-card">
      <div class="memory-card__content">${esc(m.content)}</div>
      <div class="memory-card__meta">
        <span>Importance: ${(m.importance != null) ? m.importance.toFixed(1) : '-'}</span>
        <span>Emotion: ${esc(m.emotion || '-')}</span>
        <span>${fmtDate(m.timestamp)}</span>
        <button class="btn btn-danger btn-sm mem-del-btn" data-id="${esc(m.id)}" style="margin-left: auto; padding: 0.2rem 0.5rem; font-size: 0.65rem;">Del</button>
      </div>
    </div>`).join('');

  // Bind delete buttons
  list.querySelectorAll('.mem-del-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api('/api/memories/' + btn.dataset.id, { method: 'DELETE' });
        toast('Memory deleted');
        loadMemories(charId);
      } catch { /* handled */ }
    });
  });
}

async function searchMemories() {
  const charId = $('mem-char-select').value;
  const query = $('mem-search-input').value.trim();
  if (!charId) {
    toast('Select a character first', true);
    return;
  }
  if (!query) {
    // If empty search, load all memories
    loadMemories(charId);
    return;
  }
  try {
    const results = await api('/api/characters/' + charId + '/memories/search?q=' + encodeURIComponent(query));
    renderMemories(results, charId);
  } catch { /* handled */ }
}

async function addMemory() {
  const charId = $('mem-char-select').value;
  if (!charId) {
    toast('Select a character first', true);
    return;
  }
  const content = $('mf-content').value.trim();
  if (!content) {
    toast('Content is required', true);
    return;
  }

  const payload = {
    content,
    importance: parseFloat($('mf-importance').value) || 0.5,
    emotion: $('mf-emotion').value.trim() || null,
  };

  try {
    await api('/api/characters/' + charId + '/memories', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('Memory added');
    $('mf-content').value = '';
    $('mf-emotion').value = '';
    $('mf-importance').value = '0.5';
    loadMemories(charId);
  } catch { /* handled */ }
}

// ──── Event Binding ──────────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Wire all buttons and selects to their handlers
function bindEvents() {
  // Characters
  $('btn-new-char')?.addEventListener('click', () => openCharForm(null));
  $('btn-char-back')?.addEventListener('click', () => loadCharacters());
  $('btn-char-save')?.addEventListener('click', () => saveChar());
  $('btn-char-cancel')?.addEventListener('click', () => loadCharacters());
  $('btn-detail-back')?.addEventListener('click', () => loadCharacters());
  $('btn-detail-edit')?.addEventListener('click', () => {
    if (state.selectedCharId) openCharForm(state.selectedCharId);
  });
  $('btn-detail-delete')?.addEventListener('click', () => {
    if (state.selectedCharId) deleteChar(state.selectedCharId);
  });

  // Personalities
  $('btn-new-pers')?.addEventListener('click', () => {
    $('pers-form-view').style.display = '';
  });
  $('btn-pers-cancel')?.addEventListener('click', () => {
    $('pers-form-view').style.display = 'none';
    $('pers-form').reset();
  });
  $('btn-pers-save')?.addEventListener('click', () => savePersonality());
  $('btn-init-pers')?.addEventListener('click', () => initPersonalities());

  // Roles
  $('btn-new-role')?.addEventListener('click', () => {
    $('role-form-view').style.display = '';
  });
  $('btn-role-cancel')?.addEventListener('click', () => {
    $('role-form-view').style.display = 'none';
    $('role-form').reset();
  });
  $('btn-role-save')?.addEventListener('click', () => saveRole());
  $('btn-init-roles')?.addEventListener('click', () => initRoles());

  // Memories
  $('mem-char-select')?.addEventListener('change', (e) => {
    loadMemories(e.target.value);
  });
  $('btn-mem-search')?.addEventListener('click', () => searchMemories());
  $('mem-search-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchMemories();
  });
  $('btn-mem-save')?.addEventListener('click', () => addMemory());
}

// ──── Init ───────────────────────────────────────────────────────────────

// v1.49.2 [2026-03-22] — Bootstrap on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  bindEvents();
  // Load overview on start
  loadOverview();
});
