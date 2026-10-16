"""Decision 68 R0 on the local harness: a fresh signed-in account (Auth-emulator "Google")
onboards with Software + India + Watch, opens a library article and reports what a new reader
gets: the end-of-article Up next, the card chips (order), the map's home terms and θ.

    make dev-emulator   # in another terminal
    uv run --project apps/api python tools/shots/d68_fresh.py

Emulators only; the reader is deleted at the end. Model and search calls are real (capped).
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

W = "http://localhost:5173"
EMAIL = f"fresh-{int(time.time())}@example.com"


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    out: dict = {}
    try:
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.eval(f"window.__rlEmulatorSignIn({json.dumps(EMAIL)}, 'Fresh Check')")
        await asyncio.sleep(4)
        out["consent"] = (await p.api("", "POST", "/v1/me/consent", {"version": "consent-v2"}))["status"]
        body = {"field": "software", "interests": ["economics", "finance"], "thinks_in": ["software"],
                "country": "IN", "formats": ["video"]}  # fmt: skip
        out["onboarding"] = (await p.api("", "POST", "/v1/onboarding", body))["status"]
        out["finish"] = (await p.api("", "POST", "/v1/onboarding/finish"))["status"]
        prof = (await p.api("", "GET", "/v1/me/profile"))["body"]
        out["formats"] = prof["onboarding"].get("formats")
        out["theta"] = {d["domain"]: round(d["theta"], 2) for d in prof["domains"] if abs(d["theta"]) > 1e-6}
        lib = (await p.api("", "GET", "/v1/content"))["body"]
        cid = next(i["id"] for i in lib if i.get("kind", "article") == "article")
        await p.goto(f"{W}/read/{cid}", wait=3)
        t0 = time.monotonic()
        marks = 0
        while time.monotonic() - t0 < 60 and not marks:
            await asyncio.sleep(2)
            marks = await p.eval("document.querySelectorAll('.rl-mark').length")
        out["marks"] = marks
        await p.eval("document.querySelector('.reader__end')?.scrollIntoView(); 1")
        recs = 0
        while time.monotonic() - t0 < 90 and not recs:
            await asyncio.sleep(2)
            recs = await p.eval("document.querySelectorAll('.upnext .rec').length")
        out["upnext"] = await p.eval(
            "[...document.querySelectorAll('.upnext .rec')].map(r => r.dataset.format)")
        out["upnext_note"] = await p.eval("document.querySelector('.upnext__note')?.textContent ?? null")
        await p.eval("window.scrollTo(0, 0); document.querySelector('.rl-mark')?.click(); 1")
        await asyncio.sleep(3)
        out["chips"] = await p.eval(
            "[...document.querySelectorAll('.rl-card__next:not([hidden]) .rl-next__verb')].map(v => v.textContent)")
        print("[shot]", await p.shot("d68-fresh-card"))
        graph = (await p.api("", "GET", "/v1/me/graph"))
        out["graph_status"] = graph["status"]
    finally:
        out["delete"] = (await p.api("", "DELETE", "/v1/me"))["status"]
        print(json.dumps(out, indent=1))
        await ws.close()
        cdp.stop()


asyncio.run(main())
