// The field twin: one plot rendered in three.js, driven by the simulator's daily records.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const LOOK = {
  cereal:    { h: 1.1, seed: '#6FA84F', mature: '#C9A93A', flower: '#D9C46B', shape: 'grass' },
  pulse:     { h: 0.7, seed: '#5E9E4A', mature: '#8D9A4E', flower: '#E9DFC0', shape: 'bush' },
  oilseed:   { h: 0.9, seed: '#6AAE55', mature: '#A7A45B', flower: '#F2D23D', shape: 'bush' },
  vegetable: { h: 0.55, seed: '#5FA34D', mature: '#4F8F3E', flower: '#F0E7A8', shape: 'broad' },
  fibre:     { h: 1.0, seed: '#5C9C48', mature: '#8F9E5A', flower: '#F5F1E8', shape: 'bush' },
  cash:      { h: 2.3, seed: '#66A84F', mature: '#9DB25B', flower: '#B8C77A', shape: 'tall' },
  spice:     { h: 0.8, seed: '#5FA34D', mature: '#6E9A45', flower: '#E9C98A', shape: 'broad' },
};
const OVERRIDE = {
  rice: { h: 0.95, mature: '#D8B44A' }, wheat: { mature: '#D9B85C' }, barley: { mature: '#D2B46A' },
  mustard: { flower: '#F5D021', h: 1.3 }, sunflower: { flower: '#F2B33D', h: 1.6, shape: 'tall' }, cotton: { flower: '#F7F3EA', h: 1.1 },
  sugarcane: { h: 2.8 }, maize: { h: 2.1, shape: 'tall' }, bajra: { h: 1.9, shape: 'tall' }, jowar: { h: 1.8, shape: 'tall' },
  potato: { h: 0.5 }, onion: { h: 0.45, shape: 'grass' }, spinach: { h: 0.3 }, carrot: { h: 0.35, shape: 'grass' }, jute: { h: 2.4, shape: 'tall' },
  arhar: { h: 1.6, shape: 'bush' }, turmeric: { h: 0.9, shape: 'broad' }, chillies: { h: 0.7, flower: '#E8694A' }, tomato: { flower: '#E8694A' }, brinjal: { flower: '#8E6BB3' },
};

const PLOT = 36;         // world units per side
const ROWS = 46;         // plants per row and rows
const RAIN_N = 1600;

export class FieldScene {
  constructor() {
    this.renderer = null; this.container = null; this.raf = 0; this.t = 0; this.paused = false;
    this.rec = { canopy: 0.05, water: 0.6, stress: 0, rain: 0, stage: 'ini', tmax: 30 };
    this.target = { ...this.rec };
    this.crop = { id: 'rice', look: { ...LOOK.cereal, ...OVERRIDE.rice } };
    this.clock = new THREE.Clock();
  }

  mount(container, { autoRotate = false, interactive = true } = {}) {
    this.container = container;
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    container.append(renderer.domElement);
    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0f1a14, 60, 150);
    this.scene = scene;

    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 400);
    camera.position.set(30, 19, 36);
    this.camera = camera;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.06;
    controls.maxPolarAngle = 1.42; controls.minDistance = 14; controls.maxDistance = 95;
    controls.target.set(0, 0.6, 0);
    controls.autoRotate = autoRotate; controls.autoRotateSpeed = 0.35;
    controls.enabled = interactive; controls.enablePan = false;
    this.controls = controls;

    this.field = new THREE.Group();
    scene.add(this.field);
    this.buildSky();
    this.buildLights();
    this.buildGround();
    this.buildBund();
    this.buildPlants();
    this.buildRain();
    this.buildWaterSheet();

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.loop();
    return this;
  }

  buildSky() {
    const geo = new THREE.SphereGeometry(180, 24, 12);
    const mat = new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false,
      uniforms: { top: { value: new THREE.Color('#3E7FB8') }, bottom: { value: new THREE.Color('#EAD3A6') }, grey: { value: 0.0 } },
      vertexShader: 'varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `uniform vec3 top; uniform vec3 bottom; uniform float grey; varying vec3 vP;
        void main(){ float h = normalize(vP).y; float t = smoothstep(-0.02, 0.38, h); vec3 c = mix(bottom, top, t);
        c = mix(c, vec3(0.32,0.36,0.38) * (0.7 + 0.3*t), grey); gl_FragColor = vec4(c, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
    });
    this.sky = new THREE.Mesh(geo, mat);
    this.scene.add(this.sky);
  }

  buildLights() {
    this.hemi = new THREE.HemisphereLight(0xcfe3ff, 0x4a3b28, 0.55);
    this.scene.add(this.hemi);
    const sun = new THREE.DirectionalLight(0xfff1d6, 2.2);
    sun.position.set(28, 34, 12);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const s = 30; Object.assign(sun.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 5, far: 120 });
    sun.shadow.bias = -0.0008;
    this.sun = sun;
    this.scene.add(sun, sun.target);
  }

  buildGround() {
    // Furrow texture: light/dark stripes along rows, with fine grain.
    const c = document.createElement('canvas'); c.width = c.height = 512;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#7a5b3c'; ctx.fillRect(0, 0, 512, 512);
    for (let i = 0; i < 46; i++) { ctx.fillStyle = i % 2 ? 'rgba(0,0,0,0.16)' : 'rgba(255,255,255,0.05)'; ctx.fillRect(0, i * (512 / 46), 512, 512 / 92); }
    for (let i = 0; i < 6000; i++) { ctx.fillStyle = `rgba(${Math.random() > 0.5 ? 255 : 0},${Math.random() > 0.5 ? 240 : 0},0,0.04)`; ctx.fillRect(Math.random() * 512, Math.random() * 512, 2, 2); }
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    this.groundMat = new THREE.MeshStandardMaterial({ map: tex, color: new THREE.Color('#a07a52'), roughness: 0.95, metalness: 0 });
    const plot = new THREE.Mesh(new THREE.PlaneGeometry(PLOT, PLOT), this.groundMat);
    plot.rotation.x = -Math.PI / 2; plot.receiveShadow = true;
    this.field.add(plot);
    // surrounding land, gently undulating and darker
    const g = new THREE.PlaneGeometry(300, 300, 60, 60);
    const pos = g.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i);
      const d = Math.max(Math.abs(x), Math.abs(y));
      pos.setZ(i, d > PLOT / 2 + 3 ? (Math.sin(x * 0.12) * Math.cos(y * 0.09)) * 0.9 - 0.25 : -0.25);
    }
    g.computeVertexNormals();
    const land = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: '#2f4a2b', roughness: 1 }));
    land.rotation.x = -Math.PI / 2; land.position.y = -0.02; land.receiveShadow = true;
    this.scene.add(land);
  }

  buildBund() {
    const mat = new THREE.MeshStandardMaterial({ color: '#5a4128', roughness: 1 });
    const half = PLOT / 2 + 0.5;
    const mk = (w, d, x, z) => { const m = new THREE.Mesh(new THREE.BoxGeometry(w, 0.5, d), mat); m.position.set(x, 0.25, z); m.castShadow = m.receiveShadow = true; return m; };
    this.field.add(mk(PLOT + 2, 1, 0, half), mk(PLOT + 2, 1, 0, -half), mk(1, PLOT + 2, half, 0), mk(1, PLOT + 2, -half, 0));
    // marigold border: the signature of an Indian field edge
    const n = 176;
    const geo = new THREE.IcosahedronGeometry(0.22, 1);
    const mm = new THREE.MeshStandardMaterial({ color: '#F2B33D', roughness: 0.6, emissive: '#5a3c05', emissiveIntensity: 0.35 });
    const inst = new THREE.InstancedMesh(geo, mm, n);
    const m4 = new THREE.Matrix4();
    for (let i = 0; i < n; i++) {
      const t = i / n * 4, side = Math.floor(t), f = t - side, p = -half + f * (PLOT + 1);
      const x = side === 0 ? p : side === 1 ? half : side === 2 ? -p : -half;
      const z = side === 0 ? -half : side === 1 ? p : side === 2 ? half : -p;
      m4.makeTranslation(x + (Math.random() - 0.5) * 0.3, 0.62 + Math.random() * 0.12, z + (Math.random() - 0.5) * 0.3);
      inst.setMatrixAt(i, m4);
    }
    inst.castShadow = true;
    this.field.add(inst);
    this.marigolds = inst;
  }

  plantGeometry(shape) {
    const stem = new THREE.CylinderGeometry(0.025, 0.04, 0.7, 5); stem.translate(0, 0.35, 0);
    let top;
    if (shape === 'grass') { top = new THREE.ConeGeometry(0.22, 1.0, 5); top.translate(0, 0.5, 0); }
    else if (shape === 'tall') { top = new THREE.ConeGeometry(0.28, 1.0, 6); top.translate(0, 0.5, 0); }
    else if (shape === 'broad') { top = new THREE.SphereGeometry(0.42, 7, 5); top.scale(1, 0.55, 1); top.translate(0, 0.42, 0); }
    else { top = new THREE.IcosahedronGeometry(0.38, 1); top.translate(0, 0.5, 0); }
    const geo = mergeGeometries([stem, top], false);
    geo.computeVertexNormals();
    return geo;
  }

  buildPlants() {
    if (this.plants) { this.field.remove(this.plants); this.plants.geometry.dispose(); }
    const n = ROWS * ROWS;
    const geo = this.plantGeometry(this.crop.look.shape);
    const mat = new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0, flatShading: true });
    const inst = new THREE.InstancedMesh(geo, mat, n);
    inst.castShadow = true; inst.receiveShadow = true;
    inst.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    const spacing = PLOT / ROWS;
    this.base = new Float32Array(n * 5); // x, z, scale, phase, rot
    for (let i = 0; i < n; i++) {
      const r = Math.floor(i / ROWS), c = i % ROWS;
      this.base.set([
        -PLOT / 2 + spacing / 2 + c * spacing + (Math.random() - 0.5) * spacing * 0.35,
        -PLOT / 2 + spacing / 2 + r * spacing + (Math.random() - 0.5) * spacing * 0.2,
        0.8 + Math.random() * 0.4, Math.random() * Math.PI * 2, Math.random() * Math.PI * 2,
      ], i * 5);
    }
    this.field.add(inst);
    this.plants = inst;
    this.colorPlants(true);
  }

  buildRain() {
    const g = new THREE.BufferGeometry();
    const p = new Float32Array(RAIN_N * 3);
    for (let i = 0; i < RAIN_N; i++) p.set([(Math.random() - 0.5) * 70, Math.random() * 40, (Math.random() - 0.5) * 70], i * 3);
    g.setAttribute('position', new THREE.BufferAttribute(p, 3));
    this.rain = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xbfe0ff, size: 0.12, transparent: true, opacity: 0, depthWrite: false }));
    this.scene.add(this.rain);
  }

  buildWaterSheet() {
    this.water = new THREE.Mesh(new THREE.PlaneGeometry(PLOT - 0.4, PLOT - 0.4), new THREE.MeshStandardMaterial({ color: '#4d86a8', transparent: true, opacity: 0, roughness: 0.15, metalness: 0.1 }));
    this.water.rotation.x = -Math.PI / 2; this.water.position.y = 0.06;
    this.field.add(this.water);
  }

  // Scale the rendered field with the real area: 1 ha is the reference; big US fields read as big.
  setArea(ha) {
    const f = Math.min(3.2, Math.max(0.55, Math.sqrt(Math.max(0.05, ha || 1))));
    this.field.scale.set(f, 1, f);
    const d = 46 * f + 6;
    this.controls.maxDistance = Math.max(95, d * 2.2);
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    this.camera.position.copy(this.controls.target).addScaledVector(dir, d);
    const s = 30 * f;
    Object.assign(this.sun.shadow.camera, { left: -s, right: s, top: s, bottom: -s });
    this.sun.shadow.camera.updateProjectionMatrix();
    this.scene.fog.near = 60 * f; this.scene.fog.far = 150 * f;
  }

  setCrop(id, category) {
    const look = { ...(LOOK[category] || LOOK.cereal), ...(OVERRIDE[id] || {}) };
    const changed = look.shape !== this.crop.look.shape;
    this.crop = { id, look };
    if (changed && this.plants) this.buildPlants(); else this.colorPlants(true);
  }

  setDay(rec, { immediate = false } = {}) {
    this.target = { canopy: rec.canopy ?? 0.05, water: rec.water ?? 0.6, stress: rec.stress ?? 0, rain: rec.rain ?? 0, stage: rec.stage || 'ini', tmax: rec.tmax ?? 30, progress: rec.progress ?? 0 };
    if (immediate) this.rec = { ...this.target };
  }

  colorPlants(force = false) {
    const { seed, mature, flower } = this.crop.look;
    const a = new THREE.Color(seed), b = new THREE.Color(mature), f = new THREE.Color(flower), dry = new THREE.Color('#B59B4C');
    const r = this.rec;
    const growth = Math.min(1, Math.max(0, (r.progress ?? 0) - 0.55) / 0.45);
    const c = a.clone().lerp(b, growth);
    if (r.stage === 'mid') c.lerp(f, 0.3);
    c.lerp(dry, Math.min(1, r.stress * 1.6));
    const tmp = new THREE.Color();
    const n = this.plants.count;
    for (let i = 0; i < n; i++) {
      const v = 0.9 + ((i * 7919) % 100) / 500; // deterministic per-plant variation
      tmp.copy(c).multiplyScalar(v);
      this.plants.setColorAt(i, tmp);
    }
    this.plants.instanceColor.needsUpdate = true;
  }

  resize() {
    if (!this.renderer || !this.container) return;
    const w = this.container.clientWidth || 1, hgt = this.container.clientHeight || 1;
    this.renderer.setSize(w, hgt, false);
    this.renderer.domElement.style.width = '100%'; this.renderer.domElement.style.height = '100%';
    this.camera.aspect = w / hgt; this.camera.updateProjectionMatrix();
  }

  loop() {
    this.raf = requestAnimationFrame(() => this.loop());
    if (this.paused) return;
    const dt = Math.min(0.05, this.clock.getDelta());
    this.t += dt;
    // ease toward the target day
    const k = 1 - Math.pow(0.001, dt);
    const r = this.rec, tg = this.target;
    r.canopy += (tg.canopy - r.canopy) * k; r.water += (tg.water - r.water) * k; r.stress += (tg.stress - r.stress) * k;
    r.rain += (tg.rain - r.rain) * k; r.tmax += (tg.tmax - r.tmax) * k; r.progress = (r.progress ?? 0) + ((tg.progress ?? 0) - (r.progress ?? 0)) * k;
    r.stage = tg.stage;

    // plants
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), e = new THREE.Euler();
    const h = this.crop.look.h;
    const wind = 0.05 + Math.min(0.2, r.rain * 0.01);
    const n = this.plants.count;
    for (let i = 0; i < n; i++) {
      const o = i * 5;
      const sc = this.base[o + 2] * (0.08 + r.canopy * h);
      const sway = Math.sin(this.t * 1.6 + this.base[o + 3]) * wind * r.canopy;
      e.set(sway, this.base[o + 4], sway * 0.6);
      q.setFromEuler(e);
      p.set(this.base[o], 0, this.base[o + 1]);
      s.set(0.6 + r.canopy * 0.6, sc, 0.6 + r.canopy * 0.6);
      m4.compose(p, q, s);
      this.plants.setMatrixAt(i, m4);
    }
    this.plants.instanceMatrix.needsUpdate = true;
    if ((this.frame = (this.frame || 0) + 1) % 6 === 0) this.colorPlants();

    // soil & water
    this.groundMat.color.set('#a8804f').lerp(new THREE.Color('#4a3320'), Math.min(0.85, r.water));
    const flooded = this.crop.id === 'rice' && r.water > 0.92 && r.canopy > 0.1;
    this.water.material.opacity += (((flooded ? 0.55 : 0) - this.water.material.opacity)) * k;

    // weather
    const rainy = Math.min(1, r.rain / 12);
    this.rain.material.opacity = rainy * 0.8;
    if (rainy > 0.02) {
      const pos = this.rain.geometry.attributes.position;
      for (let i = 0; i < RAIN_N; i++) { let y = pos.getY(i) - dt * (28 + rainy * 20); if (y < 0) y = 40; pos.setY(i, y); }
      pos.needsUpdate = true;
    }
    this.sky.material.uniforms.grey.value += (rainy - this.sky.material.uniforms.grey.value) * k;
    this.sun.intensity = 2.2 - rainy * 1.5; this.hemi.intensity = 0.55 + rainy * 0.3;
    const heat = Math.max(0, Math.min(1, (r.tmax - 34) / 8));
    this.sky.material.uniforms.bottom.value.set('#EAD3A6').lerp(new THREE.Color('#F3D9A4'), heat);
    this.scene.fog.color.set('#0f1a14').lerp(new THREE.Color('#3a4a4d'), rainy * 0.5);
    // sun arc follows season progress
    const ang = 0.55 + (r.progress ?? 0) * 1.4;
    this.sun.position.set(Math.cos(ang) * 40, 22 + Math.sin(ang) * 16, 14);
    // marigolds bob
    if (this.marigolds) this.marigolds.position.y = Math.sin(this.t * 1.2) * 0.02;

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  setAutoRotate(v) { if (this.controls) this.controls.autoRotate = v; }
  pause(v) { this.paused = v; if (!v) this.clock.getDelta(); }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.resizeObserver?.disconnect();
    this.controls?.dispose();
    this.scene?.traverse((o) => { o.geometry?.dispose?.(); if (o.material) { (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { m.map?.dispose?.(); m.dispose?.(); }); } });
    this.renderer?.dispose();
    this.renderer?.domElement?.remove();
    this.renderer = null;
  }
}

// A synthetic season for the landing page, so the twin moves before any plot is set.
export function demoSeason(days = 120) {
  const out = [];
  let water = 0.7;
  for (let i = 0; i < days; i++) {
    const f = i / (days - 1);
    const stage = f < 0.2 ? 'ini' : f < 0.45 ? 'dev' : f < 0.8 ? 'mid' : 'late';
    const canopy = f < 0.45 ? 0.05 + 0.95 * (f / 0.45) ** 2 * (3 - 2 * f / 0.45) : f < 0.8 ? 1 : 1 - 0.35 * (f - 0.8) / 0.2;
    const rain = (i % 9 < 2 && f < 0.7) ? 6 + Math.random() * 30 : (Math.random() < 0.1 ? Math.random() * 4 : 0);
    water = Math.max(0.15, Math.min(1, water + rain / 80 - 0.035 * canopy - 0.005));
    out.push({ day: i + 1, date: '', stage, canopy, rain: +rain.toFixed(1), water: +water.toFixed(2), stress: water < 0.35 ? (0.35 - water) * 2 : 0, tmax: 27 + Math.sin(f * 4) * 5 + (rain ? -3 : 0), progress: f });
  }
  return out;
}
