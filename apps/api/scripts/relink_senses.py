"""Re-link the demo docs' one-word sense keys (decision 66, plan docs/plans/sense-links.md L2/L3).

    uv run python -m scripts.relink_senses --dry-run           # model calls, no Firestore write
    uv run python -m scripts.relink_senses --write             # apply the saved new links
    uv run python -m scripts.relink_senses --write --delete-cache   # ... and retire their cards
    uv run python -m scripts.relink_senses --revert [--delete-cache]  # put the old links back

Docs: warm_demo's DEMO_ARTICLES and the article rows of the demo feeds' first pages, corpus only,
held-out excluded. A demand is in scope when the old rule linked it exactly (`exact_target`) and
decision 66's rule refuses it (`alias_target` is None); grown demands stay. The dry run re-links
those demands with the ingest linker (embeddings + link_confirm, ledgered, ≤ MAX_USD), prints
every old → new, the persona diff and the cache entries to retire, and saves it all to STATE.
`--write` / `--revert` touch only the saved docs, each in one transaction that updates only
`demands` and refuses a doc whose demands changed since or that is being grown. Cache deletes
(`--delete-cache`) need Sourabh's yes on the printed count.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.explain.inputs import paragraph_inputs, span_inputs
from app.graph.graph import ConceptGraph
from app.graph.linking import alias_target, exact_target
from app.ingest.models import ContentDoc, Demand, is_corpus
from app.reader.state import ReaderState
from app.store.content_repo import ContentStore, Relinked

STATE = Path(__file__).resolve().parents[3] / "data" / "build_cache" / "relink_senses.json"
PER_DOC_USD = 0.01  # one link_confirm batch + embeddings; link_confirm measured ≈ $0.004 (M2.2)
MAX_USD = 1.0
Use = Literal["new", "old"]


@dataclass(frozen=True)
class Entry:
    content_id: str
    before: list[tuple[str, str | None]]  # every demand's (id, target) when the dry run ran
    changes: dict[str, tuple[str | None, str | None]]  # demand id → (old, new)

    def snapshot(self, use: Use) -> list[tuple[str, str | None]]:
        """What the doc must hold for this apply: as planned, or as written (for a revert)."""
        if use == "new":
            return self.before
        return [(i, self.changes[i][1] if i in self.changes else t) for i, t in self.before]

    def targets(self, use: Use) -> dict[str, str | None]:
        return {i: (new if use == "new" else old) for i, (old, new) in self.changes.items()}


def in_scope(doc: ContentDoc, graph: ConceptGraph, heldout: bool) -> list[Demand]:
    if heldout or not is_corpus(doc):
        return []
    return [
        d
        for d in doc.demands
        if not d.grown
        and d.target_id is not None
        and exact_target(graph, d) == d.target_id
        and alias_target(graph, d) is None
    ]


def estimate(n_docs: int) -> float:
    return n_docs * PER_DOC_USD


def check_estimate(n_docs: int) -> None:
    if estimate(n_docs) > MAX_USD:
        raise SystemExit(f"estimate ${estimate(n_docs):.2f} for {n_docs} docs is over ${MAX_USD}")


def retired_hashes(doc: ContentDoc, demands: Sequence[Demand], graph: ConceptGraph) -> set[str]:
    """The cached cards these demands' spans and paragraphs were made under (their old links)."""
    now, state = datetime.now(UTC), ReaderState()
    out: set[str] = set()
    for d in demands:
        span = span_inputs(doc, d, graph, state, now, None, "normal")
        para = paragraph_inputs(doc, d.paragraph_id, graph, state, None, "normal")
        out |= {i.span_hash for i in (span, para) if i is not None}
    return out


async def apply(
    store: ContentStore, entries: Sequence[Entry], use: Use, now: datetime
) -> dict[str, Relinked]:
    out: dict[str, Relinked] = {}
    for e in entries:
        doc = await store.get(e.content_id)
        if doc is None:
            out[e.content_id] = "missing"
            continue
        targets = e.targets(use)
        demands = [
            d.model_copy(update={"target_id": targets[d.id]}) if d.id in targets else d
            for d in doc.demands
        ]
        out[e.content_id] = await store.relink_demands(e.content_id, e.snapshot(use), demands, now)
    return out


# ---------------------------------------------------------------- production runs


async def demo_doc_ids() -> list[str]:
    from app.ingest.urls import url_hash
    from scripts.preingest_feed import first_page_articles
    from scripts.warm_demo import DEMO_ARTICLES

    urls = [u for rows in (await first_page_articles()).values() for u in rows]
    return list(dict.fromkeys([*DEMO_ARTICLES, *(url_hash(u) for u in urls)]))


async def dry_run() -> int:
    from app import llm
    from app.config import get_settings
    from app.graph.enrich import confirm_links
    from app.graph.heldout import is_heldout
    from app.graph.linking import link_demands
    from app.graph.loader import get_graph
    from app.ingest.urls import url_hash
    from app.store.content_repo import get_content_store
    from app.store.explain_repo import ExplainRepo
    from scripts.eval_heldout import read_heldout

    settings = get_settings()
    ids = await demo_doc_ids()  # loads the serving graph (file + grown + prereq fixes)
    graph = get_graph()
    if "+g" not in graph.version:
        raise SystemExit(f"grown concepts did not load (graph {graph.version}); stopping")
    held = {url_hash(e.url) for e in read_heldout()}
    spent = await llm.get_spend_store().get_today()
    if spent + MAX_USD > settings.llm_daily_budget_usd:
        raise SystemExit(f"today's spend ${spent:.2f} leaves no room for ${MAX_USD}")
    store = get_content_store()
    docs = {cid: d for cid in ids if (d := await store.get(cid)) is not None}
    scoped = {
        cid: s
        for cid, d in docs.items()
        if (s := in_scope(d, graph, is_heldout(cid) or cid in held))
    }
    print(f"project {settings.db_project}; graph {graph.version}; {len(docs)} demo docs, "
          f"{len(scoped)} with sense keys; spent today ${spent:.2f}")  # fmt: skip
    check_estimate(len(scoped))
    metas: list[llm.CallMeta] = []
    embed_cost = 0.0

    async def embed(texts: list[str]) -> list[list[float]]:
        nonlocal embed_cost
        res = await llm.embed(texts, task_type="SEMANTIC_SIMILARITY")
        embed_cost += res.cost_usd
        return res.vectors

    async def confirm(questions):  # type: ignore[no-untyped-def]
        return await confirm_links(questions, llm.run_with_meta, metas)

    entries: list[Entry] = []
    hashes: set[str] = set()
    for cid, demands in scoped.items():
        doc = docs[cid]
        linked, _ = await link_demands(
            graph, demands, {p.id: p.text for p in doc.paragraphs}, settings.link_threshold,
            embed=embed, confirm=confirm, site=doc.site, url=doc.final_url,
        )  # fmt: skip
        changes = {
            d.id: (d.target_id, n.target_id)
            for d, n in zip(demands, linked, strict=True)
            if n.target_id != d.target_id
        }
        print(f"\n{cid[:10]} {doc.title[:70]!r}: {len(demands)} in scope, {len(changes)} change")
        for d in demands:
            old, new = changes.get(d.id, (d.target_id, d.target_id))
            label = lambda c: graph.get(c).label if c and graph.get(c) else c  # noqa: E731
            print(f"  {d.anchor.exact!r}: {label(old)} → {label(new)}")
        if changes:
            entries.append(Entry(cid, [(d.id, d.target_id) for d in doc.demands], changes))
            hashes |= retired_hashes(doc, [d for d in demands if d.id in changes], graph)
        spend = embed_cost + sum(m.cost_usd for m in metas)
        if spend > MAX_USD:
            raise SystemExit(f"spend ${spend:.2f} passed ${MAX_USD}; stopping, nothing saved")
    await persona_diff(docs, entries, graph)
    keys = await ExplainRepo(_doc_store()).keys_for_spans(hashes)
    spend = embed_cost + sum(m.cost_usd for m in metas)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "graph": graph.version, "made_at": datetime.now(UTC).isoformat(),
        "entries": [e.__dict__ for e in entries], "span_hashes": sorted(hashes),
    }, indent=1), encoding="utf-8")  # fmt: skip
    print(f"\nwould write {len(entries)} docs, "
          f"{sum(len(e.changes) for e in entries)} demands; would retire {len(keys)} cached "
          f"cards ({len(hashes)} spans/paragraphs); spent ${spend:.4f}; saved {STATE}")  # fmt: skip
    return 0


def _doc_store():  # type: ignore[no-untyped-def]
    from app.store.docstore import get_doc_store

    return get_doc_store()


async def persona_diff(
    docs: dict[str, ContentDoc], entries: Sequence[Entry], graph: ConceptGraph
) -> None:
    from app.reader.personas import PERSONAS
    from app.scoring import scorer
    from app.store.persona_repo import get_template
    from app.store.reader_repo import state_from_demo

    now = datetime.now(UTC)
    print("\npersona diff (notes per demo doc, old links → new):")
    for e in entries:
        doc = docs[e.content_id]
        targets = e.targets("new")
        relinked = doc.model_copy(update={"demands": [
            d.model_copy(update={"target_id": targets[d.id]}) if d.id in targets else d
            for d in doc.demands
        ]})  # fmt: skip
        for persona in PERSONAS:
            state = state_from_demo("relink", persona, await get_template(_doc_store(), persona),
                                    False)  # fmt: skip
            before = scorer.annotate(doc, graph, state, "balanced", now).spans
            after = scorer.annotate(relinked, graph, state, "balanced", now).spans
            b = {s.concept_id: s.label for s in before}
            a = {s.concept_id: s.label for s in after}
            print(f"  {e.content_id[:10]} {persona:14} {len(b)} → {len(a)}  "
                  f"+{sorted(a[k] for k in a.keys() - b.keys())} "
                  f"-{sorted(b[k] for k in b.keys() - a.keys())}")  # fmt: skip


async def write_or_revert(use: Use, delete_cache: bool) -> int:
    from app.store.content_repo import get_content_store
    from app.store.explain_repo import ExplainRepo

    saved = json.loads(STATE.read_text(encoding="utf-8"))
    entries = [
        Entry(e["content_id"], [tuple(x) for x in e["before"]],  # type: ignore[misc]
              {k: tuple(v) for k, v in e["changes"].items()})  # type: ignore[misc]
        for e in saved["entries"]
    ]  # fmt: skip
    verdicts = await apply(get_content_store(), entries, use, datetime.now(UTC))
    for cid, v in verdicts.items():
        print(f"  {cid[:10]} {use}: {v}")
    repo = ExplainRepo(_doc_store())
    keys = await repo.keys_for_spans(saved["span_hashes"])
    if delete_cache:
        print(f"retired {await repo.delete_keys(keys)} cached cards")
    else:
        print(f"{len(keys)} cached cards to retire: re-run with --delete-cache on Sourabh's yes")
    return 0 if all(v == "ok" for v in verdicts.values()) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--revert", action="store_true")
    parser.add_argument("--delete-cache", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        sys.exit(asyncio.run(dry_run()))
    sys.exit(asyncio.run(write_or_revert("new" if args.write else "old", args.delete_cache)))
