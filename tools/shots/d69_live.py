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
# B3 (decision 69 follow-ups): a page a reader brought in, re-opened by URL (stored: no fetch)
OWN = sys.argv[2] if len(sys.argv) > 2 else ""


async def story_list(p, cid: str) -> dict:
    summary, _ = await story_items(p, cid)
    return summary


async def story_items(p, cid: str) -> tuple[dict, list[dict]]:
    url = f"/v1/content/{cid}/recommendations?basis=story&persona=newcomer"
    body: dict = {}
    for _ in range(12):
        body = (await p.api(API, "GET", url))["body"]
        if not body.get("pending"):
            break
        await asyncio.sleep(2)
    items = body.get("items", [])
    ideas: dict[str, int] = {}
    for i in items:
        if i["relation"] != "same_story" and i.get("triggers"):
            ideas[i["triggers"][0]["label"]] = ideas.get(i["triggers"][0]["label"], 0) + 1
    whys = [i["why"] for i in items]
    return {
        "count": len(items),
        "first_two": whys[:2],
        "story": sum(w == "More on this story" for w in whys),
        "new_to_you": sum("new to you" in w for w in whys),
        "per_idea": ideas,
    }, items


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
        out["story"], end_items = await story_items(p, art["id"])
        if OWN:  # B3 on a reader's own page, re-opened by its URL
            own = await p.api(API, "POST", "/v1/recs/open", {"url": OWN})
            ob = own["body"] or {}
            out["own_open"] = {"status": own["status"], "new": ob.get("new")}
            if own["status"] == 200:
                out["own_story"] = await story_list(p, ob["content_id"])

        # B4: a page this reader was shown, not stored yet, opened through Open here. A stored
        # For you article is a library doc (the old rule), so only a `new: true` open counts.
        feed = (await p.api(API, "GET", "/v1/feed?persona=newcomer"))["body"] or {}
        cands = [
            ("for_you", i["url"], i.get("title"))
            for i in feed.get("items", [])
            if i.get("format") == "article"
            and i.get("readiness_basis") != "article"
            and i.get("open_here")
        ]
        cands += [  # web articles from step 1's end list: served to this reader just now
            ("up_next", i["url"], i.get("title"))
            for i in end_items
            if i.get("kind") == "web" and i.get("format") == "article" and i.get("open_here")
        ]
        out["suggested"] = "no unstored openable article was shown"
        for path, link, title in cands:
            opened = await p.api(API, "POST", "/v1/recs/open", {"url": link})
            ob = opened["body"] or {}
            if opened["status"] != 200 or not ob.get("new"):
                continue  # stored already (likely a library doc): not B4 evidence
            await p.api(API, "POST", f"/v1/content/{ob['content_id']}/analyse")
            out["suggested"] = {
                "path": path,
                "title": (title or "")[:70],
                "content_id": ob["content_id"],
                "story": await story_list(p, ob["content_id"]),
            }
            break

        # 2. the newcomer's map
        ov = (await p.api(API, "GET", "/v1/me/graph?view=overview&persona=newcomer"))["body"]
        solid = [n for n in ov["nodes"] if not n["ready"]]
        bare = [n["label"] for n in solid if not n["recent"]]
        rings = len(ov["nodes"]) - len(solid)
        out["newcomer_map"] = {"solid": len(solid), "rings": rings, "solid_without_evidence": bare}

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
            # never shown to this reader: no story search for it
            out["fresh_story"] = await story_list(p, o["content_id"])
    finally:
        out["cleanup"] = (await p.api(API, "DELETE", "/v1/me"))["status"]
        print(json.dumps(out, indent=1, ensure_ascii=False))
        await ws.close()
        cdp.stop()


asyncio.run(main())
