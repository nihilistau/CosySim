/**
 * cosysim-aria-portrait.js — Animated Aria Portrait System
 * States: idle | talking | thinking | listening
 * Modes: floating | messenger | voice-call | full-portrait
 *
 * Public API (window.AriaPortrait):
 *   .setState(state)   — set animation state
 *   .setMode(mode)     — switch display mode
 *   .toggleMode()      — cycle through modes
 *   .minimize()        — collapse to floating bubble
 *   .send()            — send current input value
 *
 * Voice events consumed:
 *   voice:speaking  → talking
 *   voice:done      → idle
 *   voice:listening → listening
 *   aria:thinking   → thinking
 *
 * Backward-compat bridge: proxies window.ariaWidget.setState / .open / .toggle
 */

(function () {
    'use strict';

    // ── SVG face template (small, used in floating bubble) ──────────
    const ARIA_SVG = `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" class="aria-face-svg">
        <circle cx="50" cy="50" r="46" fill="rgba(124,58,237,0.15)" stroke="rgba(167,139,250,0.3)" stroke-width="1"/>
        <circle cx="50" cy="50" r="38" fill="rgba(236,72,153,0.05)" stroke="rgba(236,72,153,0.15)" stroke-width="0.5"/>
        <g transform="translate(34,40)" class="aria-eye-group-left">
            <ellipse cx="0" cy="0" rx="5" ry="6" fill="rgba(167,139,250,0.9)" class="aria-eye-left"/>
            <circle cx="1" cy="-1" r="2" fill="rgba(236,72,153,0.8)"/>
            <circle cx="2" cy="-2" r="0.8" fill="white"/>
        </g>
        <g transform="translate(66,40)" class="aria-eye-group-right">
            <ellipse cx="0" cy="0" rx="5" ry="6" fill="rgba(167,139,250,0.9)" class="aria-eye-right"/>
            <circle cx="1" cy="-1" r="2" fill="rgba(236,72,153,0.8)"/>
            <circle cx="2" cy="-2" r="0.8" fill="white"/>
        </g>
        <path d="M 50 48 L 47 58 L 53 58" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="0.8" stroke-linecap="round"/>
        <path d="M 38 66 Q 50 74 62 66" fill="none" stroke="rgba(236,72,153,0.8)" stroke-width="2.5" stroke-linecap="round" class="aria-mouth"/>
        <path d="M 15 30 L 25 35 L 20 45" fill="none" stroke="rgba(167,139,250,0.2)" stroke-width="0.8"/>
        <path d="M 85 30 L 75 35 L 80 45" fill="none" stroke="rgba(167,139,250,0.2)" stroke-width="0.8"/>
        <circle cx="15" cy="30" r="2" fill="rgba(167,139,250,0.3)"/>
        <circle cx="85" cy="30" r="2" fill="rgba(167,139,250,0.3)"/>
        <line x1="4" y1="50" x2="96" y2="50" stroke="rgba(167,139,250,0.08)" stroke-width="0.5"/>
    </svg>`;

    // Large version used inside portrait panels
    const ARIA_SVG_LARGE = ARIA_SVG.replace('class="aria-face-svg"', 'class="aria-portrait-face-svg"');

    // ── Wave bars for voice-call waveform ────────────────────────────
    const WAVE_BARS = Array(8).fill(0).map(() => '<div class="aria-wave-bar"></div>').join('');

    // ──────────────────────────────────────────────────────────────────
    class AriaPortrait {
        constructor() {
            this._root     = null;
            this._mode     = 'floating';
            this._state    = 'idle';
            this._messages = [];
            this._apiBase  = window._ARIA_API_BASE || ('http://localhost:' + (window._ARIA_PORT || 8500));
        }

        // ── Bootstrap ────────────────────────────────────────────────
        init() {
            this._inject();
            this._bindVoiceEvents();
            this._bindNavbarBtn();
            this._setState('idle');
        }

        _inject() {
            if (document.getElementById('aria-portrait-root')) return;
            const root = document.createElement('div');
            root.className = 'aria-portrait-root';
            root.id = 'aria-portrait-root';
            root.setAttribute('data-mode', 'floating');
            root.setAttribute('data-state', 'idle');
            root.innerHTML = this._floatingHTML();
            document.body.appendChild(root);
            this._root = root;
        }

        // ── HTML builders ────────────────────────────────────────────
        _floatingHTML() {
            return `<div class="aria-float-bubble" onclick="window.AriaPortrait.toggleMode()" title="Open Aria">
                ${ARIA_SVG}
            </div>`;
        }

        _messengerHTML() {
            const msgs = this._messages.map(m => this._renderBubble(m)).join('');
            const empty = !this._messages.length
                ? '<div style="text-align:center;color:rgba(255,255,255,0.2);font-size:11px;padding:40px 20px">How can I help?</div>'
                : '';
            return `<div class="aria-panel">
                <div class="aria-panel-header">
                    <div style="display:flex;align-items:center;gap:10px">
                        <div style="width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,rgba(124,58,237,0.8),rgba(236,72,153,0.6));display:flex;align-items:center;justify-content:center;font-size:14px">🤖</div>
                        <div>
                            <div class="aria-panel-title">ARIA</div>
                            <div style="font-size:10px;color:rgba(167,139,250,0.6);letter-spacing:.1em">SYSTEM ASSISTANT</div>
                        </div>
                    </div>
                    <div class="aria-panel-controls">
                        <button class="aria-mode-btn" onclick="window.AriaPortrait.setMode('voice-call')" title="Voice call">📞</button>
                        <button class="aria-mode-btn" onclick="window.AriaPortrait.setMode('full-portrait')" title="Full portrait">🖼️</button>
                        <button class="aria-panel-close" onclick="window.AriaPortrait.minimize()">−</button>
                    </div>
                </div>
                <div class="aria-messenger-messages" id="aria-messages">${msgs}${empty}</div>
                <div class="aria-input-row">
                    <input class="aria-input" id="aria-input" placeholder="Ask Aria anything…"
                           onkeydown="if(event.key==='Enter')window.AriaPortrait.send()">
                    <button class="aria-send-btn" onclick="window.AriaPortrait.send()">↑</button>
                </div>
            </div>`;
        }

        _voiceCallHTML() {
            const statusText = this._stateLabel();
            return `<div class="aria-panel">
                <div class="aria-panel-header">
                    <div class="aria-panel-title">ARIA — VOICE CALL</div>
                    <div class="aria-panel-controls">
                        <button class="aria-mode-btn" onclick="window.AriaPortrait.setMode('messenger')" title="Chat">💬</button>
                        <button class="aria-mode-btn" onclick="window.AriaPortrait.setMode('full-portrait')" title="Portrait">🖼️</button>
                        <button class="aria-panel-close" onclick="window.AriaPortrait.minimize()">−</button>
                    </div>
                </div>
                <div class="aria-portrait-display">
                    <div class="aria-portrait-face">${ARIA_SVG_LARGE}</div>
                    <div class="aria-portrait-name">ARIA</div>
                    <div class="aria-portrait-status" id="aria-call-status">${statusText}</div>
                    <div class="aria-waveform">${WAVE_BARS}</div>
                </div>
                <div class="aria-call-controls">
                    <button class="aria-call-btn aria-call-btn-mute"    onclick="window.AriaPortrait._toggleMute()"    title="Mute">🎙️</button>
                    <button class="aria-call-btn aria-call-btn-speaker" onclick="window.AriaPortrait._toggleSpeaker()" title="Speaker">🔊</button>
                    <button class="aria-call-btn aria-call-btn-end"     onclick="window.AriaPortrait.minimize()"       title="End">📵</button>
                </div>
            </div>`;
        }

        _fullPortraitHTML() {
            const recentMsgs = this._messages.slice(-3).map(m => this._renderBubble(m)).join('');
            return `<div class="aria-panel">
                <div class="aria-panel-header">
                    <div class="aria-panel-title">ARIA — ASSISTANT</div>
                    <div class="aria-panel-controls">
                        <button class="aria-mode-btn" onclick="window.AriaPortrait.setMode('messenger')" title="Chat">💬</button>
                        <button class="aria-mode-btn" onclick="window.AriaPortrait.setMode('voice-call')" title="Voice call">📞</button>
                        <button class="aria-panel-close" onclick="window.AriaPortrait.minimize()">−</button>
                    </div>
                </div>
                <div class="aria-portrait-display" style="padding:32px">
                    <div class="aria-portrait-face" style="width:160px;height:160px">${ARIA_SVG_LARGE}</div>
                    <div class="aria-portrait-name">ARIA</div>
                    <div class="aria-portrait-status" id="aria-portrait-status">${this._stateLabel()}</div>
                </div>
                <div class="aria-messenger-messages" id="aria-messages" style="max-height:180px">${recentMsgs}</div>
                <div class="aria-input-row">
                    <input class="aria-input" id="aria-input" placeholder="Ask Aria…"
                           onkeydown="if(event.key==='Enter')window.AriaPortrait.send()">
                    <button class="aria-send-btn" onclick="window.AriaPortrait.send()">↑</button>
                </div>
            </div>`;
        }

        _renderBubble(m) {
            const isAria = m.role === 'aria' || m.role === 'assistant';
            const cls    = isAria ? 'aria-msg-aria' : 'aria-msg-user';
            return `<div class="aria-msg-bubble ${cls}">
                ${m.content || m.text || ''}
                <div class="aria-msg-time">${m.time || ''}</div>
            </div>`;
        }

        _stateLabel() {
            const labels = {
                idle: 'online',
                talking: 'speaking…',
                thinking: 'processing…',
                listening: 'listening…',
            };
            return labels[this._state] || 'online';
        }

        // ── Event binding ────────────────────────────────────────────
        _bindVoiceEvents() {
            window.addEventListener('voice:speaking',  () => this.setState('talking'));
            window.addEventListener('voice:done',      () => this.setState('idle'));
            window.addEventListener('voice:listening', () => this.setState('listening'));
            window.addEventListener('aria:thinking',   () => this.setState('thinking'));
        }

        _bindNavbarBtn() {
            const bind = () => {
                const btn = document.querySelector('[data-action="aria"], #cs-aria-btn, .cs-nav-aria');
                if (btn) btn.addEventListener('click', (e) => { e.preventDefault(); this.toggleMode(); });
            };
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', bind);
            } else {
                bind();
            }
        }

        // ── Public API ───────────────────────────────────────────────
        /** Set animation state (idle | talking | thinking | listening). */
        setState(state) {
            this._setState(state);
        }

        _setState(state) {
            this._state = state;
            if (!this._root) return;
            this._root.setAttribute('data-state', state);
            const bubble = this._root.querySelector('.aria-float-bubble');
            if (bubble) bubble.setAttribute('data-state', state);
            const statusEl = document.getElementById('aria-call-status')
                          || document.getElementById('aria-portrait-status');
            if (statusEl) statusEl.textContent = this._stateLabel();
        }

        /** Switch display mode. */
        setMode(mode) {
            this._mode = mode;
            if (!this._root) return;
            this._root.setAttribute('data-mode', mode);
            const builders = {
                'floating':      () => this._floatingHTML(),
                'messenger':     () => this._messengerHTML(),
                'voice-call':    () => this._voiceCallHTML(),
                'full-portrait': () => this._fullPortraitHTML(),
            };
            this._root.innerHTML = (builders[mode] || builders['floating'])();
            this._root.setAttribute('data-state', this._state);
            const msgsEl = document.getElementById('aria-messages');
            if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;
            try { localStorage.setItem('cs_aria_mode', mode); } catch (_) {}
        }

        /** Cycle through modes: floating → messenger → voice-call → full-portrait → floating. */
        toggleMode() {
            const cycle = ['floating', 'messenger', 'voice-call', 'full-portrait'];
            const next  = cycle[(cycle.indexOf(this._mode) + 1) % cycle.length];
            this.setMode(next);
        }

        /** Collapse to floating bubble. */
        minimize() {
            this.setMode('floating');
        }

        /** Send message from #aria-input. */
        async send() {
            const input = document.getElementById('aria-input');
            if (!input || !input.value.trim()) return;
            const text = input.value.trim();
            input.value = '';
            const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            this._messages.push({ role: 'user', content: text, time });
            this.setState('thinking');
            this._refreshMessages();
            try {
                const resp = await fetch(this._apiBase + '/api/aria/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text }),
                    signal: AbortSignal.timeout(15000),
                });
                const data = await resp.json();
                const reply = data.reply || data.response || data.text || '…';
                this._messages.push({
                    role: 'aria',
                    content: reply,
                    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                });
            } catch (_) {
                this._messages.push({ role: 'aria', content: '⚠️ Connection error', time });
            }
            this.setState('idle');
            this._refreshMessages();
        }

        _refreshMessages() {
            const msgsEl = document.getElementById('aria-messages');
            if (!msgsEl) return;
            const msgs = this._mode === 'full-portrait' ? this._messages.slice(-3) : this._messages;
            msgsEl.innerHTML = msgs.map(m => this._renderBubble(m)).join('');
            msgsEl.scrollTop = msgsEl.scrollHeight;
        }

        // Stubs — extend for real mic/speaker toggle
        _toggleMute() {}
        _toggleSpeaker() {}
    }

    // ── Bootstrap ────────────────────────────────────────────────────
    const instance = new AriaPortrait();
    window.AriaPortrait = instance;

    // Backward-compat shim so existing code using window.ariaWidget still works
    window.ariaWidget = window.ariaWidget || {
        setState: (s) => instance.setState(s),
        open:     ()  => instance.setMode('messenger'),
        toggle:   ()  => instance.toggleMode(),
    };

    function _boot() {
        instance.init();
        try {
            const saved = localStorage.getItem('cs_aria_mode');
            if (saved && saved !== 'floating') instance.setMode(saved);
        } catch (_) {}
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _boot);
    } else {
        _boot();
    }

})();
