"""Read-only local HTTP API for persisted Faultline case files.

The server deliberately opens the explicitly supplied SQLite database in
read-only mode for every request. It never uses ``ArtifactStore`` (which can
create directories/tables), never opens the budget database, and exposes no
mutation or approval endpoints.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _safe_get(self) -> tuple[str, str | None] | None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            return "health", None
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
        route = self._safe_get()
        if route is None:
            self._json(404, {"error": "not_found"})
            return
        kind, case_id = route
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

    def _method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def log_message(self, _format: str, *_args: Any) -> None:
        # Case IDs and query strings are user-controlled; keep the local
        # server quiet rather than logging potentially sensitive request data.
        return


class _CaseHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], db_path: Path) -> None:
        super().__init__(address, _APIHandler)
        self.db_path = db_path


def make_server(db: str | Path, *, host: str = "127.0.0.1", port: int = 8765) -> _CaseHTTPServer:
    """Validate and construct the loopback-only read-only API server."""
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
