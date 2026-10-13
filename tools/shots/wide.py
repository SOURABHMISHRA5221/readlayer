"""Wide layout (decision 45) on the local harness: library, profile and reader at 1024, 1280,
1440, 1920 and 390, light and dark. Screenshots, axe at every impact level, horizontal scroll,
and the layout numbers the plan's acceptance names (docs/plans/wide-layout.md). Emulators only.

    SHOTS_OUT=/tmp/wide-before uv run --project apps/api python tools/shots/wide.py --before
    SHOTS_OUT=/tmp/wide uv run --project apps/api python tools/shots/wide.py

`--before` records the same shots and numbers without asserting (run on the code before the
change); `--narrow` keeps only the tablet and phone sweeps. Without `--before`, any failed check
or any 429 exits non-zero. Sizes and themes change in place; a page is loaded once for the
desktop sizes, once for the tablet ones (768, 900, 960; light) and once at 390.
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

W = "http://localhost:5173"
DESKTOP = (1024, 1280, 1440, 1920)
TABLET = (768, 900, 960)  # stacked layouts; 960 is half of a 1920 screen
PHONE = 390
BEFORE = "--before" in sys.argv
NARROW_ONLY = "--narrow" in sys.argv  # tablet and phone sweeps only (used for the before run)
TOPICS = ["economics", "finance", "business", "policy", "technology", "science"]

# Installed before the app's code on every load: counts 429s and sums layout shifts.
INIT_JS = """window.__rl429 = 0; window.__cls = 0;
(() => { const f = window.fetch; window.fetch = async (...a) => { const r = await f(...a); if (r.status === 429) window.__rl429++; return r; };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })
    .observe({ type: 'layout-shift', buffered: true }); } catch (e) {} })();"""

AXE_ALL = ("axe.run(document, {resultTypes: ['violations']}).then(r => r.violations"
           ".map(v => v.impact + ':' + v.id + ':' + v.nodes.length))")

HELPERS = """const q = (s) => document.querySelector(s); const all = (s) => [...document.querySelectorAll(s)];
const r = (e) => (e ? e.getBoundingClientRect() : null); const n = (x) => Math.round(x * 10) / 10;
const hit = (a, b) => !!a && !!b && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
const inner = (e) => { if (!e) return null; const b = r(e), c = getComputedStyle(e);
  return [n(b.left + parseFloat(c.paddingLeft)), n(b.right - parseFloat(c.paddingRight))]; };
const small = (sel) => all(sel).filter((e) => [...e.childNodes].some((t) => t.nodeType === 3 && t.textContent.trim())
  && e.getClientRects().length && parseFloat(getComputedStyle(e).fontSize) < 13)
  .map((e) => (e.getAttribute('class') || e.tagName) + ':' + getComputedStyle(e).fontSize);"""

LIBRARY_JS = "(() => {" + HELPERS + """
  const main = r(q('.feedmain')), side = r(q('.side'));
  const row = q('.row:not(.row--skeleton)'), thumb = row && row.querySelector('.row__thumb:not([hidden])');
  const stacked = !!main && !!side && side.top >= main.bottom - 1;
  return { vw: document.documentElement.clientWidth, stacked,
    content: main && side ? n((stacked ? main.right : side.right) - main.left) : null,
    row: row ? n(r(row).width) : null, thumb: thumb ? n(r(thumb).width) : 0,
    rowText: row ? n(r(row.querySelector('.row__body')).width) : null,
    bar: inner(q('.topbar__inner')), page: main && side ? [n(main.left), n(stacked ? main.right : side.right)] : null,
    cols: all('.side__col').map((e) => { const b = r(e); return { left: n(b.left), top: n(b.top), bottom: n(b.bottom), sticky: getComputedStyle(e).position === 'sticky' }; }),
    week: !!q('.weekmap'), tiles: all('.weekmap__tile').length, goals: all('.goals-mini li').length,
    rings: all('.weekmap__ring').length, ups: all('.weekmap__up').length, line: (q('.weekmap__line') || {}).textContent || null,
    height: document.documentElement.scrollHeight, lede: q('.feedmain__lede') ? n(r(q('.feedmain__lede')).width) : null,
    small: small('.side *') }; })()"""

PROFILE_JS = "(() => {" + HELPERS + """
  const grid = q('.dom__grid'), cards = grid ? [...grid.children] : [];
  const sameRow = (a, b) => Math.abs(r(a).top - r(b).top) < 2;
  const columns = cards.filter((c) => sameRow(c, cards[0])).length;
  const lastRow = cards.filter((c) => sameRow(c, cards[cards.length - 1])).length;
  const canvas = r(q('.kmap__canvas')), svg = q('.kmap__canvas svg'), goals = r(q('.goals')), week = r(q('.week'));
  return { vw: document.documentElement.clientWidth, cards: cards.length, columns, lastRow,
    greyCell: !!grid && lastRow < columns && getComputedStyle(grid).backgroundColor !== getComputedStyle(cards[0]).backgroundColor,
    canvas: canvas ? [n(canvas.width), n(canvas.height)] : null, svg: svg ? [n(r(svg).width), n(r(svg).height)] : null,
    ctm: svg ? Math.round(svg.getScreenCTM().a * 1000) / 1000 : null,
    svgInside: canvas && svg ? r(svg).left >= canvas.left - 1 && r(svg).right <= canvas.right + 1 && r(svg).top >= canvas.top - 1 && r(svg).bottom <= canvas.bottom + 1 : null,
    height: document.documentElement.scrollHeight, level: cards.length ? getComputedStyle(cards[0].querySelector('.dom__level')).fontSize : null,
    cardRule: cards.length ? getComputedStyle(cards[0]).boxShadow.includes('inset') || getComputedStyle(grid).gap === '1px' : null,
    pairSide: goals && week ? Math.abs(goals.top - week.top) < 4 && Math.abs(goals.left - week.left) > 100 : null,
    weekAboveMap: week && canvas ? week.top < canvas.top : null,
    bar: inner(q('.topbar__inner')), page: inner(q('.profile__main')) }; })()"""

READER_JS = "(() => {" + HELPERS + """
  const prose = r(q('.prose')), grid = r(q('.reader__grid')), rail = r(q('.rail')), spine = q('.spine'), sr = r(spine);
  const num = (e) => (e ? parseInt((e.textContent.match(/\\d+/) || ['-1'])[0], 10) : null);
  return { vw: document.documentElement.clientWidth, prose: n(prose.width), grid: n(grid.width),
    gutter: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--gutter')),
    rail: rail && rail.width ? [n(rail.left), n(rail.width)] : null,
    spine: !!spine && sr.width > 0, spineHitsMarker: !!spine && all('.rl-pmark').some((m) => hit(r(m), sr)),
    spineCount: num(q('.spine__count')), railCount: num(q('.rail__head')), ticks: all('.spine__tick').length,
    notes: all('.rail__item').length, marks: new Set(all('.rl-mark').map((m) => m.dataset.rlId)).size,
    height: document.documentElement.scrollHeight,
    small: small('.spine *') }; })()"""

CARD_JS = "(() => {" + HELPERS + """
  const card = r(q('.rl-card')), rail = r(q('.rail')), prose = r(q('.prose'));
  return card && rail ? { left: n(card.left), right: n(card.right), width: n(card.width), railLeft: n(rail.left),
    railWidth: n(rail.width), vw: document.documentElement.clientWidth, overProse: hit(card, prose) } : null; })()"""

# With the page scrolled: each sidebar group's box, and where its last block ends once the group
# itself is scrolled to its end.
STICKY_JS = "(() => {" + HELPERS + """
  return all('.side__col').map((e) => { e.scrollTop = e.scrollHeight; const b = r(e), last = e.lastElementChild ? r(e.lastElementChild) : b;
    return { top: n(b.top), bottom: n(b.bottom), end: n(last.bottom), scrolls: e.scrollHeight > e.clientHeight + 1,
      sticky: getComputedStyle(e).position === 'sticky' }; }); })()"""

# A mark at mid-viewport: where the spine's fill ends against that note's tick.
SPINE_AT_JS = "(async () => {" + HELPERS + """
  const track = q('.spine__track'), fill = q('.spine__fill'); if (!track || !fill) return null;
  const marks = all('.rl-mark'), mark = marks[Math.floor(marks.length / 2)];
  mark.scrollIntoView({ block: 'center' }); await new Promise((res) => setTimeout(res, 500));
  const tick = q('.spine__tick[data-id="' + mark.dataset.rlId + '"]'); if (!tick) return { tick: null };
  const t = r(track), k = r(tick), sy = new DOMMatrix(getComputedStyle(fill).transform).d;
  return { fillEnd: n(t.top + t.height * sy), tick: n(k.top + k.height / 2), track: n(t.height) }; })()"""

SPINE_END_JS = "(async () => {" + HELPERS + """
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }); await new Promise((res) => setTimeout(res, 900));
  const fill = q('.spine__fill'); if (!fill) return null;
  return { scale: n(new DOMMatrix(getComputedStyle(fill).transform).d), text: (q('.spine__left') || {}).textContent || '' }; })()"""

PARAGRAPHS_JS = """(() => [...document.querySelectorAll('p[data-rl-paragraph]')].map((p) => { const c = p.cloneNode(true);
  c.querySelectorAll('[data-rl-ui]').forEach((e) => e.remove()); return [p.dataset.rlParagraph, c.textContent]; }))()"""

out: dict = {"mode": "before" if BEFORE else "check", "pages": {}}
failures: list[str] = []


def step(text: str) -> None:
    print(f"-- {time.strftime('%H:%M:%S')} {text}", flush=True)


def check(ok: bool, what: str) -> None:
    """A named assertion; in --before mode it is only printed."""
    if ok:
        return
    print(f"FAIL {what}", flush=True)
    if not BEFORE:
        failures.append(what)


SETTLED_JS = "document.getAnimations().filter((a) => a instanceof CSSTransition && a.playState === 'running').length"


async def view(p, width: int, dark: bool) -> None:
    """Size and theme, in place. A headless page can report itself hidden after a key press, which
    stalls transitions and animation frames: bring it to the front and wait for colours to settle."""
    await p.send("Page.bringToFront")
    await p.viewport(width, dark=dark)
    theme = "dark" if dark else "light"
    await p.eval(f"document.documentElement.dataset.theme = '{theme}'; localStorage.setItem('readlayer:theme', '{theme}'); 1")
    await asyncio.sleep(0.9)
    for _ in range(40):
        if not await p.eval(SETTLED_JS):
            break
        await asyncio.sleep(0.25)


async def key(p, name: str, vk: int) -> None:
    for kind in ("keyDown", "keyUp"):
        await p.send("Input.dispatchKeyEvent", type=kind, key=name, code=name, windowsVirtualKeyCode=vk, nativeVirtualKeyCode=vk)
    await asyncio.sleep(0.15)


async def record(p, name: str, width: int, dark: bool, metrics_js: str | None, full: bool = True) -> dict:
    """Screenshot + axe + horizontal scroll + this page's numbers, for the current size and theme."""
    tag = f"{name}-{width}-{'dark' if dark else 'light'}"
    await p.eval(cdp.AXE.read_text() + ";'axe'")
    got = {"axe": await p.eval(AXE_ALL),
           "hscroll": await p.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth"),
           "m": await p.eval(metrics_js) if metrics_js else None,
           "r429": await p.eval("window.__rl429 || 0")}
    await p.shot(tag, full=full)
    out["pages"][tag] = got
    print(f"[{tag}] axe={got['axe']} hscroll={got['hscroll']} 429={got['r429']} {json.dumps(got['m'])[:520]}", flush=True)
    check(not got["axe"], f"{tag}: axe {got['axe']}")
    check(got["hscroll"] <= 0, f"{tag}: horizontal scroll {got['hscroll']}")
    if got["r429"]:
        failures.append(f"{tag}: {got['r429']} responses were 429")
    return got


async def sweep(p, name: str, url: str, ready: str, metrics_js: str, checks, after_load=None, full: bool = True) -> None:
    """One load for the desktop sizes (light, then dark), one for the tablet ones (light), one at 390."""
    for widths in ((TABLET, (PHONE,)) if NARROW_ONLY else (DESKTOP, TABLET, (PHONE,))):
        await view(p, widths[0], False)
        await p.goto(url, wait=1.5)
        ok = await p.wait_for(ready, 75)  # a new reader's first feed is built while they wait
        check(ok, f"{name}: {ready} never appeared at {widths[0]}")
        await asyncio.sleep(2.5)
        if after_load:
            await after_load(p)
        for dark in ((False,) if widths is TABLET else (False, True)):
            for w in widths:
                await view(p, w, dark)
                await p.eval("window.scrollTo(0, 0); 1")
                got = await record(p, name, w, dark, metrics_js, full=full)
                if got["m"]:
                    checks(w, got["m"], f"{name}-{w}-{'dark' if dark else 'light'}")


def edges(m: dict, tag: str) -> None:
    if m["bar"] and m["page"]:
        check(abs(m["bar"][0] - m["page"][0]) <= 1 and abs(m["bar"][1] - m["page"][1]) <= 1, f"{tag}: top bar {m['bar']} vs page {m['page']}")


def library_checks(w: int, m: dict, tag: str) -> None:
    if w == 1280:
        check(m["content"] >= 1150, f"{tag}: content width {m['content']} < 1150")
    if w == 1440:
        check(m["content"] >= 1300, f"{tag}: content width {m['content']} < 1300")
        check(m["rowText"] is not None and m["rowText"] >= 560, f"{tag}: row text column {m['rowText']} < 560")
    if w in (1280, 1440, 1920):
        check(m["row"] is not None and m["row"] >= 720, f"{tag}: row {m['row']} < 720")
    if w == 1024:
        check(m["row"] is not None and m["row"] >= 600, f"{tag}: row {m['row']} < 600")
    check(len(m["cols"]) == 2, f"{tag}: {len(m['cols'])} sidebar groups")
    if w >= 961:
        check(m["week"], f"{tag}: no map block")
        check(not m["stacked"], f"{tag}: the sidebar is stacked")
        edges(m, tag)
    else:
        check(not m["week"], f"{tag}: the map block is rendered in a stacked sidebar")
        check(m["stacked"], f"{tag}: the sidebar is not stacked")
    if len(m["cols"]) == 2:
        beside = abs(m["cols"][0]["left"] - m["cols"][1]["left"]) > 100
        check(beside == (w >= 1440), f"{tag}: sidebar groups side by side = {beside}")
    check(not m["small"], f"{tag}: text under 13px in the sidebar {m['small']}")


def profile_checks(w: int, m: dict, tag: str) -> None:
    if w >= 1024:
        edges(m, tag)
    if w in (1280, 1440, 1920) and m["cards"] in (5, 6):
        check(m["columns"] == m["cards"], f"{tag}: {m['columns']} card columns for {m['cards']} cards (one row fits)")
    if m["cards"]:
        check(m["columns"] - m["lastRow"] <= 1 or w < 961, f"{tag}: card rows uneven ({m['columns']} across, {m['lastRow']} in the last row)")
    check(not m["greyCell"], f"{tag}: an empty grey cell in the card grid")
    check(m["cardRule"] is not False, f"{tag}: no rules between the topic cards")
    if m["svgInside"] is not None:
        check(m["svgInside"], f"{tag}: the map {m['svg']} does not fit its canvas {m['canvas']}")
    if m["canvas"]:
        floor = {1280: (820, 680), 1440: (940, 720), 1920: (1100, 720)}.get(w)
        if floor:
            check(m["canvas"][0] >= floor[0] and m["canvas"][1] >= floor[1], f"{tag}: map canvas {m['canvas']} < {floor}")
        if w in (1280, 1440, 1920):
            check(m["ctm"] is not None and abs(m["ctm"] - 1) <= 0.02, f"{tag}: map scale {m['ctm']}")
    if m["pairSide"] is not None and (w >= 1280 or w == PHONE):
        check(m["pairSide"] == (w >= 1280), f"{tag}: Goals and This week side by side = {m['pairSide']}")


def reader_checks(w: int, m: dict, tag: str) -> None:
    if w in DESKTOP:
        check(abs(m["prose"] - 680) <= 1, f"{tag}: prose column {m['prose']}")
    check(m["spine"] == (w >= 1280), f"{tag}: spine present = {m['spine']}")
    check(not m["spineHitsMarker"], f"{tag}: the spine overlaps a paragraph marker")
    if w == 1280:
        check(m["grid"] + 15 <= m["vw"] - 2 * m["gutter"], f"{tag}: grid {m['grid']} leaves no room for a scrollbar")
    if m["spine"]:
        check(m["spineCount"] == m["railCount"], f"{tag}: spine count {m['spineCount']} vs margin {m['railCount']}")
        check(m["ticks"] == m["notes"], f"{tag}: {m['ticks']} ticks for {m['notes']} notes")
    check(not m["small"], f"{tag}: text under 13px in the spine {m['small']}")


async def cls(p, name: str, url: str, ready: str) -> None:
    await view(p, 1440, False)
    await p.goto(url, wait=1.5)
    await p.wait_for(ready, 40)
    await asyncio.sleep(5)
    value = await p.eval("Math.round(window.__cls * 1000) / 1000")
    out["pages"][f"{name}-cls-1440"] = value
    print(f"[{name} layout shift 1440] {value}", flush=True)
    check(value < 0.1, f"{name}: layout shift {value} at 1440")


async def library(p, who: str, query: str) -> None:
    step(f"library ({who})")
    await sweep(p, f"library-foryou-{who}", f"{W}/?tab=foryou{query}", ".row:not(.row--skeleton), .state", LIBRARY_JS, library_checks)
    await sweep(p, f"library-topics-{who}", f"{W}/?tab=topics{query}", ".row:not(.row--skeleton)", LIBRARY_JS, library_checks, full=False)
    if NARROW_ONLY:
        return
    await cls(p, f"library-{who}", f"{W}/?tab=topics{query}", ".row:not(.row--skeleton)")
    # Tab through the sidebar at 1440: the blocks come in reading order.
    await p.eval("(() => { window.scrollTo(0, 0); const f = document.querySelector('.side input, .side button, .side a'); if (f) f.focus(); return 1; })()")
    seen: list[str] = []
    for _ in range(24):
        head = await p.eval("""(() => { const a = document.activeElement, b = a && a.closest('.side__block, .side section');
          return b ? (b.querySelector('h2') || {}).textContent || '?' : null; })()""")
        if head is None:
            break
        if not seen or seen[-1] != head:
            seen.append(head)
        await key(p, "Tab", 9)
    out["pages"][f"library-{who}-tab-order"] = seen
    print(f"[library {who} tab order 1440] {seen}", flush=True)
    check(len(seen) == len(set(seen)), f"library-{who}: Tab revisits a sidebar block: {seen}")
    # Both groups stay beside the feed on any window height; a tall one scrolls inside itself.
    for height in (900, 760):
        await p.viewport(1440, height=height)
        await asyncio.sleep(0.6)
        scrolled = await p.eval("(() => { window.scrollTo({ top: 600, behavior: 'instant' }); return window.scrollY; })()")
        await asyncio.sleep(0.4)
        cols = await p.eval(STICKY_JS)
        out["pages"][f"library-{who}-sticky-1440x{height}"] = {"scrolled": scrolled, "cols": cols}
        print(f"[library {who} sidebar groups 1440x{height}, page scrolled {scrolled}] {cols}", flush=True)
        check(len(cols) == 2 and all(c["sticky"] for c in cols), f"library-{who}: sidebar groups not sticky at 1440x{height}")
        for c in cols:
            check(scrolled < 200 or abs(c["top"] - 65) <= 1, f"library-{who}: a sidebar group is at {c['top']}, not under the bar, at 1440x{height}")
            check(c["bottom"] <= height + 0.5, f"library-{who}: a sidebar group ends at {c['bottom']} of {height}")
            check(c["end"] <= height + 0.5, f"library-{who}: the end of a sidebar group can't be reached ({c['end']} of {height})")
    await p.eval("(() => { document.querySelectorAll('.side__col').forEach((e) => { e.scrollTop = 0; }); window.scrollTo(0, 0); return 1; })()")
    await p.viewport(1440)
    if who == "demo":
        await risers(p, query)


async def risers(p, query: str) -> None:
    """The "this week" half of the map panel: two ideas the demo reader says they know rise a
    level, so the tiles show rings and "+N this week" and the line names them."""
    persona = query.split("persona=")[-1]
    nodes = (await p.api("", "GET", f"/v1/me/graph?view=overview&persona={persona}"))["body"]["nodes"]
    picks = [n["id"] for n in nodes if n["band"] == "heard of" and not n["ready"]][:2] or [n["id"] for n in nodes if n["ready"]][:2]
    done = [(await p.api("", "PATCH", f"/v1/me/graph/{cid}?persona={persona}", {"state": "known"}))["status"] for cid in picks]
    after = (await p.api("", "GET", f"/v1/me/graph?view=overview&persona={persona}"))["body"]["nodes"]
    rose = [n["label"] for n in after if n["rose_this_week"]]
    print(f"[library risers] corrected {picks} -> {done}; risen this week: {rose}", flush=True)
    check(len(rose) >= 1, "library risers: no idea counts as risen after two corrections")
    await view(p, 1440, False)
    await p.goto(f"{W}/?tab=topics{query}", wait=1.5)
    ok = await p.wait_for(".weekmap__ring", 45)
    check(ok, "library risers: no ring on a tile")
    await asyncio.sleep(1.5)
    for w, dark in ((1440, False), (1440, True), (1280, False), (1280, True)):
        await view(p, w, dark)
        m = (await record(p, "library-risers-demo", w, dark, LIBRARY_JS, full=False))["m"]
        check(m["rings"] >= 1 and m["ups"] >= 1, f"library-risers-demo-{w}: rings {m['rings']}, '+N this week' lines {m['ups']}")
        check(bool(m["line"]) and "moved up this week:" in m["line"], f"library-risers-demo-{w}: line {m['line']!r}")
        check(not m["small"], f"library-risers-demo-{w}: text under 13px {m['small']}")


async def profile(p, who: str, query: str) -> None:
    step(f"profile ({who})")
    await sweep(p, f"profile-{who}", f"{W}/profile{query}", ".kmap__canvas svg, .clist", PROFILE_JS, profile_checks)
    if NARROW_ONLY:
        return
    # A topic on its own, the inspector and the list view, at the three wide sizes (light).
    await view(p, 1440, False)
    await p.goto(f"{W}/profile{query}", wait=1.5)
    await p.wait_for(".kmap__node", 40)
    await asyncio.sleep(2)
    await p.eval("document.querySelector('.kmap__canvas').scrollIntoView({block: 'center'}); 1")
    await p.eval("(() => { const n = document.querySelector('.kmap__node[tabindex=\"0\"]') || document.querySelector('.kmap__node'); n.focus(); return 1; })()")
    first = await p.eval("document.activeElement.getAttribute('aria-label')")
    await key(p, "ArrowRight", 39)
    moved = await p.eval("document.activeElement.getAttribute('aria-label')")
    await key(p, "Enter", 13)
    await asyncio.sleep(0.6)
    opened = await p.eval("!!document.querySelector('#inspect-title')")
    out["pages"][f"profile-{who}-keyboard"] = {"first": first, "moved": moved, "inspector": opened}
    print(f"[profile {who} keyboard] {first!r} -> {moved!r}, inspector={opened}", flush=True)
    check(bool(first) and moved != first, f"profile-{who}: arrow keys don't move between map nodes")
    check(opened, f"profile-{who}: Enter doesn't open the inspector")
    for w in (1280, 1440, 1920):
        await view(p, w, False)
        await p.eval("document.querySelector('.kmap').scrollIntoView({block: 'start'}); window.scrollBy(0, -80); 1")
        await asyncio.sleep(0.4)
        await record(p, f"profile-inspector-{who}", w, False, PROFILE_JS, full=False)
    await view(p, 1440, False)
    await p.eval("(() => { const b = document.querySelectorAll('.kmap__scopes .filter')[1]; if (b) b.click(); return 1; })()")
    await asyncio.sleep(2.5)
    await record(p, f"profile-topic-{who}", 1440, False, PROFILE_JS, full=False)
    await p.eval("[...document.querySelectorAll('.kmap [role=radio]')].find((b) => b.textContent.trim() === 'List').click(); 1")
    await asyncio.sleep(0.8)
    await record(p, f"profile-list-{who}", 1440, False, None, full=False)


async def reader(p, query: str, persona: str) -> None:
    step("reader")
    lib = (await p.api("", "GET", f"/v1/content?persona={persona}"))["body"]
    art = next((i["id"] for i in lib if i["id"].startswith("2332")), lib[0]["id"])
    url = f"{W}/read/{art}{query}"
    await sweep(p, "reader", url, ".rl-mark, .reader__notice", READER_JS, reader_checks, full=False)
    if NARROW_ONLY:
        return

    # The article's words are untouched: each paragraph, minus the overlay's own UI, equals the API's.
    await view(p, 1440, False)
    await p.goto(url, wait=1.5)
    await p.wait_for(".rl-mark", 40)
    await asyncio.sleep(2.5)
    api = (await p.api("", "GET", f"/v1/content/{art}"))["body"]["paragraphs"]
    dom = dict(await p.eval(PARAGRAPHS_JS))
    wrong = [x["id"] for x in api if dom.get(x["id"]) != x["text"]]
    out["pages"]["reader-paragraphs"] = {"api": len(api), "dom": len(dom), "different": wrong}
    print(f"[reader paragraphs] api={len(api)} dom={len(dom)} different={wrong}", flush=True)
    check(not wrong and len(api) == len(dom), f"reader: paragraph text differs from the API: {wrong}")

    for w in (1280, 1440, 1920):
        await view(p, w, False)
        at = await p.eval(SPINE_AT_JS)
        out["pages"][f"reader-spine-at-{w}"] = at
        print(f"[reader spine at a mark {w}] {at}", flush=True)
        if not BEFORE:
            check(bool(at) and at.get("tick") is not None and abs(at["fillEnd"] - at["tick"]) <= 0.1 * at["track"], f"reader-{w}: spine fill vs tick {at}")
        await p.eval("(() => { const m = document.querySelectorAll('.rl-mark'), k = m[Math.floor(m.length / 2)]; k.scrollIntoView({block: 'center'}); k.click(); return 1; })()")
        await asyncio.sleep(7 if w == 1280 else 2.5)
        card = await p.eval(CARD_JS)
        out["pages"][f"reader-card-{w}"] = card
        print(f"[reader card {w}] {card}", flush=True)
        check(bool(card), f"reader-{w}: no open card")
        if card:
            check(abs(card["left"] - card["railLeft"]) <= 1, f"reader-{w}: card left {card['left']} vs rail {card['railLeft']}")
            check(card["right"] <= card["vw"] - 16 + 0.5, f"reader-{w}: card right {card['right']} of {card['vw']}")
            check(not card["overProse"], f"reader-{w}: the card overlaps the article text")
        await record(p, "reader-card", w, False, None, full=False)
        await key(p, "Escape", 27)
        await asyncio.sleep(0.5)
        await p.send("Page.bringToFront")
    await view(p, 1440, True)
    await record(p, "reader-spine", 1440, True, READER_JS, full=False)
    await view(p, 1440, False)
    end = await p.eval(SPINE_END_JS)
    out["pages"]["reader-spine-end"] = end
    print(f"[reader spine at the end] {end}", flush=True)
    if not BEFORE:
        check(bool(end) and end["scale"] >= 0.99 and "Finished" in end["text"], f"reader: spine at the end {end}")
    await record(p, "reader-end", 1440, False, READER_JS, full=False)
    await cls(p, "reader", url, ".rl-mark")


async def google_reader(p) -> None:
    """A fresh emulator Google reader with six chosen topics and three goals (no model call:
    two habits and a concept the graph knows by name)."""
    await p.reset_auth(W)
    await p.goto(W + "/", wait=3)
    email = f"wide-{int(time.time())}@example.com"
    await p.eval(f"window.__rlEmulatorSignIn('{email}', 'Wide Check')")
    await asyncio.sleep(4)
    setup = [(await p.api("", "POST", "/v1/me/consent", {"version": "consent-v2"}))["status"],
             (await p.api("", "POST", "/v1/onboarding", {"field": "software", "interests": TOPICS,
              "comfort": {t: "some" for t in TOPICS}, "thinks_in": ["cricket"], "country": "IN"}))["status"],
             (await p.api("", "POST", "/v1/calibration/skip", {}))["status"]]
    goals = [(await p.api("", "POST", "/v1/me/goals", body))["status"] for body in (
        {"type": "habit", "metric": "articles", "per_week": 5}, {"type": "habit", "metric": "minutes", "per_week": 60},
        {"type": "learning", "text": "inflation"})]
    print(f"[google reader] setup={setup} goals={goals}", flush=True)
    check(all(s < 300 for s in setup), f"google reader setup {setup}")
    out["google"] = {"setup": setup, "goals": goals}


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.send("Page.addScriptToEvaluateOnNewDocument", source=INIT_JS)
        await p.send("Emulation.setFocusEmulationEnabled", enabled=True)
        await p.viewport(1440)
        step("demo reader")
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.wait_for(".lp-nav__cta", 20)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")
        await asyncio.sleep(4)
        which = [a for a in sys.argv[1:] if not a.startswith("--")] or ["library", "profile", "reader", "google"]
        query = "?persona=newcomer"
        if "library" in which:
            await library(p, "demo", "&persona=newcomer")
        if "profile" in which:
            await profile(p, "demo", query)
        if "reader" in which:
            await reader(p, query, "newcomer")
        if "google" in which:
            step("google reader")
            await google_reader(p)
            await library(p, "google", "")
            await profile(p, "google", "")
            g = out["pages"].get("library-foryou-google-1440-light", {}).get("m") or {}
            check(g.get("goals", 0) >= 2, f"google: {g.get('goals')} goals in the sidebar")
    finally:
        cdp.OUT.mkdir(parents=True, exist_ok=True)
        (cdp.OUT / "metrics.json").write_text(json.dumps(out, indent=1))
        await ws.close()
        cdp.stop()
    print(f"\n{len(failures)} failed checks" + ("" if not failures else ":\n" + "\n".join(failures)))
    if failures and not BEFORE:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
