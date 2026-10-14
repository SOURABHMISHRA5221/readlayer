"""Media reader (docs/plans/media.md, acceptance 4, cut down after decision 2026-10-14 "small
10 minutes clips are good enough"): one seeded video in the reader as a demo reader, at 1440 and
390 (light and dark) and 1024 (light). Screenshots, axe at every impact level, horizontal scroll,
the transcript's words against the API, and one time button. Emulators only; the video must be
stored first (`scripts/ingest_media.py <url>` against the emulator).

    SHOTS_OUT=docs/evidence/media uv run --project apps/api python tools/shots/media.py <content_id> [video|podcast]

Exits non-zero on any failed check or 429.
"""

import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

W = "http://localhost:5173"
SIZES = ((1440, False), (1440, True), (1024, False), (390, False), (390, True))
PERSONA = "newcomer"
SEEK_INDEX = 4  # a paragraph well into the recording

INIT_JS = """window.__rl429 = 0; (() => { const f = window.fetch; window.fetch = async (...a) => {
  const r = await f(...a); if (r.status === 429) window.__rl429++; return r; }; })();"""
AXE_ALL = ("axe.run(document, {resultTypes: ['violations']}).then(r => r.violations"
           ".map(v => v.impact + ':' + v.id + ':' + v.nodes.length))")
PARAGRAPHS_JS = """(() => [...document.querySelectorAll('p[data-rl-paragraph]')].map((p) => { const c = p.cloneNode(true);
  c.querySelectorAll('[data-rl-ui]').forEach((e) => e.remove()); return [p.dataset.rlParagraph, c.textContent]; }))()"""
PAGE_JS = """(() => ({ stamps: document.querySelectorAll('.tstamp').length,
  marks: document.querySelectorAll('.rl-mark').length, facade: !!document.querySelector('.mplayer__facade'),
  audio: !!document.querySelector('.mplayer__audio'),
  hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth }))()"""

failures: list[str] = []
out: dict = {}


def check(ok: bool, what: str) -> None:
    if not ok:
        failures.append(what)
        print(f"  FAIL {what}", flush=True)


async def theme(p, dark: bool) -> None:
    await p.eval(f"localStorage.setItem('readlayer:theme', '{'dark' if dark else 'light'}'); 1")


async def sweep(p, url: str, kind: str) -> None:
    for width, dark in SIZES:
        name = f"{kind}-{width}-{'dark' if dark else 'light'}"
        await p.viewport(width, dark=dark)
        await theme(p, dark)
        await p.goto(url, wait=1.5)
        check(await p.wait_for(".tstamp", 40), f"{name}: no transcript")
        await p.wait_for(".rl-mark", 30)
        await asyncio.sleep(1.5)
        await p.eval(cdp.AXE.read_text() + ";'axe'")
        axe = await p.eval(AXE_ALL)
        page = await p.eval(PAGE_JS)
        shot = await p.shot(name, full=False)
        out[name] = {"axe": axe, **page}
        print(f"[{name}] axe={axe} {json.dumps(page)} {shot}", flush=True)
        check(not axe, f"{name}: axe {axe}")
        check(page["hscroll"] == 0, f"{name}: horizontal scroll {page['hscroll']}")
        if kind == "video":
            check(page["facade"], f"{name}: the player loaded before any click (should be click to load)")
        else:
            check(page["audio"], f"{name}: no audio player")


async def words_and_seek(p, url: str, content_id: str, kind: str) -> None:
    await p.viewport(1440)
    await theme(p, False)
    await p.goto(url, wait=1.5)
    await p.wait_for(".rl-mark", 40)
    await asyncio.sleep(1.5)
    api = (await p.api("", "GET", f"/v1/content/{content_id}?persona={PERSONA}"))["body"]
    paras = api["paragraphs"]
    dom = dict(await p.eval(PARAGRAPHS_JS))
    wrong = [x["id"] for x in paras if dom.get(x["id"]) != x["text"]]
    out["paragraphs"] = {"api": len(paras), "dom": len(dom), "different": wrong}
    print(f"[paragraphs] api={len(paras)} dom={len(dom)} different={wrong}", flush=True)
    check(not wrong and len(paras) == len(dom), f"transcript text differs from the API: {wrong}")
    if kind != "video":
        return  # audio seeking needs the publisher's file to play headless: not checked here

    want = paras[SEEK_INDEX]["start_s"]
    clicked = await p.eval(f"""(() => {{ const b = document.querySelectorAll('.tstamp')[{SEEK_INDEX}];
      b.scrollIntoView({{block: 'center'}}); b.click(); return b.getAttribute('aria-label'); }})()""")
    await asyncio.sleep(1.5)
    src = await p.eval("(document.querySelector('.mplayer iframe') || {}).src || null")
    start = int(src.split("start=")[1].split("&")[0]) if src and "start=" in src else None
    out["seek"] = {"button": clicked, "paragraph_start_s": want, "iframe_start_s": start}
    print(f"[seek] {clicked!r}: paragraph starts {want} s, player loads at {start} s", flush=True)
    check(start is not None and abs(start - want) <= 2, f"seek: player at {start} s, paragraph {want} s")
    await p.shot(f"{kind}-1440-light-after-seek", full=False)


async def main(content_id: str, kind: str) -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.send("Page.addScriptToEvaluateOnNewDocument", source=INIT_JS)
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.wait_for(".lp-nav__cta", 20)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")
        await asyncio.sleep(4)
        url = f"{W}/read/{content_id}?persona={PERSONA}"
        await sweep(p, url, kind)
        await words_and_seek(p, url, content_id, kind)
        throttled = await p.eval("window.__rl429")
        check(throttled == 0, f"{throttled} responses were 429")
    finally:
        cdp.OUT.mkdir(parents=True, exist_ok=True)
        (cdp.OUT / f"metrics-{kind}-{content_id[:8]}.json").write_text(json.dumps(out, indent=1))
        await ws.close()
        cdp.stop()
    print(f"\n{len(failures)} failed checks" + ("" if not failures else ":\n" + "\n".join(failures)))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "video"))
