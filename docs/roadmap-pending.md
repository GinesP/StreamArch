# Roadmap y tareas pendientes de StreamArch

Este documento recoge el estado actual del proyecto y las tareas pendientes identificadas durante la sesión de arquitectura e implementación inicial.

## Estado actual (23 mayo 2026)

El núcleo completo de StreamArch está implementado y verificado con un stream real de TikTok:

- Core Python con bootstrap, config, logging y shutdown graceful
- Dominio: StreamTarget, MonitoringSnapshot, PredictionResult, RecordingSession, RecordingArtifact
- Persistencia SQLite con conexiones por operación y WAL
- API REST: streams CRUD, dashboard, recordings, cookies
- WebSocket en tiempo real con EventBus
- UI React con Vite + TypeScript (Dashboard, Recordings, Settings)
- Sistema de cookies heredado de StreamCapQT
- Resolución TikTok real con streamget + cookies
- PredictionEngine con EMA, recencia, consistencia
- MonitoringCycle con colas FAST/MEDIUM/SLOW y workers adaptativos
- Semáforos por plataforma (protección antibot)
- Grabación ffmpeg con perfil robusto (StreamCapQT base profile)
- Watchers ffmpeg independientes para detección instantánea de fin de stream
- Remux automático .ts → .mp4 con -c copy -movflags faststart
- Parada desde API (POST /api/v1/recordings/{id}/stop)
- Naming de archivos: {canal}_{titulo}_{fecha}_{hora}.ext
- Configuración de grabación heredable (global → stream override)
- Segmentación por tiempo opcional (configurable)
- Test suite: 449 tests pasando
- Diseño de scheduler v2 completado en `docs/scheduler-redesign-v2.md`
- Referencia principal de comportamiento: `StreamCapOrigin/app/core/recording/record_manager.py`

## Tareas pendientes

### Prioridad alta

- [x] **Simplificar scheduler y eliminar MonitoringSnapshot rico** — el scheduler ahora conserva un estado operativo mínimo en memoria y deriva `MonitoringSnapshot` al vuelo para queries/UI/eventos. Objetivo: acercar la arquitectura al modelo simple de StreamCapQT y reducir inconsistencias entre estado, cola, likelihood y timing.
- [x] **Métricas de ciclo en dashboard** — worker valida "due" antes de checkear (evita checks redundantes), emite eventos `queue.cycle_stats` con contadores de enqueued/waiting por banda, sparkline de dispatched por ciclo en la UI. UI normalizada a inglés (F/M/S = Fast/Medium/Slow).
- [x] **Worker staggering y logs de check** — workers tienen delay aleatorio 0-3s antes de check (evita patrones regulares). Logs informativos por stream: "Checking X" y "Stream X is LIVE/offline". Se eliminaron logs ruidosos de "Skipped".
- [x] **UI: desconexión del core** — cuando el core está desconectado, muestra "Core disconnected" en rojo y deshabilita "Add Stream" (no se puede añadir streams sin backend).
- [x] **Workers adaptativos con boost móvil** — diseño completado en `docs/scheduler-redesign-v2.md`. Pendiente de implementación (Fase 1).
- [ ] **Scheduler redesign v2 (implementación Fase 1)** — workers adaptativos: scale-up por thresholds, reasignación de boost a cola 2× más congestionada, scale-down tras 60s vacía.
- [ ] **Scheduler redesign v2 (implementación Fase 2)** — ciclo de 180s con ordenación por priority_score.
- [ ] **Scheduler redesign v2 (implementación Fase 3)** — frontend: mostrar workers/busy por banda.
- [ ] **Scheduler redesign v2 (implementación Fase 4)** — predicción enriquecida con ventanas de emisión (HistoryManager).
- [ ] **Resolvedor Twitch funcional** — implementar StreamlinkResolver de verdad usando streamget.TwitchLiveStream, siguiendo el mismo patrón que TikTok.
- [ ] **Resolvedor YouTube funcional** — implementar YtDlpResolver usando yt-dlp o streamget.YouTubeLiveStream.
- [ ] **DELETE /api/v1/streams/{id}** — endpoint para eliminar stream con opción de limpiar grabaciones asociadas.
- [ ] **Manejo de segmentos en remux** — cuando `segment_enabled=True`, el flujo actual de stop/remux solo maneja un .ts. Hay que soportar múltiples segmentos (iterar _001.ts, _002.ts, etc. y remuxear cada uno).

### Prioridad media

- [ ] **Tests de integración reales automatizados** — E2E contra TikTok real (requiere cookies). Podría ser un script separado, no parte del suite principal de CI.
- [ ] **UI: mejorar indicador de grabación activa** — mostrar progreso en tiempo real (duración, tamaño, bitrate) desde los eventos WebSocket.
- [ ] **UI: gestión de cookies desde Settings** — mejorar el formulario de importación y mostrar estado de cookies por plataforma.
- [ ] **Direct download para FLV** — StreamCapQT tiene un modo de descarga directa para plataformas FLV sin ffmpeg. Evaluar si lo necesitamos.
- [ ] **Política de retención** — limpieza automática de grabaciones antiguas o por espacio en disco.

### Prioridad baja

- [ ] **Soporte de proxy por stream** — pasar `-http_proxy` a ffmpeg cuando esté configurado.
- [ ] **Rotación de user-agent** — aunque StreamCapQT no lo hace, algunas plataformas podrían beneficiarse.
- [ ] **Configuración de segmentación y carpeta por stream** — añadir campos a StreamTarget para override individual de `segment_enabled`, `segment_time_seconds`, `per_stream_directory`.
- [ ] **UI: dark mode refinado** — mejorar el tema oscuro con los colores exactos del diseño industrial.
- [ ] **Postprocesado con scripts** — ejecutar script personalizado después de la grabación (StreamCapQT lo soporta).
- [ ] **Conversión a otros formatos** — además de MP4, soportar MKV, etc.
- [ ] **Electron como wrapper opcional** — empaquetar la UI web como aplicación de escritorio.

### Decisiones pendientes

- [ ] **aiosqlite** — evaluar si migrar cuando el runtime sea totalmente async.
- [ ] **Framework de API** — stdlib HTTP server vs FastAPI cuando necesitemos más rendimiento o middlewares.
- [ ] **Autenticación** — para acceso remoto a la API/UI.
- [ ] **Distribución** — empaquetado del core como servicio Windows, Docker, etc.

## Notas técnicas

- Todos los resolvedores siguen el mismo patrón: heredar de `BaseResolver`, inyectar `CookieService`, usar `self.get_cookie_string()`.
- Para ffmpeg, el perfil base está en `process_runner.py` y sigue el perfil de StreamCapQT.
- La referencia para el sistema de cookies es `app/core/config/config_manager.py` de StreamCapOrigin.
- Para las plataformas adicionales, ver `app/core/platforms/platform_handlers/handlers.py` en StreamCapOrigin.
