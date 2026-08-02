/* ============================================================================
   THE QUERY
   One function. Time window, coverage floor, theme filter and language lens are
   not four features — they are one query with different axes pinned, exactly as
   on the sibling site. Every renderer reads its output.
   ========================================================================== */

function lensTest(A) {
  if (!A.lens) return null;
  const [mode, lang] = A.lens.split(':');
  const bit = LANG_BIT[lang];
  if (!bit) return null;
  return mode === 'only' ? (e => (e.m & bit) !== 0) : (e => (e.m & bit) === 0);
}

function queryEvents(A) {
  const lens = lensTest(A);
  const out = [];
  const themeCounts = {}; for (const t of THEMES) themeCounts[t] = 0;
  let inWindow = 0, belowCoverage = 0, lensDropped = 0;

  for (let i = 0; i < EV.length; i++) {
    const e = EV[i];
    if (e.t < A.win.t0 || e.t > A.win.t1) continue;
    inWindow++;
    if (e.sl < A.kt) { belowCoverage++; continue; }
    if (lens && !lens(e)) { lensDropped++; continue; }
    themeCounts[e.theme]++;
    if (!A.themes.has(e.theme)) continue;
    out.push(e);
  }
  return { events: out, themeCounts, inWindow, belowCoverage, lensDropped,
           total: EV.length };
}

let QCACHE = null;
function invalidate() { QCACHE = null; }
function q() { return QCACHE || (QCACHE = queryEvents(S)); }

/* ---------------------------------------------------------------- clustering
   Seven thousand points on a globe is confetti. Bin in screen space and draw
   one marker per occupied cell, sized by how many fell into it, so density
   reads as density instead of as an unreadable smear. The most-covered event in
   each cell supplies the label and the click target — the cell stands for
   something real rather than for a centroid nobody chose. */
function clusterScreen(pts, cell) {
  const bins = new Map();
  for (const p of pts) {
    const kx = (p.sx / cell) | 0, ky = (p.sy / cell) | 0;
    const key = kx * 4093 + ky;
    let b = bins.get(key);
    if (!b) { b = { n: 0, sx: 0, sy: 0, top: null, themes: new Set() }; bins.set(key, b); }
    b.n++; b.sx += p.sx; b.sy += p.sy;
    b.themes.add(p.e.theme);
    if (!b.top || p.e.sl > b.top.e.sl) b.top = p;
  }
  const out = [];
  for (const b of bins.values()) {
    out.push({
      n: b.n,
      sx: b.n === 1 ? b.top.sx : b.sx / b.n,
      sy: b.n === 1 ? b.top.sy : b.sy / b.n,
      e: b.top.e, d: b.top.d,
      mixed: b.themes.size > 1
    });
  }
  return out;
}
