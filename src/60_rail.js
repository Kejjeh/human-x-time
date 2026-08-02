/* ============================================================================
   THE COVERAGE RAIL
   Perpendicular to the time axis, in the one accent colour reserved for it —
   the same move the sibling site makes with knowledge-time, asking a question
   this data can actually answer. Not "when did we come to believe this?" but
   "how much of the world remembers it?"
   ========================================================================== */

const rcv = document.getElementById('railcv');
const rx = rcv.getContext('2d');
let RW = 0, RH = 0;
const RPAD = 18;

function resizeRail() {
  RW = Math.max(40, rcv.clientWidth || rcv.getBoundingClientRect().width);
  RH = Math.max(80, rcv.clientHeight || rcv.getBoundingClientRect().height);
  rcv.width = Math.round(RW * DPR); rcv.height = Math.round(RH * DPR);
  rx.setTransform(DPR, 0, 0, DPR, 0, 0);
}

/* Sitelink counts are heavy-tailed — half the corpus sits under 27 editions and
   the top is near 300 — so the rail is logarithmic or the whole scale is spent
   on a handful of capitals. */
const railU = n => Math.log(Math.max(1, n));
const RAIL_MAX = () => railU(MAX_SL);
function slToY(n) { return RPAD + (1 - railU(n) / RAIL_MAX()) * (RH - RPAD * 2); }
function yToSl(y) {
  const f = 1 - (y - RPAD) / (RH - RPAD * 2);
  return Math.round(Math.exp(Math.max(0, Math.min(1, f)) * RAIL_MAX()));
}

/* How many events survive each coverage floor, precomputed once. */
const SURVIVORS = (() => {
  const counts = new Array(MAX_SL + 2).fill(0);
  for (const e of EV) counts[Math.min(e.sl, MAX_SL)]++;
  const cum = new Array(MAX_SL + 2).fill(0);
  let run = 0;
  for (let n = MAX_SL; n >= 1; n--) { run += counts[n]; cum[n] = run; }
  return cum;
})();
const survivorsAt = n => SURVIVORS[Math.max(1, Math.min(MAX_SL, n))] || 0;

function drawRail() {
  rx.clearRect(0, 0, RW, RH);
  const spine = RW * 0.60;
  const y = slToY(S.kt);

  // the excluded band, greyed
  rx.fillStyle = withAlpha(CSSV['chalk-faint'], 0.07);
  rx.fillRect(0, y, RW, RH - y);

  // how many events survive at each height: the shape of notability
  const maxN = EV.length;
  for (let py = RPAD; py < RH - RPAD; py += 2) {
    const n = survivorsAt(yToSl(py));
    const w = (n / maxN) * (RW * 0.52);
    rx.fillStyle = withAlpha(py <= y ? CSSV.amber : CSSV['chalk-faint'], py <= y ? 0.45 : 0.16);
    rx.fillRect(spine - w, py, w, 1.4);
  }

  rx.strokeStyle = withAlpha(CSSV.amber, 0.35); rx.lineWidth = 1;
  rx.beginPath(); rx.moveTo(spine + .5, RPAD); rx.lineTo(spine + .5, RH - RPAD); rx.stroke();

  rx.font = '400 9px xt-mono, monospace';
  for (const n of [1, 3, 10, 30, 100, 300]) {
    if (n > MAX_SL) continue;
    const py = slToY(n);
    rx.strokeStyle = withAlpha(CSSV['chalk-faint'], 0.45);
    rx.beginPath(); rx.moveTo(spine + .5, py); rx.lineTo(spine + 5, py); rx.stroke();
    rx.fillStyle = CSSV['chalk-faint'];
    rx.fillText(String(n), spine + 8, py + 3);
  }

  rx.strokeStyle = CSSV.amber; rx.lineWidth = 1.6;
  rx.beginPath(); rx.moveTo(2, y + .5); rx.lineTo(RW - 2, y + .5); rx.stroke();
  rx.beginPath(); rx.arc(spine + .5, y + .5, 4.5, 0, 7);
  rx.fillStyle = CSSV.amber; rx.fill();
  rx.strokeStyle = CSSV.panel; rx.lineWidth = 1.5; rx.stroke();
}
