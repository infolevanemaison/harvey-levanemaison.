# Harvey para Levanemaison

Adaptación de Harvey a una tienda española de moda femenina (mujeres de 35 a
65 años) para buscar y gestionar **colaboraciones con creadoras de
contenido**, primero en España y después en Francia.

Principio que no cambia: **ninguna persona recibe nada sin aprobación
humana**. Harvey prepara, propone y mide; una persona decide y envía.

## Estado por fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Auditoría del código y plan | Hecha |
| 2 | Idioma ES/FR, bajas, filtro, geografía, configuración y pruebas | Hecha (rama `levanemaison/fase2-es-fr`, sin fusionar) |
| 3 | Gmail solo borradores + módulo de creadoras + medición | **Hecha en la rama `levanemaison/fase3-borradores`** (sin fusionar) |
| 4 | Auditoría de tienda (`harvey shop audit`), cambios recomendados, seguimiento de colaboraciones y respuestas | **Hecha en la rama `levanemaison/fase4-auditoria`** (sin fusionar). Falta la revisión visual (dominio bloqueado) |
| 4b | Búsqueda de creadoras por APIs oficiales (YouTube, Instagram Business Discovery) | Pendiente; hoy la lista se rellena a mano |
| 5 | Informe semanal automático desde Shopify | Consultas listas; falta programarlo (requiere tu autorización) |
| 6 | Boutiques (mayorista o depósito), solo si los márgenes lo permiten | En espera |

## Qué añade la fase 4

- `harvey shop audit productos.json`: auditoría de catálogo de solo lectura
  (fotos, stock, precios tachados, nicho, tejidos, opciones sin traducir,
  afirmaciones reguladas, envío) a partir de la consulta `harvey shop query`
  ejecutada con el conector de Shopify.
- [`cambios-tienda.md`](cambios-tienda.md): textos y estructuras listos para
  aplicar (aviso legal, envíos, devoluciones, menú, portada, fichas, checkout).
- Creadoras: `todo` (tareas del día), `sent`, un único `followup`, `reply`
  con bajas y temas legales resueltos por reglas, y colaboraciones con
  control del etiquetado de publicidad.

## Qué añade la fase 3

- **Gmail solo borradores** (`channels.email.draft_only: true`): aprobar un
  correo lo guarda como borrador en tu Gmail. El proveedor de Gmail se niega
  a enviar mientras el modo esté activo, aunque otra parte del código lo
  intentara.
- **Módulo de creadoras** (`harvey/creators/`, comando `harvey creators`):
  importación desde CSV, puntuación explicable (audiencia, interacción,
  autenticidad, coste), aprobación humana, propuestas en español o francés
  revisadas por código, borrador en Gmail, exportación para no perder datos
  entre sesiones y borrado a petición.
- **Condiciones bloqueadas**: sin tu aprobación (`creators.offer.approved`),
  ninguna propuesta puede mencionar regalos, comisiones, descuentos, códigos
  ni pagos.
- **Medición**: enlaces UTM, códigos propuestos, consultas ShopifyQL de solo
  lectura e informe de rentabilidad por creadora. Ver [`medicion.md`](medicion.md).
- **Uso desde el iPhone**: [`flujo-iphone.md`](flujo-iphone.md).

## Qué cambió en la fase 2

- `harvey/locales.py` (nuevo): idioma de salida (`en`, `es`, `fr`), país,
  tratamiento (tú/usted; vous en francés), `Accept-Language`, códigos de
  país de DataForSEO, línea de baja por idioma e instrucciones de redacción.
- `harvey/config.py`: sección `locale:`; la línea de baja admite «Responde
  "baja"», «Répondez "stop"», etc., y el pie se escribe en el idioma elegido.
- `harvey/agents/handler.py`: reconoce bajas en español y francés (con y
  sin tildes: «dadme de baja», «no me escribáis», «désinscrivez-moi», «non
  merci», «baja», «stop»…) sin confundir «estoy de baja» (baja médica).
  Amenazas legales (AEPD, CNIL, abogado, denuncia, mise en demeure…) pasan a
  revisión humana sin respuesta automática. Las respuestas se escriben en
  el idioma de la persona.
- `harvey/gate.py`: frases de spam y de "texto de IA" en español y francés.
- `harvey/agents/writer.py`: instrucciones para escribir de forma nativa en
  español de España o francés de Francia.
- `harvey/agents/scout.py` y `harvey/collectors/discover.py`: idioma y país
  en las búsquedas (Accept-Language, DataForSEO, Serper `gl`/`hl`).
- `skills/influencer_partnerships.md` (nuevo): cómo proponer y gestionar
  colaboraciones, incluido el etiquetado obligatorio de publicidad.
- `levanemaison/harvey.levanemaison.example.yaml` (nuevo): configuración
  con valores seguros (aprobación obligatoria, 10 envíos al día como
  máximo, LinkedIn apagado, horario Europe/Madrid).
- Pruebas nuevas: `tests/test_locales_es_fr.py`, `tests/test_levanemaison_config.py`.

Con `locale.language: en` (el valor por defecto) Harvey se comporta igual
que antes.

## Usarlo solo con un iPhone

No necesitas ordenador. Todo pasa por tres apps:

1. **App de Claude → Code**: abre una sesión sobre el repositorio
   `harvey-levanemaison.`. Claude trabaja en un contenedor en la nube con
   el código, ejecuta las pruebas y sube los cambios a una rama.
2. **App de GitHub**: revisa la rama, los archivos cambiados y, cuando lo
   pidas, el pull request. Fusionar es siempre decisión tuya.
3. **App de Gmail**: los mensajes aparecen en *Borradores*; los lees, los
   editas y los envías tú. Claude los crea con el conector de Gmail, sin
   necesidad de credenciales en el repositorio.

### Claves y contraseñas

Nunca en el chat ni en el repositorio. En la app de Claude: menú del entorno
en la barra de título de la sesión → **Edit** → *Network secrets* (o
variables de entorno). Una sesión nueva las recibe. Nombres que usará
Harvey: `REOON_API_KEY`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, y para
el módulo de creadoras, `YOUTUBE_API_KEY` y `META_ACCESS_TOKEN`.

### Limitación importante

El bucle automático de Harvey (`harvey run`, cada 15 minutos) necesita un
equipo siempre encendido; un contenedor de Claude Code se apaga cuando
termina la sesión. Con solo un iPhone, el modelo recomendado es **por
sesiones**: abres una sesión, pides «prepara 10 creadoras candidatas» o
«redacta propuestas para las aprobadas», revisas y cierras. Si más adelante
quieres que funcione solo, la opción es un servidor pequeño (unos 5 €/mes)
con el Docker de Harvey, y eso se decidiría aparte.

## Activar la configuración

En una sesión de Claude Code:

```bash
cp levanemaison/harvey.levanemaison.example.yaml harvey.local.yaml
```

`harvey.local.yaml` está en `.gitignore`, así que tus datos no se suben.
Completa los campos `COMPLETAR` antes de contactar a nadie.

## Qué falta para que sea útil de verdad

Ver la lista completa en [`modulo-influencers.md`](modulo-influencers.md#qué-falta)
y el checklist legal en [`cumplimiento-es-fr.md`](cumplimiento-es-fr.md).
