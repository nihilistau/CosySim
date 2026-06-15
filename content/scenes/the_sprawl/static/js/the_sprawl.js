/**
 * the_sprawl.js — THE SPRAWL boot script (B-T1 scaffold).
 * =======================================================
 * v1.63.0 [2026-06-15] — Initial scaffold (B-T1). Connects to the scene over
 * Socket.IO, logs the link, and paints the live readouts (status / build /
 * city time / link) from `state_update`. The live-map renderer (territory,
 * NPCs, the player's avatar) lands in later v1.63 tasks.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  function applyState(state) {
    if (!state) return;
    setText("sprawl-r-status", state.status || "—");
    setText("sprawl-r-version", state.version || "—");
    const clock = state.clock || {};
    setText("sprawl-r-clock", clock.display || "—");
    setText("sprawl-status", "booting…");
  }

  function setLink(text, cls) {
    const el = $("sprawl-r-link");
    if (!el) return;
    el.textContent = text;
    el.classList.remove("is-live", "is-down");
    if (cls) el.classList.add(cls);
  }

  function init() {
    if (typeof io !== "function") {
      console.warn("[the_sprawl] Socket.IO client unavailable");
      setLink("offline", "is-down");
      return;
    }

    const socket = io();

    socket.on("connect", () => {
      console.log("[the_sprawl] socket connected");
      setLink("online", "is-live");
      socket.emit("request_state");
    });

    socket.on("disconnect", () => {
      console.log("[the_sprawl] socket disconnected");
      setLink("reconnecting…", "is-down");
    });

    socket.on("state_update", (state) => {
      console.log("[the_sprawl] state_update", state);
      applyState(state);
    });

    // Seed from the REST stub so readouts paint even before the first event.
    fetch("/api/state")
      .then((r) => r.json())
      .then(applyState)
      .catch((err) => console.warn("[the_sprawl] /api/state fetch failed", err));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
