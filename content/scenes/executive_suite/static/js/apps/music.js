/**
 * apps/music.js — Music player app for the NeonOS desktop.
 * ========================================================
 * v1.62.0 [2026-06-15] — ES-T3 functional app. Player with the animated
 * equalizer (reuses the shell's .es-eq keyframes), a progress bar, transport
 * controls and a queue, mirroring the reference Music window. No real audio is
 * required: playback is a client-side SIMULATION (a ticking progress timer) so
 * it is fully self-contained. Ships a curated in-world NeonCity track list (no
 * track data source exists under content/ or data/, so this is bundled).
 *
 * CONNECTS: window.ES registry API (client-only; no backend route)
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  // Curated in-world playlist (no game data source for tracks — self-contained).
  var QUEUE = [
    { title: 'Static Skyline', artist: 'Anjul Karma', genre: 'Synthwave', dur: 268 },
    { title: 'Penthouse Rain (slowed)', artist: 'V/OID', genre: 'Ambient', dur: 314 },
    { title: 'Amber Decanter', artist: 'Lyra', genre: 'Trip-hop', dur: 227 },
    { title: 'F·87 (Lyra mix)', artist: 'Lyra', genre: 'Synthwave', dur: 242 },
    { title: 'Ghost Net Lullaby', artist: '0xGH0ST', genre: 'Glitch', dur: 198 },
  ];

  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec));
    return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
  ES.registerApp('music', {
    title: 'Music', icon: '🎵', color: 'pk', pinned: true,
    width: 400, height: 380,
    chips: [{ text: 'SHUFFLE', color: 'var(--es-pink)' }],
    render: function (body, win) {
      body.innerHTML = '';
      var idx = 0, playing = true, pos = 0, timer = null;

      var trackEl = ES.el('div', { class: 'es-mp__track' });
      var artistEl = ES.el('div', { class: 'es-mp__artist' });
      var artTitle = ES.el('div', { class: 'es-mp__art-title' });
      var eqSpans = [];
      for (var i = 0; i < 8; i++) eqSpans.push(ES.el('span'));
      var eq = ES.el('div', { class: 'es-eq es-mp__eq' }, eqSpans);
      var hero = ES.el('div', { class: 'es-mp__hero' }, [
        ES.el('div', { class: 'es-mp__art' }, [
          ES.el('div', { class: 'es-mp__art-bg' }),
          ES.el('div', { class: 'es-mp__art-overlay' }),
          artTitle,
        ]),
        ES.el('div', { class: 'es-mp__info' }, [
          ES.el('div', { class: 'es-mp__label', text: 'NOW PLAYING' }),
          trackEl, artistEl, eq,
        ]),
      ]);

      var curTime = ES.el('span', { class: 'es-mp__prog-time', text: '0:00' });
      var durTime = ES.el('span', { class: 'es-mp__prog-time', text: '0:00' });
      var fill = ES.el('div', { class: 'es-mp__prog-fill', style: { width: '0%' } });
      var track = ES.el('div', { class: 'es-mp__prog-track' }, [fill]);
      track.addEventListener('click', function (e) {
        var rect = track.getBoundingClientRect();
        pos = ((e.clientX - rect.left) / rect.width) * QUEUE[idx].dur;
        tick(true);
      });
      var prog = ES.el('div', { class: 'es-mp__prog' }, [curTime, track, durTime]);

      var playBtn = ES.el('button', { class: 'es-mp__btn es-mp__btn--play', title: 'Pause', text: '⏸' });
      var prevBtn = ES.el('button', { class: 'es-mp__btn', title: 'Prev', text: '⏮' });
      var nextBtn = ES.el('button', { class: 'es-mp__btn', title: 'Next', text: '⏭' });
      var controls = ES.el('div', { class: 'es-mp__controls' }, [prevBtn, playBtn, nextBtn]);

      var queueRows = ES.el('div', { class: 'es-mp__queue' });

      body.appendChild(ES.el('div', { class: 'es-mp' }, [
        hero, prog, controls,
        ES.el('div', { class: 'es-mp__queue-wrap' }, [
          ES.el('div', { class: 'es-mp__queue-hd', text: 'UP NEXT · ' + QUEUE.length }),
          queueRows,
        ]),
      ]));

      function setEq(on) {
        eqSpans.forEach(function (s) { s.style.animationPlayState = on ? 'running' : 'paused'; });
      }

      function loadQueue() {
        queueRows.innerHTML = '';
        QUEUE.forEach(function (t, i) {
          var row = ES.el('div', { class: 'es-mp__q-row' + (i === idx ? ' playing' : '') }, [
            ES.el('span', { class: 'n', text: i === idx ? '▶' : String(i + 1).padStart(2, '0') }),
            ES.el('span', { class: 't', text: t.title }),
            ES.el('span', { class: 'dur', text: fmt(t.dur) }),
          ]);
          row.addEventListener('click', function () { select(i); });
          queueRows.appendChild(row);
        });
      }

      function loadTrack() {
        var t = QUEUE[idx];
        trackEl.textContent = t.title;
        artistEl.textContent = t.artist + ' · ' + t.genre;
        artTitle.textContent = t.title.toUpperCase();
        durTime.textContent = fmt(t.dur);
        loadQueue();
      }

      function tick(seek) {
        var t = QUEUE[idx];
        if (!seek && playing) pos += 1;
        if (pos >= t.dur) { next(); return; }
        curTime.textContent = fmt(pos);
        fill.style.width = ((pos / t.dur) * 100).toFixed(1) + '%';
      }

      function play() { playing = true; playBtn.textContent = '⏸'; playBtn.title = 'Pause'; setEq(true); }
      function pause() { playing = false; playBtn.textContent = '▶'; playBtn.title = 'Play'; setEq(false); }
      function select(i) { idx = i; pos = 0; loadTrack(); tick(true); play(); }
      function next() { select((idx + 1) % QUEUE.length); }
      function prev() { select((idx - 1 + QUEUE.length) % QUEUE.length); }

      playBtn.addEventListener('click', function () { playing ? pause() : play(); });
      nextBtn.addEventListener('click', next);
      prevBtn.addEventListener('click', prev);

      loadTrack(); play();
      timer = setInterval(tick, 1000);
      win._musicTimer = timer;
    },
    onClose: function (win) { if (win._musicTimer) clearInterval(win._musicTimer); },
  });
  });
})();
