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


PER_MINUTE = 28  # demo readers get 30 explain calls a minute
ANON_CAP = 40  # ANON_EXPLAIN_DAILY_CAP: uncached generations per demo reader per day


class Pace:
    """Keeps requests under the demo per-minute explain limit."""

    def __init__(self) -> None:
        self.sent: list[float] = []

    async def wait(self, n: int) -> None:
        now = time.monotonic()
        self.sent = [t for t in self.sent if now - t < 60]
        if len(self.sent) + n > PER_MINUTE:
            await asyncio.sleep(61 - (now - self.sent[0]) if self.sent else 0)
            self.sent = []
        self.sent += [time.monotonic()] * n


async def explain(
    client: httpx.AsyncClient, api: str, cid: str, demand: str, persona: str, shift: int = 0
):
    t = time.perf_counter()
    resp = await client.post(
        f"{api}/v1/explain?persona={persona}",
        json={"content_id": cid, "demand_id": demand, **({"shift": shift} if shift else {})},
        timeout=150,
    )
    resp.raise_for_status()
    body = resp.json()
    return (
        body["cached"],
        body["kind"],
        round((time.perf_counter() - t) * 1000),
        body.get("capped", False),
    )


async def warm(
    client: httpx.AsyncClient, api: str, articles: list[str], n: int, shifts: tuple[int, ...] = (0,)
) -> int:
    """Two passes over the articles; returns how many cards the daily cap stopped."""
    pace = Pace()
    for pass_no in (1, 2):
        if pass_no == 2:
            await asyncio.sleep(61)  # demo readers get 30 explain calls a minute
        rows = []
        for cid in articles:
            for persona in PERSONAS:
                spans = await top_spans(client, api, cid, persona, n)
                jobs = [(s, sh) for s in spans for sh in shifts]
                await pace.wait(len(jobs))
                results = await asyncio.gather(
                    *(explain(client, api, cid, s["id"], persona, sh) for s, sh in jobs)
                )
                rows += [
                    (cid[:8], persona, s["id"], *r) for (s, _), r in zip(jobs, results, strict=True)
                ]
        hits = sum(r[3] for r in rows)
        capped = sum(r[6] for r in rows)
        kinds = {k: sum(r[4] == k and not r[6] for r in rows) for k in ("verified", "definition")}
        slowest = max((r[5] for r in rows), default=0)
        print(
            f"pass {pass_no}: {len(rows)} cards, {hits} cache hits, {kinds}, capped {capped}, "
            f"slowest {slowest} ms"
        )
    return capped


async def dry_run(
    client: httpx.AsyncClient, api: str, articles: list[str], n: int, shifts: tuple[int, ...] = (0,)
) -> None:
    """List the (article, persona, span) explanations a real run would request; generates
    nothing (annotations only, no POST /v1/explain)."""
    total = 0
    for cid in articles:
        for persona in PERSONAS:
            for s in await top_spans(client, api, cid, persona, n):
                total += len(shifts)
                print(
                    f"  {cid[:8]} {persona:15s} {s['id']:6s} {s.get('label', '')} shifts {shifts}"
                )
    print(
        f"dry run: {total} explanation requests for {articles[0][:8]} "
        f"(cap {ANON_CAP} per demo reader, one reader per article; nothing generated)"
    )
    if total > ANON_CAP:
        print(f"WARNING: {total} > {ANON_CAP}: some cards would come back capped")


async def run(
    api: str, articles: list[str], n: int, dry: bool = False, shifts: tuple[int, ...] = (0,)
) -> int:
    """One temporary demo reader per article, so no reader passes the anonymous explain cap
    (3 personas × n spans × len(shifts) ≤ 27 at the defaults); each is deleted in finally."""
    capped = 0
    for cid in articles:
        async with httpx.AsyncClient(timeout=60) as client:
            client.headers["Authorization"] = f"Bearer {await sign_in_anonymously(client)}"
            try:
                if dry:
                    await dry_run(client, api, [cid], n, shifts)
                else:
                    capped += await warm(client, api, [cid], n, shifts)
            finally:
                resp = await client.delete(f"{api}/v1/me")
                print(f"cleanup: DELETE /v1/me → {resp.status_code}")
    if capped:
        print(f"FAILED: {capped} cards were capped; they are not warm")
    return capped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("articles", nargs="*", default=list(DEMO_ARTICLES))
    parser.add_argument("--api", default=API)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="list requests, generate nothing")
    parser.add_argument(
        "--shifts", action="store_true", help="also warm the ±1-band Backgrounds (simpler/deeper)"
    )
    args = parser.parse_args()
    shifts = (0, -1, 1) if args.shifts else (0,)
    capped = asyncio.run(run(args.api.rstrip("/"), args.articles, args.top, args.dry_run, shifts))
    raise SystemExit(1 if capped else 0)


if __name__ == "__main__":
    main()
