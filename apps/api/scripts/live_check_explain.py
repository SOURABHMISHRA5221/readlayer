"""Live check for M5 against the deployed API (or a local one).

    uv run python -m scripts.live_check_explain [--api URL] [--content-id ID]

Signs in one Firebase anonymous (demo) user with the web app's public API key, then:
generate (miss) → same request (hit) → the three personas (different Background) → "This is
wrong" (evicts, review doc written) → regenerate. Prints latencies. The test user's data and
Auth account are deleted in `finally` (DELETE /v1/me). Generations count against the LLM
budget (a few cents).
"""

import argparse
import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.store.docstore import FirestoreDocStore
from app.store.explain_repo import REPORTS

API = "https://readlayer-api-d2sfihz3za-el.a.run.app"
PROJECT = "readlayer-sourabh-26"
WEB_ENV = Path(__file__).resolve().parents[3] / "apps" / "web" / ".env.local"  # make web-config
PERSONAS = ("newcomer", "trader", "policy_student")
# Economic Times markets preview (same article as scripts/explain_demo.py).
DEFAULT_CONTENT = "2332418841faa08d5f5e157c2d038d1d"


def web_api_key() -> str:
    """The Firebase web API key (public; it ships in the web bundle)."""
    if key := os.environ.get("FIREBASE_WEB_API_KEY"):
        return key
    for line in WEB_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("VITE_FIREBASE_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no Firebase web API key: set FIREBASE_WEB_API_KEY or run make web-config")


async def sign_in_anonymously(client: httpx.AsyncClient) -> str:
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={web_api_key()}"
    resp = await client.post(url, json={"returnSecureToken": True})
    resp.raise_for_status()
    return resp.json()["idToken"]


async def explain(
    client: httpx.AsyncClient, api: str, content_id: str, demand_id: str, persona: str
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    resp = await client.post(
        f"{api}/v1/explain?persona={persona}",
        json={"content_id": content_id, "demand_id": demand_id},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json(), (time.perf_counter() - started) * 1000


async def run(api: str, content_id: str) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        token = await sign_in_anonymously(client)
        client.headers["Authorization"] = f"Bearer {token}"
        try:
            await checks(client, api, content_id)
        finally:
            resp = await client.delete(f"{api}/v1/me")
            print(f"cleanup: DELETE /v1/me → {resp.status_code}")


async def checks(client: httpx.AsyncClient, api: str, content_id: str) -> None:
    resp = await client.get(f"{api}/v1/content/{content_id}/annotations?persona=newcomer")
    resp.raise_for_status()
    spans = [a for a in resp.json()["annotations"] if a["kind"] == "span"]
    top = max(spans, key=lambda a: a["score"])
    demand = top["id"]
    print(f"article {content_id}, span {demand} “{top['anchor']['exact']}” ({top['label']})")

    first, miss_ms = await explain(client, api, content_id, demand, "newcomer")
    second, hit_ms = await explain(client, api, content_id, demand, "newcomer")
    print(f"generate: kind={first['kind']} cached={first['cached']} {miss_ms:.0f} ms")
    print(f"repeat:   kind={second['kind']} cached={second['cached']} {hit_ms:.0f} ms")
    assert second["cached"] and second["id"] == first["id"], "second request was not a hit"

    cards = {"newcomer": first}
    for persona in PERSONAS[1:]:
        cards[persona], ms = await explain(client, api, content_id, demand, persona)
        print(f"{persona}: kind={cards[persona]['kind']} band={cards[persona]['band']} "
              f"frame={cards[persona]['thinks_in']} {ms:.0f} ms")  # fmt: skip
    for persona, card in cards.items():
        print(f"\n[{persona}] Background: {card['background']}\n"
              f"[{persona}] Author says: {card['author_says']}")  # fmt: skip
    backgrounds = {c["background"] for c in cards.values() if c["kind"] == "verified"}
    print(f"\ndistinct Backgrounds: {len(backgrounds)} of {len(cards)}")

    if first["kind"] != "verified":
        print("newcomer card is definition-only; report check skipped")
        return
    event_id = uuid.uuid4().hex
    resp = await client.post(
        f"{api}/v1/explain/{first['id']}/report?persona=newcomer",
        json={"event_id": event_id, "content_id": content_id, "concept_id": top["concept_id"]},
    )
    resp.raise_for_status()
    print(f"\nreport: {resp.json()}")
    review = await FirestoreDocStore(PROJECT).get(f"{REPORTS}/{first['id'][:16]}-{event_id}")
    print(f"review doc written: {review is not None}")
    again, ms = await explain(client, api, content_id, demand, "newcomer")
    print(f"after report: kind={again['kind']} cached={again['cached']} {ms:.0f} ms")
    assert not again["cached"], "entry was not evicted"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    parser.add_argument("--content-id", default=DEFAULT_CONTENT)
    args = parser.parse_args()
    asyncio.run(run(args.api.rstrip("/"), args.content_id))


if __name__ == "__main__":
    main()
