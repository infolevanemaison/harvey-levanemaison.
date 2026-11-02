"""Read-only catalog audit for a Shopify fashion store.

Input: the products as the Shopify Admin GraphQL API returns them (the
query is PRODUCTS_QUERY; run it through the Shopify connector and save the
nodes as JSON). Output: findings per product and a summary, ranked by how
much each issue costs in conversion. Nothing here talks to Shopify or
changes anything: a person applies the fixes.

Each finding has a severity:
  critical  stops a sale or creates legal risk
  high      costs conversion on every visit
  medium    hurts trust, search or operations
  low       polish
"""

import html
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

PRODUCTS_QUERY = """query($first:Int,$after:String){ products(first:$first, after:$after,
query:"status:active"){ pageInfo{hasNextPage endCursor} nodes{ title handle productType tags
totalInventory tracksInventory mediaCount{count} featuredMedia{alt} seo{title description}
options{name values} descriptionHtml collections(first:5){nodes{handle}}
priceRangeV2{minVariantPrice{amount} maxVariantPrice{amount}}
compareAtPriceRange{maxVariantCompareAtPrice{amount}}
variants(first:1){nodes{deliveryProfile{name}}} } } }"""

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# What a women's fashion store for 35-65 sells. Everything else is off-niche.
OFF_NICHE = {
    "hogar": ("lámpara", "lampara", "vitral", "maison"),
    "hombre": ("hombre", "homme", "chaquetas hombre"),
    "deporte": ("deportiv", "leggings", "fitness"),
}
# Words in a handle that are French or Italian, on a Spanish store.
FOREIGN_HANDLE_WORDS = {
    "robe", "veste", "chaussures", "mocassins", "ballerines", "escarpins", "sandales",
    "combinaison", "jupe", "pull", "sac", "ensemble", "tailleur", "blouson", "brides",
    "talon", "courte", "dentelle", "fleurs", "volants", "completo", "pantaloni",
    "drappeggiata", "abbigliamento", "homme", "souples", "confortables", "elegants",
    "elegantes", "classiques", "imprime", "boucle", "plateforme", "cheville",
}
# "Color" is Spanish too, so it is not on the list.
ENGLISH_OPTION_WORDS = {"size", "shoe size", "colour", "light gray", "burgundy",
                        "black", "white", "red", "blue", "green", "grey", "gray", "pink"}
MATERIAL_WORDS = ("composición", "composicion", "algodón", "algodon", "poliéster", "poliester",
                  "elastano", "nailon", "nylon", "viscosa", "lino", "piel", "cuero", "lana",
                  "seda", "satén", "saten", "punto", "gasa", "encaje", "lona", "ante", "%")
SIZE_WORDS = ("guía de tallas", "guia de tallas", "medidas", " cm", "talla")
# Claims that need proof or are regulated (health, slimming, orthopaedic).
CLAIM_PATTERNS = ("ortopéd", "ortoped", "adelgaz", "reduce talla", "alisante", "moldea",
                  "corrige", "terapéut", "terapeut", "milagro", "garantizad")


@dataclass
class Finding:
    severity: str
    code: str
    message: str


@dataclass
class ProductAudit:
    title: str
    handle: str
    niche: str                      # "mujer" or the off-niche group
    findings: list[Finding] = field(default_factory=list)

    @property
    def worst(self) -> str:
        if not self.findings:
            return "ok"
        return min((f.severity for f in self.findings), key=SEVERITY_ORDER.get)


def _text(description_html: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", description_html or ""))).strip()


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def niche_of(product: dict) -> str:
    haystack = " ".join([
        product.get("title", ""), product.get("productType", "") or "",
        " ".join(c.get("handle", "") for c in (product.get("collections") or {}).get("nodes", [])),
    ]).lower()
    for group, words in OFF_NICHE.items():
        if any(w in haystack for w in words):
            return group
    return "mujer"


def audit_product(p: dict) -> ProductAudit:
    out = ProductAudit(title=p.get("title", ""), handle=p.get("handle", ""), niche=niche_of(p))
    add = lambda sev, code, msg: out.findings.append(Finding(sev, code, msg))  # noqa: E731

    if out.niche != "mujer":
        add("high", "off_niche", f"Fuera del nicho de moda mujer ({out.niche}): resta "
                                 "coherencia de marca; sácalo del menú o archívalo.")

    media = ((p.get("mediaCount") or {}).get("count")) or 0
    if media <= 1:
        add("high", "one_image", "Una sola foto: en moda se compra mirando detalles, "
                                 "espalda y la prenda puesta. Mínimo 4.")
    elif media < 4:
        add("medium", "few_images", f"Solo {media} fotos; lo recomendable son 4 o más.")

    alt = ((p.get("featuredMedia") or {}).get("alt") or "").strip()
    if not alt:
        add("low", "no_alt", "La foto principal no tiene texto alternativo (accesibilidad y Google).")

    inventory = p.get("totalInventory") or 0
    if p.get("tracksInventory") is False:
        add("critical", "no_tracking", "Se vende sin control de stock: riesgo de vender tallas "
                                       "que no existen y de devoluciones.")
    elif inventory >= 5000 or inventory == 999:
        add("medium", "fake_stock", f"Stock de {inventory} unidades poco creíble: revisa la "
                                    "sincronización con el proveedor.")

    price = _num(((p.get("priceRangeV2") or {}).get("minVariantPrice") or {}).get("amount"))
    compare = _num(((p.get("compareAtPriceRange") or {}).get("maxVariantCompareAtPrice") or {}).get("amount"))
    if compare and price and compare > price:
        sev = "critical" if compare >= price * 1.8 else "medium"
        add(sev, "compare_at", f"Precio tachado {compare:.2f} € frente a {price:.2f} €: solo es "
                               "legal si fue el precio más bajo de los 30 días anteriores "
                               "(Ley 7/1996, art. 20). Si no, quítalo.")

    if not (p.get("productType") or "").strip():
        add("low", "no_type", "Sin tipo de producto: dificulta filtros y colecciones automáticas.")
    if not (p.get("collections") or {}).get("nodes"):
        add("high", "orphan", "No está en ninguna colección: solo se encuentra buscándolo.")

    handle = p.get("handle", "")
    words = set(handle.split("-"))
    foreign = sorted(words & FOREIGN_HANDLE_WORDS)
    if foreign:
        add("low", "foreign_handle", f"URL en otro idioma ({', '.join(foreign[:4])}). Cambiarla "
                                     "exige crear una redirección; hazlo solo en las más vistas.")
    if len(handle) > 75:
        add("medium", "long_handle", f"URL de {len(handle)} caracteres, parece importada.")

    for opt in p.get("options") or []:
        name = (opt.get("name") or "").lower()
        values = [str(v).lower() for v in opt.get("values") or []]
        untranslated = ([opt["name"]] if name in ENGLISH_OPTION_WORDS else []) + \
            [v for v in values if v in ENGLISH_OPTION_WORDS]
        if untranslated:
            add("medium", "english_option", f"Opciones sin traducir: {', '.join(untranslated[:4])}.")

    seo = p.get("seo") or {}
    if not (seo.get("description") or "").strip():
        add("low", "no_seo_description", "Sin meta descripción para Google.")
    elif len(seo["description"]) > 160:
        add("low", "seo_description_long", "Meta descripción de más de 160 caracteres.")

    text = _text(p.get("descriptionHtml", ""))
    lower = text.lower()
    if len(text) < 200:
        add("high", "thin_description", "Descripción muy corta: falta qué es, tejido, "
                                        "corte y cómo queda.")
    if out.niche == "mujer" and not any(w in lower for w in MATERIAL_WORDS):
        add("medium", "no_material", "No indica tejido o material (obligatorio en el etiquetado "
                                     "textil y clave para comprar online).")
    if out.niche == "mujer" and not any(w in lower for w in SIZE_WORDS):
        add("low", "no_size_help", "La descripción no orienta sobre la talla (la ficha puede "
                                   "mostrar la tabla de tallas de la app; compruébalo).")
    claims = [c for c in CLAIM_PATTERNS if c in lower]
    if claims:
        add("high", "claims", f"Afirmaciones que necesitan prueba o están reguladas "
                              f"({', '.join(claims)}): suavízalas o documenta la prueba.")

    profile = ((((p.get("variants") or {}).get("nodes") or [{}])[0]).get("deliveryProfile") or {}).get("name", "")
    if profile and "autods" in profile.lower():
        add("medium", "worldwide_shipping", f"Perfil de envío «{profile}» (resto del mundo): "
                                           "contradice «solo España y Francia».")
    return out


def audit_catalog(products: list[dict]) -> list[ProductAudit]:
    audits = [audit_product(p) for p in products]
    return sorted(audits, key=lambda a: (SEVERITY_ORDER.get(a.worst, 9), a.title))


def summary(audits: list[ProductAudit]) -> dict:
    by_code = Counter(f.code for a in audits for f in a.findings)
    by_niche = Counter(a.niche for a in audits)
    worst = Counter(a.worst for a in audits)
    return {"products": len(audits), "by_niche": dict(by_niche), "by_worst": dict(worst),
            "by_issue": dict(by_code.most_common())}


ISSUE_LABELS = {
    "no_tracking": "Venta sin control de stock",
    "compare_at": "Precio tachado (revisar legalidad)",
    "off_niche": "Producto fuera del nicho",
    "one_image": "Una sola foto",
    "orphan": "Sin colección",
    "thin_description": "Descripción muy corta",
    "claims": "Afirmaciones a revisar",
    "few_images": "Menos de 4 fotos",
    "fake_stock": "Stock poco creíble",
    "english_option": "Opciones sin traducir",
    "no_material": "Sin tejido/material",
    "no_size_help": "Sin ayuda de talla",
    "worldwide_shipping": "Envío al resto del mundo",
    "long_handle": "URL demasiado larga",
    "foreign_handle": "URL en otro idioma",
    "no_type": "Sin tipo de producto",
    "no_alt": "Foto sin texto alternativo",
    "no_seo_description": "Sin meta descripción",
    "seo_description_long": "Meta descripción larga",
}


def report_markdown(audits: list[ProductAudit]) -> str:
    s = summary(audits)
    lines = ["# Auditoría de catálogo", "",
             f"{s['products']} productos activos · " +
             " · ".join(f"{k}: {v}" for k, v in sorted(s["by_niche"].items())), "",
             "| Problema | Productos |", "|---|---:|"]
    for code, n in s["by_issue"].items():
        lines.append(f"| {ISSUE_LABELS.get(code, code)} | {n} |")
    lines += ["", "## Por producto (de más grave a menos)", ""]
    for a in audits:
        if not a.findings:
            continue
        lines.append(f"### {a.title}  ·  `{a.handle}`  ·  {a.worst}")
        for f in sorted(a.findings, key=lambda f: SEVERITY_ORDER[f.severity]):
            lines.append(f"- **{f.severity}** {f.message}")
        lines.append("")
    return "\n".join(lines)


def load_products(path) -> list[dict]:
    """A JSON file with a list of product nodes, or a raw GraphQL answer."""
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("data", data).get("products", {}).get("nodes", [])
    return data


def to_json(audits: list[ProductAudit]) -> str:
    return json.dumps([{**asdict(a), "worst": a.worst} for a in audits],
                      ensure_ascii=False, indent=1)


def _by_handle(products: list[dict]) -> dict[str, dict]:
    return {p.get("handle", ""): p for p in products}


def _common(value, other=None):
    """value restricted to the keys it shares with other, recursively."""
    if isinstance(value, dict) and isinstance(other, dict):
        return {k: _common(value[k], other[k]) for k in set(value) & set(other)}
    return value


def diff_catalog(before: list[dict], after: list[dict]) -> dict:
    """What changed between two exports of the same query: products added
    or removed, and for each product the top-level fields that differ.
    Used to prove a change touched only what it was meant to."""
    b, a = _by_handle(before), _by_handle(after)
    changed = {}
    for handle in sorted(set(b) & set(a)):
        # Only what both exports asked for: a field (or sub-field) present in
        # just one of them is a different query, not a change.
        fields = sorted(k for k in set(b[handle]) & set(a[handle])
                        if _common(b[handle][k], a[handle][k]) != _common(a[handle][k], b[handle][k]))
        if fields:
            changed[handle] = fields
    return {"added": sorted(set(a) - set(b)), "removed": sorted(set(b) - set(a)),
            "changed": changed, "unchanged": len(set(a) & set(b)) - len(changed)}


def sha256_manifest(paths) -> dict[str, str]:
    """name -> sha256 of each file, to make a backup verifiable later."""
    import hashlib
    from pathlib import Path
    return {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def add_parser(subparsers) -> None:
    sub = subparsers.add_parser(
        "shop", help="Read-only Shopify catalog audit (from a JSON export of products)")
    sub.add_argument("action", choices=("audit", "query", "diff", "fix", "verify", "plan"))
    sub.add_argument("target", nargs="?", default="",
                     help="audit/fix: the products JSON file; diff/verify: the BEFORE export")
    sub.add_argument("after", nargs="?", default="", help="diff/verify: the AFTER export")
    sub.add_argument("--json", action="store_true", help="audit: machine-readable output")
    sub.add_argument("--out", default="",
                     help="fix: where to write the metafieldsSet inputs (JSONL); plan: output folder")
    sub.add_argument("--skip", default="", help="plan: comma-separated handles already corrected")
    sub.add_argument("--accepted-payments", default="",
                     help="plan: payment icons the shop really accepts, comma-separated (default: leave icons)")
    sub.set_defaults(func=cmd_shop)


def cmd_shop(args) -> None:
    if args.action == "query":
        print("\n  Consulta de solo lectura para el conector de Shopify (pagina con after):\n")
        print(PRODUCTS_QUERY + "\n")
        return
    if not args.target:
        raise SystemExit("  Falta el archivo JSON de productos.")
    if args.action == "fix":
        _cmd_fix(args)
        return
    if args.action == "verify":
        _cmd_verify(args)
        return
    if args.action == "plan":
        _cmd_plan(args)
        return
    if args.action == "diff":
        if not args.after:
            raise SystemExit("  Falta la exportación de después.")
        d = diff_catalog(load_products(args.target), load_products(args.after))
        print(f"\n  Sin cambios: {d['unchanged']} · añadidos: {len(d['added'])} · "
              f"quitados: {len(d['removed'])} · cambiados: {len(d['changed'])}")
        for handle, fields in d["changed"].items():
            print(f"  ~ {handle}: {', '.join(fields)}")
        for handle in d["added"]:
            print(f"  + {handle}")
        for handle in d["removed"]:
            print(f"  - {handle}")
        print()
        return
    audits = audit_catalog(load_products(args.target))
    print(to_json(audits) if args.json else report_markdown(audits))


def load_product(path) -> dict:
    """One product node, from a file holding the node itself or a raw
    GraphQL answer ({"data": {"product": ...}})."""
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict) and "data" in data:
        data = data["data"].get("product") or {}
    return data


def _cmd_fix(args) -> None:
    """Prepare (never apply) the content corrections for a catalog export."""
    from harvey.shopfix import fix_catalog, fix_description, report_markdown as fix_report
    products = load_products(args.target)
    inputs, report = fix_catalog(products)
    descriptions = []
    for p in products:
        new, changes = fix_description(p.get("descriptionHtml") or "")
        if changes:
            descriptions.append({"id": p.get("id"), "handle": p.get("handle"),
                                 "descriptionHtml": new, "cambios": changes})
    print("\n" + fix_report(report))
    print(f"\n{len(descriptions)} descripciones cambiarían.")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.writelines(json.dumps({"input": i}, ensure_ascii=False) + "\n" for i in inputs)
        desc_path = args.out + ".descripciones.json"
        with open(desc_path, "w", encoding="utf-8") as f:
            json.dump(descriptions, f, ensure_ascii=False, indent=1)
        print(f"\n  Preparado, sin aplicar: {args.out} y {desc_path}")
    print("  Nada se ha escrito en Shopify. Revisa y aprueba antes de aplicarlo.\n")


def _load_any(path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, list) or (isinstance(data, dict) and "products" in data.get("data", data)):
        return load_products(path)
    return load_product(path)


def _cmd_plan(args) -> None:
    """Write the batches, their undo and the manifest. Applies nothing."""
    from pathlib import Path
    from harvey.shopfix import plan_batches
    if not args.out:
        raise SystemExit("  Indica la carpeta de salida con --out.")
    accepted = set(filter(None, args.accepted_payments.split(","))) or None
    plan = plan_batches(load_products(args.target), skip=set(filter(None, args.skip.split(","))),
                        accepted_payments=accepted)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for i, (batch, undo) in enumerate(zip(plan["lotes"], plan["restaurar"]), 1):
        (out / f"lote_{i:02d}.json").write_text(
            json.dumps({"metafields": batch}, ensure_ascii=False), encoding="utf-8")
        (out / f"restaurar_{i:02d}.json").write_text(
            json.dumps({"metafields": undo}, ensure_ascii=False), encoding="utf-8")
    from harvey.shopfix import fix_description
    descriptions = []
    for p in load_products(args.target):
        old = p.get("descriptionHtml") or ""
        new, changes = fix_description(old)
        if changes:
            descriptions.append({"id": p.get("id"), "handle": p.get("handle"), "antes": old,
                                 "despues": new, "cambios": changes})
    (out / "descripciones.json").write_text(json.dumps(descriptions, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    (out / "manifiesto.json").write_text(json.dumps(plan["manifiesto"], ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    sums = sha256_manifest(sorted(out.glob("*.json")))
    (out / "SHA256SUMS").write_text("".join(f"{v}  {k}\n" for k, v in sums.items()), encoding="utf-8")
    print(f"\n  {len(plan['manifiesto'])} fichas en {len(plan['lotes'])} lotes y "
          f"{len(descriptions)} descripciones · carpeta {out}")
    if not plan["con_compare_digest"]:
        print("  Aviso: la exportación no trae compareDigest; vuelve a exportar con él antes de aplicar.")
    print("  Nada se ha escrito en Shopify.\n")


def _cmd_verify(args) -> None:
    """Compare one product, or a whole export, before and after."""
    from harvey.shopfix import integrity_report, verify_catalog
    if not args.after:
        raise SystemExit("  Falta la exportación de después.")
    before, after = _load_any(args.target), _load_any(args.after)
    if isinstance(before, list):
        r = verify_catalog(before, after if isinstance(after, list) else [after])
        print(f"\n  Fichas correctas: {r['ok']} · con problemas: {len(r['fallos'])}")
        for handle, bad in r["fallos"].items():
            print(f"  MAL  {handle}: {', '.join(bad)}")
        print()
        if r["fallos"]:
            raise SystemExit(1)
        return
    rows = integrity_report(before, after)
    print()
    for label, ok in rows:
        print(f"  {'OK ' if ok else 'MAL'}  {label}")
    bad = [label for label, ok in rows if not ok]
    print("\n  Todo en orden.\n" if not bad else f"\n  Revisar: {', '.join(bad)}\n")
    if bad:
        raise SystemExit(1)
