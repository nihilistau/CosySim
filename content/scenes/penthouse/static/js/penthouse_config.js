/**
 * penthouse_config.js — YAML Configuration Loader
 * 
 * Fetches character, outfit, scene, and animation configs from the backend
 * (/api/config/*) and applies them to CharModels, penthouse3D, and
 * CharacterBridge at runtime. This makes every visual property data-driven
 * via YAML files in config/penthouse/.
 *
 * Load order: Three.js → penthouse_3d.js → character_models.js
 *           → character_bridge.js → penthouse_config.js → penthouse.js
 */

(function () {
  'use strict';

  const PenthouseConfig = {
    _loaded: false,
    _data: null,

    /**
     * Fetch all config from /api/config/all and apply to subsystems.
     * Returns a promise that resolves when all configs are applied.
     */
    async load() {
      if (this._loaded) return this._data;
      try {
        const resp = await fetch('/api/config/all');
        if (!resp.ok) {
          console.warn('[PenthouseConfig] Failed to load config:', resp.status);
          return null;
        }
        this._data = await resp.json();
        this._applyCharacterConfig(this._data.characters || {});
        this._applyOutfitConfig(this._data.outfits || {});
        this._applySceneConfig(this._data.scene || {});
        this._applyAnimationConfig(this._data.animations || {});
        this._loaded = true;
        console.debug('[PenthouseConfig] All configs loaded and applied');
        return this._data;
      } catch (err) {
        console.error('[PenthouseConfig] Load error:', err);
        return null;
      }
    },

    /**
     * Get a config section after loading.
     */
    get(section) {
      return this._data ? this._data[section] : null;
    },

    /**
     * Apply character appearance config to CharModels.
     * Overrides SKIN_TONES, HAIR_COLORS, and per-character CHAR_LOOKS.
     */
    _applyCharacterConfig(cfg) {
      if (!window.CharModels) {
        console.warn('[PenthouseConfig] CharModels not available, skipping character config');
        return;
      }

      // Apply skin tones
      if (cfg.skin_tones && CharModels.SKIN_TONES !== undefined) {
        const tones = {};
        for (const [name, hex] of Object.entries(cfg.skin_tones)) {
          tones[name] = typeof hex === 'string' ? parseInt(hex.replace('0x', ''), 16) : hex;
        }
        Object.assign(CharModels.SKIN_TONES, tones);
      }

      // Apply hair colors
      if (cfg.hair_colors && CharModels.HAIR_COLORS !== undefined) {
        const colors = {};
        for (const [name, hex] of Object.entries(cfg.hair_colors)) {
          colors[name] = typeof hex === 'string' ? parseInt(hex.replace('0x', ''), 16) : hex;
        }
        Object.assign(CharModels.HAIR_COLORS, colors);
      }

      // Apply eye colors
      if (cfg.eye_colors && CharModels.EYE_COLORS !== undefined) {
        const colors = {};
        for (const [name, hex] of Object.entries(cfg.eye_colors)) {
          colors[name] = typeof hex === 'string' ? parseInt(hex.replace('0x', ''), 16) : hex;
        }
        Object.assign(CharModels.EYE_COLORS, colors);
      }

      // Apply per-character looks from YAML
      if (cfg.characters && CharModels.CHAR_LOOKS !== undefined) {
        for (const [charName, charCfg] of Object.entries(cfg.characters)) {
          if (!charCfg.appearance) continue;
          const app = charCfg.appearance;
          const look = {};
          if (app.skin) look.skin = app.skin;
          if (app.hair_color) look.hairColor = app.hair_color;
          if (app.hair_style) look.hairStyle = app.hair_style;
          if (app.eye_color) look.eyes = app.eye_color;
          if (app.height_mult) look.heightMult = app.height_mult;
          if (app.build) look.build = app.build;
          CharModels.CHAR_LOOKS[charName] = look;
        }
      }

      // Apply body dimension tables
      if (cfg.body_dimensions) {
        if (cfg.body_dimensions.female && CharModels.FD !== undefined) {
          const fd = cfg.body_dimensions.female;
          for (const [key, val] of Object.entries(fd)) {
            CharModels.FD[key] = val;
          }
        }
        if (cfg.body_dimensions.male && CharModels.MD !== undefined) {
          const md = cfg.body_dimensions.male;
          for (const [key, val] of Object.entries(md)) {
            CharModels.MD[key] = val;
          }
        }
      }

      // Apply material properties
      if (cfg.materials && CharModels.MATERIALS !== undefined) {
        Object.assign(CharModels.MATERIALS, cfg.materials);
      }
    },

    /**
     * Apply outfit config to CharModels.
     * Overrides OUTFIT_MAP, LAYER_HIDES, and OUTFIT_COLORS.
     */
    _applyOutfitConfig(cfg) {
      if (!window.CharModels) return;

      // Apply outfit → layer mappings
      if (cfg.outfits && CharModels.OUTFIT_MAP !== undefined) {
        const map = {};
        for (const [name, def] of Object.entries(cfg.outfits)) {
          map[name] = def.layers || [];
        }
        Object.assign(CharModels.OUTFIT_MAP, map);
      }

      // Apply layer hide rules
      if (cfg.layer_hides && CharModels.LAYER_HIDES !== undefined) {
        Object.assign(CharModels.LAYER_HIDES, cfg.layer_hides);
      }

      // Apply outfit color themes
      if (cfg.outfit_colors && CharModels.OUTFIT_COLORS !== undefined) {
        const colors = {};
        for (const [name, theme] of Object.entries(cfg.outfit_colors)) {
          if (!theme) {
            colors[name] = null;
            continue;
          }
          const parsed = {};
          if (theme.color) parsed.color = parseInt(String(theme.color).replace('0x', ''), 16);
          if (theme.accent) parsed.accent = parseInt(String(theme.accent).replace('0x', ''), 16);
          if (theme.alpha !== undefined) parsed.alpha = theme.alpha;
          if (theme.shiny !== undefined) parsed.shiny = theme.shiny;
          colors[name] = parsed;
        }
        Object.assign(CharModels.OUTFIT_COLORS, colors);
      }
    },

    /**
     * Apply scene environment config to penthouse3D.
     * Updates location positions, camera views, lighting presets, and effects.
     */
    _applySceneConfig(cfg) {
      if (!window.penthouse3D) return;

      // Apply location positions (used by CharacterBridge for character placement)
      if (cfg.locations && typeof penthouse3D.setLocationPositions === 'function') {
        const positions = {};
        for (const [loc, data] of Object.entries(cfg.locations)) {
          if (data.position) {
            positions[loc] = {
              x: data.position.x,
              y: data.position.y,
              z: data.position.z
            };
          }
        }
        penthouse3D.setLocationPositions(positions);
      }

      // Apply camera view presets
      if (cfg.camera_views && typeof penthouse3D.setCameraViews === 'function') {
        penthouse3D.setCameraViews(cfg.camera_views);
      }

      // Apply lighting presets
      if (cfg.lighting && typeof penthouse3D.setLightingPresets === 'function') {
        penthouse3D.setLightingPresets(cfg.lighting);
      }

      // Apply effects config
      if (cfg.effects && typeof penthouse3D.setEffectsConfig === 'function') {
        penthouse3D.setEffectsConfig(cfg.effects);
      }

      // Store location data for CharacterBridge to use
      if (cfg.locations && window.CharacterBridge) {
        CharacterBridge._locationData = cfg.locations;
      }
    },

    /**
     * Apply animation config to CharacterBridge and CharModels.
     * Updates idle params, expressions, movement speed, UI settings.
     */
    _applyAnimationConfig(cfg) {
      // Apply idle animation parameters
      if (cfg.idle && window.CharModels && CharModels.IDLE_PARAMS !== undefined) {
        Object.assign(CharModels.IDLE_PARAMS, cfg.idle);
      }

      // Apply expression definitions
      if (cfg.expressions && window.CharModels && CharModels.EXPRESSIONS !== undefined) {
        Object.assign(CharModels.EXPRESSIONS, cfg.expressions);
      }

      // Apply movement/lerp speed to CharacterBridge
      if (cfg.movement && window.CharacterBridge) {
        if (cfg.movement.lerp_speed) {
          CharacterBridge._lerpSpeed = cfg.movement.lerp_speed;
        }
      }

      // Apply occupant offsets
      if (cfg.occupant_offsets && window.CharacterBridge) {
        CharacterBridge._occupantOffsets = cfg.occupant_offsets;
      }

      // Apply name label config
      if (cfg.name_label && window.CharacterBridge) {
        CharacterBridge._nameLabelConfig = cfg.name_label;
      }

      // Apply chat bubble config
      if (cfg.chat_bubble && window.CharacterBridge) {
        CharacterBridge._chatBubbleConfig = cfg.chat_bubble;
      }

      // Apply expression blend timing
      if (cfg.expression_blend && window.CharacterBridge) {
        CharacterBridge._blendConfig = cfg.expression_blend;
      }
    },

    /**
     * Helper to parse hex color strings ("0xrrggbb" or "#rrggbb") to integers.
     */
    parseHex(val) {
      if (typeof val === 'number') return val;
      if (typeof val === 'string') {
        return parseInt(val.replace(/^(0x|#)/, ''), 16);
      }
      return 0;
    }
  };

  // Auto-load on DOM ready
  // v1.58.0 [2026-06-11] — readyState guard (file now loads post-DOMContentLoaded
  // via the three_boot module chain; bare listener never fired in that case)
  function _autoLoad() {
    // Small delay to ensure CharModels and penthouse3D are initialized
    setTimeout(() => {
      PenthouseConfig.load().then(data => {
        if (data) {
          console.debug('[PenthouseConfig] Loaded:', Object.keys(data).join(', '));
          // Emit custom event so other scripts can react
          window.dispatchEvent(new CustomEvent('penthouse-config-loaded', { detail: data }));
        }
      });
    }, 500);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _autoLoad);
  } else {
    _autoLoad();
  }

  window.PenthouseConfig = PenthouseConfig;
})();
