"""
Pull dated, geolocated human events from Wikidata.

    python tools/fetch_events.py                     # the default corpus
    python tools/fetch_events.py --per-cat 3000      # bigger
    python tools/fetch_events.py --only battle,city  # one or two categories
    python tools/fetch_events.py --only school --merge --threads 2
                                                     # backfill what WDQS timed out on

Wikidata is a poor source of *sourced dates* for deep time - across ten
well-known geological referents it yielded one citation-backed date. For human
history it is the opposite: a battle, a treaty, a cathedral or an earthquake has
a date and a coordinate that nobody disputes, and the encyclopedia is a fair
thing to cite for them. So this ingests at scale and attributes honestly to
Wikidata rather than pretending to a primary source per row.

TWO THINGS THIS DOES DIFFERENTLY FROM THE FIRST VERSION
-------------------------------------------------------
1. Class QIDs are RESOLVED BY NAME, never typed in by hand. Hand-typing them is
   how this project once reported Chicxulub as Q13415, which is a star in Canis
   Major. Every class below is looked up through wbsearchentities, checked
   against its own label, and the resolution is cached in tools/classes.json so
   runs are reproducible and the mapping is reviewable in the diff.

2. Fetching is BANDED BY SITELINK COUNT rather than ranked by it. One
   `ORDER BY DESC(?sl) LIMIT 3000` over a big class times out against the 60s
   WDQS limit, and - worse - ranking by notability silently destroys the axis
   this site is built on. In the notability-ranked head 99.5% of events have an
   English article; in the 2-to-12-edition tail 11% do not. Asking each band for
   its own quota gives the coverage rail mass at every level instead of a spike
   at the top, and no single query is big enough to time out.

Writes src/events.json.
"""
import urllib.request, urllib.parse, json, os, re, time, argparse, collections, threading, unicodedata
import concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "src", "events.json")
CLASSES = os.path.join(HERE, "classes.json")
UA = {"User-Agent": "HumanTime/0.2 (https://github.com/kejjeh; mailto:joshp1001@gmail.com)",
      "Accept": "application/sparql-results+json"}
EP = "https://query.wikidata.org/sparql?format=json&query="
API = "https://www.wikidata.org/w/api.php"

# (key, label, search term for the Wikidata class, theme, date properties in
#  preference order). The search term is what gets resolved to a QID; keep it
#  the exact English label of the class you mean.
CATEGORIES = [
    # ---- conflict
    ("battle",      "Battles",             "battle",                "conflict",   "P585|P580"),
    ("siege",       "Sieges",              "siege",                 "conflict",   "P585|P580"),
    ("war",         "Wars",                "war",                   "conflict",   "P580|P585"),
    ("massacre",    "Massacres",           "massacre",              "conflict",   "P585|P580"),
    ("rebellion",   "Rebellions",          "rebellion",             "conflict",   "P580|P585"),
    ("coup",        "Coups d'etat",        "coup d'état",           "conflict",   "P585|P580"),
    ("riot",        "Riots",               "riot",                  "conflict",   "P585|P580"),
    ("fortif",      "Fortifications",      "fortification",         "conflict",   "P571"),
    ("milbase",     "Military bases",      "military base",         "conflict",   "P571"),
    # ---- polity
    ("treaty",      "Treaties",            "treaty",                "polity",     "P585|P580"),
    ("revolution",  "Revolutions",         "revolution",            "polity",     "P580|P585"),
    ("parliament",  "Parliament buildings","parliament building",   "polity",     "P571"),
    ("capital",     "Capitals",            "capital city",          "polity",     "P571"),
    ("courthouse",  "Courthouses",         "courthouse",            "polity",     "P571"),
    ("embassy",     "Embassies",           "embassy",               "polity",     "P571"),
    # ---- disaster
    ("earthquake",  "Earthquakes",         "earthquake",            "disaster",   "P585"),
    ("eruption",    "Volcanic eruptions",  "volcanic eruption",     "disaster",   "P585|P580"),
    ("shipwreck",   "Shipwrecks",          "shipwreck",             "disaster",   "P585|P571"),
    ("flood",       "Floods",              "flood",                 "disaster",   "P585|P580"),
    ("cyclone",     "Tropical cyclones",   "tropical cyclone",      "disaster",   "P585|P580"),
    ("fire",        "Fires",               "conflagration",         "disaster",   "P585|P580"),
    ("aircrash",    "Aviation accidents",  "aviation accident",     "disaster",   "P585"),
    ("railcrash",   "Rail accidents",      "railway accident",      "disaster",   "P585"),
    ("epidemic",    "Epidemics",           "epidemic",              "disaster",   "P580|P585"),
    ("famine",      "Famines",             "famine",                "disaster",   "P580|P585"),
    # ---- settlement
    ("archaeology", "Archaeological sites","archaeological site",   "settlement", "P571|P585"),
    ("city",        "Cities",              "city",                  "settlement", "P571"),
    ("town",        "Towns",               "town",                  "settlement", "P571"),
    ("village",     "Villages",            "village",               "settlement", "P571"),
    ("ghosttown",   "Ghost towns",         "ghost town",            "settlement", "P571|P576"),
    ("mine",        "Mines",               "mine",                  "settlement", "P571"),
    ("cemetery",    "Cemeteries",          "cemetery",              "settlement", "P571"),
    ("prison",      "Prisons",             "prison",                "settlement", "P571"),
    # ---- building
    ("castle",      "Castles",             "castle",                "building",   "P571"),
    ("cathedral",   "Cathedrals",          "cathedral",             "building",   "P571"),
    ("church",      "Churches",            "church building",       "building",   "P571"),
    ("mosque",      "Mosques",             "mosque",                "building",   "P571"),
    ("synagogue",   "Synagogues",          "synagogue",             "building",   "P571"),
    ("temple",      "Temples",             "temple",                "building",   "P571"),
    ("monastery",   "Monasteries",         "monastery",             "building",   "P571"),
    ("palace",      "Palaces",             "palace",                "building",   "P571"),
    ("heritage",    "World Heritage",      "World Heritage Site",   "building",   "P571|P585"),
    ("monument",    "Monuments",           "monument",              "building",   "P571"),
    ("lighthouse",  "Lighthouses",         "lighthouse",            "building",   "P571"),
    ("bridge",      "Bridges",             "bridge",                "building",   "P571"),
    ("dam",         "Dams",                "dam",                   "building",   "P571"),
    ("canal",       "Canals",              "canal",                 "building",   "P571"),
    ("tunnel",      "Tunnels",             "tunnel",                "building",   "P571"),
    ("railstation", "Railway stations",    "train station",         "building",   "P571"),
    ("airport",     "Airports",            "airport",               "building",   "P571"),
    ("stadium",     "Stadiums",            "stadium",               "building",   "P571"),
    ("skyscraper",  "Skyscrapers",         "skyscraper",            "building",   "P571"),
    ("powerplant",  "Power stations",      "power station",         "building",   "P571"),
    ("factory",     "Factories",           "factory",               "building",   "P571"),
    # ---- knowledge
    ("university",  "Universities",        "university",            "knowledge",  "P571"),
    ("school",      "Schools",             "school",                "knowledge",  "P571"),
    ("observatory", "Observatories",       "observatory",           "knowledge",  "P571"),
    ("museum",      "Museums",             "museum",                "knowledge",  "P571"),
    ("library",     "Libraries",           "library",               "knowledge",  "P571"),
    ("theatre",     "Theatres",            "theater building",               "knowledge",  "P571"),
    ("operahouse",  "Opera houses",        "opera house",           "knowledge",  "P571"),
    ("hospital",    "Hospitals",           "hospital",              "knowledge",  "P571"),
    ("botanic",     "Botanical gardens",   "botanical garden",      "knowledge",  "P571"),
    ("zoo",         "Zoos",                "zoo",                   "knowledge",  "P571"),
    ("expedition",  "Expeditions",         "expedition",            "knowledge",  "P580|P585"),
    ("spaceport",   "Spaceports",          "spaceport",             "knowledge",  "P571"),
]

THEMES = ["conflict", "polity", "disaster", "settlement", "building", "knowledge"]

# Sitelink bands, high to low, with a quota each. The low bands are where the
# "whose record is this?" axis actually lives, so they are not an afterthought.
BAND_WEIGHT = {(200, 100000): 0.08, (80, 200): 0.11, (40, 80): 0.13, (20, 40): 0.14,
               (12, 20): 0.14, (8, 12): 0.13, (5, 8): 0.12, (3, 5): 0.09, (2, 3): 0.06}

_print_lock = threading.Lock()


def say(*a):
    with _print_lock:
        print(*a, flush=True)


def get_json(url, timeout=90, tries=4, accept=None):
    hdr = dict(UA)
    if accept:
        hdr["Accept"] = accept
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:                            # noqa: BLE001
            last = e
            time.sleep(2.5 * (i + 1))
    raise last


def sparql(query, timeout=90, tries=3):
    return get_json(EP + urllib.parse.quote(query), timeout, tries)["results"]["bindings"]


# ----------------------------------------------------------- class resolution
def norm(s):
    """Fold the differences that are not differences: case, accents, apostrophes.

    Without this, "coup d'état" misses Wikidata's "coup d'état" and "theater"
    misses "theatre" - both of which look identical to a reader and are the
    reason two perfectly good categories silently vanished on the first run.
    """
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("’", "'").replace("-", " ").strip()


def search_class(term):
    """Resolve an English class name to a QID, and prove it resolved to a class.

    Two guards, both earned the hard way. The label (or a matched alias) must
    equal the term we asked for, so 'mine' cannot quietly become a film called
    Mine; and the item must actually be used as a class - it must have instances
    - so we cannot point a P31/P279* query at something that returns nothing.
    """
    url = API + "?" + urllib.parse.urlencode({
        "action": "wbsearchentities", "search": term, "language": "en",
        "type": "item", "limit": "12", "format": "json", "formatversion": "2"})
    hits = get_json(url, accept="application/json").get("search", [])
    want = norm(term)
    for h in hits:
        names = [h.get("label"), (h.get("match") or {}).get("text")]
        names += h.get("aliases") or []
        if not any(norm(n) == want for n in names if n):
            continue
        qid = h["id"]
        # Instances with COORDINATES, not instances in general. "theatre" other-
        # wise resolves to Q11635, the art form, which is a perfectly real class
        # with plenty of instances and not one of them is a place on the globe.
        n = sparql(f"SELECT (COUNT(*) AS ?n) WHERE {{ {{ SELECT ?x WHERE {{ "
                   f"?x wdt:P31/wdt:P279* wd:{qid} ; wdt:P625 ?c . }} LIMIT 60 }} }}")
        if int(n[0]["n"]["value"]) >= 40:
            return qid, h.get("label", ""), h.get("description", "")
    return None, None, None


def resolve_classes(cats, refresh):
    """Resolve the categories asked for, and never forget the ones that were not.

    The cache used to be rewritten from `out`, which holds only the categories
    this run looked at - so `--only school`, the backfill command in this
    module's own docstring, replaced a 62-entry classes.json with a 1-entry one
    and silently threw away every other resolution. Measured: 4 entries in, 1
    out, church/monument/village gone. The next full run then has to re-resolve
    from scratch, and the file stops being the reviewable record it is for.
    """
    cache = {}
    if os.path.exists(CLASSES) and not refresh:
        cache = json.load(open(CLASSES, encoding="utf-8"))
    out, missing = {}, []
    for key, label, term, theme, dp in cats:
        if key in cache and cache[key].get("qid"):
            out[key] = cache[key]
            continue
        qid, lab, desc = search_class(term)
        if not qid:
            missing.append((key, term))
            say(f"  {key:12} {term!r:26} UNRESOLVED - dropped")
            continue
        out[key] = {"qid": qid, "term": term, "label": lab, "desc": desc}
        say(f"  {key:12} {term!r:26} -> {qid:10} {lab} ({(desc or '')[:52]})")
        time.sleep(0.3)
    merged = dict(cache)
    merged.update(out)
    # Stable order, so the diff shows what changed rather than a reshuffle.
    order = [k for k, *_ in CATEGORIES]
    merged = dict(sorted(merged.items(),
                         key=lambda kv: (order.index(kv[0]) if kv[0] in order else 999, kv[0])))
    json.dump(merged, open(CLASSES, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return out, missing


# ------------------------------------------------------------------- parsing
def parse_point(s):
    m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", s or "")
    if not m:
        return None
    lng, lat = float(m.group(1)), float(m.group(2))
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    if abs(lat) < 1e-9 and abs(lng) < 1e-9:
        return None                                   # Null Island, i.e. no coordinate
    return round(lat, 4), round(lng, 4)


def parse_year(s):
    """
    Wikidata time literal -> integer year (negative = BCE).

    The sign is OPTIONAL. SPARQL JSON renders BCE as '-0479-08-06T...' but CE as
    plain '1815-06-18T...' with no leading '+'. Requiring the sign silently drops
    every event after year 1 - which looked like sparse coverage rather than a
    parser bug, because the BCE rows that survived were perfectly plausible.
    """
    m = re.match(r"([+-]?)(\d{1,})-", s or "")
    if not m:
        return None
    y = int(m.group(2))
    return -y if m.group(1) == "-" else y


# ------------------------------------------------------------------ fetching
def band_query(qid, dateprops, lo, hi, limit):
    dp = "|".join(f"wdt:{p}" for p in dateprops.split("|"))
    # No ORDER BY: the band already selects, and sorting a large class is what
    # blows the 60-second budget.
    return f"""SELECT ?i ?iLabel ?coord ?date ?sl WHERE {{
  ?i wdt:P31/wdt:P279* wd:{qid} ;
     wdt:P625 ?coord ;
     ({dp}) ?date ;
     wikibase:sitelinks ?sl .
  FILTER(?sl >= {lo} && ?sl < {hi})
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT {limit}"""


def fetch_one(job):
    key, qid, dp, lo, hi, limit = job
    try:
        rows = sparql(band_query(qid, dp, lo, hi, limit))
        return key, lo, hi, rows, None
    except Exception as e:                                # noqa: BLE001
        return key, lo, hi, [], repr(e)[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cat", type=int, default=1800,
                    help="target events per category, split across sitelink bands")
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated category keys")
    ap.add_argument("--refresh-classes", action="store_true")
    ap.add_argument("--merge", action="store_true",
                    help="add to the existing src/events.json instead of replacing it; "
                         "for backfilling the bands WDQS times out on")
    a = ap.parse_args()

    cats = CATEGORIES
    if a.only:
        want = set(a.only.split(","))
        cats = [c for c in cats if c[0] in want]

    say(f"resolving {len(cats)} classes by name")
    classes, missing = resolve_classes(cats, a.refresh_classes)
    cats = [c for c in cats if c[0] in classes]
    say(f"{len(cats)} classes resolved, {len(missing)} dropped\n")

    jobs = []
    for key, label, term, theme, dp in cats:
        qid = classes[key]["qid"]
        for (lo, hi), w in BAND_WEIGHT.items():
            jobs.append((key, qid, dp, lo, hi, max(40, int(a.per_cat * w))))

    say(f"{len(jobs)} banded queries over {len(cats)} categories, {a.threads} at a time")
    t0 = time.time()
    results = collections.defaultdict(list)
    failures = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=a.threads) as ex:
        for key, lo, hi, rows, err in ex.map(fetch_one, jobs):
            done += 1
            if err:
                failures.append((key, lo, hi, err))
            results[key].extend(rows)
            if done % 25 == 0 or done == len(jobs):
                say(f"  {done:>4}/{len(jobs)}  {time.time() - t0:>5.0f}s  "
                    f"{sum(len(v) for v in results.values()):>7,} rows  {len(failures)} failed")

    theme_of = {k: t for k, _, _, t, _ in cats}
    events = {}
    prior = {}
    prior_langs = []
    if a.merge and os.path.exists(OUT):
        prior_doc = json.load(open(OUT, encoding="utf-8"))
        prior = {e["q"]: e for e in prior_doc["events"]}
        prior_langs = prior_doc.get("langs", [])
        events.update(prior)
        say(f"merging into {len(prior):,} existing events")
    per_cat = collections.Counter()
    for key, rows in results.items():
        for r in rows:
            qid = r["i"]["value"].rsplit("/", 1)[-1]
            if qid in events:
                continue                                  # same item, two classes or two dates
            pt = parse_point(r.get("coord", {}).get("value"))
            yr = parse_year(r.get("date", {}).get("value"))
            name = r.get("iLabel", {}).get("value", "")
            if not pt or yr is None or not name or re.fullmatch(r"Q\d+", name):
                continue
            if yr > 2026 or yr < -300000:
                continue
            events[qid] = {"q": qid, "n": name, "lat": pt[0], "lng": pt[1],
                           "y": yr, "c": key, "t": theme_of[key],
                           "sl": int(r["sl"]["value"])}
            per_cat[key] += 1

    out = sorted(events.values(), key=lambda e: -e["sl"])
    by_theme = collections.Counter(e["t"] for e in out)
    years = [e["y"] for e in out]
    sls = [e["sl"] for e in out]

    # A merge run only fetched some categories; keep the full category list from
    # the file being merged into, or the packed corpus loses the labels for
    # every category this run did not touch.
    cat_rows = [{"key": k, "label": l, "theme": t} for k, l, _, t, _ in cats]
    if a.merge and os.path.exists(OUT):
        old = json.load(open(OUT, encoding="utf-8"))
        have = {c["key"] for c in cat_rows}
        cat_rows = [c for c in old.get("categories", []) if c["key"] not in have] + cat_rows
        cat_rows.sort(key=lambda c: [x[0] for x in CATEGORIES].index(c["key"])
                      if c["key"] in [x[0] for x in CATEGORIES] else 999)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc = {"events": out,
           "categories": cat_rows,
           "themes": THEMES,
           "classes": {k: classes[k]["qid"] for k in classes}}
    if a.merge and prior_langs:
        # `langs` is the vocabulary every `m` mask is written against, and it is
        # written by fetch_languages.py, not here. Rebuilding the document
        # without it on a merge run left the masks in place and the key they
        # decode with gone: LANGS becomes [], the lens dropdown loses every
        # option, and "not on English Wikipedia" matches the whole corpus
        # because LANG_BIT.en is undefined. Carry it forward.
        doc["langs"] = prior_langs
    # Events this run added have no mask yet - fetch_languages.py is a separate
    # pass - and until it runs they read as "carried by no edition at all".
    unmasked = sum(1 for e in out if "m" not in e)
    if unmasked:
        say(f"\n{unmasked:,} events have no language mask. "
            f"Run tools/fetch_languages.py before tools/build.py.")
    if a.merge:
        say(f"\nmerged: {len(prior):,} + {len(out) - len(prior):,} new = {len(out):,}")
    json.dump(doc, open(OUT, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)

    say(f"\n{len(out):,} events -> {OUT}  ({os.path.getsize(OUT):,} bytes)  "
        f"in {time.time() - t0:.0f}s")
    say("by theme: " + ", ".join(f"{k} {v:,}" for k, v in by_theme.most_common()))
    say(f"years {min(years)} to {max(years)}")
    say("\nsitelink bands (the coverage rail reads this):")
    for lo, hi in BAND_WEIGHT:
        n = sum(1 for s in sls if lo <= s < hi)
        say(f"  {lo:>4}-{hi if hi < 1000 else '+':<5} {n:>7,}  {'#' * min(56, n // 200)}")
    say("\nby century:")
    for lo, hi in [(-300000, -3000), (-3000, 0), (0, 1000), (1000, 1500),
                   (1500, 1800), (1800, 1900), (1900, 2000), (2000, 2027)]:
        n = sum(1 for y in years if lo <= y < hi)
        say(f"  {lo:>7} to {hi:<6} {n:>7,}  {'#' * min(56, n // 300)}")
    say("\nthinnest categories:")
    for k, n in sorted(per_cat.items(), key=lambda kv: kv[1])[:8]:
        say(f"  {k:12} {n:>6,}")
    if failures:
        say(f"\n{len(failures)} band queries failed:")
        for key, lo, hi, err in failures[:12]:
            say(f"  {key:12} {lo}-{hi}  {err}")


if __name__ == "__main__":
    main()
