# Scene Debugging & Health Check Conventions

## The Golden Rule
After ANY change to a scene template (`.html`) or scene Python file (`*_scene.py`),
run the health checker before committing:

```powershell
python scripts/scene_health_check.py --port <PORT> --fix
```

After restarting a scene, run it again to confirm the running instance is clean:
```powershell
python scripts/scene_health_check.py --port <PORT>
```

Full scan of all running scenes:
```powershell
python scripts/scene_health_check.py --fix
```

With Chrome CDP JS checks (requires Chrome with `--remote-debugging-port=9222`):
```powershell
python scripts/scene_health_check.py              # auto-uses Chrome
python scripts/cdp_debug.py "http://localhost:5569/" "<TAB_ID>"
```

---

## Scene Port Map
| Port | Scene key |
|------|-----------|
| 5555 | phone |
| 5556 | bedroom |
| 5557 | lounge |
| 5558 | tavern |
| 5559 | casino |
| 5560 | gallery |
| 5561 | arena |
| 5562 | realm |
| 5563 | neoncity |
| 5564 | coders |
| 5565 | games |
| 5566 | heist |
| 5567 | asset_studio |
| 5568 | command_center |
| 5569 | grid |
| 5570 | nexus_panel |
| 5572 | intel_hub |
| 8500 | hub |

---

## Every Scene's `start()` Checklist

Every scene `start()` method MUST call these in order after Flask/SocketIO setup:

```python
from content.shared import register_shared_assets  # required import

# In start():
register_shared_assets(self.app)        # shared Blueprint — /shared/* routes
self.register_health_route(self.app)    # GET /api/health
self.register_hud_route(self.app)       # GET /api/hud/state
self.register_announcer_route(self.app) # GET /api/announcer/feed
self.register_bench_route(self.app, self.socketio)  # GET /api/bench
self.register_tts_route(self.app)       # POST /api/tts (optional but recommended)
```

---

## Template Checklist

Every scene template MUST:
- **NOT** explicitly load `navbar_v2.css` or `navbar_v2.js` — `navbar_v2.html` is
  self-contained and emits them. Double-loading causes `SCENE_PORTS already declared`.
- Use `{% include 'navbar_v2.html' %}` as the single navbar include.
- **NOT** load `aria_widget.js` — use `{% include 'aria_widget.html' %}` instead
  (new cosysim-aria-portrait system). Loading both creates a ghost floating button.

```html
<!-- ✅ CORRECT -->
{% include 'navbar_v2.html' %}

<!-- ❌ WRONG — duplicates what navbar_v2.html already emits -->
<link rel="stylesheet" href="/shared/css/navbar_v2.css">
<script src="/shared/js/navbar_v2.js" defer></script>
```

---

## Common Bugs & Fixes

### `SCENE_PORTS already declared` / `CosyNavbar is not defined`
**Cause:** Template explicitly loads `navbar_v2.js` AND includes `navbar_v2.html`.  
**Fix:** Remove the explicit `<script src="/shared/js/navbar_v2.js">` from the template.

### `/shared/css/navbar_v2.css` 404 (all shared assets 404)
**Cause:** Scene `start()` never calls `register_shared_assets(self.app)`.  
**Fix:**
```python
from content.shared import register_shared_assets
# in start():
register_shared_assets(self.app)
```

### `/api/hud/state` or `/api/announcer/feed` 404
**Cause:** Scene missing `register_hud_route` or `register_announcer_route` call.  
**Fix:**
```python
self.register_hud_route(self.app)
self.register_announcer_route(self.app)
```

### Ghost "Radio" floating button blocking clicks
**Cause:** Old `aria_widget.js` loaded in template — falls back to `_buildFallback()`
because `/shared/templates/aria_widget.html` is not HTTP-accessible.  
**Fix:** Remove `<script src="/shared/js/aria_widget.js">` from template; use
`{% include 'aria_widget.html' %}` for the portrait widget.

### `NLMPanel.tsx: nlmNotebooks.find is not a function`
**Cause:** Nexus returns `{ok:true, data:{error:"connection_error"}}` — canvas passes
the error object as the notebooks array.  
**Fix:** `canvas_api.py` `nlm_notebooks()` must detect `inner.get("error")` and raise
to trigger the fallback that returns `{"notebooks": []}`.

---

## Chrome CDP Debug Session

Launch Chrome with debugging enabled (one-time setup):
```powershell
scripts/launch_chrome_debug.ps1
```

Then connect via `scripts/cdp_debug.py`:
```python
# Navigate to a scene and capture all errors:
python scripts/cdp_debug.py "http://localhost:5569/" "<TAB_ID>"
```

Get available tab IDs:
```powershell
python -c "import urllib.request,json; print(json.dumps(json.loads(urllib.request.urlopen('http://localhost:9222/json').read()), indent=2))"
```

---

## When to Run the Health Check

| Trigger | Command |
|---------|---------|
| After editing any `*_scene.py` | `python scripts/scene_health_check.py --port PORT --fix` |
| After editing any `.html` template | `python scripts/scene_health_check.py --port PORT` |
| After restarting a scene | `python scripts/scene_health_check.py --port PORT` |
| Before committing scene changes | `python scripts/scene_health_check.py --no-cdp` |
| User reports UI bug in a scene | `python scripts/scene_health_check.py --port PORT --fix` |
| After adding a new scene | `python scripts/scene_health_check.py --port NEW_PORT --fix` |
