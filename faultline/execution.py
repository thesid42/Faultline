"""Parent/child target execution boundary.

The parent owns grants and the persistent ledger. This module deliberately
does not open or mutate a ledger in a child: it serializes an immutable grant,
executes the fixed worker once, and returns the worker's ``RunRecord`` and
provider receipt for parent reconciliation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from .models import RunRecord, Scenario
from .remote import DaytonaRunner
from .worker import OneCallGrant


SUPPORTED_PROVIDERS = frozenset({"deepinfra", "groq", "nvidia", "openrouter"})
TRUSTED_ENTRY_SOURCE = b"from faultline.sandbox_worker import main\n"
TRUSTED_MODULES = (
    "faultline/__init__.py",
    "faultline/budget.py",
    "faultline/clock.py",
    "faultline/execution.py",
    "faultline/live.py",
    "faultline/models.py",
    "faultline/remote.py",
    "faultline/return_desk.py",
    "faultline/sandbox_worker.py",
    "faultline/worker.py",
)


class ExecutionError(RuntimeError):
    """Safe child execution failure; no child traceback or credential is exposed."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    run_record: RunRecord | None
    receipt: dict[str, Any] | None
    backend: str
    sandbox_id: str | None = None
    error: str | None = None

    @property
    def run(self) -> RunRecord | None:
        return self.run_record

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_record": self.run_record.model_dump(mode="json") if self.run_record is not None else None,
            "receipt": self.receipt,
            "backend": self.backend,
            "sandbox_id": self.sandbox_id,
            "error": self.error,
        }


def validate_execution_result(
    result: ExecutionResult,
    grant: OneCallGrant,
    scenario: Scenario,
    *,
    configuration_id: str = "default",
    fixture_partition: str = "main",
    source_run_id: str | None = None,
) -> None:
    """Fail closed before a parent stores evidence or settles a receipt."""
    if result.receipt is not None and result.receipt.get("reservation_id") != grant.reservation_id:
        raise ExecutionError("target receipt does not match parent grant")
    run = result.run_record
    if run is None:
        return
    if run.scenario.model_dump(mode="json") != scenario.model_dump(mode="json"):
        raise ExecutionError("target run scenario does not match executed request")
    if run.configuration_id != configuration_id or run.fixture_partition != fixture_partition or run.source_run_id != source_run_id:
        raise ExecutionError("target run provenance does not match executed request")


def grant_payload(grant: OneCallGrant) -> dict[str, Any]:
    """Serialize only immutable grant fields; no credential or ledger path."""
    return asdict(grant)


def build_trusted_package(project_root: str | os.PathLike[str] | None = None) -> dict[str, bytes]:
    """Build the minimal static Python package needed by the fixed worker."""
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    package = {relative: (root / relative).read_bytes() for relative in TRUSTED_MODULES}
    package["faultline_worker_entry.py"] = TRUSTED_ENTRY_SOURCE
    return package


def execution_payload(
    grant: OneCallGrant,
    scenario: Scenario,
    *,
    configuration_id: str = "default",
    fixture_partition: str = "main",
    source_run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "grant": grant_payload(grant),
        "scenario": scenario.model_dump(mode="json"),
        "configuration_id": configuration_id,
        "fixture_partition": fixture_partition,
        "source_run_id": source_run_id,
    }


class TargetExecutionBoundary:
    """Execute one granted target call through a killable fixed worker."""

    def __init__(
        self,
        *,
        backend: str = "local-subprocess",
        timeout_seconds: int = 120,
        daytona_runner: DaytonaRunner | None = None,
        trusted_package: Mapping[str, bytes] | None = None,
        project_root: str | os.PathLike[str] | None = None,
    ) -> None:
        if backend not in {"local-subprocess", "daytona"}:
            raise ValueError("unsupported execution backend")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.backend = backend
        self.timeout_seconds = timeout_seconds
        self.daytona_runner = daytona_runner
        self.trusted_package = dict(trusted_package) if trusted_package is not None else build_trusted_package(project_root)
        self.project_root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]

    @staticmethod
    def _validate_grant(grant: OneCallGrant) -> None:
        if grant.provider not in SUPPORTED_PROVIDERS:
            raise ValueError("unsupported target provider")
        if not grant.model or not grant.reservation_id or not grant.request_id:
            raise ValueError("incomplete immutable target grant")

    @staticmethod
    def _command_env(command_env: Mapping[str, str] | None) -> dict[str, str]:
        # Daytona receives only explicitly supplied values; the sandbox owns
        # its own PATH and runtime environment.
        return {str(key): str(value) for key, value in (command_env or {}).items()}

    @staticmethod
    def _local_env(command_env: Mapping[str, str] | None) -> dict[str, str]:
        safe_inherited = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG") if key in os.environ}
        safe_inherited.update({str(key): str(value) for key, value in (command_env or {}).items()})
        return safe_inherited

    def execute(
        self,
        grant: OneCallGrant,
        scenario: Scenario,
        *,
        command_env: Mapping[str, str] | None = None,
        configuration_id: str = "default",
        fixture_partition: str = "main",
        source_run_id: str | None = None,
    ) -> ExecutionResult:
        self._validate_grant(grant)
        payload = execution_payload(
            grant,
            scenario,
            configuration_id=configuration_id,
            fixture_partition=fixture_partition,
            source_run_id=source_run_id,
        )
        if self.backend == "daytona":
            return self._execute_daytona(payload, command_env=command_env)
        return self._execute_local(payload, command_env=command_env)

    def _execute_local(self, payload: dict[str, Any], *, command_env: Mapping[str, str] | None) -> ExecutionResult:
        env = self._local_env(command_env)
        process = subprocess.Popen(
            [sys.executable, "-m", "faultline.sandbox_worker"],
            cwd=str(self.project_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            stdout, _stderr = process.communicate(json.dumps(payload, sort_keys=True), timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.communicate()
            except subprocess.TimeoutExpired:
                pass
            raise ExecutionError("target_worker_timeout") from None
        if process.returncode != 0:
            raise ExecutionError(f"target_worker_exit_{process.returncode}")
        try:
            output = json.loads(stdout)
        except (TypeError, json.JSONDecodeError):
            raise ExecutionError("target_worker_invalid_json") from None
        return self._result_from_output(output, backend="local-subprocess")

    def _execute_daytona(self, payload: dict[str, Any], *, command_env: Mapping[str, str] | None) -> ExecutionResult:
        runner = self.daytona_runner
        if runner is None:
            raise ExecutionError("daytona_runner_required")
        package = dict(self.trusted_package)
        package.setdefault("faultline_worker_entry.py", TRUSTED_ENTRY_SOURCE)
        # The runner receives the command environment for this single child
        # invocation. It is not serialized into ``payload`` or package files.
        runner.command_env = self._command_env(command_env)
        remote_output = runner.run_trial(
            {
                "case": payload.get("configuration_id"),
                "trial": payload,
                "input": payload,
                "app_package": package,
            },
            timeout_seconds=self.timeout_seconds,
        )
        result = remote_output.get("result") if isinstance(remote_output, dict) else None
        output = result if isinstance(result, dict) else remote_output
        parsed = self._result_from_output(output, backend="daytona")
        return ExecutionResult(parsed.run_record, parsed.receipt, "daytona", str(remote_output.get("sandbox_id")) if isinstance(remote_output, dict) else None, parsed.error)

    @staticmethod
    def _result_from_output(output: Any, *, backend: str) -> ExecutionResult:
        if not isinstance(output, dict):
            raise ExecutionError("target_worker_invalid_result")
        error = output.get("error")
        run_payload = output.get("run_record")
        try:
            run = RunRecord.model_validate(run_payload) if run_payload is not None else None
        except Exception:
            raise ExecutionError("target_worker_invalid_run_record") from None
        receipt = output.get("receipt")
        if receipt is not None and not isinstance(receipt, dict):
            raise ExecutionError("target_worker_invalid_receipt")
        return ExecutionResult(run, receipt, backend, None, str(error) if error else None)
