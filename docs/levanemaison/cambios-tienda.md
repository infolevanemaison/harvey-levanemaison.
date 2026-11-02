# Cambios recomendados para levanemaison.com

Textos y estructuras listos para aplicar en Shopify. **Ninguno está aplicado**:
los pones tú, o Claude cuando lo autorices. Los textos legales son un
borrador para revisar con un asesor. Lo que va entre `[corchetes]` lo
completas tú. No hay reseñas, testimonios, urgencias, garantías ni
descuentos inventados.

---

## 1. Aviso legal (Ajustes → Políticas → Aviso legal)

> **Aviso legal**
>
> En cumplimiento del artículo 10 de la Ley 34/2002, de Servicios de la
> Sociedad de la Información y de Comercio Electrónico (LSSI), se informa:
>
> - Titular: [nombre y apellidos o razón social]
> - NIF/CIF: [número]
> - Domicilio: [dirección completa]
> - Correo electrónico: [contacto@levanemaison.com]
> - Teléfono: [opcional, si quieres atender por teléfono]
> - Datos registrales: [solo si es sociedad: Registro Mercantil de …, tomo, folio, hoja]
>
> Levane Maison es la marca comercial con la que el titular vende moda
> femenina en este sitio web. (El resto del texto actual sobre propiedad
> intelectual, responsabilidad, cookies y legislación puede mantenerse.)

## 2. Política de envíos (sustituye a la actual)

> **Envíos**
>
> **Dónde enviamos:** España (península y Baleares) y Francia
> metropolitana. [Confirma si envías a Canarias, Ceuta, Melilla y Córcega.]
>
> **Coste:** el envío es gratuito en todos los pedidos.
>
> **Plazos:** preparamos tu pedido en 1-2 días laborables. Desde que sale,
> la entrega tarda entre 8 y 12 días laborables. Antes de pagar verás la
> fecha estimada.
>
> **Seguimiento:** cuando se envíe el pedido te enviaremos un correo con el
> número de seguimiento.
>
> **Si algo va mal:** si el paquete se retrasa más de lo indicado, llega
> dañado o no llega, escríbenos a [contacto@levanemaison.com] y lo
> resolvemos contigo: reenvío o reembolso.

*Por qué:* el coste aparece en la primera línea y desaparece el tono
defensivo («no nos hacemos responsables…»), que resta confianza.

## 3. Devoluciones y reembolsos (sustituye a la actual)

> **Devoluciones y cambios**
>
> **Plazo:** tienes 30 días naturales desde que recibes el pedido para
> devolverlo o cambiarlo, sin dar explicaciones. (La ley te da 14 días;
> nosotros lo ampliamos a 30.)
>
> **Cómo:** escríbenos a [contacto@levanemaison.com] con tu número de
> pedido y te enviamos las instrucciones.
>
> **Estado:** las prendas deben estar sin usar, con sus etiquetas.
>
> **Gastos de devolución:** [elige una opción: A) «la devolución es
> gratuita: te enviamos la etiqueta», o B) «el envío de la devolución
> corre de tu cuenta; te indicamos el coste aproximado antes de que la
> envíes»].
>
> **Reembolso:** te devolvemos el importe del producto y los gastos de
> envío iniciales en un máximo de 14 días desde que nos comunicas la
> devolución. Podemos esperar a recibir la prenda o a que nos envíes el
> justificante de envío. Usamos el mismo medio de pago.
>
> **Productos defectuosos o equivocados:** avísanos en cuanto lo veas, a
> ser posible con una foto. Nos hacemos cargo de todos los gastos y te
> ofrecemos cambio o reembolso. Esto no limita la garantía legal de 3 años.

*Por qué:* la política actual dice que el envío inicial no se reembolsa y
que los defectos se avisan en 48 h. Las dos cosas chocan con la normativa
de consumo (desistimiento y garantía legal) y con lo que ya dice tu FAQ.

## 4. Menú principal

```
Novedades            → /collections/ropa-de-mujer (orden: más recientes)
Vestidos             → /collections/vestidos
Blazers y chaquetas  → /collections/blazer
Conjuntos y monos    → /collections/conjuntos-y-monos
Zapatos              ▸ Mocasines · Bailarinas y sandalias · Mary Jane y tacón · Ver todos
Guía de tallas
Contacto
```

- Quitar «Inicio» (el logo ya lleva a la portada).
- Crear `/collections/vestidos` (o renombrar la URL de `abbigliamento`, que es
  italiano) y redirigir la antigua.
- Quitar «Bolsos» (1 producto) y «Tops y lencería» del menú principal hasta
  que tengan surtido. Pueden quedarse en el pie.
- Pie de página: Envíos · Devoluciones · Guía de tallas · Contacto · Aviso
  legal · Privacidad.

## 5. Portada (orden propuesto)

1. **Hero:** la mejor foto de una mujer de 35-65 años con una prenda propia,
   en alta resolución, no exportada de WhatsApp. Texto: «Elegancia para cada
   día» (el actual funciona). Un solo botón: «Ver la colección».
2. **Compra por categoría** (el bloque actual), con 4 fotos coherentes.
3. **Más vendidos o selección** (una sola fila de productos).
4. **Nuestros compromisos** (el bloque actual: envío gratis, 30 días, pago
   seguro, ayuda con la talla). Es información real y útil.
5. **Preguntas frecuentes** (el bloque actual).
6. **Suscripción** en el pie.

**Quitar o mover:** el bloque destacado de Giulia, porque en portada promociona
un top-sujetador como primer producto, y la cinta «ELIGE TU LOOK, COMBINA A TU
MANERA» en mayúsculas.

**Barra de anuncios:** un mensaje fijo, «Envío gratuito a España y Francia ·
Devoluciones en 30 días». El -20 % desde 60 € sigue aplicándose en el carrito.
Decide si además lo anuncias: un descuento fijo en la cabecera resta
percepción premium.

## 6. Ficha de producto: estándar mínimo

**Fotos (en este orden):**
1. Prenda puesta, de frente, fondo limpio.
2. Espalda.
3. Detalle del tejido.
4. Prenda puesta en contexto (oficina, cena, paseo).
5. Opcional: vídeo corto.

**Descripción (estructura).** Solo datos reales; si no los tienes, no los
pongas:

```
[Una frase: qué es y para qué ocasión.]

Tejido: [composición exacta, p. ej. 95 % poliéster, 5 % elastano]
Corte: [ajustado / recto / evasé…], largo [midi / hasta la rodilla…]
Cómo queda: [la modelo mide X cm y lleva la talla Y] (solo si es cierto)
Cuidados: [lavado a 30 °C…]
Medidas: ver tabla de tallas.
```

- Quitar el bloque de pack («2 unidades por…») de la parte alta de la
  ficha en móvil. Puede ir debajo del botón de compra, si lo mantienes.
- El tejido es obligatorio en el etiquetado textil y falta en 24 fichas.
- Opciones en español: «Talla», «Color», «Burdeos», «Gris claro».

## 7. Faja invisible: texto prudente

> Faja de tejido elástico pensada para llevar bajo vestidos ajustados o
> fluidos. Ayuda a que la ropa interior no se marque. Disponible en
> [colores] y tallas M a 2XL. Consulta la tabla de medidas antes de elegir.

(Sustituye «efecto alisante inmediato» y «no marca ni aprieta la piel»,
promesas sobre el cuerpo que no se pueden garantizar para todas.)

## 8. Prueba del checkout desde el iPhone (5 minutos, sin pagar)

1. Abre una ficha desde Instagram (como lo haría una clienta).
2. Elige talla y añade al carrito. ¿Se ve claro el precio final?
3. Pasa a pagar. Comprueba que:
   - aparece «Envío gratuito» y una fecha estimada;
   - se ofrecen Apple Pay y Google Pay;
   - si el pedido supera 60 €, el -20 % aparece aplicado;
   - si pruebas un código, ¿choca con el descuento automático?
4. Detente antes de pagar. Anota cualquier cosa que te hiciera dudar.

## 9. Mercados y envíos (Ajustes)

- **Mercados:** activar solo España y Francia. Así se dejan de recibir
  visitas y checkouts que nunca pueden terminar.
- **Idiomas:** solo el español está publicado. Para vender en Francia,
  publicar el francés con la app gratuita *Translate & Adapt* y revisar a
  mano las fichas principales, las políticas y la FAQ.
- **Envíos:** borrar el perfil «AutoDS Free Shipping» (resto del mundo),
  que no tiene productos.
- **Productos:** activar el seguimiento de inventario en todos, y revisar
  los stocks de 999, 32.000 y 54.000 unidades.
