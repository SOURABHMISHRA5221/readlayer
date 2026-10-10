"""Live check for the rest of M6 against the deployed API (or a local one).

    uv run python -m scripts.live_check_m6 [--api URL]

One Firebase anonymous (demo) user, deleted in `finally` (DELETE /v1/me). No new URL is ingested
here (the live "Open here" check runs through the web UI); a few explanation parts may be
generated (cents).

1. The demo article's annotations carry spans, paragraph markers, the pre-read and a prompt.
2. An event batch (dwell, paragraph-only text search, opened card, dismissal) applies; the same
   batch again applies nothing.
3. Answering the prompt "Not really" changes the next load: that concept isn't prompted again.
4. Two personas on one span share the restatement (same first half of the card id) and get
   their own Background (different second half).
"""

import argparse
import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from scripts.live_check_explain import API, sign_in_anonymously

ARTICLE = "1bff839e2ef3b017b35a89fce1653a26"  # ET, "Government extends RoDTEP …"


def now() -> str:
    return datetime.now(UTC).isoformat()


async def annotations(client: httpx.AsyncClient, api: str, persona: str) -> list[dict[str, Any]]:
    resp = await client.get(f"{api}/v1/content/{ARTICLE}/annotations?persona={persona}")
    resp.raise_for_status()
    return resp.json()["annotations"]


async def checks(client: httpx.AsyncClient, api: str) -> None:
    items = await annotations(client, api, "newcomer")
    names = ("span", "paragraph", "preread", "prompt")
    kinds = {k: sum(a["kind"] == k for a in items) for k in names}
    print("1. annotations", kinds)
    assert kinds["span"] and kinds["paragraph"] and kinds["preread"] == 1 and kinds["prompt"] == 1

    span = next(a for a in items if a["kind"] == "span")
    marked = {a["paragraph_id"] for a in items if a["kind"] in ("span", "prompt")}
    content = (await client.get(f"{api}/v1/content/{ARTICLE}")).json()
    bare = next(p["id"] for p in content["paragraphs"] if p["id"] not in marked)
    batch = [
        {"id": str(uuid.uuid4()), "type": "paragraph_dwell", "at": now(), "content_id": ARTICLE,
         "paragraph_id": "p0", "words": 30, "ms": 4200},
        {"id": str(uuid.uuid4()), "type": "text_searched", "at": now(), "content_id": ARTICLE,
         "paragraph_id": bare, "concept_id": None},
        {"id": str(uuid.uuid4()), "type": "explain_opened", "at": now(), "content_id": ARTICLE,
         "concept_id": span["concept_id"]},
        {"id": str(uuid.uuid4()), "type": "annotation_dismissed", "at": now(),
         "content_id": ARTICLE, "concept_id": span["concept_id"]},
    ]  # fmt: skip
    body = {"persona": "newcomer", "events": batch}
    first = (await client.post(f"{api}/v1/events", json=body)).json()
    again = (await client.post(f"{api}/v1/events", json=body)).json()
    print("2. events", first, "replay", again)
    assert first["events_applied"] == 4 and again["events_applied"] == 0

    prompt = next(a for a in items if a["kind"] == "prompt")
    resp = await client.patch(
        f"{api}/v1/me/graph/{prompt['concept_id']}?persona=newcomer", json={"state": "unknown"}
    )
    resp.raise_for_status()
    after = await annotations(client, api, "newcomer")
    prompted = [a["concept_id"] for a in after if a["kind"] == "prompt"]
    as_span = any(a["kind"] == "span" and a["concept_id"] == prompt["concept_id"] for a in after)
    print(f"3. prompt {prompt['concept_id']} → Not really: prompted now {prompted}, span {as_span}")
    assert prompt["concept_id"] not in prompted

    shared = next(
        a for a in (await annotations(client, api, "trader"))
        if a["kind"] == "span" and a["id"] in {s["id"] for s in after if s["kind"] == "span"}
    )  # fmt: skip
    cards = {}
    for persona in ("newcomer", "trader"):
        t = time.perf_counter()
        resp = await client.post(
            f"{api}/v1/explain?persona={persona}",
            json={"content_id": ARTICLE, "demand_id": shared["id"]},
            timeout=120,
        )
        resp.raise_for_status()
        cards[persona] = resp.json() | {"ms": round((time.perf_counter() - t) * 1000)}
    n, tr = cards["newcomer"], cards["trader"]
    summary = {p: (c["kind"], c["cached"], c["ms"], c["thinks_in"]) for p, c in cards.items()}
    print(f"4. span {shared['id']} “{shared['anchor']['exact']}”:", summary)
    print("   restatement shared:", n["id"].split("-")[0] == tr["id"].split("-")[0],
          "· Backgrounds differ:", n["id"].split("-")[1] != tr["id"].split("-")[1])  # fmt: skip
    print("   prompt_version", n["prompt_version"])
    assert n["id"].split("-")[0] == tr["id"].split("-")[0]
    assert n["id"].split("-")[1] != tr["id"].split("-")[1]


async def run(api: str) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        token = await sign_in_anonymously(client)
        client.headers["Authorization"] = f"Bearer {token}"
        try:
            await checks(client, api)
            print("ALL LIVE CHECKS PASSED")
        finally:
            resp = await client.delete(f"{api}/v1/me")
            print(f"cleanup: DELETE /v1/me → {resp.status_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    asyncio.run(run(parser.parse_args().api.rstrip("/")))


if __name__ == "__main__":
    main()
