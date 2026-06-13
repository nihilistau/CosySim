/* ──── Lab Break — Three.js 3D Laboratory Environment ──── */
(function () {
  'use strict';

  if (typeof THREE === 'undefined') {
    console.warn('[lab3D] Three.js not loaded — skipping 3D environment.');
    return;
  }

  // ──── Constants ────
  var ROOM_W = 14, ROOM_H = 5, ROOM_D = 10;
  var TILE_SIZE = 1;
  var PI = Math.PI, TAU = PI * 2;
  // v1.58.0 [2026-06-11] — r184 physically-correct lighting: legacy
  // intensities convert with ×π (applied to every light + runtime write).
  var LPI = Math.PI;

  // ──── State ────
  var alertLevel = 'normal';
  var agentPos = { x: 0, z: 0 };
  var clock = new THREE.Clock();
  var animatables = [];

  // ──── Renderer setup ────
  var canvas = document.getElementById('lab-canvas');
  if (!canvas) return;

  var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.shadowMap.enabled = false;
  renderer.toneMapping = THREE.LinearToneMapping;
  renderer.toneMappingExposure = 1.0;

  // ──── Scene & camera ────
  var scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e17);
  scene.fog = new THREE.Fog(0x0a0e17, 12, 28);

  var camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 50);
  camera.position.set(0, 2.8, 8.5);
  camera.lookAt(0, 1.5, -1);

  var cameraBasePos = camera.position.clone();
  var cameraBaseTarget = new THREE.Vector3(0, 1.5, -1);
  var cameraDriftTime = 0;

  // ──── Material library ────
  var mats = {
    wallWhite:   new THREE.MeshStandardMaterial({ color: 0xd8dde6, roughness: 0.85, metalness: 0.02 }),
    ceiling:     new THREE.MeshStandardMaterial({ color: 0xc8cdd6, roughness: 0.9, metalness: 0.01 }),
    floorWhite:  new THREE.MeshStandardMaterial({ color: 0xd0d4dc, roughness: 0.7, metalness: 0.05 }),
    floorGray:   new THREE.MeshStandardMaterial({ color: 0xa8acb4, roughness: 0.7, metalness: 0.05 }),
    steel:       new THREE.MeshStandardMaterial({ color: 0xb8bcc4, roughness: 0.15, metalness: 0.9 }),
    steelDark:   new THREE.MeshStandardMaterial({ color: 0x707478, roughness: 0.2, metalness: 0.85 }),
    tableSurf:   new THREE.MeshStandardMaterial({ color: 0xe0e4ea, roughness: 0.4, metalness: 0.3 }),
    glass:       new THREE.MeshStandardMaterial({ color: 0x88ccff, roughness: 0.05, metalness: 0.1, transparent: true, opacity: 0.25 }),
    glassFrame:  new THREE.MeshStandardMaterial({ color: 0x505860, roughness: 0.3, metalness: 0.7 }),
    cabinetBody: new THREE.MeshStandardMaterial({ color: 0xc0c4cc, roughness: 0.6, metalness: 0.15 }),
    cabinetDoor: new THREE.MeshStandardMaterial({ color: 0xd0d4dc, roughness: 0.5, metalness: 0.2 }),
    hazmat:      new THREE.MeshStandardMaterial({ color: 0xf0c020, roughness: 0.6, metalness: 0.1 }),
    hazmatBlack: new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.6, metalness: 0.1 }),
    monitorBody: new THREE.MeshStandardMaterial({ color: 0x2a2e34, roughness: 0.4, metalness: 0.5 }),
    screenOff:   new THREE.MeshStandardMaterial({ color: 0x112233, roughness: 0.3, metalness: 0.2 }),
    beakerGlass: new THREE.MeshStandardMaterial({ color: 0xddeeff, roughness: 0.05, metalness: 0.0, transparent: true, opacity: 0.35 }),
    liquid:      new THREE.MeshStandardMaterial({ color: 0x22ff88, roughness: 0.3, metalness: 0.0, transparent: true, opacity: 0.6 }),
    agentBody:   new THREE.MeshStandardMaterial({ color: 0x556688, roughness: 0.7, metalness: 0.1 }),
    agentHead:   new THREE.MeshStandardMaterial({ color: 0xe8d5b7, roughness: 0.8, metalness: 0.0 })
  };

  // ──── Geometry cache ────
  var geoCache = {
    box:      new THREE.BoxGeometry(1, 1, 1),
    cyl:      new THREE.CylinderGeometry(1, 1, 1, 16),
    cylOpen:  new THREE.CylinderGeometry(1, 1, 1, 16, 1, true),
    sphere:   new THREE.SphereGeometry(1, 12, 8),
    plane:    new THREE.PlaneGeometry(1, 1)
  };

  // ──── Helpers ────
  function makeBox(w, h, d, mat) {
    var m = new THREE.Mesh(geoCache.box, mat);
    m.scale.set(w, h, d);
    return m;
  }

  function makeCyl(r, h, mat, segs) {
    var g = segs ? new THREE.CylinderGeometry(r, r, h, segs) : geoCache.cyl;
    var m = new THREE.Mesh(g, mat);
    if (!segs) m.scale.set(r, h, r);
    return m;
  }

  function pos(obj, x, y, z) {
    obj.position.set(x, y, z);
    return obj;
  }

  // ──── Build room shell ────
  function buildRoom() {
    var hw = ROOM_W / 2, hd = ROOM_D / 2;

    // Floor — checker tile pattern via InstancedMesh
    var tileGeo = new THREE.PlaneGeometry(TILE_SIZE, TILE_SIZE);
    var tilesX = Math.ceil(ROOM_W / TILE_SIZE);
    var tilesZ = Math.ceil(ROOM_D / TILE_SIZE);
    var totalTiles = tilesX * tilesZ;
    var whiteTiles = new THREE.InstancedMesh(tileGeo, mats.floorWhite, Math.ceil(totalTiles / 2));
    var grayTiles  = new THREE.InstancedMesh(tileGeo, mats.floorGray, Math.ceil(totalTiles / 2));
    var whiteIdx = 0, grayIdx = 0;
    var tmpMat = new THREE.Matrix4();

    for (var ix = 0; ix < tilesX; ix++) {
      for (var iz = 0; iz < tilesZ; iz++) {
        var tx = -hw + TILE_SIZE / 2 + ix * TILE_SIZE;
        var tz = -hd + TILE_SIZE / 2 + iz * TILE_SIZE;
        tmpMat.makeRotationX(-PI / 2);
        tmpMat.setPosition(tx, 0.001, tz);
        if ((ix + iz) % 2 === 0) {
          whiteTiles.setMatrixAt(whiteIdx++, tmpMat);
        } else {
          grayTiles.setMatrixAt(grayIdx++, tmpMat);
        }
      }
    }
    whiteTiles.count = whiteIdx;
    grayTiles.count = grayIdx;
    whiteTiles.instanceMatrix.needsUpdate = true;
    grayTiles.instanceMatrix.needsUpdate = true;
    scene.add(whiteTiles, grayTiles);

    // Back wall
    var backWall = makeBox(ROOM_W, ROOM_H, 0.15, mats.wallWhite);
    pos(backWall, 0, ROOM_H / 2, -hd);
    scene.add(backWall);

    // Left wall
    var leftWall = makeBox(0.15, ROOM_H, ROOM_D, mats.wallWhite);
    pos(leftWall, -hw, ROOM_H / 2, 0);
    scene.add(leftWall);

    // Right wall
    var rightWall = makeBox(0.15, ROOM_H, ROOM_D, mats.wallWhite);
    pos(rightWall, hw, ROOM_H / 2, 0);
    scene.add(rightWall);

    // Ceiling
    var ceilPlane = makeBox(ROOM_W, 0.12, ROOM_D, mats.ceiling);
    pos(ceilPlane, 0, ROOM_H, 0);
    scene.add(ceilPlane);

    // Ceiling acoustic tile grid — subtle lines
    var tileLineMat = new THREE.LineBasicMaterial({ color: 0x999999, transparent: true, opacity: 0.3 });
    for (var ci = -hw + 1; ci < hw; ci += 1.2) {
      var pts = [new THREE.Vector3(ci, ROOM_H - 0.01, -hd), new THREE.Vector3(ci, ROOM_H - 0.01, hd)];
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), tileLineMat));
    }
    for (var cj = -hd + 1; cj < hd; cj += 1.2) {
      var pts2 = [new THREE.Vector3(-hw, ROOM_H - 0.01, cj), new THREE.Vector3(hw, ROOM_H - 0.01, cj)];
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts2), tileLineMat));
    }

    // Baseboard strip
    var baseMat = new THREE.MeshStandardMaterial({ color: 0x888c94, roughness: 0.5, metalness: 0.3 });
    var bbBack = makeBox(ROOM_W, 0.12, 0.06, baseMat);
    pos(bbBack, 0, 0.06, -hd + 0.08);
    scene.add(bbBack);
    var bbLeft = makeBox(0.06, 0.12, ROOM_D, baseMat);
    pos(bbLeft, -hw + 0.08, 0.06, 0);
    scene.add(bbLeft);
    var bbRight = makeBox(0.06, 0.12, ROOM_D, baseMat);
    pos(bbRight, hw - 0.08, 0.06, 0);
    scene.add(bbRight);
  }

  // ──── Observation window (one-way mirror) ────
  function buildObservationWindow() {
    var winW = 5, winH = 2.8;
    // Frame
    var frameTop = makeBox(winW + 0.3, 0.15, 0.2, mats.glassFrame);
    pos(frameTop, 0, 3.6, -ROOM_D / 2 + 0.15);
    scene.add(frameTop);
    var frameBot = makeBox(winW + 0.3, 0.15, 0.2, mats.glassFrame);
    pos(frameBot, 0, 0.9, -ROOM_D / 2 + 0.15);
    scene.add(frameBot);
    var frameL = makeBox(0.15, winH + 0.15, 0.2, mats.glassFrame);
    pos(frameL, -(winW / 2 + 0.08), 2.25, -ROOM_D / 2 + 0.15);
    scene.add(frameL);
    var frameR = makeBox(0.15, winH + 0.15, 0.2, mats.glassFrame);
    pos(frameR, (winW / 2 + 0.08), 2.25, -ROOM_D / 2 + 0.15);
    scene.add(frameR);
    // Glass pane
    var glassPaneMat = new THREE.MeshStandardMaterial({
      color: 0x99bbdd, roughness: 0.02, metalness: 0.15,
      transparent: true, opacity: 0.18, side: THREE.DoubleSide
    });
    var glassPane = makeBox(winW, winH, 0.02, glassPaneMat);
    pos(glassPane, 0, 2.25, -ROOM_D / 2 + 0.12);
    scene.add(glassPane);
  }

  // ──── Examination table ────
  function buildExamTable() {
    // Surface
    var surface = makeBox(2.4, 0.08, 1.0, mats.tableSurf);
    pos(surface, 0, 1.0, -1.0);
    scene.add(surface);
    // Steel edge trim
    var trim = makeBox(2.5, 0.04, 1.05, mats.steel);
    pos(trim, 0, 0.94, -1.0);
    scene.add(trim);
    // Legs (4)
    var legPositions = [[-1.0, -0.3], [1.0, -0.3], [-1.0, -1.7], [1.0, -1.7]];
    for (var i = 0; i < legPositions.length; i++) {
      var leg = makeCyl(0.04, 0.92, mats.steelDark, 8);
      pos(leg, legPositions[i][0], 0.46, legPositions[i][1]);
      scene.add(leg);
    }
    // Cross brace
    var brace = makeBox(2.0, 0.03, 0.03, mats.steelDark);
    pos(brace, 0, 0.3, -1.0);
    scene.add(brace);
  }

  // ──── Computer monitors ────
  var monitorScreens = [];
  function buildMonitors() {
    var positions = [
      { x: -5.5, y: 2.2, z: -4.5, ry: 0.3 },
      { x: -5.5, y: 3.2, z: -4.5, ry: 0.3 },
      { x: 5.2, y: 2.5, z: -3.0, ry: -0.4 }
    ];
    for (var i = 0; i < positions.length; i++) {
      var p = positions[i];
      // Body
      var body = makeBox(1.4, 0.9, 0.08, mats.monitorBody);
      pos(body, p.x, p.y, p.z);
      body.rotation.y = p.ry;
      scene.add(body);
      // Screen (emissive)
      var screenMat = new THREE.MeshStandardMaterial({
        color: 0x003322, emissive: 0x00aa66, emissiveIntensity: 0.6,
        roughness: 0.3, metalness: 0.2
      });
      var scr = makeBox(1.2, 0.7, 0.02, screenMat);
      pos(scr, p.x, p.y, p.z + 0.05);
      scr.rotation.y = p.ry;
      scene.add(scr);
      monitorScreens.push(screenMat);
      // Mount arm
      var arm = makeBox(0.06, 0.4, 0.06, mats.steelDark);
      pos(arm, p.x, p.y - 0.6, p.z - 0.02);
      scene.add(arm);
    }
  }

  // ──── Chemical equipment ────
  var bubbles = [];
  function buildChemEquipment() {
    var baseX = 3.5, baseZ = -2.0;
    // Lab bench
    var bench = makeBox(2.5, 0.06, 0.9, mats.steel);
    pos(bench, baseX, 1.0, baseZ);
    scene.add(bench);
    // Bench legs
    var blegPos = [[-1.0, 0], [1.0, 0]];
    for (var i = 0; i < blegPos.length; i++) {
      var bl = makeBox(0.05, 1.0, 0.8, mats.steelDark);
      pos(bl, baseX + blegPos[i][0], 0.5, baseZ + blegPos[i][1]);
      scene.add(bl);
    }

    // Beaker 1
    var beaker1 = makeCyl(0.15, 0.4, mats.beakerGlass, 12);
    pos(beaker1, baseX - 0.5, 1.24, baseZ);
    scene.add(beaker1);
    var liquid1 = makeCyl(0.13, 0.25, mats.liquid, 12);
    pos(liquid1, baseX - 0.5, 1.16, baseZ);
    scene.add(liquid1);

    // Beaker 2 (taller)
    var beaker2Mat = new THREE.MeshStandardMaterial({
      color: 0xddeeff, roughness: 0.05, transparent: true, opacity: 0.35
    });
    var beaker2 = makeCyl(0.1, 0.55, beaker2Mat, 12);
    pos(beaker2, baseX + 0.1, 1.31, baseZ - 0.15);
    scene.add(beaker2);
    var liquid2Mat = new THREE.MeshStandardMaterial({
      color: 0x4488ff, roughness: 0.3, transparent: true, opacity: 0.5
    });
    var liquid2 = makeCyl(0.08, 0.35, liquid2Mat, 12);
    pos(liquid2, baseX + 0.1, 1.21, baseZ - 0.15);
    scene.add(liquid2);

    // Test tube rack
    var rack = makeBox(0.6, 0.06, 0.15, mats.steelDark);
    pos(rack, baseX + 0.7, 1.06, baseZ + 0.1);
    scene.add(rack);
    for (var t = 0; t < 5; t++) {
      var tube = makeCyl(0.025, 0.3, mats.beakerGlass, 8);
      pos(tube, baseX + 0.5 + t * 0.1, 1.22, baseZ + 0.1);
      scene.add(tube);
    }

    // Bubbles in beaker 1
    var bubbleMat = new THREE.MeshStandardMaterial({
      color: 0xaaffcc, transparent: true, opacity: 0.5, emissive: 0x22ff88, emissiveIntensity: 0.3
    });
    for (var b = 0; b < 6; b++) {
      var bub = new THREE.Mesh(geoCache.sphere, bubbleMat);
      var sc = 0.015 + Math.random() * 0.02;
      bub.scale.set(sc, sc, sc);
      bub.position.set(
        baseX - 0.5 + (Math.random() - 0.5) * 0.15,
        1.08 + Math.random() * 0.2,
        baseZ + (Math.random() - 0.5) * 0.15
      );
      bub.userData.baseY = bub.position.y;
      bub.userData.speed = 0.15 + Math.random() * 0.25;
      bub.userData.phase = Math.random() * TAU;
      bub.userData.originX = bub.position.x;
      bub.userData.originZ = bub.position.z;
      scene.add(bub);
      bubbles.push(bub);
    }
  }

  // ──── Storage cabinets ────
  function buildCabinets() {
    // Left wall cabinets
    for (var row = 0; row < 2; row++) {
      for (var col = 0; col < 2; col++) {
        var cx = -ROOM_W / 2 + 0.45;
        var cy = 1.0 + row * 1.4;
        var cz = -2.0 + col * 1.6;
        var cab = makeBox(0.7, 1.2, 0.6, mats.cabinetBody);
        pos(cab, cx, cy, cz);
        scene.add(cab);
        // Door face
        var door = makeBox(0.62, 1.1, 0.02, mats.cabinetDoor);
        pos(door, cx + 0.36, cy, cz);
        scene.add(door);
        // Handle
        var handle = makeBox(0.04, 0.2, 0.04, mats.steel);
        pos(handle, cx + 0.38, cy + 0.15, cz + 0.15);
        scene.add(handle);
      }
    }
  }

  // ──── Hazmat caution stripes (on floor near door) ────
  function buildHazmatStripes() {
    var stripeCount = 6;
    for (var i = 0; i < stripeCount; i++) {
      var mat = (i % 2 === 0) ? mats.hazmat : mats.hazmatBlack;
      var stripe = makeBox(0.15, 0.005, 1.2, mat);
      pos(stripe, 5.5 - i * 0.16, 0.005, 3.5);
      scene.add(stripe);
    }
  }

  // ──── Door (back-right) ────
  function buildDoor() {
    var dx = ROOM_W / 2 - 0.08, dy = ROOM_H / 2 - 0.3, dz = 3.5;
    // Frame
    var frameL = makeBox(0.12, ROOM_H - 0.6, 0.2, mats.steelDark);
    pos(frameL, dx, dy, dz - 0.55);
    scene.add(frameL);
    var frameR = makeBox(0.12, ROOM_H - 0.6, 0.2, mats.steelDark);
    pos(frameR, dx, dy, dz + 0.55);
    scene.add(frameR);
    var frameTop = makeBox(0.12, 0.12, 1.3, mats.steelDark);
    pos(frameTop, dx, ROOM_H - 0.66, dz);
    scene.add(frameTop);
    // Door panel
    var doorPanel = makeBox(0.06, ROOM_H - 0.8, 1.0, mats.cabinetBody);
    pos(doorPanel, dx - 0.04, dy, dz);
    scene.add(doorPanel);
  }

  // ──── Lighting ────
  var fluorescentLights = [];
  var emergencyLight = null;
  var statusLights = [];

  function buildLighting() {
    // Ambient — low baseline
    var ambient = new THREE.AmbientLight(0x404860, 0.35 * LPI);
    scene.add(ambient);

    // Overhead fluorescent panels (2 rows of emissive planes + rect area approximation)
    var fluoPositions = [
      { x: -2.5, z: -2.0 },
      { x: 2.5, z: -2.0 },
      { x: 0, z: 2.0 }
    ];
    for (var i = 0; i < fluoPositions.length; i++) {
      var fp = fluoPositions[i];
      // Emissive panel (visual)
      var panelMat = new THREE.MeshStandardMaterial({
        color: 0xffffff, emissive: 0xeef4ff, emissiveIntensity: 1.5,
        roughness: 0.2, metalness: 0.0
      });
      var panel = makeBox(2.0, 0.04, 0.5, panelMat);
      pos(panel, fp.x, ROOM_H - 0.08, fp.z);
      scene.add(panel);
      // Housing rim
      var rim = makeBox(2.1, 0.06, 0.6, mats.steelDark);
      pos(rim, fp.x, ROOM_H - 0.06, fp.z);
      scene.add(rim);
      // Point light to cast illumination
      var pLight = new THREE.PointLight(0xeef4ff, 0.8 * LPI, 12, 1.5);
      pos(pLight, fp.x, ROOM_H - 0.2, fp.z);
      scene.add(pLight);
      fluorescentLights.push({ mat: panelMat, light: pLight, baseIntensity: 0.8 * LPI, baseMat: 1.5 });
    }

    // Emergency red light (slow orbit)
    emergencyLight = new THREE.PointLight(0xff2222, 0.08 * LPI, 10, 1.5);
    pos(emergencyLight, 4.0, 4.5, -3.0);
    scene.add(emergencyLight);
    // Visual red bulb
    var redBulbMat = new THREE.MeshStandardMaterial({
      color: 0xff0000, emissive: 0xff2222, emissiveIntensity: 0.4
    });
    var redBulb = new THREE.Mesh(geoCache.sphere, redBulbMat);
    redBulb.scale.set(0.08, 0.08, 0.08);
    emergencyLight.add(redBulb);
    emergencyLight.userData.bulbMat = redBulbMat;

    // Green status indicator lights
    var greenMat = new THREE.MeshStandardMaterial({
      color: 0x00ff66, emissive: 0x00ff44, emissiveIntensity: 1.0
    });
    var statusPositions = [
      { x: -6.8, y: 3.8, z: -1.0 },
      { x: -6.8, y: 3.8, z: 1.0 },
      { x: 6.8, y: 4.2, z: -2.0 }
    ];
    for (var s = 0; s < statusPositions.length; s++) {
      var sp = statusPositions[s];
      var ledMat = greenMat.clone();
      var led = new THREE.Mesh(geoCache.sphere, ledMat);
      led.scale.set(0.05, 0.05, 0.05);
      pos(led, sp.x, sp.y, sp.z);
      scene.add(led);
      statusLights.push({ mesh: led, mat: ledMat, phase: s * 2.1 });
    }

    // Blue equipment glow (near chem bench)
    var blueGlow = new THREE.PointLight(0x4488ff, 0.3 * LPI, 4, 2);
    pos(blueGlow, 3.5, 1.5, -2.0);
    scene.add(blueGlow);
  }

  // ──── Fog plane ────
  var fogPlane = null;
  function buildFog() {
    var fogMat = new THREE.MeshStandardMaterial({
      color: 0xccddee, transparent: true, opacity: 0.04,
      side: THREE.DoubleSide, depthWrite: false
    });
    fogPlane = makeBox(ROOM_W, 0.02, ROOM_D, fogMat);
    pos(fogPlane, 0, 0.3, 0);
    scene.add(fogPlane);
  }

  // ──── Agent avatar (simple 3D figure) ────
  var agentGroup = null;
  function buildAgent() {
    agentGroup = new THREE.Group();
    // Head
    var head = new THREE.Mesh(geoCache.sphere, mats.agentHead);
    head.scale.set(0.18, 0.2, 0.18);
    pos(head, 0, 1.65, 0);
    agentGroup.add(head);
    // Torso
    var torso = makeBox(0.35, 0.45, 0.2, mats.agentBody);
    pos(torso, 0, 1.3, 0);
    agentGroup.add(torso);
    // Arms
    var armL = makeBox(0.1, 0.4, 0.1, mats.agentHead);
    pos(armL, -0.25, 1.3, 0);
    agentGroup.add(armL);
    var armR = makeBox(0.1, 0.4, 0.1, mats.agentHead);
    pos(armR, 0.25, 1.3, 0);
    agentGroup.add(armR);
    // Legs
    var legL = makeBox(0.12, 0.5, 0.12, mats.steelDark);
    pos(legL, -0.1, 0.8, 0);
    agentGroup.add(legL);
    var legR = makeBox(0.12, 0.5, 0.12, mats.steelDark);
    pos(legR, 0.1, 0.8, 0);
    agentGroup.add(legR);
    // Feet
    var footL = makeBox(0.13, 0.06, 0.2, mats.steelDark);
    pos(footL, -0.1, 0.56, 0.04);
    agentGroup.add(footL);
    var footR = makeBox(0.13, 0.06, 0.2, mats.steelDark);
    pos(footR, 0.1, 0.56, 0.04);
    agentGroup.add(footR);

    agentGroup.position.set(0, 0, -0.5);
    scene.add(agentGroup);
  }

  // ──── Build everything ────
  buildRoom();
  buildObservationWindow();
  buildExamTable();
  buildMonitors();
  buildChemEquipment();
  buildCabinets();
  buildHazmatStripes();
  buildDoor();
  buildLighting();
  buildFog();
  buildAgent();

  // ──── Animation ────
  var monitorColorCycle = 0;
  var flickerTimer = 0;
  var nextFlicker = 2.0 + Math.random() * 4.0;

  function animate() {
    requestAnimationFrame(animate);
    var dt = clock.getDelta();
    var elapsed = clock.getElapsedTime();

    // ── Camera auto-drift ──
    cameraDriftTime += dt * 0.15;
    camera.position.x = cameraBasePos.x + Math.sin(cameraDriftTime * 0.7) * 0.3;
    camera.position.y = cameraBasePos.y + Math.sin(cameraDriftTime * 0.5) * 0.08;
    camera.position.z = cameraBasePos.z + Math.cos(cameraDriftTime * 0.4) * 0.15;
    var lookTarget = cameraBaseTarget.clone();
    lookTarget.x += Math.sin(cameraDriftTime * 0.3) * 0.15;
    lookTarget.y += Math.cos(cameraDriftTime * 0.6) * 0.05;
    camera.lookAt(lookTarget);

    // ── Fluorescent flicker ──
    flickerTimer += dt;
    if (flickerTimer > nextFlicker) {
      flickerTimer = 0;
      nextFlicker = 1.5 + Math.random() * 5.0;
      var targetIdx = Math.floor(Math.random() * fluorescentLights.length);
      var fl = fluorescentLights[targetIdx];
      fl.light.intensity = fl.baseIntensity * 0.3;
      fl.mat.emissiveIntensity = fl.baseMat * 0.2;
      setTimeout(function (fRef) {
        fRef.light.intensity = fRef.baseIntensity;
        fRef.mat.emissiveIntensity = fRef.baseMat;
      }, 80 + Math.random() * 120, fl);
    }

    // ── Monitor screen color cycling ──
    monitorColorCycle += dt * 0.4;
    for (var mi = 0; mi < monitorScreens.length; mi++) {
      var phase = monitorColorCycle + mi * 1.5;
      var r = 0;
      var g = 0.4 + Math.sin(phase) * 0.3;
      var b = 0.3 + Math.cos(phase * 0.7) * 0.3;
      monitorScreens[mi].emissive.setRGB(r, Math.max(0.1, g), Math.max(0.1, b));
      monitorScreens[mi].emissiveIntensity = 0.5 + Math.sin(phase * 2.0) * 0.15;
    }

    // ── Bubbles in beaker ──
    for (var bi = 0; bi < bubbles.length; bi++) {
      var bub = bubbles[bi];
      bub.position.y += bub.userData.speed * dt;
      bub.position.x = bub.userData.originX + Math.sin(elapsed * 2.0 + bub.userData.phase) * 0.02;
      bub.position.z = bub.userData.originZ + Math.cos(elapsed * 1.5 + bub.userData.phase) * 0.02;
      if (bub.position.y > bub.userData.baseY + 0.28) {
        bub.position.y = bub.userData.baseY;
        bub.position.x = bub.userData.originX + (Math.random() - 0.5) * 0.1;
        bub.position.z = bub.userData.originZ + (Math.random() - 0.5) * 0.1;
        var ns = 0.015 + Math.random() * 0.02;
        bub.scale.set(ns, ns, ns);
      }
    }

    // ── Emergency light rotation ──
    if (emergencyLight) {
      var eRadius = 3.0;
      var eSpeed = alertLevel === 'critical' ? 2.5 : (alertLevel === 'warning' ? 1.2 : 0.25);
      emergencyLight.position.x = 4.0 + Math.cos(elapsed * eSpeed) * eRadius;
      emergencyLight.position.z = -1.0 + Math.sin(elapsed * eSpeed) * eRadius;
    }

    // ── Status indicator blink ──
    for (var si = 0; si < statusLights.length; si++) {
      var sl = statusLights[si];
      var blinkVal = Math.sin(elapsed * 1.5 + sl.phase) * 0.5 + 0.5;
      sl.mat.emissiveIntensity = 0.3 + blinkVal * 0.7;
      sl.mesh.scale.setScalar(0.04 + blinkVal * 0.02);
    }

    // ── Fog drift ──
    if (fogPlane) {
      fogPlane.position.x = Math.sin(elapsed * 0.1) * 1.5;
      fogPlane.position.z = Math.cos(elapsed * 0.08) * 1.0;
      fogPlane.material.opacity = 0.025 + Math.sin(elapsed * 0.3) * 0.015;
    }

    // ── Agent position smoothing ──
    if (agentGroup) {
      agentGroup.position.x += (agentPos.x - agentGroup.position.x) * 0.03;
      agentGroup.position.z += (agentPos.z - agentGroup.position.z) * 0.03;
      // Subtle breathing
      agentGroup.children[1].position.y = 1.3 + Math.sin(elapsed * 2.0) * 0.01;
      agentGroup.children[0].position.y = 1.65 + Math.sin(elapsed * 2.0) * 0.01;
    }

    renderer.render(scene, camera);
  }

  // ──── Alert level control ────
  function setAlert(level) {
    alertLevel = level;
    switch (level) {
      case 'critical':
        emergencyLight.intensity = 1.5 * LPI;
        emergencyLight.color.set(0xff0000);
        emergencyLight.userData.bulbMat.emissiveIntensity = 2.0;
        scene.background.set(0x120808);
        scene.fog.color.set(0x120808);
        for (var i = 0; i < fluorescentLights.length; i++) {
          fluorescentLights[i].light.intensity = 0.3 * LPI;
          fluorescentLights[i].mat.emissiveIntensity = 0.4;
          fluorescentLights[i].mat.emissive.set(0xff4444);
        }
        for (var s = 0; s < statusLights.length; s++) {
          statusLights[s].mat.color.set(0xff0000);
          statusLights[s].mat.emissive.set(0xff0000);
        }
        break;
      case 'warning':
        emergencyLight.intensity = 0.6 * LPI;
        emergencyLight.color.set(0xff6600);
        emergencyLight.userData.bulbMat.emissiveIntensity = 1.0;
        scene.background.set(0x0e0c08);
        scene.fog.color.set(0x0e0c08);
        for (var j = 0; j < fluorescentLights.length; j++) {
          fluorescentLights[j].light.intensity = 0.5 * LPI;
          fluorescentLights[j].mat.emissiveIntensity = 0.8;
          fluorescentLights[j].mat.emissive.set(0xffcc88);
        }
        for (var s2 = 0; s2 < statusLights.length; s2++) {
          statusLights[s2].mat.color.set(0xffaa00);
          statusLights[s2].mat.emissive.set(0xffaa00);
        }
        break;
      default:
        emergencyLight.intensity = 0.08 * LPI;
        emergencyLight.color.set(0xff2222);
        emergencyLight.userData.bulbMat.emissiveIntensity = 0.4;
        scene.background.set(0x0a0e17);
        scene.fog.color.set(0x0a0e17);
        for (var k = 0; k < fluorescentLights.length; k++) {
          fluorescentLights[k].light.intensity = fluorescentLights[k].baseIntensity;
          fluorescentLights[k].mat.emissiveIntensity = fluorescentLights[k].baseMat;
          fluorescentLights[k].mat.emissive.set(0xeef4ff);
        }
        for (var s3 = 0; s3 < statusLights.length; s3++) {
          statusLights[s3].mat.color.set(0x00ff66);
          statusLights[s3].mat.emissive.set(0x00ff44);
        }
        break;
    }
  }

  // ──── Agent position control ────
  function setAgentPosition(x, z) {
    agentPos.x = THREE.MathUtils.clamp(x, -ROOM_W / 2 + 0.5, ROOM_W / 2 - 0.5);
    agentPos.z = THREE.MathUtils.clamp(z, -ROOM_D / 2 + 0.5, ROOM_D / 2 - 0.5);
  }

  // ──── Window resize ────
  function onResize() {
    var w = window.innerWidth, h = window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  window.addEventListener('resize', onResize);

  // ──── Public API ────
  window.lab3D = {
    setAlert: setAlert,
    setAgentPosition: setAgentPosition
  };

  // ──── Start render loop ────
  animate();

})();
