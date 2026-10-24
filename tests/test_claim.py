from tally.engine.claim import claim_day, load_rates, lost_value, month_lines, rate_for
from tally.models import MealType

B, L, S, SN = MealType.BREAKFAST, MealType.LUNCH, MealType.SUPPER, MealType.SNACK


def test_rates_match_the_published_2026_2027_table():
    """These are the numbers the impact claim rests on, so they are asserted, not assumed."""
    r = load_rates()
    t1 = r["day_care_home"]["tier_1"]
    assert (t1["breakfast"], t1["lunch"], t1["snack"]) == (1.74, 3.31, 0.98)
    t2 = r["day_care_home"]["tier_2"]
    assert (t2["breakfast"], t2["lunch"], t2["snack"]) == (0.62, 1.99, 0.27)
    assert r["effective_from"] == "2026-07-01"


def test_a_normal_day_pays_breakfast_lunch_and_one_snack():
    d = claim_day([B, L, SN], "tier_1")
    assert d.amount == round(1.74 + 3.31 + 0.98, 2) == 6.03
    assert not d.dropped


def test_daily_maximum_drops_the_least_valuable_extra():
    """Three meals and two snacks were served. The programme pays for two meals and one snack."""
    d = claim_day([B, L, S, SN, SN], "tier_1")
    assert sorted(m.value for m in d.claimed) == ["lunch", "snack", "supper"]
    assert d.amount == round(3.31 + 3.31 + 0.98, 2)
    assert sorted(m.value for m in d.dropped) == ["breakfast", "snack"]


def test_one_meal_and_two_snacks_wins_when_that_is_worth_more():
    d = claim_day([B, SN, SN], "tier_1")
    assert d.amount == round(1.74 + 0.98 + 0.98, 2)
    assert not d.dropped


def test_tier_two_pays_less_for_the_same_day():
    assert claim_day([B, L, SN], "tier_2").amount < claim_day([B, L, SN], "tier_1").amount


def test_month_totals_match_a_hand_calculation():
    days = [claim_day([B, L, SN], "tier_1") for _ in range(20)]
    lines, total = month_lines(days, "tier_1")
    assert {ln.meal_type.value: ln.count for ln in lines} == {"breakfast": 20, "lunch": 20, "snack": 20}
    assert total == round(20 * (1.74 + 3.31 + 0.98), 2) == 120.60


def test_the_monthly_loss_figure_quoted_on_the_landing_page():
    """One lunch a day that fails the log, six children, 22 serving days, is 436.92 dollars."""
    assert lost_value([(L, 6 * 22)], "tier_1") == 436.92


def test_the_wrong_yogurt_answer_costs_rosa_194_04_a_month():
    """The figure on the proof card and the project page: a snack a day, nine children, 22 days, tier 1."""
    from tally.models import MealType

    assert lost_value([(MealType.SNACK, 9 * 22)], "tier_1") == 194.04


def test_a_lost_snack_a_day_costs_129_36():
    assert lost_value([(SN, 6 * 22)], "tier_1") == 129.36


def test_rate_lookup():
    assert rate_for(L, "tier_1") == 3.31
    assert rate_for(SN, "tier_2") == 0.27


def test_empty_day_is_worth_nothing():
    d = claim_day([], "tier_1")
    assert d.amount == 0.0 and not d.claimed
