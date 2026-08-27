"""
Load the built page in a real browser and assert it actually works.

    python tools/smoke_test.py                 # tests ./index.html
    python tools/smoke_test.py --url https://kejjeh.github.io/human-x-time/
    python tools/smoke_test.py --headed        # watch it

WHY THIS EXISTS
---------------
The sibling site lost an entire build to a silent boot failure: a legend swatch
read the wrong palette key, undefined reached a string method, and the TypeError
landed three lines above requestAnimationFrame(frame). The animation loop was
never started - not throttled, never started - and the page ran off a 1.3 Hz
watchdog for its whole development history without anyone noticing.

Nothing caught it because every check called the draw functions directly and read
back canvas pixels, which passes perfectly against a page that displays nothing.
The checks below ask the page from outside instead: did boot() report finishing,
is the app's own rAF loop live (as opposed to the worker fallback quietly
covering for it), is the thing under the middle of the stage really the canvas,
does dragging move the globe.

Requires playwright with chromium. Exits non-zero on any failure.
"""
import argparse, functools, http.server, json, os, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, passed, detail=""):
        self.rows.append((bool(passed), name, str(detail)))
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""),
              flush=True)
        return bool(passed)

    @property
    def failures(self):
        return [r for r in self.rows if not r[0]]


# file:// is not good enough: a blob-URL Worker (the animation clock) is refused
# from an opaque file origin, so the heartbeat would silently not be under test.
def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a, **k: None
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


PROBE = "window.__ticks=0;(function t(){window.__ticks++;requestAnimationFrame(t)})();"

WRAP_RENDER = """
window.__renders = 0;
if (typeof window.render === 'function' && !window.__wrapped) {
  window.__wrapped = true;
  const inner = window.render;
  window.render = function (dt) { window.__renders++; return inner(dt); };
}
"""

CANVAS_STATS = """
(sel) => {
  const c = document.querySelector(sel);
  if (!c) return { err: 'no canvas' };
  const g = c.getContext('2d');
  const W = c.width, H = c.height;
  if (!W || !H) return { err: 'zero-sized backing store' };
  const seen = new Set();
  for (let i = 0; i < 40; i++) for (let j = 0; j < 40; j++) {
    const d = g.getImageData(Math.floor((i + .5) * W / 40), Math.floor((j + .5) * H / 40), 1, 1).data;
    seen.add((d[0] << 16) | (d[1] << 8) | d[2]);
  }
  return { w: W, h: H, colours: seen.size };
}
"""


def run(url, headed, report):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        # has_touch so CDP can dispatch real multi-touch at the pinch handler.
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=1, has_touch=True)
        page = ctx.new_page()
        page_errors, console_errors = [], []
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.add_init_script(PROBE)

        page.goto(url, wait_until="load", timeout=60000)
        page.wait_for_timeout(1500)

        boot_ok = page.evaluate("window.__BOOT_OK === true")
        boot_err = page.evaluate("window.__BOOT_ERR || null")
        report.check("boot() ran to completion", boot_ok, "" if boot_ok else "__BOOT_OK is not true")
        report.check("boot() threw nothing", boot_err is None, boot_err or "")
        report.check("no uncaught page errors", not page_errors, " | ".join(page_errors[:3]))
        report.check("no console errors", not console_errors, " | ".join(console_errors[:3]))

        t0 = page.evaluate("window.__ticks")
        page.evaluate(WRAP_RENDER)
        page.wait_for_timeout(600)
        ticks = page.evaluate("window.__ticks") - t0
        renders = page.evaluate("window.__renders")
        report.check("requestAnimationFrame is ticking", ticks >= 20, f"{ticks} ticks in 600ms")
        report.check("the render loop is painting", renders >= 20, f"{renders} renders in 600ms")
        # Deleting requestAnimationFrame(frame) outright still passes the check
        # above, because the worker heartbeat picks the work up at 61 Hz. That is
        # the fallback doing its job - and it is exactly the state the sibling
        # site was silently stuck in. Ask which clock is actually driving.
        report.check("the page's own rAF loop is live, not just the fallback clock",
                     page.evaluate("typeof rafIsLive === 'function' && rafIsLive()"),
                     f"lastRafAt was {page.evaluate('Math.round(performance.now() - lastRafAt)')}ms ago")
        report.check("the worker heartbeat exists as a fallback",
                     page.evaluate("typeof beat !== 'undefined' && beat !== null"))

        hit_id = page.evaluate("""() => {
          const st = document.getElementById('stage').getBoundingClientRect();
          const el = document.elementFromPoint(st.left + st.width / 2, st.top + st.height / 2);
          return el ? (el.id || el.tagName) : null;
        }""")
        report.check("stage centre hits the globe canvas", hit_id == "globe",
                     f"elementFromPoint -> {hit_id!r}")

        box = page.locator("#globe").bounding_box()
        report.check("globe canvas fills the stage",
                     box and box["width"] > 400 and box["height"] > 300,
                     f"{box['width']:.0f}x{box['height']:.0f}" if box else "no box")

        g = page.evaluate(CANVAS_STATS, "#globe")
        report.check("globe canvas has a real backing store", not g.get("err"), g.get("err", ""))
        if not g.get("err"):
            report.check("globe is drawn, not blank", g["colours"] >= 200,
                         f"{g['colours']} distinct colours in a 40x40 sample")
        c = page.evaluate(CANVAS_STATS, "#chroncv")
        if not c.get("err"):
            report.check("the record histogram is drawn", c["colours"] >= 8, f"{c['colours']} colours")
        r = page.evaluate(CANVAS_STATS, "#railcv")
        if not r.get("err"):
            report.check("the coverage rail is drawn", r["colours"] >= 5, f"{r['colours']} colours")

        # Read once and reuse. Escaped quotes inside an f-string expression are a
        # syntax error before Python 3.12, which turned this whole gate - the one
        # build.py runs as a build gate - into a SyntaxError on 3.10 and 3.11, and
        # build.py reports that as "the built page does not work".
        chips = page.evaluate("document.getElementById('themes').children.length")
        themes = page.evaluate("THEMES.length")
        report.check("theme chips rendered", chips == themes, f"{chips} chips")
        opts = page.evaluate("document.getElementById('lens').options.length")
        report.check("the language lens is populated", opts > 10, f"{opts} options")

        # ------------------------------------------------------- the corpus
        counts = page.evaluate("""() => {
          const r = q();
          return { total: NEV, showing: (r.n !== undefined ? r.n : r.events.length),
                   langs: LANGS.length, cats: DATA.categories.length };
        }""")
        report.check("corpus loaded", counts["total"] > 5000, json.dumps(counts))
        report.check("something is on screen at the default view", counts["showing"] > 20,
                     f"{counts['showing']} events showing")
        report.check("language masks present", counts["langs"] >= 16, f"{counts['langs']} editions")
        # The mask is `1 << i` over LANGS, so a 33rd edition would alias bit 0
        # and the lens would answer for the wrong language rather than fail.
        report.check("the coverage mask still fits 32 bits", counts["langs"] <= 32,
                     f"{counts['langs']} editions")

        # Each century band is named after the century it covers. `y/100 + 1`
        # named it after the next one, so the band over 1900-2000 read "2000s".
        ribbon = page.evaluate("""() => {
          const bad = [];
          for (const c of CENTURIES) {
            const y0 = Math.round(PRESENT - c.b), y1 = Math.round(PRESENT - c.e);
            if (c.n === '1st c.') { if (y0 !== 0 || y1 !== 100) bad.push(c.n); continue; }
            const m = /^(\\d+)00s( BCE)?$/.exec(c.n);
            if (!m) { bad.push(c.n); continue; }
            const want = m[2] ? -(+m[1]) * 100 : (+m[1]) * 100;
            if (y0 !== want) bad.push(`${c.n} covers ${y0}..${y1}`);
          }
          return bad;
        }""")
        report.check("the century ribbon names the century it covers",
                     not ribbon, "; ".join(ribbon[:3]) or f"{'all bands agree'}")

        # The coverage axis is the whole second dimension: dropping the floor
        # must actually reveal the long tail rather than doing nothing.
        cov = page.evaluate("""() => {
          const k0 = S.kt;
          const at = v => { setCoverage(v); invalidate();
            const r = q(); return r.n !== undefined ? r.n : r.events.length; };
          const hi = at(80), lo = at(1);
          setCoverage(k0); invalidate();
          return { hi, lo };
        }""")
        report.check("lowering the coverage floor reveals the tail",
                     cov["lo"] > cov["hi"] * 2, f"{cov['hi']} at 80+ languages -> {cov['lo']} at 1+")

        # A language lens must actually partition the record - but only down in
        # the tail. At the default floor of 40 editions every single event has an
        # English article, so testing there measures the corpus, not the lens.
        lens = page.evaluate("""() => {
          const l0 = S.lens, k0 = S.kt, w0 = { ...S.win };
          S.kt = 1; S.win = { t0: 0, t1: T_MAX };
          const at = v => { S.lens = v; invalidate();
            const r = q(); return r.n !== undefined ? r.n : r.events.length; };
          const all = at(''), only = at('only:en'), not_ = at('not:en');
          S.lens = l0; S.kt = k0; S.win = w0; invalidate();
          return { all, only, not: not_ };
        }""")
        report.check("the language lens partitions the record",
                     lens["only"] > 0 and lens["not"] > 0 and lens["only"] < lens["all"],
                     f"whole corpus {lens['all']}, on English {lens['only']}, "
                     f"not on English {lens['not']}")

        # ------------------------------------------------------- interaction
        lam0 = page.evaluate("S.rot.lam")
        r0 = page.evaluate("window.__renders")
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        for i in range(1, 13):
            page.mouse.move(cx + i * 16, cy)
            page.wait_for_timeout(8)
        page.mouse.up()
        page.wait_for_timeout(80)
        report.check("dragging rotates the globe", abs(page.evaluate("S.rot.lam") - lam0) > 5,
                     f"lam {lam0:.1f} -> {page.evaluate('S.rot.lam'):.1f}")
        report.check("dragging repaints", page.evaluate("window.__renders") - r0 >= 8,
                     f"{page.evaluate('window.__renders') - r0} renders during the drag")

        z0 = page.evaluate("ZOOMF")
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(120)
        report.check("wheel zooms", abs(page.evaluate("ZOOMF") - z0) > 0.01,
                     f"ZOOMF {z0:.2f} -> {page.evaluate('ZOOMF'):.2f}")

        # --------------------------------------------------------- pinch zoom
        cdp = ctx.new_cdp_session(page)

        def touch(kind, points):
            cdp.send("Input.dispatchTouchEvent", {
                "type": kind,
                "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(points)]})

        page.evaluate("setZoom(1.0); S.selection = null; invalidate();")
        page.wait_for_timeout(60)
        z0 = page.evaluate("ZOOMF")
        touch("touchStart", [(cx - 60, cy), (cx + 60, cy)])
        for d in (80, 110, 150, 190):
            touch("touchMove", [(cx - d, cy), (cx + d, cy)])
            page.wait_for_timeout(16)
        touch("touchEnd", [(cx + 190, cy)])
        touch("touchEnd", [])
        page.wait_for_timeout(120)
        z1 = page.evaluate("ZOOMF")
        report.check("two fingers zoom the globe", z1 > z0 * 1.5, f"ZOOMF {z0:.2f} -> {z1:.2f}")
        report.check("a pinch does not leave a stuck pointer",
                     page.evaluate("PTRS.size === 0 && pinch === null"),
                     f"PTRS.size={page.evaluate('PTRS.size')}")
        report.check("a pinch is not read as a click", page.evaluate("S.selection") is None,
                     f"selection={page.evaluate('S.selection')!r}")

        # A cancelled pinch must not strand the gesture. Android cancels a
        # stationary finger when long-press takes over; iOS cancels one on palm
        # rejection. pointercancel used to null the pinch and stop, leaving the
        # surviving finger with no drag origin and the grabbing cursor stuck on.
        touch("touchStart", [(cx - 60, cy), (cx + 60, cy)])
        touch("touchMove", [(cx - 120, cy), (cx + 120, cy)])
        page.wait_for_timeout(20)
        touch("touchCancel", [])
        page.wait_for_timeout(80)
        report.check("a cancelled pinch leaves no stranded state",
                     page.evaluate("PTRS.size === 0 && pinch === null && gDrag === null"),
                     f"PTRS.size={page.evaluate('PTRS.size')} "
                     f"gDrag={page.evaluate('gDrag !== null')}")
        report.check("a cancelled pinch releases the grabbing cursor",
                     not page.evaluate("document.getElementById('globe').classList.contains('dragging')"))

        # Back to a normal zoom, and pick the marker nearest the middle of the
        # canvas rather than whichever happened to be drawn first: the corner
        # overlays are real elements and a click landing on one never reaches
        # the globe at all.
        page.evaluate("setZoom(0.86); renderNow();")
        page.wait_for_timeout(150)
        picked = page.evaluate("""() => {
          let best = -1, bd = 1e18;
          for (let k = 0; k < HN; k++) {
            const dx = HX[k] - GW / 2, dy = HY[k] - GH / 2;
            const d = dx * dx + dy * dy;
            if (d < bd && HX[k] > 130 && HY[k] > 90 && HX[k] < GW - 130 && HY[k] < GH - 40) {
              bd = d; best = k;
            }
          }
          return best < 0 ? null : { id: EV[HI[best]].q, x: HX[best], y: HY[best] };
        }""")
        if report.check("markers have hit targets", picked is not None):
            page.mouse.click(box["x"] + picked["x"], box["y"] + picked["y"])
            page.wait_for_timeout(200)
            report.check("clicking a marker selects it", page.evaluate("S.selection") is not None,
                         f"selection={page.evaluate('S.selection')!r}")
            txt = page.evaluate("document.getElementById('detail').innerText || ''")
            report.check("the detail panel fills in", len(txt) > 40, f"{len(txt)} chars")

            # The tip is up to 250px wide and CSS centres it on the marker, so
            # writing the marker's x straight into `left` put half of it outside
            # .stage - which is overflow:hidden - for anything near an edge.
            # Drive it to the corners rather than trusting wherever the picked
            # marker happened to be - the marker above is deliberately chosen
            # near the middle, which is the one place this cannot fail.
            escaped = page.evaluate("""() => {
              const el = document.getElementById('tip');
              const stage = document.getElementById('stage');
              const out = [];
              for (const [x, y] of [[2, 2], [GW - 2, 2], [2, GH - 2], [GW - 2, GH - 2],
                                    [GW / 2, 4], [GW / 2, GH / 2]]) {
                showTip({ id: EV[0].q, x, y, n: 1 });
                const t = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
                if (t.left < s.left - 1 || t.right > s.right + 1 ||
                    t.top < s.top - 1 || t.bottom > s.bottom + 1)
                  out.push(`${Math.round(x)},${Math.round(y)} -> ` +
                           `[${Math.round(t.left)},${Math.round(t.top)},` +
                           `${Math.round(t.right)},${Math.round(t.bottom)}]`);
              }
              el.classList.remove('on');
              return out;
            }""")
            report.check("the tooltip stays inside the stage at every edge",
                         not escaped, "; ".join(escaped[:3]) or "all six anchors fit")

            # A tap is the only thing a phone can do to a marker, and it produced
            # nothing: the tip is driven by hover, which a finger never fires,
            # and the detail panel is 156px below the fold on a narrow layout
            # and does not move when the selection changes.
            page.evaluate("S.selection = null; document.getElementById('tip').classList.remove('on'); invalidate(); renderNow();")
            page.wait_for_timeout(80)
            tx, ty = box["x"] + picked["x"], box["y"] + picked["y"]
            touch("touchStart", [(tx, ty)])
            touch("touchEnd", [])
            page.wait_for_timeout(200)
            report.check("a tap on a marker answers with the tooltip",
                         page.evaluate("document.getElementById('tip').classList.contains('on')")
                         and page.evaluate("S.selection") is not None,
                         f"selection={page.evaluate('S.selection')!r}")

        # ------------------------------------------------------------ search
        if page.evaluate("!!document.getElementById('search')"):
            page.fill("#search", "Pompeii")
            page.wait_for_timeout(260)
            n = page.evaluate("document.getElementById('results').children.length")
            report.check("search returns results", n > 0, f"{n} hits for 'Pompeii'")
            if n:
                page.evaluate("document.getElementById('results').children[0].click()")
                page.wait_for_timeout(700)
                report.check("choosing a result selects it",
                             page.evaluate("S.selection") is not None,
                             f"selection={page.evaluate('S.selection')!r}")

        # -------------------------------------------------------- URL state
        if page.evaluate("typeof writeHash === 'function'"):
            page.evaluate("setCoverage(12); S.rot.lam = 123; S.rot.phi = -33; writeHash(true);")
            page.wait_for_timeout(120)
            h = page.evaluate("location.hash")
            report.check("URL hash carries the view", len(h) > 8, h[:90])
            # about:blank first, deliberately. Navigating to a URL that differs
            # only in its hash is a SAME-DOCUMENT navigation: the browser fires
            # hashchange and never reloads, so the page under test would be the
            # one already running and the check would pass without proving
            # anything. This is the flow a stranger opening a shared link gets.
            page.goto("about:blank")
            page.goto(url.split("#")[0] + h, wait_until="load", timeout=60000)
            page.wait_for_timeout(1500)
            back = page.evaluate("({kt: S.kt, lam: Math.round(S.rot.lam), phi: Math.round(S.rot.phi)})")
            report.check("a shared URL restores the view",
                         back["kt"] == 12 and abs(back["lam"] - 123) <= 1 and abs(back["phi"] + 33) <= 1,
                         json.dumps(back))
            report.check("no errors after restoring from a URL", not page_errors,
                         " | ".join(page_errors[:2]))


        # Object.prototype keys are truthy in a plain-object map, so #s=constructor
        # put a function into S.selection and #l=only:constructor emptied the globe
        # while the lens dropdown still read "Every edition".
        page.goto("about:blank")
        page.goto(url.split("#")[0] + "#s=constructor&l=only:constructor&th=toString",
                  wait_until="load", timeout=60000)
        page.wait_for_timeout(1200)
        report.check("a hostile hash cannot poison the view",
                     page.evaluate("S.selection") is None and page.evaluate("S.lens") == ""
                     and page.evaluate("S.themes.size") == 6
                     and page.evaluate("window.__BOOT_OK") is True,
                     f"selection={page.evaluate('S.selection')!r} lens={page.evaluate('S.lens')!r}")
        report.check("a hostile hash raises no errors", not page_errors, " | ".join(page_errors[:2]))

        browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()

    httpd = None
    if a.url:
        url = a.url
    else:
        if not os.path.exists(os.path.join(ROOT, "index.html")):
            sys.exit("FATAL: index.html not found - run tools/build.py first")
        httpd, base = serve(ROOT)
        url = base + "index.html"

    print(f"smoke test: {url}")
    report = Report()
    try:
        run(url, a.headed, report)
    finally:
        if httpd:
            httpd.shutdown()

    bad = report.failures
    print(f"\n{len(report.rows) - len(bad)}/{len(report.rows)} checks passed")
    if bad:
        print("\nFAILED:")
        for _, name, detail in bad:
            print(f"  {name}   {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
