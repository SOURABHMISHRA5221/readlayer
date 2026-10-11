"""Build the landing page's static mini-demo (decision 41 A4): apps/web/src/landing/demo.json.

    cd apps/api && uv run python -m scripts.build_landing_demo --dry-run  # choose + precheck
    cd apps/api && uv run python -m scripts.build_landing_demo            # + confirm, write

1. Read-only (ADC): the demo articles, the persona templates and the concept graph; score every
   paragraph for the three demo personas exactly as the annotations route does, and pick the
   paragraph where the personas differ most (each has 1–3 notes, the sets differ). For every note,
   the expected explanation cache entries (restatement and Background, computed with the explain
   service's own key functions) must exist and be verified, or nothing else runs.
2. Then, as one temporary anonymous reader: the annotations per persona and POST /v1/explain for
   each note (all cache hits by step 1; the script stops at the first response that isn't cached
   and verified), and writes the JSON. The reader is deleted in `finally`.

Production writes (the dry run prints them): 1 anonymous Auth user (created, then deleted); the
docs the annotations GET writes for it (removed by DELETE /v1/me); +N hits on
`ops/explain/days/{date}` (not reversible). No model calls.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import get_settings
from app.explain import service
from app.explain.inputs import span_inputs
from app.graph.loader import load_graph, set_graph
from app.ingest.models import is_corpus
from app.reader.personas import PERSONA_THINKS_IN, PERSONAS
from app.scoring import scorer
from app.scoring.scorer import ScoringInputs
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.explain_repo import ExplainRepo
from app.store.persona_repo import get_template
from app.store.reader_repo import state_from_demo
from scripts.live_check_explain import API, sign_in_anonymously
from scripts.warm_demo import DEMO_ARTICLES

OUT = Path(__file__).resolve().parents[3] / "apps/web/src/landing/demo.json"
# Toggle label → persona (the personas' analogy frames: software / cricket / law).
LABELS = {
    "newcomer": "Software engineer",
    "trader": "Cricket fan",
    "policy_student": "Policy student",
}
STYLE = "normal"  # demo readers' explanation style
MAX_NOTES = 3


async def choose(graph, docs, now):
    """(article, paragraph, {persona: [span]}) where the personas differ most, or None."""
    store = get_doc_store()
    states = {
        p: state_from_demo("landing", p, await get_template(store, p), copied=False)
        for p in PERSONAS
    }
    explainers = scorer.explainer_index([d for d in docs.values() if is_corpus(d)])
    ranked = []
    for cid in DEMO_ARTICLES:
        doc = docs.get(cid)
        if doc is None:
            continue
        per = {
            p: scorer.annotate(
                doc, graph, s, "balanced", now, ScoringInputs(explainers=explainers)
            ).spans
            for p, s in states.items()
        }
        for para in doc.paragraphs:
            notes = {p: [s for s in spans if s.paragraph_id == para.id] for p, spans in per.items()}
            counts = [len(v) for v in notes.values()]
            if min(counts) < 1 or max(counts) > MAX_NOTES:
                continue
            sets = [frozenset(s.concept_id for s in v) for v in notes.values()]
            distinct = len(set(sets))
            frames = len({PERSONA_THINKS_IN[p] for p in notes})
            score = (distinct, len(frozenset().union(*sets)), max(counts) - min(counts), frames)
            ranked.append((score, doc, para, notes, states))
    return sorted(ranked, key=lambda r: r[0], reverse=True)


async def precheck(doc, para, notes, states, graph, now) -> list[str]:
    """Missing or unverified cache entries for every note (empty = all present)."""
    repo, missing = ExplainRepo(get_doc_store()), []
    rv, bv = service.restate_version(), service.background_version()
    for persona, spans in notes.items():
        for s in spans:
            demand = next(d for d in doc.demands if d.id == s.demand_id)
            inputs = span_inputs(
                doc, demand, graph, states[persona], now, PERSONA_THINKS_IN[persona], STYLE
            )
            r, b = await asyncio.gather(
                repo.get(inputs.restate_key(rv)), repo.get(inputs.background_key(bv))
            )
            if not (r and r.get("verified")) or not (b and b.get("verified")):
                missing.append(
                    f"{persona} {s.demand_id} {s.label} (restate {'ok' if r else 'missing'}, "
                    f"background {'ok' if b else 'missing'})"
                )
    return missing


async def warm(api, doc, notes) -> None:
    """POST /v1/explain for each note as one temporary demo reader (≤ 5 here, under its cap)."""
    async with httpx.AsyncClient(timeout=180) as client:
        client.headers["Authorization"] = f"Bearer {await sign_in_anonymously(client)}"
        try:
            for persona, spans in notes.items():
                for s in spans:
                    e = (
                        await client.post(
                            f"{api}/v1/explain?persona={persona}",
                            json={"content_id": doc.content_id, "demand_id": s.demand_id},
                        )
                    ).json()
                    print(
                        f"      {persona} {s.label}: {e.get('kind')} "
                        f"cached={e.get('cached')} "
                        f"capped={e.get('capped')} "
                        f"background={'yes' if e.get('background') else 'no'}"
                    )
        finally:
            resp = await client.delete(f"{api}/v1/me")
            print(f"    warm cleanup: DELETE /v1/me → {resp.status_code}")


async def confirm(api, doc, para, notes) -> dict:
    out: dict = {
        "content_id": doc.content_id,
        "title": doc.title,
        "site": doc.site,
        "paragraph": {"id": para.id, "text": para.text},
        "personas": {},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        client.headers["Authorization"] = f"Bearer {await sign_in_anonymously(client)}"
        try:
            for persona in notes:
                ann = (
                    await client.get(
                        f"{api}/v1/content/{doc.content_id}/annotations?persona={persona}"
                    )
                ).json()
                spans = [
                    a
                    for a in ann["annotations"]
                    if a["kind"] == "span" and a["paragraph_id"] == para.id
                ]
                cards = []
                for a in spans:
                    e = (
                        await client.post(
                            f"{api}/v1/explain?persona={persona}",
                            json={"content_id": doc.content_id, "demand_id": a["id"]},
                        )
                    ).json()
                    if (
                        not e.get("cached")
                        or e.get("kind") != "verified"
                        or not e.get("background")
                    ):
                        raise SystemExit(
                            f"stop: {persona} {a['label']} is not a cached verified card "
                            f"({e.get('kind')}, cached={e.get('cached')})"
                        )
                    cards.append(
                        {
                            k: a[k]
                            for k in (
                                "id",
                                "kind",
                                "anchor",
                                "paragraph_id",
                                "score",
                                "concept_id",
                                "label",
                                "definition",
                                "domain",
                                "prerequisites",
                                "band",
                                "level",
                            )
                        }
                        | {
                            "explanation": {
                                k: e[k]
                                for k in (
                                    "id",
                                    "kind",
                                    "background",
                                    "author_says",
                                    "analogy_domain",
                                    "band",
                                    "can_simpler",
                                    "can_deeper",
                                )
                            }
                        }
                    )
                out["personas"][persona] = {
                    "label": LABELS[persona],
                    "frame": PERSONA_THINKS_IN[persona],
                    "annotations": cards,
                }
        finally:
            resp = await client.delete(f"{api}/v1/me")
            print(f"cleanup: DELETE /v1/me → {resp.status_code}")
    return out


async def main(args) -> int:
    graph = await load_graph(get_settings().concepts_uri)
    set_graph(graph)
    docs = {d.content_id: d async for d in get_content_store().iter_all()}
    now = datetime.now(UTC)
    ranked = await choose(graph, docs, now)
    if args.paragraph:  # "<content id prefix>:<paragraph id>", e.g. 23324188:p5
        prefix, pid = args.paragraph.split(":")
        ranked = [r for r in ranked if r[1].content_id.startswith(prefix) and r[2].id == pid]
        if not ranked:
            print(f"STOP: {args.paragraph} is not a candidate paragraph")
            return 1
    chosen = None
    for score, doc, para, notes, states in ranked:
        print(f"article {doc.content_id[:8]} «{doc.title[:60]}», paragraph {para.id} score {score}")
        for p, spans in notes.items():
            print(
                f"    {LABELS[p]:18s} ({p}): "
                + ", ".join(f"{s.label} [{s.level}/{s.band}]" for s in spans)
            )
        missing = await precheck(doc, para, notes, states, graph, now)
        if missing and args.warm and args.paragraph:
            # Approved production write (Sourabh, 2026-10-11): warm this paragraph's missing cards
            # through the normal verified path, then check again.
            print(f"    warming {len(missing)} cards: " + "; ".join(missing))
            await warm(args.api.rstrip("/"), doc, notes)
            missing = await precheck(doc, para, notes, states, graph, now)
        if not missing:
            chosen = (score, doc, para, notes, states)
            break
        print("    not fully cached: " + "; ".join(missing))
    if chosen is None:
        print("STOP: no candidate paragraph has every card cached and verified (nothing requested)")
        return 1
    score, doc, para, notes, states = chosen
    print(f"CHOSEN {doc.content_id[:8]} {para.id}: {para.text[:220]}…")
    n = sum(len(v) for v in notes.values())
    print(f"precheck: all {n} cards cached and verified")
    print(
        f"production writes if run: 1 anonymous Auth user (deleted), its docs (deleted), "
        f"+{n} explain hits"
    )
    if args.dry_run:
        return 0
    data = await confirm(args.api.rstrip("/"), doc, para, notes)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--paragraph", help="force one paragraph, e.g. 23324188:p5")
    parser.add_argument("--warm", action="store_true", help="warm that paragraph's missing cards")
    parser.add_argument("--api", default=API)
    sys.exit(asyncio.run(main(parser.parse_args())))
