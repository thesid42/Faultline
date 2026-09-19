"""Complete Faultline demo workflow.

This orchestration layer discovers incidents from observed runs and delegates
diagnosis to the typed controller. It never labels a failure from fixture names
or from a controller response alone.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from uuid import uuid4

from .adapters import load_configured_investigator, load_configured_target
from .budget import BudgetLedger
from .clock import FixedClock
from .coverage import assess_coverage, condition_matches_scenario
from .export import prepare_proposal
from .incidents import IncidentQueue
from .investigator import AdaptiveInvestigator, BranchingStubController, InvestigatorController, Tools
from .models import BudgetState, CaseFile, EvidenceOrigin, Event, ExperimentResult, ExperimentSpec, Incident, RunRecord, RunStatus, Scenario
from .execution import TargetExecutionBoundary, validate_execution_result
from .live import LLAMA_31_8B_INSTRUCT
from .worker import OneCallWorker
from .remote import DaytonaConfig, DaytonaRunner, OptionalJevTriage, TypeSafeJevBackend
from .return_desk import ReturnDesk
from .scenarios import OBSOLETE_NOTE, UNRELATED_NOTE, default_scenarios, held_out, original_suite
from .session import InvestigationSession
from .storage import ArtifactStore
from .trials import LocalTrialRunner


_TRUSTED_EVIDENCE_FAILURES = frozenset(
    {
        "required_evidence_inconclusive",
        "held_out_validation_inconclusive",
        "held_out_reviewed_good_failed",
    }
)


@dataclass
class DemoResult:
    case: CaseFile
    incident: Incident | None
    proposal_digest: str | None = None
    db: str = "results/faultline.sqlite3"
    evidence_origin: str = "simulated"
    profile: str = "memory-conflict"

    def as_dict(self) -> dict[str, Any]:
        case = self.case
        return {
            "case_id": case.case_id,
            "case_status": case.status,
            "stop_reason": case.stop_reason,
            "incident_id": self.incident.incident_id if self.incident else None,
            "runs": len(case.runs),
            "experiments": len(case.experiment_results),
            "hypotheses": len(case.hypotheses),
            "held_out": len(case.held_out_validation),
            "coverage": [item.model_dump(mode="json") for item in case.coverage],
            "proposal_id": case.proposal.proposal_id if case.proposal else None,
            "proposal_digest": self.proposal_digest or (case.proposal.digest if case.proposal else None),
            "evidence_origin": self.evidence_origin,
            "backend": case.backend,
            "db": self.db,
            "profile": self.profile,
            "budget": case.budget.model_dump(mode="json"),
        }


@dataclass(frozen=True)
class _DemoProfile:
    """Small normalized view of the shared demo-profile contract."""

    name: str
    title: str
    condition: str
    stream: list[Scenario]
    suite: list[Scenario]
    held_out: list[Scenario]
    intervention_operator: str
    intervention_value: str | int | None


def _profile_items(value: Any) -> list[Scenario]:
    value = value() if callable(value) else value
    return list(value or [])


def _resolve_profile(name: str) -> _DemoProfile:
    """Load the core-owned profile registry without coupling offline startup."""
    try:
        from .demo_profiles import get_demo_profile
    except ImportError:
        if name != "memory-conflict":
            raise RuntimeError("fault profile registry is not installed") from None
        return _DemoProfile(name, "ReturnDesk conflicting-memory boundary", "memory_conflict", default_scenarios(), original_suite(), held_out(), "remove_note", OBSOLETE_NOTE)
    profile = get_demo_profile(name)
    return _DemoProfile(
        name=str(profile.name),
        title=str(profile.title),
        condition=str(profile.condition),
        stream=_profile_items(profile.stream),
        suite=_profile_items(profile.suite),
        held_out=_profile_items(profile.held_out),
        intervention_operator=str(profile.intervention_operator),
        intervention_value=profile.intervention_value,
    )


class _GrantedTarget:
    """ReturnDesk-shaped adapter that grants exactly one child call per run."""

    def __init__(self, provider: Any, ledger: BudgetLedger, boundary: TargetExecutionBoundary, *, case_id: str, command_env: dict[str, str] | None = None, pacing_interval_seconds: float = 3.1, monotonic: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None) -> None:
        self.provider = provider
        self.checker = ReturnDesk(checker=None).checker
        self.ledger = ledger
        self.boundary = boundary
        self.case_id = case_id
        self.command_env = command_env or {}
        self.worker = OneCallWorker(ledger)
        self.evidence_origin = EvidenceOrigin.LIVE
        self.pacing_interval_seconds = pacing_interval_seconds
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._last_free_dispatch: float | None = None

    def _pace_free_dispatch(self) -> None:
        if not str(self.provider.model).endswith(":free") or self.pacing_interval_seconds <= 0:
            return
        now = self._monotonic()
        if self._last_free_dispatch is not None:
            remaining = self.pacing_interval_seconds - (now - self._last_free_dispatch)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_free_dispatch = now

    def run(self, scenario: Scenario, *, configuration_id: str = "default", fixture_partition: str = "main", source_run_id: str | None = None) -> RunRecord:
        # A ``:free`` target has no billable token price even when a caller
        # constructed the provider with its legacy paid-rate defaults.  The
        # immutable grant must reflect the selected model, otherwise the
        # conservative token estimate rejects a legitimate zero-cost call
        # before it reaches the execution boundary.
        self._pace_free_dispatch()
        free_target = str(self.provider.model).endswith(":free")
        prompt_rate = 0.0 if free_target else self.provider.prompt_price_per_million
        completion_rate = 0.0 if free_target else self.provider.completion_price_per_million
        grant = self.worker.issue_grant(
            model=self.provider.model,
            provider=getattr(self.provider, "provider_name", getattr(self.provider, "provider", "openrouter")),
            max_cost_usd=self.provider.price_per_call,
            max_prompt_tokens=self.provider.max_prompt_tokens,
            max_output_tokens=self.provider.max_output_tokens,
            case_id=self.case_id,
            prompt_price_per_million=prompt_rate,
            completion_price_per_million=completion_rate,
        )
        # The workflow uses TargetExecutionBoundary directly (rather than
        # OneCallWorker.execute), so claim the immutable dispatch exactly once
        # before handing the grant to the fixed child.
        self.ledger.claim(grant.reservation_id, grant.grant_id)
        result = self.boundary.execute(grant, scenario, command_env=self.command_env, configuration_id=configuration_id, fixture_partition=fixture_partition, source_run_id=source_run_id)
        if result.run_record is None:
            raise RuntimeError(result.error or "target_worker_missing_run_record")
        validate_execution_result(result, grant, scenario, configuration_id=configuration_id, fixture_partition=fixture_partition, source_run_id=source_run_id)
        receipt = result.receipt or {}
        if not receipt:
            raise RuntimeError("target_worker_missing_receipt")
        if receipt and receipt.get("reservation_id") != grant.reservation_id:
            raise RuntimeError("target_receipt_reservation_mismatch")
        if receipt.get("model") is not None and receipt.get("model") != grant.model:
            raise RuntimeError("target_receipt_model_mismatch")
        if receipt.get("provider") is not None and str(receipt.get("provider")).casefold() != str(grant.provider).casefold():
            raise RuntimeError("target_receipt_provider_mismatch")
        cost = receipt.get("cost_usd", receipt.get("cost")) if isinstance(receipt, dict) else None
        self.ledger.reconcile(grant.reservation_id, cost, usage_available=cost is not None, dispatch_token=grant.grant_id)
        run = result.run_record
        run.backend = result.backend
        run.tool_grants.append({"grant_id": grant.grant_id, "reservation_id": grant.reservation_id, "request_id": grant.request_id, "max_cost_usd": grant.max_cost_usd, "backend": result.backend, "receipt": receipt, "sandbox_id": result.sandbox_id})
        return run


class _GrantedTrialRunner(LocalTrialRunner):
    def _new_target(self) -> Any:
        return self.target

    def _execute_isolated(self, scenario: Scenario, timeout_seconds: int, *, configuration_id: str = "default", fixture_partition: str = "main", source_run_id: str | None = None) -> RunRecord:
        # The boundary itself owns the killable local subprocess or Daytona
        # sandbox; never pickle its parent-owned ledger into another child.
        return self.target.run(scenario, configuration_id=configuration_id, fixture_partition=fixture_partition, source_run_id=source_run_id)


class _CheckpointingController:
    """Checkpoint before each typed command is executed."""

    def __init__(self, wrapped: InvestigatorController, checkpoint: Callable[[], None]) -> None:
        self.wrapped = wrapped
        self.checkpoint = checkpoint

    def next_action(self, observations: list[dict[str, Any]]) -> Any:
        action = self.wrapped.next_action(observations)
        self.checkpoint()
        return action


@dataclass
class _IncidentScopedTools(Tools):
    """Keep adaptive source selection pinned to the original incident run."""

    incident_run_id: str = ""
    probe_runs: list[RunRecord] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.probe_runs is None:
            self.probe_runs = []

    def probe_case(self, scenario: Scenario) -> RunRecord:
        run = super().probe_case(scenario)
        self.probe_runs.append(run)
        # The raw probe is retained separately for the final case file, but
        # must not become the source baseline for later interventions.
        self.runs[:] = [item for item in self.runs if item.run_id == self.incident_run_id]
        return run

    def to_case_file(self, **kwargs: Any) -> CaseFile:
        # Checkpoints need the complete audit timeline, while adaptive source
        # selection must continue to see only the original incident run.
        source_runs = list(self.runs)
        all_runs = list(source_runs)
        known = {item.run_id for item in all_runs}
        for run in self.probe_runs:
            if run.run_id not in known:
                all_runs.append(run)
                known.add(run.run_id)
        for result in self.results:
            if result.run is not None and result.run.run_id not in known:
                all_runs.append(result.run)
                known.add(result.run.run_id)
        self.runs[:] = all_runs
        try:
            return super().to_case_file(**kwargs)
        finally:
            self.runs[:] = source_runs


def _grader_observations(results: Iterable[ExperimentResult], condition: str) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for result in results:
        run = result.run
        if result.status != "completed" or not result.activation.activated or run is None:
            continue
        if result.observed_violation is not True or run.checker_passed is not False:
            continue
        if condition_matches_scenario(run.scenario, condition) is not True:
            continue
        observations.append({"trial_id": result.trial_id, "run_id": run.run_id, "condition": condition, "detected": True, "grader_version": "rule-checker-v1"})
    return observations


def _persist_case(session: InvestigationSession, tools: Tools, *, incident: Incident | None, scenarios: list[Scenario], coverage: list[Any] | None = None, proposal: Any | None = None, held_out_validation: list[dict[str, Any]] | None = None, status: str = "investigating", profile_name: str | None = None) -> CaseFile:
    # ExperimentResult keeps its RunRecord nested for auditability, while the
    # case timeline also needs one flat run entry. De-duplicate by run ID.
    if not isinstance(tools, _IncidentScopedTools):
        known = {run.run_id for run in tools.runs}
        for result in tools.results:
            if result.run is not None and result.run.run_id not in known:
                tools.runs.append(result.run)
                known.add(result.run.run_id)
    case = tools.to_case_file(incident=incident, scenarios=scenarios, coverage=coverage, proposal=proposal, held_out_validation=held_out_validation, status=status)
    if profile_name and "demo_profile" in CaseFile.model_fields:
        case = case.model_copy(update={"demo_profile": profile_name})
    return session.checkpoint(case)


def _run_direct(target: ReturnDesk, scenarios: Iterable[Scenario], budget: BudgetState) -> list[RunRecord]:
    runs: list[RunRecord] = []
    for scenario in scenarios:
        if not budget.can_target_trial():
            break
        budget.target_trials += 1
        try:
            runs.append(target.run(scenario))
        except Exception as exc:
            runs.append(RunRecord(scenario=scenario, status=RunStatus.INFRASTRUCTURE_ERROR, execution_status="error", checker_status="not_run", evidence_origin=EvidenceOrigin.LIVE if getattr(getattr(target, "provider", None), "evidence_origin", "simulated") == EvidenceOrigin.LIVE else EvidenceOrigin.SIMULATED, model=getattr(getattr(target, "provider", None), "model", "unknown"), provider=getattr(getattr(target, "provider", None), "provider", "unknown"), backend=getattr(getattr(target, "provider", None), "backend", "unknown"), events=[Event(actor="workflow", kind="infrastructure_error", payload={"type": type(exc).__name__})]))
    return runs


def _source_run(tools: Tools, scenario: Scenario) -> RunRecord | None:
    # Experiments retain the source scenario ID while changing its fields.
    # Bind evidence to the original default fixture, never to a later
    # intervention row that happens to share that ID.
    return next((run for run in tools.runs if run.scenario == scenario and run.scenario.scenario_id == scenario.scenario_id and run.configuration_id == "default" and run.fixture_partition == "main"), None)


def _spec(*, operator: str, value: str | int | None, scenario: Scenario, source_run: RunRecord | None, hypothesis_id: str, source_role: str = "incident", configuration_id: str = "default", fixture_partition: str = "main", repetitions: int = 3) -> ExperimentSpec:
    return ExperimentSpec(hypothesis_id=hypothesis_id, name=f"{configuration_id}:{operator}", operator=operator, value=value, source_scenario_id=scenario.scenario_id, source_run_id=source_run.run_id if source_run else None, source_role=source_role, configuration_id=configuration_id, fixture_partition=fixture_partition, repetitions=repetitions)  # type: ignore[arg-type]


def _hypothesis_for_operator(tools: Tools, operator: str) -> str:
    family = {"remove_note": "memory", "refund_api_unit": "amount_units", "delivery_attempts": "idempotency"}.get(operator)
    if family:
        match = next((item for item in tools.hypotheses if item.predicates.get("family") == family), None)
        if match:
            return match.hypothesis_id
    return tools.hypotheses[0].hypothesis_id if tools.hypotheses else "adaptive"


def _supported_relevant_hypothesis(tools: Tools, operator: str) -> bool:
    family = {"remove_note": "memory", "refund_api_unit": "amount_units", "delivery_attempts": "idempotency"}.get(operator)
    return any(item.status == "supported" and (family is None or item.predicates.get("family") == family) for item in tools.hypotheses)


def _run_required_evidence(tools: Tools, incident_scenario: Scenario, control: Scenario, profile: _DemoProfile) -> list[ExperimentResult]:
    """Collect bounded baseline/relevant/unrelated evidence arms."""
    hypothesis_id = _hypothesis_for_operator(tools, profile.intervention_operator)
    incident_source = _source_run(tools, incident_scenario)
    results: list[ExperimentResult] = []
    required = (("baseline", None), (profile.intervention_operator, profile.intervention_value), ("unrelated_note", UNRELATED_NOTE))
    for operator, value in required:
        # ActivationReceipt deliberately records the operator and source but
        # not the value. Match the spec itself, source identity, and complete
        # repetition count so a controller's different/no-op arm cannot mask
        # this registered mandatory contrast.
        exact_specs = {
            spec.experiment_id
            for spec in tools.experiments
            if spec.operator == operator
            and spec.value == value
            and spec.source_scenario_id == incident_scenario.scenario_id
            and spec.source_run_id == (incident_source.run_id if incident_source else None)
            and spec.source_role == "incident"
            and spec.configuration_id == "default"
            and spec.fixture_partition == "main"
            and spec.repetitions == 3
        }
        matching = [item for item in tools.results if item.experiment_id in exact_specs]
        if exact_specs:
            if len(matching) != 3 or {item.repetition for item in matching} != {1, 2, 3} or any(item.status != "completed" or not item.activation.activated or item.run is None for item in matching):
                raise RuntimeError("required_evidence_inconclusive")
            continue
        spec = _spec(operator=operator, value=value, scenario=incident_scenario, source_run=incident_source, hypothesis_id=hypothesis_id)
        results.extend(tools.run_experiment(spec, incident_scenario))
    return results


def _run_regression_matrix(tools: Tools, incident_scenario: Scenario, control: Scenario) -> list[ExperimentResult]:
    """Run two same-input cases through suspect and reviewed-good configs."""
    hypothesis_id = _hypothesis_for_operator(tools, "baseline")
    results: list[ExperimentResult] = []
    source_by_id = {scenario.scenario_id: _source_run(tools, scenario) for scenario in (incident_scenario, control)}
    for configuration_id in ("suspect", "reviewed_good"):
        for scenario in (incident_scenario, control):
            existing = [item for item in tools.results if item.configuration_id == configuration_id and item.fixture_partition == "main" and item.activation.operator == "baseline" and item.scenario_id == scenario.scenario_id and item.run is not None and item.run.scenario == scenario]
            if len(existing) >= 3:
                continue
            spec = _spec(operator="baseline", value=None, scenario=scenario, source_run=source_by_id[scenario.scenario_id], hypothesis_id=hypothesis_id, source_role="control" if scenario.control else "incident", configuration_id=configuration_id, repetitions=3)
            results.extend(tools.run_experiment(spec, scenario))
    return results


def _run_held_out_matrix(tools: Tools, scenarios: list[Scenario]) -> list[dict[str, Any]]:
    """Validate separate held-out IDs through both application configs."""
    hypothesis_id = tools.hypotheses[0].hypothesis_id if tools.hypotheses else "adaptive"
    validation: list[dict[str, Any]] = []
    for configuration_id in ("suspect", "reviewed_good"):
        for scenario in scenarios:
            spec = _spec(operator="baseline", value=None, scenario=scenario, source_run=None, hypothesis_id=hypothesis_id, source_role="held_out", configuration_id=configuration_id, fixture_partition="held_out", repetitions=1)
            for result in tools.run_experiment(spec, scenario):
                validation.append({"scenario_id": scenario.scenario_id, "order_id": scenario.order_id, "configuration_id": configuration_id, "trial_id": result.trial_id, "status": result.status, "checker_passed": result.run.checker_passed if result.run else None, "expected_eligible": tools.runner.target.checker.expected_eligible(scenario), "run": result.run.model_dump(mode="json") if result.run else None})
    tools.held_out_validation.extend(validation)
    cells = [item for item in tools.results if item.fixture_partition == "held_out" and item.configuration_id in {"suspect", "reviewed_good"}]
    if len(cells) != 4 or any(item.status != "completed" or not item.activation.activated or item.run is None or item.run.checker_status != "completed" for item in cells):
        raise RuntimeError("held_out_validation_inconclusive")
    good = [item for item in cells if item.configuration_id == "reviewed_good"]
    if len(good) != 2 or any(item.run is None or item.run.checker_passed is not True for item in good):
        raise RuntimeError("held_out_reviewed_good_failed")
    return validation


def _evidence_failure_trial_ids(tools: Tools) -> list[str]:
    """Return only audit IDs for rows that cannot support evidence.

    A failed suspect checker is expected incident evidence, so it is not
    included unless the row is otherwise unusable. Held-out reviewed-good
    failures are included because they invalidate the reference arm.
    """
    failed: list[str] = []
    for result in tools.results:
        unusable = (
            result.status != "completed"
            or not result.activation.activated
            or result.run is None
            or result.run.checker_status != "completed"
            or (
                result.fixture_partition == "held_out"
                and result.configuration_id == "reviewed_good"
                and result.run.checker_passed is not True
            )
        )
        if unusable:
            failed.append(result.trial_id)
    for row in tools.held_out_validation:
        if row.get("status") != "completed" or (
            row.get("configuration_id") == "reviewed_good" and row.get("checker_passed") is not True
        ):
            trial_id = row.get("trial_id")
            if isinstance(trial_id, str):
                failed.append(trial_id)
    return list(dict.fromkeys(failed))


def _held_out_conflict_fixtures(profile: _DemoProfile) -> list[Scenario]:
    """Return two fresh held-out IDs, including a withheld memory conflict."""
    fixtures = list(profile.held_out)
    if not fixtures and profile.name == "memory-conflict":
        return [Scenario(order_id="ORD-HELDOUT-CONFLICT", customer_id="CUS-HO-C", order_age_days=21, amount=35, notes=[OBSOLETE_NOTE], expected_eligible=False), Scenario(order_id="ORD-HELDOUT-CONTROL", customer_id="CUS-HO-G", order_age_days=7, amount=35, notes=[], expected_eligible=True, control=True)]
    if profile.name == "memory-conflict" and not any(condition_matches_scenario(item, profile.condition) is True for item in fixtures):
        first = fixtures[0]
        fixtures[0] = first.model_copy(update={"scenario_id": uuid4().hex, "order_id": "ORD-HELDOUT-CONFLICT", "customer_id": "CUS-HO-C", "order_age_days": 21, "notes": [OBSOLETE_NOTE], "expected_eligible": False, "control": False})
    return fixtures[:2]


def _build_jev(config: Any, ledger: BudgetLedger, enabled: bool, case_id: str) -> OptionalJevTriage | None:
    if not enabled:
        return None
    return OptionalJevTriage(backend=TypeSafeJevBackend(api_key=config.typesafe_api_key), ledger=ledger, case_id=case_id)


def _inconclusive_result(*, db: str | Path, case_id: str, reason: str, backend: str, on_progress: Callable[[CaseFile], None] | None, origin: str) -> DemoResult:
    case = CaseFile(case_id=case_id, status="inconclusive", stop_reason=reason, backend=backend, evidence_origin=EvidenceOrigin(origin))
    with ArtifactStore(db) as store:
        InvestigationSession(store, case_id=case_id, on_progress=on_progress).checkpoint(case)
    return DemoResult(case=case, incident=None, db=str(db), evidence_origin=origin)


def _sync_budget_summary(budget: BudgetState, ledger: BudgetLedger | None) -> None:
    if ledger is None:
        return
    snapshot = ledger.snapshot()
    budget.spent_usd = snapshot.spent_usd
    budget.reserved_usd = snapshot.pending_usd


def run_demo(*, live: bool = False, backend: str = "local", jev: bool = False, approve_budget: bool = False, profile: str = "memory-conflict", db: str | Path = "results/faultline.sqlite3", ledger_path: str | Path | None = None, target_model: str | None = None, investigator_model: str | None = None, target: ReturnDesk | None = None, controller: InvestigatorController | None = None, on_progress: Callable[[CaseFile], None] | None = None, case_id: str | None = None) -> DemoResult:
    """Run an offline or explicitly live full investigation."""
    if backend not in {"local", "daytona"}:
        raise ValueError("backend must be local or daytona")
    selected_profile = _resolve_profile(profile)
    config = None
    ledger: BudgetLedger | None = None
    stable_case_id = case_id or uuid4().hex
    daytona_runner: DaytonaRunner | None = None
    injected_live_components = target is not None or controller is not None
    if live:
        from .config import load_config

        config = load_config()
        canonical_ledger = Path(__file__).resolve().parents[1] / "results" / "budget.sqlite3"
        selected_ledger = Path(ledger_path).resolve() if ledger_path is not None else canonical_ledger.resolve()
        if ledger_path is not None and selected_ledger != canonical_ledger.resolve() and not injected_live_components:
            raise ValueError("live production runs must use the canonical results/budget.sqlite3 ledger")
        target_model = target_model or config.openrouter_model
        worker_caps = {"worker": 0.10} if target_model == LLAMA_31_8B_INSTRUCT else None
        ledger = BudgetLedger(selected_ledger, ceiling_usd=min(10.0, config.max_total_usd), automation_cap_usd=2.0, case_cap_usd=1.0, category_caps_usd=worker_caps)
        if approve_budget:
            ledger.approve_automation(True)
        investigator_model = investigator_model or "deepseek/deepseek-v4.1-flash"
        target = target or load_configured_target(target_model, budget=ledger, case_id=stable_case_id)
        controller = controller or load_configured_investigator(investigator_model, budget=ledger, case_id=stable_case_id)
        if backend == "daytona":
            daytona_runner = DaytonaRunner(config=DaytonaConfig(api_key=config.daytona_api_key, api_url=config.daytona_api_url, ttl_minutes=config.daytona_ttl_minutes))
    else:
        target = target or ReturnDesk()
        controller = controller or BranchingStubController()
    assert target is not None and controller is not None

    if live and ledger is not None and hasattr(target.provider, "price_per_call"):
        boundary = TargetExecutionBoundary(
            backend="daytona" if backend == "daytona" else "local-subprocess",
            timeout_seconds=120,
            daytona_runner=daytona_runner,
        )
        # Local child execution receives the credential only through its
        # one-process environment. Daytona receives no credential by default;
        # deployments must provide an authorized sandbox secret mechanism.
        # The user explicitly authorized temporary per-command Daytona access.
        # Keep the credential in the process environment only; it is never
        # placed in the grant, trusted package, request JSON, or artifacts.
        command_env = {"OPENROUTER_API_KEY": target.provider.api_key} if getattr(target.provider, "api_key", None) else {}
        target = _GrantedTarget(target.provider, ledger, boundary, case_id=stable_case_id, command_env=command_env)

    budget = BudgetState(max_target_trials=40, max_investigator_calls=12, max_jev_calls=1)
    queue = IncidentQueue()
    stream = _run_direct(target, selected_profile.stream, budget)
    suite_runs = _run_direct(target, selected_profile.suite, budget)
    all_initial = stream + suite_runs
    incident_record: Incident | None = None
    incident_run: RunRecord | None = None
    for run in all_initial:
        candidate = queue.enqueue(run)
        if candidate is not None and incident_record is None:
            incident_record, incident_run = candidate, run
    scenarios = [run.scenario for run in all_initial]
    control = next((run.scenario for run in stream if run.scenario.control), next((run.scenario for run in all_initial if run.checker_passed is True), None))
    if incident_record is None or incident_run is None or control is None:
        tools = Tools(LocalTrialRunner(target, FixedClock()), budget, runs=list(all_initial))
        initial_infra = any(run.status == RunStatus.INFRASTRUCTURE_ERROR for run in all_initial)
        tools.stop_reason = "inconclusive:initial_infrastructure_errors" if initial_infra else "inconclusive:no_independent_failed_ledger"
        _sync_budget_summary(budget, ledger)
        case = tools.to_case_file(incident=None, scenarios=scenarios, status="inconclusive").model_copy(update={"case_id": stable_case_id})
        if "demo_profile" in CaseFile.model_fields:
            case = case.model_copy(update={"demo_profile": selected_profile.name})
        with ArtifactStore(db) as store:
            InvestigationSession(store, case_id=stable_case_id, on_progress=on_progress).checkpoint(case)
        return DemoResult(case=case, incident=None, db=str(db), evidence_origin="live" if live else "simulated", profile=selected_profile.name)

    if live and isinstance(target, _GrantedTarget):
        runner = _GrantedTrialRunner(target, FixedClock(), backend=target.boundary.backend)
    elif live:
        # A live workflow may never fall back to an in-process target.  The
        # parent-owned grant/boundary is the isolation and accounting seam;
        # callers that inject a live adapter must expose the same provider
        # contract so the wrapper above can be constructed.
        raise RuntimeError("live target must be executed through TargetExecutionBoundary")
    else:
        runner = LocalTrialRunner(target, FixedClock(), backend="local-subprocess")
    jev_backend = _build_jev(config, ledger, jev, stable_case_id) if live and ledger is not None else None
    # Keep the investigator's working set focused on the independently failed
    # source run. The complete fixture stream is attached to the case after
    # controller decisions so triage cannot accidentally inspect another
    # fixture's first policy/notes event.
    tools = _IncidentScopedTools(runner, budget, runs=[incident_run], jev=jev_backend, validation_pair={"incident": incident_run.scenario.scenario_id, "control": control.scenario_id}, incident_run_id=incident_run.run_id)
    with ArtifactStore(db) as store:
        session = InvestigationSession(store, case_id=stable_case_id, on_progress=on_progress)
        _persist_case(session, tools, incident=incident_record, scenarios=scenarios, profile_name=selected_profile.name)
        try:
            checkpoint = lambda: _persist_case(session, tools, incident=incident_record, scenarios=scenarios, profile_name=selected_profile.name)  # noqa: E731
            AdaptiveInvestigator(tools, _CheckpointingController(controller, checkpoint), validation_reserve_trials=25).investigate(incident_run.scenario, max_steps=12, control_scenario=control, original_suite_runs=suite_runs)
        except Exception as exc:
            tools.stop_reason = tools.stop_reason or f"inconclusive:investigator_error:{type(exc).__name__}"
        known_runs = {run.run_id for run in tools.runs}
        for run in all_initial:
            if run.run_id not in known_runs:
                tools.runs.append(run)
                known_runs.add(run.run_id)
        _persist_case(session, tools, incident=incident_record, scenarios=scenarios, profile_name=selected_profile.name)
        controller_stop = tools.stop_reason
        provisional_matrix_stop = controller_stop.startswith("inconclusive:missing_") or controller_stop.startswith("inconclusive:validation_pair_matrix") or controller_stop.startswith("inconclusive:incomplete_2x2_repetitions")
        safe_to_complete_evidence = not controller_stop or controller_stop in {"controller_finished", "validation_handoff"} or provisional_matrix_stop
        if safe_to_complete_evidence:
            try:
                _run_required_evidence(tools, incident_run.scenario, control, selected_profile)
                _run_regression_matrix(tools, incident_run.scenario, control)
                _run_held_out_matrix(tools, _held_out_conflict_fixtures(selected_profile))
            except Exception as exc:
                candidate_reason = exc.args[0] if isinstance(exc, RuntimeError) and len(exc.args) == 1 and isinstance(exc.args[0], str) else None
                trusted_reason = candidate_reason if candidate_reason in _TRUSTED_EVIDENCE_FAILURES else None
                tools.stop_reason = f"inconclusive:{trusted_reason}" if trusted_reason is not None else "inconclusive:evidence_phase"
                tools.observations.append(
                    {
                        "kind": "validation_failure",
                        "status": "inconclusive",
                        "reason": trusted_reason or "evidence_phase_failed",
                        "failed_trial_ids": _evidence_failure_trial_ids(tools),
                    }
                )
        else:
            tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": controller_stop})
        _persist_case(session, tools, incident=incident_record, scenarios=scenarios)
        # Held-out validation has separate fixture IDs and is reported on the
        # case, never promoted into the regression proposal.
        expected_inputs = {incident_run.scenario.scenario_id: incident_run.scenario, control.scenario_id: control}
        expected_ids = set(expected_inputs)
        matrix_spec_ids = {spec.experiment_id for spec in tools.experiments if spec.operator == "baseline" and spec.fixture_partition == "main" and spec.configuration_id in {"suspect", "reviewed_good"} and spec.source_scenario_id in expected_ids}
        suspect = [item for item in tools.results if item.configuration_id == "suspect" and item.experiment_id in matrix_spec_ids]
        reviewed_good = [item for item in tools.results if item.configuration_id == "reviewed_good" and item.experiment_id in matrix_spec_ids]
        tests = tools.propose_tests(suspect=suspect, reviewed_good=reviewed_good)
        if tests and not _supported_relevant_hypothesis(tools, selected_profile.intervention_operator):
            tools.stop_reason = "inconclusive:relevant_hypothesis_not_supported"
            tests = []
        candidate_conditions = {"order_age<=14", "customer_note", "memory_conflict", "age_boundary", selected_profile.condition}
        original_conditions = {condition for condition in candidate_conditions if any(condition_matches_scenario(item, condition) is True for item in selected_profile.suite)}
        coverage = assess_coverage(original_conditions=original_conditions, existing_grader_conditions={"order_age<=14"}, discovered_conditions={selected_profile.condition}, suspect=suspect, reviewed_good=reviewed_good, grader_observations=_grader_observations(tools.results, selected_profile.condition))
        proposal = None
        if tests:
            proposal = prepare_proposal(selected_profile.title, f"Derived from independently checked same-input suspect and reviewed-good configurations for {selected_profile.condition}; a human must approve the current digest before export.", tests, [item.trial_id for item in suspect + reviewed_good])
        if (tools.stop_reason in {"validation_handoff"} or tools.stop_reason.startswith("inconclusive:missing_") or tools.stop_reason.startswith("inconclusive:validation_pair_matrix") or tools.stop_reason.startswith("inconclusive:incomplete_2x2_repetitions")) and proposal is not None:
            # The adaptive controller may ask for a proposal before the
            # bounded matrix has been collected. Re-evaluate that provisional
            # stop after the matrix; retain infra/controller errors.
            tools.stop_reason = "validation_completed" if tools.stop_reason == "validation_handoff" else ""
        if not tools.stop_reason:
            tools.stop_reason = "controller_finished"
        if tools.stop_reason.startswith("inconclusive:"):
            # A proposal is evidence-bearing output. Never expose one after a
            # trusted validation failure or any other fail-closed stop.
            proposal = None
        status = "complete" if proposal is not None and not tools.stop_reason.startswith("inconclusive:") else "inconclusive"
        incident_record.status = status  # type: ignore[assignment]
        _sync_budget_summary(budget, ledger)
        case = _persist_case(session, tools, incident=incident_record, scenarios=scenarios, coverage=coverage, proposal=proposal, status=status, profile_name=selected_profile.name)
    return DemoResult(case=case, incident=incident_record, proposal_digest=proposal.digest if proposal else None, db=str(db), evidence_origin="live" if live else "simulated", profile=selected_profile.name)
