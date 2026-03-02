/**
 * CosySim Voice Manager — v0.68
 * ==============================
 * Manages TTS/STT with backend selection, character voice map, and master toggle.
 *
 * Usage:
 *   window.voiceManager.speak("Hello!", "luna");
 *   window.voiceManager.enable();
 *   window.addEventListener('voice:speaking', e => console.log(e.detail));
 *
 * Events (CustomEvent on window):
 *   voice:enabled   — TTS was turned on
 *   voice:disabled  — TTS was turned off
 *   voice:speaking  — {charId, text} — audio playback started
 *   voice:done      — {charId}       — audio playback finished
 *   voice:transcript — {transcript}  — STT result received
 *   voice:error      — {message}     — error occurred
 */
class VoiceManager {
  constructor() {
    this._enabled  = localStorage.getItem('cosysim_tts_enabled') !== 'false';
    this._sttEnabled = localStorage.getItem('cosysim_stt_enabled') === 'true';
    this._backend  = localStorage.getItem('cs_voice_backend') || 'piper';
    this._speed    = parseFloat(localStorage.getItem('cs_voice_speed')  || '1.0');
    this._pitch    = parseFloat(localStorage.getItem('cs_voice_pitch')  || '1.0');
    this._voiceMap = JSON.parse(localStorage.getItem('cs_voice_map')    || '{}');

    this._speaking    = false;
    this._queue       = [];
    this._currentAudio = null;

    // STT
    this._recognition  = null;
    this._sttActive    = false;
  }

  // ── Master toggle ────────────────────────────────────────────────────

  enable() {
    this._enabled = true;
    localStorage.setItem('cosysim_tts_enabled', 'true');
    this._emit('voice:enabled', {});
  }

  disable() {
    this._enabled = false;
    localStorage.setItem('cosysim_tts_enabled', 'false');
    this.stop();
    this._emit('voice:disabled', {});
  }

  toggle() {
    if (this._enabled) {
      this.disable();
    } else {
      this.enable();
    }
  }

  /** @returns {boolean} */
  isEnabled() {
    return this._enabled;
  }

  // ── STT master toggle ─────────────────────────────────────────────────

  enableSTT() {
    this._sttEnabled = true;
    localStorage.setItem('cosysim_stt_enabled', 'true');
    this._emit('voice:stt_enabled', {});
  }

  disableSTT() {
    this._sttEnabled = false;
    localStorage.setItem('cosysim_stt_enabled', 'false');
    this.stopListening();
    this._emit('voice:stt_disabled', {});
  }

  /** @returns {boolean} */
  isSTTEnabled() {
    return this._sttEnabled;
  }

  // ── Speak ─────────────────────────────────────────────────────────────

  /**
   * Speak text aloud via the selected TTS backend.
   *
   * @param {string}  text    - Text to synthesize
   * @param {string|null} charId - Optional character ID for voice mapping
   * @param {object}  options - {interrupt: bool}
   * @returns {Promise<void>}
   */
  speak(text, charId = null, options = {}) {
    if (!this._enabled) {
      return Promise.resolve();
    }

    if (this._speaking) {
      if (options.interrupt) {
        this.stop();
      } else {
        return new Promise((resolve) => {
          this._queue.push({ text, charId, options, resolve });
        });
      }
    }

    return this._doSpeak(text, charId);
  }

  /**
   * Internal: perform TTS request and play audio.
   * @private
   */
  _doSpeak(text, charId) {
    this._speaking = true;

    const payload = {
      text,
      char_id: charId,
      backend: this._backend,
      speed:   this._speed,
      pitch:   this._pitch,
    };

    return fetch('/api/tts/speak', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`TTS server error: ${res.status}`);
        }
        return res.json();
      })
      .then((data) => {
        if (data.error) {
          throw new Error(data.error);
        }

        this._emit('voice:speaking', { charId, text });

        return new Promise((resolve) => {
          const audio = new Audio(data.audio_url);
          this._currentAudio = audio;

          audio.playbackRate = this._speed;

          audio.onended = () => {
            this._speaking    = false;
            this._currentAudio = null;
            this._emit('voice:done', { charId });
            resolve();
            this._processQueue();
          };

          audio.onerror = (err) => {
            this._speaking    = false;
            this._currentAudio = null;
            this._emit('voice:error', { message: `Audio play error: ${err.type}` });
            resolve();
            this._processQueue();
          };

          audio.play().catch((err) => {
            this._speaking    = false;
            this._currentAudio = null;
            this._emit('voice:error', { message: `Audio play blocked: ${err.message}` });
            resolve();
            this._processQueue();
          });
        });
      })
      .catch((err) => {
        this._speaking = false;
        this._emit('voice:error', { message: err.message || 'TTS failed' });
        this._processQueue();
      });
  }

  /** @private */
  _processQueue() {
    if (this._queue.length === 0) return;
    const next = this._queue.shift();
    this._doSpeak(next.text, next.charId).then(next.resolve);
  }

  /** Cancel current audio and clear the queue. */
  stop() {
    if (this._currentAudio) {
      this._currentAudio.pause();
      this._currentAudio.src = '';
      this._currentAudio = null;
    }
    this._speaking = false;
    // Resolve all pending queue promises
    for (const item of this._queue) {
      item.resolve();
    }
    this._queue = [];
  }

  /**
   * Speak a short preview clip.
   * @param {string}      text   - Text to preview
   * @param {string|null} charId - Optional character ID
   */
  preview(text, charId = null) {
    return this.speak(text || 'Hello, I am ready.', charId, { interrupt: true });
  }

  // ── STT ───────────────────────────────────────────────────────────────

  /**
   * Start Web Speech API recognition and resolve with transcript.
   * @returns {Promise<string>}
   */
  listen() {
    if (!this._sttEnabled) {
      return Promise.reject(new Error('STT is disabled.'));
    }
    return new Promise((resolve, reject) => {
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

      if (!SpeechRecognition) {
        const msg = 'Web Speech API not supported in this browser.';
        this._emit('voice:error', { message: msg });
        return reject(new Error(msg));
      }

      this._recognition = new SpeechRecognition();
      this._recognition.lang        = 'en-US';
      this._recognition.interimResults = false;
      this._recognition.maxAlternatives = 1;
      this._sttActive = true;

      this._recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        this._emit('voice:transcript', { transcript });
        this._sttActive = false;
        resolve(transcript);
      };

      this._recognition.onerror = (event) => {
        this._sttActive = false;
        this._emit('voice:error', { message: `STT error: ${event.error}` });
        reject(new Error(event.error));
      };

      this._recognition.onend = () => {
        this._sttActive = false;
      };

      this._recognition.start();
    });
  }

  /** Stop active STT recognition. */
  stopListening() {
    if (this._recognition && this._sttActive) {
      this._recognition.stop();
      this._sttActive = false;
    }
  }

  // ── Backend selection ─────────────────────────────────────────────────

  /**
   * Set TTS backend.
   * @param {'piper'|'orpheus'|'qwen3'} backend
   */
  setBackend(backend) {
    const valid = ['piper', 'orpheus', 'qwen3'];
    if (!valid.includes(backend)) {
      this._emit('voice:error', { message: `Unknown backend: ${backend}` });
      return;
    }
    this._backend = backend;
    localStorage.setItem('cs_voice_backend', backend);
  }

  /** @returns {string} Current backend name */
  getBackend() {
    return this._backend;
  }

  // ── Character voice map ──────────────────────────────────────────────

  /**
   * Map a character to a specific voice ID.
   * @param {string} charId
   * @param {string} voiceId
   */
  setCharacterVoice(charId, voiceId) {
    this._voiceMap[charId] = voiceId;
    localStorage.setItem('cs_voice_map', JSON.stringify(this._voiceMap));
  }

  /**
   * Get the voice ID for a character.
   * @param {string} charId
   * @returns {string|null}
   */
  getCharacterVoice(charId) {
    return this._voiceMap[charId] || null;
  }

  /** Clear all character voice mappings. */
  clearVoiceMap() {
    this._voiceMap = {};
    localStorage.setItem('cs_voice_map', '{}');
  }

  // ── Settings ──────────────────────────────────────────────────────────

  /**
   * Set playback speed.
   * @param {number} speed - 0.5–2.0
   */
  setSpeed(speed) {
    this._speed = Math.min(2.0, Math.max(0.5, parseFloat(speed) || 1.0));
    localStorage.setItem('cs_voice_speed', String(this._speed));
  }

  /**
   * Apply multiple settings at once.
   * @param {{speed?: number, pitch?: number, backend?: string}} opts
   */
  setOptions(opts) {
    if (opts.speed   !== undefined) this.setSpeed(opts.speed);
    if (opts.pitch   !== undefined) {
      this._pitch = Math.min(2.0, Math.max(0.5, parseFloat(opts.pitch) || 1.0));
      localStorage.setItem('cs_voice_pitch', String(this._pitch));
    }
    if (opts.backend !== undefined) this.setBackend(opts.backend);
  }

  /**
   * Return a snapshot of current settings.
   * @returns {{enabled: boolean, backend: string, speed: number, pitch: number}}
   */
  getSettings() {
    return {
      enabled: this._enabled,
      backend: this._backend,
      speed:   this._speed,
      pitch:   this._pitch,
    };
  }

  // ── Internal helpers ──────────────────────────────────────────────────

  /**
   * Dispatch a CustomEvent on window.
   * @private
   */
  _emit(name, detail) {
    window.dispatchEvent(new CustomEvent(name, { detail, bubbles: false }));
  }
}

// Expose singleton
window.voiceManager = new VoiceManager();
