"""Decision 68 R0 on the local harness: a fresh signed-in account (Auth-emulator "Google")
onboards with Software + India + Watch, opens a library article and reports what a new reader
gets: the end-of-article Up next, the card chips (order), the map's home terms (count, entries,
bands, no band move), θ, "moved up this week", and the feed's formats per topic.

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
        out["moved_up_this_week"] = prof["summary"].get("moved_up_this_week")
        export = (await p.api("", "GET", "/v1/me/export"))["body"]
        knows = export.get("knows") or {}
        knows = knows.values() if isinstance(knows, dict) else knows
        home = [k for k in knows if any(e.get("type") == "home_country" for e in k.get("evidence", []))]
        out["home_edges"] = len(home)
        out["home_entries_each"] = sorted({sum(e.get("type") == "home_country" for e in k["evidence"]) for k in home})
        out["home_bands"] = {b: sum(k.get("band") == b for k in home) for b in ("unaware", "heard of", "understands", "can explain")}
        out["home_band_moves"] = sum(bool(k.get("band_changed_at")) for k in home)
        out["edges_total"] = sum(1 for _ in (export.get("knows") or {}))
        feed = (await p.api("", "GET", "/v1/feed"))["body"]
        for _ in range(10):
            if not feed.get("pending"):
                break
            await asyncio.sleep(3)
            feed = (await p.api("", "GET", "/v1/feed"))["body"]
        per_topic = {}
        for i in feed.get("items", []):
            per_topic.setdefault(i["topic"], {}).setdefault(i["format"], 0)
            per_topic[i["topic"]][i["format"]] += 1
        out["feed_formats_per_topic"] = per_topic
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
