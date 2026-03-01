/**
 * CosySim Aria Floating Widget — aria_widget.js
 * ==============================================
 * Bottom-right floating glass circle with chat + voice modes.
 * Auto-injects CSS and listens for navbar:panel_request events.
 *
 * Usage:
 *   <script src="/shared/static/js/aria_widget.js"></script>
 *
 * Triggered by:
 *   window.ariaWidget.open()
 *   window.ariaWidget.toggle()
 *   document.dispatchEvent(new CustomEvent('navbar:panel_request', { detail: { panel: 'aria' } }))
 *
 * API:
 *   POST /api/aria/chat   { message: string } → { reply: string, state: string }
 *   Gracefully falls back to "Aria is offline" if endpoint unavailable.
 */
(function () {
  'use strict';

  /* ── Constants ───────────────────────────────────────────────── */
  const CSS_URL    = '/shared/static/css/aria_widget.css';
  const WIDGET_ID  = 'cs-aria-widget';
  const CHAT_URL   = '/api/aria/chat';

  /* ── CSS injection ───────────────────────────────────────────── */
  function _injectCSS() {
    if (document.getElementById('cs-aria-widget-css')) return;
    const link = document.createElement('link');
    link.id   = 'cs-aria-widget-css';
    link.rel  = 'stylesheet';
    link.href = CSS_URL;
    document.head.appendChild(link);
  }

  /* ── HTML injection ──────────────────────────────────────────── */
  function _injectHTML() {
    if (document.getElementById(WIDGET_ID)) return;
    fetch('/shared/templates/aria_widget.html')
      .then(r => r.ok ? r.text() : null)
      .then(html => {
        if (html) {
          const wrap = document.createElement('div');
          wrap.innerHTML = html.trim();
          document.body.appendChild(wrap.firstElementChild);
          _bindDOM();
        } else {
          _buildFallback();
        }
      })
      .catch(() => _buildFallback());
  }

  function _buildFallback() {
    const el = document.createElement('div');
    el.id = WIDGET_ID;
    el.className = 'cs-aria-widget';
    el.setAttribute('data-state', 'idle');
    el.innerHTML = `
      <button class="cs-aria-toggle" id="cs-aria-toggle" aria-label="Open Aria assistant" aria-expanded="false">
        <div class="cs-aria-portrait" id="cs-aria-portrait">
          <div class="cs-aria-fallback" style="display:flex">🤖</div>
        </div>
        <div class="cs-aria-state-ring"></div>
      </button>
      <div class="cs-aria-panel" id="cs-aria-panel" style="display:none">
        <div class="cs-aria-panel-header">
          <span class="cs-aria-name">ARIA</span>
          <div class="cs-aria-modes">
            <button class="cs-aria-mode-btn cs-aria-mode-btn--active" data-mode="messenger" aria-pressed="true">💬</button>
            <button class="cs-aria-mode-btn" data-mode="voice" aria-pressed="false">📞</button>
          </div>
          <button class="cs-aria-close-btn" id="cs-aria-close">✕</button>
        </div>
        <div class="cs-aria-content" data-mode-panel="messenger">
          <div class="cs-aria-messages" id="cs-aria-messages" role="log" aria-live="polite"></div>
          <div class="cs-aria-input-row">
            <input type="text" class="cs-aria-input" id="cs-aria-input" placeholder="Ask Aria…" autocomplete="off">
            <button class="cs-aria-send" id="cs-aria-send" aria-label="Send">↑</button>
          </div>
        </div>
        <div class="cs-aria-content" data-mode-panel="voice" style="display:none">
          <div class="cs-aria-portrait-large" id="cs-aria-portrait-large">
            <div class="cs-aria-waveform" id="cs-aria-waveform">
              <div class="cs-waveform-bar"></div>
              <div class="cs-waveform-bar"></div>
              <div class="cs-waveform-bar"></div>
              <div class="cs-waveform-bar"></div>
              <div class="cs-waveform-bar"></div>
            </div>
          </div>
          <div class="cs-aria-voice-status" id="cs-aria-voice-status">Press to speak</div>
          <button class="cs-aria-mic-btn" id="cs-aria-mic" aria-pressed="false">🎤</button>
        </div>
      </div>`;
    document.body.appendChild(el);
    _bindDOM();
  }

  /* ── AriaWidget class ────────────────────────────────────────── */
  class AriaWidget {
    constructor() {
      this._mode        = 'messenger';
      this._state       = 'idle';
      this._recognition = null;
      this._listening   = false;
      this._pendingMsg  = null;   // thinking bubble element

      _injectCSS();

      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => _injectHTML());
      } else {
        _injectHTML();
      }
    }

    /* ── Public API ─────────────────────────────────────────────── */

    open() {
      const panel = document.getElementById('cs-aria-panel');
      const toggle = document.getElementById('cs-aria-toggle');
      if (panel) {
        panel.style.display = '';
        panel.removeAttribute('aria-hidden');
      }
      if (toggle) toggle.setAttribute('aria-expanded', 'true');
      this._autoScroll();
      document.dispatchEvent(new CustomEvent('aria:opened'));
    }

    close() {
      const panel = document.getElementById('cs-aria-panel');
      const toggle = document.getElementById('cs-aria-toggle');
      if (panel) {
        panel.style.display = 'none';
        panel.setAttribute('aria-hidden', 'true');
      }
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
      if (this._listening) this.stopListening();
      document.dispatchEvent(new CustomEvent('aria:closed'));
    }

    toggle() {
      const panel = document.getElementById('cs-aria-panel');
      const isOpen = panel && panel.style.display !== 'none';
      isOpen ? this.close() : this.open();
    }

    /* ── State management ───────────────────────────────────────── */

    setState(state) {
      this._state = state;
      const widget = document.getElementById(WIDGET_ID);
      if (widget) widget.setAttribute('data-state', state);

      // Update voice status text
      const statusEl = document.getElementById('cs-aria-voice-status');
      if (statusEl) {
        const labels = {
          idle:      'Press to speak',
          talking:   'Aria is speaking…',
          thinking:  'Thinking…',
          listening: 'Listening…',
        };
        statusEl.textContent = labels[state] || state;
      }

      // Update portrait image for state
      const img = document.getElementById('cs-aria-img');
      if (img) {
        const stateImg = `/static/img/aria_${state}.png`;
        // Only switch if the current src is not already correct
        if (!img.src.endsWith(`aria_${state}.png`)) {
          img.onerror = () => {
            img.src = '/static/img/aria_idle.png';
            img.onerror = null;
          };
          img.src = stateImg;
        }
      }
    }

    /* ── Mode switching ─────────────────────────────────────────── */

    setMode(mode) {
      this._mode = mode;

      // Update mode button states
      document.querySelectorAll('.cs-aria-mode-btn').forEach(btn => {
        const active = btn.dataset.mode === mode;
        btn.classList.toggle('cs-aria-mode-btn--active', active);
        btn.setAttribute('aria-pressed', String(active));
      });

      // Show/hide content panels
      document.querySelectorAll('.cs-aria-content').forEach(panel => {
        panel.style.display = panel.dataset.modePanel === mode ? '' : 'none';
      });

      if (mode === 'messenger') {
        this._autoScroll();
      }
    }

    /* ── Messaging ──────────────────────────────────────────────── */

    sendMessage(text) {
      if (!text || !text.trim()) return;
      const input = document.getElementById('cs-aria-input');
      if (input) input.value = '';

      this.appendMessage('user', text.trim());
      this.setState('thinking');

      // Show thinking indicator
      this._pendingMsg = this._appendThinkingDots();

      fetch(CHAT_URL, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ message: text.trim() }),
      })
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(data => {
          this._removeThinkingDots();
          const reply = (data && data.reply) ? data.reply : 'No response.';
          const newState = (data && data.state) ? data.state : 'idle';
          this.appendMessage('aria', reply);
          this.setState(newState);
        })
        .catch(() => {
          this._removeThinkingDots();
          this.appendMessage('aria', 'Aria is offline.');
          this.setState('idle');
        });
    }

    appendMessage(role, text) {
      const messages = document.getElementById('cs-aria-messages');
      if (!messages) return;

      const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const msg = document.createElement('div');
      msg.className = `cs-aria-message cs-aria-message--${role === 'user' ? 'user' : 'aria'}`;
      msg.innerHTML = `
        <div class="cs-aria-message__bubble">${_esc(text)}</div>
        <span class="cs-aria-message__ts">${ts}</span>`;
      messages.appendChild(msg);
      this._autoScroll();

      // Clear notification badge if panel is open
      const panel = document.getElementById('cs-aria-panel');
      if (role === 'aria' && panel && panel.style.display === 'none') {
        this.setNotification(1);
      }
    }

    _appendThinkingDots() {
      const messages = document.getElementById('cs-aria-messages');
      if (!messages) return null;
      const el = document.createElement('div');
      el.className = 'cs-aria-message cs-aria-message--aria';
      el.innerHTML = `
        <div class="cs-aria-message__bubble">
          <div class="cs-aria-thinking-dots">
            <span></span><span></span><span></span>
          </div>
        </div>`;
      messages.appendChild(el);
      this._autoScroll();
      return el;
    }

    _removeThinkingDots() {
      if (this._pendingMsg) {
        this._pendingMsg.remove();
        this._pendingMsg = null;
      }
    }

    /* ── Voice / Speech ─────────────────────────────────────────── */

    startListening() {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRecognition) {
        this.appendMessage('aria', 'Voice input is not supported in this browser.');
        return;
      }
      if (this._listening) return;

      this._recognition = new SpeechRecognition();
      this._recognition.continuous = false;
      this._recognition.interimResults = false;
      this._recognition.lang = 'en-US';

      this._recognition.onstart = () => {
        this._listening = true;
        this.setState('listening');
        const mic = document.getElementById('cs-aria-mic');
        if (mic) mic.setAttribute('aria-pressed', 'true');
      };

      this._recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        this.stopListening();
        this.sendMessage(transcript);
      };

      this._recognition.onerror = (event) => {
        console.warn('[AriaWidget] Speech error:', event.error);
        this.stopListening();
        this.setState('idle');
      };

      this._recognition.onend = () => {
        this.stopListening();
      };

      this._recognition.start();
    }

    stopListening() {
      this._listening = false;
      if (this._recognition) {
        try { this._recognition.stop(); } catch (_) {}
        this._recognition = null;
      }
      const mic = document.getElementById('cs-aria-mic');
      if (mic) mic.setAttribute('aria-pressed', 'false');
      if (this._state === 'listening') this.setState('idle');
    }

    /* ── Notification badge ─────────────────────────────────────── */

    setNotification(count) {
      const notif = document.getElementById('cs-aria-notif');
      if (!notif) return;
      if (count > 0) {
        notif.textContent = String(count);
        notif.style.display = '';
      } else {
        notif.style.display = 'none';
      }
    }

    /* ── Scroll ─────────────────────────────────────────────────── */

    _autoScroll() {
      const messages = document.getElementById('cs-aria-messages');
      if (messages) {
        setTimeout(() => { messages.scrollTop = messages.scrollHeight; }, 50);
      }
    }
  }

  /* ── DOM binding (called after HTML is in the DOM) ───────────── */
  function _bindDOM() {
    const widget = window.ariaWidget;
    if (!widget) return;

    // Toggle button
    const toggleBtn = document.getElementById('cs-aria-toggle');
    if (toggleBtn) toggleBtn.addEventListener('click', () => widget.toggle());

    // Close button
    const closeBtn = document.getElementById('cs-aria-close');
    if (closeBtn) closeBtn.addEventListener('click', () => widget.close());

    // Mode buttons
    document.querySelectorAll('.cs-aria-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => widget.setMode(btn.dataset.mode));
    });

    // Send button
    const sendBtn = document.getElementById('cs-aria-send');
    if (sendBtn) sendBtn.addEventListener('click', () => {
      const input = document.getElementById('cs-aria-input');
      if (input) widget.sendMessage(input.value);
    });

    // Enter key in input
    const input = document.getElementById('cs-aria-input');
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          widget.sendMessage(input.value);
        }
      });
    }

    // Mic button
    const mic = document.getElementById('cs-aria-mic');
    if (mic) {
      mic.addEventListener('click', () => {
        if (widget._listening) {
          widget.stopListening();
        } else {
          widget.startListening();
        }
      });
    }

    // Clear notification when panel opens
    const panel = document.getElementById('cs-aria-panel');
    if (panel) {
      const observer = new MutationObserver(() => {
        if (panel.style.display !== 'none') {
          widget.setNotification(0);
        }
      });
      observer.observe(panel, { attributes: true, attributeFilter: ['style'] });
    }

    // Keyboard shortcut: Ctrl+Shift+I — toggle Aria widget
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'i')) {
        e.preventDefault();
        widget.toggle();
      }
    });
  }

  /* ── Utility ─────────────────────────────────────────────────── */
  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Init ────────────────────────────────────────────────────── */
  window.ariaWidget = new AriaWidget();

  // Listen for navbar panel requests
  document.addEventListener('navbar:panel_request', (e) => {
    if (e && e.detail && e.detail.panel === 'aria') {
      window.ariaWidget.toggle();
    }
  });

})();
