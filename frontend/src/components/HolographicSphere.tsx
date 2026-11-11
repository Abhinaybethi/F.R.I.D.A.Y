import { useEffect, useMemo, useRef, type CSSProperties } from "react";

import { useDashboard } from "../state/DashboardContext";

// ---------------------------------------------------------------
// Neural Hologram — canvas-2D port of the supplied "Neural Hologram"
// reference. A two-lobed brain of neurons is wired with curved
// synapses, wrapped in electron shells, a shell of glowing data
// fragments and a burning nucleus. Voice phases raise the firing
// rate, rotation speed and bloom; the palette matches the reference
// (gold by default, with blue and purple variants available).
//
// The previous WebGL sphere is intentionally gone: this is a pure
// Canvas2D scene with no three.js dependency.
// ---------------------------------------------------------------

export type HologramTheme = "gold" | "blue" | "purple";

export const DEFAULT_HOLOGRAM_THEME: HologramTheme = "gold";

interface Palette {
  c: [string, string];
  sg: [string, string];
  amb: string;
}

const THEMES: Record<HologramTheme, Palette> = {
  blue: {
    c: ["#3d8bff", "#7fe0ff"],
    sg: ["#bfe6ff", "#ffffff"],
    amb: "40,120,255",
  },
  purple: {
    c: ["#b648ff", "#ff8c1a"],
    sg: ["#f2c4ff", "#ffd9a8"],
    amb: "170,60,255",
  },
  gold: {
    c: ["#ff8a14", "#ffc94a"],
    sg: ["#ffe7a8", "#fff6dc"],
    amb: "255,140,20",
  },
};

const TAU = Math.PI * 2;
const NODE_COUNT = 260;
const FRAGMENT_COUNT = 2400;
const MAX_SIGNALS = 520;

/** Voice phases → idle/active energy (0–1). Unknown stages stay calm. */
const PHASE_ENERGY: Record<string, number> = {
  STANDBY: 0.2,
  IDLE: 0.2,
  ACTIVATING: 0.85,
  ACTIVATION: 0.85,
  WAKE_LISTENING: 0.35,
  LISTENING: 0.55,
  COMMAND_LISTENING: 0.55,
  TRANSCRIBING: 0.75,
  PROCESSING: 0.78,
  THINKING: 0.78,
  WAITING_FOR_CONFIRMATION: 0.6,
  EXECUTING: 0.92,
  RESPONDING: 1,
  SPEAKING: 1,
  INTERRUPTED: 1,
  ERROR: 1,
};

function phaseEnergy(phase: string | undefined): number {
  if (!phase) return 0.2;
  return PHASE_ENERGY[phase.toUpperCase()] ?? 0.2;
}

interface HologramNode {
  x: number;
  y: number;
  z: number;
  ph: [number, number, number];
  sp: number;
  type: 0 | 1;
  a: number;
  ref: number;
  edges: HologramEdge[];
  den: Array<[number, number, number]>;
  X: number;
  Y: number;
  Z: number;
  sx: number;
  sy: number;
  sz: number;
  ss: number;
  core?: boolean;
}

interface HologramEdge {
  a: HologramNode;
  b: HologramNode;
  len: number;
  off: [number, number, number];
  cx: number;
  cy: number;
  band: number;
}

interface HologramSignal {
  e: HologramEdge;
  from: 0 | 1;
  t: number;
  sp: number;
}

interface HologramFragment {
  a: number;
  b: number;
  r: number;
  len: number;
  lat: boolean;
  om: number;
  ty: 0 | 1;
}

interface NucleusParticle {
  x: number;
  y: number;
  z: number;
  p: number;
  t: 0 | 1;
}

interface ElectronShell {
  r: number;
  n: number;
  sp: number;
  tx: number;
  tz: number;
}

interface HologramModel {
  nodes: HologramNode[];
  edges: HologramEdge[];
  core: HologramNode;
  nucleus: NucleusParticle[];
  fragments: HologramFragment[];
  shells: ElectronShell[];
}

/** Deterministic pseudo-random so the neural graph is stable per mount. */
function makeRandom(seed = 11): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function createModel(): HologramModel {
  const rnd = makeRandom();
  const nodes: HologramNode[] = [];

  // Neurons arranged as a two-lobed brain shape.
  while (nodes.length < NODE_COUNT) {
    let x = rnd() * 2 - 1;
    let y = rnd() * 2 - 1;
    let z = rnd() * 2 - 1;
    const length = Math.hypot(x, y, z);
    if (length > 1 || length < 0.05) continue;

    if (rnd() < 0.6) {
      const k = (0.82 + 0.18 * rnd()) / length;
      x *= k;
      y *= k;
      z *= k;
    }
    x *= 1.15;
    y *= y > 0 ? 0.7 : 0.85;
    if (Math.abs(x) < 0.07) continue;
    x += (x < 0 ? -1 : 1) * 0.05;

    const den: Array<[number, number, number]> = [];
    for (let index = 0; index < 5; index += 1) {
      const a = rnd() * TAU;
      const b = Math.acos(rnd() * 2 - 1);
      const l = 0.05 + rnd() * 0.09;
      den.push([
        Math.sin(b) * Math.cos(a) * l,
        Math.cos(b) * l,
        Math.sin(b) * Math.sin(a) * l,
      ]);
    }

    nodes.push({
      x,
      y,
      z,
      ph: [rnd() * TAU, rnd() * TAU, rnd() * TAU],
      sp: 0.3 + rnd() * 0.5,
      type: rnd() < 0.62 ? 0 : 1,
      a: 0,
      ref: 0,
      edges: [],
      den,
      X: 0,
      Y: 0,
      Z: 0,
      sx: 0,
      sy: 0,
      sz: 0,
      ss: 1,
    });
  }

  const edges: HologramEdge[] = [];
  const seen = new Set<number>();

  const link = (i: number, j: number) => {
    const key = Math.min(i, j) * (NODE_COUNT + 1) + Math.max(i, j);
    if (seen.has(key) || i === j) return;
    seen.add(key);

    const a = nodes[i];
    const b = nodes[j];
    const edge: HologramEdge = {
      a,
      b,
      len: Math.max(0.12, Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)),
      off: [(rnd() - 0.5) * 0.25, (rnd() - 0.5) * 0.25, (rnd() - 0.5) * 0.25],
      cx: 0,
      cy: 0,
      band: 0,
    };
    edges.push(edge);
    a.edges.push(edge);
    b.edges.push(edge);
  };

  for (let i = 0; i < NODE_COUNT; i += 1) {
    const nearest: Array<[number, number]> = nodes.map((node, j) => [
      Math.hypot(node.x - nodes[i].x, node.y - nodes[i].y, node.z - nodes[i].z),
      j,
    ]);
    nearest.sort((p, q) => p[0] - q[0]);
    for (let k = 1; k <= 3; k += 1) link(i, nearest[k][1]);
  }
  for (let i = 0; i < 30; i += 1) {
    link(Math.floor(rnd() * NODE_COUNT), Math.floor(rnd() * NODE_COUNT));
  }

  // Atom nucleus at the centre, wired to the network.
  const core: HologramNode = {
    x: 0,
    y: 0,
    z: 0,
    ph: [0, 0, 0],
    sp: 0,
    type: 1,
    a: 0,
    ref: 0,
    edges: [],
    den: [],
    X: 0,
    Y: 0,
    Z: 0,
    sx: 0,
    sy: 0,
    sz: 0,
    ss: 1,
    core: true,
  };
  nodes.push(core);
  for (let i = 0; i < 22; i += 1) {
    link(NODE_COUNT, Math.floor(rnd() * NODE_COUNT));
  }

  const nucleus: NucleusParticle[] = [];
  for (let i = 0; i < 16; i += 1) {
    const a = rnd() * TAU;
    const b = Math.acos(rnd() * 2 - 1);
    const l = 0.03 + rnd() * 0.06;
    nucleus.push({
      x: Math.sin(b) * Math.cos(a) * l,
      y: Math.cos(b) * l,
      z: Math.sin(b) * Math.sin(a) * l,
      p: rnd() * TAU,
      t: (i % 2) as 0 | 1,
    });
  }

  const fragments: HologramFragment[] = [];
  for (let i = 0; i < FRAGMENT_COUNT; i += 1) {
    fragments.push({
      a: rnd() * TAU,
      b: Math.acos(rnd() * 2 - 1),
      r: 0.86 + rnd() * 0.3,
      len: 0.01 + rnd() * rnd() * 0.1,
      lat: rnd() < 0.5,
      om: (rnd() < 0.5 ? 1 : -1) * (0.02 + rnd() * 0.09),
      ty: rnd() < 0.72 ? 0 : 1,
    });
  }

  const shells: ElectronShell[] = [
    { r: 0.26, n: 2, sp: 2.4, tx: 0.3, tz: 0 },
    { r: 0.42, n: 3, sp: 1.7, tx: 1.0, tz: 0.9 },
    { r: 0.58, n: 4, sp: -1.3, tx: 0.6, tz: 2.0 },
    { r: 0.74, n: 5, sp: 1.0, tx: 1.3, tz: -0.8 },
  ];

  return { nodes, edges, core, nucleus, fragments, shells };
}

interface HolographicSphereProps {
  /** Current voice phase (accepts backend stage names such as "PROCESSING"). */
  phase?: string;
  /** Rendered size in pixels. The overlay overrides this with its own size. */
  size?: number;
  /**
   * Explicit activity level (0–1). When omitted the hologram derives it from
   * the voice phase and the number of running tasks.
   */
  activityIntensity?: number;
  /** Palette from the reference. Defaults to the gold hologram. */
  theme?: HologramTheme;
  /** Enable drag-to-rotate and click-to-fire. Off for the passive overlay. */
  interactive?: boolean;
}

export function HolographicSphere({
  phase: phaseProp,
  size = 128,
  activityIntensity,
  theme = DEFAULT_HOLOGRAM_THEME,
  interactive = false,
}: HolographicSphereProps) {
  const { voice, activity } = useDashboard();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const model = useMemo(createModel, []);

  const phase = phaseProp ?? voice?.state;
  const taskIntensity = activityIntensity ?? (activity?.length ?? 0) / 10;
  const energy = Math.max(0.15, Math.min(1, Math.max(taskIntensity, phaseEnergy(phase))));

  // The animation loop reads these refs, so prop changes never restart it.
  const energyRef = useRef(energy);
  const themeRef = useRef(theme);
  energyRef.current = energy;
  themeRef.current = theme;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const makeLayer = () => document.createElement("canvas");
    const holo = makeLayer();
    const hx = holo.getContext("2d");
    const b1 = makeLayer();
    const b1x = b1.getContext("2d");
    const b2 = makeLayer();
    const b2x = b2.getContext("2d");
    if (!hx || !b1x || !b2x) return;

    const signals: HologramSignal[] = [];
    const fragmentBuckets = [0, 1, 2, 3].map(
      () => new Float32Array(FRAGMENT_COUNT * 4),
    );
    const fragmentCounts = [0, 0, 0, 0];

    let width = 1;
    let height = 1;
    let radius = 1;
    let centerX = 0;
    let centerY = 0;
    let unit = 1;
    let yaw = 0;
    let pitch = 0.25;
    let dragging = false;
    let moved = false;
    let lastX = 0;
    let lastY = 0;
    let animation = 0;
    let lastFrame = 0;

    // Projection state shared by every drawing layer (mirrors the reference).
    let cyw = 1;
    let syw = 0;
    let cp = 1;
    let sp = 1;
    let px = 0;
    let py = 0;
    let depth = 0;
    let scale = 1;

    const setCamera = () => {
      cyw = Math.cos(yaw);
      syw = Math.sin(yaw);
      cp = Math.cos(pitch);
      sp = Math.sin(pitch);
    };

    const project = (x: number, y: number, z: number) => {
      const x1 = x * cyw + z * syw;
      const z1 = -x * syw + z * cyw;
      const y1 = y * cp - z1 * sp;
      const z2 = y * sp + z1 * cp;
      scale = 3.4 / (3.4 - z2);
      px = centerX + x1 * scale * radius;
      py = centerY + y1 * scale * radius;
      depth = z2;
    };

    const orbit = (
      orbitRadius: number,
      angle: number,
      tiltX: number,
      tiltZ: number,
    ): [number, number, number] => {
      const x = Math.cos(angle) * orbitRadius;
      const z = Math.sin(angle) * orbitRadius;
      const y1 = -z * Math.sin(tiltX);
      const z1 = z * Math.cos(tiltX);
      return [
        x * Math.cos(tiltZ) - y1 * Math.sin(tiltZ),
        x * Math.sin(tiltZ) + y1 * Math.cos(tiltZ),
        z1,
      ];
    };

    const fire = (node: HologramNode) => {
      if (node.ref > 0) return;
      node.a = 1;
      node.ref = 0.6;
      for (const edge of node.edges) {
        if (signals.length >= MAX_SIGNALS) break;
        signals.push({
          e: edge,
          from: edge.a === node ? 0 : 1,
          t: 0,
          sp: 0.5 + Math.random() * 0.4,
        });
      }
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      width = Math.max(1, Math.round(rect.width * dpr));
      height = Math.max(1, Math.round(rect.height * dpr));
      canvas.width = width;
      canvas.height = height;
      holo.width = width;
      holo.height = height;
      b1.width = Math.max(1, width >> 2);
      b1.height = Math.max(1, height >> 2);
      b2.width = Math.max(1, Math.floor(width / 12));
      b2.height = Math.max(1, Math.floor(height / 12));
      radius = Math.min(width, height) * 0.27;
      unit = radius / 330;
      centerX = width / 2;
      centerY = height * 0.48;
    };

    const draw = (time: number, delta: number) => {
      const palette = THEMES[themeRef.current] ?? THEMES.gold;
      const energyNow = energyRef.current;
      const brightness = 0.75 + energyNow * 0.35;

      // Simulation: activity decay, spontaneous firing, signal travel.
      for (const node of model.nodes) {
        node.a = Math.max(0, node.a - delta * 1.5);
        node.ref = Math.max(0, node.ref - delta);
      }
      if (Math.random() < delta * (2.6 + energyNow * 7.5)) {
        fire(model.nodes[Math.floor(Math.random() * NODE_COUNT)]);
      }
      if (Math.random() < delta * (0.5 + energyNow * 1.2)) {
        fire(model.core);
      }
      for (let i = signals.length - 1; i >= 0; i -= 1) {
        const signal = signals[i];
        signal.t += (delta * signal.sp * (0.7 + energyNow * 0.6)) / signal.e.len;
        if (signal.t >= 1) {
          const target = signal.from ? signal.e.a : signal.e.b;
          target.a = Math.min(1, target.a + 0.5);
          if (target.ref <= 0 && (target.a >= 0.95 || Math.random() < 0.3)) {
            fire(target);
          }
          signals.splice(i, 1);
        }
      }

      if (!dragging) yaw += delta * (0.12 + energyNow * 0.2);
      pitch += Math.sin(time * 0.2) * delta * 0.02;
      setCamera();

      // Living drift on every node, then project once for all layers.
      for (const node of model.nodes) {
        node.X = node.x + Math.sin(time * node.sp + node.ph[0]) * 0.035;
        node.Y = node.y + Math.sin(time * node.sp * 1.2 + node.ph[1]) * 0.035;
        node.Z = node.z + Math.sin(time * node.sp * 0.9 + node.ph[2]) * 0.035;
        project(node.X, node.Y, node.Z);
        node.sx = px;
        node.sy = py;
        node.sz = depth;
        node.ss = scale;
      }

      hx.clearRect(0, 0, width, height);
      hx.globalCompositeOperation = "lighter";
      hx.lineCap = "round";
      hx.setLineDash([]);

      // Orbit rings (hologram frame).
      hx.strokeStyle = palette.c[1];
      hx.lineWidth = unit;
      hx.setLineDash([6 * unit, 10 * unit]);
      hx.globalAlpha = 0.3 * brightness;
      for (let ring = 0; ring < 3; ring += 1) {
        hx.beginPath();
        const ringRadius = 1.45 + ring * 0.12;
        const tilt = ring * 0.7 + time * 0.05 * (ring + 1);
        for (let i = 0; i <= 90; i += 1) {
          const angle = (i / 90) * TAU;
          const x = Math.cos(angle) * ringRadius;
          const z = Math.sin(angle) * ringRadius;
          project(x, z * Math.sin(tilt) * 0.4, z * Math.cos(tilt) * 0.4);
          if (i) hx.lineTo(px, py);
          else hx.moveTo(px, py);
        }
        hx.stroke();
      }
      hx.setLineDash([]);

      // Outer shell of glowing data fragments.
      fragmentCounts[0] = 0;
      fragmentCounts[1] = 0;
      fragmentCounts[2] = 0;
      fragmentCounts[3] = 0;
      for (let i = 0; i < FRAGMENT_COUNT; i += 1) {
        const fragment = model.fragments[i];
        const spin = time * fragment.om;
        const c0 = Math.cos(spin);
        const s0 = Math.sin(spin);
        const sb = Math.sin(fragment.b);
        const a2 = fragment.lat
          ? fragment.a + fragment.len / Math.max(0.2, fragment.r * sb)
          : fragment.a;
        const b2 = fragment.lat ? fragment.b : fragment.b + fragment.len / fragment.r;
        const x1 = fragment.r * sb * Math.cos(fragment.a) * 1.18;
        const y1 = fragment.r * Math.cos(fragment.b) * 0.92;
        const z1 = fragment.r * sb * Math.sin(fragment.a);
        const x2 = fragment.r * Math.sin(b2) * Math.cos(a2) * 1.18;
        const y2 = fragment.r * Math.cos(b2) * 0.92;
        const z2 = fragment.r * Math.sin(b2) * Math.sin(a2);

        project(x1 * c0 + z1 * s0, y1, -x1 * s0 + z1 * c0);
        const ax = px;
        const ay = py;
        const az = depth;
        project(x2 * c0 + z2 * s0, y2, -x2 * s0 + z2 * c0);

        const bucket = fragment.ty * 2 + (az > 0 ? 1 : 0);
        const array = fragmentBuckets[bucket];
        let count = fragmentCounts[bucket];
        array[count] = ax;
        array[count + 1] = ay;
        array[count + 2] = px;
        array[count + 3] = py;
        count += 4;
        fragmentCounts[bucket] = count;
      }
      for (let bucket = 0; bucket < 4; bucket += 1) {
        const foreground = bucket & 1;
        const array = fragmentBuckets[bucket];
        hx.strokeStyle = bucket >> 1 ? palette.sg[0] : palette.c[0];
        hx.lineWidth = (foreground ? 1.5 : 1) * unit;
        hx.globalAlpha =
          (foreground ? 0.85 : 0.35) *
          (0.8 + 0.2 * Math.sin(time * 5 + bucket * 1.7)) *
          brightness;
        hx.beginPath();
        for (let i = 0; i < fragmentCounts[bucket]; i += 4) {
          hx.moveTo(array[i], array[i + 1]);
          hx.lineTo(array[i + 2], array[i + 3]);
        }
        hx.stroke();
      }

      // Layer 1: nested wireframe shells.
      hx.lineWidth = 0.8 * unit;
      (
        [
          [0.38, 0.5, 0],
          [0.64, -0.35, 1],
          [1.3, 0.12, 0],
        ] as const
      ).forEach(([shellRadius, spinSpeed, colour]) => {
        hx.strokeStyle = palette.c[colour];
        hx.globalAlpha = 0.16 * brightness;
        hx.beginPath();
        const spin = time * spinSpeed;
        const c0 = Math.cos(spin);
        const s0 = Math.sin(spin);
        const ring = (point: (angle: number) => [number, number, number]) => {
          for (let i = 0; i <= 40; i += 1) {
            const p = point((i / 40) * TAU);
            const x = p[0] * c0 + p[2] * s0;
            const z = -p[0] * s0 + p[2] * c0;
            project(x, p[1], z);
            if (i) hx.lineTo(px, py);
            else hx.moveTo(px, py);
          }
        };
        for (let k = 1; k < 6; k += 1) {
          const latitude = -Math.PI / 2 + (k * Math.PI) / 6;
          const ringRadius = Math.cos(latitude) * shellRadius;
          const yy = Math.sin(latitude) * shellRadius;
          ring((angle) => [
            Math.cos(angle) * ringRadius,
            yy,
            Math.sin(angle) * ringRadius,
          ]);
        }
        for (let k = 0; k < 8; k += 1) {
          const longitude = (k * Math.PI) / 8;
          ring((angle) => [
            Math.cos(angle) * Math.cos(longitude) * shellRadius,
            Math.sin(angle) * shellRadius,
            Math.cos(angle) * Math.sin(longitude) * shellRadius,
          ]);
        }
        hx.stroke();
      });

      // Layer 2: electron shells with comet trails.
      model.shells.forEach((shell, index) => {
        const tiltZ =
          shell.tz + time * 0.08 * (index + 1) * (index % 2 ? -1 : 1);
        const direction = shell.sp < 0 ? -1 : 1;
        hx.strokeStyle = palette.c[index % 2];
        hx.lineWidth = 1.1 * unit;
        hx.globalAlpha = 0.4 * brightness;
        hx.beginPath();
        for (let k = 0; k <= 72; k += 1) {
          const p = orbit(shell.r, (k / 72) * TAU, shell.tx, tiltZ);
          project(p[0], p[1], p[2]);
          if (k) hx.lineTo(px, py);
          else hx.moveTo(px, py);
        }
        hx.stroke();

        for (let electron = 0; electron < shell.n; electron += 1) {
          const start = (time * shell.sp * 0.5) + (electron * TAU) / shell.n;
          let previousX = 0;
          let previousY = 0;
          let headX = 0;
          let headY = 0;
          let headScale = 1;
          hx.strokeStyle = palette.sg[index % 2];
          hx.lineWidth = 2.2 * unit;
          for (let k = 0; k <= 10; k += 1) {
            const p = orbit(shell.r, start - k * 0.07 * direction, shell.tx, tiltZ);
            project(p[0], p[1], p[2]);
            if (k === 0) {
              headX = px;
              headY = py;
              headScale = scale;
            } else {
              hx.globalAlpha = 0.8 * (1 - k / 11) * brightness;
              hx.beginPath();
              hx.moveTo(previousX, previousY);
              hx.lineTo(px, py);
              hx.stroke();
            }
            previousX = px;
            previousY = py;
          }
          hx.globalAlpha = 0.25 * brightness;
          hx.fillStyle = palette.c[index % 2];
          hx.beginPath();
          hx.arc(headX, headY, 10 * unit * headScale, 0, TAU);
          hx.fill();
          hx.globalAlpha = brightness;
          hx.fillStyle = "#fff";
          hx.beginPath();
          hx.arc(headX, headY, 3.6 * unit * headScale, 0, TAU);
          hx.fill();
        }
      });

      // Layer 3: nucleus (protons and neutrons).
      const coreX = model.core.sx;
      const coreY = model.core.sy;
      const coreScale = model.core.ss;
      const coreRadius = (40 + 70 * model.core.a) * unit * coreScale;
      const glow = hx.createRadialGradient(
        coreX,
        coreY,
        0,
        coreX,
        coreY,
        coreRadius,
      );
      glow.addColorStop(
        0,
        `rgba(${palette.amb},${0.45 + 0.4 * model.core.a})`,
      );
      glow.addColorStop(1, `rgba(${palette.amb},0)`);
      hx.globalAlpha = 1;
      hx.fillStyle = glow;
      hx.beginPath();
      hx.arc(coreX, coreY, coreRadius, 0, TAU);
      hx.fill();

      for (const particle of model.nucleus) {
        const c0 = Math.cos(time * 1.3 + particle.p);
        const s0 = Math.sin(time * 1.3 + particle.p);
        const pulse =
          1 + 0.12 * Math.sin(time * 4 + particle.p) + model.core.a * 0.25;
        project(
          (particle.x * c0 + particle.z * s0) * pulse,
          particle.y * pulse + Math.sin(time * 3 + particle.p) * 0.01,
          (-particle.x * s0 + particle.z * c0) * pulse,
        );
        hx.globalAlpha = 0.9 * brightness;
        hx.fillStyle = palette.c[particle.t];
        hx.beginPath();
        hx.arc(px, py, 5.5 * unit * scale, 0, TAU);
        hx.fill();
        hx.globalAlpha = (0.5 + model.core.a * 0.5) * brightness;
        hx.fillStyle = "#fff";
        hx.beginPath();
        hx.arc(px, py, 2.4 * unit * scale, 0, TAU);
        hx.fill();
      }
      hx.globalAlpha = 1;

      // Swirling energy core and sweeping arcs.
      (
        [
          [0.3, 0, 1],
          [1.2, 1.1, -1],
          [0.8, 2.3, 1],
          [1.5, 3.6, -1],
        ] as const
      ).forEach(([tiltX, tiltZ, direction], index) => {
        for (let pass = 0; pass < 2; pass += 1) {
          hx.strokeStyle = pass ? palette.sg[1] : palette.c[index % 2];
          hx.lineWidth = (pass ? 1.6 : 5) * unit;
          hx.globalAlpha = (pass ? 0.9 : 0.22) * brightness;
          hx.beginPath();
          for (let k = 0; k <= 80; k += 1) {
            const p = orbit(
              0.03 + k * 0.0035,
              k * 0.13 * direction + time * 1.6 * direction + index,
              tiltX,
              tiltZ + time * 0.2 * direction,
            );
            project(p[0], p[1], p[2]);
            if (k) hx.lineTo(px, py);
            else hx.moveTo(px, py);
          }
          hx.stroke();
        }
      });
      (
        [
          [0.52, 0.4, 0, 1],
          [0.34, 2.4, 1.3, -1],
        ] as const
      ).forEach(([orbitRadius, tiltX, tiltZ, direction], index) => {
        const start = time * 0.3 * direction + index * 2;
        for (let pass = 0; pass < 2; pass += 1) {
          hx.strokeStyle = pass ? palette.sg[0] : palette.c[1];
          hx.lineWidth = (pass ? 3.5 : 10) * unit;
          hx.globalAlpha = (pass ? 0.6 : 0.12) * brightness;
          hx.beginPath();
          for (let k = 0; k <= 60; k += 1) {
            const p = orbit(
              orbitRadius,
              start + (k / 60) * 3.6,
              tiltX,
              tiltZ,
            );
            project(p[0], p[1], p[2]);
            if (k) hx.lineTo(px, py);
            else hx.moveTo(px, py);
          }
          hx.stroke();
        }
      });
      hx.globalAlpha = 1;

      // Synapses: precompute the curve midpoints and bucket by type/depth.
      for (const edge of model.edges) {
        const a = edge.a;
        const b = edge.b;
        project(
          (a.X + b.X) / 2 + edge.off[0],
          (a.Y + b.Y) / 2 + edge.off[1],
          (a.Z + b.Z) / 2 + edge.off[2],
        );
        edge.cx = px;
        edge.cy = py;
        const z = (a.sz + b.sz) / 2;
        edge.band = z < -0.3 ? 0 : z < 0.3 ? 1 : 2;
      }

      const alphas = [0.1, 0.2, 0.38];
      for (let type = 0; type < 2; type += 1) {
        for (let band = 0; band < 3; band += 1) {
          hx.strokeStyle = palette.c[type];
          hx.lineWidth = (0.8 + band * 0.35) * unit;
          hx.globalAlpha = alphas[band] * brightness;
          hx.beginPath();
          for (const edge of model.edges) {
            if (edge.band !== band || edge.a.type !== type) continue;
            hx.moveTo(edge.a.sx, edge.a.sy);
            hx.quadraticCurveTo(edge.cx, edge.cy, edge.b.sx, edge.b.sy);
          }
          hx.stroke();
        }
      }

      // Dendrites.
      for (let type = 0; type < 2; type += 1) {
        hx.strokeStyle = palette.c[type];
        hx.lineWidth = 0.8 * unit;
        hx.globalAlpha = 0.3 * brightness;
        hx.beginPath();
        for (const node of model.nodes) {
          if (node.type !== type) continue;
          for (const dendrite of node.den) {
            project(
              node.X + dendrite[0],
              node.Y + dendrite[1],
              node.Z + dendrite[2],
            );
            hx.moveTo(node.sx, node.sy);
            hx.lineTo(px, py);
          }
        }
        hx.stroke();
      }

      // Travelling signals.
      hx.lineWidth = 2.2 * unit;
      for (const signal of signals) {
        const edge = signal.e;
        const colour = palette.sg[edge.a.type];
        const pointAt = (k: number): [number, number] => {
          const t = signal.from ? 1 - k : k;
          const m = 1 - t;
          return [
            m * m * edge.a.sx + 2 * m * t * edge.cx + t * t * edge.b.sx,
            m * m * edge.a.sy + 2 * m * t * edge.cy + t * t * edge.b.sy,
          ];
        };
        const p0 = pointAt(Math.max(0, signal.t - 0.12));
        const p1 = pointAt(Math.max(0, signal.t - 0.05));
        const p2 = pointAt(signal.t);
        hx.strokeStyle = colour;
        hx.globalAlpha = 0.9 * brightness;
        hx.beginPath();
        hx.moveTo(p0[0], p0[1]);
        hx.lineTo(p1[0], p1[1]);
        hx.lineTo(p2[0], p2[1]);
        hx.stroke();
        hx.fillStyle = "#fff";
        hx.beginPath();
        hx.arc(p2[0], p2[1], 2.4 * unit, 0, TAU);
        hx.fill();
      }

      // Somata.
      for (const node of model.nodes) {
        if (node.core) continue;
        const nodeRadius = (2.4 + node.a * 3) * unit * node.ss;
        hx.globalAlpha = (0.55 + 0.4 * node.a) * brightness;
        hx.fillStyle = node.a > 0.5 ? "#fff" : palette.c[node.type];
        hx.beginPath();
        hx.arc(node.sx, node.sy, nodeRadius, 0, TAU);
        hx.fill();

        if (node.a > 0.03) {
          const haloRadius = (10 + 28 * node.a) * unit * node.ss;
          const halo = hx.createRadialGradient(
            node.sx,
            node.sy,
            0,
            node.sx,
            node.sy,
            haloRadius,
          );
          halo.addColorStop(0, `rgba(${palette.amb},${0.55 * node.a})`);
          halo.addColorStop(1, `rgba(${palette.amb},0)`);
          hx.globalAlpha = 1;
          hx.fillStyle = halo;
          hx.beginPath();
          hx.arc(node.sx, node.sy, haloRadius, 0, TAU);
          hx.fill();
        }
      }
      hx.globalAlpha = 1;
    };

    const composite = () => {
      b1x.clearRect(0, 0, b1.width, b1.height);
      b1x.drawImage(holo, 0, 0, b1.width, b1.height);
      b2x.clearRect(0, 0, b2.width, b2.height);
      b2x.drawImage(b1, 0, 0, b2.width, b2.height);

      const palette = THEMES[themeRef.current] ?? THEMES.gold;
      ctx.clearRect(0, 0, width, height);

      // Soft ambient pool behind the object (kept very low on the overlay).
      const ambient = ctx.createRadialGradient(
        centerX,
        centerY,
        0,
        centerX,
        centerY,
        radius * 1.9,
      );
      ambient.addColorStop(0, `rgba(${palette.amb},0.14)`);
      ambient.addColorStop(1, `rgba(${palette.amb},0)`);
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = ambient;
      ctx.fillRect(0, 0, width, height);

      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = 1;
      ctx.drawImage(holo, 0, 0);
      ctx.globalAlpha = 0.9;
      ctx.drawImage(b1, 0, 0, width, height);
      ctx.globalAlpha = 0.9;
      ctx.drawImage(b2, 0, 0, width, height);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };

    const frame = (milliseconds: number) => {
      const delta = Math.min(0.05, (milliseconds - lastFrame) / 1000 || 0.016);
      lastFrame = milliseconds;
      draw(milliseconds / 1000, delta);
      composite();
      animation = requestAnimationFrame(frame);
    };

    const reducedMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const onPointerDown = (event: PointerEvent) => {
      dragging = true;
      moved = false;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture?.(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!dragging) return;
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      yaw += dx * 0.006;
      pitch = Math.max(-0.9, Math.min(0.9, pitch + dy * 0.004));
      lastX = event.clientX;
      lastY = event.clientY;
    };
    const onPointerUp = (event: PointerEvent) => {
      dragging = false;
      if (moved) return;
      const rect = canvas.getBoundingClientRect();
      const clickX = ((event.clientX - rect.left) * width) / rect.width;
      const clickY = ((event.clientY - rect.top) * height) / rect.height;
      let best: HologramNode | null = null;
      let bestDistance = Number.POSITIVE_INFINITY;
      for (const node of model.nodes) {
        const distance =
          (node.sx - clickX) ** 2 + (node.sy - clickY) ** 2;
        if (distance < bestDistance) {
          bestDistance = distance;
          best = node;
        }
      }
      if (best) {
        best.ref = 0;
        fire(best);
      }
    };

    resize();

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(resize);
      observer.observe(canvas);
    }
    window.addEventListener("resize", resize);

    if (interactive) {
      canvas.style.pointerEvents = "auto";
      canvas.addEventListener("pointerdown", onPointerDown);
      canvas.addEventListener("pointermove", onPointerMove);
      canvas.addEventListener("pointerup", onPointerUp);
    }

    for (let i = 0; i < 6; i += 1) {
      fire(model.nodes[Math.floor(Math.random() * NODE_COUNT)]);
    }

    if (reducedMotion) {
      setCamera();
      draw(0, 0);
      composite();
    } else {
      animation = requestAnimationFrame(frame);
    }

    return () => {
      cancelAnimationFrame(animation);
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
    };
  }, [interactive, model]);

  const sizeStyle = { "--sphere-size": `${size}px` } as CSSProperties;

  return (
    <div className="holographic-sphere" aria-hidden="true" style={sizeStyle}>
      <canvas ref={canvasRef} data-theme={theme} />
    </div>
  );
}
