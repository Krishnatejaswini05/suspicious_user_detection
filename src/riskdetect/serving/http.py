"""A small JSON HTTP API over DetectorService, using Python's built-in server.

    POST /events                                   {"platform": ..., "records": [...]}
    GET  /actors/{platform}/{actor_id}/risk
    GET  /actors/{platform}/{actor_id}/history
    GET  /review-queue?platform=...&limit=...
    POST /actors/{platform}/{actor_id}/review  {"decision": "spam", "reviewer": ..., "note": ...}
    GET  /platforms
    GET  /health

    GET  /                                         the reviewer dashboard (web/index.html)
    GET  /web/{file}                               its scripts and styles

In demo mode (a public showcase on synthetic data) ``POST /events`` is switched off,
so visitors can look and record decisions but cannot send data in.

If an API key is configured, every API request must send it in the ``X-API-Key``
header. The dashboard files hold no data, so they are served without it; the page
asks for the key and sends it with its own API calls.

The built-in server needs no extra libraries; a framework such as FastAPI could wrap
the same DetectorService later.
"""

import hmac
import json
import re
import sys
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from riskdetect.serving.service import BadRequest, DetectorService, NotFound, ServiceError

MAX_BODY_BYTES = 5 * 1024 * 1024
WEB_DIR = Path(__file__).with_name("web")
# The dashboard's files, by URL path; nothing else on disk is ever served.
_WEB_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/web/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/web/style.css": ("style.css", "text/css; charset=utf-8"),
}
_ACTOR = re.compile(r"^/actors/(?P<platform>[^/]+)/(?P<actor>[^/]+)/(?P<what>risk|history|review)$")

Response = tuple[int, dict[str, Any]]


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: DetectorService,
        api_key: str | None = None,
        quiet: bool = False,
        demo: bool = False,
    ) -> None:
        super().__init__(address, ApiHandler)
        self.service = service
        self.api_key = api_key
        self.quiet = quiet
        self.demo = demo


class ApiHandler(BaseHTTPRequestHandler):
    server: ApiServer
    server_version = "riskdetect"

    def do_GET(self) -> None:
        web = _WEB_FILES.get(urlparse(self.path).path)
        if web is not None:
            self._send_file(*web)
            return
        self._handle(self._get)

    def do_POST(self) -> None:
        self._handle(self._post)

    # -- routing ---------------------------------------------------------------------

    def _get(self) -> Response:
        url = urlparse(self.path)
        service = self.server.service
        if url.path == "/health":
            return 200, {**service.health(), "demo": self.server.demo}
        if url.path == "/platforms":
            return 200, service.platforms()
        if url.path == "/review-queue":
            query = parse_qs(url.query)
            platform = query.get("platform", [None])[0]
            try:
                limit = int(query.get("limit", ["50"])[0])
            except ValueError as exc:
                raise BadRequest("limit must be a whole number") from exc
            return 200, service.review_queue(platform, limit)
        match = _ACTOR.match(url.path)
        if match and match["what"] == "risk":
            return 200, service.risk(unquote(match["platform"]), unquote(match["actor"]))
        if match and match["what"] == "history":
            return 200, service.history(unquote(match["platform"]), unquote(match["actor"]))
        raise NotFound(f"no such endpoint: GET {url.path}")

    def _post(self) -> Response:
        url = urlparse(self.path)
        body = self._json_body()
        service = self.server.service
        if url.path == "/events":
            if self.server.demo:
                raise _Forbidden("sending events is switched off in this demo")
            if "platform" not in body or "records" not in body:
                raise BadRequest("body needs 'platform' and 'records'")
            return 200, service.ingest(str(body["platform"]), body["records"])
        match = _ACTOR.match(url.path)
        if match and match["what"] == "review":
            return 200, service.record_review(
                unquote(match["platform"]),
                unquote(match["actor"]),
                body.get("decision"),
                body.get("reviewer"),
                body.get("note"),
            )
        raise NotFound(f"no such endpoint: POST {url.path}")

    # -- plumbing --------------------------------------------------------------------

    def _handle(self, route: Callable[[], Response]) -> None:
        try:
            self._check_key()
            status, payload = route()
        except ServiceError as exc:
            status, payload = exc.status, {"error": exc.message}
        except Exception:  # never leak internals to the caller
            self.log_error("unhandled error on %s %s", self.command, self.path)
            status, payload = 500, {"error": "internal error"}
        data = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, name: str, content_type: str) -> None:
        try:
            data = (WEB_DIR / name).read_bytes()
        except OSError:
            self.log_error("dashboard file missing: %s", name)
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def _check_key(self) -> None:
        expected = self.server.api_key
        if expected is None:
            return
        given = self.headers.get("X-API-Key", "")
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise _Unauthorized("missing or wrong X-API-Key")

    def _json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BadRequest("invalid Content-Length") from exc
        if length > MAX_BODY_BYTES:
            raise _TooLarge(f"body larger than {MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BadRequest(f"body is not valid JSON: {exc.msg}") from exc
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        return body

    def log_message(self, format: str, *args: Any) -> None:
        if not self.server.quiet:
            sys.stderr.write(f"{self.address_string()} - {format % args}\n")


class _Unauthorized(ServiceError):
    status = HTTPStatus.UNAUTHORIZED


class _Forbidden(ServiceError):
    status = HTTPStatus.FORBIDDEN


class _TooLarge(ServiceError):
    status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
