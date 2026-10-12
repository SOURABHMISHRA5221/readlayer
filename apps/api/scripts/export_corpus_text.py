"""M8 §A2/§A3: export stored articles' paragraphs for the offline redaction and PII checks.

    cd apps/api && uv run python -m scripts.export_corpus_text

Read-only (the content store); no LLM, no writes. Output: data/corpus_paragraphs.json at the repo
root (gitignored, never committed): [{content_id, source, paragraphs: [{id, text}]}], extension
docs excluded (they are what the checks protect, not what they are measured on).
"""

import asyncio
import json
from pathlib import Path

from app.store.content_repo import get_content_store

OUT = Path(__file__).resolve().parents[3] / "data" / "corpus_paragraphs.json"


async def main() -> None:
    rows = [
        {
            "content_id": d.content_id,
            "source": d.source,
            "paragraphs": [{"id": p.id, "text": p.text} for p in d.paragraphs],
        }
        async for d in get_content_store().iter_all()
        if d.source != "extension"
    ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows))
    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    paragraphs = sum(len(r["paragraphs"]) for r in rows)
    print(f"{len(rows)} docs {by_source}, {paragraphs} paragraphs → {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
