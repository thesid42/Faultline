"""Bounded asynchronous investigation jobs owned by the local API server."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import threading
from typing import Any, Callable
from uuid import uuid4

from .config import load_config
from .live import LLAMA_31_8B_INSTRUCT
from .models import CaseFile, EvidenceOrigin
from .storage import ArtifactStore
from .workflow import run_demo

PROFILES = ("memory-conflict", "amount-unit", "duplicate-refund")
MODES = ("simulated", "live")
_SAFE_EXCEPTION = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


class InvestigationActive(RuntimeError):
    """A different API investigation currently owns the one active slot."""

    def __init__(self, case_id: str) -> None:
        super().__init__(case_id)
        self.case_id = case_id


class RequestConflict(RuntimeError):
    """An idempotency key was reused with different immutable input."""


@dataclass(frozen=True)
class InvestigationRequest:
    request_id: str
    profile: str
    mode: str
    jev: bool

    def as_payload(self) -> dict[str, Any]:
        return {"profile": self.profile, "mode": self.mode, "jev": self.jev}


class InvestigationJobManager:
    """Persist API ownership and run at most one local investigation thread."""

    def __init__(self, db_path: str | Path, *, runner: Callable[..., Any] | None = None) -> None:
        self.db_path = Path(db_path).resolve()
        self.runner = runner or run_demo
        self._lock = threading.RLock()
        self._active_case_id: str | None = None
        self._records: dict[str, dict[str, Any]] = {}
        self.csrf_token = secrets.token_urlsafe(24)
        self._load_and_interrupt()

    @property
    def active_case_id(self) -> str | None:
        with self._lock:
            return self._active_case_id

    def capabilities(self) -> dict[str, Any]:
        config = load_config()
        live_available = bool(config.openrouter_api_key.strip())
        return {
            "profiles": list(PROFILES),
            "modes": list(MODES),
            "allowed_profiles": list(PROFILES),
            "allowed_modes": list(MODES),
            "target_model": LLAMA_31_8B_INSTRUCT,
            "live_available": live_available,
            "live_unavailable_reason": None if live_available else "OPENROUTER_API_KEY is not configured",
            "jev_available": bool(config.typesafe_api_key.strip()),
            "daytona_configured": bool(config.daytona_api_key.strip()),
            "execution_backend": "local-subprocess",
            "active_case_id": self.active_case_id,
            "csrf_token": self.csrf_token,
        }

    @staticmethod
    def _record_id(request_id: str) -> str:
        return f"ui-request-{request_id}"

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _load_and_interrupt(self) -> None:
        """Recover idempotency records without resuming interrupted work."""
        with ArtifactStore(self.db_path) as store:
            for record in store.list("ui_request"):
                if record.get("owner") != "faultline-api" or not isinstance(record.get("request_id"), str):
                    continue
                request_id = record["request_id"]
                self._records[request_id] = record
                case_id = record.get("case_id")
                case = store.get("case_file", str(case_id)) if case_id else None
                if isinstance(case, dict) and case.get("status") in {"queued", "investigating"}:
                    case["status"] = "inconclusive"
                    case["stop_reason"] = "inconclusive:api_restart"
                    store.put("case_file", case, str(case_id))
                    record["status"] = "inconclusive"
                    record["stop_reason"] = "inconclusive:api_restart"
                    store.put("ui_request", record, self._record_id(request_id))

    def _persist_request(self, request: InvestigationRequest, case_id: str, status: str) -> None:
        record = {
            "owner": "faultline-api",
            "request_id": request.request_id,
            "case_id": case_id,
            "payload": request.as_payload(),
            "status": status,
        }
        self._records[request.request_id] = record
        with ArtifactStore(self.db_path) as store:
            store.put("ui_request", record, self._record_id(request.request_id))

    def _persist_queued_case(self, request: InvestigationRequest, case_id: str) -> None:
        case = CaseFile(
            case_id=case_id,
            demo_profile=request.profile,
            status="queued",
            backend="local-subprocess",
            evidence_origin=EvidenceOrigin.LIVE if request.mode == "live" else EvidenceOrigin.SIMULATED,
        )
        record = {
            "owner": "faultline-api",
            "request_id": request.request_id,
            "case_id": case_id,
            "payload": request.as_payload(),
            "status": "queued",
        }
        with ArtifactStore(self.db_path) as store:
            # Both records are written before the worker is dispatched. The
            # request record makes retries safe across API restarts.
            store.put("case_file", case, case.case_id)
            store.put("ui_request", record, self._record_id(request.request_id))
        self._records[request.request_id] = record

    def _current_status(self, case_id: str) -> str:
        with ArtifactStore(self.db_path) as store:
            case = store.get("case_file", case_id)
        # A request record without its case is an interrupted/unknown job,
        # never a reason to launch another worker on an idempotent retry.
        return str(case.get("status", "queued")) if isinstance(case, dict) else "inconclusive"

    def submit(self, request: InvestigationRequest) -> tuple[str, str]:
        with self._lock:
            existing = self._records.get(request.request_id)
            if existing is not None:
                if existing.get("payload") != request.as_payload():
                    raise RequestConflict("request_id already has a different payload")
                case_id = str(existing["case_id"])
                return case_id, self._current_status(case_id)
            if self._active_case_id is not None:
                raise InvestigationActive(self._active_case_id)
            case_id = uuid4().hex
            self._persist_queued_case(request, case_id)
            self._active_case_id = case_id
            thread = threading.Thread(target=self._run, args=(request, case_id), name=f"faultline-investigation-{case_id[:8]}", daemon=True)
            try:
                thread.start()
            except Exception as exc:  # noqa: BLE001 - sanitized startup boundary
                # Persist a terminal state even if thread creation is denied
                # by the host, and release the single active slot.
                self._persist_failure(request, case_id, exc)
                record = self._records.get(request.request_id)
                if record is not None:
                    record["status"] = "inconclusive"
                    record["stop_reason"] = f"inconclusive:api_job_failure:{self._safe_error_type(exc)}"
                    with ArtifactStore(self.db_path) as store:
                        store.put("ui_request", record, self._record_id(request.request_id))
                self._active_case_id = None
                return case_id, "inconclusive"
            return case_id, "queued"

    @staticmethod
    def _safe_error_type(exc: BaseException) -> str:
        error_type = type(exc).__name__
        return error_type if _SAFE_EXCEPTION.fullmatch(error_type) else "Error"

    def _persist_failure(self, request: InvestigationRequest, case_id: str, exc: BaseException) -> None:
        error_type = self._safe_error_type(exc)
        with ArtifactStore(self.db_path) as store:
            existing = store.get("case_file", case_id)
            if isinstance(existing, dict):
                existing["status"] = "inconclusive"
                existing["stop_reason"] = f"inconclusive:api_job_failure:{error_type}"
                store.put("case_file", existing, case_id)
            else:
                case = CaseFile(
                    case_id=case_id,
                    demo_profile=request.profile,
                    status="inconclusive",
                    stop_reason=f"inconclusive:api_job_failure:{error_type}",
                    backend="local-subprocess",
                    evidence_origin=EvidenceOrigin.LIVE if request.mode == "live" else EvidenceOrigin.SIMULATED,
                )
                store.put("case_file", case, case.case_id)

    def _run(self, request: InvestigationRequest, case_id: str) -> None:
        try:
            with self._lock:
                record = self._records.get(request.request_id)
                if record is not None:
                    record["status"] = "investigating"
                    with ArtifactStore(self.db_path) as store:
                        store.put("ui_request", record, self._record_id(request.request_id))
            kwargs: dict[str, Any] = {
                "profile": request.profile,
                "db": self.db_path,
                "jev": request.jev,
                "backend": "local",
                "case_id": case_id,
            }
            if request.mode == "live":
                kwargs.update({"live": True, "target_model": LLAMA_31_8B_INSTRUCT})
            result = self.runner(**kwargs)
            status = str(getattr(getattr(result, "case", None), "status", "inconclusive"))
            with self._lock:
                record = self._records.get(request.request_id)
                if record is not None:
                    record["status"] = status
                    with ArtifactStore(self.db_path) as store:
                        store.put("ui_request", record, self._record_id(request.request_id))
        except Exception as exc:  # noqa: BLE001 - sanitized failure boundary
            self._persist_failure(request, case_id, exc)
            with self._lock:
                record = self._records.get(request.request_id)
                if record is not None:
                    record["status"] = "inconclusive"
                    record["stop_reason"] = f"inconclusive:api_job_failure:{type(exc).__name__ if _SAFE_EXCEPTION.fullmatch(type(exc).__name__) else 'Error'}"
                    with ArtifactStore(self.db_path) as store:
                        store.put("ui_request", record, self._record_id(request.request_id))
        finally:
            with self._lock:
                if self._active_case_id == case_id:
                    self._active_case_id = None
