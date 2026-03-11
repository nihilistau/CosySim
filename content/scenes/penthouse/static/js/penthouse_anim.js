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
    // ── Basic Movement ──
    idle:           { id: 'idle',           priority: 0 },
    walk:           { id: 'walk',           priority: 1 },
    run:            { id: 'run',            priority: 1 },

    // ── Seated Variations ──
    sit:            { id: 'sit',            priority: 2 },
    sit_cross:      { id: 'sit_cross',      priority: 2 },
    sit_lean:       { id: 'sit_lean',       priority: 2 },
    sit_floor:      { id: 'sit_floor',      priority: 2 },

    // ── Standing Variations ──
    lean:           { id: 'lean',           priority: 2 },
    arms_crossed:   { id: 'arms_crossed',   priority: 2 },
    hands_behind:   { id: 'hands_behind',   priority: 2 },

    // ── Lying Variations ──
    lie:            { id: 'lie',            priority: 2 },
    lie_side:       { id: 'lie_side',       priority: 2 },
    lie_front:      { id: 'lie_front',      priority: 2 },
    lounge:         { id: 'lounge',         priority: 2 },

    // ── Ground Positions ──
    kneel:          { id: 'kneel',          priority: 2 },
    kneel_sit:      { id: 'kneel_sit',      priority: 2 },
    all_fours:      { id: 'all_fours',      priority: 2 },
    crawl:          { id: 'crawl',          priority: 2 },
    sprawl:         { id: 'sprawl',         priority: 2 },

    // ── Furniture Interactions ──
    interact:       { id: 'interact',       priority: 3 },
    drink:          { id: 'drink',          priority: 3 },
    gaze:           { id: 'gaze',           priority: 2 },
    warm:           { id: 'warm',           priority: 2 },
    primp:          { id: 'primp',          priority: 3 },
    bathe:          { id: 'bathe',          priority: 3 },

    // ── Action/Gesture ──
    dance_slow:     { id: 'dance_slow',     priority: 3 },
    dance_sway:     { id: 'dance_sway',     priority: 3 },
    stretch:        { id: 'stretch',        priority: 3 },
    undress:        { id: 'undress',        priority: 3 },
    massage:        { id: 'massage',        priority: 3 },
    beckon:         { id: 'beckon',         priority: 3 },
    hair_flip:      { id: 'hair_flip',      priority: 3 },
    blow_kiss:      { id: 'blow_kiss',      priority: 3 },
    shrug:          { id: 'shrug',          priority: 3 },
    phone:          { id: 'phone',          priority: 3 },
    smoke:          { id: 'smoke',          priority: 3 },

    // ── Intimate/Paired ──
    embrace:        { id: 'embrace',        priority: 4 },
    kiss_standing:  { id: 'kiss_standing',  priority: 4 },
    lap_sit:        { id: 'lap_sit',        priority: 4 },
    straddle:       { id: 'straddle',       priority: 4 },
    ride:           { id: 'ride',           priority: 4 },
    going_down:     { id: 'going_down',     priority: 4 },
    missionary:     { id: 'missionary',     priority: 4 },
    doggy:          { id: 'doggy',          priority: 4 },
    spooning:       { id: 'spooning',       priority: 4 },
    dominant_pose:  { id: 'dominant_pose',  priority: 4 },
    submissive:     { id: 'submissive',     priority: 4 },
    seductive_pose: { id: 'seductive_pose', priority: 4 },
    flirt:          { id: 'flirt',          priority: 3 },
    intimate_touch: { id: 'intimate_touch', priority: 4 },

    // ── Special ──
    pose:           { id: 'pose',           priority: 4 },
  };

  // Blend durations (seconds) between state transitions
  const BLEND_DURATIONS = {
    // ── Basic transitions ──
    'idle→walk':     0.4,  'walk→idle':     0.5,
    'idle→run':      0.3,  'run→idle':      0.4,  'walk→run': 0.3, 'run→walk': 0.4,

    // ── Seated ──
    'idle→sit':      0.8,  'sit→idle':      0.7,
    'idle→sit_cross': 0.9, 'sit_cross→idle': 0.7,
    'idle→sit_lean': 0.8,  'sit_lean→idle': 0.7,
    'idle→sit_floor': 1.0, 'sit_floor→idle': 0.9,
    'sit→sit_cross': 0.5,  'sit_cross→sit': 0.5,
    'sit→sit_lean': 0.4,   'sit_lean→sit': 0.4,

    // ── Standing poses ──
    'idle→lean':     0.6,  'lean→idle':     0.5,
    'idle→arms_crossed': 0.5, 'arms_crossed→idle': 0.4,
    'idle→hands_behind': 0.5, 'hands_behind→idle': 0.4,

    // ── Lying ──
    'idle→lie':      1.2,  'lie→idle':      1.0,
    'idle→lie_side': 1.3,  'lie_side→idle': 1.1,
    'idle→lie_front': 1.4, 'lie_front→idle': 1.2,
    'idle→lounge':   1.0,  'lounge→idle':   0.8,
    'sit→lie':       1.0,  'lie→sit':       0.9,
    'sit→lounge':    0.6,  'lounge→sit':    0.5,
    'lie→lie_side':  0.8,  'lie_side→lie':  0.8,
    'lie→lie_front': 1.0,  'lie_front→lie': 1.0,

    // ── Ground ──
    'idle→kneel':    0.9,  'kneel→idle':    0.8,
    'idle→kneel_sit': 1.0, 'kneel_sit→idle': 0.9,
    'idle→all_fours': 1.1, 'all_fours→idle': 1.0,
    'idle→crawl':    1.2,  'crawl→idle':    1.0,
    'idle→sprawl':   1.3,  'sprawl→idle':   1.1,
    'kneel→all_fours': 0.6, 'all_fours→kneel': 0.6,
    'kneel→kneel_sit': 0.5, 'kneel_sit→kneel': 0.5,
    'all_fours→crawl': 0.3, 'crawl→all_fours': 0.3,

    // ── Furniture ──
    'idle→interact': 0.3,  'interact→idle': 0.4,
    'idle→drink':    0.4,  'drink→idle':    0.3,
    'idle→gaze':     0.6,  'gaze→idle':     0.5,
    'idle→warm':     0.7,  'warm→idle':     0.5,
    'idle→primp':    0.5,  'primp→idle':    0.4,
    'idle→bathe':    1.0,  'bathe→idle':    0.8,
    'lean→drink':    0.3,  'drink→lean':    0.3,

    // ── Action/Gesture ──
    'idle→dance_slow': 0.6,  'dance_slow→idle': 0.5,
    'idle→dance_sway': 0.5,  'dance_sway→idle': 0.4,
    'idle→stretch':    0.5,  'stretch→idle':    0.6,
    'idle→undress':    0.4,  'undress→idle':    0.5,
    'idle→massage':    0.5,  'massage→idle':    0.5,
    'idle→beckon':     0.3,  'beckon→idle':     0.3,
    'idle→hair_flip':  0.3,  'hair_flip→idle':  0.4,
    'idle→blow_kiss':  0.3,  'blow_kiss→idle':  0.3,
    'idle→shrug':      0.3,  'shrug→idle':      0.3,
    'idle→phone':      0.4,  'phone→idle':      0.3,
    'idle→smoke':      0.4,  'smoke→idle':      0.3,
    'dance_slow→dance_sway': 0.4, 'dance_sway→dance_slow': 0.4,

    // ── Intimate/Paired ──
    'idle→embrace':    0.6,  'embrace→idle':    0.5,
    'idle→kiss_standing': 0.5, 'kiss_standing→idle': 0.4,
    'idle→flirt':      0.3,  'flirt→idle':      0.3,
    'idle→seductive_pose': 0.5, 'seductive_pose→idle': 0.5,
    'idle→dominant_pose': 0.4, 'dominant_pose→idle': 0.4,
    'idle→submissive': 0.5,  'submissive→idle': 0.5,
    'idle→intimate_touch': 0.4, 'intimate_touch→idle': 0.4,
    'sit→lap_sit':     0.6,  'lap_sit→sit':     0.5,
    'idle→lap_sit':    0.8,  'lap_sit→idle':    0.7,
    'idle→straddle':   0.8,  'straddle→idle':   0.7,
    'idle→ride':       0.8,  'ride→idle':       0.7,
    'kneel→going_down': 0.5, 'going_down→kneel': 0.5,
    'idle→going_down': 0.9,  'going_down→idle': 0.8,
    'lie→missionary':  0.6,  'missionary→lie':  0.6,
    'idle→missionary': 1.0,  'missionary→idle': 0.9,
    'all_fours→doggy': 0.4,  'doggy→all_fours': 0.4,
    'idle→doggy':      1.1,  'doggy→idle':      1.0,
    'lie_side→spooning': 0.5, 'spooning→lie_side': 0.5,
    'idle→spooning':   1.2,  'spooning→idle':   1.0,
    'straddle→ride':   0.4,  'ride→straddle':   0.4,

    // ── Pose/Special ──
    'idle→pose':     0.5,  'pose→idle':     0.6,

    // ── Fallback ──
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

      // ═════════════════════════════════════════════════════════════
      //  BODY POSITION STATES
      // ═════════════════════════════════════════════════════════════

      // ── RUN state ──────────────────────────────────────────────
      if (this.currentState === 'run') {
        this.walkPhase += dt * 5.5;
        const r = t;
        if (model.armL) {
          model.armL.rotation.x = 0.55 * Math.sin(this.walkPhase) * r;
          model.armL.rotation.z = -0.15 * r;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.55 * Math.sin(this.walkPhase) * r;
          model.armR.rotation.z = 0.15 * r;
        }
        if (model.legL) model.legL.rotation.x = 0.6 * Math.sin(this.walkPhase) * r;
        if (model.legR) model.legR.rotation.x = -0.6 * Math.sin(this.walkPhase) * r;
        model.bodyGroup.position.y = 0.04 * Math.abs(Math.sin(this.walkPhase * 2)) * r;
        model.bodyGroup.rotation.x = 0.08 * r;
        model.bodyGroup.rotation.z = 0.04 * Math.sin(this.walkPhase) * r;
      }

      // ── SIT_CROSS state (legs crossed elegantly) ───────────────
      if (this.currentState === 'sit_cross') {
        const s = t;
        model.group.position.y = -0.35 * s + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = -1.4 * s;
          model.legL.rotation.z = -0.05 * s;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.2 * s;
          model.legR.rotation.z = 0.2 * s;  // crossed over
          model.legR.rotation.y = -0.3 * s;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.15 * s;
          model.armL.rotation.z = -0.2 * s;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.25 * s;
          model.armR.rotation.z = 0.1 * s;
        }
        model.bodyGroup.rotation.x = 0.03 * s;
      }

      // ── SIT_LEAN state (leaning back casually) ─────────────────
      if (this.currentState === 'sit_lean') {
        const s = t;
        model.group.position.y = -0.32 * s + (model._baseY || 0);
        model.bodyGroup.rotation.x = -0.25 * s;
        if (model.legL) {
          model.legL.rotation.x = -1.1 * s;
          model.legL.rotation.z = -0.1 * s;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.0 * s;
          model.legR.rotation.z = 0.15 * s;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.1 * s;
          model.armL.rotation.z = -0.5 * s;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.1 * s;
          model.armR.rotation.z = 0.4 * s;
        }
      }

      // ── SIT_FLOOR state (sitting on the floor) ─────────────────
      if (this.currentState === 'sit_floor') {
        const s = t;
        model.group.position.y = -0.55 * s + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = -0.9 * s;
          model.legL.rotation.z = -0.3 * s;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.2 * s;
          model.legR.rotation.z = 0.1 * s;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.3 * s;
          model.armL.rotation.z = -0.15 * s;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.2 * s;
          model.armR.rotation.z = 0.2 * s;
        }
      }

      // ── ARMS_CROSSED state (standing, confident) ───────────────
      if (this.currentState === 'arms_crossed') {
        const a = t;
        if (model.armL) {
          model.armL.rotation.x = -0.7 * a;
          model.armL.rotation.z = -0.35 * a;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.7 * a;
          model.armR.rotation.z = 0.35 * a;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = -0.05 * a;
        }
        model.bodyGroup.rotation.x = -0.03 * a;
      }

      // ── HANDS_BEHIND state (hands behind back, formal) ─────────
      if (this.currentState === 'hands_behind') {
        const h = t;
        if (model.armL) {
          model.armL.rotation.x = 0.4 * h;
          model.armL.rotation.z = 0.2 * h;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.4 * h;
          model.armR.rotation.z = -0.2 * h;
        }
        model.bodyGroup.rotation.x = -0.05 * h;
      }

      // ── LIE_SIDE state (lying on one side) ─────────────────────
      if (this.currentState === 'lie_side') {
        const l = t;
        model.group.position.y = -0.65 * l + (model._baseY || 0);
        model.bodyGroup.rotation.x = -1.3 * l;
        model.bodyGroup.rotation.z = 0.4 * l;  // rolled to side
        if (model.legL) {
          model.legL.rotation.x = -0.3 * l;
          model.legL.rotation.z = -0.15 * l;
        }
        if (model.legR) {
          model.legR.rotation.x = -0.5 * l;
          model.legR.rotation.z = 0.1 * l;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.8 * l;
          model.armL.rotation.z = -0.3 * l;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.3 * l;
          model.armR.rotation.z = 0.4 * l;
        }
        const breath = 1.0 + this.breathDepth * 0.4 * Math.sin(time * this.breathRate * Math.PI * 2);
        const torso = model.bodyGroup.children[0];
        if (torso) {
          torso.scale.x = breath;
          torso.scale.z = (d ? d.torsoScaleZ : 1) * breath;
        }
      }

      // ── LIE_FRONT state (lying face-down) ──────────────────────
      if (this.currentState === 'lie_front') {
        const l = t;
        model.group.position.y = -0.7 * l + (model._baseY || 0);
        model.bodyGroup.rotation.x = -1.55 * l;  // face down
        if (model.legL) {
          model.legL.rotation.x = 0.1 * l;
          model.legL.rotation.z = -0.1 * l;
        }
        if (model.legR) {
          model.legR.rotation.x = 0.1 * l;
          model.legR.rotation.z = 0.1 * l;
        }
        if (model.armL) {
          model.armL.rotation.x = -1.0 * l;
          model.armL.rotation.z = -0.5 * l;
        }
        if (model.armR) {
          model.armR.rotation.x = -1.0 * l;
          model.armR.rotation.z = 0.5 * l;
        }
      }

      // ── KNEEL state (upright kneeling) ─────────────────────────
      if (this.currentState === 'kneel') {
        const k = t;
        model.group.position.y = -0.45 * k + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = -1.6 * k;
          model.legL.rotation.z = -0.03 * k;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.6 * k;
          model.legR.rotation.z = 0.03 * k;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.1 * k;
          model.armL.rotation.z = -0.1 * k;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.1 * k;
          model.armR.rotation.z = 0.1 * k;
        }
        model.bodyGroup.rotation.x = 0.05 * k;
      }

      // ── KNEEL_SIT state (sitting on heels) ─────────────────────
      if (this.currentState === 'kneel_sit') {
        const k = t;
        model.group.position.y = -0.55 * k + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = -2.0 * k;
          model.legL.rotation.z = -0.05 * k;
        }
        if (model.legR) {
          model.legR.rotation.x = -2.0 * k;
          model.legR.rotation.z = 0.05 * k;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.2 * k;
          model.armL.rotation.z = -0.15 * k;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.2 * k;
          model.armR.rotation.z = 0.15 * k;
        }
      }

      // ── ALL_FOURS state ────────────────────────────────────────
      if (this.currentState === 'all_fours') {
        const a = t;
        model.group.position.y = -0.5 * a + (model._baseY || 0);
        model.bodyGroup.rotation.x = 1.1 * a;  // torso forward/horizontal
        if (model.legL) {
          model.legL.rotation.x = -1.6 * a;
          model.legL.rotation.z = -0.1 * a;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.6 * a;
          model.legR.rotation.z = 0.1 * a;
        }
        if (model.armL) {
          model.armL.rotation.x = -1.5 * a;
          model.armL.rotation.z = -0.1 * a;
        }
        if (model.armR) {
          model.armR.rotation.x = -1.5 * a;
          model.armR.rotation.z = 0.1 * a;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = -0.4 * a;
        }
      }

      // ── CRAWL state (moving on all fours) ──────────────────────
      if (this.currentState === 'crawl') {
        this.walkPhase += dt * 2.0;
        const c = t;
        model.group.position.y = -0.5 * c + (model._baseY || 0);
        model.bodyGroup.rotation.x = 1.0 * c;
        const phase = this.walkPhase;
        if (model.armL) {
          model.armL.rotation.x = (-1.5 + 0.3 * Math.sin(phase)) * c;
          model.armL.rotation.z = -0.1 * c;
        }
        if (model.armR) {
          model.armR.rotation.x = (-1.5 - 0.3 * Math.sin(phase)) * c;
          model.armR.rotation.z = 0.1 * c;
        }
        if (model.legL) {
          model.legL.rotation.x = (-1.6 - 0.2 * Math.sin(phase)) * c;
        }
        if (model.legR) {
          model.legR.rotation.x = (-1.6 + 0.2 * Math.sin(phase)) * c;
        }
        model.bodyGroup.rotation.z = 0.03 * Math.sin(phase * 0.5) * c;
      }

      // ── SPRAWL state (spread out on floor/bed) ─────────────────
      if (this.currentState === 'sprawl') {
        const s = t;
        model.group.position.y = -0.7 * s + (model._baseY || 0);
        model.bodyGroup.rotation.x = -1.5 * s;
        if (model.legL) {
          model.legL.rotation.x = -0.3 * s;
          model.legL.rotation.z = -0.4 * s;
        }
        if (model.legR) {
          model.legR.rotation.x = -0.2 * s;
          model.legR.rotation.z = 0.5 * s;
        }
        if (model.armL) {
          model.armL.rotation.x = -1.3 * s;
          model.armL.rotation.z = -0.7 * s;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.5 * s;
          model.armR.rotation.z = 0.8 * s;
        }
      }

      // ═════════════════════════════════════════════════════════════
      //  ACTION / GESTURE STATES
      // ═════════════════════════════════════════════════════════════

      // ── DANCE_SLOW state (slow romantic sway) ──────────────────
      if (this.currentState === 'dance_slow') {
        this.walkPhase += dt * 1.5;
        const ds = t;
        const phase = this.walkPhase;
        model.bodyGroup.rotation.y = 0.15 * Math.sin(phase * 0.5) * ds;
        model.bodyGroup.rotation.z = 0.05 * Math.sin(phase * 0.7) * ds;
        model.bodyGroup.position.y = 0.02 * Math.sin(phase) * ds;
        if (model.armL) {
          model.armL.rotation.x = -0.3 * ds;
          model.armL.rotation.z = (-0.3 + 0.1 * Math.sin(phase * 0.6)) * ds;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.4 * ds;
          model.armR.rotation.z = (0.2 + 0.1 * Math.sin(phase * 0.6 + 1.0)) * ds;
        }
        if (model.legL) model.legL.rotation.x = 0.05 * Math.sin(phase * 0.5) * ds;
        if (model.legR) model.legR.rotation.x = -0.05 * Math.sin(phase * 0.5) * ds;
      }

      // ── DANCE_SWAY state (hip-swaying dance) ───────────────────
      if (this.currentState === 'dance_sway') {
        this.walkPhase += dt * 2.5;
        const ds = t;
        const p = this.walkPhase;
        model.bodyGroup.rotation.y = 0.2 * Math.sin(p * 0.7) * ds;
        model.bodyGroup.rotation.z = 0.08 * Math.sin(p * 1.3) * ds;
        model.bodyGroup.position.y = 0.03 * Math.abs(Math.sin(p)) * ds;
        model.bodyGroup.position.x = 0.04 * Math.sin(p * 0.5) * ds;
        if (model.armL) {
          model.armL.rotation.x = (-0.2 + 0.3 * Math.sin(p)) * ds;
          model.armL.rotation.z = (-0.2 + 0.15 * Math.sin(p * 0.8)) * ds;
        }
        if (model.armR) {
          model.armR.rotation.x = (-0.3 + 0.3 * Math.sin(p + 1.5)) * ds;
          model.armR.rotation.z = (0.2 - 0.15 * Math.sin(p * 0.8 + 1.0)) * ds;
        }
        if (model.legL) {
          model.legL.rotation.x = 0.1 * Math.sin(p * 0.7) * ds;
          model.legL.rotation.z = -0.05 * Math.sin(p) * ds;
        }
        if (model.legR) {
          model.legR.rotation.x = -0.1 * Math.sin(p * 0.7) * ds;
          model.legR.rotation.z = 0.05 * Math.sin(p) * ds;
        }
      }

      // ── STRETCH state ──────────────────────────────────────────
      if (this.currentState === 'stretch') {
        const st = t;
        const phase = Math.sin(time * 0.4);
        if (model.armL) {
          model.armL.rotation.x = (-1.8 + 0.1 * phase) * st;
          model.armL.rotation.z = (-0.2 + 0.05 * phase) * st;
        }
        if (model.armR) {
          model.armR.rotation.x = (-1.8 + 0.1 * phase) * st;
          model.armR.rotation.z = (0.2 - 0.05 * phase) * st;
        }
        model.bodyGroup.rotation.x = (-0.1 + 0.03 * phase) * st;
        if (model.legL) model.legL.rotation.x = 0.03 * phase * st;
        if (model.legR) model.legR.rotation.x = -0.02 * phase * st;
      }

      // ── UNDRESS state (removing clothing gesture) ──────────────
      if (this.currentState === 'undress') {
        const u = t;
        const phase = Math.sin(time * 0.6);
        if (model.armR) {
          model.armR.rotation.x = (-0.4 + 0.3 * phase) * u;
          model.armR.rotation.z = (0.3 + 0.1 * phase) * u;
        }
        if (model.armL) {
          model.armL.rotation.x = (-0.6 - 0.2 * phase) * u;
          model.armL.rotation.z = (-0.2 + 0.1 * phase) * u;
        }
        model.bodyGroup.rotation.y = 0.05 * Math.sin(time * 0.3) * u;
        model.bodyGroup.rotation.z = 0.03 * phase * u;
      }

      // ── MASSAGE state (giving/receiving massage) ───────────────
      if (this.currentState === 'massage') {
        const m = t;
        const phase = time * 1.2;
        if (model.armL) {
          model.armL.rotation.x = (-0.5 + 0.15 * Math.sin(phase)) * m;
          model.armL.rotation.z = -0.2 * m;
        }
        if (model.armR) {
          model.armR.rotation.x = (-0.5 + 0.15 * Math.sin(phase + 1.5)) * m;
          model.armR.rotation.z = 0.2 * m;
        }
        model.bodyGroup.rotation.x = 0.1 * m;
        model.bodyGroup.rotation.y = 0.03 * Math.sin(phase * 0.5) * m;
      }

      // ── BECKON state (come-hither finger curl) ─────────────────
      if (this.currentState === 'beckon') {
        const b = t;
        const curl = Math.sin(time * 2.0);
        if (model.armR) {
          model.armR.rotation.x = (-0.6 + 0.05 * curl) * b;
          model.armR.rotation.z = 0.15 * b;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.1 * b;
          model.armL.rotation.z = -0.1 * b;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.y = 0.08 * b;
          model.headData.group.rotation.z = 0.05 * b;
        }
        model.bodyGroup.rotation.x = 0.03 * b;
      }

      // ── HAIR_FLIP state ────────────────────────────────────────
      if (this.currentState === 'hair_flip') {
        const h = t;
        const flip = Math.sin(time * 1.5);
        if (model.armR) {
          model.armR.rotation.x = (-1.3 + 0.3 * flip) * h;
          model.armR.rotation.z = 0.2 * h;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.15 * h;
          model.armL.rotation.z = -0.2 * h;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.z = 0.15 * Math.sin(time * 1.5 + 0.5) * h;
          model.headData.group.rotation.y = 0.1 * flip * h;
        }
        model.bodyGroup.rotation.z = 0.04 * flip * h;
      }

      // ── BLOW_KISS state ────────────────────────────────────────
      if (this.currentState === 'blow_kiss') {
        const bk = t;
        const phase = Math.sin(time * 1.0);
        if (model.armR) {
          model.armR.rotation.x = (-0.8 - 0.2 * Math.max(0, phase)) * bk;
          model.armR.rotation.z = (0.3 + 0.1 * Math.max(0, phase)) * bk;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.1 * bk;
          model.armL.rotation.z = -0.15 * bk;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = -0.05 * bk;
          model.headData.group.rotation.y = 0.1 * bk;
        }
      }

      // ── SHRUG state ────────────────────────────────────────────
      if (this.currentState === 'shrug') {
        const sh = t;
        const bounce = Math.sin(time * 2.5);
        if (model.armL) {
          model.armL.rotation.x = (-0.3 + 0.1 * bounce) * sh;
          model.armL.rotation.z = (-0.5 + 0.1 * bounce) * sh;
        }
        if (model.armR) {
          model.armR.rotation.x = (-0.3 + 0.1 * bounce) * sh;
          model.armR.rotation.z = (0.5 - 0.1 * bounce) * sh;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.z = 0.08 * sh;
        }
      }

      // ── PHONE state (holding phone to ear) ─────────────────────
      if (this.currentState === 'phone') {
        const ph = t;
        if (model.armR) {
          model.armR.rotation.x = -1.2 * ph;
          model.armR.rotation.z = 0.3 * ph;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.2 * ph;
          model.armL.rotation.z = -0.1 * ph;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.z = 0.1 * ph;
        }
        model.bodyGroup.rotation.y = 0.02 * Math.sin(time * 0.3) * ph;
      }

      // ── SMOKE state (holding cigarette) ────────────────────────
      if (this.currentState === 'smoke') {
        const sm = t;
        const puff = Math.sin(time * 0.5);
        if (model.armR) {
          model.armR.rotation.x = (-0.5 - 0.3 * Math.max(0, puff)) * sm;
          model.armR.rotation.z = 0.15 * sm;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.1 * sm;
          model.armL.rotation.z = -0.15 * sm;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = (-0.05 - 0.03 * Math.max(0, puff)) * sm;
        }
      }

      // ── FLIRT state (playful attention-getting) ────────────────
      if (this.currentState === 'flirt') {
        const f = t;
        const sway = Math.sin(time * 1.0);
        model.bodyGroup.rotation.y = 0.08 * sway * f;
        model.bodyGroup.rotation.z = 0.04 * Math.sin(time * 0.7) * f;
        if (model.armL) {
          model.armL.rotation.x = (0.15 + 0.1 * sway) * f;
          model.armL.rotation.z = -0.2 * f;
        }
        if (model.armR) {
          model.armR.rotation.x = (-0.3 + 0.15 * sway) * f;
          model.armR.rotation.z = 0.25 * f;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.y = 0.1 * sway * f;
          model.headData.group.rotation.z = 0.06 * f;
        }
      }

      // ═════════════════════════════════════════════════════════════
      //  INTIMATE / PAIRED STATES
      // ═════════════════════════════════════════════════════════════

      // ── EMBRACE state (standing embrace/hug) ───────────────────
      if (this.currentState === 'embrace') {
        const e = t;
        if (model.armL) {
          model.armL.rotation.x = -0.5 * e;
          model.armL.rotation.z = -0.4 * e;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.6 * e;
          model.armR.rotation.z = 0.3 * e;
        }
        model.bodyGroup.rotation.x = 0.05 * e;
        const sway = Math.sin(time * 0.4);
        model.bodyGroup.rotation.y = 0.02 * sway * e;
      }

      // ── KISS_STANDING state ────────────────────────────────────
      if (this.currentState === 'kiss_standing') {
        const k = t;
        model.bodyGroup.rotation.x = 0.08 * k;
        if (model.armL) {
          model.armL.rotation.x = -0.4 * k;
          model.armL.rotation.z = -0.5 * k;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.6 * k;
          model.armR.rotation.z = 0.4 * k;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = 0.1 * k;
          model.headData.group.rotation.z = 0.15 * k;
        }
      }

      // ── LAP_SIT state (sitting on someone's lap) ───────────────
      if (this.currentState === 'lap_sit') {
        const l = t;
        model.group.position.y = -0.2 * l + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = -1.2 * l;
          model.legL.rotation.z = -0.2 * l;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.2 * l;
          model.legR.rotation.z = 0.2 * l;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.3 * l;
          model.armL.rotation.z = -0.3 * l;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.4 * l;
          model.armR.rotation.z = 0.2 * l;
        }
        model.bodyGroup.rotation.x = 0.05 * l;
        model.bodyGroup.rotation.y = 0.03 * Math.sin(time * 0.5) * l;
      }

      // ── STRADDLE state (straddling, facing) ────────────────────
      if (this.currentState === 'straddle') {
        const s = t;
        model.group.position.y = -0.25 * s + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = -1.3 * s;
          model.legL.rotation.z = -0.4 * s;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.3 * s;
          model.legR.rotation.z = 0.4 * s;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.3 * s;
          model.armL.rotation.z = -0.2 * s;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.3 * s;
          model.armR.rotation.z = 0.2 * s;
        }
        model.bodyGroup.rotation.x = 0.1 * s;
      }

      // ── RIDE state (rhythmic riding motion) ────────────────────
      if (this.currentState === 'ride') {
        this.walkPhase += dt * 2.0;
        const r = t;
        const p = this.walkPhase;
        model.group.position.y = (-0.25 + 0.08 * Math.sin(p)) * r + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = (-1.3 + 0.1 * Math.sin(p)) * r;
          model.legL.rotation.z = -0.4 * r;
        }
        if (model.legR) {
          model.legR.rotation.x = (-1.3 + 0.1 * Math.sin(p)) * r;
          model.legR.rotation.z = 0.4 * r;
        }
        if (model.armL) {
          model.armL.rotation.x = (-0.3 + 0.1 * Math.sin(p * 0.5)) * r;
          model.armL.rotation.z = -0.2 * r;
        }
        if (model.armR) {
          model.armR.rotation.x = (-0.3 + 0.1 * Math.sin(p * 0.5)) * r;
          model.armR.rotation.z = 0.2 * r;
        }
        model.bodyGroup.rotation.x = (0.1 + 0.05 * Math.sin(p)) * r;
        model.bodyGroup.rotation.z = 0.03 * Math.sin(p * 0.7) * r;
      }

      // ── GOING_DOWN state (kneeling oral position) ──────────────
      if (this.currentState === 'going_down') {
        const g = t;
        model.group.position.y = -0.5 * g + (model._baseY || 0);
        if (model.legL) {
          model.legL.rotation.x = -1.8 * g;
          model.legL.rotation.z = -0.05 * g;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.8 * g;
          model.legR.rotation.z = 0.05 * g;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.4 * g;
          model.armL.rotation.z = -0.15 * g;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.5 * g;
          model.armR.rotation.z = 0.1 * g;
        }
        model.bodyGroup.rotation.x = 0.15 * g;
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = 0.1 * g;
          const bob = Math.sin(time * 1.5);
          model.headData.group.rotation.x += 0.05 * bob * g;
        }
      }

      // ── MISSIONARY state (lying back, legs parted) ─────────────
      if (this.currentState === 'missionary') {
        const m = t;
        model.group.position.y = -0.65 * m + (model._baseY || 0);
        model.bodyGroup.rotation.x = -1.4 * m;
        if (model.legL) {
          model.legL.rotation.x = -0.5 * m;
          model.legL.rotation.z = -0.4 * m;
        }
        if (model.legR) {
          model.legR.rotation.x = -0.5 * m;
          model.legR.rotation.z = 0.4 * m;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.6 * m;
          model.armL.rotation.z = -0.5 * m;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.5 * m;
          model.armR.rotation.z = 0.4 * m;
        }
        const rhythm = Math.sin(time * 1.8);
        model.bodyGroup.position.y = 0.02 * rhythm * m;
      }

      // ── DOGGY state (on all fours, receiving) ──────────────────
      if (this.currentState === 'doggy') {
        this.walkPhase += dt * 2.2;
        const dg = t;
        const p = this.walkPhase;
        model.group.position.y = -0.5 * dg + (model._baseY || 0);
        model.bodyGroup.rotation.x = 1.1 * dg;
        if (model.legL) {
          model.legL.rotation.x = -1.5 * dg;
          model.legL.rotation.z = -0.15 * dg;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.5 * dg;
          model.legR.rotation.z = 0.15 * dg;
        }
        if (model.armL) {
          model.armL.rotation.x = -1.5 * dg;
          model.armL.rotation.z = -0.1 * dg;
        }
        if (model.armR) {
          model.armR.rotation.x = -1.5 * dg;
          model.armR.rotation.z = 0.1 * dg;
        }
        // Rhythmic motion
        model.bodyGroup.position.z = 0.03 * Math.sin(p) * dg;
        model.bodyGroup.rotation.z = 0.02 * Math.sin(p * 0.7) * dg;
      }

      // ── SPOONING state (lying side-by-side) ────────────────────
      if (this.currentState === 'spooning') {
        const sp = t;
        model.group.position.y = -0.65 * sp + (model._baseY || 0);
        model.bodyGroup.rotation.x = -1.3 * sp;
        model.bodyGroup.rotation.z = 0.35 * sp;
        if (model.legL) {
          model.legL.rotation.x = -0.4 * sp;
          model.legL.rotation.z = -0.1 * sp;
        }
        if (model.legR) {
          model.legR.rotation.x = -0.6 * sp;
          model.legR.rotation.z = 0.1 * sp;
        }
        if (model.armL) {
          model.armL.rotation.x = -0.4 * sp;
          model.armL.rotation.z = -0.3 * sp;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.5 * sp;
          model.armR.rotation.z = 0.2 * sp;
        }
        const breathSp = 1.0 + this.breathDepth * 0.4 * Math.sin(time * this.breathRate * Math.PI * 2);
        const torsoSp = model.bodyGroup.children[0];
        if (torsoSp) {
          torsoSp.scale.x = breathSp;
          torsoSp.scale.z = (d ? d.torsoScaleZ : 1) * breathSp;
        }
      }

      // ── DOMINANT_POSE state (standing over, authoritative) ─────
      if (this.currentState === 'dominant_pose') {
        const dp = t;
        model.bodyGroup.rotation.x = -0.05 * dp;
        if (model.armL) {
          model.armL.rotation.x = 0.15 * dp;
          model.armL.rotation.z = -0.3 * dp;
        }
        if (model.armR) {
          model.armR.rotation.x = -0.3 * dp;
          model.armR.rotation.z = 0.15 * dp;
        }
        if (model.legL) {
          model.legL.rotation.z = -0.1 * dp;
        }
        if (model.legR) {
          model.legR.rotation.z = 0.1 * dp;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = -0.1 * dp;
        }
      }

      // ── SUBMISSIVE state (kneeling, head lowered) ──────────────
      if (this.currentState === 'submissive') {
        const sb = t;
        model.group.position.y = -0.5 * sb + (model._baseY || 0);
        model.bodyGroup.rotation.x = 0.2 * sb;
        if (model.legL) {
          model.legL.rotation.x = -1.8 * sb;
          model.legL.rotation.z = -0.03 * sb;
        }
        if (model.legR) {
          model.legR.rotation.x = -1.8 * sb;
          model.legR.rotation.z = 0.03 * sb;
        }
        if (model.armL) {
          model.armL.rotation.x = 0.3 * sb;
          model.armL.rotation.z = -0.1 * sb;
        }
        if (model.armR) {
          model.armR.rotation.x = 0.3 * sb;
          model.armR.rotation.z = 0.1 * sb;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.x = 0.2 * sb;
        }
      }

      // ── SEDUCTIVE_POSE state (alluring posture) ────────────────
      if (this.currentState === 'seductive_pose') {
        const se = t;
        const sway = Math.sin(time * 0.6);
        model.bodyGroup.rotation.y = 0.08 * sway * se;
        model.bodyGroup.rotation.z = 0.05 * se;
        if (model.armL) {
          model.armL.rotation.x = 0.15 * se;
          model.armL.rotation.z = -0.25 * se;
        }
        if (model.armR) {
          model.armR.rotation.x = (-0.6 + 0.1 * sway) * se;
          model.armR.rotation.z = 0.3 * se;
        }
        if (model.legL) {
          model.legL.rotation.z = -0.05 * se;
        }
        if (model.legR) {
          model.legR.rotation.x = 0.1 * se;
          model.legR.rotation.z = 0.12 * se;
        }
        if (model.headData && model.headData.group) {
          model.headData.group.rotation.y = 0.1 * sway * se;
          model.headData.group.rotation.z = 0.08 * se;
        }
      }

      // ── INTIMATE_TOUCH state (gentle touch/caress) ─────────────
      if (this.currentState === 'intimate_touch') {
        const it = t;
        const caress = Math.sin(time * 0.8);
        if (model.armR) {
          model.armR.rotation.x = (-0.4 + 0.15 * caress) * it;
          model.armR.rotation.z = (0.2 + 0.05 * caress) * it;
        }
        if (model.armL) {
          model.armL.rotation.x = (-0.2 + 0.1 * caress) * it;
          model.armL.rotation.z = -0.15 * it;
        }
        model.bodyGroup.rotation.x = 0.05 * it;
        model.bodyGroup.rotation.y = 0.03 * caress * it;
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

    // ── Explicit activity overrides (most specific first) ──

    // Movement
    if (act.includes('run') || act.includes('sprint') || act.includes('rush')) return 'run';
    if (act.includes('walk') || act.includes('moving') || act.includes('approach')) return 'walk';
    if (act.includes('crawl')) return 'crawl';

    // Intimate/Adult (highest priority when matched)
    if (act.includes('missionary')) return 'missionary';
    if (act.includes('doggy') || act.includes('from behind')) return 'doggy';
    if (act.includes('spooning') || act.includes('spoon')) return 'spooning';
    if (act.includes('riding') || act.includes('ride') || act.includes('cowgirl')) return 'ride';
    if (act.includes('straddle') || act.includes('mount')) return 'straddle';
    if (act.includes('going down') || act.includes('oral') || act.includes('blowjob') || act.includes('cunnilingus')) return 'going_down';
    if (act.includes('lap sit') || act.includes('lap dance') || act.includes('on lap')) return 'lap_sit';
    if (act.includes('kiss') && (act.includes('stand') || act.includes('deep'))) return 'kiss_standing';
    if (act.includes('embrace') || act.includes('hug') || act.includes('hold')) return 'embrace';
    if (act.includes('touch') || act.includes('caress') || act.includes('fondle') || act.includes('grope')) return 'intimate_touch';
    if (act.includes('dominant') || act.includes('command') || act.includes('order') || act.includes('intimidat')) return 'dominant_pose';
    if (act.includes('submissive') || act.includes('obey') || act.includes('submit') || act.includes('beg')) return 'submissive';
    if (act.includes('seduct') || act.includes('tease') || act.includes('tempt') || act.includes('allur')) return 'seductive_pose';
    if (act.includes('flirt') || act.includes('wink') || act.includes('come hither')) return 'flirt';

    // Actions & Gestures
    if (act.includes('dance') && (act.includes('slow') || act.includes('romantic'))) return 'dance_slow';
    if (act.includes('dance') || act.includes('sway') || act.includes('groove')) return 'dance_sway';
    if (act.includes('undress') || act.includes('strip') || act.includes('remove') || act.includes('take off')) return 'undress';
    if (act.includes('stretch') || act.includes('yawn') || act.includes('wake')) return 'stretch';
    if (act.includes('massage') || act.includes('rub')) return 'massage';
    if (act.includes('beckon') || act.includes('come here')) return 'beckon';
    if (act.includes('hair flip') || act.includes('toss hair')) return 'hair_flip';
    if (act.includes('blow kiss')) return 'blow_kiss';
    if (act.includes('shrug')) return 'shrug';
    if (act.includes('phone') || act.includes('call') || act.includes('text')) return 'phone';
    if (act.includes('smoke') || act.includes('cigarette') || act.includes('vape')) return 'smoke';

    // Body positions
    if (act.includes('kneel') && (act.includes('sit') || act.includes('heel'))) return 'kneel_sit';
    if (act.includes('kneel')) return 'kneel';
    if (act.includes('all fours') || act.includes('hands and knees')) return 'all_fours';
    if (act.includes('sprawl') || act.includes('spread')) return 'sprawl';
    if (act.includes('arms crossed') || act.includes('cross arms')) return 'arms_crossed';
    if (act.includes('hands behind') || act.includes('at ease')) return 'hands_behind';
    if (act.includes('sit') && (act.includes('cross') || act.includes('leg'))) return 'sit_cross';
    if (act.includes('sit') && (act.includes('lean') || act.includes('back'))) return 'sit_lean';
    if (act.includes('sit') && (act.includes('floor') || act.includes('ground'))) return 'sit_floor';

    // Furniture/location activities
    if (act.includes('drink') || act.includes('sip') || act.includes('cocktail') || act.includes('wine')) return 'drink';
    if (act.includes('bathe') || act.includes('shower') || act.includes('wash') || act.includes('soak')) return 'bathe';
    if (act.includes('primp') || act.includes('groom') || act.includes('makeup') || act.includes('mirror')) return 'primp';
    if (act.includes('interact') || act.includes('using') || act.includes('use')) return 'interact';
    if (act.includes('pose') || act.includes('model') || act.includes('show off')) return 'pose';

    // Lying variations
    if (act.includes('lie') && act.includes('side')) return 'lie_side';
    if (act.includes('lie') && (act.includes('front') || act.includes('face down') || act.includes('stomach'))) return 'lie_front';
    if (act.includes('lie') || act.includes('sleep') || act.includes('rest') || act.includes('nap')) return 'lie';
    if (act.includes('lounge') || act.includes('relax') || act.includes('chill')) return 'lounge';
    if (act.includes('gaze') || act.includes('look') || act.includes('stare') || act.includes('view')) return 'gaze';
    if (act.includes('warm') || act.includes('fire') || act.includes('cozy')) return 'warm';
    if (act.includes('cuddle') || act.includes('snuggle')) return 'spooning';
    if (act.includes('make out') || act.includes('kiss')) return 'kiss_standing';

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
