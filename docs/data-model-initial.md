# Modelo de datos inicial de StreamArch

Este documento fija el primer modelo de datos del core. No pretende cerrar todos los detalles de implementación, pero sí definir las entidades, tablas y relaciones que sostienen el MVP sin arrastrar las ambigüedades de StreamCapOrigin.

## Objetivo

Tener un modelo que permita:

- registrar streamers y su configuración operativa,
- sostener el scheduler predictivo,
- persistir sesiones de grabación y artefactos,
- exponer estado actual a la UI,
- y guardar métricas útiles sin ruido excesivo.

## Principios

## 1. Separar configuración, estado y histórico
No mezclar en una misma tabla:
- lo que el usuario configura,
- lo que el sistema está haciendo ahora,
- y lo que ocurrió en el pasado.

## 2. Evitar campos comodín ambiguos
Si una pieza tiene responsabilidad propia, merece tabla o estructura propia.

## 3. Optimizar para lectura operativa y recuperación
El core debe poder reiniciarse y entender:
- qué targets existen,
- cuál era su estado,
- qué sesiones estaban abiertas,
- y qué artefactos quedaron pendientes.

## 4. No persistir spam inútil
No guardar cada check offline si no aporta valor operativo o analítico.

## Entidades del dominio

## `StreamTarget`
Representa un objetivo de monitorización.

Responsabilidades:
- identidad del streamer
- plataforma
- flags de activación/favorito
- preferencias operativas base

## `MonitoringSnapshot`
Representa el estado actual resumido del target.

Responsabilidades:
- estado actual
- próxima revisión
- cola actual
- score actual
- última actividad observada

## `PredictionProfile`
Representa señales históricas y predictivas persistidas.

Responsabilidades:
- EMA
- consistencia
- último seen live
- patrones horarios agregados

## `RecordingSession`
Representa una sesión de directo detectada y su ciclo de vida.

## `RecordingArtifact`
Representa archivos asociados a una sesión.

Ejemplos:
- `.ts`
- `.mkv`
- `.mp4`
- logs técnicos o sidecars futuros

## `SystemEvent`
Evento relevante para auditoría, UI y diagnóstico.

## `MetricsBucket`
Agregado temporal de métricas de scheduler y detección.

## Tablas propuestas

## 1. `stream_targets`
Configuración principal del streamer.

| Campo | Tipo | Notas |
|------|------|------|
| `id` | text / uuid | PK |
| `platform` | text | twitch, tiktok, youtube, etc. |
| `handle` | text | identificador principal limpio |
| `source_url` | text | URL original o canonical |
| `display_name` | text | nombre visible en UI |
| `enabled` | boolean | monitorización activa |
| `favorite` | boolean | sesgo de prioridad |
| `preferred_quality` | text nullable | preferencia futura |
| `output_profile_id` | text nullable | FK lógica a perfil de salida |
| `schedule_mode` | text | `none`, `hinted`, `strict_hint` |
| `created_at` | datetime | |
| `updated_at` | datetime | |

### Notas
- `schedule_mode` existe para expresar intención del usuario, pero NO como gate operativo independiente.
- Si hay horarios manuales, no se modelan como strings CSV dentro de esta tabla.

## 2. `stream_target_schedule_hints`
Horarios manuales definidos por el usuario como señal fuerte.

| Campo | Tipo | Notas |
|------|------|------|
| `id` | text / uuid | PK |
| `stream_target_id` | text | FK -> `stream_targets.id` |
| `weekday` | integer nullable | 0-6, nullable si aplica a varios días/siempre |
| `start_time` | text/time | hora local normalizada |
| `duration_minutes` | integer | duración estimada |
| `priority_weight` | real | peso opcional adicional |
| `enabled` | boolean | |
| `created_at` | datetime | |

### Notas
- Esta tabla sustituye strings como `HH:MM~HH:MM` o listas separadas por comas.
- El predictor consume estos hints como señal.

## 3. `monitoring_snapshots`
Estado actual resumido por target.

| Campo | Tipo | Notas |
|------|------|------|
| `stream_target_id` | text | PK + FK |
| `state` | text | `idle`, `checking`, `recording`, `post_processing`, `error`, etc. |
| `queue_band` | text nullable | `fast`, `medium`, `slow` |
| `current_likelihood` | real | score actual |
| `current_confidence` | text | low/medium/high |
| `next_check_at` | datetime nullable | |
| `last_checked_at` | datetime nullable | |
| `last_live_at` | datetime nullable | |
| `current_recording_session_id` | text nullable | FK lógica |
| `last_error_code` | text nullable | |
| `last_error_message` | text nullable | |
| `updated_at` | datetime | |

### Notas
- Es la tabla principal de lectura rápida para dashboard.
- No sustituye el histórico.

## 4. `prediction_profiles`
Señales persistentes del predictor por target.

| Campo | Tipo | Notas |
|------|------|------|
| `stream_target_id` | text | PK + FK |
| `priority_score_ema` | real | señal principal de prioridad |
| `consistency_score` | real | densidad / estabilidad del patrón |
| `last_seen_live_at` | datetime nullable | |
| `last_detection_latency_seconds` | real nullable | última latencia observada |
| `live_detection_count` | integer | acumulado útil |
| `offline_check_count` | integer | agregado útil, no spam bruto |
| `updated_at` | datetime | |

### Notas
- Aquí viven señales agregadas, no eventos por check.
- Si algunos contadores resultan redundantes más adelante, se podrán derivar o eliminar.

## 5. `historical_hour_patterns`
Patrones horarios agregados por día/target.

| Campo | Tipo | Notas |
|------|------|------|
| `id` | text / uuid | PK |
| `stream_target_id` | text | FK |
| `weekday` | integer | 0-6 |
| `hour_of_day` | integer | 0-23 |
| `weight` | real | intensidad o relevancia |
| `sample_count` | integer | cuántas observaciones sustentan el peso |
| `last_observed_at` | datetime | |

### Notas
- Esta tabla representa la versión persistente y limpia del sistema de bloques horarios.
- Ya no actúa como sistema paralelo; solo como feature del predictor.

## 6. `recording_sessions`
Sesiones reales detectadas.

| Campo | Tipo | Notas |
|------|------|------|
| `id` | text / uuid | PK |
| `stream_target_id` | text | FK |
| `started_at` | datetime | |
| `ended_at` | datetime nullable | |
| `status` | text | `recording`, `completed`, `failed`, `aborted`, `split` |
| `source_platform` | text | redundancia útil para reporting |
| `stream_title` | text nullable | |
| `detected_by_queue` | text nullable | fast/medium/slow |
| `detection_latency_seconds` | real nullable | |
| `scheduled_hint_delay_minutes` | integer nullable | |
| `split_reason` | text nullable | stale gap, shutdown, reconnect, etc. |
| `error_code` | text nullable | |
| `error_message` | text nullable | |
| `created_at` | datetime | |
| `updated_at` | datetime | |

### Notas
- Esta tabla es clave para recuperación tras caída.
- Si el sistema reinicia, puede detectar sesiones abiertas o inconclusas.

## 7. `recording_artifacts`
Archivos asociados a la sesión.

| Campo | Tipo | Notas |
|------|------|------|
| `id` | text / uuid | PK |
| `recording_session_id` | text | FK |
| `artifact_type` | text | `raw_ts`, `raw_mkv`, `final_mp4`, `log` |
| `path` | text | ruta absoluta o relativa normalizada |
| `container_format` | text | ts/mkv/mp4 |
| `status` | text | `writing`, `ready`, `failed`, `deleted` |
| `size_bytes` | integer nullable | |
| `duration_seconds` | real nullable | |
| `checksum` | text nullable | futuro |
| `created_at` | datetime | |
| `updated_at` | datetime | |

### Notas
- Permite separar la sesión lógica del archivo físico.
- Facilita remux, limpieza y recuperación.

## 8. `system_events`
Eventos relevantes de dominio y operación.

| Campo | Tipo | Notas |
|------|------|------|
| `id` | text / uuid | PK |
| `stream_target_id` | text nullable | FK opcional |
| `recording_session_id` | text nullable | FK opcional |
| `event_type` | text | `live_detected`, `recording_started`, `disk_full`, etc. |
| `severity` | text | info/warn/error |
| `message` | text | resumen legible |
| `payload_json` | text nullable | detalles estructurados |
| `created_at` | datetime | |

### Notas
- Sirve para timeline, auditoría y troubleshooting.
- No debe convertirse en vertedero de logs de alta frecuencia.

## 9. `metrics_buckets`
Agregados temporales de salud del sistema.

| Campo | Tipo | Notas |
|------|------|------|
| `id` | text / uuid | PK |
| `bucket_start` | datetime | inicio del bucket |
| `bucket_size_seconds` | integer | 300, 900, etc. |
| `queue_band` | text | fast/medium/slow |
| `total_dispatches` | integer | |
| `total_live_detections` | integer | |
| `avg_dispatch_wait_seconds` | real nullable | |
| `p95_dispatch_wait_seconds` | real nullable | |
| `avg_detection_latency_seconds` | real nullable | |
| `sample_size` | integer | |
| `created_at` | datetime | |

### Notas
- Guarda observabilidad compacta.
- Sustituye el enfoque de eventos crudos masivos.

## Relaciones principales

```text
stream_targets
  ├── 1:N stream_target_schedule_hints
  ├── 1:1 monitoring_snapshots
  ├── 1:1 prediction_profiles
  ├── 1:N historical_hour_patterns
  ├── 1:N recording_sessions
  └── 1:N system_events

recording_sessions
  ├── 1:N recording_artifacts
  └── 1:N system_events
```

## Relación entre tablas operativas

### Configuración
- `stream_targets`
- `stream_target_schedule_hints`

### Estado actual
- `monitoring_snapshots`
- `prediction_profiles`

### Histórico
- `historical_hour_patterns`
- `recording_sessions`
- `recording_artifacts`
- `system_events`
- `metrics_buckets`

## Qué NO guardaremos de inicio

- cada check offline como fila individual,
- lógica duplicada del forecast para UI,
- ventanas serializadas como strings interpretables,
- blobs genéricos donde una relación clara resuelve mejor el modelo.

## Decisiones abiertas

| Tema | Pendiente |
|------|-----------|
| ids | UUID texto o entero autoincremental |
| timezone | política exacta de persistencia y visualización |
| payloads JSON | grado de flexibilidad aceptado en `system_events` |
| perfiles de salida | tabla propia o config embebida inicial |
| retención | cuánto histórico conservar por tabla |

## Resultado esperado

Si seguimos este modelo:

- el predictor tendrá datos útiles y limpios,
- la UI podrá consultar estado actual sin recomputar,
- y el core podrá reiniciar con contexto suficiente para recuperarse de errores y grabaciones interrumpidas.
