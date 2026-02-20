// Phone UI JavaScript
let socket;
let currentCharacter = null;
let callTimer = null;
let callDuration = 0;
let selectedFile = null;
let currentPhotoUrl = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeSocket();
    loadCharacters();
});

// Socket.IO initialization
function initializeSocket() {
    socket = io();
    // Initialize voice module now that socket exists
    if (typeof initializeVoice === 'function') initializeVoice();
    
    socket.on('connect', () => {
        console.log('Connected to server');
        updateConnectionStatus(true);
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        updateConnectionStatus(false);
    });
    
    socket.on('message_received', (data) => {
        addMessageToUI(data.role, data.content, data.timestamp, data.autonomous);
        
        // Show notification badge if not on messages screen
        const messagesScreen = document.getElementById('messagesScreen');
        if (messagesScreen.style.display !== 'block' && data.role === 'assistant') {
            const badge = document.getElementById('messageBadge');
            const currentCount = parseInt(badge.textContent) || 0;
            showNotificationBadge(currentCount + 1);
        }
    });
    
    socket.on('typing', (data) => {
        showTypingIndicator(data.is_typing);
    });
    
    socket.on('call_started', (data) => {
        handleCallStarted(data);
    });
    
    socket.on('call_ended', () => {
        handleCallEnded();
    });
    
    socket.on('photo_received', (data) => {
        addPhotoMessage(data.url, data.timestamp, data.role || 'assistant');
    });
    
    socket.on('voice_message_received', (data) => {
        addVoiceMessageToChat(data);
    });
    
    socket.on('video_message_received', (data) => {
        addVideoMessageToChat(data);
    });
    
    socket.on('error', (data) => {
        console.error('Socket error:', data.message);
        alert(data.message);
    });
}

// Update connection status
function updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connectionStatus');
    if (statusEl) {
        statusEl.textContent = connected ? 'Connected' : 'Disconnected';
        statusEl.className = 'status-indicator ' + (connected ? 'connected' : 'disconnected');
    }
}

// Load available characters
async function loadCharacters() {
    try {
        const response = await fetch('/api/characters/list');
        const data = await response.json();
        
        const select = document.getElementById('characterSelect');
        select.innerHTML = '<option value="">Select a character...</option>';
        
        data.characters.forEach(char => {
            const option = document.createElement('option');
            option.value = char.id;
            option.dataset.source = char.source || 'database';
            option.textContent = `${char.name} ${char.source === 'asset' ? '🎭' : '📊'}`;
            select.appendChild(option);
        });
        
        // Auto-select first character if available
        if (data.characters.length > 0) {
            select.value = data.characters[0].id;
            selectCharacter();
        }
        
        // Also load available scenes
        loadScenes();
    } catch (error) {
        console.error('Error loading characters:', error);
    }
}

// Select character
async function selectCharacter() {
    const select = document.getElementById('characterSelect');
    const charId = select.value;
    
    if (!charId) return;
    
    const selectedOption = select.options[select.selectedIndex];
    const source = selectedOption.dataset.source || 'database';
    
    try {
        // Try asset-based loading first, fallback to database
        const endpoint = source === 'asset' ? '/api/character/load_asset' : '/api/character/set';
        
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character_id: charId })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentCharacter = data.character;
            updateCharacterUI();
            console.log('Character set:', data.character.name);
        } else if (data.error) {
            console.error('Error setting character:', data.error);
            // If asset loading failed, try database
            if (source === 'asset') {
                const fallbackResponse = await fetch('/api/character/set', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ character_id: charId })
                });
                const fallbackData = await fallbackResponse.json();
                if (fallbackData.success) {
                    currentCharacter = fallbackData.character;
                    updateCharacterUI();
                    console.log('Character set (fallback):', fallbackData.character.name);
                }
            }
        }
    } catch (error) {
        console.error('Error setting character:', error);
    }
}

// Update UI with character info
function updateCharacterUI() {
    if (!currentCharacter) return;
    
    const contactName = document.getElementById('contactName');
    if (contactName) contactName.textContent = currentCharacter.name;
    
    const callerName = document.getElementById('callerName');
    if (callerName) callerName.textContent = currentCharacter.name;
    
    const activeCallerName = document.getElementById('activeCallerName');
    if (activeCallerName) activeCallerName.textContent = currentCharacter.name;
}

// App navigation
function openApp(appName) {
    // Hide all screens
    const screens = document.querySelectorAll('.screen-view');
    screens.forEach(screen => screen.style.display = 'none');
    
    // Show selected screen
    const screenMap = {
        'messages':      'messagesScreen',
        'phone':         'phoneScreen',
        'gallery':       'galleryScreen',
        'camera':        'homeScreen',        // Placeholder
        'browser':       'homeScreen',        // Placeholder
        'videoMessages': 'videoMessagesScreen',
        'voiceMessages': 'voiceMessagesScreen',
        'settings':      'settingsScreen',
        'voiceStudio':   'voiceStudioScreen',
        'imageSettings': 'imageSettingsScreen'
    };
    
    const screenId = screenMap[appName] || 'homeScreen';
    document.getElementById(screenId).style.display = 'block';
    
    // Clear notification badge when opening messages
    if (appName === 'messages') {
        showNotificationBadge(0);
        loadMessages();
    } else if (appName === 'gallery') {
        loadGallery();
    } else if (appName === 'videoMessages') {
        loadVideoMessages();
    } else if (appName === 'voiceMessages') {
        loadVoiceMessages();
    } else if (appName === 'settings') {
        loadPhoneSettings();
    } else if (appName === 'voiceStudio') {
        vsLoadVoices();
        vsLoadToneButtons();
        vsLoadRecordings();
    } else if (appName === 'imageSettings') {
        loadImageSettings();
    }
}

function goHome() {
    const screens = document.querySelectorAll('.screen-view');
    screens.forEach(screen => screen.style.display = 'none');
    document.getElementById('homeScreen').style.display = 'block';
}

// ══════════════════════════════ Video Messages gallery ══════════════════════
async function loadVideoMessages() {
    const list = document.getElementById('videoMsgList');
    if (!list) return;
    list.innerHTML = '<div class="media-empty">Loading…</div>';

    try {
        const res  = await fetch('/api/video-messages/list?limit=50');
        const data = await res.json();

        if (!data.messages || data.messages.length === 0) {
            list.innerHTML = '<div class="media-empty">🎥<br>No video messages yet.<br>Send one from the chat!</div>';
            return;
        }

        list.innerHTML = data.messages.map(m => `
            <div class="media-card" onclick="openMediaOverlay('video', '${_escAttr(m.url)}', '${_escAttr(m.title)}')">
                <div class="media-card-thumb">🎥</div>
                <div class="media-card-info">
                    <div class="media-card-title">${_escHtml(m.title)}</div>
                    <div class="media-card-meta">${_escHtml(m.timestamp_display)}${m.mood ? '  ·  ' + _escHtml(m.mood) : ''}</div>
                </div>
                ${m.duration ? `<div class="media-card-duration">${_fmtDur(m.duration)}</div>` : ''}
            </div>
        `).join('');
    } catch (err) {
        list.innerHTML = '<div class="media-empty">⚠️ Could not load video messages.</div>';
        console.error('loadVideoMessages error:', err);
    }
}

// ══════════════════════════════ Voice Messages gallery ══════════════════════
async function loadVoiceMessages() {
    const list = document.getElementById('voiceMsgList');
    if (!list) return;
    list.innerHTML = '<div class="media-empty">Loading…</div>';

    try {
        const res  = await fetch('/api/voice-messages/list?limit=50');
        const data = await res.json();

        if (!data.messages || data.messages.length === 0) {
            list.innerHTML = '<div class="media-empty">🎤<br>No voice messages yet.<br>Send one from the chat!</div>';
            return;
        }

        list.innerHTML = data.messages.map(m => `
            <div class="media-card" onclick="openMediaOverlay('audio', '${_escAttr(m.url)}', '${_escAttr(m.title)}')">
                <div class="media-card-thumb">🎤</div>
                <div class="media-card-info">
                    <div class="media-card-title">${_escHtml(m.title)}</div>
                    <div class="media-card-meta">${_escHtml(m.timestamp_display)}${m.mood ? '  ·  ' + _escHtml(m.mood) : ''}</div>
                </div>
                ${m.duration ? `<div class="media-card-duration">${_escHtml(m.duration_display || _fmtDur(m.duration))}</div>` : ''}
            </div>
        `).join('');
    } catch (err) {
        list.innerHTML = '<div class="media-empty">⚠️ Could not load voice messages.</div>';
        console.error('loadVoiceMessages error:', err);
    }
}

// ═══════════════════════ Skype-style connecting overlay ═════════════════════
/**
 * Open the connecting animation then switch to the media player.
 * @param {'video'|'audio'} type  - which HTML media element to use
 * @param {string}          url   - media source URL
 * @param {string}          title - display title
 */
function openMediaOverlay(type, url, title) {
    const overlay       = document.getElementById('mediaOverlay');
    const connecting    = document.getElementById('connectingPhase');
    const playerWrap    = document.getElementById('mediaPlayerWrap');
    const playerTitle   = document.getElementById('mediaPlayerTitle');
    const playerVideo   = document.getElementById('mediaPlayerVideo');
    const playerAudio   = document.getElementById('mediaPlayerAudio');

    if (!overlay) return;

    // Reset state
    connecting.style.display   = 'flex';
    playerWrap.classList.remove('active');
    playerVideo.src = '';
    playerAudio.src = '';
    playerVideo.style.display = 'none';
    playerAudio.style.display = 'none';
    document.getElementById('connectingLabel').textContent = 'Connecting…';

    // Show overlay
    overlay.classList.add('active');

    // Simulate the Skype-style connecting phase (800 ms → player)
    setTimeout(() => {
        connecting.style.display = 'none';
        playerTitle.textContent  = title || '';

        if (type === 'video') {
            playerVideo.src           = url;
            playerVideo.style.display = 'block';
        } else {
            playerAudio.src           = url;
            playerAudio.style.display = 'block';
        }

        playerWrap.classList.add('active');

        // Auto-play
        const el = type === 'video' ? playerVideo : playerAudio;
        el.play().catch(() => {/* autoplay blocked — user can still press play */});
    }, 820);
}

function closeMediaOverlay() {
    const overlay     = document.getElementById('mediaOverlay');
    const playerVideo = document.getElementById('mediaPlayerVideo');
    const playerAudio = document.getElementById('mediaPlayerAudio');
    if (!overlay) return;
    overlay.classList.remove('active');
    playerVideo.pause(); playerVideo.src = '';
    playerAudio.pause(); playerAudio.src = '';
    // Reset phases for next open
    document.getElementById('connectingPhase').style.display  = 'flex';
    document.getElementById('mediaPlayerWrap').classList.remove('active');
}

// ═══════════════════════════════ Settings screen ════════════════════════════
async function loadPhoneSettings() {
    try {
        const res  = await fetch('/api/settings');
        const data = await res.json();
        const _v   = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? el.value; };
        _v('set_msg_timeout',   data.message_timeout);
        _v('set_audio_timeout', data.audio_timeout);
        _v('set_video_timeout', data.video_timeout);
        _v('set_custom_ctx',    data.custom_llm_context ?? '');
        const freq = document.getElementById('set_auto_freq');
        if (freq && data.autonomous_frequency) freq.value = data.autonomous_frequency;
    } catch (err) {
        console.error('loadPhoneSettings error:', err);
    }
}

async function savePhoneSettings() {
    const _num = id => { const el = document.getElementById(id); return el ? parseInt(el.value) : undefined; };
    const _str = id => { const el = document.getElementById(id); return el ? el.value : undefined; };
    const payload = {
        message_timeout:        _num('set_msg_timeout'),
        audio_timeout:          _num('set_audio_timeout'),
        video_timeout:          _num('set_video_timeout'),
        custom_llm_context:     _str('set_custom_ctx'),
        autonomous_frequency:   _str('set_auto_freq')
    };
    try {
        const res  = await fetch('/api/settings', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            const btn = document.querySelector('.settings-save-btn');
            if (btn) { btn.textContent = '✅ Saved!'; setTimeout(() => btn.textContent = '💾 Save Settings', 1800); }
        }
    } catch (err) {
        console.error('savePhoneSettings error:', err);
    }
}

// ═════════════════════════════ Shared helpers ════════════════════════════════
/** Escape HTML special chars for textContent injection */
function _escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
/** Escape for HTML attribute values (already escaped < > but also double-quotes) */
function _escAttr(s) { return _escHtml(s); }
/** Format integer seconds as M:SS */
function _fmtDur(sec) {
    sec = parseInt(sec) || 0;
    const m = Math.floor(sec / 60), s = sec % 60;
    return `${m}:${String(s).padStart(2,'0')}`;
}

/** Ping /api/health and update the status-bar health dot colour */
function toggleGuiHealth() {
    fetch('/api/health').then(r => r.json()).then(h => {
        const dot = document.getElementById('guiHealthDot');
        if (!dot) return;
        const ok = h.ok !== false;
        dot.style.background = ok ? '#51cf66' : '#ff6b6b';
        dot.title = ok ? 'Services healthy' : ('Unhealthy: ' + (h.error || JSON.stringify(h)));
    }).catch(e => {
        const dot = document.getElementById('guiHealthDot');
        if (dot) { dot.style.background = '#ff6b6b'; dot.title = 'Health check failed: ' + e.message; }
    });
}

// ═══════════════════════ Voice Studio ════════════════════════════════════════

let _vsVoices = [];

async function vsLoadVoices() {
    try {
        const res  = await fetch('/api/voice-studio/voices');
        const data = await res.json();
        _vsVoices = data.voices || [];
        const sel = document.getElementById('vsVoiceSelect');
        if (!sel) return;
        sel.innerHTML = '<option value="">- Select a voice -</option>'
            + _vsVoices.map(v =>
                `<option value="${_escAttr(v.id)}">${_escHtml(v.name)}${v.is_premade ? ' ⭐' : ''}</option>`
            ).join('');
    } catch (e) {
        console.error('vsLoadVoices:', e);
    }
}

async function vsLoadToneButtons() {
    const container = document.getElementById('vsToneButtons');
    if (!container) return;
    try {
        const res  = await fetch('/api/voice-studio/tones');
        const data = await res.json();
        container.innerHTML = '';
        const allTags = {
            ...(data.emotions  || {}),
            ...(data.tones     || {}),
            ...(data.styles    || {})
        };
        Object.entries(allTags).forEach(([tag, desc]) => {
            const btn = document.createElement('button');
            btn.className = 'icon-action-btn';
            btn.style.cssText = 'font-size:11px;padding:3px 7px;';
            btn.title = desc;
            btn.textContent = tag.replace(/_/g, ' ');
            btn.onclick = () => {
                const ta = document.getElementById('vsTextInput');
                if (ta) ta.value += (ta.value ? ' ' : '') + `[${tag}]`;
            };
            container.appendChild(btn);
        });
    } catch (e) {
        console.error('vsLoadToneButtons:', e);
    }
}

async function vsLoadRecordings() {
    const voiceId = document.getElementById('vsVoiceSelect')?.value || '';
    try {
        const res  = await fetch(`/api/voice-studio/recordings?voice_id=${encodeURIComponent(voiceId)}&limit=20`);
        const data = await res.json();
        const list = document.getElementById('vsRecordingsList');
        if (!list) return;
        const recs = data.recordings || [];
        if (!recs.length) {
            list.innerHTML = '<p style="color:#666;font-size:12px;text-align:center;">No recordings yet</p>';
            return;
        }
        list.innerHTML = recs.map(r => `
            <div class="media-card" onclick="openMediaOverlay('audio','${_escAttr(r.url)}','${_escAttr(r.name)}')">
                <div class="media-card-thumb">🎵</div>
                <div class="media-card-info">
                    <div class="media-card-title">${_escHtml(r.name)}</div>
                    <div class="media-card-meta" style="font-size:10px;">${_escHtml(r.text?.substring(0,60) || '')}…</div>
                </div>
                ${r.duration ? `<div class="media-card-duration">${_fmtDur(r.duration)}</div>` : ''}
            </div>
        `).join('');
    } catch (e) {
        console.error('vsLoadRecordings:', e);
    }
}

async function vsGenerate() {
    const text = document.getElementById('vsTextInput')?.value.trim();
    if (!text) { alert('Please enter some text to synthesize.'); return; }
    const voiceId   = document.getElementById('vsVoiceSelect')?.value || '';
    const emotion   = document.getElementById('vsEmotion')?.value || '';
    const modelSize = document.getElementById('vsModelSize')?.value || 'auto';
    const btn       = document.querySelector('#voiceStudioScreen .settings-save-btn');
    if (btn) { btn.textContent = '⏳ Generating…'; btn.disabled = true; }
    try {
        const res  = await fetch('/api/voice-studio/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text, voice_id: voiceId || null, emotion: emotion || null, model_size: modelSize})
        });
        const data = await res.json();
        if (data.success && data.recording) {
            openMediaOverlay('audio', data.recording.url, data.recording.name || 'Recording');
            vsLoadRecordings();
        } else {
            alert('Generation failed: ' + (data.error || 'Unknown error'));
        }
    } catch (e) {
        alert('Voice generation error: ' + e.message);
    } finally {
        if (btn) { btn.textContent = '🎤 Generate'; btn.disabled = false; }
    }
}

async function vsNewVoice() {
    const name = prompt('Voice name:');
    if (!name) return;
    const desc = prompt('Voice description (personality, tone, accent etc.):');
    if (!desc) return;
    try {
        const res  = await fetch('/api/voice-studio/voice/new', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description: desc})
        });
        const data = await res.json();
        if (data.success) { vsLoadVoices(); }
        else { alert('Error: ' + data.error); }
    } catch (e) { alert('Error: ' + e.message); }
}

async function vsEditVoice() {
    const sel  = document.getElementById('vsVoiceSelect');
    const voiceId = sel?.value;
    if (!voiceId) { alert('Select a voice first.'); return; }
    const voice = _vsVoices.find(v => v.id === voiceId);
    if (!voice) return;
    const desc = prompt('Update voice description:', voice.description || '');
    if (desc === null) return;
    try {
        await fetch('/api/voice-studio/voice/new', {  // reuse create to keep it simple
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: voice.name + ' (edited)', description: desc})
        });
        vsLoadVoices();
    } catch (e) { alert('Error: ' + e.message); }
}

function vsCloneVoice() {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = 'audio/wav,audio/*';
    inp.style.display = 'none';
    document.body.appendChild(inp);
    inp.onchange = async () => {
        const file = inp.files[0];
        if (!file) return;
        const name = prompt('Name for cloned voice:', file.name.replace(/\.[^.]+$/, '')) || file.name;
        const form = new FormData();
        form.append('audio', file);
        form.append('name', name);
        try {
            const res  = await fetch('/api/voice-studio/voice/clone', {method: 'POST', body: form});
            const data = await res.json();
            if (data.success) { vsLoadVoices(); alert('Voice cloned!'); }
            else { alert('Clone error: ' + data.error); }
        } catch (e) { alert('Clone error: ' + e.message); }
        document.body.removeChild(inp);
    };
    inp.click();
}

async function vsBatchDialog() {
    const raw = prompt('Batch generation: Enter one line of text per recording (up to 5):');
    if (!raw) return;
    const lines = raw.split('\n').map(l => l.trim()).filter(Boolean).slice(0, 5);
    if (!lines.length) return;
    const voiceId   = document.getElementById('vsVoiceSelect')?.value || '';
    const emotion   = document.getElementById('vsEmotion')?.value || '';
    const modelSize = document.getElementById('vsModelSize')?.value || 'auto';
    let done = 0;
    for (const line of lines) {
        try {
            await fetch('/api/voice-studio/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: line, voice_id: voiceId || null,
                                      emotion: emotion || null, model_size: modelSize})
            });
            done++;
        } catch (e) { console.error('Batch line failed:', e); }
    }
    alert(`Batch done: ${done}/${lines.length} recordings generated.`);
    vsLoadRecordings();
}

// ═══════════════════════ Image Settings ═══════════════════════════════════

async function loadImageSettings() {
    try {
        // Load current settings and sampler lists in parallel
        const [settingsRes, samplersRes] = await Promise.all([
            fetch('/api/image-settings'),
            fetch('/api/comfyui/samplers')
        ]);
        const settings  = await settingsRes.json();
        const samplerData = await samplersRes.json();

        const _v = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? el.value; };
        _v('imgSteps',   settings.steps);
        _v('imgCfg',     settings.cfg);
        _v('imgDenoise', settings.denoise);

        // Populate sampler select
        const samplerSel = document.getElementById('imgSampler');
        if (samplerSel && samplerData.samplers) {
            samplerSel.innerHTML = samplerData.samplers
                .map(s => `<option value="${_escAttr(s)}"${s === settings.sampler ? ' selected' : ''}>${_escHtml(s)}</option>`)
                .join('');
        }

        // Populate scheduler select
        const schedulerSel = document.getElementById('imgScheduler');
        if (schedulerSel && samplerData.schedulers) {
            schedulerSel.innerHTML = samplerData.schedulers
                .map(s => `<option value="${_escAttr(s)}"${s === settings.scheduler ? ' selected' : ''}>${_escHtml(s)}</option>`)
                .join('');
        }

        // Populate model select if available
        const modelSel = document.getElementById('imgModel');
        if (modelSel && settings.model) modelSel.value = settings.model;
    } catch (e) {
        console.error('loadImageSettings:', e);
    }
}

async function saveImageSettings() {
    const _num = id => { const el = document.getElementById(id); return el ? parseFloat(el.value) : undefined; };
    const _str = id => { const el = document.getElementById(id); return el ? el.value : undefined; };
    const payload = {
        steps:     parseInt(_num('imgSteps') || 30),
        cfg:       _num('imgCfg'),
        denoise:   _num('imgDenoise'),
        sampler:   _str('imgSampler'),
        scheduler: _str('imgScheduler'),
        model:     _str('imgModel') || ''
    };
    try {
        const res  = await fetch('/api/image-settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            const btn = document.querySelector('#imageSettingsScreen .settings-save-btn');
            if (btn) { btn.textContent = '✅ Saved!'; setTimeout(() => btn.textContent = '💾 Save Image Settings', 1800); }
        }
    } catch (e) {
        console.error('saveImageSettings:', e);
    }
}

// Messages functionality
async function loadMessages() {
    try {
        const response = await fetch('/api/messages/history?limit=50');
        const data = await response.json();
        
        const container = document.getElementById('messagesContainer');
        container.innerHTML = '';
        
        data.messages.forEach(msg => {
            addMessageToUI(msg.role, msg.content, msg.timestamp, false);
        });
        
        scrollToBottom();
    } catch (error) {
        console.error('Error loading messages:', error);
    }
}

function handleMessageKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    // Send via socket
    socket.emit('send_message', { message: message });
    
    // Clear input
    input.value = '';
}

function addMessageToUI(role, content, timestamp, autonomous = false, shouldScroll = true) {
    const container = document.getElementById('messagesContainer');

    // ── Rich-media pattern detection ────────────────────────────────────
    // Photos stored as "[Photo sent: <media_id>]"
    const photoMatch = content && content.match(/^\[Photo sent:\s*([^\]]+)\]$/);
    if (photoMatch) {
        const mediaId = photoMatch[1].trim();
        addPhotoMessage(`/api/media/download/${mediaId}`, timestamp, role);
        return;
    }

    // Voice messages stored as "[Voice message: <transcript>]"
    const voiceMatch = content && content.match(/^\[Voice message:\s*(.*?)\]$/s);
    if (voiceMatch) {
        const transcript = voiceMatch[1].trim();
        _addVoiceHistoryBubble(role, transcript, timestamp, shouldScroll);
        return;
    }

    // Video messages stored as "[Video message: <caption>]" or "[Video: <caption>]"
    const videoMatch = content && content.match(/^\[Video(?:\s+message)?:\s*(.*?)\]$/s);
    if (videoMatch) {
        const caption = videoMatch[1].trim();
        _addVideoHistoryBubble(role, caption, timestamp, shouldScroll);
        return;
    }
    // ───────────────────────────────────────────────────────────────────

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    if (autonomous) {
        messageDiv.classList.add('autonomous');
    }
    
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble';
    bubbleDiv.textContent = content;
    
    const timeDiv = document.createElement('div');
    timeDiv.className = 'message-time';
    const time = new Date(timestamp);
    timeDiv.textContent = time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    
    bubbleDiv.appendChild(timeDiv);
    messageDiv.appendChild(bubbleDiv);
    container.appendChild(messageDiv);
    
    if (shouldScroll) {
        scrollToBottom();
    }
}

/** Render a voice-message history bubble (transcript only, no audio URL available). */
function _addVoiceHistoryBubble(role, transcript, timestamp, shouldScroll = true) {
    const container = document.getElementById('messagesContainer');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble voice-bubble';

    bubbleDiv.innerHTML = `
        <div class="voice-message-player">
            <span style="font-size:18px;margin-right:8px;">🎤</span>
            <div class="waveform">
                <div class="waveform-bar"></div>
                <div class="waveform-bar"></div>
                <div class="waveform-bar"></div>
                <div class="waveform-bar"></div>
                <div class="waveform-bar"></div>
            </div>
        </div>
        ${transcript ? `<div class="voice-transcript">${_escHtml(transcript)}</div>` : ''}
    `;

    const timeDiv = document.createElement('div');
    timeDiv.className = 'message-time';
    const t = new Date(timestamp);
    timeDiv.textContent = t.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    bubbleDiv.appendChild(timeDiv);

    messageDiv.appendChild(bubbleDiv);
    container.appendChild(messageDiv);
    if (shouldScroll) scrollToBottom();
}

/** Render a video-message history bubble (caption only, no video URL available). */
function _addVideoHistoryBubble(role, caption, timestamp, shouldScroll = true) {
    const container = document.getElementById('messagesContainer');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble video-bubble';

    bubbleDiv.innerHTML = `
        <div class="video-message-player" style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:24px;">🎥</span>
            ${caption ? `<div class="video-caption" style="font-size:13px;opacity:.9;">${_escHtml(caption)}</div>` : '<div style="opacity:.6;">Video message</div>'}
        </div>
    `;

    const timeDiv = document.createElement('div');
    timeDiv.className = 'message-time';
    const t = new Date(timestamp);
    timeDiv.textContent = t.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    bubbleDiv.appendChild(timeDiv);

    messageDiv.appendChild(bubbleDiv);
    container.appendChild(messageDiv);
    if (shouldScroll) scrollToBottom();
}

function addPhotoMessage(url, timestamp, role = 'assistant') {
    const container = document.getElementById('messagesContainer');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const imgDiv = document.createElement('div');
    imgDiv.className = 'message-bubble photo-bubble';
    
    const img = document.createElement('img');
    img.src = url;
    img.className = 'message-photo';
    img.onclick = () => openPhotoViewer(url);
    img.onerror = function() {
        this.alt = 'Image not available';
        this.style.cssText = 'width:120px;height:80px;background:#333;border-radius:8px;display:flex;align-items:center;justify-content:center;';
        this.removeAttribute('src');
    };
    
    const timeDiv = document.createElement('div');
    timeDiv.className = 'message-time';
    const time = new Date(timestamp);
    timeDiv.textContent = time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    
    imgDiv.appendChild(img);
    imgDiv.appendChild(timeDiv);
    messageDiv.appendChild(imgDiv);
    container.appendChild(messageDiv);
    
    scrollToBottom();
}

function addVoiceMessageToChat(data) {
    const container = document.getElementById('messagesContainer');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${data.role}`;
    
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble voice-bubble';
    
    // Voice message player
    const voicePlayer = document.createElement('div');
    voicePlayer.className = 'voice-message-player';
    voicePlayer.innerHTML = `
        <button class="play-btn" onclick="playVoiceMessage('${data.url}', this)">▶️</button>
        <div class="waveform">
            <div class="waveform-bar"></div>
            <div class="waveform-bar"></div>
            <div class="waveform-bar"></div>
            <div class="waveform-bar"></div>
            <div class="waveform-bar"></div>
        </div>
        <span class="duration">${formatDuration(data.duration)}</span>
    `;
    
    bubbleDiv.appendChild(voicePlayer);
    
    // Add text transcript if available
    if (data.text) {
        const transcriptDiv = document.createElement('div');
        transcriptDiv.className = 'voice-transcript';
        transcriptDiv.textContent = data.text;
        bubbleDiv.appendChild(transcriptDiv);
    }
    
    // Add timestamp
    const timeDiv = document.createElement('div');
    timeDiv.className = 'message-time';
    const time = new Date(data.timestamp);
    timeDiv.textContent = time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    
    bubbleDiv.appendChild(timeDiv);
    messageDiv.appendChild(bubbleDiv);
    container.appendChild(messageDiv);
    
    scrollToBottom();
}

function playVoiceMessage(url, button) {
    const audio = new Audio(url);
    
    // Change button to pause
    button.textContent = '⏸️';
    button.disabled = true;
    
    audio.onended = () => {
        button.textContent = '▶️';
        button.disabled = false;
    };
    
    audio.onerror = () => {
        button.textContent = '▶️';
        button.disabled = false;
        alert('Error playing voice message');
    };
    
    audio.play();
}

function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function addVideoMessageToChat(data) {
    const container = document.getElementById('messagesContainer');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${data.role}`;
    
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble video-bubble';
    
    // Video message player
    const videoPlayer = document.createElement('div');
    videoPlayer.className = 'video-message-player';
    
    const video = document.createElement('video');
    video.src = data.url;
    video.controls = true;
    video.preload = 'metadata';
    video.style.maxWidth = '280px';
    video.style.borderRadius = '12px';
    
    videoPlayer.appendChild(video);
    
    // Add caption if available
    if (data.text) {
        const captionDiv = document.createElement('div');
        captionDiv.className = 'video-caption';
        captionDiv.textContent = data.text;
        captionDiv.style.marginTop = '5px';
        captionDiv.style.fontSize = '13px';
        captionDiv.style.opacity = '0.9';
        videoPlayer.appendChild(captionDiv);
    }
    
    bubbleDiv.appendChild(videoPlayer);
    
    // Add timestamp
    const timeDiv = document.createElement('div');
    timeDiv.className = 'message-time';
    const time = new Date(data.timestamp);
    timeDiv.textContent = time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    
    bubbleDiv.appendChild(timeDiv);
    messageDiv.appendChild(bubbleDiv);
    container.appendChild(messageDiv);
    
    scrollToBottom();
}

function recordVideoMessage() {
    // Prompt for video message text
    const text = prompt('What do you want to say in the video message?');
    
    if (!text || text.trim() === '') {
        return;
    }
    
    // Show loading indicator
    const messagesScreen = document.getElementById('messagesScreen');
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'generating-indicator';
    loadingDiv.innerHTML = '🎬 Generating video message...';
    loadingDiv.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: rgba(0,0,0,0.8); color: white; padding: 20px; border-radius: 10px; z-index: 1000;';
    document.body.appendChild(loadingDiv);
    
    // Request video message generation
    socket.emit('send_video_message', {
        text: text.trim(),
        mood: 'happy'
    });
    
    // Remove loading indicator after a delay
    setTimeout(() => {
        if (loadingDiv.parentNode) {
            loadingDiv.remove();
        }
    }, 5000);
}

function showTypingIndicator(show) {
    const indicator = document.getElementById('typingIndicator');
    if (!indicator) return;
    if (show) {
        // Re-append to keep it as the last child so it shows below all messages
        const container = document.getElementById('messagesContainer');
        if (container && indicator.parentNode !== container) {
            container.appendChild(indicator);
        } else if (container) {
            container.appendChild(indicator); // moves to end even if already a child
        }
        indicator.style.display = 'block';
        scrollToBottom();
    } else {
        indicator.style.display = 'none';
    }
}

function scrollToBottom() {
    const container = document.getElementById('messagesContainer');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

// Call functionality
function startCall(type) {
    if (type === 'video') {
        // Open video call in new window/tab for better experience
        const characterName = currentCharacter ? currentCharacter.name : 'Character';
        window.open(`/video_call?character=${encodeURIComponent(characterName)}`, '_blank', 'width=800,height=600');
        return;
    }
    
    socket.emit('start_call', { type: type });
    
    // Show call screen (elements may not exist in all UI variants)
    const screens = document.querySelectorAll('.screen-view');
    screens.forEach(screen => screen.style.display = 'none');
    const callScreen = document.getElementById('callScreen');
    if (callScreen) callScreen.style.display = 'block';
    
    // Update call info
    const callTypeEl = document.getElementById('callType');
    if (callTypeEl) callTypeEl.textContent = type === 'video' ? 'Video Call' : 'Voice Call';
    
    // Show/hide video element
    const callVideo = document.getElementById('callVideo');
    if (callVideo) callVideo.style.display = type === 'video' ? 'block' : 'none';
    
    // Start timer
    callDuration = 0;
    callTimer = setInterval(updateCallTimer, 1000);
}

function endCall() {
    socket.emit('end_call');
    handleCallEnded();
}

function handleCallStarted(data) {
    console.log('Call started:', data);
}

function handleCallEnded() {
    // Stop timer
    if (callTimer) {
        clearInterval(callTimer);
        callTimer = null;
    }
    
    // Go back to phone app
    goHome();
}

function updateCallTimer() {
    callDuration++;
    const minutes = Math.floor(callDuration / 60);
    const seconds = callDuration % 60;
    const timerEl = document.getElementById('callTimer');
    if (timerEl) {
        timerEl.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }
}

function toggleMute() {
    // TODO: Implement mute functionality
    console.log('Toggle mute');
}

function toggleSpeaker() {
    // TODO: Implement speaker toggle
    console.log('Toggle speaker');
}

// Simulation functions
function simulateIncomingMessage() {
    if (!currentCharacter) {
        alert('Please select a character first');
        return;
    }
    
    const messages = [
        "Hey! What are you up to? 😊",
        "Miss you ❤️",
        "Can we talk later?",
        "Just thinking about you...",
        "Want to grab dinner tonight?"
    ];
    
    const randomMessage = messages[Math.floor(Math.random() * messages.length)];
    
    addMessageToUI('assistant', randomMessage, new Date().toISOString());
    
    // Show notification badge
    const badge = document.getElementById('messageBadge');
    if (badge) {
        const count = parseInt(badge.textContent || '0') + 1;
        badge.textContent = count;
        badge.style.display = 'block';
    }
}

function simulateIncomingCall() {
    if (!currentCharacter) {
        alert('Please select a character first');
        return;
    }
    
    if (confirm(`Incoming call from ${currentCharacter.name}. Answer?`)) {
        startCall('voice');
    }
}

// Photo upload functions
function openPhotoUpload() {
    document.getElementById('photoUploadDialog').style.display = 'flex';
}

function closePhotoUpload() {
    document.getElementById('photoUploadDialog').style.display = 'none';
    document.getElementById('photoPreview').style.display = 'none';
    selectedFile = null;
}

function triggerFileUpload() {
    document.getElementById('photoFileInput').click();
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    selectedFile = file;
    
    // Show preview
    const reader = new FileReader();
    reader.onload = (e) => {
        document.getElementById('previewImage').src = e.target.result;
        document.getElementById('photoPreview').style.display = 'block';
    };
    reader.readAsDataURL(file);
}

async function uploadPhoto() {
    if (!selectedFile) return;
    
    const formData = new FormData();
    formData.append('photo', selectedFile);
    
    try {
        const response = await fetch('/api/media/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Send photo in chat
            socket.emit('send_photo', { media_id: data.media_id });
            
            closePhotoUpload();
            alert('Photo sent!');
        } else {
            alert('Error uploading photo: ' + data.error);
        }
    } catch (error) {
        console.error('Upload error:', error);
        alert('Failed to upload photo');
    }
}

function cancelPhotoUpload() {
    closePhotoUpload();
}

async function generateSelfie() {
    if (!currentCharacter) {
        alert('Please select a character first');
        return;
    }
    
    try {
        const response = await fetch('/api/media/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mood: 'happy',
                setting: 'casual'
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Show in preview
            document.getElementById('previewImage').src = data.url;
            document.getElementById('photoPreview').style.display = 'block';
            
            // Store the generated media_id for sending
            selectedFile = { generated: true, media_id: data.media_id };
        } else {
            alert('Error generating photo: ' + data.error);
        }
    } catch (error) {
        console.error('Generation error:', error);
        alert('Failed to generate photo');
    }
}

function requestPhoto() {
    if (!currentCharacter) {
        alert('Please select a character first');
        return;
    }
    
    socket.emit('request_photo');
}

// Gallery functions
async function loadGallery() {
    if (!currentCharacter) {
        alert('Please select a character first');
        return;
    }
    
    try {
        const response = await fetch('/api/media/gallery');
        const data = await response.json();
        
        const grid = document.getElementById('galleryGrid');
        grid.innerHTML = '';
        
        if (data.photos && data.photos.length > 0) {
            data.photos.forEach(photo => {
                const thumb = document.createElement('div');
                thumb.className = 'gallery-thumbnail';
                
                const img = document.createElement('img');
                img.src = photo.url;
                img.onclick = () => openPhotoViewer(photo.url);
                
                thumb.appendChild(img);
                grid.appendChild(thumb);
            });
        } else {
            grid.innerHTML = '<p style="text-align:center; color:#666; margin-top:50px;">No photos yet</p>';
        }
    } catch (error) {
        console.error('Error loading gallery:', error);
    }
}

async function openGalleryView() {
    // Load gallery in overlay
    const overlay = document.getElementById('galleryViewOverlay');
    overlay.style.display = 'flex';
    
    try {
        const response = await fetch('/api/media/gallery');
        const data = await response.json();
        
        const grid = document.getElementById('galleryViewGrid');
        grid.innerHTML = '';
        
        if (data.photos && data.photos.length > 0) {
            data.photos.forEach(photo => {
                const thumb = document.createElement('div');
                thumb.className = 'gallery-thumbnail';
                
                const img = document.createElement('img');
                img.src = photo.url;
                img.onclick = () => {
                    closeGalleryView();
                    openPhotoViewer(photo.url);
                };
                
                thumb.appendChild(img);
                grid.appendChild(thumb);
            });
        } else {
            grid.innerHTML = '<p style="text-align:center; color:#666; margin-top:50px;">No photos yet</p>';
        }
    } catch (error) {
        console.error('Error loading gallery:', error);
    }
}

function closeGalleryView() {
    document.getElementById('galleryViewOverlay').style.display = 'none';
}

function openPhotoViewer(url) {
    currentPhotoUrl = url;
    document.getElementById('viewerImage').src = url;
    document.getElementById('photoViewer').style.display = 'flex';
}

function closePhotoViewer() {
    document.getElementById('photoViewer').style.display = 'none';
    currentPhotoUrl = null;
}

function downloadPhoto() {
    if (currentPhotoUrl) {
        const a = document.createElement('a');
        a.href = currentPhotoUrl;
        a.download = 'photo.jpg';
        a.click();
    }
}

// Autonomous Messaging Functions
function openAutonomousSettings() {
    loadAutonomousSettings();
    document.getElementById('autonomousSettingsOverlay').style.display = 'flex';
}

function closeAutonomousSettings() {
    document.getElementById('autonomousSettingsOverlay').style.display = 'none';
}

async function loadAutonomousSettings() {
    // Load from localStorage first
    const savedSettings = JSON.parse(localStorage.getItem('autonomousSettings') || '{}');
    
    // Set UI from saved settings or defaults
    document.getElementById('autonomousToggle').checked = savedSettings.enabled !== false;
    document.getElementById('frequencySelect').value = savedSettings.frequency || 'moderate';
    document.getElementById('startHourSlider').value = savedSettings.startHour || 8;
    document.getElementById('endHourSlider').value = savedSettings.endHour || 23;
    document.getElementById('enablePhotosCheck').checked = savedSettings.enablePhotos !== false;
    
    updateTimeRange();
    
    // Fetch current status from server
    try {
        const response = await fetch('/api/autonomous/status');
        const data = await response.json();
        
        if (data.enabled !== undefined) {
            document.getElementById('autonomousToggle').checked = data.enabled;
        }
    } catch (error) {
        console.error('Error loading autonomous status:', error);
    }
}

async function toggleAutonomous() {
    const enabled = document.getElementById('autonomousToggle').checked;
    
    try {
        const endpoint = enabled ? '/api/autonomous/enable' : '/api/autonomous/disable';
        const response = await fetch(endpoint, { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            console.log('Autonomous messaging', enabled ? 'enabled' : 'disabled');
            saveSettingsToLocalStorage();
        }
    } catch (error) {
        console.error('Error toggling autonomous:', error);
    }
}

function updateTimeRange() {
    const startHour = parseInt(document.getElementById('startHourSlider').value);
    const endHour = parseInt(document.getElementById('endHourSlider').value);
    
    const formatHour = (hour) => {
        const period = hour >= 12 ? 'PM' : 'AM';
        const displayHour = hour === 0 ? 12 : (hour > 12 ? hour - 12 : hour);
        return `${displayHour}:00 ${period}`;
    };
    
    document.getElementById('timeRangeDisplay').textContent = 
        `${formatHour(startHour)} - ${formatHour(endHour)}`;
}

async function updateAutonomousSettings() {
    saveSettingsToLocalStorage();
}

async function saveAutonomousSettings() {
    if (!currentCharacter) {
        alert('Please select a character first');
        return;
    }
    
    const frequency = document.getElementById('frequencySelect').value;
    const startHour = parseInt(document.getElementById('startHourSlider').value);
    const endHour = parseInt(document.getElementById('endHourSlider').value);
    const enablePhotos = document.getElementById('enablePhotosCheck').checked;
    
    try {
        const response = await fetch('/api/autonomous/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                character_id: currentCharacter.id,
                frequency: frequency,
                time_range: [startHour, endHour],
                enable_photos: enablePhotos
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            saveSettingsToLocalStorage();
            closeAutonomousSettings();
            alert('Settings saved successfully!');
        } else {
            alert('Error saving settings: ' + data.error);
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        alert('Failed to save settings');
    }
}

function saveSettingsToLocalStorage() {
    const settings = {
        enabled: document.getElementById('autonomousToggle').checked,
        frequency: document.getElementById('frequencySelect').value,
        startHour: parseInt(document.getElementById('startHourSlider').value),
        endHour: parseInt(document.getElementById('endHourSlider').value),
        enablePhotos: document.getElementById('enablePhotosCheck').checked
    };
    localStorage.setItem('autonomousSettings', JSON.stringify(settings));
}

// ============= SCENE SAVE/LOAD FUNCTIONS =============

// Load available scenes
async function loadScenes() {
    try {
        const response = await fetch('/api/scene/list');
        const data = await response.json();
        
        const select = document.getElementById('sceneSelect');
        if (!select) return;
        
        select.innerHTML = '<option value="">Select Scene...</option>';
        
        if (data.scenes && data.scenes.length > 0) {
            data.scenes.forEach(scene => {
                const option = document.createElement('option');
                option.value = scene.id;
                option.textContent = scene.metadata?.name || scene.id.substring(0, 8);
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading scenes:', error);
    }
}

// Save current scene
async function saveScene() {
    const name = prompt('Enter scene name:', 'Phone Scene ' + new Date().toLocaleDateString());
    
    if (!name) return;
    
    try {
        const response = await fetch('/api/scene/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Scene saved successfully!');
            loadScenes(); // Refresh scene list
        } else {
            alert('Error saving scene: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error saving scene:', error);
        alert('Failed to save scene');
    }
}

// Load saved scene
async function loadScene() {
    const select = document.getElementById('sceneSelect');
    const sceneId = select.value;
    
    if (!sceneId) {
        alert('Please select a scene to load');
        return;
    }
    
    if (!confirm('Loading a scene will replace the current character. Continue?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/scene/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scene_id: sceneId })
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Scene loaded successfully!');
            // Reload characters and UI
            loadCharacters();
        } else {
            alert('Error loading scene: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error loading scene:', error);
        alert('Failed to load scene');
    }
}

async function getAutonomousStatus() {
    try {
        const response = await fetch('/api/autonomous/status');
        return await response.json();
    } catch (error) {
        console.error('Error getting autonomous status:', error);
        return null;
    }
}

function showNotificationBadge(count) {
    const badge = document.getElementById('messageBadge');
    if (badge) {
        badge.textContent = count;
        badge.style.display = count > 0 ? 'inline-block' : 'none';
    }
}

// Export functions for HTML onclick handlers
window.openApp = openApp;
window.goHome = goHome;
window.sendMessage = sendMessage;
window.handleMessageKeyPress = handleMessageKeyPress;
window.startCall = startCall;
window.endCall = endCall;
window.toggleMute = toggleMute;
window.toggleSpeaker = toggleSpeaker;
window.selectCharacter = selectCharacter;
window.simulateIncomingMessage = simulateIncomingMessage;
window.simulateIncomingCall = simulateIncomingCall;
window.openPhotoUpload = openPhotoUpload;
window.closePhotoUpload = closePhotoUpload;
window.triggerFileUpload = triggerFileUpload;
window.handleFileSelect = handleFileSelect;
window.uploadPhoto = uploadPhoto;
window.cancelPhotoUpload = cancelPhotoUpload;
window.generateSelfie = generateSelfie;
window.requestPhoto = requestPhoto;
window.loadGallery = loadGallery;
window.openGalleryView = openGalleryView;
window.closeGalleryView = closeGalleryView;
window.openPhotoViewer = openPhotoViewer;
window.closePhotoViewer = closePhotoViewer;
window.downloadPhoto = downloadPhoto;
window.openAutonomousSettings = openAutonomousSettings;
window.closeAutonomousSettings = closeAutonomousSettings;
window.toggleAutonomous = toggleAutonomous;
window.updateTimeRange = updateTimeRange;
window.updateAutonomousSettings = updateAutonomousSettings;
window.saveAutonomousSettings = saveAutonomousSettings;
