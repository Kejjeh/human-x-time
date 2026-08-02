/* ============================================================================
   HUMAN x TIME — core
   Assets injected at build time by tools/build.py
   ========================================================================== */
'use strict';

const LAND_ENC  = '/*@LAND@*/';
const PLATE_ENC = '/*@PLATES@*/';
const DATA      = /*@EVENTS@*/;

const PRESENT = 2026;            // ybp is measured from here
const T_MAX   = 75000;           // the corpus reaches ~71,860 BCE
const RM = matchMedia('(prefers-reduced-motion: reduce)');

/* ---------------------------------------------------------------- decoding */
const ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-';
const AMAP = (() => { const m = new Int8Array(128).fill(-1);
  for (let i = 0; i < 64; i++) m[ALPHA.charCodeAt(i)] = i; return m; })();

function decodeRings(enc) {
  if (!enc) return [];
  const rings = [];
  for (const part of enc.split('|')) {
    if (!part) continue;
    const pts = []; let i = 0, px = 0, py = 0;
    while (i < part.length) {
      let shift = 0, res = 0, b;
      do { b = AMAP[part.charCodeAt(i++)]; res |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      px += (res & 1) ? ~(res >> 1) : (res >> 1);
      shift = 0; res = 0;
      do { b = AMAP[part.charCodeAt(i++)]; res |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      py += (res & 1) ? ~(res >> 1) : (res >> 1);
      pts.push(px / 32, py / 32);
    }
    if (pts.length >= 4) rings.push(pts);
  }
  return rings;
}
function toXYZ(rings) {
  return rings.map(r => {
    const n = r.length / 2, out = new Float64Array(n * 3);
    for (let i = 0; i < n; i++) {
      const lon = r[i * 2] * Math.PI / 180, lat = r[i * 2 + 1] * Math.PI / 180;
      const cl = Math.cos(lat);
      out[i * 3] = cl * Math.cos(lon);
      out[i * 3 + 1] = cl * Math.sin(lon);
      out[i * 3 + 2] = Math.sin(lat);
    }
    return out;
  });
}
function ringOrientation(p) {
  const n = p.length / 3;
  let nx = 0, ny = 0, nz = 0, cx = 0, cy = 0, cz = 0;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const ax = p[i * 3], ay = p[i * 3 + 1], az = p[i * 3 + 2];
    const bx = p[j * 3], by = p[j * 3 + 1], bz = p[j * 3 + 2];
    nx += ay * bz - az * by; ny += az * bx - ax * bz; nz += ax * by - ay * bx;
    cx += ax; cy += ay; cz += az;
  }
  return (nx * cx + ny * cy + nz * cz) > 0 ? 1 : -1;
}
const LAND  = toXYZ(decodeRings(LAND_ENC));
const LAND_CCW = LAND.map(ringOrientation);
const PLATE = toXYZ(decodeRings(PLATE_ENC));

function unit(lat, lng) {
  const a = lng * Math.PI / 180, b = lat * Math.PI / 180, cb = Math.cos(b);
  return [cb * Math.cos(a), cb * Math.sin(a), Math.sin(b)];
}

/* ------------------------------------------------------------ time scaling */
/* Same asinh scale as the sibling site: logarithmic in character for large
   arguments, finite at zero, and scale-invariant because the knee is tied to
   the window span. It suits this corpus for the same reason it suited deep
   time — 71,860 BCE and the year 2001 have to share one axis, and two thirds
   of the events fall after 1000 CE. */
function makeScale(t0, t1, w) {
  const k = Math.max((t1 - t0) / 46, 1e-9);
  const u0 = Math.asinh(t0 / k), u1 = Math.asinh(t1 / k);
  const du = (u1 - u0) || 1;
  return {
    k, w,
    x: t => w * (1 - (Math.asinh(t / k) - u0) / du),
    t: x => k * Math.sinh(u0 + (1 - x / w) * du)
  };
}

const ybp = year => PRESENT - year;
const yearOf = t => Math.round(PRESENT - t);

function fmtYear(y) {
  y = Math.round(y);
  if (y <= 0) return `${1 - y} BCE`;
  return `${y} CE`;
}
function fmtYbpLabel(t) {
  const y = PRESENT - t;
  if (t >= 12000) return `${(t / 1000).toFixed(t >= 1e5 ? 0 : 1).replace(/\.0$/, '')} ka`;
  return fmtYear(y);
}
function fmtSpan(s) {
  if (s >= 12000) return `${Math.round(s / 1000).toLocaleString()} thousand years`;
  return `${Math.round(s).toLocaleString()} years`;
}

/* ---------------------------------------------- historical period ribbon */
/* Old World conventions, and deliberately labelled as such: these are not
   ratified boundaries the way the ICS chart is, they are the names historians
   happen to use. Values are ybp from 2026. */
const ERAS = [
  { n: 'Palaeolithic',  b: 75000, e: 11700, c: '#4B4640' },
  { n: 'Neolithic',     b: 11700, e: 5326,  c: '#5A5347' },
  { n: 'Bronze Age',    b: 5326,  e: 3226,  c: '#6E6249' },
  { n: 'Iron Age',      b: 3226,  e: 2476,  c: '#7E6E4B' },
  { n: 'Classical',     b: 2476,  e: 1550,  c: '#8F7C4C' },
  { n: 'Post-classical',b: 1550,  e: 526,   c: '#A08A4E' },
  { n: 'Early modern',  b: 526,   e: 226,   c: '#B2984D' },
  { n: 'Industrial',    b: 226,   e: 81,    c: '#C4A54A' },
  { n: 'Modern',        b: 81,    e: 0,     c: '#D9A441' }
];
const CENTURIES = (() => {
  const out = [];
  for (let y = -1000; y < 2100; y += 100) {
    const lab = y < 0 ? `${Math.abs(y) / 100}00s BCE`
      : y === 0 ? '1st c.' : `${y / 100 + 1}00s`;
    out.push({ n: lab, b: ybp(y), e: ybp(y + 100), c: (y / 100) % 2 ? '#2A2622' : '#332E28' });
  }
  return out;
})();

/* ------------------------------------------------------------------ themes */
const THEMES = DATA.themes;
const THEME_LABEL = {
  conflict: 'Conflict', polity: 'Politics', disaster: 'Disaster',
  settlement: 'Settlement', building: 'Building', knowledge: 'Knowledge'
};
const CAT_LABEL = {};
for (const c of DATA.categories) CAT_LABEL[c.key] = c.label;

const CSSV = {};
function readPalette() {
  const cs = getComputedStyle(document.documentElement);
  for (const t of THEMES) CSSV[t] = cs.getPropertyValue('--th-' + t).trim();
  for (const k of ['ink', 'panel', 'panel-2', 'panel-3', 'chalk', 'chalk-dim', 'chalk-faint',
                   'amber', 'amber-d', 'rule', 'ocean-hi', 'ocean-lo', 'land', 'land-edge', 'plate'])
    CSSV[k] = cs.getPropertyValue('--' + k).trim();
  CSSV.abyss = CSSV.ink;                 // the carried-over globe uses this name
}
function withAlpha(hex, a) {
  const h = (hex || '').replace('#', '');
  if (h.length < 6) return hex;
  const n = parseInt(h.slice(0, 6), 16);
  return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
}

/* ------------------------------------------------------------------- data */
const LANGS = DATA.langs || [];
const LANG_BIT = {};
LANGS.forEach((l, i) => { LANG_BIT[l] = 1 << i; });

const EV = DATA.events.map((e, i) => {
  const v = unit(e.lat, e.lng);
  return { ...e, i, t: ybp(e.y), x: v[0], yv: v[1], z: v[2], theme: e.t };
});
// `t` was the theme key in the wire format and is the ybp here; keep both clear.
for (let i = 0; i < EV.length; i++) EV[i].theme = DATA.events[i].t;

const MAX_SL = EV.reduce((m, e) => Math.max(m, e.sl), 1);
const BY_Q = {}; for (const e of EV) BY_Q[e.q] = e;

/* -------------------------------------------------------------------- state */
const S = {
  win: { t0: 0, t1: 3200 },        // opens on the last ~3,200 years, where the record is
  kt: 40,                           // coverage floor: opens legible, scrub down for the long tail
  themes: new Set(THEMES),
  lens: '',                         // '' | 'only:<lang>' | 'not:<lang>'
  selection: null,
  hover: null,
  showPlates: false,
  basemap: 'satellite',
  rot: { lam: -10, phi: 25 },
  spin: { lam: 0, phi: 0 },
  cluster: true
};
