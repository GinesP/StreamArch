# Importación de cookies en StreamArch

StreamArch reutilizará el sistema de cookies de StreamCapQT/StreamCapOrigin porque ya está probado y funciona bien en producción.

## Para qué sirven

Algunas plataformas necesitan cookies válidas para:

- resolver streams correctamente,
- evitar bloqueos o restricciones,
- acceder a contenido que sin sesión falla o responde peor.

## Recomendación

Recomendamos exportar cookies con la extensión de Chrome:

- **Export cookie JSON file for Puppeteer**
- https://chromewebstore.google.com/detail/export-cookie-json-file-for-puppeteer/nmckokihipjgplolmcmjakknndddifde?hl=es&utm_source=ext_sidebar

Esta extensión genera un JSON muy compatible con el sistema que ya usa StreamCapQT y que queremos reutilizar en StreamArch.

## Flujo esperado

1. Iniciar sesión en la plataforma objetivo en el navegador.
2. Exportar las cookies con la extensión recomendada.
3. Importar el JSON en StreamArch.
4. StreamArch convertirá ese JSON a una cadena de cookies por plataforma.

## Formato esperado de entrada

El importador heredado trabaja con un JSON que suele tener una estructura tipo:

```json
[
  {
    "name": "sessionid",
    "value": "abc123",
    "domain": ".tiktok.com",
    "path": "/",
    "httpOnly": true,
    "secure": true
  }
]
```

Durante la importación, StreamArch conservará sobre todo:

- `name`
- `value`

Y construirá una cadena tipo:

```text
sessionid=abc123; otra_cookie=valor
```

## Decisión actual de arquitectura

- Las cookies se tratarán **por plataforma**, no por streamer individual.
- El sistema base se tomará de StreamCapQT/StreamCapOrigin.
- La integración final quedará desacoplada del framework de UI.

## Advertencias importantes

### 1. Son credenciales sensibles
Las cookies pueden representar una sesión autenticada. No deben compartirse ni subirse al repositorio.

### 2. Deben quedar fuera de Git
Los archivos de cookies deben permanecer ignorados por Git.

### 3. Pueden caducar
Aunque la importación funcione, las cookies pueden dejar de ser válidas con el tiempo.

### 4. Exporta desde el dominio correcto
Si exportas cookies de un dominio equivocado, la plataforma puede no responder como esperas.

## Estado actual

Todavía no está implementada la importación de cookies en StreamArch, pero esta será la referencia funcional y operativa cuando bajemos esa parte a código.
