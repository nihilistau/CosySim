/**
 * neon_base.js — NeonCity 2 Base Scene Initializer
 * =================================================
 * Loaded by neon_base.html on every scene.  Provides:
 *   - Scene accent extraction from <meta> + CSS custom properties
 *   - Socket.IO auto-connect with reconnection handling
 *   - Particle system initialization (delegates to cosysim-particles.js)
 *   - Common keyboard shortcuts
 *   - Scene transition integration
 *   - Console branding
 */

(function () {
  'use strict';

  // ──── Scene metadata ─────────────────────────────────────────────
  const sceneMeta = document.querySelector('meta[name="scene-key"]');
  const accentMeta = document.querySelector('meta[name="scene-accent"]');

  const SCENE_KEY = sceneMeta ? sceneMeta.content : 'neoncity';
  const SCENE_ACCENT = accentMeta ? accentMeta.content : '#00e5ff';

  // ──── Console branding ───────────────────────────────────────────
  console.log(
    '%c⚡ NEON CITY %c ' + SCENE_KEY.toUpperCase() + ' ',
    'background: #000; color: ' + SCENE_ACCENT + '; font-weight: bold; font-size: 14px; padding: 4px 8px; border: 1px solid ' + SCENE_ACCENT + ';',
    'background: ' + SCENE_ACCENT + '; color: #000; font-weight: bold; font-size: 14px; padding: 4px 8px;'
  );

  // ──── Socket.IO auto-connect ─────────────────────────────────────
  let socket = null;

  function initSocket() {
    if (typeof io === 'undefined') return null;

    socket = io({
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 20,
    });

    socket.on('connect', function () {
      document.body.classList.add('neon--connected');
      document.body.classList.remove('neon--disconnected');

      const dot = document.getElementById('navbar-own-dot');
      if (dot) dot.style.background = 'var(--cs-green, #22c55e)';
    });

    socket.on('disconnect', function () {
      document.body.classList.remove('neon--connected');
      document.body.classList.add('neon--disconnected');

      const dot = document.getElementById('navbar-own-dot');
      if (dot) dot.style.background = 'var(--cs-red, #ef4444)';
    });

    socket.on('state_update', function (data) {
      document.dispatchEvent(new CustomEvent('neon:state', { detail: data }));
    });

    socket.on('message', function (msg) {
      document.dispatchEvent(new CustomEvent('neon:message', { detail: msg }));
    });

    socket.on('notification', function (data) {
      document.dispatchEvent(new CustomEvent('neon:notification', { detail: data }));
    });

    return socket;
  }

  // ──── Particle system ────────────────────────────────────────────
  function initParticles() {
    const canvas = document.getElementById('cs-particles');
    if (!canvas) return;

    if (typeof CosyParticles !== 'undefined') {
      try {
        const particles = new CosyParticles(canvas, {
          scene: SCENE_KEY,
          accent: SCENE_ACCENT,
          density: 0.3,
        });
        particles.start();
        window._neonParticles = particles;
      } catch (e) {
        console.debug('Particles init skipped:', e.message);
      }
    }
  }

  // ──── Keyboard shortcuts ─────────────────────────────────────────
  function initKeyboard() {
    document.addEventListener('keydown', function (e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' ||
          e.target.isContentEditable) return;

      // Escape: close overlays
      if (e.key === 'Escape') {
        document.dispatchEvent(new CustomEvent('neon:escape'));
      }

      // I: toggle inventory panel
      if (e.key === 'i' || e.key === 'I') {
        if (!e.ctrlKey && !e.altKey && !e.metaKey) {
          const toggle = document.getElementById('hud-toggle-left');
          if (toggle) toggle.click();
        }
      }

      // M: toggle map
      if (e.key === 'm' || e.key === 'M') {
        if (!e.ctrlKey && !e.altKey && !e.metaKey) {
          document.dispatchEvent(new CustomEvent('neon:toggle-map'));
        }
      }
    });
  }

  // ──── Fade-in on load ────────────────────────────────────────────
  function initEntrance() {
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 300ms ease';
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        document.body.style.opacity = '1';
      });
    });
  }

  // ──── Boot sequence ──────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    initEntrance();
    socket = initSocket();
    initParticles();
    initKeyboard();

    // Expose global reference
    window.NeonBase = {
      sceneKey: SCENE_KEY,
      accent: SCENE_ACCENT,
      socket: socket,
    };
  });

})();
