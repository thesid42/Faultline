"""Local HTTP API for persisted Faultline case files and queued investigations.

GET requests deliberately open the explicitly supplied SQLite database in
read-only mode. Mutation endpoints are CSRF-guarded: investigation queue and
case deletion. There are no approval, export, arbitrary command, or
client-selected model/path endpoints.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .jobs import InvestigationActive, InvestigationJobManager, InvestigationRequest, MODES, PROFILES, RequestConflict


_CASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _database_uri(path: Path) -> str:
    """Build a read-only SQLite URI for an already validated local path."""
    return f"file:{path.resolve().as_posix()}?mode=ro"


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(_database_uri(path), uri=True, timeout=2.0)


class _APIHandler(BaseHTTPRequestHandler):
    server: "_CaseHTTPServer"

    def _json(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        # Requests rejected before their body is consumed must not leave a
        # persistent connection with unread bytes for the next parser pass.
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def _host_allowed(self) -> bool:
        value = self.headers.get("Host", "")
        if not value or ":" not in value:
            host, port_text = value.lower(), "80"
        else:
            host, port_text = value.rsplit(":", 1)
            host = host.lower()
        if host not in {"127.0.0.1", "localhost"}:
            return False
        try:
            port = int(port_text)
        except ValueError:
            return False
        return port in {8765, 5173, self.server.server_port}

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return False
        try:
            parsed = urlsplit(origin)
            # Do not accept credentials, query/fragment smuggling, or an
            # invalid bracket/port expression in an Origin header.
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.path not in {"", "/"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                return False
            port = parsed.port or 80
        except (TypeError, ValueError):
            return False
        return port in {8765, 5173, self.server.server_port}

    def _safe_get(self) -> tuple[str, str | None] | None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            return "health", None
        if path == "/api/capabilities":
            return "capabilities", None
        if path == "/api/cases":
            return "cases", None
        prefix = "/api/cases/"
        if path.startswith(prefix):
            case_id = path[len(prefix):]
            # IDs are database keys, not paths. Reject traversal, separators,
            # empty IDs, and encoded values outside the storage key alphabet.
            if case_id and _CASE_ID.fullmatch(case_id):
                return "case", case_id
        return None

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._host_allowed():
            self._json(403, {"error": "host_not_allowed"})
            return
        route = self._safe_get()
        if route is None:
            self._json(404, {"error": "not_found"})
            return
        kind, case_id = route
        if kind == "capabilities":
            self._json(200, self.server.jobs.capabilities())
            return
        try:
            with _connect_read_only(self.server.db_path) as db:
                if kind == "health":
                    db.execute("SELECT 1").fetchone()
                    self._json(200, {"status": "ok"})
                    return
                if kind == "cases":
                    rows = db.execute(
                        "SELECT artifact_id, payload, created_at FROM artifacts WHERE kind=? ORDER BY created_at, artifact_id",
                        ("case_file",),
                    ).fetchall()
                    summaries: list[dict[str, Any]] = []
                    for artifact_id, payload_text, created_at in rows:
                        payload = json.loads(payload_text)
                        summaries.append(
                            {
                                "caseid": str(payload.get("case_id") or artifact_id),
                                "status": payload.get("status"),
                                "profile": payload.get("demo_profile"),
                                "evidence_origin": payload.get("evidence_origin"),
                                "createdtime": created_at,
                            }
                        )
                    self._json(200, {"cases": summaries})
                    return
                row = db.execute(
                    "SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?",
                    ("case_file", case_id),
                ).fetchone()
                if row is None:
                    self._json(404, {"error": "case_not_found"})
                    return
                payload = json.loads(row[0])
                if not isinstance(payload, dict):
                    self._json(500, {"error": "case_unavailable"})
                    return
                self._json(200, payload)
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
            # Do not return database paths, SQL details, or stored payloads.
            self._json(500, {"error": "database_unavailable"})

    def _method_not_allowed(self, *, allow: str = "GET") -> None:
        self.send_response(405)
        self.send_header("Allow", allow)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _mutation_guard(self) -> bool:
        if not self._host_allowed() or not self._origin_allowed():
            self._json(403, {"error": "origin_or_host_not_allowed"})
            return False
        if not secrets.compare_digest(self.headers.get("X-Faultline-Token", ""), self.server.jobs.csrf_token):
            self._json(403, {"error": "token_required"})
            return False
        return True

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if urlsplit(self.path).path != "/api/investigations":
            self._method_not_allowed(allow="GET, DELETE")
            return
        if not self._mutation_guard():
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(415, {"error": "application_json_required"})
            return
        content_length = self.headers.get("Content-Length")
        try:
            length = int(content_length) if content_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self._json(411, {"error": "content_length_required"})
            return
        if length > 4096:
            self._json(413, {"error": "request_too_large"})
            return
        try:
            # Avoid waiting indefinitely for a declared body from a client
            # that never sends it. The declared size is already bounded.
            self.connection.settimeout(2.0)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete body")
            payload = json.loads(body.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._json(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, dict) or set(payload) != {"profile", "mode", "jev", "request_id"}:
            self._json(400, {"error": "invalid_investigation_schema"})
            return
        request_id = payload.get("request_id")
        try:
            from uuid import UUID

            parsed_id = UUID(request_id) if isinstance(request_id, str) else None
        except (ValueError, AttributeError):
            parsed_id = None
        if parsed_id is None or str(parsed_id) != request_id:
            self._json(400, {"error": "request_id_must_be_uuid"})
            return
        if payload.get("profile") not in PROFILES or payload.get("mode") not in MODES or type(payload.get("jev")) is not bool:
            self._json(400, {"error": "invalid_investigation_schema"})
            return
        request = InvestigationRequest(request_id=request_id, profile=payload["profile"], mode=payload["mode"], jev=payload["jev"])
        try:
            case_id, status = self.server.jobs.submit(request)
        except RequestConflict:
            self._json(409, {"error": "request_id_conflict"})
            return
        except InvestigationActive as exc:
            self._json(409, {"error": "investigation_active", "active_case_id": exc.case_id})
            return
        except Exception:  # noqa: BLE001 - do not expose storage/thread details
            # The job manager persists its idempotency record before dispatch;
            # an unexpected failure therefore remains safe to retry by key,
            # while the response contains no path, exception, or credential.
            self._json(500, {"error": "investigation_unavailable"})
            return
        self._json(202, {"case_id": case_id, "status": status})

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed(allow="GET, DELETE")

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed(allow="GET, DELETE")

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        route = self._safe_get()
        if route is None or route[0] != "case" or not route[1]:
            self._method_not_allowed(allow="GET, POST")
            return
        if not self._mutation_guard():
            return
        case_id = route[1]
        if self.server.jobs.active_case_id == case_id:
            self._json(409, {"error": "investigation_active", "active_case_id": case_id})
            return
        try:
            from .storage import ArtifactStore

            with ArtifactStore(self.server.db_path) as store:
                deleted = store.delete_case(case_id)
            if deleted:
                self.server.jobs.forget_case(case_id)
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
            self._json(500, {"error": "database_unavailable"})
            return
        if not deleted:
            self._json(404, {"error": "case_not_found"})
            return
        self._json(200, {"deleted": True, "case_id": case_id})

    def log_message(self, _format: str, *_args: Any) -> None:
        # Case IDs and query strings are user-controlled; keep the local
        # server quiet rather than logging potentially sensitive request data.
        return


class _CaseHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], db_path: Path) -> None:
        super().__init__(address, _APIHandler)
        self.db_path = db_path
        self.jobs = InvestigationJobManager(db_path)


def make_server(db: str | Path, *, host: str = "127.0.0.1", port: int = 8765) -> _CaseHTTPServer:
    """Validate and construct the loopback-only case and investigation API."""
    path = Path(db).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("database file does not exist")
    if host != "127.0.0.1":
        raise ValueError("API must bind to 127.0.0.1")
    return _CaseHTTPServer((host, port), path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m faultline.api")
    parser.add_argument("--db", required=True, help="existing Faultline SQLite case database")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.db)
    except (FileNotFoundError, ValueError):
        parser.error("--db must name an existing case database")
    print("Faultline API listening on http://127.0.0.1:8765", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI invocation
    raise SystemExit(main())
