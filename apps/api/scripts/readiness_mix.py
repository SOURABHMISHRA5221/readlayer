"""Readiness levels the demo personas' For you rows get (decision 60, plan W1). Read only.

    uv run python -m scripts.readiness_mix            # after `make check-gcp`

For each demo persona: the production template (`persona_templates/{p}`), its stored feed
(`persona_feeds/{p}`) and the served graph (Cloud Storage plus `graph_growth`), ranked and
selected in memory exactly as GET /v1/feed does for a fresh demo reader; prints how many rows
land on each level. Writes nothing.
"""

import asyncio
import sys
from collections import Counter
from datetime import UTC, datetime

STOP_SHARE = 0.8  # one level on ≥ 80% of the newcomer's rows: tell Sourabh, don't retune


async def main() -> int:
    from app.config import get_settings
    from app.graph.loader import get_graph, load_serving_graph
    from app.recs import feed_rank as fr
    from app.recs.feed import PERSONA_COUNTRY, SnapshotRepo, side_for, snapshot_candidates
    from app.recs.outlets import LOCAL_SHARE
    from app.recs.rank import PERSONA_FORMAT_PRIORS
    from app.store.docstore import get_doc_store
    from app.store.persona_repo import get_template
    from app.store.reader_repo import state_from_demo

    await load_serving_graph(get_settings().concepts_uri)
    graph, now, store = get_graph(), datetime.now(UTC), get_doc_store()
    print(f"served graph {graph.version}, {len(graph)} concepts")
    stop = False
    for persona in ("newcomer", "trader", "policy_student"):
        doc = await get_template(store, persona)
        snap = await SnapshotRepo(store).get(persona)
        if snap is None:
            print(f"{persona}: no stored feed")
            continue
        topics = list(snap.topics)
        reader = fr.FeedReader(
            state=state_from_demo("readiness-mix", persona, doc, False),
            interest=dict.fromkeys(topics, 1.0),
            prior=PERSONA_FORMAT_PRIORS[persona],
        )
        ranked = fr.select(
            fr.rank(snapshot_candidates(snap, graph), reader, now, graph),
            topics,
            side_for(PERSONA_COUNTRY),
            LOCAL_SHARE,
        )
        levels = Counter(r.readiness or "no line" for r in ranked)
        named = sum(1 for r in ranked if r.readiness)
        print(
            f"{persona} (template graph {doc.get('graph_version')}, feed {snap.prepared_at}): "
            f"{len(ranked)} rows, {named} with a line: {dict(sorted(levels.items()))}"
        )
        if persona == "newcomer" and named:
            top, count = max(((k, v) for k, v in levels.items() if k != "no line"),
                             key=lambda kv: kv[1])  # fmt: skip
            if count / named >= STOP_SHARE:
                stop = True
                print(f"STOP: {top} on {count}/{named} of the newcomer's rows (≥ 80%)")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
