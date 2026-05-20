# Arquitectura inicial del scheduler inteligente de StreamArch

## 1. Objetivo
Diseñar un scheduler que:

- minimice riesgo de bloqueo por parte de plataformas,
- mantenga alta capacidad de detección de directos,
- escale a muchos streamers,
- sea entendible y testeable,
- y tenga una sola fuente de verdad para predicción y decisión.

## 2. Principios de diseño

### P1. Un solo motor de decisión
No puede haber:
- un sistema que calcule score,
- otro que calcule ventana,
- otro que la UI reinterprete.

Debe existir una única salida coherente.

### P2. Varias señales, una sola decisión
Se pueden usar varias señales:
- historial por bloques horarios,
- sesiones reales,
- horarios manuales,
- favoritos,
- recencia,
- consistencia,
- estado actual.

Pero todas alimentan al mismo motor.

### P3. Scheduling ≠ detección ≠ grabación
Separación obligatoria:

- **Prediction**: estima probabilidad
- **Scheduling**: decide cuándo revisar
- **Detection**: comprueba live real
- **Recording**: graba y cierra

No se mezclan.

### P4. La UI no piensa
La UI muestra:
- score
- ventana
- estado interpretado
- próxima revisión

Pero TODO eso debe venir del core.

### P5. Los horarios manuales son señal, no gate duro
Los horarios programados no deben bloquear por fuera a un sistema que ya decidió revisar.

Deben influir mucho en el score, pero no existir como segundo filtro contradictorio.

## 3. Responsabilidades del subsistema

### 3.1 `PredictionEngine`
Responsable de producir una predicción unificada.

#### Entradas
- histórico horario agregado
- sesiones live históricas
- última vez visto live
- score EMA
- consistencia
- horario manual configurado
- favorito sí/no
- timestamp actual

#### Salidas
- `likelihood` (`0.0 - 1.0`)
- `confidence` (`low | medium | high`)
- `predicted_window`
- `next_slot`
- `ui_state`
- `reasons` explicables

#### `ui_state` sugeridos
- `idle`
- `upcoming`
- `expected_now`
- `delayed`
- `live`
- `cold`
- `disabled`

### 3.2 `SchedulingPolicy`
Convierte predicción en frecuencia operativa.

#### Entradas
- `likelihood`
- favorito
- estado del streamer
- límites globales
- reglas por plataforma

#### Salidas
- `target_interval_seconds`
- `jittered_interval_seconds`
- `priority_band`

#### `priority_band`
- `fast`
- `medium`
- `slow`

### 3.3 `QueuePlanner`
Decide a qué cola va cada target y cómo se despacha.

#### Responsabilidades
- clasificar streamers en `fast/medium/slow`
- ordenar por prioridad efectiva
- respetar semáforos por plataforma
- activar/desactivar worker boost
- evitar starvation

### 3.4 `MonitoringCoordinator`
Orquesta el ciclo.

#### Hace
- recorrer targets monitorizados
- pedir predicción
- pedir policy
- encolar
- disparar checks
- recoger resultados
- actualizar estado

#### NO hace
- matemáticas del predictor
- parseos manuales de ventanas
- lógica de UI

### 3.5 `MetricsAggregator`
Mide salud del sistema sin generar ruido inútil.

#### Persistir
- buckets agregados
- p95 de espera por cola
- cantidad de dispatches
- detecciones live
- latencia de detección
- precisión del predictor por muestreo

#### No persistir masivamente
- cada check offline sin valor

## 4. Modelo conceptual

### `StreamTarget`
Representa un streamer monitorizable.

Campos conceptuales:
- id
- plataforma
- handle/url
- enabled
- favorite
- monitoring_policy_id
- output_profile_id

### `MonitoringSnapshot`
Estado actual resumido.

- current_state
- current_queue
- last_checked_at
- last_live_at
- next_check_at
- current_likelihood
- current_confidence

### `PredictionFeatures`
Features calculadas para predecir.

- hourly_pattern_score
- session_pattern_score
- schedule_hint_score
- recency_factor
- consistency_factor
- ema_priority
- favorite_bias

### `PredictionResult`
Resultado final del motor.

- likelihood
- confidence
- predicted_window_start
- predicted_window_end
- next_slot_at
- ui_state
- reasons[]

### `RecordingSession`
- start_at
- end_at
- duration
- status
- split_reason
- source_platform

## 5. Fuentes de señal

### 5.1 Historial por bloques horarios
Se conserva, pero cambia de rol.

#### Antes
Era casi un sistema paralelo.

#### Ahora
Será una **feature estadística**:
- proximidad a horas probables
- agrupación por clusters
- ventana amplia

No decide sola.

### 5.2 Sesiones reales
Se convierten en la señal más rica.

Aportan:
- granularidad por minuto
- duración media
- día de semana
- retrasos típicos
- ventanas reales

### 5.3 Horarios manuales
No desaparecen.

Pero pasan a ser:
- una señal fuerte,
- una preferencia explícita del usuario,
- no un segundo gate fuera del predictor.

### 5.4 EMA / recencia / consistencia
Se mantienen como correctores operativos:
- quién merece más atención
- quién lleva mucho sin aparecer
- quién tiene patrón estable

## 6. Flujo operativo

### Ciclo principal
1. obtener streamers activos
2. calcular `PredictionResult`
3. aplicar `SchedulingPolicy`
4. decidir `queue_target`
5. encolar si toca
6. worker ejecuta `LiveCheck`
7. resultado actualiza estado, EMA, sesiones e histórico
8. emitir evento a UI

### Si el check da live
- abrir `RecordingSession`
- arrancar grabación
- marcar `ui_state = live`
- recalibrar score a máximo

### Si el check da offline
- actualizar recencia
- ajustar EMA
- cerrar sesión si corresponde
- recalcular siguiente revisión

## 7. Reglas clave de precedencia

### Regla 1
La decisión final sale SOLO de `PredictionEngine`.

### Regla 2
Los horarios manuales pueden empujar score hacia arriba o abajo, pero no bloquear por fuera.

### Regla 3
La ventana que ve la UI debe ser la misma ventana usada para justificar el score.

### Regla 4
No puede haber lógica duplicada de forecast en frontend.

### Regla 5
El intervalo se calcula a partir del `PredictionResult` ya obtenido, no recalculando todo otra vez.

## 8. Qué preservamos / refactorizamos / eliminamos

### Preservar
- EMA de prioridad
- colas fast/medium/slow
- jitter
- workers adaptativos
- tracking de sesiones
- consistencia
- recencia
- métricas agregadas
- forecast a horizontes

### Refactorizar
- cálculo unificado de predicción
- forma de representar ventanas
- integración de horario manual
- contrato hacia UI
- cálculo de intervalo y prioridad
- modelo persistente del scheduler

### Eliminar
- hard gate de horario en `check_if_live()`
- parseo duplicado de ventanas
- strings como representación primaria de rango horario
- lógica predictiva duplicada en la UI
- parches correctivos temporales como parte del diseño

## 9. Persistencia recomendada

### Guardar
- `stream_targets`
- `monitoring_snapshots`
- `recording_sessions`
- `historical_hour_patterns`
- `live_session_history`
- `metrics_buckets`

### Configuración en archivo
- límites globales
- concurrencia por plataforma
- thresholds
- jitter range
- políticas de retención
- parámetros de predictor

## 10. Riesgos a vigilar

### R1. Predictor demasiado opaco
Si el score no es explicable, no se podrá depurar.

#### Mitigación
Guardar `reasons` y componentes parciales.

### R2. Sobrecargar SQLite con telemetría irrelevante

#### Mitigación
Buckets agregados + sampling.

### R3. Heurísticas demasiado heredadas

#### Mitigación
Migrar conceptos, no copiar condicionales ciegamente.

### R4. Que el horario manual vuelva a convertirse en segundo sistema

#### Mitigación
Forzar que solo exista dentro del predictor unificado.

## 11. MVP del scheduler de StreamArch

### Debe incluir
- predictor unificado
- colas fast/medium/slow
- jitter
- workers adaptativos
- sesiones históricas
- EMA / recencia / consistencia
- explicación básica del score
- snapshot + eventos para UI

### Puede esperar
- visualizaciones complejas
- heatmaps avanzados
- calibración muy sofisticada
- optimizaciones finas del predictor

## 12. Decisión arquitectónica final
La inteligencia predictiva **sí es core del MVP**.

Pero en StreamArch debe existir como:

- **un solo motor**
- **explicable**
- **sin duplicidades**
- **sin gates contradictorios**
- **con contrato claro hacia colas, checks y UI**
