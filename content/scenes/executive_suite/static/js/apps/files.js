/**
 * apps/files.js — Files browser app for the NeonOS desktop.
 * ========================================================
 * v1.62.0 [2026-06-15] — ES-T3 functional app. Browses REAL game data as a
 * folder tree + grid (PINNED / DEVICES / SYSTEM sections), mirroring the
 * reference Files window. Data comes from the sandboxed backend:
 *   GET /api/files/tree         → { sections:[{label,id,title,files:[...]}] }
 *   GET /api/files/read?path=   → { name, kind, body }
 * Read-only; the backend confines reads to whitelisted roots.
 *
 * CONNECTS: window.ES registry API, executive_suite_scene /api/files/*
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  // Defer registration until after the OS core's boot() has run its
  // registerStubs() (both fire on DOMContentLoaded; the shell registered its
  // listener first, so ours runs after — replacing the stub, not the reverse).
  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  /** Map a backend file 'kind' to the reference icon class + glyph. */
  function kindIcon(kind) {
    switch (kind) {
      case 'folder': return { cls: 'folder', glyph: '📁' };
      case 'code': return { cls: 'code', glyph: '⌬' };
      case 'image': return { cls: 'image', glyph: '🖼' };
      case 'audio': return { cls: 'audio', glyph: '🎵' };
      default: return { cls: 'doc', glyph: '📄' };
    }
  }

  ready(function () {
  ES.registerApp('files', {
    title: 'Files', icon: '📁', color: 'am', pinned: true,
    width: 660, height: 420,
    chips: [{ text: 'READ-ONLY', color: 'var(--es-amber)' }],
    render: function (body, win) {
      body.innerHTML = '';
      var tree = ES.el('div', { class: 'es-fb__tree' });
      var crumbs = ES.el('div', { class: 'es-fb__crumbs' }, [
        ES.el('b', { text: 'neonos' }), ES.el('span', { class: 'sep', text: '/' }),
        ES.el('span', { text: 'loading…' }),
      ]);
      var grid = ES.el('div', { class: 'es-fb__grid' });
      var status = ES.el('div', { class: 'es-fb__status' }, [
        ES.el('span', {}, [ES.el('b', { text: '—' }), ' items']),
        ES.el('span', { text: 'NeonFS · read-only' }),
      ]);
      var main = ES.el('div', { class: 'es-fb__main' }, [crumbs, grid, status]);
      body.appendChild(ES.el('div', { class: 'es-fb' }, [tree, main]));

      var sections = [];

      function showSection(sec) {
        crumbs.innerHTML = '';
        crumbs.append(
          ES.el('b', { text: 'neonos' }), ES.el('span', { class: 'sep', text: '/' }),
          ES.el('span', { text: sec.id })
        );
        tree.querySelectorAll('.es-fb__tree-item').forEach(function (n) {
          n.classList.toggle('active', n.dataset.sid === sec.id);
        });
        grid.innerHTML = '';
        if (!sec.files.length) {
          grid.appendChild(ES.el('div', {
            class: 'es-fb__empty',
            text: 'No files here yet.',
          }));
        }
        sec.files.forEach(function (f) {
          var ic = kindIcon(f.kind);
          var file = ES.el('div', { class: 'es-file', draggable: 'true', title: f.path }, [
            ES.el('div', { class: 'es-file__icon ' + ic.cls, text: ic.glyph }),
            ES.el('div', { class: 'es-file__name', text: f.name }),
            ES.el('div', { class: 'es-file__size', text: f.size || '' }),
          ]);
          file.addEventListener('dblclick', function () { openFile(f); });
          file.addEventListener('dragstart', function (e) {
            e.dataTransfer.setData('text/plain', f.name);
            e.dataTransfer.effectAllowed = 'move';
          });
          grid.appendChild(file);
        });
        status.firstChild.innerHTML = '';
        status.firstChild.append(ES.el('b', { text: String(sec.files.length) }), ' items');
      }

      function openFile(f) {
        fetch('/api/files/read?path=' + encodeURIComponent(f.path))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.error) { ES.toast('Cannot open: ' + d.error, 'warn'); return; }
            showPreview(d);
          })
          .catch(function () { ES.toast('Read failed', 'error'); });
      }

      function showPreview(d) {
        grid.innerHTML = '';
        crumbs.innerHTML = '';
        crumbs.append(
          ES.el('b', { text: 'neonos' }), ES.el('span', { class: 'sep', text: '/' }),
          ES.el('span', { text: d.name })
        );
        var pre = ES.el('pre', { class: 'es-fb__preview', text: d.body || '(empty)' });
        grid.appendChild(pre);
      }

      function buildTree() {
        tree.innerHTML = '';
        sections.forEach(function (sec) {
          tree.appendChild(ES.el('div', { class: 'es-fb__sec', text: sec.label }));
          var item = ES.el('div', {
            class: 'es-fb__tree-item', dataset: { sid: sec.id }, title: sec.title,
          }, [ES.el('span', { class: 'ic', text: sec.icon || '📁' }), sec.title || sec.id]);
          item.addEventListener('click', function () { showSection(sec); });
          tree.appendChild(item);
        });
      }

      fetch('/api/files/tree')
        .then(function (r) { return r.json(); })
        .then(function (d) {
          sections = (d.sections || []);
          buildTree();
          if (sections.length) showSection(sections[0]);
          else grid.appendChild(ES.el('div', { class: 'es-fb__empty', text: 'No data sources.' }));
        })
        .catch(function () {
          grid.appendChild(ES.el('div', { class: 'es-fb__empty', text: 'Filesystem unavailable.' }));
        });
    },
  });
  });
})();
