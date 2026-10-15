"""Pre-ingest the demo feeds' first-page articles (plan docs/plans/oct16.md S6), so a judge's
click opens a stored page instead of waiting for "reading the page".

    uv run python -m scripts.preingest_feed --dry-run   # counters, the cap, the URL list
    uv run python -m scripts.preingest_feed             # post them to the live API

The articles a fresh demo reader sees on each persona's first page (selected in memory exactly as
GET /v1/feed does, like `readiness_mix`), newcomer's and trader's first, each URL once. They go
through the live `POST /v1/content` as a judge's click would (growth included), from anonymous
demo users of ≤ ANON_INGEST_DAILY_CAP URLs each, every user deleted in `finally`. The shared
anonymous allowances are read first: the run takes at most min(20, shared cap − used − 10) URLs,
leaving ≥ 10 ingests a day for people, and stops when fewer than 25 anonymous growth slots are
left. Production writes: ≤ 20 content docs and their grown concepts. Cost ≈ $0.012 an article.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime

import httpx

from scripts.live_check_explain import API, sign_in_anonymously

URLS_MAX = 20
LEAVE_FOR_PEOPLE = 10
GROWTH_MIN_LEFT = 25
PERSONA_ORDER = ("newcomer", "trader", "policy_student")
PACE_S = 2.0


def url_cap(used: int, shared_cap: int) -> int:
    return max(0, min(URLS_MAX, shared_cap - used - LEAVE_FOR_PEOPLE))


def ordered_urls(rows: Mapping[str, Sequence[str]]) -> list[str]:
    """Each persona's article URLs in PERSONA_ORDER, each URL once (its first place wins)."""
    return list(dict.fromkeys(u for p in PERSONA_ORDER for u in rows.get(p, ())))


async def run(
    urls: Sequence[str],
    cap: int,
    growth_left: Callable[[], Awaitable[int]],
    post: Callable[[str], Awaitable[str]],
) -> list[tuple[str, str]]:
    """Post up to `cap` URLs in order; before each, stop if growth slots ran low."""
    done: list[tuple[str, str]] = []
    for url in urls[:cap]:
        left = await growth_left()
        if left < GROWTH_MIN_LEFT:
            done.append((url, f"stopped: {left} growth slots left"))
            break
        done.append((url, await post(url)))
    return done


async def first_page_articles() -> dict[str, list[str]]:
    from app.config import get_settings
    from app.graph.loader import get_graph, load_serving_graph
    from app.recs import feed_rank as fr
    from app.recs.feed import PERSONA_COUNTRY, SnapshotRepo, side_for, snapshot_candidates
    from app.recs.outlets import LOCAL_SHARE
    from app.recs.rank import PERSONA_FORMAT_PRIORS
    from app.store.docstore import get_doc_store
    from app.store.persona_repo import get_template
    from app.store.reader_repo import state_from_demo

    await load_serving_graph(get_settings().concepts_uri)
    graph, now, store = get_graph(), datetime.now(UTC), get_doc_store()
    out: dict[str, list[str]] = {}
    for persona in PERSONA_ORDER:
        snap = await SnapshotRepo(store).get(persona)
        if snap is None:
            continue
        reader = fr.FeedReader(
            state=state_from_demo("preingest", persona, await get_template(store, persona), False),
            interest=dict.fromkeys(snap.topics, 1.0),
            prior=PERSONA_FORMAT_PRIORS[persona],
        )
        ranked = fr.rank(snapshot_candidates(snap, graph), reader, now, graph)
        rows = fr.select(ranked, list(snap.topics), side_for(PERSONA_COUNTRY), LOCAL_SHARE)
        out[persona] = [
            r.candidate.result.url for r in rows if r.candidate.result.format == "article"
        ]
    return out


async def counters(day: str) -> tuple[int, int]:
    """(anonymous ingests used today, anonymous growth slots used today)."""
    from app.store.docstore import get_doc_store

    store = get_doc_store()
    ingest = await store.get(f"ops/ingest/days/{day}") or {}
    growth = await store.get(f"ops/growth/anon_days/{day}") or {}
    return int(ingest.get("anonymous", 0)), int(growth.get("count", 0))


class Poster:
    """Posts as anonymous demo users, a new one every `per_user` URLs, each deleted after."""

    def __init__(self, client: httpx.AsyncClient, per_user: int) -> None:
        self.client, self.per_user, self.used = client, per_user, 0

    async def _rotate(self) -> None:
        if "Authorization" in self.client.headers:
            await self.close()
        self.client.headers["Authorization"] = f"Bearer {await sign_in_anonymously(self.client)}"
        self.used = 0

    async def close(self) -> None:
        if "Authorization" in self.client.headers:
            resp = await self.client.delete(f"{API}/v1/me")
            print(f"  cleanup: DELETE /v1/me → {resp.status_code}")
            del self.client.headers["Authorization"]

    async def __call__(self, url: str) -> str:
        if "Authorization" not in self.client.headers or self.used >= self.per_user:
            await self._rotate()
        self.used += 1
        await asyncio.sleep(PACE_S)
        resp = await self.client.post(f"{API}/v1/content", json={"url": url})
        body = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        print(f"  {resp.status_code} {body.get('status') or body.get('error')} {url}")
        return f"{resp.status_code} {body.get('content_id') or body.get('error')}"


async def grow_pending(content_ids: Sequence[str]) -> list[str]:
    from app.store.content_repo import get_content_store

    store, out = get_content_store(), []
    for cid in content_ids:
        doc = await store.get(cid)
        if doc is not None and doc.grow_pending:
            out.append(cid)
    return out


async def main(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.store.spend_repo import today_utc

    settings = get_settings()
    print(f"project {settings.db_project}  api {API}")
    day = today_utc()
    used, grown = await counters(day)
    cap = url_cap(used, settings.anon_global_ingest_daily_cap)
    print(
        f"{day}: anonymous ingests used {used}/{settings.anon_global_ingest_daily_cap}, "
        f"anonymous growth used {grown}/{settings.anon_growth_daily_cap}"
    )
    print(f"cap this run {cap}")
    urls = ordered_urls(await first_page_articles())
    print(f"{len(urls)} first-page articles, posting {min(cap, len(urls))}:")
    for u in urls[:cap]:
        print(f"  {u}")
    if args.dry_run:
        print("dry run: nothing posted")
        return 0

    async def growth_left() -> int:
        return settings.anon_growth_daily_cap - (await counters(day))[1]

    async with httpx.AsyncClient(timeout=180) as client:
        poster = Poster(client, settings.anon_ingest_daily_cap)
        try:
            done = await run(urls, cap, growth_left, poster)
        finally:
            await poster.close()
    ids = [r.split(" ", 1)[1] for _, r in done if r.startswith("200 ")]
    after = await counters(day)
    print(
        f"posted {len(done)}, stored {len(ids)}; counters after: ingests {after[0]}, "
        f"growth {after[1]}"
    )
    print(f"grow_pending: {await grow_pending(ids) or 'none'}")
    return 0 if len(ids) == len(done) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
