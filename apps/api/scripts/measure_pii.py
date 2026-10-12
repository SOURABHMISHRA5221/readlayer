"""M8 §A2/§A3 evidence: what the redactor and the Presidio backstop do to real articles.

    cd apps/api && uv run python -m scripts.export_corpus_text   # once, read-only
    cd apps/api && uv run python -m scripts.measure_pii [--show]

Offline over data/corpus_paragraphs.json and tests/fixtures/pii_pages.json; no network, no
writes. Prints (1) every corpus paragraph the strict redactor changes (placeholder types; the
matched text only with --show, for a local look, never into a report), (2) Presidio findings per
1,000 words per article at each score floor, the corpus maximum and the fixtures' rates, which
set `pii.MIN_SCORE` and `pii.MAX_PER_1000_WORDS`.
"""

import argparse
import json
import re
from pathlib import Path

from app.privacy import pii
from app.privacy.redact import redact

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data" / "corpus_paragraphs.json"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pii_pages.json"
FLOORS: tuple[float | None, ...] = (None, 0.4, 0.5)  # None = pii.MIN_SCORES (the policy)


def redaction_check(docs: list[dict], show: bool) -> None:
    changed = []
    for d in docs:
        for p in d["paragraphs"]:
            out = redact(p["text"])
            if out != p["text"]:
                changed.append((d, p, out))
    print(f"\n## Strict redactor: {len(changed)} of "
          f"{sum(len(d['paragraphs']) for d in docs)} paragraphs changed")  # fmt: skip
    for d, p, out in changed:
        kinds = re.findall(r"\[REDACTED:(\w+)\]", out)
        print(f"- {d['content_id'][:8]} {d['source']} {p['id']}: {kinds}")
        if show:
            for m in _matches(p["text"], out):
                print(f"    matched: {m!r}")


def _matches(before: str, after: str) -> list[str]:
    """The original spans behind each placeholder (local inspection only)."""
    pattern = re.escape(after)
    pattern = re.sub(r"\\\[REDACTED:\w+\\\]", "(.+?)", pattern)
    m = re.fullmatch(pattern, before, flags=re.S)
    return list(m.groups()) if m else ["(could not align)"]


def presidio_check(docs: list[dict]) -> None:
    print("\n## Presidio findings per 1,000 words")
    for floor in FLOORS:
        rates = []
        for d in docs:
            f = pii.scan([p["text"] for p in d["paragraphs"]], floor)
            rates.append((f.per_1000_words, f.by_type, d["content_id"][:8], d["source"]))
        rates.sort(key=lambda r: r[0], reverse=True)
        cards = max(r[1].get("CREDIT_CARD", 0) for r in rates)
        top, p99 = rates[0][0], rates[len(rates) // 100][0]
        hits = sum(1 for r in rates if r[0] > 0)
        label = floor or "policy"
        print(f"\nfloor {label}: max {top:.2f}, 99th pct {p99:.2f}, hits {hits}/{len(rates)}")
        print(f"max cards in one article {cards}")
        for rate, by_type, cid, source in rates[:8]:
            print(f"  {rate:6.2f} {cid} {source} {by_type}")
    refused = [
        d["content_id"][:8] for d in docs if pii.scan([p["text"] for p in d["paragraphs"]]).refuse
    ]
    print(f"\nrefused under the policy: {len(refused)} of {len(docs)} {refused}")
    fixtures = json.loads(FIXTURES.read_text())
    print("\n## Fixtures")
    for kind in ("refuse", "pass"):
        for page in fixtures[kind]:
            row = [f"{pii.scan(page['paragraphs'], fl).per_1000_words:.1f}" for fl in FLOORS]
            print(f"  {kind:6} {page['name']:32} " + "  ".join(row))


def main(show: bool) -> None:
    docs = json.loads(CORPUS.read_text())
    print(f"{len(docs)} docs")
    redaction_check(docs, show)
    presidio_check(docs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true", help="print matched text (local only)")
    main(parser.parse_args().show)
