# Human × Time

A globe of **7,056 dated, located human events** from Wikidata — 71,860 BCE to
2026 — with two axes at right angles. Along the bottom: when it happened. Up the
right-hand edge: **how much of the world remembers it.**

Sibling to [Earth × Time](https://kejjeh.github.io/earth-x-time/), which does the
same trick for deep time. That one asks *when did we come to believe this?* This
one asks *who remembers this?* — because that is the question this data can
actually answer.

## The second axis, and why it is not knowledge-time

Earth × Time earns its knowledge-time axis with hand-authored status timelines:
every claim carries a documented `proposed → contested → superseded` history with
citations, checked by an adversarial pass. That is expensive, which is why that
graph is 238 claims rather than 7,000.

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
tail: among battles with 2–12 editions, **11% have no English article**. The
Battle of Gubel survives only in Czech, German and Polish. So the ingest
deliberately reaches into the tail as well as the head; 241 events in the corpus
have no English article.

## Try these

| | |
|---|---|
| Drag the right-hand rail to the bottom | 1,321 events become 7,056. Europe fills in first and hardest. |
| Set the lens to **Missing from en.wikipedia** | What the anglophone record does not carry. |
| Watch the histogram | The record thickens toward the present — that is survivorship, not history. |
| Compare Europe with Central Asia at any coverage floor | The unevenness is the point. |

## Structure

One `queryEvents(axisState)` takes the time window, coverage floor, theme filter
and language lens together and returns what is visible; globe, timeline, rail and
panel all read its output. Screen-space clustering keeps 7,000 points from
becoming confetti — a cluster is labelled by its best-covered member, so the mark
stands for something real rather than a centroid nobody chose.

The globe is carried over intact from Earth × Time: canvas 2D, hand-written
orthographic projection, NASA Blue Marble inlined, no WebGL. Rendering paints
from input handlers rather than only from `requestAnimationFrame`, because rAF
does not fire in a document whose `visibilityState` is hidden.

## Building

```bash
python tools/fetch_events.py --per-cat 400 --tail 250   # Wikidata SPARQL, 17 categories
python tools/fetch_languages.py                         # per-edition coverage masks
python tools/build.py                                   # single self-contained file
```

## Toward "all of Wikipedia"

12,385,308 Wikidata items have coordinates. This corpus is 7,056 of them.

| Route | Reach | Limit |
|---|---|---|
| SPARQL, category by category (used here) | ~50–100k | hard 60 s query timeout |
| Toolforge / Quarry | metadata at scale | needs an account; not article text |
| Wikidata JSON dump, streamed | everything | ~130 GB compressed, hours per pass |

The timeout is the wall: counting items with coordinates returns instantly, but
adding a date join times out. Going much past this means the dump, which is a
batch job rather than a live query.

## Known gaps

- **Old World bias in the period ribbon.** "Classical", "Post-classical" and the
  rest are European conventions, and the ribbon says so rather than pretending to
  ICS-style ratified boundaries.
- **Wikidata's own biases are inherited wholesale**, and the coverage axis is
  there to make them visible rather than to correct them.
- **One date per event.** Where a founding date is genuinely disputed, this shows
  whichever Wikidata records. The sibling site is the one built for disputes.
