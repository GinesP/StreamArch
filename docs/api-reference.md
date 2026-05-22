# Referencia de API actual de StreamArch

Esta es la referencia operativa de los endpoints REST IMPLEMENTADOS hoy en StreamArch.

## Quick path

1. Arranca el core:

```bash
python -m app.main
```

2. Usa el base path:

```text
http://127.0.0.1:8899/api/v1
```

3. Consulta primero:
- `GET /streams`
- `GET /dashboard/state`
- `GET /recordings`
- `GET /cookies`

## Reglas generales

| Tema | Decisión |
|------|----------|
| Formato | JSON en request/response |
| Base path | `/api/v1` |
| Auth | No implementada aún |
| Errores | `{"error": {"code", "message"}}` |
| Cookies import | Por ruta de archivo JSON local, no upload |

## Streams

### `GET /api/v1/streams`
Lista todos los stream targets con su estado actual.

#### Respuesta
```json
{
  "items": [
    {
      "id": "...",
      "platform": "twitch",
      "handle": "ibai",
      "display_name": "Ibai",
      "enabled": true,
      "favorite": false,
      "state": "idle",
      "queue_band": null,
      "current_likelihood": 0.0,
      "current_confidence": "low",
      "next_check_at": null,
      "last_live_at": null
    }
  ]
}
```

### `POST /api/v1/streams`
Crea un nuevo stream target.

#### Request
```json
{
  "platform": "twitch",
  "handle": "ibai",
  "source_url": "https://twitch.tv/ibai",
  "display_name": "Ibai",
  "preferred_quality": "best",
  "output_profile_id": null,
  "schedule_mode": "none"
}
```

#### Respuesta
```json
{
  "id": "uuid-del-target"
}
```

### `PATCH /api/v1/streams/{stream_id}`
Actualiza un subconjunto de campos del stream target.

#### Campos permitidos
- `display_name`
- `source_url`
- `preferred_quality`
- `output_profile_id`
- `schedule_mode`
- `enabled`
- `favorite`

#### Respuesta
```json
{
  "status": "updated"
}
```

### `POST /api/v1/streams/{stream_id}/disable-monitoring`
Desactiva monitorización.

#### Respuesta
```json
{
  "status": "disabled"
}
```

### `POST /api/v1/streams/{stream_id}/enable-monitoring`
Activa monitorización.

#### Respuesta
```json
{
  "status": "enabled"
}
```

### `POST /api/v1/streams/{stream_id}/favorite`
Marca como favorito.

#### Respuesta
```json
{
  "status": "favorited"
}
```

### `DELETE /api/v1/streams/{stream_id}/favorite`
Quita favorito.

#### Respuesta
```json
{
  "status": "unfavorited"
}
```

## Dashboard

### `GET /api/v1/dashboard/state`
Devuelve un snapshot agregado del estado actual.

#### Respuesta
```json
{
  "streams": [],
  "total_count": 0,
  "live_count": 0,
  "error_count": 0,
  "idle_count": 0
}
```

## Recordings

### `GET /api/v1/recordings`
Lista sesiones de grabación.

### `GET /api/v1/recordings?stream_id={stream_id}`
Lista sesiones de un stream concreto.

#### Respuesta
```json
{
  "items": [
    {
      "id": "rec-1",
      "stream_target_id": "stream-1",
      "started_at": "2026-05-21T12:00:00+00:00",
      "ended_at": "2026-05-21T13:00:00+00:00",
      "status": "completed",
      "source_platform": "twitch",
      "stream_title": "Directo",
      "duration_seconds": 3600.0,
      "detected_by_queue": "fast",
      "error_code": null,
      "error_message": null,
      "split_reason": null,
      "created_at": "2026-05-21T12:00:00+00:00",
      "updated_at": "2026-05-21T13:00:00+00:00"
    }
  ]
}
```

## Cookies

### `GET /api/v1/cookies`
Lista plataformas con cookies almacenadas.

#### Respuesta
```json
{
  "platforms": ["tiktok", "twitch"]
}
```

### `GET /api/v1/cookies/{platform}`
Devuelve estado y cadena de cookies de una plataforma.

#### Respuesta
```json
{
  "platform": "tiktok",
  "cookie_string": "sessionid=abc123; other=value",
  "has_cookies": true
}
```

### `POST /api/v1/cookies/import`
Importa cookies desde una ruta de archivo JSON local.

#### Request
```json
{
  "platform": "tiktok",
  "json_path": "C:\\ruta\\a\\www.tiktok.com.cookies.json"
}
```

#### Respuesta
```json
{
  "status": "imported",
  "count": 3
}
```

### `POST /api/v1/cookies/{platform}`
Setea o actualiza una cookie individual.

#### Request
```json
{
  "name": "sessionid",
  "value": "abc123"
}
```

#### Respuesta
```json
{
  "status": "set",
  "name": "sessionid"
}
```

## Errores

### Respuesta estándar
```json
{
  "error": {
    "code": "bad_request",
    "message": "..."
  }
}
```

### Códigos actuales
- `bad_request`
- `not_found`
- `internal_error`

## WebSocket

El core expone un endpoint WebSocket para eventos en tiempo real.

### Endpoint

```
ws://127.0.0.1:8900/ws/events
```

### Puerto

Configurable vía `AppConfig.ws_port` (default 8900). Host configurable vía `AppConfig.ws_host` (default `"127.0.0.1"`).

### Envelope

Cada mensaje sigue este formato:

```json
{
  "seq": 1051,
  "type": "stream.status_changed",
  "timestamp": "2026-05-20T20:02:10Z",
  "payload": {}
}
```

- `seq`: entero auto-incremental por instancia del servidor.
- `type`: tipo de evento (ver tabla abajo).
- `timestamp`: ISO 8601 UTC.
- `payload`: dict específico del evento.

### Eventos

| Tipo | Disparo | Payload |
|------|---------|---------|
| `stream.status_changed` | Cambio de estado de un target | `stream_id`, `state`, `queue_band`, `likelihood`, `confidence`, `ui_state` |
| `stream.forecast_updated` | Predicción actualizada | `stream_id`, `likelihood`, `confidence`, `ui_state`, `next_check_at`, `predicted_window`, `reasons` |
| `recording.started` | Nueva grabación detectada | `recording_id`, `stream_id`, `started_at`, `artifact_path` |
| `recording.progress` | Telemetría durante grabación | `recording_id`, `stream_id`, `duration_seconds`, `size_bytes`, `bitrate_kbps`, `fps`, `speed` |
| `recording.finished` | Grabación finalizada | `recording_id`, `stream_id`, `status`, `ended_at` |
| `postprocess.updated` | Post-procesamiento completado | _por definir_ |
| `queue.health_updated` | Estado periódico de colas (cada ciclo) | `fast`, `medium`, `slow` con `depth` y `workers` |
| `system.alert` | Alerta del sistema | `message`, `code` (ej: `disk_full`, `shutdown_started`) |

### Flujo esperado

1. Cliente pide snapshot por REST (`GET /api/v1/dashboard/state`).
2. Cliente abre WebSocket a `/ws/events`.
3. Core envía eventos incrementales.
4. Si se corta la conexión, cliente vuelve a pedir snapshot.

### Heartbeat

El servidor envía pings cada 30s (configurado vía `ping_interval` de la librería `websockets`). El cliente debe responder con pong para mantener la conexión viva.

## Notas operativas

### Cookies
- El endpoint de import usa una **ruta local del servidor**, no upload HTTP.
- Los archivos `*.cookies.json` no deben versionarse.

### Estado de la API
- No hay autenticación aún.
- WebSocket implementado en `/ws/events`. Ver sección WebSocket arriba.
- No hay scheduler ni forecast expuestos todavía.

## Siguiente paso

Cuando se añadan nuevos endpoints, esta referencia debe actualizarse en la misma unidad de trabajo.
