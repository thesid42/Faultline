from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from faultline.budget import AutomationCapExceeded, BudgetExceeded, BudgetLedger
from faultline.live import LiveCallError, NVIDIA_NEMOTRON_NANO_OMNI_FREE, OpenRouterProvider
from faultline.models import EvidenceOrigin, Scenario
from faultline.remote import DaytonaConfig, DaytonaRunner, TypeSafeJevBackend
from faultline.return_desk import ReturnDesk
from faultline.worker import OneCallWorker


def test_ledger_persists_pending_and_duplicate_receipt(tmp_path):
    path = tmp_path / "budget.sqlite"
    first = BudgetLedger(path, ceiling_usd=1.0, automation_cap_usd=1.0)
    reservation = first.reserve(0.50, request_id="one", case_id="case-one", approved=True)
    second = BudgetLedger(path, ceiling_usd=10.0, automation_cap_usd=2.0)
    assert second.snapshot().pending_usd == pytest.approx(0.50)
    second.reserve(0.50, request_id="two", case_id="case-two", approved=True)
    with pytest.raises(BudgetExceeded):
        second.reserve(0.01, request_id="three", case_id="case-three", approved=True)
    second.reconcile(reservation.reservation_id, 0.20)
    second.reconcile(reservation.reservation_id, 0.20)
    assert second.snapshot().spent_usd == pytest.approx(0.20)


def test_ledger_automatic_cap_requires_approval(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10.0, automation_cap_usd=0.50)
    ledger.reserve(0.50, case_id="case-one")
    with pytest.raises(AutomationCapExceeded):
        ledger.reserve(0.01, case_id="case-two")
    ledger.approve_automation()
    ledger.reserve(0.01, case_id="case-two")


def test_ledger_case_cap_and_hard_ceiling(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10.0, automation_cap_usd=2.0)
    for index in range(3):
        ledger.reserve(0.30, request_id=f"case-{index}", case_id="case-a", approved=True)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(0.30, request_id="case-3", case_id="case-a", approved=True)
    ledger.reserve(0.30, request_id="case-b", case_id="case-b", approved=True)
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path / "too-large.sqlite", ceiling_usd=11.0)


def test_openrouter_pins_provider_and_keeps_receipt_on_bad_json(tmp_path, monkeypatch):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    seen: dict[str, object] = {}

    def post(url, *, headers, json, timeout):
        seen["url"] = url
        seen["json"] = json
        return httpx.Response(
            200,
            json={
                "id": "req-1",
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "choices": [{"message": {"content": "not-json"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "cost": 0},
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("faultline.live.httpx.post", post)
    provider = OpenRouterProvider("nvidia/nemotron-3-super-120b-a12b:free", api_key="test", budget=ledger)
    with pytest.raises(LiveCallError) as error:
        provider._request([{"role": "user", "content": "x"}], {"type": "json_object"})
    assert error.value.receipt is not None
    assert error.value.receipt.request_id == "req-1"
    request = seen["json"]
    assert request["provider"]["only"] == ["nvidia"]
    assert request["provider"]["allow_fallbacks"] is False
    assert request["provider"]["max_price"]["request"] == 0
    assert request["reasoning"] == {"enabled": False}


def test_openrouter_maps_http200_embedded_provider_error_without_raw_metadata(tmp_path, monkeypatch):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append(url)
        return httpx.Response(
            200,
            json={
                "error": {
                    "code": 502,
                    "metadata": {"error_type": "provider_unavailable", "message": "secret provider details"},
                }
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("faultline.live.httpx.post", post)
    provider = OpenRouterProvider("nvidia/nemotron-3-super-120b-a12b:free", api_key="test", budget=ledger)
    with pytest.raises(LiveCallError) as error:
        provider._request([{"role": "user", "content": "x"}], {"type": "json_object"})
    assert str(error.value) == "provider_unavailable:502"
    assert error.value.receipt is not None
    assert provider.last_receipt is error.value.receipt
    assert len(calls) == 1
    assert "secret" not in str(error.value)


def test_returndesk_persists_only_bounded_embedded_provider_error_code():
    class EmbeddedErrorProvider:
        evidence_origin = EvidenceOrigin.LIVE
        model = "embedded-error-fixture"
        provider = "openrouter"
        backend = "httpx"
        version = "test"

        def choose_action(self, *, order, policy, notes):
            raise LiveCallError("provider_unavailable:502")

    run = ReturnDesk(EmbeddedErrorProvider()).run(Scenario(order_id="error-order", customer_id="error-customer", order_age_days=7, amount=10))
    error = next(event for event in run.events if event.kind == "error")
    assert error.payload["code"] == "provider_unavailable:502"
    assert "secret" not in str(error.payload)


def test_nano_omni_omits_unsupported_response_format_but_strictly_parses(tmp_path, monkeypatch):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    seen = {}

    def post(url, *, headers, json, timeout):
        seen["json"] = json
        return httpx.Response(200, json={"id": "nano-1", "choices": [{"message": {"content": "invalid"}}], "usage": {"cost": 0}}, request=httpx.Request("POST", url))

    monkeypatch.setattr("faultline.live.httpx.post", post)
    provider = OpenRouterProvider(NVIDIA_NEMOTRON_NANO_OMNI_FREE, api_key="test", budget=ledger, max_prompt_tokens=256_000, max_output_tokens=512)
    with pytest.raises(LiveCallError):
        provider._request([{"role": "user", "content": "return json"}], {"type": "json_object"})
    assert "response_format" not in seen["json"]
    assert seen["json"]["max_tokens"] == 512
    assert seen["json"]["reasoning"] == {"enabled": False}


def test_worker_does_not_retry_type_error(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    worker = OneCallWorker(ledger)
    grant = worker.issue_grant(model="m", provider="p", max_cost_usd=0.10, max_prompt_tokens=100, max_output_tokens=10, case_id="case-one", approved=True)
    calls = []

    def backend(**kwargs):
        calls.append(kwargs)
        raise TypeError("backend failed")

    with pytest.raises(TypeError):
        worker.execute(grant, "prompt", backend)
    assert len(calls) == 1
    assert ledger.snapshot().pending_usd == pytest.approx(0.10)


def test_zero_cost_grant_ignores_compatibility_paid_price_defaults(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    grant = OneCallWorker(ledger).issue_grant(
        model="nvidia/example:free",
        provider="nvidia",
        max_cost_usd=0.0,
        max_prompt_tokens=256_000,
        max_output_tokens=512,
        case_id="case-free",
        prompt_price_per_million=0.30,
        completion_price_per_million=1.20,
    )
    assert grant.max_cost_usd == 0.0


def test_worker_grant_is_single_dispatch_across_replay(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", ceiling_usd=10, automation_cap_usd=2)
    worker = OneCallWorker(ledger)
    grant = worker.issue_grant(model="m", provider="p", max_cost_usd=0.10, max_prompt_tokens=100, max_output_tokens=10, case_id="case-one", approved=True)
    calls = []

    def backend(**kwargs):
        calls.append(kwargs)
        return {"id": "r", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.01}, "content": "{}"}

    worker.execute(grant, "prompt", backend)
    with pytest.raises(RuntimeError):
        worker.execute(grant, "prompt", backend)
    with pytest.raises(ValueError):
        worker.issue_grant(model="m", provider="p", max_cost_usd=0.10, max_prompt_tokens=100, max_output_tokens=10, case_id="case-one", request_id=grant.request_id, approved=True)
    assert len(calls) == 1


def test_ledger_paid_and_duplicate_invariants_persist(tmp_path):
    path = tmp_path / "budget.sqlite"
    ledger = BudgetLedger(path, ceiling_usd=0.80, automation_cap_usd=0.80, case_cap_usd=0.80)
    with pytest.raises(ValueError):
        ledger.reserve(0.01, request_id="missing-case")
    with pytest.raises(ValueError):
        ledger.reserve(0.51, request_id="too-large", case_id="case")
    ledger.reserve(0.20, request_id="same", case_id="case", category="model", approved=True)
    with pytest.raises(ValueError):
        ledger.reserve(0.10, request_id="same", case_id="case", category="model", approved=True)
    with pytest.raises(ValueError):
        ledger.reserve(0.20, request_id="same", case_id="other", category="model", approved=True)
    reopened = BudgetLedger(path, ceiling_usd=0.50, automation_cap_usd=0.40, case_cap_usd=0.20)
    snapshot = reopened.snapshot()
    assert snapshot.ceiling_usd == pytest.approx(0.50)
    assert snapshot.automation_cap_usd == pytest.approx(0.40)
    reopened.reserve(0.10, request_id="lower-cap", case_id="case-two", approved=True)
    with pytest.raises(BudgetExceeded):
        reopened.reserve(0.01, request_id="case-over", case_id="case", approved=True)


class _Answer(BaseModel):
    label: str


class _TypeSafeResponse:
    model = "jev-1.13.0"
    answers = {"q": _Answer(label="yes")}
    usage = SimpleNamespace(input_tokens=None, output_tokens=4)

    def model_dump(self, *, mode: str):
        return {"model": self.model, "answers": {"q": {"label": "yes"}}, "usage": {"input_tokens": None, "output_tokens": 4}}


class _TypeSafeClient:
    def system_one(self, **kwargs):
        return _TypeSafeResponse()


def test_typesafe_answers_are_json_safe_and_unknown_usage_cost_stays_unknown(monkeypatch):
    fake_typesafe = types.ModuleType("typesafe_sdk")
    fake_typesafe.Noul = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "typesafe_sdk", fake_typesafe)
    result = TypeSafeJevBackend(client=_TypeSafeClient()).triage(state={"x": 1}, questions={"q": "Is x true?"})
    json.dumps(result)
    assert result["answers"] == {"q": {"label": "yes"}}
    assert result["usage"]["cost_usd"] is None


class _FakeFS:
    def __init__(self, *, result=b'{"ok":true}'):
        self.folders = []
        self.uploads = []
        self.result = result

    def create_folder(self, path, mode, request_timeout=None):
        self.folders.append(path)

    def upload_file(self, src, dst, timeout=None):
        self.uploads.append((src, dst, timeout))

    def download_file(self, path, timeout=None):
        return self.result


class _FakeSandbox:
    id = "sandbox-1"

    def __init__(self, *, exit_code=0):
        self.fs = _FakeFS()
        self.process = SimpleNamespace(exec=lambda *args, **kwargs: SimpleNamespace(exit_code=exit_code))
        self.ttl = None

    def get_work_dir(self):
        return "/home/daytona"

    def set_ttl(self, value):
        self.ttl = value


class _FakeDaytona:
    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.deleted = []

    def create(self, params, timeout):
        return self.sandbox

    def delete(self, sandbox, *, wait, timeout):
        self.deleted.append((sandbox, wait, timeout))


def _trusted_package():
    return {"faultline_worker_entry.py": b"def main(request): return {'ok': True}", "pkg/data.txt": b"trusted", "faultline/worker.py": b"trusted module"}


def _install_fake_daytona(monkeypatch):
    fake_daytona = types.ModuleType("daytona")

    class Params:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_daytona.CreateSandboxFromSnapshotParams = Params
    monkeypatch.setitem(sys.modules, "daytona", fake_daytona)


def test_daytona_mock_uploads_nested_trusted_package_and_cleans_up(monkeypatch):
    _install_fake_daytona(monkeypatch)
    sandbox = _FakeSandbox()
    daytona = _FakeDaytona(sandbox)
    runner = DaytonaRunner(client=daytona, config=DaytonaConfig(api_key="secret", api_url="https://secret"), command_env={"OPENROUTER_API_KEY": "secret"})
    output = runner.run_trial({"app_package": _trusted_package(), "input": {"x": 1}}, timeout_seconds=3)
    assert output["result"] == {"ok": True}
    assert "/home/daytona/faultline_app/pkg" in sandbox.fs.folders
    assert any(path.endswith("/pkg/data.txt") for _, path, _ in sandbox.fs.uploads)
    assert daytona.deleted and daytona.deleted[0][1] is True
    assert "secret" not in repr(runner)
    assert "secret" not in repr(runner.config)


def test_daytona_rejects_fixed_artifact_and_nonzero_exit_but_always_cleans_up(monkeypatch):
    _install_fake_daytona(monkeypatch)
    sandbox = _FakeSandbox()
    daytona = _FakeDaytona(sandbox)
    runner = DaytonaRunner(client=daytona)
    with pytest.raises(ValueError):
        runner.run_trial({"app_package": {"faultline_worker_entry.py": b"x", "worker.py": b"overwrite"}})
    assert daytona.deleted
    sandbox = _FakeSandbox(exit_code=1)
    daytona = _FakeDaytona(sandbox)
    with pytest.raises(RuntimeError, match="daytona_worker_exit_1"):
        DaytonaRunner(client=daytona).run_trial({"app_package": _trusted_package()})
    assert daytona.deleted
