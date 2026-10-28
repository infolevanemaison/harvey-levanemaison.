"""From candidates to collaborations worth paying for.

Two questions a shop owner asks before saying yes to a creator:
- Who should I look at first, and what is the next step with each one?
- If she charges X, how many orders does she need to bring to pay for it?

Both answers are deterministic and say which numbers are assumptions.
Nothing here contacts anyone or spends anything.
"""

from dataclasses import dataclass

from harvey.creators.scoring import DISCARD, INCOMPLETE, PRIORITY, REVIEW
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
    """The channel from the stored score, or from the creator for rows
    scored before channels existed."""
    detail, c = row.get("score_detail") or {}, row["creator"]
    if detail.get("channel") is not None and "channel" in detail:
        return detail["channel"]
    if c.pro_contact_email and c.pro_contact_source:
        return "email"
    return "canal" if c.pro_contact_source else ""


def next_action(row: dict, proposals: list[dict]) -> str:
    c, detail = row["creator"], row.get("score_detail") or {}
    mine = [p for p in proposals if p["creator_id"] == row["id"]]
    if row["status"] in CLOSED:
        return "ninguna (cerrada)"
    if row["verdict"] == DISCARD:
        return "ninguna: descartada por las reglas de puntuación (ver `show`)"
    if any(p["status"] == "pending_review" for p in mine):
        pid = next(p["id"] for p in mine if p["status"] == "pending_review")
        return f"decidir la propuesta {pid} (aprobar o rechazar)"
    if any(p["status"] == "approved" for p in mine):
        return "crear el borrador y enviarlo tú por su canal"
    if any(p["status"] in ("drafted", "sent") for p in mine):
        return "esperar respuesta (Harvey avisa del recordatorio a los 7 días)"
    if not _channel(row):
        return "verificar un canal de colaboraciones (web, formulario, plataforma)"
    if detail.get("engagement_rate") is None:
        return "pedir media kit o anotar interacción de sus últimas publicaciones"
    if c.quoted_fee_eur is None:
        return "preguntar sus condiciones antes de valorar el coste"
    return "valorar con `harvey creators value` y decidir"


def pipeline(rows: list[dict], proposals: list[dict]) -> list[dict]:
    """Open creators ranked by commercial priority, each with its next step."""
    out = []
    for row in rows:
        if row["status"] in CLOSED:
            continue
        detail = row.get("score_detail") or {}
        points = (VERDICT_POINTS.get(row["verdict"], 0)
                  + {"email": 3, "canal": 2}.get(_channel(row), 0)
                  + _size_points(row["creator"])
                  + (2 if detail.get("engagement_rate") else 0)
                  + (1 if row["creator"].quoted_fee_eur is not None else 0))
        out.append({"id": row["id"], "handle": row["handle"], "name": row["creator"].display_name,
                    "country": row["creator"].country, "verdict": row["verdict"],
                    "channel": _channel(row), "priority": points,
                    "next": next_action(row, proposals)})
    return sorted(out, key=lambda r: (-r["priority"], r["handle"]))
