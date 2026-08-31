"""Assemble the single-file app.

Concatenates src/ in order and injects the bulky assets (fonts, coastlines,
timescale, seed graph) so none of them have to be pasted by hand.

Emits two files with identical content:
  human-x-time.html   full standalone document, for opening off disk
  artifact.html       body-only, for a host that supplies its own <head>
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
ASSETS = os.path.join(ROOT, "assets")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def embed_json(obj):
    r"""Serialise for pasting inside a <script> tag.

    The corpus is Wikidata's labels, and a label is whatever somebody typed. A
    name containing a closing script tag ends the tag early and the rest of the
    page becomes markup - so the build refused to run at all when one appeared,
    which is safe and is also a build that cannot be made to work without
    hand-editing the data. Escaping is the fix that refusal was standing in for:
    <, > and & become \uXXXX escapes, which JSON decodes back to exactly the
    same characters, so the payload is inert to anything reading the document as
    HTML and identical once parsed.

    U+2028 and U+2029 go the same way. They are legal inside a string literal
    from ES2019 and line terminators before it, and ensure_ascii=False emits
    them raw.
    """
    out = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                    ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        out = out.replace(ch, esc)
    return out


def main():
    # check_no_local_paths documents --all as "what you want from CI or a build
    # gate" and nothing ran it: the only thing standing between a leaked home
    # directory and a public repo was a pre-commit hook a fresh clone has to arm
    # by hand. It costs about a second over 4.9 MB of tracked text.
    import check_no_local_paths
    if check_no_local_paths.self_test():
        sys.exit("FATAL: the local-path patterns do not behave as documented")
    if check_no_local_paths.main(["", "--all"]):
        sys.exit("FATAL: an absolute home-directory path is tracked - see above")

    head = read(os.path.join(SRC, "00_head.html"))
    body = read(os.path.join(SRC, "10_body.html"))
    js = "\n".join(read(os.path.join(SRC, n)) for n in sorted(os.listdir(SRC))
                   if re.match(r"^\d\d_.*\.js$", n))

    fonts = read(os.path.join(ASSETS, "fonts.css"))
    coast = read(os.path.join(ASSETS, "coast.txt"))
    land = coast.split("===LAND===")[1].split("===PLATES===")[0].strip()
    plates = coast.split("===PLATES===")[1].strip()

    earth = read(os.path.join(ASSETS, "earth.txt")).strip()
    source = json.load(open(os.path.join(SRC, "events.json"), encoding="utf-8"))
    # src/events.json stays readable and reviewable in the diff; only the browser
    # gets the columnar form. See tools/pack_events.py.
    import pack_events
    try:
        events = pack_events.pack(source)
    except ValueError as err:
        sys.exit(f"FATAL: {err}")
    bad = pack_events.verify(source, events)
    if bad:
        sys.exit(f"FATAL: the packed corpus does not round-trip ({bad} mismatches)")

    # The client builds the language lens as `LANG_BIT[l] = 1 << i`. Past 32
    # editions that shift wraps - bit 32 aliases bit 0 - and the lens would
    # quietly answer for the wrong language rather than fail. The ingest caps
    # the vocabulary at 32; this is the gate that says so out loud if it stops.
    if len(events["langs"]) > 32:
        sys.exit(f"FATAL: {len(events['langs'])} language editions; the client's "
                 f"32-bit coverage mask cannot address more than 32")

    # The second axis is the language coverage, and it is written by a pass that
    # runs after the ingest. Ship without it and nothing upstream complains: the
    # corpus round-trips, the page boots, and the lens quietly becomes a dropdown
    # with one option while "not on English Wikipedia" matches everything,
    # because LANG_BIT.en is undefined. Both halves have to be there.
    if not events["langs"]:
        sys.exit("FATAL: the corpus carries no language vocabulary. "
                 "Run tools/fetch_languages.py, then build again.")
    unmasked = sum(1 for e in source["events"] if "m" not in e)
    if unmasked:
        sys.exit(f"FATAL: {unmasked:,} of {len(source['events']):,} events have no "
                 f"language mask; they would read as carried by no edition at all. "
                 f"Run tools/fetch_languages.py, then build again.")

    # `sl` is the total across all ~348 editions; `m` is a bit per edition in the
    # top 32. So the total can never be smaller than the number of bits set, and
    # an event where it is has had one of the two written by a different run than
    # the other - which is exactly the shape a half-finished coverage refresh
    # leaves behind, and it is invisible on screen: the bar and the codes agree
    # with each other and only the headline number is wrong.
    incoherent = [e["q"] for e in source["events"]
                  if e.get("sl", 0) < bin(e.get("m", 0)).count("1")]
    if incoherent:
        sys.exit(f"FATAL: {len(incoherent):,} events carry fewer total editions than "
                 f"the mask records (e.g. {incoherent[0]}); `sl` and `m` are from "
                 f"different runs. Re-run tools/fetch_languages.py.")

    # The encoding alphabet excludes quote, backslash and angle brackets, so the
    # payloads drop into a JS string literal untouched. Assert it rather than hope.
    for name, blob in (("land", land), ("plates", plates)):
        bad = set(blob) - set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-|")
        if bad:
            sys.exit(f"FATAL: {name} payload contains unsafe characters: {sorted(bad)!r}")

    head = head.replace("/*@FONTS@*/", fonts)
    js = js.replace("/*@LAND@*/", land)
    js = js.replace("/*@PLATES@*/", plates)
    js = js.replace("/*@EARTH@*/", earth)
    js = js.replace("/*@EVENTS@*/", embed_json(events))

    # Nothing may reach the browser with a placeholder still in it.
    inner = head + "\n" + body + '\n<script>\n' + js + '\n</script>\n'
    left = re.findall(r"/\*@[A-Z]+@\*/", inner)
    if left:
        sys.exit(f"FATAL: unsubstituted placeholders remain: {set(left)}")
    # A backstop, not the mechanism: embed_json has already escaped every < > &
    # in the payload, so this can only fire if the source files themselves carry
    # a closing tag.
    if re.search(r"</script", js, re.I):
        sys.exit("FATAL: a literal </script> inside the JS payload would close the tag early")

    # And the invariant embed_json exists for, asserted rather than assumed: the
    # corpus payload reaches the document with nothing in it that an HTML parser
    # would treat as markup.
    payload = embed_json(events)
    stray = {c for c in "<>&\u2028\u2029" if c in payload}
    if stray:
        sys.exit(f"FATAL: the corpus payload still carries {sorted(stray)!r} unescaped")

    # The artifact host supplies its own <head>, so drop our head tags there and
    # keep only <title> (which the publisher reads) plus the inlined styles.
    # <link rel="icon"> is not a <meta and the old rule walked straight past it,
    # which would have put this page's favicon on a host document that never
    # asked for one. Both are matched now, and the assertion below is what keeps
    # the next tag from slipping through the same gap.
    art_head = re.sub(r'^<(?:meta|link) [^>]*/>\n', '', head, flags=re.M)
    # The notes that explain those tags go with them. They sit above <style> and
    # are addressed to someone reading src/00_head.html; leaving a comment about
    # og:image inside a host's document, next to no og:image, is just litter.
    cut = art_head.find("<style>")
    if cut > 0:
        art_head = re.sub(r'<!--.*?-->\n?', '', art_head[:cut], flags=re.S) + art_head[cut:]
    art = art_head + "\n" + body + \
        '\n<script>\n' + js + '\n</script>\n'
    leaked = re.findall(r'^<(?:meta|link)\b[^>]*>', art, flags=re.M)
    if leaked:
        sys.exit("FATAL: artifact.html would carry head tags into its host: "
                 + ", ".join(t[:70] for t in leaked))

    out_art = os.path.join(ROOT, "artifact.html")
    with open(out_art, "w", encoding="utf-8") as f:
        f.write(art)

    # What a scraper and a browser tab get. All of it is in the head of the two
    # standalone documents and none of it in artifact.html, which a host owns.
    #
    # og:image is checked against the file it names, extension and magic bytes
    # both: preview shipped as .png with FF D8 FF at the front, and GitHub Pages
    # sets Content-Type from the extension, so the crawler was handed JPEG bytes
    # labelled image/png and several validators reject that outright.
    want = ['name="description"', 'property="og:title"', 'property="og:url"',
            'property="og:image"', 'name="twitter:card"', 'rel="icon"']
    absent = [w for w in want if w not in head]
    if absent:
        sys.exit(f"FATAL: the document head is missing {absent}")
    img = re.search(r'property="og:image" content="(https://[^"]+)"', head)
    if not img:
        sys.exit("FATAL: og:image must be an absolute https URL; scrapers refuse a relative one")
    name = img.group(1).rsplit("/", 1)[-1]
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        sys.exit(f"FATAL: og:image names {name}, which is not in the repository")
    with open(path, "rb") as fh:
        magic = fh.read(4)
    kind = ("jpg" if magic[:3] == b"\xff\xd8\xff" else
            "png" if magic == b"\x89PNG" else "?")
    if not name.lower().endswith("." + kind):
        sys.exit(f"FATAL: {name} is {kind} data under a .{name.rsplit('.', 1)[-1]} name; "
                 f"GitHub Pages types it from the extension and validators reject the mismatch")

    out_std = os.path.join(ROOT, "human-x-time.html")
    with open(out_std, "w", encoding="utf-8") as f:
        f.write('<!doctype html>\n<html lang="en">\n<head>\n' + head +
                '\n</head>\n<body>\n' + body +
                '\n<script>\n' + js + '\n</script>\n</body>\n</html>\n')

    # GitHub Pages serves index.html from the repo root.
    out_idx = os.path.join(ROOT, "index.html")
    with open(out_idx, "w", encoding="utf-8") as f:
        f.write(open(out_std, encoding="utf-8").read())

    raw = len(json.dumps(source, separators=(",", ":"), ensure_ascii=False).encode())
    packed = len(json.dumps(events, separators=(",", ":"), ensure_ascii=False).encode())
    print(f"events {events['n']:,}  categories {len(events['categories'])}  "
          f"langs {len(events['langs'])}")
    print(f"corpus {raw:,} -> {packed:,} bytes packed "
          f"({packed / max(1, events['n']):.1f} per event)")
    print(f"land {len(land):,} chars   plates {len(plates):,} chars   earth {len(earth):,} chars")
    print(f"fonts {len(fonts):,} chars")
    print(f"js {len(js):,} chars")
    for p in (out_std, out_art, out_idx):
        print(f"  {os.path.basename(p):22} {os.path.getsize(p):,} bytes")

    if "--no-smoke" not in sys.argv:
        smoke()


def smoke():
    """Open the thing we just built in a real browser and prove it runs.

    Not optional politeness. A build that emits a well-formed document whose
    boot() throws on line 3 is indistinguishable from a good one by every check
    upstream of here - that is not hypothetical, it is what happened on the
    sibling site, and it went unnoticed for the entire build.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("\n(skipping smoke test: pip install playwright && playwright install chromium)")
        return
    # Both outputs, not just one. build.py emits index.html and artifact.html and
    # this gate only ever loaded index.html - so the body-only form, the one that
    # actually gets published, was verified by nothing. The README's note about
    # the sibling site losing a whole build to a boot failure nothing detected is
    # about exactly this shape of gap.
    for label, args in (("index.html", []), ("artifact.html", ["--artifact"])):
        print(f"\nsmoke test: {label}")
        r = subprocess.run([sys.executable, os.path.join(HERE, "smoke_test.py")] + args,
                           capture_output=True, text=True)
        tail = [l for l in r.stdout.splitlines() if "FAIL" in l or "checks passed" in l]
        print("\n".join("  " + l.strip() for l in tail) or r.stdout[-800:])
        if r.returncode:
            sys.exit(f"FATAL: {label} does not work - see above")


if __name__ == "__main__":
    main()
