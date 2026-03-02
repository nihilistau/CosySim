/**
 * CosySim Page Transitions — 200ms fade-through-black on scene navigation.
 * Only intercepts links with [data-scene-nav] attribute.
 */
(function () {
  'use strict';

  const TRANSITION_DURATION = 200;

  function init() {
    // Apply fade-in on page load
    document.body.classList.add('cs-page-enter');
    // Remove class after animation completes
    setTimeout(() => document.body.classList.remove('cs-page-enter'), TRANSITION_DURATION + 50);

    // Intercept scene nav links
    document.addEventListener('click', (e) => {
      const link = e.target.closest('[data-scene-nav]');
      if (!link) return;
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

      e.preventDefault();
      document.body.classList.add('cs-page-exit');
      setTimeout(() => {
        window.location.href = href;
      }, TRANSITION_DURATION);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
