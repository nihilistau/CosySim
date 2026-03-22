/**
 * signal.js — SIGNAL Cyberdeck Terminal Controller
 * ==================================================
 * Lightweight messaging terminal using the phone_scene_v2 REST API.
 * This is the neon_base-compatible alternate UI for the Phone scene.
 *
 * Version: v1.52.0 [2026-03-22]
 * Author:  CosySim Team
 */

'use strict';

class SignalTerminal {
  constructor() {
    this.socket = null;
    this.contacts = [];
    this.activeThread = null;
    this.activeContact = null;
  }

  init() {
    this._setupSocket();
    this._loadContacts();
    this._loadMap();
    this._initParticles();
    console.log('[SIGNAL] Cyberdeck online.');
  }

  _initParticles() {
    const canvas = document.getElementById('signal-canvas');
    if (!canvas || typeof ParticleSystem3D === 'undefined') return;
    try {
      new ParticleSystem3D(canvas, {
        background: 'transparent', presets: ['neon_dust'],
        color: '#10b981', secondaryColor: '#06b6d4', density: 0.3, speed: 0.15,
      }).start();
    } catch (e) { console.warn('[SIGNAL] Particles failed:', e); }
  }

  _setupSocket() {
    this.socket = io('', { transports: ['websocket', 'polling'] });
    this.socket.on('connect', () => {
      document.getElementById('sig-status').textContent = '\u25C9 ONLINE';
    });
    this.socket.on('disconnect', () => {
      document.getElementById('sig-status').textContent = '\u25CB OFFLINE';
    });
    this.socket.on('message_new', (data) => {
      if (this.activeThread && data.thread_id === this.activeThread) {
        this._appendMessage(data.message || data);
      }
    });
    this.socket.on('typing', (data) => {
      if (this.activeThread && data.thread_id === this.activeThread) {
        this._showTyping(data.character || 'contact');
        setTimeout(() => this._hideTyping(), 3000);
      }
    });
  }

  // ── Contacts ────────────────────────────────────────────────────

  async _loadContacts() {
    try {
      const res = await fetch('/api/contacts');
      const data = await res.json();
      this.contacts = data.contacts || data || [];
      this._renderContacts();
    } catch (e) {
      console.warn('[SIGNAL] Contacts fetch failed:', e);
    }
  }

  _renderContacts() {
    const el = document.getElementById('contact-list');
    const countEl = document.getElementById('contact-count');
    if (!el) return;
    if (countEl) countEl.textContent = this.contacts.length;

    if (!this.contacts.length) {
      el.innerHTML = '<div class="sig-empty">No contacts found.</div>';
      return;
    }

    el.innerHTML = this.contacts.map(c => {
      const name = c.display_name || c.name || c.id || 'Unknown';
      const avatar = c.avatar || '\u{1F464}';
      const mood = c.mood || '';
      return `<div class="sig-contact" data-id="${this._esc(c.id || name)}" onclick="SignalApp.selectContact('${this._esc(c.id || name)}')">
        <span class="sig-contact__avatar">${avatar}</span>
        <span class="sig-contact__name">${this._esc(name)}</span>
        ${mood ? `<span class="sig-contact__badge">${this._esc(mood)}</span>` : ''}
      </div>`;
    }).join('');
  }

  // ── Thread Selection ────────────────────────────────────────────

  async selectContact(contactId) {
    this.activeContact = contactId;

    // Highlight active contact
    document.querySelectorAll('.sig-contact').forEach(c => {
      c.classList.toggle('active', c.dataset.id === contactId);
    });

    // Update header
    const contact = this.contacts.find(c => (c.id || c.name) === contactId);
    const name = contact ? (contact.display_name || contact.name || contactId) : contactId;
    document.getElementById('thread-name').textContent = name;
    document.getElementById('thread-status').textContent = contact?.mood || 'online';

    // Update contact info panel
    this._renderContactInfo(contact);

    // Get or create DM thread
    try {
      const res = await fetch('/api/threads/dm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_id: contactId }),
      });
      const data = await res.json();
      const threadId = data.thread_id || data.id;
      if (threadId) {
        this.activeThread = threadId;
        await this._loadMessages(threadId);
        // Join socket room for real-time updates
        if (this.socket) this.socket.emit('join_thread', { thread_id: threadId });
      }
    } catch (e) {
      console.warn('[SIGNAL] DM thread creation failed:', e);
    }
  }

  _renderContactInfo(contact) {
    const el = document.getElementById('contact-info');
    if (!el || !contact) {
      if (el) el.innerHTML = '<div class="sig-empty">No contact selected.</div>';
      return;
    }
    const name = contact.display_name || contact.name || contact.id;
    el.innerHTML = `
      <div style="font-family:var(--sig-mono);font-size:0.6rem;color:var(--sig);margin-bottom:4px">${this._esc(name)}</div>
      <div style="font-size:0.5rem;color:var(--sig-muted)">Mood: ${this._esc(contact.mood || 'unknown')}</div>
      <div style="font-size:0.5rem;color:var(--sig-muted)">Scene: ${this._esc(contact.location || 'unknown')}</div>
    `;
  }

  // ── Messages ────────────────────────────────────────────────────

  async _loadMessages(threadId) {
    const el = document.getElementById('thread-messages');
    if (!el) return;
    try {
      const res = await fetch(`/api/thread/${encodeURIComponent(threadId)}/messages`);
      const data = await res.json();
      const messages = data.messages || data || [];
      if (!messages.length) {
        el.innerHTML = '<div class="sig-welcome"><div class="sig-welcome__text">No messages yet. Say hello.</div></div>';
        return;
      }
      el.innerHTML = messages.map(m => this._renderMessage(m)).join('');
      el.scrollTop = el.scrollHeight;
    } catch (e) {
      el.innerHTML = '<div class="sig-empty">Failed to load messages.</div>';
    }
  }

  _renderMessage(m) {
    const isUser = m.role === 'user' || m.sender === 'player' || m.is_user;
    const cls = isUser ? 'sig-msg--user' : 'sig-msg--other';
    const text = m.content || m.text || m.body || '';
    const time = m.timestamp ? new Date(m.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    return `<div class="sig-msg ${cls}">
      <div class="sig-msg__bubble">${this._esc(text)}</div>
      ${time ? `<div class="sig-msg__meta">${time}</div>` : ''}
    </div>`;
  }

  _appendMessage(m) {
    const el = document.getElementById('thread-messages');
    if (!el) return;
    // Remove welcome screen if present
    const welcome = el.querySelector('.sig-welcome');
    if (welcome) welcome.remove();
    el.insertAdjacentHTML('beforeend', this._renderMessage(m));
    el.scrollTop = el.scrollHeight;
    this._hideTyping();
  }

  // ── Send ────────────────────────────────────────────────────────

  async send() {
    const input = document.getElementById('sig-input');
    if (!input || !this.activeThread) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    // Show user message immediately
    this._appendMessage({ role: 'user', content: text, timestamp: Date.now() / 1000 });

    // Show typing indicator
    this._showTyping(this.activeContact || 'contact');

    try {
      await fetch(`/api/thread/${encodeURIComponent(this.activeThread)}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      });
      // Response will come via Socket.IO message_new event
    } catch (e) {
      this._hideTyping();
      this._appendMessage({ role: 'system', content: 'Failed to send message.' });
    }
  }

  // ── Typing ──────────────────────────────────────────────────────

  _showTyping(name) {
    const el = document.getElementById('thread-typing');
    const label = document.getElementById('typing-label');
    if (el) el.style.display = '';
    if (label) label.textContent = `${name} is typing...`;
  }

  _hideTyping() {
    const el = document.getElementById('thread-typing');
    if (el) el.style.display = 'none';
  }

  // ── Map ─────────────────────────────────────────────────────────

  async _loadMap() {
    try {
      const res = await fetch('/api/city/neighbors');
      const data = await res.json();
      const el = document.getElementById('sig-map');
      if (!el) return;
      const neighbors = data.neighbors || [];
      if (!neighbors.length) {
        el.innerHTML = '<div class="sig-empty">No connections.</div>';
        return;
      }
      el.innerHTML = neighbors.map(n =>
        `<a href="http://localhost:${n.port}/" title="${n.name} (${n.district})">${this._esc(n.name)} <span style="color:var(--sig-muted)">:${n.port}</span></a>`
      ).join('');
    } catch (e) {
      console.warn('[SIGNAL] Map fetch failed:', e);
    }
  }

  // ── Utils ───────────────────────────────────────────────────────

  _esc(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
}

const SignalApp = new SignalTerminal();
document.addEventListener('DOMContentLoaded', () => SignalApp.init());
