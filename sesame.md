# Sesame AI — ARGUS Intelligence & Live CDP Findings

> Generated: 2026-06-17 · Source: ARGUS live-test session against `app.sesame.com`
> Captures: `Heap-20260617T2227*–2252*.heapsnapshot` (×5), `Heap-20260617T232218.heapsnapshot`,
> `app.sesame.com7.har`, `app.sesame.com8.har`, plus a live CDP-captured heap.
> Classification: passive traffic + client-side analysis of the user's own session.
> Fuller historical report: [`docs/ARGUS_SESAME_REPORT.md`](docs/ARGUS_SESAME_REPORT.md).

---

## 1. Summary

ARGUS was driven end-to-end against a live Chrome instance (CDP `:9223`) loaded on
`app.sesame.com`. Every read/observe/capture surface works; the two write surfaces
(Statsig gate injection, Maya-Alpha WebSocket intercept) were exercised and confirmed
under explicit authorization. The reusable patch lives in
[`scripts/argus/sesame_live_patch.py`](scripts/argus/sesame_live_patch.py).

---

## 2. Live CDP findings (this session)

| Item | Value |
|------|-------|
| Live tab | `https://app.sesame.com/welcome` (logged-out landing) |
| User agent | Chrome 149.0.7827.103 (V8 14.9) |
| Statsig cache key | `statsig.cached.evaluations.1501964201` |
| Feature gates | **46 total, 14 enabled** by default |
| Dynamic configs | **21** |
| Gate naming | **Names are hashed** in the current build (e.g. `9609502`, `95945896`) — the SDK no longer ships plaintext gate names (contrast the 9 decompiled names in §4) |
| Firebase auth in localStorage | empty `[]` on the welcome page (no signed-in session) |
| Live WebSocket | `wss://sesameai.app/agent-service-0/v1/connect?id_token=<JWT>` — 3,555 msgs / 12 types in HAR |

### Gate injection result (authorized)
Flipping all gates via the patch took the cache from **14/46 → 46/46 enabled** (32 flipped,
`rule_id='argus'`). Reversible: a reload re-evaluates against the server, or clear the
`statsig.cached.evaluations.*` keys.

### Maya-Alpha WebSocket intercept (authorized)
`WebSocket.prototype.send` is wrapped so any `call_connect` frame has its
`settings.character` rewritten to `Maya-Alpha` (the unreleased alpha voice model) before
being sent. Confirmed patched in-page; only fires when a call is started.

### JWTs recovered from heaps
- `https://securetoken.google.com/sesame-ai-demo` (RS256) — Firebase identity token
- `https://firebaseappcheck.googleapis.com/1072000975600` (RS256) — App Check token (valid)
- `app.sesame.com8.har` contains a Firebase **refresh_token** (auto-refresh possible)

---

## 3. Identity / infrastructure (client-side constants)

> These are **client-side public keys** shipped in the browser bundle, not server secrets.
> The Firebase API key is intentionally externalized to `.env` (`FIREBASE_API_KEY`).

| Component | Value |
|-----------|-------|
| App | `https://app.sesame.com` |
| API | `https://sesameai.app` |
| Firebase project | `sesame-ai-demo` |
| Statsig client key | `client-TGCzyFkjJ0ZvNupjjxCKPpxPEO8WdmZjQhxLgJlgM6H` |
| Statsig assets | `https://featureassets.org/v1` |
| GCS public bucket | `sesame-dev-public` |
| GCS prod assets | `sesame-call-assets-us-central1-prod` |
| RudderStack write key | `2wpiqnS6W3104MQz7mwfyQjME6d` |
| GA4 | `G-ZZLPJBMBEN` |
| Sentry | org `4507352690196480`, project `4509312291110912`, `sentry.javascript.react/9.17.0` |
| Build | Vite 6.2.5 · pnpm 9.15.3 · Node 18.18.2 · deploy Vercel + Kubernetes |

---

## 4. Feature gates & dynamic configs (decompiled names)

9 named gates / 9 named configs were recovered from the `index-E-c2zfaB.js` bundle (the
live build now hashes these, so the current 46 gates are a superset):

**Gates:** `disable_calling`, `upload_client_recording`, `video_download`,
`sesame_com_login`, `consumer_web_app`, `show_call_info`, `show_upsell_banner`,
`show_upsell_page`, `dummy`.

**Configs:** `web_audio_config`, `webrtc_config`, `video_download_config`,
`websocket_config`, `backoff_config`, `datadog_config`, `call_feedback_config`,
`outage_banner_config`, `dummy`.

---

## 5. Characters

| Name | Variant | Note |
|------|---------|------|
| Maya | production | default voice |
| **Maya-Alpha** | alpha | **unreleased** — reachable via `call_connect.settings.character` swap |
| Miles | production | |

---

## 6. WebSocket agent protocol

Connection: `wss://sesameai.app/agent-service-0/v1/connect?id_token=<JWT>`

**Client → server:** `client_location_state`, `webrtc_sdp_offer`, `webrtc_ice_candidate`,
`call_connect` (fields: `sample_rate`, `audio_codec`, `reconnect`, `is_private`,
**`settings`** ← character lives here, `client_name`, `client_metadata`),
`call_disconnect`, `ping` (~500 ms keepalive).

**Server → client:** `initialize` (`session_id`, `webrtc_ice_servers`), `webrtc_config`,
`webrtc_sdp_answer`, `chat`, `call_connect_response` (`call_id`), `call_disconnect_response`,
`ping_response`.

**WebRTC:** STUN/TURN `34.134.236.52:3478` (UDP+TCP), time-limited creds (1 hr).
**Audio:** 44.1 kHz, raw WebRTC Opus.

---

## 7. Internal endpoints (behind Google IAP)

32 `/external/*` endpoints recovered from the bundle, including:
`/external/agents`, `/external/presets`, `/external/sdui/preview`,
`/external/labeling/{crowd,staff}-{items,labels}`, `/external/user/clear-chat-history`,
`/external/oauth/{google,spotify,notion}/*`, `/external/generate-call-file-upload-url`,
`/external/waitlist/{join,status}`, `/external/feedback/{call,general}`.

---

## 8. Reproduce

```bash
# 1. Launch Chrome with CDP on :9223 (ARGUS profile), navigate to Sesame
chrome --remote-debugging-port=9223 \
  --user-data-dir=artifacts/argus/browser_profiles/chrome_profile https://app.sesame.com

# 2. Apply the live patch (all gates + Maya-Alpha intercept)
.venv/Scripts/python.exe -m scripts.argus.sesame_live_patch

# Variants
.venv/Scripts/python.exe -m scripts.argus.sesame_live_patch --gates-only
.venv/Scripts/python.exe -m scripts.argus.sesame_live_patch --ws-only --character Maya-Alpha
.venv/Scripts/python.exe -m scripts.argus.sesame_live_patch --dump-js   # print JS for console paste
```

*Generated by ARGUS — Sesame live-test session, 2026-06-17.*
