# Medición de resultados por creadora

Objetivo: saber, por cada creadora, cuántas visitas, pedidos e ingresos
trae y si la colaboración ha sido rentable. Todo con consultas de **solo
lectura** a Shopify. Nada de esto crea descuentos ni cambia la tienda.

## 1. Enlaces UTM: una convención para todo

| Parámetro | Valor | Ejemplo |
|---|---|---|
| `utm_source` | plataforma | `instagram` |
| `utm_medium` | siempre `influencer` | `influencer` |
| `utm_campaign` | `lvm_<país>_<aaaamm>` | `lvm_es_202611` |
| `utm_content` | usuario de la creadora | `estilo_sereno` |

```bash
harvey creators link <id> --month 2026-11 --path collections/vestidos
```

El enlace apunta a una **colección o producto concreto**, nunca a la página
de inicio, para que la visita empiece donde la llevó el contenido.

## 2. Códigos únicos

Formato propuesto: `LVM-NOMBRE<descuento>`, por ejemplo `LVM-CARMEN10`.
Harvey **solo lo propone**. Lo creas tú en Shopify (Descuentos) cuando hayas
aprobado las condiciones. El código mide también las ventas que no pasan por
el enlace (quien lo ve en un vídeo y compra días después).

## 3. Consultas (Shopify, solo lectura)

```bash
harvey creators queries --month 2026-11
```

Devuelve dos consultas ShopifyQL que Claude ejecuta con el conector de
Shopify: visitas, carritos, pagos y compras por `utm_source` y
`utm_content` de la campaña, y pedidos y ventas por código de descuento.
Los nombres de columna (`utm_campaign`, `utm_content`, `discount_code`) están
comprobados contra la API de la tienda.

## 4. Informe de rentabilidad

Con un CSV de resultados (`handle,sessions,orders,net_sales,gift_cost,fee`):

```bash
harvey creators report resultados-2026-11.csv --month 2026-11
```

Por creadora calcula:

- **Ventas netas** y **comisión** (si hay una aprobada);
- **Margen bruto** de sus ventas (`creators.economics.gross_margin_pct`);
- **Coste total**: comisión + prendas enviadas (con envío) + tarifa;
- **Contribución** = margen − coste total;
- **ROI** = contribución ÷ (prendas + tarifa);
- **Coste por pedido** y **conversión** de sus visitas.

Las creadoras con contribución negativa aparecen marcadas: «No renovar sin
revisar».

### Punto de equilibrio antes de colaborar

`break_even_orders` (en `harvey/creators/tracking.py`) dice cuántos pedidos
necesita traer una creadora para cubrir la prenda y la tarifa, según tu
margen, el descuento y la comisión. Si el descuento más la comisión superan
tu margen, cada venta pierde dinero y lo indica.

## 5. Antes de medir, comprueba que la tienda vende

Si la tienda casi no convierte, la medición solo confirmará que no hay
ventas. Las mejoras de conversión van primero (ver el análisis de
conversión que se entrega aparte, fuera del repositorio).
