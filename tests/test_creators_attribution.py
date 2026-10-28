"""Attribution keeps traffic, attributed orders and verified sales apart."""

from datetime import UTC, datetime

from harvey.creators.attribution import (
    INVALID,
    PENDING,
    UNPAID,
    VERIFIED,
    Affiliate,
    attribute,
    orders_from,
    report,
    summarise,
)
from harvey.creators.commerce import break_even_table

NOW = datetime(2026, 12, 31, tzinfo=UTC)
ANA = Affiliate(handle="ana.example", code="ANA10", rate_pct=10, base="sin_iva", approved=False)
EVA = Affiliate(handle="eva_example", code="EVA10", rate_pct=10, base="con_iva", approved=True)


def order(name="#1", day="2026-10-01", codes=(), content="", status="PAID", subtotal="121",
          tax="21", cancelled=None, source="web", days=1):
    return {"name": name, "createdAt": f"{day}T10:00:00Z", "sourceName": source,
            "cancelledAt": cancelled, "displayFinancialStatus": status, "discountCodes": list(codes),
            "currentSubtotalPriceSet": {"shopMoney": {"amount": subtotal}},
            "currentTotalTaxSet": {"shopMoney": {"amount": tax}},
            "totalRefundedSet": {"shopMoney": {"amount": "0"}},
            "shippingAddress": {"countryCodeV2": "ES"},
            "customerJourneySummary": {"daysToConversion": days, "lastVisit": {"utmParameters": {
                "source": "instagram", "medium": "influencer" if content else "",
                "campaign": "lvm_es_202610", "content": content}}}}


def test_a_code_beats_a_link_and_the_base_is_without_vat():
    hit = attribute(order(codes=["ana10"], content="eva_example"), [ANA, EVA], NOW)
    assert hit.handle == "ana.example" and hit.via == "código"
    assert hit.state == VERIFIED and hit.base_amount == 100.0 and hit.commission == 10.0


def test_a_link_alone_attributes_and_con_iva_uses_what_she_paid():
    hit = attribute(order(content="eva_example"), [ANA, EVA], NOW)
    assert hit.handle == "eva_example" and hit.via == "enlace"
    assert hit.base_amount == 121.0 and hit.commission == 12.1


def test_no_commission_until_the_return_window_has_passed():
    hit = attribute(order(codes=["ANA10"], day="2026-12-20"), [ANA], NOW)
    assert hit.state == PENDING and hit.commission == 0.0 and "2027-02-05" in hit.reason


def test_cancelled_refunded_unpaid_and_manual_orders_never_pay():
    states = [attribute(o, [ANA], NOW).state for o in (
        order(codes=["ANA10"], cancelled="2026-10-02T00:00:00Z"),
        order(codes=["ANA10"], status="REFUNDED", subtotal="0", tax="0"),
        order(codes=["ANA10"], status="PENDING"),
        order(codes=["ANA10"], source="shopify_draft_order"))]
    assert states == [INVALID, INVALID, UNPAID, INVALID]


def test_orders_outside_her_period_or_with_other_codes_are_not_hers():
    dated = Affiliate(handle="ana.example", code="ANA10", rate_pct=10, start="2026-11-01")
    assert attribute(order(codes=["ANA10"]), [dated], NOW) is None
    assert attribute(order(codes=["BIENVENIDA10"]), [ANA], NOW) is None
    assert attribute(order(content="ana.example", days=45), [ANA], NOW) is None


def test_summary_separates_traffic_attributed_and_verified():
    orders = [order("#1", codes=["ANA10"]), order("#2", content="ana.example", day="2026-12-28"),
              order("#3", codes=["ANA10"], cancelled="2026-10-02T00:00:00Z")]
    [t] = summarise(orders, [ANA], NOW, sessions={"ana_example": 40})
    assert (t.sessions, t.attributed, t.verified, t.pending, t.invalid) == (40, 3, 1, 1, 1)
    assert t.verified_sales == 100.0 and t.commission == 10.0 and t.pending_sales == 100.0
    text = report([t], [ANA])
    assert "simulación: condiciones sin aprobar" in text and "tráfico atribuido" in text


def test_orders_from_accepts_the_raw_response_and_pages():
    raw = {"data": {"orders": {"nodes": [order("#1")], "pageInfo": {}}}}
    assert [o["name"] for o in orders_from(raw)] == ["#1"]
    assert [o["name"] for o in orders_from([raw, raw])] == ["#1", "#1"]


ROW = {"producto": "Vestido ficticio", "pvp": "60,50", "coste_proveedor": "15",
       "fuente_coste": "Factura proveedor 2026-10", "envio_es": "5",
       "fuente_envio_es": "Pedido proveedor 2026-10", "iva_es_pct": "21", "fuente_iva": "Gestoría"}


def test_break_even_sin_iva_and_con_iva():
    [b] = break_even_table([ROW], "es", "sin_iva", 2.1, 0.30, rates=[10])
    # net 50.00, fee 1.57, margin 50-15-5-1.57 = 28.43 → 56.9 % of 50
    assert b.margin == 28.43 and b.max_rate_pct == 56.9 and b.profit == {10: 23.43}
    [c] = break_even_table([ROW], "es", "con_iva", 2.1, 0.30, rates=[10])
    assert c.max_rate_pct == 47.0 and c.profit == {10: 22.38}


def test_break_even_refuses_unchecked_costs():
    pending = dict(ROW, fuente_envio_es="PENDIENTE: pedido al proveedor")
    [b] = break_even_table([pending], "es", "sin_iva", 2.1, 0.30)
    assert b.margin is None and b.missing == ["envio_es"]
    [fr] = break_even_table([ROW], "fr", "sin_iva", 2.1, 0.30)
    assert fr.missing == ["envio_fr", "iva_fr_pct"]
    [nofee] = break_even_table([ROW], "es", "sin_iva")
    assert "comision_pago" in nofee.missing
