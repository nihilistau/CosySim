/**
 * CosySim Phone v2 — iOS-style messenger
 * ========================================
 * State-driven single-page app with Socket.IO real-time updates.
 *
 * State:
 *   Phone.state = {
 *     tab,            // 'messages' | 'contacts' | 'games' | 'settings'
 *     threads,        // cached list
 *     contacts,       // cached list
 *     activeThread,   // { id, name, char_id, type }
 *     gameSession,    // { session_id, round, thread_id } | null
 *   }
 */

(function () {
  'use strict';

  /* ── Utils ──────────────────────────────────────────────── */

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function el(tag, props, ...children) {
    const e = document.createElement(tag);
    if (props) Object.assign(e, props);
    children.forEach(c => {
      if (c == null) return;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return e;
  }

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso + 'Z');
    if (isNaN(d)) return '';
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const diffDays = Math.floor((now - d) / 86400000);
    if (diffDays < 7) return d.toLocaleDateString([], { weekday: 'short' });
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
    const parts = name.trim().split(' ');
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : name[0].toUpperCase();
  }

  function avatarEl(name, url, size) {
    const wrap = el('div');
    wrap.className = 'thread-avatar';
    if (size) { wrap.style.width = size + 'px'; wrap.style.height = size + 'px'; wrap.style.fontSize = Math.round(size * 0.38) + 'px'; }
    if (url) {
      const img = el('img', { src: url, alt: name });
      img.onerror = () => { wrap.textContent = initials(name); };
      wrap.appendChild(img);
    } else {
      wrap.textContent = initials(name);
    }
    return wrap;
  }

  /* ── Simple API wrapper ─────────────────────────────────── */

  async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({ ok: false, error: 'JSON parse error' }));
    if (!j.ok) throw new Error(j.error || 'API error');
    return j;
  }

  /* ══════════════════════════════════════════════════════════
     Phone namespace
  ══════════════════════════════════════════════════════════ */

  const Phone = {
    state: {
      tab:           'messages',
      threads:       [],
      contacts:      [],
      activeThread:  null,
      gameSession:   null,
    },

    socket: null,
    _typingTimers: {},

    /* ── Boot ──────────────────────────────────────────────── */

    init() {
      this._initSocket();
      this._initStatusBar();
      this._initInputBar();
      this._initChatBack();
      this._initComposeBtn();
      this._initTodCard();
      this.loadThreads();
    },

    /* ── Socket.IO ─────────────────────────────────────────── */

    _initSocket() {
      this.socket = io({ transports: ['websocket', 'polling'] });

      this.socket.on('message_new', (data) => {
        const { thread_id, message } = data;
        // Update thread list preview
        this._bumpThread(thread_id, message);
        // If this thread is open, append message
        if (this.state.activeThread && this.state.activeThread.id === thread_id) {
          this._appendMessage(message);
          this._scrollBottom(true);
        } else {
          // Flash unread badge
          this._incUnread(thread_id);
        }
        this._refreshTotalBadge();
      });

      this.socket.on('typing', (data) => {
        const { thread_id, char_id, active } = data;
        if (!this.state.activeThread || this.state.activeThread.id !== thread_id) return;
        const tid = `typing_${char_id}`;
        if (active) {
          if (!qs(`#${tid}`)) {
            const row = this._makeTypingRow(char_id);
            row.id = tid;
            qs('#chat-messages').appendChild(row);
            this._scrollBottom(true);
          }
          clearTimeout(this._typingTimers[char_id]);
          this._typingTimers[char_id] = setTimeout(() => {
            const el2 = qs(`#${tid}`);
            if (el2) el2.remove();
          }, 5000);
        } else {
          const el2 = qs(`#${tid}`);
          if (el2) el2.remove();
        }
      });

      this.socket.on('thread_updated', () => { this.loadThreads(); });

      this.socket.on('game_event', (data) => {
        const { thread_id, event: ev, challenge, choice, round, session_id } = data;
        if (ev === 'game_started') {
          this.state.gameSession = { session_id, round: 0, thread_id };
          toast('🎮 Game started!');
        }
        if (ev === 'challenge' && qs('#active-game').classList.contains('open')) {
          this._showChallenge(choice, challenge, round);
        }
        if (ev === 'game_ended') {
          this.state.gameSession = null;
          qs('#active-game').classList.remove('open');
          toast('Game ended 🏁');
        }
      });

      this.socket.on('admin_wipe', () => {
        this.state.threads = [];
        this.state.activeThread = null;
        qs('#thread-list').innerHTML = '';
        qs('#chat-messages').innerHTML = '';
        qs('#chat-screen').classList.remove('open');
        toast('All messages wiped');
      });
    },

    /* ── Status bar clock ──────────────────────────────────── */

    _initStatusBar() {
      const el2 = qs('#status-time');
      const tick = () => {
        const now = new Date();
        el2.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      };
      tick();
      const ms = (60 - new Date().getSeconds()) * 1000;
      setTimeout(() => { tick(); setInterval(tick, 60000); }, ms);
    },

    /* ── Tab switching ─────────────────────────────────────── */

    switchTab(tab) {
      this.state.tab = tab;
      qsa('.tab-item').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
      qsa('.view').forEach(v => v.classList.toggle('active', v.id === `view-${tab}`));
      qs('#nav-title').textContent = {
        messages: 'Messages', contacts: 'People', games: 'Games', settings: 'Settings',
      }[tab] || tab;
      qs('#btn-compose').style.display = tab === 'messages' ? '' : 'none';

      if (tab === 'contacts' && this.state.contacts.length === 0) this.loadContacts();
      if (tab === 'messages' && this.state.threads.length === 0) this.loadThreads();
    },

    /* ── Threads list ──────────────────────────────────────── */

    async loadThreads() {
      try {
        const data = await api('GET', '/api/threads');
        this.state.threads = data.threads || [];
        this._renderThreadList();
        this._refreshTotalBadge();
      } catch (e) {
        console.error('loadThreads', e);
      }
    },

    _renderThreadList() {
      const list = qs('#thread-list');
      list.innerHTML = '';
      const threads = this.state.threads;
      if (!threads.length) {
        list.append(this._emptyState('💬', 'No conversations yet', 'Tap + to start messaging'));
        return;
      }
      threads.forEach(t => {
        const item = el('div', { className: 'thread-item' });
        item.onclick = () => this.openThread(t);

        const av = avatarEl(t.name || t.char_name || '?', t.avatar || t.char_avatar || '', 52);
        av.className = 'thread-avatar';

        const info = el('div', { className: 'thread-info' });
        info.appendChild(el('div', { className: 'thread-name', textContent: t.name || t.char_name || 'Chat' }));
        const preview = el('div', { className: 'thread-preview', textContent: t.last_message || '\u00a0' });
        info.appendChild(preview);

        const meta = el('div', { className: 'thread-meta' });
        meta.appendChild(el('div', { className: 'thread-time', textContent: fmtTime(t.updated_at) }));
        if (t.unread > 0) {
          const dot = el('div', { className: 'unread-dot', textContent: t.unread > 99 ? '99+' : t.unread });
          meta.appendChild(dot);
        }
        item.append(av, info, meta);
        list.appendChild(item);
      });
    },

    _bumpThread(thread_id, msg) {
      const idx = this.state.threads.findIndex(t => t.id === thread_id);
      if (idx !== -1) {
        this.state.threads[idx].last_message = msg.content || '[media]';
        this.state.threads[idx].updated_at   = msg.created_at;
        this._renderThreadList();
      } else {
        this.loadThreads();
      }
    },

    _incUnread(thread_id) {
      const t = this.state.threads.find(t => t.id === thread_id);
      if (t) { t.unread = (t.unread || 0) + 1; this._renderThreadList(); }
    },

    _refreshTotalBadge() {
      const total = this.state.threads.reduce((s, t) => s + (t.unread || 0), 0);
      const badge = qs('#badge-messages');
      if (total > 0) { badge.textContent = total > 99 ? '99+' : total; badge.style.display = ''; }
      else           { badge.style.display = 'none'; }
    },

    /* ── Open DM from contacts tab ─────────────────────────── */

    async openDM(char_id, char_name) {
      try {
        const data = await api('POST', '/api/threads/dm', { character_id: char_id });
        const thread = {
          id:       data.thread_id,
          type:     'dm',
          name:     char_name,
          char_id:  char_id,
        };
        this.switchTab('messages');
        this.openThread(thread);
      } catch (e) {
        toast('Could not open conversation');
      }
    },

    /* ── Chat view ─────────────────────────────────────────── */

    async openThread(thread) {
      this.state.activeThread = thread;
      // Nav
      qs('#chat-back-label').textContent = 'Back';
      qs('#chat-title').textContent = thread.name || 'Chat';
      // Small avatar
      const avSmall = qs('#chat-avatar-small');
      avSmall.innerHTML = '';
      const contact = this.state.contacts.find(c => c.id === thread.char_id);
      avSmall.append(avatarEl(thread.name || '?', (contact || {}).avatar || '', 32));
      avSmall.className = 'msg-avatar';

      // Game button for DMs
      const gameBtn = qs('#btn-game-invite');
      gameBtn.style.display = thread.type === 'dm' ? '' : 'none';
      gameBtn.onclick = () => this.openGameForThread(thread);

      qs('#chat-screen').classList.add('open');
      qs('#chat-messages').innerHTML = '';

      if (this.socket) this.socket.emit('join_thread', { thread_id: thread.id });

      try {
        const data = await api('GET', `/api/thread/${thread.id}/messages?limit=60`);
        const msgs = data.messages || [];
        msgs.forEach(m => this._appendMessage(m, true));
        this._scrollBottom(false);
      } catch (e) {
        toast('Failed to load messages');
      }
    },

    _initChatBack() {
      qs('#chat-back').onclick = () => {
        qs('#chat-screen').classList.remove('open');
        this.state.activeThread = null;
        this.loadThreads();
      };
    },

    /* ── Message rendering ──────────────────────────────────── */

    _appendMessage(msg, batch) {
      const box  = qs('#chat-messages');
      const isOut  = msg.sender_id === 'user';
      const isSys  = msg.sender_id === 'system' || msg.msg_type === 'system';
      const isGame = msg.msg_type === 'game';
      const contact = this.state.contacts.find(c => c.id === msg.sender_id) || {};

      const row = el('div');
      row.className = 'msg-row ' + (isSys || isGame ? (isGame ? 'game' : 'sys') : (isOut ? 'out' : 'in'));

      if (!isOut && !isSys) {
        const av = el('div', { className: 'msg-avatar' });
        if (contact.avatar) {
          const img = el('img', { src: contact.avatar, alt: contact.name });
          img.onerror = () => { av.textContent = initials(contact.name || '?'); };
          av.appendChild(img);
        } else {
          av.textContent = initials(contact.name || '?');
        }
        row.appendChild(av);
      }

      const bubble = el('div', { className: 'bubble' });

      if (msg.msg_type === 'voice' && msg.media_path) {
        bubble.classList.add('voice-bubble');
        bubble.innerHTML = `
          <button class="voice-btn" onclick="this.parentNode.querySelector('audio').play()">▶</button>
          <div class="voice-waveform"></div>
          <span class="voice-duration"></span>
          <audio src="/media/voice/${this._basename(msg.media_path)}" style="display:none"></audio>
        `;
      } else if (msg.msg_type === 'photo' && msg.media_path) {
        bubble.classList.add('media-bubble');
        const img = el('img', { src: `/media/photo/${this._basename(msg.media_path)}`, alt: 'photo' });
        bubble.appendChild(img);
      } else if (msg.msg_type === 'video' && msg.media_path) {
        bubble.classList.add('media-bubble');
        const vid = el('video', { controls: true });
        vid.src = `/media/video/${this._basename(msg.media_path)}`;
        bubble.appendChild(vid);
      } else {
        bubble.textContent = msg.content || '';
        const t = el('span', { className: 'bubble-time', textContent: fmtTime(msg.created_at) });
        bubble.appendChild(t);
      }

      row.appendChild(bubble);
      box.appendChild(row);
      if (!batch) this._scrollBottom(true);
    },

    _basename(p) { return p ? p.split('/').pop().split('\\').pop() : ''; },

    _makeTypingRow(char_id) {
      const contact = this.state.contacts.find(c => c.id === char_id) || {};
      const row = el('div', { className: 'msg-row in' });
      const av  = el('div', { className: 'msg-avatar', textContent: initials(contact.name || '?') });
      const bub = el('div', { className: 'bubble typing-indicator' });
      bub.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
      row.append(av, bub);
      return row;
    },

    _scrollBottom(smooth) {
      const box = qs('#chat-messages');
      requestAnimationFrame(() => {
        box.scrollTo({ top: box.scrollHeight, behavior: smooth ? 'smooth' : 'instant' });
      });
    },

    /* ── Input bar ──────────────────────────────────────────── */

    _initInputBar() {
      const inp   = qs('#chat-text-input');
      const send  = qs('#chat-send');
      const attach = qs('#btn-attach');
      const popup  = qs('#attach-popup');

      inp.addEventListener('input', () => {
        send.disabled = !inp.value.trim();
        inp.style.height = 'auto';
        inp.style.height = Math.min(inp.scrollHeight, 120) + 'px';
        // Emit typing to server
        if (this.state.activeThread) {
          this.socket.emit('typing', { thread_id: this.state.activeThread.id, active: true });
        }
      });

      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!send.disabled) this.sendMessage(); }
      });

      send.onclick = () => this.sendMessage();

      attach.onclick = (e) => {
        e.stopPropagation();
        popup.classList.toggle('open');
      };
      document.addEventListener('click', () => popup.classList.remove('open'));
      popup.addEventListener('click', e => e.stopPropagation());
    },

    async sendMessage() {
      const inp = qs('#chat-text-input');
      const text = inp.value.trim();
      if (!text || !this.state.activeThread) return;
      inp.value = '';
      inp.style.height = '';
      qs('#chat-send').disabled = true;

      try {
        await api('POST', `/api/thread/${this.state.activeThread.id}/send`, { content: text, type: 'text' });
      } catch (e) {
        toast('Failed to send');
      }
    },

    attachPhoto() {
      const inp = el('input', { type: 'file', accept: 'image/*', style: 'display:none' });
      inp.onchange = async () => {
        if (!inp.files[0] || !this.state.activeThread) return;
        toast('Photo sharing coming soon');
      };
      inp.click();
    },

    attachVoice() {
      toast('Voice messages coming soon');
    },

    /* ── Contacts ───────────────────────────────────────────── */

    async loadContacts() {
      try {
        const data = await api('GET', '/api/contacts');
        this.state.contacts = data.contacts || [];
        this._renderContacts();
      } catch (e) {
        console.error('loadContacts', e);
      }
    },

    _renderContacts() {
      const list = qs('#contacts-list');
      list.innerHTML = '';
      if (!this.state.contacts.length) {
        list.append(this._emptyState('👥', 'No contacts', 'Characters will appear here'));
        return;
      }
      this.state.contacts.forEach(c => {
        const card = el('div', { className: 'contact-card' });

        const avWrap = el('div', { className: 'contact-avatar', style: 'position:relative' });
        if (c.avatar) {
          const img = el('img', { src: c.avatar, alt: c.name });
          img.onerror = () => { avWrap.textContent = initials(c.name); };
          avWrap.appendChild(img);
        } else {
          avWrap.textContent = initials(c.name);
        }
        const dot = el('div', { className: `status-dot ${c.status === 'online' ? 'online' : 'offline'}` });
        avWrap.appendChild(dot);

        const info = el('div', { className: 'contact-info' });
        info.appendChild(el('div', { className: 'contact-name', textContent: c.name }));
        if (c.mood) info.appendChild(el('div', { className: 'contact-mood', textContent: c.mood }));

        const actions = el('div', { className: 'contact-actions' });
        const msgBtn = el('button', { className: 'contact-btn', title: 'Message', textContent: '💬' });
        msgBtn.onclick = (e) => { e.stopPropagation(); this.openDM(c.id, c.name); };
        actions.appendChild(msgBtn);

        card.append(avWrap, info, actions);
        card.onclick = () => this.openDM(c.id, c.name);
        list.appendChild(card);
      });
    },

    /* ── Compose button (in messages tab) ───────────────────── */

    _initComposeBtn() {
      qs('#btn-compose').onclick    = () => this._showContactPicker();
      qs('#fab-new-chat').onclick   = () => this._showContactPicker();
    },

    _showContactPicker() {
      // Load contacts and show them as a chooser
      const pick = async () => {
        if (!this.state.contacts.length) await this.loadContacts();
        if (!this.state.contacts.length) { toast('No contacts available'); return; }
        const names = this.state.contacts.map(c => c.name).join(', ');
        const name  = prompt(`Start a DM with:\n${names}\n\nType a name:`);
        if (!name) return;
        const c = this.state.contacts.find(c => c.name.toLowerCase() === name.toLowerCase().trim());
        if (!c) { toast('Contact not found'); return; }
        this.openDM(c.id, c.name);
      };
      pick();
    },

    /* ── Games ──────────────────────────────────────────────── */

    _initTodCard() {
      qs('#tod-card').onclick = () => {
        if (!this.state.contacts.length) this.loadContacts().then(() => this._showGamePicker());
        else this._showGamePicker();
      };
    },

    _showGamePicker() {
      if (!this.state.contacts.length) { toast('No contacts to play with'); return; }
      const names = this.state.contacts.map(c => c.name).join(', ');
      const name  = prompt(`Play Truth or Dare with:\n${names}\n\nType a name:`);
      if (!name) return;
      const c = this.state.contacts.find(c => c.name.toLowerCase() === name.toLowerCase().trim());
      if (!c) { toast('Contact not found'); return; }
      this._startGameWithContact(c);
    },

    async _startGameWithContact(contact) {
      try {
        const dmData = await api('POST', '/api/threads/dm', { character_id: contact.id });
        const thread_id = dmData.thread_id;
        const res = await api('POST', '/api/games/start', { thread_id, character_id: contact.id });
        this.state.gameSession = { session_id: res.session_id, round: 0, thread_id };
        // Show active game UI
        qs('#game-round-label').textContent = 'Round 1';
        qs('#game-challenge-box').textContent = 'Choose Truth or Dare to begin!';
        qs('#game-challenge-box').className = 'game-challenge-box';
        qs('#active-game').classList.add('open');
        toast(`🎮 Game started with ${contact.name}!`);
      } catch (e) {
        toast('Failed to start game');
      }
    },

    openGameForThread(thread) {
      if (this.state.gameSession && this.state.gameSession.thread_id === thread.id) {
        qs('#active-game').classList.add('open');
        return;
      }
      const c = this.state.contacts.find(c => c.id === thread.char_id);
      if (c) this._startGameWithContact(c);
    },

    async gameChoose(choice) {
      const gs = this.state.gameSession;
      if (!gs) { toast('No active game'); return; }
      try {
        const res = await api('POST', '/api/games/action', { thread_id: gs.thread_id, choice });
        this._showChallenge(choice, res.challenge, res.round);
      } catch (e) {
        toast('Could not get challenge');
      }
    },

    _showChallenge(choice, challenge, round) {
      const box = qs('#game-challenge-box');
      box.textContent = challenge;
      box.className   = 'game-challenge-box ' + choice;
      qs('#game-round-label').textContent = `Round ${round}`;
    },

    async endGame() {
      const gs = this.state.gameSession;
      if (!gs) { qs('#active-game').classList.remove('open'); return; }
      try {
        await api('POST', '/api/games/end', { thread_id: gs.thread_id });
      } catch (_) {}
      this.state.gameSession = null;
      qs('#active-game').classList.remove('open');
    },

    /* ── Settings ───────────────────────────────────────────── */

    goAdmin() { window.location.href = 'http://localhost:5001'; },

    async confirmWipe() {
      if (!confirm('Delete all messages and media? This cannot be undone.')) return;
      try {
        const res = await api('POST', '/api/admin/wipe-messages');
        toast(`Wiped ${res.messages_deleted} messages and ${res.media_deleted} media files`);
      } catch (e) {
        toast('Wipe failed');
      }
    },

    /* ── Empty state helper ─────────────────────────────────── */

    _emptyState(icon, title, desc) {
      const wrap = el('div', { className: 'empty-state' });
      wrap.append(
        el('div', { className: 'icon', textContent: icon }),
        el('h3',  { textContent: title }),
        el('p',   { textContent: desc }),
      );
      return wrap;
    },
  };

  /* ── Boot ────────────────────────────────────────────────── */

  window.Phone = Phone;
  document.addEventListener('DOMContentLoaded', () => Phone.init());
})();
