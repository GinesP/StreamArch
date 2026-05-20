# Decisiones preserve/refactor/drop desde StreamCapOrigin

Este documento resume qué partes de StreamCapOrigin merecen sobrevivir en StreamArch, cuáles deben rediseñarse y cuáles conviene eliminar para no heredar inconsistencias.

## Resumen ejecutivo

La inteligencia predictiva es un activo probado y debe sobrevivir. El problema detectado no es el predictor, sino la mezcla de dos sistemas que compiten en la misma decisión final: el sistema legacy de horarios/bloques y el sistema avanzado de sesiones, likelihood y colas.

## Preserve

Elementos que conviene conservar como base conceptual o incluso como referencia de implementación.

| Elemento | Motivo |
|----------|--------|
| `priority_score` por EMA | señal útil y ya validada en producción |
| colas `fast/medium/slow` | distribución clara de frecuencia operativa |
| jitter del 15% | evita patrones detectables y thundering herd |
| workers adaptativos | mejora uso de recursos sin abrir demasiado la mano |
| `live_sessions` | histórico rico para ventanas reales y análisis fino |
| `consistency_score` | añade señal sobre estabilidad del patrón |
| recency decay | reduce atención a objetivos envejecidos |
| forecast por horizontes | útil para anticipar subidas/bajadas de probabilidad |
| métricas agregadas en SQLite | más sano que el histórico crudo masivo |

## Refactor

Elementos con valor claro, pero con implementación actual problemática.

| Elemento | Problema actual | Dirección para StreamArch |
|----------|------------------|---------------------------|
| `get_forecast_details()` | mezcla score de un sistema y ventana de otro | crear `PredictionEngine` con salida única y coherente |
| integración de horarios manuales | hoy actúan como señal y como gate duro | convertirlos solo en señal fuerte dentro del predictor |
| cálculo de intervalos | recomputa likelihood varias veces | derivar intervalo desde `PredictionResult` ya calculado |
| representación de ventanas | dispersa y con strings | usar tipos de tiempo consistentes y una única función |
| contrato hacia la UI | la UI recalcula lógica predictiva | exponer estado ya interpretado desde el core |
| modelo persistente de monitorización | campos mixtos y arrastre legacy | separar target, snapshot, sesiones y métricas |
| métricas de calibración | antes demasiado crudas | agregar por buckets y muestreo selectivo |

## Drop

Elementos que no conviene migrar porque generan acoplamiento, bugs o complejidad sin retorno.

| Elemento | Motivo para eliminar |
|----------|----------------------|
| hard gate de horario en `check_if_live()` | contradice al scheduler y desperdicia slots de cola |
| parseo duplicado de ventanas | dos implementaciones generan inconsistencias |
| strings tipo `HH:MM~HH:MM` como modelo primario | son frágiles y difíciles de validar |
| lógica predictiva duplicada en la UI | rompe la fuente única de verdad |
| parches temporales de normalización correctiva | señalan fallo de diseño, no solución duradera |
| campos legacy con contadores poco claros | mezclan viejo y nuevo sin una responsabilidad limpia |

## Problemas concretos detectados en StreamCapOrigin

## 1. Dos sistemas compiten en la misma decisión

Hoy conviven:

- sistema de horarios/bloques programados,
- sistema avanzado de sesiones + likelihood + colas.

Eso genera que un subsistema calcule probabilidad y otro cambie la ventana final o incluso bloquee la comprobación.

## 2. La UI participa en el cálculo

La UI Qt replica parte del forecasting. Eso debe desaparecer en StreamArch.

## 3. El scheduling manual actúa dos veces

- como boost de score,
- y como veto operativo.

Esa doble función es una de las raíces de la inconsistencia.

## 4. Demasiada responsabilidad concentrada

`record_manager.py` y piezas cercanas acumulan coordinación, reglas y detalles de infraestructura.

## Principios de migración

## 1. Migrar conceptos, no archivos
No hay que “portar” clases enteras si nacieron mezcladas.

## 2. Priorizar comportamiento probado
Lo que ya demostró funcionar en producción tiene preferencia sobre una limpieza estética.

## 3. Reducir cada sistema a señal
Bloques horarios, sesiones y horarios manuales deben ser señales hacia un único motor, no mini-schedulers paralelos.

## 4. Hacer el score explicable
Cada decisión relevante debe poder mostrar por qué se produjo.

## Decisión final

StreamArch debe preservar la inteligencia operativa de StreamCapOrigin, pero eliminando la convivencia caótica entre sistemas y centralizando toda decisión predictiva en un único motor con contrato claro hacia colas, checks y UI.
