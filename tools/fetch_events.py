"""
Pull dated, geolocated human events from Wikidata.

    python tools/fetch_events.py                # default slice
    python tools/fetch_events.py --per-cat 800  # bigger

Wikidata is a poor source of *sourced dates* for deep time — across ten
well-known geological referents it yielded one citation-backed date. For human
history it is the opposite: a battle, a treaty, a cathedral or an earthquake has
a date and a coordinate that nobody disputes, and the encyclopedia is a fair
thing to cite for them. So this ingests at scale and attributes honestly to
Wikidata rather than pretending to a primary source per row.

Ranking is by sitelink count — how many Wikipedia language editions carry an
article. It is free, language-agnostic, and it means "start small" can mean the
most significant N rather than an arbitrary N: at the top of the battles it
returns Waterloo, Pearl Harbor, Thermopylae, Hastings.

Writes src/events.json.
"""
import urllib.request, urllib.parse, json, os, re, time, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "src", "events.json")
UA = {"User-Agent": "HumanTime/0.1 (https://github.com/kejjeh; mailto:joshp1001@gmail.com)",
      "Accept": "application/sparql-results+json"}
EP = "https://query.wikidata.org/sparql?format=json&query="

# (key, label, Wikidata class, theme, date properties in preference order)
CATEGORIES = [
    ("battle",      "Battles",            "Q178561",  "conflict",   "P585|P580"),
    ("siege",       "Sieges",             "Q188055",  "conflict",   "P585|P580"),
    ("war",         "Wars",               "Q198",     "conflict",   "P580|P585"),
    ("massacre",    "Massacres",          "Q3199915", "conflict",   "P585|P580"),
    ("treaty",      "Treaties",           "Q131569",  "polity",     "P585|P580"),
    ("revolution",  "Revolutions",        "Q10931",   "polity",     "P580|P585"),
    ("earthquake",  "Earthquakes",        "Q7944",    "disaster",   "P585"),
    ("eruption",    "Volcanic eruptions", "Q7692360", "disaster",   "P585|P580"),
    ("shipwreck",   "Shipwrecks",         "Q852190",  "disaster",   "P585|P571"),
    ("archaeology", "Archaeological sites","Q839954", "settlement", "P571|P585"),
    ("city",        "Cities",             "Q515",     "settlement", "P571"),
    ("castle",      "Castles",            "Q23413",   "building",   "P571"),
    ("cathedral",   "Cathedrals",         "Q2977",    "building",   "P571"),
    ("heritage",    "World Heritage",     "Q9259",    "building",   "P571|P585"),
    ("university",  "Universities",       "Q3918",    "knowledge",  "P571"),
    ("observatory", "Observatories",      "Q62832",   "knowledge",  "P571"),
    ("museum",      "Museums",            "Q33506",   "knowledge",  "P571"),
]

THEMES = ["conflict", "polity", "disaster", "settlement", "building", "knowledge"]


def sparql(query, timeout=180, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(EP + urllib.parse.quote(query), headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise last


def parse_point(s):
    m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", s or "")
    if not m:
        return None
    lng, lat = float(m.group(1)), float(m.group(2))
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return round(lat, 4), round(lng, 4)


def parse_year(s):
    """
    Wikidata time literal -> integer year (negative = BCE).

    The sign is OPTIONAL. SPARQL JSON renders BCE as '-0479-08-06T...' but CE as
    plain '1815-06-18T...' with no leading '+'. Requiring the sign silently drops
    every event after year 1 — which looked like sparse coverage rather than a
    parser bug, because the BCE rows that survived were perfectly plausible.
    """
    m = re.match(r"([+-]?)(\d{1,})-", s or "")
    if not m:
        return None
    y = int(m.group(2))
    return -y if m.group(1) == "-" else y


def fetch_category(key, cls, dateprops, per_cat, min_sitelinks):
    dp = "|".join(f"wdt:{p}" for p in dateprops.split("|"))
    q = f"""SELECT ?i ?iLabel ?coord ?date ?sl WHERE {{
  ?i wdt:P31/wdt:P279* wd:{cls} ;
     wdt:P625 ?coord ;
     ({dp}) ?date ;
     wikibase:sitelinks ?sl .
  FILTER(?sl >= {min_sitelinks})
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY DESC(?sl) LIMIT {per_cat * 3}"""
    return sparql(q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cat", type=int, default=400)
    ap.add_argument("--min-sitelinks", type=int, default=6)
    a = ap.parse_args()

    events = {}
    stats = []
    for key, label, cls, theme, dateprops in CATEGORIES:
        try:
            rows = fetch_category(key, cls, dateprops, a.per_cat, a.min_sitelinks)
        except Exception as e:                       # noqa: BLE001
            print(f"  {label:22} FAILED {type(e).__name__}")
            stats.append((label, 0, 0))
            continue

        kept = 0
        seen_here = set()
        for r in rows:
            if kept >= a.per_cat:
                break
            qid = r["i"]["value"].rsplit("/", 1)[-1]
            if qid in events or qid in seen_here:
                continue                              # same item, two dates
            pt = parse_point(r.get("coord", {}).get("value"))
            yr = parse_year(r.get("date", {}).get("value"))
            name = r.get("iLabel", {}).get("value", "")
            if not pt or yr is None or not name or name.startswith("Q"):
                continue
            if yr > 2026 or yr < -300000:
                continue
            seen_here.add(qid)
            events[qid] = {
                "q": qid, "n": name, "lat": pt[0], "lng": pt[1],
                "y": yr, "c": key, "t": theme,
                "sl": int(r["sl"]["value"]),
            }
            kept += 1
        stats.append((label, len(rows), kept))
        print(f"  {label:22} {len(rows):>6} rows -> {kept:>5} kept")
        time.sleep(0.5)

    out = sorted(events.values(), key=lambda e: -e["sl"])
    by_theme = collections.Counter(e["t"] for e in out)
    years = [e["y"] for e in out]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"events": out,
               "categories": [{"key": k, "label": l, "theme": t} for k, l, _, t, _ in CATEGORIES],
               "themes": THEMES},
              open(OUT, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)

    print(f"\n{len(out):,} events -> {OUT}  ({os.path.getsize(OUT):,} bytes)")
    print("by theme:", dict(by_theme))
    print(f"years {min(years)} to {max(years)}")
    for lo, hi in [(-300000, -3000), (-3000, 0), (0, 1000), (1000, 1500),
                   (1500, 1800), (1800, 1900), (1900, 2000), (2000, 2027)]:
        n = sum(1 for y in years if lo <= y < hi)
        print(f"  {lo:>7} to {hi:<6} {n:>5}  {'#' * min(60, n // 20)}")
    print("\nmost notable:")
    for e in out[:8]:
        print(f"  {e['sl']:>3} langs  {e['y']:>6}  {e['c']:<12} {e['n'][:44]}")


if __name__ == "__main__":
    main()
