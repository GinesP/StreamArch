"""REST API route stubs for StreamArch.

Base path: /api/v1

Endpoints:
    Stream targets:
        GET    /streams
        POST   /streams
        GET    /streams/{id}
        PATCH  /streams/{id}
        DELETE /streams/{id}
        POST   /streams/{id}/enable
        POST   /streams/{id}/disable
        POST   /streams/{id}/favorite
        POST   /streams/{id}/unfavorite
        POST   /streams/{id}/force-check

    Forecast:
        GET    /streams/{id}/forecast

    Schedule hints:
        GET    /streams/{id}/schedule-hints
        POST   /streams/{id}/schedule-hints

    Recordings:
        GET    /recordings
        GET    /recordings/{id}
        GET    /recordings/{id}/artifacts

    Dashboard:
        GET    /dashboard/state

    System:
        GET    /system/health
        GET    /system/config
        PATCH  /system/config
        POST   /system/shutdown
"""
