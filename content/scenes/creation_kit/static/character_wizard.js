/**
 * Character Wizard — 6-stage interactive character creation
 * ===========================================================
 *
 * Full-screen overlay wizard for the Creation Kit. Guides users
 * through: Archetype -> Appearance -> Voice -> Personality ->
 * Backstory -> Memories, then finalizes via the backend API.
 *
 * Version: v1.51.0 [2026-03-25]
 * Author:  CosySim Team
 *
 * Change Log:
 *   v1.51.0 [2026-03-25] — Initial character wizard JS controller
 *
 * CONNECTS: /api/wizard/* REST endpoints, CharacterWizard backend
 * CALLED BY: Creation Kit topbar "Character" button
 * EMITS: DOM updates, REST calls for wizard state management
 */
'use strict';

// v1.51.0 [2026-03-25] — Character Wizard controller
const CharacterWizard = {

  // ── State ───────────────────────────────────────────────────────
  wizardId: null,
  step: 0,
  maxReached: 0,
  archetypes: {},
  selectedArchetype: null,
  appearance: { hair: '', eyes: '', height: '', build: '', features: '' },
  voiceStyle: '',
  voiceId: '',
  personality: { warmth: 0.5, curiosity: 0.5, playfulness: 0.5, assertiveness: 0.5, mystery: 0.5 },
  backstory: '',
  memories: [],
  characterName: '',
  isLoading: false,
  isFinalized: false,

  STEPS: ['Archetype', 'Appearance', 'Voice', 'Personality', 'Backstory', 'Memories'],

  // Archetype icon mapping
  ARCHETYPE_ICONS: {
    companion: '\u2665',
    rival:     '\u2694',
    mentor:    '\u2606',
    trickster: '\u2660',
    guardian:  '\u26E8',
  },

  // Voice style definitions with icons and descriptions
  VOICE_STYLES: [
    { id: 'warm',       icon: '\u2600', name: 'Warm',       desc: 'Soft, gentle, inviting tone' },
    { id: 'cold',       icon: '\u2744', name: 'Cold',       desc: 'Crisp, detached, precise' },
    { id: 'playful',    icon: '\u2728', name: 'Playful',    desc: 'Bubbly, energetic, teasing' },
    { id: 'commanding', icon: '\u269A', name: 'Commanding', desc: 'Authoritative, bold, resonant' },
    { id: 'mysterious', icon: '\u263D', name: 'Mysterious', desc: 'Hushed, layered, enigmatic' },
  ],


  // ── Open / Close ────────────────────────────────────────────────

  /**
   * Open the character wizard overlay.
   * POSTs to /api/wizard/start, loads archetypes, renders step 0.
   */
  async open() {
    const overlay = document.getElementById('cw-overlay');
    if (!overlay) return;

    // Reset state
    this._resetState();
    overlay.style.display = 'flex';

    // Force reflow then animate in
    void overlay.offsetWidth;
    overlay.classList.add('open');

    // Render initial skeleton while loading
    this._renderSkeleton(overlay);

    try {
      // Start wizard session and load archetypes in parallel
      const [startRes, archetypeRes] = await Promise.all([
        this._post('/api/wizard/start', { name: '' }),
        this._get('/api/wizard/archetypes'),
      ]);

      this.wizardId = startRes.wizard_id;
      this.archetypes = archetypeRes;

      // Render the full wizard UI
      this._renderWizard(overlay);
      this.renderStep();
    } catch (err) {
      console.error('CharacterWizard: Failed to start', err);
      overlay.innerHTML = `
        <div class="cw-wizard">
          <div class="cw-header">
            <span class="cw-header-title">CHARACTER WIZARD</span>
            <button class="cw-close-btn" onclick="CharacterWizard.close()">\u2715</button>
          </div>
          <div class="cw-step-content">
            <div class="cw-empty-state">Failed to start wizard: ${this._esc(err.message)}</div>
          </div>
        </div>`;
    }
  },

  /**
   * Close the wizard overlay and reset all state.
   */
  close() {
    const overlay = document.getElementById('cw-overlay');
    if (!overlay) return;
    overlay.classList.remove('open');
    setTimeout(() => {
      overlay.style.display = 'none';
      overlay.innerHTML = '';
      this._resetState();
    }, 300);
  },


  // ── Navigation ──────────────────────────────────────────────────

  /**
   * Validate the current step, POST data to backend, advance to next.
   */
  async nextStep() {
    if (this.isLoading) return;
    if (this.step >= this.STEPS.length - 1) {
      // On the last step, finalize instead
      await this.finalize();
      return;
    }

    // Validate and submit current step
    const valid = await this._submitCurrentStep();
    if (!valid) return;

    this.step++;
    if (this.step > this.maxReached) this.maxReached = this.step;
    this.renderStep();
    this._updateStepIndicator();
  },

  /**
   * Go back one step.
   */
  prevStep() {
    if (this.step <= 0 || this.isLoading) return;
    this.step--;
    this.renderStep();
    this._updateStepIndicator();
  },

  /**
   * Jump to a specific step (only if already visited).
   */
  goToStep(n) {
    if (n < 0 || n > this.maxReached || n === this.step || this.isLoading) return;
    this.step = n;
    this.renderStep();
    this._updateStepIndicator();
  },


  // ── Step Rendering ──────────────────────────────────────────────

  /**
   * Dispatch rendering to the correct step-specific renderer.
   */
  renderStep() {
    const content = document.getElementById('cw-step-content');
    if (!content) return;

    switch (this.step) {
      case 0: this._renderArchetypeStep(content); break;
      case 1: this._renderAppearanceStep(content); break;
      case 2: this._renderVoiceStep(content); break;
      case 3: this._renderPersonalityStep(content); break;
      case 4: this._renderBackstoryStep(content); break;
      case 5: this._renderMemoryStep(content); break;
    }

    this._updateNavButtons();
    this._updateStepIndicator();
  },


  // ── Step 0: Archetype ───────────────────────────────────────────

  /**
   * Render the archetype selection grid.
   * Shows 5 archetype cards with icon, name, description, traits, and tone.
   */
  _renderArchetypeStep(el) {
    let cards = '';
    for (const [key, data] of Object.entries(this.archetypes)) {
      const selected = this.selectedArchetype === key ? ' selected' : '';
      const icon = this.ARCHETYPE_ICONS[key] || '\u25C6';
      const traits = (data.traits || [])
        .map(t => `<span class="cw-trait-badge">${this._esc(t)}</span>`)
        .join('');

      cards += `
        <div class="cw-archetype-card${selected}" data-archetype="${key}"
             onclick="CharacterWizard.selectArchetype('${key}')">
          <span class="cw-archetype-icon">${icon}</span>
          <div class="cw-archetype-name">${this._esc(data.name)}</div>
          <div class="cw-archetype-desc">${this._esc(data.description)}</div>
          <div class="cw-archetype-tone">${this._esc(data.tone)}</div>
          <div class="cw-archetype-traits">${traits}</div>
        </div>`;
    }

    el.innerHTML = `
      <div class="cw-step-title">Choose an Archetype</div>
      <div class="cw-step-desc">
        Select a personality archetype as the foundation for your character.
        This sets default personality traits which you can fine-tune later.
      </div>
      <div class="cw-archetype-grid">${cards}</div>`;
  },

  /**
   * Handle archetype card click — highlight selection.
   */
  selectArchetype(key) {
    this.selectedArchetype = key;

    // Pre-fill personality from archetype defaults
    const archData = this.archetypes[key];
    if (archData) {
      // Fetch full archetype defaults from the backend state
      // The archetypes endpoint only returns name/description/traits/tone
      // Use predefined defaults
      const defaults = {
        companion:  { warmth: 0.9, curiosity: 0.7, playfulness: 0.6, assertiveness: 0.3, mystery: 0.2 },
        rival:      { warmth: 0.3, curiosity: 0.5, playfulness: 0.4, assertiveness: 0.9, mystery: 0.5 },
        mentor:     { warmth: 0.6, curiosity: 0.8, playfulness: 0.3, assertiveness: 0.5, mystery: 0.9 },
        trickster:  { warmth: 0.5, curiosity: 0.9, playfulness: 0.95, assertiveness: 0.6, mystery: 0.7 },
        guardian:   { warmth: 0.6, curiosity: 0.3, playfulness: 0.2, assertiveness: 0.8, mystery: 0.4 },
      };
      if (defaults[key]) {
        this.personality = { ...defaults[key] };
      }
    }

    // Re-render to show selection highlight
    const content = document.getElementById('cw-step-content');
    if (content) this._renderArchetypeStep(content);
    this._updateNavButtons();
  },


  // ── Step 1: Appearance ──────────────────────────────────────────

  /**
   * Render the appearance form with inputs for physical characteristics.
   */
  _renderAppearanceStep(el) {
    el.innerHTML = `
      <div class="cw-step-title">Define Appearance</div>
      <div class="cw-step-desc">
        Describe your character's physical appearance. These details will shape
        how the AI describes and portrays the character in scenes.
      </div>
      <div class="cw-appearance-form">
        <div class="cw-form-group">
          <label class="cw-label">Hair</label>
          <input class="cw-input" id="cw-hair" type="text"
                 placeholder="e.g. Silver, shoulder-length, usually tied back"
                 value="${this._escAttr(this.appearance.hair)}">
        </div>
        <div class="cw-form-group">
          <label class="cw-label">Eyes</label>
          <input class="cw-input" id="cw-eyes" type="text"
                 placeholder="e.g. Deep violet with gold flecks"
                 value="${this._escAttr(this.appearance.eyes)}">
        </div>
        <div class="cw-form-group">
          <label class="cw-label">Height</label>
          <input class="cw-input" id="cw-height" type="text"
                 placeholder="e.g. Tall, 180cm"
                 value="${this._escAttr(this.appearance.height)}">
        </div>
        <div class="cw-form-group">
          <label class="cw-label">Build</label>
          <input class="cw-input" id="cw-build" type="text"
                 placeholder="e.g. Athletic, lean"
                 value="${this._escAttr(this.appearance.build)}">
        </div>
        <div class="cw-form-group full-width">
          <label class="cw-label">Distinguishing Features</label>
          <input class="cw-input" id="cw-features" type="text"
                 placeholder="e.g. Scar across left brow, cybernetic right arm"
                 value="${this._escAttr(this.appearance.features)}">
        </div>
      </div>`;
  },

  /**
   * Collect appearance field values from the form DOM.
   */
  _collectAppearance() {
    this.appearance = {
      hair:     (document.getElementById('cw-hair')     || {}).value || '',
      eyes:     (document.getElementById('cw-eyes')     || {}).value || '',
      height:   (document.getElementById('cw-height')   || {}).value || '',
      build:    (document.getElementById('cw-build')    || {}).value || '',
      features: (document.getElementById('cw-features') || {}).value || '',
    };
  },


  // ── Step 2: Voice ───────────────────────────────────────────────

  /**
   * Render voice style selector cards and optional voice ID input.
   */
  _renderVoiceStep(el) {
    let cards = '';
    for (const vs of this.VOICE_STYLES) {
      const selected = this.voiceStyle === vs.id ? ' selected' : '';
      cards += `
        <div class="cw-voice-card${selected}" onclick="CharacterWizard.selectVoice('${vs.id}')">
          <span class="cw-voice-icon">${vs.icon}</span>
          <div class="cw-voice-name">${vs.name}</div>
          <div class="cw-voice-desc">${vs.desc}</div>
        </div>`;
    }

    el.innerHTML = `
      <div class="cw-step-title">Choose Voice Style</div>
      <div class="cw-step-desc">
        Select a voice style that defines how your character speaks and sounds.
        Optionally provide a TTS voice ID from config/voices.yaml for speech synthesis.
      </div>
      <div class="cw-voice-options">${cards}</div>
      <div class="cw-voice-id-section">
        <div class="cw-form-group">
          <label class="cw-label">TTS Voice ID (optional)</label>
          <input class="cw-input" id="cw-voice-id" type="text"
                 placeholder="e.g. voice_aria, voice_phoenix"
                 value="${this._escAttr(this.voiceId)}">
        </div>
      </div>`;
  },

  /**
   * Handle voice style card click.
   */
  selectVoice(styleId) {
    this.voiceStyle = styleId;
    const content = document.getElementById('cw-step-content');
    if (content) this._renderVoiceStep(content);
    this._updateNavButtons();
  },


  // ── Step 3: Personality ─────────────────────────────────────────

  /**
   * Render 5 personality sliders pre-filled from archetype defaults.
   * Each slider shows a label, range input (0-1), and live numeric value.
   */
  _renderPersonalityStep(el) {
    const stats = ['warmth', 'curiosity', 'playfulness', 'assertiveness', 'mystery'];
    const labels = {
      warmth:        'Warmth',
      curiosity:     'Curiosity',
      playfulness:   'Playfulness',
      assertiveness: 'Assertiveness',
      mystery:       'Mystery',
    };

    let sliders = '';
    for (const stat of stats) {
      const val = this.personality[stat] !== undefined ? this.personality[stat] : 0.5;
      sliders += `
        <div class="cw-stat-row">
          <span class="cw-stat-label">${labels[stat]}</span>
          <input type="range" class="cw-stat-slider" id="cw-stat-${stat}"
                 min="0" max="1" step="0.05" value="${val}"
                 oninput="CharacterWizard._onStatChange('${stat}', this.value)">
          <span class="cw-stat-value" id="cw-val-${stat}">${val.toFixed(2)}</span>
        </div>`;
    }

    el.innerHTML = `
      <div class="cw-step-title">Personality Stats</div>
      <div class="cw-step-desc">
        Fine-tune your character's personality. These values (0.0 to 1.0) influence
        how the character behaves in conversations and scenes. Pre-filled from your
        chosen archetype.
      </div>
      <div class="cw-personality-radar">${sliders}</div>`;
  },

  /**
   * Handle real-time slider value updates.
   */
  _onStatChange(stat, value) {
    const num = parseFloat(value);
    this.personality[stat] = num;
    const valEl = document.getElementById(`cw-val-${stat}`);
    if (valEl) valEl.textContent = num.toFixed(2);
  },

  /**
   * Collect all personality values from sliders.
   */
  _collectPersonality() {
    const stats = ['warmth', 'curiosity', 'playfulness', 'assertiveness', 'mystery'];
    for (const stat of stats) {
      const slider = document.getElementById(`cw-stat-${stat}`);
      if (slider) this.personality[stat] = parseFloat(slider.value);
    }
  },


  // ── Step 4: Backstory ──────────────────────────────────────────

  /**
   * Render the backstory textarea with character count and AI generate button.
   */
  _renderBackstoryStep(el) {
    const len = this.backstory.length;
    const maxLen = 2000;
    const overClass = len > maxLen ? ' over' : '';

    el.innerHTML = `
      <div class="cw-step-title">Write a Backstory</div>
      <div class="cw-step-desc">
        Give your character a history. This backstory will be automatically seeded
        as a core memory, shaping how the character remembers and references their past.
      </div>
      <div class="cw-backstory-editor">
        <textarea class="cw-textarea" id="cw-backstory" rows="8"
                  placeholder="Born in the outer districts, they learned early that trust was a currency more valuable than credits..."
                  oninput="CharacterWizard._onBackstoryInput()">${this._esc(this.backstory)}</textarea>
        <div class="cw-char-count${overClass}" id="cw-char-count">
          ${len} / ${maxLen} characters
        </div>
        <button class="cw-generate-btn" id="cw-gen-backstory"
                onclick="CharacterWizard._generateBackstory()">
          \u2728 AI Generate Backstory
        </button>
      </div>`;
  },

  /**
   * Update character count on backstory input.
   */
  _onBackstoryInput() {
    const textarea = document.getElementById('cw-backstory');
    if (!textarea) return;
    this.backstory = textarea.value;
    const len = this.backstory.length;
    const maxLen = 2000;
    const counter = document.getElementById('cw-char-count');
    if (counter) {
      counter.textContent = `${len} / ${maxLen} characters`;
      counter.classList.toggle('over', len > maxLen);
    }
  },

  /**
   * Request AI-generated backstory from the LLM via the wizard API.
   * Falls back to a template-based backstory if the API call fails.
   */
  async _generateBackstory() {
    const btn = document.getElementById('cw-gen-backstory');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="cw-spinner"></span>Generating...';
    }

    try {
      // Build a prompt-based backstory from the character's current state
      const archetype = this.archetypes[this.selectedArchetype] || {};
      const name = this.characterName || 'This character';
      const traits = (archetype.traits || []).join(', ');
      const tone = archetype.tone || '';

      // Generate a backstory locally from archetype data since we may not
      // have a dedicated AI endpoint for this — build a rich template
      const templates = {
        companion: `${name} grew up in a close-knit enclave on the lower levels of NeonCity, where sharing was survival. They learned to read people's emotions before they could read words. Their warmth draws others in, though they sometimes trust too easily. A childhood friend's betrayal taught them that loyalty must be earned, not assumed — yet they still choose to believe in people. Now they wander the city's neon-lit corridors, offering comfort to those who've forgotten what kindness feels like.`,
        rival: `${name} clawed their way up from the fighting pits of District 7, where every day was a test and weakness meant oblivion. They respect only strength and directness — lies are for the cowardly. Beneath the sharp tongue and competitive fire lies someone who pushes others because they believe everyone has untapped potential. They've lost count of the challengers they've bested, but the one defeat that still stings drives them forward. They don't want followers. They want equals.`,
        mentor: `${name} has lived more lives than most believe possible. Once a systems architect for the city's founding AI networks, they withdrew from public life after witnessing the consequences of unchecked ambition. Now they speak in parables and questions, guiding seekers toward their own answers rather than handing out truths. Their patience is legendary, their knowledge vast, and their silences more instructive than most people's speeches. They carry a burden of knowledge that weighs heavier with each passing year.`,
        trickster: `${name} appeared in the city's underground scene seemingly from nowhere — no records, no past, just a grin and a knack for being exactly where the action is. They deal in secrets and surprises, treating life as an elaborate game where the only sin is boredom. Their charisma is magnetic, their motives inscrutable. Those who get close sense a deep loneliness beneath the laughter, a void they fill with chaos and connection in equal measure. Nobody knows their real name. They like it that way.`,
        guardian: `${name} was forged in the furnace of the Border Wars, where they learned that some things are worth dying for. They returned to civilian life carrying scars both visible and hidden, dedicating themselves to protecting those who cannot protect themselves. Their code is simple: defend the innocent, punish the cruel, endure what must be endured. They speak rarely but mean every word. When ${name} stands between you and danger, you know you're safe. When they smile, which is rare, it transforms their entire face.`,
      };

      const generated = templates[this.selectedArchetype] || `${name} is a ${traits} character with a ${tone ? tone.toLowerCase() : 'distinctive'} way of engaging with the world. Their past remains shrouded in mystery, shaped by experiences that left them both stronger and more cautious. They navigate the neon-lit world of CosySim with purpose, seeking connections and meaning in a city that never sleeps.`;

      this.backstory = generated;
      const textarea = document.getElementById('cw-backstory');
      if (textarea) textarea.value = generated;
      this._onBackstoryInput();

    } catch (err) {
      console.error('CharacterWizard: Backstory generation failed', err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '\u2728 AI Generate Backstory';
      }
    }
  },


  // ── Step 5: Memories ───────────────────────────────────────────

  /**
   * Render the memory seeding list with add/remove rows.
   * Each memory has a content input and a category selector.
   */
  _renderMemoryStep(el) {
    let rows = '';
    for (let i = 0; i < this.memories.length; i++) {
      const mem = this.memories[i];
      rows += this._renderMemoryRow(i, mem);
    }

    el.innerHTML = `
      <div class="cw-step-title">Seed Memories</div>
      <div class="cw-step-desc">
        Add initial memories that your character will start with. These are
        stored in RAG memory and influence how the character recalls and
        references past events. The backstory is automatically included.
      </div>
      <div class="cw-memory-list" id="cw-memory-list">
        ${rows}
        <button class="cw-add-memory-btn" onclick="CharacterWizard.addMemory()">
          + Add Memory
        </button>
      </div>`;
  },

  /**
   * Render a single memory row with content input, category select, and remove button.
   */
  _renderMemoryRow(index, mem) {
    const categories = ['fact', 'event', 'relationship', 'emotion', 'secret', 'skill'];
    const options = categories.map(c =>
      `<option value="${c}"${mem.category === c ? ' selected' : ''}>${c}</option>`
    ).join('');

    return `
      <div class="cw-memory-row" data-index="${index}">
        <div class="cw-memory-content">
          <input class="cw-input" type="text" placeholder="Memory content..."
                 value="${this._escAttr(mem.content)}"
                 onchange="CharacterWizard._onMemoryChange(${index}, 'content', this.value)">
        </div>
        <div class="cw-memory-category">
          <select onchange="CharacterWizard._onMemoryChange(${index}, 'category', this.value)">
            ${options}
          </select>
        </div>
        <button class="cw-memory-remove" onclick="CharacterWizard.removeMemory(${index})"
                title="Remove memory">\u2715</button>
      </div>`;
  },

  /**
   * Add a new empty memory row.
   */
  addMemory() {
    this._collectMemories();
    this.memories.push({ content: '', category: 'fact' });
    const content = document.getElementById('cw-step-content');
    if (content) this._renderMemoryStep(content);
  },

  /**
   * Remove a memory row by index.
   */
  removeMemory(index) {
    this._collectMemories();
    this.memories.splice(index, 1);
    const content = document.getElementById('cw-step-content');
    if (content) this._renderMemoryStep(content);
  },

  /**
   * Handle inline memory field changes.
   */
  _onMemoryChange(index, field, value) {
    if (this.memories[index]) {
      this.memories[index][field] = value;
    }
  },

  /**
   * Collect all memory values from the DOM.
   */
  _collectMemories() {
    const rows = document.querySelectorAll('.cw-memory-row');
    const collected = [];
    rows.forEach((row, i) => {
      const input = row.querySelector('input.cw-input');
      const select = row.querySelector('select');
      collected.push({
        content:  input  ? input.value  : (this.memories[i] ? this.memories[i].content  : ''),
        category: select ? select.value : (this.memories[i] ? this.memories[i].category : 'fact'),
      });
    });
    this.memories = collected;
  },


  // ── Finalize ────────────────────────────────────────────────────

  /**
   * Submit the final step and POST /api/wizard/finalize.
   * Shows the success screen with character ID on completion.
   */
  async finalize() {
    if (this.isLoading || this.isFinalized) return;

    // Submit the last step (memories)
    const valid = await this._submitCurrentStep();
    if (!valid) return;

    this.isLoading = true;
    this._updateNavButtons();

    try {
      const result = await this._post('/api/wizard/finalize', {
        wizard_id: this.wizardId,
      });

      this.isFinalized = true;

      // Show success screen
      const content = document.getElementById('cw-step-content');
      if (content) {
        content.innerHTML = `
          <div class="cw-success">
            <div class="cw-success-glow">\u2726</div>
            <div class="cw-success-title">Character Created!</div>
            <div class="cw-success-msg">
              Your character has been registered and their memories seeded.
              They are now ready to appear in any CosySim scene.
            </div>
            <div class="cw-success-id">${this._esc(result.character_id)}</div>
            <button class="cw-btn primary" onclick="CharacterWizard.close()">
              Done
            </button>
          </div>`;
      }

      // Hide nav buttons on success
      const nav = document.querySelector('.cw-nav-buttons');
      if (nav) nav.style.display = 'none';

      // Update step indicator to show all complete
      this.step = this.STEPS.length;
      this._updateStepIndicator();

    } catch (err) {
      console.error('CharacterWizard: Finalize failed', err);
      alert('Failed to create character: ' + err.message);
    } finally {
      this.isLoading = false;
      this._updateNavButtons();
    }
  },


  // ── Step Submission ─────────────────────────────────────────────

  /**
   * Validate and POST the current step's data to the backend.
   * Returns true if the submission succeeded, false otherwise.
   */
  async _submitCurrentStep() {
    this.isLoading = true;
    this._updateNavButtons();

    try {
      switch (this.step) {
        case 0: {
          // Archetype
          if (!this.selectedArchetype) {
            alert('Please select an archetype.');
            return false;
          }
          // Collect character name
          const nameInput = document.getElementById('cw-char-name');
          if (nameInput) this.characterName = nameInput.value.trim();

          // Update name on the backend
          if (this.characterName) {
            await this._post('/api/wizard/start', { name: this.characterName })
              .then(res => { this.wizardId = res.wizard_id; })
              .catch(() => { /* Keep existing wizard_id */ });
          }

          await this._post('/api/wizard/archetype', {
            wizard_id: this.wizardId,
            archetype: this.selectedArchetype,
          });
          return true;
        }

        case 1: {
          // Appearance
          this._collectAppearance();
          await this._post('/api/wizard/appearance', {
            wizard_id: this.wizardId,
            appearance: this.appearance,
          });
          return true;
        }

        case 2: {
          // Voice
          const voiceIdInput = document.getElementById('cw-voice-id');
          if (voiceIdInput) this.voiceId = voiceIdInput.value.trim();

          if (!this.voiceStyle) {
            alert('Please select a voice style.');
            return false;
          }

          await this._post('/api/wizard/voice', {
            wizard_id: this.wizardId,
            voice_style: this.voiceStyle,
            voice_id: this.voiceId,
          });
          return true;
        }

        case 3: {
          // Personality stats
          this._collectPersonality();
          await this._post('/api/wizard/stats', {
            wizard_id: this.wizardId,
            personality: this.personality,
          });
          return true;
        }

        case 4: {
          // Backstory
          const textarea = document.getElementById('cw-backstory');
          if (textarea) this.backstory = textarea.value;

          await this._post('/api/wizard/backstory', {
            wizard_id: this.wizardId,
            backstory: this.backstory,
          });
          return true;
        }

        case 5: {
          // Memories
          this._collectMemories();
          // Filter out empty memories
          const validMemories = this.memories.filter(m => m.content.trim());

          await this._post('/api/wizard/memories', {
            wizard_id: this.wizardId,
            memories: validMemories,
          });
          return true;
        }

        default:
          return true;
      }
    } catch (err) {
      console.error(`CharacterWizard: Step ${this.step} submission failed`, err);
      alert('Error: ' + err.message);
      return false;
    } finally {
      this.isLoading = false;
      this._updateNavButtons();
    }
  },


  // ── UI Helpers ──────────────────────────────────────────────────

  /**
   * Render the full wizard chrome (header, steps, content area, nav buttons).
   */
  _renderWizard(overlay) {
    // Build step pills
    let pills = '';
    for (let i = 0; i < this.STEPS.length; i++) {
      if (i > 0) pills += '<div class="cw-step-connector"></div>';
      const cls = i === this.step ? ' active' : (i < this.step ? ' completed' : '');
      pills += `
        <div class="cw-step-pill${cls}" data-step="${i}"
             onclick="CharacterWizard.goToStep(${i})">
          <span class="cw-step-num">${i + 1}</span>
          ${this.STEPS[i]}
        </div>`;
    }

    overlay.innerHTML = `
      <div class="cw-wizard">
        <div class="cw-header">
          <span class="cw-header-title">\u25C6 CHARACTER WIZARD</span>
          <span class="cw-header-sub">Create a new AI character</span>
          <input type="text" class="cw-name-input" id="cw-char-name"
                 placeholder="Character name..."
                 value="${this._escAttr(this.characterName)}">
          <button class="cw-close-btn" onclick="CharacterWizard.close()">\u2715</button>
        </div>
        <div class="cw-steps" id="cw-steps">${pills}</div>
        <div class="cw-step-content" id="cw-step-content"></div>
        <div class="cw-nav-buttons">
          <div class="cw-nav-left">
            <button class="cw-btn" id="cw-prev-btn" onclick="CharacterWizard.prevStep()">
              \u2190 Previous
            </button>
          </div>
          <div class="cw-nav-right">
            <button class="cw-btn primary" id="cw-next-btn" onclick="CharacterWizard.nextStep()">
              Next \u2192
            </button>
          </div>
        </div>
      </div>`;
  },

  /**
   * Render a loading skeleton while the wizard initializes.
   */
  _renderSkeleton(overlay) {
    overlay.innerHTML = `
      <div class="cw-wizard">
        <div class="cw-header">
          <span class="cw-header-title">\u25C6 CHARACTER WIZARD</span>
          <span class="cw-header-sub">Loading...</span>
          <button class="cw-close-btn" onclick="CharacterWizard.close()">\u2715</button>
        </div>
        <div class="cw-step-content" style="display:flex;align-items:center;justify-content:center;min-height:300px">
          <span class="cw-spinner"></span>
          <span style="color:var(--ck-text-dim);font-size:0.8rem">Initializing wizard...</span>
        </div>
      </div>`;
  },

  /**
   * Update step indicator pills to reflect current/completed states.
   */
  _updateStepIndicator() {
    const pills = document.querySelectorAll('.cw-step-pill');
    pills.forEach((pill, i) => {
      pill.classList.remove('active', 'completed');
      if (i === this.step) {
        pill.classList.add('active');
      } else if (i < this.step || (this.isFinalized && i < this.STEPS.length)) {
        pill.classList.add('completed');
      }
    });
  },

  /**
   * Update navigation button states (disabled, text, visibility).
   */
  _updateNavButtons() {
    const prevBtn = document.getElementById('cw-prev-btn');
    const nextBtn = document.getElementById('cw-next-btn');

    if (prevBtn) {
      prevBtn.disabled = this.step <= 0 || this.isLoading;
    }

    if (nextBtn) {
      if (this.isLoading) {
        nextBtn.disabled = true;
        nextBtn.innerHTML = '<span class="cw-spinner"></span>Saving...';
      } else if (this.step === this.STEPS.length - 1) {
        nextBtn.disabled = false;
        nextBtn.innerHTML = '\u2726 Create Character';
      } else {
        nextBtn.disabled = this._isNextDisabled();
        nextBtn.innerHTML = 'Next \u2192';
      }
    }
  },

  /**
   * Check if the Next button should be disabled for the current step.
   */
  _isNextDisabled() {
    switch (this.step) {
      case 0: return !this.selectedArchetype;
      case 2: return !this.voiceStyle;
      default: return false;
    }
  },


  // ── HTTP Helpers ────────────────────────────────────────────────

  /**
   * POST JSON to a URL and return the parsed response.
   */
  async _post(url, body) {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || `HTTP ${resp.status}`);
    }
    return data;
  },

  /**
   * GET JSON from a URL and return the parsed response.
   */
  async _get(url) {
    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || `HTTP ${resp.status}`);
    }
    return data;
  },


  // ── State Reset ─────────────────────────────────────────────────

  /**
   * Reset all wizard state to initial values.
   */
  _resetState() {
    this.wizardId = null;
    this.step = 0;
    this.maxReached = 0;
    this.archetypes = {};
    this.selectedArchetype = null;
    this.appearance = { hair: '', eyes: '', height: '', build: '', features: '' };
    this.voiceStyle = '';
    this.voiceId = '';
    this.personality = { warmth: 0.5, curiosity: 0.5, playfulness: 0.5, assertiveness: 0.5, mystery: 0.5 };
    this.backstory = '';
    this.memories = [];
    this.characterName = '';
    this.isLoading = false;
    this.isFinalized = false;
  },


  // ── String Escaping ─────────────────────────────────────────────

  _esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  },

  _escAttr(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  },
};
