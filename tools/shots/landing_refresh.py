"""Landing refresh checks (docs/plans/landing-refresh.md "Budgets and checks", decision 61): the
after build against the before build (main), both local `vite preview`, signed out, no account.

    pnpm --filter web build && (cd apps/web && npx vite preview --port 4173)      # after
    (main worktree) pnpm --filter web build && npx vite preview --port 4174       # before
    SHOTS_OUT=docs/evidence/landing-refresh uv run --project apps/api python tools/shots/landing_refresh.py

Checks: axe at every impact level and no horizontal scroll at 320–1920, light and dark, with every
still loaded; headings in order; every image described; the new stills not requested before
scroll; the first view unchanged apart from the chips (pixel diff against before). Shots: full
pages and first views, before and after. Run tools/shots/landing.py too (decision 46/47 checks).
"""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
from landing import AXE_ALL, THEME  # noqa: E402

AFTER, BEFORE = "http://localhost:4173", "http://localhost:4174"
WIDTHS = (320, 390, 768, 1024, 1440, 1920)
NEW_STILLS = ("shot-extension", "shot-popup", "shot-media")
SCROLL_ALL = """(async () => { for (let y = 0; y < document.body.scrollHeight; y += 400) { scrollTo(0, y);
  await new Promise(r => setTimeout(r, 250)); } scrollTo(0, 0); return true; })()"""
# Every visible still is loaded, and none is left a placeholder (a still that never came near
# would otherwise pass unnoticed; the popup is display:none below 768, so not visible).
STILLS_DONE = """[...document.querySelectorAll('img.lp-still')].every(i => i.complete && i.naturalWidth > 0)
  && ![...document.querySelectorAll('.lp-still--pending')].some(e => e.checkVisibility())"""
HEADINGS = "[...document.querySelectorAll('h1, h2, h3, h4')].map(h => [+h.tagName[1], h.textContent.trim().slice(0, 40)])"
NO_ALT = "[...document.querySelectorAll('img, [role=img]')].filter(e => !(e.getAttribute('alt') || e.getAttribute('aria-label') || e.closest('[aria-hidden=true]'))).map(e => e.outerHTML.slice(0, 80))"
REQUESTED = "performance.getEntriesByType('resource').map(e => e.name.split('/').pop())"
READWITH = "(() => { const r = document.querySelector('.lp-readwith')?.getBoundingClientRect(); return r && r.height ? [r.left, r.top, r.right, r.bottom] : null; })()"


def diff_box(a: str, b: str) -> list[int] | None:
    """The bounding box of pixels that differ by more than a hair (ffmpeg bbox on the difference)."""
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", a, "-i", b, "-filter_complex",
                          "[0][1]blend=all_mode=difference,format=gray,bbox=min_val=24", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    boxes = re.findall(r"x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)", out)
    return [int(v) for v in boxes[-1]] if boxes else None


async def full_shot(p, name: str) -> str:
    """The whole page as viewport tiles taken while scrolling, then stacked. A captureBeyondViewport
    shot resizes the page mid-capture, which re-mounts the See it in action stills as empty
    placeholders (the first evidence showed blank device frames)."""
    total, vh, w = await p.eval("[document.documentElement.scrollHeight, innerHeight, innerWidth]")
    tiles, y = [], 0
    while y < total:
        await p.eval(f"scrollTo(0, {y}); true")
        await asyncio.sleep(0.5)
        at = await p.eval("scrollY")
        tiles.append((await p.shot(f"{name}-tile{len(tiles)}"), y - at, min(vh, total - y)))
        y += vh
    await p.eval("scrollTo(0, 0); true")
    out = str(cdp.OUT / f"{name}.png")
    inputs = [a for path, _, _ in tiles for a in ("-i", path)]
    crops = "".join(f"[{i}]crop={w}:{keep}:0:{off}[t{i}];" for i, (_, off, keep) in enumerate(tiles))
    stack = "".join(f"[t{i}]" for i in range(len(tiles))) + f"vstack=inputs={len(tiles)}" if len(tiles) > 1 else "[t0]null"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", crops + stack, out], check=True)
    for path, _, _ in tiles:
        Path(path).unlink()
    return out


def headings_in_order(hs) -> bool:
    return bool(hs) and hs[0][0] == 1 and all(b[0] <= a[0] + 1 for a, b in zip(hs, hs[1:]))


async def page_checks(p, base, w, dark, tag):
    await p.viewport(w, 900, dark=dark)
    await p.eval(THEME.format("dark" if dark else "light"))
    await p.goto(base + "/", wait=2.5)
    await p.eval(SCROLL_ALL)
    for _ in range(40):
        if await p.eval(STILLS_DONE):
            break
        await asyncio.sleep(0.25)
    await asyncio.sleep(0.5)
    name = f"{tag}-{w}-{'dark' if dark else 'light'}"
    out = {}
    if tag == "after":
        out["stills_loaded"] = await p.eval(STILLS_DONE)
        await p.eval(cdp.AXE.read_text() + ";'axe'")
        hs = await p.eval(HEADINGS)
        out.update(axe=await p.eval(AXE_ALL),
                   hscroll=await p.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth"),
                   headings_ok=headings_in_order(hs), no_alt=await p.eval(NO_ALT))
        if w == 1440 and not dark:
            out["headings"] = hs
    out["shot"] = await full_shot(p, name)
    return out


async def first_view(p, base, w, h, tag):
    await p.viewport(w, h)
    await p.eval(THEME.format("light"))
    await p.send("Network.setCacheDisabled", cacheDisabled=True)
    await p.goto(base + "/", wait=3)
    await p.send("Network.setCacheDisabled", cacheDisabled=False)
    requested = await p.eval(REQUESTED)
    return {"fold": await p.shot(f"{tag}-fold-{w}x{h}"), "readwith": await p.eval(READWITH),
            "new_stills_before_scroll": [n for n in requested if n.startswith(NEW_STILLS)]}


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    report, fails = {}, []
    try:
        await p.send("Network.enable")
        await cdp.Page.reset_auth(p, AFTER)
        for w in WIDTHS:
            for dark in (False, True):
                r = await page_checks(p, AFTER, w, dark, "after")
                report[f"after {w} {'dark' if dark else 'light'}"] = r
                if r["axe"] or r["hscroll"] > 0 or not r["headings_ok"] or r["no_alt"] or not r["stills_loaded"]:
                    fails.append(f"after {w} {'dark' if dark else 'light'}")
        await cdp.Page.reset_auth(p, BEFORE)
        for w in (390, 1440):
            for dark in (False, True):
                report[f"before {w} {'dark' if dark else 'light'}"] = await page_checks(p, BEFORE, w, dark, "before")
        for w, h in ((1440, 900), (390, 844)):
            await cdp.Page.reset_auth(p, BEFORE)
            before = await first_view(p, BEFORE, w, h, "before")
            await cdp.Page.reset_auth(p, AFTER)
            after = await first_view(p, AFTER, w, h, "after")
            box = diff_box(before["fold"], after["fold"])
            rw = after["readwith"]
            # Unchanged apart from the chips: any differing pixel lies inside the chips' row.
            inside = box is None or (rw is not None and box[0] >= rw[0] - 4 and box[1] <= rw[2] + 4
                                     and box[2] >= rw[1] - 4 and box[3] <= rw[3] + 4)
            report[f"first view {w}x{h}"] = {"diff_box": box, "chips": rw, "only_chips_changed": inside,
                                             "new_stills_before_scroll": after["new_stills_before_scroll"]}
            if not inside or after["new_stills_before_scroll"]:
                fails.append(f"first view {w}x{h}")
    finally:
        await ws.close()
        cdp.stop()
    print(json.dumps(report, indent=1))
    print("landing refresh checks:", "all pass" if not fails else f"FAIL {fails}")
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
