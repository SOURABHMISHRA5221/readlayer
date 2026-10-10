"""Folding grown concepts into concepts.json (M2.2 plan §C.5): backup before upload."""

from app.graph.models import Concept, ConceptGraphFile
from app.store.docstore import InMemoryDocStore, set_doc_store
from app.store.growth_repo import GrowthRepo
from scripts import fold_growth


def c(cid, label, prereqs=()):
    return Concept(id=cid, label=label, domain="sports", definition=f"{label} defined.",
                   base_difficulty=0.0, prerequisites=list(prereqs),
                   embedding=[1.0, 0.0])  # fmt: skip


async def test_fold_backs_up_the_previous_file_before_uploading(monkeypatch):
    current = ConceptGraphFile(version="2026-10-11-seeded", concepts=[c("c_goal", "Goal")])
    raw = current.model_dump_json().encode()
    writes: list[tuple[str, bytes]] = []

    async def read(uri):
        return raw

    async def write(uri, data, content_type="application/json"):
        writes.append((uri, data))

    store = InMemoryDocStore()
    set_doc_store(store)
    try:
        repo = GrowthRepo(store)
        await repo.create_if_absent(c("c_offside_trap", "Offside trap", ["c_goal"]), "cid1", {})
        await repo.create_if_absent(c("c_goal", "Goal"), "cid2", {})  # already in the file
        monkeypatch.setattr(fold_growth, "read_bytes", read)
        monkeypatch.setattr(fold_growth, "write_bytes", write)
        assert await fold_growth.run(upload=True) == 0
    finally:
        set_doc_store(None)
    (prev_uri, prev), (uri, new) = writes
    assert prev_uri == fold_growth.GCS_PREV_URI and prev == raw  # backup first, byte for byte
    folded = ConceptGraphFile.model_validate_json(new)
    assert uri == fold_growth.GCS_URI and [x.id for x in folded.concepts] == [
        "c_goal",
        "c_offside_trap",
    ]
    assert folded.version != current.version


async def test_without_upload_nothing_is_written(monkeypatch):
    raw = ConceptGraphFile(version="v", concepts=[c("c_goal", "Goal")]).model_dump_json().encode()
    written = []

    async def read(uri):
        return raw

    async def write(*a, **k):
        written.append(a)

    set_doc_store(InMemoryDocStore())
    try:
        monkeypatch.setattr(fold_growth, "read_bytes", read)
        monkeypatch.setattr(fold_growth, "write_bytes", write)
        await fold_growth.run(upload=False)
    finally:
        set_doc_store(None)
    assert written == []
