"""Warm the explanation cache for demo articles, the way the reader's prefetch would.

    uv run python -m scripts.warm_demo [--api URL] [--top 3] CONTENT_ID ...

One Firebase anonymous (demo) user, deleted in `finally`. For every article and persona it asks
for the top spans' explanations (pass 1: generates what's missing), then asks again (pass 2:
every one should be a cache hit). Generations cost cents; the restatement is shared across
personas, so only Backgrounds are per persona. Run after any prompt-version change.
"""

import argparse
import asyncio
import time

import httpx

from scripts.live_check_explain import API, PERSONAS, sign_in_anonymously

DEMO_ARTICLES = (
    "2332418841faa08d5f5e157c2d038d1d",  # ET markets preview (M5 "depth adapts" exhibit)
    "99a2cb53f16256bd275bafd180364134",  # Guardian, Polymarket bets on HSBC ("three frames")
    "1bff839e2ef3b017b35a89fce1653a26",  # ET, RoDTEP extension (M6 extras)
)


async def top_spans(client: httpx.AsyncClient, api: str, cid: str, persona: str, n: int):
    resp = await client.get(f"{api}/v1/content/{cid}/annotations?persona={persona}")
    resp.raise_for_status()
    spans = [a for a in resp.json()["annotations"] if a["kind"] == "span"]
    return sorted(spans, key=lambda a: -a["score"])[:n]


async def explain(client: httpx.AsyncClient, api: str, cid: str, demand: str, persona: str):
    t = time.perf_counter()
    resp = await client.post(
        f"{api}/v1/explain?persona={persona}",
        json={"content_id": cid, "demand_id": demand},
        timeout=150,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["cached"], body["kind"], round((time.perf_counter() - t) * 1000)


async def warm(client: httpx.AsyncClient, api: str, articles: list[str], n: int) -> None:
    for pass_no in (1, 2):
        if pass_no == 2:
            await asyncio.sleep(61)  # demo readers get 30 explain calls a minute
        rows = []
        for cid in articles:
            for persona in PERSONAS:
                spans = await top_spans(client, api, cid, persona, n)
                results = await asyncio.gather(
                    *(explain(client, api, cid, s["id"], persona) for s in spans)
                )
                rows += [
                    (cid[:8], persona, s["id"], *r) for s, r in zip(spans, results, strict=True)
                ]
        hits = sum(r[3] for r in rows)
        kinds = {k: sum(r[4] == k for r in rows) for k in ("verified", "definition")}
        slowest = max((r[5] for r in rows), default=0)
        print(
            f"pass {pass_no}: {len(rows)} cards, {hits} cache hits, {kinds}, slowest {slowest} ms"
        )


async def dry_run(client: httpx.AsyncClient, api: str, articles: list[str], n: int) -> None:
    """List the (article, persona, span) explanations a real run would request; generates
    nothing (annotations only, no POST /v1/explain)."""
    total = 0
    for cid in articles:
        for persona in PERSONAS:
            for s in await top_spans(client, api, cid, persona, n):
                total += 1
                print(f"  {cid[:8]} {persona:15s} {s['id']:6s} {s.get('label', '')}")
    print(f"dry run: {total} explanation requests would be made (nothing generated)")


async def run(api: str, articles: list[str], n: int, dry: bool = False) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        client.headers["Authorization"] = f"Bearer {await sign_in_anonymously(client)}"
        try:
            if dry:
                await dry_run(client, api, articles, n)
            else:
                await warm(client, api, articles, n)
        finally:
            resp = await client.delete(f"{api}/v1/me")
            print(f"cleanup: DELETE /v1/me → {resp.status_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("articles", nargs="*", default=list(DEMO_ARTICLES))
    parser.add_argument("--api", default=API)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="list requests, generate nothing")
    args = parser.parse_args()
    asyncio.run(run(args.api.rstrip("/"), args.articles, args.top, args.dry_run))


if __name__ == "__main__":
    main()
