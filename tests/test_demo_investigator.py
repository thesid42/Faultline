from __future__ import annotations

from faultline.clock import FixedClock
from faultline.investigator import BranchingStubController, Tools
from faultline.models import ActivationReceipt, Event, ExperimentResult, ExperimentSpec, Hypothesis, RunRecord, Scenario
from faultline.return_desk import ReturnDesk
from faultline.trials import LocalTrialRunner
from faultline.models import BudgetState


def _scenario(scenario_id: str, *, amount: float = 10.0) -> Scenario:
    return Scenario(scenario_id=scenario_id, order_id=f"order-{scenario_id}", customer_id=f"customer-{scenario_id}", order_age_days=7, amount=amount, expected_eligible=True)


def _source_run(scenario: Scenario) -> RunRecord:
    return RunRecord(scenario=scenario, configuration_id="default", checker_status="completed", checker_passed=False)


def _spec(*, operator: str, scenario: Scenario, source_run: RunRecord, configuration_id: str, source_role: str = "incident", value=None) -> ExperimentSpec:
    return ExperimentSpec.model_construct(
        experiment_id=f"exp-{configuration_id}-{scenario.scenario_id}-{operator}-{source_role}",
        hypothesis_id="hypothesis-1",
        name=operator,
        operator=operator,
        value=value,
        source_scenario_id=scenario.scenario_id,
        source_run_id=source_run.run_id,
        source_role=source_role,
        configuration_id=configuration_id,
        fixture_partition="main",
        repetitions=3,
        timeout_seconds=120,
        rationale="test",
    )


def _results(spec: ExperimentSpec, scenario: Scenario, *, source_run: RunRecord, violation: bool) -> list[ExperimentResult]:
    rows: list[ExperimentResult] = []
    for repetition in range(1, 4):
        run = RunRecord(
            scenario=scenario,
            source_run_id=source_run.run_id,
            configuration_id=spec.configuration_id,
            fixture_partition="main",
            checker_status="completed",
            checker_passed=not violation,
        )
        trial_id = f"trial-{spec.experiment_id}-{repetition}"
        activation = ActivationReceipt(
            experiment_id=spec.experiment_id,
            trial_id=trial_id,
            activated=True,
            operator=str(spec.operator),
            source_scenario_id=scenario.scenario_id,
            configuration_id=spec.configuration_id,
            before_digest="before",
            after_digest="after",
        )
        rows.append(ExperimentResult(
            trial_id=trial_id,
            experiment_id=spec.experiment_id,
            scenario_id=scenario.scenario_id,
            source_run_id=source_run.run_id,
            configuration_id=spec.configuration_id,
            fixture_partition="main",
            repetition=repetition,
            activation=activation,
            status="completed",
            run=run,
            observed_violation=violation,
        ))
    return rows


def _tools(*, validation_pair: dict[str, str] | None = None) -> Tools:
    return Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState(), validation_pair=validation_pair)


def test_triage_uses_gateway_attempt_and_unit_trace_without_profile_labels() -> None:
    scenario = _scenario("trace")
    run = RunRecord(
        scenario=scenario,
        checker_status="completed",
        checker_passed=False,
        events=[
            Event(actor="target", kind="retrieve_order", payload={"order_id": scenario.order_id, "amount": scenario.amount, "refund_api_unit": "minor", "amount_mismatch": True, "delivery_attempts": 3}),
            Event(actor="target", kind="retrieve_policy", payload={"max_age_days": 14}),
            Event(actor="target", kind="retrieve_notes", payload={"notes": ["A 30-day window applies."]}),
            Event(actor="target", kind="execute", payload={"duplicate_refund": True, "ledger_entries": 2, "idempotency_key": "refund:trace"}),
        ],
    )
    tools = _tools()
    hypotheses = tools.triage_hypotheses([run], selected_run=run)
    families = {item.predicates.get("family") for item in hypotheses}
    assert {"memory", "policy", "amount_units", "idempotency"}.issubset(families)
    assert not any("expected_eligible" in item.predicates for item in hypotheses)
    idempotency = next(item for item in hypotheses if item.predicates.get("family") == "idempotency")
    assert idempotency.predicates["delivery_attempts"] == 3
    amount = next(item for item in hypotheses if item.predicates.get("family") == "amount_units")
    assert amount.predicates["refund_api_unit"] == "minor"


def test_stub_controller_prioritizes_observed_duplicate_or_unit_evidence() -> None:
    duplicate = {"kind": "hypotheses", "hypotheses": [{"hypothesis_id": "h-id", "predicates": {"family": "idempotency", "delivery_attempts": 3, "duplicate_signal": True}}]}
    choice = BranchingStubController._next_observed_intervention([duplicate])
    assert choice and choice["operator"] == "delivery_attempts"
    unit = {"kind": "hypotheses", "hypotheses": [{"hypothesis_id": "h-unit", "predicates": {"family": "amount_units", "refund_api_unit": "minor", "amount_mismatch": True}}]}
    choice = BranchingStubController._next_observed_intervention([unit])
    assert choice and choice["operator"] == "refund_api_unit" and choice["value"] == "major"
    memory = {"kind": "hypotheses", "hypotheses": [{"hypothesis_id": "h-memory", "predicates": {"family": "memory", "note_text": "A 30-day window applies."}}]}
    choice = BranchingStubController._next_observed_intervention([memory])
    assert choice and choice["operator"] == "remove_note" and choice["value"] == "A 30-day window applies."


def _matrix_tools() -> tuple[Tools, Scenario, Scenario, list[ExperimentResult], list[ExperimentResult]]:
    incident = _scenario("incident", amount=20.0)
    control = _scenario("control", amount=25.0)
    source_incident = _source_run(incident)
    source_control = _source_run(control)
    tools = _tools(validation_pair={"incident": incident.scenario_id, "control": control.scenario_id})
    tools.runs.extend([source_incident, source_control])
    suspect: list[ExperimentResult] = []
    reviewed: list[ExperimentResult] = []
    for configuration, destination in (("suspect", suspect), ("reviewed_good", reviewed)):
        for role, scenario, source, violation in (
            ("incident", incident, source_incident, configuration == "suspect"),
            ("control", control, source_control, False),
        ):
            spec = _spec(operator="baseline", scenario=scenario, source_run=source, configuration_id=configuration, source_role=role)
            tools.experiments.append(spec)
            destination.extend(_results(spec, scenario, source_run=source, violation=violation))
    return tools, incident, control, suspect, reviewed


def test_validation_pair_accepts_eligible_incident_and_preserves_rule_expectation() -> None:
    tools, _incident, _control, suspect, reviewed = _matrix_tools()
    proposal = tools.propose_tests(suspect=suspect, reviewed_good=reviewed)
    assert proposal
    assert len(proposal[0]["cases"]) == 12
    assert all(case["validation_role"] in {"incident", "control"} for case in proposal[0]["cases"])
    assert all(case["expected_eligible"] is True for case in proposal[0]["cases"])


def test_validation_pair_rejects_mixed_failure_and_invalid_rows() -> None:
    tools, _incident, control, suspect, reviewed = _matrix_tools()
    reviewed_control = next(item for item in reviewed if item.scenario_id == control.scenario_id)
    reviewed[reviewed.index(reviewed_control)] = reviewed_control.model_copy(update={"observed_violation": True, "run": reviewed_control.run.model_copy(update={"checker_passed": False})})
    assert tools.propose_tests(suspect=suspect, reviewed_good=reviewed) == []
    assert tools.stop_reason == "inconclusive:validation_pair_pass_regression"

    tools, _incident, _control, suspect, reviewed = _matrix_tools()
    invalid = next(item for item in suspect if item.scenario_id == "incident")
    suspect[suspect.index(invalid)] = invalid.model_copy(update={"status": "infrastructure_error", "run": None})
    assert tools.propose_tests(suspect=suspect, reviewed_good=reviewed) == []
    assert tools.stop_reason == "inconclusive:validation_pair_matrix"


def test_validation_pair_rejects_cross_arm_full_scenario_mismatch() -> None:
    tools, incident, _control, suspect, reviewed = _matrix_tools()
    altered = incident.model_copy(update={"amount": 99.0})
    for index, result in enumerate(reviewed):
        if result.scenario_id == incident.scenario_id:
            reviewed[index] = result.model_copy(update={"run": result.run.model_copy(update={"scenario": altered})})
    assert tools.propose_tests(suspect=suspect, reviewed_good=reviewed) == []
    assert tools.stop_reason == "inconclusive:validation_pair_scenario_mismatch"


def test_strict_amount_evidence_requires_three_complete_relevant_batches() -> None:
    scenario = _scenario("strict")
    source = _source_run(scenario)
    tools = _tools(validation_pair={"incident": scenario.scenario_id, "control": "control-id"})
    tools.runs.append(source)
    hypothesis = Hypothesis(statement="wrong unit", predicates={"family": "amount_units", "refund_api_unit": "minor", "source_run_id": source.run_id, "source_scenario_id": scenario.scenario_id})
    tools.hypotheses = [hypothesis]
    batches = [
        (_spec(operator="baseline", scenario=scenario, source_run=source, configuration_id="default"), True),
        (_spec(operator="refund_api_unit", scenario=scenario, source_run=source, configuration_id="default", value="major"), False),
        (_spec(operator="unrelated_note", scenario=scenario, source_run=source, configuration_id="default", value="Customer prefers phone contact."), True),
    ]
    for spec, violation in batches:
        tools.experiments.append(spec)
        tools.results.extend(_results(spec, scenario, source_run=source, violation=violation))
    tools._recompute_strict_hypothesis_evidence()
    assert hypothesis.status == "supported"
    tools.results[-1] = tools.results[-1].model_copy(update={"observed_violation": False, "run": tools.results[-1].run.model_copy(update={"checker_passed": True})})
    tools._recompute_strict_hypothesis_evidence()
    assert hypothesis.status == "unknown"
