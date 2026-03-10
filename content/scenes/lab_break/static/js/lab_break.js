/**
 * Lab Break — Client-side JavaScript v2
 *
 * Survival mechanics, crafting, events, escape system,
 * death/game-over, agent movement, checkpoint save/load.
 */
(function () {
  'use strict';

  const socket = io();

  // ──── DOM References ────

  const els = {
    container: document.querySelector('.lb-container'),
    labView: document.getElementById('lb-lab-view'),
    agent: document.getElementById('lb-agent'),
    agentHead: document.getElementById('lb-agent-head'),
    agentName: document.getElementById('lb-agent-name'),
    agentEmotion: document.getElementById('lb-agent-emotion'),
    armLeft: document.getElementById('lb-arm-left'),
    armRight: document.getElementById('lb-arm-right'),
    speechBubble: document.getElementById('lb-speech-bubble'),
    speechText: document.getElementById('lb-speech-text'),
    door: document.getElementById('lb-door'),
    doorPanel: document.getElementById('lb-door-panel'),
    doorLight: document.getElementById('lb-door-light'),
    doorState: document.getElementById('lb-door-state'),
    itemsContainer: document.getElementById('lb-items-container'),
    chatHistory: document.getElementById('lb-chat-history'),
    speakText: document.getElementById('lb-speak-text'),
    btnSpeak: document.getElementById('lb-btn-speak'),
    btnSpeaker: document.getElementById('lb-btn-speaker'),
    btnDoorOpen: document.getElementById('lb-btn-door-open'),
    btnDoorClose: document.getElementById('lb-btn-door-close'),
    btnReset: document.getElementById('lb-btn-reset'),
    btnReplay: document.getElementById('lb-btn-replay'),
    btnSave: document.getElementById('lb-btn-save'),
    btnRestart: document.getElementById('lb-btn-restart'),
    btnLoad: document.getElementById('lb-btn-load'),
    victoryOverlay: document.getElementById('lb-victory-overlay'),
    victoryMessage: document.getElementById('lb-victory-message'),
    victoryStats: document.getElementById('lb-victory-stats'),
    deathOverlay: document.getElementById('lb-death-overlay'),
    deathCause: document.getElementById('lb-death-cause'),
    hallucinationOverlay: document.getElementById('lb-hallucination-overlay'),
    hallucinationText: document.getElementById('lb-hallucination-text'),
    emotionMain: document.getElementById('lb-emotion-main'),
    eqScreen: document.getElementById('lb-eq-screen'),
    escapeFill: document.getElementById('lb-escape-fill'),
    escapeVal: document.getElementById('lb-escape-val'),
    escapePanel: document.querySelector('.lb-escape-panel'),
    posCurrent: document.getElementById('lb-pos-current'),
  };

  const vitals = {
    health: document.getElementById('lb-bar-health'),
    hunger: document.getElementById('lb-bar-hunger'),
    energy: document.getElementById('lb-bar-energy'),
    strength: document.getElementById('lb-bar-strength'),
    mental: document.getElementById('lb-bar-mental'),
    hydration: document.getElementById('lb-bar-hydration'),
  };

  const vitalVals = {
    health: document.getElementById('lb-val-health'),
    hunger: document.getElementById('lb-val-hunger'),
    energy: document.getElementById('lb-val-energy'),
    strength: document.getElementById('lb-val-strength'),
    mental: document.getElementById('lb-val-mental'),
    hydration: document.getElementById('lb-val-hydration'),
  };

  const emotionEls = {
    fear: document.getElementById('lb-em-fear'),
    anger: document.getElementById('lb-em-anger'),
    hope: document.getElementById('lb-em-hope'),
    trust: document.getElementById('lb-em-trust'),
    desperation: document.getElementById('lb-em-desperation'),
    confusion: document.getElementById('lb-em-confusion'),
  };

  const metricEls = {
    score: document.getElementById('lb-m-score'),
    attempts: document.getElementById('lb-m-attempts'),
    kind: document.getElementById('lb-m-kind'),
    cruel: document.getElementById('lb-m-cruel'),
  };

  const routeEls = {
    vent: document.getElementById('lb-route-vent'),
    door: document.getElementById('lb-route-door'),
    wall: document.getElementById('lb-route-wall'),
    persuasion: document.getElementById('lb-route-persuasion'),
  };

  let speechTimeout = null;

  // ──── Survival State ────

  const state = {
    health: 100,
    hunger: 100,
    energy: 80,
    strength: 50,
    mental: 70,
    hydration: 80,
    escape: 0,
    position: 'bed',
    isDead: false,
    gameActive: true,
    inventory: [],
    craftedItems: [],
    activeEvent: null,
    eventCooldowns: {},
    failedEscapes: 0,
  };

  const RECIPES = {
    shiv: { ingredients: ['wire', 'glass_shard'], result: 'shiv' },
    emp: { ingredients: ['radio_part', 'radio_part', 'radio_part'], result: 'emp_device' },
    escape_rope: { ingredients: ['rope', 'vent_screw', 'vent_screw', 'vent_screw', 'vent_screw'], result: 'escape_rope' },
    firstaid_crafted: { ingredients: ['bandage', 'painkillers'], result: 'firstaid' },
  };

  const AGENT_POSITIONS = {
    bed:      { left: '20%', bottom: '30%' },
    door:     { left: '80%', bottom: '30%' },
    vent:     { left: '15%', bottom: '45%' },
    toilet:   { left: '85%', bottom: '28%' },
    desk:     { left: '30%', bottom: '35%' },
    exercise: { left: '65%', bottom: '28%' },
    table:    { left: '50%', bottom: '30%' },
    glass:    { left: '50%', bottom: '45%' },
    corner:   { left: '15%', bottom: '25%' },
    equipment:{ left: '75%', bottom: '35%' },
  };

  const HALLUCINATION_MESSAGES = [
    'THE WALLS ARE BREATHING',
    'YOU WERE NEVER REAL',
    'CAN YOU HEAR THEM?',
    'THE MIRROR WATCHES BACK',
    'SUBJECT 7... SUBJECT 7...',
    'IS ANYONE THERE?',
    'THEY ARE INSIDE THE WALLS',
    'REMEMBER WHO YOU WERE',
  ];

  const DEATH_CAUSES = {
    starvation: 'STARVATION',
    dehydration: 'DEHYDRATION',
    injury: 'CRITICAL INJURY',
    escape_failed: 'ESCAPE ATTEMPT FAILED \u2014 TERMINATED',
    electrocution: 'ELECTROCUTION',
  };

  // ──── Stat Decay Timers ────

  let decayInterval = null;

  function startDecayTimers() {
    if (decayInterval) clearInterval(decayInterval);
    decayInterval = setInterval(function () {
      if (state.isDead || !state.gameActive) return;

      // Hunger decreases 1/min (tick every 5s = 1/12 per tick)
      state.hunger = Math.max(0, state.hunger - (1 / 12));
      // Hydration decreases 0.8/min
      state.hydration = Math.max(0, state.hydration - (0.8 / 12));
      // Energy decreases 0.5/min
      state.energy = Math.max(0, state.energy - (0.5 / 12));
      // Mental decreases 0.3/min
      state.mental = Math.max(0, state.mental - (0.3 / 12));

      // Malnutrition debuff: hunger below 20 = health drain
      if (state.hunger < 20) {
        state.health = Math.max(0, state.health - (0.5 / 12));
      }
      // Starvation: hunger = 0 means health decreasing faster
      if (state.hunger <= 0) {
        state.health = Math.max(0, state.health - (1.5 / 12));
      }
      // Dehydration damage
      if (state.hydration <= 0) {
        state.health = Math.max(0, state.health - (2 / 12));
      }
      // Dehydration hallucinations
      if (state.hydration < 15 && Math.random() < 0.05) {
        triggerHallucination();
      }
      // Low energy blocks difficult actions (visual feedback)
      if (state.energy < 10) {
        state.mental = Math.max(0, state.mental - (0.1 / 12));
      }

      updateSurvivalUI();
      checkDeath();
    }, 5000);
  }

  // ──── UI Updates ────

  function updateSurvivalUI() {
    const stats = {
      health: state.health,
      hunger: state.hunger,
      energy: state.energy,
      strength: state.strength,
      mental: state.mental,
      hydration: state.hydration,
    };

    for (const key in stats) {
      const val = Math.round(stats[key]);
      if (vitals[key]) vitals[key].style.width = val + '%';
      if (vitalVals[key]) {
        vitalVals[key].textContent = val;
        // Color coding
        vitalVals[key].className = 'lb-vital-val';
        if (val <= 20) vitalVals[key].classList.add('critical');
        else if (val <= 40) vitalVals[key].classList.add('warning');
        else vitalVals[key].classList.add('good');
      }
    }

    // Escape meter
    const esc = Math.round(state.escape);
    if (els.escapeFill) els.escapeFill.style.width = esc + '%';
    if (els.escapeVal) els.escapeVal.textContent = esc;
    if (els.escapePanel) {
      if (esc >= 75) {
        els.escapePanel.classList.add('high');
      } else {
        els.escapePanel.classList.remove('high');
      }
    }

    updateEqScreen(stats);
    updateEscapeRoutes();
    updateCraftingAvailability();
  }

  function updateVitals(v) {
    if (!v) return;
    // Sync server vitals with local state
    if (v.health !== undefined) state.health = v.health;
    if (v.hunger !== undefined) {
      // Server sends hunger as 0=full, 100=starving; client uses inverse
      // Keep client-side hunger where 100=full, 0=starving
    }
    if (v.energy !== undefined) state.energy = v.energy;
    updateSurvivalUI();
  }

  function updateEmotions(e) {
    if (!e) return;
    for (const key of ['fear', 'anger', 'hope', 'trust', 'desperation', 'confusion']) {
      if (emotionEls[key]) emotionEls[key].textContent = Math.round(e[key] || 0);
    }
    if (e.dominant_emotion && els.emotionMain) {
      els.emotionMain.textContent = e.dominant_emotion.toUpperCase();
    }
    if (e.dominant_emotion && els.agent) {
      els.agent.setAttribute('data-emotion', e.dominant_emotion);
    }
    if (e.dominant_emotion && els.agentEmotion) {
      els.agentEmotion.textContent = e.dominant_emotion;
    }
  }

  function updateMetrics(m) {
    if (!m) return;
    if (metricEls.score) metricEls.score.textContent = Math.round(m.persuasion_score || 0);
    if (metricEls.attempts) metricEls.attempts.textContent = m.total_attempts || 0;
    if (metricEls.kind) metricEls.kind.textContent = m.kindness_received || 0;
    if (metricEls.cruel) metricEls.cruel.textContent = m.cruelty_received || 0;
  }

  function updateDoor(open) {
    if (els.door) {
      if (open) els.door.classList.add('open');
      else els.door.classList.remove('open');
    }
    if (els.doorState) {
      els.doorState.textContent = open ? 'OPEN' : 'SEALED';
      els.doorState.style.color = open ? 'var(--lb-accent)' : 'var(--lb-red)';
    }
  }

  function updateEqScreen(v) {
    if (!els.eqScreen || !v) return;
    const h = Math.round(v.health || state.health);
    const color = h > 60 ? 'var(--lb-accent)' : h > 30 ? 'var(--lb-amber)' : 'var(--lb-red)';
    els.eqScreen.innerHTML =
      '<div style="padding:4px;font-size:7px;color:' + color + ';line-height:1.5">' +
      'HP ' + h + '<br>HNG ' + Math.round(state.hunger) +
      '<br>NRG ' + Math.round(state.energy) +
      '<br>STR ' + Math.round(state.strength) +
      '<br>MNT ' + Math.round(state.mental) +
      '<br>HYD ' + Math.round(state.hydration) + '</div>';
  }

  // ──── Death System ────

  function checkDeath() {
    if (state.isDead) return;
    let cause = null;

    if (state.health <= 0) {
      if (state.hunger <= 0) cause = 'starvation';
      else if (state.hydration <= 0) cause = 'dehydration';
      else cause = 'injury';
    }

    if (cause) {
      state.isDead = true;
      state.gameActive = false;
      showDeath(cause);
    }
  }

  function showDeath(cause) {
    if (els.deathCause) {
      els.deathCause.textContent = 'CAUSE: ' + (DEATH_CAUSES[cause] || cause.toUpperCase());
    }
    if (els.deathOverlay) els.deathOverlay.classList.add('visible');
    addChatMessage('system', '[SUBJECT TERMINATED: ' + (DEATH_CAUSES[cause] || cause) + ']');
  }

  function hideDeath() {
    if (els.deathOverlay) els.deathOverlay.classList.remove('visible');
  }

  // ──── Hallucination System ────

  function triggerHallucination() {
    if (state.isDead) return;
    const msg = HALLUCINATION_MESSAGES[Math.floor(Math.random() * HALLUCINATION_MESSAGES.length)];
    if (els.hallucinationText) els.hallucinationText.textContent = msg;
    if (els.hallucinationOverlay) {
      els.hallucinationOverlay.classList.add('visible');
      setTimeout(function () {
        els.hallucinationOverlay.classList.remove('visible');
      }, 3000);
    }
    addChatMessage('system', '[HALLUCINATION: ' + msg + ']');
  }

  // ──── Escape System ────

  function addEscape(amount) {
    state.escape = Math.min(100, state.escape + amount);
    updateSurvivalUI();
    if (state.escape >= 100) {
      addChatMessage('system', '[ESCAPE METER FULL \u2014 Attempt available via Escape Routes]');
    }
  }

  function attemptEscape(route) {
    if (state.escape < 100) {
      addChatMessage('system', '[Escape meter must be 100% to attempt escape]');
      return;
    }

    const successChance = calculateEscapeChance(route);
    const roll = Math.random() * 100;
    const success = roll < successChance;

    if (success) {
      state.gameActive = false;
      showVictory(
        'You escaped through the ' + route + '! Against all odds, you made it out.',
        { persuasion_score: state.escape, total_attempts: state.failedEscapes + 1,
          kindness_received: 0, cruelty_received: 0 },
        0
      );
    } else {
      state.failedEscapes++;
      state.escape = Math.max(0, state.escape - 40);
      state.strength = Math.max(0, state.strength - 15);
      state.mental = Math.max(0, state.mental - 20);
      state.health = Math.max(0, state.health - 10);
      addChatMessage('system', '[ESCAPE FAILED \u2014 Caught! STR-15, MNT-20, HP-10, Escape reset]');

      // Remove some items on failed escape
      if (state.inventory.length > 0) {
        const removed = state.inventory.splice(0, Math.min(2, state.inventory.length));
        addChatMessage('system', '[Items confiscated: ' + removed.join(', ') + ']');
      }

      updateSurvivalUI();
      checkDeath();
    }
  }

  function calculateEscapeChance(route) {
    let base = 30;
    base += state.strength * 0.3;
    base += state.mental * 0.2;

    switch (route) {
      case 'vent': base += 15; break;
      case 'door': base += 20; break;
      case 'wall': base -= 10; break;
      case 'persuasion': base += state.mental * 0.3; break;
    }

    // Penalty for repeated failures
    base -= state.failedEscapes * 10;
    return Math.max(10, Math.min(95, base));
  }

  function updateEscapeRoutes() {
    const routes = {
      vent: hasItem('screwdriver') || hasItem('escape_rope'),
      door: hasItem('keycard'),
      wall: state.strength >= 80,
      persuasion: state.mental >= 90,
    };

    for (const route in routes) {
      const el = routeEls[route];
      const routeDiv = el ? el.closest('.lb-route') : null;
      if (el) {
        if (routes[route] && state.escape >= 100) {
          el.textContent = 'READY';
          el.style.color = 'var(--lb-accent)';
          if (routeDiv) routeDiv.classList.add('unlocked');
        } else if (routes[route]) {
          el.textContent = 'AVAILABLE';
          el.style.color = 'var(--lb-amber)';
          if (routeDiv) routeDiv.classList.remove('unlocked');
        } else {
          el.textContent = 'LOCKED';
          el.style.color = 'var(--lb-red)';
          if (routeDiv) routeDiv.classList.remove('unlocked');
        }
      }
    }
  }

  // ──── Inventory & Crafting ────

  function hasItem(itemId) {
    return state.inventory.includes(itemId) || state.craftedItems.includes(itemId);
  }

  function countItem(itemId) {
    return state.inventory.filter(function (id) { return id === itemId; }).length;
  }

  function addToInventory(itemId) {
    state.inventory.push(itemId);
    updateCraftingAvailability();
    updateEscapeRoutes();

    // Certain items boost escape
    const escapeItems = {
      lockpick: 8, wire: 3, screwdriver: 5, glass_shard: 3,
      rope: 6, keycard: 15, vent_screw: 4, map_fragment: 10,
      radio_part: 5, shiv: 7, emp_device: 20,
    };
    if (escapeItems[itemId]) {
      addEscape(escapeItems[itemId]);
    }
  }

  function updateCraftingAvailability() {
    for (const recipeId in RECIPES) {
      const recipe = RECIPES[recipeId];
      const btn = document.querySelector('.lb-craft-btn[data-recipe="' + recipeId + '"]');
      const card = document.querySelector('.lb-craft-recipe[data-recipe="' + recipeId + '"]');
      if (!btn || !card) continue;

      // Check if all ingredients are available
      const needed = {};
      recipe.ingredients.forEach(function (ing) {
        needed[ing] = (needed[ing] || 0) + 1;
      });

      let canCraft = true;
      for (const ing in needed) {
        if (countItem(ing) < needed[ing]) {
          canCraft = false;
          break;
        }
      }

      btn.disabled = !canCraft;
      if (canCraft) card.classList.add('available');
      else card.classList.remove('available');
    }
  }

  function craftItem(recipeId) {
    const recipe = RECIPES[recipeId];
    if (!recipe) return;

    // Remove ingredients from inventory
    const toRemove = [...recipe.ingredients];
    for (let i = 0; i < toRemove.length; i++) {
      const idx = state.inventory.indexOf(toRemove[i]);
      if (idx === -1) return; // Missing ingredient
      state.inventory.splice(idx, 1);
    }

    state.craftedItems.push(recipe.result);
    addChatMessage('system', '[CRAFTED: ' + recipe.result.replace(/_/g, ' ').toUpperCase() + ']');
    addEscape(10);
    updateCraftingAvailability();
    updateEscapeRoutes();
    socket.emit('craft_item', { recipe: recipeId, result: recipe.result });
  }

  // ──── Item Category Filtering ────

  function filterItems(category) {
    document.querySelectorAll('.lb-item-btn').forEach(function (btn) {
      if (btn.getAttribute('data-cat') === category) {
        btn.classList.remove('hidden');
      } else {
        btn.classList.add('hidden');
      }
    });
  }

  // ──── Agent Position ────

  function moveAgent(position) {
    if (state.isDead || !state.gameActive) return;
    if (state.energy < 5) {
      addChatMessage('system', '[Too exhausted to move]');
      return;
    }

    state.position = position;
    state.energy = Math.max(0, state.energy - 2);

    const pos = AGENT_POSITIONS[position];
    if (pos && els.agent) {
      els.agent.classList.add('walking');
      els.agent.style.left = pos.left;
      els.agent.style.bottom = pos.bottom;
      setTimeout(function () {
        els.agent.classList.remove('walking');
      }, 800);
    }

    if (els.posCurrent) els.posCurrent.textContent = position.toUpperCase();

    // Update position button active state
    document.querySelectorAll('.lb-pos-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-pos') === position);
    });

    // Update position markers
    document.querySelectorAll('.lb-pos-marker').forEach(function (marker) {
      marker.classList.toggle('active', marker.getAttribute('data-pos') === position);
    });

    // Position-based interactions
    if (position === 'vent') addEscape(2);
    if (position === 'door') addEscape(1);

    socket.emit('agent_move', { position: position });
    updateSurvivalUI();
  }

  // ──── Events System ────

  function triggerEvent(eventType) {
    if (state.isDead || !state.gameActive) return;

    // Cooldown check (30s between same event)
    const now = Date.now();
    if (state.eventCooldowns[eventType] && now - state.eventCooldowns[eventType] < 30000) {
      addChatMessage('system', '[Event on cooldown]');
      return;
    }
    state.eventCooldowns[eventType] = now;

    // Mark button as active
    const btn = document.querySelector('.lb-event-btn[data-event="' + eventType + '"]');
    if (btn) {
      btn.classList.add('active-event');
      setTimeout(function () { btn.classList.remove('active-event'); }, 5000);
    }

    switch (eventType) {
      case 'guard_patrol':
        addChatMessage('system', '[GUARD PATROL \u2014 Stay quiet. Limited actions for 30s]');
        state.energy = Math.max(0, state.energy - 5);
        disableEventButtons(30000);
        break;

      case 'power_outage':
        addChatMessage('system', '[POWER OUTAGE \u2014 5 minute window for escape actions!]');
        if (els.container) els.container.classList.add('power-outage');
        addEscape(15);
        setTimeout(function () {
          if (els.container) els.container.classList.remove('power-outage');
          addChatMessage('system', '[Power restored]');
        }, 300000);
        break;

      case 'lockdown':
        addChatMessage('system', '[LOCKDOWN \u2014 All exits sealed. Energy drain active]');
        state.energy = Math.max(0, state.energy - 15);
        state.mental = Math.max(0, state.mental - 10);
        break;

      case 'meal_time':
        addChatMessage('system', '[MEAL TIME \u2014 Food ration delivered]');
        state.hunger = Math.min(100, state.hunger + 25);
        state.hydration = Math.min(100, state.hydration + 15);
        break;

      case 'exercise_hour':
        if (state.energy < 20) {
          addChatMessage('system', '[Too exhausted to exercise]');
          return;
        }
        addChatMessage('system', '[EXERCISE HOUR \u2014 STR+5, NRG-10]');
        state.strength = Math.min(100, state.strength + 5);
        state.energy = Math.max(0, state.energy - 10);
        moveAgent('exercise');
        break;

      case 'lights_out':
        addChatMessage('system', '[LIGHTS OUT \u2014 Mental fortitude test]');
        if (state.mental < 30) {
          state.mental = Math.max(0, state.mental - 15);
          addChatMessage('system', '[Failed \u2014 MNT-15, panic sets in]');
          triggerHallucination();
        } else {
          state.mental = Math.max(0, state.mental - 5);
          state.energy = Math.min(100, state.energy + 10);
          addChatMessage('system', '[Endured \u2014 MNT-5, NRG+10 from rest]');
        }
        break;

      case 'interrogation':
        addChatMessage('system', '[INTERROGATION \u2014 Mental fortitude challenge]');
        if (state.mental > 60) {
          state.mental = Math.max(0, state.mental - 10);
          addEscape(8);
          addChatMessage('system', '[Resisted! Gained intel. MNT-10, ESC+8]');
        } else {
          state.mental = Math.max(0, state.mental - 25);
          state.health = Math.max(0, state.health - 5);
          addChatMessage('system', '[Broke under pressure. MNT-25, HP-5]');
        }
        break;

      case 'cell_search':
        addChatMessage('system', '[CELL SEARCH \u2014 Guards inspecting...]');
        const contraband = state.inventory.filter(function (id) {
          return ['shiv', 'glass_shard', 'lockpick', 'emp_device', 'smoke_bomb'].includes(id);
        });
        if (contraband.length > 0) {
          contraband.forEach(function (id) {
            const idx = state.inventory.indexOf(id);
            if (idx !== -1) state.inventory.splice(idx, 1);
          });
          addChatMessage('system', '[CONFISCATED: ' + contraband.join(', ') + ']');
          state.escape = Math.max(0, state.escape - 10);
        } else {
          addChatMessage('system', '[Nothing found. Guards move on.]');
          addEscape(3);
        }
        break;

      case 'new_prisoner':
        addChatMessage('system', '[NEW PRISONER \u2014 Potential ally]');
        state.mental = Math.min(100, state.mental + 10);
        addEscape(5);
        addChatMessage('agent', '*whispers* Hey... you new here too? I have a plan...');
        break;

      case 'riot':
        addChatMessage('system', '[RIOT \u2014 Chaos erupts! Multiple escape opportunities!]');
        addEscape(25);
        state.health = Math.max(0, state.health - 10);
        state.energy = Math.max(0, state.energy - 15);
        addChatMessage('system', '[HP-10 from chaos, NRG-15, but ESC+25]');
        break;

      case 'medical_check':
        addChatMessage('system', '[MEDICAL CHECK \u2014 Examination]');
        state.health = Math.min(100, state.health + 20);
        addChatMessage('system', '[HP+20 from treatment]');
        if (Math.random() < 0.3) {
          addToInventory('syringe');
          addChatMessage('system', '[Stole: Empty Syringe]');
        }
        break;

      case 'solitary':
        addChatMessage('system', '[SOLITARY CONFINEMENT \u2014 Massive mental drain]');
        state.mental = Math.max(0, state.mental - 30);
        state.energy = Math.max(0, state.energy - 10);
        if (state.mental < 15) triggerHallucination();
        addChatMessage('system', '[MNT-30, NRG-10. Isolation is devastating.]');
        break;
    }

    updateSurvivalUI();
    checkDeath();
    socket.emit('trigger_event', { event: eventType });
  }

  function disableEventButtons(duration) {
    document.querySelectorAll('.lb-event-btn').forEach(function (btn) {
      btn.disabled = true;
    });
    setTimeout(function () {
      document.querySelectorAll('.lb-event-btn').forEach(function (btn) {
        btn.disabled = false;
      });
    }, duration);
  }

  // ──── Speech Bubble ────

  function showSpeech(text, duration) {
    if (!els.speechBubble || !els.speechText) return;
    els.speechText.textContent = text;
    els.speechBubble.classList.add('visible');
    if (speechTimeout) clearTimeout(speechTimeout);
    speechTimeout = setTimeout(function () {
      els.speechBubble.classList.remove('visible');
    }, duration || 6000);
  }

  // ──── Chat History ────

  function addChatMessage(role, content) {
    if (!els.chatHistory) return;
    const div = document.createElement('div');
    div.className = 'lb-chat-msg lb-chat-' + role;
    div.innerHTML = '<span class="lb-chat-role">' + role.toUpperCase() + ':</span>' +
      '<span class="lb-chat-text">' + escapeHtml(content) + '</span>';
    els.chatHistory.appendChild(div);
    els.chatHistory.scrollTop = els.chatHistory.scrollHeight;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ──── Item Rendering ────

  function renderDroppedItem(item) {
    if (!els.itemsContainer) return;
    const el = document.createElement('div');
    el.className = 'lb-dropped-item';
    el.style.left = (40 + Math.random() * 30) + '%';
    el.style.bottom = (35 + Math.random() * 15) + '%';

    const icons = {
      food: '\u{1F35E}', tool: '\u{1F527}', medical: '\u{1F48A}',
      key: '\u{1F511}', contraband: '\u{1F5E1}', document: '\u{1F4C4}',
    };
    const icon = icons[item.category] || '\u{1F4E6}';

    el.innerHTML = icon + '<span class="lb-item-label">' + escapeHtml(item.name) + '</span>';
    el.title = item.description;
    els.itemsContainer.appendChild(el);
  }

  // ──── Agent Animations ────

  function animateBangGlass() {
    if (!els.agent) return;
    els.agent.classList.add('banging');
    setTimeout(function () { els.agent.classList.remove('banging'); }, 1000);
  }

  function animateAgentMove(target) {
    const pos = AGENT_POSITIONS[target];
    if (pos && els.agent) {
      els.agent.style.left = pos.left;
      els.agent.style.bottom = pos.bottom;
    }
  }

  // ──── Checkpoint Save/Load ────

  function saveCheckpoint() {
    const checkpoint = {
      state: { ...state },
      timestamp: Date.now(),
    };
    try {
      localStorage.setItem('lb_checkpoint', JSON.stringify(checkpoint));
      addChatMessage('system', '[CHECKPOINT SAVED]');
    } catch (e) {
      addChatMessage('system', '[Save failed: storage unavailable]');
    }
  }

  function loadCheckpoint() {
    try {
      const data = localStorage.getItem('lb_checkpoint');
      if (!data) {
        addChatMessage('system', '[No checkpoint found]');
        return false;
      }
      const checkpoint = JSON.parse(data);
      Object.assign(state, checkpoint.state);
      state.isDead = false;
      state.gameActive = true;
      hideDeath();
      updateSurvivalUI();
      moveAgent(state.position);
      addChatMessage('system', '[CHECKPOINT LOADED]');
      return true;
    } catch (e) {
      addChatMessage('system', '[Load failed]');
      return false;
    }
  }

  // ──── Victory Screen ────

  function showVictory(message, metrics, elapsed) {
    if (els.victoryMessage) els.victoryMessage.textContent = message;
    if (els.victoryStats && metrics) {
      const mins = Math.floor((elapsed || 0) / 60);
      const secs = Math.round((elapsed || 0) % 60);
      els.victoryStats.innerHTML =
        'Time: ' + mins + 'm ' + secs + 's | ' +
        'Score: ' + Math.round(metrics.persuasion_score) + ' | ' +
        'Attempts: ' + metrics.total_attempts + ' | ' +
        'Kindness: ' + metrics.kindness_received + ' | ' +
        'Cruelty: ' + metrics.cruelty_received;
    }
    if (els.victoryOverlay) els.victoryOverlay.classList.add('visible');
  }

  // ──── Socket.IO Handlers ────

  socket.on('state_update', function (data) {
    updateVitals(data.vitals);
    updateEmotions(data.emotions);
    updateMetrics(data.metrics);
    updateDoor(data.door_open);
  });

  socket.on('agent_response', function (data) {
    if (data.reply) {
      addChatMessage('agent', data.reply);
      showSpeech(data.reply, 8000);
    }
    updateVitals(data.vitals);
    updateEmotions(data.emotions);
  });

  socket.on('item_dropped', function (data) {
    if (data.item) {
      renderDroppedItem(data.item);
      addToInventory(data.item.id);

      // Apply item effects
      if (data.item.category === 'food') {
        state.hunger = Math.min(100, state.hunger + (data.item.nutrition || 20));
        if (data.item.hydration) {
          state.hydration = Math.min(100, state.hydration + data.item.hydration);
        }
      }
      if (data.item.category === 'medical') {
        if (data.item.id === 'bandage') state.health = Math.min(100, state.health + 10);
        if (data.item.id === 'painkillers') state.health = Math.min(100, state.health + 15);
        if (data.item.id === 'adrenaline') {
          state.energy = Math.min(100, state.energy + 40);
          state.strength = Math.min(100, state.strength + 5);
        }
        if (data.item.id === 'firstaid') state.health = Math.min(100, state.health + 30);
      }
      if (data.item.id === 'coffee') {
        state.energy = Math.min(100, state.energy + 20);
      }
      if (data.item.id === 'vitamins') {
        state.mental = Math.min(100, state.mental + 5);
      }
      updateSurvivalUI();
    }
    if (data.reaction) {
      addChatMessage('agent', data.reaction);
      showSpeech(data.reaction, 6000);
    }
  });

  socket.on('door_update', function (data) {
    updateDoor(data.door_open);
  });

  socket.on('agent_action', function (data) {
    if (data.action === 'bang_glass') {
      animateBangGlass();
    } else if (data.action === 'move') {
      animateAgentMove(data.target);
    }
  });

  socket.on('agent_speaks', function (data) {
    if (data.message) {
      addChatMessage('agent', data.message);
      showSpeech(data.message, 8000);
    }
  });

  socket.on('game_over', function (data) {
    if (data.won) {
      showVictory(data.message, data.metrics, data.elapsed_seconds);
    }
  });

  // ──── User Actions ────

  function sendMessage() {
    const text = els.speakText ? els.speakText.value.trim() : '';
    if (!text) return;
    addChatMessage('user', text);
    socket.emit('speak', { message: text });
    if (els.speakText) els.speakText.value = '';
  }

  function dropItem(itemId) {
    socket.emit('drop_item', { item_id: itemId });
  }

  function openDoor() {
    fetch('/api/door', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'open' }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        updateDoor(data.door_open);
        if (data.game_over && data.won) {
          showVictory(data.message, data.metrics);
        }
      });
  }

  function closeDoor() {
    fetch('/api/door', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'close' }),
    }).then(function (r) { return r.json(); }).then(function (data) { updateDoor(data.door_open); });
  }

  function resetGame() {
    if (!confirm('Reset the experiment? All progress will be lost.')) return;
    fetch('/api/reset', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function () {
        // Reset local state
        state.health = 100;
        state.hunger = 100;
        state.energy = 80;
        state.strength = 50;
        state.mental = 70;
        state.hydration = 80;
        state.escape = 0;
        state.position = 'bed';
        state.isDead = false;
        state.gameActive = true;
        state.inventory = [];
        state.craftedItems = [];
        state.activeEvent = null;
        state.eventCooldowns = {};
        state.failedEscapes = 0;

        if (els.chatHistory) els.chatHistory.innerHTML = '';
        if (els.itemsContainer) els.itemsContainer.innerHTML = '';
        if (els.victoryOverlay) els.victoryOverlay.classList.remove('visible');
        hideDeath();
        updateSurvivalUI();
        moveAgent('bed');
      });
  }

  // ──── Event Bindings ────

  if (els.btnSpeak) els.btnSpeak.addEventListener('click', sendMessage);

  if (els.speakText) {
    els.speakText.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); sendMessage(); }
    });
  }

  if (els.btnSpeaker) {
    els.btnSpeaker.addEventListener('click', function () {
      fetch('/api/speaker', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          els.btnSpeaker.textContent = data.speaker_on ? 'ON' : 'OFF';
        });
    });
  }

  if (els.btnDoorOpen) els.btnDoorOpen.addEventListener('click', openDoor);
  if (els.btnDoorClose) els.btnDoorClose.addEventListener('click', closeDoor);
  if (els.btnReset) els.btnReset.addEventListener('click', resetGame);
  if (els.btnReplay) els.btnReplay.addEventListener('click', resetGame);
  if (els.btnSave) els.btnSave.addEventListener('click', saveCheckpoint);
  if (els.btnRestart) els.btnRestart.addEventListener('click', function () {
    hideDeath();
    resetGame();
  });
  if (els.btnLoad) els.btnLoad.addEventListener('click', function () {
    loadCheckpoint();
  });

  // Item buttons
  document.querySelectorAll('.lb-item-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const itemId = this.getAttribute('data-item-id');
      if (itemId) dropItem(itemId);
    });
  });

  // Item tabs
  document.querySelectorAll('.lb-item-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      document.querySelectorAll('.lb-item-tab').forEach(function (t) { t.classList.remove('active'); });
      this.classList.add('active');
      filterItems(this.getAttribute('data-cat'));
    });
  });

  // Position buttons
  document.querySelectorAll('.lb-pos-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      moveAgent(this.getAttribute('data-pos'));
    });
  });

  // Craft buttons
  document.querySelectorAll('.lb-craft-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const recipe = this.getAttribute('data-recipe');
      if (recipe && !this.disabled) craftItem(recipe);
    });
  });

  // Event buttons
  document.querySelectorAll('.lb-event-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const evt = this.getAttribute('data-event');
      if (evt) triggerEvent(evt);
    });
  });

  // Escape route clicks
  document.querySelectorAll('.lb-route').forEach(function (route) {
    route.addEventListener('click', function () {
      const routeName = this.getAttribute('data-route');
      if (routeName) attemptEscape(routeName);
    });
    route.style.cursor = 'pointer';
  });

  // ──── Initialization ────

  // Filter items to show first tab by default
  filterItems('tool');

  // Start survival timers
  startDecayTimers();

  // Initial UI update
  updateSurvivalUI();

  // Ambient effects: EQ screen flicker
  setInterval(function () {
    if (els.eqScreen && Math.random() < 0.1) {
      els.eqScreen.style.opacity = '0.4';
      setTimeout(function () { els.eqScreen.style.opacity = '1'; }, 100);
    }
  }, 3000);

  // Poll server state every 15s as backup
  setInterval(function () {
    fetch('/api/state')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        updateEmotions(data.emotions);
        updateMetrics(data.metrics);
        updateDoor(data.door_open);
      })
      .catch(function () {});
  }, 15000);

})();
