/**
 * CosySim Page Transitions — 200ms fade-through-black on scene navigation.
 * Only intercepts links with [data-scene-nav] attribute.
 *
 * Uses a .cs-transition-overlay div for the black-screen effect so the
 * browser doesn't need to repaint the entire body during the fade.
 */
(function () {
  'use strict';

  const TRANSITION_DURATION = 200;

  // ── Overlay element ────────────────────────────────────────────────────────
  let _overlay = null;

  function getOverlay() {
    if (!_overlay) {
      _overlay = document.createElement('div');
      _overlay.className = 'cs-transition-overlay';
      _overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:99999',
        'background:#000', 'pointer-events:none',
        'opacity:0', 'transition:opacity ' + TRANSITION_DURATION + 'ms ease',
      ].join(';');
      document.body.appendChild(_overlay);
    }
    return _overlay;
  }

  function fadeOut(cb) {
    const overlay = getOverlay();
    overlay.style.opacity = '1';
    setTimeout(cb, TRANSITION_DURATION);
  }

  function fadeIn() {
    const overlay = getOverlay();
    requestAnimationFrame(() => {
      overlay.style.opacity = '0';
    });
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    // Fade-in on page load via overlay
    fadeIn();
    // Also apply class-based enter for CSS animation compatibility
    document.body.classList.add('cs-page-enter');
    setTimeout(() => document.body.classList.remove('cs-page-enter'), TRANSITION_DURATION + 50);

    // Intercept scene nav links
    document.addEventListener('click', (e) => {
      const link = e.target.closest('[data-scene-nav]');
      if (!link) return;
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

      e.preventDefault();
      document.body.classList.add('cs-page-exit');
      fadeOut(() => {
        window.location.href = href;
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
