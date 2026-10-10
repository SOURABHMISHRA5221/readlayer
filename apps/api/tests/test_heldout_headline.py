"""Held-out headline math (decision 34): per-domain rows, stop rule, grown links apart."""

from collections import Counter

from scripts.heldout_headline import rate, stop_check, summarise, table


def doc(domain, group, alias=0, confirmed=0, unlinked=0):
    return {"domain": domain, "group": group,
            "counts": Counter(alias=alias, confirmed=confirmed, unlinked=unlinked)}  # fmt: skip


def test_rows_group_business_and_non_business_and_the_untuned_new_15():
    rows = summarise([doc("finance", "old", 8, 0, 2), doc("health", "new", 3, 1, 4),
                      doc("sports", "new", 1, 0, 1)])  # fmt: skip
    assert rate(rows["business (total)"]) == "80%"
    assert rate(rows["non-business (total)"]) == "50%"
    assert rows["new 15 (untuned)"] == rows["non-business (total)"]
    assert rate(rows["  health"]) == "50%" and rate(rows["all 30"]) == "65%"


def test_stop_rule_fires_on_business_total_or_any_small_domain():
    good = summarise([doc("finance", "old", 8, 0, 2), doc("health", "new", 6, 0, 4)])
    assert stop_check(good) == []
    weak_domain = summarise([doc("finance", "old", 8, 0, 2), doc("health", "new", 9, 0, 1),
                             doc("sports", "new", 1, 0, 4)])  # fmt: skip
    assert stop_check(weak_domain) == ["sports under 50% (n=5)"]
    weak_business = summarise([doc("finance", "old", 7, 0, 3), doc("health", "new", 6, 0, 4)])
    assert stop_check(weak_business) == ["business under 75%"]


def test_grown_links_show_only_in_the_after_growth_table():
    after = {"x": Counter(alias=2, confirmed=1, grown=3, unlinked=4)}
    assert "grown here" in table(after, grown=True)[0]
    assert "grown here" not in table({"x": Counter(alias=2, unlinked=2)})[0]
    assert rate(after["x"]) == "60%"
