"""Commercial ranking and break-even, with fictitious creators only."""

from harvey.creators.commerce import deal, pipeline
from harvey.creators.scoring import Creator
from harvey.creators.store import CreatorStore


def test_deal_says_how_many_orders_pay_for_a_fee():
    d = deal(fee=120, avg_order_value=55, margin_pct=40)
    assert d.unit_contribution == 22.0
    assert d.break_even_orders == 5.5
    assert d.max_cost_for_orders[5] == 110.0


def test_a_commission_above_the_margin_never_pays():
    d = deal(fee=0, avg_order_value=55, margin_pct=20, commission_pct=25)
    assert d.unit_contribution is None and d.break_even_orders is None


def test_pipeline_puts_verified_channels_first_and_says_the_next_step(tmp_path):
    st = CreatorStore(tmp_path / "c.db")
    good, _ = st.upsert(Creator(handle="con_canal_ficticia", country="ES", followers=12_000,
                                pro_contact_source="https://plataforma.example/x",
                                channel_kind="plataforma"))
    st.upsert(Creator(handle="sin_canal_ficticia", country="ES", followers=12_000))
    st.add_proposal(good, "es", "Hola", "Cuerpo", [])
    rows = pipeline(st.list_creators(), st.list_proposals())
    assert rows[0]["handle"] == "con_canal_ficticia"
    assert rows[0]["next"].startswith("decidir la propuesta")
    assert "verificar un canal" in rows[1]["next"]


def test_a_discarded_creator_has_no_next_step(tmp_path):
    st = CreatorStore(tmp_path / "c.db")
    st.upsert(Creator(handle="extranjera_ficticia", country="US", followers=9_000))
    rows = pipeline(st.list_creators(), st.list_proposals())
    assert rows[0]["next"].startswith("ninguna")


def test_commission_profit_only_with_every_real_cost():
    from harvey.creators.commerce import commission_table
    full = {"producto": "Vestido ficticio", "pvp": "60,50", "coste_proveedor": "15",
            "envio_proveedor": "5", "iva_pct": "21"}
    lines = commission_table([full], rates=[10], pay_rate_pct=2.1, pay_fixed=0.30)
    # net 50.00; commission 5.00; fee 60.50*2.1% + 0.30 = 1.57; profit 50-15-5-1.57-5 = 23.43
    assert lines[0].commission == 5.0 and lines[0].profit == 23.43 and not lines[0].missing
    partial = dict(full, envio_proveedor="")
    line = commission_table([partial], rates=[10], pay_rate_pct=2.1, pay_fixed=0.30)[0]
    assert line.profit is None and line.missing == ["envio_proveedor"]
    assert line.commission == 5.0
    nofee = commission_table([full], rates=[10])[0]
    assert nofee.profit is None and "comision_pago" in nofee.missing
