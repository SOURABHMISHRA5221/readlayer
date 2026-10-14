"""Media follow-up B (decision 55, docs/plans/media-followup.md F5): the For you tab with a short
video, a long video and an article, served from a committed fixture (no search, no LLM). At 1440
and 390, light and dark: axe at every impact, horizontal scroll, which rows offer "Open in Gloss"
and the original, and that the keyboard reaches both with a visible focus ring. Emulators only.

    SHOTS_OUT=docs/evidence/media-followup uv run --project apps/api python tools/shots/media_followup.py

Exits non-zero on any failed check.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp

W = "http://localhost:5173"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))
FIXTURE = (Path(__file__).parent / "fixtures" / "feed_media.json").read_text()
SHORT, LONG, ARTICLE = (i["title"] for i in json.loads(FIXTURE)["items"])
MAX_TABS = 120

# Installed before the app on every load: /v1/feed answers from the fixture, nothing else changes.
INIT_JS = """(() => { const feed = %s; const f = window.fetch;
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.pathname === '/v1/feed') return new Response(JSON.stringify(feed), { status: 200, headers: { 'Content-Type': 'application/json' } });
    return f(input, init);
  }; })();""" % FIXTURE

AXE_ALL = ("axe.run(document, {resultTypes: ['violations']}).then(r => r.violations"
           ".map(v => v.impact + ':' + v.id + ':' + v.nodes.length))")
ROWS_JS = """(() => [...document.querySelectorAll('article.row')].map((r) => ({
  title: (() => { const t = r.querySelector('.row__title')?.cloneNode(true); if (!t) return null;
    t.querySelectorAll('.visually-hidden').forEach((e) => e.remove()); return t.textContent.trim(); })(),
  gloss: r.querySelector('.row__gloss')?.getAttribute('aria-label') || null,
  original: r.querySelector('.row__original')?.textContent || null,
  titleTarget: r.querySelector('.row__title a')?.target || '' })))()"""
FOCUS_JS = """(() => { const e = document.activeElement; if (!e) return null; const c = getComputedStyle(e);
  return { cls: e.className || e.tagName, label: e.getAttribute('aria-label') || e.textContent.trim().slice(0, 60),
    ring: c.outlineStyle !== 'none' && parseFloat(c.outlineWidth) > 0 }; })()"""

failures: list[str] = []
out: dict = {}


def check(ok: bool, what: str) -> None:
    if not ok:
        failures.append(what)
        print(f"  FAIL {what}", flush=True)


async def tab(p) -> None:
    for kind in ("keyDown", "keyUp"):
        await p.send("Input.dispatchKeyEvent", type=kind, key="Tab", code="Tab", windowsVirtualKeyCode=9)


async def keyboard(p, name: str) -> None:
    """Tab from the top until "Open in Gloss" on the short video, then once more to its original."""
    await p.eval("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); 1")
    for _ in range(MAX_TABS):
        await tab(p)
        focus = await p.eval(FOCUS_JS)
        if focus and focus["label"] == f"Open in Gloss: {SHORT}":
            break
    else:
        check(False, f"{name}: Tab never reached Open in Gloss")
        return
    await tab(p)
    after = await p.eval(FOCUS_JS)
    out[f"{name}-keyboard"] = {"gloss": focus, "next": after}
    print(f"[{name} keyboard] {focus} -> {after}", flush=True)
    check(focus["ring"], f"{name}: no focus ring on Open in Gloss")
    check("row__original" in str(after["cls"]) and after["ring"], f"{name}: Tab after Open in Gloss reached {after}")


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.send("Page.addScriptToEvaluateOnNewDocument", source=INIT_JS)
        await p.send("Emulation.setFocusEmulationEnabled", enabled=True)
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.wait_for(".lp-nav__cta", 20)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")
        await asyncio.sleep(4)
        for width, dark in SIZES:
            name = f"foryou-{width}-{'dark' if dark else 'light'}"
            await p.viewport(width, dark=dark)
            await p.eval(f"localStorage.setItem('readlayer:theme', '{'dark' if dark else 'light'}'); 1")
            await p.goto(f"{W}/for-you?persona=newcomer", wait=1.5)
            check(await p.wait_for(".row__gloss", 30), f"{name}: no Open in Gloss")
            await asyncio.sleep(1.5)
            rows = {r["title"]: r for r in await p.eval(ROWS_JS)}
            await p.eval(cdp.AXE.read_text() + ";'axe'")
            axe = await p.eval(AXE_ALL)
            hscroll = await p.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            out[name] = {"axe": axe, "hscroll": hscroll, "rows": rows}
            print(f"[{name}] axe={axe} hscroll={hscroll} {await p.shot(name, full=False)}", flush=True)
            check(not axe, f"{name}: axe {axe}")
            check(hscroll == 0, f"{name}: horizontal scroll {hscroll}")
            short, long_, article = rows.get(SHORT, {}), rows.get(LONG, {}), rows.get(ARTICLE, {})
            check(short.get("gloss") == f"Open in Gloss: {SHORT}", f"{name}: short video row {short}")
            check((short.get("original") or "").startswith("Watch on YouTube"), f"{name}: short video original {short}")
            check(not long_.get("gloss") and not long_.get("original") and long_.get("titleTarget") == "_blank",
                  f"{name}: long video row {long_}")
            check(not article.get("gloss") and not article.get("original"), f"{name}: article row {article}")
            await keyboard(p, name)
    finally:
        cdp.OUT.mkdir(parents=True, exist_ok=True)
        (cdp.OUT / "metrics.json").write_text(json.dumps(out, indent=1))
        await ws.close()
        cdp.stop()
    print(f"\n{len(failures)} failed checks" + ("" if not failures else ":\n" + "\n".join(failures)))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
