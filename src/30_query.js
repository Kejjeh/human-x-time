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

/* Returns both shapes on purpose. `idx` is what the per-frame globe code walks -
   an Int32Array of positions into the typed columns, so the hot loop never
   touches an object. `events` is the same set as EV objects, for the panels and
   the histogram, which run once per state change and are far easier to read
   that way. */
function queryEvents(A) {
  const lens = lensTest(A);
  const out = [];
  const idx = new Int32Array(NEV);
  let m = 0;
  const themeCounts = {}; for (const t of THEMES) themeCounts[t] = 0;
  let inWindow = 0, belowCoverage = 0, lensDropped = 0;

  for (let i = 0; i < NEV; i++) {
    const e = EV[i];
    if (e.t < A.win.t0 || e.t > A.win.t1) continue;
    inWindow++;
    if (e.sl < A.kt) { belowCoverage++; continue; }
    if (lens && !lens(e)) { lensDropped++; continue; }
    themeCounts[e.theme]++;
    if (!A.themes.has(e.theme)) continue;
    out.push(e);
    idx[m++] = i;
  }
  return { events: out, idx: idx.subarray(0, m), n: m,
           themeCounts, inWindow, belowCoverage, lensDropped, total: NEV };
}

let QCACHE = null;
function invalidate() { QCACHE = null; }
function q() { return QCACHE || (QCACHE = queryEvents(S)); }

/* Clustering lives in 45_markers.js now, next to the typed arrays it fills. */
