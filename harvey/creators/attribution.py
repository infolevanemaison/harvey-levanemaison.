"""Which orders a creator brought, and which of them earn a commission.

Three numbers that must never be mixed up:

- **attributed traffic**: sessions that arrived through her UTM link. A
  visit is not a sale.
- **attributed orders**: orders carrying her code, or whose last visit came
  through her link. Not yet money: they can be cancelled or returned.
- **verified sales**: attributed orders that are paid, not cancelled, not
  fully refunded, not entered by hand, and older than the return window.
  Only these earn a commission, on what is left after partial refunds.

Input is the shape of the read-only Admin GraphQL query in ORDERS_QUERY. It
asks for no customer field: no name, email or address, only the country.
Nothing here writes to the shop or pays anyone.
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from harvey.creators.tracking import MEDIUM, _slug

ORDERS_QUERY = """query($first: Int!, $after: String, $q: String) {
  orders(first: $first, after: $after, query: $q, sortKey: CREATED_AT) {
    nodes {
      name createdAt sourceName cancelledAt displayFinancialStatus discountCodes taxesIncluded
      currentSubtotalPriceSet { shopMoney { amount } }
      currentTotalTaxSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      shippingAddress { countryCodeV2 }
      customerJourneySummary { daysToConversion lastVisit { utmParameters { source medium campaign content } } }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""

PAID = ("PAID", "PARTIALLY_REFUNDED")
MANUAL_SOURCES = ("shopify_draft_order", "pos")

# Order states, in the words the report uses.
VERIFIED = "verificada"
PENDING = "pendiente (dentro del plazo de devolución)"
UNPAID = "pendiente de pago"
INVALID = "no válida"


@dataclass
class Affiliate:
    handle: str
    code: str = ""                     # her unique code, once created in Shopify
    rate_pct: float = 0.0
    base: str = "sin_iva"              # sin_iva | con_iva
    start: str = ""                    # YYYY-MM-DD, orders before it are not hers
    end: str = ""
    approved: bool = False             # the owner approved these terms


def load_affiliates(path: str) -> list[Affiliate]:
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not (r.get("handle") or "").strip():
                continue
            out.append(Affiliate(
                handle=r["handle"].strip().lstrip("@"), code=(r.get("codigo") or "").strip(),
                rate_pct=float((r.get("comision_pct") or "0").replace(",", ".")),
                base=(r.get("base") or "sin_iva").strip(), start=(r.get("inicio") or "").strip(),
                end=(r.get("fin") or "").strip(),
                approved=(r.get("aprobado") or "").strip().lower() in ("si", "sí", "yes", "true")))
    return out


def orders_from(data) -> list[dict]:
    """The order list from a saved query result: the raw response, its
    `orders` object, a `nodes` list or several pages saved as a list."""
    if isinstance(data, list):
        if data and isinstance(data[0], dict) and "createdAt" not in data[0]:
            return [o for page in data for o in orders_from(page)]
        return data
    for key in ("data", "orders"):
        if isinstance(data.get(key), dict):
            return orders_from(data[key])
    return list(data.get("nodes") or [])


def _money(node: dict, key: str) -> float:
    try:
        return float(((node.get(key) or {}).get("shopMoney") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _in_period(order_day: str, a: Affiliate) -> bool:
    return (not a.start or order_day >= a.start) and (not a.end or order_day <= a.end)


@dataclass
class Attributed:
    order: str
    handle: str
    via: str                           # "código" or "enlace"
    state: str
    reason: str
    base_amount: float                 # what the commission would be a percentage of
    commission: float                  # only for verified orders, else 0
    country: str = ""


def attribute(order: dict, affiliates: list[Affiliate], now: datetime,
              validation_days: int = 47, utm_window_days: int = 30) -> Attributed | None:
    """The creator an order belongs to, how, and whether it is a valid sale.

    A code beats a link: if the order carries creator A's code and its last
    visit came through creator B's link, it is A's. validation_days runs from
    the order date: by default 17 days for delivery plus the 30-day return
    period, so it is never verified while it can still be returned."""
    codes = {c.upper() for c in order.get("discountCodes") or []}
    day = (order.get("createdAt") or "")[:10]
    journey = order.get("customerJourneySummary") or {}
    utm = ((journey.get("lastVisit") or {}).get("utmParameters") or {})
    days = journey.get("daysToConversion")

    who = via = None
    for a in affiliates:
        if a.code and a.code.upper() in codes and _in_period(day, a):
            who, via = a, "código"
            break
    if who is None and (utm.get("medium") or "").lower() == MEDIUM:
        content = _slug(utm.get("content") or "")
        for a in affiliates:
            if _slug(a.handle) == content and _in_period(day, a):
                if days is None or days <= utm_window_days:
                    who, via = a, "enlace"
                break
    if who is None:
        return None

    subtotal, tax = _money(order, "currentSubtotalPriceSet"), _money(order, "currentTotalTaxSet")
    base_amount = round(subtotal - tax if who.base == "sin_iva" else subtotal, 2)
    status = order.get("displayFinancialStatus") or ""
    if (order.get("sourceName") or "") in MANUAL_SOURCES:
        state, reason = INVALID, "pedido introducido a mano, no es una venta online"
    elif order.get("cancelledAt"):
        state, reason = INVALID, "cancelado"
    elif status == "REFUNDED" or (subtotal <= 0 and _money(order, "totalRefundedSet") > 0):
        state, reason = INVALID, "reembolsado por completo"
    elif status not in PAID:
        state, reason = UNPAID, f"estado de pago: {status or 'desconocido'}"
    elif now < _when(order["createdAt"]) + timedelta(days=validation_days):
        until = (_when(order["createdAt"]) + timedelta(days=validation_days)).date().isoformat()
        state, reason = PENDING, f"se puede validar a partir del {until}"
    else:
        state, reason = VERIFIED, ("pagado, sin cancelar y fuera de plazo"
                                   + (" (reembolso parcial descontado)" if status == "PARTIALLY_REFUNDED" else ""))
    commission = round(base_amount * who.rate_pct / 100, 2) if state == VERIFIED else 0.0
    return Attributed(order=order.get("name", "?"), handle=who.handle, via=via, state=state,
                      reason=reason, base_amount=base_amount, commission=commission,
                      country=((order.get("shippingAddress") or {}).get("countryCodeV2") or ""))


@dataclass
class CreatorTotals:
    handle: str
    sessions: int | None = None        # attributed traffic (UTM), None when not measured
    attributed: int = 0
    pending: int = 0
    invalid: int = 0
    verified: int = 0
    verified_sales: float = 0.0
    commission: float = 0.0
    pending_sales: float = 0.0
    approved: bool = False
    by_code: int = 0
    by_link: int = 0
    lines: list = field(default_factory=list)


def summarise(orders: list[dict], affiliates: list[Affiliate], now: datetime | None = None,
              sessions: dict | None = None, validation_days: int = 47) -> list[CreatorTotals]:
    now = now or datetime.now(UTC)
    totals = {a.handle: CreatorTotals(handle=a.handle, approved=a.approved,
                                      sessions=(sessions or {}).get(_slug(a.handle)))
              for a in affiliates}
    for o in orders:
        hit = attribute(o, affiliates, now, validation_days)
        if hit is None:
            continue
        t = totals[hit.handle]
        t.attributed += 1
        t.lines.append(hit)
        if hit.via == "código":
            t.by_code += 1
        else:
            t.by_link += 1
        if hit.state == VERIFIED:
            t.verified += 1
            t.verified_sales = round(t.verified_sales + hit.base_amount, 2)
            t.commission = round(t.commission + hit.commission, 2)
        elif hit.state == INVALID:
            t.invalid += 1
        else:
            t.pending += 1
            t.pending_sales = round(t.pending_sales + hit.base_amount, 2)
    return list(totals.values())


def load_sessions(path: str) -> dict:
    """utm_content,sessions rows (the ShopifyQL sessions query, exported)."""
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = _slug(r.get("utm_content") or "")
            if key:
                out[key] = out.get(key, 0) + int(float(r.get("sessions") or 0))
    return out


def report(totals: list[CreatorTotals], affiliates: list[Affiliate]) -> str:
    def eur(x):
        return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    base = {a.handle: a.base for a in affiliates}
    lines = ["## Atribución por creadora", "",
             ("| Creadora | Visitas (UTM) | Pedidos atribuidos | Pendientes | No válidos | "
              "Verificados | Ventas verificadas | Comisión devengada |"),
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for t in totals:
        visits = "sin medir" if t.sessions is None else str(t.sessions)
        com = eur(t.commission) + ("" if t.approved else " (simulación: condiciones sin aprobar)")
        lines.append(f"| @{t.handle} | {visits} | {t.attributed} ({t.by_code} código, {t.by_link} enlace) | "
                     f"{t.pending} | {t.invalid} | {t.verified} | {eur(t.verified_sales)} "
                     f"({base.get(t.handle, 'sin_iva').replace('_', ' ')}) | {com} |")
    lines += ["",
              "- **Visitas** es tráfico atribuido: no es una venta.",
              "- **Pedidos atribuidos** incluye pedidos que aún pueden cancelarse o devolverse.",
              ("- **Ventas verificadas**: pagadas, sin cancelar, sin reembolso total, online y fuera del "
               "plazo de devolución. Solo estas generan comisión, sobre el importe que queda tras reembolsos parciales.")]
    detail = [ln for t in totals for ln in t.lines]
    if detail:
        lines += ["", "| Pedido | Creadora | Vía | Estado | Motivo | Base | Comisión |",
                  "|---|---|---|---|---|---:|---:|"]
        for d in detail:
            lines.append(f"| {d.order} | @{d.handle} | {d.via} | {d.state} | {d.reason} | "
                         f"{eur(d.base_amount)} | {eur(d.commission)} |")
    return "\n".join(lines)
