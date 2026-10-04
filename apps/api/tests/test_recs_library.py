from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from app.ingest.models import Anchor, ContentDoc, Demand, StoredParagraph
from app.recs import library as lib


def concept(cid, label, domain="finance", b=0.0, prereqs=(), aliases=()):
    return Concept(
        id=cid,
        label=label,
        domain=domain,
        definition="d",
        base_difficulty=b,
        prerequisites=list(prereqs),
        aliases=list(aliases),
        embedding=[1.0, 0.0],
    )


GRAPH = ConceptGraph(
    ConceptGraphFile(
        version="t",
        concepts=[
            concept("c_bond", "Bond", b=1.5),
            concept("c_yield", "Bond yield", b=1.0, prereqs=["c_bond"]),
            concept("c_curve", "Yield curve", b=1.5, prereqs=["c_yield"]),
            concept("c_inflation", "Inflation", "economics", b=-1.0),
            concept("c_repo", "Repo rate", "policy", b=0.5),
        ],
    )
)


def demand(did, target, salience=0.8, explained=False):
    return Demand(
        id=did,
        paragraph_id="p0",
        anchor=Anchor(exact=target, prefix="", suffix="", start=0, end=1),
        type="concept",
        label=target,
        target_id=target,
        salience=salience,
        explained_in_text=explained,
        zipf=3.0,
    )


def doc(cid, title, site, demands, text=None, published="2026-10-03", url=None):
    body = text or f"{title} unique body text for {cid} " * 5
    return ContentDoc(
        content_id=cid,
        url=url or f"https://{cid}.example",
        final_url=url or f"https://{cid}.example",
        title=title,
        site=site,
        source="fetch",
        fetched_at="now",
        published=published,
        paragraphs=[StoredParagraph(id="p0", text=body, structure=0.0)],
        demands=demands,
        demands_dropped=0,
        llm_calls=[],
    )


SHARED_TEXT = "the central bank raised the repo rate by twenty five basis points on friday " * 6
ARTICLE = doc(
    "main",
    "RBI raises repo rate as bond yields jump",
    "Mint",
    [demand("1", "c_repo", 0.9), demand("2", "c_yield", 0.8), demand("3", "c_inflation", 0.6)],
    text=SHARED_TEXT,
)
DOCS = [
    ARTICLE,
    doc(
        "synd",
        "Central bank lifts rates",
        "BusinessLine",
        [demand("1", "c_repo")],
        text=SHARED_TEXT,
    ),
    doc(
        "event",
        "RBI raises repo rate, bond yields jump",
        "BBC News",
        [demand("1", "c_repo"), demand("2", "c_yield")],
        published="2026-10-04",
    ),
    doc(
        "old_event",
        "RBI raises repo rate, bond yields jump",
        "The Guardian",
        [demand("1", "c_repo"), demand("2", "c_yield")],
        published="2026-01-04",
    ),
    doc(
        "wiki_bond",
        "Bond (finance) - Wikipedia",
        lib.WIKIPEDIA_SITE,
        [demand("1", "c_bond", 0.9)],
        url="https://en.wikipedia.org/wiki/Bond_(finance)",
    ),
    doc("explains_bond", "What is a bond?", "Mint", [demand("1", "c_bond", 0.8, explained=True)]),
    doc("mentions_bond", "Markets wrap", "Mint", [demand("1", "c_bond", 0.9, explained=False)]),
    doc(
        "curve",
        "The yield curve inverts again",
        "The Economic Times",
        [demand("1", "c_curve", 0.9)],
    ),
    doc(
        "angle_uk",
        "UK view on repo and yields",
        "The Guardian",
        [demand("1", "c_repo"), demand("2", "c_yield"), demand("3", "c_inflation")],
    ),
]
INDEX = lib.LibraryIndex.build(DOCS)


def ids(cands, relation):
    return {c.content_id for c in cands if c.relation == relation}


def test_same_story_finds_syndicated_and_same_event_but_not_old_news():
    cands = lib.same_story(INDEX, ARTICLE, {"c_yield"})
    assert {c.content_id for c in cands} == {"synd", "event"}
    synd = next(c for c in cands if c.content_id == "synd")
    assert synd.relevance == 1.0


def test_primer_prefers_the_wikipedia_article_on_a_weak_prerequisite():
    weak_reader = {"finance": -1.0}
    cands = lib.primers(INDEX, ARTICLE, GRAPH, weak_reader, ["c_yield"])
    by_id = {c.content_id: c for c in cands}
    assert set(by_id) == {"wiki_bond", "explains_bond"}  # "mentions_bond" doesn't explain it
    assert by_id["wiki_bond"].relevance == 1.0 > by_id["explains_bond"].relevance
    assert by_id["wiki_bond"].detail == "Bond" and by_id["wiki_bond"].trigger_ids == ("c_yield",)


def test_primer_falls_back_to_the_concept_itself_for_a_strong_reader():
    strong = {"finance": 3.0}
    cands = lib.primers(INDEX, ARTICLE, GRAPH, strong, ["c_yield"])
    assert all(c.detail == "Bond yield" for c in cands)


def test_deeper_follows_dependents():
    cands = lib.deeper(INDEX, ARTICLE, GRAPH, ["c_yield"])
    assert {(c.content_id, c.detail) for c in cands} == {("curve", "Yield curve")}


def test_angle_needs_shared_core_concepts_and_another_source():
    cands = lib.angles(INDEX, ARTICLE, {"c_repo"})
    by_id = {c.content_id: c for c in cands}
    assert "angle_uk" in by_id and by_id["angle_uk"].detail == "the UK"
    assert "wiki_bond" not in by_id and "main" not in by_id


def test_library_candidates_dedupe_per_relation():
    cands = lib.library_candidates(INDEX, ARTICLE, GRAPH, {"finance": -1.0}, ["c_yield", "c_repo"])
    keys = [(c.relation, c.content_id) for c in cands]
    assert len(keys) == len(set(keys))
    assert ids(cands, "primer") >= {"wiki_bond"} and ids(cands, "deeper") == {"curve"}
