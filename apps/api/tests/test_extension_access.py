"""Extension text is readable only by the readers who submitted it (M8 §A5, DESIGN §17.4)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.content import router as read_router
from app.ingest.models import PendingDoc, PendingParagraph
from app.main import app
from app.store.docstore import get_doc_store
from app.store.pending_repo import get_pending_repo
from app.store.reader_repo import ReaderRepo
from tests.fakes import auth
from tests.test_recs_api import env  # noqa: F401  (fixture)
from tests.test_recs_library import DOCS

EXT = "e" * 32
PENDING = "f" * 32


def reader(uid: str) -> TestClient:
    return TestClient(app, headers=auth(uid, anonymous=True))


def bring(uid: str, content_id: str) -> None:
    repo = ReaderRepo(get_doc_store())
    asyncio.run(repo.add_ingested(uid, content_id, datetime.now(UTC).isoformat()))


@pytest.fixture
def private(env):  # noqa: F811
    _, _, _, store = env
    synd = next(d for d in DOCS if d.content_id == "synd")
    store.docs[EXT] = synd.model_copy(
        update={"content_id": EXT, "url": "https://paywall.example/a", "source": "extension"}
    )
    read_router.reset_catalog()
    bring("owner", EXT)
    return synd


ROUTES = [
    ("get", f"/v1/content/{EXT}", None),
    ("get", f"/v1/content/{EXT}/annotations?persona=newcomer", None),
    ("get", f"/v1/content/{EXT}/recommendations?persona=newcomer", None),
    ("put", f"/v1/me/saved/{EXT}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=[r[1] for r in ROUTES])
def test_only_the_submitter_reads_extension_text(private, method, path, body):
    mine = getattr(reader("owner"), method)(path)
    theirs = getattr(reader("stranger"), method)(path)
    assert mine.status_code in (200, 204), mine.text
    assert theirs.status_code == 404 and theirs.json()["detail"] == "content not found"


def test_explain_is_gated_before_any_lookup(private):
    body = {"content_id": EXT, "paragraph_id": "zz"}
    assert reader("owner").post("/v1/explain", json=body).json()["detail"] == "paragraph not found"
    theirs = reader("stranger").post("/v1/explain", json=body)
    assert theirs.status_code == 404 and theirs.json()["detail"] == "content not found"


def test_pending_extension_text_is_gated_too(env):  # noqa: F811
    now = datetime.now(UTC)
    text = "Pending extension paragraph text long enough to keep. " * 3
    pending = PendingDoc(
        content_id=PENDING,
        url="https://paywall.example/b",
        final_url="https://paywall.example/b",
        title="Pending",
        site="paywall.example",
        source="extension",
        fetched_at=now.isoformat(),
        paragraphs=[PendingParagraph(id="p0", text=text)],
        expire_at=now + timedelta(hours=1),
    )
    asyncio.run(get_pending_repo().create(pending))
    bring("owner", PENDING)
    assert reader("owner").get(f"/v1/content/{PENDING}").json()["status"] == "analysing"
    stranger = reader("stranger")
    assert stranger.get(f"/v1/content/{PENDING}").status_code == 404
    assert stranger.get(f"/v1/content/{PENDING}/annotations").status_code == 404  # not 409
    assert stranger.post(f"/v1/content/{PENDING}/analyse").status_code == 404


def test_server_fetched_reader_pages_stay_readable_by_id(env):  # noqa: F811
    _, _, _, store = env
    synd = next(d for d in DOCS if d.content_id == "synd")
    store.docs["u" * 32] = synd.model_copy(
        update={"content_id": "u" * 32, "source": "user_ingested"}
    )
    read_router.reset_catalog()
    assert reader("stranger").get(f"/v1/content/{'u' * 32}").status_code == 200
