/**
 * CosySim Core Utilities
 * ======================
 * Shared JavaScript utilities for all CosySim scenes.
 * Import via: <script src="/shared/static/js/cosysim-core.js"></script>
 *
 * Provides:
 *   - CosySim.fetch(url, opts)  — fetch wrapper with error handling
 *   - CosySim.post(url, body)   — POST JSON shorthand
 *   - CosySim.socket(opts)      — Socket.IO wrapper with reconnection
 *   - CosySim.toast(msg, type)  — toast notification system
 *   - CosySim.$(sel)            — querySelector shorthand
 *   - CosySim.$$(sel)           — querySelectorAll shorthand
 *   - CosySim.el(tag, attrs)    — create element helper
 *   - CosySim.fmt(n, d)         — number formatting
 *   - CosySim.fmtMs(ms)         — millisecond formatting
 *   - CosySim.debounce(fn, ms)  — debounce utility
 *   - CosySim.throttle(fn, ms)  — throttle utility
 */
window.CosySim = window.CosySim || {};

(function (CS) {
    "use strict";

    // ── DOM Helpers ──────────────────────────────────────────
    CS.$ = (sel, ctx) => (ctx || document).querySelector(sel);
    CS.$$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));

    CS.el = function (tag, attrs, children) {
        const el = document.createElement(tag);
        if (attrs) {
            for (const [k, v] of Object.entries(attrs)) {
                if (k === "className") el.className = v;
                else if (k === "textContent") el.textContent = v;
                else if (k === "innerHTML") el.innerHTML = v;
                else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
                else el.setAttribute(k, v);
            }
        }
        if (children) {
            for (const child of Array.isArray(children) ? children : [children]) {
                if (typeof child === "string") el.appendChild(document.createTextNode(child));
                else if (child) el.appendChild(child);
            }
        }
        return el;
    };

    // ── Formatting ──────────────────────────────────────────
    CS.fmt = function (n, decimals) {
        if (n == null || isNaN(n)) return "--";
        return Number(n).toFixed(decimals != null ? decimals : 1);
    };

    CS.fmtMs = function (ms) {
        if (ms == null || isNaN(ms)) return "--";
        if (ms < 1000) return Math.round(ms) + "ms";
        return (ms / 1000).toFixed(1) + "s";
    };

    CS.ts = function (epoch) {
        if (!epoch) return "--:--:--";
        const d = new Date(typeof epoch === "number" && epoch < 1e12 ? epoch * 1000 : epoch);
        return d.toLocaleTimeString("en-GB", { hour12: false });
    };

    // ── Fetch Helpers ───────────────────────────────────────
    CS.fetch = async function (url, opts) {
        try {
            const resp = await fetch(url, opts);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            return await resp.json();
        } catch (err) {
            console.error(`[CosySim] Fetch error: ${url}`, err);
            throw err;
        }
    };

    CS.post = function (url, body) {
        return CS.fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
    };

    CS.get = function (url, params) {
        if (params) {
            const qs = new URLSearchParams(params).toString();
            url = url + (url.includes("?") ? "&" : "?") + qs;
        }
        return CS.fetch(url);
    };

    // ── Socket.IO Wrapper ───────────────────────────────────
    CS.socket = function (opts) {
        opts = opts || {};
        const url = opts.url || undefined;
        const transports = opts.transports || ["websocket", "polling"];

        if (typeof io === "undefined") {
            console.warn("[CosySim] Socket.IO client not loaded");
            return null;
        }

        const sock = io(url, {
            transports: transports,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            reconnectionAttempts: Infinity,
        });

        sock.on("connect", () => {
            console.log("[CosySim] Socket connected:", sock.id);
            if (opts.onConnect) opts.onConnect(sock);
        });

        sock.on("disconnect", (reason) => {
            console.log("[CosySim] Socket disconnected:", reason);
            if (opts.onDisconnect) opts.onDisconnect(reason);
        });

        sock.on("connect_error", (err) => {
            console.warn("[CosySim] Socket error:", err.message);
            if (opts.onError) opts.onError(err);
        });

        return sock;
    };

    // ── Toast Notifications ─────────────────────────────────
    let _toastContainer = null;

    function _ensureToastContainer() {
        if (_toastContainer) return _toastContainer;
        _toastContainer = CS.el("div", {
            id: "cosysim-toasts",
            className: "cosysim-toast-container",
        });
        // Inject minimal styles if not already present
        if (!document.getElementById("cosysim-toast-css")) {
            const style = CS.el("style", { id: "cosysim-toast-css" });
            style.textContent = `
                .cosysim-toast-container {
                    position: fixed; top: 16px; right: 16px; z-index: 99999;
                    display: flex; flex-direction: column; gap: 8px;
                    pointer-events: none;
                }
                .cosysim-toast {
                    padding: 10px 16px; border-radius: 6px;
                    font-family: -apple-system, system-ui, sans-serif;
                    font-size: 13px; line-height: 1.4;
                    color: #fff; pointer-events: auto;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    animation: cosysim-toast-in 0.3s ease;
                    max-width: 360px; word-break: break-word;
                }
                .cosysim-toast.info { background: #2563eb; }
                .cosysim-toast.success { background: #16a34a; }
                .cosysim-toast.warn { background: #d97706; }
                .cosysim-toast.error { background: #dc2626; }
                @keyframes cosysim-toast-in {
                    from { opacity: 0; transform: translateX(40px); }
                    to { opacity: 1; transform: translateX(0); }
                }
            `;
            document.head.appendChild(style);
        }
        document.body.appendChild(_toastContainer);
        return _toastContainer;
    }

    CS.toast = function (msg, type, duration) {
        type = type || "info";
        duration = duration || 4000;
        const container = _ensureToastContainer();
        const toast = CS.el("div", { className: "cosysim-toast " + type, textContent: msg });
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transition = "opacity 0.3s";
            setTimeout(() => toast.remove(), 300);
        }, duration);
    };

    // ── Utility Functions ───────────────────────────────────
    CS.debounce = function (fn, ms) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    };

    CS.throttle = function (fn, ms) {
        let last = 0;
        return function (...args) {
            const now = Date.now();
            if (now - last >= ms) {
                last = now;
                fn.apply(this, args);
            }
        };
    };

    // ── Version ─────────────────────────────────────────────
    CS.version = "1.0.0";

})(window.CosySim);
