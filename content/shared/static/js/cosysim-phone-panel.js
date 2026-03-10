/**
 * cosysim-phone-panel.js — NeonPhone Cyberpunk Slide-Out Panel
 *
 * A full phone OS experience accessible from any scene:
 *   Lock screen → Home screen → Apps (Messages, Contacts, News, Wallet, Gallery, Settings)
 *
 * Connects to the SIGNAL phone scene at localhost:5555 for data.
 * Uses Socket.IO for real-time notifications when available.
 */

(function () {
  'use strict';

  const PHONE_PORT = 5555;
  const PHONE_BASE = `http://localhost:${PHONE_PORT}`;

  const APPS = [
    { id: 'messages', name: 'SIGNAL',   icon: '💬', bg: 'rgba(0,255,160,0.12)',  glow: 'rgba(0,255,160,0.3)' },
    { id: 'contacts', name: 'CONTACTS', icon: '👤', bg: 'rgba(6,182,212,0.12)',  glow: 'rgba(6,182,212,0.3)' },
    { id: 'news',     name: 'NEWS',     icon: '📡', bg: 'rgba(249,115,22,0.12)', glow: 'rgba(249,115,22,0.3)' },
    { id: 'wallet',   name: 'WALLET',   icon: '💰', bg: 'rgba(234,179,8,0.12)',  glow: 'rgba(234,179,8,0.3)' },
    { id: 'gallery',  name: 'GALLERY',  icon: '🖼️', bg: 'rgba(168,85,247,0.12)', glow: 'rgba(168,85,247,0.3)' },
    { id: 'hacker',   name: 'HACKER',   icon: '💀', bg: 'rgba(239,68,68,0.12)',  glow: 'rgba(239,68,68,0.3)' },
    { id: 'ghost',    name: 'GHOST',    icon: '👾', bg: 'rgba(0,255,160,0.08)',  glow: 'rgba(0,255,160,0.3)' },
    { id: 'settings', name: 'CONFIG',   icon: '⚙️', bg: 'rgba(100,116,139,0.12)',glow: 'rgba(100,116,139,0.3)' },
    { id: 'expand',   name: 'EXPAND',   icon: '🔗', bg: 'rgba(139,92,246,0.12)', glow: 'rgba(139,92,246,0.3)' },
  ];

  const DOCK_APPS = ['messages', 'contacts', 'news', 'wallet'];

  // ── Helpers ──────────────────────────────────────────────────────────

  function _esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
  }

  function _timeStr() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  }

  function _dateStr() {
    const now = new Date();
    return now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
  }

  function _relativeTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
  }

  async function _api(path, opts = {}) {
    try {
      const resp = await fetch(`${PHONE_BASE}${path}`, {
        ...opts,
        signal: AbortSignal.timeout(opts.timeout || 4000),
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      });
      if (!resp.ok) return null;
      return await resp.json();
    } catch {
      return null;
    }
  }

  // ── NeonPhone Class ──────────────────────────────────────────────────

  class NeonPhone {
    constructor() {
      this._panel = null;
      this._overlay = null;
      this._open = false;
      this._unlocked = false;
      this._currentApp = null;
      this._currentThread = null;
      this._online = false;
      this._threads = [];
      this._contacts = [];
      this._unreadCount = 0;
      this._notifications = [];
      this._socket = null;
      this._clockInterval = null;
      this._retryInterval = null;
      this._autotxtMuted = false;
    }

    // ── Initialization ───────────────────────────────────────────────

    init() {
      this._injectDOM();
      this._bindNavbar();
      this._bindKeyboard();
      this._checkOnline();
      this._startClock();
    }

    _injectDOM() {
      // Panel
      const panel = document.createElement('div');
      panel.className = 'cs-phone-panel';
      panel.id = 'cs-phone-panel';
      panel.innerHTML = `
        <!-- Status Bar -->
        <div class="cs-phone-statusbar">
          <div class="cs-phone-statusbar-left">
            <div class="cs-phone-signal-dot" id="cs-phone-dot"></div>
            <span id="cs-phone-carrier">SIGNAL</span>
          </div>
          <div class="cs-phone-statusbar-right">
            <span id="cs-phone-clock">${_timeStr()}</span>
            <span>📶</span>
            <span>🔋</span>
            <button class="cs-app-back" onclick="window.PhonePanel.close()"
                    style="color:rgba(255,255,255,0.4);font-size:16px;padding:0 2px">✕</button>
          </div>
        </div>

        <!-- Lock Screen -->
        <div class="cs-phone-lock" id="cs-phone-lock">
          <div class="cs-phone-lock-bg"></div>
          <div class="cs-phone-lock-grid"></div>
          <div class="cs-phone-lock-time" id="cs-lock-time">${_timeStr()}</div>
          <div class="cs-phone-lock-date" id="cs-lock-date">${_dateStr()}</div>
          <div class="cs-phone-lock-notif" id="cs-lock-notifs"></div>
          <div class="cs-phone-lock-hint">TAP TO DECRYPT</div>
        </div>

        <!-- Offline Banner (hidden by default) -->
        <div class="cs-phone-offline-banner" id="cs-phone-offline" style="display:none">
          <span>⚠</span> SIGNAL OFFLINE — start phone scene at :5555
        </div>

        <!-- Home Screen -->
        <div class="cs-phone-home" id="cs-phone-home">
          <div class="cs-phone-greeting">
            Welcome, <strong>Runner</strong>
          </div>
          <div class="cs-phone-greeting-sub" id="cs-phone-status-line">
            System nominal
          </div>
          <div class="cs-app-grid" id="cs-app-grid"></div>
        </div>

        <!-- Dock -->
        <div class="cs-phone-dock" id="cs-phone-dock"></div>

        <!-- App View (slides over home) -->
        <div class="cs-phone-appview" id="cs-phone-appview">
          <div class="cs-app-header" id="cs-app-header">
            <button class="cs-app-back" id="cs-app-back"
                    onclick="window.PhonePanel.closeApp()">
              <span class="cs-app-back-arrow">‹</span> Home
            </button>
            <div class="cs-app-title" id="cs-app-title">APP</div>
            <div class="cs-app-header-right" id="cs-app-header-right"></div>
          </div>
          <div class="cs-app-body" id="cs-app-body"></div>
        </div>

        <!-- Toast -->
        <div class="cs-phone-toast" id="cs-phone-toast">
          <div class="cs-phone-toast-icon" id="cs-toast-icon">💬</div>
          <div class="cs-phone-toast-body">
            <div class="cs-phone-toast-title" id="cs-toast-title"></div>
            <div class="cs-phone-toast-text" id="cs-toast-text"></div>
          </div>
        </div>
      `;
      document.body.appendChild(panel);

      // Overlay
      const overlay = document.createElement('div');
      overlay.className = 'cs-phone-overlay';
      overlay.id = 'cs-phone-overlay';
      overlay.onclick = () => this.close();
      document.body.appendChild(overlay);

      this._panel = panel;
      this._overlay = overlay;

      // Wire lock screen
      const lock = document.getElementById('cs-phone-lock');
      if (lock) lock.addEventListener('click', () => this._unlock());

      // Render app grid and dock
      this._renderAppGrid();
      this._renderDock();
    }

    _bindNavbar() {
      document.addEventListener('navbar:panel_request', (e) => {
        if (e.detail && e.detail.panel === 'phone') this.toggle();
      });
      const bind = () => {
        const btn = document.querySelector('[data-action="phone"], #cs-phone-btn, .cs-nav-phone');
        if (btn && !btn._neonPhoneBound) {
          btn._neonPhoneBound = true;
          btn.addEventListener('click', (e) => { e.preventDefault(); this.toggle(); });
        }
      };
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
      } else {
        bind();
      }
    }

    _bindKeyboard() {
      document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' ||
            e.target.isContentEditable) return;
        if (e.key === 'p' || e.key === 'P') {
          e.preventDefault();
          this.toggle();
        }
        if (e.key === 'Escape' && this._open) {
          e.preventDefault();
          if (this._currentApp) this.closeApp();
          else this.close();
        }
      });
    }

    // ── Online / Socket ──────────────────────────────────────────────

    async _checkOnline() {
      const data = await _api('/api/contacts');
      this._online = !!data;
      this._updateOnlineUI();

      if (this._online) {
        this._contacts = data.contacts || data || [];
        this._connectSocket();
        this._loadThreads();
      }

      // Retry every 15s if offline
      if (!this._online && !this._retryInterval) {
        this._retryInterval = setInterval(() => this._checkOnline(), 15000);
      } else if (this._online && this._retryInterval) {
        clearInterval(this._retryInterval);
        this._retryInterval = null;
      }
    }

    _updateOnlineUI() {
      const dot = document.getElementById('cs-phone-dot');
      const offline = document.getElementById('cs-phone-offline');
      const status = document.getElementById('cs-phone-status-line');

      if (dot) {
        dot.classList.toggle('offline', !this._online);
      }
      if (offline) {
        offline.style.display = this._online ? 'none' : 'flex';
      }
      if (status) {
        status.textContent = this._online
          ? `${this._contacts.length} contacts • SIGNAL active`
          : 'SIGNAL offline — limited functionality';
      }
    }

    _connectSocket() {
      if (this._socket || typeof io === 'undefined') return;
      try {
        this._socket = io(PHONE_BASE, { transports: ['websocket', 'polling'], reconnection: true });
        this._socket.on('new_message', (d) => {
          this._showToast('💬', d.from || 'New message', (d.text || d.content || '').slice(0, 60));
          this._unreadCount++;
          this._updateBadge();
          if (this._currentApp === 'messages' && !this._currentThread) this._loadThreads();
        });
        this._socket.on('world_alert', (d) => {
          this._showToast('🌐', 'WORLD EVENT', d.title || 'Major event detected');
          this._addNotification('🌐', d.title || 'World Event', d.text || '');
        });
        this._socket.on('incoming_message', (d) => {
          this._showToast(d.type === 'ghost' ? '👾' : '📡', d.from || 'INCOMING', (d.text || '').slice(0, 60));
          this._addNotification(d.type === 'ghost' ? '👾' : '📡', d.from || 'INCOMING', d.text || '');
        });
      } catch { /* Socket.IO may not be available cross-origin */ }
    }

    // ── Clock ────────────────────────────────────────────────────────

    _startClock() {
      const update = () => {
        const time = _timeStr();
        const clock = document.getElementById('cs-phone-clock');
        const lockTime = document.getElementById('cs-lock-time');
        const lockDate = document.getElementById('cs-lock-date');
        if (clock) clock.textContent = time;
        if (lockTime) lockTime.textContent = time;
        if (lockDate) lockDate.textContent = _dateStr();
      };
      this._clockInterval = setInterval(update, 30000);
    }

    // ── Lock Screen ──────────────────────────────────────────────────

    _unlock() {
      this._unlocked = true;
      const lock = document.getElementById('cs-phone-lock');
      if (lock) lock.classList.add('unlocked');
    }

    _showLock() {
      const lock = document.getElementById('cs-phone-lock');
      if (lock) lock.classList.remove('unlocked');
      this._unlocked = false;
    }

    // ── App Grid & Dock ──────────────────────────────────────────────

    _renderAppGrid() {
      const grid = document.getElementById('cs-app-grid');
      if (!grid) return;
      grid.innerHTML = APPS.map(app => `
        <div class="cs-app-icon" onclick="window.PhonePanel.openApp('${app.id}')">
          <div class="cs-app-icon-circle"
               style="background:${app.bg};--app-glow:${app.glow}"
               id="cs-app-circle-${app.id}">
            ${app.icon}
            <div class="cs-app-badge" id="cs-badge-${app.id}" style="display:none"></div>
          </div>
          <div class="cs-app-icon-label">${app.name}</div>
        </div>
      `).join('');
    }

    _renderDock() {
      const dock = document.getElementById('cs-phone-dock');
      if (!dock) return;
      dock.innerHTML = DOCK_APPS.map(id => {
        const app = APPS.find(a => a.id === id);
        if (!app) return '';
        return `
          <div class="cs-dock-btn" onclick="window.PhonePanel.openApp('${app.id}')"
               style="--app-glow:${app.glow}" title="${app.name}">
            ${app.icon}
            <div class="cs-app-badge" id="cs-dock-badge-${app.id}" style="display:none"></div>
          </div>
        `;
      }).join('');
    }

    // ── App Navigation ───────────────────────────────────────────────

    openApp(appId) {
      if (appId === 'expand') {
        window.open(PHONE_BASE, '_blank');
        return;
      }

      this._currentApp = appId;
      this._currentThread = null;
      const appView = document.getElementById('cs-phone-appview');
      const title = document.getElementById('cs-app-title');
      const body = document.getElementById('cs-app-body');
      const headerRight = document.getElementById('cs-app-header-right');
      const backBtn = document.getElementById('cs-app-back');

      if (!appView || !body) return;

      const app = APPS.find(a => a.id === appId);
      if (title) title.textContent = app ? app.name : appId.toUpperCase();
      if (headerRight) headerRight.innerHTML = '';
      if (backBtn) backBtn.onclick = () => this.closeApp();

      body.innerHTML = '<div class="cs-phone-loading"><div class="cs-phone-loading-spinner"></div><span>Loading...</span></div>';
      appView.classList.add('active');

      // Render the app
      switch (appId) {
        case 'messages': this._renderMessages(body); break;
        case 'contacts': this._renderContacts(body); break;
        case 'news':     this._renderNews(body); break;
        case 'wallet':   this._renderWallet(body); break;
        case 'gallery':  this._renderGallery(body); break;
        case 'hacker':   this._renderHacker(body); break;
        case 'ghost':    this._renderGhost(body); break;
        case 'settings': this._renderSettings(body); break;
        default:
          body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">🚧</div><div>Coming soon</div></div>';
      }
    }

    closeApp() {
      if (this._currentThread) {
        // Go back to thread list
        this._currentThread = null;
        const body = document.getElementById('cs-app-body');
        if (body) this._renderMessages(body);
        return;
      }
      this._currentApp = null;
      const appView = document.getElementById('cs-phone-appview');
      if (appView) appView.classList.remove('active');
    }

    // ── Messages App ─────────────────────────────────────────────────

    async _loadThreads() {
      const data = await _api('/api/threads');
      if (data) {
        this._threads = data.threads || data || [];
        // Update unread badge
        let unread = 0;
        this._threads.forEach(t => { unread += (t.unread || 0); });
        this._unreadCount = unread;
        this._updateBadge();
      }
    }

    async _renderMessages(body) {
      await this._loadThreads();

      if (!this._online) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">📵</div><div>SIGNAL offline</div></div>';
        return;
      }

      if (!this._threads.length) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">💬</div><div>No conversations yet</div></div>';
        return;
      }

      body.innerHTML = `<div class="cs-thread-list">${
        this._threads.map(t => {
          const name = _esc(t.display_name || t.name || t.thread_id || 'Unknown');
          const preview = _esc((t.last_message || t.preview || 'Tap to chat').slice(0, 50));
          const avatar = t.emoji || t.avatar || name[0] || '💬';
          const time = _relativeTime(t.updated_at || t.last_activity);
          const badge = t.unread ? `<div class="cs-thread-badge">${t.unread}</div>` : '';
          return `
            <div class="cs-thread-item" onclick="window.PhonePanel._openThread('${_esc(t.thread_id || t.id)}')">
              <div class="cs-thread-avatar">${avatar}</div>
              <div class="cs-thread-info">
                <div class="cs-thread-name">${name}</div>
                <div class="cs-thread-preview">${preview}</div>
              </div>
              <div class="cs-thread-meta">
                <div class="cs-thread-time">${time}</div>
                ${badge}
              </div>
            </div>`;
        }).join('')
      }</div>`;
    }

    async _openThread(threadId) {
      this._currentThread = threadId;
      const body = document.getElementById('cs-app-body');
      const backBtn = document.getElementById('cs-app-back');
      if (!body) return;

      // Update back button to go to thread list
      if (backBtn) backBtn.onclick = () => this.closeApp();

      // Load messages
      const data = await _api(`/api/thread/${threadId}/messages`);
      const msgs = data ? (data.messages || data || []) : [];

      // Find thread info
      const thread = this._threads.find(t => (t.thread_id || t.id) === threadId) || {};
      const name = _esc(thread.display_name || thread.name || threadId);
      const avatar = thread.emoji || thread.avatar || name[0] || '💬';

      const msgsHtml = msgs.length
        ? msgs.map(m => `
            <div class="cs-msg ${m.role === 'user' || m.sender === 'player' ? 'cs-msg-me' : 'cs-msg-them'}">
              ${_esc(m.content || m.text || m.message || '')}
              <div class="cs-msg-time">${_esc(m.timestamp || m.time || '')}</div>
            </div>`).join('')
        : '<div style="text-align:center;color:rgba(255,255,255,0.2);font-size:11px;padding:30px">No messages yet — say hello</div>';

      body.innerHTML = `
        <div style="display:flex;flex-direction:column;height:100%">
          <div class="cs-chat-header">
            <button class="cs-chat-back" onclick="window.PhonePanel.closeApp()">←</button>
            <div class="cs-thread-avatar" style="width:34px;height:34px;font-size:15px">${avatar}</div>
            <div>
              <div class="cs-chat-name">${name}</div>
              <div class="cs-chat-status">online</div>
            </div>
          </div>
          <div class="cs-chat-messages" id="cs-chat-msgs">${msgsHtml}</div>
          <div class="cs-chat-input-row">
            <input class="cs-chat-input" id="cs-chat-input"
                   placeholder="Message ${name}..."
                   onkeydown="if(event.key==='Enter'){event.preventDefault();window.PhonePanel._sendMsg('${_esc(threadId)}')}">
            <button class="cs-chat-send" onclick="window.PhonePanel._sendMsg('${_esc(threadId)}')">↑</button>
          </div>
        </div>`;

      // Scroll to bottom
      const msgsEl = document.getElementById('cs-chat-msgs');
      if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;

      // Focus input
      setTimeout(() => {
        const input = document.getElementById('cs-chat-input');
        if (input) input.focus();
      }, 100);
    }

    async _sendMsg(threadId) {
      const input = document.getElementById('cs-chat-input');
      if (!input || !input.value.trim()) return;
      const text = input.value.trim();
      input.value = '';

      // Optimistic render
      const msgsEl = document.getElementById('cs-chat-msgs');
      if (msgsEl) {
        const div = document.createElement('div');
        div.className = 'cs-msg cs-msg-me';
        div.innerHTML = `${_esc(text)}<div class="cs-msg-time">${_timeStr()}</div>`;
        msgsEl.appendChild(div);

        // Show typing indicator
        const typing = document.createElement('div');
        typing.className = 'cs-msg-typing';
        typing.id = 'cs-typing-indicator';
        typing.innerHTML = '<div class="cs-msg-typing-dot"></div><div class="cs-msg-typing-dot"></div><div class="cs-msg-typing-dot"></div>';
        msgsEl.appendChild(typing);
        msgsEl.scrollTop = msgsEl.scrollHeight;
      }

      // Send via API
      const result = await _api(`/api/thread/${threadId}/send`, {
        method: 'POST',
        body: JSON.stringify({ message: text }),
        timeout: 30000,
      });

      // Remove typing indicator
      const indicator = document.getElementById('cs-typing-indicator');
      if (indicator) indicator.remove();

      // Show reply
      if (result && (result.reply || result.response || result.message)) {
        const reply = result.reply || result.response || result.message;
        if (msgsEl) {
          const div = document.createElement('div');
          div.className = 'cs-msg cs-msg-them';
          div.innerHTML = `${_esc(typeof reply === 'string' ? reply : JSON.stringify(reply))}<div class="cs-msg-time">${_timeStr()}</div>`;
          msgsEl.appendChild(div);
          msgsEl.scrollTop = msgsEl.scrollHeight;
        }
      }
    }

    // ── Contacts App ─────────────────────────────────────────────────

    async _renderContacts(body) {
      if (!this._online) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">📵</div><div>SIGNAL offline</div></div>';
        return;
      }

      const data = await _api('/api/contacts');
      const contacts = data ? (data.contacts || data || []) : [];

      if (!contacts.length) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">👤</div><div>No contacts found</div></div>';
        return;
      }

      body.innerHTML = `<div class="cs-contact-list">${
        contacts.map(c => {
          const name = _esc(c.name || c.character_id || c.id || 'Unknown');
          const bio = _esc((c.bio || c.role || c.description || '').slice(0, 50));
          const avatar = c.emoji || c.avatar || name[0] || '👤';
          const heat = c.heat_label || c.heat || '';
          return `
            <div class="cs-contact-item" onclick="window.PhonePanel._contactToThread('${_esc(c.id || c.character_id || c.name)}')">
              <div class="cs-contact-avatar">${avatar}</div>
              <div class="cs-contact-info">
                <div class="cs-contact-name">${name}</div>
                <div class="cs-contact-bio">${bio}</div>
              </div>
              ${heat ? `<div class="cs-contact-heat">${_esc(heat)}</div>` : ''}
            </div>`;
        }).join('')
      }</div>`;
    }

    async _contactToThread(contactId) {
      // Create or find DM thread, then open it
      const data = await _api('/api/threads/dm', {
        method: 'POST',
        body: JSON.stringify({ character_id: contactId }),
      });
      if (data && (data.thread_id || data.id)) {
        await this._loadThreads();
        this._openThread(data.thread_id || data.id);
      } else {
        this._showToast('⚠️', 'Error', 'Could not start conversation');
      }
    }

    // ── News App ─────────────────────────────────────────────────────

    async _renderNews(body) {
      const data = await _api('/api/news/feed');

      if (!data) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">📡</div><div>News feed unavailable</div></div>';
        return;
      }

      const articles = data.articles || data.feed || data || [];
      if (!articles.length) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">📰</div><div>No news available</div></div>';
        return;
      }

      body.innerHTML = `<div class="cs-news-list">${
        articles.map(a => `
          <div class="cs-news-item">
            <div class="cs-news-category">${_esc(a.category || a.type || 'NEWS')}</div>
            <div class="cs-news-headline">${_esc(a.title || a.headline || 'Breaking')}</div>
            <div class="cs-news-summary">${_esc((a.summary || a.body || a.content || '').slice(0, 150))}</div>
            <div class="cs-news-meta">
              <span>${_esc(a.source || 'NeonCity Wire')}</span>
              <span>${_relativeTime(a.timestamp || a.published_at)}</span>
            </div>
          </div>`).join('')
      }</div>`;
    }

    // ── Wallet App ───────────────────────────────────────────────────

    async _renderWallet(body) {
      const data = await _api('/api/economy');

      if (!data) {
        body.innerHTML = `
          <div class="cs-wallet-balance">
            <div class="cs-wallet-label">Available Balance</div>
            <div class="cs-wallet-amount"><span class="cs-wallet-symbol">₵</span> ---</div>
          </div>
          <div class="cs-phone-empty"><div class="cs-phone-empty-icon">💰</div><div>Wallet data unavailable</div></div>`;
        return;
      }

      const balance = data.balance ?? data.credits ?? 0;
      const earned = data.earned ?? data.total_earned ?? 0;
      const spent = data.spent ?? data.total_spent ?? 0;
      const transactions = data.transactions || data.history || [];

      const txHtml = transactions.length
        ? transactions.slice(0, 20).map(tx => {
            const amount = tx.amount || 0;
            const isPos = amount >= 0;
            return `
              <div class="cs-wallet-tx">
                <div class="cs-wallet-tx-icon">${tx.icon || (isPos ? '📥' : '📤')}</div>
                <div class="cs-wallet-tx-info">
                  <div class="cs-wallet-tx-desc">${_esc(tx.description || tx.reason || tx.type || 'Transaction')}</div>
                  <div class="cs-wallet-tx-time">${_relativeTime(tx.timestamp)}</div>
                </div>
                <div class="cs-wallet-tx-amount ${isPos ? 'positive' : 'negative'}">${isPos ? '+' : ''}${amount}₵</div>
              </div>`;
          }).join('')
        : '<div style="text-align:center;color:rgba(255,255,255,0.2);font-size:11px;padding:20px">No transactions yet</div>';

      body.innerHTML = `
        <div class="cs-wallet-balance">
          <div class="cs-wallet-label">Available Balance</div>
          <div class="cs-wallet-amount"><span class="cs-wallet-symbol">₵</span> ${balance.toLocaleString()}</div>
        </div>
        <div class="cs-wallet-stats">
          <div class="cs-wallet-stat">
            <div class="cs-wallet-stat-label">Earned</div>
            <div class="cs-wallet-stat-value" style="color:#00ffa0">+${earned.toLocaleString()}₵</div>
          </div>
          <div class="cs-wallet-stat">
            <div class="cs-wallet-stat-label">Spent</div>
            <div class="cs-wallet-stat-value" style="color:#ef4444">-${spent.toLocaleString()}₵</div>
          </div>
        </div>
        <div class="cs-wallet-transactions">
          <div class="cs-wallet-section-title">Recent Transactions</div>
          ${txHtml}
        </div>`;
    }

    // ── Gallery App ──────────────────────────────────────────────────

    async _renderGallery(body) {
      const data = await _api('/api/gallery');

      if (!data) {
        body.innerHTML = '<div class="cs-gallery-empty"><div class="cs-gallery-empty-icon">🖼️</div><div>Gallery unavailable</div></div>';
        return;
      }

      const items = data.images || data.gallery || data || [];
      if (!items.length) {
        body.innerHTML = '<div class="cs-gallery-empty"><div class="cs-gallery-empty-icon">🖼️</div><div>No images yet</div></div>';
        return;
      }

      body.innerHTML = `<div class="cs-gallery-grid">${
        items.map(img => {
          const src = img.url || img.path || img.thumbnail || `${PHONE_BASE}/media/photo/${img.filename || img}`;
          return `<div class="cs-gallery-thumb"><img src="${_esc(src)}" alt="" loading="lazy" onerror="this.parentElement.innerHTML='📷'"></div>`;
        }).join('')
      }</div>`;
    }

    // ── Hacker App ───────────────────────────────────────────────────

    async _renderHacker(body) {
      const data = await _api('/api/hacker/targets');

      if (!data) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">💀</div><div>Hacker network offline</div></div>';
        return;
      }

      const targets = data.targets || data || [];
      if (!targets.length) {
        body.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">🔍</div><div>No targets discovered</div></div>';
        return;
      }

      body.innerHTML = `<div class="cs-contact-list">${
        targets.map(t => `
          <div class="cs-contact-item" style="cursor:default">
            <div class="cs-contact-avatar" style="border-color:rgba(239,68,68,0.3);background:rgba(239,68,68,0.08)">💀</div>
            <div class="cs-contact-info">
              <div class="cs-contact-name">${_esc(t.name || t.character_id || t.id)}</div>
              <div class="cs-contact-bio">${_esc(t.description || t.role || 'Unknown target')}</div>
            </div>
            <div class="cs-contact-heat" style="color:rgba(239,68,68,0.6)">${_esc(t.difficulty || t.level || '???')}</div>
          </div>`).join('')
      }</div>`;
    }

    // ── Ghost Terminal ────────────────────────────────────────────────

    _renderGhost(body) {
      body.innerHTML = `
        <div style="padding:20px;display:flex;flex-direction:column;height:100%">
          <div style="text-align:center;margin-bottom:20px">
            <div style="font-size:40px;margin-bottom:8px">👾</div>
            <div style="font-size:14px;font-weight:600;color:#00ffa0;letter-spacing:0.1em">GHOST TERMINAL</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.3);margin-top:4px">Send encrypted intel to 0xGH0ST. Intel pays 50₵.</div>
          </div>
          <textarea id="cs-ghost-input"
                    class="cs-chat-input"
                    style="flex:1;border-radius:12px;resize:none;min-height:120px;padding:14px"
                    placeholder="Enter intel for 0xGH0ST..."></textarea>
          <button class="cs-chat-send"
                  style="width:100%;border-radius:12px;height:44px;margin-top:12px;font-size:13px;font-weight:700;letter-spacing:0.1em"
                  onclick="window.PhonePanel._sendGhost()">
            TRANSMIT ⬆
          </button>
        </div>`;
      setTimeout(() => {
        const input = document.getElementById('cs-ghost-input');
        if (input) input.focus();
      }, 100);
    }

    async _sendGhost() {
      const input = document.getElementById('cs-ghost-input');
      if (!input || !input.value.trim()) return;
      const msg = input.value.trim();
      input.value = '';

      const result = await _api('/api/world/send_ghost', {
        method: 'POST',
        body: JSON.stringify({ message: msg }),
        timeout: 10000,
      });

      if (result && result.ok) {
        this._showToast('👾', 'Transmitted', `+50₵ (Balance: ${result.balance}₵)`);
      } else {
        this._showToast('❌', 'Failed', result?.error || 'Transmission failed');
      }
    }

    // ── Settings App ─────────────────────────────────────────────────

    async _renderSettings(body) {
      // Check autotxt mute status
      const muteData = await _api('/api/admin/autotxt-mute');
      this._autotxtMuted = muteData ? !!muteData.muted : false;

      body.innerHTML = `
        <div class="cs-settings-list">
          <div class="cs-settings-group">Messaging</div>
          <div class="cs-settings-item">
            <div class="cs-settings-item-left">
              <div class="cs-settings-item-icon">🤖</div>
              <div>
                <div class="cs-settings-item-label">Auto-Text</div>
                <div class="cs-settings-item-desc">NPCs send autonomous messages</div>
              </div>
            </div>
            <label class="cs-toggle">
              <input type="checkbox" id="cs-setting-autotxt" ${this._autotxtMuted ? '' : 'checked'}
                     onchange="window.PhonePanel._toggleAutotxt(this.checked)">
              <div class="cs-toggle-track"></div>
              <div class="cs-toggle-thumb"></div>
            </label>
          </div>

          <div class="cs-settings-group">System</div>
          <div class="cs-settings-item">
            <div class="cs-settings-item-left">
              <div class="cs-settings-item-icon">📱</div>
              <div>
                <div class="cs-settings-item-label">Open Full Phone</div>
                <div class="cs-settings-item-desc">Launch phone scene in new tab</div>
              </div>
            </div>
            <button class="cs-app-back" style="font-size:16px" onclick="window.open('${PHONE_BASE}','_blank')">→</button>
          </div>
          <div class="cs-settings-item">
            <div class="cs-settings-item-left">
              <div class="cs-settings-item-icon">🗑️</div>
              <div>
                <div class="cs-settings-item-label">Wipe All Messages</div>
                <div class="cs-settings-item-desc">Delete all conversations (irreversible)</div>
              </div>
            </div>
            <button class="cs-app-back" style="font-size:12px;color:#ef4444"
                    onclick="if(confirm('Delete ALL messages?'))window.PhonePanel._wipeMessages()">WIPE</button>
          </div>

          <div class="cs-settings-group">Info</div>
          <div class="cs-settings-item" style="cursor:default">
            <div class="cs-settings-item-left">
              <div class="cs-settings-item-icon">ℹ️</div>
              <div>
                <div class="cs-settings-item-label">NeonPhone v3.0</div>
                <div class="cs-settings-item-desc">SIGNAL OS • CosySim Framework</div>
              </div>
            </div>
            <div style="font-size:10px;color:rgba(255,255,255,0.2)">Port ${PHONE_PORT}</div>
          </div>
        </div>`;
    }

    async _toggleAutotxt(enabled) {
      await _api('/api/admin/autotxt-mute', {
        method: 'POST',
        body: JSON.stringify({ mute: !enabled }),
      });
      this._autotxtMuted = !enabled;
      this._showToast('🤖', 'Auto-Text', enabled ? 'Enabled' : 'Muted');
    }

    async _wipeMessages() {
      await _api('/api/admin/wipe-messages', { method: 'POST' });
      this._threads = [];
      this._showToast('🗑️', 'Messages Wiped', 'All conversations deleted');
    }

    // ── Notifications & Toast ────────────────────────────────────────

    _addNotification(icon, title, text) {
      this._notifications.unshift({ icon, title, text, time: _timeStr() });
      if (this._notifications.length > 30) this._notifications.pop();

      // Update lock screen notifications
      const lockNotifs = document.getElementById('cs-lock-notifs');
      if (lockNotifs && !this._unlocked) {
        const item = document.createElement('div');
        item.className = 'cs-lock-notif-item';
        item.style.animation = 'cs-notif-in 0.3s ease';
        item.innerHTML = `
          <div class="cs-lock-notif-icon">${icon}</div>
          <div class="cs-lock-notif-body">
            <div class="cs-lock-notif-title">${_esc(title)}</div>
            <div class="cs-lock-notif-text">${_esc(text)}</div>
          </div>`;
        lockNotifs.insertBefore(item, lockNotifs.firstChild);
        if (lockNotifs.children.length > 3) lockNotifs.lastChild.remove();
      }
    }

    _showToast(icon, title, text) {
      const toast = document.getElementById('cs-phone-toast');
      const tIcon = document.getElementById('cs-toast-icon');
      const tTitle = document.getElementById('cs-toast-title');
      const tText = document.getElementById('cs-toast-text');

      if (!toast) return;
      if (tIcon) tIcon.textContent = icon;
      if (tTitle) tTitle.textContent = title;
      if (tText) tText.textContent = text;

      toast.classList.add('show');
      clearTimeout(this._toastTimeout);
      this._toastTimeout = setTimeout(() => toast.classList.remove('show'), 3500);
    }

    _updateBadge() {
      // Update navbar badge
      if (window.CosyNavbar && typeof window.CosyNavbar.updatePhoneBadge === 'function') {
        window.CosyNavbar.updatePhoneBadge(this._unreadCount);
      } else {
        const badge = document.getElementById('navbar-phone-badge') ||
          document.querySelector('[data-action="phone"] .cs-nav-badge, .cs-nav-phone .cs-nav-badge');
        if (badge) {
          badge.textContent = this._unreadCount || '';
          badge.hidden = !this._unreadCount;
        }
      }

      // Update app grid badge
      const msgBadge = document.getElementById('cs-badge-messages');
      if (msgBadge) {
        msgBadge.style.display = this._unreadCount ? 'flex' : 'none';
        msgBadge.textContent = this._unreadCount;
      }
      const dockBadge = document.getElementById('cs-dock-badge-messages');
      if (dockBadge) {
        dockBadge.style.display = this._unreadCount ? 'flex' : 'none';
        dockBadge.textContent = this._unreadCount;
      }
    }

    // ── Public API ───────────────────────────────────────────────────

    open() {
      this._panel.classList.add('open');
      this._overlay.classList.add('open');
      this._open = true;
      if (!this._unlocked) return;
      this._checkOnline();
    }

    close() {
      this._panel.classList.remove('open');
      this._overlay.classList.remove('open');
      this._open = false;
    }

    toggle() {
      this._open ? this.close() : this.open();
    }

    addNotification(notif) {
      this._addNotification(notif.icon || '📨', notif.title || 'Alert', notif.text || notif.body || '');
      this._unreadCount++;
      this._updateBadge();
    }

    destroy() {
      if (this._clockInterval) clearInterval(this._clockInterval);
      if (this._retryInterval) clearInterval(this._retryInterval);
      if (this._socket) this._socket.disconnect();
      if (this._panel) this._panel.remove();
      if (this._overlay) this._overlay.remove();
    }
  }

  // ── Bootstrap ──────────────────────────────────────────────────────

  const instance = new NeonPhone();
  window.PhonePanel = instance;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => instance.init());
  } else {
    instance.init();
  }

})();
