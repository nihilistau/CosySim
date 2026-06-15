/**
 * apps/assistant.js — live AI Assistant app for the NeonOS desktop.
 * =================================================================
 * v1.62.0 [2026-06-15] — ES-T4 live in-world AI companion. Reproduces the
 * reference desktop's Assistant panel: avatar + LIVE badge, a chat feed, an
 * input row and an "Add my Agent" control. The default companion is Aria (a
 * seeded character). Sending a message drives a real CharacterAgent on the
 * backend and renders the live agent reply, with a typing indicator while
 * waiting.
 *
 * Transport: prefers the shared Socket.IO client (ES.socket) —
 *   emit  assistant_message {text, agent_id}
 *   recv  assistant_typing  {agent_id, typing}
 *   recv  assistant_reply   {text, agent_id, name, fallback}
 * Falls back to POST /api/assistant/send when the socket is unavailable.
 *
 * ORDERING CAVEAT: the shell registers stub apps on DOMContentLoaded AFTER app
 * modules execute at parse time, so we MUST defer ES.registerApp(...) into a
 * ready() wrapper (same pattern as apps/mail.js) or the stub would win.
 *
 * CONNECTS: window.ES registry API, executive_suite_scene assistant dispatch
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  /** Two-letter initials for the placeholder avatar (no portrait assets). */
  function initials(name) {
    var parts = String(name || '?').trim().split(/\s+/);
    var s = (parts[0] || '?')[0] + (parts[1] ? parts[1][0] : '');
    return s.toUpperCase();
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    ES.registerApp('assistant', {
      title: 'Assistant', icon: '🤖', color: 'cy', singleton: true,
      width: 600, height: 480,
      render: function (body, win) {
        body.innerHTML = '';

        // State — current companion + a small in-memory transcript.
        var agentId = 'aria';
        var agentName = 'Aria';
        var roster = [];
        var pending = false;

        // ── Header (avatar · name · LIVE badge · Add my Agent) ──
        var avatar = ES.el('div', { class: 'es-asst__avatar', text: initials(agentName) });
        var nameEl = ES.el('div', { class: 'es-asst__name', text: agentName });
        var subEl = ES.el('div', { class: 'es-asst__sub', text: 'live in-world agent' });
        var live = ES.el('span', { class: 'es-asst__live', text: 'LIVE' });
        var addBtn = ES.el('button', {
          class: 'es-asst__addbtn', title: 'Choose which agent drives the assistant',
          html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">' +
            '<rect x="3" y="6" width="14" height="12" rx="2"/><path d="M17 10l4-2v8l-4-2"/></svg>' +
            '<span>Add my Agent</span>',
        });
        var hd = ES.el('div', { class: 'es-asst__hd' }, [
          avatar,
          ES.el('div', { class: 'es-asst__id' }, [nameEl, subEl]),
          live,
          ES.el('div', { class: 'es-asst__spacer' }),
          addBtn,
        ]);

        // ── Chat feed ──
        var feed = ES.el('div', { class: 'es-asst__feed' });

        // ── Input row ──
        var input = ES.el('input', { type: 'text', placeholder: 'Aria awaits your message…' });
        var field = ES.el('div', { class: 'es-asst__field' }, [
          ES.el('span', {
            html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="#6b7280">' +
              '<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
          }),
          input,
        ]);
        var sendBtn = ES.el('button', {
          class: 'es-asst__send', title: 'Send',
          html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
            'stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/>' +
            '<polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
        });
        var inputRow = ES.el('div', { class: 'es-asst__input' }, [field, sendBtn]);

        body.appendChild(ES.el('div', { class: 'es-asst' }, [hd, feed, inputRow]));

        // ── Helpers ──
        function setAgent(id, name) {
          agentId = id;
          agentName = name || id;
          nameEl.textContent = agentName;
          avatar.textContent = initials(agentName);
          input.placeholder = agentName + ' awaits your message…';
        }

        function addMsg(text, who, cls) {
          var m = ES.el('div', { class: 'es-asst__msg ' + (cls || who) }, [
            ES.el('span', { class: 'es-asst__msg-who', text: who === 'mine' ? '@root' : agentName }),
            ES.el('span', { text: text }),
          ]);
          feed.appendChild(m);
          feed.scrollTop = feed.scrollHeight;
          return m;
        }

        var typingEl = null;
        function showTyping(on) {
          if (on) {
            if (typingEl) return;
            typingEl = ES.el('div', { class: 'es-asst__typing' }, [
              ES.el('span'), ES.el('span'), ES.el('span'),
            ]);
            feed.appendChild(typingEl);
            feed.scrollTop = feed.scrollHeight;
          } else if (typingEl) {
            typingEl.remove();
            typingEl = null;
          }
        }

        function setLive(on) {
          if (on) { live.classList.remove('off'); live.textContent = 'LIVE'; }
          else { live.classList.add('off'); live.textContent = 'OFF'; }
        }

        // ── Reply handling (socket + REST fallback) ──
        function onReply(res) {
          if (!res || res.agent_id !== agentId) { /* keep simple: still render */ }
          showTyping(false);
          pending = false;
          sendBtn.disabled = false;
          var text = (res && res.text) || '(no reply)';
          addMsg(text, 'theirs', res && res.fallback ? 'fallback' : 'theirs');
          if (res && res.fallback) setLive(false); else setLive(true);
        }

        function restSend(text) {
          fetch('/api/assistant/send', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, agent_id: agentId }),
          }).then(function (r) { return r.json(); })
            .then(onReply)
            .catch(function () {
              showTyping(false); pending = false; sendBtn.disabled = false;
              addMsg('(comms link to my agent is down — try again in a moment.)', 'theirs', 'fallback');
              setLive(false);
            });
        }

        function doSend() {
          var text = input.value.trim();
          if (!text || pending) return;
          pending = true;
          sendBtn.disabled = true;
          addMsg(text, 'mine');
          input.value = '';
          showTyping(true);
          var socket = ES.socket;
          if (socket && socket.connected) {
            socket.emit('assistant_message', { text: text, agent_id: agentId });
          } else {
            restSend(text);
          }
        }

        sendBtn.addEventListener('click', doSend);
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') doSend(); });

        // Wire live socket events (typing + reply). Null-safe.
        if (ES.socket) {
          ES.socket.on('assistant_typing', function (d) { showTyping(!!(d && d.typing)); });
          ES.socket.on('assistant_reply', onReply);
        }

        // ── "Add my Agent" picker overlay ──
        function openPicker() {
          var existing = body.querySelector('.es-asst__picker');
          if (existing) { existing.remove(); return; }
          var list = ES.el('div', { class: 'es-asst__picker-list' });
          var picker = ES.el('div', { class: 'es-asst__picker' }, [
            ES.el('div', { class: 'es-asst__picker-hd', text: 'CHOOSE YOUR AGENT' }),
            list,
            ES.el('button', { class: 'es-asst__picker-close', text: 'cancel', onClick: function () { picker.remove(); } }),
          ]);

          function renderRoster() {
            list.innerHTML = '';
            (roster.length ? roster : [{ id: 'aria', name: 'Aria', tagline: '' }]).forEach(function (a) {
              var row = ES.el('button', {
                class: 'es-asst__pick' + (a.id === agentId ? ' active' : ''),
              }, [
                ES.el('div', { class: 'es-asst__pick-av', text: initials(a.name) }),
                ES.el('div', {}, [
                  ES.el('div', { class: 'es-asst__pick-name', text: a.name }),
                  ES.el('div', { class: 'es-asst__pick-tag', text: a.tagline || ('@' + a.id) }),
                ]),
              ]);
              row.addEventListener('click', function () {
                setAgent(a.id, a.name);
                picker.remove();
                ES.toast('Agent switched to ' + a.name, 'success');
                addMsg('— ' + a.name + ' is now driving your assistant —', 'theirs', 'hint');
              });
              list.appendChild(row);
            });
          }

          renderRoster();
          body.firstChild.appendChild(picker);

          // Lazily load the roster the first time the picker opens.
          if (!roster.length) {
            fetch('/api/assistant/agents')
              .then(function (r) { return r.json(); })
              .then(function (d) { roster = (d && d.agents) || []; renderRoster(); })
              .catch(function () { /* keep the static default */ });
          }
        }
        addBtn.addEventListener('click', openPicker);

        // ── Greeting / empty state ──
        addMsg('Welcome to NEONOS. I\'m ' + agentName + ', your live agent — ask me anything.', 'theirs', 'hint');
        setTimeout(function () { try { input.focus(); } catch (e) { /* ignore */ } }, 50);
      },
    });
  });
})();
