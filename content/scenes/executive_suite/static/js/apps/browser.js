/**
 * apps/browser.js — Cosmetic "NeonNet" browser app for the NeonOS desktop.
 * =======================================================================
 * v1.62.0 [2026-06-15] — ES-T3 functional (cosmetic) app. An in-world browser
 * with an address bar and a couple of canned neon pages (NeonCity news + an
 * OmniCorp corp portal + a darknet bookmark). Client-side only — no network
 * access; typing an unknown address shows a tasteful "not found" page. This is
 * intentionally cosmetic flavour, not a real browser.
 *
 * CONNECTS: window.ES registry API (client-only; no backend route)
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  var PAGES = {
    'neon://news': {
      title: 'NEONCITY WIRE',
      html:
        '<div class="es-br__page es-br__news">' +
        '<h1>NEONCITY WIRE</h1>' +
        '<div class="es-br__byline">cycle 421 · rolling feed</div>' +
        '<article><h2>OmniCorp posts record quarter amid blackout probe</h2>' +
        '<p>The arcology giant reported gains even as regulators question last month&rsquo;s grid failure over the Floor-87 district.</p></article>' +
        '<article><h2>Maglev line 7 reopens after substation anomaly</h2>' +
        '<p>Transit authority blames "harmless resonance"; commuters report flickering platforms and a low hum.</p></article>' +
        '<article><h2>Rain advisory: acid index moderate through dawn</h2>' +
        '<p>Wear coatings. Street vendors near the Den remain open under awnings.</p></article>' +
        '</div>',
    },
    'neon://omnicorp': {
      title: 'OMNICORP PORTAL',
      html:
        '<div class="es-br__page es-br__corp">' +
        '<h1>OMNICORP</h1>' +
        '<div class="es-br__byline">employee services · authenticated as guest</div>' +
        '<div class="es-br__panel">Welcome to the OmniCorp self-service portal. Your provisional clearance is <b>F-87</b>.</div>' +
        '<ul class="es-br__links">' +
        '<li>▸ Badge management <span>(restricted)</span></li>' +
        '<li>▸ Floor directory <span>(87 hidden)</span></li>' +
        '<li>▸ HR welcome packet <span>do not open</span></li>' +
        '</ul></div>',
    },
    'neon://ghostnet': {
      title: 'GHOST://NET',
      html:
        '<div class="es-br__page es-br__ghost">' +
        '<h1>ghost://net</h1>' +
        '<div class="es-br__byline">enc-only · trace masked</div>' +
        '<pre class="es-br__term">&gt; node up. 3 peers.\n&gt; drop: the_score.heist (signed)\n&gt; do not reply over clear.</pre>' +
        '</div>',
    },
  };

  var BOOKMARKS = [
    { label: 'Wire', url: 'neon://news' },
    { label: 'OmniCorp', url: 'neon://omnicorp' },
    { label: 'ghost://net', url: 'neon://ghostnet' },
  ];

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
  ES.registerApp('browser', {
    title: 'Browser', icon: '🌐', color: 'cy',
    width: 620, height: 420,
    render: function (body, win) {
      body.style.flexDirection = 'column';
      body.innerHTML = '';
      var addr = ES.el('input', {
        class: 'es-br__addr', type: 'text', spellcheck: 'false', value: 'neon://news',
      });
      var go = ES.el('button', { class: 'es-br__go', text: 'GO' });
      var marks = ES.el('div', { class: 'es-br__marks' });
      BOOKMARKS.forEach(function (b) {
        var m = ES.el('button', { class: 'es-br__mark', text: b.label });
        m.addEventListener('click', function () { navigate(b.url); });
        marks.appendChild(m);
      });
      var bar = ES.el('div', { class: 'es-br__bar' }, [
        ES.el('span', { class: 'es-br__lock', text: '⌬' }), addr, go,
      ]);
      var viewport = ES.el('div', { class: 'es-br__viewport' });
      body.appendChild(ES.el('div', { class: 'es-br' }, [bar, marks, viewport]));

      function navigate(url) {
        url = (url || '').trim().toLowerCase();
        addr.value = url;
        var page = PAGES[url];
        if (!page) {
          viewport.innerHTML =
            '<div class="es-br__page es-br__404"><h1>404 · signal lost</h1>' +
            '<p>NeonNet could not resolve <b>' + (url || '∅') + '</b>.</p>' +
            '<p class="es-br__byline">try a bookmark above.</p></div>';
          win.setTitle('Browser · not found');
          return;
        }
        viewport.innerHTML = page.html;
        win.setTitle('Browser · ' + page.title);
      }

      go.addEventListener('click', function () { navigate(addr.value); });
      addr.addEventListener('keydown', function (e) { if (e.key === 'Enter') navigate(addr.value); });

      navigate('neon://news');
    },
  });
  });
})();
