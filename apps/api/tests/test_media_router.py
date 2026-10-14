"""The media routes: POST /v1/recs/open for recordings, POST .../transcribe, GET fields, and the
POST /v1/content guard (Media plan §F, R3, R4, R14)."""

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.content import catalog
from app.main import app
from app.media import service, urls
from app.media.refusals import MediaRefused, MediaUnavailable
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.spend_repo import InMemorySpendStore
from tests.fakes import FakeLLM, auth
from tests.test_content_api import reply
from tests.test_media_service import FakeTranscribe, info

URL = "https://youtu.be/d6fUwCBvVc0?si=share"
CID = urls.content_id(urls.YouTube("d6fUwCBvVc0"))


@pytest.fixture
def env(monkeypatch):
    store = InMemoryContentStore()
    set_content_store(store)
    catalog.reset()
    spend = InMemorySpendStore()
    llm.set_spend_store(spend)
    fake = FakeTranscribe()
    monkeypatch.setattr(llm, "transcribe", fake)
    lookup: dict = {"info": info()}

    async def youtube_info(video_id, _settings):
        if isinstance(lookup["info"], Exception):
            raise lookup["info"]
        return lookup["info"]

    monkeypatch.setattr(service, "youtube_info", youtube_info)
    monkeypatch.setattr(llm, "run_with_meta", FakeLLM(reply))
    yield {"store": store, "spend": spend, "fake": fake, "lookup": lookup}
    set_content_store(None)
    llm.set_spend_store(None)
    catalog.reset()


def client(uid: str = "reader", anonymous: bool = False) -> TestClient:
    return TestClient(app, headers=auth(uid, anonymous=anonymous))


def test_open_transcribe_analyse_through_the_api(env, docs):
    c = client()
    opened = c.post("/v1/recs/open", json={"url": URL})
    assert opened.status_code == 200, opened.text
    assert opened.json() == {
        "content_id": CID, "new": True, "ready": False, "kind": "video", "stage": "transcribe",
    }  # fmt: skip

    detail = c.get(f"/v1/content/{CID}").json()
    assert detail["status"] == "transcribing" and detail["paragraphs"] == []
    assert detail["media"] == {
        "kind": "video", "video_id": "d6fUwCBvVc0", "audio_url": None, "duration_s": 949,
    }  # fmt: skip
    assert c.get(f"/v1/content/{CID}/annotations").status_code == 409
    assert c.post(f"/v1/content/{CID}/analyse").json()["error"] == "content_transcribing"

    done = c.post(f"/v1/content/{CID}/transcribe")
    assert done.status_code == 200 and done.json() == {"content_id": CID, "status": "analysing"}
    detail = c.get(f"/v1/content/{CID}").json()
    assert detail["status"] == "analysing"
    assert [p["start_s"] for p in detail["paragraphs"]][:2] == [0, 316]

    assert c.post(f"/v1/content/{CID}/analyse").json()["status"] == "ready"
    ready = c.get(f"/v1/content/{CID}").json()
    assert ready["status"] == "ready" and ready["media"]["kind"] == "video"
    assert ready["paragraphs"][0]["start_s"] == 0

    # Listed in this reader's library (brought in by them), and a repeat open is free.
    again = c.post("/v1/recs/open", json={"url": "https://www.youtube.com/watch?v=d6fUwCBvVc0"})
    assert again.json()["ready"] is True and again.json()["stage"] is None
    assert len(env["fake"].windows) == 1


@pytest.mark.parametrize("code", ["not_embeddable", "too_long", "not_english", "live"])
def test_refusals_are_422_with_a_message(env, code):
    env["lookup"]["info"] = MediaRefused(code)
    resp = client().post("/v1/recs/open", json={"url": URL})
    assert resp.status_code == 422
    assert resp.json()["error"] == code and "Open original" in resp.json()["message"]


def test_a_failed_lookup_is_503(env):
    env["lookup"]["info"] = MediaUnavailable("youtube")
    resp = client().post("/v1/recs/open", json={"url": URL})
    assert resp.status_code == 503 and resp.json()["error"] == "media_unavailable"


def test_the_cap_is_429_media_cap_reached(env, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anon_media_daily_cap", 0)
    resp = client("demo", anonymous=True).post("/v1/recs/open", json={"url": URL})
    assert resp.status_code == 429 and resp.json()["error"] == "media_cap_reached"
    assert "Sign in" in resp.json()["message"]


def test_a_budget_refusal_on_transcribe_is_503(env):
    c = client()
    c.post("/v1/recs/open", json={"url": URL})
    env["spend"].media = 3.0
    resp = c.post(f"/v1/content/{CID}/transcribe")
    assert resp.status_code == 503 and resp.json()["error"] == "llm_budget_exceeded"
    assert "Retry-After" in resp.headers


def test_a_refusal_while_transcribing_shows_on_the_page(env):
    env["lookup"]["info"] = info(language=None)
    env["fake"].language = "hi"
    c = client()
    c.post("/v1/recs/open", json={"url": URL})
    resp = c.post(f"/v1/content/{CID}/transcribe")
    assert resp.status_code == 422 and resp.json()["error"] == "not_english"
    detail = c.get(f"/v1/content/{CID}").json()
    assert detail["status"] == "refused" and detail["refusal"]["code"] == "not_english"


def test_a_timed_out_call_is_504_and_the_page_may_retry(env):
    env["fake"].time_out = True
    c = client()
    c.post("/v1/recs/open", json={"url": URL})
    resp = c.post(f"/v1/content/{CID}/transcribe")
    assert resp.status_code == 504
    assert resp.json() == {
        "error": "transcribe_timeout",
        "message": "Transcribing took too long. Try again.",
    }
    assert c.get(f"/v1/content/{CID}").json()["status"] == "transcribing"


def test_transcribe_of_an_unknown_id_is_404(env):
    assert client().post("/v1/content/abc123/transcribe").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"url": URL},
        {"url": URL, "title": "x", "paragraphs": ["some text that is long enough to count"]},
    ],
)
def test_post_content_sends_recordings_to_read_any_link(env, body):
    resp = client().post("/v1/content", json=body)
    assert resp.status_code == 422 and resp.json()["error"] == "use_open_here"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://cdn.example/show/episode.mp3", "apple_link_only"),
        ("https://podcasts.apple.com/us/podcast/a-show/id1200361736", "not_an_episode"),
    ],
)
def test_podcast_links_refused_before_any_lookup_are_422(env, url, code):
    resp = client().post("/v1/recs/open", json={"url": url})
    assert resp.status_code == 422 and resp.json()["error"] == code
    assert "Open original" in resp.json()["message"]


def test_an_unreachable_episode_on_transcribe_is_503_and_retryable(env, monkeypatch):
    async def unavailable(content_id, settings):
        raise MediaUnavailable("audio")

    monkeypatch.setattr(service, "transcribe_pending", unavailable)
    resp = client().post(f"/v1/content/{CID}/transcribe")
    assert resp.status_code == 503 and resp.json()["error"] == "media_unavailable"
    assert resp.headers["Retry-After"] == "60"
