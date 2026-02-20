# Agents Implementation Plan — Phase 29 (media pipeline)

📌 Purpose: provide a single, actionable checklist and developer guidelines for agent work that directly follow the Phase 29 handoff. Use this document to track progress, run tests, and onboard new contributors working on agent + media-related tasks.

---

## Quick status
- Source handoff: `docs/phase29-handoff-prompt.md`
- Focus: phone/tablet media pipeline (voice/video download, offline ingest, inline players)
- Branch / repo: master — CosySim (this workspace)

---

## Environment (how to run locally)
- Activate Conda environment:
  - Windows PowerShell: `conda activate cosyvoice`
- Activate virtualenv (if using project `.venv`):
  - PowerShell: `& .\.venv\Scripts\Activate.ps1`
- Run tests: `python -m pytest tests -q --tb=short`
- Start phone scene (dev): `python launcher.py --mode phone`

> Note: ensure `lmstudio` / `chromadb` dependencies are available for full integration tests.

---

## Phase 29 tasks (mapped from handoff) — actionable checklist
- [x] Task 5 — Fix video download path (check simulation/media first)
- [x] Task 6 — Ensure media directories are created on startup
- [x] Task 7 — Offline media ingest for voice & video apps (filesystem scan fallback)
- [x] Task 8 — Voice playback in chat (inline player if file exists)
- [x] Task 9 — Video playback in chat (inline player if file exists)
- [x] Task 10 — Photo 404 handling (placeholder image)
- [x] Task 11 — Wire media overlay player (gallery → overlay playback)
- [ ] Task 12 — Run full test suite & commit + PR (CI green)

---

## Acceptance criteria (how to mark a task done)
- Video/voice files saved to `content/simulation/media/*` or `content/media/*` stream successfully via `/api/*/download/*`.
- Dropping `.wav`/`.mp4` files into either `content/simulation/media/*` or `content/media/*` shows them in the Phone apps (Voice / Video) without DB entries.
- Chat history that references `[Voice message: X]` or `[Video message: X]` renders an inline player when the file is present and degrades gracefully (transcript / placeholder) when missing.
- Photo avatars/images that 404 show the placeholder SVG and do not crash the UI.
- Unit + integration tests pass on CI (no regressions introduced).

---

## How agents should follow this plan (developer guidelines)
1. Read the handoff (`docs/phase29-handoff-prompt.md`) before implementing or reviewing PRs.
2. Work in small commits focused on one task at a time (one task → one commit). Use clear commit messages referencing the Task number.
3. Add unit tests for filesystem fallback and download-route behavior where feasible.
4. When changing UI, include a short manual test in the PR description (steps + expected outcome).
5. Use EventChain logging for diagnostic events related to agent-driven media generation or file discovery.
6. Prefer backwards-compatible changes and graceful degradation — do not raise exceptions for missing files.

---

## Testing checklist (manual + automated)
- Manual:
  1. `conda activate cosyvoice` + `& .\.venv\Scripts\Activate.ps1`
  2. Start phone scene: `python launcher.py --mode phone`
  3. Drop a `.wav` into `content/media/voice/` → open Phone → Voice Messages → verify appears and plays.
  4. Drop a `.mp4` into `content/simulation/media/video/` → open Phone → Video Messages → verify appears and plays in overlay.
  5. Send chat messages that contain `[Voice message: filename.wav]` and confirm inline player or transcript fallback.
  6. Open a missing photo and confirm placeholder displays.
- Automated:
  - Add tests to `tests/` that:
    - Call `/api/video-message/download/<filename>` and assert 200/404 as expected for files in simulation vs missing.
    - Verify `GET /api/video-messages/list` and `GET /api/voice-messages/list` return filesystem-discovered files when DB has none.

---

## PR & merging rules
- PR title should include `Phase 29` and the task summary.
- Attach manual test steps and one screenshot or short GIF for UI changes.
- Link to EventChain traces if testing agent-generated media.
- Require at least one code review + passing CI before merge.

---

## Triage & follow-ups (if tests fail or regressions appear)
- Reproduce locally using `pytest -k <test_name>` and `python -m pytest tests -q`.
- If CI fails due to environment issues (protobuf/chromadb/opentelemetry), capture exact error and open an infra ticket; do not block the PR if unrelated to media logic.
- Add regression tests for any bug fixed during the review.

---

## Owner / Contacts
- Primary owner for Phase 29: @nihilistau (repo owner)
- Secondary: CosySim maintainers (see `CODE_OF_CONDUCT.md` / `CONTRIBUTING.md`)

---

## Quick reference (useful file locations)
- Phone scene (routes & UI): `content/scenes/phone/`
- Media generator: `content/simulation/services/media_generator.py`
- Voice / Video message services: `content/simulation/services/voice_message.py`, `content/simulation/services/video_message.py`
- Apps (gallery): `content/scenes/phone/apps/voice_messages.py`, `.../video_messages.py`
- Frontend phone UI: `content/scenes/phone/static/js/phone.js`, `phone_ui.html`
- EventChain diagnostics: `content/simulation/database/events.py`

---

## Post-handoff checklist (for the release)
- [ ] Ensure CI passes on target branch (all relevant tests).
- [ ] Squash/clean commits for final PR if requested by maintainers.
- [ ] Update `CHANGELOG.md` / release notes with a short summary: "Fix media pipeline: offline ingest, download path, inline players".

---

If you want, I can:
- Add the automated tests for filesystem ingest + download routes now.
- Open a PR with this file and the Phase 29 commit(s).

Tell me which follow-up you want next.