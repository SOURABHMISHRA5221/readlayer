"""Wide layout (decision 45) on the local harness: library, profile and reader at 1024, 1280,
1440, 1920 and 390, light and dark. Screenshots, axe at every impact level, horizontal scroll,
and the layout numbers the plan's acceptance names (docs/plans/wide-layout.md). Emulators only.

    SHOTS_OUT=/tmp/wide-before uv run --project apps/api python tools/shots/wide.py --before
    SHOTS_OUT=/tmp/wide uv run --project apps/api python tools/shots/wide.py

`--before` records the same shots and numbers without asserting (run on the code before the
change). Without it, any failed check or any 429 exits non-zero. Sizes and themes change in
place; a page is loaded once for the desktop sizes and once at 390.
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

W = "http://localhost:5173"
DESKTOP = (1024, 1280, 1440, 1920)
PHONE = 390
BEFORE = "--before" in sys.argv
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
    small: small('.side *') }; })()"""

PROFILE_JS = "(() => {" + HELPERS + """
  const grid = q('.dom__grid'), cards = grid ? [...grid.children] : [];
  const sameRow = (a, b) => Math.abs(r(a).top - r(b).top) < 2;
  const columns = cards.filter((c) => sameRow(c, cards[0])).length;
  const lastRow = cards.filter((c) => sameRow(c, cards[cards.length - 1])).length;
  const canvas = r(q('.kmap__canvas')), svg = q('.kmap__canvas svg'), goals = r(q('.goals')), week = r(q('.week'));
  return { vw: document.documentElement.clientWidth, cards: cards.length, columns,
    greyCell: !!grid && lastRow < columns && getComputedStyle(grid).backgroundColor !== getComputedStyle(cards[0]).backgroundColor,
    canvas: canvas ? [n(canvas.width), n(canvas.height)] : null, svg: svg ? [n(r(svg).width), n(r(svg).height)] : null,
    ctm: svg ? Math.round(svg.getScreenCTM().a * 1000) / 1000 : null,
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
    small: small('.spine *') }; })()"""

CARD_JS = "(() => {" + HELPERS + """
  const card = r(q('.rl-card')), rail = r(q('.rail')), prose = r(q('.prose'));
  return card && rail ? { left: n(card.left), right: n(card.right), width: n(card.width), railLeft: n(rail.left),
    railWidth: n(rail.width), vw: document.documentElement.clientWidth, overProse: hit(card, prose) } : null; })()"""

# A mark at mid-viewport: where the spine's fill ends against that note's tick.
SPINE_AT_JS = "(async () => {" + HELPERS + """
  const track = q('.spine__track'), fill = q('.spine__fill'); if (!track || !fill) return null;
  const marks = all('.rl-mark'), mark = marks[Math.floor(marks.length / 2)];
  mark.scrollIntoView({ block: 'center' }); await new Promise((res) => setTimeout(res, 500));
  const tick = q('.spine__tick[data-id="' + mark.dataset.rlId + '"]'); if (!tick) return { tick: null };
  const t = r(track), k = r(tick), sy = new DOMMatrix(getComputedStyle(fill).transform).d;
  return { fillEnd: n(t.top + t.height * sy), tick: n(k.top + k.height / 2), track: n(t.height) }; })()"""

SPINE_END_JS = "(async () => {" + HELPERS + """
  window.scrollTo(0, document.documentElement.scrollHeight); await new Promise((res) => setTimeout(res, 600));
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


async def view(p, width: int, dark: bool) -> None:
    await p.viewport(width, dark=dark)
    theme = "dark" if dark else "light"
    await p.eval(f"document.documentElement.dataset.theme = '{theme}'; localStorage.setItem('readlayer:theme', '{theme}'); 1")
    await asyncio.sleep(0.9)


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
    """One load for the desktop sizes (light, then dark), one at 390."""
    for widths in (DESKTOP, (PHONE,)):
        await view(p, widths[0], False)
        await p.goto(url, wait=1.5)
        ok = await p.wait_for(ready, 40)
        check(ok, f"{name}: {ready} never appeared at {widths[0]}")
        await asyncio.sleep(2.5)
        if after_load:
            await after_load(p)
        for dark in (False, True):
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
    if w >= 1024:
        check(m["week"], f"{tag}: no map block")
        check(len(m["cols"]) == 2, f"{tag}: {len(m['cols'])} sidebar groups")
        edges(m, tag)
    if w == PHONE:
        check(not m["week"], f"{tag}: the map block is rendered on a phone")
    if len(m["cols"]) == 2:
        beside = abs(m["cols"][0]["left"] - m["cols"][1]["left"]) > 100
        check(beside == (w >= 1440), f"{tag}: sidebar groups side by side = {beside}")
    check(not m["small"], f"{tag}: text under 13px in the sidebar {m['small']}")


def profile_checks(w: int, m: dict, tag: str) -> None:
    if w >= 1024:
        edges(m, tag)
    if w == 1280 and m["cards"] >= 5:
        check(m["columns"] >= 5, f"{tag}: {m['columns']} card columns for {m['cards']} cards")
    check(not m["greyCell"], f"{tag}: an empty grey cell in the card grid")
    if m["canvas"]:
        floor = {1280: (820, 680), 1440: (940, 720), 1920: (1100, 720)}.get(w)
        if floor:
            check(m["canvas"][0] >= floor[0] and m["canvas"][1] >= floor[1], f"{tag}: map canvas {m['canvas']} < {floor}")
        if w in (1280, 1440, 1920):
            check(m["ctm"] is not None and abs(m["ctm"] - 1) <= 0.02, f"{tag}: map scale {m['ctm']}")
    if m["pairSide"] is not None:
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
    await sweep(p, f"library-foryou-{who}", f"{W}/?tab=foryou{query}", ".row:not(.row--skeleton), .feedtab__note, .state", LIBRARY_JS, library_checks)
    await sweep(p, f"library-topics-{who}", f"{W}/?tab=topics{query}", ".row:not(.row--skeleton)", LIBRARY_JS, library_checks, full=False)
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
    cols = (await p.eval(LIBRARY_JS))["cols"]
    out["pages"][f"library-{who}-sticky-1440x900"] = cols
    for c in cols:
        if c["sticky"]:
            check(c["bottom"] <= 900, f"library-{who}: a sticky sidebar group ends at {c['bottom']} of 900")


async def profile(p, who: str, query: str) -> None:
    step(f"profile ({who})")
    await sweep(p, f"profile-{who}", f"{W}/profile{query}", ".kmap__canvas svg, .clist", PROFILE_JS, profile_checks)
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
