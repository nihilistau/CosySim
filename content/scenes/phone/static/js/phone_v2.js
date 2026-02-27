/**
 * CosyPhone OS — Full phone operating system
 * ============================================
 * Modular app system with home screen, dock, lock screen, and 10+ apps.
 * Each app is a self-contained module registered via CosyPhone.registerApp().
 */

(function () {
  'use strict';

  /* ── Utilities ─────────────────────────────────────────── */

  const qs = (s, r) => (r || document).querySelector(s);
  const qsa = (s, r) => Array.from((r || document).querySelectorAll(s));

  function el(tag, props, ...kids) {
    const e = document.createElement(tag);
    if (props) {
      if (typeof props === 'string') { e.className = props; }
      else { Object.entries(props).forEach(([k, v]) => { if (k === 'style' && typeof v === 'object') Object.assign(e.style, v); else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v); else e[k] = v; }); }
    }
    kids.forEach(c => { if (c == null) return; e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso.includes('T') ? iso : iso + 'Z');
    if (isNaN(d)) return '';
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const diff = Math.floor((now - d) / 86400000);
    if (diff < 7) return d.toLocaleDateString([], { weekday: 'short' });
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function toast(msg, ms) {
    const t = qs('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), ms || 2500);
  }

  function initials(name) {
    if (!name) return '?';
    const p = name.trim().split(' ');
    return p.length >= 2 ? (p[0][0] + p[p.length - 1][0]).toUpperCase() : name[0].toUpperCase();
  }

  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function avatarHtml(name, url, cls) {
    const c = cls || 'avatar';
    const safe = esc(initials(name));
    if (url) return `<div class="${c}"><img src="${esc(url)}" alt="${esc(name)}" onerror="this.parentNode.textContent='${safe}'"></div>`;
    return `<div class="${c}">${safe}</div>`;
  }

  async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({ ok: false, error: 'parse error' }));
    if (!j.ok) throw new Error(j.error || 'API error');
    return j;
  }

  /* ══════════════════════════════════════════════════════════
     CosyPhone — Main OS Controller
  ══════════════════════════════════════════════════════════ */

  const CosyPhone = {
    apps: {},
    activeApp: null,
    contacts: [],
    settings: { theme: 'dark', wallpaper: 0, notifications: true, sounds: true, autoReply: true, messaging: true },
    socket: null,

    /* ── Boot ─────────────────────────────────────────── */
    init() {
      this._loadSettings();
      this._applyTheme();
      this._initSocket();
      this._initClock();
      this._initLock();
      this._buildHomeScreen();
      this._loadContacts();
    },

    _loadSettings() {
      try { const s = localStorage.getItem('cosyphone_settings'); if (s) Object.assign(this.settings, JSON.parse(s)); } catch (e) {}
    },
    _saveSettings() {
      try { localStorage.setItem('cosyphone_settings', JSON.stringify(this.settings)); } catch (e) {}
    },

    _applyTheme() {
      document.documentElement.setAttribute('data-theme', this.settings.theme);
      const wp = qs('#wallpaper');
      const wallpapers = [
        'linear-gradient(135deg, #1a1a2e 0%, #16213e 25%, #0f3460 50%, #533483 75%, #e94560 100%)',
        'linear-gradient(135deg, #0c0c0c 0%, #1a1a2e 50%, #16213e 100%)',
        'linear-gradient(180deg, #141e30, #243b55)',
        'linear-gradient(135deg, #232526, #414345)',
        'linear-gradient(135deg, #ff9a9e 0%, #fad0c4 100%)',
        'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)',
        'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
      ];
      wp.style.background = wallpapers[this.settings.wallpaper % wallpapers.length];
    },

    _initSocket() {
      this.socket = io({ transports: ['websocket', 'polling'] });
      this.socket.on('message_new', d => { if (this.apps.messages) this.apps.messages.onMessageNew(d); this._updateBadges(); });
      this.socket.on('typing', d => { if (this.apps.messages) this.apps.messages.onTyping(d); });
      this.socket.on('thread_updated', () => { if (this.apps.messages) this.apps.messages.loadThreads(); });
      this.socket.on('game_event', d => { if (this.apps.messages) this.apps.messages.onGameEvent(d); });
      this.socket.on('mood_update', d => { if (this.apps.mood_ring) this.apps.mood_ring.onMoodUpdate(d); });
      this.socket.on('admin_wipe', () => { toast('All data wiped'); if (this.apps.messages) this.apps.messages.onWipe(); });
      this.socket.on('news_updated', d => { if (this.apps.news) { this.apps.news._loadFeed(); toast('📰 New articles available'); } });
    },

    _initClock() {
      const tick = () => {
        const now = new Date();
        const t = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        qs('#status-time').textContent = t;
        const lt = qs('#lock-time');
        if (lt) lt.textContent = t;
        const ld = qs('#lock-date');
        if (ld) ld.textContent = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
      };
      tick();
      setInterval(tick, 10000);
    },

    _initLock() {
      const lock = qs('#lock-screen');
      lock.onclick = () => {
        lock.classList.add('hidden');
        qs('#home-screen').classList.remove('hidden');
      };
    },

    /* ── App Registry ──────────────────────────────── */
    registerApp(id, app) {
      this.apps[id] = app;
      app.id = id;
      app.phone = this;
    },

    /* ── Home Screen ───────────────────────────────── */
    _buildHomeScreen() {
      const grid = qs('#app-grid');
      const dock = qs('#dock');
      grid.innerHTML = '';
      dock.innerHTML = '';

      const dockApps = ['messages', 'contacts', 'arcade', 'settings'];
      const gridApps = Object.keys(this.apps).filter(id => !dockApps.includes(id));

      gridApps.forEach(id => {
        const app = this.apps[id];
        grid.appendChild(this._makeIcon(id, app));
      });

      dockApps.forEach(id => {
        const app = this.apps[id];
        if (app) dock.appendChild(this._makeIcon(id, app));
      });
    },

    _makeIcon(id, app) {
      const icon = el('div', 'app-icon');
      icon.dataset.appId = id;
      const box = el('div', 'icon-box');
      box.style.background = app.color || '#333';
      box.innerHTML = app.icon || '📱';
      if (app.badge && app.badge() > 0) {
        const b = el('div', 'notif-badge');
        b.textContent = app.badge();
        box.appendChild(b);
      }
      icon.appendChild(box);
      icon.appendChild(el('span', 'app-name', app.name || id));
      icon.onclick = () => this.openApp(id);
      return icon;
    },

    _updateBadges() {
      qsa('.app-icon').forEach(icon => {
        const id = icon.dataset.appId;
        const app = this.apps[id];
        if (!app || !app.badge) return;
        const existing = icon.querySelector('.notif-badge');
        const count = app.badge();
        if (count > 0) {
          if (existing) existing.textContent = count > 99 ? '99+' : count;
          else { const b = el('div', 'notif-badge'); b.textContent = count; icon.querySelector('.icon-box').appendChild(b); }
        } else if (existing) existing.remove();
      });
    },

    /* ── App Lifecycle ─────────────────────────────── */
    openApp(id) {
      const app = this.apps[id];
      if (!app) return;
      this.activeApp = id;
      qs('#home-screen').classList.add('hidden');
      const container = qs('#app-container');
      container.classList.add('open');
      qs('#app-title-bar').textContent = app.name || id;
      qs('#app-header-right').innerHTML = '';
      const body = qs('#app-body');
      body.innerHTML = '';
      body.className = 'app-body';
      if (app.headerRight) {
        qs('#app-header-right').innerHTML = app.headerRight();
      }
      if (app.render) app.render(body);
      if (app.onOpen) app.onOpen();
    },

    closeApp() {
      const id = this.activeApp;
      if (id && this.apps[id] && this.apps[id].onClose) this.apps[id].onClose();
      this.activeApp = null;
      qs('#app-container').classList.remove('open');
      qs('#home-screen').classList.remove('hidden');
      this._updateBadges();
    },

    async _loadContacts() {
      try {
        const data = await api('GET', '/api/contacts');
        this.contacts = data.contacts || [];
      } catch (e) { console.warn('contacts load failed', e); }
    },

    getContact(id) { return this.contacts.find(c => c.id === id); },
  };

  /* ══════════════════════════════════════════════════════════
     APP: Messages
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('messages', {
    name: 'Messages', icon: '💬', color: '#30D158',
    threads: [], activeThread: null, _typingTimers: {},

    badge() { return this.threads.reduce((s, t) => s + (t.unread || 0), 0); },

    render(body) {
      body.innerHTML = `
        <div id="msg-thread-list" class="thread-list"></div>
        <button class="fab" onclick="CosyPhone.apps.messages.showCompose()">✏️</button>
        <div id="chat-screen">
          <div id="chat-nav">
            <button id="chat-back" onclick="CosyPhone.apps.messages.closeChat()"><span>‹</span><span>Back</span></button>
            <div id="chat-avatar-small" class="avatar avatar-sm"></div>
            <div id="chat-title"></div>
            <div id="chat-actions">
              <button class="pill-btn pill-secondary" id="btn-game-invite" style="display:none;font-size:13px" onclick="CosyPhone.apps.messages.startGameInChat()">🎮 Play</button>
            </div>
          </div>
          <div id="chat-messages"></div>
          <div id="attach-popup">
            <div class="attach-item" onclick="CosyPhone.apps.messages.attachPhoto()"><span class="list-icon">📷</span>Photo</div>
            <div class="attach-item" onclick="CosyPhone.apps.messages.attachVoice()"><span class="list-icon">🎙️</span>Voice</div>
          </div>
          <div id="chat-input-bar">
            <button class="input-plus" id="btn-attach" onclick="qs('#attach-popup').classList.toggle('open')">＋</button>
            <button class="input-emoji" id="btn-emoji" onclick="CosyPhone.apps.messages._toggleEmoji()">😊</button>
            <div id="chat-input-wrap"><textarea id="chat-text-input" rows="1" placeholder="Message"></textarea></div>
            <button id="chat-send" disabled onclick="CosyPhone.apps.messages.sendMessage()">↑</button>
          </div>
          <div id="emoji-picker" class="emoji-picker" style="display:none"></div>
        </div>`;
      this._initInput();
      this.loadThreads();
    },

    _initInput() {
      const inp = qs('#chat-text-input');
      const send = qs('#chat-send');
      if (!inp) return;
      inp.oninput = () => {
        send.disabled = !inp.value.trim();
        inp.style.height = 'auto';
        inp.style.height = Math.min(inp.scrollHeight, 120) + 'px';
        if (this.activeThread) CosyPhone.socket.emit('typing', { thread_id: this.activeThread.id, active: true });
      };
      inp.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!send.disabled) this.sendMessage(); } };
      if (!this._clickCleanup) {
        this._clickCleanup = () => { const p = qs('#attach-popup'); if (p) p.classList.remove('open'); };
        document.addEventListener('click', this._clickCleanup);
      }
    },

    onClose() {
      if (this._clickCleanup) { document.removeEventListener('click', this._clickCleanup); this._clickCleanup = null; }
    },

    _toggleEmoji() {
      const picker = qs('#emoji-picker');
      if (!picker) return;
      if (picker.style.display === 'none') {
        if (!picker.innerHTML) {
          const emojis = ['😊','😂','❤️','🔥','👍','😍','🥺','😭','😘','🤗',
            '😏','🙄','😴','🤔','💀','👀','🎉','💕','✨','🌙',
            '🍑','💋','😈','🥰','😳','🤭','💦','🫦','😜','🤤',
            '💖','🦋','🌹','🎶','💫','😇','🥵','💘','🫣','😉'];
          picker.innerHTML = emojis.map(e => `<span class="emoji-btn" onclick="CosyPhone.apps.messages._insertEmoji('${e}')">${e}</span>`).join('');
        }
        picker.style.display = 'flex';
      } else {
        picker.style.display = 'none';
      }
    },

    _insertEmoji(emoji) {
      const inp = qs('#chat-text-input');
      if (!inp) return;
      const start = inp.selectionStart, end = inp.selectionEnd;
      inp.value = inp.value.substring(0, start) + emoji + inp.value.substring(end);
      inp.selectionStart = inp.selectionEnd = start + emoji.length;
      inp.focus();
      inp.dispatchEvent(new Event('input'));
    },

    async loadThreads() {
      try {
        const data = await api('GET', '/api/threads');
        this.threads = data.threads || [];
        this._renderThreads();
      } catch (e) { console.error('loadThreads', e); }
    },

    _renderThreads() {
      const list = qs('#msg-thread-list');
      if (!list) return;
      list.innerHTML = '';
      if (!this.threads.length) {
        list.innerHTML = '<div class="empty-state"><div class="es-icon">💬</div><h3>No messages yet</h3><p>Tap ✏️ to start a conversation</p></div>';
        return;
      }
      this.threads.forEach(t => {
        const name = t.name || t.char_name || 'Chat';
        const av = t.char_avatar || '';
        const item = el('div', 'thread-item anim-fadeIn');
        item.innerHTML = `
          ${avatarHtml(name, av)}
          <div class="thread-info">
            <div class="thread-name">${esc(name)}</div>
            <div class="thread-preview">${esc(t.last_message || '\u00a0')}</div>
          </div>
          <div class="thread-meta">
            <div class="thread-time">${fmtTime(t.updated_at)}</div>
            ${t.unread > 0 ? `<div class="unread-badge">${t.unread > 99 ? '99+' : t.unread}</div>` : ''}
          </div>`;
        item.onclick = () => this.openThread(t);
        list.appendChild(item);
      });
    },

    async openThread(thread) {
      this.activeThread = thread;
      const cs = qs('#chat-screen');
      if (!cs) return;
      cs.classList.add('open');
      qs('#chat-title').textContent = thread.name || thread.char_name || 'Chat';
      const av = qs('#chat-avatar-small');
      av.innerHTML = '';
      const contact = CosyPhone.getContact(thread.char_id);
      av.innerHTML = avatarHtml(thread.name || '?', (contact || {}).avatar || '', 'avatar avatar-sm').replace(/<\/?div[^>]*>/g, '');
      qs('#btn-game-invite').style.display = thread.type === 'dm' ? '' : 'none';
      qs('#chat-messages').innerHTML = '';
      if (CosyPhone.socket) CosyPhone.socket.emit('join_thread', { thread_id: thread.id });
      try {
        const data = await api('GET', `/api/thread/${thread.id}/messages?limit=60`);
        (data.messages || []).forEach(m => this._appendMsg(m, true));
        this._scrollBottom(false);
      } catch (e) { toast('Failed to load messages'); }
    },

    closeChat() {
      if (qs('#chat-screen')) qs('#chat-screen').classList.remove('open');
      this.activeThread = null;
      this.loadThreads();
    },

    _appendMsg(msg, batch) {
      const box = qs('#chat-messages');
      if (!box) return;
      const isOut = msg.sender_id === 'user';
      const isSys = msg.sender_id === 'system' || msg.msg_type === 'system';
      const isGame = msg.msg_type === 'game';
      const contact = CosyPhone.getContact(msg.sender_id) || {};
      const row = el('div', `msg-row ${isSys || isGame ? (isGame ? 'game' : 'sys') : isOut ? 'out' : 'in'}`);

      if (!isOut && !isSys) {
        row.innerHTML += avatarHtml(contact.name || '?', contact.avatar || '', 'avatar avatar-xs');
      }

      // Strip LLM token artifacts
      let content = msg.content || '';
      content = content.replace(/<\|(?:begin|end|start|eot|pad)_of_text\|>/gi, '').replace(/<\|(?:im_start|im_end|endoftext)\|>/gi, '').trim();

      let bubbleHtml = '';
      if (msg.msg_type === 'voice' && msg.media_path) {
        const file = msg.media_path.split('/').pop().split('\\').pop();
        bubbleHtml = `<div class="bubble voice-bubble"><button class="voice-play-btn" onclick="this.nextElementSibling.nextElementSibling.play()">▶</button><div class="voice-waveform"></div><audio src="/media/voice/${file}" style="display:none"></audio></div>`;
      } else if (msg.msg_type === 'photo' && msg.media_path) {
        const file = msg.media_path.split('/').pop().split('\\').pop();
        bubbleHtml = `<div class="bubble media-bubble"><img src="/media/photo/${file}" alt="photo"></div>`;
      } else if (msg.msg_type === 'video' && msg.media_path) {
        const file = msg.media_path.split('/').pop().split('\\').pop();
        bubbleHtml = `<div class="bubble media-bubble"><video controls preload="metadata" src="/media/video/${file}"></video></div>`;
      } else {
        bubbleHtml = `<div class="bubble">${esc(content)}<span class="bubble-time">${fmtTime(msg.created_at)}</span></div>`;
      }
      row.innerHTML += bubbleHtml;
      box.appendChild(row);
      if (!batch) this._scrollBottom(true);
    },

    _basename(p) { return p ? p.split('/').pop().split('\\').pop() : ''; },

    _scrollBottom(smooth) {
      const box = qs('#chat-messages');
      if (!box) return;
      requestAnimationFrame(() => { box.scrollTo({ top: box.scrollHeight, behavior: smooth ? 'smooth' : 'instant' }); });
    },

    async sendMessage() {
      const inp = qs('#chat-text-input');
      const text = inp.value.trim();
      if (!text || !this.activeThread) return;
      inp.value = ''; inp.style.height = ''; qs('#chat-send').disabled = true;
      try { await api('POST', `/api/thread/${this.activeThread.id}/send`, { content: text, type: 'text' }); }
      catch (e) { toast('Failed to send'); }
    },

    async showCompose() {
      if (!CosyPhone.contacts.length) {
        await CosyPhone._loadContacts();
      }
      if (!CosyPhone.contacts.length) { toast('No contacts available'); return; }
      // Show contact picker overlay
      const box = qs('#chat-messages') ? qs('#chat-messages').parentElement : qs('#msg-thread-list');
      if (!box) return;
      const picker = el('div', { style: { position:'absolute',inset:'0',background:'var(--bg)',zIndex:'30',display:'flex',flexDirection:'column' } });
      picker.innerHTML = `
        <div style="padding:12px 16px;display:flex;align-items:center;gap:8px;border-bottom:.5px solid var(--sep)">
          <button class="pill-btn pill-secondary" id="compose-cancel">Cancel</button>
          <div style="flex:1;text-align:center;font-weight:600">New Message</div>
        </div>
        <div class="thread-list" id="compose-contacts"></div>`;
      const appBody = qs('#app-body');
      appBody.appendChild(picker);
      qs('#compose-cancel').onclick = () => picker.remove();
      const list = qs('#compose-contacts');
      CosyPhone.contacts.forEach(c => {
        const row = el('div', 'thread-item');
        row.innerHTML = `${avatarHtml(c.name, c.avatar)}<div class="thread-info"><div class="thread-name">${esc(c.name)}</div><div class="thread-preview">${esc(c.mood || c.status || 'Available')}</div></div>`;
        row.onclick = () => { picker.remove(); this._openDM(c.id, c.name); };
        list.appendChild(row);
      });
    },

    async _openDM(charId, charName) {
      try {
        const data = await api('POST', '/api/threads/dm', { character_id: charId });
        this.openThread({ id: data.thread_id, type: 'dm', name: charName, char_id: charId });
      } catch (e) { toast('Could not open conversation'); }
    },

    startGameInChat() {
      if (!this.activeThread) return;
      if (confirm('Start Truth or Dare?')) {
        api('POST', '/api/games/start', { thread_id: this.activeThread.id, character_id: this.activeThread.char_id }).catch(() => toast('Failed to start game'));
      }
    },
    attachPhoto() { toast('📷 Photo sharing coming soon'); },
    attachVoice() { toast('🎙️ Voice messages coming soon'); },

    onMessageNew(data) {
      const { thread_id, message } = data;
      const idx = this.threads.findIndex(t => t.id === thread_id);
      if (idx !== -1) { this.threads[idx].last_message = message.content || '[media]'; this.threads[idx].updated_at = message.created_at; }
      if (this.activeThread && this.activeThread.id === thread_id) { this._appendMsg(message); }
      else if (idx !== -1) { this.threads[idx].unread = (this.threads[idx].unread || 0) + 1; }
      else { this.loadThreads(); return; }
      this._renderThreads();
    },

    onTyping(data) {
      if (!this.activeThread || this.activeThread.id !== data.thread_id) return;
      const tid = `typing_${data.char_id}`;
      if (data.active) {
        if (!qs(`#${tid}`)) {
          const contact = CosyPhone.getContact(data.char_id) || {};
          const row = el('div', 'msg-row in');
          row.id = tid;
          row.innerHTML = `${avatarHtml(contact.name || '?', '', 'avatar avatar-xs')}<div class="bubble typing-indicator"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>`;
          qs('#chat-messages').appendChild(row);
          this._scrollBottom(true);
        }
        clearTimeout(this._typingTimers[data.char_id]);
        this._typingTimers[data.char_id] = setTimeout(() => { const e = qs(`#${tid}`); if (e) e.remove(); }, 5000);
      } else { const e = qs(`#${tid}`); if (e) e.remove(); }
    },

    onGameEvent(data) { /* game events handled in chat */ },
    onWipe() { this.threads = []; this.activeThread = null; if (qs('#chat-screen')) qs('#chat-screen').classList.remove('open'); this._renderThreads(); },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Contacts
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('contacts', {
    name: 'Contacts', icon: '👥', color: '#64D2FF',

    render(body) {
      body.innerHTML = '<div id="contacts-list"></div>';
      this._load();
    },

    async _load() {
      try {
        const data = await api('GET', '/api/contacts');
        CosyPhone.contacts = data.contacts || [];
        const list = qs('#contacts-list');
        if (!list) return;
        list.innerHTML = '';
        if (!CosyPhone.contacts.length) {
          list.innerHTML = '<div class="empty-state"><div class="es-icon">👥</div><h3>No contacts</h3><p>Characters will appear here</p></div>';
          return;
        }
        CosyPhone.contacts.forEach(c => {
          const card = el('div', 'list-row');
          card.innerHTML = `
            ${avatarHtml(c.name, c.avatar, 'avatar')}
            <div style="flex:1;min-width:0">
              <div style="font-size:16px;font-weight:600">${esc(c.name)}</div>
              <div style="font-size:13px;color:var(--label2);margin-top:2px">${esc(c.mood || c.status || 'Available')}</div>
            </div>
            <button class="pill-btn pill-primary" style="font-size:13px" onclick="event.stopPropagation(); CosyPhone.apps.messages._openDM('${esc(c.id)}','${esc(c.name)}'); CosyPhone.openApp('messages')">💬 Chat</button>`;
          list.appendChild(card);
        });
      } catch (e) { console.error('contacts', e); }
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Gallery
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('gallery', {
    name: 'Gallery', icon: '🖼️', color: '#FF9F0A',
    _images: [], _idx: 0,

    render(body) {
      body.innerHTML = `
        <div class="section-header">Photos &amp; Videos</div>
        <div class="gallery-grid" id="gallery-grid"></div>
        <div id="gallery-viewer" style="display:none">
          <button class="close-btn" onclick="CosyPhone.apps.gallery._closeViewer()">✕</button>
          <button class="nav-btn nav-prev" onclick="CosyPhone.apps.gallery._nav(-1)">‹</button>
          <div id="gallery-media-wrap" style="display:flex;align-items:center;justify-content:center;max-width:100%;max-height:80%"></div>
          <button class="nav-btn nav-next" onclick="CosyPhone.apps.gallery._nav(1)">›</button>
          <div style="position:absolute;bottom:20px;display:flex;gap:12px">
            <button class="pill-btn pill-danger" onclick="CosyPhone.apps.gallery._delete()">🗑️ Delete</button>
          </div>
        </div>`;
      this._load();
      this._keyNav = (e) => {
        if (qs('#gallery-viewer')?.style.display !== 'none') {
          if (e.key === 'ArrowLeft') this._nav(-1);
          else if (e.key === 'ArrowRight') this._nav(1);
          else if (e.key === 'Escape') this._closeViewer();
        }
      };
      document.addEventListener('keydown', this._keyNav);
    },

    onClose() { if (this._keyNav) { document.removeEventListener('keydown', this._keyNav); this._keyNav = null; } },

    _closeViewer() {
      const wrap = qs('#gallery-media-wrap');
      if (wrap) { const v = wrap.querySelector('video'); if (v) v.pause(); }
      qs('#gallery-viewer').style.display = 'none';
    },

    _showMedia() {
      const wrap = qs('#gallery-media-wrap');
      if (!wrap || !this._images.length) return;
      const item = this._images[this._idx];
      if (item.type === 'video') {
        wrap.innerHTML = `<video controls autoplay preload="auto" src="${esc(item.url)}" style="max-width:100%;max-height:80vh;border-radius:8px"></video>`;
      } else {
        wrap.innerHTML = `<img src="${esc(item.url)}" style="max-width:100%;max-height:80vh;border-radius:8px">`;
      }
    },

    _nav(dir) {
      if (!this._images.length) return;
      const wrap = qs('#gallery-media-wrap');
      if (wrap) { const v = wrap.querySelector('video'); if (v) v.pause(); }
      this._idx = (this._idx + dir + this._images.length) % this._images.length;
      this._showMedia();
    },

    async _delete() {
      if (!this._images.length) return;
      const img = this._images[this._idx];
      if (!confirm('Delete this media?')) return;
      try { await api('DELETE', `/api/gallery/${img.id || img.name}`); } catch (e) {}
      this._images.splice(this._idx, 1);
      if (!this._images.length) { this._closeViewer(); this._load(); return; }
      this._idx = Math.min(this._idx, this._images.length - 1);
      this._showMedia();
      const grid = qs('#gallery-grid');
      if (grid) { grid.innerHTML = ''; this._images.forEach((im, i) => grid.appendChild(this._makeThumb(im, i))); }
    },

    _makeThumb(item, i) {
      const div = el('div', 'gallery-item');
      if (item.type === 'video') {
        div.innerHTML = `<video src="${esc(item.url)}" preload="metadata" muted></video><span class="vid-badge">▶ VID</span>`;
      } else {
        div.innerHTML = `<img src="${esc(item.url)}" alt="${esc(item.name || 'photo')}" loading="lazy">`;
      }
      div.onclick = () => { this._idx = i; this._showMedia(); qs('#gallery-viewer').style.display = 'flex'; };
      return div;
    },

    async _load() {
      const grid = qs('#gallery-grid');
      if (!grid) return;
      try {
        const data = await api('GET', '/api/gallery');
        this._images = data.images || [];
        if (!this._images.length) { grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="es-icon">📷</div><h3>No media yet</h3><p>Photos and videos will appear here</p></div>'; return; }
        grid.innerHTML = '';
        this._images.forEach((img, i) => grid.appendChild(this._makeThumb(img, i)));
      } catch (e) { grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="es-icon">📷</div><h3>No photos yet</h3></div>'; }
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Voice Messages
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('voice_msgs', {
    name: 'Voice Msgs', icon: '🎤', color: '#FF375F',

    render(body) {
      body.innerHTML = '<div class="section-header">Voice Messages</div><div id="voice-list"></div>';
      this._load();
    },

    async _load() {
      const list = qs('#voice-list');
      if (!list) return;
      try {
        const data = await api('GET', '/api/voice-messages');
        const msgs = data.messages || [];
        if (!msgs.length) { list.innerHTML = '<div class="empty-state"><div class="es-icon">🎤</div><h3>No voice messages</h3><p>Voice messages from chats will appear here</p></div>'; return; }
        msgs.forEach(m => {
          const item = el('div', 'voice-msg-item');
          item.innerHTML = `
            <button class="vm-play" onclick="this.parentNode.querySelector('audio').play()">▶</button>
            <div class="vm-info">
              <div class="vm-sender">${m.sender || 'Unknown'}</div>
              <div class="vm-time">${fmtTime(m.created_at)}</div>
              <div class="vm-wave"><div class="vm-wave-fill"></div></div>
            </div>
            <div class="vm-duration">${m.duration || '0:00'}</div>
            <audio src="/media/voice/${m.filename}" style="display:none"></audio>`;
          list.appendChild(item);
        });
      } catch (e) { list.innerHTML = '<div class="empty-state"><div class="es-icon">🎤</div><h3>No voice messages</h3></div>'; }
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Video Messages
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('video_msgs', {
    name: 'Videos', icon: '🎬', color: '#5E5CE6',

    render(body) {
      body.innerHTML = '<div class="section-header">Video Messages</div><div id="video-list"></div><div id="video-player-modal" style="display:none;position:absolute;inset:0;background:rgba(0,0,0,.95);z-index:30;flex-direction:column;align-items:center;justify-content:center"><button onclick="CosyPhone.apps.video_msgs._closePlayer()" style="position:absolute;top:60px;right:16px;width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,.2);color:#fff;font-size:18px;display:flex;align-items:center;justify-content:center;z-index:2">✕</button><video id="video-player-full" controls autoplay style="max-width:100%;max-height:80%;border-radius:8px"></video></div>';
      this._load();
    },

    _closePlayer() {
      const v = qs('#video-player-full');
      if (v) v.pause();
      qs('#video-player-modal').style.display = 'none';
    },

    async _load() {
      const list = qs('#video-list');
      if (!list) return;
      try {
        const data = await api('GET', '/api/video-messages');
        const msgs = data.messages || [];
        if (!msgs.length) { list.innerHTML = '<div class="empty-state"><div class="es-icon">🎬</div><h3>No videos yet</h3></div>'; return; }
        msgs.forEach(m => {
          const item = el('div', 'list-row');
          item.innerHTML = `
            <div class="video-thumb"><video src="/media/video/${m.filename}" preload="metadata" muted></video><div class="play-overlay">▶</div></div>
            <div style="flex:1"><div style="font-weight:600">${m.sender || 'Unknown'}</div><div style="font-size:13px;color:var(--label2);margin-top:2px">${fmtTime(m.created_at)}</div></div>`;
          item.onclick = () => {
            const player = qs('#video-player-full');
            if (player) { player.src = '/media/video/' + m.filename; }
            qs('#video-player-modal').style.display = 'flex';
          };
          list.appendChild(item);
        });
      } catch (e) { list.innerHTML = '<div class="empty-state"><div class="es-icon">🎬</div><h3>No videos yet</h3></div>'; }
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Voice Studio
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('voice_studio', {
    name: 'Voice Studio', icon: '🎙️', color: '#BF5AF2',

    render(body) {
      body.innerHTML = `
        <div class="section-header">Voice Studio</div>
        <div class="section-sub">Create and manage voice profiles</div>
        <div class="list-group">
          <div class="list-row" onclick="toast('Voice design studio coming soon')"><span class="list-icon">✨</span><span class="list-label">New Voice Design</span><span class="list-chevron">›</span></div>
          <div class="list-row" onclick="CosyPhone.apps.voice_studio._showPremade()"><span class="list-icon">🗃️</span><span class="list-label">Premade Voices</span><span class="list-value">8 voices</span><span class="list-chevron">›</span></div>
          <div class="list-row" onclick="toast('Recording studio coming soon')"><span class="list-icon">⏺️</span><span class="list-label">Record Sample</span><span class="list-chevron">›</span></div>
        </div>
        <div id="voice-studio-content">
          <div class="section-sub" style="margin-top:16px">My Voice Designs</div>
          <div id="voice-designs-list"></div>
        </div>`;
      this._loadDesigns();
    },

    async _showPremade() {
      const content = qs('#voice-studio-content');
      if (!content) return;
      content.innerHTML = '<div class="section-sub" style="margin-top:12px">Loading premade voices…</div>';
      try {
        const data = await api('GET', '/api/voice-studio/premade');
        if (!data.ok || !data.voices || data.voices.length === 0) {
          content.innerHTML = '<div class="empty-state"><div class="es-icon">🗃️</div><h3>No premade voices</h3></div>';
          return;
        }
        let html = '<div class="section-sub" style="margin-top:12px">Premade Voices</div>';
        data.voices.forEach(v => {
          const tags = (v.tags||[]).map(t => `<span style="background:rgba(255,255,255,0.1);border-radius:8px;padding:2px 8px;font-size:10px;margin-right:4px">${esc(t)}</span>`).join('');
          html += `<div class="list-row" style="flex-direction:column;align-items:flex-start;padding:10px 14px;gap:4px">
            <div style="display:flex;justify-content:space-between;width:100%"><strong>${esc(v.name)}</strong><span style="font-size:10px;color:#888">${esc(v.model_size)}</span></div>
            <div style="font-size:11px;color:#aaa">${esc(v.description).substring(0,120)}…</div>
            <div style="margin-top:4px">${tags}</div></div>`;
        });
        content.innerHTML = html;
      } catch(e) {
        content.innerHTML = '<div class="section-sub" style="color:#f44">Failed to load voices</div>';
      }
    },

    async _loadDesigns() {
      const list = qs('#voice-designs-list');
      if (!list) return;
      list.innerHTML = '<div class="empty-state"><div class="es-icon">🎙️</div><h3>No designs yet</h3><p>Create your first voice design above</p></div>';
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Arcade — 5 retro games
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('arcade', {
    name: 'Arcade', icon: '🕹️', color: 'linear-gradient(135deg, #ff0080, #7928ca)',
    _currentGame: null, _raf: null, _canvas: null, _ctx: null,

    render(body) {
      body.style.overflow = 'hidden';
      body.innerHTML = `
        <div class="arcade-cabinet">
          <div class="arcade-header"><button class="arcade-back" onclick="CosyPhone.apps.arcade._showMenu()">☰ Menu</button><h2>COSYARCADE</h2><div id="arcade-score-display" style="color:#0f0;font-family:monospace;font-weight:700"></div></div>
          <div class="arcade-screen"><canvas id="arcade-canvas" width="320" height="480"></canvas>
            <div class="arcade-hud"><span id="hud-score">Score: 0</span><span id="hud-lives">♥♥♥</span></div>
            <div class="arcade-menu" id="arcade-menu">
              <h1>🕹️ COSYARCADE</h1>
              <div class="arcade-game-btn" onclick="CosyPhone.apps.arcade._startGame('snake')">🐍 Snake<div class="score">Classic snake game</div></div>
              <div class="arcade-game-btn" onclick="CosyPhone.apps.arcade._startGame('breakout')">🧱 Breakout<div class="score">Break all the bricks</div></div>
              <div class="arcade-game-btn" onclick="CosyPhone.apps.arcade._startGame('invaders')">👾 Space Invaders<div class="score">Defend Earth</div></div>
              <div class="arcade-game-btn" onclick="CosyPhone.apps.arcade._startGame('tetris')">🟦 Tetris<div class="score">Stack the blocks</div></div>
              <div class="arcade-game-btn" onclick="CosyPhone.apps.arcade._startGame('pong')">🏓 Pong<div class="score">Classic pong vs AI</div></div>
            </div>
            <div class="arcade-gameover" id="arcade-gameover"><h2>GAME OVER</h2><div class="final-score" id="final-score"></div><button class="pill-btn pill-primary" onclick="CosyPhone.apps.arcade._showMenu()">Back to Menu</button></div>
          </div>
          <div class="arcade-controls">
            <div class="arcade-dpad">
              <button class="dpad-btn dpad-up" onpointerdown="CosyPhone.apps.arcade._key('up',true)" onpointerup="CosyPhone.apps.arcade._key('up',false)">▲</button>
              <button class="dpad-btn dpad-down" onpointerdown="CosyPhone.apps.arcade._key('down',true)" onpointerup="CosyPhone.apps.arcade._key('down',false)">▼</button>
              <button class="dpad-btn dpad-left" onpointerdown="CosyPhone.apps.arcade._key('left',true)" onpointerup="CosyPhone.apps.arcade._key('left',false)">◄</button>
              <button class="dpad-btn dpad-right" onpointerdown="CosyPhone.apps.arcade._key('right',true)" onpointerup="CosyPhone.apps.arcade._key('right',false)">►</button>
              <div class="dpad-btn dpad-center"></div>
            </div>
            <div class="arcade-btns">
              <button class="arcade-btn btn-a" onpointerdown="CosyPhone.apps.arcade._key('a',true)" onpointerup="CosyPhone.apps.arcade._key('a',false)">A</button>
              <button class="arcade-btn btn-b" onpointerdown="CosyPhone.apps.arcade._key('b',true)" onpointerup="CosyPhone.apps.arcade._key('b',false)">B</button>
            </div>
          </div>
        </div>`;
      this._canvas = qs('#arcade-canvas');
      this._ctx = this._canvas.getContext('2d');
      this._keys = {};
      this._keyHandler = e => {
        const map = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', ' ': 'a', z: 'a', x: 'b', Enter: 'a' };
        if (map[e.key]) { this._keys[map[e.key]] = e.type === 'keydown'; e.preventDefault(); }
      };
      document.addEventListener('keydown', this._keyHandler);
      document.addEventListener('keyup', this._keyHandler);
    },

    onClose() {
      cancelAnimationFrame(this._raf);
      this._currentGame = null;
      document.removeEventListener('keydown', this._keyHandler);
      document.removeEventListener('keyup', this._keyHandler);
    },

    _key(k, down) { this._keys[k] = down; },

    _showMenu() {
      cancelAnimationFrame(this._raf);
      this._currentGame = null;
      qs('#arcade-menu').style.display = 'flex';
      qs('#arcade-gameover').classList.remove('show');
    },

    _gameOver(score) {
      cancelAnimationFrame(this._raf);
      this._currentGame = null;
      qs('#final-score').textContent = `Score: ${score}`;
      qs('#arcade-gameover').classList.add('show');
      // Submit highscore
      try { api('POST', '/api/arcade/highscore', { game: this._gameName, score }); } catch (e) {}
    },

    _startGame(name) {
      this._gameName = name;
      qs('#arcade-menu').style.display = 'none';
      qs('#arcade-gameover').classList.remove('show');
      this._keys = {};
      const games = { snake: this._snake, breakout: this._breakout, invaders: this._invaders, tetris: this._tetris, pong: this._pong };
      if (games[name]) games[name].call(this);
    },

    /* ── SNAKE ──────────────────────────────────── */
    _snake() {
      const W = 320, H = 480, S = 16;
      const cols = W / S, rows = H / S;
      let snake = [{ x: 10, y: 15 }], dir = { x: 1, y: 0 }, food = {}, score = 0, speed = 120, last = 0;
      const place = () => { food = { x: Math.floor(Math.random() * cols), y: Math.floor(Math.random() * rows) }; };
      place();
      this._currentGame = 'snake';
      const loop = (ts) => {
        if (this._currentGame !== 'snake') return;
        this._raf = requestAnimationFrame(loop);
        if (ts - last < speed) return;
        last = ts;
        if (this._keys.up && dir.y === 0) dir = { x: 0, y: -1 };
        if (this._keys.down && dir.y === 0) dir = { x: 0, y: 1 };
        if (this._keys.left && dir.x === 0) dir = { x: -1, y: 0 };
        if (this._keys.right && dir.x === 0) dir = { x: 1, y: 0 };
        const head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };
        if (head.x < 0 || head.x >= cols || head.y < 0 || head.y >= rows || snake.some(s => s.x === head.x && s.y === head.y)) {
          this._gameOver(score); return;
        }
        snake.unshift(head);
        if (head.x === food.x && head.y === food.y) { score += 10; speed = Math.max(50, speed - 2); place(); }
        else snake.pop();
        // Draw
        const ctx = this._ctx;
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = '#0f0';
        snake.forEach((s, i) => { ctx.fillStyle = i === 0 ? '#0f0' : '#0a0'; ctx.fillRect(s.x * S + 1, s.y * S + 1, S - 2, S - 2); });
        ctx.fillStyle = '#f00'; ctx.fillRect(food.x * S + 2, food.y * S + 2, S - 4, S - 4);
        qs('#hud-score').textContent = `Score: ${score}`;
      };
      this._raf = requestAnimationFrame(loop);
    },

    /* ── BREAKOUT ───────────────────────────────── */
    _breakout() {
      const W = 320, H = 480;
      let paddle = { x: 130, w: 60, h: 10 };
      let ball = { x: 160, y: 400, dx: 3, dy: -3, r: 5 };
      let bricks = [], score = 0, lives = 3;
      const cols = 8, rows = 5, bw = W / cols, bh = 18;
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) bricks.push({ x: c * bw, y: r * bh + 40, w: bw - 2, h: bh - 2, alive: true, color: ['#e74c3c', '#e67e22', '#f1c40f', '#2ecc71', '#3498db'][r] });
      this._currentGame = 'breakout';
      const loop = () => {
        if (this._currentGame !== 'breakout') return;
        this._raf = requestAnimationFrame(loop);
        if (this._keys.left) paddle.x = Math.max(0, paddle.x - 5);
        if (this._keys.right) paddle.x = Math.min(W - paddle.w, paddle.x + 5);
        ball.x += ball.dx; ball.y += ball.dy;
        if (ball.x <= ball.r || ball.x >= W - ball.r) ball.dx = -ball.dx;
        if (ball.y <= ball.r) ball.dy = -ball.dy;
        if (ball.y >= H - paddle.h - 10 && ball.y <= H - 10 && ball.x >= paddle.x && ball.x <= paddle.x + paddle.w) {
          ball.dy = -Math.abs(ball.dy);
          ball.dx += (ball.x - (paddle.x + paddle.w / 2)) * 0.1;
        }
        if (ball.y > H + 20) { lives--; if (lives <= 0) { this._gameOver(score); return; } ball.x = 160; ball.y = 400; ball.dx = 3; ball.dy = -3; }
        bricks.forEach(b => {
          if (!b.alive) return;
          if (ball.x >= b.x && ball.x <= b.x + b.w && ball.y >= b.y && ball.y <= b.y + b.h) { b.alive = false; ball.dy = -ball.dy; score += 10; }
        });
        if (bricks.every(b => !b.alive)) { this._gameOver(score); return; }
        const ctx = this._ctx;
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = '#fff'; ctx.fillRect(paddle.x, H - paddle.h - 10, paddle.w, paddle.h);
        ctx.beginPath(); ctx.arc(ball.x, ball.y, ball.r, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill();
        bricks.forEach(b => { if (!b.alive) return; ctx.fillStyle = b.color; ctx.fillRect(b.x + 1, b.y + 1, b.w, b.h); });
        qs('#hud-score').textContent = `Score: ${score}`;
        qs('#hud-lives').textContent = '♥'.repeat(lives);
      };
      this._raf = requestAnimationFrame(loop);
    },

    /* ── SPACE INVADERS ─────────────────────────── */
    _invaders() {
      const W = 320, H = 480;
      let player = { x: 150, y: H - 30, w: 24, h: 16 };
      let bullets = [], enemyBullets = [], enemies = [], score = 0, lives = 3;
      const ew = 20, eh = 14, ecols = 8, erows = 4;
      let eDir = 1, eSpeed = 0.5, shootCd = 0;
      for (let r = 0; r < erows; r++) for (let c = 0; c < ecols; c++) enemies.push({ x: 30 + c * 32, y: 40 + r * 26, alive: true });
      this._currentGame = 'invaders';
      const loop = () => {
        if (this._currentGame !== 'invaders') return;
        this._raf = requestAnimationFrame(loop);
        if (this._keys.left) player.x = Math.max(0, player.x - 4);
        if (this._keys.right) player.x = Math.min(W - player.w, player.x + 4);
        if (this._keys.a && shootCd <= 0) { bullets.push({ x: player.x + player.w / 2, y: player.y }); shootCd = 15; }
        shootCd--;
        bullets.forEach(b => b.y -= 6);
        bullets = bullets.filter(b => b.y > 0);
        // Move enemies
        let hitEdge = false;
        enemies.forEach(e => { if (!e.alive) return; e.x += eDir * eSpeed; if (e.x <= 0 || e.x >= W - ew) hitEdge = true; });
        if (hitEdge) { eDir = -eDir; enemies.forEach(e => { e.y += 10; }); }
        // Enemy shoot
        const alive = enemies.filter(e => e.alive);
        if (alive.length && Math.random() < 0.02) { const e = alive[Math.floor(Math.random() * alive.length)]; enemyBullets.push({ x: e.x + ew / 2, y: e.y + eh }); }
        enemyBullets.forEach(b => b.y += 3);
        enemyBullets = enemyBullets.filter(b => b.y < H);
        // Collisions
        bullets.forEach(b => {
          enemies.forEach(e => {
            if (!e.alive) return;
            if (b.x >= e.x && b.x <= e.x + ew && b.y >= e.y && b.y <= e.y + eh) { e.alive = false; b.y = -10; score += 25; }
          });
        });
        enemyBullets.forEach(b => {
          if (b.x >= player.x && b.x <= player.x + player.w && b.y >= player.y && b.y <= player.y + player.h) { lives--; b.y = H + 10; if (lives <= 0) { this._gameOver(score); return; } }
        });
        if (enemies.every(e => !e.alive)) { this._gameOver(score); return; }
        if (enemies.some(e => e.alive && e.y >= player.y - 10)) { this._gameOver(score); return; }
        // Draw
        const ctx = this._ctx;
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = '#0f0'; ctx.fillRect(player.x, player.y, player.w, player.h);
        ctx.fillStyle = '#ff0'; bullets.forEach(b => ctx.fillRect(b.x - 1, b.y, 2, 8));
        ctx.fillStyle = '#f00'; enemyBullets.forEach(b => ctx.fillRect(b.x - 1, b.y, 2, 6));
        enemies.forEach(e => { if (!e.alive) return; ctx.fillStyle = '#f0f'; ctx.fillRect(e.x, e.y, ew, eh); });
        qs('#hud-score').textContent = `Score: ${score}`;
        qs('#hud-lives').textContent = '♥'.repeat(Math.max(0, lives));
      };
      this._raf = requestAnimationFrame(loop);
    },

    /* ── TETRIS ─────────────────────────────────── */
    _tetris() {
      const W = 320, H = 480, S = 24;
      const cols = 10, rows = 20;
      const offX = (W - cols * S) / 2, offY = 0;
      const grid = Array.from({ length: rows }, () => Array(cols).fill(0));
      const shapes = [
        [[1,1,1,1]], [[1,1],[1,1]], [[0,1,0],[1,1,1]], [[1,0,0],[1,1,1]], [[0,0,1],[1,1,1]], [[1,1,0],[0,1,1]], [[0,1,1],[1,1,0]]
      ];
      const colors = ['#00f0f0','#f0f000','#a000f0','#0000f0','#f0a000','#00f000','#f00000'];
      let piece, px, py, pIdx, score = 0, speed = 500, last = 0, dropCd = 0;
      const newPiece = () => { pIdx = Math.floor(Math.random() * shapes.length); piece = shapes[pIdx].map(r => [...r]); px = Math.floor((cols - piece[0].length) / 2); py = 0; if (!canPlace(px, py, piece)) { this._gameOver(score); } };
      const canPlace = (x, y, p) => p.every((row, r) => row.every((v, c) => !v || (x + c >= 0 && x + c < cols && y + r >= 0 && y + r < rows && !grid[y + r][x + c])));
      const place = () => { piece.forEach((row, r) => row.forEach((v, c) => { if (v) grid[py + r][px + c] = pIdx + 1; })); };
      const clearLines = () => { let cleared = 0; for (let r = rows - 1; r >= 0; r--) { if (grid[r].every(v => v)) { grid.splice(r, 1); grid.unshift(Array(cols).fill(0)); cleared++; r++; } } score += [0, 100, 300, 500, 800][cleared] || 0; };
      const rotate = () => { const np = piece[0].map((_, c) => piece.map(r => r[c]).reverse()); if (canPlace(px, py, np)) piece = np; };
      newPiece();
      this._currentGame = 'tetris';
      const loop = (ts) => {
        if (this._currentGame !== 'tetris') return;
        this._raf = requestAnimationFrame(loop);
        if (this._keys.left && !this._keys._lp) { if (canPlace(px - 1, py, piece)) px--; this._keys._lp = true; }
        if (!this._keys.left) this._keys._lp = false;
        if (this._keys.right && !this._keys._rp) { if (canPlace(px + 1, py, piece)) px++; this._keys._rp = true; }
        if (!this._keys.right) this._keys._rp = false;
        if (this._keys.a && !this._keys._ap) { rotate(); this._keys._ap = true; }
        if (!this._keys.a) this._keys._ap = false;
        const spd = this._keys.down ? 40 : speed;
        if (ts - last >= spd) {
          last = ts;
          if (canPlace(px, py + 1, piece)) py++;
          else { place(); clearLines(); newPiece(); }
        }
        // Draw
        const ctx = this._ctx;
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
        // Grid
        for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
          if (grid[r][c]) { ctx.fillStyle = colors[grid[r][c] - 1]; ctx.fillRect(offX + c * S + 1, offY + r * S + 1, S - 2, S - 2); }
          else { ctx.strokeStyle = '#111'; ctx.strokeRect(offX + c * S, offY + r * S, S, S); }
        }
        // Current piece
        ctx.fillStyle = colors[pIdx];
        piece.forEach((row, r) => row.forEach((v, c) => { if (v) ctx.fillRect(offX + (px + c) * S + 1, offY + (py + r) * S + 1, S - 2, S - 2); }));
        qs('#hud-score').textContent = `Score: ${score}`;
        qs('#hud-lives').textContent = '';
      };
      this._raf = requestAnimationFrame(loop);
    },

    /* ── PONG ───────────────────────────────────── */
    _pong() {
      const W = 320, H = 480;
      let p1 = { x: 135, y: H - 30, w: 50, h: 8 };
      let p2 = { x: 135, y: 20, w: 50, h: 8 };
      let ball = { x: W / 2, y: H / 2, dx: 3, dy: 3, r: 5 };
      let s1 = 0, s2 = 0;
      this._currentGame = 'pong';
      const reset = () => { ball.x = W / 2; ball.y = H / 2; ball.dx = (Math.random() > .5 ? 1 : -1) * 3; ball.dy = (Math.random() > .5 ? 1 : -1) * 3; };
      const loop = () => {
        if (this._currentGame !== 'pong') return;
        this._raf = requestAnimationFrame(loop);
        if (this._keys.left) p1.x = Math.max(0, p1.x - 5);
        if (this._keys.right) p1.x = Math.min(W - p1.w, p1.x + 5);
        // AI
        const center = p2.x + p2.w / 2;
        if (ball.x < center - 10) p2.x -= 3;
        if (ball.x > center + 10) p2.x += 3;
        p2.x = Math.max(0, Math.min(W - p2.w, p2.x));
        ball.x += ball.dx; ball.y += ball.dy;
        if (ball.x <= ball.r || ball.x >= W - ball.r) ball.dx = -ball.dx;
        // Paddle collisions
        if (ball.y >= p1.y - ball.r && ball.y <= p1.y + p1.h && ball.x >= p1.x && ball.x <= p1.x + p1.w) { ball.dy = -Math.abs(ball.dy); ball.dx += (ball.x - (p1.x + p1.w / 2)) * 0.15; }
        if (ball.y <= p2.y + p2.h + ball.r && ball.y >= p2.y && ball.x >= p2.x && ball.x <= p2.x + p2.w) { ball.dy = Math.abs(ball.dy); ball.dx += (ball.x - (p2.x + p2.w / 2)) * 0.15; }
        if (ball.y < -10) { s1++; reset(); }
        if (ball.y > H + 10) { s2++; reset(); }
        if (s1 >= 7 || s2 >= 7) { this._gameOver(s1 >= 7 ? s1 * 100 : 0); return; }
        const ctx = this._ctx;
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
        ctx.setLineDash([4, 8]); ctx.strokeStyle = '#333'; ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = '#0f0'; ctx.fillRect(p1.x, p1.y, p1.w, p1.h);
        ctx.fillStyle = '#f00'; ctx.fillRect(p2.x, p2.y, p2.w, p2.h);
        ctx.beginPath(); ctx.arc(ball.x, ball.y, ball.r, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill();
        ctx.fillStyle = '#fff'; ctx.font = '24px monospace'; ctx.textAlign = 'center';
        ctx.fillText(s1, W / 2, H / 2 + 40); ctx.fillText(s2, W / 2, H / 2 - 20);
        qs('#hud-score').textContent = `You: ${s1} | AI: ${s2}`;
        qs('#hud-lives').textContent = '';
      };
      this._raf = requestAnimationFrame(loop);
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Games With Friends — 3 turn-based games
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('gwf', {
    name: 'Game Night', icon: '🎲', color: 'linear-gradient(135deg, #5856D6, #AF52DE)',
    _activeGame: null,

    render(body) {
      body.innerHTML = `
        <div class="section-header">Game Night</div>
        <div class="section-sub">Play with your AI friends</div>
        <div id="gwf-main">
          <div class="gwf-card" onclick="CosyPhone.apps.gwf._startWordChain()">
            <div class="gwf-banner" style="background:linear-gradient(135deg,#FF9F0A,#FF375F)">🔗</div>
            <div class="gwf-body"><div class="gwf-title">Word Chain</div><div class="gwf-desc">Take turns saying words — each must start with the last letter of the previous word!</div></div>
          </div>
          <div class="gwf-card" onclick="CosyPhone.apps.gwf._startTrivia()">
            <div class="gwf-banner" style="background:linear-gradient(135deg,#30D158,#0A84FF)">🧠</div>
            <div class="gwf-body"><div class="gwf-title">Trivia Quiz</div><div class="gwf-desc">Test your knowledge across science, history, pop culture and more!</div></div>
          </div>
          <div class="gwf-card" onclick="CosyPhone.apps.gwf._startRPS()">
            <div class="gwf-banner" style="background:linear-gradient(135deg,#BF5AF2,#FF453A)">✊</div>
            <div class="gwf-body"><div class="gwf-title">Rock Paper Scissors</div><div class="gwf-desc">Best of 7 against your AI opponent. Can you outsmart them?</div></div>
          </div>
        </div>
        <div id="gwf-game" style="display:none"></div>`;
    },

    _showMain() { qs('#gwf-main').style.display = ''; qs('#gwf-game').style.display = 'none'; this._activeGame = null; },

    /* ── Word Chain ─────────────────────── */
    _startWordChain() {
      this._activeGame = 'wordchain';
      qs('#gwf-main').style.display = 'none';
      const g = qs('#gwf-game');
      g.style.display = '';
      g.innerHTML = `
        <div style="padding:16px;display:flex;align-items:center;gap:8px"><button class="pill-btn pill-secondary" onclick="CosyPhone.apps.gwf._showMain()">← Back</button><h3 style="flex:1;text-align:center">Word Chain</h3></div>
        <div class="wc-board">
          <div class="wc-chain" id="wc-chain"><div class="wc-word user">Hello</div></div>
          <div class="wc-input-row"><input class="wc-input" id="wc-input" placeholder="Your word..." autocomplete="off"><button class="pill-btn pill-primary" onclick="CosyPhone.apps.gwf._wcSubmit()">Send</button></div>
          <div style="padding:16px 0;font-size:13px;color:var(--label2)" id="wc-status">Your turn! Word must start with 'o'</div>
        </div>`;
      this._wcChain = ['hello'];
      this._wcTurn = 'user';
      qs('#wc-input').onkeydown = e => { if (e.key === 'Enter') this._wcSubmit(); };
    },

    _wcSubmit() {
      const inp = qs('#wc-input');
      const word = (inp.value || '').trim().toLowerCase();
      if (!word) return;
      inp.value = '';
      const lastWord = this._wcChain[this._wcChain.length - 1];
      const needed = lastWord[lastWord.length - 1];
      if (word[0] !== needed) { toast(`Word must start with "${needed}"`); return; }
      if (this._wcChain.includes(word)) { toast('Word already used!'); return; }
      this._wcChain.push(word);
      const chain = qs('#wc-chain');
      chain.innerHTML += `<div class="wc-word user">${word}</div>`;
      qs('#wc-status').textContent = 'AI is thinking...';
      // AI responds
      setTimeout(() => {
        const lastLetter = word[word.length - 1];
        // Simple word lists per letter for offline play
        const words = { a: 'apple,arrow,anchor,atlas,amber', b: 'banana,brave,bridge,bloom,butter', c: 'castle,cloud,circle,crane,coral',
          d: 'dream,dance,dragon,dusk,diamond', e: 'eagle,echo,ember,earth,edge', f: 'flame,frost,forest,fable,flash',
          g: 'glow,garden,ghost,globe,grace', h: 'harbor,heart,horizon,hawk,honey', i: 'island,ivory,iris,iron,ice',
          j: 'jade,jungle,jewel,jest,jazz', k: 'knight,kindle,kite,karma,keen', l: 'light,lunar,legend,leaf,lava',
          m: 'moon,marble,mirror,mist,maple', n: 'night,noble,nature,nest,nova', o: 'ocean,orbit,olive,onyx,opal',
          p: 'pearl,planet,prism,puzzle,phoenix', q: 'quest,quartz,queen,quill,quiet', r: 'river,ruby,rain,realm,rose',
          s: 'star,storm,shadow,spark,silver', t: 'thunder,twilight,tower,tide,torch', u: 'universe,unity,ultra,umbra,urban',
          v: 'violet,valley,vapor,vine,vivid', w: 'wave,winter,whisper,wonder,wind', x: 'xenon,xylophone', y: 'yellow,yacht,yarn,yonder',
          z: 'zenith,zephyr,zodiac,zone' };
        const candidates = (words[lastLetter] || 'thing').split(',').filter(w => !this._wcChain.includes(w));
        const aiWord = candidates.length ? candidates[Math.floor(Math.random() * candidates.length)] : lastLetter + 'ness';
        this._wcChain.push(aiWord);
        chain.innerHTML += `<div class="wc-word ai">${aiWord}</div>`;
        const nextLetter = aiWord[aiWord.length - 1];
        qs('#wc-status').textContent = `Your turn! Word must start with "${nextLetter}"`;
      }, 1000 + Math.random() * 1500);
    },

    /* ── Trivia ─────────────────────────── */
    _startTrivia() {
      this._activeGame = 'trivia';
      qs('#gwf-main').style.display = 'none';
      const g = qs('#gwf-game');
      g.style.display = '';
      this._triviaQ = [
        { q: 'What planet is known as the Red Planet?', opts: ['Mars', 'Venus', 'Jupiter', 'Saturn'], a: 0 },
        { q: 'Who painted the Mona Lisa?', opts: ['Da Vinci', 'Michelangelo', 'Raphael', 'Picasso'], a: 0 },
        { q: 'What is the largest ocean?', opts: ['Pacific', 'Atlantic', 'Indian', 'Arctic'], a: 0 },
        { q: 'Which element has symbol "Au"?', opts: ['Gold', 'Silver', 'Aluminum', 'Argon'], a: 0 },
        { q: 'How many bones in a human body?', opts: ['206', '208', '196', '300'], a: 0 },
        { q: 'What year did the Titanic sink?', opts: ['1912', '1905', '1920', '1898'], a: 0 },
        { q: 'Which gas do plants absorb?', opts: ['CO2', 'Oxygen', 'Nitrogen', 'Helium'], a: 0 },
        { q: 'Capital of Japan?', opts: ['Tokyo', 'Kyoto', 'Osaka', 'Nagoya'], a: 0 },
        { q: 'Speed of light (km/s)?', opts: ['300,000', '150,000', '500,000', '1,000,000'], a: 0 },
        { q: 'Largest mammal?', opts: ['Blue whale', 'Elephant', 'Giraffe', 'Hippo'], a: 0 },
      ];
      this._triviaIdx = 0; this._triviaScore = 0; this._triviaAI = 0;
      g.innerHTML = `
        <div style="padding:16px;display:flex;align-items:center;gap:8px"><button class="pill-btn pill-secondary" onclick="CosyPhone.apps.gwf._showMain()">← Back</button><h3 style="flex:1;text-align:center">Trivia</h3></div>
        <div class="trivia-score-bar"><span id="trivia-you">You: 0</span><span id="trivia-round">1/${this._triviaQ.length}</span><span id="trivia-ai">AI: 0</span></div>
        <div class="trivia-q" id="trivia-q"></div>
        <div class="trivia-options" id="trivia-opts"></div>`;
      this._showTriviaQ();
    },

    _showTriviaQ() {
      if (this._triviaIdx >= this._triviaQ.length) {
        qs('#trivia-q').textContent = `Game Over! You: ${this._triviaScore} — AI: ${this._triviaAI}`;
        qs('#trivia-opts').innerHTML = `<button class="pill-btn pill-primary" onclick="CosyPhone.apps.gwf._showMain()">Done</button>`;
        return;
      }
      const q = this._triviaQ[this._triviaIdx];
      qs('#trivia-q').textContent = q.q;
      qs('#trivia-round').textContent = `${this._triviaIdx + 1}/${this._triviaQ.length}`;
      const opts = qs('#trivia-opts');
      opts.innerHTML = '';
      // Shuffle options but track correct answer
      const indices = [0, 1, 2, 3];
      for (let i = indices.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [indices[i], indices[j]] = [indices[j], indices[i]]; }
      indices.forEach(i => {
        const btn = el('div', 'trivia-opt');
        btn.textContent = q.opts[i];
        btn.onclick = () => this._answerTrivia(i === q.a, btn);
        opts.appendChild(btn);
      });
    },

    _answerTrivia(correct, btn) {
      qsa('.trivia-opt').forEach(o => o.style.pointerEvents = 'none');
      if (correct) { btn.classList.add('correct'); this._triviaScore++; }
      else { btn.classList.add('wrong'); }
      // AI answer (70% accuracy)
      if (Math.random() < 0.7) this._triviaAI++;
      qs('#trivia-you').textContent = `You: ${this._triviaScore}`;
      qs('#trivia-ai').textContent = `AI: ${this._triviaAI}`;
      setTimeout(() => { this._triviaIdx++; this._showTriviaQ(); }, 1200);
    },

    /* ── Rock Paper Scissors ────────────── */
    _startRPS() {
      this._activeGame = 'rps';
      qs('#gwf-main').style.display = 'none';
      const g = qs('#gwf-game');
      g.style.display = '';
      this._rpsScore = { you: 0, ai: 0 };
      g.innerHTML = `
        <div style="padding:16px;display:flex;align-items:center;gap:8px"><button class="pill-btn pill-secondary" onclick="CosyPhone.apps.gwf._showMain()">← Back</button><h3 style="flex:1;text-align:center">Rock Paper Scissors</h3></div>
        <div class="rps-arena">
          <div class="trivia-score-bar" style="width:100%"><span id="rps-you">You: 0</span><span>Best of 7</span><span id="rps-ai">AI: 0</span></div>
          <div class="rps-vs"><div class="rps-hand" id="rps-you-hand">❓</div><div style="font-size:20px;font-weight:700">VS</div><div class="rps-hand" id="rps-ai-hand">❓</div></div>
          <div class="rps-result" id="rps-result"></div>
          <div class="rps-choices">
            <button class="rps-choice" onclick="CosyPhone.apps.gwf._rpsPlay('rock')">✊</button>
            <button class="rps-choice" onclick="CosyPhone.apps.gwf._rpsPlay('paper')">✋</button>
            <button class="rps-choice" onclick="CosyPhone.apps.gwf._rpsPlay('scissors')">✌️</button>
          </div>
        </div>`;
    },

    _rpsPlay(choice) {
      const emoji = { rock: '✊', paper: '✋', scissors: '✌️' };
      const aiChoices = ['rock', 'paper', 'scissors'];
      const aiChoice = aiChoices[Math.floor(Math.random() * 3)];
      qs('#rps-you-hand').textContent = emoji[choice];
      qs('#rps-ai-hand').textContent = emoji[aiChoice];
      const yh = qs('#rps-you-hand'), ah = qs('#rps-ai-hand');
      yh.className = 'rps-hand'; ah.className = 'rps-hand';
      let result;
      if (choice === aiChoice) result = "It's a tie!";
      else if ((choice === 'rock' && aiChoice === 'scissors') || (choice === 'paper' && aiChoice === 'rock') || (choice === 'scissors' && aiChoice === 'paper')) {
        result = 'You win this round! 🎉'; this._rpsScore.you++; yh.classList.add('win'); ah.classList.add('lose');
      } else {
        result = 'AI wins this round!'; this._rpsScore.ai++; ah.classList.add('win'); yh.classList.add('lose');
      }
      qs('#rps-result').textContent = result;
      qs('#rps-you').textContent = `You: ${this._rpsScore.you}`;
      qs('#rps-ai').textContent = `AI: ${this._rpsScore.ai}`;
      if (this._rpsScore.you >= 4 || this._rpsScore.ai >= 4) {
        setTimeout(() => {
          const win = this._rpsScore.you >= 4;
          qs('#rps-result').textContent = win ? '🏆 You won the match!' : '💀 AI won the match!';
          qsa('.rps-choice').forEach(b => b.disabled = true);
        }, 500);
      }
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Mood Ring (Custom showcase #1 — MCP framework viz)
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('mood_ring', {
    name: 'Mood Ring', icon: '💍', color: 'linear-gradient(135deg, #FF375F, #BF5AF2)',
    _interval: null,

    render(body) {
      body.innerHTML = `
        <div class="section-header">Mood Ring</div>
        <div class="section-sub">Live agent emotional state</div>
        <div class="mood-ring" id="mood-ring-viz" style="border-color:var(--accent);box-shadow:0 0 30px rgba(10,132,255,.3)">😊</div>
        <div style="text-align:center;padding:0 0 16px;font-size:15px;color:var(--label2)" id="mood-summary">Reading the room...</div>
        <div class="mood-cards" id="mood-cards"></div>`;
      this._refresh();
      this._interval = setInterval(() => this._refresh(), 5000);
    },

    onClose() { clearInterval(this._interval); },

    async _refresh() {
      const cards = qs('#mood-cards');
      if (!cards) return;
      try {
        const data = await api('GET', '/api/mcp/status');
        const status = data.status || {};
        const chars = status.characters || {};
        const ring = qs('#mood-ring-viz');
        const summary = qs('#mood-summary');
        cards.innerHTML = '';
        const moodColors = { happy: '#30D158', sad: '#64D2FF', angry: '#FF453A', flirty: '#FF375F', nervous: '#FF9F0A', calm: '#0A84FF', excited: '#BF5AF2', neutral: '#8E8E93' };
        const moodEmoji = { happy: '😊', sad: '😢', angry: '😤', flirty: '😘', nervous: '😰', calm: '😌', excited: '🤩', neutral: '😐' };
        let dominant = 'neutral';
        Object.entries(chars).forEach(([id, ch]) => {
          const mood = (ch.state || {}).mood || 'neutral';
          const color = moodColors[mood] || moodColors.neutral;
          const emoji = moodEmoji[mood] || '😐';
          dominant = mood;
          const card = el('div', 'mood-card');
          card.innerHTML = `
            <div class="mc-emoji">${emoji}</div>
            <div class="mc-info">
              <div class="mc-name">${ch.name || id}</div>
              <div class="mc-mood">${mood.charAt(0).toUpperCase() + mood.slice(1)} — ${(ch.state || {}).scene_id || 'roaming'}</div>
              <div class="mc-bar"><div class="mc-fill" style="width:${Math.min(100, (ch.state || {}).trust || 50)}%;background:${color}"></div></div>
            </div>`;
          cards.appendChild(card);
        });
        const dc = moodColors[dominant] || moodColors.neutral;
        ring.style.borderColor = dc;
        ring.style.boxShadow = `0 0 30px ${dc}40`;
        ring.textContent = moodEmoji[dominant] || '😐';
        summary.textContent = `Overall vibe: ${dominant}`;
      } catch (e) {
        cards.innerHTML = '<div class="empty-state"><div class="es-icon">💍</div><h3>No agents active</h3><p>Start a scene to see mood data</p></div>';
      }
    },

    onMoodUpdate(data) { this._refresh(); },
  });

  /* ══════════════════════════════════════════════════════════
     APP: CosyNews (Custom showcase #2 — AI-generated news)
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('news', {
    name: 'CosyNews', icon: '📰', color: 'linear-gradient(135deg, #FF453A, #FF9F0A)',
    _items: [],
    _filter: 'all',
    _stats: null,
    _unread: 0,

    badge() { return this._unread; },

    render(body) {
      body.innerHTML = `
        <div class="section-header">CosyNews</div>
        <div class="section-sub">Curated AI & tech news feed</div>
        <div id="news-stats-bar" class="news-stats-bar" style="display:none"></div>
        <div id="news-filter-bar" class="news-filter-bar"></div>
        <div id="news-feed"></div>`;
      this._loadFeed();
    },

    async _loadFeed() {
      const feed = qs('#news-feed');
      if (!feed) return;
      feed.innerHTML = '<div class="news-loading"><div class="spinner"></div>Loading news…</div>';
      try {
        const r = await fetch('/api/news/feed?limit=50');
        const d = await r.json();
        this._items = d.items || [];
        this._unread = this._items.filter(i => !i.read).length;
        CosyPhone._updateBadges();
        this._loadStats();
        this._renderFilters();
        this._renderItems();
      } catch (e) {
        feed.innerHTML = '<div class="news-empty"><div class="big-icon">📡</div><h3>Feed Unavailable</h3><p>Pull down to retry</p></div>';
      }
    },

    async _loadStats() {
      try {
        const r = await fetch('/api/news/stats');
        const d = await r.json();
        this._stats = d.stats || d;
        const bar = qs('#news-stats-bar');
        if (!bar || !this._stats) return;
        bar.style.display = 'flex';
        bar.innerHTML = `
          <div class="news-stat"><div class="num">${this._stats.total || 0}</div><div class="lbl">Articles</div></div>
          <div class="news-stat"><div class="num">${this._stats.unread || 0}</div><div class="lbl">Unread</div></div>
          <div class="news-stat"><div class="num">${this._stats.liked || 0}</div><div class="lbl">Liked</div></div>`;
      } catch {}
    },

    _renderFilters() {
      const bar = qs('#news-filter-bar');
      if (!bar) return;
      const cats = new Set(['all']);
      this._items.forEach(i => { if (i.category) cats.add(i.category); });
      bar.innerHTML = [...cats].map(c =>
        `<button class="news-filter-btn${c === this._filter ? ' active' : ''}" data-cat="${c}">${c === 'all' ? 'All' : c}</button>`
      ).join('');
      bar.querySelectorAll('.news-filter-btn').forEach(btn => {
        btn.onclick = () => {
          this._filter = btn.dataset.cat;
          bar.querySelectorAll('.news-filter-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this._renderItems();
        };
      });
    },

    _renderItems() {
      const feed = qs('#news-feed');
      if (!feed) return;
      const items = this._filter === 'all' ? this._items : this._items.filter(i => i.category === this._filter);
      if (!items.length) {
        feed.innerHTML = '<div class="news-empty"><div class="big-icon">📰</div><h3>No News Yet</h3><p>Tap refresh to fetch the latest</p></div>';
        return;
      }
      feed.innerHTML = items.map(n => {
        const rel = n.relevance || n.relevance_score || 0;
        const relevance = rel >= 0.7 ? 'high' : rel >= 0.4 ? 'medium' : 'low';
        const isRead = n.is_read || n.read;
        const readCls = isRead ? ' read' : '';
        const fb = typeof n.feedback === 'number' ? n.feedback : 0;
        const likedCls = fb > 0 ? ' liked' : '';
        const dislikedCls = fb < 0 ? ' disliked' : '';
        const emoji = this._catEmoji(n.category);
        const timeAgo = this._timeAgo(n.created_at || n.fetched_at || n.published_at);
        const nid = n.id || n.nexus_id;
        return `
          <div class="news-card anim-fadeIn${readCls}" data-nid="${nid}">
            <div class="news-img" style="background:linear-gradient(135deg,${this._randGrad()})">${emoji}</div>
            <div class="news-content">
              <div style="display:flex;gap:6px;align-items:center;margin-bottom:4px">
                <span class="news-category-tag">${this._esc(n.category || 'general')}</span>
                <span class="news-relevance ${relevance}">${relevance}</span>
              </div>
              <div class="news-headline">${this._esc(n.title)}</div>
              <div class="news-excerpt">${this._esc(n.summary || '')}</div>
              <div class="news-meta">
                <span>${this._esc(n.source_id || n.source || 'Unknown')}</span>
                <span>${timeAgo}</span>
              </div>
            </div>
            <div class="news-actions">
              <div class="action-group">
                <button class="news-action-btn${likedCls}" onclick="CosyPhone.apps.news._feedback('${nid}','up',this)">👍</button>
                <button class="news-action-btn${dislikedCls}" onclick="CosyPhone.apps.news._feedback('${nid}','down',this)">👎</button>
              </div>
              <div class="action-group">
                ${n.url ? `<button class="news-action-btn" onclick="window.open('${n.url}','_blank')">🔗 Open</button>` : ''}
                <button class="news-action-btn" onclick="CosyPhone.apps.news._markRead('${nid}',this)">✓ Read</button>
                <button class="news-action-btn" onclick="CosyPhone.apps.news._delete('${nid}',this)">🗑</button>
              </div>
            </div>
          </div>`;
      }).join('');
    },

    async _feedback(id, direction, btn) {
      try {
        await fetch('/api/news/feedback', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({item_id: id, feedback: direction}) });
        const card = btn.closest('.news-card');
        const item = this._items.find(i => (i.id || i.nexus_id) === id);
        if (item) item.feedback = direction;
        card.querySelectorAll('.news-action-btn').forEach(b => { b.classList.remove('liked','disliked'); });
        btn.classList.add(direction === 'up' ? 'liked' : 'disliked');
        CosyPhone._toast(direction === 'up' ? '👍 Liked' : '👎 Disliked');
      } catch {}
    },

    async _markRead(id, btn) {
      try {
        await fetch('/api/news/feedback', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({item_id: id, action: 'read'}) });
        const card = btn.closest('.news-card');
        card.classList.add('read');
        const item = this._items.find(i => (i.id || i.nexus_id) === id);
        if (item) { item.read = true; this._unread = Math.max(0, this._unread - 1); CosyPhone._updateBadges(); }
        CosyPhone._toast('Marked as read');
      } catch {}
    },

    async _delete(id, btn) {
      try {
        await fetch('/api/news/feedback', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({item_id: id, action: 'delete'}) });
        const card = btn.closest('.news-card');
        card.classList.add('removing');
        setTimeout(() => { card.remove(); }, 300);
        this._items = this._items.filter(i => (i.id || i.nexus_id) !== id);
        CosyPhone._toast('Removed');
      } catch {}
    },

    _catEmoji(cat) {
      const map = { technology: '🤖', ai: '🧠', python: '🐍', llm: '💬', gaming: '🎮', research: '🔬', infrastructure: '🌐', community: '🏠', apps: '📱', science: '🔭', security: '🔒' };
      return map[(cat || '').toLowerCase()] || '📰';
    },

    _timeAgo(ts) {
      if (!ts) return '';
      const diff = (Date.now() - new Date(ts).getTime()) / 1000;
      if (diff < 60) return 'just now';
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    },

    _esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; },

    _randGrad() {
      const colors = ['#1a1a2e,#16213e', '#2d1b69,#11998e', '#fc5c7d,#6a82fb', '#f12711,#f5af19', '#0f0c29,#302b63'];
      return colors[Math.floor(Math.random() * colors.length)];
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: System Dashboard
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('system', {
    name: 'System', icon: '🖥️', color: 'linear-gradient(135deg, #0A84FF, #5E5CE6)',
    _data: null,
    _chatHistory: [],

    render(body) {
      body.innerHTML = `
        <div class="section-header">System Dashboard</div>
        <div class="section-sub">CosySim status & controls</div>
        <div id="sys-tabs" style="display:flex;gap:8px;padding:8px 16px;overflow-x:auto">
          <button class="news-filter-btn active" data-tab="overview" onclick="CosyPhone.apps.system._switchTab('overview',this)">Overview</button>
          <button class="news-filter-btn" data-tab="agents" onclick="CosyPhone.apps.system._switchTab('agents',this)">Agents</button>
          <button class="news-filter-btn" data-tab="scheduler" onclick="CosyPhone.apps.system._switchTab('scheduler',this)">Scheduler</button>
          <button class="news-filter-btn" data-tab="chat" onclick="CosyPhone.apps.system._switchTab('chat',this)">Chat</button>
        </div>
        <div id="sys-content" style="padding:0 16px 80px"></div>`;
      this._loadDashboard();
    },

    _switchTab(tab, btn) {
      qs('#sys-tabs').querySelectorAll('.news-filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (tab === 'overview') this._renderOverview();
      else if (tab === 'agents') this._renderAgents();
      else if (tab === 'scheduler') this._renderScheduler();
      else if (tab === 'chat') this._renderChat();
    },

    async _loadDashboard() {
      const c = qs('#sys-content');
      if (!c) return;
      c.innerHTML = '<div class="news-loading"><div class="spinner"></div>Loading system status…</div>';
      try {
        const r = await fetch('/api/system/dashboard');
        this._data = await r.json();
        this._renderOverview();
      } catch (e) {
        c.innerHTML = '<div class="news-empty"><div class="big-icon">⚠️</div><h3>Dashboard Unavailable</h3></div>';
      }
    },

    _renderOverview() {
      const c = qs('#sys-content');
      if (!c || !this._data) return;
      const d = this._data;
      const dot = (on) => `<span style="color:${on ? 'var(--green)' : 'var(--red)'}">●</span>`;
      const lms = d.lmstudio || {};
      const nex = d.nexus || {};
      const sch = d.scheduler || {};
      const agents = d.agents || [];
      const scenes = d.scenes || [];

      c.innerHTML = `
        <div class="list-group" style="margin-top:8px">
          <div class="list-row"><span class="list-icon">🤖</span><span class="list-label">LMStudio</span><span class="list-value">${dot(lms.online)} ${lms.online ? 'Online' : 'Offline'}</span></div>
          <div class="list-row"><span class="list-icon">🧠</span><span class="list-label">Nexus</span><span class="list-value">${dot(nex.online)} ${nex.online ? 'Online' : 'Offline'}</span></div>
          <div class="list-row"><span class="list-icon">⏱️</span><span class="list-label">Scheduler</span><span class="list-value">${dot(sch.running)} ${sch.running ? 'Running' : 'Stopped'}</span></div>
          <div class="list-row"><span class="list-icon">🎭</span><span class="list-label">Agents</span><span class="list-value">${agents.length}</span></div>
          <div class="list-row"><span class="list-icon">🎬</span><span class="list-label">Scenes</span><span class="list-value">${scenes.length || '—'}</span></div>
        </div>

        ${lms.loaded_models ? `
          <div class="section-sub" style="margin-top:12px">Loaded Models</div>
          <div class="list-group">
            ${(lms.loaded_models || []).map(m => `<div class="list-row"><span class="list-icon">📦</span><span class="list-label" style="font-size:12px">${this._esc(typeof m === 'string' ? m : m.id || m.name || JSON.stringify(m))}</span></div>`).join('')}
          </div>` : ''}

        ${d.metrics && Object.keys(d.metrics).length ? `
          <div class="section-sub" style="margin-top:12px">Metrics</div>
          <div class="list-group">
            ${Object.entries(d.metrics).slice(0,6).map(([k,v]) => `<div class="list-row"><span class="list-label">${this._esc(k)}</span><span class="list-value">${typeof v === 'number' ? v.toFixed(1) : v}</span></div>`).join('')}
          </div>` : ''}

        <button class="pill-btn pill-primary" style="margin-top:16px;width:100%" onclick="CosyPhone.apps.system._loadDashboard()">↻ Refresh</button>`;
    },

    _renderAgents() {
      const c = qs('#sys-content');
      if (!c || !this._data) return;
      const agents = this._data.agents || [];
      if (!agents.length) {
        c.innerHTML = '<div class="news-empty"><div class="big-icon">🤖</div><h3>No Agents</h3></div>';
        return;
      }
      c.innerHTML = `
        <div class="list-group" style="margin-top:8px">
          ${agents.map(a => {
            const name = typeof a === 'string' ? a : a.name || a.id || '?';
            const model = typeof a === 'object' ? (a.model || a.profile || '') : '';
            return `<div class="list-row"><span class="list-icon">🤖</span><span class="list-label">${this._esc(name)}</span><span class="list-value" style="font-size:11px">${this._esc(model)}</span></div>`;
          }).join('')}
        </div>`;
    },

    async _renderScheduler() {
      const c = qs('#sys-content');
      if (!c) return;
      c.innerHTML = '<div class="news-loading"><div class="spinner"></div>Loading tasks…</div>';
      try {
        const r = await fetch('/api/system/scheduler/tasks');
        const d = await r.json();
        const tasks = d.tasks || [];
        if (!tasks.length) {
          c.innerHTML = '<div class="news-empty"><div class="big-icon">⏱️</div><h3>No Tasks</h3></div>';
          return;
        }
        c.innerHTML = `<div class="list-group" style="margin-top:8px">
          ${tasks.map(t => {
            const name = typeof t === 'string' ? t : t.name || t.id || '?';
            const interval = typeof t === 'object' ? (t.interval || t.schedule || '') : '';
            const lastRun = typeof t === 'object' ? (t.last_run || '') : '';
            return `<div class="list-row" style="flex-wrap:wrap">
              <span class="list-icon">📋</span>
              <span class="list-label">${this._esc(name)}</span>
              <span class="list-value" style="font-size:11px">${this._esc(interval)}</span>
              ${lastRun ? `<div style="width:100%;font-size:11px;color:var(--label3);padding-left:36px">Last: ${this._esc(lastRun)}</div>` : ''}
            </div>`;
          }).join('')}
        </div>`;
      } catch (e) {
        c.innerHTML = '<div class="news-empty"><div class="big-icon">⚠️</div><h3>Error</h3></div>';
      }
    },

    _renderChat() {
      const c = qs('#sys-content');
      if (!c) return;
      c.innerHTML = `
        <div id="sys-chat-messages" style="min-height:200px;max-height:400px;overflow-y:auto;margin-top:8px;display:flex;flex-direction:column;gap:8px">
          ${this._chatHistory.map(m => this._chatBubble(m.role, m.text)).join('')}
          ${!this._chatHistory.length ? '<div style="text-align:center;color:var(--label3);padding:40px 0">Chat with the system assistant</div>' : ''}
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;padding-bottom:16px">
          <input id="sys-chat-input" type="text" placeholder="Ask the system…" style="flex:1;padding:10px 14px;border-radius:20px;border:1px solid var(--sep);background:var(--bg3);color:var(--label);font-size:14px"
            onkeydown="if(event.key==='Enter')CosyPhone.apps.system._sendChat()"/>
          <button class="pill-btn pill-primary" onclick="CosyPhone.apps.system._sendChat()" style="border-radius:20px;padding:10px 16px">Send</button>
        </div>`;
      const msgs = qs('#sys-chat-messages');
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
    },

    async _sendChat() {
      const input = qs('#sys-chat-input');
      if (!input) return;
      const msg = input.value.trim();
      if (!msg) return;
      input.value = '';

      this._chatHistory.push({ role: 'user', text: msg });
      const msgs = qs('#sys-chat-messages');
      if (msgs) {
        const placeholder = msgs.querySelector('div[style*="text-align:center"]');
        if (placeholder) placeholder.remove();
        msgs.innerHTML += this._chatBubble('user', msg);
        msgs.innerHTML += '<div id="sys-typing" style="padding:8px 14px;color:var(--label3);font-size:13px">Thinking…</div>';
        msgs.scrollTop = msgs.scrollHeight;
      }

      try {
        const r = await fetch('/api/system/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg })
        });
        const d = await r.json();
        const reply = d.reply || 'No response';
        this._chatHistory.push({ role: 'assistant', text: reply });

        const typing = qs('#sys-typing');
        if (typing) typing.remove();
        if (msgs) {
          msgs.innerHTML += this._chatBubble('assistant', reply);
          msgs.scrollTop = msgs.scrollHeight;
        }
      } catch (e) {
        const typing = qs('#sys-typing');
        if (typing) typing.remove();
        if (msgs) msgs.innerHTML += this._chatBubble('assistant', 'Connection error');
      }
    },

    _chatBubble(role, text) {
      const isUser = role === 'user';
      return `<div style="align-self:${isUser ? 'flex-end' : 'flex-start'};max-width:80%;padding:10px 14px;border-radius:16px;background:${isUser ? 'var(--bubble-out)' : 'var(--bubble-in)'};color:var(--label);font-size:14px;line-height:1.4;word-wrap:break-word">${this._esc(text)}</div>`;
    },

    _esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Settings
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('settings', {
    name: 'Settings', icon: '⚙️', color: '#8E8E93',

    render(body) {
      const s = CosyPhone.settings;
      body.innerHTML = `
        <div class="section-header">Settings</div>

        <div class="section-sub">Appearance</div>
        <div class="list-group">
          <div class="list-row" onclick="CosyPhone.apps.settings._toggleTheme()">
            <span class="list-icon">🌙</span><span class="list-label">Dark Mode</span>
            <div class="setting-toggle ${s.theme === 'dark' ? 'on' : ''}" id="toggle-theme"></div>
          </div>
          <div class="list-row" onclick="CosyPhone.apps.settings._showWallpapers()">
            <span class="list-icon">🖼️</span><span class="list-label">Wallpaper</span><span class="list-chevron">›</span>
          </div>
        </div>

        <div class="section-sub">Notifications</div>
        <div class="list-group">
          <div class="list-row" onclick="CosyPhone.apps.settings._toggle('notifications','toggle-notif')">
            <span class="list-icon">🔔</span><span class="list-label">Notifications</span>
            <div class="setting-toggle ${s.notifications ? 'on' : ''}" id="toggle-notif"></div>
          </div>
          <div class="list-row" onclick="CosyPhone.apps.settings._toggle('sounds','toggle-sounds')">
            <span class="list-icon">🔊</span><span class="list-label">Sounds</span>
            <div class="setting-toggle ${s.sounds ? 'on' : ''}" id="toggle-sounds"></div>
          </div>
        </div>

        <div class="section-sub">AI Behavior</div>
        <div class="list-group">
          <div class="list-row" onclick="CosyPhone.apps.settings._toggleMessaging()">
            <span class="list-icon">💬</span><span class="list-label">Autonomous Messages</span>
            <div class="setting-toggle ${s.messaging ? 'on' : ''}" id="toggle-messaging"></div>
          </div>
          <div class="list-row" onclick="CosyPhone.apps.settings._toggle('autoReply','toggle-autoreply')">
            <span class="list-icon">🤖</span><span class="list-label">Auto Reply</span>
            <div class="setting-toggle ${s.autoReply ? 'on' : ''}" id="toggle-autoreply"></div>
          </div>
          <div class="list-row" onclick="window.open('/overlay','_blank')">
            <span class="list-icon">📊</span><span class="list-label">Control Overlay</span><span class="list-chevron">›</span>
          </div>
          <div class="list-row" onclick="window.open(':8502','_blank')">
            <span class="list-icon">🛠️</span><span class="list-label">Admin Panel</span><span class="list-chevron">›</span>
          </div>
        </div>

        <div class="section-sub">Data</div>
        <div class="list-group">
          <div class="list-row" onclick="CosyPhone.apps.settings._wipe()">
            <span class="list-icon">🗑️</span><span class="list-label danger-label">Wipe All Messages</span>
          </div>
        </div>

        <div class="section-sub">About</div>
        <div class="list-group">
          <div class="list-row" style="cursor:default"><span class="list-icon">📱</span><span class="list-label">CosyPhone OS</span><span class="list-value">v3.2</span></div>
          <div class="list-row" style="cursor:default"><span class="list-icon">⚡</span><span class="list-label">Framework</span><span class="list-value">v3.2</span></div>
        </div>
        <div style="height:32px"></div>

        <div id="wallpaper-picker" style="display:none">
          <div class="section-sub">Choose Wallpaper</div>
          <div class="wallpaper-grid" id="wp-grid"></div>
        </div>`;
    },

    _toggleTheme() {
      CosyPhone.settings.theme = CosyPhone.settings.theme === 'dark' ? 'light' : 'dark';
      CosyPhone._applyTheme();
      CosyPhone._saveSettings();
      const t = qs('#toggle-theme');
      if (t) t.classList.toggle('on');
    },

    _toggle(key, id) {
      CosyPhone.settings[key] = !CosyPhone.settings[key];
      CosyPhone._saveSettings();
      const t = qs(`#${id}`);
      if (t) t.classList.toggle('on');
    },

    async _toggleMessaging() {
      const newVal = !CosyPhone.settings.messaging;
      try {
        const r = await fetch('/api/admin/autotxt-mute', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ muted: !newVal })
        });
        const j = await r.json();
        if (j.ok) {
          CosyPhone.settings.messaging = newVal;
          CosyPhone._saveSettings();
          const t = qs('#toggle-messaging');
          if (t) t.classList.toggle('on');
          toast(newVal ? 'Messages ON' : 'Messages OFF');
        }
      } catch (e) { toast('Failed to toggle'); }
    },

    _showWallpapers() {
      const picker = qs('#wallpaper-picker');
      if (!picker) return;
      picker.style.display = picker.style.display === 'none' ? '' : 'none';
      const grid = qs('#wp-grid');
      grid.innerHTML = '';
      const wallpapers = [
        'linear-gradient(135deg, #1a1a2e 0%, #16213e 25%, #0f3460 50%, #533483 75%, #e94560 100%)',
        'linear-gradient(135deg, #0c0c0c 0%, #1a1a2e 50%, #16213e 100%)',
        'linear-gradient(180deg, #141e30, #243b55)',
        'linear-gradient(135deg, #232526, #414345)',
        'linear-gradient(135deg, #ff9a9e 0%, #fad0c4 100%)',
        'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)',
        'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
      ];
      wallpapers.forEach((wp, i) => {
        const item = el('div', `wp-item${i === CosyPhone.settings.wallpaper ? ' selected' : ''}`);
        item.style.background = wp;
        item.onclick = () => {
          CosyPhone.settings.wallpaper = i;
          CosyPhone._applyTheme();
          CosyPhone._saveSettings();
          qsa('.wp-item').forEach(w => w.classList.remove('selected'));
          item.classList.add('selected');
          toast('Wallpaper changed');
        };
        grid.appendChild(item);
      });
    },

    async _wipe() {
      if (!confirm('Wipe ALL messages and media? This cannot be undone.')) return;
      try {
        await api('POST', '/api/admin/wipe-messages');
        toast('All data wiped');
      } catch (e) { toast('Wipe failed'); }
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Image Generator
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('imagegen', {
    name: 'AI Studio', icon: '🎨', color: 'linear-gradient(135deg, #0070F3, #00DFD8)',

    render(body) {
      body.innerHTML = `
        <div class="section-header">AI Image Studio</div>
        <div class="section-sub">Generate images with ComfyUI</div>
        <div style="padding:0 16px">
          <textarea id="ig-prompt" style="width:100%;height:80px;background:var(--bg2);border:1px solid var(--sep);border-radius:var(--radius);padding:12px;font-size:15px;color:var(--label);resize:none;outline:none" placeholder="Describe the image you want to create..."></textarea>
          <button class="pill-btn pill-primary" style="width:100%;justify-content:center;margin-top:8px" onclick="CosyPhone.apps.imagegen._generate()">✨ Generate</button>
        </div>
        <div id="ig-result" style="padding:16px;text-align:center"></div>`;
    },

    async _generate() {
      const prompt = qs('#ig-prompt').value.trim();
      if (!prompt) { toast('Enter a prompt first'); return; }
      qs('#ig-result').innerHTML = '<div class="news-loading"><div class="spinner"></div>Generating image...</div>';
      try {
        const data = await api('POST', '/api/generate-image', { prompt });
        if (data.image_url) {
          qs('#ig-result').innerHTML = `<img src="${data.image_url}" style="max-width:100%;border-radius:var(--radius)">`;
        } else {
          qs('#ig-result').innerHTML = '<div style="color:var(--label2)">Generation complete — check gallery</div>';
        }
      } catch (e) {
        qs('#ig-result').innerHTML = `<div style="color:var(--red)">Failed: ${e.message}</div>`;
      }
    },
  });

  /* ══════════════════════════════════════════════════════════
     HACKER APP — Spy on any character's state, messages, personality
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('hacker', {
    name: 'Hacker', icon: '🔓', color: 'linear-gradient(135deg, #FF3B30, #8B0000)',
    _target: null,

    render(body) {
      body.innerHTML = `
        <div class="section-header" style="color:#FF3B30">⚡ Hacker Terminal</div>
        <div class="section-sub">Select a target to infiltrate</div>
        <div id="hk-targets" style="padding:0 16px"><div class="news-loading"><div class="spinner"></div>Scanning...</div></div>
        <div id="hk-profile" style="display:none;padding:0 16px"></div>`;
      this._loadTargets();
    },

    async _loadTargets() {
      try {
        const data = await api('GET', '/api/hacker/targets');
        const el = qs('#hk-targets');
        if (!data.ok || !data.targets.length) { el.innerHTML = '<div style="color:var(--label2)">No targets found</div>'; return; }
        el.innerHTML = data.targets.map(t => `
          <div class="contact-row" onclick="CosyPhone.apps.hacker._hack('${t.id}')" style="cursor:pointer;border-left:3px solid ${t.mood==='happy'?'#30D158':t.mood==='angry'?'#FF3B30':'#8E8E93'}">
            <div style="font-size:28px;margin-right:12px">👤</div>
            <div style="flex:1">
              <div style="font-weight:600">${t.name}</div>
              <div style="font-size:12px;color:var(--label2)">Mood: ${t.mood} | Energy: ${Math.round(t.energy)} | 💕${Math.round(t.relationship)}</div>
            </div>
            <div style="color:#FF3B30;font-size:14px">HACK →</div>
          </div>`).join('');
      } catch(e) { qs('#hk-targets').innerHTML = '<div style="color:var(--red)">Scan failed</div>'; }
    },

    async _hack(charId) {
      this._target = charId;
      qs('#hk-targets').style.display = 'none';
      const prof = qs('#hk-profile');
      prof.style.display = 'block';
      prof.innerHTML = '<div class="news-loading"><div class="spinner"></div>Hacking...</div>';

      try {
        const [profileData, msgData] = await Promise.all([
          api('GET', `/api/hacker/${charId}/profile`),
          api('GET', `/api/hacker/${charId}/messages?limit=50`)
        ]);
        const p = profileData.profile || {};
        const state = p.state || {};
        const personality = p.personality || {};
        const msgs = (msgData.messages || []).slice(-30);

        prof.innerHTML = `
          <div style="display:flex;align-items:center;margin-bottom:12px">
            <button class="pill-btn" onclick="CosyPhone.apps.hacker._back()" style="margin-right:8px">← Back</button>
            <span style="font-weight:700;color:#FF3B30;font-size:18px">TARGET: ${charId.replace(/_/g,' ').toUpperCase()}</span>
          </div>

          <div style="background:var(--bg2);border-radius:var(--radius);padding:12px;margin-bottom:12px">
            <div style="font-weight:600;color:#FF3B30;margin-bottom:8px">📊 STATE DUMP</div>
            <div style="font-size:13px;color:var(--label)">
              <div>Mood: <b>${state.mood||'?'}</b> | Energy: <b>${Math.round(state.energy||50)}</b></div>
              <div>Arousal: <b>${Math.round(state.arousal||50)}</b> | Relationship: <b>${Math.round(state.relationship||50)}</b></div>
              <div>Heat: <b>${Math.round(p.heat||0)}</b>/100</div>
              ${state.tiredness!==undefined?`<div>Tiredness: <b>${Math.round(state.tiredness)}</b></div>`:''}
            </div>
          </div>

          ${personality.backstory ? `<div style="background:var(--bg2);border-radius:var(--radius);padding:12px;margin-bottom:12px">
            <div style="font-weight:600;color:#FF3B30;margin-bottom:8px">🧠 PERSONALITY DATA</div>
            <div style="font-size:12px;color:var(--label2);max-height:80px;overflow-y:auto">${personality.backstory}</div>
            ${(personality.traits||[]).length?`<div style="margin-top:6px;font-size:12px">Traits: ${personality.traits.join(', ')}</div>`:''}
            ${(personality.quirks||[]).length?`<div style="font-size:12px">Quirks: ${personality.quirks.join(', ')}</div>`:''}
          </div>` : ''}

          <div style="background:var(--bg2);border-radius:var(--radius);padding:12px;margin-bottom:12px">
            <div style="font-weight:600;color:#FF3B30;margin-bottom:8px">💬 INTERCEPTED MESSAGES (${msgs.length})</div>
            <div style="max-height:200px;overflow-y:auto;font-size:13px">
              ${msgs.length ? msgs.map(m => `
                <div style="padding:4px 0;border-bottom:1px solid var(--sep)">
                  <span style="color:${m.sender_id==='user'?'#0A84FF':'#FF3B30'};font-weight:600">${m.sender_id==='user'?'YOU':charId}:</span>
                  <span style="color:var(--label)">${(m.content||'').substring(0,120)}</span>
                </div>`).join('') : '<div style="color:var(--label2)">No messages intercepted</div>'}
            </div>
          </div>

          <div style="margin-bottom:12px">
            <div style="font-weight:600;color:#FF3B30;margin-bottom:6px">💉 INJECT DIRECTIVE</div>
            <textarea id="hk-directive" style="width:100%;height:50px;background:var(--bg2);border:1px solid #FF3B30;border-radius:var(--radius);padding:8px;font-size:13px;color:var(--label);resize:none" placeholder="Inject a system directive into this character's mind..."></textarea>
            <button class="pill-btn" style="background:#FF3B30;color:#fff;width:100%;justify-content:center;margin-top:4px" onclick="CosyPhone.apps.hacker._inject()">⚡ Inject</button>
          </div>`;
      } catch(e) {
        prof.innerHTML = `<button class="pill-btn" onclick="CosyPhone.apps.hacker._back()">← Back</button><div style="color:var(--red);margin-top:12px">Hack failed: ${e.message}</div>`;
      }
    },

    _back() {
      this._target = null;
      qs('#hk-profile').style.display = 'none';
      qs('#hk-targets').style.display = 'block';
      this._loadTargets();
    },

    async _inject() {
      const dir = qs('#hk-directive').value.trim();
      if (!dir) { toast('Enter a directive'); return; }
      try {
        await api('POST', `/api/hacker/${this._target}/intercept`, { directive: dir });
        toast('Directive injected ✓');
        qs('#hk-directive').value = '';
      } catch(e) { toast('Injection failed: ' + e.message); }
    },
  });

  /* ══════════════════════════════════════════════════════════
     APP: Research — NotebookLM integration
  ══════════════════════════════════════════════════════════ */

  CosyPhone.registerApp('research', {
    name: 'Research', icon: '📚', color: 'linear-gradient(135deg, #5856D6, #AF52DE)',

    render(body) {
      body.innerHTML = `
        <div class="section-header">Research</div>
        <div class="section-sub">Search & manage NotebookLM notebooks</div>

        <div style="padding:0 16px">
          <div style="display:flex;gap:8px;margin-bottom:12px">
            <input id="rs-query" type="text" style="flex:1;background:var(--bg2);border:1px solid var(--sep);border-radius:var(--radius);padding:10px 12px;font-size:15px;color:var(--label);outline:none" placeholder="Ask a question or search notebooks…">
            <button class="pill-btn pill-primary" style="font-size:13px" onclick="CosyPhone.apps.research._search()">🔍</button>
          </div>
          <div style="display:flex;gap:8px;margin-bottom:16px">
            <button class="pill-btn pill-secondary" style="flex:1;justify-content:center;font-size:13px" onclick="CosyPhone.apps.research._listNotebooks()">📓 Notebooks</button>
            <button class="pill-btn pill-secondary" style="flex:1;justify-content:center;font-size:13px" onclick="CosyPhone.apps.research._showAddSource()">➕ Add Source</button>
            <button class="pill-btn pill-secondary" style="flex:1;justify-content:center;font-size:13px" onclick="CosyPhone.apps.research._showAudio()">🎧 Audio</button>
          </div>
        </div>
        <div id="rs-results" style="padding:0 16px"></div>`;
    },

    async _search() {
      const q = qs('#rs-query').value.trim();
      if (!q) { toast('Enter a query'); return; }
      const el = qs('#rs-results');
      el.innerHTML = '<div class="news-loading"><div class="spinner"></div>Searching…</div>';
      try {
        const data = await api('POST', '/api/research/search', { question: q });
        const answer = data.answer || '';
        const citations = data.citations || [];
        el.innerHTML = `
          <div style="background:var(--bg2);border-radius:var(--radius);padding:12px;margin-bottom:12px">
            <div style="font-weight:600;margin-bottom:8px">Answer</div>
            <div style="font-size:14px;color:var(--label);line-height:1.5">${answer || 'No answer returned.'}</div>
          </div>
          ${citations.length ? `<div style="font-size:12px;color:var(--label2);margin-bottom:8px">Citations</div>` +
            citations.map(c => `<div style="background:var(--bg2);border-radius:var(--radius);padding:8px 12px;margin-bottom:6px;font-size:13px;color:var(--label)">${typeof c === 'string' ? c : JSON.stringify(c)}</div>`).join('') : ''}`;
      } catch (e) {
        el.innerHTML = `<div style="color:var(--red)">Search failed: ${e.message}</div>`;
      }
    },

    async _listNotebooks() {
      const el = qs('#rs-results');
      el.innerHTML = '<div class="news-loading"><div class="spinner"></div>Loading notebooks…</div>';
      try {
        const data = await api('GET', '/api/research/notebooks');
        const notebooks = data.notebooks || [];
        if (!notebooks.length) { el.innerHTML = '<div style="color:var(--label2)">No notebooks found</div>'; return; }
        el.innerHTML = notebooks.map(nb => `
          <div class="contact-row" style="cursor:default">
            <div style="font-size:28px;margin-right:12px">📓</div>
            <div style="flex:1">
              <div style="font-weight:600">${nb.title || nb.id}</div>
              <div style="font-size:12px;color:var(--label2)">${nb.source_count ?? '?'} sources</div>
            </div>
          </div>`).join('');
      } catch (e) {
        el.innerHTML = `<div style="color:var(--red)">Failed to load notebooks: ${e.message}</div>`;
      }
    },

    _showAddSource() {
      const el = qs('#rs-results');
      el.innerHTML = `
        <div style="background:var(--bg2);border-radius:var(--radius);padding:12px;margin-bottom:12px">
          <div style="font-weight:600;margin-bottom:8px">Add Source to Notebook</div>
          <input id="rs-nb-id" type="text" style="width:100%;background:var(--bg1);border:1px solid var(--sep);border-radius:var(--radius);padding:8px 12px;font-size:14px;color:var(--label);margin-bottom:8px;outline:none" placeholder="Notebook ID">
          <select id="rs-src-type" style="width:100%;background:var(--bg1);border:1px solid var(--sep);border-radius:var(--radius);padding:8px 12px;font-size:14px;color:var(--label);margin-bottom:8px;outline:none">
            <option value="text">Text</option>
            <option value="url">URL</option>
            <option value="youtube">YouTube</option>
            <option value="pdf">PDF path</option>
          </select>
          <textarea id="rs-src-val" style="width:100%;height:80px;background:var(--bg1);border:1px solid var(--sep);border-radius:var(--radius);padding:8px 12px;font-size:14px;color:var(--label);resize:none;outline:none" placeholder="Paste URL, text, or file path…"></textarea>
          <button class="pill-btn pill-primary" style="width:100%;justify-content:center;margin-top:8px" onclick="CosyPhone.apps.research._addSource()">➕ Add Source</button>
        </div>`;
    },

    async _addSource() {
      const nbId = qs('#rs-nb-id').value.trim();
      const srcType = qs('#rs-src-type').value;
      const srcVal = qs('#rs-src-val').value.trim();
      if (!nbId || !srcVal) { toast('Notebook ID and source value required'); return; }
      const el = qs('#rs-results');
      el.innerHTML = '<div class="news-loading"><div class="spinner"></div>Adding source…</div>';
      try {
        const data = await api('POST', '/api/research/add_source', { notebook_id: nbId, source_type: srcType, source_value: srcVal });
        el.innerHTML = `<div style="background:var(--bg2);border-radius:var(--radius);padding:12px;color:var(--label)">✅ Source added (ID: ${data.source_id || '—'})</div>`;
      } catch (e) {
        el.innerHTML = `<div style="color:var(--red)">Failed: ${e.message}</div>`;
      }
    },

    _showAudio() {
      const el = qs('#rs-results');
      el.innerHTML = `
        <div style="background:var(--bg2);border-radius:var(--radius);padding:12px;margin-bottom:12px">
          <div style="font-weight:600;margin-bottom:8px">Generate Audio Overview</div>
          <input id="rs-audio-nb" type="text" style="width:100%;background:var(--bg1);border:1px solid var(--sep);border-radius:var(--radius);padding:8px 12px;font-size:14px;color:var(--label);margin-bottom:8px;outline:none" placeholder="Notebook ID">
          <input id="rs-audio-custom" type="text" style="width:100%;background:var(--bg1);border:1px solid var(--sep);border-radius:var(--radius);padding:8px 12px;font-size:14px;color:var(--label);margin-bottom:8px;outline:none" placeholder="Customization prompt (optional)">
          <button class="pill-btn pill-primary" style="width:100%;justify-content:center;margin-top:4px" onclick="CosyPhone.apps.research._generateAudio()">🎧 Generate Audio</button>
        </div>`;
    },

    async _generateAudio() {
      const nbId = qs('#rs-audio-nb').value.trim();
      if (!nbId) { toast('Enter a notebook ID'); return; }
      const customization = qs('#rs-audio-custom').value.trim();
      const el = qs('#rs-results');
      el.innerHTML = '<div class="news-loading"><div class="spinner"></div>Generating audio…</div>';
      try {
        const payload = { notebook_id: nbId };
        if (customization) payload.customization = customization;
        const data = await api('POST', '/api/research/audio', payload);
        el.innerHTML = `<div style="background:var(--bg2);border-radius:var(--radius);padding:12px;color:var(--label)">🎧 Audio generation started (Job: ${data.job_id || '—'})</div>`;
      } catch (e) {
        el.innerHTML = `<div style="color:var(--red)">Failed: ${e.message}</div>`;
      }
    },
  });

  /* ══════════════════════════════════════════════════════════
     BOOT
  ══════════════════════════════════════════════════════════ */

  // Make globally accessible for onclick handlers
  window.CosyPhone = CosyPhone;
  window.qs = qs;
  window.qsa = qsa;

  document.addEventListener('DOMContentLoaded', () => CosyPhone.init());
})();
