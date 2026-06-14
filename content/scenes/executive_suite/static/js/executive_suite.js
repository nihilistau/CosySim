/* Executive Suite — placeholder boot client.
   v1.62.0 [2026-06-15] — Initial scaffold (ES-T1). Connects Socket.IO and
   logs the connection; the full OS desktop client is built in later tasks. */
(function () {
  "use strict";

  const statusEl = document.getElementById("es-boot-status");

  function setStatus(text) {
    if (statusEl) {
      statusEl.textContent = text;
    }
  }

  // socket.io is loaded by neon_base.html before this script.
  if (typeof io !== "function") {
    console.warn("[executive_suite] Socket.IO not available");
    return;
  }

  const socket = io();

  socket.on("connect", function () {
    console.log("[executive_suite] connected", socket.id);
    setStatus("online — awaiting desktop");
  });

  socket.on("state_update", function (state) {
    console.log("[executive_suite] state_update", state);
  });

  socket.on("disconnect", function () {
    console.log("[executive_suite] disconnected");
    setStatus("reconnecting…");
  });
})();
