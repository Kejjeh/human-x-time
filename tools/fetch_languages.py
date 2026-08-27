"""
Add per-language Wikipedia coverage to each event.

    python tools/fetch_languages.py

The second axis of this site is "who remembers this?", so it needs to know not
just how many language editions carry an article but WHICH. That is what makes
"covered by Chinese Wikipedia but not English" a query rather than a wish.

SPARQL times out aggregating sitelinks, so this uses wbgetentities, 50 items a
call, asking only for the sitelinks property.

Storage: a 32-bit mask over the 32 most common editions in this corpus, plus the
uncorrected total. 4 bytes an event instead of a list of strings.

Rewrites src/events.json in place, adding `m` (mask) and `L` (top language list).
"""
import urllib.request, urllib.parse, json, os, time, collections, threading
import concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATH = os.path.join(ROOT, "src", "events.json")
UA = {"User-Agent": "HumanTime/0.1 (https://github.com/kejjeh; mailto:joshp1001@gmail.com)"}
API = "https://www.wikidata.org/w/api.php"

EDITIONS = set()          # filled by main() from the sitematrix API

# Which sitelinks are Wikipedia LANGUAGE EDITIONS.
#
# The old test was `k.endswith("wiki")` minus a hand-written deny-list, and it
# let `abstractwiki` through - Abstract Wikipedia, a Wikimedia project, not an
# edition anybody reads an article in. It is served from abstract.wikipedia.org,
# so a host test does not catch it either, and it sits on most high-profile
# items: seven of ten cities sampled carried it, which is the top of the very
# rail this number drives. Every deny-list is one project launch out of date.
#
# So ask. action=sitematrix is the canonical list of editions, one call, and it
# answers no for abstractwiki, commonswiki, testwiki and nostalgiawiki while
# answering yes for every real edition including zh_min_nanwiki and be_x_oldwiki.
SITEMATRIX = (API + "?action=sitematrix&format=json&formatversion=2"
                    "&smtype=language&smlangprop=code|site")


def wikipedia_editions():
    """The dbnames of every open Wikipedia language edition, from the API."""
    with urllib.request.urlopen(
            urllib.request.Request(SITEMATRIX, headers=UA), timeout=60) as r:
        matrix = json.load(r)["sitematrix"]
    out = set()
    for key, group in matrix.items():
        if key in ("count", "specials"):
            continue
        for site in group.get("site", []):
            if site.get("code") == "wiki" and not site.get("closed") and not site.get("private"):
                out.add(site["dbname"])
    if len(out) < 100:                       # a truncated answer must not silently
        raise SystemExit(                    # redefine the corpus as uncovered
            f"sitematrix returned only {len(out)} editions; refusing to rebuild the masks")
    return out


def batch(qids):
    params = {"action": "wbgetentities", "ids": "|".join(qids),
              "props": "sitelinks", "format": "json", "formatversion": "2"}
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r).get("entities", {})
        except Exception:                             # noqa: BLE001
            time.sleep(2 * (i + 1))
    return {}


def main():
    doc = json.load(open(PATH, encoding="utf-8"))
    events = doc["events"]
    global EDITIONS
    EDITIONS = wikipedia_editions()
    print(f"{len(EDITIONS)} open Wikipedia language editions")
    qids = [e["q"] for e in events]
    print(f"{len(qids):,} events; {(len(qids) + 49) // 50} batches of 50")

    # Serial, this is six minutes at thirty thousand events. Four workers is
    # polite to the API and turns it into ninety seconds.
    langs_for = {}
    lock = threading.Lock()
    chunks = [qids[i:i + 50] for i in range(0, len(qids), 50)]
    t0 = time.time()
    done = [0]

    def work(chunk):
        ents = batch(chunk)
        got = {}
        for qid, ent in ents.items():
            sl = ent.get("sitelinks") or {}
            got[qid] = sorted(k[:-4] for k in sl if k in EDITIONS)
        with lock:
            langs_for.update(got)
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(chunks):
                print(f"  {done[0] * 50:>6}/{len(qids)}  {time.time() - t0:.0f}s", flush=True)

    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, chunks))

    # The 32 editions that appear most often here. A fixed vocabulary, so the
    # mask means the same thing in every event and the client needs no lookup.
    freq = collections.Counter(l for ls in langs_for.values() for l in ls)
    top = [l for l, _ in freq.most_common(32)]
    idx = {l: i for i, l in enumerate(top)}
    print(f"\ntop 32 editions: {','.join(top)}")

    missing = 0
    for e in events:
        ls = langs_for.get(e["q"])
        if ls is None:
            # The API never answered for this one. Zeroing the mask while
            # leaving the old `sl` in place makes the page state a
            # contradiction - "remembered in 40 editions", every one of the 32
            # codes struck through, "No English article" - so keep whatever a
            # previous good run recorded and let the count below report it.
            missing += 1
            e.setdefault("m", 0)
            continue
        mask = 0
        for l in ls:
            if l in idx:
                mask |= (1 << idx[l])
        e["m"] = mask
        e["sl"] = len(ls)                # authoritative count from the sitelinks themselves

    doc["langs"] = top
    json.dump(doc, open(PATH, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

    cov = collections.Counter()
    for e in events:
        for l in top:
            if e["m"] & (1 << idx[l]):
                cov[l] += 1
    print(f"\nrewrote {PATH}  ({os.path.getsize(PATH):,} bytes)   unresolved: {missing}")
    if missing:
        print(f"  WARNING: {missing:,} events kept their previous coverage; "
              f"re-run to resolve them.")
    print("coverage by edition (of %d events):" % len(events))
    for l, n in cov.most_common(12):
        print(f"  {l:6} {n:>5}  {100*n//len(events):>3}%  {'#' * (n * 40 // len(events))}")
    # the whole point of the axis: how uneven is the record?
    # No idx.get("en", 0) default here: if English somehow missed the top 32,
    # bit 0 is some other edition and the headline number would be a quiet lie.
    if "en" in idx:
        en = sum(1 for e in events if e["m"] & (1 << idx["en"]))
        print(f"\nevents NOT on English Wikipedia: {len(events) - en:,}")
    else:
        print("\nEnglish is not in the top 32 editions of this corpus (unexpected)")


if __name__ == "__main__":
    main()
