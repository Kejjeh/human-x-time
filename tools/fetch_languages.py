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
import urllib.request, urllib.parse, json, os, time, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATH = os.path.join(ROOT, "src", "events.json")
UA = {"User-Agent": "HumanTime/0.1 (https://github.com/kejjeh; mailto:joshp1001@gmail.com)"}
API = "https://www.wikidata.org/w/api.php"

SKIP = {"commonswiki", "specieswiki", "metawiki", "sourceswiki", "wikidatawiki"}


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
    qids = [e["q"] for e in events]
    print(f"{len(qids):,} events; {(len(qids) + 49) // 50} batches of 50")

    langs_for = {}
    t0 = time.time()
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        ents = batch(chunk)
        for qid, ent in ents.items():
            sl = ent.get("sitelinks") or {}
            langs_for[qid] = sorted(
                k[:-4] for k in sl
                if k.endswith("wiki") and k not in SKIP and "wikiquote" not in k
            )
        done = min(i + 50, len(qids))
        if (i // 50) % 10 == 0 or done == len(qids):
            print(f"  {done:>5}/{len(qids)}  {time.time() - t0:.0f}s")
        time.sleep(0.12)

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
            missing += 1
            e["m"] = 0
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
    print("coverage by edition (of %d events):" % len(events))
    for l, n in cov.most_common(12):
        print(f"  {l:6} {n:>5}  {100*n//len(events):>3}%  {'#' * (n * 40 // len(events))}")
    # the whole point of the axis: how uneven is the record?
    en = sum(1 for e in events if e["m"] & (1 << idx.get("en", 0)))
    print(f"\nevents NOT on English Wikipedia: {len(events) - en:,}")


if __name__ == "__main__":
    main()
