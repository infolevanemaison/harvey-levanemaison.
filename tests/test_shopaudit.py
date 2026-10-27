"""The read-only catalog audit. Fictional products only."""

import json
from types import SimpleNamespace

from harvey.shopaudit import audit_catalog, audit_product, cmd_shop, niche_of, summary


def product(**kw):
    base = {
        "title": "Vestido Prueba Midi", "handle": "vestido-prueba-midi", "productType": "Vestido",
        "totalInventory": 40, "tracksInventory": True, "mediaCount": {"count": 6},
        "featuredMedia": {"alt": "Vestido de prueba"},
        "seo": {"title": "Vestido", "description": "Un vestido de prueba."},
        "options": [{"name": "Color", "values": ["Negro"]}, {"name": "Talla", "values": ["M"]}],
        "descriptionHtml": "<p>" + "Vestido midi de algodón con corte evasé. " * 6 +
                           "Consulta la guía de tallas.</p>",
        "collections": {"nodes": [{"handle": "vestidos"}]},
        "priceRangeV2": {"minVariantPrice": {"amount": "49.95"}},
        "compareAtPriceRange": None,
        "variants": {"nodes": [{"deliveryProfile": {"name": "Perfil general"}}]},
    }
    base.update(kw)
    return base


def codes(p):
    return {f.code for f in audit_product(p).findings}


def test_a_complete_product_is_clean():
    assert codes(product()) == set()


def test_off_niche_products_are_grouped():
    assert niche_of(product(title="Lámpara Prueba")) == "hogar"
    assert niche_of(product(title="Chaqueta Prueba", productType="Chaquetas hombre")) == "hombre"
    assert niche_of(product(title="Leggings deportivos prueba")) == "deporte"


def test_selling_without_stock_and_inflated_compare_at_are_critical():
    a = audit_product(product(tracksInventory=False,
                              compareAtPriceRange={"maxVariantCompareAtPrice": {"amount": "119.99"}}))
    assert a.worst == "critical"
    assert {"no_tracking", "compare_at"} <= {f.code for f in a.findings}


def test_images_options_and_text_are_checked():
    found = codes(product(mediaCount={"count": 1}, descriptionHtml="<p>Corto.</p>",
                          options=[{"name": "Size", "values": ["S", "light gray"]}],
                          handle="robe-courte-prueba", productType="",
                          collections={"nodes": []}))
    assert {"one_image", "thin_description", "english_option", "foreign_handle",
            "no_type", "orphan", "no_material"} <= found


def test_spanish_color_option_is_not_untranslated():
    assert "english_option" not in codes(product())


def test_regulated_claims_are_flagged():
    assert "claims" in codes(product(descriptionHtml="<p>" + "Faja con efecto alisante. " * 10 + "</p>"))


def test_worldwide_shipping_profile_is_flagged():
    p = product(variants={"nodes": [{"deliveryProfile": {"name": "AutoDS Free Shipping"}}]})
    assert "worldwide_shipping" in codes(p)


def test_catalog_is_sorted_worst_first_and_summarised(tmp_path, capsys):
    items = [product(), product(title="Otro", tracksInventory=False)]
    audits = audit_catalog(items)
    assert audits[0].title == "Otro"
    assert summary(audits)["by_worst"] == {"critical": 1, "ok": 1}
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"data": {"products": {"nodes": items}}}), encoding="utf-8")
    cmd_shop(SimpleNamespace(action="audit", target=str(path), json=False))
    assert "Venta sin control de stock" in capsys.readouterr().out


def test_diff_reports_only_what_changed(tmp_path, capsys):
    from harvey.shopaudit import diff_catalog, sha256_manifest
    before = [product(handle="a"), product(handle="b", templateSuffix="buildora-x"), product(handle="c")]
    after = [product(handle="a"), product(handle="b", templateSuffix="levane"), product(handle="d")]
    d = diff_catalog(before, after)
    assert d == {"added": ["d"], "removed": ["c"], "changed": {"b": ["templateSuffix"]}, "unchanged": 1}
    f = tmp_path / "x.json"
    f.write_text("{}", encoding="utf-8")
    assert sha256_manifest([f])["x.json"] == \
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(before), encoding="utf-8")
    a.write_text(json.dumps(after), encoding="utf-8")
    cmd_shop(SimpleNamespace(action="diff", target=str(b), after=str(a), json=False))
    assert "~ b: templateSuffix" in capsys.readouterr().out


def test_diff_ignores_fields_only_one_export_asked_for():
    from harvey.shopaudit import diff_catalog
    before = [{"handle": "a", "m": {"id": "1", "value": "x"}, "extra": 1}]
    after = [{"handle": "a", "m": {"value": "x", "updatedAt": "t"}, "status": "ACTIVE"}]
    assert diff_catalog(before, after)["changed"] == {}
    after[0]["m"]["value"] = "y"
    assert diff_catalog(before, after)["changed"] == {"a": ["m"]}
