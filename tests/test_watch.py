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
    assert alerts == [] and set(unchecked) == {"tema publicado", "catálogo", "Meta Ads"}


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
