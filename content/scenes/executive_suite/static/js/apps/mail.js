/**
 * apps/mail.js — Mail app for the NeonOS desktop.
 * ===============================================
 * v1.62.1 [2026-06-15] — L1: Mail now reads the unified GlobalCommsLog. Adds an
 *   INTERCEPTS folder surfacing comms the player obtained by hacking (clearly
 *   labelled 'intercepted'/'planted') — the OS payoff of phone hacking:
 *   GET  /api/mail/intercepts      -> hacked/planted comms list
 * v1.62.0 [2026-06-15] — ES-T3 functional app. Reads + composes against the
 *   phone comms via:
 *   GET  /api/mail/threads         -> inbox list + unread count
 *   GET  /api/mail/thread/<id>     -> message list (preview pane)
 *   POST /api/mail/send            -> persist an outbound message
 * Renders the reference Mail layout (folder tabs + inbox list + preview pane +
 * compose) and keeps the dock unread badge in sync. Shows a friendly empty
 * state when there are no comms (never crashes).
 *
 * CONNECTS: window.ES registry API, executive_suite_scene /api/mail/*
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  /** Best-effort short relative time from an ISO timestamp. */
  function shortTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 90) return 'now';
    if (diff < 3600) return Math.round(diff / 60) + 'm';
    if (diff < 86400) return Math.round(diff / 3600) + 'h';
    return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
  ES.registerApp('mail', {
    title: 'Mail', icon: '✉', color: 'cy', pinned: true,
    width: 680, height: 440,
    render: function (body, win) {
      body.innerHTML = '';
      var list = ES.el('div', { class: 'es-em__list' });
      var cnt = ES.el('span', { class: 'cnt', text: '0' });

      // v1.62.1 [2026-06-15] — L1: folder tabs (INBOX / INTERCEPTS). INTERCEPTS
      // surfaces comms the player obtained by hacking the unified comms log.
      var hdLabel = ES.el('b', { text: 'INBOX' });
      var tabInbox = ES.el('button', { class: 'es-em__tab active', text: 'INBOX' });
      var tabIntercepts = ES.el('button', { class: 'es-em__tab', text: 'INTERCEPTS' });
      var tabs = ES.el('div', { class: 'es-em__tabs' }, [tabInbox, tabIntercepts]);
      var inbox = ES.el('div', { class: 'es-em__inbox' }, [
        ES.el('div', { class: 'es-em__inbox-hd' }, [hdLabel, cnt]),
        tabs,
        list,
      ]);
      var view = ES.el('div', { class: 'es-em__view' });
      body.appendChild(ES.el('div', { class: 'es-em', html: '' }));
      body.firstChild.append(inbox, view);

      var threads = [];
      var selectedId = null;
      var folder = 'inbox';   // 'inbox' | 'intercepts'

      function emptyView(msg) {
        view.innerHTML = '';
        view.appendChild(ES.el('div', { class: 'es-em__empty' }, [
          ES.el('div', { class: 'es-em__empty-glyph', text: '✉' }),
          ES.el('div', { text: msg || 'Select a message to read.' }),
        ]));
      }

      function renderList() {
        list.innerHTML = '';
        if (!threads.length) {
          list.appendChild(ES.el('div', { class: 'es-em__empty', text: 'No comms yet.' }));
          return;
        }
        threads.forEach(function (t) {
          var unread = t.unread > 0;
          var row = ES.el('div', {
            class: 'es-em__row' + (unread ? ' unread' : '') + (t.id === selectedId ? ' selected' : ''),
          }, [
            ES.el('div', { class: 'es-em__row-top' }, [
              ES.el('span', { class: 'es-em__from' + (unread ? ' bold' : ''), text: t.from }),
              ES.el('span', { class: 'es-em__time', text: shortTime(t.time) }),
            ]),
            ES.el('div', { class: 'es-em__preview', text: t.preview || '(no preview)' }),
          ]);
          row.addEventListener('click', function () { openThread(t.id); });
          list.appendChild(row);
        });
      }

      function openThread(id) {
        selectedId = id;
        renderList();
        view.innerHTML = '';
        view.appendChild(ES.el('div', { class: 'es-em__view-body', text: 'loading…' }));
        fetch('/api/mail/thread/' + encodeURIComponent(id))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.error) { emptyView('Thread unavailable.'); return; }
            renderThread(d);
            // a thread is now read — refresh counts + badge
            refreshThreads(false);
          })
          .catch(function () { emptyView('Failed to load thread.'); });
      }

      function renderThread(d) {
        view.innerHTML = '';
        var hd = ES.el('div', { class: 'es-em__view-hd' }, [
          ES.el('div', { class: 'es-em__view-subj', text: d.title || 'thread' }),
          ES.el('div', { class: 'es-em__view-meta' }, [
            ES.el('b', { text: d.title || '' }), ES.el('span', { text: '· comms log' }),
          ]),
        ]);
        var bodyEl = ES.el('div', { class: 'es-em__view-body' });
        (d.messages || []).forEach(function (m) {
          bodyEl.appendChild(ES.el('div', {
            class: 'es-em__msg' + (m.mine ? ' mine' : ''),
          }, [
            ES.el('span', { class: 'es-em__msg-from', text: m.from + ' · ' + shortTime(m.time) }),
            ES.el('p', { text: m.content }),
          ]));
        });
        if (!(d.messages || []).length) {
          bodyEl.appendChild(ES.el('p', { class: 'es-em__preview', text: '(no messages)' }));
        }
        // Compose box (persists into the same thread + the comms backbone)
        var input = ES.el('input', {
          class: 'es-em__compose-in', type: 'text', placeholder: 'Reply over clear…',
        });
        var sendBtn = ES.el('button', { class: 'es-em__compose-send', text: 'SEND' });
        var compose = ES.el('div', { class: 'es-em__compose' }, [input, sendBtn]);
        function doSend() {
          var text = input.value.trim();
          if (!text) return;
          sendBtn.disabled = true;
          fetch('/api/mail/send', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id: d.id, content: text }),
          }).then(function (r) { return r.json(); })
            .then(function (res) {
              sendBtn.disabled = false;
              if (!res.success) { ES.toast('Send failed: ' + (res.error || ''), 'error'); return; }
              input.value = '';
              bodyEl.appendChild(ES.el('div', { class: 'es-em__msg mine' }, [
                ES.el('span', { class: 'es-em__msg-from', text: 'You · now' }),
                ES.el('p', { text: res.message.content }),
              ]));
              bodyEl.scrollTop = bodyEl.scrollHeight;
              ES.toast('Sent', 'success');
              refreshThreads(false);
            })
            .catch(function () { sendBtn.disabled = false; ES.toast('Send failed', 'error'); });
        }
        sendBtn.addEventListener('click', doSend);
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') doSend(); });
        view.append(hd, bodyEl, compose);
        bodyEl.scrollTop = bodyEl.scrollHeight;
      }

      function refreshThreads(selectFirst) {
        return fetch('/api/mail/threads')
          .then(function (r) { return r.json(); })
          .then(function (d) {
            threads = d.threads || [];
            cnt.textContent = String(d.unread || 0);
            win.setBadge(d.unread ? d.unread : null);
            renderList();
            if (selectFirst && threads.length && !selectedId) openThread(threads[0].id);
            else if (!threads.length) emptyView('Inbox is empty. New comms appear here.');
          })
          .catch(function () {
            cnt.textContent = '0';
            list.innerHTML = '';
            list.appendChild(ES.el('div', { class: 'es-em__empty', text: 'Comms offline.' }));
            emptyView('Comms offline.');
          });
      }

      // ── INTERCEPTS folder (v1.62.1 — L1) ──────────────────────────────
      // Renders hacked/planted comms the player obtained, each clearly labelled.
      function renderIntercepts(items) {
        list.innerHTML = '';
        if (!items.length) {
          list.appendChild(ES.el('div', { class: 'es-em__empty', text: 'No intercepts. Hack a phone to capture comms.' }));
          return;
        }
        items.forEach(function (it) {
          var row = ES.el('div', { class: 'es-em__row es-em__row--intercept' }, [
            ES.el('div', { class: 'es-em__row-top' }, [
              ES.el('span', { class: 'es-em__tagline' }, [
                ES.el('span', { class: 'es-em__tag es-em__tag--' + it.label, text: it.label }),
                ES.el('span', { class: 'es-em__from', text: ' ' + it.from + ' → ' + it.to }),
              ]),
              ES.el('span', { class: 'es-em__time', text: shortTime(it.time) }),
            ]),
            ES.el('div', { class: 'es-em__preview', text: it.content || '(no content)' }),
          ]);
          row.addEventListener('click', function () { showIntercept(it); });
          list.appendChild(row);
        });
      }

      function showIntercept(it) {
        view.innerHTML = '';
        var hd = ES.el('div', { class: 'es-em__view-hd' }, [
          ES.el('div', { class: 'es-em__view-subj' }, [
            ES.el('span', { class: 'es-em__tag es-em__tag--' + it.label, text: it.label.toUpperCase() }),
            ES.el('span', { text: ' ' + it.from + ' → ' + it.to }),
          ]),
          ES.el('div', { class: 'es-em__view-meta' }, [
            ES.el('b', { text: it.channel || 'comms' }),
            ES.el('span', { text: '· ' + (it.label === 'planted' ? 'planted by you' : 'intercepted via hack') }),
          ]),
        ]);
        var bodyEl = ES.el('div', { class: 'es-em__view-body' }, [
          ES.el('div', { class: 'es-em__msg' }, [
            ES.el('span', { class: 'es-em__msg-from', text: it.from + ' · ' + shortTime(it.time) }),
            ES.el('p', { text: it.content }),
          ]),
        ]);
        view.append(hd, bodyEl);
      }

      function refreshIntercepts() {
        return fetch('/api/mail/intercepts')
          .then(function (r) { return r.json(); })
          .then(function (d) {
            var items = d.intercepts || [];
            cnt.textContent = String(items.length || 0);
            renderIntercepts(items);
            emptyView(items.length ? 'Select an intercept to read.' : 'No captured comms yet.');
          })
          .catch(function () {
            cnt.textContent = '0';
            list.innerHTML = '';
            list.appendChild(ES.el('div', { class: 'es-em__empty', text: 'Comms offline.' }));
            emptyView('Comms offline.');
          });
      }

      function selectFolder(name) {
        if (folder === name) return;
        folder = name;
        selectedId = null;
        tabInbox.classList.toggle('active', name === 'inbox');
        tabIntercepts.classList.toggle('active', name === 'intercepts');
        hdLabel.textContent = name === 'intercepts' ? 'INTERCEPTS' : 'INBOX';
        if (name === 'intercepts') { emptyView('Loading intercepts…'); refreshIntercepts(); }
        else { emptyView('Select a message to read.'); refreshThreads(false); }
      }
      tabInbox.addEventListener('click', function () { selectFolder('inbox'); });
      tabIntercepts.addEventListener('click', function () { selectFolder('intercepts'); });

      emptyView('Select a message to read.');
      refreshThreads(true);
    },
  });
  });
})();
