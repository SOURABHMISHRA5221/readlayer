"""Decision 68 PR A live check: a just-opened link gets its card chips once its notes arrive.

    uv run --project apps/api python tools/shots/d68_live.py URL

One demo reader on https://glossreader.web.app opens URL (a page not stored yet, so it goes
through the two-phase "Open here"), waits for its notes, opens the first note and counts the
"Up next" chips. The reader is deleted with DELETE /v1/me. Writes in production: 1 anonymous
reader (deleted), the opened page (stored once, like any Read any link) and its analysis.
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

from live_site import WEB  # noqa: E402

API = "https://readlayer-api-751104670850.asia-south1.run.app"


async def main(url: str) -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    report: dict = {"url": url}
    try:
        await p.viewport(1440)
        await cdp.Page.reset_auth(p, WEB)
        await p.goto(WEB + "/", wait=4)
        await p.wait_for(".lp-nav__cta", 30)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")  # Try it as a demo consumer
        await asyncio.sleep(6)
        opened = await p.api(API, "POST", "/v1/recs/open", {"url": url})
        body = opened["body"] or {}
        report["open"] = {"status": opened["status"], **{k: body.get(k) for k in ("content_id", "new", "ready")}}
        if opened["status"] != 200:
            return
        cid = body["content_id"]
        t0 = time.monotonic()
        await p.goto(f"{WEB}/read/{cid}?persona=newcomer", wait=2)
        marks = 0
        while time.monotonic() - t0 < 150 and not marks:
            await asyncio.sleep(3)
            marks = await p.eval("document.querySelectorAll('.rl-mark').length")
        report["notes_after_s"] = round(time.monotonic() - t0, 1)
        report["marks"] = marks
        await asyncio.sleep(4)  # chips are asked once the notes are in
        await p.eval("document.querySelector('.rl-mark')?.click()")
        await asyncio.sleep(3)
        report["chips"] = await p.eval(
            "Array.from(document.querySelectorAll('.rl-card__next:not([hidden]) a.rl-next'))"
            ".map(a => a.querySelector('.rl-next__verb').textContent + ': ' + a.querySelector('.rl-next__title').textContent)"
        )
        report["chip_requests"] = await p.eval(
            "performance.getEntriesByType('resource').filter(e => e.name.includes('basis=article')).length"
        )
        print("shot", await p.shot("d68-live-card"))
    finally:
        report["cleanup"] = (await p.api(API, "DELETE", "/v1/me"))["status"]
        print(json.dumps(report, indent=1))
        await ws.close()
        cdp.stop()


asyncio.run(main(sys.argv[1]))
