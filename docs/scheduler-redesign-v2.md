# Rediseño del scheduler — v2

## Contexto

Este documento concreta el diseño operativo del scheduler de StreamArch,
partiendo de la arquitectura general definida en
[architecture-initial-scheduler.md](architecture-initial-scheduler.md) y
las decisiones tomadas durante la sesión de revisión del 23 mayo 2026.

Referencia de comportamiento esperado: StreamCap Origin
(`C:\Users\gperez\dev\StreamCapOrigin\app\core\recording\record_manager.py`
y `history_manager.py`).

---

## Decisiones arquitecturales

| Decisión | Opción tomada | Motivo |
|----------|--------------|--------|
| Concurrencia | `threading` + `queue.Queue` | Solo 3-4 workers; asyncio no aporta beneficio |
| Colas | 3 físicas (FAST/MEDIUM/SLOW) `queue.Queue` | Ya existen, funcionan, dan priorización natural |
| Ciclo | ~180s (configurable) | Alineado con StreamCap; reduce presión sobre plataformas |
| Workers | 3 base + 1 boost móvil = máx 4 | Igual que StreamCap; límite global evita saturación |
| Boost | Solo 1 cola puede tener 2 workers a la vez | Evita que 2 workers de diferentes colas golpeen la misma plataforma simultáneamente |
| Stagger | `time.sleep(random.uniform(0.5, 3.0))` antes del semáforo | Rompe patrones regulares visibles desde fuera |
| Ordenación | Streams ordenados por `priority_score` descendente antes de encolar | Streams más probables se procesan primero |
| Predicción | `PredictionEngine` actual (se enriquecerá después) | Ya existe, funciona, extensible |
| Métricas | `queue.cycle_stats` existente + enriquecer | Ya funciona en frontend |

---

## Flujo operativo

### Ciclo principal (`MonitoringCycle._run_one_cycle`)

```
Cada ~180s:
  1. Obtener targets habilitados
  2. Ordenar por priority_score descendente (con random tiebreaker)
  3. Para cada target:
     a. Calcular likelihood_score (vía PredictionEngine)
     b. Calcular adjusted_interval + queue_band (vía policy.py)
     c. Si next_check_at <= now → encolar en cola correspondiente
  4. Consumir resultados pendientes de workers
  5. Detectar transiciones de estado (live/offline)
  6. Emitir eventos (status_changed, queue.health_updated, queue.cycle_stats)
```

#### Cambios respecto a hoy

| Aspecto | Hoy | Nuevo |
|---------|-----|-------|
| `loop_interval_seconds` | 15 | 180 (configurable) |
| Ordenación | Sin ordenar | Por `priority_score` descendente |
| Encolado | Inmediato al estar due | Mismo, pero con ordenación previa |

### Workers adaptativos (`WorkerPool`)

```
3 workers base: 1 por cola (FAST, MEDIUM, SLOW), siempre vivos
1 boost móvil: se asigna a la cola más congestionada

Monitor cada 15s (_monitor_loop mejorado):
  - Scale-up: si depth[cola] > scale_up_at[cola]
                AND current[cola] < MAX_PER_BAND (2)
                AND ninguna otra cola tiene boost →
              añadir worker extra a esa cola

  - Reasignación: si depth[otra_cola] >= 2 * depth[cola_con_boost]
                    AND depth[otra_cola] > scale_up_at[otra_cola] →
                  mover boost (quitar de la actual, añadir a la otra)

  - Scale-down: si cola con boost lleva 60s vacía →
                eliminar worker extra

Total máximo: 4 workers (3 base + 1 boost)
```

#### Thresholds por cola

| Cola | Workers base | Workers máx | Scale-up threshold |
|------|-------------|-------------|-------------------|
| FAST | 1 | 2 | depth >= 5 |
| MEDIUM | 1 | 2 | depth >= 8 |
| SLOW | 1 | 2 | depth >= 5 |

#### Cambios respecto a hoy

| Aspecto | Hoy | Nuevo |
|---------|-----|-------|
| Boost | Fijo en una cola (el que más items tenía al crearse) | **Móvil**: se reasigna cada 15s según congestión |
| Scale-down | Nunca se quita el boost | Se quita tras 60s de cola vacía |
| Reasignación | No existe | Se mueve a cola 2× más congestionada |
| Monitor | Solo scale-up | Scale-up + reassign + scale-down |

### Stagger en el worker

Antes de adquirir el semáforo de plataforma:

```python
# Worker._worker_loop
item = queue_planner.dequeue_for_band(band)
if item is None:
    continue

# Stagger: rompe patrones regulares
time.sleep(random.uniform(0.5, 3.0))

# Validación due
if due_checker and not due_checker(stream_id):
    continue

# Semáforo y check
semaphores.acquire_sync(platform_key)
try:
    result = live_check_service.check_stream(stream_id)
    result_store.store(stream_id, result)
finally:
    semaphores.release_sync(platform_key)
```

### Due-checker

Ya implementado. Usa `last_checked_at`:
- Si `last_checked_at` es `None` → procesar
- Si `now - last_checked_at > 60s` → procesar  
- Si `now - last_checked_at <= 60s` → descartar (otro worker ya lo checkeó)

---

## Métricas

### Evento `queue.cycle_stats` (ya existe, enriquecer)

Payload actual:
```json
{
  "enqueued": {"fast": 3, "medium": 0, "slow": 12},
  "waiting": {"fast": 5, "medium": 39, "slow": 75},
  "cycle_timestamp": "2026-05-23T12:34:56Z"
}
```

Payload propuesto (añadir):
```json
{
  "enqueued": {"fast": 3, "medium": 0, "slow": 12},
  "waiting": {"fast": 5, "medium": 39, "slow": 75},
  "busy": {"fast": 1, "medium": 0, "slow": 2},
  "workers": {"fast": 1, "medium": 1, "slow": 2},
  "cycle_timestamp": "2026-05-23T12:34:56Z"
}
```

Donde `busy` = items actualmente siendo procesados por workers (pendientes
de resultado en `LiveCheckResultStore`).

### PredictorMetricsStore (futuro)

Se puede implementar después como SQLite similar a StreamCap, registrando
eventos `check_dispatched` y `check_result` con:
- `rec_id`
- `priority_score` / `likelihood`
- `loop_time_seconds`
- `is_live` / `was_live`
- `detection_latency_seconds`
- `dispatch_wait_seconds`

---

## Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `monitoring_cycle.py` | Ciclo de 180s, ordenación por priority_score, stagger ajustado |
| `worker_pool.py` | Workers adaptativos con boost móvil, scale-down, reassign |
| `queue_planner.py` | Sin cambios (ya soporta el modelo actual) |
| `startup.py` | Pasar `loop_interval_seconds=180` al `MonitoringCycle` |
| `Dashboard.tsx` | Mostrar workers por banda en métricas |
| `types.ts` | Tipos para los nuevos campos de métricas |

---

## Plan de implementación

### Fase 1 — Workers adaptativos (prioritario)
1. Refactorizar `WorkerPool._monitor_loop` para:
   - Scale-up por thresholds
   - Reasignación de boost (cola 2× más congestionada)
   - Scale-down tras 60s de cola vacía
2. Ajustar stagger a `random.uniform(0.5, 3.0)`
3. Tests: verificar que boost se mueve, scale-down funciona

### Fase 2 — Ciclo de 180s
1. Cambiar `loop_interval_seconds` de 15 a 180 (configurable)
2. Ordenar streams por `priority_score` antes de procesar
3. Actualizar métricas (`busy`, `workers` en evento)
4. Tests: verificar ordenación y nuevo intervalo

### Fase 3 — Frontend
1. Mostrar `workers` por banda en Dashboard
2. Mostrar `busy` (items en proceso)

### Fase 4 — Predicción (póstumo)
1. Enriquecer `PredictionEngine` con señales de ventana de emisión
2. Sesiones históricas como fuente de verdad única
3. HistoryManager similar a StreamCap

---

## Riesgos

| Riesgo | Mitigación |
|--------|-----------|
| 180s de ciclo retrasa detección de streams live | FAST (60s) sigue siendo rápido; el ciclo es para decidir qué revisar, no para revisar |
| Boost móvil causa thrashing (cambia cada 15s) | Threshold de 2× congestión + scale-down con 60s de holgura |
| Ordenación por priority_score añade latencia al ciclo | Con <1000 streams, ordenar en Python es <1ms |
| Workers adaptativos aumentan la complejidad de tests | Tests unitarios para scale-up, reassign, scale-down por separado |

---

## Referencias

- [architecture-initial-scheduler.md](architecture-initial-scheduler.md) — Arquitectura general
- StreamCap Origin: `C:\Users\gperez\dev\StreamCapOrigin\app\core\recording\record_manager.py`
- StreamCap HistoryManager: `C:\Users\gperez\dev\StreamCapOrigin\app\core\recording\history_manager.py`
- Documentación StreamCap: (proporcionada por el usuario en la sesión del 23 mayo 2026)
