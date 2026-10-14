"""M9 part 2 acceptance 5 on the emulator harness, real Vertex: same-page synonyms grow once.

    FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 FIRESTORE_PROJECT=demo-readlayer ENV=dev \\
    GROWTH_ENABLED=true uv run python -m scripts.harness_m9_merge <url>

The served graph already holds the five concepts grown from the BBC PFAS article (folded Oct 10),
so they are taken out of this process's graph first; then the article is fetched and analysed
with a reader's growth slots, as Read any link does. Pass: "Forever chemicals" and "PFAS" end as
one concept with the other label as an alias, while PFAS / PFOS and the two site-assessment
phases, if grown, stay separate. Emulator only.
"""

import argparse
import asyncio
import os
import sys

FOLDED = {
    "c_forever_chemicals",
    "c_pfas",
    "c_pfos",
    "c_phase_1_environmental_site_assessment",
    "c_phase_2_environmental_site_assessment",
}


async def main(a: argparse.Namespace) -> int:
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        print("emulator only: set FIRESTORE_EMULATOR_HOST")
        return 2
    from app import llm
    from app.auth import Caller
    from app.config import get_settings
    from app.graph.graph import ConceptGraph
    from app.graph.loader import get_graph, load_serving_graph, set_graph
    from app.graph.models import ConceptGraphFile
    from app.ingest import quota, service

    settings = get_settings()
    assert settings.db_project == "demo-readlayer", settings.db_project
    await load_serving_graph(settings.concepts_uri)
    g = get_graph()
    kept = [
        c.model_copy(update={"prerequisites": [p for p in c.prerequisites if p not in FOLDED]})
        for c in g.concepts
        if c.id not in FOLDED
    ]
    set_graph(ConceptGraph(ConceptGraphFile(version=g.version + "-m9h", concepts=kept)))
    print(f"graph: {len(g)} → {len(get_graph())} concepts (the article's five taken out)")
    spend = llm.get_spend_store()
    start = await spend.get_today()
    doc = await service.ingest_url(
        a.url, "user_ingested", quota.growth_reserver(Caller("m9-merge-harness", False), settings)
    )
    grown = {d.label: d.target_id for d in doc.demands if d.grown}
    print(f"grown links: {grown}")
    concepts = {cid: get_graph().get(cid) for cid in set(grown.values())}
    for cid, c in concepts.items():
        print(f"  {cid}: {c.label!r} aliases={c.aliases}")
    labels = {k.casefold(): v for k, v in grown.items()}
    fc, pfas, pfos = (labels.get(x) for x in ("forever chemicals", "pfas", "pfos"))
    ok = fc is not None and fc == pfas
    ok &= pfos is None or pfos != pfas
    p1 = next((v for k, v in labels.items() if k.startswith("phase 1")), None)
    p2 = next((v for k, v in labels.items() if k.startswith("phase 2")), None)
    ok &= p1 is None or p2 is None or p1 != p2
    print(f"forever chemicals → {fc}, PFAS → {pfas}, PFOS → {pfos}, phases → {p1} / {p2}")
    print(f"run spend ${await spend.get_today() - start:.4f} (emulator ledger)")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    sys.exit(asyncio.run(main(p.parse_args())))
