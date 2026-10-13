"""Media step 3: emulator harness run on real Vertex (plan acceptance 1-3, video half).

Run from apps/api with the harness up (make dev-emulator):
    uv run python -m scripts.harness_media main
    uv run python -m scripts.harness_media refuse <url> [--api URL] [--anon]
    uv run python -m scripts.harness_media hindi <url>
    uv run python -m scripts.harness_media anoncap <url1> <url2> [--api URL]
    uv run python -m scripts.harness_media costly <url> --api http://127.0.0.1:8001
    uv run python -m scripts.harness_media t04

Reads the emulator's spend ledger (never production): FIRESTORE_EMULATOR_HOST is forced here.
"""

import argparse
import asyncio
import json
import os
import time
import urllib.parse
import uuid
from typing import Any

os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8085"

import httpx  # noqa: E402
from google.cloud import firestore  # noqa: E402

from app.store.spend_repo import today_utc  # noqa: E402

API = "http://127.0.0.1:8000"
AUTH = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1"
VIDEO = "https://www.youtube.com/watch?v=d6fUwCBvVc0"
REF_WORDS, LAST_START_MIN, DURATION_S = 1822, 900, 949
TRANSCRIBE_MAX_USD = 0.10
PERSONAS = ("newcomer", "trader")

_db: firestore.AsyncClient | None = None


def emu() -> firestore.AsyncClient:
    """Created inside the running loop: an aio gRPC client made at import time can hang."""
    global _db
    if _db is None:
        _db = firestore.AsyncClient(project="demo-readlayer")
    return _db


async def ledger() -> tuple[float, float]:
    snap = await emu().document(f"ops/spend/days/{today_utc()}").get()
    data = snap.to_dict() or {}
    return float(data.get("cost_usd", 0.0)), float(data.get("media_usd", 0.0))


async def slot_count(uid: str) -> int:
    snap = await emu().document(f"users/{uid}/media_counts/{today_utc()}").get()
    return int((snap.to_dict() or {}).get("count", 0))


async def sign_in(client: httpx.AsyncClient, google: bool) -> tuple[str, str]:
    """(idToken, uid). Google = an unsigned emulator Google identity, as the web harness does."""
    if google:
        email = f"media-{uuid.uuid4().hex[:6]}@example.com"
        claims = json.dumps({"sub": email, "email": email, "email_verified": True, "name": "M"})
        body = {
            "postBody": urllib.parse.urlencode({"id_token": claims, "providerId": "google.com"}),
            "requestUri": "http://localhost",
            "returnSecureToken": True,
        }
        resp = await client.post(f"{AUTH}/accounts:signInWithIdp?key=demo-key", json=body)
    else:
        resp = await client.post(
            f"{AUTH}/accounts:signUp?key=demo-key", json={"returnSecureToken": True}
        )
    resp.raise_for_status()
    data = resp.json()
    return data["idToken"], data["localId"]


async def reader(google: bool) -> tuple[httpx.AsyncClient, str]:
    client = httpx.AsyncClient(timeout=600)
    token, uid = await sign_in(client, google)
    client.headers["Authorization"] = f"Bearer {token}"
    return client, uid


async def open_(client: httpx.AsyncClient, api: str, url: str) -> tuple[int, dict[str, Any]]:
    resp = await client.post(f"{api}/v1/recs/open", json={"url": url})
    return resp.status_code, resp.json()


async def transcribe(client: httpx.AsyncClient, api: str, cid: str) -> tuple[int, dict, float]:
    started = time.perf_counter()
    while True:
        resp = await client.post(f"{api}/v1/content/{cid}/transcribe")
        if resp.status_code != 202:
            return resp.status_code, resp.json(), time.perf_counter() - started
        await asyncio.sleep(5)


async def analyse(client: httpx.AsyncClient, api: str, cid: str) -> tuple[int, float]:
    started = time.perf_counter()
    while True:
        resp = await client.post(f"{api}/v1/content/{cid}/analyse")
        if resp.status_code != 202:
            return resp.status_code, time.perf_counter() - started
        await asyncio.sleep(5)


def transcript_checks(doc: dict[str, Any]) -> bool:
    paras = doc["paragraphs"]
    words = sum(len(p["text"].split()) for p in paras)
    starts = [p["start_s"] for p in paras]
    ok_words = abs(words - REF_WORDS) <= REF_WORDS * 0.10
    ok_last = starts[-1] >= LAST_START_MIN
    ok_order = all(a <= b for a, b in zip(starts, starts[1:], strict=False))
    ok_inside = all(0 <= s <= DURATION_S for s in starts)
    print(f"  transcript: {len(paras)} paragraphs, {words} words (ref {REF_WORDS}, ±10%: "
          f"{ok_words}); last start {starts[-1]} s (≥ {LAST_START_MIN}: {ok_last}); "
          f"non-decreasing {ok_order}; inside duration {ok_inside}")  # fmt: skip
    return ok_words and ok_last and ok_order and ok_inside


async def main_run(api: str) -> None:
    results: dict[str, bool] = {}
    a, uid_a = await reader(google=True)
    print(f"[A] Google reader {uid_a}")
    spend0, media0 = await ledger()
    print(f"  ledger before: ${spend0:.4f} (media ${media0:.4f})")

    t = time.perf_counter()
    code, body = await open_(a, api, VIDEO)
    t_open = time.perf_counter() - t
    print(f"  open {code} {body} {t_open:.1f} s")
    cid = body["content_id"]
    spend1, media1 = await ledger()
    print(f"  ledger after open: +${spend1 - spend0:.4f} (no model call expected)")

    code, tbody, t_tr = await transcribe(a, api, cid)
    spend2, media2 = await ledger()
    tr_cost = media2 - media1
    print(f"  transcribe {code} {tbody} {t_tr:.1f} s, ledger +${spend2 - spend1:.4f} "
          f"(media +${tr_cost:.4f}; ≤ $0.10: {tr_cost <= TRANSCRIBE_MAX_USD})")  # fmt: skip
    results["transcribe ≤ $0.10"] = code == 200 and tr_cost <= TRANSCRIBE_MAX_USD
    if code != 200:
        print("  STOP: transcribe failed")
        return

    code, t_an = await analyse(a, api, cid)
    spend3, _ = await ledger()
    print(f"  analyse {code} {t_an:.1f} s, ledger +${spend3 - spend2:.4f} "
          f"(≤ 100 s: {t_an <= 100})")  # fmt: skip
    results["analyse ≤ 100 s"] = code == 200 and t_an <= 100
    print(f"  phase timings: open {t_open:.1f} s, transcribe {t_tr:.1f} s, analyse {t_an:.1f} s")

    doc = (await a.get(f"{api}/v1/content/{cid}")).json()
    print(f"  GET status {doc['status']} media {doc['media']}")
    results["transcript"] = doc["status"] == "ready" and transcript_checks(doc)
    print(f"  slot used by A: {await slot_count(uid_a)}")

    # Acceptance 2: a second reader (demo) opens the same URL: no model call, no slot.
    b, uid_b = await reader(google=False)
    before = await ledger()
    code, body = await open_(b, api, VIDEO)
    after = await ledger()
    free = after == before and await slot_count(uid_b) == 0
    print(f"[B] demo reader {uid_b}: open {code} {body}; ledger unchanged and no slot: {free}")
    results["second reader free"] = code == 200 and body.get("ready") is True and free

    # Two personas, different note counts on the same transcript (no model call).
    counts = {}
    spans: dict[str, list[dict]] = {}
    for persona in PERSONAS:
        resp = await b.get(f"{api}/v1/content/{cid}/annotations?persona={persona}")
        resp.raise_for_status()
        spans[persona] = [x for x in resp.json()["annotations"] if x["kind"] == "span"]
        counts[persona] = len(resp.json()["annotations"])
    print(f"  note counts {counts}")
    results["personas differ"] = len(set(counts.values())) > 1

    # One verified card on a transcript span.
    card = None
    for span in sorted(spans["newcomer"], key=lambda x: -x["score"])[:3]:
        resp = await b.post(
            f"{api}/v1/explain?persona=newcomer",
            json={"content_id": cid, "demand_id": span["id"]},
            timeout=120,
        )
        resp.raise_for_status()
        card = resp.json()
        print(f"  explain “{span['anchor']['exact']}” → {card['kind']}")
        if card["kind"] == "verified":
            print(f"    Background: {card['background']}\n    Says: {card['author_says']}")
            break
    results["verified card"] = bool(card and card["kind"] == "verified")
    spend4, _ = await ledger()
    print(f"  total harness spend this run: ${spend4 - spend0:.4f}")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
    print(f"content_id {cid}")


async def refuse(api: str, url: str, anon: bool) -> None:
    c, uid = await reader(google=not anon)
    before = await ledger()
    code, body = await open_(c, api, url)
    after = await ledger()
    slots = await slot_count(uid)
    print(f"open {url} → {code} {body}; ledger +${after[0] - before[0]:.4f}; slot {slots}")


async def hindi(api: str, url: str) -> None:
    c, _ = await reader(google=True)
    before = await ledger()
    code, body = await open_(c, api, url)
    print(f"[1] open → {code} {body}")
    if code == 200:
        code, tbody, secs = await transcribe(c, api, body["content_id"])
        print(f"    transcribe → {code} {tbody} {secs:.1f} s")
    mid = await ledger()
    print(f"    ledger +${mid[0] - before[0]:.4f} (one paid window expected)")
    c2, _ = await reader(google=True)
    code, body = await open_(c2, api, url)
    end = await ledger()
    print(f"[2] another reader: open → {code} {body}; ledger +${end[0] - mid[0]:.4f} (free)")


async def anoncap(api: str, first: str, second: str) -> None:
    c, uid = await reader(google=False)
    for url in (first, second):
        before = await ledger()
        code, body = await open_(c, api, url)
        after = await ledger()
        slots = await slot_count(uid)
        print(f"open {url} → {code} {body}; ledger +${after[0] - before[0]:.4f}; slot {slots}")


async def t04(api: str) -> None:
    """Frozen case T04: one whole-URL call near the cap; words ≥ 2,600, last start ≥ 1,050."""
    c, _ = await reader(google=True)
    before = await ledger()
    code, body = await open_(c, api, "https://www.youtube.com/watch?v=rrkrvAUbU9Y")
    print(f"open → {code} {body}")
    code, tbody, secs = await transcribe(c, api, body["content_id"])
    after = await ledger()
    print(f"transcribe → {code} {tbody} {secs:.1f} s; media +${after[1] - before[1]:.4f}")
    if code != 200:
        return
    doc = (await c.get(f"{api}/v1/content/{body['content_id']}")).json()
    paras = doc["paragraphs"]
    words = sum(len(p["text"].split()) for p in paras)
    starts = [p["start_s"] for p in paras]
    ordered = all(a <= b for a, b in zip(starts, starts[1:], strict=False))
    print(f"T04: {len(paras)} paragraphs, {words} words (≥ 2600: {words >= 2600}), last start "
          f"{starts[-1]} (≥ 1050: {starts[-1] >= 1050}), non-decreasing {ordered}")  # fmt: skip


async def costly(api: str, url: str) -> None:
    c, _ = await reader(google=True)
    before = await ledger()
    code, body = await open_(c, api, url)
    print(f"open → {code} {body}")
    code, tbody, secs = await transcribe(c, api, body["content_id"])
    after = await ledger()
    print(f"transcribe → {code} {tbody} {secs:.1f} s; ledger +${after[1] - before[1]:.4f} media")


def cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["main", "refuse", "hindi", "anoncap", "costly", "t04"])
    p.add_argument("urls", nargs="*")
    p.add_argument("--api", default=API)
    p.add_argument("--anon", action="store_true")
    a = p.parse_args()
    run = {
        "main": lambda: main_run(a.api),
        "refuse": lambda: refuse(a.api, a.urls[0], a.anon),
        "hindi": lambda: hindi(a.api, a.urls[0]),
        "anoncap": lambda: anoncap(a.api, a.urls[0], a.urls[1]),
        "costly": lambda: costly(a.api, a.urls[0]),
        "t04": lambda: t04(a.api),
    }[a.cmd]
    asyncio.run(run())


if __name__ == "__main__":
    cli()
