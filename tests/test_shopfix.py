"""Content corrections are prepared by explicit rules and reported."""

import json

from harvey.shopfix import fix_catalog, fix_sections, integrity_report, report_markdown


def sections(**hero):
    base = {"hero": {"informacion": [{"titulo_html": "Envío y entrega", "contenido_html":
            "Envío gratis. Preparamos tu pedido en 24-48 horas laborables y la entrega tarda "
            "entre 7 y 15 días. Recibirás el número de seguimiento por correo."}],
            "oferta_cantidad_html": '<span class="pl-vol-tag">Para probar</span>'
                                    '<span class="pl-vol-tag">Más popular</span>'
                                    '<span class="pl-vol-tag">Mejor precio</span>',
            "pago": {"proveedores": ["visa", "paypal", "applepay"]}},
            "faq": {"preguntas": [{"respuesta_html": "la entrega tarda entre 7 y 15 días en España"}]}}
    base["hero"].update(hero)
    return json.dumps(base, ensure_ascii=False)


def test_only_the_listed_sentences_change():
    new, fix = fix_sections("x", sections())
    d = json.loads(new)
    info = d["hero"]["informacion"][0]["contenido_html"]
    assert "entre 8 y 12 días laborables desde el envío" in info
    assert "cuando el transportista lo ofrezca" in info
    assert "Más popular" not in d["hero"]["oferta_cantidad_html"]
    assert "Mejor precio" in d["hero"]["oferta_cantidad_html"]   # true by arithmetic
    assert "8 y 12" in d["faq"]["preguntas"][0]["respuesta_html"]
    assert d["hero"]["pago"]["proveedores"] == ["visa", "paypal", "applepay"]  # untouched by default
    assert dict(fix.changes)["plazo de la política de envíos"] == 2


def test_payment_icons_follow_what_is_accepted():
    new, fix = fix_sections("x", sections(), accepted_payments={"visa", "applepay"})
    assert json.loads(new)["hero"]["pago"]["proveedores"] == ["visa", "applepay"]
    assert fix.removed_payment_icons == ["paypal"]


def test_clean_content_is_left_byte_for_byte():
    raw = json.dumps({"hero": {"informacion": [{"contenido_html": "Envío gratis."}]}})
    new, fix = fix_sections("x", raw)
    assert new == raw and not fix.changes


def test_catalog_builds_inputs_only_for_changed_products():
    products = [{"id": "gid://shopify/Product/1", "handle": "a", "m": {"value": sections()}},
                {"id": "gid://shopify/Product/2", "handle": "b",
                 "m": {"value": json.dumps({"hero": {}})}}]
    inputs, report = fix_catalog(products)
    assert [i["ownerId"] for i in inputs] == ["gid://shopify/Product/1"]
    assert inputs[0]["type"] == "json" and inputs[0]["key"] == "sections"
    assert "1 fichas cambiarían" in report_markdown(report)


def test_every_tracking_and_delivery_variant_is_covered():
    raw = json.dumps({"faq": {"preguntas": [{"respuesta_html":
          "Preparamos tu pedido en 24-48 horas laborables y la entrega tarda entre 7 y 15 días "
          "en España y Francia. El envío es gratis y recibirás el número de seguimiento por correo."}]}},
          ensure_ascii=False)
    new, _ = fix_sections("x", raw)
    text = json.loads(new)["faq"]["preguntas"][0]["respuesta_html"]
    assert "la entrega a España y Francia tarda entre 8 y 12 días laborables desde el envío." in text
    assert "cuando el transportista lo ofrezca, recibirás" in text
    assert "7 y 15" not in text


def test_rules_are_idempotent():
    once, _ = fix_sections("x", sections())
    twice, fix = fix_sections("x", once)
    assert twice == once and not fix.changes


def node(raw, **over):
    p = {"status": "ACTIVE", "templateSuffix": "levane", "title": "Vestido de ejemplo",
         "descriptionHtml": "<p>Ejemplo</p>", "options": [{"name": "Talla", "values": ["S", "M"]}],
         "media": {"nodes": [{"id": "m1"}, {"id": "m2"}]},
         "variants": {"nodes": [{"id": "v1", "price": "49.95", "compareAtPrice": None,
                                 "availableForSale": True}]},
         "metafields": {"nodes": [{"namespace": "shopipi", "key": "sections", "value": raw}]}}
    p.update(over)
    return p


def with_buy_button(raw):
    d = json.loads(raw)
    d["hero"].update(cta_add="Añadir al carrito", ocultar_compra=False)
    return json.dumps(d, ensure_ascii=False)


def test_integrity_passes_when_only_the_rules_changed():
    before = with_buy_button(sections())
    after, _ = fix_sections("x", before)
    rows = integrity_report(node(before), node(after))
    assert all(ok for _, ok in rows), rows


def test_integrity_catches_a_lost_photo_or_an_extra_edit():
    before = with_buy_button(sections())
    after, _ = fix_sections("x", before)
    rows = dict(integrity_report(node(before), node(after, media={"nodes": [{"id": "m1"}]})))
    assert rows["fotos"] is False
    tampered = json.loads(after)
    tampered["hero"]["ocultar_compra"] = True
    rows = dict(integrity_report(node(before), node(json.dumps(tampered, ensure_ascii=False))))
    assert rows["contenido: solo cambian las frases de las reglas"] is False
    assert rows["botón «Añadir al carrito» visible"] is False


def test_catalog_reads_the_metafields_list_shape_too():
    inputs, _ = fix_catalog([{"id": "gid://shopify/Product/3", **node(sections())}])
    assert [i["ownerId"] for i in inputs] == ["gid://shopify/Product/3"]


def test_description_claims_are_toned_down_and_nothing_else():
    from harvey.shopfix import fix_description
    html = ("<h3>Modelo™ — ligero</h3><p><strong>Por qué esta prenda encanta tanto:</strong></p>"
            "<ul><li>✓ Largo midi favorecedor para todo tipo de cuerpos</li>"
            "<li>✓ Perfecto para el día a día</li></ul>")
    new, changes = fix_description(html)
    assert "™" not in new and "encanta" not in new and "todo tipo de cuerpos" not in new
    assert "Lo que la hace especial:" in new and "Largo midi fácil de llevar" in new
    assert "Perfecto para el día a día" in new          # ordinary praise stays
    assert len(changes) == 3
    assert fix_description(new) == (new, [])
