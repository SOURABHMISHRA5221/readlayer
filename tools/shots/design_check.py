"""Design pass checks on the local harness: screenshots + axe + target sizes per page.

    SHOTS_OUT=/tmp/gloss-after uv run --project apps/api python tools/shots/design_check.py library
"""

import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

WEB = "http://localhost:5173"
API = ""  # the Vite dev server proxies /v1
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
        if which in ("reader", "all"):
            lib = (await p.api(API, "GET", "/v1/content?persona=newcomer"))["body"]
            art = next((i["id"] for i in lib if i["id"].startswith("2332")), lib[0]["id"])
            await audit(p, "reader", f"/read/{art}?persona=newcomer", ".rl-mark, .reader__notice")
            await p.viewport(1440)
            await demo(p)  # a fresh demo reader: the page loads above use up the per-minute limit
            for w, dark, name in ((1440, False, "card"), (1440, True, "card"), (390, False, "sheet"), (390, True, "sheet")):
                await p.viewport(w, dark=dark)
                await p.goto(WEB + f"/read/{art}?persona=newcomer", wait=1)
                await p.wait_for(".rl-mark")
                await asyncio.sleep(1)
                await p.eval("const m = document.querySelector('.rl-mark'); m.scrollIntoView({block: 'center'}); m.click(); 1")
                await asyncio.sleep(6)
                a = await p.audit()
                tag = f"{w}-{'dark' if dark else 'light'}"
                print(f"[reader {name} {tag}] axe={a['axe']} hscroll={a['hscroll']} small={json.dumps(a['small'])[:200]}", await p.shot(f"reader-{name}-{tag}"))
            await p.viewport(1440)
            await demo(p)
            await p.goto(WEB + f"/read/{art}?persona=newcomer", wait=1)
            await p.wait_for(".rl-mark")
            await asyncio.sleep(1)
            await p.eval("const m = document.querySelector('.rl-mark'); m.scrollIntoView({block: 'center'}); m.click(); 1")
            await asyncio.sleep(4)
            await p.eval("document.querySelector('.rl-card button[data-action=\"knew_this\"]').click(); 1")
            await asyncio.sleep(1)
            await p.eval("document.querySelector('.recap').scrollIntoView(); 1")
            await asyncio.sleep(5)
            a = await p.audit()
            undo = await p.eval("[...document.querySelectorAll('.recap button')].map(b => b.getAttribute('aria-label') + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height))")
            print(f"[recap 1440] axe={a['axe']} undo={undo}", await p.shot("reader-recap-1440-light"))
        if which in ("profile", "all"):
            await audit(p, "profile", "/profile?persona=newcomer", ".kmap__canvas svg, .clist")
            for w, dark in ((1440, True), (390, False)):
                await p.viewport(w, dark=dark)
                await p.goto(WEB + "/profile?persona=newcomer", wait=1)
                await p.wait_for(".kmap")
                await asyncio.sleep(1.5)
                await p.eval("document.querySelector('.kmap').scrollIntoView(); (document.querySelector('.kmap__node') || document.querySelector('.clist__item')).dispatchEvent(new MouseEvent('click', {bubbles: true})); 1")
                await asyncio.sleep(1)
                a = await p.audit()
                print(f"[map {w}-{'dark' if dark else 'light'}] axe={a['axe']} hscroll={a['hscroll']}", await p.shot(f"profile-map-{w}-{'dark' if dark else 'light'}"))
            await p.viewport(1440)
            await p.goto(WEB + "/profile?persona=newcomer", wait=1)
            await p.wait_for(".kmap__node")
            await asyncio.sleep(1)
            await p.eval("document.querySelector('.kmap').scrollIntoView(); document.querySelector('.kmap__node').focus(); 1")
            await p.send("Input.dispatchKeyEvent", type="keyDown", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39)
            await p.send("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r")
            await asyncio.sleep(1)
            focused = await p.eval("document.activeElement.getAttribute('aria-label')")
            title = await p.eval("document.querySelector('.inspect__title')?.textContent")
            tabstops = await p.eval("document.querySelectorAll('.kmap__node[tabindex=\"0\"]').length")
            print(f"[map keyboard] focused={focused!r} inspector={title!r} tab stops={tabstops}")
            a = await p.audit()
            print("[map inspector 1440] axe", a["axe"], await p.shot("profile-map-1440-light"))
        if which in ("library", "all"):
            await audit(p, "library-foryou", "/?persona=newcomer", ".rows li, .state")
            await audit(p, "library-topics", "/?tab=topics&persona=newcomer", ".rows li")
            await audit(p, "library-saved", "/?tab=saved&persona=newcomer", ".panel")
            await p.reset_auth(WEB)
            await audit(p, "signin", "/", ".signin__title")
    finally:
        await ws.close()
        cdp.stop()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
