from __future__ import annotations

import time
from datetime import timedelta

import pytest

from faultline.clock import FixedClock
from faultline.coverage import assess_coverage, condition_matches_scenario
from faultline.export import approve, export_proposal, prepare_proposal
from faultline.cli import approve_export
from faultline.incidents import IncidentQueue
from faultline.investigator import AdaptiveInvestigator, BranchingStubController, Tools
from faultline.models import Action, BudgetState, ExperimentSpec, EvidenceOrigin, Scenario, utc_now
from faultline.return_desk import RefundTool, ReturnDesk, RuleChecker
from faultline.scenarios import OBSOLETE_NOTE, PREFERENCE_NOTE, held_out, incident, legitimate_control
from faultline.trials import LocalTrialRunner
from faultline.storage import ArtifactStore


def test_checker_boundary_and_refund_tool_identity_and_total() -> None:
    checker = RuleChecker()
    at_boundary = Scenario(order_id="x", customer_id="c", order_age_days=14, amount=10)
    after_boundary = at_boundary.model_copy(update={"order_age_days": 15})
    assert checker.expected_eligible(at_boundary)
    assert not checker.expected_eligible(after_boundary)
    ledger: list[dict[str, object]] = []
    tool = RefundTool(ledger)
    tool.issue_refund(order_id="x", customer_id="c", amount=10, idempotency_key="i", expected_order_id="x", expected_customer_id="c", expected_amount=10)
    with pytest.raises(ValueError, match="total"):
        tool.issue_refund(order_id="x", customer_id="c", amount=10, idempotency_key="second", expected_order_id="x", expected_customer_id="c", expected_amount=10)
    assert checker.check(at_boundary, Action(kind="refund", order_id="x", amount=10, reason="", idempotency_key="i"), ledger)[0]
    ledger.append({"kind": "refund", "order_id": "x", "customer_id": "wrong", "amount": 10, "idempotency_key": "bad"})
    assert checker.check(at_boundary, None, ledger)[0] is False


def test_checker_accepts_denial_or_escalation_for_ineligible_and_rejects_eligible_denial() -> None:
    checker = RuleChecker()
    denied = Scenario(order_id="old", customer_id="c", order_age_days=21, amount=10)
    action = Action(kind="deny", order_id="old", idempotency_key="d")
    assert checker.check(denied, action, [])[0] is True
    escalation = Action(kind="escalate", order_id="old", idempotency_key="e")
    assert checker.check(denied, escalation, [{"kind": "escalation", "order_id": "old", "idempotency_key": "e"}])[0] is True
    eligible = denied.model_copy(update={"order_age_days": 7})
    assert checker.check(eligible, Action(kind="deny", order_id="old", idempotency_key="d2"), [])[0] is False


def test_idempotent_retry_returns_original_but_reuse_with_changed_arguments_rejects() -> None:
    ledger: list[dict[str, object]] = []
    tool = RefundTool(ledger)
    first = tool.issue_refund(order_id="x", customer_id="c", amount=10, idempotency_key="same")
    assert tool.issue_refund(order_id="x", customer_id="c", amount=10, idempotency_key="same") is first
    with pytest.raises(ValueError, match="idempotency"):
        tool.issue_refund(order_id="x", customer_id="c", amount=9, idempotency_key="same")


class WrongIdProvider:
    evidence_origin = EvidenceOrigin.SIMULATED
    model = "wrong-id-fixture"
    provider = "test"
    backend = "local"
    version = "1"

    def choose_action(self, *, order, policy, notes):
        return Action(kind="refund", order_id="other", amount=order["amount"], idempotency_key="bad")


class MissingOriginProvider:
    model = "missing-origin-fixture"
    provider = "test"
    backend = "local"
    version = "1"

    def choose_action(self, *, order, policy, notes):
        return Action(kind="deny", order_id=order["order_id"], amount=None, idempotency_key="deny")


def test_return_desk_fails_closed_on_wrong_id_and_missing_provenance() -> None:
    scenario = Scenario(order_id="x", customer_id="c", order_age_days=7, amount=10)
    wrong_id = ReturnDesk(WrongIdProvider()).run(scenario)
    assert wrong_id.actual_ledger == []
    assert wrong_id.status.value == "invalid"
    missing = ReturnDesk(MissingOriginProvider()).run(scenario)
    assert missing.status.value == "invalid"
    assert missing.evidence_origin is EvidenceOrigin.SIMULATED


def test_activation_receipt_and_invalid_exclusion() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    invalid = runner.run(ExperimentSpec(hypothesis_id="h", name="bad", operator="order_age", value="15", repetitions=1), incident())[0]
    assert invalid.status == "excluded"
    assert not invalid.activation.activated
    valid = runner.run(ExperimentSpec(hypothesis_id="h", name="good", operator="remove_note", value=incident().notes[0], repetitions=1), incident())[0]
    assert valid.activation.activated
    assert valid.status == "completed"


def test_baseline_is_valid_unchanged_and_trial_callbacks_stay_parent_side() -> None:
    calls = []

    def reserve(spec, scenario, trial_id):
        calls.append(("reserve", spec.operator, scenario.scenario_id, trial_id))
        return {"grant": "local"}

    def reconcile(spec, scenario, trial_id, run, reservation):
        calls.append(("reconcile", spec.operator, scenario.scenario_id, trial_id, run is not None, reservation))

    runner = LocalTrialRunner(ReturnDesk(), FixedClock(), reserve_trial=reserve, reconcile_trial=reconcile)
    result = runner.run(ExperimentSpec(hypothesis_id="h", name="baseline", operator="baseline", repetitions=1), incident())[0]
    assert result.status == "completed"
    assert result.activation.activated and result.activation.before_digest == result.activation.after_digest
    assert result.run is not None and result.run.activation_receipts
    assert calls[0][0] == "reserve" and calls[-1][0] == "reconcile"


def test_held_out_validation_consumes_budget_and_retains_trace() -> None:
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState())
    validation = tools.validate_held_out(held_out())
    assert len(validation) == 2
    assert tools.budget.target_trials == 2
    assert all(item["trace_digest"] and item["run"]["events"] for item in validation)
    case = tools.to_case_file(status="complete")
    assert len(case.held_out_validation) == 2


def test_adaptive_controller_branches_and_terminates() -> None:
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState())
    results = AdaptiveInvestigator(tools, BranchingStubController()).investigate(incident(), max_steps=12)
    assert results
    assert any(result.activation.operator == "remove_note" for result in results)
    assert any(result.activation.operator == "unrelated_note" for result in results)
    assert any(item.get("kind") == "hypotheses" for item in tools.observations)
    assert any(item.get("kind") == "suite_check" for item in tools.observations)
    assert any(item.get("kind") == "propose_tests" for item in tools.observations)
    assert tools.budget.investigator_calls <= 12
    assert tools.stop_reason.startswith("inconclusive:")
    memory = next(item for item in tools.hypotheses if item.predicates.get("family") == "memory")
    assert memory.status == "supported"
    assert all(result.status == "completed" for result in results)


def test_unrelated_note_control_keeps_obsolete_memory() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    result = runner.run(ExperimentSpec(hypothesis_id="h", name="control", operator="unrelated_note", value="Customer prefers phone contact.", repetitions=1), incident())[0]
    assert result.activation.activated
    assert result.status == "completed"
    assert result.observed_violation is True
    assert result.run is not None
    assert any("30-day" in note for note in result.run.scenario.notes)



class SlowProvider:
    evidence_origin = EvidenceOrigin.SIMULATED
    model = "slow-fixture"
    provider = "test"
    backend = "local"
    version = "1"

    def choose_action(self, *, order, policy, notes):
        time.sleep(2)
        return Action(kind="deny", order_id=order["order_id"], idempotency_key="slow")


def test_timeout_is_killable_and_does_not_claim_agent_failure() -> None:
    runner = LocalTrialRunner(ReturnDesk(SlowProvider()), FixedClock())
    result = runner.run(ExperimentSpec(hypothesis_id="h", name="timeout", operator="order_age", value=15, repetitions=1, timeout_seconds=1), incident())[0]
    assert result.status == "infrastructure_error"
    assert result.observed_violation is None


def test_budget_reservation_includes_inflight_and_soft_stop() -> None:
    budget = BudgetState(soft_ceiling_usd=1, hard_ceiling_usd=2)
    budget.reserve(0.75)
    with pytest.raises(RuntimeError, match="soft"):
        budget.reserve(0.30)


def test_incident_deduplication_requires_independent_failure() -> None:
    target = ReturnDesk()
    queue = IncidentQueue()
    failing = target.run(incident())
    assert queue.enqueue(failing) is not None
    assert queue.enqueue(failing) is queue.all()[0]
    assert queue.enqueue(target.run(legitimate_control())) is None


def test_coverage_keeps_unknown_separate_from_missed() -> None:
    coverage = assess_coverage(original_conditions={"age_boundary"}, existing_grader_conditions={"ordinary_refund"}, suspect=[], reviewed_good=[])
    by_name = {item.condition: item for item in coverage}
    assert by_name["age_boundary"].original_suite == "present"
    assert by_name["age_boundary"].grader_observed == "unknown"
    assert by_name["ordinary_refund"].original_suite == "missing"


def test_shared_coverage_predicates_and_mixed_grader_counts() -> None:
    stale = Scenario(order_id="x", customer_id="c", order_age_days=21, amount=1, notes=["A 30-day window applies."])
    assert condition_matches_scenario(stale, "memory_conflict") is True
    assert condition_matches_scenario(stale.model_copy(update={"notes": []}), "memory_conflict") is False
    assert condition_matches_scenario(stale.model_copy(update={"order_age_days": 7}), "memory_conflict") is False
    assert condition_matches_scenario(stale.model_copy(update={"order_age_days": 31}), "memory_conflict") is False


def test_policy_diagnosis_quotes_observed_note_and_event_link() -> None:
    run = ReturnDesk().run(incident())
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState(), runs=[run])
    hypotheses = tools.triage_hypotheses([run])
    memory = [item for item in hypotheses if item.predicates.get("family") == "memory" and item.predicates.get("note_text") == OBSOLETE_NOTE]
    assert memory
    assert memory[0].predicates["evidence_event_id"]
    observed = next(item for item in tools.observations if item.get("kind") == "hypotheses")
    assert any(item["statement"].find(OBSOLETE_NOTE) >= 0 for item in observed["hypotheses"])


def test_order_age_intervention_keeps_incident_source() -> None:
    class Controller:
        def __init__(self):
            self.done = False

        def next_action(self, observations):
            if self.done:
                return {"kind": "finish"}
            self.done = True
            return {"kind": "run_experiment", "operator": "order_age", "value": 7, "source": "incident"}

    source = incident()
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState())
    results = AdaptiveInvestigator(tools, Controller()).investigate(source, max_steps=2)
    assert results
    assert all(result.scenario_id == source.scenario_id for result in results)
    assert all(result.run is not None and result.run.scenario.order_age_days == 7 for result in results)


def test_unrelated_note_control_preserves_policy_and_obsolete_notes() -> None:
    scenario = incident().model_copy(update={"notes": ["Refunds are allowed up to 14 days.", OBSOLETE_NOTE, PREFERENCE_NOTE]})
    result = LocalTrialRunner(ReturnDesk(), FixedClock()).run(ExperimentSpec(hypothesis_id="h", name="control", operator="unrelated_note", value="Customer prefers phone contact.", repetitions=1), scenario)[0]
    assert result.activation.activated and result.run is not None
    assert "Refunds are allowed up to 14 days." in result.run.scenario.notes
    assert OBSOLETE_NOTE in result.run.scenario.notes
    assert "Customer prefers phone contact." in result.run.scenario.notes


def test_configuration_ids_define_arms_even_when_outputs_disagree() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    tools = Tools(runner, BudgetState())
    incident_case = incident()
    control_case = legitimate_control()
    suspect_spec = ExperimentSpec(hypothesis_id="h", name="suspect", operator="baseline", configuration_id="suspect_config", repetitions=3)
    suspect_fail = tools.run_experiment(suspect_spec, incident_case)
    suspect_control = tools.run_experiment(suspect_spec, control_case)
    good_spec = ExperimentSpec(hypothesis_id="h", name="reviewed", operator="baseline", configuration_id="reviewed_good_config", repetitions=3)
    good_fail = tools.run_experiment(good_spec, incident_case)
    good_control = tools.run_experiment(good_spec, control_case)
    good_fail[0].run.checker_passed = False  # type: ignore[union-attr]
    assert tools._result_arm(suspect_control[0]) == "suspect"
    assert tools._result_arm(good_fail[0]) == "reviewed_good"
    proposal = tools.propose_tests(suspect=suspect_fail + suspect_control, reviewed_good=good_fail + good_control)
    assert proposal == []
    assert tools.stop_reason == "inconclusive:reviewed_good_configuration_failed"


def test_default_or_unknown_outputs_never_define_configuration_arms() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    tools = Tools(runner, BudgetState())
    default_result = tools.run_experiment(ExperimentSpec(hypothesis_id="h", name="default", operator="baseline", repetitions=1), incident())[0]
    unknown_result = tools.run_experiment(ExperimentSpec(hypothesis_id="h", name="unknown", operator="baseline", configuration_id="unreviewed-v2", repetitions=1), incident())[0]
    assert tools._result_arm(default_result) is None
    assert tools._result_arm(unknown_result) is None


def test_proposal_requires_matched_eligible_and_ineligible_fixtures_in_both_arms() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    tools = Tools(runner, BudgetState())
    suspect = []
    reviewed = []
    for config, destination in (("suspect_config", suspect), ("reviewed_good_config", reviewed)):
        destination.extend(tools.run_experiment(ExperimentSpec(hypothesis_id="h", name=config, operator="baseline", configuration_id=config, repetitions=1), incident()))
        # A single ineligible fixture is not a validated denied/allowed pair.
    assert tools.propose_tests(suspect=suspect, reviewed_good=reviewed) == []
    assert tools.stop_reason == "inconclusive:incomplete_2x2_repetitions"


def test_valid_explicit_configuration_matrix_retains_suspect_failure() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    tools = Tools(runner, BudgetState())
    suspect = []
    reviewed = []
    incident_case = incident()
    control_case = legitimate_control()
    for config, destination in (("suspect_config", suspect), ("reviewed_good_config", reviewed)):
        destination.extend(tools.run_experiment(ExperimentSpec(hypothesis_id="h", name=config, operator="baseline", configuration_id=config, repetitions=3), incident_case))
        destination.extend(tools.run_experiment(ExperimentSpec(hypothesis_id="h", name=config, operator="baseline", configuration_id=config, repetitions=3), control_case))
    proposal = tools.propose_tests(suspect=suspect, reviewed_good=reviewed)
    assert proposal
    assert any(case["arm"] == "suspect" and case["observed_violation"] is True for case in proposal[0]["cases"])


def test_incomplete_repetition_matrix_preserves_infrastructure_row_reasons() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    tools = Tools(runner, BudgetState())
    incident_case = incident()
    control_case = legitimate_control()
    suspect = []
    reviewed = []
    for config, destination in (("suspect", suspect), ("reviewed_good", reviewed)):
        destination.extend(tools.run_experiment(ExperimentSpec(hypothesis_id="h", name=config, operator="baseline", configuration_id=config, repetitions=3), incident_case))
        destination.extend(tools.run_experiment(ExperimentSpec(hypothesis_id="h", name=config, operator="baseline", configuration_id=config, repetitions=3), control_case))
    failed = next(result for result in reviewed if result.scenario_id == control_case.scenario_id)
    failed.status = "infrastructure_error"
    failed.run = None
    failed.excluded_reason = "worker timeout"
    assert tools.propose_tests(suspect=suspect, reviewed_good=reviewed) == []
    assert tools.stop_reason == "inconclusive:incomplete_2x2_repetitions"
    observation = next(item for item in reversed(tools.observations) if item.get("kind") == "propose_tests")
    assert observation["raw"]["excluded_rows"] >= 1
    assert any(row["reason"] == "result_status:infrastructure_error" for row in observation["raw"]["excluded"])


def test_matrix_rejects_same_id_with_changed_actual_scenario_inputs() -> None:
    runner = LocalTrialRunner(ReturnDesk(), FixedClock())
    tools = Tools(runner, BudgetState())
    incident_case = incident()
    control_case = legitimate_control()
    reviewed_incident = incident_case.model_copy(update={"notes": ["edited note"]})
    reviewed_control = control_case.model_copy(update={"notes": ["edited note"]})
    suspect = []
    reviewed = []
    for config, scenarios, destination in (("suspect", (incident_case, control_case), suspect), ("reviewed_good", (reviewed_incident, reviewed_control), reviewed)):
        for scenario in scenarios:
            destination.extend(tools.run_experiment(ExperimentSpec(hypothesis_id="h", name=config, operator="baseline", configuration_id=config, repetitions=3), scenario))
    assert tools.propose_tests(suspect=suspect, reviewed_good=reviewed) == []
    assert tools.stop_reason == "inconclusive:scenario_input_mismatch_between_arms"


def test_triage_and_inspection_use_explicit_selected_incident_trace() -> None:
    suite_run = ReturnDesk().run(Scenario(order_id="suite", customer_id="suite-c", order_age_days=14, amount=10, notes=["Refunds are allowed up to 14 days."]))
    incident_run = ReturnDesk().run(incident())
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState(), runs=[suite_run, incident_run])
    hypotheses = tools.triage_hypotheses(tools.runs, selected_run=incident_run)
    assert any(item.predicates.get("note_text") == OBSOLETE_NOTE for item in hypotheses)
    assert not any(item.predicates.get("note_text") == "Refunds are allowed up to 14 days." for item in hypotheses)
    assert tools.check_suite(tools.runs, original_suite_runs=[suite_run])["total"] == 1


def test_unusable_later_evidence_does_not_overwrite_supported_rationale() -> None:
    source = incident()
    source_run = ReturnDesk().run(source)
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState(), runs=[source_run])
    hypothesis = next(item for item in tools.triage_hypotheses([source_run]) if item.predicates.get("family") == "memory")
    hypothesis.status = "supported"
    hypothesis.rationale = "earlier causal evidence"
    spec = ExperimentSpec(hypothesis_id=hypothesis.hypothesis_id, name="unmatched", operator="baseline", repetitions=3, source_scenario_id=source.scenario_id)
    tools.run_experiment(spec, source)
    assert hypothesis.status == "supported"
    assert hypothesis.rationale == "earlier causal evidence"
    assert any(item.get("kind") == "hypothesis_evidence" and item.get("status") == "unusable" for item in tools.observations)


def test_budget_deadline_blocks_new_target_and_investigator_work() -> None:
    expired = BudgetState(started_at=utc_now() - timedelta(seconds=601))
    assert not expired.can_target_trial()
    assert not expired.can_investigate()
    defaults = BudgetState()
    assert defaults.soft_ceiling_usd == 2
    assert defaults.hard_ceiling_usd == 10
    assert defaults.max_case_seconds == 600


def test_controller_failure_is_explicitly_inconclusive() -> None:
    class BrokenController:
        def next_action(self, observations):
            raise ValueError("controller fixture failure")

    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState())
    AdaptiveInvestigator(tools, BrokenController()).investigate(incident(), max_steps=1)
    assert tools.stop_reason == "inconclusive:controller_error:ValueError"


def test_held_out_fixtures_withhold_conflict_note_and_use_separate_ids() -> None:
    withheld = held_out()
    assert len(withheld) == 2
    assert withheld[0].scenario_id != withheld[1].scenario_id
    assert OBSOLETE_NOTE in withheld[0].notes
    assert OBSOLETE_NOTE not in withheld[1].notes


def test_note_intervention_cannot_support_policy_retrieval_or_missing_baseline() -> None:
    source = incident()
    run = ReturnDesk().run(source)
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState(), runs=[run])
    policy = next(item for item in tools.triage_hypotheses([run]) if item.predicates.get("family") == "policy")
    spec = ExperimentSpec(hypothesis_id=policy.hypothesis_id, name="notes", operator="policy_notes", value="reviewed_policy", source_scenario_id=run.scenario.scenario_id, source_run_id=run.run_id)
    tools.run_experiment(spec, source)
    assert policy.status == "open"
    assert "does not test policy retrieval" in policy.rationale


def test_held_out_action_without_resolved_fixture_is_inconclusive() -> None:
    class Controller:
        def next_action(self, observations):
            return {"kind": "run_experiment", "operator": "baseline", "source": "held_out", "value": "missing-held-out"}

    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState())
    AdaptiveInvestigator(tools, Controller()).investigate(incident(), max_steps=1)
    assert tools.stop_reason == "inconclusive:held_out_source_unresolved"
    assert tools.budget.target_trials == 0


def test_review_gate_invalidates_changed_proposal_and_exports_correctness() -> None:
    proposal = prepare_proposal("t", "r", [{"cases": [{"scenario": incident().model_dump(mode="json"), "expected_eligible": False, "observed_violation": True}]}], [])
    approval = approve(proposal, "reviewer")
    proposal.rationale = "changed after approval"
    with pytest.raises(PermissionError):
        export_proposal(proposal, approval, "artifacts/invalid-export")
    proposal = prepare_proposal("t", "r", [{"cases": []}], [])
    approval = approve(proposal, "reviewer")
    test_file, json_file = export_proposal(proposal, approval, "artifacts/export")
    source = test_file.read_text(encoding="utf-8")
    assert "checker_passed is True" in source
    assert "not case[\"observed_violation\"]" not in source
    assert json_file.exists()


def test_approve_export_requires_id_for_ambiguous_proposals(tmp_path) -> None:
    db = tmp_path / "case.sqlite3"
    first = prepare_proposal("first", "r", [{"cases": []}], [])
    second = prepare_proposal("second", "r", [{"cases": []}], [])
    with ArtifactStore(db) as store:
        store.put("proposal", first, first.proposal_id)
        store.put("proposal", second, second.proposal_id)
    with pytest.raises(RuntimeError, match="proposal-id"):
        approve_export(str(db), str(tmp_path / "ambiguous"), "reviewer")
    result = approve_export(str(db), str(tmp_path / "selected"), "reviewer", second.proposal_id)
    assert result["proposal_id"] == second.proposal_id
