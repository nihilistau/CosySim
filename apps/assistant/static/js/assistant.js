/**
 * CosySim Assistant — Frontend SPA
 * v1.0.0 [2026-03-23]
 *
 * Vanilla JS single-page app: chat, conversations, model selection,
 * file upload, streaming via SocketIO, settings persistence.
 */
'use strict';

(function () {
  // ── State ────────────────────────────────────────────────────
  const state = {
    conversations: [],
    currentId: null,
    models: [],
    settings: {},
    isGenerating: false,
    attachments: [],
  };

  // ── DOM Refs ─────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const els = {};
  function resolveEls() {
    els.sidebar = $('sidebar');
    els.sidebarToggle = $('sidebar-toggle');
    els.newChatBtn = $('new-chat-btn');
    els.convList = $('conversation-list');
    els.modelSelect = $('model-select');
    els.settingsBtn = $('settings-btn');
    els.messages = $('messages');
    els.welcome = $('welcome');
    els.input = $('message-input');
    els.sendBtn = $('send-btn');
    els.fileInput = $('file-input');
    els.attachments = $('attachments');
    els.charCount = $('char-count');
    els.settingsModal = $('settings-modal');
    els.settingsClose = $('settings-close');
    els.settingsSave = $('settings-save');
    els.settingTemp = $('setting-temperature');
    els.settingTempVal = $('temperature-value');
    els.settingMaxTokens = $('setting-max-tokens');
    els.settingSysPrompt = $('setting-system-prompt');
    els.settingDefaultModel = $('setting-default-model');
    els.dropZone = $('file-drop-zone');
    els.localModels = $('local-models');
  }

  // ── API Client ───────────────────────────────────────────────
  const api = {
    async get(url) {
      const r = await fetch(url);
      return r.ok ? r.json() : null;
    },
    async post(url, data) {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return r.json();
    },
    async del(url) {
      const r = await fetch(url, { method: 'DELETE' });
      return r.ok;
    },
    async patch(url, data) {
      const r = await fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return r.ok;
    },
    async upload(file) {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch('/api/upload', { method: 'POST', body: fd });
      return r.json();
    },
  };

  // ── Socket.IO ────────────────────────────────────────────────
  const socket = io();
  let currentAssistantEl = null;
  let currentAssistantContent = '';

  socket.on('chat_delta', (data) => {
    if (!currentAssistantEl) {
      hideWelcome();
      currentAssistantEl = appendMessage('assistant', '');
      currentAssistantContent = '';
    }
    currentAssistantContent += data.content;
    const contentEl = currentAssistantEl.querySelector('.msg-content');
    contentEl.innerHTML = renderMarkdown(currentAssistantContent);
    scrollToBottom();
  });

  socket.on('chat_complete', (data) => {
    state.isGenerating = false;
    updateInputState();
    currentAssistantEl = null;
    currentAssistantContent = '';
    loadConversations(); // refresh sidebar
  });

  socket.on('chat_error', (data) => {
    state.isGenerating = false;
    updateInputState();
    appendMessage('system', `Error: ${data.error}`);
    currentAssistantEl = null;
    currentAssistantContent = '';
  });

  socket.on('conversation_created', (conv) => {
    state.currentId = conv.id;
    loadConversations();
  });

  socket.on('message_saved', () => {
    // User message was saved — could update UI if needed
  });

  // ── Message Rendering ────────────────────────────────────────
  function appendMessage(role, content, msgId) {
    const div = document.createElement('div');
    div.className = `msg msg--${role}`;
    if (msgId) div.dataset.msgId = msgId;

    const header = document.createElement('div');
    header.className = 'msg-header';

    const roleLabel = document.createElement('span');
    roleLabel.className = 'msg-role';
    roleLabel.textContent = role === 'assistant' ? `Assistant · ${els.modelSelect.value}` : role;
    header.appendChild(roleLabel);

    if (msgId && state.currentId) {
      const forkBtn = document.createElement('button');
      forkBtn.className = 'msg-fork-btn';
      forkBtn.textContent = '⑂ Fork';
      forkBtn.title = 'Fork conversation from this message';
      forkBtn.addEventListener('click', () => forkFromMessage(msgId));
      header.appendChild(forkBtn);
    }

    div.appendChild(header);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'msg-content';
    if (role === 'assistant') {
      contentDiv.innerHTML = content
        ? renderMarkdown(content)
        : '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
    } else {
      contentDiv.textContent = content;
    }
    div.appendChild(contentDiv);

    els.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
      try {
        return marked.parse(text, { breaks: true });
      } catch {
        return escapeHtml(text);
      }
    }
    return escapeHtml(text).replace(/\n/g, '<br>');
  }

  function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  function hideWelcome() {
    if (els.welcome) els.welcome.style.display = 'none';
  }

  function showWelcome() {
    if (els.welcome) els.welcome.style.display = '';
  }

  function scrollToBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  // ── Conversations ────────────────────────────────────────────
  async function loadConversations() {
    const data = await api.get('/api/conversations?limit=50');
    if (!data) return;
    state.conversations = data.conversations || [];
    renderConversationList();
  }

  function renderConversationList() {
    els.convList.innerHTML = '';
    for (const conv of state.conversations) {
      const div = document.createElement('div');
      div.className = `conv-item${conv.id === state.currentId ? ' active' : ''}`;
      div.innerHTML = `
        <span class="conv-title">${escapeHtml(conv.title)}</span>
        <span class="conv-delete" title="Delete">✕</span>
      `;
      div.querySelector('.conv-title').addEventListener('click', () => loadConversation(conv.id));
      div.querySelector('.conv-delete').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteConversation(conv.id);
      });
      els.convList.appendChild(div);
    }
  }

  async function loadConversation(id) {
    const conv = await api.get(`/api/conversations/${id}`);
    if (!conv) return;
    state.currentId = id;

    // Set model from conversation
    if (conv.model) {
      els.modelSelect.value = conv.model;
    }

    // Render messages
    els.messages.innerHTML = '';
    hideWelcome();
    for (const msg of conv.messages || []) {
      appendMessage(msg.role, msg.content, msg.id);
    }
    if (!conv.messages?.length) {
      showWelcome();
    }

    renderConversationList();
  }

  async function createConversation() {
    const model = els.modelSelect.value;
    const conv = await api.post('/api/conversations', { model });
    state.currentId = conv.id;
    els.messages.innerHTML = '';
    showWelcome();
    loadConversations();
    els.input.focus();
  }

  async function deleteConversation(id) {
    await api.del(`/api/conversations/${id}`);
    if (state.currentId === id) {
      state.currentId = null;
      els.messages.innerHTML = '';
      showWelcome();
    }
    loadConversations();
  }

  // ── Send Message ─────────────────────────────────────────────
  function sendMessage() {
    const content = els.input.value.trim();
    if (!content || state.isGenerating) return;

    // Create conversation if needed
    if (!state.currentId) {
      // Will be created by the server
    }

    state.isGenerating = true;
    updateInputState();
    hideWelcome();

    // Show user message immediately
    appendMessage('user', content);

    // Prepend file content if attached
    let fullContent = content;
    if (state.attachments.length > 0) {
      const fileTexts = state.attachments
        .filter((a) => a.text_content)
        .map((a) => `--- ${a.original_name} ---\n${a.text_content}`)
        .join('\n\n');
      if (fileTexts) {
        fullContent = `${fileTexts}\n\n${content}`;
      }
      state.attachments = [];
      els.attachments.innerHTML = '';
    }

    // Emit via SocketIO for streaming
    socket.emit('send_message', {
      conversation_id: state.currentId,
      content: fullContent,
      model: els.modelSelect.value,
    });

    els.input.value = '';
    autoResizeInput();
  }

  function updateInputState() {
    els.sendBtn.disabled = state.isGenerating;
    els.sendBtn.textContent = state.isGenerating ? '...' : 'Send';
    els.input.disabled = state.isGenerating;
    if (!state.isGenerating) els.input.focus();
  }

  // ── Input Auto-Resize ────────────────────────────────────────
  function autoResizeInput() {
    els.input.style.height = 'auto';
    els.input.style.height = Math.min(els.input.scrollHeight, 200) + 'px';
    els.charCount.textContent = els.input.value.length > 0 ? `${els.input.value.length} chars` : '';
  }

  // ── File Upload ──────────────────────────────────────────────
  async function handleFiles(files) {
    for (const file of files) {
      const result = await api.upload(file);
      if (result.error) {
        appendMessage('system', `Upload failed: ${result.error}`);
        continue;
      }
      state.attachments.push(result);

      const chip = document.createElement('div');
      chip.className = 'attachment-chip';
      chip.innerHTML = `
        <span>${escapeHtml(result.original_name)}</span>
        <span class="remove" data-id="${result.id}">✕</span>
      `;
      chip.querySelector('.remove').addEventListener('click', () => {
        state.attachments = state.attachments.filter((a) => a.id !== result.id);
        chip.remove();
      });
      els.attachments.appendChild(chip);
    }
  }

  // ── Settings ─────────────────────────────────────────────────
  async function loadSettings() {
    const settings = await api.get('/api/settings');
    if (!settings) return;
    state.settings = settings;
    els.settingTemp.value = settings.temperature ?? 0.7;
    els.settingTempVal.textContent = settings.temperature ?? 0.7;
    els.settingMaxTokens.value = settings.max_tokens ?? 4096;
    els.settingSysPrompt.value = settings.system_prompt ?? '';
    if (settings.default_model) {
      els.modelSelect.value = settings.default_model;
    }
  }

  async function saveSettings() {
    const settings = {
      temperature: parseFloat(els.settingTemp.value),
      max_tokens: parseInt(els.settingMaxTokens.value, 10),
      system_prompt: els.settingSysPrompt.value,
      default_model: els.settingDefaultModel.value,
    };
    await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    state.settings = settings;
    els.settingsModal.close();
  }

  // ── Models ───────────────────────────────────────────────────
  async function loadModels() {
    const data = await api.get('/api/models');
    if (!data) return;
    state.models = data.models || [];

    // Add local models to the select dropdown
    const localGroup = els.localModels;
    localGroup.innerHTML = '';
    for (const m of state.models) {
      if (m.backend === 'lmstudio') {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.id;
        localGroup.appendChild(opt);
      }
    }

    // Populate settings model dropdown
    if (els.settingDefaultModel) {
      els.settingDefaultModel.innerHTML = '';
      for (const m of state.models) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = `${m.id} (${m.vendor})`;
        els.settingDefaultModel.appendChild(opt);
      }
    }
  }

  // ── Provider Status ──────────────────────────────────────────
  async function loadProviderStatus() {
    const data = await api.get('/api/providers');
    if (!data) return;
    for (const [name, info] of Object.entries(data)) {
      const row = document.querySelector(`[data-provider="${name}"]`);
      if (!row) continue;
      const dot = row.querySelector('.status-dot');
      const count = row.querySelector('.provider-count');
      dot.className = `status-dot ${info.online ? 'online' : 'offline'}`;
      count.textContent = info.models ? `${info.models} models` : '';
    }
  }

  // ── Event Binding ────────────────────────────────────────────
  function bindEvents() {
    // Send
    els.sendBtn.addEventListener('click', sendMessage);
    els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
    els.input.addEventListener('input', autoResizeInput);

    // New chat
    els.newChatBtn.addEventListener('click', createConversation);

    // Sidebar toggle (mobile)
    els.sidebarToggle.addEventListener('click', () => {
      els.sidebar.classList.toggle('open');
    });

    // Settings
    els.settingsBtn.addEventListener('click', () => els.settingsModal.showModal());
    els.settingsClose.addEventListener('click', () => els.settingsModal.close());
    els.settingsSave.addEventListener('click', saveSettings);
    els.settingTemp.addEventListener('input', () => {
      els.settingTempVal.textContent = els.settingTemp.value;
    });

    // Compare
    const compareBtn = $('compare-btn');
    const compareModal = $('compare-modal');
    const compareClose = $('compare-close');
    const compareRun = $('compare-run');
    if (compareBtn && compareModal) {
      compareBtn.addEventListener('click', () => {
        populateModelSelects();
        compareModal.showModal();
      });
      compareClose.addEventListener('click', () => compareModal.close());
      compareRun.addEventListener('click', runComparison);
    }

    // Playground
    const pgBtn = $('playground-btn');
    const pgModal = $('playground-modal');
    const pgClose = $('playground-close');
    const pgRun = $('pg-run');
    const pgTemp = $('pg-temp');
    if (pgBtn && pgModal) {
      pgBtn.addEventListener('click', () => {
        populateModelSelects();
        pgModal.showModal();
      });
      pgClose.addEventListener('click', () => pgModal.close());
      pgRun.addEventListener('click', runPlayground);
      pgTemp.addEventListener('input', () => {
        $('pg-temp-val').textContent = pgTemp.value;
      });
    }

    // File upload
    els.fileInput.addEventListener('change', () => {
      if (els.fileInput.files.length) handleFiles(els.fileInput.files);
      els.fileInput.value = '';
    });

    // Drag & drop
    els.dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      els.dropZone.classList.add('dragover');
    });
    els.dropZone.addEventListener('dragleave', () => {
      els.dropZone.classList.remove('dragover');
    });
    els.dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      els.dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
    });

    // Paste images
    document.addEventListener('paste', (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const files = [];
      for (const item of items) {
        if (item.kind === 'file') files.push(item.getAsFile());
      }
      if (files.length) handleFiles(files);
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'n') {
        e.preventDefault();
        createConversation();
      }
      if (e.key === 'Escape') {
        if (els.settingsModal.open) els.settingsModal.close();
        if (els.sidebar.classList.contains('open')) els.sidebar.classList.remove('open');
      }
    });
  }

  // ── Fork ──────────────────────────────────────────────────────
  async function forkFromMessage(msgId) {
    if (!state.currentId) return;
    const result = await api.post(`/api/conversations/${state.currentId}/fork`, {
      from_message_id: msgId,
    });
    if (result && result.id) {
      await loadConversations();
      loadConversation(result.id);
    }
  }

  // ── Compare ──────────────────────────────────────────────────
  function populateModelSelects() {
    const selects = ['compare-model-a', 'compare-model-b', 'pg-model'];
    for (const id of selects) {
      const sel = $(id);
      if (!sel || sel.options.length > 1) continue;
      sel.innerHTML = '';
      for (const m of state.models) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = `${m.id} (${m.vendor})`;
        sel.appendChild(opt);
      }
    }
  }

  async function runComparison() {
    const prompt = $('compare-prompt').value.trim();
    if (!prompt) return;

    const modelA = $('compare-model-a').value;
    const modelB = $('compare-model-b').value;
    const results = $('compare-results');
    const runBtn = $('compare-run');

    runBtn.disabled = true;
    runBtn.textContent = 'Comparing...';
    results.style.display = 'none';

    const data = await api.post('/api/compare', { prompt, model_a: modelA, model_b: modelB });

    runBtn.disabled = false;
    runBtn.textContent = 'Compare';

    if (data) {
      $('compare-header-a').textContent = data.model_a.model;
      $('compare-header-b').textContent = data.model_b.model;
      $('compare-body-a').innerHTML = renderMarkdown(data.model_a.response);
      $('compare-body-b').innerHTML = renderMarkdown(data.model_b.response);
      results.style.display = 'grid';
    }
  }

  // ── Playground ───────────────────────────────────────────────
  async function runPlayground() {
    const system = $('pg-system').value.trim();
    const prompt = $('pg-input').value.trim();
    const model = $('pg-model').value;
    const temp = parseFloat($('pg-temp').value);
    const output = $('pg-output');
    const runBtn = $('pg-run');

    if (!prompt) return;

    runBtn.disabled = true;
    runBtn.textContent = 'Running...';
    output.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';

    const messages = [];
    if (system) messages.push({ role: 'system', content: system });
    messages.push({ role: 'user', content: prompt });

    try {
      const res = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, messages, temperature: temp, max_tokens: 4096 }),
      });
      const data = await res.json();
      const text = data.choices?.[0]?.message?.content || data.error?.message || 'No response';
      output.innerHTML = renderMarkdown(text);
    } catch (err) {
      output.textContent = `Error: ${err.message}`;
    }

    runBtn.disabled = false;
    runBtn.textContent = 'Run';
  }

  // ── Init ─────────────────────────────────────────────────────
  async function init() {
    resolveEls();
    bindEvents();
    await Promise.all([
      loadConversations(),
      loadModels(),
      loadSettings(),
      loadProviderStatus(),
    ]);
    // Refresh provider status every 30s
    setInterval(loadProviderStatus, 30000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
