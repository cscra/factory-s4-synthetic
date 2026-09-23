"""Loopback-only standard-library HTTP service for the synthetic first slice."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .domain import CRITERION_VERSION, CalculationError, DomainError, parse_dataset
from .storage import EnergyStore, SCHEMA_VERSION, StorageError


MAX_BODY_BYTES = 65_536
STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"
_READ_ACTORS = {"ANALYST", "REVIEWER"}


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        store: EnergyStore,
        build_ref: str,
    ):
        self.store = store
        self.build_ref = build_ref
        super().__init__(address, handler)


class _Handler(BaseHTTPRequestHandler):
    server: _LoopbackServer
    protocol_version = "HTTP/1.0"

    def log_message(self, format: str, *args: object) -> None:
        # The bounded synthetic service deliberately avoids raw request logging.
        return

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        # BaseHTTPRequestHandler otherwise emits an unbounded 501 HTML page for
        # every method without a do_METHOD attribute.
        if code == HTTPStatus.NOT_IMPLEMENTED and getattr(self, "command", None):
            self._method_not_allowed(head_only=self.command == "HEAD")
            return
        super().send_error(code, message, explain)

    def _send_bytes(
        self, status: int, body: bytes, content_type: str, *, head_only: bool = False
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_json(self, status: int, value: object, *, head_only: bool = False) -> None:
        self._send_bytes(
            status,
            _json_bytes(value),
            "application/json; charset=utf-8",
            head_only=head_only,
        )

    def _error(self, status: int, code: str, *, head_only: bool = False) -> None:
        self._send_json(
            status,
            {
                "ok": False,
                "error": {
                    "code": code,
                    "message": "synthetic batch rejected",
                },
            },
            head_only=head_only,
        )

    def _actor(self) -> str:
        return self.headers.get("X-Synthetic-Actor", "")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._error(HTTPStatus.NOT_FOUND, "RESOURCE_NOT_FOUND")
            return
        if parsed.path == "/api/health":
            try:
                database_identity = self.server.store.database_identity()
            except StorageError:
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_STORAGE_ERROR"
                )
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "health": {
                        "build_ref": self.server.build_ref,
                        "criterion_version": CRITERION_VERSION,
                        "schema_version": SCHEMA_VERSION,
                        "database_identity": database_identity,
                        "listener": "127.0.0.1",
                        "ready": True,
                    },
                },
            )
            return
        if parsed.path in {"/", "/index.html"}:
            try:
                index_bytes = STATIC_INDEX.read_bytes()
            except OSError:
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_SERVER_ERROR"
                )
                return
            self._send_bytes(
                HTTPStatus.OK,
                index_bytes,
                "text/html; charset=utf-8",
            )
            return
        if parsed.path == "/api/datasets":
            if self._actor() not in _READ_ACTORS:
                self._error(HTTPStatus.FORBIDDEN, "ROLE_NOT_PERMITTED")
                return
            try:
                datasets = self.server.store.list_datasets()
            except StorageError:
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_STORAGE_ERROR"
                )
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "datasets": datasets})
            return
        prefix = "/api/datasets/"
        if parsed.path.startswith(prefix):
            if self._actor() not in _READ_ACTORS:
                self._error(HTTPStatus.FORBIDDEN, "ROLE_NOT_PERMITTED")
                return
            dataset_id = unquote(parsed.path[len(prefix) :])
            if not dataset_id or "/" in dataset_id:
                self._error(HTTPStatus.NOT_FOUND, "DATASET_NOT_FOUND")
                return
            try:
                dataset = self.server.store.get(dataset_id)
            except StorageError:
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_STORAGE_ERROR"
                )
                return
            if dataset is None:
                self._error(HTTPStatus.NOT_FOUND, "DATASET_NOT_FOUND")
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "dataset": dataset})
            return
        self._error(HTTPStatus.NOT_FOUND, "RESOURCE_NOT_FOUND")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.path != "/api/datasets" or parsed.query or parsed.fragment:
            self._error(HTTPStatus.NOT_FOUND, "RESOURCE_NOT_FOUND")
            return
        # Actor authorization is intentionally selected before body inspection.
        if self._actor() != "ANALYST":
            self._error(HTTPStatus.FORBIDDEN, "ROLE_NOT_PERMITTED")
            return

        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header) if length_header is not None else None
        except ValueError:
            length = None
        if length is None or length < 1:
            self._error(HTTPStatus.LENGTH_REQUIRED, "HTTP_LENGTH_REQUIRED")
            return
        if length > MAX_BODY_BYTES:
            self._error(HTTPStatus.CONTENT_TOO_LARGE, "HTTP_PAYLOAD_TOO_LARGE")
            return
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "text/csv":
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "HTTP_MEDIA_TYPE_REQUIRED")
            return

        source_bytes = self.rfile.read(length)
        if len(source_bytes) != length:
            self._error(HTTPStatus.BAD_REQUEST, "HTTP_BODY_INCOMPLETE")
            return
        dataset_id = self.headers.get("X-Dataset-ID", "")
        try:
            candidate = parse_dataset(dataset_id, source_bytes)
            success_bytes = _json_bytes(
                {"ok": True, "dataset": candidate.to_public_dict()}
            )
        except CalculationError as error:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, error.code)
            return
        except DomainError as error:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, error.code)
            return
        except (TypeError, ValueError):
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_SERVER_ERROR")
            return

        try:
            self.server.store.save(candidate)
        except StorageError as error:
            if error.code in {
                "DUPLICATE_DATASET_REPLAY",
                "DATASET_ID_REUSE_CONFLICT",
            }:
                self._error(HTTPStatus.CONFLICT, error.code)
            else:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_STORAGE_ERROR")
            return
        self._send_bytes(
            HTTPStatus.CREATED,
            success_bytes,
            "application/json; charset=utf-8",
        )

    def _method_not_allowed(self, *, head_only: bool = False) -> None:
        self._error(
            HTTPStatus.METHOD_NOT_ALLOWED,
            "METHOD_NOT_ALLOWED",
            head_only=head_only,
        )

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed(head_only=True)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._method_not_allowed()


def make_server(
    host: str,
    port: int,
    db_path: str | Path,
    *,
    build_ref: str,
) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("the synthetic service binds only 127.0.0.1")
    if not isinstance(port, int) or not 0 <= port <= 65_535:
        raise ValueError("port must be an integer from 0 through 65535")
    store = EnergyStore(db_path)
    store.initialize()
    return _LoopbackServer((host, port), _Handler, store=store, build_ref=build_ref)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--build-ref", required=True)
    arguments = parser.parse_args()
    server = make_server(
        arguments.host,
        arguments.port,
        arguments.db,
        build_ref=arguments.build_ref,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
