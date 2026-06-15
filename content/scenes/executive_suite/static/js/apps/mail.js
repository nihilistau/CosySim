/**
 * apps/mail.js — Mail app for the NeonOS desktop.
 * ===============================================
 * v1.62.0 [2026-06-15] — ES-T3 functional app. Reads + composes against the
 * EXISTING phone comms (PhoneDB threads/messages) via:
 *   GET  /api/mail/threads         → inbox list + unread count
 *   GET  /api/mail/thread/<id>     → message list (preview pane)
 *   POST /api/mail/send            → persist an outbound message
 * Renders the reference Mail layout (inbox list + preview pane + compose) and
 * keeps the dock unread badge in sync. Shows a friendly empty state when the
 * comms DB has no threads (never crashes).
 *
 * NOTE: this repoints to GlobalCommsLog in sub-project 2 — the backend keeps
 * the response shape stable so this client survives that swap.
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
    width: 660, height: 420,
    render: function (body, win) {
      body.innerHTML = '';
      var list = ES.el('div', { class: 'es-em__list' });
      var cnt = ES.el('span', { class: 'cnt', text: '0' });
      var inbox = ES.el('div', { class: 'es-em__inbox' }, [
        ES.el('div', { class: 'es-em__inbox-hd' }, [ES.el('b', { text: 'INBOX' }), cnt]),
        list,
      ]);
      var view = ES.el('div', { class: 'es-em__view' });
      body.appendChild(ES.el('div', { class: 'es-em', html: '' }));
      body.firstChild.append(inbox, view);

      var threads = [];
      var selectedId = null;

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
            ES.el('b', { text: d.title || '' }), ES.el('span', { text: '· phone comms' }),
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
        // Compose box (persists into the same thread)
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

      emptyView('Select a message to read.');
      refreshThreads(true);
    },
  });
  });
})();
