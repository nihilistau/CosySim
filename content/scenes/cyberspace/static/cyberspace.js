/**
 * cyberspace.js — CYBERSPACE Hacking Minigame Controller
 * ======================================================
 *
 * Client-side logic for the cyberspace hacking minigame.
 * Handles grid rendering, movement, program usage, narration,
 * fog-of-war, and game state management via Socket.IO.
 *
 * Version: v1.49.0 [2026-03-22]
 * Author:  CosySim Team
 *
 * Change Log:
 *   v1.49.0 [2026-03-22] — Full minigame controller: grid rendering, HUD updates,
 *                           program targeting, d-pad movement, narration feed,
 *                           game-over flow, keyboard controls
 *   v1.0.0  [2026-03-22] — Initial scaffold via Creation Kit
 */

'use strict';

// ──── Constants ──────────────────────────────────────────────────────────

// v1.49.0 [2026-03-22] — Keyboard bindings for grid movement + programs
const KEY_BINDINGS = {
  ArrowUp: 'north', ArrowDown: 'south', ArrowLeft: 'west', ArrowRight: 'east',
  w: 'north', s: 'south', a: 'west', d: 'east',
  W: 'north', S: 'south', A: 'west', D: 'east',
};

const PROGRAM_KEYS = {
  '1': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5,
};

// Programs that require a target node
const TARGETED_PROGRAMS = new Set(['decrypt', 'attack', 'exploit']);

// ──── Scene App Class ────────────────────────────────────────────────────

/**
 * CyberspaceController — main controller for the hacking minigame.
 *
 * CONNECTS: Socket.IO server, DOM elements, HackerState
 * EMITS: cyberspace_jack_in, cyberspace_move, cyberspace_use_program, cyberspace_jack_out
 */
class CyberspaceController {
  constructor() {
    this.socket = null;
    this.state = null;       // Latest cyberspace_state from server
    this.jackedIn = false;
    this.pendingProgram = null;  // Program waiting for target selection
  }

  // ── Lifecycle ──────────────────────────────────────────────────────

  /** Initialize the controller: socket, DOM bindings, keyboard. */
  // v1.49.0 [2026-03-22] — Full initialization with socket events + input handling
  init() {
    this._setupSocket();
    this._bindDom();
    this._bindKeyboard();
    console.log('[CYBERSPACE] Controller initialized');
  }

  // ── Socket.IO ──────────────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — All cyberspace Socket.IO event handlers
  // CONNECTS: CyberspaceScene Socket.IO handlers on server

  _setupSocket() {
    this.socket = io('', { transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      console.log('[CYBERSPACE] Socket connected');
    });

    // Full scene state (base HUD)
    this.socket.on('scene_state', (data) => {
      console.log('[CYBERSPACE] Scene state:', data);
    });

    // Cyberspace game state — main state push
    this.socket.on('cyberspace_state', (data) => {
      this.state = data;
      this.jackedIn = data.jacked_in;
      this._renderState(data);
    });

    // ICE encounter
    this.socket.on('ice_encounter', (data) => {
      this._addNarration(
        `ICE ATTACK at (${data.position[0]},${data.position[1]}) — ${data.damage} DMG! HP: ${data.hp_remaining}`,
        'danger'
      );
      this._flashScreen('red');
    });

    // Hack result
    this.socket.on('hack_result', (data) => {
      const cls = data.success ? 'system' : 'warning';
      this._addNarration(data.message, cls);
      if (data.narration) {
        this._addNarration(data.narration, 'llm');
      }
    });

    // Trace warning
    this.socket.on('trace_warning', (data) => {
      this._addNarration(data.message, 'warning');
      this._flashScreen('yellow');
    });

    // Flatline (game over — HP=0 or trace=100)
    this.socket.on('flatline', (data) => {
      this._addNarration(data.message, 'danger');
      this._showGameOver(data, 'flatlined');
    });

    // Escape (jack out)
    this.socket.on('escape', (data) => {
      this._addNarration(data.message || 'Jacked out safely.', 'system');
      this._showGameOver(data, 'escaped');
    });

    // LLM narration
    this.socket.on('cyberspace_narration', (data) => {
      if (data.text) {
        this._addNarration(data.text, 'llm');
      }
    });

    // Error
    this.socket.on('error', (data) => {
      console.warn('[CYBERSPACE] Error:', data.message || data);
      this._addNarration(`ERROR: ${data.message || 'Unknown error'}`, 'danger');
    });
  }

  // ── DOM Bindings ───────────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Button click handlers for jack-in, d-pad, jack-out

  _bindDom() {
    // Jack in button (splash screen)
    const jackInBtn = document.getElementById('cs-jack-in-btn');
    if (jackInBtn) {
      jackInBtn.addEventListener('click', () => this._jackIn());
    }

    // Retry button (game over screen)
    const retryBtn = document.getElementById('cs-retry-btn');
    if (retryBtn) {
      retryBtn.addEventListener('click', () => this._jackIn());
    }

    // Jack out button
    const jackOutBtn = document.getElementById('cs-jack-out-btn');
    if (jackOutBtn) {
      jackOutBtn.addEventListener('click', () => this._jackOut());
    }

    // D-pad buttons
    document.querySelectorAll('.cs-dpad-btn[data-dir]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const dir = btn.dataset.dir;
        if (dir) this._move(dir);
      });
    });

    // Cancel target selection
    const cancelTarget = document.getElementById('cs-cancel-target');
    if (cancelTarget) {
      cancelTarget.addEventListener('click', () => this._cancelTarget());
    }
  }

  // ── Keyboard ───────────────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Arrow keys + WASD for movement, 1-6 for programs

  _bindKeyboard() {
    document.addEventListener('keydown', (e) => {
      if (!this.jackedIn) return;

      // Escape to cancel target or jack out
      if (e.key === 'Escape') {
        if (this.pendingProgram) {
          this._cancelTarget();
        }
        return;
      }

      // Movement keys
      const dir = KEY_BINDINGS[e.key];
      if (dir && !this.pendingProgram) {
        e.preventDefault();
        this._move(dir);
        return;
      }

      // Program keys (1-6)
      if (PROGRAM_KEYS[e.key] !== undefined && this.state) {
        const idx = PROGRAM_KEYS[e.key];
        const programs = this.state.programs || [];
        if (idx < programs.length) {
          e.preventDefault();
          this._activateProgram(programs[idx].id);
        }
      }
    });
  }

  // ── Actions ────────────────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Client → server action dispatchers
  // EMITS: cyberspace_jack_in, cyberspace_move, cyberspace_use_program, cyberspace_jack_out

  /** Jack in — start a new cyberspace session. */
  _jackIn() {
    this._hideGameOver();
    this._hideSplash();
    this._showGame();
    this._clearNarration();
    this._addNarration('Initiating neural handshake...', 'system');
    this.socket.emit('cyberspace_jack_in');
  }

  /** Move in a direction. */
  _move(direction) {
    if (!this.jackedIn) return;
    this.socket.emit('cyberspace_move', { direction });
  }

  /** Activate a program — may require target selection. */
  _activateProgram(programId) {
    if (!this.jackedIn) return;
    if (!this.state) return;

    // Check if available
    const prog = (this.state.programs || []).find((p) => p.id === programId);
    if (!prog || !prog.available) {
      this._addNarration(`${prog ? prog.name : programId} not available.`, 'warning');
      return;
    }

    // Targeted programs need node selection
    if (TARGETED_PROGRAMS.has(programId)) {
      this.pendingProgram = programId;
      this._showTargetPrompt();
      this._highlightTargetableNodes(programId);
      return;
    }

    // Non-targeted programs fire immediately
    this.socket.emit('cyberspace_use_program', { program: programId });
  }

  /** Use a program on a target node. */
  _useProgramOnTarget(row, col) {
    if (!this.pendingProgram) return;
    const programId = this.pendingProgram;
    this.pendingProgram = null;
    this._hideTargetPrompt();
    this._clearTargetHighlights();
    this.socket.emit('cyberspace_use_program', {
      program: programId,
      target: [row, col],
    });
  }

  /** Cancel target selection mode. */
  _cancelTarget() {
    this.pendingProgram = null;
    this._hideTargetPrompt();
    this._clearTargetHighlights();
  }

  /** Jack out — safe escape. */
  _jackOut() {
    if (!this.jackedIn) return;
    this.socket.emit('cyberspace_jack_out');
  }

  // ── Rendering ──────────────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Full state rendering: grid, HUD, programs, data

  /**
   * Render the full cyberspace game state.
   * @param {Object} data — cyberspace_state from server
   */
  _renderState(data) {
    if (!data) return;
    this._renderGrid(data);
    this._renderHud(data);
    this._renderPrograms(data);
    this._renderDataList(data);

    // Check for game over
    if (!data.jacked_in && data.result && data.result !== 'active') {
      // Game over is handled by specific event handlers (flatline/escape)
      // but also handle it here as a fallback
      if (data.result === 'traced') {
        this._showGameOver({
          message: 'TRACED. Corporate security locked your signal.',
          credits_kept: data.credits_stolen,
          turns_survived: data.turns,
        }, 'traced');
      }
    }
  }

  /**
   * Render the 5x5 network grid with fog-of-war.
   * @param {Object} data — cyberspace_state
   */
  // CONNECTS: cs-grid DOM element, data.grid, data.position
  _renderGrid(data) {
    const gridEl = document.getElementById('cs-grid');
    if (!gridEl) return;

    gridEl.innerHTML = '';
    const grid = data.grid || [];
    const [playerR, playerC] = data.position || [0, 0];

    for (let r = 0; r < (data.grid_size?.rows || 5); r++) {
      for (let c = 0; c < (data.grid_size?.cols || 5); c++) {
        const node = grid[r] ? grid[r][c] : null;
        const cell = document.createElement('div');
        cell.className = 'cs-node';
        cell.dataset.row = r;
        cell.dataset.col = c;

        if (!node || !node.visible) {
          // Fog of war
          cell.classList.add('cs-node-unknown');
          cell.innerHTML = '<span class="cs-node-icon">?</span><span class="cs-node-label">???</span>';
        } else {
          cell.classList.add('cs-node-visible');
          cell.classList.add(`cs-node-${node.type}`);

          if (node.hacked) cell.classList.add('cs-node-hacked');
          if (node.destroyed) cell.classList.add('cs-node-destroyed');

          cell.innerHTML = `<span class="cs-node-icon">${node.icon}</span><span class="cs-node-label">${node.name}</span>`;
          cell.title = node.description || node.name;
        }

        // Player marker
        if (r === playerR && c === playerC) {
          cell.classList.add('cs-node-player');
        }

        // Click handler for target selection
        cell.addEventListener('click', () => {
          if (this.pendingProgram) {
            this._useProgramOnTarget(r, c);
          }
        });

        gridEl.appendChild(cell);
      }
    }
  }

  /**
   * Update HUD bars and values.
   * @param {Object} data — cyberspace_state
   */
  // CONNECTS: cs-hp-bar, cs-trace-bar, cs-credits-text, cs-turn-text
  _renderHud(data) {
    // HP bar
    const hpBar = document.getElementById('cs-hp-bar');
    const hpText = document.getElementById('cs-hp-text');
    if (hpBar && hpText) {
      const hpPct = Math.max(0, Math.min(100, (data.hp / (data.max_hp || 100)) * 100));
      hpBar.style.width = hpPct + '%';
      hpText.textContent = data.hp;
      hpBar.classList.toggle('cs-bar-low', data.hp <= 30);
    }

    // Trace bar
    const traceBar = document.getElementById('cs-trace-bar');
    const traceText = document.getElementById('cs-trace-text');
    if (traceBar && traceText) {
      traceBar.style.width = data.trace_level + '%';
      traceText.textContent = data.trace_level + '%';
      traceBar.classList.toggle('cs-bar-critical', data.trace_level >= 70);
    }

    // Credits
    const creditsText = document.getElementById('cs-credits-text');
    if (creditsText) {
      creditsText.textContent = '\u00A4' + data.credits_stolen;
    }

    // Turn
    const turnText = document.getElementById('cs-turn-text');
    if (turnText) {
      turnText.textContent = data.turns;
    }

    // Cloak indicator
    const cloakIndicator = document.getElementById('cs-cloak-indicator');
    const cloakText = document.getElementById('cs-cloak-text');
    if (cloakIndicator && cloakText) {
      if (data.cloak_remaining > 0) {
        cloakIndicator.style.display = '';
        cloakText.textContent = data.cloak_remaining;
      } else {
        cloakIndicator.style.display = 'none';
      }
    }
  }

  /**
   * Render the programs panel.
   * @param {Object} data — cyberspace_state
   */
  // CONNECTS: cs-programs DOM element
  _renderPrograms(data) {
    const container = document.getElementById('cs-programs');
    if (!container) return;

    container.innerHTML = '';
    const programs = data.programs || [];

    programs.forEach((prog, idx) => {
      const btn = document.createElement('button');
      btn.className = 'cs-program-btn';
      btn.disabled = !prog.available;

      const keyHint = idx < 6 ? `[${idx + 1}]` : '';
      btn.innerHTML = `
        <span class="cs-program-name">${keyHint} ${prog.name}</span>
        <span class="cs-program-desc">${prog.description}</span>
        ${prog.cost > 0 ? `<span class="cs-program-cost">+${prog.cost}T</span>` : ''}
        ${prog.cooldown_remaining > 0 ? `<span class="cs-program-cd">CD:${prog.cooldown_remaining}</span>` : ''}
      `;

      btn.addEventListener('click', () => {
        if (!btn.disabled) {
          this._activateProgram(prog.id);
        }
      });

      container.appendChild(btn);
    });
  }

  /**
   * Render the stolen data list.
   * @param {Object} data — cyberspace_state
   */
  _renderDataList(data) {
    const container = document.getElementById('cs-data-list');
    if (!container) return;

    const items = data.data_stolen || [];
    if (items.length === 0) {
      container.innerHTML = '<p class="cs-dim">No data stolen yet.</p>';
    } else {
      container.innerHTML = items.map(
        (id) => `<div class="cs-data-item">&gt; ${id}</div>`
      ).join('');
    }
  }

  // ── Narration Feed ─────────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Narration log rendering with auto-scroll

  /**
   * Add a line to the narration feed.
   * @param {string} text — narration text
   * @param {string} [cls='system'] — CSS modifier: system, llm, warning, danger
   */
  _addNarration(text, cls = 'system') {
    const feed = document.getElementById('cs-narration');
    if (!feed) return;

    // Remove placeholder
    const placeholder = feed.querySelector('.cs-dim');
    if (placeholder) placeholder.remove();

    const line = document.createElement('p');
    line.className = `cs-narration-line cs-narration-${cls}`;
    line.textContent = `> ${text}`;
    feed.appendChild(line);

    // Auto-scroll to bottom
    feed.scrollTop = feed.scrollHeight;

    // Cap at 50 lines
    while (feed.children.length > 50) {
      feed.removeChild(feed.firstChild);
    }
  }

  /** Clear the narration feed. */
  _clearNarration() {
    const feed = document.getElementById('cs-narration');
    if (feed) {
      feed.innerHTML = '<p class="cs-narration-line cs-dim">Awaiting connection...</p>';
    }
  }

  // ── Target Selection ───────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Target mode for programs that need a node selection

  /** Show target selection prompt. */
  _showTargetPrompt() {
    const el = document.getElementById('cs-target-prompt');
    if (el) el.style.display = '';
  }

  /** Hide target selection prompt. */
  _hideTargetPrompt() {
    const el = document.getElementById('cs-target-prompt');
    if (el) el.style.display = 'none';
  }

  /**
   * Highlight nodes that can be targeted by the active program.
   * @param {string} programId — program identifier
   */
  _highlightTargetableNodes(programId) {
    if (!this.state) return;
    const [pr, pc] = this.state.position || [0, 0];
    const grid = this.state.grid || [];

    // Only adjacent nodes are targetable
    const adjacent = [
      [pr - 1, pc], [pr + 1, pc], [pr, pc - 1], [pr, pc + 1],
    ];

    adjacent.forEach(([r, c]) => {
      if (r < 0 || r >= 5 || c < 0 || c >= 5) return;
      const node = grid[r] ? grid[r][c] : null;
      if (!node || !node.visible) return;

      // Filter by program type
      let valid = false;
      if (programId === 'decrypt' && (node.type === 'data_vault' || node.type === 'firewall') && !node.hacked) valid = true;
      if (programId === 'attack' && node.type === 'ice_node' && !node.destroyed) valid = true;
      if (programId === 'exploit' && node.type === 'firewall' && !node.hacked && !node.destroyed) valid = true;

      if (valid) {
        const cell = document.querySelector(`.cs-node[data-row="${r}"][data-col="${c}"]`);
        if (cell) cell.classList.add('cs-node-targetable');
      }
    });
  }

  /** Remove all target highlights. */
  _clearTargetHighlights() {
    document.querySelectorAll('.cs-node-targetable').forEach((el) => {
      el.classList.remove('cs-node-targetable');
    });
  }

  // ── Screen Transitions ─────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Splash, game, game-over screen transitions

  _hideSplash() {
    const el = document.getElementById('cs-splash');
    if (el) el.style.display = 'none';
  }

  _showGame() {
    const el = document.getElementById('cs-game');
    if (el) el.style.display = '';
  }

  _hideGame() {
    const el = document.getElementById('cs-game');
    if (el) el.style.display = 'none';
  }

  /**
   * Show game over overlay with result stats.
   * @param {Object} data — event data from server
   * @param {string} result — 'flatlined', 'traced', or 'escaped'
   */
  _showGameOver(data, result) {
    const overlay = document.getElementById('cs-gameover');
    if (!overlay) return;

    const title = document.getElementById('cs-gameover-title');
    const msg = document.getElementById('cs-gameover-message');
    const credits = document.getElementById('cs-gameover-credits');
    const turns = document.getElementById('cs-gameover-turns');
    const dataCount = document.getElementById('cs-gameover-data');
    const narration = document.getElementById('cs-gameover-narration');

    if (title) {
      if (result === 'flatlined') {
        title.textContent = 'FLATLINE';
        title.className = 'cs-gameover-title cs-gameover-flatline';
      } else if (result === 'traced') {
        title.textContent = 'TRACED';
        title.className = 'cs-gameover-title cs-gameover-traced';
      } else {
        title.textContent = 'ESCAPED';
        title.className = 'cs-gameover-title cs-gameover-escaped';
      }
    }

    if (msg) msg.textContent = data.message || '';

    const creditVal = data.credits_earned || data.credits_kept || data.credits_lost || 0;
    if (credits) credits.textContent = '\u00A4' + creditVal;
    if (turns) turns.textContent = data.turns_survived || data.turns || 0;
    if (dataCount) {
      const stolen = this.state ? (this.state.data_stolen || []).length : 0;
      dataCount.textContent = stolen;
    }
    if (narration) narration.textContent = data.narration || '';

    overlay.style.display = '';
    this.jackedIn = false;
  }

  _hideGameOver() {
    const el = document.getElementById('cs-gameover');
    if (el) el.style.display = 'none';
  }

  // ── Visual Effects ─────────────────────────────────────────────────
  // v1.49.0 [2026-03-22] — Screen flash for damage/warning events

  /**
   * Flash the screen border a color briefly.
   * @param {string} color — 'red' or 'yellow'
   */
  _flashScreen(color) {
    const scene = document.querySelector('.cyberspace-scene');
    if (!scene) return;

    const flashColor = color === 'red'
      ? 'rgba(255, 0, 64, 0.15)'
      : 'rgba(255, 204, 0, 0.1)';

    scene.style.boxShadow = `inset 0 0 60px ${flashColor}`;
    setTimeout(() => {
      scene.style.boxShadow = '';
    }, 300);
  }
}

// ──── Bootstrap ──────────────────────────────────────────────────────────

const cyberspaceApp = new CyberspaceController();

document.addEventListener('DOMContentLoaded', () => {
  cyberspaceApp.init();
});
