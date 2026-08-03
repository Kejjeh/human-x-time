/* ============================================================================
   EVENTS ON THE GLOBE

   This is the only code in the site that runs per frame over the whole corpus,
   and the corpus grew by a factor of five. The old version pushed one object per
   visible event per frame and then a second one per cluster; at seven thousand
   events that was invisible, at forty thousand it is tens of thousands of short-
   lived objects sixty times a second, which is a garbage collector pause you can
   feel in the middle of a drag.

   So everything here is parallel typed arrays, allocated once and grown by
   doubling. Nothing in the frame path allocates. The object array EV still
   exists and is still what the panels and the histogram read - those run once
   per state change, where a plain object is worth far more than a byte saved.
   ========================================================================== */

function markerRadius(n, sl) {
  if (n > 1) return Math.min(15, 4 + Math.log2(n) * 2.4);
  return 2.4 + Math.min(6, Math.log2(1 + sl) * 0.95);
}

/* ------------------------------------------------- projected points (scratch) */
let PX = new Float32Array(0), PY = new Float32Array(0), PD = new Float32Array(0);
let PI = new Int32Array(0);
/* ------------------------------------------------------- drawable groups */
let GX = new Float32Array(0), GY = new Float32Array(0), GD = new Float32Array(0);
let GI = new Int32Array(0), GN = new Uint32Array(0), GMIX = new Uint8Array(0);
let GORD = new Int32Array(0);
const BUCKET = new Int32Array(64);      // counting-sort offsets: 6 depth slabs x 6 themes + 1
let NG = 0;

function grow(n) {
  if (PX.length >= n) return;
  const k = Math.max(2048, 1 << Math.ceil(Math.log2(n)));
  PX = new Float32Array(k); PY = new Float32Array(k); PD = new Float32Array(k);
  PI = new Int32Array(k);
  GX = new Float32Array(k); GY = new Float32Array(k); GD = new Float32Array(k);
  GI = new Int32Array(k); GN = new Uint32Array(k); GMIX = new Uint8Array(k);
  GORD = new Int32Array(k);
}

/* ---------------------------------------------------------------- clustering
   Forty thousand points on a globe is confetti. Bin in screen space and draw one
   marker per occupied cell, sized by how many fell into it, so density reads as
   density instead of as an unreadable smear. The most-covered event in each cell
   supplies the label and the click target - the cell stands for something real
   rather than for a centroid nobody chose. */
const BINS = new Map();
function clusterInto(m, cell) {
  BINS.clear();
  for (let k = 0; k < m; k++) {
    /* Math.floor, not |0. Bitwise-or truncates toward zero, so -0.9 and +0.9
       both land in cell 0 and the row and column through the canvas origin are
       twice as wide as every other. Zoomed in, the globe's centre is off-screen
       and a large part of the visible disc has negative screen coordinates, so
       that double-width cross sat right across it - two bands of markers merged
       into neighbours they are not near. Also *4093 on a negative index
       collides with a positive one; flooring keeps the key monotonic. */
    const key = Math.floor(PX[k] / cell) * 4093 + Math.floor(PY[k] / cell);
    const b = BINS.get(key);
    if (b === undefined) {
      BINS.set(key, [1, PX[k], PY[k], PI[k], PD[k], THEME_IX[EV[PI[k]].theme]]);
    } else {
      b[0]++; b[1] += PX[k]; b[2] += PY[k];
      if (EVSL[PI[k]] > EVSL[b[3]]) { b[3] = PI[k]; b[4] = PD[k]; }
      if (b[5] >= 0 && b[5] !== THEME_IX[EV[PI[k]].theme]) b[5] = -1;
    }
  }
  let g = 0;
  for (const b of BINS.values()) {
    GN[g] = b[0];
    GX[g] = b[0] === 1 ? b[1] : b[1] / b[0];
    GY[g] = b[0] === 1 ? b[2] : b[2] / b[0];
    GI[g] = b[3]; GD[g] = b[4]; GMIX[g] = b[5] < 0 ? 1 : 0;
    g++;
  }
  return g;
}

/* --------------------------------------------------------------- hit testing
   Also arrays. The hover handler runs this on every pointermove, so the cheap
   box rejection before the hypot is not premature - it is the difference
   between 0.1 ms and 2 ms on a corpus this size. */
let HX = new Float32Array(0), HY = new Float32Array(0), HR = new Float32Array(0);
let HI = new Int32Array(0), HC = new Uint32Array(0);
let HN = 0;

function hitTest(mx, my) {
  let best = -1, bd = 1e9;
  for (let k = 0; k < HN; k++) {
    const r = HR[k];
    const dx = HX[k] - mx; if (dx > r || dx < -r) continue;
    const dy = HY[k] - my; if (dy > r || dy < -r) continue;
    const d = Math.sqrt(dx * dx + dy * dy);
    if (d < r && d < bd) { bd = d; best = k; }
  }
  if (best < 0) return null;
  return { id: EV[HI[best]].q, i: HI[best], x: HX[best], y: HY[best], n: HC[best] };
}

function drawEvents() {
  const F = q();
  const src = F.idx, N = F.n;
  grow(Math.max(N, 2048));
  if (HX.length < PX.length) {
    HX = new Float32Array(PX.length); HY = new Float32Array(PX.length);
    HR = new Float32Array(PX.length); HI = new Int32Array(PX.length);
    HC = new Uint32Array(PX.length);
  }

  const m0 = M[0], m1 = M[1], m2 = M[2], m3 = M[3], m4 = M[4],
        m5 = M[5], m6 = M[6], m7 = M[7], m8 = M[8];

  let m = 0;
  for (let k = 0; k < N; k++) {
    const i = src[k];
    const x = EVX[i], y = EVYV[i], z = EVZ[i];
    const d = m0 * x + m1 * y + m2 * z;
    if (d <= 0.015) continue;                        // behind the limb
    PI[m] = i; PD[m] = d;
    PX[m] = GCX + GR * (m3 * x + m4 * y + m5 * z);
    PY[m] = GCY - GR * (m6 * x + m7 * y + m8 * z);
    m++;
  }

  if (S.cluster) {
    NG = clusterInto(m, Math.max(15, GR * 0.055));
  } else {
    NG = m;
    for (let k = 0; k < m; k++) {
      GX[k] = PX[k]; GY[k] = PY[k]; GD[k] = PD[k]; GI[k] = PI[k];
      GN[k] = 1; GMIX[k] = 0;
    }
  }

  HN = 0;
  gx.save();

  /* Turning clustering off with the coverage floor at 1 and the window at
     maximum puts every event on screen at once. One beginPath/fill per marker
     is 62 ms a frame there - sixteen frames a second, in the one mode where the
     user is most likely to be dragging around looking at the density.

     Batched, it is one path per theme colour: seven fills instead of a hundred
     and fifty thousand canvas calls. The per-marker path stays for everything
     below the threshold, because it is the one that can afford the cluster
     ring, the mixed-theme stroke and the selection halo. */
  // Only ever the unclustered path: on a large enough display the cell grid can
  // exceed the threshold on its own, and clusters need the ring, the mixed-theme
  // stroke and the count, none of which the batched path draws.
  const DENSE = !S.cluster && NG > 2500;
  if (DENSE) {
    gx.beginPath();
    for (let k = 0; k < NG; k++) {
      const r = markerRadius(GN[k], EVSL[GI[k]]) + 1.5;
      gx.moveTo(GX[k] + r, GY[k]);              // moveTo, or subpaths join up
      gx.arc(GX[k], GY[k], r, 0, 7);
    }
    gx.fillStyle = 'rgba(4,8,14,0.5)'; gx.fill();

    /* Batching by colour means one theme is drawn entirely after another, so
       whichever theme comes last in THEMES sits on top of every overlap - the
       density map picks up a systematic colour cast that has nothing to do with
       the data. Painting per marker would fix it and costs 60 ms a frame here.
       So: counting-sort the groups into DEPTH SLABS first, colour second. Front
       slabs are still drawn over back slabs, and theme order only decides ties
       inside one slab, where the markers are at comparable depth anyway.
       Two O(N) passes, no allocation, and the fills stay batched. */
    const T = THEMES.length, SLABS = 6, NB = SLABS * T;
    BUCKET.fill(0, 0, NB + 1);
    for (let k = 0; k < NG; k++) {
      const slab = Math.min(SLABS - 1, (GD[k] * SLABS) | 0);   // GD is cos(angle), 0..1
      BUCKET[slab * T + EVTH[GI[k]] + 1]++;
    }
    for (let b = 0; b < NB; b++) BUCKET[b + 1] += BUCKET[b];
    for (let k = 0; k < NG; k++) {
      const slab = Math.min(SLABS - 1, (GD[k] * SLABS) | 0);
      GORD[BUCKET[slab * T + EVTH[GI[k]]]++] = k;
    }
    // BUCKET[b] now points one past bucket b, so bucket b spans [prev, BUCKET[b]).
    let start = 0;
    for (let b = 0; b < NB; b++) {
      const end = BUCKET[b];
      if (end > start) {
        gx.beginPath();
        for (let j = start; j < end; j++) {
          const k = GORD[j];
          const r = markerRadius(GN[k], EVSL[GI[k]]);
          gx.moveTo(GX[k] + r, GY[k]);
          gx.arc(GX[k], GY[k], r, 0, 7);
        }
        gx.fillStyle = CSSV[THEMES[b % T]] || CSSV.chalk;
        gx.fill();
      }
      start = end;
    }
    for (let k = 0; k < NG; k++) {
      HX[HN] = GX[k]; HY[HN] = GY[k];
      HR[HN] = markerRadius(GN[k], EVSL[GI[k]]) + 6;
      HI[HN] = GI[k]; HC[HN] = GN[k]; HN++;
    }
    const sel = S.selection && BY_Q[S.selection];
    if (sel) {
      for (let k = 0; k < NG; k++) {
        if (GI[k] !== sel.i) continue;
        const r = markerRadius(GN[k], EVSL[GI[k]]);
        gx.beginPath(); gx.arc(GX[k], GY[k], r + 5, 0, 7);
        gx.strokeStyle = CSSV.chalk; gx.lineWidth = 1.3; gx.stroke();
        break;
      }
    }
  } else {
  /* Painter's order. Only built on the branch that uses it: the dense branch
     does its own depth-slab bucketing, and filling and comparator-sorting an
     array of tens of thousands only to throw it away was pure cost. */
  for (let k = 0; k < NG; k++) GORD[k] = k;
  const ord = GORD.subarray(0, NG).sort((a, b) => GD[a] - GD[b]);
  for (let oi = 0; oi < NG; oi++) {
    const k = ord[oi];
    const i = GI[k], n = GN[k];
    const e = EV[i];
    const col = CSSV[e.theme] || CSSV.chalk;
    const r = markerRadius(n, EVSL[i]);
    const sx = GX[k], sy = GY[k];

    // dark contact ring: a theme colour can otherwise land on sunlit desert
    // at its own value and vanish
    gx.beginPath(); gx.arc(sx, sy, r + 1.5, 0, 7);
    gx.fillStyle = 'rgba(4,8,14,0.5)'; gx.fill();

    gx.beginPath(); gx.arc(sx, sy, r, 0, 7);
    if (n > 1) {
      gx.fillStyle = withAlpha(GMIX[k] ? CSSV['chalk-dim'] : col, 0.7);
      gx.fill();
      gx.strokeStyle = withAlpha(GMIX[k] ? CSSV.chalk : col, 0.9);
      gx.lineWidth = 1.1; gx.stroke();
    } else {
      gx.fillStyle = col; gx.fill();
    }

    if (S.selection === e.q) {
      gx.beginPath(); gx.arc(sx, sy, r + 5, 0, 7);
      gx.strokeStyle = CSSV.chalk; gx.lineWidth = 1.3; gx.stroke();
    }

    HX[HN] = sx; HY[HN] = sy; HR[HN] = r + 6; HI[HN] = i; HC[HN] = n; HN++;
  }
  }

  // counts inside the bigger clusters
  gx.font = `600 9px xt-mono, monospace`;
  gx.textAlign = 'center'; gx.textBaseline = 'middle';
  for (let k = 0; k < NG; k++) {
    if (GN[k] < 4) continue;
    if (markerRadius(GN[k], EVSL[GI[k]]) < 8) continue;
    gx.fillStyle = 'rgba(6,10,16,0.85)';
    gx.fillText(String(GN[k]), GX[k], GY[k] + 0.5);
  }
  gx.textAlign = 'start'; gx.textBaseline = 'alphabetic';

  /* Labels: only the singles, only the well-covered, only where they fit.

     Collecting every candidate and sorting was most of the remaining frame cost
     unclustered - thirty-seven thousand pushes and a comparator sort, to keep
     thirty-four. This is a bounded insertion into a fixed 34-slot list instead:
     one pass, no allocation, and the common case is a single comparison against
     the current floor. */
  const LMAX = 34;
  const labelled = [];
  let floorRank = -1;
  for (let k = 0; k < NG; k++) {
    if (GN[k] !== 1 && EVSL[GI[k]] <= 80) continue;
    const r = EV[GI[k]].q === S.selection ? 1e9 : EVSL[GI[k]];
    if (labelled.length === LMAX && r <= floorRank) continue;
    let pos = labelled.length;
    while (pos > 0 && (labelled[pos - 1].r < r)) pos--;
    labelled.splice(pos, 0, { k, r });
    if (labelled.length > LMAX) labelled.pop();
    floorRank = labelled[labelled.length - 1].r;
  }

  const boxes = [];
  gx.font = `400 11px xt-cond, sans-serif`;
  for (const { k } of labelled) {
    const e = EV[GI[k]];
    const strong = e.q === S.selection || e.q === S.hover;
    if (!strong && EVSL[GI[k]] < 90) continue;
    const t = e.n;
    const w = gx.measureText(t).width;
    const r = markerRadius(GN[k], EVSL[GI[k]]);
    const sx = GX[k], sy = GY[k];
    for (const [bx, by] of [[sx + r + 5, sy + 4], [sx - w - r - 5, sy + 4],
                            [sx - w / 2, sy - r - 6], [sx - w / 2, sy + r + 13]]) {
      const box = [bx - 2, by - 10, w + 4, 13];
      if (bx < 4 || bx + w > GW - 4 || by < 12 || by > GH - 6) continue;
      let hit = false;
      for (const o of boxes) {
        if (box[0] < o[0] + o[2] && box[0] + box[2] > o[0] &&
            box[1] < o[1] + o[3] && box[1] + box[3] > o[1]) { hit = true; break; }
      }
      if (hit) continue;
      boxes.push(box);
      gx.fillStyle = 'rgba(6,10,16,0.66)';
      gx.fillRect(box[0], box[1], box[2], box[3]);
      gx.fillStyle = strong ? '#F4F0E8' : withAlpha(CSSV[e.theme] || CSSV.chalk, 0.95);
      gx.font = `${strong ? 600 : 400} 11px xt-cond, sans-serif`;
      gx.fillText(t, bx, by);
      break;
    }
  }
  gx.restore();
}
