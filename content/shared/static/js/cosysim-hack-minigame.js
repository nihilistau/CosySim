/**
 * cosysim-hack-minigame.js — CosySim v0.81 "THE LIVING CITY"
 *
 * Hacking matrix puzzle mini-game.
 * No external libraries required.
 *
 * Usage:
 *   // Open hack interface for a target
 *   CosyHack.open('signal_comms_tower');
 *
 *   // Or open with a pre-loaded puzzle
 *   CosyHack.openPuzzle(puzzleData);
 */
(function () {
  'use strict';

  // ── Config ────────────────────────────────────────────────────────────────────
  const API_BASE = '';  // relative — same origin as scene

  // ── State ─────────────────────────────────────────────────────────────────────
  let _puzzle       = null;   // current puzzle data from server
  let _selected     = [];     // array of {r, c} objects in selection order
  let _timer        = null;   // setInterval handle
  let _elapsed      = 0;      // seconds elapsed
  let _done         = false;  // puzzle completed or failed

  // ── DOM Bootstrap ─────────────────────────────────────────────────────────────
  function _ensureOverlay() {
    if (document.getElementById('cs-hack-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'cs-hack-overlay';
    overlay.innerHTML = `
      <div class="cs-hack-panel">
        <div class="cs-hack-header">
          <div>
            <div class="cs-hack-title">⬡ NETRUNNER INTERFACE</div>
            <div class="cs-hack-target-label" id="cs-hack-target-label">TARGET: —</div>
          </div>
          <span class="cs-hack-close" id="cs-hack-close" title="Abort">✕</span>
        </div>

        <div id="cs-hack-puzzle-body">
          <div class="cs-hack-timer-wrap">
            <div class="cs-hack-timer-label">
              <span>TRACE PROGRESS</span>
              <span id="cs-hack-timer-text">—</span>
            </div>
            <div class="cs-hack-timer-bar">
              <div class="cs-hack-timer-fill" id="cs-hack-timer-fill" style="width:100%"></div>
            </div>
          </div>

          <div class="cs-hack-sequence" id="cs-hack-sequence">
            <span class="cs-hack-seq-label">SEQUENCE:</span>
          </div>

          <div class="cs-hack-grid-wrap">
            <div class="cs-hack-grid" id="cs-hack-grid"></div>
          </div>

          <div class="cs-hack-actions">
            <button class="cs-hack-btn cs-hack-btn-danger" id="cs-hack-abort">ABORT</button>
            <button class="cs-hack-btn cs-hack-btn-primary" id="cs-hack-submit">EXECUTE</button>
          </div>
        </div>

        <div class="cs-hack-outcome" id="cs-hack-outcome">
          <div class="cs-hack-outcome-icon" id="cs-hack-outcome-icon"></div>
          <div class="cs-hack-outcome-title" id="cs-hack-outcome-title"></div>
          <div class="cs-hack-outcome-detail" id="cs-hack-outcome-detail"></div>
          <button class="cs-hack-btn cs-hack-btn-primary" id="cs-hack-outcome-close" style="margin-top:8px">CLOSE</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    document.getElementById('cs-hack-close').addEventListener('click', () => CosyHack.close());
    document.getElementById('cs-hack-abort').addEventListener('click', () => CosyHack.close());
    document.getElementById('cs-hack-submit').addEventListener('click', _submitSolution);
    document.getElementById('cs-hack-outcome-close').addEventListener('click', () => CosyHack.close());

    // Close on overlay background click
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) CosyHack.close();
    });

    // Keyboard: Escape closes, Enter submits
    document.addEventListener('keydown', (e) => {
      if (!document.getElementById('cs-hack-overlay').classList.contains('active')) return;
      if (e.key === 'Escape') CosyHack.close();
      if (e.key === 'Enter' && !_done) _submitSolution();
    });
  }

  // ── Open / Close ─────────────────────────────────────────────────────────────
  async function _open(targetId) {
    _ensureOverlay();
    _reset();
    _showPuzzleBody();

    document.getElementById('cs-hack-target-label').textContent = `TARGET: ${targetId.toUpperCase()}`;
    document.getElementById('cs-hack-timer-text').textContent = '…';

    try {
      const resp = await fetch(`${API_BASE}/api/hack/puzzle`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target_id: targetId}),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        _showOutcome(false, 'CONNECTION REFUSED', data.error || 'Target unavailable.');
        return;
      }
      _openPuzzle(data);
    } catch (err) {
      _showOutcome(false, 'CONNECTION ERROR', String(err));
    }
  }

  function _openPuzzle(puzzleData) {
    _ensureOverlay();
    _reset();
    _showPuzzleBody();
    _puzzle = puzzleData;
    _elapsed = 0;
    _done = false;

    // Render target label
    document.getElementById('cs-hack-target-label').textContent =
      `TARGET: ${(puzzleData.target_id || '').toUpperCase()}`;

    // Render sequence
    _renderSequence(puzzleData.sequence_codes || [], puzzleData.sequence_length);

    // Render grid
    _renderGrid(puzzleData.grid);

    // Start timer
    _startTimer(puzzleData.time_limit);

    // Show overlay
    document.getElementById('cs-hack-overlay').classList.add('active');
  }

  function _close() {
    _stopTimer();
    const overlay = document.getElementById('cs-hack-overlay');
    if (overlay) overlay.classList.remove('active');
    _reset();
  }

  function _reset() {
    _puzzle = null;
    _selected = [];
    _elapsed = 0;
    _done = false;
    _stopTimer();
  }

  // ── Sequence & Grid rendering ──────────────────────────────────────────────
  function _renderSequence(codes, length) {
    const wrap = document.getElementById('cs-hack-sequence');
    wrap.innerHTML = '<span class="cs-hack-seq-label">TARGET:</span>';
    const useCodes = codes && codes.length ? codes : Array(length).fill('??');
    useCodes.forEach(code => {
      const el = document.createElement('span');
      el.className = 'cs-hack-seq-code';
      el.textContent = code;
      wrap.appendChild(el);
    });
  }

  function _renderGrid(grid) {
    const container = document.getElementById('cs-hack-grid');
    container.innerHTML = '';
    const size = grid.length;
    container.style.gridTemplateColumns = `repeat(${size}, 56px)`;

    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        const cell = document.createElement('div');
        cell.className = 'cs-hack-cell';
        cell.dataset.r = r;
        cell.dataset.c = c;
        cell.textContent = grid[r][c];
        cell.addEventListener('click', _onCellClick);
        container.appendChild(cell);
      }
    }
  }

  // ── Cell selection ────────────────────────────────────────────────────────
  function _onCellClick(e) {
    if (_done) return;
    const cell = e.currentTarget;
    const r = parseInt(cell.dataset.r, 10);
    const c = parseInt(cell.dataset.c, 10);

    // Toggle: if already selected at end, deselect
    const lastIdx = _selected.findIndex(s => s.r === r && s.c === c);
    if (lastIdx !== -1) {
      // Remove this cell and everything after it
      const toRemove = _selected.splice(lastIdx);
      toRemove.forEach(s => {
        const el = document.querySelector(`.cs-hack-cell[data-r="${s.r}"][data-c="${s.c}"]`);
        if (el) { el.classList.remove('selected'); _clearOrderLabel(el); }
      });
      return;
    }

    const seqLen = _puzzle ? _puzzle.sequence_length : 4;
    if (_selected.length >= seqLen) return; // max reached

    _selected.push({r, c});
    cell.classList.add('selected');
    _setOrderLabel(cell, _selected.length);

    // Auto-submit when full
    if (_selected.length === seqLen) {
      setTimeout(_submitSolution, 150);
    }
  }

  function _setOrderLabel(cell, n) {
    let label = cell.querySelector('.cs-hack-cell-order');
    if (!label) {
      label = document.createElement('span');
      label.className = 'cs-hack-cell-order';
      cell.appendChild(label);
    }
    label.textContent = n;
  }

  function _clearOrderLabel(cell) {
    const label = cell.querySelector('.cs-hack-cell-order');
    if (label) label.remove();
  }

  // ── Submit solution ──────────────────────────────────────────────────────
  async function _submitSolution() {
    if (_done || !_puzzle) return;
    _done = true;
    _stopTimer();

    const cells = _selected.map(s => [s.r, s.c]);

    try {
      const resp = await fetch(`${API_BASE}/api/hack/submit`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          puzzle_id: _puzzle.puzzle_id,
          cells: cells,
          elapsed: _elapsed,
        }),
      });
      const result = await resp.json();

      if (result.success) {
        _flashCells('correct');
        setTimeout(() => {
          const rewards = (result.rewards_granted || []).join(', ') || 'Access granted.';
          _showOutcome(true, 'ACCESS GRANTED', rewards);
        }, 600);
      } else {
        _flashCells('wrong');
        setTimeout(() => {
          const heatInfo = result.heat_delta ? ` Heat +${result.heat_delta}.` : '';
          _showOutcome(false, 'TRACE TRIGGERED', result.message + heatInfo);
        }, 600);
      }
    } catch (err) {
      _showOutcome(false, 'SUBMIT ERROR', String(err));
    }
  }

  function _flashCells(cls) {
    _selected.forEach(s => {
      const el = document.querySelector(`.cs-hack-cell[data-r="${s.r}"][data-c="${s.c}"]`);
      if (el) {
        el.classList.remove('selected');
        el.classList.add(cls);
      }
    });
  }

  // ── Timer ─────────────────────────────────────────────────────────────────
  function _startTimer(limitSecs) {
    const fill = document.getElementById('cs-hack-timer-fill');
    const label = document.getElementById('cs-hack-timer-text');
    _elapsed = 0;
    const tickMs = 100;

    _timer = setInterval(() => {
      _elapsed += tickMs / 1000;
      const remaining = Math.max(0, limitSecs - _elapsed);
      const pct = Math.max(0, (remaining / limitSecs) * 100);
      fill.style.width = pct + '%';
      fill.style.transition = `width ${tickMs}ms linear`;
      label.textContent = remaining.toFixed(1) + 's';

      if (pct < 25) fill.classList.add('danger');
      else fill.classList.remove('danger');

      if (_elapsed >= limitSecs && !_done) {
        _done = true;
        _stopTimer();
        _handleTimeout();
      }
    }, tickMs);
  }

  function _stopTimer() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  async function _handleTimeout() {
    if (!_puzzle) {
      _showOutcome(false, 'TRACE COMPLETE', 'Connection terminated.');
      return;
    }
    // Submit with elapsed > time_limit to trigger server-side timeout
    try {
      await fetch(`${API_BASE}/api/hack/submit`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          puzzle_id: _puzzle.puzzle_id,
          cells: [],
          elapsed: (_puzzle.time_limit || 0) + 1,
        }),
      });
    } catch (_) { /* ignore */ }
    _showOutcome(false, 'TRACE COMPLETE', 'Your signal was traced. Target locked temporarily.');
  }

  // ── Outcome screen ────────────────────────────────────────────────────────
  function _showOutcome(success, title, detail) {
    _showPuzzleBody(false);
    const outcomeEl = document.getElementById('cs-hack-outcome');
    document.getElementById('cs-hack-outcome-icon').textContent = success ? '✅' : '🔴';
    const titleEl = document.getElementById('cs-hack-outcome-title');
    titleEl.textContent = title;
    titleEl.className = 'cs-hack-outcome-title ' + (success ? 'success' : 'failure');
    document.getElementById('cs-hack-outcome-detail').textContent = detail || '';
    outcomeEl.classList.add('visible');

    // Ensure overlay is visible
    document.getElementById('cs-hack-overlay').classList.add('active');

    // Dispatch event for scene integration
    window.dispatchEvent(new CustomEvent('cs:hack:complete', {
      detail: {success, title, detail}
    }));
  }

  function _showPuzzleBody(visible = true) {
    const body = document.getElementById('cs-hack-puzzle-body');
    const outcome = document.getElementById('cs-hack-outcome');
    if (body)    body.style.display    = visible ? '' : 'none';
    if (outcome) { outcome.classList.remove('visible'); outcome.style.display = visible ? 'none' : ''; }
  }

  // ── Public API ────────────────────────────────────────────────────────────
  window.CosyHack = {
    /** Open hack interface for a target ID — fetches puzzle from API. */
    open: _open,

    /** Open with a pre-loaded puzzle object (from /api/hack/puzzle). */
    openPuzzle: _openPuzzle,

    /** Close the overlay. */
    close: _close,

    /** Check if hack overlay is currently active. */
    isOpen: () => !!(document.getElementById('cs-hack-overlay') &&
                     document.getElementById('cs-hack-overlay').classList.contains('active')),
  };

})();
