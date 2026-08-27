/* ============================================================================
   TIME AXIS + PERIOD RIBBON + EVENT DENSITY
   The sibling site's signature was the stratigraphic ribbon in real ICS colours.
   The equivalent here is a histogram of the record itself: how many events
   survive, century by century. It shows the shape of what is remembered, which
   is the honest thing this corpus is actually about.
   ========================================================================== */

const ccv = document.getElementById('chroncv');
const cx2 = ccv.getContext('2d');

const TICK_H = 17, HIST_H = 56, ERA_H = 15, CENT_H = 12;
const CH_H = TICK_H + HIST_H + ERA_H + CENT_H + 4;
let CW = 0, SCALE = null;

function resizeChron() {
  CW = Math.max(120, ccv.clientWidth || ccv.parentElement.getBoundingClientRect().width);
  ccv.width = Math.round(CW * DPR); ccv.height = Math.round(CH_H * DPR);
  ccv.style.height = CH_H + 'px';
  cx2.setTransform(DPR, 0, 0, DPR, 0, 0);
}
function chronScale() { return makeScale(S.win.t0, S.win.t1, CW); }

/* 1, 2, 5 times a power of ten - the ladder that suits a logarithmic axis. */
function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
  const n = raw / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

/* The decade ladder is right for a window spanning orders of magnitude, which is
   what the asinh scale exists for. It is EMPTY for a narrow window that happens
   to contain none of its rungs: [74,000, 75,000] and [11,990, 12,010] each
   produced no labels at all - a time axis with no indication of what time it is
   showing, reachable by zooming in anywhere in deep time. So when the ladder
   comes up short, fall back to a linear nice step across the window. */
function tickValues(t0, t1) {
  const out = [];
  const p0 = Math.floor(Math.log10(Math.max(t0, 1))),
        p1 = Math.ceil(Math.log10(Math.max(t1, 1)));
  for (let p = p0; p <= p1; p++)
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, p);
      if (v >= t0 && v <= t1) out.push(v);
    }
  if (t0 <= 0) out.push(0);

  if (out.length < 3 && t1 > t0) {
    const step = niceStep((t1 - t0) / 5);
    const first = Math.ceil(t0 / step);
    const last = Math.floor(t1 / step);
    for (let i = first; i <= last; i++) {
      const v = i * step;                      // multiply, never accumulate
      if (out.indexOf(v) < 0) out.push(v);
    }
  }
  return out.sort((a, b) => b - a);
}

function drawBandLane(sc, rows, y, h, dark) {
  for (const iv of rows) {
    if (iv.e > S.win.t1 || iv.b < S.win.t0) continue;
    const x0 = Math.max(-2, sc.x(Math.min(iv.b, S.win.t1)));
    const x1 = Math.min(CW + 2, sc.x(Math.max(iv.e, S.win.t0)));
    const w = x1 - x0;
    if (w < 0.4) continue;
    cx2.fillStyle = iv.c;
    cx2.fillRect(x0, y, Math.max(w, 0.6), h - 1);
    if (w > 5) {
      cx2.strokeStyle = 'rgba(0,0,0,0.3)'; cx2.lineWidth = 0.5;
      cx2.beginPath(); cx2.moveTo(x0 + .25, y); cx2.lineTo(x0 + .25, y + h - 1); cx2.stroke();
    }
    if (w > 26) {
      cx2.font = `600 9px xt-cond, sans-serif`;
      const tw = cx2.measureText(iv.n).width;
      if (tw + 8 < w) {
        cx2.fillStyle = dark ? 'rgba(236,230,220,0.85)' : 'rgba(14,12,10,0.82)';
        cx2.fillText(iv.n, x0 + (w - tw) / 2, y + h - 4);
      }
    }
  }
}

/* Histogram of surviving events per column — the shape of the record.

   Walks the typed columns through F.idx, the way drawEvents does, rather than
   the EV objects. Same reason: at the coverage floor of 1 with the window at
   maximum this is 38,242 iterations, and it runs on every state change, which
   during a rail drag is every frame. The object walk cost a property load per
   event and - worse - a THEMES.indexOf per event, a linear scan to recover a
   number EVTH already holds. */
function drawHistogram(sc, yTop, h) {
  const F = q();
  const cols = Math.max(40, Math.floor(CW / 4));
  const bins = new Float64Array(cols);
  const nTh = THEMES.length;
  const binsTheme = THEMES.map(() => new Float64Array(cols));
  const idx = F.idx, N = F.n;
  const invW = cols / CW;
  for (let k = 0; k < N; k++) {
    const i = idx[k];
    const x = sc.x(EVT[i]);
    if (x < 0 || x >= CW) continue;
    const b = Math.min(cols - 1, Math.floor(x * invW));
    bins[b]++;
    const ti = EVTH[i];
    if (ti < nTh) binsTheme[ti][b]++;
  }
  let max = 0; for (const v of bins) max = Math.max(max, v);
  if (max <= 0) {
    cx2.fillStyle = CSSV['chalk-faint'];
    cx2.font = '400 11px xt-sans, sans-serif';
    cx2.fillText('nothing in this window at this coverage', 12, yTop + h / 2);
    return;
  }
  const bw = CW / cols;
  for (let b = 0; b < cols; b++) {
    if (!bins[b]) continue;
    let acc = 0;
    for (let ti = 0; ti < THEMES.length; ti++) {
      const v = binsTheme[ti][b];
      if (!v) continue;
      const hh = (v / max) * (h - 6);
      cx2.fillStyle = withAlpha(CSSV[THEMES[ti]], 0.88);
      cx2.fillRect(b * bw, yTop + h - 3 - acc - hh, Math.max(bw - 0.5, 0.8), hh);
      acc += hh;
    }
  }
  cx2.fillStyle = CSSV['chalk-faint'];
  cx2.font = '400 9px xt-mono, monospace';
  cx2.fillText(`${max} events at the peak`, 6, yTop + 10);
}

function drawChron() {
  const sc = SCALE = chronScale();
  cx2.clearRect(0, 0, CW, CH_H);

  cx2.font = '400 9.5px xt-mono, monospace';
  let lastX = -999;
  const tv = tickValues(S.win.t0, S.win.t1);
  for (let ti = 0; ti < tv.length; ti++) {
    const t = tv[ti];
    const x = sc.x(t);
    if (x < 2 || x > CW - 2) continue;
    cx2.strokeStyle = withAlpha(CSSV['chalk-faint'], 0.3);
    cx2.beginPath(); cx2.moveTo(x, TICK_H - 5); cx2.lineTo(x, TICK_H); cx2.stroke();
    // How close this tick's nearest neighbour is decides how precise its label
    // has to be; see fmtYbpLabel.
    let gap = Infinity;
    if (ti > 0) gap = Math.min(gap, Math.abs(t - tv[ti - 1]));
    if (ti < tv.length - 1) gap = Math.min(gap, Math.abs(t - tv[ti + 1]));
    const lab = fmtYbpLabel(t, isFinite(gap) ? gap : 0);
    const w = cx2.measureText(lab).width;
    if (x - w / 2 > lastX + 8 && x + w / 2 < CW - 2) {
      cx2.fillStyle = CSSV['chalk-faint'];
      cx2.fillText(lab, x - w / 2, TICK_H - 7);
      lastX = x + w / 2;
    }
  }

  drawHistogram(sc, TICK_H, HIST_H);

  let y = TICK_H + HIST_H;
  drawBandLane(sc, ERAS, y, ERA_H, false);
  drawBandLane(sc, CENTURIES, y + ERA_H, CENT_H, true);

  cx2.strokeStyle = CSSV.rule; cx2.lineWidth = 1;
  cx2.beginPath(); cx2.moveTo(0, y + .5); cx2.lineTo(CW, y + .5); cx2.stroke();

  if (S.selection && BY_Q[S.selection]) {
    const x = sc.x(BY_Q[S.selection].t);
    if (x >= -1 && x <= CW + 1) {
      cx2.strokeStyle = CSSV.amber; cx2.lineWidth = 1;
      cx2.beginPath(); cx2.moveTo(x + .5, 0); cx2.lineTo(x + .5, CH_H); cx2.stroke();
    }
  }
}
