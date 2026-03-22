/**
 * Command Center — Real-time dashboard controller.
 * Connects via Socket.IO, renders system/pipeline/alert/activity metrics.
 */
const CC = (function () {
    "use strict";

    const MAX_FEED = 200;
    let socket = null;
    let paused = false;

    // v1.49.1 [2026-03-22] — XSS escape helper for dynamic content
    function _esc(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
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
                        <span class="feed-type scene">${_esc(m.speaker || "?")}</span>
                        <span class="feed-msg">${_esc(m.text || "")}</span>
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

    // ── C1: Live Feed Panel ────────────────────────────────
    let liveFeedTimer = null;
    let liveFeedScene = "";

    function loadLiveFeedScenes() {
        fetch("/api/live_feed")
            .then(r => r.json())
            .then(scenes => {
                const sel = $("#live-feed-scene");
                if (!sel) return;
                const prev = sel.value;
                sel.innerHTML = '<option value="">Select a scene...</option>';
                (scenes || []).forEach(s => {
                    const opt = document.createElement("option");
                    opt.value = s.name;
                    opt.textContent = s.title || s.name;
                    sel.appendChild(opt);
                });
                if (prev) sel.value = prev;
            })
            .catch(() => {});
    }

    function onLiveFeedSceneChange() {
        const sel = $("#live-feed-scene");
        liveFeedScene = sel ? sel.value : "";
        if (liveFeedTimer) clearInterval(liveFeedTimer);
        if (liveFeedScene) {
            refreshLiveFeed();
            liveFeedTimer = setInterval(refreshLiveFeed, 5000);
        } else {
            const container = $("#live-feed-messages");
            if (container) container.innerHTML = '<div class="muted">Select a scene to view live messages</div>';
        }
    }

    function refreshLiveFeed() {
        if (!liveFeedScene) return;
        fetch(`/api/live_feed/${liveFeedScene}?limit=20`)
            .then(r => r.json())
            .then(msgs => {
                const container = $("#live-feed-messages");
                if (!container) return;
                if (!msgs || msgs.length === 0) {
                    container.innerHTML = '<div class="muted">No messages yet</div>';
                    return;
                }
                container.innerHTML = msgs.map(m =>
                    `<div class="feed-item compact">
                        <span class="feed-ts">${ts(m.ts)}</span>
                        <span class="feed-type scene">${m.speaker || "?"}</span>
                        <span class="feed-msg">${m.text || ""}</span>
                    </div>`
                ).join("");
                container.scrollTop = container.scrollHeight;
            })
            .catch(() => {});
    }

    // ── C2: Scene Status Cards ──────────────────────────────
    function refreshSceneStatus() {
        fetch("/api/scene_status")
            .then(r => r.json())
            .then(cards => {
                const container = $("#scene-status-cards");
                if (!container) return;
                if (!cards || cards.length === 0) {
                    container.innerHTML = '<div class="muted">No scenes running</div>';
                    return;
                }
                container.innerHTML = cards.map(c => {
                    const heat = c.conversation_heat != null ? c.conversation_heat : "-";
                    const heatClass = heat >= 80 ? "crit" : heat >= 50 ? "warn" : "";
                    const stateEntries = Object.entries(c.game_state || {});
                    const stateStr = stateEntries.length > 0
                        ? stateEntries.map(([k, v]) => `${k}: ${v}`).join(", ")
                        : "—";
                    return `<div class="status-card">
                        <div class="status-card-header">
                            <span class="status-card-title">${c.title || c.name}</span>
                            <span class="status-dot green" title="Running"></span>
                        </div>
                        <div class="status-card-body">
                            <div class="detail-stat"><span>Port</span><span>${c.port || "?"}</span></div>
                            <div class="detail-stat"><span>Characters</span><span>👤 ${c.active_characters}</span></div>
                            <div class="detail-stat"><span>State</span><span>${stateStr}</span></div>
                            <div class="detail-stat"><span>Heat</span><span class="${heatClass}">🔥 ${heat}</span></div>
                        </div>
                    </div>`;
                }).join("");
            })
            .catch(() => {});
    }

    // ── C3: Character State Viewer ──────────────────────────
    function loadCharacterState() {
        const input = $("#char-state-input");
        const charId = input ? input.value.trim() : "";
        if (!charId) return;

        fetch(`/api/character_state/${charId}`)
            .then(r => r.json())
            .then(data => {
                const container = $("#char-state-content");
                if (!container) return;
                if (data.error) {
                    container.innerHTML = `<div class="muted">${data.error}</div>`;
                    return;
                }

                let html = '<div class="char-state-columns">';

                // Stats column
                html += '<div class="char-state-col"><h3>Stats</h3>';
                const stats = data.stats || {};
                for (const [k, v] of Object.entries(stats)) {
                    if (v != null) html += `<div class="detail-stat"><span>${k}</span><span>${v}</span></div>`;
                }
                if (data.scene) html += `<div class="detail-stat"><span>Scene</span><span>${data.scene}</span></div>`;
                html += '</div>';

                // Buffs column
                html += '<div class="char-state-col"><h3>Active Buffs</h3>';
                const buffs = data.buffs || [];
                if (buffs.length === 0) {
                    html += '<div class="muted">No active buffs</div>';
                } else {
                    buffs.forEach(b => {
                        const deltas = Object.entries(b.deltas || {}).map(([k, v]) => `${k}:${v > 0 ? "+" : ""}${v}`).join(" ");
                        html += `<div class="buff-card">
                            <span class="buff-id">${b.id}</span>
                            <span class="buff-deltas">${deltas}</span>
                            <span class="muted">${b.remaining_secs}s left</span>
                        </div>`;
                    });
                }
                html += '</div>';

                // Tags column
                html += '<div class="char-state-col"><h3>Top Tags</h3>';
                const tags = data.tags || [];
                if (tags.length === 0) {
                    html += '<div class="muted">No tags</div>';
                } else {
                    tags.forEach(t => {
                        const pct = Math.min(100, Math.round(t.strength * 100));
                        html += `<div class="tag-row">
                            <span class="tag-name">${t.tag}</span>
                            <div class="meter" style="flex:1;height:10px;"><div class="meter-fill" style="width:${pct}%"></div></div>
                            <span class="tag-strength">${t.strength}</span>
                        </div>`;
                    });
                }
                html += '</div>';

                // Relationships
                html += '<div class="char-state-col"><h3>Relationships</h3>';
                const rels = data.relationships || [];
                if (rels.length === 0) {
                    html += '<div class="muted">No relationships</div>';
                } else {
                    rels.forEach(r => {
                        html += `<div class="detail-stat"><span>→ ${r.target}</span><span>T:${r.trust} A:${r.attraction}</span></div>`;
                    });
                }
                html += '</div>';

                html += '</div>';
                container.innerHTML = html;
            })
            .catch(() => {});
    }

    // ── C4: Scene Control Panel ────────────────────────────
    let scControlScene = "";
    let scControlChars = [];

    function loadSceneControlScenes() {
        fetch("/api/live_feed")
            .then(r => r.json())
            .then(scenes => {
                const sel = $("#sc-scene-select");
                const dest = $("#sc-xfer-dest");
                if (!sel) return;
                const prev = sel.value;
                sel.innerHTML = '<option value="">Select a scene...</option>';
                if (dest) dest.innerHTML = '<option value="">Destination...</option>';
                (scenes || []).forEach(s => {
                    const opt = document.createElement("option");
                    opt.value = s.name;
                    opt.textContent = s.title || s.name;
                    sel.appendChild(opt);
                    if (dest) {
                        const opt2 = opt.cloneNode(true);
                        dest.appendChild(opt2);
                    }
                });
                if (prev) sel.value = prev;
            })
            .catch(() => {});
    }

    function onSceneControlSceneChange() {
        const sel = $("#sc-scene-select");
        scControlScene = sel ? sel.value : "";
        if (scControlScene) {
            loadSceneControlCharacters();
        } else {
            scControlChars = [];
            updateSceneControlCharDropdowns([]);
            const container = $("#sc-characters");
            if (container) container.innerHTML = '<div class="muted">Select a scene to view characters</div>';
            setText("sc-char-count", "");
        }
    }

    function loadSceneControlCharacters() {
        if (!scControlScene) return;
        fetch(`/api/scene_control/characters/${scControlScene}`)
            .then(r => r.json())
            .then(chars => {
                scControlChars = chars || [];
                updateSceneControlCharDropdowns(scControlChars);
                renderSceneControlCharacters(scControlChars);
                setText("sc-char-count", `${scControlChars.length} character(s)`);
            })
            .catch(() => {});
    }

    function updateSceneControlCharDropdowns(chars) {
        ["#sc-dir-char", "#sc-xfer-char"].forEach(selId => {
            const sel = $(selId);
            if (!sel) return;
            sel.innerHTML = '<option value="">Character...</option>';
            chars.forEach(c => {
                const opt = document.createElement("option");
                opt.value = c.id;
                opt.textContent = c.name || c.id;
                sel.appendChild(opt);
            });
        });
    }

    function renderSceneControlCharacters(chars) {
        const container = $("#sc-characters");
        if (!container) return;
        if (!chars || chars.length === 0) {
            container.innerHTML = '<div class="muted">No characters in this scene</div>';
            return;
        }
        container.innerHTML = chars.map(c => {
            const mood = c.mood || "neutral";
            const energy = c.energy != null ? c.energy : "?";
            return `<div class="sc-char-card">
                <div class="sc-char-name">${c.name || c.id}</div>
                <div class="sc-char-stats">
                    <span>😊 ${mood}</span>
                    <span>⚡ ${energy}</span>
                    ${c.arousal != null ? `<span>💗 ${c.arousal}</span>` : ""}
                    ${c.inhibition != null ? `<span>🛡 ${c.inhibition}</span>` : ""}
                </div>
            </div>`;
        }).join("");
    }

    function sendDirective() {
        if (!scControlScene) { addFeedItem("alert", "Select a scene first"); return; }
        const charSel = $("#sc-dir-char");
        const charId = charSel ? charSel.value : "";
        const text = ($("#sc-dir-text") || {}).value || "";
        const turns = parseInt(($("#sc-dir-turns") || {}).value) || 3;

        if (!charId || !text) { addFeedItem("alert", "Character and directive text required"); return; }

        fetch("/api/scene_control/directive", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ scene_id: scControlScene, character_id: charId, directive: text, turns }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                addFeedItem("alert", `Directive failed: ${data.error}`);
            } else {
                addFeedItem("system", `Directive → ${charId} in ${scControlScene} (${turns} turns)`);
                const input = $("#sc-dir-text");
                if (input) input.value = "";
            }
        })
        .catch(e => addFeedItem("alert", `Directive error: ${e.message}`));
    }

    function sendBroadcast() {
        if (!scControlScene) { addFeedItem("alert", "Select a scene first"); return; }
        const msg = ($("#sc-bcast-msg") || {}).value || "";
        const sender = ($("#sc-bcast-sender") || {}).value || "system";

        if (!msg) { addFeedItem("alert", "Broadcast message required"); return; }

        fetch("/api/scene_control/broadcast", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ scene_id: scControlScene, message: msg, sender }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                addFeedItem("alert", `Broadcast failed: ${data.error}`);
            } else {
                addFeedItem("system", `📢 Broadcast to ${scControlScene}: ${msg.substring(0, 60)}`);
                const input = $("#sc-bcast-msg");
                if (input) input.value = "";
            }
        })
        .catch(e => addFeedItem("alert", `Broadcast error: ${e.message}`));
    }

    function sendTransfer() {
        if (!scControlScene) { addFeedItem("alert", "Select a scene first"); return; }
        const charSel = $("#sc-xfer-char");
        const destSel = $("#sc-xfer-dest");
        const charId = charSel ? charSel.value : "";
        const dest = destSel ? destSel.value : "";

        if (!charId || !dest) { addFeedItem("alert", "Character and destination required"); return; }
        if (dest === scControlScene) { addFeedItem("alert", "Destination must differ from source"); return; }

        fetch("/api/scene_control/transfer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ character_id: charId, from_scene: scControlScene, to_scene: dest }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                addFeedItem("alert", `Transfer failed: ${data.error}`);
            } else {
                addFeedItem("system", `🔄 Transferred ${charId}: ${scControlScene} → ${dest}`);
                setTimeout(loadSceneControlCharacters, 1000);
            }
        })
        .catch(e => addFeedItem("alert", `Transfer error: ${e.message}`));
    }

    // ── C5: System Metrics ──────────────────────────────────
    function refreshSystemMetrics() {
        fetch("/api/system_metrics")
            .then(r => r.json())
            .then(data => {
                const container = $("#sys-metrics-content");
                if (!container) return;

                const fw = data.framework || {};
                const totals = data.totals || {};
                const mem = data.memory || {};

                let html = '<div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">';
                html += `<div class="stat-card"><div class="stat-value">${fw.ready ? "✓" : "✗"}</div><div class="stat-label">Framework</div></div>`;
                html += `<div class="stat-card"><div class="stat-value">${totals.scenes || 0}</div><div class="stat-label">Scenes</div></div>`;
                html += `<div class="stat-card"><div class="stat-value">${totals.characters || 0}</div><div class="stat-label">Characters</div></div>`;
                html += `<div class="stat-card"><div class="stat-value">${totals.events || 0}</div><div class="stat-label">Events</div></div>`;
                html += `<div class="stat-card"><div class="stat-value">${mem.rss_mb || "?"}</div><div class="stat-label">RSS (MB)</div></div>`;
                html += `<div class="stat-card"><div class="stat-value">${fw.active_timers || 0}</div><div class="stat-label">Timers</div></div>`;
                html += '</div>';

                if (fw.scenes && fw.scenes.length > 0) {
                    html += '<div style="margin-top:8px;font-size:11px;color:var(--cc-muted);">Scenes: ' + fw.scenes.join(", ") + '</div>';
                }

                container.innerHTML = html;
            })
            .catch(() => {});
    }

    // ── C6: AI Training Pipeline ────────────────────────────
    function refreshTrainingData() {
        fetch("/api/training/jobs")
            .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(jobs => renderFinetuneJobs(jobs))
            .catch(() => {
                const tbody = $("#finetune-jobs-body");
                if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="muted" style="padding:6px;">Failed to load jobs</td></tr>';
            });
        refreshLeaderboard();
        loadModelRegistry();
    }

    function renderFinetuneJobs(jobs) {
        const tbody = $("#finetune-jobs-body");
        if (!tbody) return;
        if (!Array.isArray(jobs) || jobs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="muted" style="padding:6px;">No jobs found</td></tr>';
            return;
        }
        tbody.innerHTML = jobs.map(j => {
            const jobId = (j.job_id || j.id || "").substring(0, 8);
            const status = j.status || "unknown";
            const bgColor = status === "running" ? "var(--cc-green,#4caf50)"
                : status === "failed" || status === "error" ? "var(--cc-red,#f44336)"
                : status === "done" || status === "complete" ? "var(--cc-green,#4caf50)"
                : "var(--cc-yellow,#ffb300)";
            const progress = j.progress != null ? `${Math.round(j.progress)}%` : "--";
            const created = j.created_at
                ? new Date(j.created_at * 1000).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })
                : "--";
            return `<tr style="border-bottom:1px solid var(--cc-border,#2a2a2a);">
                <td style="padding:4px 6px;font-family:monospace;font-size:11px;" title="${j.job_id || j.id || ""}">${jobId}</td>
                <td style="padding:4px 6px;">${j.model_type || j.type || "--"}</td>
                <td style="padding:4px 6px;"><span style="background:${bgColor};color:#000;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:bold;">${status}</span></td>
                <td style="padding:4px 6px;">${progress}</td>
                <td style="padding:4px 6px;" class="muted">${created}</td>
            </tr>`;
        }).join("");
    }

    function refreshLeaderboard() {
        fetch("/api/training/leaderboard")
            .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(rows => renderLeaderboard(rows))
            .catch(() => {
                const tbody = $("#leaderboard-body");
                if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="muted" style="padding:6px;">Failed to load leaderboard</td></tr>';
            });
    }

    function renderLeaderboard(rows) {
        const tbody = $("#leaderboard-body");
        if (!tbody) return;
        if (!Array.isArray(rows) || rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="muted" style="padding:6px;">No benchmark data</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map(r => {
            const score = r.best_score != null ? r.best_score : null;
            let scoreHtml = "--";
            if (score != null) {
                const pct = Math.round(score * 100);
                const color = score > 0.8 ? "var(--cc-green,#4caf50)"
                    : score > 0.6 ? "var(--cc-yellow,#ffb300)"
                    : "var(--cc-red,#f44336)";
                scoreHtml = `<span style="background:${color};color:#000;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:bold;">${pct}%</span>`;
            }
            const modelId = (r.model_id || "").substring(0, 12);
            return `<tr style="border-bottom:1px solid var(--cc-border,#2a2a2a);">
                <td style="padding:4px 6px;">${r.model_type || "--"}</td>
                <td style="padding:4px 6px;">${scoreHtml}</td>
                <td style="padding:4px 6px;font-family:monospace;font-size:11px;" title="${r.model_id || ""}">${modelId}</td>
                <td style="padding:4px 6px;">${r.status || "--"}</td>
            </tr>`;
        }).join("");
    }

    function loadModelRegistry() {
        fetch("/api/training/model-registry")
            .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(models => renderActiveModels(models))
            .catch(() => {
                const container = $("#active-models-list");
                if (container) container.innerHTML = '<div class="muted">Failed to load model registry</div>';
            });
    }

    function renderActiveModels(models) {
        const container = $("#active-models-list");
        if (!container) return;
        const entries = Array.isArray(models)
            ? models
            : Object.entries(models || {}).map(([k, v]) => ({
                model_type: k,
                adapter_path: typeof v === "string" ? v : (v.adapter_path || ""),
              }));
        if (entries.length === 0) {
            container.innerHTML = '<div class="muted">No active fine-tuned models</div>';
            return;
        }
        container.innerHTML = entries.map(m => {
            const adapterFile = (m.adapter_path || "--").replace(/\\/g, "/").split("/").pop();
            return `<div class="detail-stat">
                <span>${m.model_type || m.type || "--"}</span>
                <span class="muted" style="font-family:monospace;font-size:10px;overflow:hidden;text-overflow:ellipsis;max-width:140px;" title="${m.adapter_path || ""}">${adapterFile}</span>
            </div>`;
        }).join("");
    }

    function runNextFinetuneJob() {
        fetch("/api/training/jobs/run-next", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
        })
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(data => {
            addFeedItem("system", `Training job started: ${data.job_id || data.id || "?"}`);
            setTimeout(refreshTrainingData, 2000);
        })
        .catch(e => addFeedItem("alert", `Failed to start job: ${e.message}`));
    }

    // ── C7: Knowledge Engine ────────────────────────────────
    function refreshKnowledgeEngine() {
        fetch("/api/nexus/router-stats")
            .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(data => {
                if (!data) return;
                const saved = data.tokens_saved ?? data.total_tokens_saved;
                setText("nexus-cache-hits", data.cache_hits ?? data.tier1_hits ?? "--");
                setText("nexus-fts-hits", data.fts_hits ?? data.tier2_hits ?? "--");
                setText("nexus-nlm-answers", data.nlm_answers ?? data.tier3_hits ?? "--");
                setText("nexus-llm-fallbacks", data.llm_fallbacks ?? data.tier4_hits ?? "--");
                setText("nexus-tokens-saved", saved != null
                    ? (saved > 999 ? `${Math.round(saved / 1000)}k` : saved)
                    : "--");
            })
            .catch(() => {
                ["nexus-cache-hits", "nexus-fts-hits", "nexus-nlm-answers",
                 "nexus-llm-fallbacks", "nexus-tokens-saved"].forEach(id => setText(id, "Err"));
            });
    }

    function triggerSchedulerTask(taskId) {
        const statusEl = $(`#action-status-${taskId}`);
        if (statusEl) statusEl.textContent = "Triggering…";
        fetch("/api/scheduler/trigger", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task_id: taskId }),
        })
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(data => {
            const now = new Date().toLocaleTimeString("en-GB", { hour12: false });
            const result = data.status || data.result || "ok";
            if (statusEl) statusEl.textContent = `${now} — ${result}`;
            addFeedItem("system", `Scheduler: ${taskId} → ${result}`);
        })
        .catch(e => {
            const now = new Date().toLocaleTimeString("en-GB", { hour12: false });
            if (statusEl) statusEl.textContent = `${now} — failed`;
            addFeedItem("alert", `Scheduler trigger failed: ${taskId} — ${e.message}`);
        });
    }

    function initTraining() {
        refreshTrainingData();
        refreshKnowledgeEngine();
        setInterval(refreshTrainingData, 30000);
        setInterval(refreshKnowledgeEngine, 30000);
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

        // C1: Populate live feed scene dropdown
        loadLiveFeedScenes();
        setInterval(loadLiveFeedScenes, 15000);

        // C2: Load scene status cards
        refreshSceneStatus();
        setInterval(refreshSceneStatus, 5000);

        // C4: Scene control panel
        loadSceneControlScenes();
        setInterval(loadSceneControlScenes, 15000);

        // C5: Load system metrics
        refreshSystemMetrics();
        setInterval(refreshSystemMetrics, 10000);

        // C6/C7: AI Training + Knowledge Engine
        initTraining();
    }

    document.addEventListener("DOMContentLoaded", init);

    return {
        togglePause, clearFeed, exportTraining,
        selectScene, showAllScenes, prevScene, nextScene,
        viewCharacter, viewConversations, injectEvent,
        onLiveFeedSceneChange, refreshSceneStatus,
        loadCharacterState, refreshSystemMetrics,
        onSceneControlSceneChange, sendDirective,
        sendBroadcast, sendTransfer,
        refreshTrainingData, refreshLeaderboard, loadModelRegistry,
        runNextFinetuneJob, refreshKnowledgeEngine, triggerSchedulerTask,
    };
})();
