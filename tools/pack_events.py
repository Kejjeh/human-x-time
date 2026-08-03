"""
Pack src/events.json into the compact wire format the page decodes.

Imported by tools/build.py; run directly to see the numbers and prove the
round-trip:

    python tools/pack_events.py

WHY
---
The readable corpus costs about 131 bytes an event as JSON objects: every row
repeats the key names, spells coordinates out in decimal, and stores the QID as
the string "Q1234567". At seven thousand events that was 925 KB and nobody cared.
At forty thousand it is five megabytes, which is a slow first paint on a phone
and an artifact that will not publish.

So: columnar, delta-coded where the column is sorted, zigzag varints in the same
64-character alphabet the coastlines already use (chosen because none of its
characters need escaping inside a JSON string, so the payload survives the trip
into the document untouched).

Sorting by YEAR rather than by notability is what makes the biggest single
column nearly free - consecutive deltas are 0 or 1 for most of the corpus, one
character each, against the six or so a raw year would take.

Names are the irreducible part. They are roughly half the packed size and there
is no honest way around that; a self-contained page has to carry its own labels.
"""
import json, os, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src", "events.json")

ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"


def varint(n, out):
    """Base-64 varint, low 5 bits per character, bit 0x20 = 'more follows'."""
    assert n >= 0, n
    while True:
        b = n & 0x1F
        n >>= 5
        out.append(ALPHA[b | (0x20 if n else 0)])
        if not n:
            return


def zigzag(n):
    return (n << 1) ^ (n >> 63) if n < 0 else (n << 1)


def enc_delta(values, zig=True):
    out, prev = [], 0
    for v in values:
        d = v - prev
        prev = v
        varint(zigzag(d) if zig else d, out)
    return "".join(out)


def enc_plain(values, zig=False):
    out = []
    for v in values:
        varint(zigzag(v) if zig else v, out)
    return "".join(out)


def dec_all(s):
    """Decode a whole varint column back to a list. Used to prove the round-trip."""
    idx = {c: i for i, c in enumerate(ALPHA)}
    out, i, n = [], 0, len(s)
    while i < n:
        shift, res = 0, 0
        while True:
            b = idx[s[i]]
            i += 1
            res |= (b & 0x1F) << shift
            shift += 5
            if not (b & 0x20):
                break
        out.append(res)
    return out


def unzig(n):
    return ~(n >> 1) if (n & 1) else (n >> 1)


def pack(doc):
    events = sorted(doc["events"], key=lambda e: (e["y"], e["q"]))
    cats = [c["key"] for c in doc["categories"]]
    cat_ix = {k: i for i, k in enumerate(cats)}
    themes = doc["themes"]

    # A name containing a newline would corrupt the split on the other side.
    names = [e["n"].replace("\n", " ").replace("\r", " ") for e in events]

    cols = {
        # sorted ascending, so the deltas are 0 or 1 almost everywhere
        "y":   enc_delta([e["y"] for e in events]),
        # random order after the year sort; a raw varint beats a zigzag delta here
        "q":   enc_plain([int(e["q"][1:]) for e in events]),
        # 1e3 is 111 m at the equator - four orders of magnitude finer than one
        # screen pixel at maximum zoom, and two characters cheaper than 1e4
        "lat": enc_plain([round(e["lat"] * 1000) for e in events], zig=True),
        "lng": enc_plain([round(e["lng"] * 1000) for e in events], zig=True),
        # no theme column: a category determines its theme, so shipping both
        # would be a byte an event to restate what categories already say
        "c":   enc_plain([cat_ix[e["c"]] for e in events]),
        "sl":  enc_plain([max(0, int(e["sl"])) for e in events]),
        "m":   enc_plain([int(e.get("m", 0)) for e in events]),
    }

    return {
        "v": 2,
        "n": len(events),
        "themes": themes,
        "categories": doc["categories"],
        "langs": doc.get("langs", []),
        "names": "\n".join(names),
        "cols": cols,
    }


def verify(doc, packed):
    """Decode the packed columns in Python and compare against the source."""
    events = sorted(doc["events"], key=lambda e: (e["y"], e["q"]))
    cats = [c["key"] for c in doc["categories"]]
    names = packed["names"].split("\n")
    assert len(names) == packed["n"], f"{len(names)} names for {packed['n']} events"

    ys, prev = [], 0
    for d in dec_all(packed["cols"]["y"]):
        prev += unzig(d)
        ys.append(prev)
    qs = dec_all(packed["cols"]["q"])
    lats = [unzig(v) for v in dec_all(packed["cols"]["lat"])]
    lngs = [unzig(v) for v in dec_all(packed["cols"]["lng"])]
    cs = dec_all(packed["cols"]["c"])
    sls = dec_all(packed["cols"]["sl"])
    ms = dec_all(packed["cols"]["m"])

    bad = 0
    for i, e in enumerate(events):
        if (ys[i] != e["y"] or qs[i] != int(e["q"][1:]) or cats[cs[i]] != e["c"]
                or sls[i] != int(e["sl"]) or ms[i] != int(e.get("m", 0))
                or names[i] != e["n"].replace("\n", " ").replace("\r", " ")
                or abs(lats[i] / 1000 - e["lat"]) > 0.0006
                or abs(lngs[i] / 1000 - e["lng"]) > 0.0006):
            bad += 1
            if bad <= 3:
                print(f"  MISMATCH at {i}: {e['q']} {e['n'][:40]}")
    return bad


def main():
    doc = json.load(open(SRC, encoding="utf-8"))
    packed = pack(doc)
    raw = len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    new = len(json.dumps(packed, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    n = packed["n"]
    print(f"{n:,} events")
    print(f"  readable {raw:>12,} bytes   {raw / n:>6.1f} per event")
    print(f"  packed   {new:>12,} bytes   {new / n:>6.1f} per event   "
          f"{100 * (1 - new / raw):.0f}% smaller")
    print("\ncolumn sizes:")
    print(f"  {'names':6} {len(packed['names']):>10,}  {len(packed['names']) / n:>5.1f}/event")
    for k, v in sorted(packed["cols"].items(), key=lambda kv: -len(kv[1])):
        print(f"  {k:6} {len(v):>10,}  {len(v) / n:>5.1f}/event")

    bad = verify(doc, packed)
    print(f"\nround-trip: {'OK' if not bad else f'{bad} MISMATCHES'}")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
