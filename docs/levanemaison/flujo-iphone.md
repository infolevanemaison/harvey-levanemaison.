# Flujo de trabajo desde el iPhone

Todo se hace hablando con Claude en la app de Claude (pestaña Code, sobre
este repositorio) y revisando el resultado en Gmail. Harvey **no envía
nada**: cada mensaje acaba como borrador en tu Gmail y lo envías tú.

## Una vez: preparar la sesión

Pídele a Claude:

> Activa la configuración de Levanemaison.

Claude ejecuta `cp levanemaison/harvey.levanemaison.example.yaml harvey.local.yaml`.
Ese archivo no se sube a GitHub. Completa con Claude los campos `COMPLETAR`
(tu nombre, la razón social y la dirección para el pie de los mensajes, y tu margen).

> **Importante:** el contenedor de Claude Code se borra al cerrar la sesión.
> La lista de creadoras (`data/creators.db`) vive en el contenedor y **no se
> sube a GitHub** porque contiene datos personales. Para no perderla, pide al
> final de cada sesión «exporta las creadoras a un CSV» y guárdalo en tu
> iCloud o Drive, o vuelve a importar tu CSV al empezar la siguiente.

## Cada ronda de creadoras

| Paso | Qué dices a Claude | Qué pasa | Quién decide |
|---|---|---|---|
| 1 | «Importa este CSV de creadoras» (lo adjuntas o pegas) | `harvey creators import` puntúa a cada una | — |
| 2 | «Enséñame la lista» | Puntuación /100 con motivos y alertas | Tú lees |
| 3 | «Apruebo a @usuario» | `harvey creators approve <id>` | **Tú** |
| 4 | «Redacta una propuesta para @usuario» | Propuesta en su idioma, revisada por el código | — |
| 5 | «Apruebo la propuesta» o «cámbiala así…» | `approve-proposal` | **Tú** |
| 6 | «Crea el borrador en Gmail» | Borrador en tu Gmail, nunca se envía | — |
| 7 | Abres Gmail en el iPhone → Borradores → revisas → **Enviar** | El único envío real | **Tú** |
| 8 | «Ha respondido así: …» | Claude propone una respuesta en borrador | Tú envías |
| 9 | «Ya lo he enviado» | `harvey creators sent <id>`: desde aquí cuentan los plazos | Tú |
| 10 | «¿Qué tengo pendiente?» | `harvey creators todo`: recordatorios, respuestas, envíos de prendas, etiquetado | Tú decides |

**Respuestas:** pega su mensaje («Ha respondido esto: …»). Claude ejecuta
`harvey creators reply <id> --text "…"`:
- si pide la baja, sus datos se borran al momento y no se le contesta;
- si menciona abogados, denuncias, AEPD o CNIL, no se sugiere respuesta: la
  atiendes tú;
- en otro caso se prepara una respuesta en su idioma que espera tu aprobación
  y, aprobada, va como borrador **dentro del mismo hilo** de Gmail.

**Resumen semanal:** «Dame el resumen de colaboraciones». Claude ejecuta
`harvey creators digest`: creadoras por estado, propuestas pendientes,
colaboraciones, tareas del día y resultados.

**Registrar resultados:** «Anota que @usuario trajo 80 visitas, 2 pedidos y
99,90 € en noviembre». Claude ejecuta `harvey creators result <id> --month
2026-11 sessions=80 orders=2 net_sales=99.90`.

**Revisar el correo de golpe:** «Mira en Gmail si han respondido las
creadoras». Claude busca en tu Gmail con el conector, guarda los mensajes
en un JSON fuera del repositorio y ejecuta `harvey creators inbox
mensajes.json`. Cada mensaje se procesa una sola vez y se ignoran los
remitentes que no son creadoras de tu lista.

**Recordatorio:** como máximo uno, a los 7 días sin respuesta
(`harvey creators followup <id>`). A los 21 días se propone cerrarla, sin
volver a escribir.

**Colaboraciones acordadas:** `harvey creators collab <id> --terms "…" --due AAAA-MM-DD`
y después `collab-set <id> status=shipped shipped_on=…`,
`post_urls=… status=published` y `labelled_as_ad=1`. `todo` avisa si la
publicación se retrasa o no está etiquetada como publicidad.

Si una creadora dice «baja», «no me escribas» o «stop», o lo pide de
cualquier otra forma: «@usuario se da de baja». Claude ejecuta
`harvey creators forget <id>`, que borra sus datos y la deja marcada para no
volver a añadirla.

## Qué rellenar en el CSV (solo datos públicos o que ella te dé)

`handle, platform, display_name, country, language, profile_url, followers,
avg_likes, avg_comments, avg_views, posts_last_30d, sponsored_posts_last_30d,
follower_growth_30d_pct, audience_female_pct, audience_35_65_pct,
audience_target_country_pct, comment_quality (1-5), content_notes,
pro_contact_email, pro_contact_source, quoted_fee_eur`

- **Interacción:** media de likes y comentarios de sus últimas 9 a 12
  publicaciones, contada a mano en su perfil.
- **Audiencia (sexo, edad, país):** solo si ella te da su media kit o
  capturas de sus estadísticas. Si no, déjalo vacío: Harvey lo marcará como
  pendiente en vez de inventarlo.
- **Contacto:** solo el email profesional que ella publica para
  colaboraciones, y la URL donde aparece. Sin eso, Harvey no prepara email.
- Ejemplo con datos ficticios: `levanemaison/creadoras_ejemplo_ficticias.csv`.

## Condiciones (regalo, comisión, descuento)

Mientras `creators.offer.approved` sea `false`, el código **bloquea**
cualquier propuesta que mencione regalos, prendas gratis, comisiones,
descuentos, códigos o pagos, en español, francés o inglés. Cuando decidas
las condiciones, dile a Claude:

> Apruebo estas condiciones: prenda de hasta X €, comisión del Y %, descuento del Z %.

A partir de ahí, las propuestas solo podrán usar esas cifras exactas.
