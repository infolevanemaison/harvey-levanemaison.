"""Turn read-only snapshots into alerts.

A snapshot is a dict with any of these keys, each in the shape the read
queries in ``queries`` return:

  orders      list of order nodes (ORDERS_QUERY)
  products    list of product nodes (shopaudit.PRODUCTS_QUERY)
  theme       the MAIN theme node (THEME_QUERY)
  campaigns   Meta campaigns (META_CAMPAIGN_FIELDS)
  insights    Meta insights for today, one row per campaign

A key that is missing is not checked and says so, rather than reporting
"all clear" about something nobody looked at.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from harvey.shopaudit import audit_catalog, summary

URGENT, HIGH, MEDIUM, LOW = "urgente", "alta", "media", "baja"
SEVERITIES = (URGENT, HIGH, MEDIUM, LOW)

FAILED_DELIVERY = ("ATTEMPTED_DELIVERY", "FAILURE", "NOT_DELIVERED")
FAILURE_STATUSES = FAILED_DELIVERY + ("DELAYED",)
DELIVERED = ("DELIVERED", "PICKED_UP")
CLOSED_FULFILLMENT = ("CANCELED", "LABEL_VOIDED")


@dataclass
class Settings:
    ship_within_days: int = 3          # paid and not sent after this: alert
    deliver_within_days: int = 15      # the store promises "between 7 and 15 days"
    ad_daily_cap_eur: float = 0.0      # owner's extra budget is 0 EUR
    ad_spend_without_sale_eur: float = 10.0
    test_theme_words: tuple = ("NO PUBLICAR", "PRUEBA")


@dataclass
class Alert:
    severity: str
    code: str
    key: str            # what it is about: an order name, a campaign id, "catalog"
    message: str
    action: str
    needs_owner: bool = False

    @property
    def fingerprint(self) -> str:
        return f"{self.code}:{self.key}"


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _days(since: datetime | None, now: datetime) -> float:
    return (now - since).total_seconds() / 86400 if since else 0.0


def _money(node, key) -> float:
    try:
        return float(((node or {}).get(key) or {}).get("shopMoney", {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_manual(order: dict) -> bool:
    gateways = {(t.get("gateway") or "") for t in order.get("transactions") or []
                if t.get("status") == "SUCCESS"}
    return order.get("sourceName") == "shopify_draft_order" or (gateways and gateways <= {"manual"})


def check_orders(orders: list[dict], now: datetime, s: Settings) -> list[Alert]:
    out = []
    manual_paid = []
    for o in orders:
        if o.get("test"):
            continue
        name = o.get("name") or "?"
        if o.get("cancelledAt"):
            if o.get("displayFinancialStatus") == "PAID" and _is_manual(o) and _money(o, "totalRefundedSet") == 0:
                manual_paid.append((name, _money(o, "totalPriceSet")))
            continue
        paid = o.get("displayFinancialStatus") in ("PAID", "PARTIALLY_PAID", "PARTIALLY_REFUNDED")
        fulfillments = [f for f in o.get("fulfillments") or []
                        if f.get("displayStatus") not in CLOSED_FULFILLMENT]
        if paid and not fulfillments and o.get("displayFulfillmentStatus") not in (
                "FULFILLED", "FULFILLMENT_NOT_REQUIRED"):
            age = _days(_ts(o.get("createdAt")), now)
            if age > s.ship_within_days:
                out.append(Alert(HIGH, "pedido_sin_enviar", name,
                                 f"Pedido {name} pagado hace {age:.0f} días y sin enviar.",
                                 "Comprobar el pedido al proveedor y el número de seguimiento."))
        for f in fulfillments:
            status = f.get("displayStatus") or ""
            numbers = [t.get("number") for t in f.get("trackingInfo") or [] if t.get("number")]
            if status in DELIVERED or f.get("deliveredAt"):
                continue
            if status in FAILURE_STATUSES:
                out.append(Alert(URGENT, "entrega_fallida", name,
                                 f"Pedido {name}: el transportista marca «{status}».",
                                 "Revisar el seguimiento y contactar con la clienta (tú decides el mensaje).",
                                 needs_owner=True))
                continue
            if not numbers:
                out.append(Alert(MEDIUM, "sin_seguimiento", name,
                                 f"Pedido {name} enviado sin número de seguimiento.",
                                 "Pedir el número al proveedor y añadirlo al pedido."))
            sent = _ts(f.get("createdAt"))
            eta = _ts(f.get("estimatedDeliveryAt"))
            age = _days(sent, now)
            if (eta and now > eta) or age > s.deliver_within_days:
                out.append(Alert(URGENT if age > s.deliver_within_days + 7 else HIGH,
                                 "entrega_retrasada", name,
                                 f"Pedido {name} enviado hace {age:.0f} días y sin entregar "
                                 f"(plazo prometido: {s.deliver_within_days} días).",
                                 "Revisar el seguimiento y preparar una solución para la clienta.",
                                 needs_owner=True))
    if manual_paid:
        total = sum(a for _, a in manual_paid)
        out.append(Alert(LOW, "pedidos_manuales_cancelados", "pedidos",
                         f"{len(manual_paid)} pedidos manuales (borradores) cancelados siguen como "
                         f"pagados, {total:.2f} EUR sin cobro real: "
                         f"{', '.join(n for n, _ in manual_paid)}.",
                         "No contarlos como ventas en los informes; decidir si se archivan.",
                         needs_owner=True))
    return out



def check_theme(theme: dict | None, s: Settings) -> list[Alert]:
    name = (theme or {}).get("name") or ""
    if any(w.lower() in name.lower() for w in s.test_theme_words):
        return [Alert(HIGH, "tema_de_pruebas_publicado", (theme or {}).get("id", "tema"),
                      f"El tema publicado se llama «{name}».",
                      "Confirmar si es intencionado; si no, publicar el tema revisado.",
                      needs_owner=True)]
    return []


def check_catalog(products: list[dict]) -> list[Alert]:
    audits = audit_catalog(products)
    s = summary(audits)
    out = []
    critical = [a for a in audits if a.worst == "critical"]
    if critical:
        out.append(Alert(HIGH, "catalogo_critico", "catalogo",
                         f"{len(critical)} de {s['products']} productos activos con un problema "
                         "que impide vender o es un riesgo legal.",
                         "Ver `harvey shop audit` para la lista; cada cambio necesita tu aprobación.",
                         needs_owner=True))
    no_tracking = s["by_issue"].get("no_tracking", 0)
    if no_tracking:
        out.append(Alert(MEDIUM, "venta_sin_stock", "catalogo",
                         f"{no_tracking} productos activos se venden sin control de stock.",
                         "Verificar proveedor y stock antes de promocionarlos."))
    return out


def _purchases(row: dict) -> int:
    total = 0
    for a in row.get("actions") or []:
        if a.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase"):
            try:
                total = max(total, int(float(a.get("value") or 0)))
            except ValueError:
                pass
    return total


def check_ads(campaigns: list[dict], insights: list[dict], s: Settings) -> list[Alert]:
    out = []
    active = [c for c in campaigns if c.get("effective_status") == "ACTIVE"]
    for c in active:
        out.append(Alert(HIGH, "campana_activa", str(c.get("id")),
                         f"La campaña «{c.get('name')}» está ACTIVA.",
                         "Confirmar que la activaste tú; Harvey no la toca.", needs_owner=True))
    spend = 0.0
    for row in insights:
        try:
            value = float(row.get("spend") or 0)
        except ValueError:
            value = 0.0
        spend += value
        if value >= s.ad_spend_without_sale_eur and _purchases(row) == 0:
            out.append(Alert(HIGH, "gasto_sin_ventas", str(row.get("campaign_id")),
                             f"«{row.get('campaign_name')}» lleva {value:.2f} EUR hoy sin compras.",
                             "Valorar pausarla (necesita tu aprobación).", needs_owner=True))
    if spend > s.ad_daily_cap_eur and active:
        out.append(Alert(URGENT if spend > s.ad_daily_cap_eur + 20 else HIGH, "gasto_sobre_limite",
                         "meta", f"Gasto en Meta hoy: {spend:.2f} EUR (límite: {s.ad_daily_cap_eur:.2f}).",
                         "Revisar qué campaña gasta y decidir si se pausa.", needs_owner=True))
    elif spend > s.ad_daily_cap_eur:
        # Spent earlier today by a campaign that is paused now: worth knowing, nothing to stop.
        out.append(Alert(MEDIUM, "gasto_antes_de_pausa", "meta",
                         f"Gasto en Meta hoy: {spend:.2f} EUR, de campañas que ya están en pausa.",
                         "Nada que parar; queda anotado para el control de gastos."))
    return out


def run_checks(snapshot: dict, now: datetime | None = None,
               settings: Settings | None = None) -> tuple[list[Alert], list[str]]:
    """Alerts, and the areas that could not be checked (no data)."""
    now = now or datetime.now(UTC)
    s = settings or Settings()
    alerts, unchecked = [], []
    if "orders" in snapshot:
        alerts += check_orders(snapshot["orders"], now, s)
    else:
        unchecked.append("pedidos y entregas")
    if "theme" in snapshot:
        alerts += check_theme(snapshot["theme"], s)
    else:
        unchecked.append("tema publicado")
    if "products" in snapshot:
        alerts += check_catalog(snapshot["products"])
    else:
        unchecked.append("catálogo")
    if "campaigns" in snapshot:
        alerts += check_ads(snapshot["campaigns"], snapshot.get("insights") or [], s)
    else:
        unchecked.append("Meta Ads")
    alerts.sort(key=lambda a: (SEVERITIES.index(a.severity), a.code, a.key))
    return alerts, unchecked
