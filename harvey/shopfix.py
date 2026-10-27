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
import re
from dataclasses import dataclass, field

RULES = (
    # The longer sentence first, so it reads naturally once corrected.
    ("la entrega tarda entre 7 y 15 días en España y Francia",
     "la entrega a España y Francia tarda entre 8 y 12 días laborables desde el envío",
     "plazo de la política de envíos"),
    ("la entrega tarda entre 7 y 15 días",
     "la entrega tarda entre 8 y 12 días laborables desde el envío",
     "plazo de la política de envíos"),
    ("Recibirás el número de seguimiento por correo.",
     "Recibirás el número de seguimiento por correo cuando el transportista lo ofrezca.",
     "la política solo promete seguimiento si el transportista lo ofrece"),
    ("El envío es gratis y recibirás el número de seguimiento por correo.",
     "El envío es gratis y, cuando el transportista lo ofrezca, recibirás el número de "
     "seguimiento por correo.",
     "la política solo promete seguimiento si el transportista lo ofrece"),
    ('pl-vol-tag">Más popular<', 'pl-vol-tag">Pack de 2<',
     "«Más popular» no se puede demostrar sin datos de ventas"),
    ('pl-vol-tag\\">Más popular<', 'pl-vol-tag\\">Pack de 2<',
     "«Más popular» no se puede demostrar sin datos de ventas"),
)

# Product descriptions (descriptionHtml) also feed Google Shopping and the
# Shop app, so the same care applies there. Regex rules, each anchored to the
# exact claim it removes.
DESCRIPTION_RULES = (
    (r"Por qué (esta prenda|este conjunto|este vestido) encanta tanto:", "Lo que la hace especial:",
     "«encanta tanto» presupone opiniones de clientas que no constan"),
    (r"Por qué (este zapato|este bolso|este modelo) encanta tanto:", "Lo que lo hace especial:",
     "«encanta tanto» presupone opiniones de clientas que no constan"),
    (r"\s*favorecedor para todo tipo de cuerpos?", " fácil de llevar",
     "nadie puede prometer que favorece a todos los cuerpos"),
    (r"™", "", "el símbolo ™ reivindica una marca que no consta registrada"),
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


def fix_description(html_text: str) -> tuple[str, list[tuple[str, int]]]:
    """(corrected description, [(why, count)])."""
    counts: dict = {}
    for pattern, new, why in DESCRIPTION_RULES:
        html_text, n = re.subn(pattern, new, html_text)
        if n:
            counts[why] = counts.get(why, 0) + n
    return html_text, sorted(counts.items())


def sections_value(product: dict) -> str:
    """The shopipi.sections JSON of a product node, whether it was queried as
    an aliased `m: metafield(...)` or inside `metafields { nodes }`."""
    if (product.get("m") or {}).get("value"):
        return product["m"]["value"]
    for m in (product.get("metafields") or {}).get("nodes") or []:
        if m.get("namespace") == "shopipi" and m.get("key") == "sections":
            return m.get("value") or ""
    return ""


def fix_catalog(products: list[dict], accepted_payments=None) -> tuple[list[dict], list[Fix]]:
    """products: nodes with id, handle and the shopipi.sections metafield.
    Returns the metafieldsSet inputs for the products that change, and the
    report."""
    inputs, report = [], []
    for p in products:
        raw = sections_value(p)
        if not raw:
            continue
        new, fix = fix_sections(p.get("handle", ""), raw, accepted_payments)
        if new != raw:
            inputs.append({"ownerId": p["id"], "namespace": "shopipi", "key": "sections",
                           "type": "json", "value": new})
            report.append(fix)
    return inputs, report


def only_rule_changes(before_raw: str, after_raw: str) -> bool:
    """True when after_raw is exactly what the rules make of before_raw: no
    other text, image, price or block of the page has moved."""
    expected, _ = fix_sections("", before_raw)
    return json.loads(expected) == json.loads(after_raw)


# What a buyer needs from a product page, and must still be there after a
# content correction. Each entry is (label, how to read it from a node).
INTEGRITY = (
    ("estado", lambda p: p.get("status")),
    ("plantilla", lambda p: p.get("templateSuffix")),
    ("título", lambda p: p.get("title")),
    ("descripción", lambda p: p.get("descriptionHtml")),
    ("fotos", lambda p: [m.get("id") for m in (p.get("media") or {}).get("nodes") or []]),
    ("opciones y tallas", lambda p: p.get("options")),
    ("variantes", lambda p: [v.get("id") for v in (p.get("variants") or {}).get("nodes") or []]),
    ("precios", lambda p: [(v.get("price"), v.get("compareAtPrice"))
                           for v in (p.get("variants") or {}).get("nodes") or []]),
    ("disponibles para la venta", lambda p: [v.get("availableForSale")
                                             for v in (p.get("variants") or {}).get("nodes") or []]),
    ("otros metacampos", lambda p: sorted((m.get("namespace"), m.get("key"), m.get("value"))
                                          for m in (p.get("metafields") or {}).get("nodes") or []
                                          if (m.get("namespace"), m.get("key")) != ("shopipi", "sections"))),
)


def buy_button_visible(raw: str) -> bool:
    """The page shows «Añadir al carrito»: the label is there and the app's
    switch that hides the purchase block is off."""
    try:
        hero = json.loads(raw).get("hero") or {}
    except (ValueError, AttributeError):
        return False
    return bool(hero.get("cta_add")) and not hero.get("ocultar_compra")


def integrity_report(before: dict, after: dict) -> list[tuple[str, bool]]:
    """[(what, unchanged?)] comparing two snapshots of the same product, plus
    whether the page still carries its buy button and its corrected text."""
    rows = [(label, read(before) == read(after)) for label, read in INTEGRITY]
    b, a = sections_value(before), sections_value(after)
    rows.append(("contenido: solo cambian las frases de las reglas", only_rule_changes(b, a)))
    rows.append(("botón «Añadir al carrito» visible", buy_button_visible(a)))
    return rows


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
