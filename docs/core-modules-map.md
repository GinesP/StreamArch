# Mapa de módulos y carpetas del core de StreamArch

Este documento propone la estructura inicial del core para evitar repetir los acoplamientos de StreamCapOrigin. La idea central es separar **predicción**, **scheduling**, **detección**, **grabación** e **interfaces**.

## Objetivo

Tener un core que:

- sea fácil de entender,
- permita migrar la inteligencia predictiva sin barro heredado,
- aísle infraestructura de reglas de negocio,
- y exponga un contrato claro a la UI web.

## Estructura propuesta

```text
streamarch/
├── app/
│   ├── domain/
│   │   ├── stream_target/
│   │   ├── monitoring/
│   │   ├── prediction/
│   │   ├── recording/
│   │   ├── events/
│   │   └── shared/
│   ├── application/
│   │   ├── commands/
│   │   ├── queries/
│   │   ├── services/
│   │   ├── dto/
│   │   └── orchestrators/
│   ├── infrastructure/
│   │   ├── db/
│   │   ├── repositories/
│   │   ├── ffmpeg/
│   │   ├── resolvers/
│   │   ├── scheduler/
│   │   ├── metrics/
│   │   ├── files/
│   │   ├── config/
│   │   └── logging/
│   ├── interfaces/
│   │   ├── api/
│   │   ├── websocket/
│   │   ├── presenters/
│   │   └── mappers/
│   ├── bootstrap/
│   └── main.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
└── docs/
```

## Responsabilidad por capa

| Capa | Qué contiene | Qué NO debe contener |
|------|--------------|----------------------|
| `domain/` | reglas de negocio, entidades, value objects, estados | FastAPI, SQLite, ffmpeg, JSON de API |
| `application/` | casos de uso, coordinación, DTOs | queries SQL directas, lógica de plataforma |
| `infrastructure/` | persistencia, ffmpeg, stream resolvers, config, IO | reglas de negocio principales |
| `interfaces/` | REST, WS, presentación hacia UI | decisiones del scheduler o del predictor |
| `bootstrap/` | wiring, startup, shutdown, DI simple | lógica de dominio |

## Detalle por módulo

## `app/domain/`

### `stream_target/`
Modelo del streamer monitorizable.

Posibles piezas:
- `entities.py` → `StreamTarget`
- `value_objects.py` → `Platform`, `StreamHandle`, `FavoriteFlag`
- `policies.py` → reglas básicas de activación/desactivación

### `monitoring/`
Estado operativo de monitorización.

Posibles piezas:
- `states.py` → `idle`, `checking`, `recording`, `post_processing`, `error`
- `snapshot.py` → `MonitoringSnapshot`
- `rules.py` → transiciones permitidas

### `prediction/`
Corazón de la inteligencia predictiva.

Posibles piezas:
- `features.py` → cálculo de señales parciales
- `engine.py` → `PredictionEngine`
- `results.py` → `PredictionResult`
- `explanations.py` → razones explicables del score

### `recording/`
Ciclo de vida de sesiones y artefactos.

Posibles piezas:
- `session.py` → `RecordingSession`
- `artifacts.py` → `RecordingArtifact`
- `rules.py` → cierre, split, remux requerido

### `events/`
Eventos de dominio y contratos internos.

Ejemplos:
- `stream_checked`
- `live_detected`
- `recording_started`
- `recording_finished`
- `disk_full_detected`

### `shared/`
Tipos comunes del dominio.

Ejemplos:
- resultados
- errores
- clocks
- ids

## `app/application/`

### `commands/`
Casos de uso mutables.

Ejemplos:
- `add_stream.py`
- `update_stream.py`
- `disable_monitoring.py`
- `mark_favorite.py`
- `force_check.py`
- `stop_core_gracefully.py`

### `queries/`
Lectura para UI y API.

Ejemplos:
- `list_streams.py`
- `get_dashboard_state.py`
- `get_stream_forecast.py`
- `list_recordings.py`

### `services/`
Servicios de aplicación que coordinan dominio + infra.

Ejemplos:
- `prediction_service.py`
- `recording_service.py`
- `health_service.py`

### `dto/`
Contratos de entrada/salida entre capas.

### `orchestrators/`
Coordinadores de alto nivel.

Ejemplos:
- `monitoring_cycle.py`
- `shutdown_orchestrator.py`
- `postprocess_orchestrator.py`

## `app/infrastructure/`

### `db/`
Conexión SQLite, migraciones, PRAGMAs, WAL.

### `repositories/`
Implementaciones persistentes de repositorios.

Ejemplos:
- `stream_target_repository.py`
- `monitoring_snapshot_repository.py`
- `recording_session_repository.py`
- `metrics_bucket_repository.py`

### `ffmpeg/`
Adaptadores del motor de grabación.

Ejemplos:
- `process_runner.py`
- `progress_parser.py`
- `transmuxer.py`
- `shutdown.py`

### `resolvers/`
Resolución de URLs/streams por backend externo.

Ejemplos:
- `streamget_resolver.py`
- `streamlink_resolver.py`
- `ytdlp_resolver.py`
- `resolver_chain.py`

### `scheduler/`
Infraestructura del scheduler, no reglas del predictor.

Ejemplos:
- `queue_planner.py`
- `worker_pool.py`
- `platform_semaphores.py`
- `jitter.py`

### `metrics/`
Agregación y persistencia compacta de métricas.

### `files/`
Filesystem, paths, naming, retención.

### `config/`
Carga de archivo de configuración y overrides por entorno.

### `logging/`
Logs técnicos y de auditoría.

## `app/interfaces/`

### `api/`
REST para CRUD, settings y acciones explícitas.

### `websocket/`
Eventos de estado vivo y telemetría.

### `presenters/`
Transforman datos internos en payloads listos para UI.

### `mappers/`
Mapeos entre DTOs, modelos internos y contratos públicos.

## `app/bootstrap/`

Responsable de:
- iniciar config,
- abrir DB,
- construir dependencias,
- iniciar scheduler,
- registrar señales de apagado,
- cerrar el sistema limpiamente.

## Reglas estructurales

## Regla 1
`interfaces/` no llama a SQLite ni a ffmpeg directamente.

## Regla 2
`domain/` no sabe nada de FastAPI, WebSocket o la UI.

## Regla 3
La lógica del predictor vive en `domain/prediction`, no en `record_manager` gigantesco.

## Regla 4
La UI consume un estado ya interpretado; no recalcula clusters ni ventanas.

## Regla 5
`infrastructure/scheduler/` gestiona colas y workers; `domain/prediction/` decide señales y score.

## Mapeo conceptual desde StreamCapOrigin

| StreamCapOrigin | StreamArch |
|-----------------|------------|
| `record_manager.py` gigante | `application/orchestrators/` + `infrastructure/scheduler/` + `application/services/` |
| `history_manager.py` | `domain/prediction/` |
| `recording_model.py` mixto | `domain/stream_target/`, `domain/monitoring/`, `domain/recording/` |
| lógica de forecast en UI Qt | `interfaces/presenters/` + `domain/prediction/results.py` |
| predictor metrics | `infrastructure/metrics/` |

## Orden recomendado de implementación

1. `domain/stream_target/`
2. `domain/monitoring/`
3. `domain/prediction/`
4. `domain/recording/`
5. `infrastructure/db/` + `repositories/`
6. `infrastructure/resolvers/`
7. `infrastructure/ffmpeg/`
8. `infrastructure/scheduler/`
9. `application/commands/queries/`
10. `interfaces/api/` y `websocket/`
11. `bootstrap/`

## Resultado esperado

Si respetamos esta estructura:

- la inteligencia predictiva sobrevive,
- el core se vuelve mucho más legible,
- y evitamos que vuelva a aparecer un “mega manager” central con múltiples responsabilidades.
