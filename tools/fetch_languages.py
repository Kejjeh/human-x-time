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


def get(url, tries=6):
    """One API call, retried with backoff.

    Wikidata answers 429 freely to a shared egress address, and this crawl is
    765 calls: without a retry the failures are not rare, they are routine. A
    429 is slept on for longer than a connection error, because it is the API
    asking for exactly that.

    Measured on the run this was written for: 148 of 765 batches gave up under
    the old four-try schedule, leaving 7,400 events - 19% of the corpus -
    unresolved."""
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:                  # noqa: PERF203
            last = err
            wait = 0
            if err.code == 429:
                try:
                    wait = int(err.headers.get("Retry-After") or 0)
                except ValueError:
                    wait = 0
                wait = max(wait, 5 * (i + 1))
            else:
                wait = 2 * (i + 1)
            if i < tries - 1:
                time.sleep(wait)
        except Exception as err:                               # noqa: BLE001
            last = err
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    raise RuntimeError(f"{tries} tries failed: {last}")


def wikipedia_editions():
    """The dbnames of every open Wikipedia language edition, from the API.

    Retried like everything else. This was the one call that was not, so a
    single 429 on the very first request killed the whole crawl before it read
    one event - measured, with the identical URL answering 200 a second later."""
    try:
        matrix = get(SITEMATRIX)["sitematrix"]
    except RuntimeError as err:
        raise SystemExit(f"sitematrix unreachable: {err}")
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
    try:
        return get(url).get("entities", {})
    except RuntimeError:
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

    # A second, patient pass over whatever the API never answered for.
    #
    # This used to be left alone: unresolved events kept their previous `sl` and
    # `m` and the run printed a warning. That is not a safe fallback, and the
    # reason is two lines further down - `doc["langs"]` is rewritten in the same
    # write. The mask is a set of BIT POSITIONS into that vocabulary, so the
    # moment the top-32 ordering shifts by one place, every kept mask starts
    # meaning a different set of languages. A partially-refreshed corpus is not
    # a slightly stale corpus; it is a corpus that is confidently wrong about
    # which editions carry 19% of its rows.
    #
    # So: retry the stragglers serially, in smaller batches, until they are all
    # answered or the rounds run out. Serial on purpose - four workers is what
    # earned the 429s in the first place.
    for rnd in range(1, 6):
        missing = [qid for qid in qids if qid not in langs_for]
        if not missing:
            break
        print(f"\n  round {rnd}: {len(missing):,} unresolved, retrying serially", flush=True)
        for i in range(0, len(missing), 20):
            ents = batch(missing[i:i + 20])
            for qid, ent in ents.items():
                sl = ent.get("sitelinks") or {}
                langs_for[qid] = sorted(k[:-4] for k in sl if k in EDITIONS)
            time.sleep(0.4)

    missing = [qid for qid in qids if qid not in langs_for]
    if missing:
        raise SystemExit(
            f"\n{len(missing):,} of {len(qids):,} events unresolved after 5 retry rounds.\n"
            "Refusing to write a partial corpus: the top-32 vocabulary is recomputed in\n"
            "the same pass, and a kept mask is bit positions into it, so rows that missed\n"
            "this run would be read against a vocabulary they were never built for.\n"
            "src/events.json is unchanged. Re-run when the API is answering.")

    # The 32 editions that appear most often here. A fixed vocabulary, so the
    # mask means the same thing in every event and the client needs no lookup.
    freq = collections.Counter(l for ls in langs_for.values() for l in ls)
    top = [l for l, _ in freq.most_common(32)]
    idx = {l: i for i, l in enumerate(top)}
    print(f"\ntop 32 editions: {','.join(top)}")

    for e in events:
        ls = langs_for[e["q"]]           # every one of them, or we exited above
        mask = 0
        for l in ls:
            if l in idx:
                mask |= (1 << idx[l])
        e["m"] = mask
        e["sl"] = len(ls)                # authoritative count from the sitelinks themselves

    doc["langs"] = top
    # Written beside and renamed over. A five-megabyte json.dump that dies part
    # way through - a full disk, a Ctrl-C - leaves a truncated events.json that
    # every tool downstream reads as a parse error, and the only copy of the
    # corpus is in git. os.replace is atomic on the same filesystem.
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, PATH)

    cov = collections.Counter()
    for e in events:
        for l in top:
            if e["m"] & (1 << idx[l]):
                cov[l] += 1
    print(f"\nrewrote {PATH}  ({os.path.getsize(PATH):,} bytes)   "
          f"all {len(events):,} events resolved from live sitelinks")
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
