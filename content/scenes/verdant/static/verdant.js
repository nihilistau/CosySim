/**
 * Verdant Realms — Scene Controller
 * =================================
 * Drives the dual-agent LitRPG UI: starts a session, renders Director
 * narration + Companion asides, wires the action rail (d20 / skill check /
 * combat / party / end turn), and keeps the stat bars, faction standings,
 * quest tracker, and event timeline in sync with the backend + Socket.IO.
 *
 * Backend contract (content/scenes/verdant/verdant_scene.py):
 *   POST /api/verdant/new                  → opening beat
 *   POST /api/verdant/action {type,...}    → next beat
 *   GET  /api/verdant/state                → full state snapshot
 *   Socket.IO: verdant_state | turn_update | dice_roll | combat_update | level_up
 *
 * Version: v1.64.0 [2026-06-27]
 * Author:  CosySim Team
 *
 * Change Log:
 *   v1.64.0 [2026-06-27] — Initial controller: session bootstrap, beat
 *                          rendering, action rail wiring, live state sync.
 */

/* ──── Scene Controller ──────────────────────────────────────────────── */

class VerdantRealmsScene {
  constructor() {
    this.state = null;
    this.socket = null;
    this.busy = false;
  }

  /* ──── Bootstrap ──────────────────────────────────────────────────── */

  init() {
    // Live socket (best-effort — REST is the source of truth).
    try {
      this.socket = io();
      this.socket.on('verdant_state', (s) => this.applyState(s));
      this.socket.on('turn_update', (s) => this.applyState(s));
      this.socket.on('dice_roll', (r) => this.showDice(r));
      this.socket.on('combat_update', (c) => { if (c.state) this.applyState(c.state); });
      this.socket.on('level_up', (r) => this.pushEvent(`✨ Level up! You are now level ${r.level}.`));
    } catch (e) {
      console.warn('[verdant] socket unavailable, REST only', e);
    }

    // Resume an active session if one exists, else start fresh.
    fetch('/api/verdant/state')
      .then((r) => r.json())
      .then((s) => {
        if (s && s.active) {
          this.applyState(s);
          this.pushEvent('Resumed your journey through the Verdant Realms.');
        } else {
          this.newGame();
        }
      })
      .catch(() => this.newGame());
  }

  /* ──── Networking ─────────────────────────────────────────────────── */

  async newGame() {
    if (this.busy) return;
    this.busy = true;
    this.setNarration('The canopy stirs…');
    try {
      const res = await fetch('/api/verdant/new', { method: 'POST' });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      this.handleBeat(data);
    } catch (e) {
      this.setNarration('The weave is quiet. (Could not reach the Director.)');
      console.error('[verdant] newGame failed', e);
    } finally {
      this.busy = false;
    }
  }

  async action(payload) {
    if (this.busy) return;
    this.busy = true;
    this.pulseCursor(true);
    try {
      const res = await fetch('/api/verdant/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      this.handleBeat(data);
    } catch (e) {
      this.pushEvent('The realm did not answer. Try again.');
      console.error('[verdant] action failed', e);
    } finally {
      this.busy = false;
      this.pulseCursor(false);
    }
  }

  /* ──── Action rail (called from template onclick) ─────────────────── */

  sendMessage() {
    const input = document.getElementById('custom-input');
    const text = (input.value || '').trim();
    if (!text) return;
    input.value = '';
    this.pushEvent(`▸ ${text}`);
    this.action({ type: 'message', text });
  }

  chooseOption(id, text) {
    this.pushEvent(`▸ ${text}`);
    this.action({ type: 'choice', choice_id: id });
  }

  rollD20()    { this.action({ type: 'roll_d20' }); }
  skillCheck() { this.action({ type: 'skill_check' }); }
  combat()     { this.action({ type: 'combat' }); }
  party()      { this.action({ type: 'party' }); }
  endTurn()    { this.action({ type: 'end_turn' }); }

  /* ──── Rendering ──────────────────────────────────────────────────── */

  handleBeat(data) {
    if (data.narration) this.setNarration(data.narration);
    if (data.companion) this.showCompanion(data.companion);
    if (Array.isArray(data.choices)) this.renderChoices(data.choices);
    if (data.state) this.applyState(data.state);
  }

  setNarration(text) {
    const el = document.getElementById('narrative-text');
    if (!el) return;
    el.innerHTML = '';
    const span = document.createElement('span');
    span.textContent = text;
    el.appendChild(span);
    const cursor = document.createElement('span');
    cursor.className = 'narrative-cursor';
    cursor.id = 'narrative-cursor';
    cursor.textContent = '▌';
    el.appendChild(cursor);
  }

  showCompanion(text) {
    if (!text) return;
    this.pushEvent(`🧭 ${text}`);
  }

  renderChoices(choices) {
    const wrap = document.getElementById('vd-choices');
    if (!wrap) return;
    wrap.innerHTML = '';
    choices.forEach((c) => {
      const btn = document.createElement('button');
      btn.className = 'vd-choice';
      btn.textContent = c.text;
      btn.onclick = () => this.chooseOption(c.id, c.text);
      wrap.appendChild(btn);
    });
  }

  applyState(s) {
    if (!s) return;
    this.state = s;

    // Turn counter.
    const turn = document.getElementById('turn-counter');
    if (turn && typeof s.turn_number === 'number') turn.textContent = `Turn ${s.turn_number}`;

    // Director / Companion meters.
    if (s.director) {
      this.setBar('stat-influence', 'stat-influence-val', s.director.influence, 100);
      this.setBar('stat-threads', 'stat-threads-val', s.director.threads, 5, true);
    }
    if (s.companion) {
      this.setBar('stat-loyalty', 'stat-loyalty-val', s.companion.loyalty, 100);
      this.setBar('stat-focus', 'stat-focus-val', s.companion.focus, 4, true);
    }

    // Faction standings.
    if (s.factions) this.renderFactions(s.factions);

    // Active quest.
    if (s.quest) this.renderQuest(s.quest);

    // Choices (in case state carried them).
    if (Array.isArray(s.choices) && s.choices.length) this.renderChoices(s.choices);
  }

  setBar(barId, valId, value, max, fraction) {
    const bar = document.getElementById(barId);
    const val = document.getElementById(valId);
    if (typeof value !== 'number') return;
    const pct = Math.max(0, Math.min(100, (value / max) * 100));
    if (bar) bar.style.width = `${pct}%`;
    if (val) val.textContent = fraction ? `${value} / ${max}` : `${value} / ${max}`;
  }

  renderFactions(factions) {
    const list = document.getElementById('faction-list');
    if (!list) return;
    list.innerHTML = '';
    Object.entries(factions).forEach(([key, f]) => {
      const row = document.createElement('div');
      row.className = 'faction-entry';
      row.dataset.faction = key;
      row.innerHTML =
        `<span class="faction-icon">${f.icon || '◆'}</span>` +
        `<span class="faction-name">${f.name || key}</span>` +
        `<div class="faction-bar-wrap"><div class="faction-bar" style="width:${f.standing || 0}%"></div></div>`;
      list.appendChild(row);
    });
  }

  renderQuest(q) {
    const setText = (id, t) => { const e = document.getElementById(id); if (e) e.textContent = t; };
    setText('quest-title', q.title || 'No active quest');
    setText('quest-objective', q.objective || '—');
    const goal = q.goal || 0;
    const prog = q.progress || 0;
    const bar = document.getElementById('quest-progress-bar');
    if (bar) bar.style.width = goal ? `${(prog / goal) * 100}%` : '0%';
    setText('quest-progress-label', `${prog} / ${goal}`);
  }

  showDice(r) {
    if (!r) return;
    const nat = r.natural != null ? r.natural : '?';
    const total = r.total != null ? r.total : nat;
    let line = `⚄ Rolled d20: ${nat}`;
    if (r.modifier) line += ` (${r.modifier >= 0 ? '+' : ''}${r.modifier}) = ${total}`;
    if (r.crit) line += ' — NAT 20!';
    if (r.fumble) line += ' — fumble!';
    if (r.skill) line += ` · ${r.skill} vs DC ${r.dc} → ${r.success ? 'SUCCESS' : 'FAIL'}`;
    this.pushEvent(line);
  }

  pushEvent(text) {
    const list = document.getElementById('timeline-list');
    if (!list) return;
    const li = document.createElement('li');
    li.className = 'timeline-item';
    li.textContent = text;
    list.insertBefore(li, list.firstChild);
    // Cap the timeline length.
    while (list.children.length > 30) list.removeChild(list.lastChild);
  }

  pulseCursor(on) {
    const cursor = document.getElementById('narrative-cursor');
    if (cursor) cursor.style.opacity = on ? '1' : '';
  }
}

/* Expose for the template's inline bootstrap. */
window.VerdantRealmsScene = VerdantRealmsScene;
