"""HTTP + SSE transport for the web GUI adapter."""

from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import parse_qs, urlparse

from human_sched.gui.contract import GuiAdapterMetadata
from human_sched.gui.facade import SchedulerGuiFacade

_TASK_ACTION_RE = re.compile(r"^/api/tasks/(?P<task_id>\d+)/(pause|resume|complete|delete)$")
_LIFE_AREA_DELETE_RE = re.compile(r"^/api/life-areas/(?P<life_area_id>\d+)/delete$")
_LIFE_AREA_RENAME_RE = re.compile(r"^/api/life-areas/(?P<life_area_id>\d+)/rename$")


class _GuiThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class SchedulerHttpService:
    """Owns web transport lifecycle and diagnostics counters."""

    __slots__ = (
        "facade",
        "metadata",
        "host",
        "port",
        "base_url",
        "static_dir",
        "frontend_redirect_url",
        "_httpd",
        "_running",
        "_lock",
        "_sse_active_clients",
        "_sse_retried_writes",
        "_sse_dropped_clients",
        "_sse_last_error",
    )

    def __init__(
        self,
        *,
        facade: SchedulerGuiFacade,
        metadata: GuiAdapterMetadata,
        host: str,
        port: int,
        static_dir: Path,
        frontend_redirect_url: str | None = None,
    ) -> None:
        self.facade = facade
        self.metadata = metadata
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.static_dir = static_dir.resolve()
        self.frontend_redirect_url = frontend_redirect_url.rstrip("/") if frontend_redirect_url else None

        self._httpd: _GuiThreadingHTTPServer | None = None
        self._running = False
        self._lock = RLock()

        self._sse_active_clients = 0
        self._sse_retried_writes = 0
        self._sse_dropped_clients = 0
        self._sse_last_error: str | None = None

    def serve_forever(self) -> None:
        handler = build_request_handler(self)
        self._httpd = _GuiThreadingHTTPServer((self.host, self.port), handler)

        with self._lock:
            self._running = True

        self.facade.publish_info(
            f"Web adapter ready at {self.base_url}",
        )

        try:
            self._httpd.serve_forever(poll_interval=0.5)
        finally:
            self.stop()

    def stop(self) -> None:
        with self._lock:
            self._running = False

        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def diagnostics_payload(self) -> dict[str, Any]:
        with self._lock:
            status = "connected" if self._sse_active_clients > 0 else "idle"
            payload = self.facade.diagnostics(
                adapter_metadata=self.metadata,
                base_url=self.base_url,
                event_stream_status=status,
                event_stream_active_clients=self._sse_active_clients,
                event_stream_retried_writes=self._sse_retried_writes,
                event_stream_dropped_clients=self._sse_dropped_clients,
            )
            payload["last_event_stream_error"] = self._sse_last_error
            return payload

    def mark_sse_connected(self) -> None:
        with self._lock:
            self._sse_active_clients += 1

    def mark_sse_disconnected(self) -> None:
        with self._lock:
            self._sse_active_clients = max(0, self._sse_active_clients - 1)

    def mark_sse_retry(self, error: BaseException) -> None:
        with self._lock:
            self._sse_retried_writes += 1
            self._sse_last_error = str(error)

    def mark_sse_drop(self, error: BaseException | None = None) -> None:
        with self._lock:
            self._sse_dropped_clients += 1
            if error is not None:
                self._sse_last_error = str(error)


def build_request_handler(service: SchedulerHttpService) -> type[BaseHTTPRequestHandler]:
    """Bind service instance into a request handler class."""

    class SchedulerRequestHandler(BaseHTTPRequestHandler):
        server_version = "HumanSchedHTTP/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            try:
                if path == "/api/health":
                    self._write_json(
                        {
                            "status": "ok",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    return

                if path == "/api/meta":
                    payload = service.facade.metadata(
                        adapter_metadata=service.metadata,
                        base_url=service.base_url,
                    )
                    self._write_json(payload)
                    return

                if path == "/api/settings":
                    self._write_json(service.facade.app_settings())
                    return

                if path == "/api/diagnostics":
                    self._write_json(service.diagnostics_payload())
                    return

                if path == "/api/life-areas":
                    self._write_json({"items": service.facade.list_life_areas()})
                    return

                if path == "/api/tasks":
                    life_area_id = self._parse_optional_int(query, "life_area_id")
                    urgency_tier = self._first(query, "urgency")
                    state = self._first(query, "state")
                    tasks = service.facade.list_tasks(
                        life_area_id=life_area_id,
                        urgency_tier=urgency_tier,
                        state=state,
                    )
                    self._write_json({"items": tasks})
                    return

                if path == "/api/dispatch":
                    self._write_json({"dispatch": service.facade.current_dispatch()})
                    return

                if path == "/api/events":
                    limit = self._parse_optional_int(query, "limit") or 200
                    self._write_json({"items": service.facade.list_events(limit=limit)})
                    return

                if path == "/api/events/stream":
                    self._handle_sse(query)
                    return

                if service.frontend_redirect_url:
                    target = f"{service.frontend_redirect_url}{self.path}"
                    self.send_response(307)
                    self.send_header("Location", target)
                    self.end_headers()
                    return

                self._serve_static(path)
            except KeyError as exc:
                self._write_error(404, str(exc))
            except ValueError as exc:
                self._write_error(400, str(exc))
            except Exception as exc:  # pragma: no cover - safety net for manual runs
                self._write_error(500, f"Internal error: {exc}")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            try:
                if path == "/api/life-areas":
                    body = self._read_json_body()
                    payload = service.facade.create_life_area(
                        name=str(body.get("name", "")),
                    )
                    self._write_json(payload, status=201)
                    return

                life_area_match = _LIFE_AREA_DELETE_RE.match(path)
                if life_area_match:
                    life_area_id = int(life_area_match.group("life_area_id"))
                    payload = service.facade.delete_life_area(
                        life_area_id=life_area_id,
                    )
                    self._write_json(payload)
                    return

                life_area_rename_match = _LIFE_AREA_RENAME_RE.match(path)
                if life_area_rename_match:
                    body = self._read_json_body()
                    life_area_id = int(life_area_rename_match.group("life_area_id"))
                    payload = service.facade.rename_life_area(
                        life_area_id=life_area_id,
                        name=str(body.get("name", "")),
                    )
                    self._write_json(payload)
                    return

                if path == "/api/tasks":
                    body = self._read_json_body()
                    payload = service.facade.create_task(
                        life_area_id=int(body.get("life_area_id")),
                        title=str(body.get("title", "")),
                        urgency_tier=str(body.get("urgency_tier", "normal")),
                        notes=str(body.get("notes", "")),
                    )
                    self._write_json(payload, status=201)
                    return

                if path == "/api/what-next":
                    payload = service.facade.what_next()
                    self._write_json({"dispatch": payload})
                    return

                if path == "/api/reset":
                    payload = service.facade.reset_simulation()
                    self._write_json(payload)
                    return

                task_match = _TASK_ACTION_RE.match(path)
                if task_match:
                    task_id = int(task_match.group("task_id"))
                    if path.endswith("/pause"):
                        payload = service.facade.pause_task(task_id=task_id)
                    elif path.endswith("/resume"):
                        payload = service.facade.resume_task(task_id=task_id)
                    elif path.endswith("/complete"):
                        payload = service.facade.complete_task(task_id=task_id)
                    else:
                        payload = service.facade.delete_task(task_id=task_id)
                    self._write_json(payload)
                    return

                self._write_error(404, "Unknown endpoint")
            except KeyError as exc:
                self._write_error(404, str(exc))
            except ValueError as exc:
                self._write_error(400, str(exc))
            except TypeError as exc:
                self._write_error(400, f"Invalid request payload: {exc}")
            except Exception as exc:  # pragma: no cover - safety net for manual runs
                self._write_error(500, f"Internal error: {exc}")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Allow", "GET,POST,OPTIONS")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            # Keep test and local runs readable.
            return

        def _handle_sse(self, query: dict[str, list[str]]) -> None:
            after = self._parse_optional_int(query, "after")
            subscriber_id = service.facade.subscribe_events(after_event_id=after)
            service.mark_sse_connected()

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            try:
                self._write_sse_chunk(": connected\n\n")
                while service.is_running:
                    payload = service.facade.next_event(
                        subscriber_id,
                        timeout_seconds=15.0,
                    )
                    if payload is None:
                        if not self._write_sse_chunk(": keep-alive\n\n"):
                            break
                        continue

                    event_lines = [
                        f"id: {payload['event_id']}",
                        f"event: {payload['event_type']}",
                        f"data: {json.dumps(payload, separators=(',', ':'))}",
                        "",
                    ]
                    text = "\n".join(event_lines) + "\n"
                    if not self._write_sse_chunk(text):
                        break
            finally:
                service.facade.unsubscribe_events(subscriber_id)
                service.mark_sse_disconnected()

        def _write_sse_chunk(self, text: str) -> bool:
            data = text.encode("utf-8")
            try:
                self.wfile.write(data)
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError) as exc:
                service.mark_sse_drop(exc)
                return False
            except OSError as exc:
                service.mark_sse_retry(exc)
                try:
                    self.wfile.write(data)
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError, OSError) as retry_exc:
                    service.mark_sse_drop(retry_exc)
                    return False

        def _serve_static(self, path: str) -> None:
            rel = "index.html" if path in {"", "/"} else path.lstrip("/")
            target = (service.static_dir / rel).resolve()

            if service.static_dir not in target.parents and target != service.static_dir:
                self._write_error(404, "File not found")
                return
            if not target.exists() or not target.is_file():
                self._write_error(404, "File not found")
                return

            content_type, _ = mimetypes.guess_type(str(target))
            if content_type is None:
                content_type = "application/octet-stream"

            content = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _read_json_body(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                return {}
            raw = self.rfile.read(content_length)
            if not raw:
                return {}
            decoded = raw.decode("utf-8")
            data = json.loads(decoded)
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        @staticmethod
        def _parse_optional_int(query: dict[str, list[str]], key: str) -> int | None:
            raw = SchedulerRequestHandler._first(query, key)
            if raw is None or raw == "":
                return None
            return int(raw)

        @staticmethod
        def _first(query: dict[str, list[str]], key: str) -> str | None:
            values = query.get(key)
            if not values:
                return None
            return values[0]

        def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _write_error(self, status: int, message: str) -> None:
            payload = {
                "error": {
                    "status": status,
                    "message": message,
                }
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return SchedulerRequestHandler
