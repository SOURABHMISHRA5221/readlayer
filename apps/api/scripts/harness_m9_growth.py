"""M9 part 1 acceptance 2 on the emulator harness, real Vertex (plan docs/plans/M9.md).

    FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 FIRESTORE_PROJECT=demo-readlayer ENV=dev \\
        uv run python -m scripts.harness_m9_growth <url> [--bad-url URL]

1. reader A opens <url> with growth caps at 0: stored, few links, grow_pending true;
2. reader A reopens with the normal caps: POST .../grow's service grows it (linked > 0), the
   reader's growth counter equals the labels tried;
3. reader B reopens: "none", no model call, no slot;
4. a fetch that fails reserves nothing (no growth counter written).
Emulator only: refuses to run without FIRESTORE_EMULATOR_HOST.
"""

import argparse
import asyncio
import os
import sys

from app import llm
from app.auth import Caller
from app.config import get_settings
from app.graph.loader import get_graph, load_serving_graph
from app.ingest import quota, service
from app.ingest.growing import grow_stored
from app.ingest.urls import url_hash
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.spend_repo import today_utc


def linked(doc) -> int:
    return sum(d.target_id is not None for d in doc.demands)


async def counter(uid: str) -> int:
    doc = await get_doc_store().get(f"users/{uid}/growth_counts/{today_utc()}")
    return int((doc or {}).get("count", 0))


async def main(a: argparse.Namespace) -> int:
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        print("emulator only: set FIRESTORE_EMULATOR_HOST")
        return 2
    settings = get_settings()
    assert settings.db_project == "demo-readlayer", settings.db_project
    await load_serving_graph(settings.concepts_uri)
    print(f"graph: {len(get_graph())} concepts")
    spend = llm.get_spend_store()
    start = await spend.get_today()
    a_reader, b_reader = Caller("m9-harness-a", False), Caller("m9-harness-b", False)
    capped = settings.model_copy(update={"growth_per_uid_day": 0})

    doc = await service.ingest_url(a.url, "user_ingested", quota.growth_reserver(a_reader, capped))
    slots = await counter(a_reader.uid)
    print(f"1. stored {doc.content_id}: {linked(doc)}/{len(doc.demands)} linked, "
          f"grow_pending={doc.grow_pending}, tried={doc.grow_tried}, slots={slots}")  # fmt: skip
    ok = doc.grow_pending is True and await counter(a_reader.uid) == 0

    done = await grow_stored(doc, quota.growth_reserver(a_reader, settings))
    after = await get_content_store().get(doc.content_id)
    used = await counter(a_reader.uid)
    print(f"2. grow: {done.status}, linked +{done.linked} -> "
          f"{linked(after)}/{len(after.demands)}, tried={after.grow_tried}, "
          f"slots used={used}, grow_pending={after.grow_pending}")  # fmt: skip
    ok &= done.status == "grown" and done.linked > 0 and used == len(after.grow_tried)

    before_b = await spend.get_today()
    again = await grow_stored(after, quota.growth_reserver(b_reader, settings))
    print(f"3. reader B: {again.status}, slots={await counter(b_reader.uid)}, "
          f"spend +${await spend.get_today() - before_b:.4f}")  # fmt: skip
    ok &= again.status == "none" and await counter(b_reader.uid) == 0

    if a.bad_url:
        c_reader = Caller("m9-harness-c", False)
        try:
            await service.ingest_url(
                a.bad_url, "user_ingested", quota.growth_reserver(c_reader, settings)
            )
        except Exception as exc:  # the fetch fails: nothing reserved
            print(f"4. bad fetch: {type(exc).__name__}, slots={await counter(c_reader.uid)}")
        ok &= await counter(c_reader.uid) == 0
    print(f"run spend ${await spend.get_today() - start:.4f} (emulator ledger)")
    print("PASS" if ok else "FAIL")
    assert url_hash(a.url) == doc.content_id
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--bad-url")
    sys.exit(asyncio.run(main(p.parse_args())))
