/**
 * Video Call and Video Message Management
 */

const VideoCall = {
    socket: null,
    callId: null,
    callActive: false,
    videoEnabled: true,
    audioEnabled: true,
    callStartTime: null,
    timerInterval: null,
    userStream: null,
    
    init() {
        this.socket = io();
        this.setupSocketListeners();
    },
    
    setupSocketListeners() {
        // Video call events
        this.socket.on('video_call_started', (data) => {
            console.log('Video call started:', data);
            this.callId = data.call_id;
            this.callActive = true;
            this.updateCallStatus('Connected');
            this.startCallTimer();
            this.hideLoading();
        });
        
        this.socket.on('video_call_answered', (data) => {
            console.log('Video call answered:', data);
            this.callActive = true;
            this.updateCallStatus('Connected');
            this.startCallTimer();
        });
        
        this.socket.on('video_call_ended', (data) => {
            console.log('Video call ended:', data);
            this.endCall();
        });
        
        this.socket.on('video_frame', (data) => {
            // Update character video frame
            this.updateVideoFrame(data.frame);
        });
        
        this.socket.on('video_toggled', (data) => {
            console.log('Video toggled:', data.enabled);
        });
        
        // Error handling
        this.socket.on('error', (data) => {
            console.error('Video call error:', data.message);
            alert('Error: ' + data.message);
        });
    },
    
    async startCall() {
        console.log('Starting video call...');
        this.showLoading();
        
        // Request user camera permission
        await this.requestUserCamera();
        
        // Emit start video call event
        this.socket.emit('start_video_call', {
            type: 'outgoing'
        });
    },
    
    async joinCall(callId) {
        console.log('Joining video call:', callId);
        this.callId = callId;
        this.showLoading();
        
        // Request user camera permission
        await this.requestUserCamera();
        
        // Answer the call
        this.socket.emit('answer_video_call', {
            call_id: callId
        });
    },
    
    endCall() {
        console.log('Ending video call...');
        
        // Stop timer
        this.stopCallTimer();
        
        // Stop user video stream
        this.stopUserCamera();
        
        // Emit end call event
        if (this.callId) {
            this.socket.emit('end_video_call', {
                call_id: this.callId
            });
        }
        
        this.callActive = false;
        this.callId = null;
        
        // Close window or redirect
        setTimeout(() => {
            window.close();
        }, 500);
    },
    
    toggleVideo() {
        this.videoEnabled = !this.videoEnabled;
        
        // Toggle user video stream
        if (this.userStream) {
            const videoTrack = this.userStream.getVideoTracks()[0];
            if (videoTrack) {
                videoTrack.enabled = this.videoEnabled;
            }
        }
        
        // Update UI
        const userVideoContainer = document.getElementById('user-video-container');
        const placeholder = document.getElementById('user-video-placeholder');
        const videoBtn = document.getElementById('video-toggle-btn');
        
        if (this.videoEnabled) {
            userVideoContainer.classList.remove('video-off');
            placeholder.style.display = 'none';
            videoBtn.classList.remove('disabled');
        } else {
            userVideoContainer.classList.add('video-off');
            placeholder.style.display = 'flex';
            videoBtn.classList.add('disabled');
        }
        
        // Notify server
        this.socket.emit('toggle_video', {
            enabled: this.videoEnabled
        });
    },
    
    toggleAudio() {
        this.audioEnabled = !this.audioEnabled;
        
        // Toggle user audio stream
        if (this.userStream) {
            const audioTrack = this.userStream.getAudioTracks()[0];
            if (audioTrack) {
                audioTrack.enabled = this.audioEnabled;
            }
        }
        
        // Update UI
        const muteBtn = document.getElementById('mute-btn');
        if (this.audioEnabled) {
            muteBtn.classList.remove('muted');
            muteBtn.querySelector('.icon').textContent = '🎤';
        } else {
            muteBtn.classList.add('muted');
            muteBtn.querySelector('.icon').textContent = '🔇';
        }
    },
    
    async requestUserCamera() {
        try {
            this.userStream = await navigator.mediaDevices.getUserMedia({
                video: true,
                audio: true
            });
            
            // Display user video
            const userVideo = document.getElementById('user-video');
            userVideo.srcObject = this.userStream;
            
            // Hide placeholder
            document.getElementById('user-video-placeholder').style.display = 'none';
            
            console.log('User camera access granted');
        } catch (error) {
            console.warn('Camera access denied or not available:', error);
            // Show placeholder
            document.getElementById('user-video-placeholder').style.display = 'flex';
        }
    },
    
    stopUserCamera() {
        if (this.userStream) {
            this.userStream.getTracks().forEach(track => track.stop());
            this.userStream = null;
        }
    },
    
    updateVideoFrame(frameData) {
        const characterVideo = document.getElementById('character-video');
        characterVideo.src = `data:image/png;base64,${frameData}`;
    },
    
    updateCallStatus(status) {
        document.getElementById('call-status').textContent = status;
    },
    
    startCallTimer() {
        this.callStartTime = Date.now();
        this.timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - this.callStartTime) / 1000);
            const minutes = Math.floor(elapsed / 60);
            const seconds = elapsed % 60;
            document.getElementById('call-timer').textContent = 
                `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        }, 1000);
    },
    
    stopCallTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    },
    
    toggleFullscreen() {
        const container = document.getElementById('video-call-container');
        
        if (!document.fullscreenElement) {
            container.requestFullscreen().catch(err => {
                console.error('Fullscreen error:', err);
            });
        } else {
            document.exitFullscreen();
        }
    },
    
    showLoading() {
        document.getElementById('video-loading').style.display = 'flex';
    },
    
    hideLoading() {
        document.getElementById('video-loading').style.display = 'none';
    }
};

const VideoMessage = {
    socket: null,
    
    init(socket) {
        this.socket = socket || io();
        this.setupSocketListeners();
    },
    
    setupSocketListeners() {
        this.socket.on('video_message_received', (data) => {
            console.log('Video message received:', data);
            this.displayVideoMessage(data);
        });
    },
    
    async sendVideoMessage(text, mood = 'happy') {
        console.log('Sending video message...');
        
        // Emit video message event
        this.socket.emit('send_video_message', {
            text: text,
            mood: mood
        });
    },
    
    displayVideoMessage(messageData) {
        // This will be called from phone.js to display in chat
        const messageContainer = document.createElement('div');
        messageContainer.className = `message ${messageData.role}`;
        
        const videoElement = document.createElement('video');
        videoElement.src = messageData.url;
        videoElement.controls = true;
        videoElement.className = 'video-message';
        
        const timestampDiv = document.createElement('div');
        timestampDiv.className = 'timestamp';
        timestampDiv.textContent = new Date(messageData.timestamp).toLocaleTimeString();
        
        messageContainer.appendChild(videoElement);
        messageContainer.appendChild(timestampDiv);
        
        const messagesContainer = document.getElementById('messages-container');
        if (messagesContainer) {
            messagesContainer.appendChild(messageContainer);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    },
    
    createVideoMessagePlayer(videoData) {
        // Create a video player element for chat
        const player = document.createElement('div');
        player.className = 'video-message-player';
        player.innerHTML = `
            <video controls preload="metadata">
                <source src="${videoData.url}" type="video/mp4">
                Your browser does not support video playback.
            </video>
            <div class="video-info">
                <span class="duration">${this.formatDuration(videoData.duration)}</span>
                ${videoData.text ? `<span class="caption">${videoData.text}</span>` : ''}
            </div>
        `;
        return player;
    },
    
    formatDuration(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${String(secs).padStart(2, '0')}`;
    }
};

// Initialize when video call page loads
if (window.location.pathname.includes('video_call') || 
    document.getElementById('video-call-container')) {
    VideoCall.init();
    
    // Setup control button handlers
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('end-call-btn')?.addEventListener('click', () => {
            VideoCall.endCall();
        });
        
        document.getElementById('mute-btn')?.addEventListener('click', () => {
            VideoCall.toggleAudio();
        });
        
        document.getElementById('video-toggle-btn')?.addEventListener('click', () => {
            VideoCall.toggleVideo();
        });
        
        document.getElementById('fullscreen-btn')?.addEventListener('click', () => {
            VideoCall.toggleFullscreen();
        });
    });
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { VideoCall, VideoMessage };
}
