/**
 * penthouse_anim.js — Animation State Machine & Expression Blending
 *
 * Provides:
 * - AnimState: Per-character animation state with smooth transitions
 * - State machine: idle → walk → sit → interact → pose (with blending)
 * - Expression blending: smooth morph between facial states
 * - Eyelid animation: natural blink cycles with random timing
 * - Breathing variation: adapts to mood/activity
 * - Look-at system: characters glance at nearby characters/director
 *
 * Load order: character_models.js → penthouse_anim.js → character_bridge.js
 */

(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════
  //  ANIMATION STATES
  // ═══════════════════════════════════════════════════════════════════

  const ANIM_STATES = {
    idle:       { id: 'idle',       priority: 0 },
    walk:       { id: 'walk',       priority: 1 },
    sit:        { id: 'sit',        priority: 2 },
    lean:       { id: 'lean',       priority: 2 },
    lie:        { id: 'lie',        priority: 2 },
    lounge:     { id: 'lounge',     priority: 2 },
    interact:   { id: 'interact',   priority: 3 },
    drink:      { id: 'drink',      priority: 3 },
    gaze:       { id: 'gaze',       priority: 2 },
    warm:       { id: 'warm',       priority: 2 },
    primp:      { id: 'primp',      priority: 3 },
    bathe:      { id: 'bathe',      priority: 3 },
    pose:       { id: 'pose',       priority: 4 },
  };

  // Blend durations (seconds) between state transitions
  const BLEND_DURATIONS = {
    'idle→walk':     0.4,
    'walk→idle':     0.5,
    'idle→sit':      0.8,
    'sit→idle':      0.7,
    'idle→lean':     0.6,
    'lean→idle':     0.5,
    'idle→lie':      1.2,
    'lie→idle':      1.0,
    'idle→lounge':   1.0,
    'lounge→idle':   0.8,
    'idle→interact': 0.3,
    'interact→idle': 0.4,
    'idle→drink':    0.4,
    'drink→idle':    0.3,
    'idle→gaze':     0.6,
    'gaze→idle':     0.5,
    'idle→warm':     0.7,
    'warm→idle':     0.5,
    'idle→primp':    0.5,
    'primp→idle':    0.4,
    'idle→bathe':    1.0,
    'bathe→idle':    0.8,
    'idle→pose':     0.5,
    'pose→idle':     0.6,
    'sit→lie':       1.0,
    'lie→sit':       0.9,
    'sit→lounge':    0.6,
    'lounge→sit':    0.5,
    'lean→drink':    0.3,
    'drink→lean':    0.3,
    '*':             0.5,
  };

  // ═══════════════════════════════════════════════════════════════════
  //  EXPRESSION TARGETS (face part values per mood)
  // ═══════════════════════════════════════════════════════════════════

  const EXPRESSION_PRESETS = {
    neutral:   { browY: 0.042, browRot: 0.10, mouthSX: 1.0, mouthSY: 1.0, mouthRX: 0.314, pupilS: 1.0, headTilt: 0, blush: 0 },
    happy:     { browY: 0.046, browRot: 0.10, mouthSX: 1.3, mouthSY: 1.2, mouthRX: 0.314, pupilS: 1.1, headTilt: 0, blush: 0.1 },
    aroused:   { browY: 0.038, browRot: 0.05, mouthSX: 1.1, mouthSY: 1.4, mouthRX: 0.314, pupilS: 1.4, headTilt: 0, blush: 0.5 },
    sad:       { browY: 0.044, browRot: 0.25, mouthSX: 0.9, mouthSY: 0.8, mouthRX: 0.628, pupilS: 1.0, headTilt: 0.05, blush: 0 },
    angry:     { browY: 0.038, browRot: -0.2, mouthSX: 1.2, mouthSY: 0.6, mouthRX: 0.314, pupilS: 0.8, headTilt: -0.03, blush: 0.15 },
    fear:      { browY: 0.050, browRot: 0.10, mouthSX: 1.4, mouthSY: 1.8, mouthRX: 0.314, pupilS: 0.7, headTilt: 0, blush: 0 },
    seductive: { browY: 0.043, browRot: 0.15, mouthSX: 1.15, mouthSY: 1.0, mouthRX: 0.314, pupilS: 1.2, headTilt: 0.04, blush: 0.3 },
    orgasm:    { browY: 0.046, browRot: 0.18, mouthSX: 1.5, mouthSY: 2.0, mouthRX: 0.314, pupilS: 1.6, headTilt: -0.06, blush: 0.8 },
    shy:       { browY: 0.046, browRot: 0.20, mouthSX: 0.9, mouthSY: 0.9, mouthRX: 0.314, pupilS: 1.0, headTilt: 0.10, blush: 0.4 },
    smirk:     { browY: 0.044, browRot: 0.05, mouthSX: 1.1, mouthSY: 0.9, mouthRX: 0.314, pupilS: 1.05, headTilt: 0.02, blush: 0.1 },
    contempt:  { browY: 0.040, browRot: -0.1, mouthSX: 0.85, mouthSY: 0.7, mouthRX: 0.471, pupilS: 0.95, headTilt: 0.03, blush: 0 },
    relaxed:   { browY: 0.044, browRot: 0.10, mouthSX: 1.1, mouthSY: 1.05, mouthRX: 0.314, pupilS: 1.0, headTilt: 0, blush: 0 },
    surprised: { browY: 0.050, browRot: 0.10, mouthSX: 1.4, mouthSY: 1.6, mouthRX: 0.314, pupilS: 0.8, headTilt: -0.04, blush: 0.1 },
    drunk:     { browY: 0.042, browRot: 0.05, mouthSX: 1.15, mouthSY: 1.1, mouthRX: 0.314, pupilS: 1.1, headTilt: 0.06, blush: 0.3 },
    sleepy:    { browY: 0.040, browRot: 0.08, mouthSX: 1.0, mouthSY: 0.95, mouthRX: 0.314, pupilS: 0.9, headTilt: 0.08, blush: 0 },
    dominant:  { browY: 0.040, browRot: -0.15, mouthSX: 1.05, mouthSY: 0.95, mouthRX: 0.314, pupilS: 1.1, headTilt: -0.03, blush: 0 },
  };

  // Map mood keywords to preset names
  const MOOD_ALIASES = {
    joy: 'happy', pleasure: 'happy', delight: 'happy',
    horny: 'aroused', lust: 'aroused',
    upset: 'sad', melancholy: 'sad',
    rage: 'angry', furious: 'angry',
    scared: 'fear', shock: 'surprised', surprise: 'surprised',
    seduce: 'seductive', flirt: 'seductive', tease: 'seductive', coy: 'seductive',
    moan: 'orgasm', ecstasy: 'orgasm', climax: 'orgasm',
    embarrass: 'shy', blush: 'shy',
    mischief: 'smirk', sly: 'smirk',
    disgust: 'contempt', bored: 'contempt',
    relax: 'relaxed', content: 'relaxed', peace: 'relaxed', calm: 'relaxed',
  };

  // ═══════════════════════════════════════════════════════════════════
  //  ANIM STATE CLASS (one per character model)
  // ═══════════════════════════════════════════════════════════════════

  class AnimState {
    constructor(model) {
      this.model = model;

      // State machine
      this.currentState = 'idle';
      this.previousState = 'idle';
      this.stateTime = 0;
      this.blendProgress = 1.0;  // 1.0 = fully in currentState
      this.blendDuration = 0;

      // Expression blending
      this.currentExpression = { ...EXPRESSION_PRESETS.neutral };
      this.targetExpression = { ...EXPRESSION_PRESETS.neutral };
      this.expressionBlend = 1.0;
      this.expressionBlendSpeed = 2.0;  // 0.5 seconds default
      this.currentMood = 'neutral';

      // Blink system
      this.blinkTimer = 2.0 + Math.random() * 3.0;  // random first blink
      this.blinkPhase = 0;  // 0=open, 1=closing, 2=closed, 3=opening
      this.blinkSpeed = 12.0;  // blinks per second (speed of close/open)
      this.blinkProgress = 0;
      this.eyelidClose = 0;  // 0=fully open, 1=fully closed

      // Breathing
      this.breathRate = 1.1;
      this.breathDepth = 0.015;
      this.targetBreathRate = 1.1;
      this.targetBreathDepth = 0.015;

      // Look-at
      this.lookTarget = null;  // {x, y, z} or null for idle look
      this.lookWeight = 0;
      this.lookBlendSpeed = 2.0;

      // Activity modifiers
      this.activityLevel = 0;  // 0=calm, 1=active (affects breathing, sway)

      // Sitting state
      this.seatHeight = 0;
      this.seatLegAngle = 0;

      // Walk
      this.walkPhase = 0;
      this.walkSpeed = 0;
    }

    /**
     * Transition to a new animation state.
     */
    setState(newState) {
      if (newState === this.currentState) return;
      if (!ANIM_STATES[newState]) return;

      this.previousState = this.currentState;
      this.currentState = newState;
      this.stateTime = 0;

      const key = `${this.previousState}→${newState}`;
      this.blendDuration = BLEND_DURATIONS[key] || BLEND_DURATIONS['*'];
      this.blendProgress = 0;
    }

    /**
     * Set expression with smooth blending.
     */
    setMood(mood) {
      const m = (mood || 'neutral').toLowerCase();
      let presetName = 'neutral';

      // Direct match first
      if (EXPRESSION_PRESETS[m]) {
        presetName = m;
      } else {
        // Try aliases — find first keyword match
        for (const [keyword, target] of Object.entries(MOOD_ALIASES)) {
          if (m.includes(keyword)) {
            presetName = target;
            break;
          }
        }
      }

      if (presetName === this.currentMood) return;

      this.currentMood = presetName;
      this.currentExpression = { ...this.targetExpression };
      this.targetExpression = { ...EXPRESSION_PRESETS[presetName] };
      this.expressionBlend = 0;

      // Adjust breathing based on mood
      this._updateBreathingForMood(presetName);
    }

    /**
     * Set a specific point to look at (or null for idle).
     */
    setLookTarget(target) {
      this.lookTarget = target;
    }

    /**
     * Main update — call every frame with deltaTime.
     */
    update(dt, globalTime) {
      // Blend between states
      if (this.blendProgress < 1.0) {
        this.blendProgress = Math.min(1.0, this.blendProgress + dt / this.blendDuration);
      }
      this.stateTime += dt;

      // Expression blending
      if (this.expressionBlend < 1.0) {
        this.expressionBlend = Math.min(1.0, this.expressionBlend + dt * this.expressionBlendSpeed);
      }

      // Smooth breathing transitions
      this.breathRate += (this.targetBreathRate - this.breathRate) * dt * 2.0;
      this.breathDepth += (this.targetBreathDepth - this.breathDepth) * dt * 2.0;

      // Look-at weight
      if (this.lookTarget) {
        this.lookWeight = Math.min(1.0, this.lookWeight + dt * this.lookBlendSpeed);
      } else {
        this.lookWeight = Math.max(0, this.lookWeight - dt * this.lookBlendSpeed);
      }

      // Update subsystems
      this._updateBlink(dt);
      this._applyAnimState(globalTime, dt);
      this._applyExpression();
      this._applyBlink();
      this._applyLookAt(globalTime);
    }

    // ── Private methods ─────────────────────────────────────────────

    _updateBreathingForMood(mood) {
      switch (mood) {
        case 'aroused':
        case 'orgasm':
          this.targetBreathRate = 2.0;
          this.targetBreathDepth = 0.025;
          break;
        case 'fear':
        case 'surprised':
          this.targetBreathRate = 1.8;
          this.targetBreathDepth = 0.022;
          break;
        case 'angry':
          this.targetBreathRate = 1.6;
          this.targetBreathDepth = 0.020;
          break;
        case 'relaxed':
        case 'sleepy':
          this.targetBreathRate = 0.8;
          this.targetBreathDepth = 0.012;
          break;
        case 'drunk':
          this.targetBreathRate = 0.9;
          this.targetBreathDepth = 0.018;
          break;
        default:
          this.targetBreathRate = 1.1;
          this.targetBreathDepth = 0.015;
      }
    }

    _updateBlink(dt) {
      this.blinkTimer -= dt;

      if (this.blinkPhase === 0) {
        // Waiting for blink
        if (this.blinkTimer <= 0) {
          this.blinkPhase = 1;
          this.blinkProgress = 0;
        }
      } else if (this.blinkPhase === 1) {
        // Closing
        this.blinkProgress += dt * this.blinkSpeed;
        this.eyelidClose = Math.min(1.0, this.blinkProgress);
        if (this.blinkProgress >= 1.0) {
          this.blinkPhase = 2;
          this.blinkProgress = 0;
        }
      } else if (this.blinkPhase === 2) {
        // Closed (brief hold)
        this.blinkProgress += dt * this.blinkSpeed * 2;
        if (this.blinkProgress >= 0.3) {
          this.blinkPhase = 3;
          this.blinkProgress = 0;
        }
      } else if (this.blinkPhase === 3) {
        // Opening
        this.blinkProgress += dt * this.blinkSpeed * 0.8;
        this.eyelidClose = Math.max(0, 1.0 - this.blinkProgress);
        if (this.blinkProgress >= 1.0) {
          this.blinkPhase = 0;
          this.eyelidClose = 0;
          // Randomize next blink: 2-6 seconds, with occasional double-blinks
          const doubleBlink = Math.random() < 0.15;
          this.blinkTimer = doubleBlink ? 0.15 : (2.0 + Math.random() * 4.0);
        }
      }
    }

    _applyAnimState(time, dt) {
      const model = this.model;
      if (!model || !model.bodyGroup) return;

      const d = model.dims;
      const t = this.blendProgress;  // 0→1 blend into current state

      // ── IDLE state ────────────────────────────────────────────
      if (this.currentState === 'idle' || this.blendProgress < 1.0) {
        const idleWeight = this.currentState === 'idle' ? 1.0 : (1.0 - t);

        // Breathing
        const breath = 1.0 + this.breathDepth * Math.sin(time * this.breathRate * Math.PI * 2);
        const torso = model.bodyGroup.children[0];
        if (torso) {
          torso.scale.x = 1.0 + (breath - 1.0) * idleWeight;
          torso.scale.z = d.torsoScaleZ * (1.0 + (breath - 1.0) * idleWeight);
        }

        // Body sway
        const swayAmp = 0.01 * (1.0 + this.activityLevel * 0.5);
        model.bodyGroup.rotation.y = swayAmp * Math.sin(time * 0.6) * idleWeight;

        // Weight shift
        model.bodyGroup.position.x = 0.015 * Math.sin(time * 0.35) * idleWeight;

        // Arm swing
        if (model.armL) {
          const baseArmRX = 0.03 * Math.sin(time * 0.8 + 1.0) * idleWeight;
          const baseArmRZ = (-0.02 + 0.01 * Math.sin(time * 0.5)) * idleWeight;
          model.armL.rotation.x = baseArmRX;
          model.armL.rotation.z = baseArmRZ;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.03 * Math.sin(time * 0.8 + 2.5) * idleWeight;
          model.armR.rotation.z = (0.02 - 0.01 * Math.sin(time * 0.5 + 1.0)) * idleWeight;
        }

        // Leg flex
        if (model.legL) model.legL.rotation.x = 0.005 * Math.sin(time * 0.4) * idleWeight;
        if (model.legR) model.legR.rotation.x = 0.005 * Math.sin(time * 0.4 + Math.PI) * idleWeight;
      }

      // ── WALK state ────────────────────────────────────────────
      if (this.currentState === 'walk') {
        this.walkPhase += dt * 3.0;
        const w = t;  // blend weight into walk

        if (model.armL) {
          model.armL.rotation.x = 0.3 * Math.sin(this.walkPhase) * w;
          model.armL.rotation.z = -0.05 * w;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.3 * Math.sin(this.walkPhase) * w;
          model.armR.rotation.z = 0.05 * w;
        }
        if (model.legL) model.legL.rotation.x = 0.35 * Math.sin(this.walkPhase) * w;
        if (model.legR) model.legR.rotation.x = -0.35 * Math.sin(this.walkPhase) * w;

        // Slight body bob
        model.bodyGroup.position.y = 0.02 * Math.abs(Math.sin(this.walkPhase * 2)) * w;
        // Hip sway
        model.bodyGroup.rotation.z = 0.03 * Math.sin(this.walkPhase) * w;
      }

      // ── SIT state ─────────────────────────────────────────────
      if (this.currentState === 'sit') {
        const s = t;

        // Lower body position
        model.group.position.y = -0.35 * s + (model._baseY || 0);

        // Legs bent at ~90°
        if (model.legL) {
          model.legL.rotation.x = -1.4 * s;
          model.legL.rotation.z = -0.05 * s;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.4 * s;
          model.legR.rotation.z = 0.05 * s;
        }

        // Arms resting on legs
        if (model.armL) {
          model.armL.rotation.x = 0.3 * s;
          model.armL.rotation.z = -0.15 * s;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.3 * s;
          model.armR.rotation.z = 0.15 * s;
        }

        // Subtle idle breathing still applies
        const breath = 1.0 + this.breathDepth * 0.7 * Math.sin(time * this.breathRate * Math.PI * 2);
        const torso = model.bodyGroup.children[0];
        if (torso) {
          torso.scale.x = breath;
          torso.scale.z = model.dims.torsoScaleZ * breath;
        }
      }

      // ── LEAN state ────────────────────────────────────────────
      if (this.currentState === 'lean') {
        const l = t;

        model.bodyGroup.rotation.x = -0.15 * l;  // leaning back slightly
        model.bodyGroup.position.z = -0.1 * l;

        if (model.armL) {
          model.armL.rotation.x = 0.4 * l;
          model.armL.rotation.z = -0.3 * l;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.1 * l;
          model.armR.rotation.z = 0.1 * l;
        }
      }

      // ── INTERACT state ────────────────────────────────────────
      if (this.currentState === 'interact') {
        const i = t;
        // Gesture — one arm extended
        if (model.armR) {
          model.armR.rotation.x = -0.5 * i;
          model.armR.rotation.z = 0.3 * i;
        }
        // Slight forward lean
        model.bodyGroup.rotation.x = 0.05 * i;
      }

      // ── LIE state (bed — reclining on back) ───────────────────
      if (this.currentState === 'lie') {
        const l = t;

        // Lower and rotate body to horizontal
        model.group.position.y = -0.6 * l + (model._baseY || 0);
        model.bodyGroup.rotation.x = -1.4 * l;  // lean far back

        // Legs extended, slightly apart
        if (model.legL) {
          model.legL.rotation.x = -0.2 * l;
          model.legL.rotation.z = -0.08 * l;
        }
        if (model.legR) {
          model.legR.rotation.x = -0.15 * l;
          model.legR.rotation.z = 0.06 * l;
        }

        // One arm behind head, other resting
        if (model.armL) {
          model.armL.rotation.x = -1.2 * l;
          model.armL.rotation.z = -0.6 * l;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.2 * l;
          model.armR.rotation.z = 0.15 * l;
        }

        // Gentle breathing in lying position
        const breath = 1.0 + this.breathDepth * 0.5 * Math.sin(time * this.breathRate * Math.PI * 2);
        const torso = model.bodyGroup.children[0];
        if (torso) {
          torso.scale.x = breath;
          torso.scale.z = (d ? d.torsoScaleZ : 1) * breath;
        }
      }

      // ── LOUNGE state (couch — sprawled relaxation) ─────────────
      if (this.currentState === 'lounge') {
        const l = t;

        // Lowered, leaning back
        model.group.position.y = -0.3 * l + (model._baseY || 0);
        model.bodyGroup.rotation.x = -0.4 * l;

        // Legs stretched out, one crossed
        if (model.legL) {
          model.legL.rotation.x = -0.8 * l;
          model.legL.rotation.z = -0.05 * l;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.0 * l;
          model.legR.rotation.z = 0.15 * l;
        }

        // Arms spread along couch back
        if (model.armL) {
          model.armL.rotation.x = -0.1 * l;
          model.armL.rotation.z = -0.7 * l;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.15 * l;
          model.armR.rotation.z = 0.5 * l;
        }

        // Slow relaxed breathing
        const breath = 1.0 + this.breathDepth * 0.6 * Math.sin(time * this.breathRate * Math.PI * 2);
        const torso = model.bodyGroup.children[0];
        if (torso) {
          torso.scale.x = breath;
          torso.scale.z = (d ? d.torsoScaleZ : 1) * breath;
        }
      }

      // ── DRINK state (holding glass at bar) ─────────────────────
      if (this.currentState === 'drink') {
        const dk = t;

        // Slight lean on bar
        model.bodyGroup.rotation.x = -0.08 * dk;

        // One arm holding glass, other resting on bar
        if (model.armR) {
          const sip = Math.sin(time * 0.4);
          model.armR.rotation.x = (-0.8 - 0.15 * Math.max(0, sip)) * dk;
          model.armR.rotation.z = 0.2 * dk;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.3 * dk;
          model.armL.rotation.z = -0.25 * dk;
        }

        // Casual weight shift
        model.bodyGroup.position.x = 0.02 * Math.sin(time * 0.3) * dk;
      }

      // ── GAZE state (balcony — leaning on railing, looking out) ─
      if (this.currentState === 'gaze') {
        const g = t;

        // Forward lean onto railing
        model.bodyGroup.rotation.x = 0.2 * g;
        model.bodyGroup.position.z = 0.1 * g;

        // Both arms resting on railing
        if (model.armL) {
          model.armL.rotation.x = 0.5 * g;
          model.armL.rotation.z = -0.1 * g;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.5 * g;
          model.armR.rotation.z = 0.1 * g;
        }

        // Head tilted up slightly (stargazing)
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = -0.1 * g;
        }

        // Gentle wind sway
        model.bodyGroup.rotation.y = 0.015 * Math.sin(time * 0.5) * g;
      }

      // ── WARM state (fireplace — sitting with hands toward fire) ─
      if (this.currentState === 'warm') {
        const w = t;

        // Seated position
        model.group.position.y = -0.3 * w + (model._baseY || 0);

        // Legs bent, tucked
        if (model.legL) {
          model.legL.rotation.x = -1.2 * w;
          model.legL.rotation.z = -0.1 * w;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.3 * w;
          model.legR.rotation.z = 0.08 * w;
        }

        // Hands extended toward fire
        if (model.armL) {
          model.armL.rotation.x = -0.6 * w;
          model.armL.rotation.z = -0.15 * w;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.6 * w;
          model.armR.rotation.z = 0.15 * w;
        }

        // Flickering warm glow sway
        model.bodyGroup.rotation.y = 0.01 * Math.sin(time * 0.8 + Math.random() * 0.1) * w;
      }

      // ── PRIMP state (vanity — sitting at mirror, grooming) ─────
      if (this.currentState === 'primp') {
        const p = t;

        // Seated
        model.group.position.y = -0.35 * p + (model._baseY || 0);

        // Legs together, under desk
        if (model.legL) {
          model.legL.rotation.x = -1.4 * p;
          model.legL.rotation.z = -0.02 * p;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.4 * p;
          model.legR.rotation.z = 0.02 * p;
        }

        // One hand touching face, other holding item
        if (model.armR) {
          const gesture = Math.sin(time * 0.6);
          model.armR.rotation.x = (-0.7 - 0.1 * gesture) * p;
          model.armR.rotation.z = 0.2 * p;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.4 * p;
          model.armL.rotation.z = -0.3 * p;
        }

        // Slight head tilt studying reflection
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.y = 0.05 * Math.sin(time * 0.4) * p;
        }
      }

      // ── BATHE state (bath — seated in tub, relaxed) ────────────
      if (this.currentState === 'bathe') {
        const b = t;

        // Lowered into tub
        model.group.position.y = -0.5 * b + (model._baseY || 0);

        // Body slightly reclined
        model.bodyGroup.rotation.x = -0.25 * b;

        // Legs submerged, slightly bent
        if (model.legL) {
          model.legL.rotation.x = -0.6 * b;
          model.legL.rotation.z = -0.1 * b;
        }
        if (model.legR) {
          model.legR.rotation.x = -0.5 * b;
          model.legR.rotation.z = 0.1 * b;
        }

        // Arms resting on tub edge
        if (model.armL) {
          model.armL.rotation.x = -0.1 * b;
          model.armL.rotation.z = -0.6 * b;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.1 * b;
          model.armR.rotation.z = 0.6 * b;
        }

        // Gentle water sway
        model.bodyGroup.position.x = 0.008 * Math.sin(time * 0.7) * b;
        model.bodyGroup.position.z = 0.005 * Math.sin(time * 0.5 + 1.0) * b;
      }
    }

    _applyExpression() {
      const model = this.model;
      if (!model || !model.headData || !model.headData.group) return;

      const hd = model.headData;
      const b = this.expressionBlend;
      const curr = this.currentExpression;
      const tgt = this.targetExpression;

      // Lerp all expression values
      const browY    = curr.browY    + (tgt.browY    - curr.browY)    * b;
      const browRot  = curr.browRot  + (tgt.browRot  - curr.browRot)  * b;
      const mouthSX  = curr.mouthSX  + (tgt.mouthSX  - curr.mouthSX)  * b;
      const mouthSY  = curr.mouthSY  + (tgt.mouthSY  - curr.mouthSY)  * b;
      const mouthRX  = curr.mouthRX  + (tgt.mouthRX  - curr.mouthRX)  * b;
      const pupilS   = curr.pupilS   + (tgt.pupilS   - curr.pupilS)   * b;
      const headTilt = curr.headTilt + (tgt.headTilt - curr.headTilt) * b;

      // Apply to face parts
      const mouth  = hd.group.getObjectByName('mouth');
      const browL  = hd.group.getObjectByName('browL');
      const browR  = hd.group.getObjectByName('browR');
      const pupilL = hd.group.getObjectByName('pupilL');
      const pupilR = hd.group.getObjectByName('pupilR');

      if (browL) { browL.position.y = browY; browL.rotation.z = browRot; }
      if (browR) { browR.position.y = browY; browR.rotation.z = -browRot; }
      if (mouth) { mouth.scale.set(mouthSX, mouthSY, 1); mouth.rotation.x = mouthRX; }
      if (pupilL) pupilL.scale.set(pupilS, pupilS, pupilS);
      if (pupilR) pupilR.scale.set(pupilS, pupilS, pupilS);

      // Head tilt from expression (additive to look-at)
      if (hd.group) {
        hd.group.userData.expressionTilt = headTilt;
      }
    }

    _applyBlink() {
      const model = this.model;
      if (!model || !model.headData || !model.headData.group) return;

      const hd = model.headData;
      const eyelidL = hd.group.getObjectByName('eyelidL');
      const eyelidR = hd.group.getObjectByName('eyelidR');

      if (eyelidL) {
        eyelidL.scale.y = 1.0 + this.eyelidClose * 1.5;
        eyelidL.position.y = 0.018 - this.eyelidClose * 0.012;
      }
      if (eyelidR) {
        eyelidR.scale.y = 1.0 + this.eyelidClose * 1.5;
        eyelidR.position.y = 0.018 - this.eyelidClose * 0.012;
      }

      // Also squeeze pupils during blink
      const pupilL = hd.group.getObjectByName('pupilL');
      const pupilR = hd.group.getObjectByName('pupilR');
      if (pupilL && this.eyelidClose > 0.5) {
        const squeeze = 1.0 - (this.eyelidClose - 0.5) * 1.6;
        pupilL.scale.y *= Math.max(0.1, squeeze);
      }
      if (pupilR && this.eyelidClose > 0.5) {
        const squeeze = 1.0 - (this.eyelidClose - 0.5) * 1.6;
        pupilR.scale.y *= Math.max(0.1, squeeze);
      }
    }

    _applyLookAt(time) {
      const model = this.model;
      if (!model || !model.headData || !model.headData.group) return;
      const hd = model.headData;

      // Base idle look (micro-movement)
      const idleLookY = 0.04 * Math.sin(time * 0.25);
      const idleLookX = 0.015 * Math.sin(time * 0.3 + 0.5);

      // Expression tilt
      const expressionTilt = hd.group.userData.expressionTilt || 0;

      if (this.lookTarget && this.lookWeight > 0) {
        // Calculate direction to target
        const worldPos = new THREE.Vector3();
        model.group.getWorldPosition(worldPos);
        const dx = this.lookTarget.x - worldPos.x;
        const dz = this.lookTarget.z - worldPos.z;
        const targetYaw = Math.atan2(dx, dz);

        // Clamp look range to ±45°
        const clampedYaw = Math.max(-0.785, Math.min(0.785, targetYaw - model.group.rotation.y));
        const w = this.lookWeight;

        hd.group.rotation.y = idleLookY * (1 - w) + clampedYaw * 0.4 * w;
        hd.group.rotation.x = idleLookX * (1 - w) + expressionTilt;
      } else {
        hd.group.rotation.y = idleLookY;
        hd.group.rotation.x = idleLookX + expressionTilt;
      }
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  //  ANIMATION MANAGER (manages all character AnimStates)
  // ═══════════════════════════════════════════════════════════════════

  const AnimManager = {
    _states: new Map(),  // charName → AnimState
    _lastTime: 0,
    _clock: null,

    /**
     * Register a character model for animation.
     */
    register(name, model) {
      const state = new AnimState(model);
      this._states.set(name.toLowerCase(), state);
      model._animState = state;
      model._baseY = model.group ? model.group.position.y : 0;
      return state;
    },

    /**
     * Remove a character from animation.
     */
    unregister(name) {
      this._states.delete(name.toLowerCase());
    },

    /**
     * Get AnimState for a character.
     */
    getState(name) {
      return this._states.get(name.toLowerCase()) || null;
    },

    /**
     * Set animation state for a character.
     */
    setState(name, state) {
      const s = this.getState(name);
      if (s) s.setState(state);
    },

    /**
     * Set expression/mood for a character with smooth blending.
     */
    setMood(name, mood) {
      const s = this.getState(name);
      if (s) s.setMood(mood);
    },

    /**
     * Set look-at target for a character.
     */
    setLookTarget(name, target) {
      const s = this.getState(name);
      if (s) s.setLookTarget(target);
    },

    /**
     * Update all characters — call once per frame.
     */
    updateAll(time) {
      const dt = this._lastTime > 0 ? Math.min(time - this._lastTime, 0.1) : 0.016;
      this._lastTime = time;

      for (const [, state] of this._states) {
        state.update(dt, time);
      }
    },

    /**
     * Get animation state summary for all characters.
     */
    getDebugInfo() {
      const info = {};
      for (const [name, state] of this._states) {
        info[name] = {
          state: state.currentState,
          mood: state.currentMood,
          blendProgress: state.blendProgress.toFixed(2),
          breathRate: state.breathRate.toFixed(1),
          lookWeight: state.lookWeight.toFixed(2),
        };
      }
      return info;
    },

    /**
     * Clear all states.
     */
    clear() {
      this._states.clear();
      this._lastTime = 0;
    },
  };

  // ═══════════════════════════════════════════════════════════════════
  //  LOCATION-BASED STATE INFERENCE
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Infer animation state from location + context.
   * Called by CharacterBridge when character positions update.
   */
  function inferAnimState(locationId, activity) {
    const act = (activity || '').toLowerCase();

    // Explicit activity overrides
    if (act.includes('walk') || act.includes('moving')) return 'walk';
    if (act.includes('drink') || act.includes('sip')) return 'drink';
    if (act.includes('bathe') || act.includes('shower') || act.includes('wash')) return 'bathe';
    if (act.includes('primp') || act.includes('groom') || act.includes('makeup')) return 'primp';
    if (act.includes('interact') || act.includes('using')) return 'interact';
    if (act.includes('pose') || act.includes('sex')) return 'pose';
    if (act.includes('lie') || act.includes('sleep') || act.includes('rest')) return 'lie';
    if (act.includes('lounge') || act.includes('relax') || act.includes('sprawl')) return 'lounge';
    if (act.includes('gaze') || act.includes('look') || act.includes('stare')) return 'gaze';
    if (act.includes('warm') || act.includes('fire')) return 'warm';

    // Location-based defaults with furniture-specific animations
    switch (locationId) {
      case 'bed':       return 'lie';
      case 'couch':     return 'lounge';
      case 'bar':       return 'drink';
      case 'vanity':    return 'primp';
      case 'bath':      return 'bathe';
      case 'balcony':   return 'gaze';
      case 'fireplace': return 'warm';
      case 'doorway':   return 'idle';
      default:          return 'idle';
    }
  }

  // Expose
  window.PenthouseAnim = {
    AnimState,
    AnimManager,
    ANIM_STATES,
    EXPRESSION_PRESETS,
    inferAnimState,
  };

})();
