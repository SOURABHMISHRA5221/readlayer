"""Design pass stage 5 checks: reduced motion, the extension icon PNG, harness flows."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
import design_check as dc  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


async def icon(p):
    svg = (ROOT / "apps/web/public/favicon.svg").read_text()
    await p.viewport(128, 128)
    await p.goto("data:text/html,<style>html,body{margin:0;background:transparent}</style>" + svg.replace("<svg ", '<svg width="128" height="128" ').replace("#", "%23"), wait=1)
    r = await p.send("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": 128, "height": 128, "scale": 1})
    import base64
    out = ROOT / "apps/web/public/margo-mark-128.png"
    out.write_bytes(base64.b64decode(r["data"]))
    print("[icon]", out, out.stat().st_size, "bytes")


async def reduced(p):
    await dc.demo(p)
    await p.viewport(1440, reduced=True)
    await p.goto(dc.WEB + "/?persona=newcomer", wait=1)
    await p.wait_for(".rows li, .state")
    lib = (await p.api("", "GET", "/v1/content?persona=newcomer"))["body"]
    art = next((i["id"] for i in lib if i["id"].startswith("2332")), lib[0]["id"])
    await p.goto(dc.WEB + f"/read/{art}?persona=newcomer", wait=1)
    await p.wait_for(".rl-mark")
    await asyncio.sleep(1)
    blink = await p.eval("getComputedStyle(document.querySelector('.margo--blink .margo__eye') || document.body).animationName")
    await p.goto(dc.WEB + "/profile?persona=newcomer", wait=1)
    await p.wait_for(".kmap__node")
    pop = await p.eval("[...document.querySelectorAll('.kmap__node--new')].map(n => getComputedStyle(n).animationName)")
    print(f"[reduced motion] margo blink animation={blink!r}; map pop animations={sorted(set(pop)) or 'no new nodes'}")


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await icon(p)
        await reduced(p)
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
