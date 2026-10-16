"""Decision 69 live checks on https://glossreader.web.app after the PR 1 + PR 2 deploy.

    uv run --project apps/api python tools/shots/d69_live.py [FRESH_URL]

One demo reader (landing CTA) then:
1. B: the video's library article (Guardian, Polymarket / HSBC / Lloyds) as the newcomer:
   `basis=story` until settled → "More on this story" first, key-idea reasons, no "new to you".
   Writes: ≤ 2 `rec_cache` `story:*` docs, once ever for that article.
2. A: the newcomer's overview map: solid nodes all with evidence (≥ 12).
3. C: FRESH_URL (default: a page not stored yet) through Open here: phase 1 time, then analysis;
   the log check of the wait before the first model call runs separately (gcloud logging).
   Writes: that article and its analysis, like any Read any link.
The demo reader is deleted at the end (DELETE /v1/me).
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

from live_site import WEB  # noqa: E402

API = "https://readlayer-api-751104670850.asia-south1.run.app"
FRESH = sys.argv[1] if len(sys.argv) > 1 else "https://en.wikipedia.org/wiki/Shrinkflation"


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    out: dict = {}
    try:
        await p.viewport(1440)
        await cdp.Page.reset_auth(p, WEB)
        await p.goto(WEB + "/", wait=4)
        await p.wait_for(".lp-nav__cta", 30)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")  # Try the demo
        await asyncio.sleep(6)

        # 1. the story list on the video's library article
        lib = (await p.api(API, "GET", "/v1/content?persona=newcomer"))["body"]
        art = next(i for i in lib if "Polymarket" in (i.get("title") or ""))
        out["article"] = {"id": art["id"], "title": art["title"][:80]}
        url = f"/v1/content/{art['id']}/recommendations?basis=story&persona=newcomer"
        body: dict = {}
        for _ in range(12):
            body = (await p.api(API, "GET", url))["body"]
            if not body.get("pending"):
                break
            await asyncio.sleep(2)
        whys = [i["why"] for i in body.get("items", [])]
        out["story"] = {
            "pending": body.get("pending"),
            "count": len(whys),
            "first_two": whys[:2],
            "story": sum(w == "More on this story" for w in whys),
            "key_idea": sum("a key idea here" in w for w in whys),
            "new_to_you": sum("new to you" in w for w in whys),
            "formats": [i["format"] for i in body.get("items", [])],
        }

        # 2. the newcomer's map
        ov = (await p.api(API, "GET", "/v1/me/graph?view=overview&persona=newcomer"))["body"]
        solid = [n for n in ov["nodes"] if not n["ready"]]
        out["newcomer_map"] = {"solid": len(solid), "rings": len(ov["nodes"]) - len(solid),
                               "solid_without_evidence": [n["label"] for n in solid if not n["recent"]]}  # fmt: skip

        # 3. a fresh link: phase 1, then the analysis
        t0 = time.monotonic()
        opened = await p.api(API, "POST", "/v1/recs/open", {"url": FRESH})
        o = opened["body"] or {}
        out["open"] = {"status": opened["status"], "new": o.get("new"), "ready": o.get("ready"),
                       "phase1_s": round(time.monotonic() - t0, 1)}  # fmt: skip
        if opened["status"] == 200 and not o.get("ready"):
            t1 = time.monotonic()
            done = await p.api(API, "POST", f"/v1/content/{o['content_id']}/analyse")
            out["analyse"] = {"status": done["status"], "s": round(time.monotonic() - t1, 1),
                              "content_id": o["content_id"]}  # fmt: skip
    finally:
        out["cleanup"] = (await p.api(API, "DELETE", "/v1/me"))["status"]
        print(json.dumps(out, indent=1, ensure_ascii=False))
        await ws.close()
        cdp.stop()


asyncio.run(main())
