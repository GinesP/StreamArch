"""REST API endpoint handlers — one function per route.

Base path: /api/v1

Each handler function receives::

    container — the wired :class:`Container`
    params    — path parameters extracted by the router (``dict[str, str]``)
    body      — parsed JSON body (``dict`` or ``None`` for GET)

And returns ``(json_data, http_status)``.
"""

import logging
import os
from dataclasses import asdict

from app.application.commands.add_stream import AddStreamCommand
from app.application.commands.disable_monitoring import DisableMonitoringCommand
from app.application.commands.enable_monitoring import EnableMonitoringCommand
from app.application.commands.force_check import ForceCheckCommand
from app.application.commands.mark_favorite import MarkFavoriteCommand
from app.application.commands.stop_recording import StopRecordingCommand
from app.application.commands.unmark_favorite import UnmarkFavoriteCommand
from app.application.commands.update_stream import UpdateStreamCommand
from app.application.queries.get_dashboard_state import GetDashboardStateQuery
from app.application.queries.list_recordings import ListRecordingsQuery
from app.application.queries.list_streams import ListStreamsQuery
from app.bootstrap.container import Container
from app.interfaces.api.server import Router
from app.interfaces.presenters.stream_presenter import StreamPresenter

logger = logging.getLogger("streamarch")


# ── Route handlers ─────────────────────────────────────────────────────


def handle_list_streams(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """GET /api/v1/streams — list all streams with current monitoring state."""
    dtos = container.list_streams_handler.handle(ListStreamsQuery())
    return StreamPresenter.present_stream_list(dtos), 200


def handle_add_stream(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/streams — create a new stream target.

    After persisting the target, triggers an immediate live check and
    registers the target in the monitoring cycle so the result is
    available on the next cycle.
    """
    if body is None:
        raise ValueError("Request body is required and must be valid JSON")

    cmd = AddStreamCommand(
        platform=_require(body, "platform"),
        handle=_require(body, "handle"),
        source_url=_require(body, "source_url"),
        display_name=_require(body, "display_name"),
        preferred_quality=body.get("preferred_quality"),
        output_profile_id=body.get("output_profile_id"),
        schedule_mode=body.get("schedule_mode"),
    )

    target_id = container.add_stream_handler.handle(cmd)

    # ── Immediate live check for the new target ─────────────────
    try:
        result = container.force_check_handler.handle(
            ForceCheckCommand(stream_id=target_id),
        )
        # Store result so the monitoring cycle picks it up on next pass
        if container.live_check_result_store is not None:
            container.live_check_result_store.store(target_id, result)
        # Register runtime state so the target appears in snapshots
        if container.monitoring_cycle is not None:
            container.monitoring_cycle.register_new_target(target_id)
    except Exception:
        # Non-fatal — the monitoring cycle will pick up the new target
        # on its next pass anyway.
        logger.exception("Initial live check failed for new stream %s", target_id)

    return {"id": target_id}, 201


def handle_update_stream(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """PATCH /api/v1/streams/{stream_id} — update stream target fields."""
    if body is None:
        raise ValueError("Request body is required and must be valid JSON")
    if not body:
        raise ValueError("At least one field to update is required")

    stream_id = params.get("stream_id", "")
    cmd = UpdateStreamCommand(stream_id=stream_id, **body)
    container.update_stream_handler.handle(cmd)
    return {"status": "updated"}, 200


def handle_dashboard_state(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """GET /api/v1/dashboard/state — aggregate dashboard state."""
    dto = container.get_dashboard_state_handler.handle(GetDashboardStateQuery())
    return asdict(dto), 200


def handle_disable_monitoring(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/streams/{stream_id}/disable-monitoring — stop monitoring."""
    stream_id = params.get("stream_id", "")
    container.disable_monitoring_handler.handle(
        DisableMonitoringCommand(stream_id=stream_id)
    )
    return {"status": "disabled"}, 200


def handle_enable_monitoring(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/streams/{stream_id}/enable-monitoring — start monitoring."""
    stream_id = params.get("stream_id", "")
    container.enable_monitoring_handler.handle(
        EnableMonitoringCommand(stream_id=stream_id)
    )
    return {"status": "enabled"}, 200


def handle_mark_favorite(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/streams/{stream_id}/favorite — mark as favourite."""
    stream_id = params.get("stream_id", "")
    container.mark_favorite_handler.handle(
        MarkFavoriteCommand(stream_id=stream_id)
    )
    return {"status": "favorited"}, 200


def handle_unmark_favorite(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """DELETE /api/v1/streams/{stream_id}/favorite — unmark as favourite."""
    stream_id = params.get("stream_id", "")
    container.unmark_favorite_handler.handle(
        UnmarkFavoriteCommand(stream_id=stream_id)
    )
    return {"status": "unfavorited"}, 200


def handle_list_recordings(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """GET /api/v1/recordings — list recording sessions.

    Supports an optional ``stream_id`` query parameter to filter by target::

        GET /api/v1/recordings?stream_id=abc-123
    """
    stream_id = params.get("stream_id")
    dtos = container.list_recordings_handler.handle(
        ListRecordingsQuery(stream_id=stream_id)
    )
    return {"items": [asdict(d) for d in dtos]}, 200


def handle_stop_recording(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/recordings/{recording_id}/stop — stop an active recording.

    Idempotent — stopping an already-finished session returns 200 with
    ``{"status": "stopped"}``.  A nonexistent recording_id returns 400.
    """
    recording_id = params.get("recording_id", "")
    container.stop_recording_handler.handle(
        StopRecordingCommand(recording_id=recording_id)
    )
    return {"status": "stopped"}, 200


# ── Cookie handlers ─────────────────────────────────────────────────────


def handle_list_cookie_platforms(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """GET /api/v1/cookies — list platforms with stored cookies."""
    platforms = container.cookie_service.list_platforms()
    return {"platforms": platforms}, 200


def handle_get_cookie_platform(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """GET /api/v1/cookies/{platform} — get cookie status for a platform."""
    platform = params["platform"]
    cookie_string = container.cookie_service.get_cookie_string(platform)
    return {
        "platform": platform,
        "cookie_string": cookie_string,
        "has_cookies": bool(cookie_string),
    }, 200


def handle_import_cookies(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/cookies/import — import cookies from a JSON file path."""
    if body is None:
        raise ValueError("Request body is required and must be valid JSON")

    platform = _require(body, "platform")
    file_path = _require(body, "file_path")

    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")

    count = container.cookie_service.import_cookies(platform, file_path)
    return {"status": "imported", "platform": platform, "count": count}, 200


def handle_set_cookie(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/cookies/{platform} — set or update a single cookie."""
    if body is None:
        raise ValueError("Request body is required and must be valid JSON")

    platform = params["platform"]
    name = _require(body, "name")
    value = _require(body, "value")

    container.cookie_service.set_cookie(platform, name, value)
    return {"status": "set", "platform": platform, "name": name}, 200


# ── Force check ──────────────────────────────────────────────────────────


def handle_force_check(
    container: Container, params: dict, body: dict | None
) -> tuple[dict, int]:
    """POST /api/v1/streams/{stream_id}/force-check — trigger a live check.

    The resolver chain is consulted immediately and the monitoring
    snapshot is updated with the result.
    """
    stream_id = params.get("stream_id", "")
    result = container.force_check_handler.handle(
        ForceCheckCommand(stream_id=stream_id)
    )
    return {
        "stream_id": stream_id,
        "is_live": result.is_live,
        "stream_url": result.stream_url,
        "title": result.title,
        "anchor_name": result.anchor_name,
        "m3u8_url": result.m3u8_url,
    }, 200


# ── Helpers ────────────────────────────────────────────────────────────


def _require(body: dict, key: str) -> str:
    """Get *key* from *body* or raise a ``ValueError``."""
    value = body.get(key)
    if not value or not str(value).strip():
        raise ValueError(f"'{key}' is required")
    return str(value).strip()


# ── Router factory ─────────────────────────────────────────────────────


def build_router() -> Router:
    """Create and populate the route table for the REST API.

    Current endpoints::

        GET    /api/v1/streams
        POST   /api/v1/streams
        PATCH  /api/v1/streams/{stream_id}
        POST   /api/v1/streams/{stream_id}/disable-monitoring
        POST   /api/v1/streams/{stream_id}/enable-monitoring
        POST   /api/v1/streams/{stream_id}/force-check
        POST   /api/v1/streams/{stream_id}/favorite
        DELETE /api/v1/streams/{stream_id}/favorite
        GET    /api/v1/dashboard/state
        GET    /api/v1/recordings
        POST   /api/v1/recordings/{recording_id}/stop
        GET    /api/v1/cookies
        POST   /api/v1/cookies/import
        GET    /api/v1/cookies/{platform}
        POST   /api/v1/cookies/{platform}
    """
    router = Router()
    router.add("GET", "/api/v1/streams", handle_list_streams)
    router.add("POST", "/api/v1/streams", handle_add_stream)
    router.add("PATCH", "/api/v1/streams/{stream_id}", handle_update_stream)
    router.add(
        "POST", "/api/v1/streams/{stream_id}/disable-monitoring",
        handle_disable_monitoring,
    )
    router.add(
        "POST", "/api/v1/streams/{stream_id}/enable-monitoring",
        handle_enable_monitoring,
    )
    router.add(
        "POST", "/api/v1/streams/{stream_id}/force-check",
        handle_force_check,
    )
    router.add(
        "POST", "/api/v1/streams/{stream_id}/favorite",
        handle_mark_favorite,
    )
    router.add(
        "DELETE", "/api/v1/streams/{stream_id}/favorite",
        handle_unmark_favorite,
    )
    router.add("GET", "/api/v1/dashboard/state", handle_dashboard_state)
    router.add("GET", "/api/v1/recordings", handle_list_recordings)
    router.add(
        "POST", "/api/v1/recordings/{recording_id}/stop",
        handle_stop_recording,
    )
    # ── Cookie routes (import first so it's matched before {platform}) ──
    router.add("GET", "/api/v1/cookies", handle_list_cookie_platforms)
    router.add("POST", "/api/v1/cookies/import", handle_import_cookies)
    router.add("GET", "/api/v1/cookies/{platform}", handle_get_cookie_platform)
    router.add("POST", "/api/v1/cookies/{platform}", handle_set_cookie)
    return router
