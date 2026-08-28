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

        # The worker beat exists for the case rAF does not fire. While rAF is
        # healthy it used to keep posting at 60Hz anyway - 125 messages in two
        # seconds, every one a main-thread dispatch that reads a clock and
        # returns - and kept doing it past the two-minute idle cutoff meant to
        # stop it. It watches at 2Hz now and only runs the clock when it is one.
        if page.evaluate("beat !== null"):
            page.evaluate("window.__beats = 0; const p = beat.onmessage;"
                          " beat.onmessage = e => { window.__beats++; p(e); };")
            page.wait_for_timeout(1500)
            idle = page.evaluate("({beats: __beats, ms: beatMs, raf: rafIsLive()})")
            report.check("the beat stands down while rAF is healthy",
                         idle["raf"] and idle["ms"] > 100 and idle["beats"] < 20,
                         f"{idle['beats']} beats in 1.5s at {idle['ms']}ms")

            # ...and is still a real clock when rAF stops.
            page.evaluate("""() => {
              window.__realRaf = requestAnimationFrame;
              window.requestAnimationFrame = () => 0;
              lastInteraction = performance.now();
              S.spin.lam = 6; S.spin.phi = 0; needGlobe = true;
              window.__lam0 = S.rot.lam;
            }""")
            page.wait_for_timeout(1200)
            fb = page.evaluate("({ms: beatMs, raf: rafIsLive(),"
                               " moved: Math.abs(S.rot.lam - __lam0)})")
            page.evaluate("window.requestAnimationFrame = window.__realRaf;"
                          " S.spin.lam = 0; requestAnimationFrame(frame);")
            page.wait_for_timeout(300)
            report.check("the beat still drives animation when rAF stops",
                         not fb["raf"] and fb["ms"] <= 20 and fb["moved"] > 5,
                         f"{fb['moved']:.0f} degrees of spin at {fb['ms']}ms with rAF dead")

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

        # Where markers overlap, the one you can see is the one painted last -
        # both draw paths run back to front. Taking the nearest centre instead
        # selected the marker underneath in 1,938 of 1,954 overlapping cases.
        front = page.evaluate("""() => {
          S.cluster = false; S.kt = 25; invalidate(); drawEvents();
          let tested = 0, ok = 0;
          for (let a = 0; a < HN && tested < 300; a++)
            for (let b = a + 1; b < Math.min(HN, a + 60); b++) {
              const d = Math.hypot(HX[a] - HX[b], HY[a] - HY[b]);
              if (!(d > 0.5 && d < Math.min(HR[a], HR[b]) * 0.6)) continue;
              const mx = (HX[a] + HX[b]) / 2, my = (HY[a] + HY[b]) / 2;
              let want = -1;
              for (let k = HN - 1; k >= 0; k--) {
                const r = HR[k], ax = HX[k] - mx, ay = HY[k] - my;
                if (ax * ax + ay * ay < r * r) { want = k; break; }
              }
              const got = hitTest(mx, my);
              tested++;
              if (want >= 0 && got && got.i === HI[want]) ok++;
              if (tested >= 300) break;
            }
          return { tested, ok };
        }""")
        if front["tested"]:
            report.check("a click takes the marker on top, not the nearest",
                         front["ok"] == front["tested"],
                         f"{front['ok']}/{front['tested']} overlapping pairs")

        # pointerdown fires for every button, so a right-click used to be a
        # gesture: on the rail it set the coverage floor, measured jumping from
        # 40 to 3 while the context menu opened over the top.
        page.evaluate("setZoom(0.86); S.cluster = true; S.rot.lam = -10; S.spin.lam = 0; setCoverage(40); renderNow();")
        page.wait_for_timeout(80)
        lam0 = page.evaluate("S.rot.lam")
        kt0 = page.evaluate("S.kt")
        rb = page.evaluate("(() => { const r = document.getElementById('railcv')"
                           ".getBoundingClientRect(); return {x: r.left, y: r.top,"
                           " w: r.width, h: r.height}; })()")
        page.mouse.move(box["x"] + 200, box["y"] + 200)
        page.mouse.down(button="right")
        page.mouse.move(box["x"] + 320, box["y"] + 200, steps=5)
        page.mouse.up(button="right")
        page.mouse.move(rb["x"] + rb["w"] / 2, rb["y"] + rb["h"] * 0.8)
        page.mouse.down(button="right")
        page.mouse.up(button="right")
        page.wait_for_timeout(150)
        report.check("a secondary button drives nothing",
                     abs(page.evaluate("S.rot.lam") - lam0) < 1 and page.evaluate("S.kt") == kt0,
                     f"lam {lam0:.1f} -> {page.evaluate('S.rot.lam'):.1f}, "
                     f"floor {kt0} -> {page.evaluate('S.kt')}")
        # ...and the primary one still does.
        page.mouse.move(box["x"] + 200, box["y"] + 200)
        page.mouse.down()
        page.mouse.move(box["x"] + 320, box["y"] + 200, steps=5)
        page.mouse.up()
        page.wait_for_timeout(150)
        report.check("the primary button still drags", abs(page.evaluate("S.rot.lam") - lam0) > 1,
                     f"lam {lam0:.1f} -> {page.evaluate('S.rot.lam'):.1f}")

        # queryEvents reuses one index buffer and one events array across calls
        # instead of allocating 153 KB a query. Nothing may hold a result across
        # an invalidate(); this is the check that says so if something starts to.
        reuse = page.evaluate("""() => {
          const before = { kt: S.kt, t0: S.win.t0, t1: S.win.t1 };
          S.kt = 1; S.win.t0 = 0; S.win.t1 = T_MAX; invalidate();
          const a = q(), an = a.n, first = a.idx[0], ev0 = a.events[0];
          S.kt = 200; invalidate();
          const b = q();
          const shrank = b.n < an;
          S.kt = 1; invalidate();
          const c = q();
          const restored = c.n === an && c.idx[0] === first && c.events[0] === ev0;
          S.kt = before.kt; S.win.t0 = before.t0; S.win.t1 = before.t1; invalidate();
          return { shrank, restored, n: an };
        }""")
        report.check("re-querying the same state gives the same answer",
                     reuse["shrank"] and reuse["restored"],
                     f"{reuse['n']} events, unchanged across two intervening queries")

        # Four events in the corpus are carried by no Wikipedia edition anywhere,
        # and a floor of 1 excluded every one of them from every view the site
        # could produce - so the header advertised 38,242 events of which 38,238
        # were reachable. The floor goes to zero now, and "Show all" means all.
        allcov = page.evaluate("""() => {
          setWindow(0, T_MAX); S.themes = new Set(THEMES); S.lens = '';
          document.getElementById('btn-allcov').click();
          invalidate();
          const shown = q().n;
          let zero = 0;
          for (let i = 0; i < NEV; i++) if (EVSL[i] === 0) zero++;
          // and the survivor curve the rail draws has to agree with the query
          let disagree = 0;
          for (const k of [0, 1, 2, 3, 10, 40]) {
            setCoverage(k); invalidate();
            if (q().n !== survivorsAt(k)) disagree++;
          }
          setCoverage(0); invalidate();
          return { shown, total: NEV, zero, disagree, floor: S.kt };
        }""")
        report.check("\"Show all\" reaches every event in the corpus",
                     allcov["shown"] == allcov["total"] and allcov["floor"] == 0,
                     f"{allcov['shown']:,} of {allcov['total']:,}, "
                     f"{allcov['zero']} carried by no edition")
        report.check("the rail's survivor curve matches the query at every floor",
                     allcov["disagree"] == 0, f"{allcov['disagree']} floors disagree")

        # Choosing a search result opens whatever is hiding it. It could not open
        # a floor of 1 for an event with a coverage of 0: the result was selected,
        # flown to, and shown in the panel with nothing on the globe.
        reach = page.evaluate("""() => {
          setCoverage(40); invalidate();
          let i = -1;
          for (let k = 0; k < NEV; k++) if (EVSL[k] === 0) { i = k; break; }
          if (i < 0) return null;
          chooseEvent(i); TW = null; invalidate();
          return { name: EV[i].n, floor: S.kt, inQuery: q().events.includes(EV[i]),
                   selected: S.selection === EV[i].q };
        }""")
        if reach:
            report.check("choosing a result always opens what is hiding it",
                         reach["inQuery"] and reach["selected"],
                         f"{reach['name']!r} at floor {reach['floor']}")

        # The time axis is a focusable role="slider" and answered no key at all -
        # worse than not being focusable, because it advertises an affordance it
        # does not have. The rail beside it has handled six keys all along.
        kb = page.evaluate("""() => {
          const key = k => ccv.dispatchEvent(
            new KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
          const span = () => S.win.t1 - S.win.t0;
          const out = {};
          setWindow(500, 3500); drawChron(); const t1 = S.win.t1;
          key('ArrowRight'); drawChron(); out.right = S.win.t1 < t1;
          setWindow(500, 3500); drawChron(); const t1b = S.win.t1;
          key('ArrowLeft'); drawChron(); out.left = S.win.t1 > t1b;
          setWindow(0, 3200); drawChron(); const s0 = span();
          key('ArrowUp'); drawChron(); out.zoomIn = span() < s0;
          setWindow(0, 3200); drawChron(); const s1 = span();
          key('ArrowDown'); drawChron(); out.zoomOut = span() > s1;
          setWindow(0, 3200); key('Home'); out.home = S.win.t1 >= T_MAX * 0.99;
          setWindow(0, 3200); key('End'); out.end = S.win.t1 < 200;
          setWindow(0, 3200); drawChron();
          return out;
        }""")
        report.check("the time axis answers the keyboard",
                     all(kb.values()),
                     ", ".join(k for k, v in kb.items() if not v) or
                     "pan, zoom, Home and End all respond")

        # aria-valuenow alone is a bare number in a unit nothing on screen uses.
        vt = page.evaluate("""() => {
          setCoverage(40); setWindow(0, 3200); invalidate(); renderNow();
          return { rail: rcv.getAttribute('aria-valuetext'),
                   chron: ccv.getAttribute('aria-valuetext') };
        }""")
        report.check("both sliders announce their value in words",
                     bool(vt["rail"]) and bool(vt["chron"]) and
                     any(c.isalpha() for c in vt["rail"] or "") and
                     any(c.isalpha() for c in vt["chron"] or ""),
                     f"rail {vt['rail']!r}, axis {vt['chron']!r}")

        # The label placer avoids other labels and the canvas edges. It knew
        # nothing about the two panels drawn on top of the globe, so it put names
        # under them - 28 across 36 rotations at the default view, "Saint
        # Petersburg" and "Great Wall of China" among them.
        lab = page.evaluate("""() => {
          const real = gx.fillText.bind(gx);
          const seen = [];
          gx.fillText = function (t, x, y) { seen.push({t: String(t), x, y, f: gx.font}); return real(t, x, y); };
          const base = gcv.getBoundingClientRect();
          const rects = ['.stage-tl', '.stage-tr'].map(sel => {
            const el = document.querySelector(sel); if (!el) return null;
            const r = el.getBoundingClientRect();
            return {l: r.left - base.left, t: r.top - base.top,
                    r: r.right - base.left, b: r.bottom - base.top};
          }).filter(Boolean);
          setCoverage(40); setWindow(0, 3200); S.cluster = true;
          let over = 0, drawn = 0, first = null;
          for (let lam = -180; lam < 180; lam += 45) for (const phi of [-40, 0, 40]) {
            S.rot.lam = lam; S.rot.phi = phi; invalidate(); needGlobe = true;
            seen.length = 0; renderNow();
            for (const s of seen) {
              if (!/xt-cond/.test(s.f) || /600 9px/.test(s.f)) continue;
              drawn++;
              const w = gx.measureText(s.t).width;
              const box = {l: s.x - 2, t: s.y - 10, r: s.x + w + 2, b: s.y + 3};
              for (const o of rects)
                if (box.l < o.r && box.r > o.l && box.t < o.b && box.b > o.t) {
                  over++; if (!first) first = s.t;
                }
            }
          }
          gx.fillText = real;
          S.rot.lam = -10; S.rot.phi = 25; invalidate(); needGlobe = true; renderNow();
          return {over, drawn, first};
        }""")
        # `drawn` guards the assertion: zero overlaps because nothing was drawn
        # is not a pass, and that is exactly what a throw inside drawEvents looks
        # like from out here.
        report.check("no globe label is drawn under the stage overlays",
                     lab["over"] == 0 and lab["drawn"] > 100,
                     f"{lab['drawn']} labels drawn, {lab['over']} under an overlay"
                     + (f" (e.g. {lab['first']!r})" if lab["first"] else ""))

        # The tick ladder is 1, 2, 5 times a power of ten - right for a window
        # spanning orders of magnitude, and empty for a narrow one containing
        # none of its rungs. [74,000, 75,000] and [11,990, 12,010] each drew a
        # time axis with no labels at all. And once labelled, one decimal was
        # not enough to tell 12,000 from 12,005: two ticks, one text.
        ticks = page.evaluate("""() => {
          const real = cx2.fillText.bind(cx2);
          const seen = [];
          cx2.fillText = function (t, x, y) { seen.push({t: String(t), f: cx2.font}); return real(t, x, y); };
          const blank = [], dup = [];
          for (const [a, b] of [[0, 20], [0, 130], [0, 3200], [0, 12000], [0, T_MAX],
                                [74000, 75000], [11990, 12010], [500, 560],
                                [30000, 31000], [2000, 2400], [6000, 6020]]) {
            setWindow(a, b); invalidate(); seen.length = 0; drawChron();
            const lab = seen.filter(s => /xt-mono/.test(s.f) && /9\.5px/.test(s.f)).map(s => s.t);
            if (!lab.length) blank.push(`${a}-${b}`);
            if (new Set(lab).size !== lab.length) dup.push(`${a}-${b}: ${lab.join(' ')}`);
          }
          cx2.fillText = real;
          setWindow(0, 3200); invalidate();
          return {blank, dup};
        }""")
        report.check("every window labels its time axis",
                     not ticks["blank"],
                     ("blank at " + ", ".join(ticks["blank"])) if ticks["blank"] else "all labelled")
        report.check("no two ticks carry the same label",
                     not ticks["dup"], "; ".join(ticks["dup"][:2]) or "all distinct")

        # The bar and the number above it measure different things: e.sl counts
        # every Wikipedia edition, the bar and the codes are over the top 32. The
        # Pyramid of Menkaure read "45 language editions" over a bar at 100%.
        bar = page.evaluate("""() => {
          setCoverage(0); setWindow(0, T_MAX); invalidate();
          let best = 0;
          for (let i = 0; i < NEV; i++) if (EVSL[i] > EVSL[best]) best = i;
          S.selection = EV[best].q; renderDetail();
          const note = document.querySelector('#detail .barnote');
          const num = document.querySelector('#detail .sect .num');
          const one = (() => { for (let i = 0; i < NEV; i++) if (EVSL[i] === 1) return i; return -1; })();
          let singular = null;
          if (one >= 0) {
            S.selection = EV[one].q; renderDetail();
            singular = (document.querySelector('#detail .sect .num') || {}).textContent;
          }
          S.selection = null; renderDetail();
          return { note: note && note.textContent.trim(),
                   num: num && num.textContent.trim(), singular: singular && singular.trim() };
        }""")
        report.check("the coverage bar says what it is a fraction of",
                     bool(bar["note"]) and "of the" in (bar["note"] or ""),
                     f"{bar['num']!r} over {bar['note']!r}")
        if bar["singular"]:
            report.check("a single edition is not \"1 language editions\"",
                         "1 language editions" not in bar["singular"], repr(bar["singular"]))

        # pointermove fires per pixel. The tip rebuilt its innerHTML and
        # re-measured its width on every one - a DOM parse and a forced layout
        # sixty times a second for a tip whose text never changed - and the drag
        # branch read the canvas box it never uses.
        churn = page.evaluate("""() => {
          let rects = 0, writes = 0, measures = 0;
          const realRect = Element.prototype.getBoundingClientRect;
          Element.prototype.getBoundingClientRect = function () { rects++; return realRect.call(this); };
          const tip = document.getElementById('tip');
          const ih = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
          Object.defineProperty(tip, 'innerHTML', {
            set(v) { writes++; ih.set.call(this, v); }, get() { return ih.get.call(this); },
            configurable: true });
          const ow = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
          Object.defineProperty(tip, 'offsetWidth',
            { get() { measures++; return ow.get.call(this); }, configurable: true });

          let k = -1;
          for (let i = 0; i < HN; i++) if (HR[i] > 10) { k = i; break; }
          const out = { found: k >= 0 };
          if (k >= 0) {
            const box = realRect.call(gcv);
            writes = 0; measures = 0;
            for (let i = 0; i < 30; i++)
              gcv.dispatchEvent(new PointerEvent('pointermove', {
                clientX: box.left + HX[k] + (i % 3) - 1, clientY: box.top + HY[k] + ((i >> 1) % 3) - 1,
                bubbles: true, pointerId: 1, pointerType: 'mouse' }));
            out.hoverWrites = writes; out.hoverMeasures = measures;
          }
          rects = 0;
          gcv.dispatchEvent(new PointerEvent('pointerdown', {clientX: 600, clientY: 400,
            bubbles: true, pointerId: 2, pointerType: 'mouse', isPrimary: true, button: 0}));
          for (let i = 0; i < 30; i++)
            gcv.dispatchEvent(new PointerEvent('pointermove',
              {clientX: 600 + i, clientY: 400, bubbles: true, pointerId: 2, pointerType: 'mouse'}));
          gcv.dispatchEvent(new PointerEvent('pointerup', {clientX: 630, clientY: 400,
            bubbles: true, pointerId: 2, pointerType: 'mouse'}));
          out.dragRects = rects;
          Element.prototype.getBoundingClientRect = realRect;
          delete tip.innerHTML; delete tip.offsetWidth;
          S.spin.lam = 0; S.spin.phi = 0;
          return out;
        }""")
        if churn.get("found"):
            report.check("holding still over one marker does not rebuild the tip",
                         churn["hoverWrites"] <= 2 and churn["hoverMeasures"] <= 2,
                         f"{churn['hoverWrites']} rebuilds and "
                         f"{churn['hoverMeasures']} measures across 30 moves")
        report.check("dragging forces no layout it does not use",
                     churn["dragRects"] == 0,
                     f"{churn['dragRects']} getBoundingClientRect across 30 drag moves")

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

        # Zoom-to-cursor holds until the requested span drops under the 20-year
        # floor. setWindow then rebuilt the window as [t0, t0 + 20] - keeping
        # the left edge and letting the right one run - so every further scroll
        # panned instead of doing nothing: 68 years of drift over 52 steps.
        floor = page.evaluate("""() => {
          setWindow(0, 3200); drawChron();
          const ax = CW * 0.5, wins = [];
          for (let i = 0; i < 80; i++) {
            const s = SCALE || chronScale(), tp = Math.max(0, s.t(ax));
            const k = Math.max((S.win.t1 - S.win.t0) / 46, 1e-9);
            const up = Math.asinh(tp / k), u0 = Math.asinh(S.win.t0 / k),
                  u1 = Math.asinh(S.win.t1 / k);
            setWindow(Math.max(0, k * Math.sinh(up + (u0 - up) * 0.862)),
                      Math.min(T_MAX, k * Math.sinh(up + (u1 - up) * 0.862)));
            drawChron();
            wins.push([S.win.t0, S.win.t1]);
          }
          const at = wins.filter(w => Math.abs(w[1] - w[0] - MIN_SPAN) < 1e-6);
          return { n: at.length,
                   slide: at.length < 2 ? 0 : Math.abs(at[at.length - 1][0] - at[0][0]) };
        }""")
        report.check("zooming past the floor does not pan the window",
                     floor["n"] > 5 and floor["slide"] < 8,
                     f"{floor['slide']:.1f} years over {floor['n']} steps at the floor")
        page.evaluate("setWindow(0, 3200);")

        # One walk keeps the top ten and counts every match; the total has to be
        # the real one, not an estimate, because the UI prints it.
        srch = page.evaluate("""() => {
          const out = {};
          for (const s of ['an', 'the', 'york']) {
            const hits = searchEvents(s, 10);
            let brute = 0;
            for (let i = 0; i < NEV; i++) if (NAME_LC[i].indexOf(s) >= 0) brute++;
            out[s] = { total: SEARCH_TOTAL, brute, top: hits.length ? EV[hits[0].i].n : null,
                       ordered: hits.every((h, k) => k === 0 ||
                         hits[k - 1].rank > h.rank ||
                         (hits[k - 1].rank === h.rank && hits[k - 1].sl >= h.sl)) };
          }
          return out;
        }""")
        report.check("search counts every match exactly",
                     all(v["total"] == v["brute"] for v in srch.values()),
                     ", ".join(f"{k} {v['total']}/{v['brute']}" for k, v in srch.items()))
        report.check("search ranks prefix over word-start over coverage",
                     all(v["ordered"] for v in srch.values()) and srch["york"]["top"] == "York",
                     f"top hit for 'york' is {srch['york']['top']!r}")

        # Language codes and theme keys come from the corpus, which comes from
        # Wikidata, and they used to go into innerHTML raw. A dbname is [a-z0-9_]
        # in practice, so this was never exploitable - but it is a third party's
        # data in a file where every other interpolation is escaped, and a code
        # of `x"><img ...>` put a live element into the lens and the panel.
        inject = page.evaluate("""() => {
          const PAY = 'x"><img src=x onerror="window.__XSS=1">';
          const out = {};
          const l0 = LANGS[0]; LANGS[0] = PAY; LANG_BIT[PAY] = LANG_BIT[l0];
          const sel = document.getElementById('lens');
          sel.dataset.built = ''; renderLens();
          const keep = S.selection;
          S.selection = EV[0].q; renderDetail();
          out.lang = !!document.querySelector('#lens img, #detail img');
          LANGS[0] = l0; delete LANG_BIT[PAY]; sel.dataset.built = ''; renderLens();
          const t0 = THEMES[0]; THEMES[0] = PAY; S.themes.add(PAY); CSSV[PAY] = '#fff';
          renderThemes();
          out.theme = !!document.querySelector('#themes img');
          THEMES[0] = t0; S.themes.delete(PAY); renderThemes();
          const n0 = EV[0].n; EV[0].n = PAY; S.selection = EV[0].q; renderDetail();
          out.name = !!document.querySelector('#detail img');
          EV[0].n = n0; S.selection = keep; invalidate(); renderDetail();
          out.flag = !!window.__XSS;
          return out;
        }""")
        report.check("corpus strings cannot inject markup",
                     not any(inject.values()),
                     ", ".join(f"{k} leaked" for k, v in inject.items() if v) or
                     "lens, themes, names and the panel all escape")

        # A render that throws is caught so the loop survives it, and the canvas
        # keeps its last good frame - so from out here nothing changes. Injecting
        # a failure into drawEvents mid-session escaped nothing to window.onerror,
        # left __BOOT_OK true, and left 1,997 distinct colours on the globe. The
        # page counts render failures now; this is the check that reads the count.
        live = page.evaluate("""() => {
          let seed = 999;
          const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
          const pick = a => a[(rnd() * a.length) | 0];
          const colours = () => {
            const c = document.createElement('canvas'); c.width = 80; c.height = 80;
            const x = c.getContext('2d', {willReadFrequently: true});
            x.drawImage(gcv, 0, 0, gcv.width, gcv.height, 0, 0, 80, 80);
            const d = x.getImageData(0, 0, 80, 80).data, s = new Set();
            for (let i = 0; i < d.length; i += 4) s.add((d[i] << 16) | (d[i+1] << 8) | d[i+2]);
            return s.size;
          };
          const before = window.__RENDER_ERRS;
          const acts = [
            () => { S.rot.lam += rnd() * 120 - 60; needGlobe = true; },
            () => setZoom(ZMIN + rnd() * (ZMAX - ZMIN)),
            () => setCoverage((rnd() * 300) | 0),
            () => setWindow(0, 20 + rnd() * (T_MAX - 20)),
            () => { S.cluster = !S.cluster; needGlobe = true; },
            () => { S.basemap = S.basemap === 'chart' ? 'satellite' : 'chart';
                    SURF.key = ''; needGlobe = true; },
            () => { S.showPlates = !S.showPlates; needGlobe = true; },
            () => { S.lens = pick(['', 'not:en', 'only:zh']); },
          ];
          let minCol = Infinity;
          for (let i = 0; i < 120; i++) {
            pick(acts)(); invalidate(); needGlobe = true; renderNow();
            if (i % 10 === 0) minCol = Math.min(minCol, colours());
          }
          S.basemap = 'satellite'; setZoom(0.86); setCoverage(40);
          setWindow(0, 3200); S.lens = ''; S.cluster = true; S.showPlates = false;
          invalidate(); needGlobe = true; renderNow();
          return { errs: window.__RENDER_ERRS - before, minCol,
                   first: window.__RENDER_ERR };
        }""")
        report.check("120 view states render without a caught failure",
                     live["errs"] == 0,
                     f"{live['errs']} render failures"
                     + (f": {str(live['first'])[:70]}" if live["first"] else ""))
        report.check("the globe stays drawn across every view state",
                     live["minCol"] > 40, f"fewest colours seen: {live['minCol']}")

        # Text drawn over the stage must not follow the theme's ink: the stage
        # gradient is near-black in both themes, and in light mode --chalk-dim
        # measured 2.53:1 against it, on the line explaining the coverage axis.
        contrast = page.evaluate("""() => {
          const root = document.documentElement;
          const had = root.getAttribute('data-theme');
          root.setAttribute('data-theme', 'light');
          const px = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
          const lum = v => { const a = v.map(x => { x /= 255;
            return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
            return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]; };
          const bg = [10, 18, 32];                       // the stage gradient's light end
          const out = {};
          for (const sel of ['#hd-sub', '.stage-tl .headline']) {
            const el = document.querySelector(sel);
            if (!el) continue;
            const L1 = lum(px(getComputedStyle(el).color)), L2 = lum(bg);
            out[sel] = +(((Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05))).toFixed(2);
          }
          if (had) root.setAttribute('data-theme', had); else root.removeAttribute('data-theme');
          readPalette(); SURF.key = ''; markAll(); renderNow();
          return out;
        }""")
        worst = min(contrast.values()) if contrast else 0
        report.check("stage overlay text clears AA in light mode", worst >= 4.5,
                     ", ".join(f"{k} {v}:1" for k, v in contrast.items()))

        # :focus-visible paints outside the border box, #globe fills .stage and
        # .stage is overflow:hidden - so the ring was clipped away entirely, on a
        # role="application" element that takes arrow keys.
        # :focus-visible only matches keyboard-initiated focus, so the resolved
        # style of a scripted focus() says nothing. Read the rule itself.
        ring = page.evaluate("""() => {
          let offset = null;
          for (const sheet of document.styleSheets) {
            let rules; try { rules = sheet.cssRules; } catch (_) { continue; }
            for (const r of rules)
              if (r.selectorText && /#globe:focus-visible/.test(r.selectorText))
                offset = r.style.outlineOffset;
          }
          return {offset, clipped:
            getComputedStyle(document.getElementById('stage')).overflow === 'hidden' &&
            gcv.clientWidth >= document.getElementById('stage').clientWidth};
        }""")
        report.check("the globe's focus ring is drawn inside the canvas",
                     not ring["clipped"] or
                     (ring["offset"] and parseable_negative(ring["offset"])),
                     f"#globe:focus-visible outline-offset {ring['offset']!r}"
                     f" in an overflow:hidden stage")

        # ------------------------------------------------------- the fuzz
        # A deterministic random walk over every control there is, checking the
        # invariants after every 25 steps. This is what found the unguarded
        # setPointerCapture on the rail and the time axis: it throws for a
        # pointer that is not active, the call sat above the assignment, and the
        # handler died before rDrag or cDrag was ever set - so the gesture did
        # not happen and an uncaught error landed on the page. Seeded, so a
        # failure is reproducible.
        page_errors.clear()
        fuzz = page.evaluate("""() => {
          let seed = 12345;
          const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
          const pick = a => a[(rnd() * a.length) | 0];
          const box = gcv.getBoundingClientRect();
          const rb = rcv.getBoundingClientRect(), cb = ccv.getBoundingClientRect();
          const ptr = (el, kind, x, y, id) => el.dispatchEvent(new PointerEvent(kind,
            {clientX: x, clientY: y, bubbles: true, pointerId: id, pointerType: 'mouse',
             isPrimary: true, button: 0}));
          const key = (el, k) => el.dispatchEvent(
            new KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
          const bad = [];
          const check = what => {
            const p = [];
            for (const v of [S.kt, S.win.t0, S.win.t1, S.rot.lam, S.rot.phi, ZOOMF, GR, GW, GH])
              if (!isFinite(v)) p.push('non-finite');
            if (!(S.kt >= 0 && S.kt <= MAX_SL)) p.push('kt ' + S.kt);
            if (!(S.win.t0 >= 0 && S.win.t1 <= T_MAX && S.win.t1 > S.win.t0))
              p.push('window ' + S.win.t0 + '..' + S.win.t1);
            if (!(ZOOMF >= ZMIN && ZOOMF <= ZMAX)) p.push('zoom ' + ZOOMF);
            if (!(S.rot.phi >= -89 && S.rot.phi <= 89)) p.push('phi ' + S.rot.phi);
            if (!S.themes.size) p.push('no themes');
            if (S.selection !== null &&
                !Object.prototype.hasOwnProperty.call(BY_Q, S.selection)) p.push('bad selection');
            if (PTRS.size > 3) p.push('leaked pointers ' + PTRS.size);
            const F = q();
            if (F.idx.length !== F.n || F.events.length !== F.n) p.push('query inconsistent');
            if (p.length) bad.push(what + ': ' + p.join(', '));
          };
          const acts = [
            () => { const x = box.left + rnd() * box.width, y = box.top + rnd() * box.height;
                    ptr(gcv, 'pointerdown', x, y, 1);
                    for (let i = 0; i < 3; i++) ptr(gcv, 'pointermove', x + rnd() * 60 - 30, y, 1);
                    ptr(gcv, 'pointerup', x, y, 1); },
            () => ptr(gcv, 'pointermove', box.left + rnd() * box.width, box.top + rnd() * box.height, 9),
            () => gcv.dispatchEvent(new WheelEvent('wheel',
                    {deltaY: rnd() > 0.5 ? 120 : -120, bubbles: true, cancelable: true})),
            () => { const y = rb.top + rnd() * rb.height;
                    ptr(rcv, 'pointerdown', rb.left + 10, y, 2);
                    ptr(rcv, 'pointermove', rb.left + 10, y + rnd() * 40 - 20, 2);
                    ptr(rcv, 'pointerup', rb.left + 10, y, 2); },
            () => { const x = cb.left + rnd() * cb.width;
                    ptr(ccv, 'pointerdown', x, cb.top + 10, 3);
                    ptr(ccv, 'pointermove', x + rnd() * 120 - 60, cb.top + 10, 3);
                    ptr(ccv, 'pointerup', x, cb.top + 10, 3); },
            () => ccv.dispatchEvent(new WheelEvent('wheel',
                    {deltaY: rnd() > 0.5 ? 120 : -120, bubbles: true, cancelable: true})),
            () => key(ccv, pick(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'])),
            () => key(rcv, pick(['ArrowUp', 'ArrowDown', 'Home', 'End'])),
            () => key(gcv, pick(['ArrowLeft', 'ArrowRight', '+', '-', 'Escape'])),
            () => pick(['btn-cluster', 'btn-basemap', 'btn-plates', 'btn-allcov'])
                    && document.getElementById(pick(['btn-cluster', 'btn-basemap',
                         'btn-plates', 'btn-allcov'])).click(),
            () => pick([...document.querySelectorAll('#presets button')]).click(),
            () => { const c = pick([...document.querySelectorAll('#themes .theme')]); if (c) c.click(); },
            () => { const sel = document.getElementById('lens');
                    sel.value = pick([...sel.options]).value;
                    sel.dispatchEvent(new Event('change', {bubbles: true})); },
            () => chooseEvent((rnd() * NEV) | 0),
            () => setSelection(rnd() > 0.5 ? EV[(rnd() * NEV) | 0].q : null),
          ];
          for (let i = 0; i < 600; i++) {
            try { pick(acts)(); } catch (e) { bad.push('step ' + i + ' threw: ' + e); }
            if (i % 25 === 0) {
              try { renderNow(); } catch (e) { bad.push('render threw: ' + e); }
              check('step ' + i);
            }
          }
          renderNow(); check('final');
          return {steps: 600, bad: bad.slice(0, 4), count: bad.length};
        }""")
        report.check("600 random interactions break no invariant",
                     fuzz["count"] == 0, "; ".join(fuzz["bad"]) or "state stayed valid throughout")
        report.check("600 random interactions raise no uncaught error",
                     not page_errors, " | ".join(page_errors[:2]))

        # reset to something sane for the checks that follow
        page.evaluate("location.hash = ''; readHash(); syncControls(); applyZoom(); changed(); renderNow();")
        page.wait_for_timeout(200)
        page_errors.clear()

        # A finger's first instinct on a narrow layout is to swipe up and read on.
        # All three canvases took touch-action:none, so a 250px upward swipe took
        # the latitude from 12 to -89 with scrollY still 0 - the top of the first
        # screen refused to scroll and rewrote the view instead. Two halves: the
        # stylesheet hands vertical gestures back to the browser under a coarse
        # pointer, and the handler stays out of the way while a gesture still
        # looks vertical, because the moves before the browser decides still
        # arrive here. This context has no touch emulation, so the gesture is
        # driven straight at the handler with the pointerType it keys on.
        rule = page.evaluate("""() => {
          for (const sheet of document.styleSheets) {
            let rules; try { rules = sheet.cssRules; } catch (_) { continue; }
            for (const r of rules) {
              if (r.media && /coarse/.test(r.conditionText || r.media.mediaText))
                for (const inner of r.cssRules || [])
                  if (/#globe/.test(inner.selectorText || ''))
                    return {sel: inner.selectorText, touchAction: inner.style.touchAction};
            }
          }
          return null;
        }""")
        report.check("a coarse pointer gets the page's vertical gestures back",
                     bool(rule) and rule["touchAction"] == "pan-y",
                     f"{rule['sel']} -> touch-action: {rule['touchAction']}" if rule
                     else "no coarse-pointer rule for #globe")

        drag = page.evaluate("""() => {
          const box = gcv.getBoundingClientRect();
          const go = (path, type) => {
            S.rot.phi = 12; S.rot.lam = -10; S.spin.lam = 0; S.spin.phi = 0;
            gcv.dispatchEvent(new PointerEvent('pointerdown', {clientX: box.left + path[0][0],
              clientY: box.top + path[0][1], bubbles: true, pointerId: 40,
              pointerType: type, isPrimary: true, button: 0}));
            for (const [x, y] of path.slice(1))
              gcv.dispatchEvent(new PointerEvent('pointermove', {clientX: box.left + x,
                clientY: box.top + y, bubbles: true, pointerId: 40, pointerType: type}));
            gcv.dispatchEvent(new PointerEvent('pointerup', {clientX: box.left + path[path.length-1][0],
              clientY: box.top + path[path.length-1][1], bubbles: true, pointerId: 40,
              pointerType: type}));
            S.spin.lam = 0; S.spin.phi = 0;
            return {phi: S.rot.phi, lam: S.rot.lam};
          };
          const down = [[200,120],[200,150],[200,180],[200,210],[200,240],[200,270]];
          const across = [[120,200],[160,200],[200,200],[240,200],[280,200],[320,200]];
          return {touchVertical: go(down, 'touch'), touchHorizontal: go(across, 'touch'),
                  mouseVertical: go(down, 'mouse')};
        }""")
        tv, th, mv = drag["touchVertical"], drag["touchHorizontal"], drag["mouseVertical"]
        report.check("a vertical swipe leaves the globe where it was",
                     abs(tv["phi"] - 12) < 0.5 and abs(tv["lam"] + 10) < 0.5,
                     f"latitude 12 -> {tv['phi']:.1f}, longitude -10 -> {tv['lam']:.1f}")
        report.check("a horizontal drag still turns the globe",
                     abs(th["lam"] + 10) > 3,
                     f"longitude -10 -> {th['lam']:.1f}")
        report.check("a mouse drag is unaffected by the touch guard",
                     abs(mv["phi"] - 12) > 3,
                     f"latitude 12 -> {mv['phi']:.1f}")

        # Flying to a search result while the stage is scrolled out of view
        # animates the camera where nobody can see it.
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(500)
        page.evaluate("window.scrollTo(0, 500);")
        page.wait_for_timeout(200)
        scrolled = page.evaluate("Math.round(document.getElementById('stage').getBoundingClientRect().top)")
        page.evaluate("chooseEvent(0)")
        page.wait_for_timeout(900)
        back = page.evaluate("({top: Math.round(document.getElementById('stage')"
                             ".getBoundingClientRect().top), sel: S.selection})")
        report.check("choosing a result brings the globe into view first",
                     scrolled < -50 and back["top"] > -8 and back["sel"] is not None,
                     f"stage top {scrolled}px before, {back['top']}px after")

        page.set_viewport_size({"width": 1280, "height": 800})
        page.wait_for_timeout(400)
        page.evaluate("location.hash=''; readHash(); syncControls(); applyZoom(); changed(); renderNow();")
        page.wait_for_timeout(200)
        page_errors.clear()

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


# The artifact variant, wrapped the way a host wraps it.
#
# build.py emits two documents and this gate only ever loaded one. artifact.html
# is the body-only form - the one that actually gets published - and it differs
# from index.html in exactly the place a boot failure hides: build.py strips the
# meta tags out of its head with a regex, and nothing checked what was left. The
# note in the README about the sibling site losing a whole build to a boot
# failure nothing detected is about precisely this shape of gap, and it was open
# on one of the two outputs.
#
# The wrapper is written beside the built files rather than into them, and it is
# gitignored; --artifact builds it and tests that instead of index.html.
ARTIFACT_WRAPPER = "artifact-wrapped.html"


def wrap_artifact():
    src = os.path.join(ROOT, "artifact.html")
    if not os.path.exists(src):
        sys.exit("FATAL: artifact.html not found - run tools/build.py first")
    with open(src, encoding="utf-8") as f:
        body = f.read()
    out = os.path.join(ROOT, ARTIFACT_WRAPPER)
    with open(out, "w", encoding="utf-8") as f:
        f.write('<!doctype html>\n<html lang="en">\n<head>\n'
                '<meta charset="utf-8" />\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
                '</head>\n<body>\n' + body + '\n</body>\n</html>\n')
    return ARTIFACT_WRAPPER


def parseable_negative(css_len):
    """True when a CSS length string is a negative number of pixels."""
    try:
        return float(str(css_len).replace("px", "").strip()) < 0
    except ValueError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--artifact", action="store_true",
                    help="test artifact.html wrapped in a host document, not index.html")
    a = ap.parse_args()

    httpd = None
    if a.url:
        url = a.url
    elif a.artifact:
        page = wrap_artifact()
        httpd, base = serve(ROOT)
        url = base + page
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
