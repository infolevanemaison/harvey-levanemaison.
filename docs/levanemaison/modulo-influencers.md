# Módulo de creadoras de contenido: investigación y diseño

Harvey busca **empresas** (por su web, su ficha de Google o un directorio) y
el email de quien decide. No sabe nada de Instagram, TikTok ni YouTube. Este
documento recoge qué haría falta para añadir creadoras de contenido, con
canales autorizados y aprobación humana en cada contacto.

> Precios, límites y disponibilidad por país cambian a menudo. Todo lo
> marcado *(verificar)* debe comprobarse en la web oficial antes de pagar o
> integrar nada.

## 1. Canales para encontrar creadoras, de más a menos recomendable

### A. Que ellas vengan a ti (entrante)

- **Shopify Collabs** (app oficial de Shopify): las creadoras solicitan
  colaborar, se gestionan regalos, enlaces de afiliada y comisiones desde
  Shopify. Sin coste de la app para la tienda *(verificar disponibilidad en
  España y condiciones)*. Es el canal más limpio legalmente: la creadora
  inicia el contacto.
- **Página "Colabora con nosotras"** en levanemaison.com con un formulario
  y consentimiento explícito. Cero riesgo LSSI.
- **Mercados de marcas y creadoras** como TikTok One/Creator Marketplace o
  el de Instagram *(verificar disponibilidad para marcas en ES/FR)*.

### B. Búsqueda por APIs oficiales (gratis o casi)

| Fuente | Qué da | Limitaciones |
|---|---|---|
| **YouTube Data API v3** | Buscar canales por palabra clave y país, suscriptores, vídeos | Cuota diaria gratuita limitada *(verificar)*; YouTube tiene menos creadoras 40+ que Instagram |
| **Instagram Graph API: Business Discovery** | Seguidores, número de publicaciones y métricas públicas de cuentas profesionales **dado su nombre de usuario** | Necesita una cuenta de Instagram profesional propia conectada a una app de Meta; no busca por tema; solo cuentas Business/Creator |
| **Instagram Graph API: búsqueda por hashtag** | Publicaciones destacadas o recientes de un hashtag (#modamadura, #over50style…) | Límite de hashtags distintos por semana *(verificar)*; no siempre devuelve la autora |

Combinación propuesta: hashtags y búsquedas dan **candidatas**, Business
Discovery da **métricas**, y una persona valida cada ficha.

### C. Herramientas de pago especializadas

Heepsy, Modash, Kolsquare, Hivency, Upfluence y similares tienen buscadores
con filtros de edad y país de la audiencia, y datos ya tratados según el
RGPD por el proveedor. Coste habitual de decenas a cientos de euros al mes
*(verificar)*. Solo merecen la pena cuando el canal haya demostrado ventas.

### D. Lo que NO haremos

- Extraer datos de Instagram, TikTok o LinkedIn con robots: lo prohíben sus
  condiciones y es un tratamiento de datos difícil de justificar.
- Escribir a direcciones personales encontradas fuera del canal profesional
  que la creadora publica.
- Mensajes directos automatizados.

## 2. Diseño técnico propuesto

Encaja en la arquitectura de Harvey sin romperla:

```
harvey/collectors/creators.py      CreatorProvider (como DiscoveryProvider)
  ├─ ManualCSV          lista revisada a mano (primera versión, 0 €)
  ├─ YouTubeChannels    YouTube Data API v3
  └─ InstagramBusiness  Business Discovery (con tu cuenta profesional)

state.py   tablas nuevas:
  creators(id, platform, handle, profile_url, country, language,
           followers, engagement_rate, audience_fit, niche_tags,
           pro_contact, pro_contact_source_url, legal_basis,
           status, created_at, delete_after)
  collaborations(id, creator_id, offer, product_ids, gift_cost,
           discount_code, utm_campaign, post_urls, labelled_as_ad,
           orders, revenue, cost_per_order)

signals.py  señales nuevas (propuestas, nunca activas por defecto):
  FOLLOWERS, ENGAGEMENT_RATE, AUDIENCE_FIT, PRO_CONTACT_PUBLISHED,
  POSTS_FASHION_40_PLUS
```

Estados de una creadora:

```
candidata → revisada (humano) → aprobada para contacto (humano)
→ borrador preparado → enviado (humano, desde Gmail)
→ respondió → en negociación (humano) → prenda enviada
→ publicado (etiquetado como publicidad) → medido
                                   ↘ baja / descartada (para siempre)
```

Reglas en código (no en el prompt):

- Solo se redacta para creadoras **aprobadas por una persona** y con
  `pro_contact_published` (email profesional publicado por ella, con la URL
  donde aparece).
- `do_not_contact` y las bajas se aplican también a creadoras.
- Borrado automático de candidatas no contactadas a los 6 meses y de las
  que no respondieron a los 12 *(plazos a validar)*.
- Puntuación transparente: encaje de audiencia, engagement y coherencia de
  estilo, nunca solo seguidores.

### Modo "solo borradores" (fase 3)

Hoy Harvey envía desde Gmail cuando apruebas un correo en la Bandeja de
salida. Para trabajar desde el iPhone, proponemos un modo en el que aprobar
**crea un borrador en tu Gmail** en lugar de enviarlo. Tú lo abres en la app
de Gmail, lo retocas y pulsas enviar. Cambio acotado en
`harvey/integrations/gmail.py` y `harvey/agents/sender.py`, con pruebas.

### Medición (fase 5)

- Un código de descuento y un enlace con UTM por creadora (crearlos en
  Shopify exige tu aprobación).
- Informe semanal con ShopifyQL de solo lectura: sesiones por fuente y
  campaña, pedidos y ventas por código, coste por pedido. Sin datos
  personales de clientas.

## 3. Hallazgos de la tienda que afectan al plan

Lectura agregada de Shopify (sin datos de clientas). Las cifras concretas se
comentaron en la conversación y no se guardan en el repositorio.

- El catálogo mezcla moda femenina con **ropa de hombre y lámparas
  decorativas**. Para creadoras de moda 40+, conviene dirigir el tráfico a
  colecciones femeninas concretas (vestidos, blazers, conjuntos, calzado
  cómodo).
- El tráfico que llega desde redes sociales **apenas convierte**. Antes de
  invertir en creadoras hay que medir bien (UTM y códigos) y revisar la
  página de destino de móvil.
- Algunos productos muestran inventarios muy altos o a cero, lo que sugiere
  inventario sin seguimiento: hay que confirmar plazos de entrega antes de
  regalar prendas.

## Qué falta

**Decisiones tuyas**

1. Oferta para creadoras: prenda regalada (coste máximo por creadora),
   comisión por venta (%), descuento para su comunidad (%), tarifa sí/no.
2. Datos del remitente para el pie: razón social, NIF y dirección (LSSI).
3. Buzón de envío: dirección en un dominio secundario o en el principal
   (para colaboraciones uno a uno, el principal es aceptable con volúmenes
   muy bajos).
4. Política de privacidad de la web: añadir el tratamiento de datos de
   creadoras (ver `cumplimiento-es-fr.md`).
5. Si quieres probar Shopify Collabs como canal principal entrante.

**Desarrollo (con tu aprobación, fase a fase)**

1. Fase 3: modo solo borradores en Gmail.
2. Fase 4: `creators.py` con `ManualCSV` primero, luego YouTube e Instagram
   Business Discovery.
3. Fase 5: informe semanal de resultados desde Shopify.
4. Plantilla de acuerdo de colaboración (con etiquetado de publicidad) para
   revisar con un asesor.

**Servicios externos (ninguno es necesario para empezar)**

| Servicio | Para qué | Coste aproximado |
|---|---|---|
| Gmail (ya lo tienes) | Borradores y respuestas | 0 € |
| Reoon u otro verificador | Comprobar que un email profesional existe | Plan gratuito *(verificar)* |
| YouTube Data API | Búsqueda de canales | 0 € dentro de la cuota |
| Meta for Developers + Instagram profesional | Business Discovery | 0 € |
| Shopify Collabs | Programa de creadoras entrante | 0 € de app *(verificar)* |
| Herramienta de búsqueda de pago | Solo si el canal funciona | Decenas a cientos €/mes |
