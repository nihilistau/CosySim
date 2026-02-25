/**
 * CosySim Bedroom — Detailed Character Model System
 * Anatomically correct male/female humanoids with clothing, expressions, animation
 * Three.js r128 — procedural geometry only (no external models)
 */

/* global THREE */

// ═══════════════════════════════════════════════════════════════════════
//  PALETTES & LOOKUPS
// ═══════════════════════════════════════════════════════════════════════

const SKIN_TONES = {
    pale: 0xfde7d6, light: 0xffe0bd, fair: 0xf5c7a1,
    medium: 0xd4a574, tan: 0xc68642, brown: 0x8d5524, dark: 0x5c3310,
};
const HAIR_COLORS = {
    black: 0x1a1a1a, dark_brown: 0x3b2314, brown: 0x6b4423,
    auburn: 0x8b3a1a, red: 0xaa3322, blonde: 0xd4a853, platinum: 0xe8dcc8, pink: 0xff69b4,
};
const NIPPLE_COL = 0xc4756a;
const LIP_COL = 0xcc5566;

// Per-character default appearance (lowercase name → config)
const CHAR_LOOKS = {
    lola:    { gender: 'female', skin: 'fair',   hair: 'dark_brown', iris: 0x6b4423 },
    viktor:  { gender: 'male',   skin: 'medium', hair: 'black',      iris: 0x3a5a3a },
    aria:    { gender: 'female', skin: 'light',  hair: 'blonde',     iris: 0x4488cc },
    frankie: { gender: 'male',   skin: 'tan',    hair: 'brown',      iris: 0x5a4030 },
    mira:    { gender: 'female', skin: 'medium', hair: 'auburn',     iris: 0x654321 },
};

// ═══════════════════════════════════════════════════════════════════════
//  BODY DIMENSION TABLES  (all values in scene-units)
// ═══════════════════════════════════════════════════════════════════════

// Female  ≈ 1.65 u tall
const FD = {
    headR: 0.12, headY: 1.50,
    neckR: 0.045, neckH: 0.08,
    // torso LatheGeometry — [radius, localY], positioned at torsoY in world
    torsoY: 0.80,
    torsoProfile: [
        [0.001,0.00],[0.15,0.02],[0.16,0.06],[0.14,0.12],[0.095,0.22],
        [0.10,0.28],[0.13,0.36],[0.14,0.42],[0.15,0.46],[0.06,0.50],
        [0.045,0.55],[0.001,0.55],
    ],
    torsoScaleZ: 0.72,
    breastR: 0.072, breastLocalY: 0.38, breastSpc: 0.08, breastFwd: 0.09,
    nippleR: 0.014,
    shoulderY: 1.30, shoulderSpc: 0.15,
    hipY: 0.82, hipSpc: 0.09,
    uArmR: [0.040, 0.032], uArmH: 0.26,
    lArmR: [0.032, 0.025], lArmH: 0.24,
    handW: 0.03, handH: 0.05, handD: 0.02,
    thighR: [0.080, 0.055], thighH: 0.37,
    kneeR: 0.048,
    shinR: [0.050, 0.038], shinH: 0.39,
    footW: 0.06, footH: 0.06, footD: 0.15,
    buttR: 0.10, buttLocalY: 0.04,
};

// Male  ≈ 1.78 u tall
const MD = {
    headR: 0.13, headY: 1.62,
    neckR: 0.055, neckH: 0.10,
    torsoY: 0.88,
    torsoProfile: [
        [0.001,0.00],[0.13,0.02],[0.14,0.06],[0.13,0.12],[0.12,0.22],
        [0.14,0.28],[0.17,0.36],[0.18,0.42],[0.19,0.48],[0.07,0.52],
        [0.055,0.60],[0.001,0.60],
    ],
    torsoScaleZ: 0.68,
    pecLocalY: 0.40, pecR: 0.035,
    shoulderY: 1.42, shoulderSpc: 0.19,
    hipY: 0.90, hipSpc: 0.09,
    uArmR: [0.048, 0.038], uArmH: 0.28,
    lArmR: [0.038, 0.030], lArmH: 0.26,
    handW: 0.035, handH: 0.055, handD: 0.025,
    thighR: [0.090, 0.060], thighH: 0.42,
    kneeR: 0.052,
    shinR: [0.055, 0.042], shinH: 0.42,
    footW: 0.07, footH: 0.06, footD: 0.17,
    penisBaseR: 0.020, penisTipR: 0.015, penisH: 0.08, penisLocalY: -0.02,
    testicleR: 0.022,
    buttR: 0.09, buttLocalY: 0.04,
};

// ═══════════════════════════════════════════════════════════════════════
//  OUTFIT → CLOTHING LAYERS
// ═══════════════════════════════════════════════════════════════════════

const OUTFIT_MAP = {
    nothing:          [],
    lingerie:         ['bra','panties'],
    evening_dress:    ['dress'],
    silk_robe:        ['robe'],
    casual:           ['tshirt','shorts'],
    lace_bodysuit:    ['bodysuit'],
    leather:          ['top_leather','pants'],
    schoolgirl:       ['crop_top','skirt'],
    nurse:            ['dress_short'],
    topless:          ['shorts'],
    bottomless:       ['tshirt'],
    see_through:      ['bodysuit_sheer'],
    leather_harness:  ['harness'],
    stockings_only:   ['stockings'],
    collar_and_leash: ['collar'],
};

// Anatomy parts hidden by each clothing layer
const LAYER_HIDES = {
    bra:            ['nippleL','nippleR'],
    panties:        ['genitalia'],
    tshirt:         ['nippleL','nippleR'],
    top_leather:    ['nippleL','nippleR'],
    crop_top:       ['nippleL','nippleR'],
    shorts:         ['genitalia'],
    pants:          ['genitalia'],
    dress:          ['nippleL','nippleR','genitalia'],
    dress_short:    ['nippleL','nippleR','genitalia'],
    robe:           ['nippleL','nippleR','genitalia'],
    bodysuit:       ['nippleL','nippleR','genitalia'],
    bodysuit_sheer: [],
    skirt:          ['genitalia'],
    harness:        [],
    stockings:      [],
    collar:         [],
};

// Default colour themes per outfit
const OUTFIT_COLORS = {
    nothing:          null,
    lingerie:         { col: 0x1a0a0a, accent: 0xcc2244 },
    evening_dress:    { col: 0x220022, accent: 0x880066 },
    silk_robe:        { col: 0xd4c4e0, accent: 0xaa88cc },
    casual:           { col: 0x334455, accent: 0x556677 },
    lace_bodysuit:    { col: 0x1a1a1a, accent: 0x333333, alpha: 0.45 },
    leather:          { col: 0x1a1a1a, accent: 0x222222, shiny: true },
    schoolgirl:       { col: 0xffffff, accent: 0x223366 },
    nurse:            { col: 0xfafafa, accent: 0xcc2233 },
    topless:          { col: 0x334455, accent: 0x556677 },
    bottomless:       { col: 0x445566, accent: 0x556677 },
    see_through:      { col: 0x111111, accent: 0x222222, alpha: 0.25 },
    leather_harness:  { col: 0x1a1a1a, accent: 0x444444, shiny: true },
    stockings_only:   { col: 0x111111, accent: 0x222222 },
    collar_and_leash: { col: 0x331111, accent: 0x666666, shiny: true },
};

// ═══════════════════════════════════════════════════════════════════════
//  MATERIAL FACTORIES
// ═══════════════════════════════════════════════════════════════════════

function _skinMat(toneKey) {
    return new THREE.MeshStandardMaterial({
        color: SKIN_TONES[toneKey] || SKIN_TONES.fair,
        roughness: 0.65, metalness: 0.0,
    });
}
function _clothMat(color, opts) {
    const o = opts || {};
    return new THREE.MeshStandardMaterial({
        color,
        roughness: o.shiny ? 0.25 : 0.55,
        metalness: o.shiny ? 0.35 : 0.0,
        transparent: (o.alpha != null && o.alpha < 1),
        opacity: o.alpha != null ? o.alpha : 1.0,
        side: o.alpha != null ? THREE.DoubleSide : THREE.FrontSide,
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  BODY PART BUILDERS
// ═══════════════════════════════════════════════════════════════════════

function _buildTorso(d, skinMat) {
    const pts = d.torsoProfile.map(([r, y]) => new THREE.Vector2(r, y));
    const geo = new THREE.LatheGeometry(pts, 24);
    const mesh = new THREE.Mesh(geo, skinMat);
    mesh.position.y = d.torsoY;
    mesh.scale.z = d.torsoScaleZ;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
}

function _buildButt(d, skinMat) {
    const g = new THREE.Group();
    const geo = new THREE.SphereGeometry(d.buttR, 14, 10, 0, Math.PI * 2, Math.PI * 0.35, Math.PI * 0.45);
    [-1, 1].forEach(s => {
        const cheek = new THREE.Mesh(geo, skinMat);
        cheek.position.set(s * d.buttR * 0.55, d.torsoY + d.buttLocalY, -d.buttR * 0.5);
        cheek.castShadow = true;
        g.add(cheek);
    });
    return g;
}

function _buildBreasts(d, skinMat) {
    const g = new THREE.Group();
    const nipMat = new THREE.MeshStandardMaterial({ color: NIPPLE_COL, roughness: 0.6 });
    const brGeo = new THREE.SphereGeometry(d.breastR, 16, 12);
    [-1, 1].forEach((s, i) => {
        const br = new THREE.Mesh(brGeo, skinMat);
        br.position.set(s * d.breastSpc, d.torsoY + d.breastLocalY, d.breastFwd);
        br.scale.z = 0.85;
        br.castShadow = true;
        g.add(br);
        // Nipple
        const nipGeo = new THREE.SphereGeometry(d.nippleR, 8, 8);
        const nip = new THREE.Mesh(nipGeo, nipMat);
        nip.position.set(s * d.breastSpc, d.torsoY + d.breastLocalY, d.breastFwd + d.breastR * 0.82);
        nip.name = i === 0 ? 'nippleL' : 'nippleR';
        g.add(nip);
    });
    return g;
}

function _buildPecs(d, skinMat) {
    const g = new THREE.Group();
    const nipMat = new THREE.MeshStandardMaterial({ color: NIPPLE_COL, roughness: 0.6 });
    const pecGeo = new THREE.SphereGeometry(d.pecR, 10, 8, 0, Math.PI * 2, 0, Math.PI * 0.55);
    [-1, 1].forEach((s, i) => {
        const pec = new THREE.Mesh(pecGeo, skinMat);
        pec.position.set(s * 0.07, d.torsoY + d.pecLocalY, 0.10);
        pec.scale.set(1.2, 0.8, 0.6);
        g.add(pec);
        const nipGeo = new THREE.SphereGeometry(0.008, 6, 6);
        const nip = new THREE.Mesh(nipGeo, nipMat);
        nip.position.set(s * 0.07, d.torsoY + d.pecLocalY - 0.01, 0.12);
        nip.name = i === 0 ? 'nippleL' : 'nippleR';
        g.add(nip);
    });
    return g;
}

function _buildHead(d, skinMat, hairColor, irisColor, gender) {
    const g = new THREE.Group();
    g.position.y = d.headY;

    // Skull
    const head = new THREE.Mesh(new THREE.SphereGeometry(d.headR, 20, 16), skinMat);
    head.castShadow = true;
    g.add(head);

    // Ears
    const earGeo = new THREE.SphereGeometry(d.headR * 0.18, 8, 6, 0, Math.PI);
    [-1, 1].forEach(s => {
        const ear = new THREE.Mesh(earGeo, skinMat);
        ear.position.set(s * d.headR * 0.92, -0.01, 0);
        ear.rotation.y = s * Math.PI * 0.5;
        g.add(ear);
    });

    // Nose
    const noseGeo = new THREE.ConeGeometry(0.012, 0.025, 6);
    const nose = new THREE.Mesh(noseGeo, skinMat);
    nose.position.set(0, -0.01, d.headR * 0.92);
    nose.rotation.x = -Math.PI / 2;
    g.add(nose);

    // Lips
    const lipGeo = new THREE.TorusGeometry(0.018, 0.005, 6, 12, Math.PI);
    const lipMat = new THREE.MeshStandardMaterial({ color: LIP_COL, roughness: 0.5 });
    const lips = new THREE.Mesh(lipGeo, lipMat);
    lips.position.set(0, -0.038, d.headR * 0.88);
    lips.rotation.x = Math.PI * 0.1;
    lips.name = 'mouth';
    g.add(lips);

    // Eyes + iris + pupil
    const eyeWhiteMat = new THREE.MeshStandardMaterial({ color: 0xf5f5f5, roughness: 0.3 });
    const irisMat = new THREE.MeshStandardMaterial({ color: irisColor, roughness: 0.4 });
    const pupilMat = new THREE.MeshStandardMaterial({ color: 0x0a0a0a });
    const eyeGeo = new THREE.SphereGeometry(0.020, 10, 8);
    const irisGeo = new THREE.SphereGeometry(0.012, 8, 8);
    const pupilGeo = new THREE.SphereGeometry(0.006, 6, 6);
    const ez = d.headR * 0.86;
    [-1, 1].forEach((s, i) => {
        const ex = s * 0.038;
        const ey = 0.018;
        const eye = new THREE.Mesh(eyeGeo, eyeWhiteMat);
        eye.position.set(ex, ey, ez);
        g.add(eye);
        const iris = new THREE.Mesh(irisGeo, irisMat);
        iris.position.set(ex, ey, ez + 0.012);
        g.add(iris);
        const pupil = new THREE.Mesh(pupilGeo, pupilMat);
        pupil.position.set(ex, ey, ez + 0.018);
        pupil.name = i === 0 ? 'pupilL' : 'pupilR';
        g.add(pupil);
        // Catchlight
        const catchGeo = new THREE.SphereGeometry(0.003, 4, 4);
        const catchMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
        const catchLight = new THREE.Mesh(catchGeo, catchMat);
        catchLight.position.set(ex + 0.005, ey + 0.006, ez + 0.022);
        g.add(catchLight);
    });

    // Eyebrows
    const browGeo = new THREE.BoxGeometry(0.032, 0.005, 0.006);
    const browMat = new THREE.MeshStandardMaterial({ color: hairColor, roughness: 0.8 });
    [-1, 1].forEach((s, i) => {
        const brow = new THREE.Mesh(browGeo, browMat);
        brow.position.set(s * 0.038, 0.042, d.headR * 0.84);
        brow.rotation.z = s * 0.12;
        brow.name = i === 0 ? 'browL' : 'browR';
        g.add(brow);
    });

    // Eyelashes (female only — subtle dark strip above eyes)
    if (gender === 'female') {
        const lashGeo = new THREE.BoxGeometry(0.025, 0.003, 0.003);
        const lashMat = new THREE.MeshStandardMaterial({ color: 0x111111 });
        [-1, 1].forEach(s => {
            const lash = new THREE.Mesh(lashGeo, lashMat);
            lash.position.set(s * 0.038, 0.032, d.headR * 0.88);
            g.add(lash);
        });
    }

    // Hair
    const hairMat = new THREE.MeshStandardMaterial({ color: hairColor, roughness: 0.75 });
    // Skull cap
    const capGeo = new THREE.SphereGeometry(d.headR * 1.08, 16, 10, 0, Math.PI * 2, 0, Math.PI * 0.55);
    const cap = new THREE.Mesh(capGeo, hairMat);
    cap.position.y = d.headR * 0.10;
    cap.castShadow = true;
    g.add(cap);

    if (gender === 'female') {
        // Long hair — drapes down back and sides
        const drapeGeo = new THREE.BoxGeometry(0.24, 0.32, 0.07);
        const drape = new THREE.Mesh(drapeGeo, hairMat);
        drape.position.set(0, -0.12, -d.headR * 0.65);
        drape.castShadow = true;
        g.add(drape);
        // Side drapes
        [-1, 1].forEach(s => {
            const sideGeo = new THREE.BoxGeometry(0.06, 0.22, 0.05);
            const side = new THREE.Mesh(sideGeo, hairMat);
            side.position.set(s * d.headR * 0.85, -0.06, -d.headR * 0.2);
            g.add(side);
        });
    } else {
        // Short hair — just the cap, slightly thicker
        const crop = new THREE.Mesh(
            new THREE.SphereGeometry(d.headR * 1.06, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.48),
            hairMat
        );
        crop.position.y = d.headR * 0.12;
        g.add(crop);
    }

    return g;
}

function _buildArm(d, skinMat, side) {
    const g = new THREE.Group();
    // Position at shoulder
    g.position.set(side * d.shoulderSpc, d.shoulderY, 0);
    g.rotation.z = side * 0.12; // slight outward angle

    // Shoulder joint
    const sjGeo = new THREE.SphereGeometry(d.uArmR[0] * 1.15, 10, 8);
    g.add(new THREE.Mesh(sjGeo, skinMat));

    // Upper arm
    const uGeo = new THREE.CylinderGeometry(d.uArmR[0], d.uArmR[1], d.uArmH, 14);
    const uArm = new THREE.Mesh(uGeo, skinMat);
    uArm.position.y = -d.uArmH / 2;
    uArm.castShadow = true;
    g.add(uArm);

    // Elbow
    const eGeo = new THREE.SphereGeometry(d.lArmR[0] * 1.05, 8, 6);
    const elbow = new THREE.Mesh(eGeo, skinMat);
    elbow.position.y = -d.uArmH;
    g.add(elbow);

    // Lower arm
    const lGeo = new THREE.CylinderGeometry(d.lArmR[0], d.lArmR[1], d.lArmH, 12);
    const lArm = new THREE.Mesh(lGeo, skinMat);
    lArm.position.y = -d.uArmH - d.lArmH / 2;
    lArm.castShadow = true;
    g.add(lArm);

    // Hand
    const hGeo = new THREE.BoxGeometry(d.handW, d.handH, d.handD);
    const hand = new THREE.Mesh(hGeo, skinMat);
    hand.position.y = -d.uArmH - d.lArmH - d.handH / 2;
    g.add(hand);

    return g;
}

function _buildLeg(d, skinMat, side) {
    const g = new THREE.Group();
    g.position.set(side * d.hipSpc, d.hipY, 0);

    // Hip joint
    const hjGeo = new THREE.SphereGeometry(d.thighR[0] * 1.1, 10, 8);
    g.add(new THREE.Mesh(hjGeo, skinMat));

    // Thigh
    const tGeo = new THREE.CylinderGeometry(d.thighR[0], d.thighR[1], d.thighH, 16);
    const thigh = new THREE.Mesh(tGeo, skinMat);
    thigh.position.y = -d.thighH / 2;
    thigh.castShadow = true;
    g.add(thigh);

    // Knee
    const kGeo = new THREE.SphereGeometry(d.kneeR, 10, 8);
    const knee = new THREE.Mesh(kGeo, skinMat);
    knee.position.y = -d.thighH;
    g.add(knee);

    // Shin
    const sGeo = new THREE.CylinderGeometry(d.shinR[0], d.shinR[1], d.shinH, 14);
    const shin = new THREE.Mesh(sGeo, skinMat);
    shin.position.y = -d.thighH - d.shinH / 2;
    shin.castShadow = true;
    g.add(shin);

    // Foot
    const fGeo = new THREE.BoxGeometry(d.footW, d.footH, d.footD);
    const foot = new THREE.Mesh(fGeo, skinMat);
    foot.position.set(0, -(d.thighH + d.shinH + d.footH / 2), d.footD * 0.15);
    foot.castShadow = true;
    g.add(foot);

    return g;
}

function _buildFemaleAnatomy(d, skinMat) {
    const g = new THREE.Group();
    g.name = 'genitalia';
    // Vulva — subtle mound at groin
    const mat = skinMat.clone();
    mat.color = new THREE.Color(NIPPLE_COL).lerp(new THREE.Color(SKIN_TONES.fair), 0.6);
    const moundGeo = new THREE.SphereGeometry(0.035, 10, 8, 0, Math.PI * 2, 0, Math.PI * 0.6);
    const mound = new THREE.Mesh(moundGeo, mat);
    mound.position.set(0, d.torsoY - 0.01, 0.06);
    mound.scale.set(0.7, 1.0, 0.5);
    g.add(mound);
    // Slit line
    const slitGeo = new THREE.BoxGeometry(0.003, 0.04, 0.005);
    const slitMat = new THREE.MeshStandardMaterial({ color: 0x9a5a5a, roughness: 0.5 });
    const slit = new THREE.Mesh(slitGeo, slitMat);
    slit.position.set(0, d.torsoY - 0.02, 0.075);
    g.add(slit);
    return g;
}

function _buildMaleAnatomy(d, skinMat) {
    const g = new THREE.Group();
    g.name = 'genitalia';
    const gMat = skinMat.clone();
    gMat.color = new THREE.Color(SKIN_TONES.fair).lerp(new THREE.Color(NIPPLE_COL), 0.25);
    // Shaft
    const shaftGeo = new THREE.CylinderGeometry(d.penisBaseR, d.penisTipR, d.penisH, 10);
    const shaft = new THREE.Mesh(shaftGeo, gMat);
    shaft.position.set(0, d.torsoY + d.penisLocalY, 0.06);
    shaft.rotation.x = Math.PI * 0.15;
    shaft.castShadow = true;
    g.add(shaft);
    // Glans
    const glansGeo = new THREE.SphereGeometry(d.penisTipR * 1.25, 8, 8);
    const glansMat = gMat.clone();
    glansMat.color = new THREE.Color(NIPPLE_COL);
    const glans = new THREE.Mesh(glansGeo, glansMat);
    glans.position.set(0, d.torsoY + d.penisLocalY - d.penisH * 0.48, 0.075);
    g.add(glans);
    // Testicles
    const tGeo = new THREE.SphereGeometry(d.testicleR, 8, 8);
    [-1, 1].forEach(s => {
        const t = new THREE.Mesh(tGeo, gMat);
        t.position.set(s * 0.018, d.torsoY + d.penisLocalY - 0.01, 0.03);
        g.add(t);
    });
    return g;
}

// ═══════════════════════════════════════════════════════════════════════
//  CLOTHING LAYER BUILDERS
// ═══════════════════════════════════════════════════════════════════════

function _buildAllClothing(gender, charColor) {
    const d = gender === 'male' ? MD : FD;
    const layers = {};

    // We build every possible layer; all start hidden
    // The outfit system shows/hides them

    const _mat = (outfit) => {
        const oc = OUTFIT_COLORS[outfit] || { col: 0x333333 };
        return _clothMat(oc.col, oc);
    };

    // ── Bra (female only) ────────────────────────────────────
    if (gender === 'female') {
        const braG = new THREE.Group();
        const braMat = _clothMat(0x1a0a0a, { alpha: 0.92 });
        const cupGeo = new THREE.SphereGeometry(d.breastR * 1.12, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.58);
        [-1, 1].forEach(s => {
            const cup = new THREE.Mesh(cupGeo, braMat);
            cup.position.set(s * d.breastSpc, d.torsoY + d.breastLocalY, d.breastFwd * 0.9);
            cup.scale.z = 0.85;
            braG.add(cup);
        });
        // Band
        const bandGeo = new THREE.TorusGeometry(0.135, 0.006, 6, 24);
        const band = new THREE.Mesh(bandGeo, braMat);
        band.position.y = d.torsoY + d.breastLocalY - 0.04;
        band.rotation.x = Math.PI / 2;
        band.scale.z = d.torsoScaleZ;
        braG.add(band);
        // Straps
        [-1, 1].forEach(s => {
            const strapGeo = new THREE.CylinderGeometry(0.004, 0.004, 0.18, 6);
            const strap = new THREE.Mesh(strapGeo, braMat);
            strap.position.set(s * d.breastSpc, d.torsoY + d.breastLocalY + 0.09, d.breastFwd * 0.45);
            strap.rotation.z = s * 0.12;
            braG.add(strap);
        });
        braG.visible = false;
        layers.bra = braG;
    }

    // ── Panties / briefs ──────────────────────────────────────
    const pantiesG = new THREE.Group();
    const pantiesMat = _clothMat(0x1a0a0a);
    // Front panel
    const pfGeo = new THREE.PlaneGeometry(0.16, 0.10);
    const pf = new THREE.Mesh(pfGeo, pantiesMat);
    pf.position.set(0, d.torsoY + 0.03, (gender === 'female' ? 0.09 : 0.08));
    pantiesG.add(pf);
    // Back panel
    const pbGeo = new THREE.PlaneGeometry(0.16, 0.10);
    const pb = new THREE.Mesh(pbGeo, pantiesMat);
    pb.position.set(0, d.torsoY + 0.03, -d.buttR * 0.45);
    pb.rotation.y = Math.PI;
    pantiesG.add(pb);
    // Waistband
    const wbGeo = new THREE.TorusGeometry(0.14, 0.006, 6, 24);
    const wb = new THREE.Mesh(wbGeo, pantiesMat);
    wb.position.y = d.torsoY + 0.07;
    wb.rotation.x = Math.PI / 2;
    wb.scale.z = d.torsoScaleZ;
    pantiesG.add(wb);
    pantiesG.visible = false;
    layers.panties = pantiesG;

    // ── T-shirt / Top ──────────────────────────────────────────
    const tshirtG = new THREE.Group();
    const tshirtMat = _clothMat(0x334455);
    // Main body cover — slightly larger torso
    const shirtPts = d.torsoProfile.map(([r, y]) => new THREE.Vector2(r * 1.08, y));
    // Clip to waist→shoulders (skip bottom hip and top neck)
    const shirtPtsClipped = shirtPts.slice(3, shirtPts.length - 2);
    if (shirtPtsClipped.length > 2) {
        const shirtGeo = new THREE.LatheGeometry(shirtPtsClipped, 20);
        const shirtMesh = new THREE.Mesh(shirtGeo, tshirtMat);
        shirtMesh.position.y = d.torsoY;
        shirtMesh.scale.z = d.torsoScaleZ;
        tshirtG.add(shirtMesh);
    }
    // Sleeves (short cylinders at shoulders)
    [-1, 1].forEach(s => {
        const sleeveGeo = new THREE.CylinderGeometry(d.uArmR[0] * 1.5, d.uArmR[0] * 1.35, d.uArmH * 0.45, 10);
        const sleeve = new THREE.Mesh(sleeveGeo, tshirtMat);
        sleeve.position.set(s * d.shoulderSpc, d.shoulderY - d.uArmH * 0.22, 0);
        sleeve.rotation.z = s * 0.12;
        tshirtG.add(sleeve);
    });
    tshirtG.visible = false;
    layers.tshirt = tshirtG;

    // ── Leather top (same shape, different material) ──────────
    const ltG = tshirtG.clone();
    ltG.traverse(c => { if (c.isMesh) c.material = _clothMat(0x1a1a1a, { shiny: true }); });
    ltG.visible = false;
    layers.top_leather = ltG;

    // ── Crop top ──────────────────────────────────────────────
    const cropG = new THREE.Group();
    const cropMat = _clothMat(0xffffff);
    // Just covers chest area
    const cropPts = d.torsoProfile.map(([r, y]) => new THREE.Vector2(r * 1.06, y));
    const cropClip = cropPts.slice(5, cropPts.length - 2);
    if (cropClip.length > 2) {
        const cropGeo = new THREE.LatheGeometry(cropClip, 18);
        const cropMesh = new THREE.Mesh(cropGeo, cropMat);
        cropMesh.position.y = d.torsoY;
        cropMesh.scale.z = d.torsoScaleZ;
        cropG.add(cropMesh);
    }
    cropG.visible = false;
    layers.crop_top = cropG;

    // ── Shorts ────────────────────────────────────────────────
    const shortsG = new THREE.Group();
    const shortsMat = _clothMat(0x334455);
    [-1, 1].forEach(s => {
        const sGeo = new THREE.CylinderGeometry(d.thighR[0] * 1.15, d.thighR[0] * 1.1, d.thighH * 0.5, 14);
        const short = new THREE.Mesh(sGeo, shortsMat);
        short.position.set(s * d.hipSpc, d.hipY - d.thighH * 0.25, 0);
        shortsG.add(short);
    });
    // Crotch bridge
    const cbGeo = new THREE.BoxGeometry(d.hipSpc * 2.2, d.thighH * 0.15, d.thighR[0] * 1.8);
    const cb = new THREE.Mesh(cbGeo, shortsMat);
    cb.position.set(0, d.hipY - 0.02, 0);
    shortsG.add(cb);
    shortsG.visible = false;
    layers.shorts = shortsG;

    // ── Pants (full length legs) ──────────────────────────────
    const pantsG = new THREE.Group();
    const pantsMat = _clothMat(0x1a1a1a, { shiny: true });
    [-1, 1].forEach(s => {
        const tGeo = new THREE.CylinderGeometry(d.thighR[0] * 1.12, d.shinR[0] * 1.15, d.thighH + d.shinH * 0.7, 14);
        const pant = new THREE.Mesh(tGeo, pantsMat);
        pant.position.set(s * d.hipSpc, d.hipY - (d.thighH + d.shinH * 0.7) / 2, 0);
        pantsG.add(pant);
    });
    const pcbGeo = new THREE.BoxGeometry(d.hipSpc * 2.2, d.thighH * 0.15, d.thighR[0] * 1.8);
    const pcb = new THREE.Mesh(pcbGeo, pantsMat);
    pcb.position.set(0, d.hipY - 0.02, 0);
    pantsG.add(pcb);
    pantsG.visible = false;
    layers.pants = pantsG;

    // ── Dress (full — shoulders to knees) ─────────────────────
    const dressG = new THREE.Group();
    const dressMat = _clothMat(0x220022);
    const dressGeo = new THREE.CylinderGeometry(
        d.torsoProfile[8][0] * 1.1,  // shoulder width
        0.22,                          // flared at knee
        (d.shoulderY - 0.45),          // length shoulder→knee
        20, 1, true
    );
    const dressMesh = new THREE.Mesh(dressGeo, dressMat);
    dressMesh.position.y = d.shoulderY - (d.shoulderY - 0.45) / 2;
    dressMesh.scale.z = d.torsoScaleZ * 1.1;
    dressMesh.castShadow = true;
    dressG.add(dressMesh);
    dressG.visible = false;
    layers.dress = dressG;

    // ── Short dress (nurse) ───────────────────────────────────
    const sdG = new THREE.Group();
    const sdMat = _clothMat(0xfafafa);
    const sdGeo = new THREE.CylinderGeometry(
        d.torsoProfile[8][0] * 1.1,
        0.18,
        (d.shoulderY - d.hipY + 0.10),
        18, 1, true
    );
    const sdMesh = new THREE.Mesh(sdGeo, sdMat);
    sdMesh.position.y = d.shoulderY - (d.shoulderY - d.hipY + 0.10) / 2;
    sdMesh.scale.z = d.torsoScaleZ * 1.1;
    sdG.add(sdMesh);
    // Red cross accent
    const crossVGeo = new THREE.BoxGeometry(0.01, 0.06, 0.005);
    const crossHGeo = new THREE.BoxGeometry(0.06, 0.01, 0.005);
    const crossMat = new THREE.MeshStandardMaterial({ color: 0xcc2233 });
    const cv = new THREE.Mesh(crossVGeo, crossMat);
    cv.position.set(0, d.shoulderY - 0.15, 0.16);
    sdG.add(cv);
    const ch = new THREE.Mesh(crossHGeo, crossMat);
    ch.position.set(0, d.shoulderY - 0.15, 0.16);
    sdG.add(ch);
    sdG.visible = false;
    layers.dress_short = sdG;

    // ── Skirt ─────────────────────────────────────────────────
    const skirtG = new THREE.Group();
    const skirtMat = _clothMat(0x223366);
    const skirtGeo = new THREE.CylinderGeometry(0.12, 0.20, 0.30, 18, 1, true);
    const skirtMesh = new THREE.Mesh(skirtGeo, skirtMat);
    skirtMesh.position.y = d.torsoY + 0.20;
    skirtMesh.scale.z = d.torsoScaleZ * 1.1;
    skirtMesh.castShadow = true;
    skirtG.add(skirtMesh);
    skirtG.visible = false;
    layers.skirt = skirtG;

    // ── Robe ──────────────────────────────────────────────────
    const robeG = new THREE.Group();
    const robeMat = _clothMat(0xd4c4e0, { alpha: 0.85 });
    const robeGeo = new THREE.CylinderGeometry(
        d.torsoProfile[8][0] * 1.2,
        0.25,
        (d.shoulderY - 0.20),
        20, 1, true
    );
    const robeMesh = new THREE.Mesh(robeGeo, robeMat);
    robeMesh.position.y = d.shoulderY - (d.shoulderY - 0.20) / 2;
    robeMesh.scale.z = d.torsoScaleZ * 1.15;
    robeG.add(robeMesh);
    robeG.visible = false;
    layers.robe = robeG;

    // ── Bodysuit (opaque) ─────────────────────────────────────
    const bsG = new THREE.Group();
    const bsMat = _clothMat(0x1a1a1a);
    // Torso shell
    const bsPts = d.torsoProfile.map(([r, y]) => new THREE.Vector2(r * 1.05, y));
    const bsGeo = new THREE.LatheGeometry(bsPts, 20);
    const bsMesh = new THREE.Mesh(bsGeo, bsMat);
    bsMesh.position.y = d.torsoY;
    bsMesh.scale.z = d.torsoScaleZ;
    bsG.add(bsMesh);
    // Thigh covers
    [-1, 1].forEach(s => {
        const tGeo = new THREE.CylinderGeometry(d.thighR[0] * 1.08, d.thighR[0] * 1.05, d.thighH * 0.6, 12);
        const t = new THREE.Mesh(tGeo, bsMat);
        t.position.set(s * d.hipSpc, d.hipY - d.thighH * 0.3, 0);
        bsG.add(t);
    });
    bsG.visible = false;
    layers.bodysuit = bsG;

    // ── Bodysuit (sheer) ──────────────────────────────────────
    const bssG = bsG.clone();
    const bssMat = _clothMat(0x111111, { alpha: 0.25 });
    bssG.traverse(c => { if (c.isMesh) c.material = bssMat; });
    bssG.visible = false;
    layers.bodysuit_sheer = bssG;

    // ── Stockings ─────────────────────────────────────────────
    const stockG = new THREE.Group();
    const stockMat = _clothMat(0x111111, { alpha: 0.85 });
    [-1, 1].forEach(s => {
        const sGeo = new THREE.CylinderGeometry(d.shinR[0] * 1.12, d.shinR[1] * 1.15, d.shinH + d.thighH * 0.3, 12);
        const stocking = new THREE.Mesh(sGeo, stockMat);
        stocking.position.set(s * d.hipSpc, d.hipY - d.thighH * 0.7 - d.shinH * 0.3, 0);
        stockG.add(stocking);
    });
    stockG.visible = false;
    layers.stockings = stockG;

    // ── Harness (straps across chest) ─────────────────────────
    const harnG = new THREE.Group();
    const harnMat = _clothMat(0x1a1a1a, { shiny: true });
    const strapR = 0.005;
    // Chest ring
    const ringGeo = new THREE.TorusGeometry(0.13, strapR, 6, 20);
    const ring = new THREE.Mesh(ringGeo, harnMat);
    ring.position.y = d.torsoY + (gender === 'female' ? d.breastLocalY : d.pecLocalY) - 0.04;
    ring.rotation.x = Math.PI / 2;
    ring.scale.z = d.torsoScaleZ;
    harnG.add(ring);
    // Shoulder straps
    [-1, 1].forEach(s => {
        const strapGeo = new THREE.CylinderGeometry(strapR, strapR, 0.30, 6);
        const strap = new THREE.Mesh(strapGeo, harnMat);
        strap.position.set(s * 0.08, d.shoulderY - 0.08, 0.05);
        strap.rotation.z = s * 0.15;
        harnG.add(strap);
    });
    // Center vertical strap
    const cvStrap = new THREE.Mesh(new THREE.CylinderGeometry(strapR, strapR, 0.30, 6), harnMat);
    cvStrap.position.set(0, d.torsoY + 0.30, 0.12);
    harnG.add(cvStrap);
    harnG.visible = false;
    layers.harness = harnG;

    // ── Collar ────────────────────────────────────────────────
    const collarG = new THREE.Group();
    const collarMat = _clothMat(0x331111, { shiny: true });
    const collarGeo = new THREE.TorusGeometry(d.neckR * 1.4, 0.008, 8, 16);
    const collarMesh = new THREE.Mesh(collarGeo, collarMat);
    collarMesh.position.y = d.torsoY + d.torsoProfile[d.torsoProfile.length - 2][1] - 0.03;
    collarMesh.rotation.x = Math.PI / 2;
    collarG.add(collarMesh);
    // Ring / buckle
    const buckleGeo = new THREE.TorusGeometry(0.012, 0.003, 6, 8);
    const buckleMat = new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.8, roughness: 0.2 });
    const buckle = new THREE.Mesh(buckleGeo, buckleMat);
    buckle.position.set(0, collarMesh.position.y, d.neckR * 1.4 + 0.01);
    collarG.add(buckle);
    collarG.visible = false;
    layers.collar = collarG;

    return layers;
}

// ═══════════════════════════════════════════════════════════════════════
//  MAIN CREATE FUNCTION
// ═══════════════════════════════════════════════════════════════════════

function createDetailedCharacter(opts) {
    const name = (opts.name || '').toLowerCase();
    const look = CHAR_LOOKS[name] || {};
    const gender = opts.gender || look.gender || 'female';
    const skinKey = opts.skin || look.skin || 'fair';
    const hairKey = opts.hair || look.hair || 'dark_brown';
    const irisCol = look.iris || 0x6b4423;
    const charColor = opts.charColor || '#ff6b9d';

    const d = gender === 'male' ? MD : FD;
    const skinMat = _skinMat(skinKey);
    const hairCol = HAIR_COLORS[hairKey] || 0x3b2314;

    const group = new THREE.Group();

    // ── Body ────────────────────────────────────
    const bodyGroup = new THREE.Group();
    bodyGroup.add(_buildTorso(d, skinMat));
    bodyGroup.add(_buildButt(d, skinMat));

    if (gender === 'female') {
        const breastsG = _buildBreasts(d, skinMat);
        bodyGroup.add(breastsG);
    } else {
        bodyGroup.add(_buildPecs(d, skinMat));
    }

    // Head
    const headData = _buildHead(d, skinMat, hairCol, irisCol, gender);
    bodyGroup.add(headData.group);

    // Arms
    const armL = _buildArm(d, skinMat, -1);
    const armR = _buildArm(d, skinMat, 1);
    bodyGroup.add(armL);
    bodyGroup.add(armR);

    // Legs
    const legL = _buildLeg(d, skinMat, -1);
    const legR = _buildLeg(d, skinMat, 1);
    bodyGroup.add(legL);
    bodyGroup.add(legR);

    // Genitalia
    const anatG = gender === 'female'
        ? _buildFemaleAnatomy(d, skinMat)
        : _buildMaleAnatomy(d, skinMat);
    bodyGroup.add(anatG);

    group.add(bodyGroup);

    // ── Clothing ────────────────────────────────
    const clothingGroup = new THREE.Group();
    const clothingLayers = _buildAllClothing(gender, charColor);
    for (const [layerName, layerGroup] of Object.entries(clothingLayers)) {
        clothingGroup.add(layerGroup);
    }
    group.add(clothingGroup);

    // ── Glow ring at feet ───────────────────────
    const ringCol = new THREE.Color(charColor);
    const ringGeo = new THREE.RingGeometry(0.40, 0.55, 32);
    const ringMat = new THREE.MeshBasicMaterial({
        color: ringCol, transparent: true, opacity: 0.3, side: THREE.DoubleSide,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.02;
    group.add(ring);

    // ── Name label ──────────────────────────────
    const labelY = (gender === 'male' ? 1.90 : 1.78);
    const label = _makeNameLabel(opts.name || 'Character', charColor);
    label.position.y = labelY;
    group.add(label);

    // ── Build anatomy index for clothing hide/show ──
    const anatomyParts = {};
    bodyGroup.traverse(child => {
        if (child.name === 'nippleL' || child.name === 'nippleR' || child.name === 'genitalia') {
            anatomyParts[child.name] = child;
        }
    });
    // Also tag the genitalia group's children
    if (anatG.name === 'genitalia') {
        anatomyParts.genitalia = anatG;
    }

    return {
        group,
        bodyGroup,
        clothingGroup,
        clothingLayers,
        anatomyParts,
        headData,
        ring,
        armL, armR,
        legL, legR,
        gender,
        dims: d,
        charColor,
        bubbleY: labelY + 0.35,
        currentOutfit: null,
    };
}

// ═══════════════════════════════════════════════════════════════════════
//  NAME LABEL (upgraded with accent color)
// ═══════════════════════════════════════════════════════════════════════

function _makeNameLabel(name, accentColor) {
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, 256, 64);
    // Glow
    ctx.shadowColor = accentColor || '#ff6b9d';
    ctx.shadowBlur = 8;
    ctx.font = 'bold 28px "Segoe UI", sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.fillText(name, 128, 40);
    ctx.shadowBlur = 0;
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
    const sp = new THREE.Sprite(mat);
    sp.scale.set(1.6, 0.4, 1);
    return sp;
}

// ═══════════════════════════════════════════════════════════════════════
//  OUTFIT UPDATE
// ═══════════════════════════════════════════════════════════════════════

function updateCharacterOutfit(model, outfitKey) {
    if (!model || !model.clothingLayers) return;
    const key = outfitKey || 'nothing';
    if (model.currentOutfit === key) return;
    model.currentOutfit = key;

    const layersToShow = OUTFIT_MAP[key] || [];

    // Hide all clothing layers first
    for (const [name, grp] of Object.entries(model.clothingLayers)) {
        grp.visible = false;
    }

    // Show the ones for this outfit
    for (const layerName of layersToShow) {
        if (model.clothingLayers[layerName]) {
            model.clothingLayers[layerName].visible = true;
        }
    }

    // Update anatomy visibility — show everything first
    for (const [partName, part] of Object.entries(model.anatomyParts)) {
        part.visible = true;
    }
    // Then hide parts covered by visible clothing
    for (const layerName of layersToShow) {
        const hides = LAYER_HIDES[layerName] || [];
        for (const partName of hides) {
            if (model.anatomyParts[partName]) {
                model.anatomyParts[partName].visible = false;
            }
        }
    }

    // Recolour clothing layers to match outfit's colour scheme
    const oc = OUTFIT_COLORS[key];
    if (oc && oc.col != null) {
        for (const layerName of layersToShow) {
            const grp = model.clothingLayers[layerName];
            if (!grp) continue;
            grp.traverse(child => {
                if (child.isMesh && child.material) {
                    child.material.color.setHex(oc.col);
                    if (oc.shiny) { child.material.roughness = 0.25; child.material.metalness = 0.35; }
                    if (oc.alpha != null) {
                        child.material.transparent = true;
                        child.material.opacity = oc.alpha;
                    }
                }
            });
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  FACIAL EXPRESSIONS
// ═══════════════════════════════════════════════════════════════════════

function setCharacterExpression(model, mood) {
    if (!model || !model.headData) return;
    const hd = model.headData;
    const mouth = hd.group.getObjectByName('mouth');
    const browL = hd.group.getObjectByName('browL');
    const browR = hd.group.getObjectByName('browR');
    const pupilL = hd.group.getObjectByName('pupilL');
    const pupilR = hd.group.getObjectByName('pupilR');

    // Reset to neutral
    if (browL) { browL.rotation.z = 0.10; browL.position.y = 0.042; }
    if (browR) { browR.rotation.z = -0.10; browR.position.y = 0.042; }
    if (mouth) { mouth.scale.set(1, 1, 1); mouth.rotation.x = Math.PI * 0.1; }
    if (pupilL) pupilL.scale.set(1, 1, 1);
    if (pupilR) pupilR.scale.set(1, 1, 1);

    const m = (mood || 'neutral').toLowerCase();
    if (m.includes('happy') || m.includes('joy') || m.includes('pleasure') || m.includes('delight')) {
        if (mouth) mouth.scale.set(1.3, 1.2, 1);
        if (browL) browL.position.y = 0.046;
        if (browR) browR.position.y = 0.046;
    } else if (m.includes('aroused') || m.includes('horny') || m.includes('lust')) {
        if (browL) { browL.position.y = 0.038; browL.rotation.z = 0.05; }
        if (browR) { browR.position.y = 0.038; browR.rotation.z = -0.05; }
        if (mouth) mouth.scale.set(1.1, 1.4, 1);
        if (pupilL) pupilL.scale.set(1.4, 1.4, 1.4);
        if (pupilR) pupilR.scale.set(1.4, 1.4, 1.4);
    } else if (m.includes('sad') || m.includes('upset') || m.includes('melanchol')) {
        if (browL) { browL.rotation.z = 0.25; browL.position.y = 0.044; }
        if (browR) { browR.rotation.z = -0.25; browR.position.y = 0.044; }
        if (mouth) { mouth.scale.set(0.9, 0.8, 1); mouth.rotation.x = Math.PI * 0.2; }
    } else if (m.includes('angry') || m.includes('rage') || m.includes('furious')) {
        if (browL) { browL.rotation.z = -0.2; browL.position.y = 0.038; }
        if (browR) { browR.rotation.z = 0.2; browR.position.y = 0.038; }
        if (mouth) mouth.scale.set(1.2, 0.6, 1);
        if (pupilL) pupilL.scale.set(0.8, 0.8, 0.8);
        if (pupilR) pupilR.scale.set(0.8, 0.8, 0.8);
    } else if (m.includes('fear') || m.includes('scared') || m.includes('shock') || m.includes('surprise')) {
        if (browL) browL.position.y = 0.050;
        if (browR) browR.position.y = 0.050;
        if (mouth) mouth.scale.set(1.4, 1.8, 1);
        if (pupilL) pupilL.scale.set(0.7, 0.7, 0.7);
        if (pupilR) pupilR.scale.set(0.7, 0.7, 0.7);
    } else if (m.includes('seduc') || m.includes('flirt') || m.includes('teas') || m.includes('coy')) {
        if (browL) { browL.position.y = 0.045; browL.rotation.z = 0.15; }
        if (browR) { browR.position.y = 0.040; browR.rotation.z = -0.05; }
        if (mouth) mouth.scale.set(1.15, 1.0, 1);
    } else if (m.includes('moan') || m.includes('ecsta') || m.includes('orgasm') || m.includes('climax')) {
        if (browL) { browL.position.y = 0.046; browL.rotation.z = 0.18; }
        if (browR) { browR.position.y = 0.046; browR.rotation.z = -0.18; }
        if (mouth) mouth.scale.set(1.5, 2.0, 1);
        if (pupilL) pupilL.scale.set(1.6, 1.6, 1.6);
        if (pupilR) pupilR.scale.set(1.6, 1.6, 1.6);
    } else if (m.includes('contempt') || m.includes('disgust') || m.includes('bored')) {
        if (browL) { browL.position.y = 0.040; browL.rotation.z = -0.1; }
        if (browR) { browR.position.y = 0.043; browR.rotation.z = 0.08; }
        if (mouth) { mouth.scale.set(0.85, 0.7, 1); mouth.rotation.x = Math.PI * 0.15; }
    } else if (m.includes('shy') || m.includes('embarrass') || m.includes('blush')) {
        if (browL) { browL.position.y = 0.046; browL.rotation.z = 0.2; }
        if (browR) { browR.position.y = 0.046; browR.rotation.z = -0.2; }
        if (mouth) mouth.scale.set(0.9, 0.9, 1);
        // Subtle "looking down"
        if (hd.group) hd.group.rotation.x = 0.1;
    } else if (m.includes('smirk') || m.includes('mischiev') || m.includes('sly')) {
        if (browL) { browL.position.y = 0.044; browL.rotation.z = 0.05; }
        if (browR) { browR.position.y = 0.048; browR.rotation.z = -0.15; }
        if (mouth) { mouth.scale.set(1.1, 0.9, 1); }
    } else if (m.includes('relax') || m.includes('content') || m.includes('peace') || m.includes('calm')) {
        if (mouth) mouth.scale.set(1.1, 1.05, 1);
        if (browL) browL.position.y = 0.044;
        if (browR) browR.position.y = 0.044;
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  BREATHING & IDLE ANIMATION
// ═══════════════════════════════════════════════════════════════════════

function animateCharacterModel(model, time) {
    if (!model || !model.bodyGroup) return;
    const d = model.dims;

    // Breathing — torso scale oscillation
    const breathAmp = 0.015;
    const breathFreq = 1.1 + (model.charColor === '#ff6b9d' ? 0.1 : 0);
    const breath = 1.0 + breathAmp * Math.sin(time * breathFreq * Math.PI * 2);
    const torsoMesh = model.bodyGroup.children[0];
    if (torsoMesh) {
        torsoMesh.scale.x = breath;
        torsoMesh.scale.z = d.torsoScaleZ * breath;
    }

    // Gentle body sway (side-to-side)
    const sway = 0.01 * Math.sin(time * 0.6);
    model.bodyGroup.rotation.y = sway;

    // Weight shift — subtle lateral translation
    const weightShift = 0.015 * Math.sin(time * 0.35);
    model.bodyGroup.position.x = weightShift;

    // Arms — natural swing with asymmetric timing
    if (model.armL) {
        model.armL.rotation.x = 0.03 * Math.sin(time * 0.8 + 1.0);
        model.armL.rotation.z = -0.02 + 0.01 * Math.sin(time * 0.5);
    }
    if (model.armR) {
        model.armR.rotation.x = 0.03 * Math.sin(time * 0.8 + 2.5);
        model.armR.rotation.z = 0.02 - 0.01 * Math.sin(time * 0.5 + 1.0);
    }

    // Legs — subtle knee flex
    if (model.legL) model.legL.rotation.x = 0.005 * Math.sin(time * 0.4);
    if (model.legR) model.legR.rotation.x = 0.005 * Math.sin(time * 0.4 + Math.PI);

    // Head micro-movement (looking around subtly)
    if (model.headData && model.headData.group) {
        model.headData.group.rotation.y = 0.04 * Math.sin(time * 0.25);
        model.headData.group.rotation.x = 0.015 * Math.sin(time * 0.3 + 0.5);
    }

    // Blink cycle (every ~4 seconds, brief scale-down of eyes)
    const blinkCycle = time % 4.0;
    if (model.headData && model.headData.group && blinkCycle > 3.85 && blinkCycle < 3.95) {
        const pupilL = model.headData.group.getObjectByName('pupilL');
        const pupilR = model.headData.group.getObjectByName('pupilR');
        if (pupilL) pupilL.scale.y = 0.2;
        if (pupilR) pupilR.scale.y = 0.2;
    } else if (model.headData && model.headData.group) {
        const pupilL = model.headData.group.getObjectByName('pupilL');
        const pupilR = model.headData.group.getObjectByName('pupilR');
        if (pupilL && pupilL.scale.y < 0.9) pupilL.scale.y = 1.0;
        if (pupilR && pupilR.scale.y < 0.9) pupilR.scale.y = 1.0;
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  SEX POSE / INTERACTION SYSTEM
// ═══════════════════════════════════════════════════════════════════════

/**
 * Pose definitions for sexual interactions.
 * Each pose defines body part transforms for up to 3 participants:
 *   role A = initiator/active, B = receiver, C = third participant.
 * Values are relative offsets/rotations applied on top of the base position.
 *
 * Fields per role:
 *   pos:   {x,y,z}        — world-space offset from the anchor point (bed centre)
 *   rot:   {x,y,z}        — body group euler rotation
 *   armL:  {rx,ry,rz}     — left arm rotations
 *   armR:  {rx,ry,rz}     — right arm rotations
 *   legL:  {rx,ry,rz}     — left leg rotations
 *   legR:  {rx,ry,rz}     — right leg rotations
 *   headTilt: number       — head group X rotation (nod)
 *   thrust: {amp,freq}     — rhythmic hip motion (amplitude, frequency Hz)
 *   breathMult: number     — breathing intensity multiplier
 */

const SEX_POSES = {
    // ── Standing / standing ──────────────────────────────────────────
    'kiss deeply': {
        A: { pos:{x:-0.15,y:0,z:0}, rot:{x:0,y:0.3,z:0},
             armL:{rx:0.6,ry:0,rz:0.3}, armR:{rx:0.8,ry:0,rz:-0.2},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:-0.15, thrust:null, breathMult:1.4 },
        B: { pos:{x:0.15,y:0,z:0}, rot:{x:0,y:-0.3,z:0},
             armL:{rx:0.5,ry:0,rz:0.2}, armR:{rx:0.7,ry:0,rz:-0.3},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:-0.12, thrust:null, breathMult:1.3 },
    },
    'bite neck': {
        A: { pos:{x:-0.12,y:0,z:0.05}, rot:{x:0,y:0.4,z:0},
             armL:{rx:0.5,ry:0,rz:0.4}, armR:{rx:0.9,ry:0.2,rz:-0.1},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:0.2, thrust:null, breathMult:1.5 },
        B: { pos:{x:0.12,y:0,z:-0.05}, rot:{x:0,y:-0.2,z:0},
             armL:{rx:0.3,ry:0,rz:0.1}, armR:{rx:0.4,ry:0,rz:-0.1},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:-0.3, thrust:null, breathMult:1.6 },
    },
    'spank': {
        A: { pos:{x:-0.3,y:0,z:0}, rot:{x:0,y:0.2,z:0},
             armL:{rx:0.4,ry:0,rz:0.3}, armR:{rx:-1.2,ry:0,rz:-0.2},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0.1,ry:0,rz:0},
             headTilt:0.05, thrust:null, breathMult:1.3 },
        B: { pos:{x:0.3,y:-0.35,z:0}, rot:{x:1.2,y:Math.PI,z:0},
             armL:{rx:0.3,ry:0,rz:0.2}, armR:{rx:0.3,ry:0,rz:-0.2},
             legL:{rx:-0.6,ry:0,rz:0}, legR:{rx:-0.6,ry:0,rz:0},
             headTilt:0.1, thrust:null, breathMult:1.5 },
    },
    // ── Oral ─────────────────────────────────────────────────────────
    'oral — give': {
        A: { pos:{x:0,y:-0.7,z:0.25}, rot:{x:0,y:0,z:0},
             armL:{rx:0.8,ry:0,rz:0.3}, armR:{rx:0.8,ry:0,rz:-0.3},
             legL:{rx:-1.5,ry:0,rz:0}, legR:{rx:-1.5,ry:0,rz:0},
             headTilt:0.15, thrust:null, breathMult:1.6 },
        B: { pos:{x:0,y:0,z:0}, rot:{x:0,y:0,z:0},
             armL:{rx:0.3,ry:0,rz:0.3}, armR:{rx:0.3,ry:0,rz:-0.3},
             legL:{rx:0.15,ry:0,rz:-0.15}, legR:{rx:0.15,ry:0,rz:0.15},
             headTilt:-0.25, thrust:null, breathMult:1.8 },
    },
    'oral — receive': {
        A: { pos:{x:0,y:0,z:0}, rot:{x:0,y:0,z:0},
             armL:{rx:-0.1,ry:0,rz:0.2}, armR:{rx:-0.1,ry:0,rz:-0.2},
             legL:{rx:0.15,ry:0,rz:-0.15}, legR:{rx:0.15,ry:0,rz:0.15},
             headTilt:-0.3, thrust:null, breathMult:2.0 },
        B: { pos:{x:0,y:-0.7,z:0.25}, rot:{x:0,y:0,z:0},
             armL:{rx:0.8,ry:0,rz:0.3}, armR:{rx:0.8,ry:0,rz:-0.3},
             legL:{rx:-1.5,ry:0,rz:0}, legR:{rx:-1.5,ry:0,rz:0},
             headTilt:0.15, thrust:{amp:0.03,freq:1.2}, breathMult:1.5 },
    },
    'finger / handjob': {
        A: { pos:{x:-0.2,y:0,z:0.1}, rot:{x:0,y:0.4,z:0},
             armL:{rx:0.3,ry:0,rz:0.2}, armR:{rx:1.0,ry:0.3,rz:0},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:0.05, thrust:null, breathMult:1.3 },
        B: { pos:{x:0.2,y:0,z:-0.1}, rot:{x:0,y:-0.3,z:0},
             armL:{rx:0.1,ry:0,rz:0.1}, armR:{rx:0.1,ry:0,rz:-0.1},
             legL:{rx:0.2,ry:0,rz:-0.2}, legR:{rx:0.2,ry:0,rz:0.2},
             headTilt:-0.2, thrust:null, breathMult:1.8 },
    },
    'face sit': {
        A: { pos:{x:0,y:0.15,z:0}, rot:{x:0,y:0,z:0},
             armL:{rx:0.3,ry:0,rz:0.4}, armR:{rx:0.3,ry:0,rz:-0.4},
             legL:{rx:-0.8,ry:0,rz:-0.4}, legR:{rx:-0.8,ry:0,rz:0.4},
             headTilt:-0.2, thrust:{amp:0.04,freq:0.8}, breathMult:2.0 },
        B: { pos:{x:0,y:-0.65,z:0}, rot:{x:-0.2,y:0,z:0},
             armL:{rx:0.6,ry:0,rz:0.4}, armR:{rx:0.6,ry:0,rz:-0.4},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:0.3, thrust:null, breathMult:1.5 },
    },
    'throat fuck': {
        A: { pos:{x:0,y:0,z:0}, rot:{x:0,y:0,z:0},
             armL:{rx:0.6,ry:0.2,rz:0.1}, armR:{rx:0.6,ry:-0.2,rz:-0.1},
             legL:{rx:0.1,ry:0,rz:0}, legR:{rx:0.1,ry:0,rz:0},
             headTilt:0.1, thrust:{amp:0.06,freq:2.5}, breathMult:1.8 },
        B: { pos:{x:0,y:-0.7,z:0.3}, rot:{x:0,y:0,z:0},
             armL:{rx:0.5,ry:0,rz:0.2}, armR:{rx:0.5,ry:0,rz:-0.2},
             legL:{rx:-1.5,ry:0,rz:0}, legR:{rx:-1.5,ry:0,rz:0},
             headTilt:0.2, thrust:null, breathMult:2.2 },
    },
    // ── Main sex positions ───────────────────────────────────────────
    'ride': {
        A: { pos:{x:0,y:0.25,z:0.05}, rot:{x:-0.1,y:0,z:0},
             armL:{rx:0.4,ry:0,rz:0.3}, armR:{rx:0.4,ry:0,rz:-0.3},
             legL:{rx:-1.2,ry:0,rz:-0.5}, legR:{rx:-1.2,ry:0,rz:0.5},
             headTilt:-0.25, thrust:{amp:0.08,freq:1.5}, breathMult:2.2 },
        B: { pos:{x:0,y:-0.55,z:0}, rot:{x:-0.3,y:0,z:0},
             armL:{rx:0.6,ry:0,rz:0.4}, armR:{rx:0.6,ry:0,rz:-0.4},
             legL:{rx:-0.5,ry:0,rz:-0.3}, legR:{rx:-0.5,ry:0,rz:0.3},
             headTilt:-0.15, thrust:{amp:0.04,freq:1.5}, breathMult:2.0 },
    },
    'fuck — missionary': {
        A: { pos:{x:0,y:-0.1,z:0.15}, rot:{x:0.6,y:0,z:0},
             armL:{rx:0.8,ry:0,rz:0.4}, armR:{rx:0.8,ry:0,rz:-0.4},
             legL:{rx:-0.4,ry:0,rz:0}, legR:{rx:-0.4,ry:0,rz:0},
             headTilt:0.15, thrust:{amp:0.07,freq:1.8}, breathMult:2.5 },
        B: { pos:{x:0,y:-0.55,z:0}, rot:{x:-0.5,y:0,z:0},
             armL:{rx:0.7,ry:0,rz:0.5}, armR:{rx:0.7,ry:0,rz:-0.5},
             legL:{rx:-0.8,ry:0,rz:-0.6}, legR:{rx:-0.8,ry:0,rz:0.6},
             headTilt:-0.2, thrust:null, breathMult:2.2 },
    },
    'fuck — doggy': {
        A: { pos:{x:0,y:0,z:-0.3}, rot:{x:0.3,y:0,z:0},
             armL:{rx:0.6,ry:0,rz:0.3}, armR:{rx:0.6,ry:0,rz:-0.3},
             legL:{rx:-0.3,ry:0,rz:0}, legR:{rx:-0.3,ry:0,rz:0},
             headTilt:0.1, thrust:{amp:0.09,freq:2.0}, breathMult:2.5 },
        B: { pos:{x:0,y:-0.35,z:0.3}, rot:{x:1.0,y:Math.PI,z:0},
             armL:{rx:0.5,ry:0,rz:0.2}, armR:{rx:0.5,ry:0,rz:-0.2},
             legL:{rx:-0.6,ry:0,rz:-0.3}, legR:{rx:-0.6,ry:0,rz:0.3},
             headTilt:0.2, thrust:null, breathMult:2.3 },
    },
    'edge': {
        A: { pos:{x:-0.2,y:0,z:0.1}, rot:{x:0,y:0.3,z:0},
             armL:{rx:0.3,ry:0,rz:0.2}, armR:{rx:1.1,ry:0.3,rz:0},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:0.1, thrust:null, breathMult:1.4 },
        B: { pos:{x:0.2,y:0,z:-0.1}, rot:{x:0,y:-0.2,z:0},
             armL:{rx:0.1,ry:0,rz:0.1}, armR:{rx:0.1,ry:0,rz:-0.1},
             legL:{rx:0.3,ry:0,rz:-0.3}, legR:{rx:0.3,ry:0,rz:0.3},
             headTilt:-0.35, thrust:null, breathMult:2.5 },
    },
    'use toy on target': {
        A: { pos:{x:-0.25,y:0,z:0.1}, rot:{x:0,y:0.3,z:0},
             armL:{rx:0.2,ry:0,rz:0.1}, armR:{rx:1.2,ry:0.2,rz:0},
             legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
             headTilt:0.1, thrust:null, breathMult:1.3 },
        B: { pos:{x:0.2,y:0,z:-0.1}, rot:{x:0,y:-0.2,z:0},
             armL:{rx:0.2,ry:0,rz:0.2}, armR:{rx:0.2,ry:0,rz:-0.2},
             legL:{rx:0.25,ry:0,rz:-0.3}, legR:{rx:0.25,ry:0,rz:0.3},
             headTilt:-0.3, thrust:null, breathMult:2.2 },
    },
    // ── Climax / Finish ──────────────────────────────────────────────
    'cum on target': {
        A: { pos:{x:-0.15,y:0,z:0.15}, rot:{x:0,y:0.2,z:0},
             armL:{rx:0.2,ry:0,rz:0.1}, armR:{rx:1.0,ry:0,rz:0},
             legL:{rx:0.1,ry:0,rz:0}, legR:{rx:0.1,ry:0,rz:0},
             headTilt:-0.3, thrust:null, breathMult:3.0 },
        B: { pos:{x:0.15,y:-0.5,z:0}, rot:{x:-0.3,y:-0.3,z:0},
             armL:{rx:0.3,ry:0,rz:0.2}, armR:{rx:0.3,ry:0,rz:-0.2},
             legL:{rx:-0.4,ry:0,rz:0}, legR:{rx:-0.4,ry:0,rz:0},
             headTilt:-0.15, thrust:null, breathMult:2.0 },
    },
    'orgasm together': {
        A: { pos:{x:-0.08,y:-0.15,z:0.1}, rot:{x:0.3,y:0.15,z:0},
             armL:{rx:0.7,ry:0,rz:0.5}, armR:{rx:0.7,ry:0,rz:-0.5},
             legL:{rx:-0.4,ry:0,rz:0}, legR:{rx:-0.4,ry:0,rz:0},
             headTilt:-0.35, thrust:{amp:0.1,freq:3.0}, breathMult:3.5 },
        B: { pos:{x:0.08,y:-0.45,z:0}, rot:{x:-0.4,y:-0.15,z:0},
             armL:{rx:0.8,ry:0,rz:0.5}, armR:{rx:0.8,ry:0,rz:-0.5},
             legL:{rx:-0.7,ry:0,rz:-0.5}, legR:{rx:-0.7,ry:0,rz:0.5},
             headTilt:-0.3, thrust:{amp:0.08,freq:3.0}, breathMult:3.5 },
    },
    'aftercare': {
        A: { pos:{x:-0.1,y:-0.5,z:0}, rot:{x:-0.2,y:0.15,z:0.1},
             armL:{rx:0.4,ry:0,rz:0.3}, armR:{rx:0.5,ry:0.2,rz:-0.1},
             legL:{rx:-0.3,ry:0,rz:0}, legR:{rx:-0.4,ry:0,rz:0},
             headTilt:-0.1, thrust:null, breathMult:0.8 },
        B: { pos:{x:0.1,y:-0.5,z:0}, rot:{x:-0.2,y:-0.15,z:-0.1},
             armL:{rx:0.5,ry:0.2,rz:0.1}, armR:{rx:0.4,ry:0,rz:-0.3},
             legL:{rx:-0.4,ry:0,rz:0}, legR:{rx:-0.3,ry:0,rz:0},
             headTilt:-0.1, thrust:null, breathMult:0.8 },
    },
    // ── Three-player poses ───────────────────────────────────────────
    'threesome — spit roast': {
        A: { pos:{x:0,y:0,z:-0.35}, rot:{x:0.3,y:0,z:0},
             armL:{rx:0.5,ry:0,rz:0.3}, armR:{rx:0.5,ry:0,rz:-0.3},
             legL:{rx:-0.3,ry:0,rz:0}, legR:{rx:-0.3,ry:0,rz:0},
             headTilt:0.1, thrust:{amp:0.08,freq:1.8}, breathMult:2.3 },
        B: { pos:{x:0,y:-0.35,z:0}, rot:{x:0.9,y:0,z:0},
             armL:{rx:0.5,ry:0,rz:0.2}, armR:{rx:0.5,ry:0,rz:-0.2},
             legL:{rx:-0.5,ry:0,rz:-0.3}, legR:{rx:-0.5,ry:0,rz:0.3},
             headTilt:0.2, thrust:null, breathMult:2.5 },
        C: { pos:{x:0,y:0,z:0.35}, rot:{x:0,y:Math.PI,z:0},
             armL:{rx:0.4,ry:0,rz:0.2}, armR:{rx:0.4,ry:0,rz:-0.2},
             legL:{rx:0.1,ry:0,rz:0}, legR:{rx:0.1,ry:0,rz:0},
             headTilt:0.1, thrust:{amp:0.06,freq:2.2}, breathMult:2.0 },
    },
    'threesome — double oral': {
        A: { pos:{x:-0.25,y:-0.7,z:0.2}, rot:{x:0,y:0.3,z:0},
             armL:{rx:0.7,ry:0,rz:0.3}, armR:{rx:0.7,ry:0,rz:-0.3},
             legL:{rx:-1.5,ry:0,rz:0}, legR:{rx:-1.5,ry:0,rz:0},
             headTilt:0.15, thrust:null, breathMult:1.5 },
        B: { pos:{x:0,y:0,z:0}, rot:{x:0,y:0,z:0},
             armL:{rx:0.3,ry:0,rz:0.3}, armR:{rx:0.3,ry:0,rz:-0.3},
             legL:{rx:0.2,ry:0,rz:-0.2}, legR:{rx:0.2,ry:0,rz:0.2},
             headTilt:-0.3, thrust:null, breathMult:2.5 },
        C: { pos:{x:0.25,y:-0.7,z:0.2}, rot:{x:0,y:-0.3,z:0},
             armL:{rx:0.7,ry:0,rz:0.3}, armR:{rx:0.7,ry:0,rz:-0.3},
             legL:{rx:-1.5,ry:0,rz:0}, legR:{rx:-1.5,ry:0,rz:0},
             headTilt:0.15, thrust:null, breathMult:1.5 },
    },
    'threesome — ride and suck': {
        A: { pos:{x:-0.2,y:0.25,z:0}, rot:{x:-0.1,y:0.2,z:0},
             armL:{rx:0.4,ry:0,rz:0.3}, armR:{rx:0.4,ry:0,rz:-0.3},
             legL:{rx:-1.2,ry:0,rz:-0.4}, legR:{rx:-1.2,ry:0,rz:0.4},
             headTilt:-0.2, thrust:{amp:0.07,freq:1.4}, breathMult:2.2 },
        B: { pos:{x:0,y:-0.55,z:0}, rot:{x:-0.3,y:0,z:0},
             armL:{rx:0.5,ry:0,rz:0.3}, armR:{rx:0.5,ry:0,rz:-0.3},
             legL:{rx:-0.4,ry:0,rz:-0.2}, legR:{rx:-0.4,ry:0,rz:0.2},
             headTilt:-0.1, thrust:null, breathMult:2.5 },
        C: { pos:{x:0.3,y:-0.6,z:0.25}, rot:{x:0,y:-0.4,z:0},
             armL:{rx:0.7,ry:0,rz:0.2}, armR:{rx:0.7,ry:0,rz:-0.2},
             legL:{rx:-1.5,ry:0,rz:0}, legR:{rx:-1.5,ry:0,rz:0},
             headTilt:0.15, thrust:null, breathMult:1.5 },
    },
    'threesome — daisy chain': {
        A: { pos:{x:-0.3,y:-0.5,z:-0.2}, rot:{x:-0.3,y:0.5,z:0.1},
             armL:{rx:0.6,ry:0,rz:0.3}, armR:{rx:0.8,ry:0,rz:-0.2},
             legL:{rx:-0.4,ry:0,rz:0}, legR:{rx:-0.5,ry:0,rz:0.3},
             headTilt:0.15, thrust:null, breathMult:2.0 },
        B: { pos:{x:0.3,y:-0.5,z:-0.2}, rot:{x:-0.3,y:-0.5,z:-0.1},
             armL:{rx:0.8,ry:0,rz:0.2}, armR:{rx:0.6,ry:0,rz:-0.3},
             legL:{rx:-0.5,ry:0,rz:-0.3}, legR:{rx:-0.4,ry:0,rz:0},
             headTilt:0.15, thrust:null, breathMult:2.0 },
        C: { pos:{x:0,y:-0.5,z:0.35}, rot:{x:-0.3,y:Math.PI,z:0},
             armL:{rx:0.7,ry:0,rz:0.3}, armR:{rx:0.7,ry:0,rz:-0.3},
             legL:{rx:-0.4,ry:0,rz:-0.2}, legR:{rx:-0.4,ry:0,rz:0.2},
             headTilt:0.15, thrust:null, breathMult:2.0 },
    },
    'threesome — double penetration': {
        A: { pos:{x:-0.1,y:-0.1,z:-0.2}, rot:{x:0.4,y:0.1,z:0},
             armL:{rx:0.6,ry:0,rz:0.3}, armR:{rx:0.6,ry:0,rz:-0.3},
             legL:{rx:-0.3,ry:0,rz:0}, legR:{rx:-0.3,ry:0,rz:0},
             headTilt:0.1, thrust:{amp:0.08,freq:1.6}, breathMult:2.5 },
        B: { pos:{x:0,y:0,z:0}, rot:{x:0,y:0,z:0},
             armL:{rx:0.5,ry:0,rz:0.4}, armR:{rx:0.5,ry:0,rz:-0.4},
             legL:{rx:-0.9,ry:0,rz:-0.6}, legR:{rx:-0.9,ry:0,rz:0.6},
             headTilt:-0.3, thrust:null, breathMult:3.0 },
        C: { pos:{x:0.1,y:-0.55,z:0.2}, rot:{x:-0.2,y:Math.PI+0.1,z:0},
             armL:{rx:0.5,ry:0,rz:0.2}, armR:{rx:0.5,ry:0,rz:-0.2},
             legL:{rx:-0.3,ry:0,rz:0}, legR:{rx:-0.3,ry:0,rz:0},
             headTilt:0.1, thrust:{amp:0.07,freq:1.8}, breathMult:2.3 },
    },
    'threesome — one watches': {
        A: { pos:{x:-0.15,y:-0.1,z:0.1}, rot:{x:0.5,y:0.1,z:0},
             armL:{rx:0.7,ry:0,rz:0.4}, armR:{rx:0.7,ry:0,rz:-0.4},
             legL:{rx:-0.3,ry:0,rz:0}, legR:{rx:-0.3,ry:0,rz:0},
             headTilt:0.1, thrust:{amp:0.07,freq:1.8}, breathMult:2.4 },
        B: { pos:{x:0.15,y:-0.55,z:0}, rot:{x:-0.5,y:-0.1,z:0},
             armL:{rx:0.6,ry:0,rz:0.4}, armR:{rx:0.6,ry:0,rz:-0.4},
             legL:{rx:-0.8,ry:0,rz:-0.5}, legR:{rx:-0.8,ry:0,rz:0.5},
             headTilt:-0.2, thrust:null, breathMult:2.2 },
        C: { pos:{x:1.2,y:0,z:0}, rot:{x:0,y:-0.5,z:0},
             armL:{rx:0.2,ry:0,rz:0.1}, armR:{rx:0.8,ry:0.3,rz:0},
             legL:{rx:0.1,ry:0,rz:-0.1}, legR:{rx:0.1,ry:0,rz:0.1},
             headTilt:-0.1, thrust:null, breathMult:1.8 },
    },
};

// Fallback pose for actions without a dedicated pose definition
const _FALLBACK_POSE = {
    A: { pos:{x:-0.15,y:0,z:0}, rot:{x:0,y:0.2,z:0},
         armL:{rx:0.5,ry:0,rz:0.3}, armR:{rx:0.5,ry:0,rz:-0.3},
         legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
         headTilt:0, thrust:null, breathMult:1.5 },
    B: { pos:{x:0.15,y:0,z:0}, rot:{x:0,y:-0.2,z:0},
         armL:{rx:0.3,ry:0,rz:0.2}, armR:{rx:0.3,ry:0,rz:-0.2},
         legL:{rx:0,ry:0,rz:0}, legR:{rx:0,ry:0,rz:0},
         headTilt:0, thrust:null, breathMult:1.5 },
};

// ── Pose interpolation state ─────────────────────────────────────────

const _activePoseState = {
    active: false,
    actionName: null,
    participants: [],      // [{model, role, anchorPos, targetPose, currentLerp}]
    lerpProgress: 0,       // 0 → 1, drives the transition
    lerpSpeed: 2.5,        // per-second interpolation speed
    thrustPhase: 0,        // running phase for rhythmic motion
};

/**
 * Start a sexual interaction pose.
 * @param {string} actionName — key from BED_GAME_ACTIONS / SEX_POSES
 * @param {Array<{model:object, anchorX:number, anchorZ:number}>} participants
 *   Ordered: [A=initiator, B=receiver, C=third (optional)]
 *   anchorX/Z = world-space centre point (e.g. bed position)
 */
function startSexPose(actionName, participants) {
    const poseDef = SEX_POSES[actionName] || _FALLBACK_POSE;
    const roles = ['A', 'B', 'C'];

    _activePoseState.active = true;
    _activePoseState.actionName = actionName;
    _activePoseState.lerpProgress = 0;
    _activePoseState.thrustPhase = 0;
    _activePoseState.participants = [];

    for (let i = 0; i < participants.length && i < 3; i++) {
        const p = participants[i];
        const roleKey = roles[i];
        const target = poseDef[roleKey] || _FALLBACK_POSE.A;
        const anchorX = p.anchorX || 0;
        const anchorZ = p.anchorZ || 0;

        // Strip to nothing for explicit poses (explicit_level >= 3)
        if (p.model && p.model.currentOutfit !== 'nothing') {
            updateCharacterOutfit(p.model, 'nothing');
        }

        _activePoseState.participants.push({
            model: p.model,
            role: roleKey,
            anchorX, anchorZ,
            target,
            // Store the base (standing) transforms so we can LERP from them
            basePos: p.model ? {
                x: p.model.group.position.x,
                y: p.model.group.position.y,
                z: p.model.group.position.z
            } : {x:0,y:0,z:0},
        });
    }
}

/**
 * Stop the current sex pose and return participants to standing.
 * @param {boolean} instant — if true, snap back immediately (no lerp)
 */
function stopSexPose(instant) {
    if (!_activePoseState.active) return;
    if (instant) {
        // Snap everything back to neutral
        for (const p of _activePoseState.participants) {
            if (!p.model) continue;
            _resetModelPose(p.model);
            p.model.group.position.set(p.basePos.x, p.basePos.y, p.basePos.z);
        }
        _activePoseState.active = false;
        _activePoseState.participants = [];
    } else {
        // Trigger a reverse lerp by setting a cleanup flag
        _activePoseState._returning = true;
        _activePoseState.lerpProgress = 1.0;
    }
}

function _resetModelPose(model) {
    if (!model) return;
    model.bodyGroup.rotation.set(0, 0, 0);
    if (model.armL) model.armL.rotation.set(0, 0, 0);
    if (model.armR) model.armR.rotation.set(0, 0, 0);
    if (model.legL) model.legL.rotation.set(0, 0, 0);
    if (model.legR) model.legR.rotation.set(0, 0, 0);
    if (model.headData && model.headData.group) model.headData.group.rotation.x = 0;
}

function _lerp(a, b, t) { return a + (b - a) * t; }

/**
 * Tick the sex pose animation — call every frame from the main animate() loop.
 * @param {number} dt — delta time in seconds
 * @param {number} time — total elapsed time
 */
function animateSexPose(dt, time) {
    if (!_activePoseState.active) return;

    // Handle returning to standing
    if (_activePoseState._returning) {
        _activePoseState.lerpProgress -= dt * _activePoseState.lerpSpeed;
        if (_activePoseState.lerpProgress <= 0) {
            stopSexPose(true);
            _activePoseState._returning = false;
            return;
        }
    } else {
        // Advance lerp toward target
        if (_activePoseState.lerpProgress < 1.0) {
            _activePoseState.lerpProgress = Math.min(1.0, _activePoseState.lerpProgress + dt * _activePoseState.lerpSpeed);
        }
    }

    const t = _activePoseState.lerpProgress;
    _activePoseState.thrustPhase += dt;

    for (const p of _activePoseState.participants) {
        const model = p.model;
        if (!model || !model.bodyGroup) continue;
        const tgt = p.target;

        // ── Position (world-space anchor + pose offset) ──
        const destX = p.anchorX + tgt.pos.x;
        const destY = tgt.pos.y;
        const destZ = p.anchorZ + tgt.pos.z;
        model.group.position.x = _lerp(p.basePos.x, destX, t);
        model.group.position.y = _lerp(p.basePos.y, destY, t);
        model.group.position.z = _lerp(p.basePos.z, destZ, t);

        // ── Body rotation ──
        model.bodyGroup.rotation.x = _lerp(0, tgt.rot.x, t);
        model.bodyGroup.rotation.y = _lerp(0, tgt.rot.y, t);
        model.bodyGroup.rotation.z = _lerp(0, tgt.rot.z, t);

        // ── Arms ──
        if (model.armL) {
            model.armL.rotation.x = _lerp(0, tgt.armL.rx, t);
            model.armL.rotation.y = _lerp(0, tgt.armL.ry, t);
            model.armL.rotation.z = _lerp(0, tgt.armL.rz, t);
        }
        if (model.armR) {
            model.armR.rotation.x = _lerp(0, tgt.armR.rx, t);
            model.armR.rotation.y = _lerp(0, tgt.armR.ry, t);
            model.armR.rotation.z = _lerp(0, tgt.armR.rz, t);
        }

        // ── Legs ──
        if (model.legL) {
            model.legL.rotation.x = _lerp(0, tgt.legL.rx, t);
            model.legL.rotation.y = _lerp(0, tgt.legL.ry, t);
            model.legL.rotation.z = _lerp(0, tgt.legL.rz, t);
        }
        if (model.legR) {
            model.legR.rotation.x = _lerp(0, tgt.legR.rx, t);
            model.legR.rotation.y = _lerp(0, tgt.legR.ry, t);
            model.legR.rotation.z = _lerp(0, tgt.legR.rz, t);
        }

        // ── Head tilt ──
        if (model.headData && model.headData.group) {
            model.headData.group.rotation.x = _lerp(0, tgt.headTilt || 0, t);
        }

        // ── Rhythmic thrust (only at full lerp) ──
        if (tgt.thrust && t > 0.8) {
            const thrustT = Math.sin(_activePoseState.thrustPhase * tgt.thrust.freq * Math.PI * 2);
            const thrustAmt = tgt.thrust.amp * thrustT * t;
            // Apply thrust as forward/back motion relative to body facing
            const angle = model.bodyGroup.rotation.y || 0;
            model.group.position.z += thrustAmt * Math.cos(angle);
            model.group.position.x += thrustAmt * Math.sin(angle);
        }

        // ── Intensified breathing ──
        const bMul = _lerp(1.0, tgt.breathMult || 1.0, t);
        const breathAmp = 0.012 * bMul;
        const breathFreq = 1.2 * (0.8 + bMul * 0.4);
        const breath = 1.0 + breathAmp * Math.sin(time * breathFreq * Math.PI * 2);
        if (model.bodyGroup.children[0]) {
            model.bodyGroup.children[0].scale.x = breath;
            model.bodyGroup.children[0].scale.z = (model.dims ? model.dims.torsoScaleZ : 0.7) * breath;
        }
    }
}

/**
 * Check whether a sex pose is currently active.
 */
function isSexPoseActive() {
    return _activePoseState.active;
}

/**
 * Get info about the current pose (for UI display).
 */
function getSexPoseInfo() {
    if (!_activePoseState.active) return null;
    return {
        actionName: _activePoseState.actionName,
        participantCount: _activePoseState.participants.length,
        roles: _activePoseState.participants.map(p => p.role),
        progress: _activePoseState.lerpProgress,
    };
}

function makeDialogBubble(text, accentColor) {
    const maxLen = 48;
    const lines = [];
    let remaining = text;
    while (remaining.length > 0) {
        if (remaining.length <= maxLen) { lines.push(remaining); break; }
        let cut = remaining.lastIndexOf(' ', maxLen);
        if (cut <= 0) cut = maxLen;
        lines.push(remaining.slice(0, cut));
        remaining = remaining.slice(cut).trim();
        if (lines.length >= 3) {
            if (remaining.length > 0) lines[lines.length - 1] += '…';
            break;
        }
    }

    const lineH = 30;
    const padding = 16;
    const canvasW = 512;
    const canvasH = padding * 2 + lines.length * lineH + 20; // +20 for tail
    const canvas = document.createElement('canvas');
    canvas.width = canvasW; canvas.height = canvasH;
    const ctx = canvas.getContext('2d');

    const bubbleH = canvasH - 20;
    const r = 14;

    // Background
    ctx.fillStyle = 'rgba(12, 12, 22, 0.88)';
    ctx.strokeStyle = accentColor || '#ff6b9d';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(r, 0); ctx.lineTo(canvasW - r, 0);
    ctx.arcTo(canvasW, 0, canvasW, r, r);
    ctx.lineTo(canvasW, bubbleH - r);
    ctx.arcTo(canvasW, bubbleH, canvasW - r, bubbleH, r);
    // Tail
    ctx.lineTo(canvasW / 2 + 10, bubbleH);
    ctx.lineTo(canvasW / 2, canvasH);
    ctx.lineTo(canvasW / 2 - 10, bubbleH);
    ctx.lineTo(r, bubbleH);
    ctx.arcTo(0, bubbleH, 0, bubbleH - r, r);
    ctx.lineTo(0, r);
    ctx.arcTo(0, 0, r, 0, r);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Text
    ctx.font = 'bold 22px "Segoe UI", sans-serif';
    ctx.fillStyle = '#f0f0f0';
    ctx.textAlign = 'center';
    lines.forEach((line, i) => {
        ctx.fillText(line, canvasW / 2, padding + 22 + i * lineH);
    });

    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
    const sp = new THREE.Sprite(mat);
    const aspect = canvasW / canvasH;
    const scale = 2.2;
    sp.scale.set(scale, scale / aspect, 1);
    return sp;
}

// ═══════════════════════════════════════════════════════════════════════
//  PUBLIC API
// ═══════════════════════════════════════════════════════════════════════

window.CharModels = {
    create:        createDetailedCharacter,
    updateOutfit:  updateCharacterOutfit,
    setExpression: setCharacterExpression,
    animate:       animateCharacterModel,
    makeBubble:    makeDialogBubble,
    // Sex pose system
    startPose:     startSexPose,
    stopPose:      stopSexPose,
    animatePose:   animateSexPose,
    isPoseActive:  isSexPoseActive,
    getPoseInfo:   getSexPoseInfo,
    SEX_POSES:     SEX_POSES,
    CHAR_LOOKS:    CHAR_LOOKS,
    OUTFIT_MAP:    OUTFIT_MAP,
};
