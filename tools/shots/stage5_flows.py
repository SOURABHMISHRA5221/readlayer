"""Design pass acceptance 4/5 on the local harness (emulators; harness LLM budget only)."""

import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
import design_check as dc  # noqa: E402

W = dc.WEB


async def article(p):
    lib = (await p.api("", "GET", "/v1/content?persona=newcomer"))["body"]
    return next((i["id"] for i in lib if i["id"].startswith("2332")), lib[0]["id"])


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.viewport(1440)
        # --- zero interactions: recap shows no band changes
        await dc.demo(p)
        art = await article(p)
        await p.goto(W + f"/read/{art}?persona=newcomer", wait=1)
        await p.wait_for(".rl-mark")
        await asyncio.sleep(2)
        await p.eval("document.querySelector('.recap').scrollIntoView(); 1")
        await asyncio.sleep(4)
        print("[recap, no interaction]", await p.eval("document.querySelector('.recap__lede').textContent"),
              "| rows", await p.eval("document.querySelectorAll('.recap__moves li').length"))
        # --- Say it simpler through the API (same call the card makes)
        ann = (await p.api("", "GET", f"/v1/content/{art}/annotations?persona=newcomer"))["body"]
        span = next(a for a in ann["annotations"] if a["kind"] == "span")
        own = await p.api("", "POST", "/v1/explain?persona=newcomer", {"content_id": art, "demand_id": span["id"]})
        simp = await p.api("", "POST", "/v1/explain?persona=newcomer", {"content_id": art, "demand_id": span["id"], "shift": -1})
        print(f"[simpler] own band={own['body']['band']} kind={own['body']['kind']} | simpler band={simp['body']['band']} kind={simp['body']['kind']} can_simpler={own['body']['can_simpler']}")
        # --- Knew this in the card, then the recap and Undo
        await p.goto(W + f"/read/{art}?persona=newcomer", wait=1)
        await p.wait_for(".rl-mark")
        await asyncio.sleep(2)
        await p.eval("const m = document.querySelector('.rl-mark--new') || document.querySelector('.rl-mark'); m.scrollIntoView({block:'center'}); m.click(); 1")
        await asyncio.sleep(3)
        label = await p.eval("document.querySelector('.rl-card__title').textContent")
        await p.eval("document.querySelector('.rl-card button[data-action=\"knew_this\"]').click(); 1")
        await asyncio.sleep(1)
        await p.key("Escape") if hasattr(p, "key") else None
        await p.eval("document.querySelector('.recap').scrollIntoView(); 1")
        await asyncio.sleep(5)
        rows = await p.eval("[...document.querySelectorAll('.recap__moves li')].map(li => li.innerText.replace(/\\n+/g, ' | '))")
        print(f"[recap after Knew this on {label!r}]", rows)
        undo = await p.eval("(() => { const b = document.querySelector('.recap__moves button'); if (!b) return null; const n = b.getAttribute('aria-label'); b.click(); return n; })()")
        await asyncio.sleep(2)
        print("[undo]", undo, "→", await p.eval("[...document.querySelectorAll('.recap__moves li small')].map(s => s.textContent)"))
        # --- Helpful in the action bar, Save, Saved tab, export
        await p.eval("window.scrollTo(0, 0); document.querySelector('.actionbar__helpful').click(); document.querySelector('.actionbar button[aria-label=\"Save\"]').click(); 1")
        await asyncio.sleep(7)  # events flush every 5 s
        await p.goto(W + "/?tab=saved&persona=newcomer", wait=1)
        await p.wait_for(".rows li, .state")
        print("[saved tab]", await p.eval("[...document.querySelectorAll('.rows .row__title')].map(t => t.textContent.slice(0, 60))"))
        exp = (await p.api("", "GET", "/v1/me/export"))["body"]
        events = exp.get("events", {})
        helpful = [e for e in (events.values() if isinstance(events, dict) else events) if e.get("type") == "article_helpful"]
        print("[export] saved:", list((exp.get("saved") or {}).keys()), "| article_helpful events:", len(helpful))
        # --- persona chip switches persona
        await p.eval("document.querySelector('.persona__chip').click(); 1")
        await asyncio.sleep(0.5)
        await p.eval("[...document.querySelectorAll('.persona__option')].find(o => o.textContent.includes('trader') || o.textContent.includes('Trader')).click(); 1")
        await asyncio.sleep(1.5)
        print("[persona chip] url now", await p.eval("location.search"))
        await p.api("", "DELETE", "/v1/me")
        # --- a brand-new Google (emulator) reader's map is not empty
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.eval("window.__rlEmulatorSignIn('fresh-map@example.com', 'Fresh Map')")
        await asyncio.sleep(4)
        ov = (await p.api("", "GET", "/v1/me/graph?view=overview"))["body"]
        print(f"[new Google reader map] domains={ov['domains']} nodes={len(ov['nodes'])} solid={sum(not n['ready'] for n in ov['nodes'])} rings={sum(n['ready'] for n in ov['nodes'])}")
        await p.api("", "DELETE", "/v1/me")
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
