/**
 * Command Center — Real-time dashboard controller.
 * Connects via Socket.IO, renders system/pipeline/alert/activity metrics.
 */
const CC = (function () {
    "use strict";

    const MAX_FEED = 200;
    let socket = null;
    let paused = false;
    let startTime = Date.now();
    let sceneData = [];          // Cached scene summaries
    let selectedScene = null;    // Currently focused scene ID
    let sceneIndex = -1;         // -1 = show all

    // ── Helpers ─────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    function fmt(n, decimals = 1) {
        if (n == null || isNaN(n)) return "--";
        return Number(n).toFixed(decimals);
    }

    function fmtMs(ms) {
        if (ms == null || isNaN(ms)) return "--";
        return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
    }

    function ts(epoch) {
        if (!epoch) return "--:--:--";
        const d = new Date(epoch * 1000);
        return d.toLocaleTimeString("en-GB", { hour12: false });
    }

    function elapsed() {
        const sec = Math.floor((Date.now() - startTime) / 1000);
        const h = String(Math.floor(sec / 3600)).padStart(2, "0");
        const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
        const s = String(sec % 60).padStart(2, "0");
        return `${h}:${m}:${s}`;
    }

    function meterClass(pct) {
        if (pct >= 90) return "crit";
        if (pct >= 75) return "warn";
        return "";
    }

    function setMeter(id, pct, suffix = "%") {
        const fill = $(`#${id}-fill`);
        const val = $(`#${id}-val`);
        if (!fill || !val) return;
        const p = Math.max(0, Math.min(100, pct || 0));
        fill.style.width = p + "%";
        fill.className = "meter-fill " + meterClass(p);
        val.textContent = fmt(p, 0) + suffix;
    }

    function setText(id, text) {
        const el = $(`#${id}`);
        if (el) el.textContent = text;
    }

    // ── System Metrics ──────────────────────────────────────
    function updateSystem(data) {
        if (!data || typeof data !== "object") return;
        const cpu = data.cpu_pct ?? data.cpu ?? 0;
        const ram = data.ram_pct ?? (data.ram && data.ram.percent) ?? 0;
        const gpu = data.gpu_vram_pct ?? (data.gpu && data.gpu.vram_pct) ?? 0;
        const temp = data.gpu_temp_c ?? (data.gpu && data.gpu.temp) ?? 0;

        setMeter("cpu", cpu);
        setMeter("ram", ram);
        setMeter("gpu", gpu);
        setMeter("temp", temp, "°C");
    }

    // ── Pipeline Metrics ────────────────────────────────────
    function updatePipeline(data) {
        if (!data || typeof data !== "object") return;
        setText("pipe-queue", data.queue_depth ?? 0);
        setText("pipe-active", data.active ?? 0);
        setText("pipe-latency", fmtMs(data.avg_latency_ms));
        setText("pipe-tps", fmt(data.avg_tps));
        setText("pipe-kills", data.total_kills ?? 0);
        setText("pipe-prewarm", data.total_prewarms ?? 0);
    }

    // ── Alert Status ────────────────────────────────────────
    function updateAlerts(statusMap) {
        if (!statusMap || typeof statusMap !== "object") return;
        const container = $("#alert-nodes");
        if (!container) return;

        container.innerHTML = "";
        let worst = "green";
        for (const [node, level] of Object.entries(statusMap)) {
            const el = document.createElement("div");
            el.className = "alert-node";
            el.innerHTML = `<span class="dot ${level}"></span><span>${node}</span>`;
            container.appendChild(el);
            if (level === "red") worst = "red";
            else if (level === "yellow" && worst !== "red") worst = "yellow";
        }

        const badge = $("#worst-alert");
        if (badge) {
            badge.className = "alert-badge " + worst;
            badge.textContent = worst === "green" ? "ALL CLEAR" : worst === "yellow" ? "WARNING" : "ALERT";
        }
        const dot = $("#ws-status");
        if (dot) dot.className = "status-dot " + (socket && socket.connected ? "green" : "red");
    }

    function updateAlertHistory(history) {
        const ul = $("#alert-history");
        if (!ul || !Array.isArray(history)) return;
        if (history.length === 0) {
            ul.innerHTML = '<li class="muted">No alerts</li>';
            return;
        }
        ul.innerHTML = history.slice(0, 10).map(a =>
            `<li><span class="dot ${a.level}" style="display:inline-block;width:8px;height:8px;border-radius:50%;vertical-align:middle;margin-right:4px;background:var(--cc-${a.level})"></span>`
            + `<strong>${a.node || ""}</strong> ${a.message || ""} <span class="muted">${ts(a.ts)}</span></li>`
        ).join("");
    }

    // ── Activity Bus ────────────────────────────────────────
    function updateActivity(data) {
        if (!data) return;
        const cur = $("#current-activities");
        const hist = $("#activity-history");

        if (cur) {
            const activities = data.current || [];
            if (activities.length === 0) {
                cur.innerHTML = '<em class="muted">Idle</em>';
            } else {
                cur.innerHTML = activities.map(a =>
                    `<span class="activity-tag">${a.kind || "?"}: ${a.label || "--"}</span>`
                ).join(" ");
            }
        }

        if (hist) {
            const items = data.history || [];
            if (items.length === 0) {
                hist.innerHTML = '<li class="muted">No recent activity</li>';
            } else {
                hist.innerHTML = items.slice(0, 15).map(h =>
                    `<li>${h.kind || "?"}: ${h.label || "--"} — <span class="muted">${fmtMs(h.elapsed_ms)}</span></li>`
                ).join("");
            }
        }
    }

    // ── Benchmarks / LLM KPIs ───────────────────────────────
    function updateBenchmarks(data) {
        if (!data) return;
        const kpis = data.llm_kpis || {};
        setText("llm-avg-tps", fmt(kpis.avg_tps));
        setText("llm-avg-ttft", fmtMs(kpis.avg_ttft_ms));
        setText("llm-p95-latency", fmtMs(kpis.p95_latency_ms));
        setText("llm-total-calls", kpis.count || 0);
    }

    // ── Training Stats ──────────────────────────────────────
    function updateTraining(data) {
        if (!data) return;
        const container = $("#training-stats");
        if (!container) return;

        const datasets = data.datasets || {};
        if (Object.keys(datasets).length === 0 && !data.total) {
            container.innerHTML = '<em class="muted">No data yet</em>';
            return;
        }

        let html = `<div class="training-row"><strong>Total candidates</strong><span>${data.total || 0}</span></div>`;
        for (const [name, info] of Object.entries(datasets)) {
            const count = typeof info === "number" ? info : (info.count || 0);
            html += `<div class="training-row"><span>${name}</span><span>${count}</span></div>`;
        }
        container.innerHTML = html;
    }

    // ── Live Feed ───────────────────────────────────────────
    function addFeedItem(type, msg) {
        if (paused) return;
        const list = $("#feed-list");
        if (!list) return;

        // Remove placeholder
        const placeholder = list.querySelector(".muted");
        if (placeholder) placeholder.remove();

        const item = document.createElement("div");
        item.className = "feed-item";
        item.innerHTML = `<span class="feed-ts">${ts(Date.now() / 1000)}</span>`
            + `<span class="feed-type ${type}">${type}</span>`
            + `<span class="feed-msg">${msg}</span>`;

        list.prepend(item);

        // Trim
        while (list.children.length > MAX_FEED) {
            list.lastChild.remove();
        }
    }

    // ── Full Dashboard State ────────────────────────────────
    function applyDashboard(data) {
        if (!data) return;
        updateSystem(data.system);
        updatePipeline(data.pipeline);
        updateAlerts(data.alerts);
        updateAlertHistory(data.alert_history);
        updateActivity(data.activity);
        updateBenchmarks(data.benchmarks);
        updateTraining(data.training);
    }

    // ── Scene Monitor ─────────────────────────────────────────
    function updateSceneCards(scenes) {
        sceneData = scenes || [];
        const container = $("#scene-cards");
        if (!container) return;

        if (sceneData.length === 0) {
            container.innerHTML = '<div class="muted">No scenes running</div>';
            return;
        }

        container.innerHTML = sceneData.map(s => {
            const phase = (s.state && s.state.phase) || (s.state && s.state.game_phase) || "-";
            const heat = s.heat != null ? s.heat : "-";
            const chars = s.character_count || 0;
            const heatClass = heat >= 80 ? "crit" : heat >= 50 ? "warn" : "";
            return `<div class="scene-card" onclick="CC.selectScene('${s.id}')">
                <div class="scene-card-title">${s.title || s.id}</div>
                <div class="scene-card-meta">
                    <span title="Port">:${s.port || "?"}</span>
                    <span title="Characters">👤 ${chars}</span>
                    <span title="Heat" class="${heatClass}">🔥 ${heat}</span>
                </div>
                <div class="scene-card-phase">${phase}</div>
            </div>`;
        }).join("");
    }

    function selectScene(sceneId) {
        selectedScene = sceneId;
        sceneIndex = sceneData.findIndex(s => s.id === sceneId);

        // Show detail panel, hide cards
        const cards = $("#panel-scenes");
        const detail = $("#panel-scene-detail");
        if (cards) cards.style.display = "none";
        if (detail) detail.style.display = "";

        setText("detail-title", sceneData[sceneIndex]?.title || sceneId);

        // Load detail info
        const s = sceneData[sceneIndex] || {};
        const info = $("#detail-info");
        if (info) {
            const state = s.state || {};
            let stateHtml = Object.entries(state).map(([k, v]) =>
                `<div class="detail-stat"><span>${k}</span><span>${v}</span></div>`
            ).join("");
            info.innerHTML = `
                <div class="detail-stat"><span>Port</span><span>${s.port || "?"}</span></div>
                <div class="detail-stat"><span>Genre</span><span>${s.genre || "?"}</span></div>
                <div class="detail-stat"><span>Characters</span><span>${s.character_count || 0}</span></div>
                <div class="detail-stat"><span>Heat</span><span>${s.heat || "-"}</span></div>
                ${stateHtml}
            `;
        }

        // Load chat feed
        fetch(`/api/scenes/${sceneId}/feed?limit=20`)
            .then(r => r.json())
            .then(msgs => {
                const list = $("#detail-feed-list");
                if (!list) return;
                if (!msgs || msgs.length === 0) {
                    list.innerHTML = '<div class="muted">No messages</div>';
                    return;
                }
                list.innerHTML = msgs.map(m =>
                    `<div class="feed-item compact">
                        <span class="feed-type scene">${m.speaker || "?"}</span>
                        <span class="feed-msg">${m.text || ""}</span>
                    </div>`
                ).join("");
            })
            .catch(() => {});

        // Load characters
        fetch(`/api/scenes/${sceneId}/characters`)
            .then(r => r.json())
            .then(chars => {
                const list = $("#detail-char-list");
                if (!list) return;
                if (!chars || chars.length === 0) {
                    list.innerHTML = '<div class="muted">No characters</div>';
                    return;
                }
                list.innerHTML = chars.map(c => `
                    <div class="char-card" onclick="CC.viewCharacter('${c.id}')">
                        <div class="char-name">${c.name || c.id}</div>
                        <div class="char-stats">
                            <span>😊 ${c.mood || "?"}</span>
                            <span>⚡ ${c.energy || "?"}</span>
                            ${c.arousal != null ? `<span>💗 ${c.arousal}</span>` : ""}
                        </div>
                    </div>
                `).join("");
            })
            .catch(() => {});
    }

    function showAllScenes() {
        selectedScene = null;
        sceneIndex = -1;
        const cards = $("#panel-scenes");
        const detail = $("#panel-scene-detail");
        if (cards) cards.style.display = "";
        if (detail) detail.style.display = "none";
        setText("scene-nav-label", "All Scenes");
    }

    function prevScene() {
        if (sceneData.length === 0) return;
        sceneIndex = (sceneIndex - 1 + sceneData.length) % sceneData.length;
        selectScene(sceneData[sceneIndex].id);
    }

    function nextScene() {
        if (sceneData.length === 0) return;
        sceneIndex = (sceneIndex + 1) % sceneData.length;
        selectScene(sceneData[sceneIndex].id);
    }

    function viewCharacter(charId) {
        fetch(`/api/characters/${charId}`)
            .then(r => r.json())
            .then(data => {
                const info = $("#detail-chars");
                if (!info) return;
                let html = `<h3>${data.name || charId}</h3>`;
                html += `<div class="char-detail">`;
                for (const [k, v] of Object.entries(data)) {
                    if (k === "id" || k === "relationships" || k === "stats" || k === "flags") continue;
                    html += `<div class="detail-stat"><span>${k}</span><span>${v}</span></div>`;
                }
                if (data.relationships) {
                    html += `<h4>Relationships</h4>`;
                    for (const r of data.relationships) {
                        html += `<div class="detail-stat"><span>→ ${r.target}</span><span>trust:${r.trust} attr:${r.attraction}</span></div>`;
                    }
                }
                html += `</div>`;
                html += `<button class="cc-btn small" onclick="CC.viewConversations('${charId}')">📜 Conversations</button>`;
                info.innerHTML = html;
            })
            .catch(() => {});
    }

    function viewConversations(charId) {
        fetch(`/api/characters/${charId}/conversations?limit=20`)
            .then(r => r.json())
            .then(convs => {
                const feed = $("#detail-feed-list");
                if (!feed) return;
                if (!convs || convs.length === 0) {
                    feed.innerHTML = '<div class="muted">No conversations</div>';
                    return;
                }
                feed.innerHTML = convs.map(c =>
                    `<div class="feed-item compact">
                        <span class="feed-type ${c.role === 'assistant' ? 'pipeline' : 'system'}">${c.role}</span>
                        <span class="feed-msg">${c.content || ""}</span>
                    </div>`
                ).join("");
            })
            .catch(() => {});
    }

    function injectEvent() {
        if (!selectedScene) return;
        const content = prompt("Enter event/directive text:");
        if (!content) return;
        const type = prompt("Type: narrative, directive, or broadcast", "narrative");
        if (!type) return;

        fetch(`/api/scenes/${selectedScene}/inject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content, type }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                addFeedItem("alert", `Inject failed: ${data.error}`);
            } else {
                addFeedItem("system", `Injected ${type} into ${selectedScene}`);
            }
        })
        .catch(e => addFeedItem("alert", `Inject error: ${e.message}`));
    }

    // ── Socket.IO ───────────────────────────────────────────
    function connect() {
        socket = io({ transports: ["websocket", "polling"] });

        socket.on("connect", () => {
            const dot = $("#ws-status");
            if (dot) dot.className = "status-dot green";
            addFeedItem("system", "Connected to Command Center");
        });

        socket.on("disconnect", () => {
            const dot = $("#ws-status");
            if (dot) dot.className = "status-dot red";
            addFeedItem("system", "Disconnected");
        });

        socket.on("dashboard_state", applyDashboard);

        socket.on("metric_system", (data) => {
            updateSystem(data);
        });

        socket.on("metric_pipeline", (data) => {
            updatePipeline(data);
            if (data && data.avg_latency_ms) {
                addFeedItem("pipeline", `Latency: ${fmtMs(data.avg_latency_ms)} | TPS: ${fmt(data.avg_tps)} | Queue: ${data.queue_depth || 0}`);
            }
        });

        socket.on("metric_alerts", (data) => {
            updateAlerts(data);
        });

        socket.on("metric_alert", (data) => {
            if (data) {
                addFeedItem("alert", `${data.node}: ${data.level} — ${data.message || ""}`);
            }
        });

        socket.on("metric_activity", (data) => {
            updateActivity(data);
        });

        socket.on("metric_request", (data) => {
            if (data) {
                addFeedItem("pipeline",
                    `${data.agent_id || "?"} → ${data.tier || "?"} | ${fmtMs(data.latency_ms)} | ${fmt(data.tps)} TPS`
                );
            }
        });

        socket.on("scene_updates", (data) => {
            if (!selectedScene) {
                updateSceneCards(data);
            } else {
                sceneData = data || [];
            }
        });
    }

    // ── Public API ──────────────────────────────────────────
    function togglePause() {
        paused = !paused;
        const btn = $("#btn-pause");
        if (btn) btn.textContent = paused ? "▶ Resume" : "⏸ Pause";
    }

    function clearFeed() {
        const list = $("#feed-list");
        if (list) list.innerHTML = '<div class="feed-item muted">Feed cleared</div>';
    }

    function exportTraining() {
        fetch("/api/training/export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ min_quality: 0.7 }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                addFeedItem("alert", `Export failed: ${data.error}`);
            } else {
                addFeedItem("system", `Exported ${data.exported} candidates`);
            }
        })
        .catch(e => addFeedItem("alert", `Export error: ${e.message}`));
    }

    // ── Init ────────────────────────────────────────────────
    function init() {
        connect();
        // Uptime counter
        setInterval(() => {
            const el = $("#uptime");
            if (el) el.textContent = elapsed();
        }, 1000);

        // Initial scene load
        fetch("/api/scenes")
            .then(r => r.json())
            .then(updateSceneCards)
            .catch(() => {});

        // Fallback: poll REST if socket is slow
        setTimeout(() => {
            fetch("/api/dashboard")
                .then(r => r.json())
                .then(applyDashboard)
                .catch(() => {});
        }, 2000);
    }

    document.addEventListener("DOMContentLoaded", init);

    return {
        togglePause, clearFeed, exportTraining,
        selectScene, showAllScenes, prevScene, nextScene,
        viewCharacter, viewConversations, injectEvent,
    };
})();
