/**
 * apps/terminal.js — Sandboxed console app for the NeonOS desktop.
 * ===============================================================
 * v1.62.0 [2026-06-15] — ES-T3 functional app. A CRT-style terminal that runs
 * ONLY a whitelist of safe, read-only commands via the backend:
 *   POST /api/console { command } → { ok, lines[], clear? }
 * The whitelist (status / whoami / scenes / world / inbox / help / clear) lives
 * server-side; there is NO arbitrary code or shell execution. Unknown commands
 * return "command not found". Keeps a local input history (↑/↓).
 *
 * CONNECTS: window.ES registry API, executive_suite_scene /api/console
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
  ES.registerApp('terminal', {
    title: 'Term', icon: '▶', color: 'sl',
    width: 560, height: 360,
    chips: [{ text: 'SANDBOXED', color: 'var(--es-green)' }],
    render: function (body, win) {
      body.innerHTML = '';
      var out = ES.el('div', { class: 'es-tm__out' });
      var prompt = ES.el('span', { class: 'es-tm__prompt', text: 'root@neoncity:~$' });
      var input = ES.el('input', {
        class: 'es-tm__in', type: 'text', spellcheck: 'false', autocomplete: 'off',
      });
      var line = ES.el('div', { class: 'es-tm__line' }, [prompt, input]);
      body.appendChild(ES.el('div', { class: 'es-tm' }, [out, line]));

      var history = [];
      var hIdx = 0;

      function print(text, cls) {
        out.appendChild(ES.el('div', { class: 'es-tm__row' + (cls ? ' ' + cls : ''), text: text }));
        out.scrollTop = out.scrollHeight;
      }

      function echoCommand(cmd) {
        out.appendChild(ES.el('div', { class: 'es-tm__row es-tm__row--cmd' }, [
          ES.el('span', { class: 'es-tm__prompt', text: 'root@neoncity:~$ ' }),
          ES.el('span', { text: cmd }),
        ]));
      }

      function run(cmd) {
        echoCommand(cmd);
        fetch('/api/console', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: cmd }),
        }).then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.clear) { out.innerHTML = ''; return; }
            (d.lines || []).forEach(function (l) {
              print(l, d.ok ? null : 'es-tm__row--err');
            });
          })
          .catch(function () { print('neonsh: connection error', 'es-tm__row--err'); });
      }

      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          var cmd = input.value.trim();
          input.value = '';
          if (!cmd) { echoCommand(''); return; }
          history.push(cmd); hIdx = history.length;
          run(cmd);
        } else if (e.key === 'ArrowUp') {
          if (hIdx > 0) { hIdx--; input.value = history[hIdx] || ''; }
          e.preventDefault();
        } else if (e.key === 'ArrowDown') {
          if (hIdx < history.length) { hIdx++; input.value = history[hIdx] || ''; }
          e.preventDefault();
        }
      });

      body.addEventListener('click', function () { input.focus(); });

      print('NEONOS shell · sandboxed (read-only)');
      print("type 'help' for available commands");
      run('status');
    },
    onOpen: function (win) {
      var inp = win.body.querySelector('.es-tm__in');
      if (inp) inp.focus();
    },
  });
  });
})();
