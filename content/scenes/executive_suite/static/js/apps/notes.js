/**
 * apps/notes.js — Notes app for the NeonOS desktop.
 * =================================================
 * v1.62.0 [2026-06-15] — ES-T3 functional app. Persistent notes with the
 * reference toolbar + status bar (word count + saved indicator). Loads/saves
 * via:
 *   GET  /api/notes   → { notes:[{id,title,body,updated_at}] }
 *   POST /api/notes   → persist the full notes list to data/...notes.json
 * Autosaves (debounced) on edit. A single editable document for simplicity;
 * the backend stores a list so it scales to multiple notes later.
 *
 * CONNECTS: window.ES registry API, executive_suite_scene /api/notes
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  var DEFAULT_BODY = '# CYCLE NOTES\n\n- [ ] new note — start typing\n';

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
  ES.registerApp('notes', {
    title: 'Notes', icon: '📝', color: 'vi', pinned: true,
    width: 540, height: 380,
    chips: [{ text: 'SAVED', color: 'var(--es-green)' }],
    render: function (body, win) {
      body.innerHTML = '';
      var editor = ES.el('textarea', {
        class: 'es-np__editor es-np__editor--edit', spellcheck: 'false',
        placeholder: 'Type your notes…',
      });
      var wordsEl = ES.el('b', { text: '0' });
      var saveEl = ES.el('span', { class: 'save', text: '● loading…' });
      var toolbar = ES.el('div', { class: 'es-np__toolbar' });
      ['MD', 'B', 'I', 'H1', '|', '☐', '▣'].forEach(function (t) {
        if (t === '|') { toolbar.appendChild(ES.el('div', { class: 'es-np__tb-divider' })); return; }
        var btn = ES.el('button', { class: 'es-np__tb-btn' + (t === 'MD' ? ' active' : ''), text: t });
        btn.addEventListener('click', function () { applyTool(t); });
        toolbar.appendChild(btn);
      });
      var status = ES.el('div', { class: 'es-np__status' }, [
        ES.el('span', {}, [wordsEl, ' words']),
        ES.el('span', { text: 'md · UTF-8 · LF' }),
        saveEl,
      ]);
      body.appendChild(ES.el('div', { class: 'es-np' }, [toolbar, editor, status]));

      var noteId = null;
      var saveTimer = null;

      function countWords() {
        var w = editor.value.trim();
        wordsEl.textContent = String(w ? w.split(/\s+/).length : 0);
      }

      /** Insert/wrap text at the cursor for the toolbar buttons. */
      function applyTool(t) {
        var s = editor.selectionStart, e = editor.selectionEnd;
        var sel = editor.value.slice(s, e);
        var ins = sel;
        if (t === 'B') ins = '**' + (sel || 'bold') + '**';
        else if (t === 'I') ins = '_' + (sel || 'italic') + '_';
        else if (t === 'H1') ins = '# ' + (sel || 'Heading');
        else if (t === '☐') ins = '- [ ] ' + (sel || 'todo');
        else if (t === '▣') ins = '- [x] ' + (sel || 'done');
        else return;
        editor.setRangeText(ins, s, e, 'end');
        editor.focus();
        onEdit();
      }

      function onEdit() {
        countWords();
        saveEl.className = 'save save--dirty';
        saveEl.textContent = '○ unsaved';
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(save, 800);
      }

      function save() {
        var note = {
          id: noteId || 'note_main',
          title: (editor.value.split('\n')[0] || 'Untitled').replace(/^#+\s*/, '').slice(0, 60),
          body: editor.value,
          updated_at: new Date().toISOString(),
        };
        noteId = note.id;
        fetch('/api/notes', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notes: [note] }),
        }).then(function (r) { return r.json(); })
          .then(function (res) {
            if (res.success) {
              saveEl.className = 'save';
              saveEl.textContent = '● saved';
              win.setChips([{ text: 'SAVED', color: 'var(--es-green)' }]);
            } else {
              saveEl.className = 'save save--err';
              saveEl.textContent = '● save failed';
            }
          })
          .catch(function () {
            saveEl.className = 'save save--err';
            saveEl.textContent = '● offline';
          });
      }

      editor.addEventListener('input', onEdit);

      fetch('/api/notes')
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var notes = d.notes || [];
          if (notes.length) {
            noteId = notes[0].id;
            editor.value = notes[0].body || '';
          } else {
            editor.value = DEFAULT_BODY;
          }
          countWords();
          saveEl.className = 'save';
          saveEl.textContent = '● saved';
        })
        .catch(function () {
          editor.value = DEFAULT_BODY;
          countWords();
          saveEl.className = 'save save--err';
          saveEl.textContent = '● offline';
        });
    },
    onClose: function () { /* autosave already persisted on edit */ },
  });
  });
})();
