/**
 * apps/settings.js — Settings app for the NeonOS desktop.
 * =======================================================
 * v1.62.0 [2026-06-15] — ES-T3 functional app. An accent-colour picker plus a
 * few toggles (reduced motion, scanlines). Preferences persist to localStorage
 * and are applied live to the shell CSS variables (--es, --es-rgb, --es-glow).
 * Settings re-apply on shell load via the small bootstrap at the bottom of this
 * file, so a chosen accent survives a refresh.
 *
 * CONNECTS: window.ES registry API (client-only; localStorage-backed)
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  var STORE_KEY = 'es.settings.v1';

  var ACCENTS = [
    { id: 'cy', name: 'Cyan', hex: '#06b6d4', rgb: '6 182 212' },
    { id: 'pk', name: 'Pink', hex: '#ec4899', rgb: '236 72 153' },
    { id: 'vi', name: 'Violet', hex: '#a855f7', rgb: '168 85 247' },
    { id: 'am', name: 'Amber', hex: '#f59e0b', rgb: '245 158 11' },
    { id: 'gr', name: 'Green', hex: '#22c55e', rgb: '34 197 94' },
  ];

  function load() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function save(s) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (e) { /* quota */ }
  }

  /** Apply settings to the live shell (CSS vars + body classes). */
  function apply(s) {
    var root = document.documentElement;
    var accent = ACCENTS.filter(function (a) { return a.id === s.accent; })[0] || ACCENTS[0];
    root.style.setProperty('--es', accent.hex);
    root.style.setProperty('--es-rgb', accent.rgb);
    root.style.setProperty('--es-glow', 'rgba(' + accent.rgb.split(' ').join(',') + ',0.45)');
    document.body.classList.toggle('es-reduced-motion', !!s.reducedMotion);
    document.body.classList.toggle('es-scanlines', !!s.scanlines);
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
  ES.registerApp('settings', {
    title: 'Settings', icon: '⚙', color: 'sl',
    width: 480, height: 420,
    render: function (body) {
      body.innerHTML = '';
      var s = load();
      if (!s.accent) s.accent = 'cy';
      var wrap = ES.el('div', { class: 'es-set' });

      // Accent picker
      wrap.appendChild(ES.el('div', { class: 'es-set__sec', text: 'ACCENT' }));
      var swatches = ES.el('div', { class: 'es-set__swatches' });
      ACCENTS.forEach(function (a) {
        var sw = ES.el('button', {
          class: 'es-set__swatch' + (a.id === s.accent ? ' active' : ''),
          style: { background: a.hex }, title: a.name,
        });
        sw.addEventListener('click', function () {
          s.accent = a.id; save(s); apply(s);
          swatches.querySelectorAll('.es-set__swatch').forEach(function (n) { n.classList.remove('active'); });
          sw.classList.add('active');
          ES.toast('Accent: ' + a.name, 'success');
        });
        swatches.appendChild(sw);
      });
      wrap.appendChild(swatches);

      // Toggles
      wrap.appendChild(ES.el('div', { class: 'es-set__sec', text: 'DISPLAY' }));
      function toggle(label, key) {
        var row = ES.el('label', { class: 'es-set__toggle' });
        var cb = ES.el('input', { type: 'checkbox' });
        cb.checked = !!s[key];
        cb.addEventListener('change', function () { s[key] = cb.checked; save(s); apply(s); });
        row.append(cb, ES.el('span', { text: label }));
        return row;
      }
      wrap.appendChild(toggle('Reduced motion', 'reducedMotion'));
      wrap.appendChild(toggle('CRT scanlines', 'scanlines'));

      // ── Phone OS upgrades (wired in sub-project 3) ──────────────────
      // PLACEHOLDER: these controls are intentionally inert for now. Sub-project
      // 3 will bind them to the live phone-OS sync / upgrade pipeline. Left here
      // (disabled) so the panel layout and copy are ready ahead of that work.
      wrap.appendChild(ES.el('div', { class: 'es-set__sec', text: 'PHONE OS UPGRADES' }));
      var ph = ES.el('div', { class: 'es-set__placeholder' }, [
        ES.el('div', { class: 'es-set__toggle es-set__toggle--disabled' }, [
          ES.el('input', { type: 'checkbox', disabled: 'disabled' }),
          ES.el('span', { text: 'Sync phone OS profile' }),
        ]),
        ES.el('div', { class: 'es-set__toggle es-set__toggle--disabled' }, [
          ES.el('input', { type: 'checkbox', disabled: 'disabled' }),
          ES.el('span', { text: 'Auto-install comms upgrades' }),
        ]),
        ES.el('div', { class: 'es-set__hint', text: 'Wired in sub-project 3.' }),
      ]);
      wrap.appendChild(ph);

      body.appendChild(wrap);
      apply(s);
    },
  });
  });

  // Apply persisted settings immediately on load so the accent survives refresh.
  apply(load());
})();
