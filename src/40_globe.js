/* ============================================================================
   THE GLOBE  (carried over intact from Earth × Time)
   Orthographic, canvas 2D, projection written by hand. Every vertex is stored
   as a unit vector at load time, so a frame costs one 3x3 matrix build plus
   nine multiplies per point — no trigonometry in the draw loop.
   ========================================================================== */

const gcv = document.getElementById('globe');
const gx = gcv.getContext('2d');
let GW = 0, GH = 0, GR = 0, GCX = 0, GCY = 0, DPR = 1;
let ZOOMF = 0.86;

/* ============================================================================
   SATELLITE SURFACE
   NASA Blue Marble, equirectangular, inlined. Painted by inverse-projecting
   every pixel of the disc back to a longitude and latitude and sampling the
   texture — the honest way to put a real image on an orthographic sphere.
   asin and atan2 per pixel are the cost, so the buffer drops to half linear
   resolution while the globe is moving and sharpens the moment it stops.
   ========================================================================== */
const TEX = { w: 0, h: 0, data: null, ready: false };
(function loadTexture() {
  const img = new Image();
  img.onload = () => {
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const cc = c.getContext('2d', { willReadFrequently: true });
    cc.drawImage(img, 0, 0);
    const d = cc.getImageData(0, 0, c.width, c.height);
    TEX.w = c.width; TEX.h = c.height; TEX.data = d.data; TEX.ready = true;
    if (typeof markAll === 'function') markAll();
  };
  img.src = 'data:image/jpeg;base64,/*@EARTH@*/';
})();

/* Ray directions for the disc, in the *unrotated* view frame. Depends only on
   canvas geometry, so it is rebuilt on resize and reused every frame. */
const RAY = { scale: 0, w: 0, h: 0, key: '', nz: null, nx: null, ny: null, idx: null, buf: null, img: null };

/* The rays are unit directions built from the disc's centre and radius, so they
   are only valid for the geometry they were built from. Testing the scale and
   the width alone missed both of the ways that geometry moves without either
   changing: a zoom (GR changes, GW does not) and a height-only window resize
   (GH and GCY change, GW does not). Both left the imagery painted at the old
   radius while the atmosphere, the limb, the graticule and every marker used
   the new one - a photograph of Earth sitting still inside a limb ring that
   grows. Key the cache on everything buildRays actually reads. */
const rayKey = scale => `${scale}|${GW.toFixed(2)}x${GH.toFixed(2)}|${GCX.toFixed(2)},${GCY.toFixed(2)}|${GR.toFixed(3)}`;

function buildRays(scale) {
  const w = Math.max(1, Math.round(GW * scale)), h = Math.max(1, Math.round(GH * scale));
  const cx = GCX * scale, cy = GCY * scale, r = GR * scale;
  const n = w * h;
  const nz = new Float32Array(n), nx = new Float32Array(n), ny = new Float32Array(n);
  const idx = new Int32Array(n);
  let k = 0;
  for (let y = 0; y < h; y++) {
    const dy = (y + 0.5 - cy) / r;
    for (let x = 0; x < w; x++) {
      const dx = (x + 0.5 - cx) / r;
      const r2 = dx * dx + dy * dy;
      if (r2 > 1) continue;
      idx[k] = y * w + x;
      nx[k] = dx; ny[k] = -dy; nz[k] = Math.sqrt(1 - r2);
      k++;
    }
  }
  RAY.scale = scale; RAY.w = w; RAY.h = h; RAY.key = rayKey(scale);
  RAY.nz = nz; RAY.nx = nx; RAY.ny = ny; RAY.idx = idx; RAY.count = k;
  RAY.img = gx.createImageData(w, h);
  RAY.buf = new Uint32Array(RAY.img.data.buffer);
}

const INV_PI = 1 / Math.PI;

/* Per-pixel trig stays native.

   A lookup table for asin plus a polynomial atan2 measured ~19% faster in one
   interleaved test and ~20% slower in another; the two disagreed because
   routing the trig through closure parameters defeats inlining, so neither
   number was trustworthy. The atan2 polynomial was accurate to 0.04 px, but the
   asin table was out by 4.5 px — uniform sampling in z under-resolves near the
   poles, where asin steepens toward a singularity. Wrong, and not measurably
   faster, so it is gone. The responsiveness win is taken structurally below
   instead, where it can be measured end to end.
   ------------------------------------------------------------------------- */

const SURF = { canvas: null, ctx: null, key: '' };

function paintSatelliteCached(scale) {
  const key = `${S.rot.lam.toFixed(3)}|${S.rot.phi.toFixed(3)}|${GR.toFixed(1)}|${scale}|${GW}x${GH}`;
  if (SURF.key !== key || !SURF.canvas) {
    if (!paintSatellite(scale)) return false;
    SURF.key = key;
  }
  gx.imageSmoothingEnabled = true;
  gx.drawImage(SURF.canvas, 0, 0, SURF.canvas.width, SURF.canvas.height, 0, 0, GW, GH);
  return true;
}

/* Adaptive resolution.

   The projection cost is linear in pixel count and machines differ by an order
   of magnitude, so the scale is chosen from what a paint actually cost here
   rather than from a constant guessed on one laptop. Quantised to four steps so
   the surface cache is not thrashed by a scale that drifts every frame. */
let satFullMs = 16;                      // rolling estimate of a full-res paint;
                                         // starts pessimistic so the first drag is
                                         // coarse-and-smooth, then sharpens as it learns
const SAT_BUDGET_MS = 4.5;               // what we will spend while the globe moves
const SAT_STEPS = [0.34, 0.45, 0.6, 0.8, 1];
function movingScale() {
  const want = Math.sqrt(SAT_BUDGET_MS / Math.max(0.5, satFullMs));
  for (const st of SAT_STEPS) if (st >= want) return st;
  return 1;
}

function paintSatellite(scale) {
  if (!TEX.ready) return false;
  const _t0 = performance.now();
  if (RAY.key !== rayKey(scale)) buildRays(scale);
  const { nz, nx, ny, idx, buf, count } = RAY;
  const tw = TEX.w, th = TEX.h, td = TEX.data;
  const m0 = M[0], m1 = M[1], m2 = M[2], m3 = M[3], m4 = M[4],
        m5 = M[5], m6 = M[6], m7 = M[7], m8 = M[8];

  buf.fill(0);
  for (let i = 0; i < count; i++) {
    const a = nz[i], b = nx[i], c = ny[i];
    // M is orthonormal, so the inverse is the transpose: world = Mᵀ · view
    const px = m0 * a + m3 * b + m6 * c;
    const py = m1 * a + m4 * b + m7 * c;
    const pz = m2 * a + m5 * b + m8 * c;

    let u = (Math.atan2(py, px) * INV_PI + 1) * 0.5 * tw;
    let v = (0.5 - Math.asin(pz > 1 ? 1 : pz < -1 ? -1 : pz) * INV_PI) * th;
    u = u < 0 ? 0 : u >= tw ? tw - 1 : u | 0;
    v = v < 0 ? 0 : v >= th ? th - 1 : v | 0;
    const t = (v * tw + u) << 2;

    // Limb darkening: a sphere lit from the viewer still falls off at the rim.
    const sh = 0.45 + 0.55 * a;
    buf[idx[i]] = 0xff000000 |
      ((td[t + 2] * sh) << 16) |
      ((td[t + 1] * sh) << 8) |
      (td[t] * sh);
  }
  if (!SURF.canvas) {
    SURF.canvas = document.createElement('canvas');
    SURF.ctx = SURF.canvas.getContext('2d');
  }
  if (SURF.canvas.width !== RAY.w || SURF.canvas.height !== RAY.h) {
    SURF.canvas.width = RAY.w; SURF.canvas.height = RAY.h;
  }
  SURF.ctx.putImageData(RAY.img, 0, 0);
  // normalise to a full-res equivalent so the estimate is scale-independent
  satFullMs = satFullMs * 0.75 + ((performance.now() - _t0) / (scale * scale)) * 0.25;
  return true;
}

/* A thin blue shell just outside the limb, the way Earth reads from orbit. */
function paintAtmosphere() {
  const g = gx.createRadialGradient(GCX, GCY, GR * 0.985, GCX, GCY, GR * 1.10);
  g.addColorStop(0, 'rgba(126,186,232,0.55)');
  g.addColorStop(0.35, 'rgba(96,158,214,0.22)');
  g.addColorStop(1, 'rgba(70,130,190,0)');
  gx.beginPath();
  gx.arc(GCX, GCY, GR * 1.10, 0, 7);
  gx.fillStyle = g;
  gx.fill();
}

const M = new Float64Array(9);
function buildMatrix() {
  const l = S.rot.lam * Math.PI / 180, p = S.rot.phi * Math.PI / 180;
  const cl = Math.cos(l), sl = Math.sin(l), cp = Math.cos(p), sp = Math.sin(p);
  M[0] = cp * cl; M[1] = -cp * sl; M[2] = sp;      // depth row
  M[3] = sl;      M[4] = cl;       M[5] = 0;       // screen x row
  M[6] = -sp * cl; M[7] = sp * sl; M[8] = cp;      // screen y row
}

/* Graticule, built once as unit vectors. */
const GRAT = (() => {
  const out = [];
  for (let lon = -180; lon < 180; lon += 30) {
    const r = [];
    for (let lat = -90; lat <= 90; lat += 4) r.push(...unit(lat, lon));
    out.push(new Float64Array(r));
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const r = [];
    for (let lon = -180; lon <= 180; lon += 4) r.push(...unit(lat, lon));
    out.push(new Float64Array(r));
  }
  return out;
})();

/*
 * Size the backing store only — never write an inline width/height.
 *
 * The clamp below stops a zero measurement producing a zero-sized canvas, but
 * written as an inline style it becomes permanent: a page laid out while hidden
 * (a background tab, an artifact iframe before it is shown) measures 0, pins the
 * element at the 80px minimum, and stays an 80px globe in an 800px stage
 * forever after. CSS keeps the element at 100% of the stage; only the pixel
 * buffer is set here, and sizeGuard re-syncs it once real layout arrives.
 */
function resizeGlobe() {
  const w = gcv.clientWidth || gcv.parentElement.getBoundingClientRect().width;
  const h = gcv.clientHeight || gcv.parentElement.getBoundingClientRect().height;
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  GW = Math.max(80, w); GH = Math.max(80, h);
  gcv.width = Math.round(GW * DPR); gcv.height = Math.round(GH * DPR);
  gx.setTransform(DPR, 0, 0, DPR, 0, 0);
  GCX = GW / 2; GCY = GH / 2;
  applyZoom();
}

/* Zoom alone. Assigning gcv.width reallocates and blanks the bitmap and resets
   the whole 2D context state, which is the right thing to do when the element
   changes size and pure waste sixty times a second during a pinch, where only
   the radius moves. Splitting it out means a pinch touches two numbers. */
function applyZoom() {
  GR = Math.min(GW, GH) * 0.5 * ZOOMF;
  SURF.key = '';                       // the cached sphere is the wrong size now
}

/** Cheap per-frame check that the buffers still match the laid-out boxes. */
function sizeGuard() {
  const w = gcv.clientWidth, h = gcv.clientHeight;
  if (w > 0 && h > 0 && (Math.abs(w - GW) > 1 || Math.abs(h - GH) > 1)) {
    resizeGlobe(); resizeChron(); resizeRail();
    markAll();
    return true;
  }
  return false;
}

/* ------------------------------------------------------------ ring drawing */
/* Scratch buffers, sized to the largest ring, reused every frame. */
const RB = { d: null, Y: null, Z: null };
function ensureBuffers(n) {
  if (!RB.d || RB.d.length < n) {
    RB.d = new Float64Array(n * 2); RB.Y = new Float64Array(n * 2); RB.Z = new Float64Array(n * 2);
  }
}

function projectRing(ring) {
  const n = ring.length / 3;
  ensureBuffers(n);
  const { d, Y, Z } = RB;
  let nVis = 0;
  for (let i = 0; i < n; i++) {
    const px = ring[i * 3], py = ring[i * 3 + 1], pz = ring[i * 3 + 2];
    d[i] = M[0] * px + M[1] * py + M[2] * pz;
    Y[i] = M[3] * px + M[4] * py + M[5] * pz;
    Z[i] = M[6] * px + M[7] * py + M[8] * pz;
    if (d[i] > 0) nVis++;
  }
  return { n, nVis };
}

/*
 * Which way round the limb does a gap close?
 *
 * Not a question the hidden vertices can answer. Their azimuths wind through
 * extra whole turns on a ring as long as Eurasia, and on a ring as small as a
 * Siberian lake they are identical to within rounding — either way the sign is
 * junk and the arc sweeps the wrong way, flooding the disc.
 *
 * It follows from orientation instead. Walking the limb in the direction of
 * increasing azimuth in the right-handed view frame keeps the visible
 * hemisphere on the left; a ring whose interior is also on its left therefore
 * closes that same way, at every gap, regardless of how much is hidden. The
 * matrix rows are a right-handed triple, and screen angle is atan2(-Z, Y),
 * which runs opposite to that azimuth — hence canvas counterclockwise.
 */
function limbSweepIsCCW(orientation) { return orientation > 0; }

/* Open polylines — graticule, plate boundaries. Hidden runs are simply cut,
   never bridged, so nothing smears across the disc. */
function strokePolyline(ring) {
  const { n } = projectRing(ring);
  const { d, Y, Z } = RB;
  let drawing = false, drew = false;
  gx.beginPath();
  for (let i = 0; i < n; i++) {
    if (d[i] > 0) {
      const sx = GCX + GR * Y[i], sy = GCY - GR * Z[i];
      if (!drawing) { gx.moveTo(sx, sy); drawing = true; } else gx.lineTo(sx, sy);
      drew = true;
    } else drawing = false;
  }
  if (drew) gx.stroke();
  return drew;
}

/**
 * Filled landmasses, clipped to the visible hemisphere.
 *
 * Collapsing hidden vertices onto the rim (the cheap trick) turns any continent
 * straddling the horizon into a polygon that swallows the globe. Instead: cut
 * the ring at the horizon, then close each gap by following the limb itself,
 * choosing the sweep direction that passes over where the hidden vertices
 * actually went. Fill the closed path, then stroke only the true coastline so
 * the limb arcs are not mistaken for shoreline.
 */
function drawLandRing(ring, orientation) {
  const { n, nVis } = projectRing(ring);
  if (nVis === 0) return false;
  const { d, Y, Z } = RB;

  if (nVis === n) {
    gx.beginPath();
    for (let i = 0; i < n; i++) {
      const sx = GCX + GR * Y[i], sy = GCY - GR * Z[i];
      if (i === 0) gx.moveTo(sx, sy); else gx.lineTo(sx, sy);
    }
    gx.closePath(); gx.fill(); gx.stroke();
    return true;
  }

  let start = -1;
  for (let i = 0; i < n; i++) if (d[i] <= 0 && d[(i + 1) % n] > 0) { start = i; break; }
  if (start < 0) return false;

  const cross = (i, j) => {
    const t = d[i] / (d[i] - d[j]);
    let y = Y[i] + (Y[j] - Y[i]) * t, z = Z[i] + (Z[j] - Z[i]) * t;
    const m = Math.hypot(y, z) || 1;
    return [y / m, z / m];
  };

  const segs = [];
  let cur = null;
  for (let k = 0; k < n; k++) {
    const i = (start + k) % n, j = (start + k + 1) % n;
    if (d[i] > 0) {
      if (!cur) { cur = { pts: [], inAng: null }; segs.push(cur); }
      cur.pts.push(Y[i], Z[i]);
      if (d[j] <= 0) {
        const c = cross(i, j);
        cur.pts.push(c[0], c[1]);
        cur.outAng = Math.atan2(-c[1], c[0]);
        cur = null;
      }
    } else if (d[j] > 0) {
      const c = cross(i, j);
      cur = { pts: [c[0], c[1]], inAng: Math.atan2(-c[1], c[0]) };
      segs.push(cur);
    }
  }
  const chains = segs.filter(s => s.inAng != null && s.outAng != null);
  if (!chains.length) return false;
  const ccw = limbSweepIsCCW(orientation);

  /* Chains must be re-paired by position along the limb, not by ring order.
     Where a coastline crosses the horizon many times, the chain that follows
     another around the rim is rarely the next one in the ring; pairing by ring
     order crosses the arcs over each other and the fill inverts. */
  const TAU = Math.PI * 2;
  const gapTo = (from, to) => {
    const d = ccw ? (from - to) : (to - from);
    return ((d % TAU) + TAU) % TAU;
  };

  const used = new Array(chains.length).fill(false);
  gx.beginPath();
  for (let s0 = 0; s0 < chains.length; s0++) {
    if (used[s0]) continue;
    let cur = s0, first = true, guard = 0;
    while (guard++ <= chains.length) {
      used[cur] = true;
      const seg = chains[cur];
      for (let q = 0; q < seg.pts.length; q += 2) {
        const sx = GCX + GR * seg.pts[q], sy = GCY - GR * seg.pts[q + 1];
        if (first && q === 0) gx.moveTo(sx, sy); else gx.lineTo(sx, sy);
      }
      first = false;
      let best = -1, bestD = Infinity;
      for (let t = 0; t < chains.length; t++) {
        const d2 = gapTo(seg.outAng, chains[t].inAng);
        if (d2 < bestD - 1e-12) { bestD = d2; best = t; }
      }
      if (best < 0) break;
      gx.arc(GCX, GCY, GR, seg.outAng, chains[best].inAng, ccw);
      if (best === s0 || used[best]) break;
      cur = best;
    }
    gx.closePath();
  }
  gx.fill();

  // coastline only — the limb arcs above are a fill device, not shoreline
  gx.beginPath();
  for (const seg of chains) {
    for (let q = 0; q < seg.pts.length; q += 2) {
      const sx = GCX + GR * seg.pts[q], sy = GCY - GR * seg.pts[q + 1];
      if (q === 0) gx.moveTo(sx, sy); else gx.lineTo(sx, sy);
    }
  }
  gx.stroke();
  return true;
}

/* --------------------------------------------------------------- great arcs */
function arcPoints(a, b, steps) {
  let dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  dot = Math.max(-1, Math.min(1, dot));
  const om = Math.acos(dot), so = Math.sin(om);
  const pts = new Float64Array(steps * 3);
  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1);
    let c1, c2;
    if (so < 1e-6) { c1 = 1 - t; c2 = t; }
    else { c1 = Math.sin((1 - t) * om) / so; c2 = Math.sin(t * om) / so; }
    pts[i * 3] = a[0] * c1 + b[0] * c2;
    pts[i * 3 + 1] = a[1] * c1 + b[1] * c2;
    pts[i * 3 + 2] = a[2] * c1 + b[2] * c2;
  }
  return pts;
}

/** Draw an arc raised off the surface; returns screen points for the travelling dot. */
function drawArc(pts, lift, color, width, dash, dashOffset) {
  const n = pts.length / 3;
  gx.strokeStyle = color; gx.lineWidth = width;
  if (dash) { gx.setLineDash(dash); gx.lineDashOffset = dashOffset || 0; }
  const screen = new Float64Array(n * 2);
  const vis = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const h = 1 + lift * Math.sin(Math.PI * t);
    const px = pts[i * 3], py = pts[i * 3 + 1], pz = pts[i * 3 + 2];
    const d = M[0] * px + M[1] * py + M[2] * pz;
    const yv = M[3] * px + M[4] * py + M[5] * pz;
    const zv = M[6] * px + M[7] * py + M[8] * pz;
    screen[i * 2] = GCX + GR * h * yv;
    screen[i * 2 + 1] = GCY - GR * h * zv;
    vis[i] = d > -(h - 1) * 0.9 ? 1 : 0;
  }
  let drawing = false;
  gx.beginPath();
  for (let i = 0; i < n; i++) {
    if (vis[i]) {
      if (!drawing) { gx.moveTo(screen[i * 2], screen[i * 2 + 1]); drawing = true; }
      else gx.lineTo(screen[i * 2], screen[i * 2 + 1]);
    } else drawing = false;
  }
  gx.stroke();
  gx.setLineDash([]);
  return { screen, vis, n };
}

/* ------------------------------------------------------------------ markers */
/* Hit targets are parallel typed arrays in 45_markers.js and are rebuilt inside
   drawEvents; ask hitTest(x, y) for what is under the cursor. */

/* drawMarker and drawLabel came over with the globe from the sibling site,
   where markers are claims rather than events. Nothing here called them, and
   drawMarker's markerRadius(sig) was in fact resolving to the two-argument
   markerRadius in 45_markers.js - later declarations in the same script win -
   so it would have drawn the wrong size the moment anything did call it. */

/* ------------------------------------------------------------------- render */
let arcPhase = 0;
let ON_IMAGERY = false;
let LAST_INPUT_AT = -1e9;   // set by the input handlers; see paintOnInput   // label scrims darken over satellite imagery

function drawGlobe(dt) {
  buildMatrix();
  gx.clearRect(0, 0, GW, GH);

  const moving = !!gDrag || Math.abs(S.spin.lam) > 0.01 || Math.abs(S.spin.phi) > 0.01
    || (performance.now() - LAST_INPUT_AT) < 170;
  const satellite = S.basemap === 'satellite' && TEX.ready;
  ON_IMAGERY = satellite;

  if (satellite) {
    paintAtmosphere();
    paintSatelliteCached(moving ? movingScale() : 1);
  } else {
    const grd = gx.createRadialGradient(GCX - GR * 0.3, GCY - GR * 0.35, GR * 0.1, GCX, GCY, GR);
    grd.addColorStop(0, CSSV['ocean-hi']); grd.addColorStop(1, CSSV['ocean-lo']);
    gx.beginPath(); gx.arc(GCX, GCY, GR, 0, 7); gx.fillStyle = grd; gx.fill();
  }

  gx.save();
  gx.beginPath(); gx.arc(GCX, GCY, GR, 0, 7); gx.clip();

  // graticule
  gx.strokeStyle = satellite ? 'rgba(255,255,255,0.13)' : withAlpha(CSSV['land-edge'], 0.16);
  gx.lineWidth = 0.5;
  for (const g of GRAT) strokePolyline(g);

  // coastlines: the whole basemap in chart mode, nothing at all over imagery
  if (!satellite) {
    gx.fillStyle = CSSV.land; gx.strokeStyle = CSSV['land-edge']; gx.lineWidth = 0.7;
    for (let i = 0; i < LAND.length; i++) drawLandRing(LAND[i], LAND_CCW[i]);
  }

  // plate boundaries — a geological-survey underlay, drawn over the land it cuts
  if (S.showPlates) {
    gx.strokeStyle = satellite ? 'rgba(255,196,120,0.62)' : CSSV.plate;
    gx.lineWidth = satellite ? 1.1 : 0.9;
    gx.setLineDash([3, 2.5]);
    for (const p of PLATE) strokePolyline(p);
    gx.setLineDash([]);
  }

  gx.restore();

  // limb
  gx.beginPath(); gx.arc(GCX, GCY, GR, 0, 7);
  gx.strokeStyle = satellite ? 'rgba(150,200,240,0.5)' : withAlpha(CSSV['land-edge'], 0.7);
  gx.lineWidth = 1; gx.stroke();

  drawEvents();

  if (!RM.matches) arcPhase += dt;
}
