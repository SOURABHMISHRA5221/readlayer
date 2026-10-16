"""Decision 69 PR 2 on the local harness: the honest map (A), the story Up next (B) and the
"consume" wording (F). A fresh signed-in account (Auth-emulator "Google") onboards with Software +
India + Sports, answers two Quick check rows, then:

- the overview map holds only evidence: every solid node has recent evidence, rings only;
- the profile page (map, topic view legend) and the landing, library and onboarding pages: axe,
  horizontal scroll and small targets at 1440 / 390, light and dark;
- a library article's end-of-article list: "More on this story" items lead, the rest say "a key
  idea here", none says "new to you".

    make dev-emulator   # in another terminal
    SHOTS_OUT=docs/evidence/d69 uv run --project apps/api python tools/shots/d69.py

Emulators only; the account is deleted at the end. Model and search calls are real (capped).
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

W = "http://localhost:5173"
EMAIL = f"d69-{int(time.time())}@example.com"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))


async def audit_all(p, name, path, ready):
    out = {}
    for w, dark in SIZES:
        await p.viewport(w, dark=dark)
        await p.eval(f"localStorage.setItem('readlayer:theme', '{'dark' if dark else 'light'}'); 1")
        await p.goto(W + path, wait=1)
        ok = await p.wait_for(ready, 40)
        await asyncio.sleep(1.5)
        a = await p.audit()
        tag = f"{w}-{'dark' if dark else 'light'}"
        await p.shot(f"{name}-{tag}", full=True)
        out[tag] = {"ready": ok, "axe": a["axe"], "hscroll": a["hscroll"], "small": a["small"][:3]}
    return out


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    out: dict = {}
    try:
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        out["landing_hero"] = await p.eval("document.querySelector('.lp-hero h1, h1')?.textContent")
        out["landing"] = await audit_all(p, "landing", "/", ".lp")  # signed out: the landing
        await p.viewport(1440)
        await p.goto(W + "/", wait=2)
        await p.eval(f"window.__rlEmulatorSignIn({json.dumps(EMAIL)}, 'D69 Check')")
        await asyncio.sleep(4)
        await p.api("", "POST", "/v1/me/consent", {"version": "consent-v2"})
        body = {"field": "software", "interests": ["sports", "science"], "thinks_in": ["software"],
                "country": "IN", "formats": ["article", "video"]}  # fmt: skip
        out["onboarding"] = (await p.api("", "POST", "/v1/onboarding", body))["status"]
        qs = (await p.api("", "GET", "/v1/calibration/set"))["body"]
        for item, answer in zip(qs.get("items", [])[::-1][:2], ("explain", "none"), strict=False):
            await p.api("", "POST", "/v1/calibration/answer",
                        {"concept_id": item["concept_id"], "answer": answer})  # fmt: skip
        out["finish"] = (await p.api("", "POST", "/v1/onboarding/finish"))["status"]

        # A: the overview map holds only evidence
        ov = (await p.api("", "GET", "/v1/me/graph?view=overview"))["body"]
        solid = [n for n in ov["nodes"] if not n["ready"]]
        out["map"] = {
            "domains": ov["domains"],
            "solid": len(solid),
            "rings": len(ov["nodes"]) - len(solid),
            "solid_without_evidence": [n["label"] for n in solid if not n["recent"]],
            "evidence_types": sorted({e["type"] for n in solid for e in n["recent"]}),
        }
        prof = (await p.api("", "GET", "/v1/me/profile"))["body"]
        out["summary"] = prof["summary"]["text"]  # A2: only topics whose level was set or moved
        out["rated"] = sorted(d["domain"] for d in prof["domains"] if d["rated"])
        out["known_unrated"] = sorted(d["domain"] for d in prof["domains"]
                                      if not d["rated"] and d.get("known", 0) > 0)  # fmt: skip
        out["profile"] = await audit_all(p, "profile", "/profile", ".kmap")
        await p.viewport(1440)
        await p.goto(W + "/profile", wait=2)
        await p.wait_for(".kmap__legend", 30)
        await p.eval("[...document.querySelectorAll('.kmap .filter')].find(b => b.textContent.trim() === 'Sports')?.click(); 1")
        await asyncio.sleep(2)
        out["topic_legend"] = await p.eval("[...document.querySelectorAll('.kmap__legend li')].map(l => l.textContent.trim())")
        print("[shot]", await p.shot("profile-topic-sports-1440-light", full=True))

        # B: a library article's end-of-article list
        lib = (await p.api("", "GET", "/v1/content"))["body"]
        cid = next(i["id"] for i in lib if i.get("kind", "article") == "article")
        out["article"] = cid
        await p.goto(f"{W}/read/{cid}", wait=3)
        await p.eval("document.querySelector('.upnext')?.scrollIntoView(); 1")
        whys: list[str] = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            await asyncio.sleep(3)
            whys = await p.eval("[...document.querySelectorAll('.upnext .rec .rec__why')].map(e => e.textContent)")
            live = await p.eval("document.querySelector('.upnext__note--live') !== null")
            if whys and any(w == "More on this story" for w in whys) and not live:
                break
        out["upnext"] = {
            "count": len(whys),
            "first_two": whys[:2],
            "story": sum(w == "More on this story" for w in whys),
            "key_idea": sum("a key idea here" in w for w in whys),
            "new_to_you": sum("new to you" in w for w in whys),
            "other": [w for w in whys if w != "More on this story" and "a key idea here" not in w],
        }
        print("[shot]", await p.shot("upnext-story-1440-light", full=True))

        # F: wording in the signed-in library
        out["library"] = await audit_all(p, "library", "/", ".topbar")
        out["delete"] = (await p.api("", "DELETE", "/v1/me"))["status"]

        # A2 on a demo persona: its summary still names every topic its level is set in
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.wait_for(".lp-nav__cta", 30)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")
        await asyncio.sleep(6)
        demo = (await p.api("", "GET", "/v1/me/profile?persona=newcomer"))["body"]
        out["newcomer_summary"] = demo["summary"]["text"]
        out["newcomer_rated"] = sorted(d["domain"] for d in demo["domains"] if d["rated"])
    finally:
        out["cleanup"] = (await p.api("", "DELETE", "/v1/me"))["status"]
        print(json.dumps(out, indent=1))
        await ws.close()
        cdp.stop()


asyncio.run(main())
