"""Read-only precheck for tools/shots/landing_media.py (decision 44 V2/V4; plan round 1 item 7).

    cd apps/api && uv run python -m scripts.landing_media_precheck

With ADC, reads the demo markets article, the persona templates and the explanation cache, and
prints what the live recording would show and write: which notes each persona gets, the
"Know this?" prompt (if any), whether every Background the clips open (including the cricket
fan's "Say it simpler" one band down) is cached and verified, and the exact production writes.
Writes nothing and calls no model.
"""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

from app.config import get_settings
from app.explain import service
from app.explain.inputs import span_inputs
from app.explain.router import shifted
from app.graph.loader import load_graph, set_graph
from app.ingest.models import is_corpus
from app.reader.personas import PERSONA_THINKS_IN
from app.scoring import scorer
from app.scoring.scorer import ScoringInputs
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.explain_repo import ExplainRepo
from app.store.persona_repo import get_template
from app.recs.feed import SnapshotRepo
from app.recs.router import WEB_TRIGGERS
from app.recs.web_search import build_query, get_web_search
from app.store.reader_repo import state_from_demo

CONTENT_ID = "2332418841faa08d5f5e157c2d038d1d"
PARAGRAPH = "p5"
STYLE = "normal"  # demo readers' explanation style
# (persona, concept, shift): the Backgrounds the product shot and the clips open.
OPENED = (
    ("newcomer", "c_basis_points", 0),  # product shot and clip 1
    ("newcomer", "c_monetary_tightening", 0),  # clip 1
    ("trader", "c_monetary_tightening", 0),  # clip 2, before
    ("trader", "c_monetary_tightening", -1),  # clip 2, "Say it simpler"
)
KNEW_THIS = ("c_basis_points", "c_monetary_tightening")  # clip 4, as the newcomer


async def main() -> int:
    now = datetime.now(UTC)
    store = get_doc_store()
    graph = await load_graph(get_settings().concepts_uri)
    set_graph(graph)
    docs = {d.content_id: d async for d in get_content_store().iter_all()}
    doc = docs.get(CONTENT_ID)
    if doc is None:
        print(f"ABORT: {CONTENT_ID} not found")
        return 1
    corpus = [d for d in docs.values() if is_corpus(d)]
    explainers = scorer.explainer_index(corpus)
    states, out, triggers = {}, {"spans": {}, "prompt": {}}, {}
    for persona in ("newcomer", "trader"):
        states[persona] = state_from_demo(
            "landing", persona, await get_template(store, persona), copied=False
        )
        result = scorer.annotate(
            doc, graph, states[persona], "balanced", now, ScoringInputs(explainers=explainers)
        )
        out["spans"][persona] = [
            (s.paragraph_id, s.label, s.band) for s in result.spans if s.paragraph_id == PARAGRAPH
        ]
        triggers[persona] = result.spans[:WEB_TRIGGERS]  # what Up next searches (recs router)
        out["prompt"][persona] = (
            (result.prompt.paragraph_id, result.prompt.label) if result.prompt else None
        )
    repo, missing = ExplainRepo(store), []
    rv, bv = service.restate_version(), service.background_version()
    for persona, concept, shift in OPENED:
        demand = next(
            d for d in doc.demands if d.paragraph_id == PARAGRAPH and d.target_id == concept
        )
        base = span_inputs(
            doc, demand, graph, states[persona], now, PERSONA_THINKS_IN[persona], STYLE
        )
        inputs = replace(base, band=shifted(base.band, shift)) if shift else base
        r, b = await asyncio.gather(
            repo.get(inputs.restate_key(rv)), repo.get(inputs.background_key(bv))
        )
        ok = bool(r and r.get("verified")) and bool(b and b.get("verified"))
        out.setdefault("opened", []).append((persona, concept, shift, inputs.band, ok))
        if not ok:
            missing.append(f"{persona} {concept} shift {shift}")
    # Decision 46e round 1 item 1: the captures cost no searches. The anonymous feed is served
    # from the seeded snapshot only; Up next (mounted with the reader) searches only on a cache
    # miss for the article's top concepts, so every one must be fresh.
    snap = await SnapshotRepo(store).get("newcomer")
    out["feed_snapshot"] = {"items": len(snap.items) if snap else 0, "prepared_at": snap.prepared_at if snap else None}
    web, searches = get_web_search(), []
    for persona, spans in triggers.items():
        for span in spans:
            for fmt in sorted(web.formats):
                _, fresh = await web.cached(span.concept_id, fmt, build_query(span.label, fmt, span.domain))
                if not fresh:
                    searches.append(f"{persona} {span.concept_id} {fmt}")
    print(json.dumps(out, indent=2, default=str))
    print(f"\nexplanations to generate if run: {len(missing)} (≈ $0.005 each) {missing}")
    print(f"web searches if run (Up next cache misses): {len(searches)} {searches}")
    print(f"feed: served from persona_feeds/newcomer ({out['feed_snapshot']['items']} items), 0 searches")
    print(
        "production writes if run: 1 anonymous Auth user and its reader docs (DELETE /v1/me "
        "removes both); explain hits +"
        f"{len(OPENED) + 1} on ops/explain/days/{now:%Y-%m-%d} (product shot, desktop and phone, "
        f"plus the clips; not reversible); 1 'Know this?' answer (if a prompt exists) and "
        f"{len(KNEW_THIS)} 'Knew this' in the demo graph (deleted with the reader)"
    )
    if missing or searches or not snap or not snap.items:
        print("REFUSE: the run would generate, search or build a feed (decision 46e: 0 of each)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
