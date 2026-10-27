"""Prepare corrections to product page content, without applying them.

The product pages are built from a JSON metafield per product
(shopipi.sections, written by the Buildora app). Some of its sentences
promise more than the shop's policies do. This module rewrites only those
sentences, by explicit rules, and reports every change so a person can
approve them before anything is written to Shopify.

Each rule is (pattern, replacement, why). Patterns are plain substrings, so
a rule can never touch text it wasn't written for.
"""

import json
from dataclasses import dataclass, field

RULES = (
    ("la entrega tarda entre 7 y 15 días",
     "la entrega tarda entre 8 y 12 días laborables desde el envío",
     "plazo de la política de envíos"),
    ("Recibirás el número de seguimiento por correo.",
     "Recibirás el número de seguimiento por correo cuando el transportista lo ofrezca.",
     "la política solo promete seguimiento si el transportista lo ofrece"),
    ('pl-vol-tag">Más popular<', 'pl-vol-tag">Pack de 2<',
     "«Más popular» no se puede demostrar sin datos de ventas"),
    ('pl-vol-tag\\">Más popular<', 'pl-vol-tag\\">Pack de 2<',
     "«Más popular» no se puede demostrar sin datos de ventas"),
)


@dataclass
class Fix:
    handle: str
    changes: list[tuple[str, int]] = field(default_factory=list)   # (why, count)
    removed_payment_icons: list[str] = field(default_factory=list)


def _rewrite(value, counts: dict):
    if isinstance(value, str):
        for old, new, why in RULES:
            n = value.count(old)
            if n:
                value = value.replace(old, new)
                counts[why] = counts.get(why, 0) + n
        return value
    if isinstance(value, list):
        return [_rewrite(v, counts) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite(v, counts) for k, v in value.items()}
    return value


def fix_sections(handle: str, raw: str, accepted_payments: set[str] | None = None) -> tuple[str, Fix]:
    """(corrected JSON, what changed). accepted_payments: the payment icons
    the shop really accepts (e.g. {"visa", "mastercard", "applepay"}); icons
    outside it are removed. None leaves the icons alone."""
    data = json.loads(raw)
    counts: dict = {}
    data = _rewrite(data, counts)
    fix = Fix(handle=handle, changes=sorted(counts.items()))
    hero = data.get("hero") if isinstance(data, dict) else None
    pago = hero.get("pago") if isinstance(hero, dict) else None
    if accepted_payments is not None and isinstance(pago, dict):
        icons = pago.get("proveedores") or []
        fix.removed_payment_icons = [i for i in icons if i not in accepted_payments]
        pago["proveedores"] = [i for i in icons if i in accepted_payments]
    if not fix.changes and not fix.removed_payment_icons:
        return raw, fix
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")), fix


def fix_catalog(products: list[dict], accepted_payments=None) -> tuple[list[dict], list[Fix]]:
    """products: nodes with id, handle and m.value (the metafield). Returns
    the metafieldsSet inputs for the products that change, and the report."""
    inputs, report = [], []
    for p in products:
        raw = ((p.get("m") or {}).get("value")) or ""
        if not raw:
            continue
        new, fix = fix_sections(p.get("handle", ""), raw, accepted_payments)
        if new != raw:
            inputs.append({"ownerId": p["id"], "namespace": "shopipi", "key": "sections",
                           "type": "json", "value": new})
            report.append(fix)
    return inputs, report


def report_markdown(report: list[Fix]) -> str:
    totals: dict = {}
    for f in report:
        for why, n in f.changes:
            totals[why] = totals.get(why, 0) + n
    icons = sum(1 for f in report if f.removed_payment_icons)
    lines = ["# Correcciones preparadas (sin aplicar)", "",
             f"{len(report)} fichas cambiarían.", "", "| Motivo | Sustituciones |", "|---|---:|"]
    lines += [f"| {why} | {n} |" for why, n in sorted(totals.items())]
    if icons:
        lines.append(f"| iconos de pago no aceptados retirados | {icons} fichas |")
    return "\n".join(lines)
