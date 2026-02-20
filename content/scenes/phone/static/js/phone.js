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
        
        // Update mood/relationship/arousal if the server sent new values
        if (currentCharacter) {
            if (data.mood) currentCharacter.mood = data.mood;
            if (data.relationship_level !== undefined) currentCharacter.relationship_level = data.relationship_level;
            if (data.arousal !== undefined) currentCharacter.arousal = data.arousal;
        }
        if (data.role === 'assistant') updateMoodRelDisplay();
        
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
        addPhotoMessage(data.url, data.timestamp, data.role || 'assistant', data.caption);
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
    
    // Update mood & relationship indicators in chat header
    updateMoodRelDisplay();
}

/** Refresh the mood dot, relationship hearts, and arousal bar in the message header. */
function updateMoodRelDisplay() {
    if (!currentCharacter) return;
    const mood    = currentCharacter.mood || 'neutral';
    const rel     = parseFloat(currentCharacter.relationship_level || 0.5);
    const arousal = parseFloat(currentCharacter.arousal || 0);
    
    // Mood dot colour mapping
    const moodColours = {
        happy:'#34c759', excited:'#ff9500', flirty:'#ff2d55',
        sad:'#5ac8fa', angry:'#ff3b30', neutral:'#8e8e93',
        anxious:'#ffcc00', playful:'#af52de', loving:'#ff375f',
        bored:'#636366', curious:'#0a84ff', shy:'#d4a0e8',
        seductive:'#e63946', aroused:'#d00000', passionate:'#dc2f02',
        teasing:'#f77f00', needy:'#9d4edd', confident:'#f4a261',
    };
    const dot = document.getElementById('moodDot');
    if (dot) dot.style.background = moodColours[mood] || '#8e8e93';
    
    const label = document.getElementById('moodLabel');
    if (label) label.textContent = mood;
    
    // Relationship hearts (0–5 filled)
    const hearts = document.getElementById('relHearts');
    if (hearts) {
        const filled = Math.round(rel * 5);
        hearts.textContent = '❤️'.repeat(filled) + '🤍'.repeat(5 - filled);
    }
    
    // Arousal fire bar (0–5 flames)
    const fire = document.getElementById('arousalFire');
    if (fire) {
        const flames = Math.round(arousal * 5);
        fire.textContent = flames > 0 ? '🔥'.repeat(flames) : '';
        fire.style.display = flames > 0 ? 'inline' : 'none';
    }
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
        vsLoadRecordings();
        vsLoadToneButtons();
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
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    if (autonomous) messageDiv.classList.add('autonomous');
    
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble';
    bubbleDiv.textContent = content;
    
    // Timestamp + read-receipt row
    const metaDiv = document.createElement('div');
    metaDiv.className = 'message-meta';
    
    const timeSpan = document.createElement('span');
    timeSpan.className = 'message-time';
    const time = new Date(timestamp);
    timeSpan.textContent = time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    metaDiv.appendChild(timeSpan);
    
    // Read receipt checkmarks for user messages
    if (role === 'user') {
        const receipt = document.createElement('span');
        receipt.className = 'read-receipt delivered';
        receipt.textContent = '✓✓';
        metaDiv.appendChild(receipt);
        // Mark as read after a brief delay (simulates delivery)
        setTimeout(() => { receipt.className = 'read-receipt read'; }, 800);
    }
    
    bubbleDiv.appendChild(metaDiv);
    messageDiv.appendChild(bubbleDiv);
    container.appendChild(messageDiv);
    
    if (shouldScroll) scrollToBottom();
}

function addPhotoMessage(url, timestamp, role = 'assistant', caption = '') {
    const container = document.getElementById('messagesContainer');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const imgDiv = document.createElement('div');
    imgDiv.className = 'message-bubble photo-bubble';
    
    const img = document.createElement('img');
    img.src = url;
    img.className = 'message-photo';
    img.onclick = () => openPhotoViewer(url);
    
    imgDiv.appendChild(img);
    
    // Caption under the photo
    if (caption) {
        const capDiv = document.createElement('div');
        capDiv.className = 'photo-caption';
        capDiv.textContent = caption;
        imgDiv.appendChild(capDiv);
    }
    
    const timeDiv = document.createElement('div');
    timeDiv.className = 'message-time';
    const time = new Date(timestamp);
    timeDiv.textContent = time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    
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
        // Set character name in typing bubble
        const nameEl = indicator.querySelector('.typing-name');
        if (nameEl && currentCharacter) {
            nameEl.textContent = currentCharacter.name;
        }
        // Re-append to keep it as the last child so it shows below all messages
        const container = document.getElementById('messagesContainer');
        if (container) container.appendChild(indicator);
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

// ══════════════════════════════ VOICE STUDIO ══════════════════════════════

async function vsLoadVoices() {
    try {
        const resp = await fetch('/api/voice-studio/voices');
        const data = await resp.json();
        const sel = document.getElementById('vsVoiceSelect');
        if (!sel) return;
        sel.innerHTML = '<option value="">-- Select Voice --</option>';
        (data.voices || []).forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.textContent = `${v.name} (${v.model_size})${v.is_premade ? ' ★' : ''}`;
            sel.appendChild(opt);
        });
    } catch(e) { console.error('vsLoadVoices:', e); }
}

async function vsLoadRecordings() {
    try {
        const resp = await fetch('/api/voice-studio/recordings?limit=20');
        const data = await resp.json();
        const list = document.getElementById('vsRecordingsList');
        if (!list) return;
        const recs = data.recordings || [];
        if (!recs.length) { list.innerHTML = '<div style="color:#888;font-size:12px;padding:8px;">No recordings yet</div>'; return; }
        list.innerHTML = recs.map(r => `
            <div style="display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid #222;">
                <button onclick="vsPlayRec('${r.url}')" style="background:none;border:none;cursor:pointer;font-size:16px;">▶️</button>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:12px;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${r.name || 'Recording'}</div>
                    <div style="font-size:10px;color:#888;">${r.duration ? r.duration.toFixed(1) + 's' : ''} · ${r.text ? r.text.substring(0,40) + '...' : ''}</div>
                </div>
                <button onclick="vsDeleteRec('${r.id}')" style="background:none;border:none;cursor:pointer;font-size:12px;color:#f44;">🗑️</button>
            </div>
        `).join('');
    } catch(e) { console.error('vsLoadRecordings:', e); }
}

function vsLoadToneButtons() {
    const container = document.getElementById('vsToneButtons');
    if (!container) return;
    const tags = {
        '😊 Happy':'happy', '😢 Sad':'sad', '😠 Angry':'angry',
        '🤩 Excited':'excited', '😏 Flirty':'flirty', '🔥 Seductive':'seductive',
        '💪 Confident':'confident', '🙈 Shy':'shy', '🌙 Mystery':'mysterious',
        '💕 Loving':'loving', '🎭 Dramatic':'dramatic', '💤 ASMR':'asmr',
        '📢 Shout':'shout', '🤫 Whisper':'whisper', '😤 Raspy':'raspy',
    };
    container.innerHTML = Object.entries(tags).map(([label, val]) =>
        `<button onclick="vsInsertTone('${val}')" style="font-size:10px;padding:2px 6px;border-radius:8px;border:1px solid #444;background:#222;color:#fff;cursor:pointer;">${label}</button>`
    ).join('');
}

function vsInsertTone(tone) {
    const ta = document.getElementById('vsTextInput');
    if (ta) ta.value += ` [${tone}] `;
    ta.focus();
}

async function vsGenerate() {
    const text = document.getElementById('vsTextInput')?.value?.trim();
    if (!text) { alert('Enter text first'); return; }
    const voiceId = document.getElementById('vsVoiceSelect')?.value || null;
    const emotion = document.getElementById('vsEmotion')?.value || null;
    const modelSize = document.getElementById('vsModelSize')?.value || 'auto';

    try {
        const resp = await fetch('/api/voice-studio/generate', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ text, voice_id: voiceId, emotion, model_size: modelSize })
        });
        const data = await resp.json();
        if (data.success && data.recording) {
            vsPlayRec(data.recording.url);
            vsLoadRecordings();
        } else {
            alert(data.error || 'Generation failed');
        }
    } catch(e) { alert('Error: ' + e.message); }
}

function vsPlayRec(url) {
    const audio = new Audio(url);
    audio.play().catch(e => console.error('Playback error:', e));
}

async function vsDeleteRec(id) {
    if (!confirm('Delete this recording?')) return;
    await fetch(`/api/voice-studio/recordings/${id}`, { method: 'DELETE' });
    vsLoadRecordings();
}

function vsNewVoice() {
    const name = prompt('Voice name:');
    if (!name) return;
    const desc = prompt('Voice description (acoustic traits, pitch, pace, style):');
    if (!desc) return;
    const modelSize = prompt('Model size (0.6b or 1.7b):', '1.7b');
    fetch('/api/voice-studio/voices', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ name, description: desc, model_size: modelSize || '1.7b' })
    }).then(() => vsLoadVoices());
}

function vsEditVoice() {
    const id = document.getElementById('vsVoiceSelect')?.value;
    if (!id || id.startsWith('premade_')) { alert('Select a custom voice to edit'); return; }
    const desc = prompt('New voice description:');
    if (!desc) return;
    fetch(`/api/voice-studio/voices/${id}`, {
        method: 'PUT',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ description: desc })
    }).then(() => vsLoadVoices());
}

function vsCloneVoice() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.wav,.mp3,.ogg';
    input.onchange = async () => {
        const file = input.files[0];
        if (!file) return;
        const name = prompt('Name for cloned voice:', `Clone: ${file.name}`);
        if (!name) return;
        const form = new FormData();
        form.append('audio', file);
        form.append('name', name);
        const resp = await fetch('/api/voice-studio/clone', { method: 'POST', body: form });
        const data = await resp.json();
        if (data.success) { vsLoadVoices(); alert('Voice cloned!'); }
        else alert(data.error || 'Clone failed');
    };
    input.click();
}

function vsBatchDialog() {
    const script = prompt(
        'Paste a batch script (one line per generation):\n\n' +
        'Format: CHARACTER (emotion): "dialogue"\n' +
        'Or plain text lines\n\n' +
        'Example:\nCOMMANDER: "Fire all batteries!"\nAI (calm): "Reactor at 84%"'
    );
    if (!script) return;
    const voiceId = document.getElementById('vsVoiceSelect')?.value || null;
    fetch('/api/voice-studio/batch', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ script, voice_id: voiceId })
    }).then(r => r.json()).then(data => {
        alert(`Batch complete: ${data.generated}/${data.total} generated`);
        vsLoadRecordings();
    }).catch(e => alert('Batch error: ' + e.message));
}

// Export voice studio functions
window.vsLoadVoices = vsLoadVoices;
window.vsLoadRecordings = vsLoadRecordings;
window.vsLoadToneButtons = vsLoadToneButtons;
window.vsInsertTone = vsInsertTone;
window.vsGenerate = vsGenerate;
window.vsPlayRec = vsPlayRec;
window.vsDeleteRec = vsDeleteRec;
window.vsNewVoice = vsNewVoice;
window.vsEditVoice = vsEditVoice;
window.vsCloneVoice = vsCloneVoice;
window.vsBatchDialog = vsBatchDialog;

// ══════════════════════════════ IMAGE SETTINGS ════════════════════════════

async function loadImageSettings() {
    try {
        const resp = await fetch('/api/image-settings');
        const data = await resp.json();
        const s = data.settings || {};

        const stepsEl = document.getElementById('imgSteps');
        const cfgEl = document.getElementById('imgCfg');
        const denoiseEl = document.getElementById('imgDenoise');
        const samplerEl = document.getElementById('imgSampler');
        const schedulerEl = document.getElementById('imgScheduler');
        const modelEl = document.getElementById('imgModel');

        if (stepsEl) stepsEl.value = s.steps || 30;
        if (cfgEl) cfgEl.value = s.cfg || 7;
        if (denoiseEl) denoiseEl.value = s.denoise || 1;

        // Populate sampler options
        if (samplerEl) {
            samplerEl.innerHTML = (data.available_samplers || []).map(name =>
                `<option value="${name}" ${name === s.sampler_name ? 'selected' : ''}>${name}</option>`
            ).join('');
        }

        // Populate scheduler options
        if (schedulerEl) {
            schedulerEl.innerHTML = (data.available_schedulers || []).map(name =>
                `<option value="${name}" ${name === s.scheduler ? 'selected' : ''}>${name}</option>`
            ).join('');
        }

        // Populate model options
        if (modelEl) {
            modelEl.innerHTML = '<option value="">Auto-detect</option>' +
                (data.available_models || []).map(name =>
                    `<option value="${name}" ${name === s.model ? 'selected' : ''}>${name}</option>`
                ).join('');
        }
    } catch(e) { console.error('loadImageSettings:', e); }
}

async function saveImageSettings() {
    const settings = {
        steps: parseInt(document.getElementById('imgSteps')?.value) || 30,
        cfg: parseFloat(document.getElementById('imgCfg')?.value) || 7,
        denoise: parseFloat(document.getElementById('imgDenoise')?.value) || 1,
        sampler_name: document.getElementById('imgSampler')?.value || 'euler',
        scheduler: document.getElementById('imgScheduler')?.value || 'normal',
        model: document.getElementById('imgModel')?.value || null,
    };
    try {
        const resp = await fetch('/api/image-settings', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(settings)
        });
        const data = await resp.json();
        if (data.success) alert('Image settings saved!');
        else alert('Error saving settings');
    } catch(e) { alert('Error: ' + e.message); }
}

window.loadImageSettings = loadImageSettings;
window.saveImageSettings = saveImageSettings;
