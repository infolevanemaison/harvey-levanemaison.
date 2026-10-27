"""Content corrections are prepared by explicit rules and reported."""

import json

from harvey.shopfix import fix_catalog, fix_sections, report_markdown


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
