"""Minimal HTTP server for the REST API — stdlib only.

Provides a :class:`Router` for method+path dispatch with path parameters,
an :class:`APIHandler` that reads JSON bodies and sends JSON responses,
and a :func:`create_server` factory that wires the container into the
handler.

Usage::

    router = Router()
    router.add("GET", "/api/v1/streams", handle_list)

    server = create_server("127.0.0.1", 8899, container, router)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
"""

import json
import logging
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from app.bootstrap.container import Container

logger = logging.getLogger("streamarch")

# ── Router ─────────────────────────────────────────────────────────────


class Route:
    """A single registered route — method, compiled pattern, handler."""

    def __init__(self, method: str, pattern: re.Pattern, handler: Callable) -> None:
        self.method = method
        self.pattern = pattern
        self.handler = handler


class Router:
    """Lightweight path router with ``{param}`` extraction.

    Usage::

        router = Router()
        router.add("GET", "/api/v1/streams", handle_list)
        router.add("GET", "/api/v1/streams/{id}", handle_get)
        router.add("POST", "/api/v1/streams", handle_create)
    """

    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, path_spec: str, handler: Callable) -> None:
        """Register *handler* for *method* + *path_spec*.

        Path spec uses ``{name}`` syntax for variable segments::

            router.add("GET", "/items/{item_id}", handler)

        The handler receives extracted params as ``{name: value}``.
        """
        regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path_spec)
        self._routes.append(Route(method, re.compile(f"^{regex}$"), handler))

    def dispatch(
        self, method: str, path: str
    ) -> tuple[Callable | None, dict[str, str]]:
        """Find a matching handler, return it with extracted path params.

        Returns ``(None, {})`` when no route matches.
        """
        for route in self._routes:
            if route.method != method:
                continue
            m = route.pattern.match(path)
            if m:
                return route.handler, m.groupdict()
        return None, {}


# ── Request handler ────────────────────────────────────────────────────


class APIHandler(BaseHTTPRequestHandler):
    """HTTP handler that speaks JSON and dispatches through a :class:`Router`.

    Class-level attributes set once by :func:`create_server`::

        APIHandler.router   = <Router>
        APIHandler.container = <Container>
    """

    router: Router = Router()
    container: Container = Container()
    quiet: bool = True

    def log_message(self, format: str, *args: Any) -> None:
        if not self.quiet:
            logger.debug("HTTP %s %s", self.command, self.path)

    # ── JSON helpers ──────────────────────────────────────────────────

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    # ── Dispatch ──────────────────────────────────────────────────────

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        handler_fn, params = self.router.dispatch(self.command, path)

        # Merge query-string parameters into the params dict so handlers
        # can access both path captures and query parameters from the same
        # ``params`` argument.  For repeated keys only the first value is
        # kept — sufficient for our current needs.
        if parsed.query:
            for key, values in parse_qs(parsed.query).items():
                params.setdefault(key, values[0])

        if handler_fn is None:
            self._send_json(
                404,
                {
                    "error": {
                        "code": "not_found",
                        "message": f"Not found: {self.command} {path}",
                    }
                },
            )
            return

        body = self._read_body()
        try:
            data, status = handler_fn(self.container, params, body)
            self._send_json(status, data)
        except ValueError as e:
            self._send_json(
                400,
                {"error": {"code": "bad_request", "message": str(e)}},
            )
        except Exception:
            logger.exception(
                "Unhandled error handling %s %s", self.command, path
            )
            self._send_json(
                500,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Internal server error",
                    }
                },
            )

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()


# ── Server factory ─────────────────────────────────────────────────────


def create_server(
    host: str,
    port: int,
    container: Container,
    router: Router,
    quiet: bool = True,
) -> HTTPServer:
    """Return an ``HTTPServer`` wired with *container* and *router*.

    The server is **not** started — call ``.serve_forever()`` on the
    returned instance (typically in a background daemon thread).
    """
    APIHandler.router = router
    APIHandler.container = container
    APIHandler.quiet = quiet

    server = HTTPServer((host, port), APIHandler)
    server.timeout = 0.5
    return server
