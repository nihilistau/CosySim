/**
 * control_panel.js — CosySim Control Panel
 * Handles the right-hand panel: Status, Character, Settings, Terminal tabs.
 * Loaded AFTER phone.js so `socket` global is available.
 */

// ════════════════════════════════════════════════════════════
//  0.  Init
// ════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    initControlPanel();
});

function initControlPanel() {
    buildMoodGrid();
    loadSettings();
    loadLLMModels();
    loadComfyModels();

    // start polling status every 3 s
    pollStatus();
    setInterval(pollStatus, 3000);

    // start log polling every 2 s
    startLogPoll();

    // socket events forwarded from phone.js
    // phone.js fires updateConnectionStatus(bool) — we patch it to also update CP
    _patchConnectionStatus();
    _patchSocketEvents();
}

// ════════════════════════════════════════════════════════════
//  1.  Tab switching
// ════════════════════════════════════════════════════════════
const CP_TABS = ['status', 'character', 'settings', 'terminal'];

function switchCpTab(name) {
    CP_TABS.forEach(t => {
        document.getElementById('cpTab-' + t).classList.toggle('active', t === name);
        const content = document.getElementById('cpContent-' + t);
        if (content) content.classList.toggle('active', t === name);
    });
    // activate terminal log poll if terminal opened
    if (name === 'terminal') startLogPoll();
}

// ════════════════════════════════════════════════════════════
//  2.  Connection status (connection dot in header)
// ════════════════════════════════════════════════════════════
function _patchConnectionStatus() {
    // patch the existing phone.js function
    const origFn = window.updateConnectionStatus;
    window.updateConnectionStatus = function(connected) {
        if (origFn) origFn(connected);
        const dot   = document.getElementById('cpConnDot');
        const label = document.getElementById('cpConnLabel');
        if (dot)   dot.classList.toggle('ok', connected);
        if (label) label.textContent = connected ? 'Connected' : 'Disconnected';
    };
}

function _patchSocketEvents() {
    // Wait for socket to be created by phone.js
    const tryPatch = () => {
        if (!window.socket) { setTimeout(tryPatch, 200); return; }
        window.socket.on('active_request_start', () => setRequestActive(true));
        window.socket.on('active_request_end',   () => setRequestActive(false));
    };
    setTimeout(tryPatch, 500);
}

// ════════════════════════════════════════════════════════════
//  3.  Status tab: service polling & model selectors
// ════════════════════════════════════════════════════════════
async function pollStatus() {
    try {
        const r = await fetch('/api/status');
        if (!r.ok) return;
        const d = await r.json();

        // LLM
        const llmDot = document.getElementById('llmDot');
        const llmLabel = document.getElementById('llmModelLabel');
        if (llmDot) {
            llmDot.className = 'svc-dot ' + (d.llm.ok ? 'ok' : 'err');
        }
        if (llmLabel) llmLabel.textContent = d.llm.model || '—';

        // ComfyUI
        const comfyDot = document.getElementById('comfyDot');
        const comfyLabel = document.getElementById('comfyModelLabel');
        const comfyBar  = document.getElementById('comfyProgress');
        if (comfyDot) comfyDot.className = 'svc-dot ' + (d.comfyui.ok ? 'ok' : 'err');
        if (comfyLabel) {
            const sel = document.getElementById('comfyModelSelect');
            comfyLabel.textContent = (sel && sel.value) ? sel.value.split('/').pop() : (d.comfyui.ok ? 'online' : '—');
        }
        if (comfyBar) comfyBar.style.width = (d.comfyui.progress || 0) + '%';

        // Active request state (HTTP fallback – socket events preferred)
        if (!d.active_request) setRequestActive(false);
    } catch (_) { /* silently ignore */ }
}

async function loadLLMModels() {
    try {
        const r = await fetch('/api/llm/models');
        if (!r.ok) return;
        const d = await r.json();
        const sel = document.getElementById('llmModelSelect');
        if (!sel) return;
        sel.innerHTML = '';
        (d.models || []).forEach(m => {
            const opt = document.createElement('option');
            opt.value = m; opt.textContent = m;
            if (m === d.current) opt.selected = true;
            sel.appendChild(opt);
        });
        if (!d.models.length) {
            sel.innerHTML = '<option value="">No models found</option>';
        }
    } catch (e) {
        console.warn('loadLLMModels:', e);
    }
}

async function setLLMModel(model) {
    if (!model) return;
    try {
        await fetch('/api/llm/set_model', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model})
        });
        document.getElementById('llmModelLabel').textContent = model;
    } catch (e) { console.warn('setLLMModel:', e); }
}

async function loadComfyModels() {
    try {
        const r = await fetch('/api/comfyui/models');
        if (!r.ok) return;
        const d = await r.json();
        const sel = document.getElementById('comfyModelSelect');
        if (!sel) return;
        sel.innerHTML = '';
        (d.models || []).forEach(m => {
            const opt = document.createElement('option');
            opt.value = m; opt.textContent = m.split('/').pop();
            if (m === d.current) opt.selected = true;
            sel.appendChild(opt);
        });
        if (!d.models.length) {
            sel.innerHTML = '<option value="">No models found</option>';
        }
    } catch (e) { console.warn('loadComfyModels:', e); }
}

async function setComfyModel(model) {
    if (!model) return;
    try {
        await fetch('/api/comfyui/set_model', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model})
        });
    } catch (e) { console.warn('setComfyModel:', e); }
}

// active request indicator
function setRequestActive(active) {
    const spinner  = document.getElementById('reqSpinner');
    const label    = document.getElementById('reqLabel');
    const cancelBtn = document.getElementById('reqCancelBtn');
    if (spinner)  spinner.style.display  = active ? '' : 'none';
    if (label)    label.textContent      = active ? 'Request in progress…' : 'Idle';
    if (cancelBtn) cancelBtn.style.display = active ? '' : 'none';
}

async function cancelRequest() {
    try {
        await fetch('/api/request/cancel', {method: 'POST'});
        setRequestActive(false);
        appendLog({level:'WARNING', ts:_ts(), message:'Request cancel signal sent'});
    } catch (e) { console.warn('cancelRequest:', e); }
}

// ════════════════════════════════════════════════════════════
//  4.  Character tab
// ════════════════════════════════════════════════════════════
const MOODS = [
    'happy','playful','flirty','seductive','shy',
    'mysterious','loving','excited','curious',
    'melancholy','confident','anxious','angry','neutral'
];
let _selectedMood = '';

function buildMoodGrid() {
    const grid = document.getElementById('moodGrid');
    if (!grid) return;
    grid.innerHTML = '';
    MOODS.forEach(m => {
        const btn = document.createElement('button');
        btn.className = 'mood-btn';
        btn.textContent = m;
        btn.dataset.mood = m;
        btn.onclick = () => selectMood(m);
        grid.appendChild(btn);
    });
}

function selectMood(mood) {
    _selectedMood = mood;
    document.querySelectorAll('.mood-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mood === mood);
    });
}

async function reloadCharacterEditor() {
    try {
        const r = await fetch('/api/character/info');
        if (!r.ok) return;
        const c = await r.json();
        _fillCharEditor(c);
        document.getElementById('charEditorCard').style.display = '';
    } catch (e) { console.warn('reloadCharacterEditor:', e); }
}

function _fillCharEditor(c) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
    set('charName',        c.name);
    set('charAge',         c.age);
    set('charOccupation',  c.occupation);
    set('charRelLevel',    c.relationship_level);
    set('charPersonality', c.personality);
    set('charBackstory',   c.backstory);
    set('charPhysDesc',    c.physical_description);
    set('charSpeechStyle', c.speech_style);
    set('charInterests',   c.interests);
    set('charQuirks',      c.quirks);
    set('charFears',       c.fears);
    set('charSecrets',     c.secrets);
    selectMood(c.mood || '');
}

// Override phone.js selectCharacter to also populate the editor
const _origSelectCharacter = window.selectCharacter;
window.selectCharacter = async function() {
    if (_origSelectCharacter) await _origSelectCharacter();
    // small delay so active_character is set server-side
    setTimeout(reloadCharacterEditor, 600);
};

async function saveCharacterEdits() {
    const get = id => { const el = document.getElementById(id); return el ? el.value : ''; };
    const payload = {
        name:                 get('charName'),
        age:                  parseInt(get('charAge')) || undefined,
        occupation:           get('charOccupation'),
        relationship_level:   parseFloat(get('charRelLevel')) || undefined,
        mood:                 _selectedMood || undefined,
        personality:          get('charPersonality'),
        backstory:            get('charBackstory'),
        physical_description: get('charPhysDesc'),
        speech_style:         get('charSpeechStyle'),
        interests:            get('charInterests'),
        quirks:               get('charQuirks'),
        fears:                get('charFears'),
        secrets:              get('charSecrets'),
    };
    // remove undefined keys
    Object.keys(payload).forEach(k => payload[k] === undefined && delete payload[k]);
    try {
        const r = await fetch('/api/character/update', {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const d = await r.json();
        if (d.success) appendLog({level:'INFO', ts:_ts(), message:'Character saved.'});
        else appendLog({level:'ERROR', ts:_ts(), message:'Save failed: ' + (d.error||'')});
    } catch (e) { appendLog({level:'ERROR', ts:_ts(), message:'Save error: '+e}); }
}

// ════════════════════════════════════════════════════════════
//  5.  Settings tab
// ════════════════════════════════════════════════════════════
async function loadSettings() {
    try {
        const r = await fetch('/api/settings');
        if (!r.ok) return;
        const s = await r.json();
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = String(val); };
        setVal('setMsgTimeout',   s.message_timeout);
        setVal('setAudioTimeout', s.audio_timeout);
        setVal('setVideoTimeout', s.video_timeout);
        setVal('setCustomCtx',    s.custom_llm_context || '');
        setVal('setAutoFreq',     s.autonomous_frequency || 'moderate');
    } catch (e) { console.warn('loadSettings:', e); }
}

async function saveSettings() {
    const get = id => { const el = document.getElementById(id); return el ? el.value : null; };
    const payload = {
        message_timeout:      parseInt(get('setMsgTimeout'))   || 180,
        audio_timeout:        parseInt(get('setAudioTimeout'))  || 600,
        video_timeout:        parseInt(get('setVideoTimeout'))  || 600,
        custom_llm_context:   get('setCustomCtx') || '',
        autonomous_frequency: get('setAutoFreq') || 'moderate',
    };
    try {
        const r = await fetch('/api/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const d = await r.json();
        if (d.success) appendLog({level:'INFO', ts:_ts(), message:'Settings saved.'});
    } catch (e) { appendLog({level:'ERROR', ts:_ts(), message:'Settings save error: '+e}); }
}

// ════════════════════════════════════════════════════════════
//  6.  Terminal tab — log streaming
// ════════════════════════════════════════════════════════════
let _logLevel   = 'INFO';
let _lastLogId  = 0;
let _logPollTimer = null;
let _logPaused  = false;

function setLogLevel(level) {
    _logLevel  = level;
    _lastLogId = 0;  // reset so we get fresh history
}

function startLogPoll() {
    if (_logPollTimer) return;
    _logPollTimer = setInterval(fetchLogs, 2000);
}

function toggleLogPoll() {
    _logPaused = !_logPaused;
    const btn = document.getElementById('logPollBtn');
    if (btn) btn.textContent = _logPaused ? '▶ Resume' : '⏸ Pause';
}

async function fetchLogs() {
    if (_logPaused) return;
    try {
        const r = await fetch(`/api/logs?level=${_logLevel}&limit=100&since_id=${_lastLogId}`);
        if (!r.ok) return;
        const d = await r.json();
        (d.logs || []).forEach(entry => {
            appendLog(entry);
            if (entry.id > _lastLogId) _lastLogId = entry.id;
        });
    } catch (_) { /* silently ignore */ }
}

function appendLog(entry) {
    const out = document.getElementById('terminalOutput');
    if (!out) return;
    const p = document.createElement('p');
    p.className = 'log-line ' + (entry.level || 'INFO');
    p.textContent = `[${entry.ts||''}] ${entry.level||''} ${entry.logger ? entry.logger + ':' : ''} ${entry.message||''}`;
    out.appendChild(p);
    const autoScroll = document.getElementById('logAutoScroll');
    if (autoScroll && autoScroll.checked) out.scrollTop = out.scrollHeight;
    // trim old lines
    while (out.children.length > 1000) out.removeChild(out.firstChild);
}

function clearLogs() {
    const out = document.getElementById('terminalOutput');
    if (out) out.innerHTML = '<p class="log-line INFO">— log cleared —</p>';
    _lastLogId = 0;
}

// ════════════════════════════════════════════════════════════
//  7.  Terminal mini-CLI
// ════════════════════════════════════════════════════════════
const _cmdHistory = [];
let _cmdHistIdx = -1;

function handleTerminalKey(e) {
    if (e.key === 'Enter') { e.preventDefault(); runTerminalCommand(); }
    if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (_cmdHistIdx < _cmdHistory.length - 1) {
            _cmdHistIdx++;
            document.getElementById('terminalInput').value = _cmdHistory[_cmdHistory.length - 1 - _cmdHistIdx] || '';
        }
    }
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (_cmdHistIdx > 0) {
            _cmdHistIdx--;
            document.getElementById('terminalInput').value = _cmdHistory[_cmdHistory.length - 1 - _cmdHistIdx] || '';
        } else {
            _cmdHistIdx = -1;
            document.getElementById('terminalInput').value = '';
        }
    }
}

async function runTerminalCommand() {
    const input = document.getElementById('terminalInput');
    const raw   = (input.value || '').trim();
    if (!raw) return;
    input.value = '';
    _cmdHistory.push(raw);
    _cmdHistIdx = -1;
    appendLog({level:'DEBUG', ts:_ts(), message:'> ' + raw});

    const parts = raw.split(/\s+/);
    const cmd   = parts[0].toLowerCase();
    const args  = parts.slice(1);

    switch (cmd) {
        case 'help':
            _cliHelp();
            break;
        case 'status':
            await pollStatus();
            appendLog({level:'INFO', ts:_ts(), message:'Status refresh triggered.'});
            break;
        case 'char':
        case 'character':
            await _cliCharacter(args);
            break;
        case 'send':
            _cliSend(args.join(' '));
            break;
        case 'settings':
            await _cliSettings(args);
            break;
        case 'cancel':
            await cancelRequest();
            break;
        case 'clear':
            clearLogs();
            break;
        default:
            appendLog({level:'WARNING', ts:_ts(), message:'Unknown command: ' + cmd + '  (type "help" for list)'});
    }
}

function _cliHelp() {
    const cmds = [
        'help                   — show this help',
        'status                 — refresh service status',
        'char list              — list characters',
        'char set <id>          — set active character',
        'char info              — show info for active character',
        'send <message>         — send a chat message to active character',
        'settings               — show current settings',
        'settings set <key> <v> — update a setting (e.g. settings set message_timeout 120)',
        'cancel                 — cancel active LLM request',
        'clear                  — clear terminal',
    ];
    cmds.forEach(c => appendLog({level:'INFO', ts:_ts(), message:c}));
}

async function _cliCharacter(args) {
    const sub = args[0]?.toLowerCase();
    if (sub === 'list' || !sub) {
        try {
            const r = await fetch('/api/characters/list');
            const d = await r.json();
            (d.characters || []).forEach(c => {
                appendLog({level:'INFO', ts:_ts(), message:`  ${c.id} — ${c.name} (${c.source})`});
            });
        } catch (e) { appendLog({level:'ERROR', ts:_ts(), message:'list error: '+e}); }
    } else if (sub === 'set' && args[1]) {
        const charId = args[1];
        const sel = document.getElementById('characterSelect');
        if (sel) { sel.value = charId; }
        // trigger set via API
        try {
            const r = await fetch('/api/character/set', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({character_id: charId})
            });
            const d = await r.json();
            if (d.success) {
                appendLog({level:'INFO', ts:_ts(), message:'Active character: ' + d.character.name});
                // update phone.js display
                if (typeof loadFirstCharacter === 'function') loadFirstCharacter();
            } else {
                appendLog({level:'ERROR', ts:_ts(), message:'Set failed: '+(d.error||'')});
            }
        } catch (e) { appendLog({level:'ERROR', ts:_ts(), message:'set error: '+e}); }
    } else if (sub === 'info') {
        try {
            const r = await fetch('/api/character/info');
            const c = await r.json();
            if (c.error) { appendLog({level:'ERROR', ts:_ts(), message:c.error}); return; }
            appendLog({level:'INFO', ts:_ts(), message:`Name: ${c.name}, Age: ${c.age}, Mood: ${c.mood}, Rel: ${c.relationship_level}`});
        } catch (e) { appendLog({level:'ERROR', ts:_ts(), message:'info error: '+e}); }
    }
}

function _cliSend(msg) {
    if (!msg) { appendLog({level:'WARNING', ts:_ts(), message:'Usage: send <message>'}); return; }
    if (!window.socket) { appendLog({level:'ERROR', ts:_ts(), message:'Socket not connected.'}); return; }
    window.socket.emit('send_message', {message: msg});
    appendLog({level:'INFO', ts:_ts(), message:'Sent: ' + msg});
}

async function _cliSettings(args) {
    if (!args[0] || args[0] === 'show') {
        const r = await fetch('/api/settings');
        const s = await r.json();
        Object.entries(s).forEach(([k,v]) => appendLog({level:'INFO', ts:_ts(), message:`  ${k} = ${v}`}));
    } else if (args[0] === 'set' && args[1] && args[2] !== undefined) {
        const patch = {};
        patch[args[1]] = isNaN(args[2]) ? args[2] : Number(args[2]);
        await fetch('/api/settings', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
        appendLog({level:'INFO', ts:_ts(), message:`${args[1]} = ${args[2]}`});
    }
}

// tiny helper
function _ts() {
    return new Date().toTimeString().slice(0,8);
}
