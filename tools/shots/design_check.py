"""Design pass checks on the local harness: screenshots + axe + target sizes per page.

    SHOTS_OUT=/tmp/gloss-after uv run --project apps/api python tools/shots/design_check.py library
"""

import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

WEB = "http://localhost:5173"
API = "http://localhost:8000"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))


async def demo(p, persona="Newcomer"):
    await p.reset_auth(WEB)
    await p.goto(WEB + "/", wait=3)
    await p.click_text("button", persona, 5)


async def audit(p, name, path, ready, sizes=SIZES, full=True, scroll=None):
    for w, dark in sizes:
        await p.viewport(w, dark=dark)
        await p.goto(WEB + path, wait=1)
        ok = await p.wait_for(ready, 25)
        await asyncio.sleep(1.2)
        if scroll:
            await p.eval(f"document.querySelector({json.dumps(scroll)})?.scrollIntoView(); 1")
            await asyncio.sleep(0.6)
        a = await p.audit()
        tag = f"{w}-{'dark' if dark else 'light'}"
        shot = await p.shot(f"{name}-{tag}", full=full)
        print(f"[{name} {tag}] ready={ok} axe={a['axe']} hscroll={a['hscroll']} small={json.dumps(a['small'])[:240]} {shot}")


async def main(which):
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.viewport(1440)
        await demo(p)
        if which in ("library", "all"):
            await audit(p, "library-foryou", "/?persona=newcomer", ".rows li, .state")
            await audit(p, "library-topics", "/?tab=topics&persona=newcomer", ".rows li")
            await audit(p, "library-saved", "/?tab=saved&persona=newcomer", ".panel", sizes=((1440, False), (390, True)))
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
