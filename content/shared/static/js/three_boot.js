/**
 * Three.js r184 Boot Module — global bridge + legacy script chain
 * ================================================================
 * Stage-1 migration shim (r128 CDN globals → vendored r184 ES modules).
 *
 * Imports the vendored three.js build + the addons CosySim uses, exposes
 * them on `window.THREE` (module namespaces are frozen, so a shallow clone
 * carries the addon classes), then loads the page's legacy classic scripts
 * SEQUENTIALLY so their global-THREE code runs exactly as before.
 *
 * Usage (scene template):
 *   {% block head_scripts %}
 *     {% include 'partials/three_importmap.html' %}
 *   {% endblock %}
 *   ...
 *   <script>window.__THREE_LEGACY_SCRIPTS__ = ['/static/penthouse_3d.js', ...];</script>
 *   <script type="module" src="/shared/js/three_boot.js"></script>
 *
 * Events:
 *   'three:ready'         — window.THREE is available (before legacy chain)
 *   'three:legacy-loaded' — every legacy script has executed
 *
 * Version: v1.58.0 [2026-06-11]
 * Author:  CosySim Team
 *
 * Change Log:
 *   v1.58.0 [2026-06-11] — Initial boot shim (penthouse + lab_break migration)
 *
 * CONNECTS: partials/three_importmap.html, penthouse.html, lab_break.html
 * EMITS: three:ready, three:legacy-loaded
 */
import * as THREE_NS from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

/* Module namespace objects are frozen — clone so addons can ride along the
   same global the r128 examples/js builds used to populate. */
const THREE = Object.assign({}, THREE_NS, {
  OrbitControls,
  GLTFLoader,
  RoomEnvironment,
  RoundedBoxGeometry,
});

window.THREE = THREE;
window.dispatchEvent(new CustomEvent('three:ready', {
  detail: { revision: THREE_NS.REVISION },
}));
console.info(`[three_boot] three.js r${THREE_NS.REVISION} ready (operation=boot)`);

/* ──── Ordered legacy script chain ────────────────────────────────────
   async=false: dynamically-inserted classic scripts download IN PARALLEL
   but execute in insertion order (HTML spec). Awaiting each onload
   serially was ~9× slower on the werkzeug dev server. */

const scripts = window.__THREE_LEGACY_SCRIPTS__ || [];
await Promise.all(scripts.map((src) => new Promise((resolve) => {
  const el = document.createElement('script');
  el.src = src;
  el.async = false;  // ordered execution, parallel fetch
  el.onload = resolve;
  el.onerror = () => {
    console.error(`[three_boot] FAILED to load ${src} (operation=legacy_chain)`);
    resolve(); // keep loading the rest — partial UI beats a blank page
  };
  document.head.appendChild(el);
})));

window.dispatchEvent(new CustomEvent('three:legacy-loaded', {
  detail: { count: scripts.length },
}));
if (scripts.length) {
  console.info(`[three_boot] ${scripts.length} legacy scripts loaded (operation=legacy_chain)`);
}
