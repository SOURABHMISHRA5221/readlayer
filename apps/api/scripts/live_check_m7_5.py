"""Live check for M7.5 against the deployed API (demo-reader side; Sourabh checks the
signed-in feed and goals with his own Google account).

    uv run python -m scripts.live_check_m7_5 --url ARTICLE_URL [--api URL]

One Firebase anonymous (demo) reader, deleted in `finally` (DELETE /v1/me):
1. GET /v1/feed?persona=newcomer → the pre-seeded snapshot (`snapshot: true`, items, no search).
2. Goals are signed-in only: GET /v1/me/goals → 403.
3. Read any link: POST /v1/recs/open with one non-business article not in the library → the
   article is readable within 5 s, and a second demo reader's library doesn't list it while the
   first reader's does.
Writes kept: 1 `contents/` doc (source user_ingested), ≤ 5 `graph_growth/` docs, counters.
"""

import argparse
import asyncio
import time

import httpx

from app.ingest.urls import url_hash
from scripts.live_check_explain import API, sign_in_anonymously


async def reader(client: httpx.AsyncClient) -> httpx.AsyncClient:
    token = await sign_in_anonymously(client)
    return httpx.AsyncClient(timeout=90, headers={"Authorization": f"Bearer {token}"})


async def run(api: str, url: str) -> None:
    async with httpx.AsyncClient(timeout=90) as anon:
        a, b = await reader(anon), await reader(anon)
        try:
            feed = (await a.get(f"{api}/v1/feed?persona=newcomer")).json()
            print(f"1. feed: snapshot={feed['snapshot']} prepared_at={feed['prepared_at']} "
                  f"items={len(feed['items'])} topics={feed['topics']}")  # fmt: skip
            assert feed["snapshot"] is True and feed["items"], "demo snapshot missing"
            status = (await a.get(f"{api}/v1/me/goals")).status_code
            print(f"2. goals for a demo reader → {status}")
            assert status == 403
            t = time.perf_counter()
            opened = (await a.post(f"{api}/v1/recs/open", json={"url": url})).json()
            cid = opened["content_id"]
            detail = await a.get(f"{api}/v1/content/{cid}")
            seconds = time.perf_counter() - t
            print(f"3. read any link: {opened} → article {detail.status_code} in {seconds:.1f} s")
            assert detail.status_code == 200 and seconds < 5
            assert cid == url_hash(url)
            await a.post(f"{api}/v1/content/{cid}/analyse", timeout=180)
            mine = {i["id"] for i in (await a.get(f"{api}/v1/content")).json()}
            theirs = {i["id"] for i in (await b.get(f"{api}/v1/content")).json()}
            print(f"   in A's library: {cid in mine}; in B's library: {cid in theirs}")
            assert cid in mine and cid not in theirs
            print("ALL LIVE CHECKS PASSED")
        finally:
            for c in (a, b):
                resp = await c.delete(f"{api}/v1/me")
                print(f"cleanup: DELETE /v1/me → {resp.status_code}")
                await c.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.api.rstrip("/"), args.url))


if __name__ == "__main__":
    main()
