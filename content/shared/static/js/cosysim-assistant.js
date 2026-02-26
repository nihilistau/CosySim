/**
 * CosySim System Assistant Overlay
 * =================================
 * Floating chat widget for Aria, the system assistant.
 * Auto-injects into every scene via shared assets.
 *
 * API: POST /api/assistant/chat  { message, scene_id }
 *      → { reply, mood, action?, source }
 */
(function () {
  'use strict';

  const currentPort = parseInt(window.location.port, 10) || 80;
  let panelOpen = false;
  let sending = false;

  // ── Build DOM ─────────────────────────────────────────────
  function createAssistant() {
    // Inject CSS
    if (!document.getElementById('cs-assistant-css')) {
      const link = document.createElement('link');
      link.id = 'cs-assistant-css';
      link.rel = 'stylesheet';
      link.href = '/shared/css/cosysim-assistant.css';
      document.head.appendChild(link);
    }

    // Toggle button
    const toggle = document.createElement('button');
    toggle.id = 'cs-assistant-toggle';
    toggle.className = 'cs-assistant-toggle';
    toggle.innerHTML = '✦';
    toggle.title = 'System Assistant (Ctrl+Shift+A)';
    toggle.onclick = togglePanel;
    document.body.appendChild(toggle);

    // Panel
    const panel = document.createElement('div');
    panel.id = 'cs-assistant-panel';
    panel.className = 'cs-assistant-panel';
    panel.innerHTML = `
      <div class="cs-assistant-header">
        <div class="cs-assistant-avatar">✦</div>
        <div class="cs-assistant-info">
          <div class="cs-assistant-name">Aria</div>
          <div class="cs-assistant-status">System Assistant</div>
        </div>
        <button class="cs-assistant-close" onclick="window._csAssistant.toggle()">✕</button>
      </div>
      <div id="cs-assistant-messages" class="cs-assistant-messages">
        <div class="cs-assistant-msg system">Aria is here. Ask me anything or try a quick action below.</div>
      </div>
      <div class="cs-assistant-actions">
        <button class="cs-assistant-action" onclick="window._csAssistant.send('status')">📊 Status</button>
        <button class="cs-assistant-action" onclick="window._csAssistant.send('scenes')">🗂️ Scenes</button>
        <button class="cs-assistant-action" onclick="window._csAssistant.send('help')">❓ Help</button>
      </div>
      <div class="cs-assistant-input-area">
        <input id="cs-assistant-input" class="cs-assistant-input"
               placeholder="Ask Aria anything..."
               autocomplete="off"
               onkeydown="if(event.key==='Enter')window._csAssistant.sendFromInput()">
        <button id="cs-assistant-send" class="cs-assistant-send"
                onclick="window._csAssistant.sendFromInput()">Send</button>
      </div>
    `;
    document.body.appendChild(panel);
  }

  // ── Toggle Panel ──────────────────────────────────────────
  function togglePanel() {
    panelOpen = !panelOpen;
    const panel = document.getElementById('cs-assistant-panel');
    if (panel) {
      panel.classList.toggle('open', panelOpen);
      if (panelOpen) {
        const input = document.getElementById('cs-assistant-input');
        if (input) setTimeout(() => input.focus(), 100);
      }
    }
  }

  // ── Add Message ───────────────────────────────────────────
  function addMessage(text, role) {
    const container = document.getElementById('cs-assistant-messages');
    if (!container) return;
    const msg = document.createElement('div');
    msg.className = `cs-assistant-msg ${role}`;
    msg.textContent = text;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
  }

  function addTypingIndicator() {
    const container = document.getElementById('cs-assistant-messages');
    if (!container) return;
    const typing = document.createElement('div');
    typing.id = 'cs-assistant-typing';
    typing.className = 'cs-assistant-typing';
    typing.innerHTML = '<span></span><span></span><span></span>';
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;
  }

  function removeTypingIndicator() {
    const el = document.getElementById('cs-assistant-typing');
    if (el) el.remove();
  }

  // ── Send Message ──────────────────────────────────────────
  async function sendMessage(text) {
    if (!text || !text.trim() || sending) return;
    text = text.trim();

    // Ensure panel is open
    if (!panelOpen) togglePanel();

    addMessage(text, 'user');
    sending = true;
    const sendBtn = document.getElementById('cs-assistant-send');
    if (sendBtn) sendBtn.disabled = true;

    addTypingIndicator();

    try {
      const resp = await fetch('/api/assistant/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, scene_id: detectSceneId() }),
        signal: AbortSignal.timeout(15000),
      });

      removeTypingIndicator();

      if (resp.ok) {
        const data = await resp.json();
        addMessage(data.reply || 'No response.', 'assistant');

        // Handle navigation commands
        if (data.action && data.action.type === 'navigate' && data.action.port) {
          setTimeout(() => {
            if (window._csNav) {
              window._csNav.navigateTo(data.action.port);
            } else {
              window.location.href = `http://localhost:${data.action.port}/`;
            }
          }, 1500);
        }
      } else {
        addMessage('Sorry, I had trouble processing that. Try again?', 'assistant');
      }
    } catch (err) {
      removeTypingIndicator();
      // Fallback to local responses when server endpoint isn't available
      const fallback = getLocalFallback(text);
      addMessage(fallback, 'assistant');
    }

    sending = false;
    if (sendBtn) sendBtn.disabled = false;
  }

  function sendFromInput() {
    const input = document.getElementById('cs-assistant-input');
    if (!input) return;
    sendMessage(input.value);
    input.value = '';
  }

  // ── Local Fallback (no server) ────────────────────────────
  function getLocalFallback(text) {
    const lower = text.toLowerCase();
    if (lower === 'status' || lower === 'system status') {
      return "I can't reach the assistant API right now, but you can check the Command Center (:5566) for full system status.";
    }
    if (lower === 'scenes' || lower === 'list scenes') {
      const scenes = window._csNav ? window._csNav.scenes : [];
      if (scenes.length) {
        return 'Available scenes: ' + scenes.map(s => `${s.icon} ${s.label}`).join(', ');
      }
      return 'Scene list unavailable — check the navbar dropdown.';
    }
    if (lower === 'help') {
      return "I'm Aria, your system assistant. I can help navigate scenes, check status, and chat. Try 'status', 'scenes', or 'go to bedroom'.";
    }
    if (lower.startsWith('go to ') || lower.startsWith('navigate to ')) {
      const target = lower.replace('go to ', '').replace('navigate to ', '').trim();
      const scenes = window._csNav ? window._csNav.scenes : [];
      const match = scenes.find(s => s.id.includes(target) || s.label.toLowerCase().includes(target));
      if (match) {
        setTimeout(() => {
          if (window._csNav) window._csNav.navigateTo(match.port);
          else window.location.href = `http://localhost:${match.port}/`;
        }, 1000);
        return `Taking you to ${match.label}... 🚀`;
      }
      return `I couldn't find a scene matching '${target}'.`;
    }
    return "I'm here but the assistant API isn't available on this scene. Try the navbar for navigation, or check back later.";
  }

  // ── Scene Detection ───────────────────────────────────────
  function detectSceneId() {
    if (window._csNav) {
      const scene = window._csNav.getCurrentScene();
      if (scene) return scene.id;
    }
    return 'unknown';
  }

  // ── Keyboard Shortcut ─────────────────────────────────────
  function setupKeyboard() {
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.shiftKey && (e.key === 'A' || e.key === 'a')) {
        e.preventDefault();
        togglePanel();
      }
    });
  }

  // ── Public API ────────────────────────────────────────────
  window._csAssistant = {
    toggle: togglePanel,
    send: sendMessage,
    sendFromInput: sendFromInput,
    isOpen: () => panelOpen,
  };

  // ── Init ──────────────────────────────────────────────────
  function init() {
    createAssistant();
    setupKeyboard();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
