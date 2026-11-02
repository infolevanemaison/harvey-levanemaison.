"""Promotion profitability. Illustrative prices and costs only."""

from harvey.promotions import compare, extra_orders_to_break_even, scenario


def test_discount_only_applies_above_the_minimum():
    assert scenario("x", 30, 10, 1, 20, 60).discount == 0
    assert scenario("x", 30, 10, 2, 20, 60).discount == 12.0


def test_contribution_counts_cost_shipping_fees_and_vat():
    s = scenario("x", 50, 20, 1, shipping_cost=4, vat_pct=21, fee_pct=1.5, fee_fixed=0.25)
    assert s.fees == 1.0
    assert s.contribution == round(50 / 1.21 - 20 - 4 - 1.0, 2)


def test_a_single_expensive_item_loses_margin_to_the_threshold():
    r = compare(80, 40, 20, 60)
    assert r["single_item_already_qualifies"]
    assert r["promo"]["contribution"] < r["base"]["contribution"]
    assert r["lift_needed"] > 1


def test_a_two_unit_promotion_can_beat_one_full_price_unit():
    r = compare(35, 10, 20, 60)
    assert r["promo"]["units"] == 2
    assert r["lift_needed"] < 1


def test_a_losing_promotion_has_no_break_even():
    base = scenario("a", 20, 15, 1)
    promo = scenario("b", 20, 15, 3, 40, 60)
    assert extra_orders_to_break_even(base, promo) is None
