"""Readiness live check (docs/plans/readiness.md V13, W2): as one demo reader on the live site,
the level counts of GET /v1/feed for each persona, one For you shot, then End demo; afterwards
confirms (read only) that the anonymous Auth user and `users/{uid}` are gone.

    make check-gcp
    SHOTS_OUT=docs/evidence/readiness uv run --project apps/api python tools/shots/readiness_live.py

Writes in production: 1 anonymous reader, its `users/{uid}` and `rec_signals/{persona}` docs
(feed impressions), all deleted by End demo. No search or model call (demo feeds are snapshots).
"""

import asyncio
import json
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp

W = "https://readlayer-sourabh-26.web.app"
API = "https://readlayer-api-d2sfihz3za-el.a.run.app"
PROJECT = "readlayer-sourabh-26"
UID_JS = "JSON.parse(atob(%s.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).user_id"


def gone(uid: str) -> dict:
    """Read only: is the Auth user and its Firestore doc deleted?"""
    import firebase_admin
    from firebase_admin import auth
    from google.cloud import firestore

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": PROJECT})
    try:
        auth.get_user(uid)
        auth_gone = False
    except auth.UserNotFoundError:
        auth_gone = True
    db = firestore.Client(project=PROJECT)
    user = db.collection("users").document(uid)
    subs = [c.id for c in user.collections()]
    return {"auth_user_gone": auth_gone, "users_doc_gone": not user.get().exists, "subcollections": subs}


async def main() -> None:
    out: dict = {}
    cdp.launch()
    p, ws = await cdp.open_page()
    uid = None
    try:
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=4)
        await p.wait_for(".lp-nav__cta", 30)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")
        await asyncio.sleep(6)
        uid = await p.eval(UID_JS % json.dumps(await p.token()))
        for persona in ("newcomer", "trader", "policy_student"):
            r = await p.api(API, "GET", f"/v1/feed?persona={persona}")
            items = (r["body"] or {}).get("items", [])
            out[persona] = {
                "status": r["status"],
                "rows": len(items),
                "levels": dict(Counter(i.get("readiness") or "no line" for i in items)),
                "stretch_lines": [[i["title"], i.get("read_first", [])] for i in items if i.get("readiness") == "stretch"],
            }
            print(f"[{persona}] {out[persona]['status']} {out[persona]['rows']} rows {out[persona]['levels']}", flush=True)
        await p.eval("localStorage.setItem('readlayer:theme', 'light'); 1")
        await p.goto(f"{W}/for-you?persona=newcomer", wait=2)
        await p.wait_for(".row__why", 40)
        await asyncio.sleep(2)
        out["on_screen"] = await p.eval("[...document.querySelectorAll('.row__why')].map(e => e.textContent)")
        print("[shot]", await p.shot("live-foryou-1440-light", full=False), flush=True)
        await p.eval("document.querySelector('.account__chip').click(); 1")
        await asyncio.sleep(1)
        out["end_demo_clicked"] = await p.click_text("button.account__action", "End demo", wait=6)
    finally:
        await ws.close()
        cdp.stop()
    if uid:
        await asyncio.sleep(3)
        out["deleted"] = gone(uid)
        print("[deleted]", out["deleted"], flush=True)
    cdp.OUT.mkdir(parents=True, exist_ok=True)
    (cdp.OUT / "live.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
