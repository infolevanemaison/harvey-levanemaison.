"""Is a promotion worth it? Contribution per order with and without it.

Inputs a person can check: price, unit cost (the supplier's price, with its
shipping if the supplier charges it), the shop's own shipping cost per order
and the payment fee. Output: what each order leaves after the discount, and
how many extra orders the promotion must bring to pay for itself.

Nothing here reads or changes the shop.
"""

from dataclasses import asdict, dataclass

# Shopify Payments, EU cards, Basic plan, as a rule of thumb. Check your plan.
DEFAULT_FEE_PCT = 1.5
DEFAULT_FEE_FIXED = 0.25


@dataclass
class Scenario:
    name: str
    units: int
    revenue: float           # what the customer pays (VAT included, as Shopify shows it)
    discount: float
    cost: float              # units x unit cost
    shipping: float
    fees: float
    contribution: float      # revenue - cost - shipping - fees (before VAT and marketing)
    margin_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


def scenario(name: str, unit_price: float, unit_cost: float, units: int = 1,
             discount_pct: float = 0.0, min_subtotal: float = 0.0,
             shipping_cost: float = 0.0, vat_pct: float = 0.0,
             fee_pct: float = DEFAULT_FEE_PCT, fee_fixed: float = DEFAULT_FEE_FIXED) -> Scenario:
    """One order. The discount applies only when the subtotal reaches
    min_subtotal (Shopify's "minimum purchase amount"). vat_pct removes the
    VAT included in the price before computing contribution; 0 keeps the
    gross figure (useful when VAT isn't being charged yet)."""
    subtotal = unit_price * units
    discount = round(subtotal * discount_pct / 100, 2) if subtotal >= min_subtotal and discount_pct else 0.0
    paid = round(subtotal - discount, 2)
    net_of_vat = paid / (1 + vat_pct / 100) if vat_pct else paid
    fees = round(paid * fee_pct / 100 + fee_fixed, 2)
    cost = round(unit_cost * units, 2)
    contribution = round(net_of_vat - cost - shipping_cost - fees, 2)
    return Scenario(name, units, paid, discount, cost, shipping_cost, fees, contribution,
                    round(contribution / net_of_vat * 100, 1) if net_of_vat else 0.0)


def extra_orders_to_break_even(without: Scenario, with_promo: Scenario) -> float | None:
    """How much the promotion must lift orders (as a ratio) to leave the same
    total contribution. 1.25 means it needs 25 % more orders. None when an
    order with the promotion loses money."""
    if with_promo.contribution <= 0:
        return None
    return round(without.contribution / with_promo.contribution, 2)


def compare(unit_price: float, unit_cost: float, discount_pct: float, min_subtotal: float,
            **kw) -> dict:
    """The usual question: one unit at full price versus the promotion as
    customers actually trigger it (one unit if that already reaches the
    minimum, else the fewest units that do)."""
    base = scenario("1 unidad sin promoción", unit_price, unit_cost, 1, **kw)
    units = 1
    while unit_price * units < min_subtotal and units < 10:
        units += 1
    promo = scenario(f"{units} unidad(es) con -{discount_pct:g} %", unit_price, unit_cost, units,
                     discount_pct, min_subtotal, **kw)
    per_unit = round(promo.contribution / units, 2)
    return {
        "base": base.to_dict(), "promo": promo.to_dict(),
        "contribution_per_unit_promo": per_unit,
        "single_item_already_qualifies": unit_price >= min_subtotal,
        "lift_needed": extra_orders_to_break_even(base, promo),
    }
