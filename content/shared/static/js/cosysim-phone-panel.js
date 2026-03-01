/**
 * cosysim-phone-panel.js — Universal slide-in phone panel
 * Bridges to the SIGNAL scene (NeonPhone) at localhost:5555
 */

(function() {
    'use strict';

    const PHONE_PORT = 5555;
    const PHONE_BASE = `http://localhost:${PHONE_PORT}`;

    class PhonePanel {
        constructor() {
            this._panel = null;
            this._overlay = null;
            this._open = false;
            this._activeTab = 'contacts';
            this._activeContact = null;
            this._contacts = [];
            this._messages = {};
            this._notifications = [];
            this._unreadCount = 0;
            this._pollInterval = null;
        }

        init() {
            this._inject();
            this._bindNavbar();
            this._loadContacts();
            this._startPolling();
        }

        _inject() {
            const panelEl = document.createElement('div');
            panelEl.className = 'cs-phone-panel';
            panelEl.id = 'cs-phone-panel';
            panelEl.innerHTML = `
                <div class="cs-phone-header">
                    <div class="cs-phone-header-left">
                        <span class="cs-phone-signal-icon">📱</span>
                        <div>
                            <div class="cs-phone-title">SIGNAL</div>
                        </div>
                    </div>
                    <div style="display:flex;align-items:center;gap:10px">
                        <div class="cs-phone-status-dot" id="cs-phone-dot"></div>
                        <button class="cs-phone-close" onclick="window.PhonePanel.close()">✕</button>
                    </div>
                </div>
                <div class="cs-phone-tabs">
                    <button class="cs-phone-tab active" data-tab="contacts" onclick="window.PhonePanel.switchTab('contacts')">Contacts</button>
                    <button class="cs-phone-tab" data-tab="notifications" onclick="window.PhonePanel.switchTab('notifications')">Alerts</button>
                </div>
                <div class="cs-phone-content" id="cs-phone-content">
                    <div class="cs-phone-loading">
                        <div class="cs-phone-loading-spinner"></div>
                        <span>Connecting to SIGNAL...</span>
                    </div>
                </div>
            `;
            document.body.appendChild(panelEl);

            const overlayEl = document.createElement('div');
            overlayEl.className = 'cs-phone-overlay';
            overlayEl.id = 'cs-phone-overlay';
            overlayEl.onclick = () => this.close();
            document.body.appendChild(overlayEl);

            this._panel = panelEl;
            this._overlay = overlayEl;
        }

        _bindNavbar() {
            // Listen for the navbar:panel_request event fired by navbar_v2.js
            document.addEventListener('navbar:panel_request', (e) => {
                if (e.detail && e.detail.panel === 'phone') this.toggle();
            });
            // Also support direct button wiring for custom navbars
            const bind = () => {
                const btn = document.querySelector('[data-action="phone"], #cs-phone-btn, .cs-nav-phone');
                if (btn && !btn._phonePanelBound) {
                    btn._phonePanelBound = true;
                    btn.addEventListener('click', (e) => { e.preventDefault(); this.toggle(); });
                }
            };
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', bind);
            } else {
                bind();
            }
        }

        async _loadContacts() {
            try {
                const resp = await fetch(`${PHONE_BASE}/api/contacts`, { signal: AbortSignal.timeout(3000) });
                if (!resp.ok) { this._showOffline(); return; }
                const data = await resp.json();
                this._contacts = data.contacts || data || [];
                if (this._activeTab === 'contacts' && !this._activeContact) this._renderContacts();
                const dot = document.getElementById('cs-phone-dot');
                if (dot) { dot.style.background = '#10b981'; dot.style.boxShadow = '0 0 8px #10b981'; }
            } catch {
                this._showOffline();
            }
        }

        async _loadMessages(contactId) {
            try {
                const resp = await fetch(`${PHONE_BASE}/api/messages/${contactId}`, { signal: AbortSignal.timeout(3000) });
                if (!resp.ok) return [];
                const data = await resp.json();
                return data.messages || data || [];
            } catch { return []; }
        }

        async _sendMessage(contactId, text) {
            try {
                const resp = await fetch(`${PHONE_BASE}/api/send`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ contact_id: contactId, message: text }),
                    signal: AbortSignal.timeout(10000),
                });
                return await resp.json();
            } catch { return null; }
        }

        _startPolling() {
            this._pollInterval = setInterval(() => {
                if (!this._open) return;
                if (this._activeContact) {
                    this._loadMessages(this._activeContact).then(msgs => {
                        this._messages[this._activeContact] = msgs;
                        this._renderChat(this._activeContact);
                    });
                } else {
                    this._loadContacts();
                }
            }, 5000);
        }

        _showOffline() {
            const content = document.getElementById('cs-phone-content');
            if (!content) return;
            content.innerHTML = `
                <div class="cs-phone-empty">
                    <div class="cs-phone-empty-icon">📵</div>
                    <div>SIGNAL offline</div>
                    <div style="font-size:10px;color:rgba(255,255,255,0.2)">Start the phone scene at :5555</div>
                </div>`;
            const dot = document.getElementById('cs-phone-dot');
            if (dot) { dot.style.background = '#ef4444'; dot.style.boxShadow = '0 0 8px #ef4444'; }
        }

        _renderContacts() {
            const content = document.getElementById('cs-phone-content');
            if (!content) return;
            if (!this._contacts.length) {
                content.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">👤</div><div>No contacts</div></div>';
                return;
            }
            content.innerHTML = `<div class="cs-contact-list">${
                this._contacts.map(c => {
                    const id = c.id || c.character_id || c.name;
                    const name = c.name || c.character_id || c.id;
                    const preview = (c.last_message || c.bio || 'Tap to chat').slice(0, 40);
                    return `
                        <div class="cs-contact-item" onclick="window.PhonePanel.openChat('${id}')">
                            <div class="cs-contact-avatar">${c.emoji || c.avatar || name?.[0] || '👤'}</div>
                            <div class="cs-contact-info">
                                <div class="cs-contact-name">${name}</div>
                                <div class="cs-contact-preview">${preview}</div>
                            </div>
                            <div class="cs-contact-meta">
                                <div class="cs-contact-time">${c.last_seen || ''}</div>
                                ${c.unread ? `<div class="cs-contact-badge">${c.unread}</div>` : ''}
                            </div>
                        </div>`;
                }).join('')
            }</div>`;
        }

        async _renderChat(contactId) {
            const content = document.getElementById('cs-phone-content');
            if (!content) return;
            if (!this._messages[contactId]) {
                this._messages[contactId] = await this._loadMessages(contactId);
            }
            const contact = this._contacts.find(c => (c.id || c.character_id || c.name) === contactId) || { name: contactId };
            const msgs = this._messages[contactId] || [];
            const msgsHtml = msgs.length
                ? msgs.map(m => `
                    <div class="cs-msg ${m.role === 'user' || m.sender === 'player' ? 'cs-msg-me' : 'cs-msg-them'}">
                        ${m.content || m.text || m.message || ''}
                        <div class="cs-msg-time">${m.timestamp || m.time || ''}</div>
                    </div>`).join('')
                : '<div style="text-align:center;color:rgba(255,255,255,0.3);font-size:11px;padding:20px">No messages yet</div>';

            content.innerHTML = `<div class="cs-chat-view" style="height:100%;display:flex;flex-direction:column">
                <div class="cs-chat-header">
                    <button class="cs-chat-back" onclick="window.PhonePanel.backToContacts()">←</button>
                    <div class="cs-contact-avatar" style="width:32px;height:32px;font-size:14px">${contact.emoji || contact.name?.[0] || '👤'}</div>
                    <div>
                        <div class="cs-chat-contact-name">${contact.name || contactId}</div>
                        <div class="cs-chat-online">online</div>
                    </div>
                </div>
                <div class="cs-chat-messages" id="cs-chat-msgs">${msgsHtml}</div>
                <div class="cs-chat-input-row">
                    <input class="cs-chat-input" id="cs-chat-input-field"
                           placeholder="Message ${contact.name || contactId}..."
                           onkeydown="if(event.key==='Enter')window.PhonePanel.sendMsg('${contactId}')">
                    <button class="cs-chat-send" onclick="window.PhonePanel.sendMsg('${contactId}')">↑</button>
                </div>
            </div>`;
            const msgsEl = document.getElementById('cs-chat-msgs');
            if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;
        }

        _renderNotifications() {
            const content = document.getElementById('cs-phone-content');
            if (!content) return;
            if (!this._notifications.length) {
                content.innerHTML = '<div class="cs-phone-empty"><div class="cs-phone-empty-icon">🔔</div><div>No alerts</div></div>';
                return;
            }
            content.innerHTML = `<div class="cs-notif-list">${
                this._notifications.map(n => `
                    <div class="cs-notif-item">
                        <div class="cs-notif-icon">${n.icon || '📨'}</div>
                        <div class="cs-notif-body">
                            <div class="cs-notif-title">${n.title || n.type || 'Alert'}</div>
                            <div class="cs-notif-text">${(n.text || n.body || n.message || '').slice(0, 80)}</div>
                        </div>
                        <div class="cs-notif-time">${n.time || n.timestamp || ''}</div>
                    </div>`).join('')
            }</div>`;
        }

        // ── Public API ────────────────────────────────────────────────────────

        open() {
            this._panel.classList.add('open');
            this._overlay.classList.add('open');
            this._open = true;
            this._loadContacts();
        }

        close() {
            this._panel.classList.remove('open');
            this._overlay.classList.remove('open');
            this._open = false;
        }

        toggle() {
            this._open ? this.close() : this.open();
        }

        switchTab(tab) {
            this._activeTab = tab;
            this._activeContact = null;
            document.querySelectorAll('.cs-phone-tab').forEach(t => {
                t.classList.toggle('active', t.dataset.tab === tab);
            });
            if (tab === 'contacts') this._renderContacts();
            else if (tab === 'notifications') this._renderNotifications();
        }

        openChat(contactId) {
            this._activeContact = contactId;
            this._renderChat(contactId);
        }

        backToContacts() {
            this._activeContact = null;
            this._renderContacts();
        }

        async sendMsg(contactId) {
            const input = document.getElementById('cs-chat-input-field');
            if (!input || !input.value.trim()) return;
            const text = input.value.trim();
            input.value = '';
            if (!this._messages[contactId]) this._messages[contactId] = [];
            this._messages[contactId].push({
                role: 'user', content: text,
                timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}),
            });
            this._renderChat(contactId);
            const result = await this._sendMessage(contactId, text);
            if (result?.reply || result?.response) {
                this._messages[contactId].push({
                    role: 'assistant', content: result.reply || result.response,
                    timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}),
                });
                this._renderChat(contactId);
            }
        }

        addNotification(notif) {
            this._notifications.unshift(notif);
            this._unreadCount++;
            this._updateBadge();
        }

        _updateBadge() {
            // navbar_v2.js exposes window.CosyNavbar with updatePhoneBadge()
            if (window.CosyNavbar && typeof window.CosyNavbar.updatePhoneBadge === 'function') {
                window.CosyNavbar.updatePhoneBadge(this._unreadCount);
                return;
            }
            // Fallback: update badge element directly
            const badge = document.getElementById('navbar-phone-badge') ||
                document.querySelector('[data-action="phone"] .cs-nav-badge, .cs-nav-phone .cs-nav-badge');
            if (badge) {
                badge.textContent = this._unreadCount || '';
                badge.hidden = !this._unreadCount;
            }
        }

        destroy() {
            if (this._pollInterval) clearInterval(this._pollInterval);
            if (this._panel) this._panel.remove();
            if (this._overlay) this._overlay.remove();
        }
    }

    const instance = new PhonePanel();
    window.PhonePanel = instance;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => instance.init());
    } else {
        instance.init();
    }

})();
