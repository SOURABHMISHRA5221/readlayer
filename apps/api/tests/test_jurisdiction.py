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
