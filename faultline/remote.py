"""Optional TypeSafe Jev and Daytona execution adapters.

SDKs are imported lazily so offline tests remain network-free. Daytona is an
execution boundary for trusted, fixed worker files only; model output is data
and is never evaluated as code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol

from .models import Hypothesis


class ExperimentBackend(Protocol):
    backend_name: str
    def run_trial(self, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]: ...


class TriageBackend(Protocol):
    def triage(self, *, state: dict[str, Any], questions: dict[str, str]) -> dict[str, Any]: ...


@dataclass
class DaytonaConfig:
    snapshot: str | None = None
    max_active: int = 2
    auto_stop_minutes: int = 5
    ttl_minutes: int = 10
    api_key: str | None = field(default=None, repr=False)
    api_url: str | None = field(default=None, repr=False)


def _safe_remote_path(path: str) -> str:
    candidate = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or candidate.is_absolute()
        or ".." in candidate.parts
        or any(part == ".git" or part == ".env" or part.endswith(".env") for part in candidate.parts)
    ):
        raise ValueError("unsafe sandbox package path")
    return "/faultline_app/" + str(candidate)


def _json_safe(value: Any) -> Any:
    """Recursively convert SDK/Pydantic answer objects into JSON data."""
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


FIXED_WORKER_SOURCE = b'''"""Faultline fixed worker; input is data, never executable code."""\nimport json\nfrom pathlib import Path\nfrom faultline_worker_entry import main\nrequest = json.loads(Path("request.json").read_text())\nresult = main(request)\nPath("result.json").write_text(json.dumps(result, sort_keys=True))\n'''


@dataclass
class DaytonaRunner:
    """Run the trusted fixed worker in a fresh Daytona sandbox.

    ``command_env`` is supplied by the parent for one process invocation only;
    it is never uploaded to the sandbox filesystem or persisted in artifacts.
    """
    client: Any | None = field(default=None, repr=False)
    config: DaytonaConfig | None = None
    command_env: Mapping[str, str] | None = field(default=None, repr=False)
    backend_name: str = "daytona"

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = DaytonaConfig()

    def _daytona(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            from daytona import Daytona, DaytonaConfig as SDKDaytonaConfig
        except ImportError as exc:
            raise RuntimeError("daytona_sdk_unavailable") from exc
        kwargs: dict[str, Any] = {}
        if self.config and self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config and self.config.api_url:
            kwargs["api_url"] = self.config.api_url
        return Daytona(SDKDaytonaConfig(**kwargs))

    def run_trial(self, payload: dict[str, Any], *, timeout_seconds: int = 120) -> dict[str, Any]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        daytona = self._daytona()
        sandbox = None
        try:
            try:
                from daytona import CreateSandboxFromSnapshotParams
            except ImportError as exc:
                raise RuntimeError("daytona_sdk_unavailable") from exc
            cfg = self.config or DaytonaConfig()
            kwargs: dict[str, Any] = {"language": "python", "auto_stop_interval": cfg.auto_stop_minutes, "auto_delete_interval": cfg.ttl_minutes}
            if cfg.snapshot:
                kwargs["snapshot"] = cfg.snapshot
            sandbox = daytona.create(CreateSandboxFromSnapshotParams(**kwargs), timeout=timeout_seconds)
            if hasattr(sandbox, "set_ttl"):
                sandbox.set_ttl(cfg.ttl_minutes)

            # Only trusted app files, this fixed worker, and request JSON are
            # uploaded. Never upload .env, git metadata, a workspace, or
            # model-generated code.
            app_package = payload.get("app_package", {})
            if not isinstance(app_package, Mapping):
                raise ValueError("app_package must be a mapping of trusted files")
            if "faultline_worker_entry.py" not in app_package:
                raise ValueError("trusted app package must include faultline_worker_entry.py")
            work_dir = sandbox.get_work_dir()
            app_root = work_dir.rstrip("/") + "/faultline_app"
            sandbox.fs.create_folder(app_root, "755", request_timeout=timeout_seconds)
            sandbox.fs.upload_file(FIXED_WORKER_SOURCE, app_root + "/worker.py", timeout=timeout_seconds)
            request = {"case": payload.get("case"), "trial": payload.get("trial"), "input": payload.get("input")}
            sandbox.fs.upload_file(json.dumps(request, sort_keys=True).encode(), app_root + "/request.json", timeout=timeout_seconds)
            for name, content in app_package.items():
                if not isinstance(name, str) or not isinstance(content, (bytes, bytearray)):
                    raise ValueError("trusted app package must map string paths to bytes")
                _safe_remote_path(name)
                package_path = PurePosixPath(name)
                if str(package_path) in {"worker.py", "request.json", "result.json"}:
                    raise ValueError("trusted app package cannot overwrite fixed worker artifacts")
                parent = PurePosixPath(app_root)
                for part in package_path.parts[:-1]:
                    parent /= part
                    sandbox.fs.create_folder(str(parent), "755", request_timeout=timeout_seconds)
                sandbox.fs.upload_file(bytes(content), app_root + "/" + str(package_path), timeout=timeout_seconds)

            result = sandbox.process.exec(
                "python worker.py",
                cwd=app_root,
                env=dict(self.command_env or {}),
                timeout=timeout_seconds,
            )
            exit_code = getattr(result, "exit_code", None)
            if exit_code != 0:
                raise RuntimeError(f"daytona_worker_exit_{exit_code}")
            output = sandbox.fs.download_file(app_root + "/result.json", timeout_seconds)
            if isinstance(output, bytes):
                output = output.decode("utf-8")
            return {"sandbox_id": getattr(sandbox, "id", "unknown"), "result": json.loads(output), "backend": self.backend_name}
        finally:
            if sandbox is not None:
                try:
                    daytona.delete(sandbox, wait=True, timeout=timeout_seconds)
                except Exception as exc:
                    raise RuntimeError(f"daytona_cleanup_{type(exc).__name__}") from None


class TypeSafeJevBackend:
    """Thin lazy TypeSafe SDK adapter for one atomic Jev request."""
    backend_name = "typesafe"

    def __init__(self, *, api_key: str | None = None, client: Any | None = None, model: str = "jev-1.13.0", timeout: float = 60.0) -> None:
        self.api_key = api_key or os.getenv("TYPESAFE_API_KEY")
        self.client = client
        self.model = model
        self.timeout = timeout
        self.last_response: Any | None = None

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            from typesafe_sdk import RetryPolicy, TypeSafeClient
        except ImportError as exc:
            raise RuntimeError("typesafe_sdk_unavailable") from exc
        if not self.api_key:
            raise RuntimeError("TYPESAFE_API_KEY is required for Jev")
        self.client = TypeSafeClient(api_key=self.api_key, retry=RetryPolicy(max_retries=0, timeout=self.timeout), timeout=self.timeout)
        return self.client

    def triage(self, *, state: dict[str, Any], questions: dict[str, str]) -> dict[str, Any]:
        try:
            from typesafe_sdk import Noul
        except ImportError as exc:
            raise RuntimeError("typesafe_sdk_unavailable") from exc
        nouls = {key: Noul(instructions=value) for key, value in questions.items()}
        response = self._client().system_one(state=state, questions=nouls, model=self.model)
        self.last_response = response
        answers = getattr(response, "answers", None)
        usage = getattr(response, "usage", None)
        response_dump = response.model_dump(mode="json") if hasattr(response, "model_dump") else {}
        if isinstance(response_dump, dict):
            answers = response_dump.get("answers", answers)
            usage_dump = response_dump.get("usage", {})
            response_model = response_dump.get("model", getattr(response, "model", self.model))
        else:
            usage_dump = {}
            response_model = getattr(response, "model", self.model)
        input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
        output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
        if isinstance(usage_dump, dict):
            input_tokens = usage_dump.get("input_tokens", input_tokens)
            output_tokens = usage_dump.get("output_tokens", output_tokens)
        try:
            cost_usd = float(input_tokens) * 0.042 / 1_000_000 if input_tokens is not None else None
            if cost_usd is not None and (cost_usd < 0 or not math.isfinite(cost_usd)):
                cost_usd = None
        except (TypeError, ValueError):
            cost_usd = None
        return {
            "model": response_model,
            "answers": _json_safe(answers),
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            },
        }


DEFAULT_JEV_QUESTIONS = {
    "note_contradicts_policy": "Does any customer note contradict the current return policy max-age rule?",
    "note_is_historical": "Does the customer note describe historical guidance rather than a current exception?",
    "amount_unit_mismatch": "Based only on supplied gateway/order/execute trace fields, is there evidence that a refund amount or API unit was converted incorrectly?",
    "retry_idempotency_effect": "Based only on supplied gateway/order/execute trace fields, is there evidence that delivery retries or idempotency handling produced a repeated refund effect?",
}


@dataclass
class OptionalJevTriage:
    backend: TriageBackend
    model_version: str = "jev-1.13.0"
    ledger: Any | None = None
    max_cost_usd: float = 0.003
    case_id: str | None = None

    def triage(self, hypotheses: list[Hypothesis], evidence: dict[str, Any]) -> dict[str, Any] | None:
        if not hypotheses:
            return None
        questions = dict(DEFAULT_JEV_QUESTIONS)
        state = {"evidence": evidence, "hypotheses": [item.model_dump(mode="json") for item in hypotheses]}
        # TypeSafe's documented bound is 32K state plus the longest question.
        # Refuse an oversized request before reserving or dispatching anything.
        state_bytes = len(json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        longest_question = max((len(question.encode("utf-8")) for question in questions.values()), default=0)
        if state_bytes + longest_question > 32_000:
            return None
        reservation = None
        try:
            if self.ledger is not None:
                reservation = self.ledger.reserve(self.max_cost_usd, category="jev", case_id=self.case_id)
                dispatch_token = f"jev:{id(self)}:{reservation.reservation_id}"
                self.ledger.claim(reservation.reservation_id, dispatch_token)
            output = self.backend.triage(state=state, questions=questions)
            usage = output.get("usage") if isinstance(output, dict) else None
            usage = usage if isinstance(usage, dict) else {}
            cost = usage.get("cost_usd", usage.get("cost"))
            if reservation is not None:
                self.ledger.reconcile(reservation.reservation_id, cost, usage_available=cost is not None, dispatch_token=dispatch_token)
        except Exception:
            if reservation is not None:
                self.ledger.reconcile(reservation.reservation_id, None, usage_available=False, dispatch_token=dispatch_token)
            return None
        return {
            "questions": questions,
            "event_ids": [event.get("event_id") for event in evidence.get("events", []) if isinstance(event, dict)],
            "outputs": output,
            "model_version": output.get("model", self.model_version) if isinstance(output, dict) else self.model_version,
        }
