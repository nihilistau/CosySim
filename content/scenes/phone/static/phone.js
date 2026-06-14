/**
 * SIGNAL — phone.js  (v0.68 Dark Renaissance)
 * Hacker mystery communication scene — SignalScene controller
 */
'use strict';

class SignalScene {
  constructor() {
    /** @type {string|null} */
    this.activeContact = null;
    /** @type {Object.<string,Array>} */
    this.threads = {};
    /** @type {Object.<string,Object>} */
    this.contacts = {};
    /** @type {io.Socket} */
    this.socket = null;
    /** @type {number} */
    this.ghostStage = 0;

    this._typingTimer = null;
  }

  // ── Initialisation ──────────────────────────────────────────────────────────

  init() {
    this._setupSocket();
    this.loadContacts();
    this._autoResizeInput();
    console.debug('[SIGNAL] Scene initialised');
  }

  _setupSocket() {
    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      console.debug('[SIGNAL] Socket connected:', this.socket.id);
      this.socket.emit('get_contacts');
      this.socket.emit('get_0xgh0st_status');
    });

    this.socket.on('disconnect', () => {
      console.warn('[SIGNAL] Socket disconnected');
    });

    // v1.49.2 [2026-03-22] — Socket.IO reconnect feedback
    this.socket.io.on('reconnect', (attempt) => {
      console.debug('[Phone] Reconnected after ' + attempt + ' attempt(s)');
    });
    this.socket.io.on('reconnect_attempt', (attempt) => {
      if (attempt % 3 === 0) console.debug('[Phone] Reconnecting... (attempt ' + attempt + ')');
    });

    // Contact list
    this.socket.on('contacts', (data) => {
      this._renderContacts(Array.isArray(data) ? data : []);
    });

    // Thread loaded
    this.socket.on('thread', (data) => {
      if (!data || !data.contact) return;
      const { contact, messages } = data;
      this.threads[contact.id] = messages || [];
      this._renderThread(messages || [], contact.id);
      this._updateThreadHeader(contact);
    });

    // New message (inbound or outbound)
    this.socket.on('message_new', (data) => {
      if (!data || !data.contact_id || !data.message) return;
      const { contact_id, message } = data;

      if (!this.threads[contact_id]) this.threads[contact_id] = [];
      this.threads[contact_id].push(message);

      // If this thread is open, append the bubble
      if (contact_id === this.activeContact) {
        this._appendMessage(message, contact_id);
        this._scrollToBottom();
      }

      // Update sidebar preview
      this._updateContactPreview(contact_id, message.text);
    });

    // Typing indicator
    this.socket.on('typing', (data) => {
      if (!data || data.contact_id !== this.activeContact) return;
      this._showTyping(data.is_typing, data.contact_id);
    });

    // Ghost status
    this.socket.on('ghost_status', (data) => {
      if (!data) return;
      this.ghostStage = data.stage || 0;
      this._updateGhostStatusBar(data);
    });

    // Investigation board
    this.socket.on('investigation_state', (data) => {
      this._renderInvestigation(data);
    });

    // Errors
    this.socket.on('error', (data) => {
      console.error('[SIGNAL] Server error:', data?.message);
    });
  }

  // ── Contacts ────────────────────────────────────────────────────────────────

  loadContacts() {
    this.socket.emit('get_contacts');
  }

  /**
   * Render the full contacts sidebar list.
   * @param {Array} contacts
   */
  _renderContacts(contacts) {
    const list = document.getElementById('contactsList');
    if (!list) return;

    list.innerHTML = '';
    contacts.forEach((c) => {
      this.contacts[c.id] = c;
      const li = this._buildContactItem(c);
      list.appendChild(li);
    });
  }

  /**
   * Build a single <li> contact item element.
   * @param {Object} contact
   * @returns {HTMLLIElement}
   */
  _buildContactItem(contact) {
    const li = document.createElement('li');
    li.className = `contact-item${contact.dot_class === 'ghost' ? ' ghost' : ''}`;
    li.dataset.contactId = contact.id;
    li.setAttribute('role', 'button');
    li.setAttribute('tabindex', '0');
    li.onclick = () => this.openThread(contact.id);
    li.onkeydown = (e) => { if (e.key === 'Enter') this.openThread(contact.id); };

    const isGhost = contact.dot_class === 'ghost';

    li.innerHTML = `
      <span class="contact-avatar">${contact.avatar_emoji || '👤'}</span>
      <div class="contact-info">
        <div class="contact-name">${contact.name}</div>
        <div class="contact-preview">${this._escHtml(contact.last_message || '')}</div>
      </div>
      ${isGhost
        ? `<span class="ghost-badge">ENC</span>`
        : `<span class="contact-dot ${contact.dot_class || 'gray'}"></span>`
      }
      ${contact.unread > 0
        ? `<span class="unread-badge">${contact.unread}</span>`
        : ''
      }
    `;

    return li;
  }

  /** Update a contact's preview text without full re-render. */
  _updateContactPreview(contactId, text) {
    const item = document.querySelector(`[data-contact-id="${contactId}"]`);
    if (!item) return;
    const preview = item.querySelector('.contact-preview');
    if (preview) preview.textContent = text.slice(0, 60);
  }

  // ── Thread ───────────────────────────────────────────────────────────────────

  /**
   * Open a contact thread and load messages.
   * @param {string} contactId
   */
  openThread(contactId) {
    this.activeContact = contactId;

    // Update sidebar active state
    document.querySelectorAll('.contact-item').forEach((el) => {
      el.classList.toggle('active', el.dataset.contactId === contactId);
    });

    // Clear current thread
    const container = document.getElementById('threadContainer');
    if (container) container.innerHTML = '';

    // Show / hide ghost ping button
    const ghostBtn = document.getElementById('ghostTriggerBtn');
    if (ghostBtn) ghostBtn.style.display = contactId === '0xgh0st' ? 'block' : 'none';

    // Request thread from server
    this.socket.emit('open_thread', { contact_id: contactId });
  }

  /**
   * Render a full message thread.
   * @param {Array} messages
   * @param {string} contactId
   */
  _renderThread(messages, contactId) {
    const container = document.getElementById('threadContainer');
    if (!container) return;

    container.innerHTML = '';

    if (messages.length === 0) {
      container.innerHTML = `
        <div class="thread-empty">
          <div class="empty-icon">💬</div>
          <div class="empty-text">NO MESSAGES YET</div>
          <div class="empty-sub">Send the first message.</div>
        </div>`;
      return;
    }

    messages.forEach((msg) => this._appendMessage(msg, contactId, container));
    this._scrollToBottom();
  }

  /**
   * Append a single message bubble to the thread.
   * @param {Object} msg
   * @param {string} contactId
   * @param {HTMLElement} [container]
   */
  _appendMessage(msg, contactId, container) {
    const el = container || document.getElementById('threadContainer');
    if (!el) return;

    // Remove "empty" placeholder if present
    const empty = el.querySelector('.thread-empty');
    if (empty) empty.remove();

    const isUser   = msg.from === 'user';
    const isGhost  = msg.from === '0xgh0st';
    const contact  = this.contacts[contactId] || {};
    const rowClass = isUser ? 'user' : 'contact';
    const bubbleClass = isUser ? 'user' : (isGhost ? 'ghost' : 'contact');

    const row = document.createElement('div');
    row.className = `message-row ${rowClass}`;
    row.dataset.msgId = msg.id || '';

    const timestamp = this._formatTimestamp(msg.timestamp);

    let bubbleContent;
    if (isGhost) {
      bubbleContent = this._formatGhostMessage(msg);
    } else {
      bubbleContent = `${this._escHtml(msg.text)}<span class="bubble-timestamp">${timestamp}</span>`;
    }

    row.innerHTML = `
      ${!isUser
        ? `<span class="bubble-avatar">${isGhost ? '👾' : (contact.avatar_emoji || '👤')}</span>`
        : ''
      }
      <div class="message-bubble ${bubbleClass}">${bubbleContent}</div>
      ${isUser ? `<span class="bubble-avatar">🧑</span>` : ''}
    `;

    el.appendChild(row);
  }

  /**
   * Format a 0xGH0ST message with glitch effects and hex fragments.
   * @param {Object} msg
   * @returns {string} HTML string
   */
  _formatGhostMessage(msg) {
    const hexFragments = Array.from({ length: 3 }, () =>
      Math.floor(Math.random() * 0xFFFF)
        .toString(16)
        .toUpperCase()
        .padStart(4, '0')
    ).join(' ');

    const escaped = this._escHtml(msg.text);
    const timestamp = this._formatTimestamp(msg.timestamp);

    return `
      <span class="glitch-text" data-text="${escaped}">${escaped}</span>
      <span class="ghost-fragment">:: ${hexFragments} ::</span>
      <span class="bubble-timestamp">${timestamp}</span>
    `;
  }

  // ── Send message ─────────────────────────────────────────────────────────────

  sendMessage() {
    if (!this.activeContact) return;

    const input = document.getElementById('messageInput');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    input.style.height = 'auto';

    // Optimistic local bubble
    const optimistic = {
      id: `opt_${Date.now()}`,
      from: 'user',
      text,
      timestamp: new Date().toISOString(),
      read: true,
    };
    this._appendMessage(optimistic, this.activeContact);
    this._scrollToBottom();

    // Send via socket
    this.socket.emit('send_message', {
      contact_id: this.activeContact,
      text,
    });
  }

  /** Handle Enter key in the message input. */
  _onInputKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  // ── Typing indicator ─────────────────────────────────────────────────────────

  _showTyping(isTyping, contactId) {
    const row   = document.getElementById('typingRow');
    const label = document.getElementById('typingLabel');
    const dots  = row?.querySelector('.typing-indicator');
    if (!row || !label) return;

    if (isTyping) {
      const isGhost = contactId === '0xgh0st';
      label.textContent = isGhost ? 'decrypting...' : 'typing...';
      label.className   = `typing-label${isGhost ? ' ghost-typing' : ''}`;
      if (dots) dots.className = `typing-indicator${isGhost ? ' ghost' : ''}`;
      row.style.display = 'flex';
    } else {
      row.style.display = 'none';
    }
  }

  // ── Thread header ─────────────────────────────────────────────────────────────

  _updateThreadHeader(contact) {
    const name   = document.getElementById('threadName');
    const status = document.getElementById('threadStatus');
    const avatar = document.getElementById('threadAvatar');

    if (name)   name.textContent   = contact.name || contact.id.toUpperCase();
    if (avatar) avatar.textContent = contact.avatar_emoji || '📱';

    if (status) {
      const isGhost = contact.id === '0xgh0st';
      status.textContent = isGhost ? 'SIGNAL ENCRYPTED' : (contact.status || '—');
      status.style.color = isGhost ? 'var(--accent)' : '';
    }
  }

  // ── Ghost story ───────────────────────────────────────────────────────────────

  /** Admin-trigger: push an ambient 0xGH0ST message. */
  _triggerGhostMessage() {
    this.socket.emit('trigger_ghost_message');
  }

  _updateGhostStatusBar(data) {
    const bar    = document.getElementById('ghostStatusBar');
    const stages = document.getElementById('gstStages');
    const msg    = document.getElementById('gstMsg');
    if (!bar) return;

    bar.style.display = 'flex';

    const totalStages = (data.stages || []).length || 5;
    if (stages) {
      stages.innerHTML = Array.from({ length: totalStages }, (_, i) =>
        `<div class="gst-stage-dot${i <= (data.stage || 0) ? ' active' : ''}"></div>`
      ).join('');
    }

    if (msg && data.stage_data) {
      msg.textContent = data.stage_data.clue || '';
    }
  }

  // ── Investigation panel ───────────────────────────────────────────────────────

  _toggleInvestigation() {
    const panel = document.getElementById('investigationPanel');
    if (!panel) return;
    const isOpen = panel.classList.toggle('open');
    if (isOpen) this._requestInvestigation();
  }

  _requestInvestigation() {
    this.socket.emit('get_investigation');
  }

  _renderInvestigation(data) {
    const container = document.getElementById('invClues');
    if (!container) return;

    const clues = data?.clues || [];
    if (clues.length === 0) {
      container.innerHTML = `<p class="inv-empty">No clues yet. Interact with 0xGH0ST to uncover the signal.</p>`;
      return;
    }

    container.innerHTML = clues
      .filter((c) => c.revealed !== false)
      .map((c) => {
        const tags = (c.tags || [])
          .map((t) => `<span class="clue-tag">${this._escHtml(t)}</span>`)
          .join('');
        return `
          <div class="clue-card">
            <div class="clue-title">${this._escHtml(c.title || 'CLUE')}</div>
            <div class="clue-content">${this._escHtml(c.content || '')}</div>
            ${tags ? `<div class="clue-tags">${tags}</div>` : ''}
          </div>`;
      })
      .join('');
  }

  // ── Utilities ─────────────────────────────────────────────────────────────────

  /** Escape HTML special characters. */
  _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** Format ISO timestamp into short local time. */
  _formatTimestamp(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (_) {
      return '';
    }
  }

  _scrollToBottom() {
    const container = document.getElementById('threadContainer');
    if (container) {
      requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
      });
    }
  }

  /** Auto-resize the message textarea as the user types. */
  _autoResizeInput() {
    const input = document.getElementById('messageInput');
    if (!input) return;
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    });
  }
}

// ── Bootstrap ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  window.signal = new SignalScene();
  window.signal.init();
});
