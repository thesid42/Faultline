from __future__ import annotations

from types import SimpleNamespace
import json
from threading import Event, Thread
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from faultline.api import make_server
from faultline.config import FaultlineConfig
from faultline.jobs import InvestigationJobManager, InvestigationRequest
from faultline.storage import ArtifactStore


def _url(server, path: str) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}{path}"


def _get(server, path: str) -> tuple[int, dict]:
    with urlopen(_url(server, path), timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post(server, payload: dict, token: str, *, origin: str | None = "http://127.0.0.1:5173", host: str | None = None) -> tuple[int, dict]:
    headers = {
        "Content-Type": "application/json",
        "Origin": origin or "",
        "X-Faultline-Token": token,
    }
    if host is not None:
        headers["Host"] = host
    request = Request(_url(server, "/api/investigations"), data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _wait_for_case(server, case_id: str, expected: set[str], timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _status, payload = _get(server, f"/api/cases/{case_id}")
        if payload.get("status") in expected:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"case did not reach {expected}")


@pytest.fixture()
def job_server(tmp_path):
    db = tmp_path / "cases.sqlite3"
    # Creating the DB is an explicit fixture setup; GET handlers themselves
    # still use SQLite mode=ro and never create a store.
    with ArtifactStore(db):
        pass
    started = Event()
    release = Event()
    calls: list[dict] = []

    def runner(**kwargs):
        calls.append(kwargs)
        started.set()
        assert release.wait(3)
        with ArtifactStore(db) as store:
            raw = store.get("case_file", kwargs["case_id"])
            assert raw is not None
            raw["status"] = "complete"
            raw["observations"] = [{"step": "fake-offline-runner"}]
            store.put("case_file", raw, kwargs["case_id"])
        return SimpleNamespace(case=SimpleNamespace(status="complete"))

    server = make_server(db, port=0)
    # Injection is test-only; production construction uses run_demo.
    server.jobs = InvestigationJobManager(db, runner=runner)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, db, calls, started, release
    finally:
        release.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _request_payload(*, request_id: str | None = None, profile: str = "memory-conflict") -> dict:
    return {
        "profile": profile,
        "mode": "simulated",
        "jev": False,
        "request_id": request_id or str(uuid4()),
    }


def test_capabilities_expose_readiness_only_not_credentials(tmp_path, monkeypatch):
    db = tmp_path / "cases.sqlite3"
    with ArtifactStore(db):
        pass
    manager = InvestigationJobManager(db, runner=lambda **_kwargs: None)
    monkeypatch.setattr(
        "faultline.jobs.load_config",
        lambda: FaultlineConfig(
            openrouter_api_key="openrouter-secret",
            typesafe_api_key="typesafe-secret",
            daytona_api_key="daytona-secret",
        ),
    )
    ready = manager.capabilities()
    encoded = json.dumps(ready)
    assert ready["live_available"] is True
    assert ready["live_unavailable_reason"] is None
    assert ready["jev_available"] is True
    assert ready["daytona_configured"] is True
    assert ready["execution_backend"] == "local-subprocess"
    for secret in ("openrouter-secret", "typesafe-secret", "daytona-secret"):
        assert secret not in encoded

    monkeypatch.setattr("faultline.jobs.load_config", lambda: FaultlineConfig())
    unavailable = manager.capabilities()
    assert unavailable["live_available"] is False
    assert unavailable["live_unavailable_reason"] == "OPENROUTER_API_KEY is not configured"
    assert unavailable["jev_available"] is False
    assert unavailable["daytona_configured"] is False


def test_capabilities_and_async_idempotent_single_active_job(job_server):
    server, _db, calls, started, release = job_server
    _status, capabilities = _get(server, "/api/capabilities")
    assert capabilities["profiles"] == ["memory-conflict", "amount-unit", "duplicate-refund"]
    assert capabilities["modes"] == ["simulated", "live"]
    assert capabilities["target_model"] == "meta-llama/llama-3.1-8b-instruct"
    assert capabilities["active_case_id"] is None

    payload = _request_payload()
    status, accepted = _post(server, payload, capabilities["csrf_token"])
    assert status == 202
    assert accepted["status"] == "queued"
    assert started.wait(2)
    assert len(calls) == 1

    # Retries with the same immutable request key never launch a second run;
    # a different key is rejected while the one active slot is occupied.
    status, duplicate = _post(server, payload, capabilities["csrf_token"])
    assert status == 202
    assert duplicate["case_id"] == accepted["case_id"]
    status, conflict = _post(server, {**payload, "profile": "amount-unit"}, capabilities["csrf_token"])
    assert status == 409 and conflict["error"] == "request_id_conflict"
    status, busy = _post(server, _request_payload(), capabilities["csrf_token"])
    assert status == 409 and busy["error"] == "investigation_active"
    release.set()
    finished = _wait_for_case(server, accepted["case_id"], {"complete"})
    assert finished["observations"] == [{"step": "fake-offline-runner"}]
    assert _get(server, "/api/capabilities")[1]["active_case_id"] is None


def test_api_security_rejects_missing_origin_bad_token_schema_and_oversize(job_server):
    server, _db, _calls, _started, release = job_server
    _status, capabilities = _get(server, "/api/capabilities")
    payload = _request_payload()
    status, body = _post(server, payload, capabilities["csrf_token"], origin=None)
    assert status == 403 and body["error"] == "origin_or_host_not_allowed"
    status, body = _post(server, payload, "wrong", origin="http://127.0.0.1:5173")
    assert status == 403 and body["error"] == "token_required"
    status, body = _post(server, {**payload, "extra": 1}, capabilities["csrf_token"])
    assert status == 400 and body["error"] == "invalid_investigation_schema"
    status, body = _post(server, payload, capabilities["csrf_token"], origin="http://localhost:not-a-port")
    assert status == 403 and body["error"] == "origin_or_host_not_allowed"
    status, body = _post(server, payload, capabilities["csrf_token"], host="evil.example:8765")
    assert status == 403 and body["error"] == "origin_or_host_not_allowed"
    oversized = {**payload, "padding": "x" * 5000}
    status, body = _post(server, oversized, capabilities["csrf_token"])
    assert status == 413 and body["error"] == "request_too_large"
    release.set()


def test_failure_preserves_trace_and_sanitizes_exception(tmp_path):
    db = tmp_path / "cases.sqlite3"
    with ArtifactStore(db):
        pass

    def failing_runner(**kwargs):
        with ArtifactStore(db) as store:
            raw = store.get("case_file", kwargs["case_id"])
            assert raw is not None
            raw["observations"] = [{"event": "before-failure", "token": "not-a-secret"}]
            store.put("case_file", raw, kwargs["case_id"])
        raise RuntimeError("provider key should never be persisted")

    manager = InvestigationJobManager(db, runner=failing_runner)
    request = InvestigationRequest(str(uuid4()), "memory-conflict", "simulated", False)
    case_id, status = manager.submit(request)
    assert status == "queued"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with ArtifactStore(db) as store:
            case = store.get("case_file", case_id)
        if case and case.get("status") == "inconclusive":
            break
        time.sleep(0.02)
    assert case["status"] == "inconclusive"
    assert case["observations"] == [{"event": "before-failure", "token": "not-a-secret"}]
    assert "RuntimeError" in case["stop_reason"]
    assert "provider key" not in case["stop_reason"]


def test_request_mapping_survives_manager_restart_without_relaunch(tmp_path):
    db = tmp_path / "cases.sqlite3"
    with ArtifactStore(db):
        pass
    calls: list[dict] = []

    def runner(**kwargs):
        calls.append(kwargs)
        with ArtifactStore(db) as store:
            raw = store.get("case_file", kwargs["case_id"])
            raw["status"] = "complete"
            store.put("case_file", raw, kwargs["case_id"])
        return SimpleNamespace(case=SimpleNamespace(status="complete"))

    request = InvestigationRequest(str(uuid4()), "amount-unit", "simulated", False)
    first = InvestigationJobManager(db, runner=runner)
    case_id, _status = first.submit(request)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(calls) == 0:
        time.sleep(0.02)
    assert len(calls) == 1
    while time.monotonic() < deadline and first.active_case_id is not None:
        time.sleep(0.02)
    assert first.active_case_id is None
    with ArtifactStore(db) as store:
        assert store.get("case_file", case_id)["status"] == "complete"
    second = InvestigationJobManager(db, runner=lambda **_kwargs: pytest.fail("must not relaunch"))
    assert second.submit(request) == (case_id, "complete")
