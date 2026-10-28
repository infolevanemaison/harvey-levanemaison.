"""From candidates to collaborations worth paying for.

Two questions a shop owner asks before saying yes to a creator:
- Who should I look at first, and what is the next step with each one?
- If she charges X, how many orders does she need to bring to pay for it?

Both answers are deterministic and say which numbers are assumptions.
Nothing here contacts anyone or spends anything.
"""

from dataclasses import dataclass

from harvey.creators.scoring import DISCARD, INCOMPLETE, PRIORITY, REVIEW, channel_of, viable_terms
from harvey.creators.tracking import Economics, break_even_orders

VERDICT_POINTS = {PRIORITY: 3, REVIEW: 2, INCOMPLETE: 1, DISCARD: -5}
CLOSED = ("rejected", "opted_out", "measured")


@dataclass
class Deal:
    unit_contribution: float | None   # what one order leaves after margin and commission
    break_even_orders: float | None   # orders needed to recover fee + gift
    max_cost_for_orders: dict         # {orders: highest fee+gift that still breaks even}
    assumptions: list[str]


def deal(fee: float, avg_order_value: float, margin_pct: float,
         commission_pct: float = 0.0, gift_cost: float = 0.0) -> Deal:
    econ = Economics(gross_margin_pct=margin_pct, commission_pct=commission_pct,
                     gift_cost=gift_cost, fee=fee)
    unit = avg_order_value * (margin_pct - commission_pct) / 100
    unit = round(unit, 2) if unit > 0 else None
    return Deal(
        unit_contribution=unit,
        break_even_orders=break_even_orders(avg_order_value, econ),
        max_cost_for_orders={n: round(n * unit, 2) for n in (2, 5, 10)} if unit else {},
        assumptions=[f"ticket medio {avg_order_value:.2f} EUR", f"margen bruto {margin_pct:g} %",
                     f"comisión {commission_pct:g} %", f"coste fijo {fee:.2f} EUR",
                     f"producto enviado {gift_cost:.2f} EUR"],
    )


def _size_points(creator) -> int:
    if creator.platform == "blog":
        return 1
    f = creator.followers or 0
    if 2_000 <= f <= 50_000:
        return 2          # micro: usually the best cost per real interaction
    if 0 < f < 2_000 or 50_000 < f <= 150_000:
        return 1
    return 0


def _channel(row: dict) -> str:
    return channel_of(row["creator"])


def next_action(row: dict, proposals: list[dict]) -> str:
    c, detail = row["creator"], row.get("score_detail") or {}
    mine = [p for p in proposals if p["creator_id"] == row["id"]]
    if row["status"] in CLOSED:
        return "ninguna (cerrada)"
    if row["verdict"] == DISCARD:
        return "ninguna: descartada por las reglas de puntuación (ver `show`)"
    if any(p["status"] == "pending_review" for p in mine):
        pid = next(p["id"] for p in mine if p["status"] == "pending_review")
        if not _channel(row):
            return (f"propuesta {pid} en espera: no hay un canal permitido para enviarla "
                    "(busca uno que ella abra para colaboraciones)")
        return f"decidir la propuesta {pid} (aprobar o rechazar)"
    if any(p["status"] == "approved" for p in mine):
        return "crear el borrador y enviarlo tú por su canal"
    if any(p["status"] in ("drafted", "sent") for p in mine):
        return "esperar respuesta (Harvey avisa del recordatorio a los 7 días)"
    if not _channel(row):
        return "verificar un canal de colaboraciones (web, formulario, plataforma)"
    if not c.stats_verified:
        return "conseguir estadísticas verificadas (media kit o capturas) antes de decidir"
    if not viable_terms(c) and c.quoted_fee_eur is None:
        return "saber si acepta comisión o producto, o su tarifa, antes de valorar el coste"
    return "valorar con `harvey creators value` y decidir"


def pipeline(rows: list[dict], proposals: list[dict]) -> list[dict]:
    """Open creators ranked by commercial priority, each with its next step."""
    out = []
    for row in rows:
        if row["status"] in CLOSED:
            continue
        detail = row.get("score_detail") or {}
        c = row["creator"]
        verified, channel, viable = c.stats_verified, _channel(row), viable_terms(c)
        # The three things that make an opportunity real: numbers she can
        # prove, a channel we may use, and terms a zero budget can afford.
        points = (VERDICT_POINTS.get(row["verdict"], 0)
                  + (3 if channel else 0)
                  + (3 if verified else 0)
                  + (3 if viable else 0)
                  + _size_points(c)
                  + (2 if detail.get("engagement_rate") else 0)
                  + (1 if c.quoted_fee_eur is not None else 0))
        out.append({"id": row["id"], "handle": row["handle"], "name": c.display_name,
                    "country": c.country, "verdict": row["verdict"],
                    "channel": channel, "verified": verified, "viable": viable,
                    "priority": points, "next": next_action(row, proposals)})
    return sorted(out, key=lambda r: (-r["priority"], r["handle"]))


# ── Commission simulation, only with real costs ─────────────────────────────

REQUIRED_COSTS = ("pvp", "coste_proveedor", "envio_proveedor", "iva_pct")


@dataclass
class CommissionLine:
    product: str
    rate_pct: float
    commission: float | None
    profit: float | None              # per order, only when every real cost is known
    missing: list[str]


def _amount(value) -> float | None:
    text = str(value or "").strip().replace("€", "").replace(",", ".")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def commission_table(costs: list[dict], rates=(5.0, 10.0, 15.0),
                     pay_rate_pct: float | None = None, pay_fixed: float | None = None,
                     discount_pct: float = 0.0) -> list[CommissionLine]:
    """Per product and commission rate: the commission and, only when the
    price, supplier cost, supplier shipping, VAT rate and payment fee are
    all real figures, the profit per order. A missing figure is named, never
    guessed. VAT comes out of the price (prices include it); the commission
    is paid on the net sale (price after discount, without VAT)."""
    out = []
    for row in costs:
        row = dict(row)
        row.setdefault("envio_proveedor", row.get("envio_es"))      # the cost register's column
        row.setdefault("iva_pct", row.get("iva_es_pct"))
        vals = {k: _amount(row.get(k)) for k in REQUIRED_COSTS}
        missing = [k for k, v in vals.items() if v is None]
        if pay_rate_pct is None or pay_fixed is None:
            missing.append("comision_pago")
        pvp = vals["pvp"]
        for rate in rates:
            commission = profit = None
            if pvp is not None and vals["iva_pct"] is not None:
                paid = pvp * (1 - discount_pct / 100)
                net = paid / (1 + vals["iva_pct"] / 100)
                commission = round(net * rate / 100, 2)
                if not missing:
                    fee = paid * pay_rate_pct / 100 + pay_fixed
                    profit = round(net - vals["coste_proveedor"] - vals["envio_proveedor"]
                                   - fee - commission, 2)
            out.append(CommissionLine(product=row.get("producto", "?"), rate_pct=rate,
                                      commission=commission, profit=profit, missing=missing))
    return out


# ── Break-even with checked costs only ──────────────────────────────────────

BASES = ("sin_iva", "con_iva")
UNCHECKED = ("pendiente", "supuesto", "estimado", "?")


def _checked(row: dict, value_key: str, source_key: str) -> tuple[float | None, str]:
    """A cost counts only with a value AND a source that says where it was
    checked (an invoice, a supplier order, the shop's own record). An empty
    source or one marked PENDIENTE / SUPUESTO / ESTIMADO is not a checked cost."""
    value, source = _amount(row.get(value_key)), str(row.get(source_key) or "").strip()
    if value is None or not source or source.lower().startswith(UNCHECKED):
        return None, source
    return value, source


@dataclass
class BreakEven:
    product: str
    country: str
    base: str                          # what the commission is a percentage of
    paid: float | None                 # what the customer pays, VAT included
    net: float | None                  # paid without VAT
    margin: float | None               # net - supplier - shipping - payment fee, before commission
    max_rate_pct: float | None         # commission % on `base` that leaves exactly 0
    profit: dict                       # {rate: profit per order}
    missing: list[str]
    sources: dict


def break_even_table(costs: list[dict], country: str = "es", base: str = "sin_iva",
                     pay_rate_pct: float | None = None, pay_fixed: float | None = None,
                     discount_pct: float = 0.0, rates=(5.0, 10.0, 15.0)) -> list[BreakEven]:
    """Per product, for one destination country: the margin an order leaves
    before commission and the highest commission that still breaks even.

    Columns read from the cost register: pvp, coste_proveedor/fuente_coste,
    envio_<country>/fuente_envio_<country>, iva_<country>_pct/fuente_iva.
    `base` says whether the commission is a percentage of the sale without
    VAT (sin_iva) or of what the customer paid (con_iva). Nothing is
    computed from a cost that has not been checked: it is listed as missing."""
    if base not in BASES:
        raise ValueError(f"base must be one of {BASES}")
    cc = country.lower()
    out = []
    for row in costs:
        pvp = _amount(row.get("pvp"))
        supplier, s_src = _checked(row, "coste_proveedor", "fuente_coste")
        ship, sh_src = _checked(row, f"envio_{cc}", f"fuente_envio_{cc}")
        vat, v_src = _checked(row, f"iva_{cc}_pct", "fuente_iva")
        missing = [k for k, v in (("pvp", pvp), ("coste_proveedor", supplier),
                                  (f"envio_{cc}", ship), (f"iva_{cc}_pct", vat)) if v is None]
        if pay_rate_pct is None or pay_fixed is None:
            missing.append("comision_pago")
        paid = net = margin = max_rate = None
        profit = {}
        if pvp is not None:
            paid = round(pvp * (1 - discount_pct / 100), 2)
        if paid is not None and vat is not None:
            net = round(paid / (1 + vat / 100), 2)
        if not missing:
            fee = paid * pay_rate_pct / 100 + pay_fixed
            margin = round(net - supplier - ship - fee, 2)
            on = net if base == "sin_iva" else paid
            max_rate = round(100 * margin / on, 1) if margin > 0 else 0.0
            profit = {r: round(margin - on * r / 100, 2) for r in rates}
        out.append(BreakEven(product=row.get("producto", "?"), country=cc, base=base, paid=paid,
                             net=net, margin=margin, max_rate_pct=max_rate, profit=profit,
                             missing=missing,
                             sources={"coste": s_src, "envio": sh_src, "iva": v_src}))
    return out
