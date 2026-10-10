"""Jurisdiction cues and the candidate filter (M2.2, issue #6)."""

from app.graph.jurisdiction import allowed, cues


def test_cues_come_from_site_url_currency_and_names():
    assert cues(site="The Guardian") == {"GB"}
    assert cues(url="https://www.bbc.co.uk/news/articles/x") == {"GB"}
    assert cues(text="Prices rose ₹40 a kilo.") == {"IN"}
    assert cues(text="German Chancellor Friedrich Merz said Berlin would act.") == {"DE"}
    assert cues(text="Talks with US authorities resumed in Washington.") == {"US"}
    assert cues(text="Let us see what the bus driver said.") == frozenset()  # no "us" false hit
    assert "EU" in cues(text="Brussels set new rules for the eurozone.")


def test_jurisdictional_kinds_from_another_country_are_dropped():
    uk = cues(site="The Guardian", text="Chancellor John Healey prepares his Budget.")
    assert allowed("role", "GB", uk)
    assert not allowed("role", "US", uk)  # UK Chancellor ↛ US Treasury Secretary
    germany = cues(site="Reuters", text="German Chancellor Friedrich Merz said...")
    assert not allowed("role", "GB", germany) and not allowed("role", "US", germany)


def test_global_concepts_other_kinds_and_unknown_articles_are_kept():
    uk = frozenset({"GB"})
    assert allowed("tax", "global", uk)
    assert allowed("idea", "US", uk)  # only jurisdictional kinds are filtered
    assert allowed(None, "US", uk)  # pre-M2.2 concepts have no kind
    assert allowed("role", "US", frozenset())  # no cues: we don't know, keep it


def test_eu_bodies_apply_in_member_states():
    assert allowed("regulator", "EU", frozenset({"DE"}))
    assert not allowed("regulator", "EU", frozenset({"GB"}))


# ---------------------------------------------------------------- in the linker


def _concept(cid, label, kind, where, vec):
    from app.graph.models import Concept

    return Concept(id=cid, label=label, domain="policy", definition=f"{label} defined.",
                   base_difficulty=0.0, kind=kind, jurisdiction=where, embedding=vec)  # fmt: skip


def test_plan_links_drops_a_us_role_for_a_uk_chancellor():
    from app.graph.graph import ConceptGraph
    from app.graph.linking import plan_links
    from app.graph.models import ConceptGraphFile
    from app.ingest.models import Anchor, Demand

    graph = ConceptGraph(
        ConceptGraphFile(
            version="t",
            concepts=[
                _concept("c_treasury_secretary", "Treasury Secretary", "role", "US", [1.0, 0.0]),
                _concept(
                    "c_chancellor_of_the_exchequer",
                    "Chancellor of the Exchequer",
                    "role",
                    "GB",
                    [0.99, 0.1],
                ),  # fmt: skip
            ],
        )
    )
    text = "Chancellor John Healey prepares for his first Budget next month."
    anchor = Anchor(exact="Chancellor", prefix="", suffix=" John", start=0, end=10)
    d = Demand(id="d1", paragraph_id="p0", type="concept", label="Chancellor", salience=0.9,
               explained_in_text=False, zipf=4.0, anchor=anchor)  # fmt: skip
    plan = plan_links(graph, [d], {"Chancellor": [1.0, 0.0]}, {"p0": text}, 0.5,
                      site="The Guardian", url="https://www.theguardian.com/x")  # fmt: skip
    (q,) = plan.questions
    assert [cid for cid, *_ in q.candidates] == ["c_chancellor_of_the_exchequer"]
    assert q.kinds == ("role",) and q.jurisdictions == ("GB",) and q.article == ("GB",)


def test_v3_rendering_shows_kind_jurisdiction_and_article_signs():
    from app.graph.enrich import LinkQuestion, render_link_questions

    q = LinkQuestion("d1", "Chancellor", "UK Chancellor said.", (("c_x", "X", "def.", 0.9),),
                     kinds=("role",), jurisdictions=("GB",), article=("GB",))  # fmt: skip
    text = render_link_questions([q])
    assert "article from: GB" in text and "candidate c_x: X [role, GB]: def." in text
    bare = render_link_questions([LinkQuestion("d1", "p", "s", (("c_y", "Y", "d", 0.9),))])
    assert "article from: unknown" in bare and "[concept, global]" in bare


def test_link_confirm_v3_examples_avoid_held_out_wording():
    from app import llm

    prompt = llm.load_prompt("link_confirm")
    assert prompt.version == "link_confirm-v3"
    for held_out in ("health and care levy", "preferential trade access", "Healey", "Burnham"):
        assert held_out.lower() not in prompt.system.lower()


def test_eval_cases_go_through_the_code_filter():
    from evals.linker import case_question, load

    cases = {c["id"]: c for c in load("link_confirm")}
    assert [cid for cid, *_ in case_question(cases["L01"]).candidates] == [
        "c_chancellor_of_the_exchequer"
    ]
    assert case_question(cases["L16"]).candidates == ()  # German chancellor: both dropped
    assert len(case_question(cases["L16"], filtered=False).candidates) == 2
