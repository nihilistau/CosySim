/**
 * cs-component.js — Base component class for CosySim UI
 * =======================================================
 * Provides auto-cleanup for DOM and Socket.IO event listeners,
 * preventing the listener leaks that cause radio/phone bugs.
 *
 * Usage:
 *   class MyWidget extends CSComponent {
 *     init() {
 *       this.on(this.el, 'click', () => this.toggle());
 *       this.socketOn(socket, 'world_event', data => this.update(data));
 *     }
 *   }
 *
 * Exposed globally as window.CSComponent.
 */

'use strict';

class CSComponent {
  /**
   * @param {string|Element} el  CSS selector or DOM element.
   * @param {object} [options]   Arbitrary options hash for subclasses.
   */
  constructor(el, options = {}) {
    this.el = typeof el === 'string' ? document.querySelector(el) : el;
    this.options = options;
    /** @type {Array<{target: EventTarget, event: string, handler: Function, options?: object}>} */
    this._listeners = [];
    /** @type {Array<{socket: object, event: string, handler: Function}>} */
    this._socketListeners = [];
    this._destroyed = false;
    this.init();
  }

  /**
   * Subclasses override this to set up their DOM bindings.
   * Called automatically by the constructor.
   */
  init() {}

  /**
   * Register a DOM event listener with automatic cleanup.
   *
   * @param {EventTarget} target   Element or window/document.
   * @param {string}      event    Event name (e.g. 'click').
   * @param {Function}    handler  Callback.
   * @param {object}      [opts]   addEventListener options.
   * @returns {this}
   */
  on(target, event, handler, opts) {
    target.addEventListener(event, handler, opts);
    this._listeners.push({ target, event, handler, options: opts });
    return this;
  }

  /**
   * Register a Socket.IO event listener with automatic cleanup.
   *
   * @param {object}   socket   Socket.IO socket instance.
   * @param {string}   event    Event name.
   * @param {Function} handler  Callback.
   * @returns {this}
   */
  socketOn(socket, event, handler) {
    socket.on(event, handler);
    this._socketListeners.push({ socket, event, handler });
    return this;
  }

  /**
   * Remove a specific DOM listener registered via on().
   *
   * @param {EventTarget} target
   * @param {string}      event
   * @param {Function}    handler
   */
  off(target, event, handler) {
    target.removeEventListener(event, handler);
    this._listeners = this._listeners.filter(
      l => !(l.target === target && l.event === event && l.handler === handler)
    );
  }

  /**
   * Tear down all registered listeners (DOM + Socket.IO).
   * Safe to call multiple times.
   */
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this._listeners.forEach(({ target, event, handler, options }) =>
      target.removeEventListener(event, handler, options)
    );
    this._socketListeners.forEach(({ socket, event, handler }) =>
      socket.off(event, handler)
    );
    this._listeners = [];
    this._socketListeners = [];
  }

  /**
   * Query within this component's root element.
   *
   * @param {string} selector  CSS selector.
   * @returns {Element|null}
   */
  $(selector) {
    return this.el ? this.el.querySelector(selector) : null;
  }

  /**
   * Query all within this component's root element.
   *
   * @param {string} selector  CSS selector.
   * @returns {NodeList}
   */
  $$(selector) {
    return this.el ? this.el.querySelectorAll(selector) : [];
  }
}

window.CSComponent = CSComponent;
