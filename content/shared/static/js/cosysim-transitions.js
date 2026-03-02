// cosysim-transitions.js
// Intercepts data-scene-nav links for smooth scene-to-scene transitions
(function () {
  const DURATION = 200; // ms — matches --cs-transition-page in design_tokens

  function addOverlay() {
    if (document.getElementById('cs-transition-overlay')) return document.getElementById('cs-transition-overlay');
    const el = document.createElement('div');
    el.id = 'cs-transition-overlay';
    el.style.cssText = 'position:fixed;inset:0;background:#000;z-index:9999;pointer-events:none;opacity:0;transition:opacity 200ms ease';
    document.body.appendChild(el);
    return el;
  }

  function fadeOut(cb) {
    const overlay = addOverlay();
    requestAnimationFrame(() => {
      overlay.style.opacity = '1';
      setTimeout(cb, DURATION);
    });
  }

  function fadeIn() {
    const overlay = addOverlay();
    overlay.style.opacity = '1';
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        overlay.style.opacity = '0';
      });
    });
  }

  // Intercept scene nav links
  document.addEventListener('click', function (e) {
    const link = e.target.closest('[data-scene-nav]');
    if (!link || !link.href) return;
    e.preventDefault();
    const href = link.href;
    fadeOut(() => { window.location.href = href; });
  });

  // Fade in on page load
  window.addEventListener('DOMContentLoaded', fadeIn);
})();
