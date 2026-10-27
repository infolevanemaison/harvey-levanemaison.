"""Measuring creator collaborations: UTM links, proposed codes, profitability.

Nothing here touches the shop. Codes are *proposals* a person creates in
Shopify by hand once the conditions are approved; links are plain URLs.
The ShopifyQL queries are read-only and use the column names the shop's
analytics accepts (utm_source / utm_medium / utm_campaign on sessions,
discount_code on sales), checked against the live API.

UTM convention (one source of truth, so reports group cleanly):

  utm_source   = platform        instagram | tiktok | youtube
  utm_medium   = influencer
  utm_campaign = lvm_<country>_<yyyymm>     e.g. lvm_es_202611
  utm_content  = <handle>        the creator, so each one is measurable
"""

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

MEDIUM = "influencer"


def _slug(text: str, upper: bool = False) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", "_" if not upper else "", text).strip("_")
    return text.upper() if upper else text.lower()


def campaign_name(country: str, month: str, prefix: str = "lvm") -> str:
    """lvm_es_202611 for Spain, November 2026. month is YYYY-MM or YYYYMM."""
    digits = re.sub(r"\D", "", month or "")
    if len(digits) != 6:
        raise ValueError("month must be YYYY-MM")
    return f"{_slug(prefix)}_{(country or 'xx').lower()}_{digits}"


def utm_link(base_url: str, platform: str, campaign: str, handle: str, path: str = "") -> str:
    """The link a creator shares. Lands on a collection or product, never the
    home page, so the visit starts where the content pointed."""
    if not base_url:
        raise ValueError("set creators.landing_base_url (e.g. https://levanemaison.com)")
    parts = urlsplit(base_url.rstrip("/") + "/" + path.lstrip("/"))
    query = urlencode({
        "utm_source": _slug(platform) or "social",
        "utm_medium": MEDIUM,
        "utm_campaign": campaign,
        "utm_content": _slug(handle),
    })
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path or "/", query, ""))


def proposed_code(display_name: str, handle: str, discount_pct: float, prefix: str = "") -> str:
    """A memorable unique code, e.g. LVM-CARMEN10. Only a suggestion: it
    exists only once a person creates it in Shopify."""
    base = _slug(display_name.split()[0] if display_name.strip() else handle, upper=True)[:10]
    pct = f"{discount_pct:g}" if discount_pct else ""
    code = f"{base}{pct}"
    return f"{_slug(prefix, upper=True)}-{code}" if prefix else code


# ── Read-only ShopifyQL, run through the Shopify connector ──

def shopifyql_sessions(campaign: str, since: str = "-30d") -> str:
    return (f"FROM sessions SHOW sessions, sessions_with_cart_additions, "
            f"sessions_that_reached_checkout, sessions_that_completed_checkout, conversion_rate "
            f"WHERE utm_medium = '{MEDIUM}' AND utm_campaign = '{campaign}' "
            f"GROUP BY utm_source, utm_content SINCE {since} UNTIL today")


def shopifyql_codes(since: str = "-30d") -> str:
    return (f"FROM sales SHOW orders, gross_sales, discounts, net_sales "
            f"GROUP BY discount_code SINCE {since} UNTIL today")


# ── Profitability ──

@dataclass
class Economics:
    gross_margin_pct: float          # product margin before marketing, e.g. 55
    commission_pct: float = 0.0      # paid on net sales through her link/code
    gift_cost: float = 0.0           # cost to you of the pieces sent, incl. shipping
    fee: float = 0.0                 # fixed fee paid to her


@dataclass
class Result:
    handle: str
    sessions: int
    orders: int
    net_sales: float
    commission: float
    gross_profit: float              # margin on her sales
    marketing_cost: float            # commission + gift + fee
    contribution: float              # gross_profit - marketing_cost
    roi: float | None                # contribution / (gift + fee), None if nothing invested
    cost_per_order: float | None
    conversion_rate: float | None


def profitability(handle: str, sessions: int, orders: int, net_sales: float,
                  econ: Economics) -> Result:
    commission = round(net_sales * econ.commission_pct / 100, 2)
    gross_profit = round(net_sales * econ.gross_margin_pct / 100, 2)
    marketing = round(commission + econ.gift_cost + econ.fee, 2)
    contribution = round(gross_profit - marketing, 2)
    invested = econ.gift_cost + econ.fee
    return Result(
        handle=handle, sessions=sessions, orders=orders, net_sales=round(net_sales, 2),
        commission=commission, gross_profit=gross_profit, marketing_cost=marketing,
        contribution=contribution,
        roi=round(contribution / invested, 2) if invested else None,
        cost_per_order=round(marketing / orders, 2) if orders else None,
        conversion_rate=round(orders / sessions, 4) if sessions else None,
    )


def break_even_orders(avg_order_value: float, econ: Economics,
                      discount_pct: float = 0.0) -> float | None:
    """Orders she must bring for the gift and fee to pay for themselves.

    gross_margin_pct is the margin at full price, so a discount comes
    straight off it: per order you keep AOV x (margin - discount), less the
    commission on what the customer actually paid. None when every order
    loses money."""
    m, d, c = econ.gross_margin_pct / 100, discount_pct / 100, econ.commission_pct / 100
    unit = avg_order_value * (m - d) - c * avg_order_value * (1 - d)
    if unit <= 0:
        return None
    return round((econ.gift_cost + econ.fee) / unit, 1)


def report_markdown(results: list[Result], title: str = "Resultados por creadora") -> str:
    """A table a person can read on a phone, plus totals."""
    def eur(x):
        return "-" if x is None else f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    def pct(x):
        return "-" if x is None else f"{x * 100:.1f} %".replace(".", ",")

    lines = [f"## {title}", "",
             "| Creadora | Visitas | Pedidos | Conv. | Ventas netas | Comisión | Coste total | Contribución | ROI |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in sorted(results, key=lambda r: r.contribution, reverse=True):
        roi = "-" if r.roi is None else f"{r.roi:.2f}x".replace(".", ",")
        lines.append(f"| @{r.handle} | {r.sessions} | {r.orders} | {pct(r.conversion_rate)} | "
                     f"{eur(r.net_sales)} | {eur(r.commission)} | {eur(r.marketing_cost)} | "
                     f"{eur(r.contribution)} | {roi} |")
    total_sales = sum(r.net_sales for r in results)
    total_cost = sum(r.marketing_cost for r in results)
    total_contrib = sum(r.contribution for r in results)
    lines += ["", f"**Total:** {sum(r.orders for r in results)} pedidos, ventas {eur(total_sales)}, "
                  f"coste {eur(total_cost)}, contribución {eur(total_contrib)}."]
    losing = [r.handle for r in results if r.contribution < 0]
    if losing:
        lines.append(f"**No renovar sin revisar:** {', '.join('@' + h for h in losing)} "
                     "(contribución negativa).")
    return "\n".join(lines)
