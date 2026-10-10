"""Live growth check for M2.2, the way a judge would do it (plan Production writes 3).

    uv run python -m scripts.live_check_m2_2 --url ARTICLE_URL [--api URL] [--persona newcomer]

Runs only after GROWTH_ENABLED is true in production. One Firebase anonymous (demo) reader pastes
one non-business article (POST /v1/content, both phases in one request). Then, before cleanup:
- reads the `graph_growth/` docs grown from it and prints each concept's id, domain, kind,
  definition and prerequisites (for the manual "domain confirmed correct" judgement);
- polls the library as the same reader (up to GROWTH_REFRESH_S + 30 s) until the article is
  listed, and checks that a grown concept appears in that persona's annotations for it.
Pre-flight: the shared anonymous ingest count must be under 30 and the day's growth count must
leave ≥ 5 slots; otherwise it stops and asks to run on the next UTC day.
Cleanup in `finally`: DELETE /v1/me (the reader's whole users/{uid} tree and its Auth user).
Writes kept: 1 contents/ doc, ≤ 5 graph_growth/ docs, the growth day counter, +1 anonymous ingest.
"""

import argparse
import asyncio
import time
from typing import Any

import httpx

from app.ingest.urls import url_hash
from app.store.docstore import get_doc_store
from app.store.growth_repo import get_growth_repo
from app.store.spend_repo import today_utc
from scripts.live_check_explain import API, sign_in_anonymously

ANON_INGEST_CAP, GROWTH_DAY_CAP, SLOTS = 30, 100, 5
POLL_S = 90


async def preflight() -> None:
    day, store = today_utc(), get_doc_store()
    anon = int((await store.get(f"ops/ingest/days/{day}") or {}).get("anonymous", 0))
    grown = await get_growth_repo().used_today(day)
    print(f"pre-flight {day}: anonymous ingests {anon}/{ANON_INGEST_CAP}, "
          f"growth {grown}/{GROWTH_DAY_CAP}")  # fmt: skip
    if anon >= ANON_INGEST_CAP or GROWTH_DAY_CAP - grown < SLOTS:
        raise SystemExit("today's caps are used up: run this on the next UTC day")


async def checks(client: httpx.AsyncClient, api: str, url: str, persona: str) -> None:
    cid = url_hash(url)
    if await get_doc_store().get(f"contents/{cid}"):
        raise SystemExit("this article is already in the library: pick one that isn't")
    started = time.perf_counter()
    resp = await client.post(f"{api}/v1/content", json={"url": url}, timeout=180)
    print(f"1. POST /v1/content → {resp.status_code} in {time.perf_counter() - started:.1f} s")
    resp.raise_for_status()
    grown = [g for g in await get_growth_repo().since(None) if g.source_cid == cid]
    print(f"2. grown from it: {len(grown)}")
    for g in grown:
        c = g.concept
        print(f"   {c.id} | {c.label} | {c.domain} | {c.kind} | {c.jurisdiction} | prereqs "
              f"{c.prerequisites}\n     {c.definition}")  # fmt: skip
    assert grown, "no concept grew from the article"
    ids = {g.concept.id for g in grown}
    deadline = time.monotonic() + POLL_S
    listed: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        items = (await client.get(f"{api}/v1/content?persona={persona}")).json()
        listed = next((i for i in items if i["id"] == cid), None)
        if listed:
            break
        await asyncio.sleep(10)
    assert listed, "the article never appeared in the library"
    print(f"3. listed in the library: concepts_new={listed['concepts_new']}")
    assert listed["concepts_new"] >= 1, "the library row doesn't count any new concept"
    ann = (await client.get(f"{api}/v1/content/{cid}/annotations?persona={persona}")).json()
    hits = sorted({a["concept_id"] for a in ann["annotations"] if a.get("concept_id") in ids})
    print(f"4. grown concepts annotated for {persona}: {hits}")
    assert hits, "no grown concept reached the annotations"


async def run(api: str, url: str, persona: str) -> None:
    await preflight()
    async with httpx.AsyncClient(timeout=90) as client:
        client.headers["Authorization"] = f"Bearer {await sign_in_anonymously(client)}"
        try:
            await checks(client, api, url, persona)
            print("ALL LIVE CHECKS PASSED")
        finally:
            resp = await client.delete(f"{api}/v1/me")
            print(f"cleanup: DELETE /v1/me → {resp.status_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    parser.add_argument("--url", required=True)
    parser.add_argument("--persona", default="newcomer")
    args = parser.parse_args()
    asyncio.run(run(args.api.rstrip("/"), args.url, args.persona))


if __name__ == "__main__":
    main()
