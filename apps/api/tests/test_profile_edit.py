"""Edit a profile with a prompt (DESIGN §15.3, M7): whitelist, resolve, preview, apply, undo,
limits, privacy, and session-only edits for demo readers."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import llm
from app.content import router as read_router
from app.graph import resolve as resolve_mod
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import Concept, ConceptGraphFile
from app.main import app
from app.reader import model
from app.reader import profile_edit as pe
from app.reader.model import Edge, Evidence
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.fakes import auth, consented, meta

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def concept(cid: str, domain: str, b: float, freq: int, label: str | None = None) -> Concept:
    return Concept(
        id=cid,
        label=label or cid.removeprefix("c_").replace("_", " ").title(),
        domain=domain,
        definition=f"Definition of {cid}.",
        base_difficulty=b,
        doc_freq=freq,
        embedding=[1.0, 0.0],
    )


GRAPH = ConceptGraph(
    ConceptGraphFile(
        version="t",
        concepts=[
            concept("c_options", "finance", 0.5, 50, "Options"),
            concept("c_repo_rate", "economics", -0.5, 40, "Repo rate"),
            *[
                concept(f"c_fin_{i}", "finance", round(-1.5 + i * 0.3, 2), 30 - i)
                for i in range(12)
            ],
        ],
    )
)


class FakeEditLLM:
    """Replaces llm.run_with_meta for profile_edit: returns the scripted ops (validated by the
    real schema), or raises."""

    def __init__(self, output=None, error: Exception | None = None) -> None:
        self.output = output if output is not None else {"ops": []}
        self.error = error
        self.calls: list[dict] = []

    async def __call__(self, task, schema, prompt_vars, **_):
        self.calls.append({"task": task, "vars": prompt_vars})
        if self.error:
            raise self.error
        return llm.LLMResult(schema.model_validate(self.output), meta(task=task))  # flat schema


ACCEPTANCE = {
    "ops": [
        {"op": "set_thinks_in", "domains": ["software"]},
        {"op": "mark_concepts", "names": ["options"], "state": "known"},
        {"op": "set_explanation_style", "length": "short"},
    ]
}


@pytest.fixture
def env(monkeypatch):
    set_content_store(InMemoryContentStore())
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    fake = FakeEditLLM(ACCEPTANCE)
    monkeypatch.setattr(llm, "run_with_meta", fake)

    async def no_embed(texts):  # exact matches only in tests (no network)
        raise llm.LLMUnavailable("no embeddings in tests")

    monkeypatch.setattr(resolve_mod, "_embed", no_embed)
    yield fake
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def google(uid="g1") -> TestClient:
    return consented(TestClient(app, headers=auth(uid)))


def parse(client, text="I'm a backend engineer, I know options well, keep explanations short",
          persona=""):  # fmt: skip
    q = f"?persona={persona}" if persona else ""
    return client.post(f"/v1/me/profile/edits{q}", json={"text": text})


# ---------------------------------------------------------------- whitelist


@pytest.mark.parametrize(
    "bad",
    [
        {"ops": [{"op": "delete_account"}]},  # unknown op
        {"ops": [{"op": "set_density", "density": "guided", "concept_id": "c_options"}]},  # extra
        {"ops": [{"op": "mark_concepts", "names": ["x"] * 31, "state": "known"}]},  # > 30 per op
        {"ops": [{"op": "set_thinks_in", "domains": ["astrology"]}]},  # outside the list
        {"ops": [], "note": "hi"},  # extra top-level field
    ],
)
def test_the_schema_rejects_anything_off_the_whitelist(bad):
    with pytest.raises(ValidationError):
        pe.ProfileEditOps.model_validate(bad)


def test_off_schema_model_output_is_rejected_as_a_whole(env, docs):
    try:
        pe.ProfileEditOps.model_validate({"ops": [{"op": "drop_tables"}]})
    except ValidationError as cause:
        error = llm.LLMUnavailable("profile_edit: invalid output")
        error.__cause__ = cause
    env.error = error
    resp = parse(google())
    assert resp.status_code == 422 and resp.json()["error"] == "not_understood"
    assert not [p for p in docs.docs if "/profile_edits/" in p]


def test_a_concept_id_from_the_model_is_rejected(env, docs):
    env.output = {"ops": [{"op": "mark_concepts", "names": ["c_options"], "state": "known"}]}
    resp = parse(google())
    assert resp.status_code == 422 and resp.json()["error"] == "concept_id_from_model"
    assert not [p for p in docs.docs if "/profile_edits/" in p]


def test_more_than_30_names_in_one_edit_is_refused_before_any_linking(env, monkeypatch):
    calls = []

    async def counting_embed(texts):
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(resolve_mod, "_embed", counting_embed)
    env.output = {
        "ops": [
            {"op": "mark_concepts", "names": [f"idea {i}" for i in range(20)], "state": "known"},
            {"op": "mark_concepts", "names": [f"thing {i}" for i in range(11)], "state": "known"},
        ]
    }
    resp = parse(google())
    assert resp.status_code == 422 and resp.json()["error"] == "too_many_concepts"
    assert calls == []


async def test_the_resolver_sends_at_most_three_batches_of_names():
    seen: list[int] = []

    async def embed(texts):
        return [[1.0, 0.0] for _ in texts]

    async def confirm(questions):
        seen.append(len(questions))
        return {}

    names = [f"unknown idea {i}" for i in range(45)]
    _, unresolved = await resolve_mod.resolve_names(GRAPH, names, 0.5, embed=embed, confirm=confirm)
    assert seen == [30]  # 3 × LINK_BATCH at most reach link_confirm
    assert len(unresolved) == 45


# ---------------------------------------------------------------- privacy


def test_prompt_gets_redacted_text_and_fixed_lists_only(env, caplog):
    text = "I'm sam@example.com, call +91 98765 43210. I know options well."
    with caplog.at_level(logging.INFO):
        resp = parse(google(), text)
    assert resp.status_code == 200
    (call,) = env.calls
    assert set(call["vars"]) == {"text", "domains", "frames"}
    assert "sam@example.com" not in call["vars"]["text"] and "[email]" in call["vars"]["text"]
    assert "98765" not in call["vars"]["text"]
    assert "g1" not in repr(call["vars"])
    assert not [r for r in caplog.records if "options well" in r.getMessage() + repr(r.__dict__)]


def test_unresolved_names_are_reported_dropped_and_never_stored(env, docs, caplog):
    env.output = {
        "ops": [{"op": "mark_concepts", "names": ["options", "Zorblax yield"], "state": "known"}]
    }
    with caplog.at_level(logging.INFO):
        body = parse(google()).json()
    assert body["preview"]["unresolved"] == ["Zorblax yield"]
    assert [k["concept_id"] for k in body["preview"]["known"]] == ["c_options"]
    stored = docs.docs[f"users/g1/profile_edits/{body['edit_id']}"]
    assert "Zorblax" not in repr(stored) and stored["resolved"]["concepts"] == {"c_options": True}
    assert not [r for r in caplog.records if "Zorblax" in repr(r.__dict__)]


# ---------------------------------------------------------------- preview, apply, undo


def test_preview_writes_nothing_to_the_reader_model(env, docs):
    g = google()
    before = {p: d for p, d in docs.docs.items() if p.startswith("users/g1")}
    body = parse(g).json()
    assert body["preview"]["settings"] == [
        {"setting": "explanation_style", "before": "normal", "after": "short"},
        {"setting": "thinks_in", "before": [], "after": ["software"]},
    ]
    edit_paths = ("/profile_edits/", "/profile_edit_counts/")
    after = {
        p: d for p, d in docs.docs.items()
        if p.startswith("users/g1") and not any(e in p for e in edit_paths)
    }  # fmt: skip
    assert after == before


def test_apply_then_undo_restores_alpha_beta_theta_and_settings_exactly(env, docs):
    g = google()
    g.patch("/v1/me/graph/c_options", json={"state": "unknown"})  # an existing edge
    g.patch("/v1/me/settings", json={"density": "minimal"})
    env.output = {
        "ops": [
            *ACCEPTANCE["ops"],
            {"op": "set_domain_level", "domain": "finance", "level": "expert"},
            {"op": "set_density", "density": "guided"},
        ]
    }

    def snapshot():
        return {
            p: d for p, d in docs.docs.items()
            if p.startswith("users/g1/knows/") or p.startswith("users/g1/domains/")
        }  # fmt: skip

    before = snapshot()
    user_before = docs.docs["users/g1"]
    edit = parse(g).json()["edit_id"]
    applied = g.post(f"/v1/me/profile/edits/{edit}/apply").json()
    assert applied["status"] == "applied"
    user = docs.docs["users/g1"]
    assert user["explanation_style"] == "short" and user["density"] == "guided"
    assert user["thinks_in"] == ["software"]
    opts = docs.docs["users/g1/knows/c_options"]
    assert opts["evidence"][-1]["type"] == "profile_edit_concept"
    assert docs.docs["users/g1/domains/finance"]["theta"] == pytest.approx(0.75)  # 0 + ½(1.5 − 0)
    assert docs.docs[f"users/g1/events/profile_edit-{edit}"]["type"] == "profile_edit"

    undone = g.post(f"/v1/me/profile/edits/{edit}/undo").json()
    assert undone["status"] == "undone"
    after = snapshot()
    assert set(after) <= set(before) | {"users/g1/domains/finance"}
    for path, doc in before.items():
        assert after[path]["alpha"] == pytest.approx(doc["alpha"])
        assert after[path]["beta"] == pytest.approx(doc["beta"])
    assert after.get("users/g1/domains/finance", {"theta": 0.0})["theta"] == pytest.approx(0.0)
    assert not [p for p in after if p.startswith("users/g1/knows/c_fin_")]  # created, removed
    user = docs.docs["users/g1"]
    for key in ("explanation_style", "density", "thinks_in"):
        assert user[key] == user_before[key]
    assert g.post(f"/v1/me/profile/edits/{edit}/undo").status_code == 409


def test_undo_keeps_settings_the_reader_changed_since(env, docs):
    g = google()
    edit = parse(g).json()["edit_id"]
    g.post(f"/v1/me/profile/edits/{edit}/apply")
    g.patch("/v1/me/settings", json={"explanation_style": "detailed"})
    g.post(f"/v1/me/profile/edits/{edit}/undo")
    assert docs.docs["users/g1"]["explanation_style"] == "detailed"
    assert docs.docs["users/g1"]["thinks_in"] == []


def test_a_pending_edit_expires_and_is_cleaned_up(env, docs):
    g = google()
    edit = parse(g).json()["edit_id"]
    path = f"users/g1/profile_edits/{edit}"
    docs.docs[path]["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    assert g.post(f"/v1/me/profile/edits/{edit}/apply").status_code == 409
    assert g.get("/v1/me/profile/edits").json() == {"edits": []}
    assert path not in docs.docs
    assert g.post("/v1/me/profile/edits/0123/apply").status_code == 404


def test_the_11th_parse_of_the_day_is_refused(env):
    g = google()
    for _ in range(10):
        assert parse(g).status_code == 200
    capped = parse(g)
    assert capped.status_code == 429 and capped.json()["error"] == "profile_edit_cap"


def test_export_and_delete_cover_edits_and_counts(env, docs):
    g = google()
    edit = parse(g).json()["edit_id"]
    g.post(f"/v1/me/profile/edits/{edit}/apply")
    exported = g.get("/v1/me/export").json()
    blob = repr(exported)
    assert "profile_edits" in blob and "profile_edit_counts" in blob
    assert g.delete("/v1/me").status_code == 204
    assert not [p for p in docs.docs if p.startswith("users/g1")]


def test_signed_in_readers_need_consent(env):
    raw = TestClient(app, headers=auth("g9"))
    assert parse(raw).status_code == 403


# ---------------------------------------------------------------- demo sessions


def test_demo_edits_change_only_this_sessions_persona_and_reset_restores_it(env, docs):
    anon = TestClient(app, headers=auth("a1", anonymous=True))
    template_before = {p: d for p, d in docs.docs.items() if p.startswith("persona_templates/")}
    edit = parse(anon, persona="trader").json()["edit_id"]
    assert anon.post(f"/v1/me/profile/edits/{edit}/apply?persona=trader").status_code == 200
    demo = docs.docs["users/a1/demo_graphs/trader"]
    assert demo["thinks_in"] == ["software"]  # session-only frame for this persona
    assert demo["knows"]["c_options"]["evidence"][-1]["type"] == "profile_edit_concept"
    profile = anon.get("/v1/me/profile?persona=trader").json()
    assert profile["thinks_in"] == ["software"]
    # Another persona and the shared template are untouched.
    assert "users/a1/demo_graphs/newcomer" not in docs.docs
    templates = {p: d for p, d in docs.docs.items() if p.startswith("persona_templates/")}
    assert templates == template_before
    # Applying with another persona's scope is refused.
    edit2 = parse(anon, persona="trader").json()["edit_id"]
    assert anon.post(f"/v1/me/profile/edits/{edit2}/apply?persona=newcomer").status_code == 409

    reset = anon.post("/v1/me/demo/reset", json={"persona": "trader"}).json()
    assert reset["reset"] is True and reset["edits_removed"] == 2
    assert "users/a1/demo_graphs/trader" not in docs.docs
    assert anon.get("/v1/me/profile?persona=trader").json()["thinks_in"] == ["cricket"]
    google_reader = google("g2")
    assert google_reader.post("/v1/me/demo/reset", json={"persona": "trader"}).status_code == 403


def test_demo_parse_caps_per_uid():
    assert pe.MAX_NAMES_PER_EDIT == 30


def test_undo_skips_an_edge_that_was_dropped_after_apply():
    c = GRAPH.get("c_options")
    assert c is not None
    resolved = pe.Resolved({"c_options": True}, {}, {})
    applied = pe.apply(resolved, GRAPH, {}, {}, {}, NOW)
    out = pe.undo(applied.edge_deltas, {}, {}, {}, NOW, {}, {}, {})  # the edge is gone
    assert out.edges == {} and out.removed == []
    # An edge the edit created but the reader touched since stays, minus the edit's share.
    edge = applied.edges["c_options"]
    later = Edge(**(vars(edge) | {
        "alpha": edge.alpha + 2.0,
        "evidence": (*edge.evidence, Evidence("knew_this", 2.0, NOW + timedelta(hours=1))),
    }))  # fmt: skip
    out = pe.undo(applied.edge_deltas, {}, {}, {}, NOW, {"c_options": later}, {}, {})
    kept = out.edges["c_options"]
    assert [e.type for e in kept.evidence] == ["knew_this"]
    p0 = model.prior(0.0, c.base_difficulty)
    assert kept.alpha == pytest.approx(model.K_PRIOR * p0 + 2.0)


def test_a_flat_op_with_another_ops_field_rejects_the_whole_edit(env, docs):
    env.output = {
        "ops": [
            {"op": "set_explanation_style", "length": "short"},
            {"op": "set_density", "density": "guided", "names": ["options"]},  # names: not its
        ]
    }
    resp = parse(google())
    assert resp.status_code == 422 and resp.json()["error"] == "not_understood"
    assert not [p for p in docs.docs if "/profile_edits/" in p]


def test_more_than_20_ops_is_rejected_by_the_strict_schema():
    flat = pe.ModelEditOps.model_validate(
        {"ops": [{"op": "set_density", "density": "guided"}] * 21}
    )
    with pytest.raises(ValidationError):
        pe.strict(flat)


def test_the_preview_leaves_out_settings_that_wouldnt_change(env, docs):
    g = google()
    g.patch("/v1/me/settings", json={"thinks_in": ["software"]})
    settings = parse(g).json()["preview"]["settings"]
    assert [s["setting"] for s in settings] == ["explanation_style"]


def test_reset_restores_the_session_settings_a_demo_edit_changed(env, docs):
    anon = TestClient(app, headers=auth("a3", anonymous=True))
    edit = parse(anon, persona="newcomer").json()["edit_id"]
    anon.post(f"/v1/me/profile/edits/{edit}/apply?persona=newcomer")
    assert docs.docs["users/a3"]["explanation_style"] == "short"
    anon.post("/v1/me/demo/reset", json={"persona": "newcomer"})
    assert docs.docs["users/a3"]["explanation_style"] == "normal"


def test_liked_content_ids_must_look_like_ids(env):
    from app.me.onboarding import OnboardingIn

    with pytest.raises(ValidationError):
        OnboardingIn.model_validate({"field": "software", "liked_content_ids": ["../../x"]})
