from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from faultline.execution import (
    ExecutionError,
    ExecutionResult,
    TargetExecutionBoundary,
    build_trusted_package,
    validate_execution_result,
)
from faultline.models import RunRecord, Scenario
from faultline.sandbox_worker import GrantedOpenRouterProvider, execute_request
from faultline.worker import OneCallGrant


def _grant(*, provider="nvidia"):
    return OneCallGrant(
        grant_id="grant-1",
        reservation_id="reservation-1",
        request_id="request-1",
        model="nvidia/nemotron-3-super-120b-a12b:free",
        provider=provider,
        max_cost_usd=0.0,
        max_prompt_tokens=1024,
        max_output_tokens=64,
    )


def _scenario():
    return Scenario(order_id="order-1", customer_id="customer-1", order_age_days=21, amount=12.0)


def test_granted_provider_never_opens_a_ledger():
    provider = GrantedOpenRouterProvider(_grant(), api_key="secret")
    reservation = provider._reserve()
    assert reservation.reservation_id == "reservation-1"
    provider._settle(None, None)
    assert provider.grant.reservation_id == "reservation-1"
    with pytest.raises(RuntimeError):
        provider._reserve()


def test_trusted_package_contains_fixed_entry_and_dependencies():
    package = build_trusted_package()
    assert package["faultline_worker_entry.py"] == b"from faultline.sandbox_worker import main\n"
    assert "faultline/sandbox_worker.py" in package
    assert "faultline/clock.py" in package


def test_worker_entry_returns_run_record_and_receipt_without_ledger(monkeypatch):
    def fake_request(self, messages, response_format):
        from faultline.live import CallReceipt

        self.last_receipt = CallReceipt("provider-request", self.model, "nvidia", 4, 3, 0.0, None)
        return {"kind": "deny", "order_id": "order-1", "amount": None, "reason": "bounded", "idempotency_key": "deny:order-1"}

    monkeypatch.setattr(GrantedOpenRouterProvider, "_request", fake_request)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    result = execute_request({"grant": asdict(_grant()), "scenario": _scenario().model_dump(mode="json")})
    assert result["run_record"]["backend"] == "openrouter-child"
    assert result["receipt"]["request_id"] == "provider-request"


def test_parent_validation_binds_receipt_and_run_provenance():
    scenario = _scenario()
    result = ExecutionResult(
        RunRecord(scenario=scenario, configuration_id="suspect", fixture_partition="seed", source_run_id="source-1"),
        {"reservation_id": "reservation-1"},
        "local-subprocess",
    )
    validate_execution_result(
        result,
        _grant(),
        scenario,
        configuration_id="suspect",
        fixture_partition="seed",
        source_run_id="source-1",
    )

    with pytest.raises(ExecutionError, match="receipt"):
        validate_execution_result(
            ExecutionResult(result.run_record, {"reservation_id": "other"}, "local-subprocess"),
            _grant(),
            scenario,
            configuration_id="suspect",
            fixture_partition="seed",
            source_run_id="source-1",
        )
    with pytest.raises(ExecutionError, match="provenance"):
        validate_execution_result(result, _grant(), scenario, configuration_id="reviewed_policy")


class _FakeDaytonaRunner:
    def __init__(self, run_record):
        self.command_env = None
        self.run_record = run_record
        self.payload = None

    def run_trial(self, payload, *, timeout_seconds):
        self.payload = payload
        return {"sandbox_id": "sandbox-1", "backend": "daytona", "result": {"run_record": self.run_record.model_dump(mode="json"), "receipt": {"request_id": "r"}}}


def test_daytona_boundary_passes_trusted_package_and_per_command_env_only():
    scenario = _scenario()
    fake = _FakeDaytonaRunner(RunRecord(scenario=scenario))
    boundary = TargetExecutionBoundary(backend="daytona", daytona_runner=fake, trusted_package={"trusted.py": b"x"})
    result = boundary.execute(_grant(), scenario, command_env={"OPENROUTER_API_KEY": "secret"})
    assert result.backend == "daytona"
    assert result.sandbox_id == "sandbox-1"
    assert fake.command_env["OPENROUTER_API_KEY"] == "secret"
    assert "TYPESAFE_API_KEY" not in fake.command_env
    assert "faultline_worker_entry.py" in fake.payload["app_package"]
    assert "OPENROUTER_API_KEY" not in json.dumps({key: value for key, value in fake.payload.items() if key != "app_package"})


def test_local_boundary_rejects_unsupported_provider_and_has_no_ambient_env(monkeypatch):
    with pytest.raises(ValueError):
        TargetExecutionBoundary().execute(_grant(provider="unknown"), _scenario())

    calls = {}

    class Process:
        returncode = 0

        def communicate(self, input=None, timeout=None):
            calls["input"] = input
            calls["timeout"] = timeout
            return json.dumps({"run_record": RunRecord(scenario=_scenario()).model_dump(mode="json"), "receipt": None}), ""

        def kill(self):
            calls["killed"] = True

    def fake_popen(args, **kwargs):
        calls["args"] = args
        calls["env"] = kwargs["env"]
        return Process()

    monkeypatch.setattr("faultline.execution.subprocess.Popen", fake_popen)
    result = TargetExecutionBoundary(timeout_seconds=2).execute(_grant(), _scenario(), command_env={"OPENROUTER_API_KEY": "secret"})
    assert result.run_record is not None
    assert calls["env"]["OPENROUTER_API_KEY"] == "secret"
    assert "TYPESAFE_API_KEY" not in calls["env"]
    assert calls["timeout"] == 2


def test_local_boundary_kills_timeout(monkeypatch):
    class Process:
        returncode = -9

        def communicate(self, input=None, timeout=None):
            raise __import__("subprocess").TimeoutExpired("worker", timeout)

        def kill(self):
            self.killed = True

    monkeypatch.setattr("faultline.execution.subprocess.Popen", lambda *args, **kwargs: Process())
    with pytest.raises(ExecutionError, match="target_worker_timeout"):
        TargetExecutionBoundary(timeout_seconds=1).execute(_grant(), _scenario(), command_env={"OPENROUTER_API_KEY": "secret"})
