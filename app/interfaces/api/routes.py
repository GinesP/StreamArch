"""REST API endpoint handlers — one function per route.

Base path: /api/v1

Each handler function receives::

    container — the wired :class:`Container`
    params    — path parameters extracted by the router (``dict[str, str]``)
    body      — parsed JSON body (``dict`` or ``None`` for GET)

And returns ``(json_data, http_status)``.
"""

from dataclasses import asdict

from app.application.commands.add_stream import AddStreamCommand
from app.application.commands.update_stream import UpdateStreamCommand
from app.application.queries.get_dashboard_state import GetDashboardStateQuery
from app.application.queries.list_streams import ListStreamsQuery
from app.bootstrap.container import Container
from app.interfaces.api.server import Router
from app.interfaces.presenters.stream_presenter import StreamPresenter


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
    """POST /api/v1/streams — create a new stream target."""
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


# ── Helpers ────────────────────────────────────────────────────────────


def _require(body: dict, key: str) -> str:
    """Get *key* from *body* or raise a ``ValueError``."""
    value = body.get(key)
    if not value or not str(value).strip():
        raise ValueError(f"'{key}' is required")
    return str(value).strip()


# ── Router factory ─────────────────────────────────────────────────────


def build_router() -> Router:
    """Create and populate the route table for the first API slice.

    Current endpoints::

        GET    /api/v1/streams
        POST   /api/v1/streams
        PATCH  /api/v1/streams/{stream_id}
        GET    /api/v1/dashboard/state
    """
    router = Router()
    router.add("GET", "/api/v1/streams", handle_list_streams)
    router.add("POST", "/api/v1/streams", handle_add_stream)
    router.add("PATCH", "/api/v1/streams/{stream_id}", handle_update_stream)
    router.add("GET", "/api/v1/dashboard/state", handle_dashboard_state)
    return router
