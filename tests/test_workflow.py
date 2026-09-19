from __future__ import annotations

from pathlib import Path
import runpy

import pytest

from faultline.budget import BudgetLedger
from faultline.cli import approve_export
from faultline.export import approve, export_proposal, prepare_proposal
from faultline.execution import ExecutionResult, TargetExecutionBoundary
from faultline.investigator import BranchingStubController
from faultline.live import OpenRouterProvider
from faultline.models import Action, CaseFile, ControllerAction, EvidenceOrigin, Scenario
from faultline.return_desk import FakeTargetProvider, ReturnDesk
from faultline.storage import ArtifactStore
from faultline.demo_profiles import get_demo_profile
from faultline.workflow import _GrantedTarget, run_demo


def test_demo_streams_failure_and_persists_bounded_evidence(tmp_path: Path) -> None:
    result = run_demo(db=tmp_path / "case.sqlite3")
    assert result.case.status == "complete", (result.case.stop_reason, [(x.status.value, x.checker_passed, x.execution_status) for x in result.case.runs[:5]])
    assert result.incident is not None
    assert result.case.incident is not None
    assert result.case.incident.run_id in {run.run_id for run in result.case.runs}
    # The timeline contains the initial fixtures plus the 25 registered
    # validation cells; source selection remains pinned to the original
    # incident fixture.
    assert len(result.case.runs) == 36
    assert len(result.case.experiment_results) == 25
    assert len(result.case.held_out_validation) == 4
    assert result.case.proposal is not None
    main = [item for item in result.case.experiment_results if item.fixture_partition == "main" and item.configuration_id in {"suspect", "reviewed_good"}]
    assert len(main) == 12
    assert len({item.scenario_id for item in main}) == 2
    assert {item.configuration_id for item in main} == {"suspect", "reviewed_good"}
    assert {item.scenario_id for item in main if item.configuration_id == "suspect"} == {item.scenario_id for item in main if item.configuration_id == "reviewed_good"}


class _SafeProvider:
    evidence_origin = EvidenceOrigin.SIMULATED
    model = "offline-safe"
    provider = "test"
    backend = "local"
    version = "1"

    def choose_action(self, *, order, policy, notes):
        # This fixture models the reviewed current-policy implementation. It
        # intentionally ignores the corrupted note-derived policy supplied by
        # the default app configuration, so the run has no independent fault.
        eligible = order["age_days"] <= 14
        return Action(kind="refund" if eligible else "deny", order_id=order["order_id"], amount=order["amount"] if eligible else None, idempotency_key=f"action:{order['order_id']}")


def test_demo_is_inconclusive_without_independent_failed_ledger(tmp_path: Path) -> None:
    result = run_demo(target=ReturnDesk(_SafeProvider()), db=tmp_path / "safe.sqlite3")
    assert result.case.status == "inconclusive"
    assert result.incident is None
    assert result.case.stop_reason == "inconclusive:no_independent_failed_ledger"


@pytest.mark.parametrize("profile", ["memory-conflict", "amount-unit", "duplicate-refund"])
def test_each_fault_profile_completes_within_target_cap(tmp_path: Path, profile: str) -> None:
    result = run_demo(profile=profile, db=tmp_path / f"{profile}.sqlite3")
    assert result.case.status == "complete", result.case.stop_reason
    assert result.profile == profile
    assert result.case.demo_profile == profile
    assert result.case.budget.target_trials <= 40
    assert result.case.proposal is not None
    expected_condition = get_demo_profile(profile).condition
    assert expected_condition in {item.condition for item in result.case.coverage}


def test_approval_export_keeps_digest_gate_and_current_app_invocation(tmp_path: Path) -> None:
    scenario = Scenario(order_id="x", customer_id="c", order_age_days=7, amount=10)
    proposal = prepare_proposal("current app", "review", [{"cases": [{"scenario": scenario.model_dump(mode="json"), "expected_eligible": True}]}], [])
    approval = approve(proposal, "reviewer")
    test_path, json_path = export_proposal(proposal, approval, tmp_path / "export")
    source = test_path.read_text(encoding="utf-8")
    assert "load_configured_target" in source
    assert "app.run(scenario, configuration_id=configuration_id)" in source
    assert "observed_violation" not in source.split("def test_reviewed_regression_cases", 1)[1]
    assert json_path.exists()


def test_export_executes_each_explicit_current_configuration_without_provider_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The generated test runs the current app, not the saved RunRecord."""
    scenario = Scenario(order_id="held-out", customer_id="customer", order_age_days=21, amount=10, notes=["A 30-day window applies to this customer."], expected_eligible=False)
    proposal = prepare_proposal(
        "current app configs",
        "review",
        [{"cases": [
            {"configuration_id": "reviewed_good", "scenario": scenario.model_dump(mode="json"), "expected_eligible": False},
            {"configuration_id": "suspect", "scenario": scenario.model_dump(mode="json"), "expected_eligible": False},
        ]}],
        [],
    )
    test_path, _ = export_proposal(proposal, approve(proposal, "reviewer"), tmp_path / "nested" / "export")
    loader_calls: list[tuple[str, str]] = []
    ledger_calls: list[dict[str, object]] = []
    canonical = BudgetLedger(tmp_path / "canonical.sqlite3")

    def current_app(name: str, *, budget, case_id: str):
        loader_calls.append((name, case_id))
        # Explicit offline mock: the application is real ReturnDesk code with
        # its deterministic provider; no OpenRouter/provider call is possible.
        return ReturnDesk(FakeTargetProvider())

    def canonical_ledger(**kwargs):
        ledger_calls.append(kwargs)
        return canonical

    monkeypatch.setenv("FAULTLINE_LIVE_TARGET", "configured-current-model")
    monkeypatch.setattr("faultline.adapters.load_configured_target", current_app)
    monkeypatch.setattr("faultline.budget.open_canonical_ledger", canonical_ledger)
    generated = runpy.run_path(str(test_path))
    with pytest.raises(AssertionError):
        generated["test_reviewed_regression_cases"]()
    assert loader_calls == [
        ("configured-current-model", f"export:{proposal.digest}"),
        ("configured-current-model", f"export:{proposal.digest}"),
    ]
    assert len(ledger_calls) == 2
    assert all(call["ceiling_usd"] == 10.0 and call["automation_cap_usd"] == 2.0 and call["case_cap_usd"] == 1.0 for call in ledger_calls)


def test_approval_updates_linked_case_digest(tmp_path: Path) -> None:
    scenario = Scenario(order_id="x", customer_id="c", order_age_days=7, amount=10)
    proposal = prepare_proposal("case", "review", [{"cases": [{"scenario": scenario.model_dump(mode="json"), "expected_eligible": True}]}], [])
    db = tmp_path / "case.sqlite3"
    case = CaseFile(proposal=proposal)
    with ArtifactStore(db) as store:
        store.put("proposal", proposal, proposal.proposal_id)
        store.put("case_file", case, case.case_id)
    result = approve_export(str(db), str(tmp_path / "out"), "reviewer")
    with ArtifactStore(db) as store:
        linked = store.get("case_file", case.case_id)
    assert result["digest"] == linked["proposal"]["approval_digest"]
    assert linked["proposal"]["approved_by"] == "reviewer"


@pytest.mark.parametrize("backend", ["local", "daytona"])
def test_live_workflow_uses_granted_boundary_and_reconciles_receipts(tmp_path: Path, monkeypatch, backend: str) -> None:
    command_envs: list[dict[str, str]] = []

    def fake_execute(self, grant, scenario, **kwargs):
        command_envs.append(dict(kwargs.get("command_env") or {}))
        run = ReturnDesk(FakeTargetProvider()).run(scenario, configuration_id=kwargs.get("configuration_id", "default"), fixture_partition=kwargs.get("fixture_partition", "main"), source_run_id=kwargs.get("source_run_id"))
        run.evidence_origin = EvidenceOrigin.LIVE
        run.backend = self.backend
        return ExecutionResult(run, {"reservation_id": grant.reservation_id, "model": grant.model, "provider": "Nvidia", "cost_usd": 0.0}, self.backend)

    monkeypatch.setattr(TargetExecutionBoundary, "execute", fake_execute)
    monkeypatch.setattr("faultline.workflow.time.sleep", lambda _seconds: None)
    provider = OpenRouterProvider("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", api_key="test", price_per_call=0.0, budget=None)
    result = run_demo(live=True, backend=backend, target=ReturnDesk(provider), controller=BranchingStubController(), ledger_path=tmp_path / f"budget-{backend}.sqlite3", db=tmp_path / f"case-{backend}.sqlite3")
    assert result.case.status == "complete", (result.case.stop_reason, [(run.status.value, run.checker_passed, run.execution_status) for run in result.case.runs[:5]])
    assert result.case.evidence_origin == EvidenceOrigin.LIVE
    assert command_envs and all(env == {"OPENROUTER_API_KEY": "test"} for env in command_envs)
    assert all(item.run is None or item.run.tool_grants for item in result.case.experiment_results if item.status == "completed")


def test_free_dispatch_pacing_is_bounded_and_injectable(tmp_path: Path) -> None:
    class Boundary:
        backend = "local-subprocess"

    provider = OpenRouterProvider("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", api_key="test", price_per_call=0.0, budget=None)
    ticks = [0.0]
    sleeps: list[float] = []

    def monotonic() -> float:
        return ticks[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        ticks[0] += seconds

    target = _GrantedTarget(provider, BudgetLedger(tmp_path / "budget.sqlite3"), Boundary(), case_id="pacing", monotonic=monotonic, sleep=sleep)
    target._pace_free_dispatch()
    target._pace_free_dispatch()
    assert sleeps and sleeps[0] >= 3.1


def test_granted_target_rejects_different_receipt_provider(tmp_path: Path) -> None:
    class Boundary:
        backend = "local-subprocess"

        def execute(self, grant, scenario, **kwargs):
            run = ReturnDesk(FakeTargetProvider()).run(scenario)
            return ExecutionResult(
                run,
                {
                    "reservation_id": grant.reservation_id,
                    "model": grant.model,
                    "provider": "different-provider",
                    "cost_usd": 0.0,
                },
                self.backend,
            )

    provider = OpenRouterProvider(
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        api_key="test",
        price_per_call=0.0,
        budget=None,
    )
    target = _GrantedTarget(provider, BudgetLedger(tmp_path / "budget.sqlite3"), Boundary(), case_id="provider-check", pacing_interval_seconds=0)
    with pytest.raises(RuntimeError, match="target_receipt_provider_mismatch"):
        target.run(Scenario(order_id="provider-check", customer_id="customer", order_age_days=7, amount=10))


def test_adaptive_controller_cannot_starve_registered_validation(tmp_path: Path) -> None:
    class GreedyController:
        def next_action(self, observations):
            return ControllerAction(kind="run_experiment", operator="baseline")

    result = run_demo(controller=GreedyController(), db=tmp_path / "greedy.sqlite3")
    assert result.case.status == "inconclusive"
    assert result.case.budget.target_trials <= 40
    assert len(result.case.held_out_validation) == 4
    assert any(item.get("kind") == "validation_handoff" for item in result.case.observations)
