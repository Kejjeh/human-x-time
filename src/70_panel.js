/* ============================================================================
   PANELS
   ========================================================================== */
const elDetail = document.getElementById('detail');
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function langList(e) {
  const have = [], missing = [];
  for (const l of LANGS) ((e.m & LANG_BIT[l]) ? have : missing).push(l);
  return { have, missing };
}

function renderDetail() {
  const F = q();
  if (!S.selection || !BY_Q[S.selection]) {
    const top = F.events.slice().sort((a, b) => b.sl - a.sl).slice(0, 6);
    // Sorted, not sliced raw: the corpus arrives in year order now, so an
    // unsorted slice would quietly become "the five oldest" instead of "the
    // five best-covered that English has no article for".
    const thin = F.events.filter(e => !(e.m & LANG_BIT.en))
      .sort((a, b) => b.sl - a.sl).slice(0, 5);
    elDetail.innerHTML = `
      <div class="empty">
        <strong>Nothing selected</strong>
        Click a marker. Clusters split as you zoom the globe.
        ${top.length ? `<p style="margin-top:14px"><strong>Most widely remembered here</strong></p>
          <ol>${top.map(e => `<li><button class="pick" data-q="${e.q}">${esc(e.n)}</button>
            <span class="num" style="color:var(--chalk-faint)"> ${fmtYear(e.y)} · ${e.sl} langs</span></li>`).join('')}</ol>` : ''}
        ${thin.length ? `<p style="margin-top:14px"><strong>In this window, but not on English Wikipedia</strong></p>
          <ol>${thin.map(e => `<li><button class="pick" data-q="${e.q}">${esc(e.n)}</button>
            <span class="num" style="color:var(--chalk-faint)"> ${fmtYear(e.y)} · ${e.sl} langs</span></li>`).join('')}</ol>` : ''}
      </div>`;
    return;
  }

  const e = BY_Q[S.selection];
  const { have, missing } = langList(e);
  const pct = Math.round(100 * have.length / LANGS.length);
  // nearest in time, within the same window
  const near = F.events
    .filter(x => x.q !== e.q)
    .sort((a, b) => Math.abs(a.y - e.y) - Math.abs(b.y - e.y))
    .slice(0, 6);

  elDetail.innerHTML = `
    <div class="dt-head">
      <span class="tag" style="color:${CSSV[e.theme]};border-color:${withAlpha(CSSV[e.theme], .45)}">
        ${esc(CAT_LABEL[e.c] || e.c)}</span>
      <h2>${esc(e.n)}</h2>
      <div class="when num">${fmtYear(e.y)}</div>
      <div class="where num">${e.lat.toFixed(3)}°, ${e.lng.toFixed(3)}°</div>
    </div>

    <div class="sect">
      <span class="lbl">Who remembers it</span>
      <div class="num" style="font-size:15px;color:var(--amber)">${e.sl} language editions</div>
      <div class="langbar"><i style="width:${pct}%"></i></div>
      <div class="langs">
        ${have.map(l => `<span>${l}</span>`).join('')}
        ${missing.slice(0, 12).map(l => `<span class="miss">${l}</span>`).join('')}
      </div>
      <p class="hint">Struck-through codes are major editions with no article on this.
        ${!(e.m & LANG_BIT.en) ? '<b style="color:var(--amber)">No English article.</b>' : ''}</p>
    </div>

    <div class="sect">
      <span class="lbl">Source</span>
      <p class="srcline">
        <a href="https://www.wikidata.org/wiki/${e.q}" target="_blank" rel="noopener">Wikidata ${e.q}</a>
        — date and coordinates as recorded there.
      </p>
      <p class="hint">This site cites the encyclopedia, not a primary source per row.
        For a battle or a cathedral that is a fair thing to cite; for a contested
        radiometric date it would not be, which is why the sibling site works differently.</p>
    </div>

    ${near.length ? `<div class="sect nearby">
      <span class="lbl">Nearest in time</span>
      ${near.map(x => `<button class="pick" data-q="${x.q}">
        <span class="y num">${fmtYear(x.y)}</span>
        <span class="t">${esc(x.n)}</span></button>`).join('')}
    </div>` : ''}`;
}

function renderThemes() {
  const F = q();
  document.getElementById('themes').innerHTML = THEMES.map(t => `
    <button class="theme" data-theme="${t}" data-on="${S.themes.has(t)}"
            aria-pressed="${S.themes.has(t)}">
      <span class="sw" style="--c:${CSSV[t]}"></span>
      <span>${THEME_LABEL[t]}</span>
      <span class="n">${F.themeCounts[t] || 0}</span>
    </button>`).join('');
}

function renderLens() {
  const sel = document.getElementById('lens');
  if (sel.dataset.built) return;
  sel.dataset.built = '1';
  const opts = ['<option value="">Every edition</option>'];
  for (const l of LANGS.slice(0, 16))
    opts.push(`<option value="not:${l}">Missing from ${l}.wikipedia</option>`);
  for (const l of LANGS.slice(0, 16))
    opts.push(`<option value="only:${l}">Present in ${l}.wikipedia</option>`);
  sel.innerHTML = opts.join('');
}
