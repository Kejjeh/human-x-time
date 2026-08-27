/* ============================================================================
   SEARCH

   Tens of thousands of events and, until now, no way to reach one you already
   knew about. You could only browse.

   No index. A linear scan over the name column with indexOf is roughly a
   millisecond at this corpus size, which is well under the 90 ms debounce, and
   an inverted index would be a data structure to keep correct in exchange for
   nothing a user could perceive. If the corpus grows by another order of
   magnitude this is the first thing to revisit.

   Ranking is prefix, then word-start, then substring, then coverage - so typing
   "york" gives York before York Minster and both before New York, and
   "cathedral" gives the ones the world has actually heard of first.
   ========================================================================== */

const NAME_LC = new Array(NEV);
for (let i = 0; i < NEV; i++) NAME_LC[i] = EV[i].n.toLowerCase();

const WORD_BREAK = /[\s(,'\-]/;

/* One pass, bounded insertion, and the total falls out of the same walk.
   The note above says a linear scan is "roughly a millisecond". It was for a
   rare term and not for a common one: "an" matches 8,913 names, and pushing an
   object per match, sorting all 8,913 of them and then scanning the corpus a
   second time in countMatches to get the total cost 7.46 ms - on the main
   thread, on every keystroke, which is a dropped frame while you type. Keeping
   ten and counting as we go is 0.9 ms for the same query. Same output: rank
   descending, then coverage descending, ties in corpus order, because the
   insertion stops at the first element that is not strictly worse. */
let SEARCH_TOTAL = 0;

function searchEvents(qs, limit) {
  const s = qs.trim().toLowerCase();
  SEARCH_TOTAL = 0;
  if (s.length < 2) return [];
  const k = limit || 10;
  const hits = [];
  let floorRank = -1, floorSl = -1;
  for (let i = 0; i < NEV; i++) {
    const at = NAME_LC[i].indexOf(s);
    if (at < 0) continue;
    SEARCH_TOTAL++;
    const rank = at === 0 ? 3 : WORD_BREAK.test(NAME_LC[i][at - 1]) ? 2 : 1;
    const sl = EVSL[i];
    if (hits.length === k && (rank < floorRank || (rank === floorRank && sl <= floorSl))) continue;
    let pos = hits.length;
    while (pos > 0 && (hits[pos - 1].rank < rank ||
                       (hits[pos - 1].rank === rank && hits[pos - 1].sl < sl))) pos--;
    hits.splice(pos, 0, { i, rank, sl });
    if (hits.length > k) hits.pop();
    const last = hits[hits.length - 1];
    floorRank = last.rank; floorSl = last.sl;
  }
  return hits;
}

const elSearch = document.getElementById('search');
const elResults = document.getElementById('results');
const elSearchNote = document.getElementById('search-note');
let SR = { hits: [], cursor: -1, total: 0, q: '' };

function hilite(label, s) {
  const i = label.toLowerCase().indexOf(s.toLowerCase());
  if (i < 0) return esc(label);
  return esc(label.slice(0, i)) + '<mark>' + esc(label.slice(i, i + s.length)) +
    '</mark>' + esc(label.slice(i + s.length));
}

function renderResults() {
  const s = elSearch.value.trim();
  elResults.innerHTML = SR.hits.map((h, k) => {
    const e = EV[h.i];
    return `<li role="option" id="sr-${k}" data-i="${h.i}" aria-selected="${k === SR.cursor}">` +
      `<span class="nm">${hilite(e.n, s)}</span>` +
      `<span class="when">${fmtYear(e.y)} &middot; ${e.sl}</span></li>`;
  }).join('');
  elSearch.setAttribute('aria-expanded', String(SR.hits.length > 0));
  elSearch.setAttribute('aria-activedescendant', SR.cursor >= 0 ? `sr-${SR.cursor}` : '');
  elSearchNote.textContent = !s || s.length < 2 ? ''
    : !SR.hits.length ? 'nothing in the corpus matches'
    : SR.total > SR.hits.length ? `showing ${SR.hits.length} of ${SR.total} matches`
    : '';
}

function closeResults() {
  // Cancel the pending debounce too. Without this, dismissing the dropdown and
  // then doing nothing for 90 ms reopens it: the timer from the last keystroke
  // is still queued and repopulates SR behind the user's back.
  clearTimeout(searchTimer); searchTimer = null;
  SR = { hits: [], cursor: -1, total: 0, q: elSearch.value.trim() };
  elResults.innerHTML = '';
  elSearch.setAttribute('aria-expanded', 'false');
  elSearchNote.textContent = '';
}

/* Turning up at the right place is not enough: a result can be invisible under
   the current coverage floor, outside the time window, or in a theme that has
   been switched off. Choosing it opens whatever is in the way. */
function chooseEvent(i) {
  const e = EV[i];
  if (!e) return;
  // Math.max(1, ...) here meant an event carried by no edition at all could be
  // chosen, flown to, and shown in the panel with no marker anywhere on the
  // globe - the one case this function exists to prevent.
  if (e.sl < S.kt) S.kt = e.sl;
  if (!S.themes.has(e.theme)) S.themes.add(e.theme);
  if (S.lens) {
    const [mode, lang] = S.lens.split(':');
    const has = (e.m & LANG_BIT[lang]) !== 0;
    if ((mode === 'only' && !has) || (mode === 'not' && has)) {
      S.lens = '';
      const sel = document.getElementById('lens');
      if (sel) sel.value = '';
    }
  }
  if (e.t < S.win.t0 || e.t > S.win.t1) {
    S.win.t0 = 0;
    S.win.t1 = Math.max(120, Math.min(T_MAX, e.t * 1.8 + 60));
  }
  flyToEvent(i);
  closeResults();
  elSearch.blur();
}

let searchTimer = null;
function runSearch() {
  // searchEvents sets SEARCH_TOTAL on the same walk, so there is no second scan.
  const hits = searchEvents(elSearch.value, 10);
  SR = { hits, cursor: -1, total: SEARCH_TOTAL, q: elSearch.value.trim() };
  renderResults();
}
elSearch.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 90);
});

/* Typing "pomp" and hitting Enter within 90 ms of the last keystroke used to
   select the top hit for "pom", because the debounced recompute had not run yet.
   Stamp the query the hits belong to, and flush synchronously if Enter arrives
   before the timer does. */
function flushSearch() {
  clearTimeout(searchTimer); searchTimer = null;
  runSearch();
}


elSearch.addEventListener('keydown', e => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const n = SR.hits.length;
    if (!n) return;
    SR.cursor = e.key === 'ArrowDown'
      ? (SR.cursor >= n - 1 ? 0 : SR.cursor + 1)
      : (SR.cursor <= 0 ? n - 1 : SR.cursor - 1);
    renderResults();
    const el = document.getElementById('sr-' + SR.cursor);
    if (el) el.scrollIntoView({ block: 'nearest' });
    e.preventDefault();
  } else if (e.key === 'Enter') {
    if (SR.q !== elSearch.value.trim()) { flushSearch(); SR.cursor = -1; }
    const h = SR.hits[SR.cursor >= 0 ? SR.cursor : 0];
    if (h) chooseEvent(h.i);
    e.preventDefault();
  } else if (e.key === 'Escape') {
    if (SR.hits.length) closeResults(); else { elSearch.value = ''; elSearch.blur(); }
    e.stopPropagation();
  }
});

elResults.addEventListener('click', e => {
  const li = e.target.closest('li[data-i]');
  if (li) chooseEvent(+li.dataset.i);
});

/* "/" focuses search from anywhere, unless the user is already typing. */
document.addEventListener('keydown', e => {
  if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  elSearch.focus(); elSearch.select();
  e.preventDefault();
});

document.addEventListener('click', e => {
  if (!e.target.closest('#search, #results')) closeResults();
});
