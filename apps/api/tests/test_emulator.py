"""Integration against the Firestore and Auth emulators (real Firestore transactions, real
Firebase token verification, real recursive delete). Skipped unless the emulators run:

    make test-emulator      # firebase emulators:exec --only firestore,auth -- pytest -m emulator
"""

import os
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app import auth
from app.content import router as read_router
from app.graph.loader import get_graph, set_graph
from app.main import app
from app.recs import router as recs_router
from app.recs import web_search as ws
from app.store import docstore
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.reader_repo import USER_SUBCOLLECTIONS
from tests.test_me_api import event
from tests.test_recs_api import FakeProvider
from tests.test_recs_library import DOCS, GRAPH

PROJECT = "demo-readlayer"
FIRESTORE = os.environ.get("FIRESTORE_EMULATOR_HOST")
AUTH = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(not (FIRESTORE and AUTH), reason="Firestore/Auth emulators not running"),
]


def sign_up_anonymous() -> tuple[str, str]:
    resp = httpx.post(
        f"http://{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake",
        json={"returnSecureToken": True},
    )
    resp.raise_for_status()
    body = resp.json()
    return body["localId"], body["idToken"]


def auth_user_exists(uid: str) -> bool:
    resp = httpx.post(
        f"http://{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup",
        json={"localId": [uid]},
        headers={"Authorization": "Bearer owner"},
    )
    resp.raise_for_status()
    return bool(resp.json().get("users"))


def all_user_docs(uid: str) -> list[str]:
    """Straight from the emulator with the sync client, independent of the API's store."""
    db = firestore.Client(project=PROJECT)
    paths = []
    user = db.document(f"users/{uid}")
    if user.get().exists:
        paths.append(user.path)
    for coll in user.collections():
        paths.extend(snap.reference.path for snap in coll.stream())
    return paths


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", FIRESTORE)
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", AUTH)
    docstore.set_doc_store(docstore.FirestoreDocStore(PROJECT))
    auth.set_auth_admin(auth.FirebaseAuthAdmin(PROJECT))
    store = InMemoryContentStore()
    store.docs = {d.content_id: d for d in DOCS}
    set_content_store(store)
    read_router.reset_catalog()
    recs_router._index = None
    previous = get_graph()
    set_graph(GRAPH)
    from app import config

    ws.set_web_search(
        ws.WebSearch(
            {f: FakeProvider() for f in ("article", "video", "podcast")},
            ws.InMemoryRecCache(),
            ws.InMemorySearchCalls(),
            config.get_settings(),
            frozenset(),
        )
    )
    yield
    ws.set_web_search(None)
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def test_export_then_delete_against_the_emulators(live, monkeypatch):
    from app.ingest import router as ingest_router
    from tests.test_me_api import _fake_ingest

    monkeypatch.setattr(ingest_router, "ingest_url", _fake_ingest(InMemoryContentStore()))
    uid, id_token = sign_up_anonymous()
    # One client session = one event loop for the async Firestore client (as under uvicorn).
    with TestClient(app, headers={"Authorization": f"Bearer {id_token}"}) as client:
        set_graph(GRAPH)  # lifespan loaded the (empty) configured graph
        assert client.patch("/v1/me/settings", json={"thinks_in": ["software"]}).status_code == 200
        batch = {"events": [event("e1"), event("d1", "paragraph_dwell", None, words=250)]}
        assert client.post("/v1/events", json=batch).json()["events_applied"] == 2
        assert client.post("/v1/events", json=batch).json()["events_applied"] == 0  # replay
        assert client.get("/v1/content/main/annotations").status_code == 200
        items = client.get("/v1/content/main/recommendations").json()["items"]
        shown = {"events": [{"id": "r1", "type": "rec_shown", "item_id": items[0]["id"]}]}
        assert client.post("/v1/recs/events", json=shown).json()["applied"] == 1
        new = client.post("/v1/content", json={"url": "https://emu.example/a"})
        assert new.status_code == 200, new.text

        body = client.get("/v1/me/export").json()
        assert body["user"]["thinks_in"] == ["software"] and body["user"]["is_anonymous"] is True
        # A demo reader's graph is their persona's copy (demo_graphs), not knows/domains.
        # profile_edits arrive in M7.
        for name in ("demo_graphs", "events", "weekly", "rec_signals", "ingest_counts"):
            assert body[name], name
        stored = all_user_docs(uid)
        assert stored[0] == f"users/{uid}"
        for path in stored[1:]:
            _, _, coll, doc_id = path.split("/")
            assert coll in USER_SUBCOLLECTIONS and doc_id in body[coll], path

        assert client.delete("/v1/me").status_code == 204
    assert all_user_docs(uid) == []
    assert not auth_user_exists(uid)


def test_rules_deny_all_client_access(live):
    """Unauthenticated REST (what a browser SDK would do) is refused by firestore.rules."""
    base = f"http://{FIRESTORE}/v1/projects/{PROJECT}/databases/(default)/documents"
    probe = f"users/{uuid.uuid4().hex}"
    assert httpx.get(f"{base}/{probe}").status_code == 403
    assert httpx.get(f"{base}/contents/x").status_code == 403
    write = httpx.patch(f"{base}/{probe}", json={"fields": {"x": {"stringValue": "y"}}})
    assert write.status_code == 403


async def test_growth_claim_and_finish_are_transactions_on_the_content_doc():
    """M9 G4 on real Firestore: one claim at a time, a stale finish drops, text untouched."""
    from datetime import UTC, datetime, timedelta

    from app.ingest.models import Anchor, ContentDoc, Demand
    from app.store.content_repo import FirestoreContentStore

    store = FirestoreContentStore(PROJECT)
    cid = f"m9-claim-{uuid.uuid4().hex[:8]}"
    anchor = Anchor(exact="offside", prefix="", suffix="", start=0, end=7)
    before = ContentDoc(
        content_id=cid, url="https://x.example/a", final_url="https://x.example/a", title="T",
        site="x.example", source="extension", fetched_at="2026-10-15T00:00:00+00:00",
        paragraphs=[], demands_dropped=0, llm_calls=[], grow_pending=True,
        demands=[Demand(id="d1", paragraph_id="p0", type="concept", label="Offside",
                        salience=0.9, explained_in_text=False, zipf=3.0, anchor=anchor)],
    )  # fmt: skip
    await store.put(before)
    now = datetime.now(UTC)
    status, token = await store.claim_growth(cid, now, now + timedelta(seconds=60))
    assert status == "claimed" and token
    assert await store.claim_growth(cid, now, now + timedelta(seconds=60)) == ("busy", None)
    linked = [d.model_copy(update={"target_id": "c_x"}) for d in before.demands]
    assert await store.finish_growth(cid, "stale", linked, [], False, []) is False
    assert await store.finish_growth(cid, token, linked, [], False, ["false nine"]) is True
    after = await store.get(cid)
    assert after.demands == linked and after.grow_pending is False and after.grow_token is None
    assert after.paragraphs == before.paragraphs
    later = now + timedelta(seconds=120)
    assert (await store.claim_growth(cid, later, later + timedelta(seconds=60)))[0] == "claimed"
    assert await store.claim_growth("m9-absent-doc", now, now) == ("absent", None)
