"""M9 part 1 acceptance 2 on the emulator harness, real Vertex, through the HTTP routes the web
app uses (plan docs/plans/M9.md; milestone review round 1, item 3).

    FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 \\
    FIRESTORE_PROJECT=demo-readlayer FIREBASE_PROJECT=demo-readlayer ENV=dev \\
        uv run python -m scripts.harness_m9_growth <url> [--bad-url URL]

1. demo reader A opens <url> by Read any link (POST /v1/recs/open, then …/analyse) with growth caps
   at 0: GET says `grow_pending`, notes counted (newcomer persona);
2. caps back to normal: A's POST …/grow grows it, the notes are counted again, A's growth counter
   moved;
3. demo reader B's POST …/grow: "none", no slot;
4. Read any link on a URL that fails to fetch reserves nothing.
Emulator only: refuses to run without both emulator hosts.
"""

import argparse
import os
import sys

import httpx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.store.spend_repo import today_utc

PERSONA = "newcomer"


def sign_up() -> tuple[str, str]:
    host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
    resp = httpx.post(
        f"http://{host}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake",
        json={"returnSecureToken": True},
    )
    resp.raise_for_status()
    return resp.json()["localId"], resp.json()["idToken"]


def main(a: argparse.Namespace) -> int:
    hosts = ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST")
    if not all(os.environ.get(h) for h in hosts):
        print("emulator only: set FIRESTORE_EMULATOR_HOST and FIREBASE_AUTH_EMULATOR_HOST")
        return 2
    settings = get_settings()
    assert settings.db_project == "demo-readlayer", settings.db_project
    capped = settings.model_copy(update={"growth_per_uid_day": 0})
    from google.cloud import firestore

    db = firestore.Client(project=settings.db_project)

    def slots(uid: str) -> int:
        snap = db.document(f"users/{uid}/growth_counts/{today_utc()}").get()
        return int((snap.to_dict() or {}).get("count", 0)) if snap.exists else 0

    def spend() -> float:
        snap = db.document(f"ops/spend/days/{today_utc()}").get()
        return float((snap.to_dict() or {}).get("cost_usd", 0.0)) if snap.exists else 0.0

    a_uid, a_token = sign_up()
    b_uid, b_token = sign_up()
    start = spend()
    ok = True
    with TestClient(app) as client:  # the lifespan loads the served graph
        a_hdr = {"Authorization": f"Bearer {a_token}"}
        b_hdr = {"Authorization": f"Bearer {b_token}"}
        notes = f"annotations?persona={PERSONA}"
        app.dependency_overrides[get_settings] = lambda: capped
        opened = client.post("/v1/recs/open", json={"url": a.url}, headers=a_hdr)
        cid = opened.json()["content_id"]
        client.post(f"/v1/content/{cid}/analyse", headers=a_hdr).raise_for_status()
        app.dependency_overrides.clear()
        detail = client.get(f"/v1/content/{cid}", headers=a_hdr).json()
        notes1 = client.get(f"/v1/content/{cid}/{notes}", headers=a_hdr).json()
        print(f"1. opened {cid} by Read any link: grow_pending={detail['grow_pending']}, "
              f"notes={notes1['count']}, slots={slots(a_uid)}")  # fmt: skip
        ok &= detail["grow_pending"] is True and slots(a_uid) == 0

        grown = client.post(f"/v1/content/{cid}/grow", headers=a_hdr)
        notes2 = client.get(f"/v1/content/{cid}/{notes}&refresh=1", headers=a_hdr).json()
        after = client.get(f"/v1/content/{cid}", headers=a_hdr).json()
        print(f"2. grow: {grown.status_code} {grown.json()}; notes {notes1['count']} -> "
              f"{notes2['count']}; slots={slots(a_uid)}; "
              f"grow_pending={after['grow_pending']}")  # fmt: skip
        ok &= grown.json().get("status") == "grown" and grown.json().get("linked", 0) > 0
        ok &= notes2["count"] > notes1["count"] and slots(a_uid) > 0

        again = client.post(f"/v1/content/{cid}/grow", headers=b_hdr)
        print(f"3. reader B: {again.status_code} {again.json()}, slots={slots(b_uid)}")
        ok &= again.json().get("status") == "none" and slots(b_uid) == 0

        if a.bad_url:
            c_uid, c_token = sign_up()
            c_hdr = {"Authorization": f"Bearer {c_token}"}
            bad = client.post("/v1/recs/open", json={"url": a.bad_url}, headers=c_hdr)
            err = bad.json().get("error")
            print(f"4. bad fetch: {bad.status_code} {err}, slots={slots(c_uid)}")
            ok &= bad.status_code >= 400 and slots(c_uid) == 0
    print(f"run spend ${spend() - start:.4f} (emulator ledger)")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--bad-url")
    sys.exit(main(p.parse_args()))
