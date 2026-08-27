# Human × Time

A globe of **38,242 dated, located human events** from Wikidata — 71,860 BCE to
2026 — with two axes at right angles. Along the bottom: when it happened. Up the
right-hand edge: **how much of the world remembers it.**

Every view has a URL: the window, the coverage floor, the rotation, the themes,
the language lens and the selection all live in `location.hash`. There is a
search box over all 38,242 names, and choosing a result opens whatever filter is
hiding it before flying there.

Sibling to [Earth × Time](https://kejjeh.github.io/earth-x-time/), which does the
same trick for deep time. That one asks *when did we come to believe this?* This
one asks *who remembers this?* — because that is the question this data can
actually answer.

## The second axis, and why it is not knowledge-time

Earth × Time earns its knowledge-time axis with hand-authored status timelines:
every claim carries a documented `proposed → contested → superseded` history with
citations, checked by an adversarial pass. That is expensive, which is why that
graph is 275 claims rather than 38,000.

Wikidata gives one date per event and no belief history. Two things were measured
before deciding:

- only **16%** of Wikidata date statements resolve to a citation at all
- citation counts do **not** encode consensus — Alvarez 1980 is cited 80 times in
  1989 and 54 in 1991, *dipping* across the very confirmation that settled the
  argument

So a knowledge-time rail here would be a slider wired to nothing. Nobody disputes
that Waterloo was 1815.

What the data does support is **coverage**: how many Wikipedia language editions
carry an article, and which ones. The rail scrubs a coverage floor; the lens
filters by edition. Absence is a fact about the record, not about history.

**One caveat that shaped the corpus.** Ranking by notability selects for things
every edition covers — in the notability-ranked head, 99.5% of events have an
English article, which flattens the axis to nothing. The asymmetry lives in the
tail. So the ingest asks each sitelink band for its own quota rather than ranking
a whole class by notability — which also dodges the 60-second query timeout, since
no single query is large enough to hit it. **7,387 events in the corpus have no
English article**, against 241 in the first cut.

## Try these

| | |
|---|---|
| Drag the right-hand rail past the bottom | 2,183 events become 38,242 — all of them, including four no Wikipedia edition anywhere carries. Europe fills in first and hardest. |
| Set the lens to **Missing from en.wikipedia** | 7,387 events the anglophone record does not carry. |
| Watch the histogram | The record thickens toward the present — that is survivorship, not history. |
| Compare Europe with Central Asia at any coverage floor | The unevenness is the point. |

## Structure

One `queryEvents(axisState)` takes the time window, coverage floor, theme filter
and language lens together and returns what is visible; globe, timeline, rail and
panel all read its output. Screen-space clustering keeps 38,000 points from
becoming confetti — a cluster is labelled by its best-covered member, so the mark
stands for something real rather than a centroid nobody chose.

The corpus ships columnar: delta-coded zigzag varints in the coastline alphabet,
43 bytes an event against 119 as JSON objects. `src/events.json` stays readable
and reviewable in the diff; only the browser gets the packed form, and the build
refuses to ship a payload that does not round-trip.

The per-frame path is parallel typed arrays and allocates nothing. That matters
in exactly one place, and it is a place a user reaches in two clicks: coverage
floor at 1, window at maximum, clustering off, every event on screen at once.
Batching the canvas paths and replacing a 38,000-element sort with a bounded
34-slot insertion took that frame from **62 ms to 12 ms**. The batching is by
depth slab first and colour second, because batching by colour alone puts one
theme systematically on top of every overlap and tints the density map.

`tools/smoke_test.py` loads the built page in headless Chromium and asks it, from
outside, whether it works — 65 checks, run against both built documents and wired into the build as a gate. The sibling
site lost a whole build to a boot failure nothing detected, and this one had no
`safeBoot` at all until now.

`tools/check_no_local_paths.py` refuses any commit whose staged content carries
an absolute path out of somebody's home directory — `C:\Users\…`, `/Users/…`,
`/home/…`. It exists because one nearly shipped in
`docs/ux-review-2026-08-03.md`, written by an agent that had been handed
absolute paths in its brief; it was caught by hand, which is not a control.
Obvious placeholders (`/home/you/…`) still pass, in any case. The hook is
versioned in `.githooks/` so it is reviewable in the diff; a fresh clone arms it
once with `git config core.hooksPath .githooks` — and because that is a step a
fresh clone can forget, `tools/build.py` runs the same check over every tracked
file before it writes anything. The patterns have a test of their own
(`--self-test`, sixteen cases, also run by the build), because a gate nobody
tests is a gate nobody knows the shape of: matching used to be case-sensitive,
so three of those sixteen — a lowercased Windows path, an uppercased one, a
lowercased macOS one — walked straight through, along with anything reached
through a WSL or git-bash drive mount.

The globe is carried over intact from Earth × Time: canvas 2D, hand-written
orthographic projection, NASA Blue Marble inlined, no WebGL. Rendering paints
from input handlers rather than only from `requestAnimationFrame`, because rAF
does not fire in a document whose `visibilityState` is hidden.

## Building

```bash
python tools/fetch_events.py --per-cat 1800    # 62 categories, banded by sitelink count
python tools/fetch_languages.py                # per-edition coverage masks, threaded
python tools/build.py                          # packs, builds, and smoke-tests
```

The three inlined assets change far less often and have their own fetchers, each
writing the file `build.py` reads:

```bash
python tools/fetch_coast.py                    # -> assets/coast.txt
python tools/fetch_fonts.py                    # -> assets/fonts.css
python tools/fetch_texture.py                  # -> assets/earth.txt
```

Two of those used to write `tools/coast_out.txt` and `tools/fonts_out.css`, which
nothing reads — you could regenerate an asset, run the build, and get the old one
back with no error anywhere. They also wrote a plausible-looking partial file when
a fetch failed; an empty land payload decodes to zero rings, so chart mode loses
every coastline and the page still looks like it works. Both now refuse to write
at all rather than write half a result.

Class QIDs are **resolved by name**, never typed in by hand — that is how this
project once reported Chicxulub as Q13415, which is a star in Canis Major. Each
class is looked up, checked against its own label, and required to have instances
*with coordinates*; the resolution is cached in `tools/classes.json` so it is
reviewable in the diff. Four of 66 classes were dropped by that guard, including
`theatre`, which resolves to the art form rather than the building.

## Toward "all of Wikipedia"

12,385,308 Wikidata items have coordinates. This corpus is 38,242 of them.

| Route | Reach | Limit |
|---|---|---|
| SPARQL, banded by sitelink count (used here) | ~50–100k | hard 60 s query timeout |
| Toolforge / Quarry | metadata at scale | needs an account; not article text |
| Wikidata JSON dump, streamed | everything | ~130 GB compressed, hours per pass |

The timeout is the wall, and it is not theoretical: twelve of 558 band queries
came back 502, 504 or 429 on the big classes — villages, churches, schools — and a
slower two-thread backfill recovered 699 of them and still could not finish
`school`. Going much past this means the dump, which is a batch job rather than a
live query.

## Known gaps

- **Old World bias in the period ribbon.** "Classical", "Post-classical" and the
  rest are European conventions, and the ribbon says so rather than pretending to
  ICS-style ratified boundaries.
- **Wikidata's own biases are inherited wholesale**, and the coverage axis is
  there to make them visible rather than to correct them.
- **One date per event.** Where a founding date is genuinely disputed, this shows
  whichever Wikidata records. The sibling site is the one built for disputes.
- **A UX review found twelve more.** The worst of them is fixed: a tap on a marker
  used to show nothing at all, because the tooltip is driven by hover and a finger
  never produces one. A tap now answers with the tooltip. The detail panel is still
  the third grid row on a narrow layout — measured at y=1011 in an 855px viewport —
  and still does not scroll itself into view when the selection changes. The rest
  are unimplemented. See
  [`docs/ux-review-2026-08-03.md`](docs/ux-review-2026-08-03.md), which covers this
  site and its sibling together.
