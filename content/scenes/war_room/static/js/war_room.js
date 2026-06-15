/**
 * war_room.js — THE WAR ROOM faction command center (C-T1 scaffold).
 * =================================================================
 * v1.63.0 [2026-06-16] — Bootable placeholder (C-T1). Connects the shared
 * Socket.IO client, logs the scene state and reflects link status on the
 * "booting…" page. The live command-center renderer (faction select, crew
 * orders, territory ops) replaces this in later v1.63 tasks.
 *
 * Data sources:
 *   - GET /api/state            → {scene, display_name, status, ...} (stub)
 *   - Socket.IO: `state_update` (scene identity / clock for the boot page)
 *
 * Defensive throughout: missing data / no Socket.IO degrades gracefully and
 * never throws — the goal is 0 uncaught console errors.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  function setText(id, value) {
    var el = $(id);
    if (el) el.textContent = value;
  }

  function setLink(text, cls) {
    var el = $('war-link');
    if (!el) return;
    el.textContent = text;
    el.classList.remove('is-live', 'is-down');
    if (cls) el.classList.add(cls);
  }

  /** Reflect a scene-state stub on the boot page. */
  function applyState(state) {
    if (!state) return;
    console.log('[war_room] state', state);
    if (state.status) setText('war-status', state.status);
  }

  function seedFromRest() {
    fetch('/api/state')
      .then(function (r) { return r.json(); })
      .then(applyState)
      .catch(function (err) {
        console.warn('[war_room] /api/state fetch failed', err);
      });
  }

  function init() {
    seedFromRest();

    if (typeof io !== 'function') {
      console.warn('[war_room] Socket.IO client unavailable');
      setLink('offline', 'is-down');
      return;
    }

    var socket = io();

    socket.on('connect', function () {
      console.log('[war_room] socket connected');
      setLink('online', 'is-live');
    });

    socket.on('disconnect', function () {
      console.log('[war_room] socket disconnected');
      setLink('reconnecting…', 'is-down');
    });

    socket.on('state_update', function (state) {
      applyState(state);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
