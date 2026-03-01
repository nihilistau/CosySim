// Intel Hub — Main JavaScript
// CosySim v0.67

'use strict';

// ══════════════════════════════════════════════════
// STATE
// ══════════════════════════════════════════════════

const state = {
  activeSection: 'overview',
  activeTtsBackend: 'piper',
  activeVttBackend: 'web_speech',
  activeMediaMode: 'image',
  autoSpeak: true,
  attachedFiles: [],
  lastReply: null,
  audioCtx: null,
  recognition: null,
  isMicActive: false,
  isWaveformAnimating: false,
  waveformAnimId: null,
  mediaAssets: { image: null, anim: null, video: null },
  chatHistory: [],
  systemPollInterval: null,
  activeNlmNotebookId: null,
};

// ══════════════════════════════════════════════════
// SOCKET.IO
// ══════════════════════════════════════════════════

let socket = null;

function initSocket() {
  try {
    socket = io({ transports: ['websocket', 'polling'] });

    socket.on('connect', () => {
      console.log('Socket connected:', socket.id);
    });

    socket.on('disconnect', () => {
      console.log('Socket disconnected');
    });

    socket.on('metrics_update', (data) => {
      if (state.activeSection === 'system') {
        updateSystemGauges(data);
      }
    });

    socket.on('activity_item', (data) => {
      if (state.activeSection === 'scheduler') {
        appendSchedulerLog(data.message || JSON.stringify(data));
      }
    });

    socket.on('state_update', (data) => {
      if (data.aria_status) setAriaStatus(data.aria_status, data.speaking || false);
      if (data.nexus_stats && state.activeSection === 'nexus') updateNexusStats(data.nexus_stats);
    });
  } catch (e) {
    console.warn('Socket.IO unavailable:', e.message);
  }
}

// ══════════════════════════════════════════════════
// API HELPER
// ══════════════════════════════════════════════════

async function api(path, options = {}) {
  const defaults = { headers: { 'Content-Type': 'application/json' } };
  if (options.body instanceof FormData) {
    // Let browser set multipart boundary
    delete defaults.headers['Content-Type'];
  }
  const res = await fetch(path, { ...defaults, ...options });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res;
}

// ══════════════════════════════════════════════════
// TOAST
// ══════════════════════════════════════════════════

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => {
    el.classList.add('removing');
    setTimeout(() => el.remove(), 280);
  }, 3220);
}

// ══════════════════════════════════════════════════
// SECTION NAVIGATION
// ══════════════════════════════════════════════════

const sectionLoaders = {
  overview: loadOverview,
  assistant: () => {},
  news: initNewsSection,
  profile: loadProfile,
  nexus: loadNexus,
  nlm: loadNlm,
  cache: loadCache,
  scheduler: loadScheduler,
  finetuning: loadFinetuning,
  benchmarks: loadBenchmarks,
  backups: loadBackups,
  copilot: loadCopilot,
  system: loadSystem,
};

function initNav() {
  document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
    btn.addEventListener('click', () => {
      const section = btn.dataset.section;
      navigateTo(section);
    });
  });
}

function navigateTo(section) {
  // Stop system polling when leaving
  if (state.activeSection === 'system' && section !== 'system') {
    clearInterval(state.systemPollInterval);
    state.systemPollInterval = null;
  }

  state.activeSection = section;

  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`.nav-item[data-section="${section}"]`);
  if (btn) btn.classList.add('active');

  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  const sec = document.getElementById(`sec-${section}`);
  if (sec) sec.classList.add('active');

  const loader = sectionLoaders[section];
  if (loader) loader();
}

// ══════════════════════════════════════════════════
// PANEL COLLAPSE
// ══════════════════════════════════════════════════

function initCollapse() {
  document.querySelectorAll('.collapse-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const body = btn.closest('.panel').querySelector('.panel-body');
      if (!body) return;
      body.classList.toggle('collapsed');
      btn.classList.toggle('collapsed');
    });
  });
}

// ══════════════════════════════════════════════════
// WAVEFORM
// ══════════════════════════════════════════════════

function drawWaveformFake(canvas, active) {
  const ctx = canvas.getContext('2d');
  const bars = 36;
  let frame = 0;

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const grad = ctx.createLinearGradient(0, 0, canvas.width, 0);
    grad.addColorStop(0, '#8b5cf6');
    grad.addColorStop(1, '#22d3ee');
    ctx.fillStyle = grad;
    const bw = canvas.width / bars - 2;
    for (let i = 0; i < bars; i++) {
      const h = active
        ? (Math.sin(frame * 0.15 + i * 0.6) * 0.5 + 0.5) * (canvas.height * 0.8) + 4
        : 4;
      const y = (canvas.height - h) / 2;
      ctx.beginPath();
      if (ctx.roundRect) {
        ctx.roundRect(i * (bw + 2), y, bw, h, 2);
      } else {
        ctx.rect(i * (bw + 2), y, bw, h);
      }
      ctx.fill();
    }
    frame++;
    if (active || frame < 10) {
      state.waveformAnimId = requestAnimationFrame(draw);
    } else {
      state.isWaveformAnimating = false;
    }
  }

  cancelAnimationFrame(state.waveformAnimId);
  state.isWaveformAnimating = true;
  draw();
}

// ══════════════════════════════════════════════════
// AUDIO STRIP
// ══════════════════════════════════════════════════

function showAudioStrip() {
  document.getElementById('audio-strip').classList.add('visible');
}

function hideAudioStrip() {
  document.getElementById('audio-strip').classList.remove('visible');
  const player = document.getElementById('audio-player');
  player.pause();
}

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function initAudioStrip() {
  const player = document.getElementById('audio-player');
  const fill = document.getElementById('audio-progress-fill');
  const timeEl = document.getElementById('audio-time');
  const playBtn = document.getElementById('btn-audio-play');
  const closeBtn = document.getElementById('btn-audio-close');
  const audioWave = document.getElementById('audio-waveform');

  player.addEventListener('timeupdate', () => {
    if (!player.duration) return;
    const pct = (player.currentTime / player.duration) * 100;
    fill.style.width = `${pct}%`;
    timeEl.textContent = formatTime(player.currentTime);
  });

  player.addEventListener('ended', () => {
    playBtn.textContent = '▶';
    drawWaveformFake(audioWave, false);
    setAriaStatus('Ready', false);
    document.getElementById('media-frame').classList.remove('speaking');
    document.getElementById('status-dot').classList.remove('pulse');
  });

  playBtn.addEventListener('click', () => {
    if (player.paused) {
      player.play();
      playBtn.textContent = '⏸';
      drawWaveformFake(audioWave, true);
    } else {
      player.pause();
      playBtn.textContent = '▶';
      drawWaveformFake(audioWave, false);
    }
  });

  closeBtn.addEventListener('click', () => {
    hideAudioStrip();
    drawWaveformFake(audioWave, false);
  });
}

// ══════════════════════════════════════════════════
// ARIA STATUS
// ══════════════════════════════════════════════════

function setAriaStatus(text, pulse = false) {
  const el = document.getElementById('aria-status');
  const dot = document.getElementById('status-dot');
  if (el) el.textContent = text;
  if (dot) {
    if (pulse) dot.classList.add('pulse');
    else dot.classList.remove('pulse');
  }
}

// ══════════════════════════════════════════════════
// CHAT
// ══════════════════════════════════════════════════

function addMessage(role, text) {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `msg msg-${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = role === 'aria' ? 'A' : 'U';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.textContent = text;

  div.appendChild(avatar);
  div.appendChild(bubble);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;

  state.chatHistory.push({ role, text });
}

async function sendChatMessage() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text && state.attachedFiles.length === 0) return;

  input.value = '';
  input.style.height = '';

  if (text) addMessage('user', text);

  const statusEl = document.getElementById('chat-status');
  statusEl.style.display = 'block';
  statusEl.textContent = 'Aria is thinking...';
  setAriaStatus('Thinking...', true);
  document.getElementById('btn-send').disabled = true;

  try {
    let body;
    let fetchOpts;

    if (state.attachedFiles.length > 0) {
      const fd = new FormData();
      fd.append('message', text);
      state.attachedFiles.forEach(f => fd.append('files', f));
      fetchOpts = { method: 'POST', body: fd };
    } else {
      fetchOpts = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history: state.chatHistory.slice(-10) }),
      };
    }

    const data = await fetch('/api/assistant/chat', fetchOpts).then(r => r.json());
    const reply = data.reply || data.message || 'Sorry, I had trouble responding.';

    state.lastReply = reply;
    addMessage('aria', reply);
    clearAttachments();

    if (state.autoSpeak) {
      synthesizeAndPlay(reply);
    } else {
      setAriaStatus('Ready', false);
    }
  } catch (err) {
    addMessage('aria', 'Error connecting to assistant. Please check the server.');
    toast('Chat API error: ' + err.message, 'error');
    setAriaStatus('Error', false);
  } finally {
    statusEl.style.display = 'none';
    document.getElementById('btn-send').disabled = false;
  }
}

function clearAttachments() {
  state.attachedFiles = [];
  const el = document.getElementById('chat-attachments');
  el.innerHTML = '';
  el.style.display = 'none';
}

function addAttachmentChip(file) {
  const el = document.getElementById('chat-attachments');
  el.style.display = 'flex';

  const chip = document.createElement('div');
  chip.className = 'attachment-chip';
  chip.innerHTML = `📎 ${file.name} <button title="Remove">✕</button>`;
  chip.querySelector('button').addEventListener('click', () => {
    state.attachedFiles = state.attachedFiles.filter(f => f !== file);
    chip.remove();
    if (state.attachedFiles.length === 0) el.style.display = 'none';
  });
  el.appendChild(chip);
}

function initChat() {
  const sendBtn = document.getElementById('btn-send');
  const input = document.getElementById('chat-input');
  const clearBtn = document.getElementById('btn-clear-chat');
  const autospeakBtn = document.getElementById('btn-autospeak');
  const replayBtn = document.getElementById('btn-replay-last');
  const attachBtn = document.getElementById('btn-attach-file');
  const fileInput = document.getElementById('file-attach-input');
  const micQuickBtn = document.getElementById('btn-mic-quick');

  sendBtn.addEventListener('click', sendChatMessage);

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  clearBtn.addEventListener('click', () => {
    document.getElementById('chat-messages').innerHTML = '';
    state.chatHistory = [];
    addMessage('aria', 'Chat cleared. How can I help you?');
  });

  autospeakBtn.addEventListener('click', () => {
    state.autoSpeak = !state.autoSpeak;
    autospeakBtn.classList.toggle('active', state.autoSpeak);
    toast(state.autoSpeak ? 'Auto-speak ON' : 'Auto-speak OFF', 'info');
  });

  replayBtn.addEventListener('click', () => {
    if (state.lastReply) {
      synthesizeAndPlay(state.lastReply);
    } else {
      toast('No previous reply to replay', 'info');
    }
  });

  attachBtn.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', (e) => {
    [...e.target.files].forEach(file => {
      state.attachedFiles.push(file);
      addAttachmentChip(file);
    });
    fileInput.value = '';
  });

  micQuickBtn.addEventListener('mousedown', () => startQuickMic());
  micQuickBtn.addEventListener('mouseup', () => stopQuickMic());
  micQuickBtn.addEventListener('mouseleave', () => stopQuickMic());
}

// ══════════════════════════════════════════════════
// TTS — SYNTHESIZE AND PLAY
// ══════════════════════════════════════════════════

async function synthesizeAndPlay(text) {
  if (!text) return;

  setAriaStatus('Speaking...', true);
  document.getElementById('media-frame').classList.add('speaking');

  const backend = state.activeTtsBackend;
  const payload = { text, backend };

  if (backend === 'piper') {
    payload.voice = document.getElementById('piper-voice').value;
    payload.speed = parseFloat(document.getElementById('piper-speed').value);
  } else if (backend === 'orpheus') {
    payload.voice = document.getElementById('orpheus-voice').value;
  } else if (backend === 'orpheus_native') {
    payload.voice = document.getElementById('native-voice').value;
    payload.layers = parseInt(document.getElementById('native-layers').value, 10);
  } else if (backend === 'qwen3') {
    payload.voice_design = document.getElementById('qwen3-design').value;
    payload.model = document.getElementById('qwen3-model').value;
  }

  try {
    const res = await fetch('/api/assistant/voice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(`TTS API error: ${res.status}`);

    const rtf = res.headers.get('X-TTS-RTF');
    const latency = res.headers.get('X-TTS-Latency-Ms');

    if (rtf) {
      const badge = document.getElementById('tts-rtf');
      if (badge) badge.textContent = `RTF: ${parseFloat(rtf).toFixed(2)}`;
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);

    const player = document.getElementById('audio-player');
    player.src = url;
    player.load();
    player.play();

    document.getElementById('btn-audio-play').textContent = '⏸';
    showAudioStrip();
    drawWaveformFake(document.getElementById('audio-waveform'), true);
    drawWaveformFake(document.getElementById('tts-waveform'), true);

    if (latency) toast(`TTS: ${latency}ms latency`, 'info');
  } catch (err) {
    setAriaStatus('TTS Error', false);
    document.getElementById('media-frame').classList.remove('speaking');
    toast('TTS error: ' + err.message, 'error');
  }
}

// ══════════════════════════════════════════════════
// TTS PANEL
// ══════════════════════════════════════════════════

function initTtsPanel() {
  // Backend tabs
  document.querySelectorAll('.btn-backend').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-backend').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.activeTtsBackend = btn.dataset.backend;

      document.querySelectorAll('.tts-config').forEach(c => c.classList.remove('active'));
      const cfg = document.querySelector(`.tts-config[data-for="${btn.dataset.backend}"]`);
      if (cfg) cfg.classList.add('active');
    });
  });

  // Piper speed slider
  const speedSlider = document.getElementById('piper-speed');
  const speedVal = document.getElementById('piper-speed-val');
  if (speedSlider && speedVal) {
    speedSlider.addEventListener('input', () => {
      speedVal.textContent = parseFloat(speedSlider.value).toFixed(1);
    });
  }

  // Native layers slider
  const layersSlider = document.getElementById('native-layers');
  const layersVal = document.getElementById('native-layers-val');
  if (layersSlider && layersVal) {
    layersSlider.addEventListener('input', () => {
      layersVal.textContent = layersSlider.value;
    });
  }

  // TTS test button
  document.getElementById('btn-tts-test').addEventListener('click', () => {
    const text = document.getElementById('tts-test-text').value.trim();
    if (text) synthesizeAndPlay(text);
  });

  // Emotion chips — insert at cursor
  document.querySelectorAll('.emotion-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const tag = chip.dataset.tag;
      const input = document.getElementById('tts-test-text');
      const pos = input.selectionStart;
      const val = input.value;
      input.value = val.slice(0, pos) + tag + val.slice(pos);
      input.selectionStart = input.selectionEnd = pos + tag.length;
      input.focus();
    });
  });

  // Load voices from server
  loadTtsVoices();
}

async function loadTtsVoices() {
  try {
    const data = await api('/api/tts/voices');
    if (data.piper && Array.isArray(data.piper)) {
      const sel = document.getElementById('piper-voice');
      if (sel && data.piper.length > 0) {
        sel.innerHTML = data.piper.map(v =>
          `<option value="${v.id}">${v.name}</option>`
        ).join('');
      }
    }
    if (data.orpheus && Array.isArray(data.orpheus)) {
      const sel = document.getElementById('orpheus-voice');
      if (sel && data.orpheus.length > 0) {
        sel.innerHTML = data.orpheus.map(v =>
          `<option value="${v.id}">${v.name}</option>`
        ).join('');
      }
    }
  } catch (e) {
    // Use defaults from HTML
  }
}

// ══════════════════════════════════════════════════
// VTT PANEL
// ══════════════════════════════════════════════════

function initVttPanel() {
  document.querySelectorAll('.btn-vtt-backend').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-vtt-backend').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.activeVttBackend = btn.dataset.backend;

      document.querySelectorAll('.vtt-config').forEach(c => c.classList.remove('active'));
      const cfg = document.querySelector(`.vtt-config[data-for="${btn.dataset.backend}"]`);
      if (cfg) cfg.classList.add('active');
    });
  });

  const micBtn = document.getElementById('btn-vtt-mic');
  micBtn.addEventListener('mousedown', startVttRecording);
  micBtn.addEventListener('mouseup', stopVttRecording);
  micBtn.addEventListener('mouseleave', stopVttRecording);
  micBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startVttRecording(); });
  micBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopVttRecording(); });

  const vttUpload = document.getElementById('vtt-file-upload');
  if (vttUpload) {
    vttUpload.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      try {
        const data = await fetch('/api/assistant/listen', { method: 'POST', body: fd }).then(r => r.json());
        document.getElementById('vtt-transcript').textContent = data.transcript || '(no transcript)';
        document.getElementById('chat-input').value = data.transcript || '';
      } catch (err) {
        toast('Whisper upload error: ' + err.message, 'error');
      }
    });
  }
}

function initWebSpeech() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return null;

  const rec = new SpeechRecognition();
  const lang = document.getElementById('ws-lang');
  const cont = document.getElementById('ws-continuous');
  const interim = document.getElementById('ws-interim');

  rec.lang = lang ? lang.value : 'en-US';
  rec.continuous = cont ? cont.checked : true;
  rec.interimResults = interim ? interim.checked : true;

  rec.onresult = (e) => {
    let transcript = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      transcript += e.results[i][0].transcript;
    }
    document.getElementById('vtt-transcript').textContent = transcript;
    document.getElementById('chat-input').value = transcript;
  };

  rec.onerror = (e) => {
    toast('Speech recognition error: ' + e.error, 'error');
    stopVttRecording();
  };

  return rec;
}

function startVttRecording() {
  if (state.isMicActive) return;
  state.isMicActive = true;
  document.getElementById('btn-vtt-mic').classList.add('active');

  if (state.activeVttBackend === 'web_speech') {
    state.recognition = initWebSpeech();
    if (state.recognition) state.recognition.start();
    else toast('Web Speech API not supported in this browser', 'error');
  } else if (state.activeVttBackend === 'whisper') {
    toast('Whisper: recording started — release to transcribe', 'info');
  }
}

function stopVttRecording() {
  if (!state.isMicActive) return;
  state.isMicActive = false;
  document.getElementById('btn-vtt-mic').classList.remove('active');

  if (state.recognition) {
    state.recognition.stop();
    state.recognition = null;
  }
}

// Quick mic capture for chat input
let quickRecognition = null;

function startQuickMic() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) { toast('Web Speech not supported', 'error'); return; }

  quickRecognition = new SpeechRecognition();
  quickRecognition.lang = 'en-US';
  quickRecognition.continuous = false;
  quickRecognition.interimResults = false;

  quickRecognition.onresult = (e) => {
    const text = e.results[0][0].transcript;
    document.getElementById('chat-input').value = text;
  };

  quickRecognition.start();
  document.getElementById('btn-mic-quick').classList.add('active');
}

function stopQuickMic() {
  if (quickRecognition) {
    quickRecognition.stop();
    quickRecognition = null;
  }
  document.getElementById('btn-mic-quick').classList.remove('active');
}

// ══════════════════════════════════════════════════
// MEDIA FRAME
// ══════════════════════════════════════════════════

function initMediaFrame() {
  document.querySelectorAll('.btn-media-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-media-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.activeMediaMode = btn.dataset.mode;

      document.getElementById('media-img').style.display = 'none';
      document.getElementById('media-anim').style.display = 'none';
      document.getElementById('media-video').style.display = 'none';

      const el = document.getElementById(`media-${btn.dataset.mode === 'image' ? 'img' : btn.dataset.mode === 'anim' ? 'anim' : 'video'}`);
      if (el) el.style.display = 'block';
    });
  });

  document.getElementById('media-upload').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    const isVideo = file.type.startsWith('video/');

    if (isVideo) {
      document.getElementById('media-video').src = url;
      state.mediaAssets.video = url;
    } else if (file.name.match(/\.(gif|webp)$/i)) {
      document.getElementById('media-anim').src = url;
      state.mediaAssets.anim = url;
    } else {
      document.getElementById('media-img').src = url;
      state.mediaAssets.image = url;
    }

    toast(`Media uploaded: ${file.name}`, 'success');
  });
}

// ══════════════════════════════════════════════════
// NEXUS SECTION
// ══════════════════════════════════════════════════

async function loadNexus() {
  try {
    const [status, entries] = await Promise.all([
      api('/api/nexus/status').catch(() => null),
      api('/api/nexus/entries').catch(() => null),
    ]);

    if (status) updateNexusStats(status);
    if (entries && Array.isArray(entries.items)) renderNexusEntries(entries.items);
  } catch (e) {
    toast('Failed to load Nexus data', 'error');
  }
}

function updateNexusStats(s) {
  if (s.entries !== undefined) document.getElementById('nexus-entries').textContent = s.entries;
  if (s.qa_pairs !== undefined) document.getElementById('nexus-qa').textContent = s.qa_pairs;
  if (s.rules !== undefined) document.getElementById('nexus-rules').textContent = s.rules;
  if (s.hit_rate !== undefined) document.getElementById('nexus-hitrate').textContent = (s.hit_rate * 100).toFixed(1) + '%';
}

function renderNexusEntries(items) {
  const tbody = document.getElementById('nexus-entries-body');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-mute);text-align:center;padding:24px;">No entries found.</td></tr>';
    return;
  }
  tbody.innerHTML = items.slice(0, 50).map(item => `
    <tr>
      <td>${escHtml(item.title || '')}</td>
      <td><span class="badge badge-info">${escHtml(item.content_type || 'note')}</span></td>
      <td><span class="badge badge-violet">${escHtml(item.category || '')}</span></td>
      <td style="color:var(--text-mute)">${item.updated_at ? new Date(item.updated_at).toLocaleDateString() : '—'}</td>
      <td><div class="td-actions">
        <button class="btn-table btn-table-danger" data-id="${item.id}" onclick="deleteNexusEntry('${item.id}')">Delete</button>
      </div></td>
    </tr>
  `).join('');
}

function initNexusSection() {
  document.getElementById('btn-nexus-search').addEventListener('click', async () => {
    const q = document.getElementById('nexus-search-input').value.trim();
    if (!q) return;
    try {
      const data = await api(`/api/nexus/entries?q=${encodeURIComponent(q)}`);
      if (data.items) renderNexusEntries(data.items);
    } catch (e) {
      toast('Search failed', 'error');
    }
  });

  document.getElementById('nexus-search-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('btn-nexus-search').click();
  });

  document.getElementById('btn-nexus-refresh').addEventListener('click', loadNexus);

  document.getElementById('btn-nexus-add').addEventListener('click', async () => {
    const title = document.getElementById('nexus-add-title').value.trim();
    const content = document.getElementById('nexus-add-content').value.trim();
    const category = document.getElementById('nexus-add-category').value;
    if (!title || !content) { toast('Title and content required', 'error'); return; }
    try {
      await api('/api/nexus/entries', {
        method: 'POST',
        body: JSON.stringify({ title, content, category, content_type: 'note' }),
      });
      toast('Entry added', 'success');
      document.getElementById('nexus-add-title').value = '';
      document.getElementById('nexus-add-content').value = '';
      loadNexus();
    } catch (e) {
      toast('Failed to add entry: ' + e.message, 'error');
    }
  });
}

async function deleteNexusEntry(id) {
  try {
    await api(`/api/nexus/entries/${id}`, { method: 'DELETE' });
    toast('Entry deleted', 'success');
    loadNexus();
  } catch (e) {
    toast('Delete failed', 'error');
  }
}

// ══════════════════════════════════════════════════
// NLM SECTION
// ══════════════════════════════════════════════════

async function loadNlm() {
  try {
    const data = await api('/api/nlm/notebooks');
    renderNlmNotebooks(data.notebooks || []);
  } catch (e) {
    document.getElementById('nlm-notebooks-body').innerHTML =
      '<tr><td colspan="5" style="color:var(--text-mute);text-align:center;padding:24px;">Could not load notebooks.</td></tr>';
  }
}

function renderNlmNotebooks(notebooks) {
  const tbody = document.getElementById('nlm-notebooks-body');
  if (!notebooks.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-mute);text-align:center;padding:24px;">No notebooks yet.</td></tr>';
    return;
  }
  tbody.innerHTML = notebooks.map(nb => `
    <tr>
      <td>${escHtml(nb.name || '')}</td>
      <td style="font-family:monospace;font-size:11px;color:var(--text-mute)">${escHtml(nb.id || '')}</td>
      <td>${nb.source_count || 0}</td>
      <td><span class="badge badge-${nb.status === 'ready' ? 'success' : 'pending'}">${escHtml(nb.status || 'unknown')}</span></td>
      <td><div class="td-actions">
        <button class="btn-table btn-table-primary" onclick="openNlmNotebook('${nb.id}', '${escHtml(nb.name)}')">Ask</button>
        <button class="btn-table" onclick="generateNlmDoc('${nb.id}')">Generate</button>
      </div></td>
    </tr>
  `).join('');
}

function openNlmNotebook(id, name) {
  state.activeNlmNotebookId = id;
  document.getElementById('nlm-active-nb-name').textContent = name;
  document.getElementById('nlm-ask-panel').style.display = 'block';
  document.getElementById('nlm-ask-input').focus();
}

async function generateNlmDoc(notebookId) {
  try {
    await api('/api/nlm/generate', {
      method: 'POST',
      body: JSON.stringify({ notebook_id: notebookId, type: 'study_guide' }),
    });
    toast('Document generation started', 'success');
  } catch (e) {
    toast('Generate failed: ' + e.message, 'error');
  }
}

function initNlmSection() {
  const toggleBtn = document.getElementById('btn-create-notebook-toggle');
  const form = document.getElementById('create-notebook-form');

  toggleBtn.addEventListener('click', () => {
    const visible = form.style.display !== 'none';
    form.style.display = visible ? 'none' : 'block';
    toggleBtn.textContent = visible ? '＋ New Notebook' : '✕ Cancel';
  });

  document.getElementById('btn-nlm-cancel').addEventListener('click', () => {
    form.style.display = 'none';
    toggleBtn.textContent = '＋ New Notebook';
  });

  document.getElementById('btn-nlm-create').addEventListener('click', async () => {
    const name = document.getElementById('nlm-nb-name').value.trim();
    const topic = document.getElementById('nlm-nb-topic').value.trim();
    const sourcesRaw = document.getElementById('nlm-nb-sources').value.trim();
    if (!name) { toast('Notebook name required', 'error'); return; }
    const sources = sourcesRaw.split('\n').map(s => s.trim()).filter(Boolean);
    try {
      await api('/api/nlm/notebooks', {
        method: 'POST',
        body: JSON.stringify({ name, topic, sources }),
      });
      toast('Notebook created', 'success');
      document.getElementById('nlm-nb-name').value = '';
      document.getElementById('nlm-nb-topic').value = '';
      document.getElementById('nlm-nb-sources').value = '';
      form.style.display = 'none';
      toggleBtn.textContent = '＋ New Notebook';
      loadNlm();
    } catch (e) {
      toast('Create failed: ' + e.message, 'error');
    }
  });

  document.getElementById('btn-nlm-ask').addEventListener('click', async () => {
    const question = document.getElementById('nlm-ask-input').value.trim();
    if (!question || !state.activeNlmNotebookId) return;
    const resultEl = document.getElementById('nlm-ask-result');
    resultEl.style.display = 'block';
    resultEl.textContent = 'Asking NLM...';
    try {
      const data = await api('/api/nlm/ask', {
        method: 'POST',
        body: JSON.stringify({ notebook_id: state.activeNlmNotebookId, question }),
      });
      resultEl.textContent = data.answer || '(no answer)';
    } catch (e) {
      resultEl.textContent = 'Error: ' + e.message;
    }
  });

  document.getElementById('nlm-ask-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('btn-nlm-ask').click();
  });
}

// ══════════════════════════════════════════════════
// CACHE SECTION
// ══════════════════════════════════════════════════

async function loadCache() {
  try {
    const data = await api('/api/cache/status');
    if (data.total_pairs !== undefined) document.getElementById('cache-pairs').textContent = data.total_pairs;
    if (data.essential !== undefined) document.getElementById('cache-essential').textContent = data.essential;
    if (data.useful !== undefined) document.getElementById('cache-useful').textContent = data.useful;
    if (data.next_run) document.getElementById('cache-next-run').textContent = data.next_run;
    if (data.last_cycle) document.getElementById('cache-last-cycle').textContent = data.last_cycle;
    if (data.status) {
      const statusEl = document.getElementById('cache-pipeline-status');
      const badgeClass = data.status === 'running' ? 'badge-info' : data.status === 'error' ? 'badge-error' : 'badge-success';
      statusEl.innerHTML = `<span class="badge ${badgeClass}">${data.status}</span>`;
    }
    if (data.gaps && Array.isArray(data.gaps)) renderCacheGaps(data.gaps);
    if (data.review_sheets && Array.isArray(data.review_sheets)) renderCacheReviews(data.review_sheets);
  } catch (e) {
    document.getElementById('cache-pairs').textContent = '—';
  }
}

function renderCacheGaps(gaps) {
  const el = document.getElementById('cache-gaps-list');
  if (!gaps.length) {
    el.innerHTML = '<div style="color:var(--text-mute);font-size:13px;text-align:center;padding:16px;">No coverage gaps detected.</div>';
    return;
  }
  el.innerHTML = gaps.map(g => `
    <div class="gap-item">
      <span class="gap-item-topic">${escHtml(g.topic || g)}</span>
      <span class="gap-item-count">${g.missing || 0} missing</span>
      <button class="btn-table btn-table-primary" onclick="generateGapQA('${escHtml(g.topic || g)}')">Fill</button>
    </div>
  `).join('');
}

async function generateGapQA(topic) {
  try {
    await api('/api/cache/generate', { method: 'POST', body: JSON.stringify({ topic }) });
    toast(`Generating QA for: ${topic}`, 'info');
  } catch (e) {
    toast('Failed to generate QA', 'error');
  }
}

function renderCacheReviews(sheets) {
  const tbody = document.getElementById('cache-reviews-body');
  if (!sheets.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-mute);text-align:center;padding:24px;">No review sheets yet.</td></tr>';
    return;
  }
  tbody.innerHTML = sheets.map(s => `
    <tr>
      <td>${s.date || '—'}</td>
      <td>${escHtml(s.topic || '—')}</td>
      <td>${s.pairs_added || 0}</td>
      <td>${s.coverage ? (s.coverage * 100).toFixed(0) + '%' : '—'}</td>
      <td><button class="btn-table" onclick="viewReviewSheet('${s.id}')">View</button></td>
    </tr>
  `).join('');
}

function initCacheSection() {
  document.getElementById('btn-run-pipeline').addEventListener('click', async () => {
    try {
      await api('/api/cache/pipeline/run', { method: 'POST' });
      toast('Cache pipeline started', 'info');
      setTimeout(loadCache, 2000);
    } catch (e) {
      toast('Pipeline start failed: ' + e.message, 'error');
    }
  });
}

// ══════════════════════════════════════════════════
// SCHEDULER SECTION
// ══════════════════════════════════════════════════

async function loadScheduler() {
  try {
    const data = await api('/api/scheduler/tasks');
    renderSchedulerTasks(data.tasks || []);
  } catch (e) {
    document.getElementById('scheduler-tasks-body').innerHTML =
      '<tr><td colspan="6" style="color:var(--text-mute);text-align:center;padding:24px;">Could not load tasks.</td></tr>';
  }
}

function renderSchedulerTasks(tasks) {
  const tbody = document.getElementById('scheduler-tasks-body');
  if (!tasks.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-mute);text-align:center;padding:24px;">No scheduled tasks.</td></tr>';
    return;
  }
  tbody.innerHTML = tasks.map(t => {
    const statusClass = t.status === 'running' ? 'badge-info' : t.status === 'done' ? 'badge-success' : t.status === 'error' ? 'badge-error' : 'badge-pending';
    return `
      <tr>
        <td>${escHtml(t.name || t.id)}</td>
        <td style="color:var(--text-mute)">${escHtml(t.schedule || '—')}</td>
        <td style="color:var(--text-mute)">${t.last_run || '—'}</td>
        <td style="color:var(--text-mute)">${t.next_run || '—'}</td>
        <td><span class="badge ${statusClass}">${t.status || 'pending'}</span></td>
        <td><button class="btn-table btn-table-primary" onclick="runSchedulerTask('${t.id}')">▶ Run Now</button></td>
      </tr>
    `;
  }).join('');
}

async function runSchedulerTask(taskId) {
  try {
    await api(`/api/scheduler/tasks/${taskId}/run`, { method: 'POST' });
    toast(`Task ${taskId} triggered`, 'info');
    setTimeout(loadScheduler, 1500);
  } catch (e) {
    toast('Task run failed: ' + e.message, 'error');
  }
}

function appendSchedulerLog(msg) {
  const log = document.getElementById('scheduler-log');
  const ts = new Date().toLocaleTimeString();
  log.textContent += `\n[${ts}] ${msg}`;
  log.scrollTop = log.scrollHeight;
}

function initSchedulerSection() {
  document.getElementById('btn-refresh-scheduler').addEventListener('click', loadScheduler);
}

// ══════════════════════════════════════════════════
// FINE-TUNING SECTION
// ══════════════════════════════════════════════════

async function loadFinetuning() {
  try {
    const data = await api('/api/finetuning/status');
    renderFtModels(data.models || []);
    renderFtJobs(data.jobs || []);
  } catch (e) {
    document.getElementById('finetune-models-grid').innerHTML =
      '<div style="color:var(--text-mute);font-size:13px;">Could not load fine-tuning data.</div>';
  }
}

function renderFtModels(models) {
  const grid = document.getElementById('finetune-models-grid');
  if (!models.length) {
    grid.innerHTML = '<div style="color:var(--text-mute);font-size:13px;text-align:center;padding:24px;">No models available.</div>';
    return;
  }
  grid.innerHTML = models.map(m => `
    <div class="model-card">
      <div class="model-card-name">${escHtml(m.name || m.id)}</div>
      <div class="model-card-meta">${escHtml(m.size || '')} · ${escHtml(m.arch || '')}</div>
      <span class="badge badge-${m.status === 'ready' ? 'success' : 'pending'}">${escHtml(m.status || 'unknown')}</span>
    </div>
  `).join('');
}

function renderFtJobs(jobs) {
  const tbody = document.getElementById('finetune-jobs-body');
  if (!jobs.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-mute);text-align:center;padding:24px;">No training jobs.</td></tr>';
    return;
  }
  tbody.innerHTML = jobs.map(j => `
    <tr>
      <td>${escHtml(j.name || j.id)}</td>
      <td>${escHtml(j.base_model || '—')}</td>
      <td style="color:var(--text-mute)">${escHtml(j.dataset || '—')}</td>
      <td style="min-width:100px;">
        <div class="progress-bar"><div class="progress-fill" style="width:${j.progress || 0}%"></div></div>
        <div style="font-size:11px;color:var(--text-mute);margin-top:3px;">${j.progress || 0}%</div>
      </td>
      <td><span class="badge badge-${j.status === 'running' ? 'info' : j.status === 'done' ? 'success' : 'pending'}">${escHtml(j.status || 'pending')}</span></td>
      <td><button class="btn-table btn-table-danger" onclick="cancelFtJob('${j.id}')">Cancel</button></td>
    </tr>
  `).join('');
}

async function cancelFtJob(jobId) {
  try {
    await api(`/api/finetuning/jobs/${jobId}/cancel`, { method: 'POST' });
    toast('Job cancelled', 'info');
    setTimeout(loadFinetuning, 1000);
  } catch (e) {
    toast('Cancel failed', 'error');
  }
}

function initFinetuningSection() {
  document.getElementById('btn-launch-ft').addEventListener('click', async () => {
    const baseModel = document.getElementById('ft-base-model').value;
    const dataset = document.getElementById('ft-dataset').value.trim();
    const epochs = parseInt(document.getElementById('ft-epochs').value, 10);
    const batchSize = parseInt(document.getElementById('ft-batch').value, 10);
    if (!dataset) { toast('Dataset path required', 'error'); return; }
    try {
      await api('/api/finetuning/jobs', {
        method: 'POST',
        body: JSON.stringify({ base_model: baseModel, dataset, epochs, batch_size: batchSize }),
      });
      toast('Training job launched', 'success');
      loadFinetuning();
    } catch (e) {
      toast('Launch failed: ' + e.message, 'error');
    }
  });
}

// ══════════════════════════════════════════════════
// BENCHMARKS SECTION
// ══════════════════════════════════════════════════

async function loadBenchmarks() {
  try {
    const data = await api('/api/benchmarks/latest');
    renderBenchmarkResults(data.results || []);
  } catch (e) {
    document.getElementById('benchmarks-body').innerHTML =
      '<tr><td colspan="7" style="color:var(--text-mute);text-align:center;padding:24px;">Could not load benchmarks.</td></tr>';
  }
}

function renderBenchmarkResults(results) {
  const tbody = document.getElementById('benchmarks-body');
  if (!results.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-mute);text-align:center;padding:24px;">No results yet.</td></tr>';
    return;
  }
  tbody.innerHTML = results.map(r => `
    <tr>
      <td>${escHtml(r.model || '—')}</td>
      <td style="color:var(--emerald)">${r.tokens_per_sec ? r.tokens_per_sec.toFixed(1) : '—'}</td>
      <td style="color:var(--cyan)">${r.rtf ? r.rtf.toFixed(3) : '—'}</td>
      <td style="color:var(--text-dim)">${r.latency_ms ? r.latency_ms.toFixed(0) : '—'}</td>
      <td style="color:var(--text-mute)">${r.vram_mb || '—'}</td>
      <td style="color:var(--text-mute)">${r.date || '—'}</td>
      <td><canvas class="sparkline" width="60" height="20" data-trend="${r.trend || ''}"></canvas></td>
    </tr>
  `).join('');
  // Draw sparklines
  tbody.querySelectorAll('.sparkline[data-trend]').forEach(canvas => {
    drawSparkline(canvas, (canvas.dataset.trend || '').split(',').map(Number).filter(Boolean));
  });
}

function drawSparkline(canvas, values) {
  if (!values.length) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  ctx.strokeStyle = '#8b5cf6';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function initBenchmarksSection() {
  document.getElementById('btn-run-benchmark').addEventListener('click', async () => {
    const model = document.getElementById('bench-model').value;
    const iters = parseInt(document.getElementById('bench-iters').value, 10);
    const promptLen = document.getElementById('bench-prompt-len').value;
    try {
      await api('/api/benchmarks/run', {
        method: 'POST',
        body: JSON.stringify({ model, iterations: iters, prompt_length: promptLen }),
      });
      toast('Benchmark started', 'info');
      setTimeout(loadBenchmarks, 3000);
    } catch (e) {
      toast('Benchmark failed: ' + e.message, 'error');
    }
  });
}

// ══════════════════════════════════════════════════
// BACKUPS SECTION
// ══════════════════════════════════════════════════

async function loadBackups() {
  try {
    const data = await api('/api/backups/list');
    renderBackups(data.backups || []);
    // Populate restore select
    const sel = document.getElementById('restore-select');
    sel.innerHTML = '<option value="">— select a backup —</option>' +
      (data.backups || []).map(b => `<option value="${b.id}">${b.date} — ${b.label || b.id}</option>`).join('');
  } catch (e) {
    document.getElementById('backups-body').innerHTML =
      '<tr><td colspan="6" style="color:var(--text-mute);text-align:center;padding:24px;">Could not load backups.</td></tr>';
  }
}

function renderBackups(backups) {
  const tbody = document.getElementById('backups-body');
  if (!backups.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-mute);text-align:center;padding:24px;">No backups yet.</td></tr>';
    return;
  }
  tbody.innerHTML = backups.map(b => `
    <tr>
      <td>${escHtml(b.date || '—')}</td>
      <td>${escHtml(b.label || b.id)}</td>
      <td style="color:var(--text-mute)">${escHtml(b.size || '—')}</td>
      <td style="color:var(--text-mute)">${(b.targets || []).join(', ') || '—'}</td>
      <td><span class="badge badge-${b.status === 'ok' ? 'success' : 'error'}">${escHtml(b.status || '—')}</span></td>
      <td><div class="td-actions">
        <button class="btn-table" onclick="downloadBackup('${b.id}')">⬇ Download</button>
        <button class="btn-table btn-table-danger" onclick="deleteBackup('${b.id}')">Delete</button>
      </div></td>
    </tr>
  `).join('');
}

function initBackupsSection() {
  document.getElementById('btn-run-backup').addEventListener('click', async () => {
    try {
      await api('/api/backups/run', { method: 'POST' });
      toast('Backup started', 'info');
      setTimeout(loadBackups, 3000);
    } catch (e) {
      toast('Backup failed: ' + e.message, 'error');
    }
  });

  document.getElementById('btn-restore').addEventListener('click', async () => {
    const backupId = document.getElementById('restore-select').value;
    const target = document.getElementById('restore-target').value;
    if (!backupId) { toast('Select a backup first', 'error'); return; }
    if (!confirm(`Restore ${target} from ${backupId}? This may overwrite current data.`)) return;
    try {
      await api('/api/backups/restore', {
        method: 'POST',
        body: JSON.stringify({ backup_id: backupId, target }),
      });
      toast('Restore initiated', 'success');
    } catch (e) {
      toast('Restore failed: ' + e.message, 'error');
    }
  });
}

async function downloadBackup(id) {
  window.open(`/api/backups/${id}/download`, '_blank');
}

async function deleteBackup(id) {
  if (!confirm('Delete this backup?')) return;
  try {
    await api(`/api/backups/${id}`, { method: 'DELETE' });
    toast('Backup deleted', 'success');
    loadBackups();
  } catch (e) {
    toast('Delete failed', 'error');
  }
}

// ══════════════════════════════════════════════════
// COPILOT SECTION
// ══════════════════════════════════════════════════

async function loadCopilot() {
  try {
    const data = await api('/api/copilot/rules');
    renderCopilotRules(data.rules || []);
    renderCopilotAgents(data.agents || []);
    renderCopilotHooks(data.hooks || []);
  } catch (e) {
    document.getElementById('copilot-rules-list').innerHTML =
      '<div style="color:var(--text-mute);font-size:13px;text-align:center;padding:24px;">Could not load Copilot data.</div>';
  }
}

function renderCopilotRules(rules) {
  const el = document.getElementById('copilot-rules-list');
  if (!rules.length) {
    el.innerHTML = '<div style="color:var(--text-mute);font-size:13px;text-align:center;padding:24px;">No rules defined.</div>';
    return;
  }
  el.innerHTML = rules.map((r, i) => `
    <div class="rule-item">
      <span class="rule-item-icon">📋</span>
      <div class="rule-item-body">
        <div class="rule-item-title">${escHtml(r.title || `Rule ${i + 1}`)}</div>
        <div class="rule-item-desc">${escHtml(r.description || r.content || '')}</div>
      </div>
      <span class="badge badge-${r.scope === 'global' ? 'violet' : 'info'}">${escHtml(r.scope || 'local')}</span>
    </div>
  `).join('');
}

function renderCopilotAgents(agents) {
  const el = document.getElementById('copilot-agents-list');
  if (!agents.length) {
    el.innerHTML = '<div style="color:var(--text-mute);font-size:13px;text-align:center;padding:24px;">No agents defined.</div>';
    return;
  }
  el.innerHTML = agents.map(a => `
    <div class="agent-item">
      <span class="rule-item-icon">🤖</span>
      <div class="rule-item-body">
        <div class="rule-item-title">${escHtml(a.name || a.id)}</div>
        <div class="rule-item-desc">${escHtml(a.description || '')}</div>
      </div>
      <span class="badge badge-success">active</span>
    </div>
  `).join('');
}

function renderCopilotHooks(hooks) {
  const el = document.getElementById('copilot-hooks-list');
  if (!hooks.length) {
    el.innerHTML = '<div style="color:var(--text-mute);font-size:13px;text-align:center;padding:24px;">No hooks defined.</div>';
    return;
  }
  el.innerHTML = hooks.map(h => `
    <div class="hook-item">
      <span class="rule-item-icon">🪝</span>
      <div class="rule-item-body">
        <div class="rule-item-title">${escHtml(h.name || h.event)}</div>
        <div class="rule-item-desc">${escHtml(h.description || h.script || '')}</div>
      </div>
      <span class="badge badge-info">${escHtml(h.event || 'hook')}</span>
    </div>
  `).join('');
}

function initCopilotSection() {
  document.getElementById('btn-save-rules').addEventListener('click', async () => {
    toast('Rules saved (no-op in demo)', 'info');
  });
}

// ══════════════════════════════════════════════════
// SYSTEM SECTION
// ══════════════════════════════════════════════════

async function loadSystem() {
  await Promise.all([fetchSystemResources(), checkServiceHealth(), checkLmStudio()]);

  // Poll every 5s while section is active
  if (!state.systemPollInterval) {
    state.systemPollInterval = setInterval(() => {
      if (state.activeSection === 'system') {
        fetchSystemResources();
        checkServiceHealth();
        checkLmStudio();
      }
    }, 5000);
  }
}

async function fetchSystemResources() {
  try {
    const data = await api('/api/system/resources');
    updateSystemGauges(data);
  } catch (e) {
    // fail silently — gauges keep last values
  }
}

function updateSystemGauges(data) {
  if (data.cpu !== undefined) {
    document.getElementById('gauge-cpu-val').textContent = data.cpu.toFixed(1) + '%';
    document.getElementById('gauge-cpu-fill').style.width = data.cpu + '%';
  }
  if (data.ram_used_gb !== undefined && data.ram_total_gb !== undefined) {
    document.getElementById('gauge-ram-val').textContent = data.ram_used_gb.toFixed(1) + ' GB';
    document.getElementById('gauge-ram-fill').style.width = ((data.ram_used_gb / data.ram_total_gb) * 100) + '%';
  }
  if (data.vram_used_mb !== undefined && data.vram_total_mb !== undefined) {
    document.getElementById('gauge-vram-val').textContent = data.vram_used_mb.toFixed(0) + ' MB';
    document.getElementById('gauge-vram-fill').style.width = ((data.vram_used_mb / data.vram_total_mb) * 100) + '%';
  }
  if (data.gpu_temp !== undefined) {
    document.getElementById('gauge-temp-val').textContent = data.gpu_temp.toFixed(0) + '°C';
    const pct = Math.min(data.gpu_temp / 100 * 100, 100);
    document.getElementById('gauge-temp-fill').style.width = pct + '%';
  }
}

async function checkLmStudio() {
  try {
    const start = Date.now();
    const data = await api('/api/lmstudio/status');
    const ms = Date.now() - start;
    const el = document.getElementById('lms-server-status');
    el.innerHTML = `<span class="badge badge-success">Online</span> <span style="font-size:11px;color:var(--text-mute)">${ms}ms</span>`;
    if (data.model) document.getElementById('lms-model-name').textContent = data.model;
    if (data.context_used !== undefined) document.getElementById('lms-context').textContent = data.context_used + ' tokens';
    if (data.active_slots !== undefined) document.getElementById('lms-slots').textContent = data.active_slots;
  } catch (e) {
    document.getElementById('lms-server-status').innerHTML = '<span class="badge badge-error">Offline</span>';
  }
}

async function checkServiceHealth() {
  const rows = document.querySelectorAll('#service-health-list .service-row');
  for (const row of rows) {
    const url = row.dataset.url;
    const dotEl = row.querySelector('.service-dot .badge');
    const latEl = row.querySelector('.service-latency');
    if (!url || !dotEl) continue;
    const start = Date.now();
    try {
      const res = await fetch(url, { method: 'GET', signal: AbortSignal.timeout(3000) });
      const ms = Date.now() - start;
      dotEl.className = 'badge badge-success';
      dotEl.textContent = '●';
      if (latEl) latEl.textContent = ms + 'ms';
    } catch {
      dotEl.className = 'badge badge-error';
      dotEl.textContent = '●';
      if (latEl) latEl.textContent = 'offline';
    }
  }
}

function initSystemSection() {
  document.getElementById('btn-refresh-lms').addEventListener('click', () => {
    checkLmStudio();
    checkServiceHealth();
  });
}

// ══════════════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════════════

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ══════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  initSocket();
  initNav();
  initCollapse();
  initChat();
  initTtsPanel();
  initVttPanel();
  initMediaFrame();
  initAudioStrip();

  // Section-specific init
  initNexusSection();
  initNlmSection();
  initCacheSection();
  initSchedulerSection();
  initFinetuningSection();
  initBenchmarksSection();
  initBackupsSection();
  initCopilotSection();
  initSystemSection();
  initProfileSection();
  initOverviewSection();

  // Show overview section by default
  navigateTo('overview');
});

// ══════════════════════════════════════════════════
// OVERVIEW SECTION
// ══════════════════════════════════════════════════

const OV_SERVICES = [
  { id: 'lmstudio', name: 'LMStudio',  port: '1234', url: 'http://localhost:1234/api/v1/models' },
  { id: 'nexus',    name: 'Nexus KMS', port: '8700', url: 'http://localhost:8700/api/health' },
  { id: 'tts',      name: 'TTS Server',port: '8600', url: 'http://localhost:8600/health' },
  { id: 'hub',      name: 'Hub',       port: '8500', url: 'http://localhost:8500/api/health' },
  { id: 'comfyui',  name: 'ComfyUI',   port: '8188', url: 'http://localhost:8188/system_stats' },
  { id: 'nexus_panel', name: 'Nexus Panel', port: '5570', url: 'http://localhost:5570/api/health' },
];

async function loadOverview() {
  // Nexus stats
  try {
    const stats = await api('/api/nexus/stats');
    document.getElementById('ov-nexus-entries').textContent = stats.total_entries ?? '—';
    document.getElementById('ov-qa-pairs').textContent = stats.qa_pairs ?? '—';
    const hr = stats.hit_rate_24h != null ? `${(stats.hit_rate_24h * 100).toFixed(1)}%` : '—';
    document.getElementById('ov-hit-rate').textContent = hr;
  } catch {}

  // Scheduler task count
  try {
    const sched = await api('/api/scheduler/tasks');
    document.getElementById('ov-tasks').textContent = (sched.tasks || []).length;
  } catch {}

  checkOverviewServices();
  loadActivityFeed();
}

function checkOverviewServices() {
  const container = document.getElementById('ov-services-list');
  container.innerHTML = OV_SERVICES.map(s => `
    <div class="service-mini-row">
      <span class="service-mini-dot checking" id="ov-dot-${s.id}"></span>
      <span class="service-mini-name">${escHtml(s.name)}</span>
      <span class="service-mini-port">${escHtml(s.port)}</span>
      <span class="service-mini-latency" id="ov-lat-${s.id}">...</span>
    </div>
  `).join('');

  OV_SERVICES.forEach(s => {
    const t0 = Date.now();
    fetch(s.url, { mode: 'no-cors', cache: 'no-cache', signal: AbortSignal.timeout(3000) })
      .then(() => {
        const dot = document.getElementById(`ov-dot-${s.id}`);
        const lat = document.getElementById(`ov-lat-${s.id}`);
        if (dot) dot.className = 'service-mini-dot online';
        if (lat) lat.textContent = `${Date.now() - t0}ms`;
      })
      .catch(() => {
        const dot = document.getElementById(`ov-dot-${s.id}`);
        if (dot) dot.className = 'service-mini-dot offline';
        const lat = document.getElementById(`ov-lat-${s.id}`);
        if (lat) lat.textContent = 'offline';
      });
  });
}

async function loadActivityFeed() {
  const container = document.getElementById('ov-activity-feed');
  try {
    const data = await api('/api/scheduler/history?limit=8');
    const items = data.history || [];
    if (!items.length) {
      container.innerHTML = '<div class="activity-empty">No recent activity.</div>';
      return;
    }
    container.innerHTML = items.map(item => {
      const t = item.run_at || item.time || '';
      const name = item.task_id || item.task_name || item.message || JSON.stringify(item);
      const status = item.status || '';
      const statusCol = status === 'ok' ? 'var(--emerald)' : status === 'error' ? 'var(--rose)' : 'var(--text-mute)';
      return `
        <div class="activity-item">
          <span class="activity-item-time">${escHtml(String(t).slice(0, 16))}</span>
          <span style="flex:1">${escHtml(String(name))}</span>
          ${status ? `<span style="color:${statusCol};font-size:11px;">${escHtml(status)}</span>` : ''}
        </div>
      `;
    }).join('');
  } catch {
    container.innerHTML = '<div class="activity-empty">Could not load activity.</div>';
  }
}

function initOverviewSection() {
  document.getElementById('btn-refresh-services')?.addEventListener('click', () => {
    checkOverviewServices();
  });

  // Quick-action buttons navigate to sections
  document.querySelectorAll('.quick-action[data-goto]').forEach(btn => {
    btn.addEventListener('click', () => navigateTo(btn.dataset.goto));
  });
}

// ══════════════════════════════════════════════════
// PROFILE SECTION
// ══════════════════════════════════════════════════

let profileData = null;

async function loadProfile() {
  try {
    profileData = await api('/api/user-profile');
    renderProfile(profileData);
    const ts = profileData.last_analyzed;
    const tsEl = document.getElementById('profile-last-analyzed');
    if (tsEl) {
      tsEl.textContent = ts
        ? `Last analyzed: ${new Date(ts).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`
        : '';
    }
  } catch {
    toast('Failed to load profile', 'error');
    document.getElementById('profile-facts-list').innerHTML = '<div class="loading-text">Profile unavailable.</div>';
    document.getElementById('profile-prefs-dict').innerHTML = '<div class="loading-text">—</div>';
  }
}

function renderProfile(data) {
  if (!data) return;

  // Header
  const name = data.name || 'User';
  const nameEl = document.getElementById('profile-name');
  if (nameEl) nameEl.textContent = name;

  const initEl = document.getElementById('profile-avatar-initial');
  if (initEl) initEl.textContent = name.charAt(0).toUpperCase();

  const techBg = (data.preferences && data.preferences.tech_background)
    || data.tech_background
    || 'No tech background set.';
  const techEl = document.getElementById('profile-tech-bg');
  if (techEl) techEl.textContent = techBg;

  // Facts
  const facts = data.facts || [];
  const factsCountEl = document.getElementById('facts-count');
  if (factsCountEl) factsCountEl.textContent = facts.length;
  renderFactsList(facts);

  // Preferences
  const prefs = data.preferences || {};
  const prefsCountEl = document.getElementById('prefs-count');
  if (prefsCountEl) prefsCountEl.textContent = Object.keys(prefs).length;
  renderPrefsDict(prefs);
}

function renderFactsList(facts) {
  const container = document.getElementById('profile-facts-list');
  if (!container) return;
  if (!facts.length) {
    container.innerHTML = '<div class="loading-text">No facts recorded yet. Re-analyze to populate.</div>';
    return;
  }
  container.innerHTML = facts.map((fact, i) => `
    <div class="fact-item" data-index="${i}">
      <span class="fact-item-bullet"></span>
      <span class="fact-item-text">${escHtml(String(fact))}</span>
      <button class="fact-item-del" data-index="${i}" title="Note: re-analyze to update facts">✕</button>
    </div>
  `).join('');
}

function renderPrefsDict(prefs) {
  const container = document.getElementById('profile-prefs-dict');
  if (!container) return;
  const entries = Object.entries(prefs);
  if (!entries.length) {
    container.innerHTML = '<div class="loading-text">No preferences set yet.</div>';
    return;
  }
  container.innerHTML = entries.map(([key, val]) => `
    <div class="pref-row" data-key="${escHtml(key)}">
      <span class="pref-key">${escHtml(key)}</span>
      <span class="pref-value" contenteditable="false" data-original="${escHtml(String(val))}">${escHtml(String(val))}</span>
      <div class="pref-actions">
        <button class="pref-edit-btn" title="Edit value">✏</button>
        <button class="pref-del-btn" title="Delete preference">✕</button>
      </div>
    </div>
  `).join('');

  container.querySelectorAll('.pref-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => togglePrefEdit(btn));
  });
  container.querySelectorAll('.pref-del-btn').forEach(btn => {
    btn.addEventListener('click', () => deletePreference(btn.closest('.pref-row').dataset.key));
  });
}

function togglePrefEdit(btn) {
  const row = btn.closest('.pref-row');
  const valEl = row.querySelector('.pref-value');
  const editing = valEl.contentEditable === 'true';
  if (editing) {
    const key = row.dataset.key;
    const newVal = valEl.textContent.trim();
    valEl.contentEditable = 'false';
    btn.textContent = '✏';
    valEl.onblur = null;
    savePreference(key, newVal);
  } else {
    valEl.contentEditable = 'true';
    valEl.focus();
    // Place cursor at end
    const range = document.createRange();
    const sel = window.getSelection();
    range.selectNodeContents(valEl);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
    btn.textContent = '✓';
    valEl.onblur = () => { if (valEl.contentEditable === 'true') togglePrefEdit(btn); };
  }
}

async function savePreference(key, value) {
  try {
    await api('/api/user-profile/preference', {
      method: 'POST',
      body: JSON.stringify({ key, value }),
    });
    if (profileData) {
      profileData.preferences = profileData.preferences || {};
      profileData.preferences[key] = value;
    }
    toast(`Saved: ${key}`, 'success');
  } catch {
    toast('Failed to save preference', 'error');
  }
}

async function deletePreference(key) {
  try {
    // Set empty string to effectively clear it (server stores it; future: add DELETE endpoint)
    await api('/api/user-profile/preference', {
      method: 'POST',
      body: JSON.stringify({ key, value: '' }),
    });
    if (profileData?.preferences) {
      delete profileData.preferences[key];
    }
    renderPrefsDict(profileData?.preferences || {});
    const prefsCountEl = document.getElementById('prefs-count');
    if (prefsCountEl) prefsCountEl.textContent = Object.keys(profileData?.preferences || {}).length;
    toast(`Removed: ${key}`, 'success');
  } catch {
    toast('Failed to remove preference', 'error');
  }
}

function initProfileSection() {
  document.getElementById('btn-add-fact')?.addEventListener('click', () => {
    const form = document.getElementById('facts-add-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    if (form.style.display === 'block') document.getElementById('new-fact-input').focus();
  });

  document.getElementById('btn-cancel-fact')?.addEventListener('click', () => {
    document.getElementById('facts-add-form').style.display = 'none';
    document.getElementById('new-fact-input').value = '';
  });

  document.getElementById('btn-save-fact')?.addEventListener('click', async () => {
    const fact = document.getElementById('new-fact-input').value.trim();
    if (!fact) { toast('Enter a fact first', 'error'); return; }
    try {
      await api('/api/user-profile/fact', {
        method: 'POST',
        body: JSON.stringify({ fact }),
      });
      document.getElementById('facts-add-form').style.display = 'none';
      document.getElementById('new-fact-input').value = '';
      toast('Fact saved', 'success');
      await loadProfile();
    } catch {
      toast('Failed to save fact', 'error');
    }
  });

  document.getElementById('new-fact-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('btn-save-fact').click();
    if (e.key === 'Escape') document.getElementById('btn-cancel-fact').click();
  });

  document.getElementById('btn-add-pref')?.addEventListener('click', () => {
    const form = document.getElementById('prefs-add-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    if (form.style.display === 'block') document.getElementById('new-pref-key').focus();
  });

  document.getElementById('btn-cancel-pref')?.addEventListener('click', () => {
    document.getElementById('prefs-add-form').style.display = 'none';
    document.getElementById('new-pref-key').value = '';
    document.getElementById('new-pref-value').value = '';
  });

  document.getElementById('btn-save-pref')?.addEventListener('click', async () => {
    const key   = document.getElementById('new-pref-key').value.trim();
    const value = document.getElementById('new-pref-value').value.trim();
    if (!key || !value) { toast('Key and value required', 'error'); return; }
    try {
      await api('/api/user-profile/preference', {
        method: 'POST',
        body: JSON.stringify({ key, value }),
      });
      document.getElementById('prefs-add-form').style.display = 'none';
      document.getElementById('new-pref-key').value = '';
      document.getElementById('new-pref-value').value = '';
      toast('Preference saved', 'success');
      await loadProfile();
    } catch {
      toast('Failed to save preference', 'error');
    }
  });

  document.getElementById('btn-reanalyze')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-reanalyze');
    btn.disabled = true;
    btn.textContent = 'Analyzing...';
    try {
      await api('/api/analyzer/recent', {
        method: 'POST',
        body: JSON.stringify({ lookback_sessions: 5 }),
      });
      toast('Re-analysis complete', 'success');
      await loadProfile();
    } catch {
      toast('Re-analysis failed — check scheduler', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '↻ Re-analyze';
    }
  });
}


// --- News Section ---

let _newsActiveCat = 'all';
let _newsAllArticles = [];

function initNewsSection() {
  document.querySelectorAll('.cat-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.cat-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _newsActiveCat = btn.dataset.cat;
      renderNewsArticles();
    });
  });
  document.getElementById('news-search')?.addEventListener('input', renderNewsArticles);
  document.getElementById('news-fetch-btn')?.addEventListener('click', async () => {
    const btn = document.getElementById('news-fetch-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Fetching...';
    try {
      const res = await api('/api/news/fetch-now', { method: 'POST' });
      if (res.success) {
        toast('Fetched ' + res.articles_found + ' articles, stored ' + res.stored, 'success');
        await loadNewsArticles();
        await loadNewsSources();
      } else {
        toast('Fetch failed: ' + (res.error || 'unknown'), 'error');
      }
    } catch (e) {
      toast('Fetch error: ' + e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '🔄 Fetch Now';
    }
  });
  loadNewsSources();
  loadNewsArticles();
}

async function loadNewsSources() {
  try {
    const res = await api('/api/news/sources');
    if (!res.success) return;
    const el = document.getElementById('news-sources-list');
    const countEl = document.getElementById('news-source-count');
    if (countEl) countEl.textContent = res.enabled + '/' + res.total;
    if (!el) return;
    if (!res.sources || !res.sources.length) {
      el.innerHTML = '<div style="font-size:12px;color:var(--text-mute);">No sources configured</div>';
      return;
    }
    el.innerHTML = res.sources.map(function(s) {
      const dotClass = s.last_fetch_status === 'ok' ? 'source-dot-ok' :
                       s.last_fetch_status === 'error' ? 'source-dot-error' : 'source-dot-pending';
      const dotSymbol = s.last_fetch_status === 'ok' ? '\u25cf' :
                        s.last_fetch_status === 'error' ? '\u25cf' : '\u25cb';
      return '<div class="source-row">' +
        '<span class="' + dotClass + '">' + dotSymbol + '</span>' +
        '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + s.name + '</span>' +
        '<span style="color:var(--text-mute);font-size:10px;">' + (s.category || '') + '</span>' +
        '</div>';
    }).join('');
    const fetched = res.sources.find(function(s) { return s.last_fetched; });
    const lastFetchEl = document.getElementById('news-last-fetch');
    if (lastFetchEl && fetched && fetched.last_fetched) {
      lastFetchEl.textContent = new Date(fetched.last_fetched * 1000).toLocaleString();
    }
  } catch (e) {
    console.warn('News sources load failed:', e);
  }
}

async function loadNewsArticles() {
  try {
    const cat = _newsActiveCat === 'all' ? '' : _newsActiveCat;
    const url = '/api/news/latest?limit=50' + (cat ? '&category=' + cat : '');
    const res = await api(url);
    _newsAllArticles = res.articles || [];
    renderNewsArticles();
  } catch (e) {
    console.warn('News load failed:', e);
  }
}

function renderNewsArticles() {
  const container = document.getElementById('news-articles-container');
  if (!container) return;
  const search = (document.getElementById('news-search')?.value || '').toLowerCase();
  const catFilter = _newsActiveCat;
  const filtered = _newsAllArticles.filter(function(a) {
    if (catFilter !== 'all' && a.category !== catFilter) return false;
    if (search && !a.title.toLowerCase().includes(search) &&
        !(a.content || '').toLowerCase().includes(search)) return false;
    return true;
  });
  if (!filtered.length) {
    const msg = _newsAllArticles.length ? 'No articles match filter' : 'No articles yet \u2014 click Fetch Now';
    container.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:200px;gap:12px;">'
      + '<div style="font-size:32px;">\uD83D\uDCED</div>'
      + '<div style="font-size:14px;color:var(--text-mute);">' + msg + '</div>'
      + '</div>';
    return;
  }
  const catColors = {
    ai_ml: '#6366f1', local_inference: '#8b5cf6', open_source: '#10b981',
    python: '#3b82f6', security: '#f43f5e', science: '#f59e0b', dev_tools: '#06b6d4'
  };
  container.innerHTML = filtered.map(function(a) {
    const catColor = catColors[a.category] || '#6366f1';
    const titleText = a.title.replace(/^News:\s*/i, '');
    const urlMatch = (a.content || '').match(/URL:\s*(https?:\/\/[^\n]+)/);
    const articleUrl = urlMatch ? urlMatch[1].trim() : '';
    const summaryMatch = (a.content || '').match(/\n\n([\s\S]+)$/);
    const summary = summaryMatch ? summaryMatch[1].replace(/\*\*/g, '').trim() : '';
    const scoreMatch = (a.content || '').match(/Relevance:\s*([\d.]+)/);
    const score = scoreMatch ? parseFloat(scoreMatch[1]) : 0;
    const scoreW = Math.round(Math.min(1, score) * 100);
    const timeStr = a.created_at ? new Date(a.created_at).toLocaleString() : '';
    const tagBadges = (a.tags || [])
      .filter(function(t) { return t !== 'news'; })
      .slice(0, 2)
      .map(function(t) {
        return '<span style="font-size:10px;color:var(--text-mute);background:var(--bg-dark);padding:1px 6px;border-radius:8px;">' + t + '</span>';
      }).join('');
    return '<div class="news-article-card">'
      + '<div class="news-article-title">'
      + (articleUrl ? '<a href="' + articleUrl + '" target="_blank" rel="noopener">' + titleText + '</a>' : titleText)
      + '</div>'
      + '<div class="news-article-meta">'
      + '<span class="news-cat-chip" style="background:' + catColor + '22;color:' + catColor + ';">' + (a.category || '').replace(/_/g, ' ') + '</span>'
      + (timeStr ? '<span style="font-size:11px;color:var(--text-mute);">' + timeStr + '</span>' : '')
      + tagBadges
      + '</div>'
      + (summary ? '<div class="news-article-summary">' + summary.slice(0, 300) + '</div>' : '')
      + '<div class="news-score-bar"><div class="news-score-fill" style="width:' + scoreW + '%;"></div></div>'
      + '</div>';
  }).join('');
}
