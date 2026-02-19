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
    updateTime();
    loadCharacters();
    setInterval(updateTime, 1000);
});

// Socket.IO initialization
function initializeSocket() {
    socket = io();
    
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

// Update time displays
function updateTime() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    const dateStr = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
    
    const statusTime = document.getElementById('statusTime');
    if (statusTime) statusTime.textContent = timeStr;
    
    const homeDate = document.getElementById('homeDate');
    if (homeDate) homeDate.textContent = dateStr;
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
        'messages': 'messagesScreen',
        'phone': 'phoneScreen',
        'gallery': 'galleryScreen',
        'camera': 'homeScreen', // Placeholder
        'settings': 'homeScreen', // Placeholder
        'browser': 'homeScreen' // Placeholder
    };
    
    const screenId = screenMap[appName] || 'homeScreen';
    document.getElementById(screenId).style.display = 'block';
    
    // Clear notification badge when opening messages
    if (appName === 'messages') {
        showNotificationBadge(0);
        loadMessages();
    } else if (appName === 'gallery') {
        loadGallery();
    }
}

function goHome() {
    const screens = document.querySelectorAll('.screen-view');
    screens.forEach(screen => screen.style.display = 'none');
    document.getElementById('homeScreen').style.display = 'block';
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
    if (indicator) {
        indicator.style.display = show ? 'block' : 'none';
        if (show) scrollToBottom();
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
    
    // Show call screen
    const screens = document.querySelectorAll('.screen-view');
    screens.forEach(screen => screen.style.display = 'none');
    document.getElementById('callScreen').style.display = 'block';
    
    // Update call info
    const callType = document.getElementById('callType');
    callType.textContent = type === 'video' ? 'Video Call' : 'Voice Call';
    
    // Show video if video call
    const callVideo = document.getElementById('callVideo');
    if (type === 'video') {
        callVideo.style.display = 'block';
    } else {
        callVideo.style.display = 'none';
    }
    
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
