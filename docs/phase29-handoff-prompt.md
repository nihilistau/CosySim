# Phase 29 Implementation — Tablet Media Pipeline Fix

## AGENT PROMPT

You are implementing Phase 29 of the CosySim project. Your task is to fix the broken media rendering pipeline for the tablet/phone UI. The project is at `C:\Files\Models\CosySim` on Windows. Use PowerShell commands with Windows-style paths (backslashes).

**Model override: claude-opus-4.6**

---

## CONTEXT

**CosySim** is a three-pillar AI agent simulation framework:
- Pillar 1: CosySim engine (Python/Flask)
- Pillar 2: LMStudio (local LLM inference)
- Pillar 3: ComfyUI (image/video generation)

The phone/tablet scene (`content/scenes/phone/`) is a chat UI where users talk to AI characters. Characters can send text, photos, voice messages, and video messages. All interactions are stored in conversation history.

**Current state:**
- 315/315 tests passing
- 3 recent commits completed Phase 28 tasks:
  - `22d053f` — Tablet rewrite (780x680 frame, glass UI, health monitor)
  - `0159a74` — Chat fixes (rich media pattern detection, persistence)
  - `8bac0e3` — Default LLM set to qwen3-4b-z-engineer-q8

**The problem:**
1. ✅ Chat history was showing `[Photo sent: UUID]` as text — **FIXED** (commit 0159a74)
2. ✅ Chat was resetting on re-entry — **FIXED** (commit 0159a74)
3. 🔴 **Voice/video messages don't play** — download routes broken
4. 🔴 **No offline media ingest** — can't drop files in folders and have them appear

---

## CRITICAL BUG DISCOVERED

**Video Download 404 Issue:**
- Generator saves videos to: `content/simulation/media/video/`
- Download route checks: `content/media/video/` (wrong path!)
- Voice route already checks BOTH dirs (simulation + media) — video needs same fix

**File:** `content/scenes/phone/phone_scene.py`
- Line ~775: Voice route checks 2 dirs ✅
- Line ~1012: Video route checks 1 dir ❌ (missing simulation path)

---

## YOUR TASKS (8 remaining)

### ✅ Already Complete (4/12)
1. Chat history rendering — addMessageToUI() detects patterns
2. Chat persistence — loadMessages() doesn't wipe on re-entry
3. Badge detection — fixed active-class check
4. Default LLM — set to qwen3-4b-z-engineer-q8

### 🔴 TODO (8/12)

#### **Task 5: Fix video download path**
**File:** `content/scenes/phone/phone_scene.py` (around line 1012)

**Current code:**
```python
video_dir = Path(__file__).parent.parent / "media" / "video"
```

**Fix needed:**
```python
# Check simulation dir first (where generator writes), then media dir
video_dirs = [
    Path(__file__).parent.parent.parent / "simulation" / "media" / "video",
    Path(__file__).parent.parent / "media" / "video"
]
for video_dir in video_dirs:
    video_path = video_dir / filename
    if video_path.exists():
        return send_file(video_path, mimetype='video/mp4')
return jsonify({'error': 'Video not found'}), 404
```

#### **Task 6: Ensure media directories exist**
**Files:** `content/scenes/phone/phone_scene.py` (in `__init__` method)

Add directory creation on scene startup:
```python
# In PhoneScene.__init__()
media_dirs = [
    Path("content/media/voice"),
    Path("content/media/video"),
    Path("content/simulation/media/voice"),
    Path("content/simulation/media/video")
]
for d in media_dirs:
    d.mkdir(parents=True, exist_ok=True)
```

#### **Task 7: Offline media ingest**
**Files:** 
- `content/scenes/phone/apps/voice_messages.py` (VoiceMessagesApp.get_list)
- `content/scenes/phone/apps/video_messages.py` (VideoMessagesApp.get_list)

**Current:** Only returns DB-tracked messages
**Fix:** Also scan filesystem for files not in DB

Add filesystem scan fallback:
```python
# After DB query, scan media directories
media_files = []
for media_dir in [simulation_voice_dir, content_voice_dir]:
    if media_dir.exists():
        for file in media_dir.glob("*.wav"):  # or *.mp4 for video
            # If not in DB results, add as discovered file
            # Extract character/timestamp from filename pattern
            media_files.append({
                'id': file.stem,
                'filename': file.name,
                'url': f"/api/voice/download/{file.name}",
                'source': 'filesystem',
                'timestamp': file.stat().st_mtime
            })
```

#### **Task 8: Voice playback in chat**
**File:** `content/scenes/phone/static/js/phone.js`

Enhance the `_addRichMediaBubble()` function (created in 0159a74) to check if audio file exists and render player:
```javascript
// In _addRichMediaBubble, for voice messages:
// Try to fetch the audio file
// If exists: render <audio> player with transcript below
// If 404: render transcript-only bubble (current behavior)
```

#### **Task 9: Video playback in chat**
**File:** `content/scenes/phone/static/js/phone.js`

Same as Task 8, but for video messages — render `<video>` player if file exists.

#### **Task 10: Photo 404 handling**
**File:** `content/scenes/phone/static/js/phone.js` (in `addPhotoMessage()`)

Add error handler to `<img>` tag:
```javascript
img.onerror = function() {
    this.src = '/static/images/placeholder.png';  // or render a gray box
    this.alt = 'Image not available';
};
```

#### **Task 11: Wire media overlay player**
**File:** `content/scenes/phone/static/js/phone.js`

Functions `loadVoiceMessages()` and `loadVideoMessages()` render card lists. When clicked, they should open the `.media-overlay` player:
```javascript
// In media card click handler:
function playMediaFromGallery(url, type) {
    const overlay = document.getElementById('mediaOverlay');
    const player = document.getElementById('mediaPlayerWrap');
    // Show overlay, load URL into audio/video element, play
}
```

#### **Task 12: Run tests & commit**
```powershell
cd C:\Files\Models\CosySim
python -m pytest tests\ -q --tb=short
# Ensure 315/315 pass
git add .
git commit -m "Fix media pipeline: video path, offline ingest, inline players

- Video download now checks simulation/media/video first (matches generator)
- Ensure all media dirs created on startup
- Offline media ingest: scan folders for files not in DB
- Voice/video inline players in chat history (with 404 fallback)
- Photo error handling with placeholder
- Wire media overlay player for gallery cards

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## KEY FILES

### Backend (Python)
- `content/scenes/phone/phone_scene.py` — Flask routes, socket handlers
  - Line ~775: Voice download route (already checks 2 dirs) ✅
  - Line ~1012: Video download route (needs fix) 🔴
  - Line ~1062: `list_video_messages()` endpoint
  - Line ~1075: `list_voice_messages()` endpoint
  - `__init__()`: Add media dir creation

- `content/simulation/services/voice_message.py`
  - Line 35-36: Saves to `simulation/media/voice/` ✅

- `content/simulation/services/video_message.py`
  - Line 40-41: Saves to `simulation/media/video/` ✅

- `content/scenes/phone/apps/voice_messages.py`
  - `get_list()`: Needs filesystem scan fallback

- `content/scenes/phone/apps/video_messages.py`
  - `get_list()`: Needs filesystem scan fallback

### Frontend (JavaScript)
- `content/scenes/phone/static/js/phone.js`
  - Line ~527: `addMessageToUI()` — already detects patterns ✅
  - Line ~565: `addPhotoMessage()` — needs error handler
  - Line ~601: `addVoiceMessageToChat()` — socket version (working)
  - Line ~675: `addVideoMessageToChat()` — socket version (working)
  - Line ~277: `loadVideoMessages()` — needs overlay wiring
  - Line ~319: `loadVoiceMessages()` — needs overlay wiring
  - Line ~588: `_addRichMediaBubble()` — needs player enhancement

---

## TESTING REQUIREMENTS

1. **Manual test:** 
   - Drop a `.wav` file in `content/media/voice/` → visit tablet → open Voice Messages → file should appear
   - Same for `.mp4` in `content/media/video/`

2. **Automated test:**
   ```powershell
   python -m pytest tests\ -q --tb=short
   ```
   Must show: **315 passed**

3. **Regression check:**
   - Photos still work (clicking opens fullscreen viewer)
   - Text messages still work
   - Chat persistence still works (navigate away & back, messages stay)

---

## CONSTRAINTS

- **Minimal changes:** Don't refactor unnecessarily. Surgical fixes only.
- **Graceful degradation:** If media file doesn't exist, show transcript/placeholder. Don't crash.
- **Windows paths:** Use backslashes for PowerShell, forward slashes for URLs.
- **Test before commit:** 315/315 must pass.
- **Follow existing patterns:** Voice route pattern → apply to video route.

---

## EXPECTED OUTCOME

After your work:
1. ✅ Video messages download correctly (simulation dir checked first)
2. ✅ Voice/video files dropped in folders appear in lists
3. ✅ Chat history shows inline audio/video players when files exist
4. ✅ Missing media degrades gracefully (transcript/placeholder shown)
5. ✅ Gallery cards wire to overlay player
6. ✅ All 315 tests pass
7. ✅ Clean commit message

---

## START COMMAND

Begin implementation immediately. Work through tasks 5-12 in order. Test after each major change. Commit when all tasks complete and tests pass.
