// Voice Call and Voice Message Handler
// NOTE: callTimer, callDuration, socket, currentCharacter are declared in phone.js
let currentCall = null;
let isMuted = false;
let isSpeakerOn = false;
let audioContext = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// Initialize voice functionality
function initializeVoice() {
    // Setup audio context for recording
    if (!audioContext && (window.AudioContext || window.webkitAudioContext)) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    
    // Listen for incoming calls
    if (socket) {
        socket.on('incoming_call', handleIncomingCall);
        socket.on('call_answered', handleCallAnswered);
        socket.on('call_ended', handleCallEnded);
        socket.on('call_audio', handleCallAudio);
        socket.on('voice_message_received', handleVoiceMessageReceived);
    }
}

// Voice Call Functions
function startCall(type = 'voice') {
    if (!socket || !currentCharacter) {
        alert('Please select a character first');
        return;
    }
    
    // Play dial tone
    const dialTone = document.getElementById('dialTone');
    if (dialTone) dialTone.play();
    
    // Emit call start event
    socket.emit('start_call', {
        type: type
    });
    
    console.log('Starting call...');
}

function handleIncomingCall(data) {
    console.log('Incoming call:', data);
    
    currentCall = {
        id: data.call_id,
        character: data.character_name,
        type: data.type,
        status: 'ringing'
    };
    
    // Show incoming call overlay in phone UI
    showIncomingCallOverlay(data);
    
    // Play ringtone
    const ringtone = document.getElementById('ringtone');
    if (ringtone) ringtone.play();
}

function answerCall() {
    if (!currentCall) return;
    
    // Stop ringtone
    const ringtone = document.getElementById('ringtone');
    if (ringtone) {
        ringtone.pause();
        ringtone.currentTime = 0;
    }
    
    // Answer via socket
    socket.emit('answer_call', {
        call_id: currentCall.id
    });
    
    currentCall.status = 'active';
    
    // Show active call screen
    showActiveCallScreen();
    
    // Start call timer
    startCallTimer();
    
    // Start microphone for STT
    startMicrophone();
}

function handleCallAnswered(data) {
    console.log('Call answered:', data);
    
    if (currentCall) {
        currentCall.status = 'active';
        showActiveCallScreen();
        startCallTimer();
        startMicrophone();
    }
}

function endCall() {
    if (!currentCall) return;
    
    // Emit end call event
    socket.emit('end_call', {
        call_id: currentCall.id
    });
    
    // Stop recording
    stopMicrophone();
    
    // Stop timer
    stopCallTimer();
    
    // Show call ended screen
    showCallEndedScreen();
}

function handleCallEnded(data) {
    console.log('Call ended:', data);
    
    if (data && data.duration) {
        callDuration = data.duration;
    }
    
    // Stop recording
    stopMicrophone();
    
    // Stop timer
    stopCallTimer();
    
    // Show call ended screen
    showCallEndedScreen();
}

function declineCall() {
    if (!currentCall) return;
    
    // Stop ringtone
    const ringtone = document.getElementById('ringtone');
    if (ringtone) {
        ringtone.pause();
        ringtone.currentTime = 0;
    }
    
    // End the call
    socket.emit('end_call', {
        call_id: currentCall.id
    });
    
    // Hide incoming call screen
    hideIncomingCallOverlay();
    
    currentCall = null;
}

function callAgain() {
    closeCallScreen();
    startCall('voice');
}

function closeCallScreen() {
    // Hide all call screens
    const incomingScreen = document.getElementById('incomingCallScreen');
    const activeScreen = document.getElementById('activeCallScreen');
    const endedScreen = document.getElementById('callEndedScreen');
    
    if (incomingScreen) incomingScreen.style.display = 'none';
    if (activeScreen) activeScreen.style.display = 'none';
    if (endedScreen) endedScreen.style.display = 'none';
    
    // Also hide overlay in phone UI
    hideIncomingCallOverlay();
    hideActiveCallOverlay();
    
    currentCall = null;
}

// Call Timer
function startCallTimer() {
    callDuration = 0;
    updateCallTimer();
    
    callTimer = setInterval(() => {
        callDuration++;
        updateCallTimer();
    }, 1000);
}

function stopCallTimer() {
    if (callTimer) {
        clearInterval(callTimer);
        callTimer = null;
    }
}

function updateCallTimer() {
    const minutes = Math.floor(callDuration / 60);
    const seconds = callDuration % 60;
    const timeStr = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    
    const timerEl = document.getElementById('callTimer');
    if (timerEl) timerEl.textContent = timeStr;
}

// Call Controls
function toggleMute() {
    isMuted = !isMuted;
    
    const muteBtn = document.getElementById('muteBtn');
    if (muteBtn) {
        muteBtn.querySelector('.icon').textContent = isMuted ? '🔇' : '🎤';
        muteBtn.classList.toggle('active', isMuted);
    }
    
    // Mute microphone stream if recording
    if (mediaRecorder && mediaRecorder.stream) {
        mediaRecorder.stream.getAudioTracks().forEach(track => {
            track.enabled = !isMuted;
        });
    }
}

function toggleSpeaker() {
    isSpeakerOn = !isSpeakerOn;
    
    const speakerBtn = document.getElementById('speakerBtn');
    if (speakerBtn) {
        speakerBtn.querySelector('.icon').textContent = isSpeakerOn ? '🔊' : '🔉';
        speakerBtn.classList.toggle('active', isSpeakerOn);
    }
}

// Microphone Recording for STT
async function startMicrophone() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        
        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
            
            // Send audio chunks to server for STT
            if (socket && currentCall && currentCall.status === 'active') {
                const reader = new FileReader();
                reader.onload = () => {
                    socket.emit('call_audio', {
                        audio: reader.result
                    });
                };
                reader.readAsArrayBuffer(event.data);
            }
        };
        
        // Record in chunks (every 2 seconds)
        mediaRecorder.start(2000);
        isRecording = true;
        
        console.log('Microphone started');
    } catch (error) {
        console.error('Error accessing microphone:', error);
        alert('Could not access microphone');
    }
}

function stopMicrophone() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        isRecording = false;
        console.log('Microphone stopped');
    }
}

// Handle incoming call audio (TTS from character)
function handleCallAudio(data) {
    if (data.type === 'text') {
        // Text-only response (no TTS available)
        console.log('Character:', data.text);
        
        // Display text in call screen (optional)
        showCallTranscript(data.text, 'assistant');
    } else if (data.type === 'audio') {
        // Play audio chunk
        playAudioChunk(data.data, data.sample_rate);
    }
}

function playAudioChunk(audioData, sampleRate) {
    if (!audioContext) return;
    
    // Convert base64 or ArrayBuffer to audio
    const audioBuffer = audioContext.createBuffer(1, audioData.length / 2, sampleRate);
    const channelData = audioBuffer.getChannelData(0);
    
    // Convert Int16 to Float32
    const view = new DataView(audioData);
    for (let i = 0; i < channelData.length; i++) {
        channelData[i] = view.getInt16(i * 2, true) / 32768.0;
    }
    
    // Play audio
    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    source.start();
}

// Voice Message Functions
function startVoiceMessageRecording() {
    if (isRecording) {
        stopVoiceMessageRecording();
        return;
    }
    
    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            
            mediaRecorder.ondataavailable = (event) => {
                audioChunks.push(event.data);
            };
            
            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                uploadVoiceMessage(audioBlob);
            };
            
            mediaRecorder.start();
            isRecording = true;
            
            // Show recording indicator
            showRecordingIndicator();
        })
        .catch(error => {
            console.error('Error accessing microphone:', error);
            alert('Could not access microphone');
        });
}

function stopVoiceMessageRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        isRecording = false;
        
        hideRecordingIndicator();
    }
}

async function uploadVoiceMessage(audioBlob) {
    // TODO: Upload audio to server
    // For now, just show a placeholder
    console.log('Voice message recorded:', audioBlob);
    alert('Voice message recording feature coming soon!');
}

function handleVoiceMessageReceived(data) {
    console.log('Voice message received:', data);
    
    // Add voice message to chat UI
    addVoiceMessageToUI(data);
}

function addVoiceMessageToUI(data) {
    const messagesContainer = document.getElementById('messagesContainer');
    if (!messagesContainer) return;
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${data.role}`;
    
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
    
    messageDiv.appendChild(voicePlayer);
    
    // Add text transcript if available
    if (data.text) {
        const transcriptDiv = document.createElement('div');
        transcriptDiv.className = 'voice-transcript';
        transcriptDiv.textContent = data.text;
        messageDiv.appendChild(transcriptDiv);
    }
    
    // Add timestamp
    const timestampDiv = document.createElement('div');
    timestampDiv.className = 'timestamp';
    timestampDiv.textContent = formatTimestamp(data.timestamp);
    messageDiv.appendChild(timestampDiv);
    
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
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

// UI Helper Functions
function showIncomingCallOverlay(data) {
    // Create overlay in phone UI
    let overlay = document.getElementById('incomingCallOverlay');
    
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'incomingCallOverlay';
        overlay.className = 'call-overlay incoming';
        document.body.appendChild(overlay);
    }
    
    overlay.innerHTML = `
        <div class="call-overlay-content">
            <div class="caller-avatar">
                <img src="/static/img/default-avatar.png" alt="Avatar">
            </div>
            <h2>${data.character_name}</h2>
            <p>Incoming call...</p>
            <div class="call-actions">
                <button class="decline-btn" onclick="declineCall()">📵 Decline</button>
                <button class="answer-btn" onclick="answerCall()">📞 Answer</button>
            </div>
        </div>
    `;
    
    overlay.style.display = 'flex';
}

function hideIncomingCallOverlay() {
    const overlay = document.getElementById('incomingCallOverlay');
    if (overlay) overlay.style.display = 'none';
}

function showActiveCallScreen() {
    hideIncomingCallOverlay();
    
    let overlay = document.getElementById('activeCallOverlay');
    
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'activeCallOverlay';
        overlay.className = 'call-overlay active';
        document.body.appendChild(overlay);
    }
    
    overlay.innerHTML = `
        <div class="call-overlay-content">
            <div class="caller-avatar-small">
                <img src="/static/img/default-avatar.png" alt="Avatar">
            </div>
            <h3>${currentCall.character}</h3>
            <p>Connected</p>
            <div class="call-timer" id="callTimer">00:00</div>
            <div class="audio-visualizer">
                <div class="visualizer-bar"></div>
                <div class="visualizer-bar"></div>
                <div class="visualizer-bar"></div>
                <div class="visualizer-bar"></div>
                <div class="visualizer-bar"></div>
            </div>
            <div class="call-controls">
                <button class="call-control-btn" id="muteBtn" onclick="toggleMute()">
                    <span class="icon">🎤</span>
                    <span class="label">Mute</span>
                </button>
                <button class="call-control-btn" id="speakerBtn" onclick="toggleSpeaker()">
                    <span class="icon">🔉</span>
                    <span class="label">Speaker</span>
                </button>
                <button class="call-control-btn end" onclick="endCall()">
                    <span class="icon">📵</span>
                    <span class="label">End</span>
                </button>
            </div>
        </div>
    `;
    
    overlay.style.display = 'flex';
}

function hideActiveCallOverlay() {
    const overlay = document.getElementById('activeCallOverlay');
    if (overlay) overlay.style.display = 'none';
}

function showCallEndedScreen() {
    hideActiveCallOverlay();
    
    let overlay = document.getElementById('callEndedOverlay');
    
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'callEndedOverlay';
        overlay.className = 'call-overlay ended';
        document.body.appendChild(overlay);
    }
    
    const minutes = Math.floor(callDuration / 60);
    const seconds = callDuration % 60;
    const durationStr = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    
    overlay.innerHTML = `
        <div class="call-overlay-content">
            <div class="ended-icon">📞</div>
            <h2>Call Ended</h2>
            <p>${currentCall ? currentCall.character : 'Unknown'}</p>
            <p class="call-duration">Duration: ${durationStr}</p>
            <div class="call-actions">
                <button class="call-again-btn" onclick="callAgain()">📞 Call Again</button>
                <button class="close-btn" onclick="closeCallScreen()">Close</button>
            </div>
        </div>
    `;
    
    overlay.style.display = 'flex';
    
    // Auto-close after 3 seconds
    setTimeout(() => {
        closeCallScreen();
    }, 3000);
}

function showRecordingIndicator() {
    // Add recording indicator to mic button
    const micBtn = document.querySelector('.microphone-button');
    if (micBtn) {
        micBtn.classList.add('recording');
        micBtn.textContent = '🔴';
    }
}

function hideRecordingIndicator() {
    const micBtn = document.querySelector('.microphone-button');
    if (micBtn) {
        micBtn.classList.remove('recording');
        micBtn.textContent = '🎤';
    }
}

function showCallTranscript(text, role) {
    // Optional: Show transcript during call
    console.log(`[${role}]: ${text}`);
}

function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

// initializeVoice() is called from phone.js after socket is set up
