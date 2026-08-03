/* ============================================================================
   THE VIEW IN THE URL

   Where you are on the globe, how far back the window reaches, how much of the
   world has to remember something before it appears, which themes are on and
   which language lens is applied - all of it is a point in a small state space,
   and until now none of it left the tab.

   Two rules:

   1. A malformed hash must never stop the page. Every value is parsed
      defensively, clamped to its own range, and checked against the data before
      it is applied. The whole read is wrapped and returns false on failure. A
      URL is user input from a stranger.

   2. history.replaceState throws in a sandboxed iframe with an opaque origin,
      which is where this page is often embedded. Not worth breaking a working
      page over: the failure is swallowed and there is simply no shareable URL
      in that context.
   ========================================================================== */

let hashTimer = null;
let hashSelf = '';

function encodeHash() {
  const p = [];
  p.push('c=' + S.kt);
  p.push('t=' + Math.round(S.win.t0) + '_' + Math.round(S.win.t1));
  p.push('r=' + S.rot.lam.toFixed(1) + ',' + S.rot.phi.toFixed(1));
  p.push('z=' + ZOOMF.toFixed(2));
  if (S.selection) p.push('s=' + S.selection);
  const off = THEMES.filter(t => !S.themes.has(t));
  if (off.length) p.push('th=' + off.join('.'));
  if (S.lens) p.push('l=' + S.lens);
  if (!S.cluster) p.push('cl=0');
  if (S.basemap !== 'satellite') p.push('b=' + S.basemap);
  if (S.showPlates) p.push('p=1');
  return '#' + p.join('&');
}

function writeHash(now) {
  clearTimeout(hashTimer);
  const put = () => {
    const h = encodeHash();
    if (h === location.hash) return;
    hashSelf = h;
    try { history.replaceState(null, '', h); } catch (_) { /* opaque origin; carry on */ }
  };
  // Dragging changes the rotation sixty times a second; the URL settles when the
  // gesture does.
  if (now) put(); else hashTimer = setTimeout(put, 400);
}

function readHash() {
  try {
    const raw = (location.hash || '').replace(/^#/, '');
    if (!raw) return false;
    const p = {};
    for (const kv of raw.split('&')) {
      const i = kv.indexOf('=');
      if (i > 0) p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1));
    }
    const num = (v, lo, hi, d) => {
      const n = parseFloat(v);
      return isFinite(n) ? Math.max(lo, Math.min(hi, n)) : d;
    };

    S.kt = Math.round(num(p.c, 1, MAX_SL, S.kt));
    if (p.t) {
      const [a, b] = p.t.split('_');
      const t0 = num(a, 0, T_MAX, S.win.t0), t1 = num(b, 0, T_MAX, S.win.t1);
      if (t1 - t0 >= 20) { S.win.t0 = t0; S.win.t1 = t1; }
    }
    if (p.r) {
      const [a, b] = p.r.split(',');
      S.rot.lam = num(a, -100000, 100000, S.rot.lam);
      S.rot.phi = num(b, -89, 89, S.rot.phi);
    }
    if (p.z) ZOOMF = num(p.z, ZMIN, ZMAX, ZOOMF);
    if (p.s && BY_Q[p.s]) S.selection = p.s;
    if (p.th) {
      const off = new Set(p.th.split('.').filter(t => THEMES.includes(t)));
      // All themes off is an empty globe that reads as a broken page.
      if (off.size < THEMES.length) S.themes = new Set(THEMES.filter(t => !off.has(t)));
    }
    if (p.l) {
      const [mode, lang] = p.l.split(':');
      if ((mode === 'only' || mode === 'not') && LANG_BIT[lang]) S.lens = p.l;
    }
    if (p.cl === '0') S.cluster = false;
    if (p.b === 'chart' || p.b === 'satellite') S.basemap = p.b;
    if (p.p === '1') S.showPlates = true;
    return true;
  } catch (err) {
    console.warn('unreadable view in the URL; using defaults', err);
    return false;
  }
}

/** Controls whose pressed state lives in the DOM rather than in a render pass. */
function syncControls() {
  const set = (id, on, text) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.setAttribute('aria-pressed', String(on));
    if (text) el.textContent = text;
  };
  set('btn-cluster', S.cluster);
  set('btn-basemap', S.basemap === 'satellite', S.basemap === 'satellite' ? 'Satellite' : 'Chart');
  set('btn-plates', S.showPlates);
  const lens = document.getElementById('lens');
  if (lens) lens.value = S.lens;
}

window.addEventListener('hashchange', () => {
  if (location.hash === hashSelf) return;
  if (!readHash()) return;
  renderLens();                 // the lens options must exist before value= sticks
  syncControls();
  resizeGlobe();
  SURF.key = '';
  changed();
});
