"""Design pass live check: one demo reader on the live site (deleted after through the API)."""

import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

from live_site import WEB  # noqa: E402
API = "https://readlayer-api-751104670850.asia-south1.run.app"


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.viewport(1440)
        await p.reset_auth(WEB)
        await p.goto(WEB + "/", wait=4)
        print("[sign-in] title", await p.eval("document.title"), "| logo", await p.eval("document.querySelector('.wordmark')?.textContent"))
        await p.click_text("button", "Markets trader", 6)
        for path, ready, name in (("/?persona=trader", ".rows li, .state", "library"), ("/profile?persona=trader", ".kmap", "profile")):
            await p.goto(WEB + path, wait=1)
            ok = await p.wait_for(ready, 30)
            await __import__("asyncio").sleep(2)
            a = await p.audit()
            print(f"[{name}] ready={ok} axe={a['axe']} hscroll={a['hscroll']} small={a['small'][:3]}")
        lib = (await p.api(API, "GET", "/v1/content?persona=trader"))["body"]
        art = next((i["id"] for i in lib if i["id"].startswith("2332")), lib[0]["id"])
        await p.goto(WEB + f"/read/{art}?persona=trader", wait=1)
        await p.wait_for(".rl-mark", 40)
        await asyncio.sleep(2)
        a = await p.audit()
        levels = await p.eval("({new: document.querySelectorAll('.rl-mark--new[tabindex]').length, refresher: document.querySelectorAll('.rl-mark--refresher[tabindex]').length})")
        print(f"[reader] axe={a['axe']} hscroll={a['hscroll']} highlights={levels} margin={await p.eval('document.querySelector(\".rail__head\")?.textContent')!r}")
        await p.eval("document.querySelector('.actionbar__helpful').click(); document.querySelector('.actionbar button[aria-label=\"Save\"]').click(); 1")
        ann = (await p.api(API, "GET", f"/v1/content/{art}/annotations?persona=trader"))["body"]
        span = next((x for x in ann["annotations"] if x["kind"] == "span" and x.get("level") == "refresher"), None) or next(x for x in ann["annotations"] if x["kind"] == "span")
        own = (await p.api(API, "POST", "/v1/explain?persona=trader", {"content_id": art, "demand_id": span["id"]}))["body"]
        t = asyncio.get_event_loop().time()
        simp = (await p.api(API, "POST", "/v1/explain?persona=trader", {"content_id": art, "demand_id": span["id"], "shift": -1}))["body"]
        print(f"[simpler] {span['label']}: own {own['band']} ({own['kind']}, cached {own['cached']}) → {simp['band']} ({simp['kind']}, capped {simp.get('capped')}) in {asyncio.get_event_loop().time() - t:.1f} s")
        await asyncio.sleep(7)  # events flush every 5 s
        saved = (await p.api(API, "GET", "/v1/me/saved/ids?persona=trader"))["body"]
        exp = (await p.api(API, "GET", "/v1/me/export"))["body"]
        ev = exp.get("events", {})
        helpful = [e for e in (ev.values() if isinstance(ev, dict) else ev) if e.get("type") == "article_helpful"]
        print(f"[saved] {saved} | article_helpful events {len(helpful)}")
        d = await p.api(API, "DELETE", "/v1/me")
        print("[cleanup] DELETE /v1/me", d["status"])
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
