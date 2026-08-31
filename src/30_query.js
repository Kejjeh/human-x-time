/* ============================================================================
   THE QUERY
   One function. Time window, coverage floor, theme filter, Wikidata category and
   language lens are not five features — they are one query with different axes
   pinned, exactly as on the sibling site. Every renderer reads its output.
   ========================================================================== */

/* Returns the mask bit and which way the test runs, rather than a closure over
   an EV object - the walk below reads EVM, not e.m. */
function lensTest(A) {
  if (!A.lens) return null;
  const [mode, lang] = A.lens.split(':');
  const bit = LANG_BIT[lang];
  if (!bit) return null;
  return { bit, want: mode === 'only' };
}

/* Returns both shapes on purpose. `idx` is what the per-frame globe code walks -
   an Int32Array of positions into the typed columns, so the hot loop never
   touches an object. `events` is the same set as EV objects, for the panels and
   the histogram, which run once per state change and are far easier to read
   that way. */
/* Scratch, allocated once.
   `new Int32Array(NEV)` is 153 KB every call, and subarray keeps the whole
   buffer alive, so a rail drag threw away 153 KB a frame plus an events array
   that grew to 38,242 entries by repeated push. Everything else on this path
   stopped allocating two commits ago; this was the last one that had not.
   Both are reused. Nothing may hold a query result across an invalidate(),
   which nothing does - QCACHE is the only reference and every consumer calls
   q() fresh. */
const QIDX = new Int32Array(NEV);
const QOUT = [];
const THEME_ON = new Uint8Array(64);       // A.themes as bits, so the walk does
                                           // not hash a string per event

/* Category counts, allocated once for the same reason everything else here is.
   64 slots against 62 Wikidata classes in the corpus. */
const CAT_COUNTS = new Uint32Array(64);

function queryEvents(A) {
  const lens = lensTest(A);
  const lensBit = lens ? lens.bit : 0, lensWant = lens ? lens.want : false;
  const t0 = A.win.t0, t1 = A.win.t1, kt = A.kt;
  const nTh = THEMES.length;
  for (let t = 0; t < nTh; t++) THEME_ON[t] = A.themes.has(THEMES[t]) ? 1 : 0;
  /* -1 is "no category pinned", so the test in the walk is one integer compare
     rather than a string compare per event. An unrecognised key pins nothing
     rather than emptying the globe; readHash validates against CATS as well. */
  const catIx = A.cat && CAT_IX[A.cat] !== undefined ? CAT_IX[A.cat] : -1;

  const out = QOUT; out.length = 0;
  const idx = QIDX;
  let m = 0;
  const counts = new Uint32Array(nTh);
  CAT_COUNTS.fill(0);
  let inWindow = 0, belowCoverage = 0, lensDropped = 0, catDropped = 0;

  for (let i = 0; i < NEV; i++) {
    const t = EVT[i];
    if (t < t0 || t > t1) continue;
    inWindow++;
    if (EVSL[i] < kt) { belowCoverage++; continue; }
    if (lensBit && ((EVM[i] & lensBit) !== 0) !== lensWant) { lensDropped++; continue; }
    const th = EVTH[i];
    /* Each tally counts everything EXCEPT its own axis. That is the whole rule,
       and both halves of it have a wrong answer sitting right next to them.

       A theme count is what clicking that chip would give you, so it has to
       respect a pinned category: with Capitals pinned the chips read 262
       Conflict and 266 Politics beside a globe showing 227 of anything, and
       clicking Politics did not produce 266 of them.

       A category count has to respect the themes, for the same reason - but it
       cannot sit below the category test, or every category except the pinned
       one reports zero and the control can never be moved to a different one. */
    const catOK = catIx < 0 || EVC[i] === catIx;
    if (catOK) counts[th]++;
    if (!THEME_ON[th]) continue;
    CAT_COUNTS[EVC[i]]++;
    if (!catOK) { catDropped++; continue; }
    out.push(EV[i]);
    idx[m++] = i;
  }

  const themeCounts = {};
  for (let t = 0; t < nTh; t++) themeCounts[THEMES[t]] = counts[t];
  return { events: out, idx: idx.subarray(0, m), n: m,
           themeCounts, catCounts: CAT_COUNTS, inWindow, belowCoverage,
           lensDropped, catDropped, total: NEV };
}

let QCACHE = null;
function invalidate() { QCACHE = null; }
function q() { return QCACHE || (QCACHE = queryEvents(S)); }

/* Clustering lives in 45_markers.js now, next to the typed arrays it fills. */
