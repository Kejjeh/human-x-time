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
    // Recorded even when the URL already says this: hashSelf is "the view the
    // bar is showing", not "what we wrote". Setting it only after a successful
    // write left it stale, and the hashchange guard then ignored the Back that
    // returned to exactly that view.
    hashSelf = h;
    if (h === location.hash) return;
    try { history.replaceState(null, '', h); } catch (_) { /* opaque origin; carry on */ }
  };
  // Dragging changes the rotation sixty times a second; the URL settles when the
  // gesture does.
  if (now) put(); else hashTimer = setTimeout(put, 400);
}

function readHash() {
  try {
    // No early return on an empty hash: "" is a legitimate view - the default
    // one - and navigating Back to a bare URL has to restore it rather than
    // leave whatever the previous entry had on screen.
    const raw = (location.hash || '').replace(/^#/, '');
    const p = {};
    for (const kv of raw.split('&')) {
      const i = kv.indexOf('=');
      if (i > 0) p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1));
    }
    const num = (v, lo, hi, d) => {
      const n = parseFloat(v);
      return isFinite(n) ? Math.max(lo, Math.min(hi, n)) : d;
    };

    /* `BY_Q[id]` and `LANG_BIT[lang]` are truthy for "constructor", "toString"
       and everything else on Object.prototype, so #s=constructor put a function
       into S.selection and #l=only:constructor emptied the globe while the lens
       dropdown still read "Every edition". Membership needs an own-property
       test, not truthiness. */
    const own = (o, k) => typeof k === 'string' && Object.prototype.hasOwnProperty.call(o, k);

    /* Every field is SET, not patched. Leaving a field alone when its key is
       absent is right for a first load and wrong for every later one: Back from
       a view with a selection to one without left the selection on screen, and
       the debounced writeHash then put it back, silently rewriting the history
       entry the user had just returned to. */
    S.kt = Math.round(num(p.c, 1, MAX_SL, 40));

    let t0 = 0, t1 = 3200;
    if (p.t) {
      const [a, b] = p.t.split('_');
      const u0 = num(a, 0, T_MAX, 0), u1 = num(b, 0, T_MAX, 3200);
      if (u1 - u0 >= 20) { t0 = u0; t1 = u1; }
    }
    S.win.t0 = t0; S.win.t1 = t1;

    const [ra, rb] = (p.r || '').split(',');
    S.rot.lam = num(ra, -100000, 100000, -10);
    S.rot.phi = num(rb, -89, 89, 25);
    ZOOMF = num(p.z, ZMIN, ZMAX, 0.86);
    S.selection = own(BY_Q, p.s) ? p.s : null;

    const off = new Set((p.th || '').split('.').filter(t => THEMES.includes(t)));
    // All themes off is an empty globe that reads as a broken page.
    S.themes = new Set(off.size && off.size < THEMES.length
      ? THEMES.filter(t => !off.has(t)) : THEMES);

    S.lens = '';
    if (p.l) {
      const [mode, lang] = p.l.split(':');
      if ((mode === 'only' || mode === 'not') && own(LANG_BIT, lang)) S.lens = p.l;
    }
    S.cluster = p.cl !== '0';
    S.basemap = p.b === 'chart' ? 'chart' : 'satellite';
    S.showPlates = p.p === '1';
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
  hashSelf = '';                // consumed; a later Back to this view must not be ignored
  readHash();                   // false only means "no hash", which is a real view too
  renderLens();                 // the lens options must exist before value= sticks
  syncControls();
  applyZoom();
  changed();
});
