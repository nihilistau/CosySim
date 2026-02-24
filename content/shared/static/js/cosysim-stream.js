/**
 * CosySim Pipeline Stream Consumer
 * =================================
 * Socket.IO-based consumer for VirtualPipeline streaming events.
 * Import via: <script src="/shared/static/js/cosysim-stream.js"></script>
 * Requires: cosysim-core.js, socket.io client
 *
 * Provides:
 *   - CosySim.PipelineStream(socket, opts) — attach to a socket for pipeline events
 *     Events consumed: pipeline_start, pipeline_delta, pipeline_watcher,
 *                      pipeline_prewarm, pipeline_kill, pipeline_complete
 *
 * Usage:
 *   const stream = CosySim.PipelineStream(socket, {
 *       onDelta: (token) => appendToChat(token),
 *       onWatcher: (analysis) => showWatcherStatus(analysis),
 *       onKill: (info) => showRetryIndicator(),
 *       onPrewarm: (tool) => showToolSpinner(tool),
 *       onComplete: (result) => finalizeMessage(result),
 *       typingEl: document.getElementById('typing-indicator'),
 *   });
 */
window.CosySim = window.CosySim || {};

(function (CS) {
    "use strict";

    /**
     * Attach pipeline event listeners to a Socket.IO socket.
     * @param {object} socket - Socket.IO client instance
     * @param {object} opts - Callback options
     * @returns {object} Stream controller with detach()
     */
    CS.PipelineStream = function (socket, opts) {
        opts = opts || {};

        const state = {
            active: false,
            requestId: null,
            tokens: "",
            tokenCount: 0,
            watcherSignal: null,
            prewarming: [],
            killed: false,
            retryCount: 0,
        };

        // Typing indicator element (optional)
        const typingEl = opts.typingEl || null;

        function showTyping(show, label) {
            if (!typingEl) return;
            typingEl.style.display = show ? "block" : "none";
            if (label && typingEl.textContent !== undefined) {
                typingEl.textContent = label;
            }
        }

        // ── Event Handlers ──────────────────────────────────

        function onStart(data) {
            state.active = true;
            state.requestId = data.request_id || null;
            state.tokens = "";
            state.tokenCount = 0;
            state.watcherSignal = null;
            state.prewarming = [];
            state.killed = false;
            showTyping(true, "Generating...");
            if (opts.onStart) opts.onStart(data);
        }

        function onDelta(data) {
            if (!state.active) return;
            const token = data.token || data.content || "";
            state.tokens += token;
            state.tokenCount++;
            if (opts.onDelta) opts.onDelta(token, state);
        }

        function onWatcher(data) {
            if (!state.active) return;
            state.watcherSignal = data.signal || "continue";
            const label = data.signal === "continue"
                ? `Generating... (${state.tokenCount} tokens)`
                : `Watcher: ${data.signal}`;
            showTyping(true, label);
            if (opts.onWatcher) opts.onWatcher(data, state);
        }

        function onPrewarm(data) {
            if (!state.active) return;
            const tool = data.tool || data.intent || "tool";
            state.prewarming.push(tool);
            showTyping(true, `Pre-warming: ${tool}...`);
            if (opts.onPrewarm) opts.onPrewarm(data, state);
        }

        function onKill(data) {
            if (!state.active) return;
            state.killed = true;
            state.retryCount = (data.retry_count || 0) + 1;
            showTyping(true, `Retrying (${state.retryCount})...`);
            state.tokens = "";
            state.tokenCount = 0;
            if (opts.onKill) opts.onKill(data, state);
        }

        function onComplete(data) {
            state.active = false;
            showTyping(false);
            if (opts.onComplete) opts.onComplete(data, state);
        }

        // ── Attach Listeners ────────────────────────────────

        socket.on("pipeline_start", onStart);
        socket.on("pipeline_delta", onDelta);
        socket.on("pipeline_watcher", onWatcher);
        socket.on("pipeline_prewarm", onPrewarm);
        socket.on("pipeline_kill", onKill);
        socket.on("pipeline_complete", onComplete);

        // ── Controller ──────────────────────────────────────

        return {
            getState: () => ({ ...state }),

            detach: function () {
                socket.off("pipeline_start", onStart);
                socket.off("pipeline_delta", onDelta);
                socket.off("pipeline_watcher", onWatcher);
                socket.off("pipeline_prewarm", onPrewarm);
                socket.off("pipeline_kill", onKill);
                socket.off("pipeline_complete", onComplete);
            },
        };
    };

})(window.CosySim);
