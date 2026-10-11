"""landing_art.py's own cap (decision 44 V3, plan round 1 items 1-2)."""

from scripts.landing_art import CAP_USD, MAX_IMAGES, Budget, plan


def test_stops_before_the_image_cap():
    budget = Budget(price=0.01)
    made = 0
    while budget.allows_another():
        budget.charge(0.01)
        made += 1
    assert made == MAX_IMAGES == 8


def test_stops_before_the_dollar_cap_and_never_trusts_a_lower_reported_price():
    budget = Budget(price=0.0672)
    made = 0
    while budget.allows_another():
        budget.charge(0.0)  # LiteLLM reported nothing: the configured price is charged anyway
        made += 1
    assert made == 8 and budget.spent <= CAP_USD
    expensive = Budget(price=0.134)
    count = 0
    while expensive.allows_another():
        expensive.charge(0.134)
        count += 1
    assert count == 4 and expensive.spent <= CAP_USD  # 4 x 0.134 = 0.536; a fifth would pass


def test_plan_is_two_variants_per_scene_one_scene_or_one_reroll():
    assert len(plan(None)) == 6
    assert plan("tabs") == [("tabs", 3)]
    assert plan(None, "shredder") == [("shredder", 1), ("shredder", 2)]
