/* ============================================================================
   THE GUIDED PATH

   `grep -c tour` returned 0 across this repo's head, body and boot. The sibling
   site has one, and it flies between named points - which is exactly the wrong
   shape here. No single one of 38,242 events is the argument; the argument is
   what the SET does when you move an axis. So every step of this moves a
   control and says what the numbers did, and the numbers are read out of the
   live query rather than written down - the corpus is regenerated from Wikidata
   and any figure hard-coded here would be quietly wrong by the next run.

   The script is not invented. It is the README's own "Try these" table.

   Two mechanism notes, both of them things that bite:

     - flyToEvent takes an EV index and unconditionally calls setSelection, so
       the rotation-only step sets its own tween instead. A guided path that
       silently selects something is telling you about one event when the step
       is about a continent.
     - Setting S.lens and calling changed() does not move the <select>.
       renderLens returns early forever once dataset.built is set, so the option
       list is never rebuilt and the control keeps showing "Every edition" while
       the globe is filtered. syncControls is what writes the value.
   ========================================================================== */

const elTour = document.getElementById('tour');
const elTourText = document.getElementById('tour-text');
const elTourN = document.getElementById('tour-n');

/* Counts for a state, without disturbing the one on screen. queryEvents reads
   its axes off whatever object it is handed, so this hands it a shallow copy -
   and takes the number out before anything can invalidate it. */
function countUnder(patch) {
  const A = { win: { ...S.win }, kt: S.kt, themes: S.themes, lens: S.lens,
              cat: S.cat, ...patch };
  return queryEvents(A).n;
}

/* Each step: a title, the prose, and the move it makes. `go` runs on arrival,
   forwards or back, so a step is a place rather than a transition. */
const TOUR = [
  {
    text: () => `This is one query with two axes. Along the bottom, <b>when</b> —
      ${fmtYbpLabel(S.win.t1)} to ${fmtYbpLabel(S.win.t0)} right now. Up the
      right-hand edge, <b>how many Wikipedia language editions</b> carry an
      article about it. Everything on screen is those two dials and nothing else.`,
    go: () => {
      S.lens = ''; S.cat = ''; S.themes = new Set(THEMES);
      setSelection(null);
      S.win.t0 = 0; S.win.t1 = 3200;
      setCoverage(40);
      syncControls();
    }
  },
  {
    text: () => `The floor was at 40 editions and <b>${TOURN.at40.toLocaleString()}</b>
      events cleared it. At a floor of 1 there are <b>${TOURN.at1.toLocaleString()}</b>.
      Most of the record is not famous; it was simply below the line.`,
    go: () => setCoverage(1)
  },
  {
    text: () => `Now only the events with <b>no English article</b>:
      <b>${TOURN.noEn.toLocaleString()}</b> of them, out of
      ${TOURN.at1.toLocaleString()}. Absence is a fact about the record, not
      about history — and it is not scattered evenly across the map.`,
    go: () => {
      setCoverage(1);
      S.lens = 'not:en';
      syncControls();          // renderLens will not rebuild the list; see the header
      changed();
    }
  },
  {
    text: () => `Every edition again, and the window opened to all
      <b>75,000</b> years. Watch the histogram along the bottom: it is almost
      flat until the last few centuries and then goes vertical. That is the
      record thickening, not the past.`,
    go: () => {
      S.lens = ''; syncControls();
      setCoverage(1);
      setWindow(0, T_MAX);
    }
  },
  {
    text: () => `Same floor, same window, turned to <b>Central Asia</b>. The
      globe is not evenly covered and the axis is what shows it: the same query
      that fills western Europe leaves whole regions nearly bare.`,
    go: () => {
      setCoverage(1);
      spinTo(-65, 40);
    }
  }
];

/* Numbers the prose quotes, computed once when the tour opens so a step does
   not re-run three queries every time it is read. */
const TOURN = { at40: 0, at1: 0, noEn: 0 };

/* Rotation without a selection. flyToEvent would pick an event and open the
   panel on it, which is a different claim from "look at this region". */
function spinTo(lam, phi) {
  let l = lam;
  while (l - S.rot.lam > 180) l -= 360;
  while (l - S.rot.lam < -180) l += 360;
  S.spin.lam = S.spin.phi = 0;
  TW = { t: 0, dur: RM.matches ? 0.01 : 1.1,
         from: { lam: S.rot.lam, phi: S.rot.phi },
         to: { lam: l, phi } };
  needGlobe = true; paintOnInput();
}

let tourAt = -1;

function tourGo(i) {
  if (i < 0 || i >= TOUR.length) return tourEnd();
  tourAt = i;
  TOUR[i].go();
  elTourText.innerHTML = TOUR[i].text();
  elTourN.textContent = `${i + 1} / ${TOUR.length}`;
  document.getElementById('tour-prev').disabled = i === 0;
  document.getElementById('tour-next').textContent = i === TOUR.length - 1 ? 'Done' : 'Next';
}

function tourStart() {
  TOURN.at40 = countUnder({ win: { t0: 0, t1: 3200 }, kt: 40, lens: '', cat: '',
                            themes: new Set(THEMES) });
  TOURN.at1 = countUnder({ win: { t0: 0, t1: 3200 }, kt: 1, lens: '', cat: '',
                           themes: new Set(THEMES) });
  TOURN.noEn = countUnder({ win: { t0: 0, t1: 3200 }, kt: 1, lens: 'not:en', cat: '',
                            themes: new Set(THEMES) });
  elTour.hidden = false;
  tourGo(0);
  document.getElementById('tour-next').focus();
}

/* Closing leaves the view where the tour left it rather than restoring the
   default. The last step is a real view worth being in, and snapping away from
   it would undo the one thing the path was for. */
function tourEnd() {
  tourAt = -1;
  elTour.hidden = true;
  document.getElementById('btn-tour').focus();
}

document.getElementById('btn-tour').addEventListener('click',
  () => (elTour.hidden ? tourStart() : tourEnd()));
document.getElementById('tour-next').addEventListener('click', () => tourGo(tourAt + 1));
document.getElementById('tour-prev').addEventListener('click', () => tourGo(tourAt - 1));
document.getElementById('tour-end').addEventListener('click', tourEnd);
elTour.addEventListener('keydown', e => { if (e.key === 'Escape') tourEnd(); });
