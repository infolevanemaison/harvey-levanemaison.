import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from harvey.watch.alerts import decisions, load_state, should_notify, update_state
from harvey.watch.checks import (
    Settings,
    check_ads,
    check_orders,
    check_theme,
    run_checks,
)
from harvey.watch.cli import process
from harvey.watch.fetch import Budget, MetaReader, ShopifyReader, snapshot_from_env
from harvey.watch.guard import UnsafeQuery, check_query
from harvey.watch.queries import SHOPIFY_QUERIES

NOW = datetime(2030, 3, 31, 12, tzinfo=UTC)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _order(name, days_ago, fulfillments=(), fin="PAID", ful="UNFULFILLED", **kw):
    return {"name": name, "createdAt": _iso(days_ago), "cancelledAt": None, "test": False,
            "displayFinancialStatus": fin, "displayFulfillmentStatus": ful,
            "fulfillments": list(fulfillments), "transactions": [], "sourceName": "web", **kw}


def _ful(days_ago, status="FULFILLED", number="TRK-EXAMPLE-1", **kw):
    return {"createdAt": _iso(days_ago), "displayStatus": status,
            "trackingInfo": [{"company": "Other", "number": number}] if number else [], **kw}


# --- guard ---------------------------------------------------------------

def test_shipped_queries_pass_the_guard():
    for q in SHOPIFY_QUERIES.values():
        check_query(q)


@pytest.mark.parametrize("query", [
    "mutation { productUpdate(product: {id: \"x\", status: DRAFT}) { userErrors { message } } }",
    "subscription { orders { name } }",
    "{ __schema { types { name } } }",
    "{ orders(first: 1) { nodes { email } } }",
    "{ orders(first: 1) { nodes { customer { id } } } }",
    "{ orders(first: 1) { nodes { shippingAddress { address1 city zip } } } }",
    "{ orders(first: 1) { nodes { shippingAddress { company } } } }",
    "",
])
def test_guard_refuses_writes_and_personal_data(query):
    with pytest.raises(UnsafeQuery):
        check_query(query)


def test_guard_allows_country_and_carrier_and_words_inside_strings():
    check_query('{ orders(first: 1, query: "email:x") { nodes { shippingAddress { countryCodeV2 } '
                'fulfillments(first: 1) { trackingInfo(first: 1) { company number } } } } }')


# --- orders --------------------------------------------------------------

def test_paid_and_not_sent_after_three_days():
    alerts = check_orders([_order("#9001", 5), _order("#9002", 1)], NOW, Settings())
    assert [(a.code, a.key) for a in alerts] == [("pedido_sin_enviar", "#9001")]


def test_late_delivery_escalates_to_urgent():
    late = check_orders([_order("#9003", 20, [_ful(17)], ful="FULFILLED")], NOW, Settings())
    very_late = check_orders([_order("#9004", 40, [_ful(30)], ful="FULFILLED")], NOW, Settings())
    assert [(a.code, a.severity) for a in late] == [("entrega_retrasada", "alta")]
    assert [(a.code, a.severity) for a in very_late] == [("entrega_retrasada", "urgente")]
    assert very_late[0].needs_owner


def test_failed_delivery_is_urgent_and_delivered_is_quiet():
    alerts = check_orders([_order("#9005", 9, [_ful(8, "ATTEMPTED_DELIVERY")], ful="FULFILLED"),
                           _order("#9006", 30, [_ful(25, "DELIVERED")], ful="FULFILLED")],
                          NOW, Settings())
    assert [(a.code, a.key, a.severity) for a in alerts] == [("entrega_fallida", "#9005", "urgente")]


def test_missing_tracking_number():
    alerts = check_orders([_order("#9007", 4, [_ful(2, number="")], ful="FULFILLED")], NOW, Settings())
    assert [a.code for a in alerts] == ["sin_seguimiento"]


def test_cancelled_manual_orders_still_paid_are_one_low_alert():
    manual = {"sourceName": "shopify_draft_order", "cancelledAt": _iso(1),
                  "totalPriceSet": {"shopMoney": {"amount": "10.5"}},
                  "totalRefundedSet": {"shopMoney": {"amount": "0.0"}},
                  "transactions": [{"kind": "SALE", "status": "SUCCESS", "gateway": "manual"}]}
    orders = [{**_order("#9101", 9), **manual}, {**_order("#9102", 9), **manual}]
    alerts = check_orders(orders, NOW, Settings())
    assert len(alerts) == 1 and alerts[0].code == "pedidos_manuales_cancelados"
    assert "21.00 EUR" in alerts[0].message and alerts[0].severity == "baja"


def test_test_orders_are_ignored():
    assert check_orders([_order("#9008", 9, test=True)], NOW, Settings()) == []


# --- theme and ads -------------------------------------------------------

def test_test_theme_published():
    assert check_theme({"id": "t1", "name": "Pruebas tema (NO PUBLICAR)"}, Settings())[0].needs_owner
    assert check_theme({"id": "t2", "name": "Tema principal"}, Settings()) == []


def test_ads_active_campaign_and_spend_over_cap():
    campaigns = [{"id": "1", "name": "Ejemplo A", "effective_status": "ACTIVE"},
                 {"id": "2", "name": "Ejemplo B", "effective_status": "PAUSED"}]
    insights = [{"campaign_id": "1", "campaign_name": "Ejemplo A", "spend": "12.40", "actions": []}]
    codes = sorted(a.code for a in check_ads(campaigns, insights, Settings()))
    assert codes == ["campana_activa", "gasto_sin_ventas", "gasto_sobre_limite"]


def test_ads_quiet_when_all_paused_and_no_spend():
    assert check_ads([{"id": "2", "effective_status": "PAUSED"}], [], Settings()) == []


def test_missing_sources_are_reported_not_cleared():
    alerts, unchecked = run_checks({"orders": []}, NOW)
    assert alerts == [] and set(unchecked) == {"tema publicado", "catálogo", "variantes", "Meta Ads"}


# --- state ---------------------------------------------------------------

def test_new_then_open_then_resolved():
    state = {"open": {}, "resolved": []}
    late = check_orders([_order("#9010", 5)], NOW, Settings())
    first = update_state(state, late, NOW)
    assert len(first["new"]) == 1 and len(should_notify(first)) == 1
    second = update_state(state, late, NOW + timedelta(hours=1))
    assert second["new"] == [] and should_notify(second) == []
    third = update_state(state, [], NOW + timedelta(hours=2))
    assert len(third["resolved"]) == 1 and state["open"] == {}


def test_unchecked_area_does_not_resolve_its_alerts():
    state = {"open": {}, "resolved": []}
    update_state(state, check_orders([_order("#9011", 5)], NOW, Settings()), NOW)
    change = update_state(state, [], NOW, unchecked=["pedidos y entregas"])
    assert change["resolved"] == [] and len(state["open"]) == 1


def test_escalation_notifies_again():
    state = {"open": {}, "resolved": []}
    update_state(state, check_orders([_order("#9012", 20, [_ful(17)], ful="FULFILLED")], NOW, Settings()), NOW)
    later = NOW + timedelta(days=6)
    change = update_state(state, check_orders([_order("#9012", 26, [_ful(23)], ful="FULFILLED")],
                                              later, Settings()), later)
    assert [a.severity for a in should_notify(change)] == ["urgente"]


def test_decisions_rank_by_severity():
    state = {"open": {}, "resolved": []}
    alerts = check_orders([_order("#9013", 40, [_ful(30)], ful="FULFILLED")], NOW, Settings())
    alerts += check_theme({"id": "t", "name": "NO PUBLICAR"}, Settings())
    update_state(state, alerts, NOW)
    text = decisions(state)
    assert text.index("urgente") < text.index("alta")


# --- end to end ----------------------------------------------------------

def test_process_writes_reports_and_notifies_only_once(tmp_path):
    snap = {"orders": [_order("#9014", 6)], "theme": {"id": "t", "name": "Tema"},
            "products": [], "campaigns": [], "insights": []}
    out = tmp_path / "vigilancia"
    r1 = process(snap, str(out), NOW)
    assert r1["notify"] == 1 and (out / "notificar.md").exists()
    assert "#9014" in (out / "ultimo.md").read_text(encoding="utf-8")
    r2 = process(snap, str(out), NOW + timedelta(hours=1))
    assert r2["notify"] == 0 and not (out / "notificar.md").exists()
    assert json.loads((out / "estado.json").read_text(encoding="utf-8"))["open"]
    assert load_state(str(out / "estado.json"))["last_run"]


# --- fetchers ------------------------------------------------------------

def test_shopify_reader_refuses_mutation_before_any_request():
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    reader = ShopifyReader("ejemplo.myshopify.com", "tok-secreto", Budget(5), client)
    with pytest.raises(UnsafeQuery):
        reader.query("mutation { x }")
    assert calls == []


def test_budget_caps_requests_and_errors_hide_the_token():
    def handler(request):
        return httpx.Response(500, json={})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    reader = MetaReader("act_123", "tok-secreto", Budget(1), client)
    with pytest.raises(RuntimeError) as e:
        reader.campaigns()
    assert "tok-secreto" not in str(e.value)
    with pytest.raises(RuntimeError, match="límite"):
        reader.campaigns()


def test_meta_reader_only_gets():
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"data": [{"id": "1", "effective_status": "PAUSED"}]})
    reader = MetaReader("123", "tok", Budget(5), httpx.Client(transport=httpx.MockTransport(handler)))
    assert reader.campaigns()[0]["id"] == "1" and reader.insights_today() and methods == ["GET", "GET"]


def test_no_tokens_no_requests():
    snap, errors = snapshot_from_env(env={})
    assert snap == {} and errors == []


def test_spend_from_campaigns_paused_since_is_only_noted():
    insights = [{"campaign_id": "2", "campaign_name": "Ejemplo B", "spend": "2.50", "actions": []}]
    alerts = check_ads([{"id": "2", "effective_status": "PAUSED"}], insights, Settings())
    assert [(a.code, a.severity, a.needs_owner) for a in alerts] == [("gasto_antes_de_pausa", "media", False)]


# --- token, privacy, daily report ---------------------------------------

def _token_client(scope, seen=None):
    def handler(request):
        if seen is not None:
            seen.append((request.method, request.url.path, request.content.decode()))
        return httpx.Response(200, json={"access_token": "tok-corto", "scope": scope, "expires_in": 86399})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_token_with_read_scopes_only():
    from harvey.watch.fetch import shopify_token
    seen = []
    token = shopify_token("ejemplo.myshopify.com", "id-1", "secreto-1", Budget(2),
                          _token_client("read_orders,read_products,read_themes", seen))
    assert token == "tok-corto"
    method, path, body = seen[0]
    assert (method, path) == ("POST", "/admin/oauth/access_token") and "grant_type=client_credentials" in body


@pytest.mark.parametrize("scope", ["read_orders,write_products", "write_orders", ""])
def test_token_with_any_write_scope_stops(scope):
    from harvey.watch.fetch import shopify_token
    with pytest.raises(RuntimeError, match="PARADA"):
        shopify_token("ejemplo.myshopify.com", "id-1", "secreto-1", Budget(2), _token_client(scope))


def test_token_errors_hide_the_secret():
    from harvey.watch.fetch import shopify_token
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    with pytest.raises(RuntimeError) as e:
        shopify_token("ejemplo.myshopify.com", "id-1", "secreto-1", Budget(2), client)
    assert "secreto-1" not in str(e.value)


def test_scrub_hides_emails_phones_and_keys_but_not_dates_or_orders():
    from harvey.watch.alerts import scrub
    text = scrub("ana@example.com +34 600 000 000 shpat_abcdefgh1234 #1001 2030-03-31T12:00 12.50 EUR")
    assert "@" not in text and "600 000 000" not in text and "shpat_" not in text
    assert "#1001" in text and "2030-03-31T12:00" in text and "12.50 EUR" in text


def test_reports_never_carry_an_email_from_an_error(tmp_path):
    out = tmp_path / "v"
    process({"orders": []}, str(out), NOW, errors=["fallo con cliente ana@example.com"])
    for name in ("ultimo.md", "notificar.md", "estado.json", "decisiones.md"):
        assert "ana@example.com" not in (out / name).read_text(encoding="utf-8")


def test_daily_report_flags_a_stalled_watch():
    from harvey.watch.alerts import daily_report
    state = {"open": {}, "resolved": [], "last_run": (NOW - timedelta(hours=5)).isoformat()}
    assert "urgente" in daily_report(state, NOW)
    state["last_run"] = (NOW - timedelta(minutes=30)).isoformat()
    assert "Vigilancia funcionando" in daily_report(state, NOW)
    assert "no se ha ejecutado nunca" in daily_report({"open": {}, "resolved": []}, NOW)


def test_daily_report_groups_open_items_and_lists_recent_resolutions():
    from harvey.watch.alerts import daily_report
    state = {"open": {}, "resolved": []}
    update_state(state, check_orders([_order("#9020", 5)], NOW, Settings()), NOW)
    update_state(state, [], NOW + timedelta(hours=1))
    update_state(state, check_theme({"id": "t", "name": "NO PUBLICAR"}, Settings()), NOW + timedelta(hours=2))
    text = daily_report(state, NOW + timedelta(hours=2))
    assert "**tema publicado**" in text and "#9020" in text.split("Resueltas en las últimas 24 h")[1]


def test_one_failing_shopify_source_does_not_hide_the_others(monkeypatch):
    from harvey.watch import fetch

    def handler(request):
        if request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "tok", "scope": "read_orders,read_products,read_themes"})
        query = json.loads(request.content)["query"]
        if "orders(" in query:
            return httpx.Response(200, json={"data": {"orders": {"nodes": [], "pageInfo": {}}}})
        if "productVariants(" in query:
            return httpx.Response(200, json={"data": {"productVariants": {"nodes": [], "pageInfo": {}}}})
        if "products(" in query:
            denied = {"message": "Access denied for someField field.", "extensions": {"code": "ACCESS_DENIED"}}
            return httpx.Response(200, json={"errors": [denied] * 50})
        return httpx.Response(200, json={"data": {"themes": {"nodes": [{"id": "t", "name": "Tema"}]}}})

    transport, real_client = httpx.MockTransport(handler), httpx.Client
    monkeypatch.setattr(fetch.httpx, "Client", lambda **kw: real_client(transport=transport))
    env = {"SHOPIFY_SHOP": "ejemplo.myshopify.com", "SHOPIFY_CLIENT_ID": "id", "SHOPIFY_CLIENT_SECRET": "sec"}
    snap, errors = fetch.snapshot_from_env(env=env)
    assert set(snap) == {"orders", "theme", "variants"} and snap["theme"]["name"] == "Tema"
    assert len(errors) == 1 and errors[0].startswith("products:")
    assert errors[0].count("Access denied") == 1 and "sec" not in errors[0]


def test_watch_products_query_needs_no_shipping_scope():
    from harvey.watch.queries import PRODUCTS_QUERY
    assert "deliveryProfile" not in PRODUCTS_QUERY
    assert PRODUCTS_QUERY.count("{") == PRODUCTS_QUERY.count("}")
    check_query(PRODUCTS_QUERY)



# --- variants that keep selling without stock ----------------------------

def _variant(policy, qty, title="Ejemplo", status="ACTIVE"):
    return {"inventoryPolicy": policy, "inventoryQuantity": qty,
            "product": {"handle": title.lower(), "title": title, "status": status}}


def test_variants_selling_at_zero_and_continue_policy():
    from harvey.watch.checks import check_variants
    variants = [_variant("CONTINUE", 0, "Vestido A"), _variant("CONTINUE", -2, "Vestido A"),
                _variant("CONTINUE", 5, "Blusa B"), _variant("DENY", 0, "Falda C"),
                _variant("CONTINUE", 0, "Borrador D", status="DRAFT")]
    alerts = {a.code: a for a in check_variants(variants)}
    assert set(alerts) == {"venta_con_cero_existencias", "politica_seguir_vendiendo"}
    zero = alerts["venta_con_cero_existencias"]
    assert zero.severity == "alta" and zero.needs_owner and "2 variantes de 1 productos" in zero.message
    assert "Vestido A (2)" in zero.message and "Borrador" not in zero.message
    assert "3 de 4 variantes activas (2 productos)" in alerts["politica_seguir_vendiendo"].message


def test_variants_all_deny_is_quiet():
    from harvey.watch.checks import check_variants
    assert check_variants([_variant("DENY", 0), _variant("DENY", 3)]) == []
    assert check_variants([]) == []


def test_variants_filter_is_lower_case():
    from harvey.watch.queries import VARIANTS_FILTER, VARIANTS_QUERY
    assert VARIANTS_FILTER == "product_status:active"
    check_query(VARIANTS_QUERY)


def test_throttled_query_waits_and_retries_within_budget():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"errors": [{"message": "Throttled",
                                                         "extensions": {"code": "THROTTLED"}}]})
        return httpx.Response(200, json={"data": {"themes": {"nodes": []}}})
    budget = Budget(5)
    reader = ShopifyReader("ejemplo.myshopify.com", "tok", budget, httpx.Client(transport=httpx.MockTransport(handler)))
    waits = []
    reader.sleep = waits.append
    assert reader.query(SHOPIFY_QUERIES["theme"]) == {"themes": {"nodes": []}}
    assert len(calls) == 2 and waits == [2] and budget.used == 2


def test_catalog_summarises_conversion_obstacles_without_notifying():
    from harvey.watch.checks import check_catalog
    one_photo = {"title": "Vestido Ejemplo", "handle": "vestido-ejemplo", "tracksInventory": True,
                 "totalInventory": 10, "mediaCount": {"count": 1}, "featuredMedia": {"alt": "x"},
                 "collections": {"nodes": [{"handle": "vestidos"}]}, "descriptionHtml": "<p>Corto</p>",
                 "options": [], "tags": [], "productType": "Vestido"}
    alerts = [a for a in check_catalog([one_photo]) if a.code == "mejoras_conversion"]
    assert len(alerts) == 1 and alerts[0].severity == "baja" and not alerts[0].needs_owner
    assert "1 de 1 productos activos" in alerts[0].message and "Una sola foto (1)" in alerts[0].message
    state = {"open": {}, "resolved": []}
    assert should_notify(update_state(state, alerts, NOW)) == []


def _product(title, photos=6, collection=True):
    return {"title": title, "handle": title.lower().replace(" ", "-"), "tracksInventory": True,
            "totalInventory": 20, "mediaCount": {"count": photos}, "featuredMedia": {"alt": title},
            "collections": {"nodes": [{"handle": "vestidos"}] if collection else []},
            "descriptionHtml": "<p>" + "Vestido largo de punto, tejido: algodón y elastano. Guía de tallas en cm. " * 6 + "</p>",
            "options": [{"name": "Talla", "values": ["S", "M"]}], "tags": [], "productType": "Vestido",
            "seo": {"description": "Vestido de punto."}}


def test_ready_to_promote_skips_serious_issues_and_zero_stock():
    from harvey.watch.checks import ready_to_promote
    products = [_product("Vestido Bueno"), _product("Vestido Sin Fotos", photos=1),
                _product("Vestido Sin Stock")]
    variants = [_variant("DENY", 3, "Vestido Bueno"), _variant("CONTINUE", 0, "Vestido Sin Stock")]
    for v in variants:
        v["product"]["handle"] = v["product"]["title"].lower().replace(" ", "-")
    alerts = ready_to_promote(products, variants)
    assert len(alerts) == 1 and alerts[0].code == "productos_mas_preparados"
    msg = alerts[0].message
    assert "Vestido Bueno" in msg and "Sin Fotos" not in msg and "Sin Stock" not in msg
    assert alerts[0].severity == "baja" and not alerts[0].needs_owner


def test_ready_to_promote_empty_when_nothing_qualifies():
    from harvey.watch.checks import ready_to_promote
    assert ready_to_promote([_product("Vestido X", photos=1)], []) == []
