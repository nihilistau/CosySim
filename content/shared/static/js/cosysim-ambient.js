/**
 * cosysim-ambient.js — Per-scene ambient audio manager
 * Uses Web Audio API oscillators + noise for procedural ambience (no audio files needed)
 */
(function () {
  'use strict';

  const SCENE_AMBIENTS = {
    bedroom:  { type: 'rain',          volume: 0.08, bpm: 0 },
    casino:   { type: 'crowd',         volume: 0.06, bpm: 120 },
    arena:    { type: 'crowd_intense', volume: 0.1,  bpm: 140 },
    tavern:   { type: 'tavern_noise',  volume: 0.07, bpm: 80 },
    lounge:   { type: 'jazz',          volume: 0.05, bpm: 100 },
    gallery:  { type: 'silence',       volume: 0.02, bpm: 0 },
    realm:    { type: 'wind',          volume: 0.06, bpm: 0 },
    neoncity: { type: 'city_hum',      volume: 0.07, bpm: 130 },
    phone:    { type: 'static',        volume: 0.04, bpm: 0 },
  };

  class AmbientAudioManager {
    constructor() {
      this.ctx = null;
      this.nodes = [];
      this.volume = 0.5;
      this.enabled = false;
      this.scene = document.body?.dataset?.scene || 'bedroom';
      this._initOnInteraction();
    }

    _initOnInteraction() {
      // Web Audio requires user interaction first
      const start = () => {
        if (!this.ctx) {
          this.ctx = new (window.AudioContext || window.webkitAudioContext)();
          this._startAmbient();
          document.removeEventListener('click', start);
          document.removeEventListener('keydown', start);
        }
      };
      document.addEventListener('click', start, { once: true });
      document.addEventListener('keydown', start, { once: true });
    }

    _startAmbient() {
      const config = SCENE_AMBIENTS[this.scene] || SCENE_AMBIENTS.bedroom;
      this.enabled = true;

      const gainNode = this.ctx.createGain();
      gainNode.gain.setValueAtTime(config.volume * this.volume, this.ctx.currentTime);
      gainNode.connect(this.ctx.destination);

      switch (config.type) {
        case 'rain':          this._generateRain(gainNode);    break;
        case 'static':        this._generateStatic(gainNode);  break;
        case 'wind':          this._generateWind(gainNode);    break;
        case 'city_hum':      this._generateCityHum(gainNode); break;
        case 'crowd':
        case 'crowd_intense': this._generateCrowd(gainNode, config.type === 'crowd_intense'); break;
        default:              this._generateLowHum(gainNode);  break;
      }

      this.nodes.push(gainNode);
    }

    _generateRain(dest) {
      // White noise filtered to sound like rain
      const bufferSize = this.ctx.sampleRate * 2;
      const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.loop = true;

      const filter = this.ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.frequency.value = 1200;
      filter.Q.value = 0.5;

      source.connect(filter);
      filter.connect(dest);
      source.start();
    }

    _generateStatic(dest) {
      const bufferSize = this.ctx.sampleRate;
      const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) data[i] = (Math.random() * 2 - 1) * 0.3;
      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.loop = true;
      source.connect(dest);
      source.start();
    }

    _generateWind(dest) {
      const bufferSize = this.ctx.sampleRate * 2;
      const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;
      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.loop = true;
      const filter = this.ctx.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.value = 400;
      source.connect(filter);
      filter.connect(dest);
      source.start();
    }

    _generateCityHum(dest) {
      [60, 120, 180].forEach((freq, i) => {
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        osc.type = 'sawtooth';
        osc.frequency.value = freq;
        gain.gain.value = 0.015 / (i + 1);
        osc.connect(gain);
        gain.connect(dest);
        osc.start();
      });
    }

    _generateLowHum(dest) {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 55;
      gain.gain.value = 0.03;
      osc.connect(gain);
      gain.connect(dest);
      osc.start();
    }

    _generateCrowd(dest, intense = false) {
      // Layered noise filtered to simulate crowd murmur
      [400, 800, 1600].forEach((freq) => {
        const bufferSize = this.ctx.sampleRate;
        const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;
        const source = this.ctx.createBufferSource();
        source.buffer = buffer;
        source.loop = true;
        const filter = this.ctx.createBiquadFilter();
        filter.type = 'bandpass';
        filter.frequency.value = freq;
        filter.Q.value = intense ? 2 : 1;
        const gain = this.ctx.createGain();
        gain.gain.value = intense ? 0.04 : 0.02;
        source.connect(filter);
        filter.connect(gain);
        gain.connect(dest);
        source.start();
      });
    }

    setVolume(vol) {
      this.volume = Math.max(0, Math.min(1, vol));
      this.nodes.forEach(n => {
        if (n.gain) n.gain.setValueAtTime(n.gain.value * this.volume, this.ctx?.currentTime || 0);
      });
    }

    toggle() {
      if (!this.ctx) return;
      if (this.ctx.state === 'suspended') {
        this.ctx.resume();
      } else {
        this.ctx.suspend();
      }
    }

    stop() {
      this.nodes.forEach(n => { try { n.disconnect(); } catch(e) {} });
      this.nodes = [];
      if (this.ctx) { this.ctx.close(); this.ctx = null; }
    }
  }

  window.ambientAudio = new AmbientAudioManager();

  // Wire to admin overlay controls if present
  window.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('cs-ambient-toggle');
    if (toggle) {
      toggle.addEventListener('change', () => window.ambientAudio.toggle());
    }
    const vol = document.getElementById('cs-ambient-volume');
    if (vol) {
      vol.addEventListener('input', (e) => window.ambientAudio.setVolume(parseFloat(e.target.value)));
    }
  });
})();
