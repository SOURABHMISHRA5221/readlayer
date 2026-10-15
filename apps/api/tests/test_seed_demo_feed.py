"""The demo feed seeder re-checks cached recordings against today's filters (decision 64)."""

from app.recs.models import WebResult
from scripts.seed_demo_feed import offered_recordings


def video(title: str) -> WebResult:
    return WebResult(url=f"https://www.youtube.com/watch?v={abs(hash(title))}", title=title,
                     source="YouTube", format="video")  # fmt: skip


def test_cached_recordings_pass_todays_title_check():
    kept = offered_recordings([
        video("ഈ റാലി സൂചനയോ| Political Analysis|Debate Malayalam| NEWS INDIA MALAYALAM POINT"),
        video("Why this Nobel Prize matters for your money | DW News"),
    ])  # fmt: skip
    assert [r.title for r in kept] == ["Why this Nobel Prize matters for your money | DW News"]
