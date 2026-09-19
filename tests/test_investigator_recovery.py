from __future__ import annotations

from datetime import datetime, timezone

from faultline.clock import FixedClock
from faultline.investigator import AdaptiveInvestigator, Tools
from faultline.models import BudgetState, ControllerAction, ExperimentSpec
from faultline.return_desk import ReturnDesk
from faultline.scenarios import OBSOLETE_NOTE, incident
from faultline.trials import LocalTrialRunner


def _tools() -> Tools:
    desk = ReturnDesk()
    return Tools(
        runner=LocalTrialRunner(
            desk, FixedClock(datetime(2025, 1, 15, 12, tzinfo=timezone.utc))
        ),
        budget=BudgetState(),
    )


class NullThenValid:
    corrected = False

    def next_action(self, observations: list[dict]) -> ControllerAction:
        if not observations:
            return ControllerAction(kind="probe_case")
        kinds = [item.get("kind") for item in observations]
        if kinds[-1] == "trace" and "hypotheses" not in kinds:
            return ControllerAction(kind="triage_hypotheses")
        if not self.corrected and any(kind == "invalid_experiment_plan" for kind in kinds):
            self.corrected = True
            return ControllerAction(
                kind="run_experiment",
                operator="remove_note",
                value=OBSOLETE_NOTE,
                rationale="remove the exact obsolete note named by the trace",
            )
        if not self.corrected and kinds[-1] == "hypotheses":
            return ControllerAction(
                kind="run_experiment",
                operator="policy_notes",
                value=None,
                rationale="check the policy retrieval path",
            )
        return ControllerAction(kind="finish", rationale="recovery regression complete")


def test_malformed_plan_is_preflighted_then_valid_correction_runs() -> None:
    tools = _tools()
    controller = NullThenValid()
    AdaptiveInvestigator(tools, controller).investigate(incident(), max_steps=8)

    invalid = [item for item in tools.observations if item.get("kind") == "invalid_experiment_plan"]
    assert len(invalid) == 1
    assert invalid[0]["operator"] == "policy_notes"
    assert invalid[0]["value"] is None
    assert invalid[0]["error_code"] == "missing_string_value"
    assert invalid[0]["correction_contract"]["value_type"] == "non-empty string"
    assert tools.budget.target_trials == 4  # one probe plus one three-repetition experiment
    assert tools.results
    assert all(item.status == "completed" and item.activation.activated for item in tools.results)
    assert tools.experiments[-1].rationale == "remove the exact obsolete note named by the trace"
    assert tools.stop_reason == "controller_finished"


class AlwaysMalformed:
    def next_action(self, observations: list[dict]) -> ControllerAction:
        if not observations:
            return ControllerAction(kind="probe_case")
        kinds = [item.get("kind") for item in observations]
        if kinds[-1] == "trace" and "hypotheses" not in kinds:
            return ControllerAction(kind="triage_hypotheses")
        return ControllerAction(kind="run_experiment", operator="policy_notes", value=None)


def test_permanently_malformed_plan_stops_inconclusive_without_trials() -> None:
    tools = _tools()
    AdaptiveInvestigator(tools, AlwaysMalformed()).investigate(incident(), max_steps=12)

    assert tools.stop_reason == "inconclusive:controller_no_progress"
    assert tools.budget.target_trials == 1
    warnings = [item for item in tools.observations if item.get("kind") == "controller_recovery"]
    assert warnings and warnings[0]["status"] == "warning"
    assert warnings[0]["correction_contract"]["value_type"] == "non-empty string"
    assert any(item.get("kind") == "invalid_experiment_plan" for item in tools.observations)
    assert not tools.results


class RepeatingInspect:
    def next_action(self, observations: list[dict]) -> ControllerAction:
        if not observations:
            return ControllerAction(kind="probe_case")
        return ControllerAction(kind="inspect_trace")


def test_repeated_inspection_gets_recovery_warning_then_bounded_stop() -> None:
    tools = _tools()
    AdaptiveInvestigator(tools, RepeatingInspect()).investigate(incident(), max_steps=12)

    assert tools.stop_reason == "inconclusive:controller_no_progress"
    warning = next(item for item in tools.observations if item.get("kind") == "controller_recovery")
    assert warning["reason"] == "repeated_no_progress"
    assert warning["signature"].startswith("inspect_trace:")
    assert warning["steps_remaining"] > 0


def test_identical_source_triage_preserves_hypothesis_identity_and_evidence() -> None:
    tools = _tools()
    run = ReturnDesk().run(incident())

    first = tools.triage_hypotheses([run], selected_run=run)
    selected = first[0]
    selected.status = "supported"
    selected.rationale = "retain the original causal evidence"
    predicates = dict(selected.predicates)

    second = tools.triage_hypotheses([run], selected_run=run)
    retained = next(item for item in second if item.hypothesis_id == selected.hypothesis_id)

    assert retained.hypothesis_id == selected.hypothesis_id
    assert retained.status == "supported"
    assert retained.rationale == "retain the original causal evidence"
    assert retained.predicates == predicates
    assert tools.observations[-1]["kind"] == "hypotheses"
    assert tools.observations[-1]["status"] == "unchanged"


class ValidInterventionThenReads:
    def next_action(self, observations: list[dict]) -> ControllerAction:
        if not observations:
            return ControllerAction(kind="probe_case")
        latest = observations[-1].get("kind")
        if latest == "trace":
            return ControllerAction(kind="triage_hypotheses")
        if latest == "hypotheses":
            return ControllerAction(
                kind="run_experiment",
                operator="remove_note",
                value=OBSOLETE_NOTE,
                rationale="test the exact note observed in the source trace",
            )
        return ControllerAction(kind="check_suite")


def test_valid_source_contrast_hands_off_before_controller_reads_consume_cap() -> None:
    tools = _tools()
    AdaptiveInvestigator(tools, ValidInterventionThenReads(), validation_reserve_trials=25).investigate(
        incident(), max_steps=12
    )

    assert tools.stop_reason == "validation_handoff"
    handoff = next(item for item in tools.observations if item.get("kind") == "validation_handoff")
    assert handoff["reason"] == "adaptive_step_budget_reserved_for_validation"
    assert tools.budget.target_trials + handoff["reserved_trials"] <= tools.budget.max_target_trials


class RepeatingSuiteCheck:
    def next_action(self, observations: list[dict]) -> ControllerAction:
        if not observations:
            return ControllerAction(kind="probe_case")
        return ControllerAction(kind="check_suite")


def test_unchanged_suite_checks_are_bounded_no_progress() -> None:
    tools = _tools()
    AdaptiveInvestigator(tools, RepeatingSuiteCheck()).investigate(incident(), max_steps=12)

    assert tools.stop_reason == "inconclusive:controller_no_progress"
    warning = next(item for item in tools.observations if item.get("kind") == "controller_recovery")
    assert warning["signature"].startswith("check_suite:")


def test_exhausted_investigator_budget_is_not_masked_by_handoff() -> None:
    tools = _tools()
    scenario = incident()
    source = tools.probe_case(scenario)
    tools.inspect_trace(source)
    hypothesis = tools.triage_hypotheses([source], selected_run=source)[0]
    spec = ExperimentSpec(
        hypothesis_id=hypothesis.hypothesis_id,
        name="remove-note",
        operator="remove_note",
        value=OBSOLETE_NOTE,
        source_scenario_id=scenario.scenario_id,
        source_run_id=source.run_id,
        repetitions=3,
    )
    tools.run_experiment(spec, scenario)
    tools.budget.investigator_calls = tools.budget.max_investigator_calls

    AdaptiveInvestigator(tools, RepeatingSuiteCheck(), validation_reserve_trials=25).investigate(
        scenario, max_steps=12
    )

    assert tools.stop_reason == "inconclusive:investigator_call_budget_exhausted"
    assert not any(item.get("kind") == "validation_handoff" for item in tools.observations)
