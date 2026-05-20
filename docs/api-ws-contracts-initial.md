# Contratos iniciales REST y WebSocket de StreamArch

Este documento define qué expone el core a la UI en la primera fase. La idea es dar un contrato claro y estable antes de escribir demasiado código, evitando que la UI empiece a inventar su propio modelo del sistema.

## Objetivo

Definir:

- qué operaciones hace la UI por REST,
- qué información recibe por WebSocket,
- cuál es el snapshot base,
- y qué estados deben salir ya interpretados desde el core.

## Principios

## 1. REST para ordenar
La UI usa REST para:
- CRUD,
- configuración,
- acciones explícitas,
- lecturas bajo demanda.

## 2. WebSocket para observar
La UI usa WebSocket para:
- cambios de estado,
- telemetría viva,
- salud del sistema,
- alertas.

## 3. Snapshot + eventos
La UI no reconstruye el mundo solo con eventos.

Flujo esperado:
1. pedir snapshot por REST,
2. abrir WebSocket,
3. aplicar eventos incrementales,
4. si se corta conexión, volver a pedir snapshot.

## 4. La UI no calcula forecast
Los payloads deben traer:
- estado interpretado,
- score actual,
- ventana prevista,
- próxima revisión,
- motivos básicos.

## Base path sugerido

```text
/api/v1
```

## REST API inicial

## 1. Stream targets

### `GET /api/v1/streams`
Lista targets monitorizados.

#### Respuesta sugerida
```json
{
  "items": [
    {
      "id": "st_123",
      "platform": "twitch",
      "handle": "ibai",
      "display_name": "Ibai",
      "enabled": true,
      "favorite": true,
      "state": "recording",
      "queue_band": "fast",
      "current_likelihood": 1.0,
      "current_confidence": "high",
      "next_check_at": null,
      "last_live_at": "2026-05-20T20:02:00Z"
    }
  ]
}
```

### `POST /api/v1/streams`
Crear streamer monitorizado.

#### Request sugerido
```json
{
  "platform": "twitch",
  "handle": "ibai",
  "source_url": "https://twitch.tv/ibai",
  "display_name": "Ibai",
  "enabled": true,
  "favorite": false
}
```

### `GET /api/v1/streams/{stream_id}`
Detalle del target.

### `PATCH /api/v1/streams/{stream_id}`
Editar configuración básica.

Campos típicos:
- `display_name`
- `enabled`
- `favorite`
- `preferred_quality`
- `schedule_mode`

### `DELETE /api/v1/streams/{stream_id}`
Eliminar target.

### `POST /api/v1/streams/{stream_id}/enable`
Activar monitorización.

### `POST /api/v1/streams/{stream_id}/disable`
Desactivar monitorización.

### `POST /api/v1/streams/{stream_id}/favorite`
Marcar favorito.

### `POST /api/v1/streams/{stream_id}/unfavorite`
Quitar favorito.

### `POST /api/v1/streams/{stream_id}/force-check`
Forzar comprobación manual.

## 2. Forecast / predictor

### `GET /api/v1/streams/{stream_id}/forecast`
Devuelve la visión interpretada del predictor.

#### Respuesta sugerida
```json
{
  "stream_id": "st_123",
  "likelihood": 0.82,
  "confidence": "high",
  "ui_state": "expected_now",
  "predicted_window": {
    "start": "2026-05-20T19:45:00Z",
    "end": "2026-05-20T23:10:00Z"
  },
  "next_slot_at": "2026-05-20T20:00:00Z",
  "reasons": [
    "strong_session_pattern",
    "recent_live_activity",
    "favorite_bias"
  ],
  "current_queue_band": "fast",
  "target_interval_seconds": 60,
  "jittered_interval_seconds": 54
}
```

## 3. Schedule hints

### `GET /api/v1/streams/{stream_id}/schedule-hints`
Lista horarios manuales configurados.

### `POST /api/v1/streams/{stream_id}/schedule-hints`
Añade hint manual.

### `PATCH /api/v1/schedule-hints/{hint_id}`
Edita hint manual.

### `DELETE /api/v1/schedule-hints/{hint_id}`
Elimina hint manual.

## 4. Recording sessions

### `GET /api/v1/recordings`
Lista sesiones grabadas.

### `GET /api/v1/recordings/{recording_id}`
Detalle de sesión.

### `GET /api/v1/recordings/{recording_id}/artifacts`
Lista artefactos.

### `POST /api/v1/recordings/{recording_id}/stop`
Detención manual si sigue grabando.

## 5. Dashboard / estado global

### `GET /api/v1/dashboard/state`
Snapshot global de la aplicación.

#### Respuesta sugerida
```json
{
  "system": {
    "core_status": "running",
    "uptime_seconds": 86400,
    "disk_free_bytes": 842000000000,
    "active_recordings": 2,
    "connected_clients": 1
  },
  "queues": {
    "fast": { "depth": 2, "workers": 2, "p95_dispatch_wait_seconds": 1.2 },
    "medium": { "depth": 14, "workers": 1, "p95_dispatch_wait_seconds": 14.8 },
    "slow": { "depth": 45, "workers": 1, "p95_dispatch_wait_seconds": 124.1 }
  },
  "streams": [],
  "active_recordings": []
}
```

## 6. System / config

### `GET /api/v1/system/health`
Salud técnica simple.

### `GET /api/v1/system/config`
Configuración pública/segura para UI.

### `PATCH /api/v1/system/config`
Actualizar configuración editable desde UI.

### `POST /api/v1/system/shutdown`
Solicitar apagado limpio del core.

## WebSocket inicial

## Endpoint sugerido

```text
/ws/events
```

## Reglas del canal

- mensajes pequeños,
- secuencia incremental,
- payloads tipados por evento,
- nada de usar WS como reemplazo completo de REST en el MVP.

## Envelope sugerido

```json
{
  "seq": 1051,
  "type": "stream.status_changed",
  "timestamp": "2026-05-20T20:02:10Z",
  "payload": {}
}
```

## Eventos iniciales

## 1. `stream.status_changed`
Cuando cambia el estado principal de un target.

```json
{
  "seq": 1051,
  "type": "stream.status_changed",
  "timestamp": "2026-05-20T20:02:10Z",
  "payload": {
    "stream_id": "st_123",
    "state": "recording",
    "queue_band": "fast",
    "likelihood": 1.0,
    "confidence": "high",
    "ui_state": "live"
  }
}
```

## 2. `stream.forecast_updated`
Cuando cambia de forma relevante la predicción visible.

```json
{
  "seq": 1052,
  "type": "stream.forecast_updated",
  "timestamp": "2026-05-20T19:55:00Z",
  "payload": {
    "stream_id": "st_123",
    "likelihood": 0.92,
    "confidence": "high",
    "ui_state": "expected_now",
    "next_check_at": "2026-05-20T19:56:00Z",
    "predicted_window": {
      "start": "2026-05-20T19:45:00Z",
      "end": "2026-05-20T23:10:00Z"
    },
    "reasons": ["session_pattern_peak", "recent_live_activity"]
  }
}
```

## 3. `recording.started`

```json
{
  "seq": 1053,
  "type": "recording.started",
  "timestamp": "2026-05-20T20:02:11Z",
  "payload": {
    "recording_id": "rec_1",
    "stream_id": "st_123",
    "started_at": "2026-05-20T20:02:10Z",
    "artifact_path": "recordings/ibai_20260520_200210.ts"
  }
}
```

## 4. `recording.progress`

```json
{
  "seq": 1054,
  "type": "recording.progress",
  "timestamp": "2026-05-20T20:05:00Z",
  "payload": {
    "recording_id": "rec_1",
    "stream_id": "st_123",
    "duration_seconds": 170,
    "size_bytes": 734003200,
    "bitrate_kbps": 4850,
    "fps": 60,
    "speed": 1.0
  }
}
```

## 5. `recording.finished`

```json
{
  "seq": 1055,
  "type": "recording.finished",
  "timestamp": "2026-05-20T23:15:00Z",
  "payload": {
    "recording_id": "rec_1",
    "stream_id": "st_123",
    "status": "completed",
    "ended_at": "2026-05-20T23:14:50Z"
  }
}
```

## 6. `postprocess.updated`
Para reflejar remux/transmux y disponibilidad del MP4 final.

## 7. `queue.health_updated`
Estado periódico resumido de colas.

```json
{
  "seq": 1056,
  "type": "queue.health_updated",
  "timestamp": "2026-05-20T20:15:00Z",
  "payload": {
    "fast": { "depth": 2, "workers": 2 },
    "medium": { "depth": 14, "workers": 1 },
    "slow": { "depth": 45, "workers": 1 }
  }
}
```

## 8. `system.alert`
Alertas relevantes.

Ejemplos:
- `disk_full`
- `ffmpeg_not_found`
- `db_locked_recovered`
- `shutdown_started`

## Estado que debe venir resuelto desde el core

La UI no debe inferir esto por su cuenta:

- `state`
- `queue_band`
- `likelihood`
- `confidence`
- `ui_state`
- `predicted_window`
- `next_check_at`
- `recording_status`
- `postprocess_status`

## Errores y consistencia

## REST
Usar errores estructurados.

Ejemplo sugerido:
```json
{
  "error": {
    "code": "stream_not_found",
    "message": "The requested stream target does not exist."
  }
}
```

## WebSocket
Si la UI detecta hueco en `seq`, debe pedir snapshot de nuevo por REST.

## Resultado esperado

Si respetamos este contrato:

- la UI tendrá un modelo simple y fiable,
- el core conservará la inteligencia y la autoridad del estado,
- y evitaremos que reaparezcan cálculos duplicados y fuentes de verdad paralelas.
