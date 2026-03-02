/**
 * cosysim-stt.js — Push-to-talk Speech-to-Text via Web Speech API
 * Sends transcribed text to the active scene's chat endpoint via Socket.IO
 */
(function () {
  'use strict';

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  class CosySimSTT {
    constructor() {
      this.available = !!SpeechRecognition;
      this.listening = false;
      this.recognition = null;
      this.button = null;
      this._init();
    }

    _init() {
      if (!this.available) {
        console.warn('[CosySTT] Web Speech API not available in this browser');
        return;
      }

      this.recognition = new SpeechRecognition();
      this.recognition.continuous = false;
      this.recognition.interimResults = true;
      this.recognition.lang = 'en-US';
      this.recognition.maxAlternatives = 1;

      this.recognition.onresult = (event) => {
        const transcript = Array.from(event.results)
          .map(r => r[0].transcript)
          .join('');
        const isFinal = event.results[event.results.length - 1].isFinal;

        this._updatePreview(transcript, isFinal);

        if (isFinal) {
          this._sendTranscript(transcript.trim());
          this.stop();
        }
      };

      this.recognition.onerror = (event) => {
        console.error('[CosySTT] Error:', event.error);
        this._setButtonState('error');
        setTimeout(() => this._setButtonState('idle'), 2000);
      };

      this.recognition.onend = () => {
        this.listening = false;
        this._setButtonState('idle');
      };

      // Inject the PTT button into the page
      window.addEventListener('DOMContentLoaded', () => this._injectButton());

      // Keyboard shortcut: hold Space when input is not focused
      document.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && !this._isInputFocused() && !this.listening) {
          e.preventDefault();
          this.start();
        }
      });
      document.addEventListener('keyup', (e) => {
        if (e.code === 'Space' && this.listening) {
          this.stop();
        }
      });
    }

    _injectButton() {
      const btn = document.createElement('button');
      btn.id = 'cs-ptt-btn';
      btn.className = 'cs-ptt-btn';
      btn.title = 'Push to Talk (Space)';
      btn.innerHTML = `<span class="cs-ptt-icon">🎤</span><span class="cs-ptt-label">PTT</span>`;
      btn.setAttribute('aria-label', 'Push to talk');

      const preview = document.createElement('div');
      preview.id = 'cs-stt-preview';
      preview.className = 'cs-stt-preview';
      preview.setAttribute('aria-live', 'polite');

      btn.addEventListener('mousedown', () => this.start());
      btn.addEventListener('mouseup', () => this.stop());
      btn.addEventListener('touchstart', (e) => { e.preventDefault(); this.start(); });
      btn.addEventListener('touchend', () => this.stop());

      document.body.appendChild(btn);
      document.body.appendChild(preview);
      this.button = btn;
      this.preview = preview;

      if (!this.available) {
        btn.disabled = true;
        btn.title = 'Speech recognition not available';
      }
    }

    start() {
      if (!this.available || this.listening) return;
      this.listening = true;
      this._setButtonState('listening');
      this.recognition.start();
    }

    stop() {
      if (!this.listening) return;
      this.listening = false;
      this.recognition.stop();
      this._setButtonState('idle');
    }

    _sendTranscript(text) {
      if (!text) return;
      // Send via Socket.IO if available
      if (typeof io !== 'undefined' && window._csSocket) {
        window._csSocket.emit('user_message', { text, source: 'stt' });
      }
      // Also inject into any visible chat input
      const chatInput = document.querySelector('#cs-chat-input, [data-chat-input], .chat-input input, .chat-input textarea');
      if (chatInput) {
        chatInput.value = text;
        chatInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }

    _updatePreview(text, isFinal) {
      if (!this.preview) return;
      this.preview.textContent = isFinal ? `✓ "${text}"` : text;
      this.preview.classList.toggle('is-final', isFinal);
    }

    _setButtonState(state) {
      if (!this.button) return;
      this.button.dataset.state = state;
      const icon = this.button.querySelector('.cs-ptt-icon');
      if (icon) {
        icon.textContent = state === 'listening' ? '🔴' : state === 'error' ? '⚠️' : '🎤';
      }
    }

    _isInputFocused() {
      const tag = document.activeElement?.tagName?.toLowerCase();
      return tag === 'input' || tag === 'textarea' || document.activeElement?.isContentEditable;
    }
  }

  window.cosySimSTT = new CosySimSTT();
})();
