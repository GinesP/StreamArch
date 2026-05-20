# Primer borrador de arquitectura general de StreamArch

StreamArch será una aplicación de grabación y monitorización de streams con un **core residente en Python** y una **UI web desacoplada**. La aplicación real es el motor; la interfaz es administración y observabilidad.

## Objetivo

Construir un sistema que:

- monitorice muchos streamers sin abusar de las plataformas,
- detecte directos con buena latencia,
- grabe con seguridad ante fallos,
- cierre limpiamente,
- y pueda evolucionar sin volver a un core monolítico difícil de mantener.

## Visión de alto nivel

```text
UI Web / Cliente
  ├── REST API
  └── WebSocket

Core StreamArch (Python)
  ├── CRUD y configuración
  ├── PredictionEngine
  ├── SchedulingPolicy + QueuePlanner
  ├── LiveCheck / resolvers
  ├── RecordingEngine (ffmpeg)
  ├── Postprocess / transmux
  ├── Persistence (SQLite)
  └── Metrics + Events
```

## Principios arquitectónicos

## 1. El core manda
La UI no controla procesos directamente ni ejecuta ffmpeg.

## 2. Una sola fuente de verdad
El estado operativo y predictivo se calcula en el core y se expone a la UI.

## 3. Separación de motores
Prediction, scheduling, detection y recording son subsistemas distintos.

## 4. Persistencia mínima pero útil
Guardar lo necesario para operar, explicar decisiones y recuperarse de fallos.

## 5. Robustez antes que cosmética
La prioridad es no perder sesiones ni generar comportamientos detectables por plataformas.

## Componentes principales

## `PredictionEngine`
Produce score, ventana, siguiente slot y estado explicable a partir de señales históricas y manuales.

## `SchedulingPolicy`
Convierte score en intervalos, jitter y bandas de prioridad.

## `QueuePlanner`
Gestiona colas fast/medium/slow, workers adaptativos y límites por plataforma.

## `LiveCheckService`
Comprueba si un target está live usando resolvers desacoplados.

## `RecordingEngine`
Gestiona procesos `ffmpeg`, progreso y parada controlada.

## `PostProcessEngine`
Hace remux/transmux de `.ts`/`.mkv` a `.mp4` cuando corresponda.

## `PersistenceLayer`
SQLite como fuente operativa de verdad.

## `EventBus`
Difunde cambios internos al WebSocket y a observabilidad local.

## Flujo principal

1. El core carga configuración y estado persistido.
2. El scheduler calcula predicción por streamer.
3. Se asigna cola e intervalo.
4. Un worker ejecuta `LiveCheck` respetando límites por plataforma.
5. Si detecta live, arranca `RecordingEngine`.
6. Durante la grabación, se emiten eventos de estado y telemetría.
7. Al terminar, se cierra sesión, se remuxa si aplica y se persiste el resultado.

## Comunicación con la UI

## REST
Para:
- CRUD de streamers
- configuración
- acciones explícitas
- lecturas de dashboard e historial

## WebSocket
Para:
- cambios de estado
- progreso de grabación
- salud de colas
- alertas del sistema

## Persistencia recomendada

| Área | Qué guardar |
|------|-------------|
| stream targets | configuración operativa por streamer |
| monitoring snapshots | estado actual resumido |
| recording sessions | sesiones reales y su estado |
| recording artifacts | archivos generados y metadatos |
| historical patterns | señales horarias y de sesión |
| metrics buckets | agregados compactos |
| system events | eventos relevantes y errores |

## Decisiones ya tomadas

| Tema | Decisión |
|------|----------|
| lenguaje del core | Python |
| UI | web desacoplada |
| comunicación | REST + WebSocket |
| persistencia inicial | SQLite |
| grabación | `ffmpeg` |
| formato temporal de grabación | `.ts` o `.mkv` |
| salida final preferida | `.mp4` por remux/transmux |
| predictor | sí, como parte core del MVP |

## Decisiones todavía abiertas

| Tema | Pendiente |
|------|-----------|
| framework exacto de API | validar FastAPI u otra opción equivalente |
| librería UI | React es candidata fuerte, aún no blindada |
| formato final interno de configuración | YAML/TOML/JSON con criterio definitivo |
| estrategia precisa de tests | definir TDD y capas de verificación |
| packaging/distribución | servicio Windows, wrapper de escritorio y despliegue futuro |

## MVP recomendado

## Debe incluir
- CRUD de streamers
- activar/desactivar monitorización
- favoritos
- predictor unificado
- colas fast/medium/slow
- jitter
- workers adaptativos
- live check desacoplado
- grabación segura con ffmpeg
- cierre limpio
- persistencia de sesiones
- WebSocket de estado

## Puede esperar
- Electron
- dashboards avanzados
- heatmaps sofisticados
- acceso remoto serio
- calibración compleja de predictor
- optimizaciones muy finas de observabilidad

## Riesgos principales

## 1. Repetir un mega-manager central
Mitigación: separar por capas y responsabilidades.

## 2. Reintroducir múltiples fuentes de verdad
Mitigación: un solo predictor y UI pasiva.

## 3. Persistir demasiado ruido
Mitigación: buckets agregados y sampling.

## 4. Duplicar grabaciones o cerrar mal sesiones
Mitigación: máquina de estados clara y shutdown controlado.

## Siguiente paso recomendado

Usar este borrador como base para aterrizar:

1. módulos concretos del core,
2. contrato de datos inicial,
3. y después formalizar el diseño mediante SDD si queremos convertirlo en guía de implementación.
