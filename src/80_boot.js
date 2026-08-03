/* ============================================================================
   WIRING
   ========================================================================== */
let needGlobe = true, needChron = true, needRail = true, needPanel = true;
function markAll() { needGlobe = needChron = needRail = needPanel = true; }
function changed() { invalidate(); markAll(); paintOnInput(); writeHash(); }

function setCoverage(n) {
  const v = Math.max(1, Math.min(MAX_SL, Math.round(n)));
  if (v === S.kt) return;
  S.kt = v; changed();
}
function setWindow(t0, t1) {
  const span = Math.max(20, Math.min(T_MAX, t1 - t0));
  let a = Math.max(0, t0), b = a + span;
  if (b > T_MAX) { b = T_MAX; a = Math.max(0, b - span); }
  S.win.t0 = a; S.win.t1 = b; changed();
}
function setSelection(qid) { S.selection = qid; changed(); }

/* -------------------------------------------------------------------- globe */
let gDrag = null, gMoved = 0;
const gVel = [];

/* One clamp for the zoom, in one place. The wheel, the keyboard and the pinch
   were otherwise each carrying their own copy of the same two magic numbers. */
const ZMIN = 0.45, ZMAX = 4.5;
function setZoom(z) {
  const n = Math.max(ZMIN, Math.min(ZMAX, z));
  if (n === ZOOMF) return false;
  ZOOMF = n; applyZoom(); needGlobe = true;
  return true;
}

/* Two-finger zoom.
 *
 * touch-action:none already routes touches here as pointer events, so one finger
 * has always dragged; there was simply nothing listening for a second. Keep the
 * set of live pointers and treat "two or more down" as the pinch state.
 *
 * The baseline is re-established whenever the set changes - a finger added, one
 * lifted, a third landing - because otherwise the distance ratio is measured
 * against a pair that no longer exists and the globe jumps. */
const PTRS = new Map();
let pinch = null;

function pinchState() {
  const it = PTRS.values();
  const a = it.next().value, b = it.next().value;
  if (!a || !b) return null;
  return { d: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
           mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
}
function rebasePinch() {
  const s = pinchState();
  pinch = s ? { d0: s.d, z0: ZOOMF, mx: s.mx, my: s.my } : null;
}

gcv.addEventListener('pointerdown', e => {
  try { gcv.setPointerCapture(e.pointerId); } catch (_) { /* drag works without it */ }
  // A primary pointerdown means a gesture is starting with nothing else held, so
  // it is also the moment to forget any pointer whose "up" we never received.
  if (e.isPrimary) { PTRS.clear(); pinch = null; }
  PTRS.set(e.pointerId, { x: e.clientX, y: e.clientY });
  S.spin.lam = S.spin.phi = 0;
  TW = null;                 // a hand on the globe outranks a fly-to in progress
  gVel.length = 0;
  gcv.classList.add('dragging');
  if (PTRS.size >= 2) {
    gDrag = null;            // a pinch is not a drag...
    gMoved = 999;            // ...and must not land as a click when it ends
    rebasePinch();
    return;
  }
  gDrag = { x: e.clientX, y: e.clientY };
  gMoved = 0;
});
gcv.addEventListener('pointermove', e => {
  if (PTRS.has(e.pointerId)) PTRS.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pinch && PTRS.size >= 2) {
    const s = pinchState();
    if (s) {
      setZoom(pinch.z0 * (s.d / pinch.d0));
      const k = 180 / (GR * Math.PI) * 1.1;
      S.rot.lam += (s.mx - pinch.mx) * k;
      S.rot.phi = Math.max(-89, Math.min(89, S.rot.phi + (s.my - pinch.my) * k));
      pinch.mx = s.mx; pinch.my = s.my;
      needGlobe = true; paintOnInput();
    }
    return;
  }
  const rect = gcv.getBoundingClientRect();
  if (gDrag) {
    const dx = e.clientX - gDrag.x, dy = e.clientY - gDrag.y;
    gMoved += Math.abs(dx) + Math.abs(dy);
    const k = 180 / (GR * Math.PI) * 1.1;
    S.rot.lam += dx * k;
    S.rot.phi = Math.max(-89, Math.min(89, S.rot.phi + dy * k));
    gVel.push({ dx, dy, t: performance.now() });
    if (gVel.length > 5) gVel.shift();
    gDrag = { x: e.clientX, y: e.clientY };
    needGlobe = true; paintOnInput();
    return;
  }
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const best = hitTest(mx, my);
  const id = best ? best.id : null;
  if (id !== S.hover) { S.hover = id; needGlobe = true; paintOnInput(); }
  const tip = document.getElementById('tip');
  if (id && BY_Q[id]) {
    const ev = BY_Q[id];
    tip.innerHTML = `<span class="t">${esc(ev.n)}</span><span class="d">${fmtYear(ev.y)} · ${ev.sl} langs${
      best.n > 1 ? ` · +${best.n - 1} more here` : ''}</span>`;
    tip.style.left = best.x + 'px'; tip.style.top = best.y + 'px';
    tip.classList.add('on'); gcv.style.cursor = 'pointer';
  } else { tip.classList.remove('on'); gcv.style.cursor = ''; }
});
function endGlobeDrag(e) {
  gcv.classList.remove('dragging');   // before the guard: a cancelled pinch has no gDrag
  if (!gDrag) return;
  gDrag = null;
  if (!RM.matches && gVel.length) {
    const now = performance.now();
    const recent = gVel.filter(v => now - v.t < 90);
    if (recent.length) {
      const k = 180 / (GR * Math.PI) * 1.1;
      S.spin.lam = recent.reduce((a, v) => a + v.dx, 0) / recent.length * k * 0.9;
      S.spin.phi = recent.reduce((a, v) => a + v.dy, 0) / recent.length * k * 0.9;
    }
  }
  if (gMoved < 5) {
    const rect = gcv.getBoundingClientRect();
    const best = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    setSelection(best ? best.id : null);
  }
}
/* Lifting a finger mid-pinch must not end the gesture, and must not be read as a
   click. Only the last one up is a real pointerup.

   pointercancel has to do exactly the same bookkeeping, which it did not: it
   nulled the pinch and stopped. Two ways that bites, both reachable on a real
   phone - Android cancels a stationary finger when the long-press gesture takes
   over, iOS cancels one on palm rejection. Three fingers down and the first is
   cancelled: the baseline still describes a pair that no longer exists, so the
   next move divides by the wrong distance and the globe snaps to minimum zoom
   and jumps a hundred degrees of longitude in one frame. Two fingers down and
   one is cancelled: the survivor never gets a drag origin back, so it stops
   rotating the globe and starts hovering tooltips instead, and the grabbing
   cursor is still stuck on when everything is finally lifted. */
function releasePointer(e) {
  PTRS.delete(e.pointerId);
  if (PTRS.size >= 2) { rebasePinch(); return true; }
  pinch = null;
  if (PTRS.size === 1) {
    const p = PTRS.values().next().value;
    gDrag = { x: p.x, y: p.y, t: performance.now() };   // hand back without a jump
    gMoved = 999; gVel.length = 0;
    return true;
  }
  return false;
}
gcv.addEventListener('pointerup', e => { if (!releasePointer(e)) endGlobeDrag(e); });
gcv.addEventListener('pointercancel', e => {
  if (releasePointer(e)) return;
  gDrag = null; gVel.length = 0;
  gcv.classList.remove('dragging');
});
gcv.addEventListener('wheel', e => {
  e.preventDefault();
  setZoom(ZOOMF * (e.deltaY > 0 ? 0.92 : 1.087));
  paintOnInput();
}, { passive: false });
gcv.addEventListener('keydown', e => {
  const step = e.shiftKey ? 15 : 5;
  if (e.key === 'ArrowLeft') S.rot.lam -= step;
  else if (e.key === 'ArrowRight') S.rot.lam += step;
  else if (e.key === 'ArrowUp') S.rot.phi = Math.min(89, S.rot.phi + step);
  else if (e.key === 'ArrowDown') S.rot.phi = Math.max(-89, S.rot.phi - step);
  else if (e.key === '+' || e.key === '=') setZoom(ZOOMF * 1.12);
  else if (e.key === '-') setZoom(ZOOMF * 0.89);
  else if (e.key === 'Escape') { setSelection(null); return e.preventDefault(); }
  else return;
  needGlobe = true; paintOnInput(); e.preventDefault();
});

/* -------------------------------------------------------------------- chron */
let cDrag = null;
const chronPos = e => { const r = ccv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
ccv.addEventListener('pointerdown', e => {
  ccv.setPointerCapture(e.pointerId);
  cDrag = { x: chronPos(e).x, t0: S.win.t0, t1: S.win.t1 };
});
ccv.addEventListener('pointermove', e => {
  if (!cDrag) return;
  const p = chronPos(e);
  const k = Math.max((cDrag.t1 - cDrag.t0) / 46, 1e-9);
  const u0 = Math.asinh(cDrag.t0 / k), u1 = Math.asinh(cDrag.t1 / k);
  const shift = ((p.x - cDrag.x) / CW) * (u1 - u0);
  let a = k * Math.sinh(u0 + shift), b = k * Math.sinh(u1 + shift);
  if (a < 0) { b -= a; a = 0; }
  if (b > T_MAX) { a -= (b - T_MAX); b = T_MAX; a = Math.max(0, a); }
  setWindow(a, b);
});
ccv.addEventListener('pointerup', () => { cDrag = null; });
ccv.addEventListener('pointercancel', () => { cDrag = null; });
ccv.addEventListener('wheel', e => {
  e.preventDefault();
  const sc = SCALE || chronScale();
  const tp = Math.max(0, sc.t(chronPos(e).x));
  const f = e.deltaY > 0 ? 1.16 : 0.862;
  const k = Math.max((S.win.t1 - S.win.t0) / 46, 1e-9);
  const up = Math.asinh(tp / k);
  const u0 = Math.asinh(S.win.t0 / k), u1 = Math.asinh(S.win.t1 / k);
  setWindow(Math.max(0, k * Math.sinh(up + (u0 - up) * f)),
            Math.min(T_MAX, k * Math.sinh(up + (u1 - up) * f)));
}, { passive: false });
document.getElementById('presets').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  setWindow(+b.dataset.t0, +b.dataset.t1);
});

/* --------------------------------------------------------------------- rail */
let rDrag = false;
const railSet = e => { const r = rcv.getBoundingClientRect(); setCoverage(yToSl(e.clientY - r.top)); };
rcv.addEventListener('pointerdown', e => { rcv.setPointerCapture(e.pointerId); rDrag = true; railSet(e); });
rcv.addEventListener('pointermove', e => { if (rDrag) railSet(e); });
rcv.addEventListener('pointerup', () => { rDrag = false; });
rcv.addEventListener('pointercancel', () => { rDrag = false; });
rcv.addEventListener('keydown', e => {
  const f = e.shiftKey ? 1.6 : 1.15;
  if (e.key === 'ArrowUp' || e.key === 'ArrowRight') setCoverage(Math.max(S.kt + 1, S.kt * f));
  else if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') setCoverage(Math.min(S.kt - 1, S.kt / f));
  else if (e.key === 'Home') setCoverage(1);
  else if (e.key === 'End') setCoverage(MAX_SL);
  else return;
  e.preventDefault();
});
document.getElementById('btn-allcov').addEventListener('click', () => setCoverage(1));

/* ----------------------------------------------------------------- controls */
document.getElementById('themes').addEventListener('click', e => {
  const b = e.target.closest('.theme'); if (!b) return;
  const t = b.dataset.theme;
  if (S.themes.has(t)) S.themes.delete(t); else S.themes.add(t);
  if (!S.themes.size) S.themes = new Set(THEMES);
  changed();
});
document.getElementById('lens').addEventListener('change', e => { S.lens = e.target.value; changed(); });
elDetail.addEventListener('click', e => {
  const b = e.target.closest('[data-q]'); if (!b) return;
  setSelection(b.dataset.q); elDetail.scrollTop = 0;
});
document.getElementById('btn-cluster').addEventListener('click', e => {
  S.cluster = !S.cluster;
  e.currentTarget.setAttribute('aria-pressed', String(S.cluster));
  needGlobe = true; paintOnInput();
});
document.getElementById('btn-basemap').addEventListener('click', e => {
  S.basemap = S.basemap === 'satellite' ? 'chart' : 'satellite';
  const sat = S.basemap === 'satellite';
  e.currentTarget.setAttribute('aria-pressed', String(sat));
  e.currentTarget.textContent = sat ? 'Satellite' : 'Chart';
  needGlobe = true; paintOnInput();
});
document.getElementById('btn-plates').addEventListener('click', e => {
  S.showPlates = !S.showPlates;
  e.currentTarget.setAttribute('aria-pressed', String(S.showPlates));
  needGlobe = true; paintOnInput();
});
document.getElementById('btn-theme').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const dark = cur ? cur === 'dark' : !matchMedia('(prefers-color-scheme: light)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
  readPalette(); SURF.key = ''; markAll(); paintOnInput();
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  readPalette(); SURF.key = ''; markAll(); paintOnInput();
});

/* ---------------------------------------------------------------- rendering */
/* render(dt) does the work, frame(now) only schedules it, and paintOnInput
   paints straight from the handler when rAF is not running — which it is not in
   a document whose visibilityState is "hidden". Learned on the sibling site,
   where the whole UI drew from inside the rAF callback and therefore never
   appeared at all in that case. */
let last = performance.now(), lastPaint = 0, lastRafAt = -1e9, painting = false;

/* -------------------------------------------------------------- flying there
   A search result three quarters of the way round the globe is not much use if
   it simply appears behind you. The shortest way round is chosen by unwrapping
   the target longitude to within 180 degrees of where we are, so the globe never
   spins the long way for the sake of arithmetic. */
let TW = null;
function ease(t) { return t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

function flyToEvent(i) {
  const e = EV[i];
  if (!e) return;
  let lam = -e.lng;
  while (lam - S.rot.lam > 180) lam -= 360;
  while (lam - S.rot.lam < -180) lam += 360;
  S.spin.lam = S.spin.phi = 0;
  TW = {
    t: 0, dur: RM.matches ? 0.01 : 0.9,
    from: { lam: S.rot.lam, phi: S.rot.phi },
    to: { lam, phi: Math.max(-70, Math.min(70, e.lat)) }
  };
  setSelection(e.q);
}

function render(dt) {
  lastPaint = performance.now();
  sizeGuard();

  if (TW) {
    TW.t += dt;
    const p = Math.min(1, TW.t / TW.dur), k = ease(p);
    S.rot.lam = TW.from.lam + (TW.to.lam - TW.from.lam) * k;
    S.rot.phi = TW.from.phi + (TW.to.phi - TW.from.phi) * k;
    needGlobe = true;
    if (p >= 1) TW = null;
  }

  if ((S.spin.lam || S.spin.phi) && !gDrag) {
    S.rot.lam += S.spin.lam;
    S.rot.phi = Math.max(-89, Math.min(89, S.rot.phi + S.spin.phi));
    S.spin.lam *= 0.94; S.spin.phi *= 0.94;
    if (Math.abs(S.spin.lam) < 0.008 && Math.abs(S.spin.phi) < 0.008) S.spin.lam = S.spin.phi = 0;
    needGlobe = true;
  }

  if (needGlobe) { drawGlobe(dt); needGlobe = false; }
  if (needChron) { drawChron(); needChron = false; }
  if (needRail) { drawRail(); needRail = false; }
  if (needPanel) {
    const F = q();
    renderDetail(); renderThemes(); renderLens();
    document.getElementById('hdr-count').textContent = EV.length.toLocaleString();
    document.getElementById('hd-cov').textContent = S.kt;
    document.getElementById('hd-n').textContent = F.events.length.toLocaleString();
    document.getElementById('rail-n').textContent = S.kt + '+';
    const span = S.win.t1 - S.win.t0;
    document.getElementById('rd-window').textContent =
      S.win.t1 >= T_MAX * 0.99 ? 'all 75,000 years'
        : `${fmtYbpLabel(S.win.t1)} to ${fmtYbpLabel(S.win.t0)}`;
    const dropped = F.inWindow - F.events.length;
    document.getElementById('rd-drop').innerHTML = dropped > 0
      ? `<b>${dropped.toLocaleString()}</b> hidden by coverage, theme or lens`
      : '';
    document.getElementById('hd-sub').textContent =
      S.lens ? `${F.lensDropped.toLocaleString()} events in this window fail the language filter.`
        : `${F.belowCoverage.toLocaleString()} events in this window are remembered in fewer than ${S.kt} editions.`;
    document.getElementById('lens-hint').textContent = S.lens
      ? 'Filtering by which Wikipedia edition carries an article. Absence is a fact about the record, not about history.'
      : 'Pick an edition to see what it does — or does not — cover.';
    rcv.setAttribute('aria-valuenow', S.kt);
    ccv.setAttribute('aria-valuenow', Math.round(S.win.t1));
    needPanel = false;
  }
}
function frame(now) {
  lastRafAt = performance.now();
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  try { render(dt); } catch (err) { console.error('render failed', err); }
  requestAnimationFrame(frame);
}
function renderNow() {
  last = performance.now();
  try { render(0.016); } catch (err) { console.error('render failed', err); }
}
/* Has the animation loop actually run lately?
   The old test asked whether a frame had been *requested*, which is true forever
   after the first one — rAF stops firing but the flag never clears — while
   lastPaint keeps being refreshed by the watchdog. So the guard read as "rAF is
   alive" permanently and paintOnInput returned early on every input, dropping
   26 of 36 moves in a drag. Ask when a frame last ran instead. */
function rafIsLive() { return performance.now() - lastRafAt < 120; }

/* Paint on every input event. No time throttle.

   A throttle needs a trailing timer to make up the frames it skips, and in a
   document whose visibilityState is hidden — the case that made painting from
   input necessary in the first place — chained timers are clamped to about 1Hz.
   So the throttle dropped three quarters of a drag and the recovery never came:
   36 pointer moves produced 9 paints.

   There is no need for one. A paint costs ~1ms on a cache hit and a few ms on a
   miss, the adaptive scale keeps it there, the re-entrancy guard stops overlap,
   and the event loop cannot deliver the next move until this handler returns —
   so the input rate is self-limiting. Sharpening is still deferred, because that
   frame is expensive and belongs in the quiet after the gesture. */
let sharpen = null;

function scheduleSharpen() {
  if (sharpen) clearTimeout(sharpen);
  sharpen = setTimeout(() => {
    sharpen = null;
    needGlobe = true;
    renderNow();                 // one crisp frame, once the hands have stopped
  }, 190);
}

function paintOnInput() {
  LAST_INPUT_AT = performance.now();
  lastInteraction = LAST_INPUT_AT;
  scheduleSharpen();
  writeHash();                    // debounced; the URL settles when the gesture does
  if (painting || rafIsLive()) return;
  painting = true;
  try { renderNow(); } finally { painting = false; }
}


/* ------------------------------------------------------- the animation clock

   Measured in a document whose visibilityState is "hidden":

       requestAnimationFrame        0 Hz   (never fires)
       main-thread setInterval(16)  1.3 Hz (clamped by intensive throttling)
       Worker setInterval(16)      61.7 Hz (not throttled)

   Input already paints itself, so dragging is smooth regardless. But anything
   that animates on its own — the travelling dots along causal arcs, the pulse
   on planet-wide facts, the inertia after a flick, Replay sweeping the
   knowledge rail — has no clock at all, and ran at the watchdog's 1.3 Hz.

   A dedicated worker's timer is exempt from that throttling, so one posts a
   tick and the main thread renders on it. MessageChannel also escapes the
   clamp, at 330,000 Hz, but that is a busy-spin rather than a clock.

   The beat stands down the moment rAF starts working, so a normal foreground
   tab is driven by rAF exactly as before, and it stops rendering after two
   minutes without input so a genuinely backgrounded tab is not animated for
   nobody. If the host's CSP forbids blob workers it degrades to what we had. */
let beat = null;
let lastInteraction = performance.now();
const BEAT_IDLE_MS = 120000;

function isAnimating() {
  if (RM.matches) return false;
  if (TW) return true;                                    // flying to a search hit
  if (Math.abs(S.spin.lam) > 0.008 || Math.abs(S.spin.phi) > 0.008) return true;
  return false;
}

function onBeat() {
  if (rafIsLive()) return;                       // the real loop is back
  if (performance.now() - lastInteraction > BEAT_IDLE_MS) return;
  const dirty = needGlobe || needChron || needRail || needPanel;
  if (!dirty && !isAnimating()) return;
  const now = performance.now();
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  if (isAnimating()) needGlobe = true;           // arcs and spin repaint the globe
  try { render(dt); } catch (err) { console.error('render failed', err); }
}

function startHeartbeat() {
  if (beat) return;
  try {
    const url = URL.createObjectURL(new Blob(
      ['setInterval(function(){postMessage(0)},16);'], { type: 'text/javascript' }));
    beat = new Worker(url);
    URL.revokeObjectURL(url);
    beat.onmessage = onBeat;
  } catch (_) {
    beat = null;                                  // CSP may forbid it; carry on
  }
}

setInterval(() => {
  if (performance.now() - lastPaint > 400 &&
      (needGlobe || needChron || needRail || needPanel)) renderNow();
}, 250);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { markAll(); renderNow(); }
});

function boot() {
  readPalette();
  readHash();                     // a shared view wins over the defaults...
  renderLens();                   // ...and the lens needs its options before value= sticks
  syncControls();                 // ...and the controls have to say so
  resizeGlobe(); resizeChron(); resizeRail();
  changed();
  renderNow();
  requestAnimationFrame(frame);
  startHeartbeat();
  window.__BOOT_OK = true;
}

/* The sibling site lost an entire build to a boot() that threw one line before
   requestAnimationFrame(frame) — a cosmetic swatch colour killed the render loop,
   and nothing detected it because the page still drew, once, off a watchdog. The
   loop must start even if setup fails, and the flags are what lets
   tools/smoke_test.py ask from outside whether boot actually ran. */
function safeBoot() {
  window.__BOOT_OK = false;
  window.__BOOT_ERR = null;
  try { boot(); }
  catch (err) {
    window.__BOOT_ERR = String((err && err.stack) || err);
    console.error('boot failed; starting the render loop anyway', err);
    try { markAll(); renderNow(); } catch (_) {}
    requestAnimationFrame(frame);
    startHeartbeat();
  }
}
const ro = new ResizeObserver(() => { resizeGlobe(); resizeChron(); resizeRail(); markAll(); renderNow(); });
ro.observe(document.getElementById('stage'));
ro.observe(document.querySelector('.chron'));
ro.observe(document.querySelector('.rail'));
if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { markAll(); renderNow(); });
safeBoot();
