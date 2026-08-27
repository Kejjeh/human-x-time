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
    /* The band spans [y, y+100), so it is named after y - not after y+100.
       `y / 100 + 1` put every CE band one century into the future: the band
       covering 1900 to 2000 was labelled "2000s", and the one covering 2000 to
       2100 was labelled "2100s", a century that has not started. The BCE arm
       was already naming the band by its own start. */
    const lab = y < 0 ? `${Math.abs(y) / 100}00s BCE`
      : y === 0 ? '1st c.' : `${y / 100}00s`;
    out.push({ n: lab, b: ybp(y), e: ybp(y + 100), c: (y / 100) % 2 ? '#2A2622' : '#332E28' });
  }
  return out;
})();

/* ------------------------------------------------------------------ themes */
const THEMES = DATA.themes;
const THEME_IX = {}; THEMES.forEach((t, i) => { THEME_IX[t] = i; });
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

/* The corpus arrives columnar: see tools/pack_events.py for the format and why.
   Forty thousand events as JSON objects is five megabytes of key names and
   decimal strings; packed it is a fifth of that.

   Note the shift ceiling. `x << shift` takes the shift modulo 32, so a column
   whose values need more than 32 bits would silently wrap. Every column here is
   at most 32 bits wide - the language mask is exactly 32 - so the highest shift
   reached is 30 and the final `>>> 0` recovers the unsigned value. */
function decodeVarints(s, n) {
  const out = new Uint32Array(n);
  let i = 0;
  for (let k = 0; k < n; k++) {
    let shift = 0, res = 0, b;
    do {
      b = AMAP[s.charCodeAt(i++)];
      res |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    out[k] = res >>> 0;
  }
  return out;
}
const unzig = v => (v & 1) ? ~(v >>> 1) : (v >>> 1);

if (DATA.v !== 2) throw new Error('events payload is not the v2 packed format');

const NEV = DATA.n;
const CATS = DATA.categories.map(c => c.key);
const CAT_THEME = DATA.categories.map(c => c.theme);

/* Hot columns as typed arrays. drawEvents runs these every frame; the object
   array below is for everything that runs once per state change, where a plain
   object is far easier to read and costs nothing. */
const EVX = new Float32Array(NEV), EVYV = new Float32Array(NEV), EVZ = new Float32Array(NEV);
const EVT = new Float32Array(NEV);          // years before present
const EVSL = new Uint16Array(NEV);
const EVTH = new Uint8Array(NEV);           // theme index; the frame path must not
const EV = new Array(NEV);                  // do a string lookup per marker

(() => {
  const C = DATA.cols;
  const names = DATA.names.split('\n');
  if (names.length !== NEV) throw new Error(`${names.length} names for ${NEV} events`);
  const dy = decodeVarints(C.y, NEV), dq = decodeVarints(C.q, NEV);
  const dlat = decodeVarints(C.lat, NEV), dlng = decodeVarints(C.lng, NEV);
  const dc = decodeVarints(C.c, NEV), dsl = decodeVarints(C.sl, NEV);
  const dm = decodeVarints(C.m, NEV);
  let year = 0;
  for (let i = 0; i < NEV; i++) {
    year += unzig(dy[i]);                    // delta-coded: the corpus is in year order
    const lat = unzig(dlat[i]) / 1000, lng = unzig(dlng[i]) / 1000;
    const a = lng * Math.PI / 180, b = lat * Math.PI / 180, cb = Math.cos(b);
    EVX[i] = cb * Math.cos(a); EVYV[i] = cb * Math.sin(a); EVZ[i] = Math.sin(b);
    EVT[i] = PRESENT - year;
    EVSL[i] = dsl[i];
    EVTH[i] = THEME_IX[CAT_THEME[dc[i]]];
    EV[i] = {
      i, q: 'Q' + dq[i], n: names[i], lat, lng, y: year,
      c: CATS[dc[i]], theme: CAT_THEME[dc[i]], sl: dsl[i], m: dm[i],
      t: EVT[i], x: EVX[i], yv: EVYV[i], z: EVZ[i]
    };
  }
})();

let MAX_SL = 1;
for (let i = 0; i < NEV; i++) if (EVSL[i] > MAX_SL) MAX_SL = EVSL[i];
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
