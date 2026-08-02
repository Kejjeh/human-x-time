/* ============================================================================
   EVENTS ON THE GLOBE
   ========================================================================== */

function markerRadius(n, sl) {
  if (n > 1) return Math.min(15, 4 + Math.log2(n) * 2.4);
  return 2.4 + Math.min(6, Math.log2(1 + sl) * 0.95);
}

function drawEvents() {
  const F = q();
  const pts = [];
  const m0 = M[0], m1 = M[1], m2 = M[2], m3 = M[3], m4 = M[4],
        m5 = M[5], m6 = M[6], m7 = M[7], m8 = M[8];

  for (const e of F.events) {
    const d = m0 * e.x + m1 * e.yv + m2 * e.z;
    if (d <= 0.015) continue;                        // behind the limb
    pts.push({
      e, d,
      sx: GCX + GR * (m3 * e.x + m4 * e.yv + m5 * e.z),
      sy: GCY - GR * (m6 * e.x + m7 * e.yv + m8 * e.z)
    });
  }

  const groups = S.cluster ? clusterScreen(pts, Math.max(15, GR * 0.055)) : pts.map(p => ({ ...p, n: 1 }));
  groups.sort((a, b) => a.d - b.d);

  gx.save();
  for (const g of groups) {
    const col = CSSV[g.e.theme] || CSSV.chalk;
    const r = markerRadius(g.n, g.e.sl);
    const sel = S.selection === g.e.q;

    // dark contact ring: a theme colour can otherwise land on sunlit desert
    // at its own value and vanish
    gx.beginPath(); gx.arc(g.sx, g.sy, r + 1.5, 0, 7);
    gx.fillStyle = 'rgba(4,8,14,0.5)'; gx.fill();

    gx.beginPath(); gx.arc(g.sx, g.sy, r, 0, 7);
    if (g.n > 1) {
      gx.fillStyle = withAlpha(g.mixed ? CSSV['chalk-dim'] : col, 0.7);
      gx.fill();
      gx.strokeStyle = withAlpha(g.mixed ? CSSV.chalk : col, 0.9);
      gx.lineWidth = 1.1; gx.stroke();
    } else {
      gx.fillStyle = col; gx.fill();
    }

    if (sel) {
      gx.beginPath(); gx.arc(g.sx, g.sy, r + 5, 0, 7);
      gx.strokeStyle = CSSV.chalk; gx.lineWidth = 1.3; gx.stroke();
    }

    HIT.push({ id: g.e.q, x: g.sx, y: g.sy, r: r + 6, n: g.n });
  }

  // counts inside the bigger clusters
  gx.font = `600 9px xt-mono, monospace`;
  gx.textAlign = 'center'; gx.textBaseline = 'middle';
  for (const g of groups) {
    if (g.n < 4) continue;
    const r = markerRadius(g.n, g.e.sl);
    if (r < 8) continue;
    gx.fillStyle = 'rgba(6,10,16,0.85)';
    gx.fillText(String(g.n), g.sx, g.sy + 0.5);
  }
  gx.textAlign = 'start'; gx.textBaseline = 'alphabetic';

  // labels: only the singles, only the well-covered, only where they fit
  const boxes = [];
  const labelled = groups
    .filter(g => g.n === 1 || g.e.sl > 80)
    .sort((a, b) => (b.e.q === S.selection ? 1e9 : b.e.sl) - (a.e.q === S.selection ? 1e9 : a.e.sl))
    .slice(0, 34);
  gx.font = `400 11px xt-cond, sans-serif`;
  for (const g of labelled) {
    const strong = g.e.q === S.selection || g.e.q === S.hover;
    if (!strong && g.e.sl < 90) continue;
    const t = g.e.n;
    const w = gx.measureText(t).width;
    const r = markerRadius(g.n, g.e.sl);
    let placed = false;
    for (const [bx, by] of [[g.sx + r + 5, g.sy + 4], [g.sx - w - r - 5, g.sy + 4],
                            [g.sx - w / 2, g.sy - r - 6], [g.sx - w / 2, g.sy + r + 13]]) {
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
      gx.fillStyle = strong ? '#F4F0E8' : withAlpha(CSSV[g.e.theme] || CSSV.chalk, 0.95);
      gx.font = `${strong ? 600 : 400} 11px xt-cond, sans-serif`;
      gx.fillText(t, bx, by);
      placed = true;
      break;
    }
    if (!placed) continue;
  }
  gx.restore();
}
