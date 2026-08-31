/* ============================================================================
   PANELS
   ========================================================================== */
const elDetail = document.getElementById('detail');
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* Language codes and theme keys come from the corpus, which comes from
   Wikidata, and they used to go into innerHTML raw. In practice a sitelink
   dbname is [a-z0-9_] and no attack survives that - but every other
   interpolation in this file is escaped, the corpus is a third party's data,
   and a code of `x"><img src=x onerror=...>` put a live element into both the
   lens dropdown and the detail panel when it was tried. Nothing here is
   trusted markup. Event names, QIDs and palette values go the same way. */

/* The bar and the number above it were measuring different things.
   `e.sl` counts every Wikipedia edition - some 340 of them - while the bar and
   the codes below it are over LANGS, the 32 most-carried. So the Pyramid of
   Menkaure read "45 language editions" above a bar at 100%, and Paris read 289
   above a bar at 100%: six times the coverage, same picture, and nothing on
   screen said the bar had a different denominator. The bar is captioned now. */
function langList(e) {
  const have = [], missing = [];
  for (const l of LANGS) ((e.m & LANG_BIT[l]) ? have : missing).push(l);
  return { have, missing };
}

/* Bounded selection instead of a sort.
   Every list in this panel is a top-six of a set that reaches 38,242 rows at
   the coverage floor of 1 - and renderDetail runs once per state change, which
   during a rail drag or a time-axis drag means once per frame. Three full sorts
   of the visible set cost 17 ms there, on the frame path that the rest of this
   codebase went to some trouble to keep under 12. A k-of-n insertion is one
   pass with one comparison against the current floor in the common case, and k
   is six. Same output, no allocation beyond the k slots. */
function topK(items, k, better) {
  const out = [];
  for (let i = 0; i < items.length; i++) {
    const e = items[i];
    if (out.length === k && !better(e, out[k - 1])) continue;
    let pos = out.length;
    while (pos > 0 && better(e, out[pos - 1])) pos--;
    out.splice(pos, 0, e);
    if (out.length > k) out.pop();
  }
  return out;
}
const byCoverage = (a, b) => a.sl > b.sl;

/* The panel is rebuilt only when the panel changes.
 *
 * renderDetail reassigned elDetail.innerHTML unconditionally, from the needPanel
 * block, and needPanel is set by markAll() inside changed(), which setCoverage,
 * setWindow, setSelection and every theme and lens change all call. So every
 * pointermove of a rail drag destroyed and rebuilt the panel. Three things fell
 * out of that, and they are the reason this is not a micro-optimisation:
 *
 *   - It broke the site's own headline interaction. The README sells scrubbing
 *     the coverage floor with something selected - precisely the gesture that
 *     threw the reader back to the top of the panel on every step.
 *   - Focus died. The delegated click handler fires on a button whose subtree is
 *     then replaced, so activeElement dropped to <body> and the keyboard user
 *     lost their place on every hop.
 *   - #detail was the aria-live region. Announcing ten kilobytes of panel per
 *     pointer event is not an announcement, it is a denial of service.
 *
 * The comparison is against the rendered string itself rather than a signature
 * over the state that feeds it. A signature has to be kept in step by hand with
 * everything the template reads - the near list, the cluster members, the pinned
 * category, the coverage counts - and the failure mode when it drifts is a panel
 * that silently stops updating. The string cannot drift from itself. Building it
 * is a few bounded top-k passes; what this skips is the innerHTML parse, the
 * layout, the destroyed focus and the announcement. */
let lastDetailHTML = null;

function writeDetail(html) {
  if (html === lastDetailHTML) return false;
  lastDetailHTML = html;
  /* Put the reader back where they were. Restoring by data-q rather than by
     index: the list can be a different length after the rewrite, and landing on
     whatever is now fourth is worse than landing nowhere. */
  const act = document.activeElement;
  const keep = act && elDetail.contains(act) ? act.getAttribute('data-q') : null;
  const top = elDetail.scrollTop;
  elDetail.innerHTML = html;
  elDetail.scrollTop = top;
  if (keep) {
    const again = elDetail.querySelector(`[data-q="${CSS.escape(keep)}"]`);
    if (again) again.focus();
  }
  return true;
}

function renderDetail() {
  const F = q();
  if (!S.selection || !BY_Q[S.selection]) {
    const top = topK(F.events, 6, byCoverage);
    // Ranked, not sliced raw: the corpus arrives in year order now, so an
    // unsorted slice would quietly become "the five oldest" instead of "the
    // five best-covered that English has no article for".
    const thin = topK(F.events.filter(e => !(e.m & LANG_BIT.en)), 5, byCoverage);
    writeDetail(`
      <div class="empty">
        <strong>Nothing selected</strong>
        Click a marker. Clusters split as you zoom the globe.
        ${top.length ? `<p style="margin-top:14px"><strong>Most widely remembered here</strong></p>
          <ol>${top.map(e => `<li><button class="pick" data-q="${esc(e.q)}">${esc(e.n)}</button>
            <span class="num" style="color:var(--chalk-faint)"> ${fmtYear(e.y)} · ${e.sl} langs</span></li>`).join('')}</ol>` : ''}
        ${thin.length ? `<p style="margin-top:14px"><strong>In this window, but not on English Wikipedia</strong></p>
          <ol>${thin.map(e => `<li><button class="pick" data-q="${esc(e.q)}">${esc(e.n)}</button>
            <span class="num" style="color:var(--chalk-faint)"> ${fmtYear(e.y)} · ${e.sl} langs</span></li>`).join('')}</ol>` : ''}
      </div>`);
    return;
  }

  const e = BY_Q[S.selection];
  const { have, missing } = langList(e);
  const pct = Math.round(100 * have.length / LANGS.length);
  // nearest in time, within the same window
  const near = topK(F.events, 7, (a, b) => Math.abs(a.y - e.y) < Math.abs(b.y - e.y))
    .filter(x => x.q !== e.q).slice(0, 6);

  writeDetail(`
    <div class="dt-head">
      <button class="tag" type="button" data-cat="${esc(e.c)}"
        aria-pressed="${S.cat === e.c}"
        title="Show only ${esc(CAT_LABEL[e.c] || e.c)} across the whole corpus"
        style="color:${esc(CSSV[e.theme])};border-color:${esc(withAlpha(CSSV[e.theme], .45))}"
        >${esc(CAT_LABEL[e.c] || e.c)}</button>
      <h2>${esc(e.n)}</h2>
      <div class="when num">${fmtYear(e.y)}</div>
      <div class="where num">${e.lat.toFixed(3)}°, ${e.lng.toFixed(3)}°</div>
    </div>

    <div class="sect">
      <span class="lbl">Who remembers it</span>
      <div class="num" style="font-size:15px;color:var(--amber)">${e.sl === 0
        ? 'No Wikipedia article, in any edition'
        : `${e.sl} language edition${e.sl === 1 ? '' : 's'}`}</div>
      <div class="langbar"><i style="width:${pct}%"></i></div>
      <div class="barnote num">${have.length} of the ${LANGS.length} most-carried editions</div>
      <div class="langs">
        ${have.map(l => `<a href="https://www.wikidata.org/wiki/Special:GoToLinkedPage/${
          encodeURIComponent(l)}wiki/${encodeURIComponent(e.q)}"
          target="_blank" rel="noopener"
          title="Read this on ${esc(l)}.wikipedia">${esc(l)}</a>`).join('')}
        ${missing.slice(0, 12).map(l => `<span class="miss">${esc(l)}</span>`).join('')}
      </div>
      <p class="hint">Codes that carry an article are links; struck-through ones are
        major editions with no article on this.
        ${!(e.m & LANG_BIT.en) ? '<b style="color:var(--amber)">No English article.</b>' : ''}</p>
    </div>

    <div class="sect">
      <span class="lbl">Source</span>
      <p class="srcline">
        <a href="https://www.wikidata.org/wiki/${esc(e.q)}" target="_blank" rel="noopener">Wikidata ${esc(e.q)}</a>
        — date and coordinates as recorded there.
      </p>
      <p class="hint">This site cites the encyclopedia, not a primary source per row.
        For a battle or a cathedral that is a fair thing to cite; for a contested
        radiometric date it would not be, which is why the sibling site works differently.</p>
    </div>

    ${alsoHere(e)}

    ${near.length ? `<div class="sect nearby">
      <span class="lbl">Nearest in time</span>
      ${near.map(x => `<button class="pick" data-q="${esc(x.q)}">
        <span class="y num">${fmtYear(x.y)}</span>
        <span class="t">${esc(x.n)}</span></button>`).join('')}
    </div>` : ''}`);
}

/* One line, in its own live region, written only when it changes.
   This is what #detail used to be, minus the ten kilobytes and minus the flood:
   a rail drag moves this string only when the number in it actually moves. */
let lastSay = null;
function announce() {
  const F = q();
  const e = S.selection && BY_Q[S.selection];
  const say = e
    ? `${e.n}, ${fmtYear(e.y)}, ${e.sl === 0 ? 'no Wikipedia article'
        : `carried by ${e.sl} language edition${e.sl === 1 ? '' : 's'}`}.`
    : `${F.events.length.toLocaleString()} events shown${
        S.cat ? `, ${CAT_LABEL[S.cat] || S.cat} only` : ''}.`;
  if (say === lastSay) return;
  lastSay = say;
  const el = document.getElementById('say');
  if (el) el.textContent = say;
}

/* The tooltip has always said "+7 more here" over a cluster. This is the part
   that keeps the promise: the rest of the cell, named, in one click each.

   S.group is a snapshot taken at the moment of the click, in the projection that
   was on screen then - so it is dropped as soon as the globe moves (dropGroup in
   80_boot.js) rather than left to describe a view from three drags ago. The
   caption says "cluster cell" rather than "place" on purpose: these events are
   near each other ON SCREEN at this zoom, which is not the same claim as being
   near each other on the ground, and at low zoom the difference is hundreds of
   kilometres. */
function alsoHere(sel) {
  const g = S.group;
  if (!g || g.total < 2) return '';
  const rest = g.ids.map(i => EV[i]).filter(x => x && x.q !== sel.q);
  if (!rest.length) return '';
  const shown = rest.length + 1;                 // the selected one is in the cell too
  return `<div class="sect nearby">
      <span class="lbl">Also at this mark</span>
      <p class="hint" style="margin:-4px 0 8px">${g.total.toLocaleString()} events share this
        cluster cell${g.total > shown ? `; the ${shown} most widely remembered are listed` : ''}.
        Zoom the globe to split it.</p>
      ${rest.map(x => `<button class="pick" data-q="${esc(x.q)}" data-here="1">
        <span class="y num">${fmtYear(x.y)}</span>
        <span class="t">${esc(x.n)}</span>
        <span class="c num">${x.sl}</span></button>`).join('')}
    </div>`;
}

/* The pinned category, as one dismissible chip.
   62 Wikidata classes ship in the corpus, are collapsed to 6 themes for colour,
   and were surfaced per event as an inert caption. "Show me the other
   cathedrals" was unaskable of 1,205 of them.

   Only the pinned one is rendered. A roster of 62 rows above `.detail`, which is
   `flex:1 1 auto`, squeezes the panel that actually answers the question down to
   nothing - so the way in is the event you are already looking at, and this is
   the way back out. */
function renderCatPin() {
  const el = document.getElementById('catpin');
  if (!el) return;
  if (!S.cat) { el.innerHTML = ''; return; }
  const n = q().catCounts[CAT_IX[S.cat]] || 0;
  el.innerHTML = `<button type="button" id="btn-unpin"
      aria-label="Stop showing only ${esc(CAT_LABEL[S.cat] || S.cat)}">
      <span>${esc(CAT_LABEL[S.cat] || S.cat)}</span>
      <span class="n">${n.toLocaleString()}</span>
      <span class="x" aria-hidden="true">&times;</span></button>`;
}

function renderThemes() {
  const F = q();
  document.getElementById('themes').innerHTML = THEMES.map(t => `
    <button class="theme" data-theme="${esc(t)}" data-on="${S.themes.has(t)}"
            aria-pressed="${S.themes.has(t)}">
      <span class="sw" style="--c:${esc(CSSV[t])}"></span>
      <span>${esc(THEME_LABEL[t] || t)}</span>
      <span class="n">${F.themeCounts[t] || 0}</span>
    </button>`).join('');
}

function renderLens() {
  const sel = document.getElementById('lens');
  if (sel.dataset.built) return;
  sel.dataset.built = '1';
  const opts = ['<option value="">Every edition</option>'];
  for (const l of LANGS.slice(0, 16))
    opts.push(`<option value="not:${esc(l)}">Missing from ${esc(l)}.wikipedia</option>`);
  for (const l of LANGS.slice(0, 16))
    opts.push(`<option value="only:${esc(l)}">Present in ${esc(l)}.wikipedia</option>`);
  sel.innerHTML = opts.join('');
}
