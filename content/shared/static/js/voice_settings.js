/**
 * CosySim Voice Settings UI Wiring — v0.68
 * ==========================================
 * Binds the voice_settings.html panel elements to window.voiceManager.
 *
 * Must be loaded AFTER cosysim-voice.js.
 * Usage: <script src="/shared/static/js/voice_settings.js"></script>
 *
 * Wires:
 *   - Master toggle  → voiceManager.toggle()
 *   - Backend radios → voiceManager.setBackend(value)
 *   - Speed slider   → voiceManager.setSpeed(value)
 *   - STT toggle     → localStorage 'cs_stt_enabled' flag
 *   - Preview button → voiceManager.preview(...)
 *   - voice:enabled / voice:disabled → update toggle aria-checked
 */
(function () {
  'use strict';

  /* ── Wait for DOM to be ready ────────────────────────────────── */
  function init() {
    const vm = window.voiceManager;
    if (!vm) {
      console.warn('[VoiceSettings] window.voiceManager not found — check load order.');
      return;
    }

    const panel        = document.getElementById('cs-voice-settings');
    const masterToggle = document.getElementById('cs-voice-master-toggle');
    const sttToggle    = document.getElementById('cs-stt-toggle');
    const speedSlider  = document.getElementById('cs-voice-speed');
    const speedValue   = document.getElementById('cs-speed-value');
    const previewBtn   = document.getElementById('cs-voice-preview');
    const backendRadios = document.querySelectorAll('input[name="cs-backend"]');

    if (!panel) return;   // panel not present in this template

    /* ── Sync initial state from voiceManager ──────────────────── */
    const settings = vm.getSettings();

    _setToggleState(masterToggle, settings.enabled);
    _setPanelEnabled(panel, settings.enabled);

    // Speed
    if (speedSlider) {
      speedSlider.value = settings.speed;
      if (speedValue) speedValue.textContent = settings.speed.toFixed(1) + 'x';
    }

    // Backend
    backendRadios.forEach((radio) => {
      radio.checked = (radio.value === settings.backend);
    });

    // STT
    const sttEnabled = localStorage.getItem('cs_stt_enabled') === 'true';
    if (sttToggle) _setToggleState(sttToggle, sttEnabled);

    /* ── Master toggle click ───────────────────────────────────── */
    if (masterToggle) {
      masterToggle.addEventListener('click', () => {
        vm.toggle();
      });
    }

    /* ── Reflect voice:enabled / voice:disabled events ─────────── */
    window.addEventListener('voice:enabled', () => {
      _setToggleState(masterToggle, true);
      _setPanelEnabled(panel, true);
    });

    window.addEventListener('voice:disabled', () => {
      _setToggleState(masterToggle, false);
      _setPanelEnabled(panel, false);
    });

    /* ── Backend radio change ─────────────────────────────────── */
    backendRadios.forEach((radio) => {
      radio.addEventListener('change', () => {
        if (radio.checked) {
          vm.setBackend(radio.value);
        }
      });
    });

    /* ── Speed slider ─────────────────────────────────────────── */
    if (speedSlider) {
      speedSlider.addEventListener('input', () => {
        const val = parseFloat(speedSlider.value);
        vm.setSpeed(val);
        if (speedValue) {
          speedValue.textContent = val.toFixed(1) + 'x';
        }
        speedSlider.setAttribute('aria-valuenow', val);
      });
    }

    /* ── STT toggle ───────────────────────────────────────────── */
    if (sttToggle) {
      sttToggle.addEventListener('click', () => {
        const current = localStorage.getItem('cs_stt_enabled') === 'true';
        const next    = !current;
        localStorage.setItem('cs_stt_enabled', String(next));
        _setToggleState(sttToggle, next);
        window.dispatchEvent(
          new CustomEvent(next ? 'voice:stt_enabled' : 'voice:stt_disabled', { detail: {} })
        );
      });
    }

    /* ── Preview button ─────────────────────────────────────────── */
    if (previewBtn) {
      previewBtn.addEventListener('click', () => {
        vm.preview("Hello, I'm ready.");
      });
    }

    /* ── speaking / done states on preview button ─────────────── */
    window.addEventListener('voice:speaking', () => {
      if (previewBtn) previewBtn.disabled = true;
    });

    window.addEventListener('voice:done', () => {
      if (previewBtn) previewBtn.disabled = false;
    });

    window.addEventListener('voice:error', (e) => {
      if (previewBtn) previewBtn.disabled = false;
      console.warn('[VoiceManager]', e.detail && e.detail.message);
    });
  }

  /* ── Helpers ──────────────────────────────────────────────── */

  function _setToggleState(btn, on) {
    if (!btn) return;
    btn.setAttribute('aria-checked', on ? 'true' : 'false');
  }

  function _setPanelEnabled(panel, on) {
    if (!panel) return;
    panel.setAttribute('data-voice-enabled', on ? 'true' : 'false');
  }

  /* ── Boot ─────────────────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
