"""Typed controller tools and an adaptive evidence-driven loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import BudgetState, CaseFile, ControllerAction, ExperimentResult, ExperimentSpec, Hypothesis, RunRecord, Scenario
from .remote import OptionalJevTriage
from .scenarios import OBSOLETE_NOTE, UNRELATED_NOTE, legitimate_control
from .trials import LocalTrialRunner


class InvestigatorController(Protocol):
    def next_action(self, observations: list[dict[str, Any]]) -> ControllerAction | dict[str, Any] | str: ...


@dataclass
class Tools:
    runner: LocalTrialRunner
    budget: BudgetState
    runs: list[RunRecord] = field(default_factory=list)
    results: list[ExperimentResult] = field(default_factory=list)
    experiments: list[ExperimentSpec] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    proposed_tests: list[dict[str, Any]] = field(default_factory=list)
    triage: dict[str, Any] | None = None
    jev: OptionalJevTriage | None = None
    stop_reason: str = ""

    def inspect_trace(self, run: RunRecord) -> dict[str, Any]:
        evidence = {"kind": "trace", "run_id": run.run_id, "trace_digest": run.trace_digest, "events": [event.model_dump(mode="json") for event in run.events], "ledger": run.actual_ledger, "checker_passed": run.checker_passed, "status": run.status.value}
        self.observations.append(evidence)
        return evidence

    def triage_hypotheses(self, runs: list[RunRecord]) -> list[Hypothesis]:
        observed_kinds = {event.kind for run in runs for event in run.events}
        hypotheses: list[Hypothesis] = []
        if "retrieve_policy" in observed_kinds:
            hypotheses.append(Hypothesis(statement="the retrieved policy differs from the reviewed policy", predicates={"evidence_event": "retrieve_policy", "family": "policy"}))
        if "retrieve_notes" in observed_kinds:
            hypotheses.append(Hypothesis(statement="a retrieved customer note changes the decision", predicates={"evidence_event": "retrieve_notes", "family": "memory"}))
        if any(row.get("kind") == "refund" for run in runs for row in run.actual_ledger):
            hypotheses.append(Hypothesis(statement="the target executed a refund for a case independently marked ineligible", predicates={"evidence_event": "execute", "ledger_kind": "refund", "family": "execution"}))
        if not hypotheses:
            hypotheses.append(Hypothesis(statement="the available trace is insufficient to localize the violation", predicates={"evidence": "incomplete"}, status="unknown"))
        self.hypotheses = hypotheses
        self.observations.append({"kind": "hypotheses", "count": len(hypotheses), "hypothesis_ids": [item.hypothesis_id for item in hypotheses]})
        if self.jev is not None and self.budget.can_jev():
            self.budget.jev_calls += 1
            selected = next((run for run in runs if run.events), runs[0] if runs else None)
            evidence = {"events": [event.model_dump(mode="json") for event in selected.events]} if selected else {}
            judgment = self.jev.triage(hypotheses, evidence)
            self.triage = judgment
            self.observations.append({"kind": "jev_triage", "available": judgment is not None, "result": judgment})
        return hypotheses

    def run_experiment(self, spec: ExperimentSpec, scenario: Scenario) -> list[ExperimentResult]:
        count = spec.repetitions
        if not self.budget.can_target_trial(count):
            self.stop_reason = "target trial budget exhausted"
            raise RuntimeError(self.stop_reason)
        self.budget.target_trials += count
        self.experiments.append(spec)
        output = self.runner.run(spec, scenario)
        self.results.extend(output)
        self.observations.extend({"kind": "experiment", "trial_id": result.trial_id, "operator": spec.operator, "activated": result.activation.activated, "status": result.status, "violation": result.observed_violation} for result in output)
        self._revise_hypotheses(spec, output)
        return output

    def probe_case(self, scenario: Scenario) -> RunRecord:
        if not self.budget.can_target_trial():
            self.stop_reason = "target trial budget exhausted"
            raise RuntimeError(self.stop_reason)
        self.budget.target_trials += 1
        run = self.runner.probe(scenario)
        self.runs.append(run)
        return run

    def check_suite(self, runs: list[RunRecord]) -> dict[str, int]:
        summary = {"total": len(runs), "passed": sum(run.checker_passed is True for run in runs), "failed": sum(run.checker_passed is False for run in runs), "invalid": sum(run.status.value == "invalid" for run in runs), "infrastructure_error": sum(run.status.value == "infrastructure_error" for run in runs)}
        self.observations.append({"kind": "suite_check", **summary})
        return summary

    def propose_tests(self, *, suspect: list[ExperimentResult] | None = None, reviewed_good: list[ExperimentResult] | None = None) -> list[dict[str, Any]]:
        # Expected outcomes are derived from reviewed checker rules, not model
        # opinion. Only completed, activated trials contribute evidence.
        if suspect is None or reviewed_good is None:
            suspect, reviewed_good = self._split_results()
        suspect = [result for result in suspect if result.status == "completed" and result.activation.activated and result.run]
        reviewed_good = [result for result in reviewed_good if result.status == "completed" and result.activation.activated and result.run]
        cases: list[dict[str, Any]] = []
        for result in suspect + reviewed_good:
            if not result.run:
                continue
            scenario = result.run.scenario
            cases.append({"scenario": scenario.model_dump(mode="json"), "expected_eligible": self.runner.target.checker.expected_eligible(scenario), "observed_violation": result.observed_violation, "trial_id": result.trial_id, "evidence_origin": result.evidence_origin.value})
        proposal = [{"name": "denied/allowed boundary pair", "cases": cases, "suspect_count": len(suspect), "reviewed_good_count": len(reviewed_good)}]
        self.proposed_tests = proposal
        self.observations.append({"kind": "propose_tests", "status": "generated", "suspect_count": len(suspect), "reviewed_good_count": len(reviewed_good)})
        return proposal

    def finish(self) -> dict[str, Any]:
        return {"target_trials": self.budget.target_trials, "investigator_calls": self.budget.investigator_calls, "jev_calls": self.budget.jev_calls, "paid_calls": self.budget.paid_calls, "spent_usd": self.budget.spent_usd, "stop_reason": self.stop_reason}

    def to_case_file(self, *, incident=None, scenarios: list[Scenario] | None = None, coverage=None, proposal=None, held_out_validation=None, status: str = "complete") -> CaseFile:
        evidence_origin = self.runs[-1].evidence_origin if self.runs else (self.results[-1].evidence_origin if self.results else "simulated")
        return CaseFile(
            status=status,  # type: ignore[arg-type]
            stop_reason=self.stop_reason,
            incident=incident,
            scenarios=list(scenarios or []),
            runs=list(self.runs),
            hypotheses=list(self.hypotheses),
            experiments=list(self.experiments),
            experiment_results=list(self.results),
            observations=list(self.observations),
            coverage=list(coverage or []),
            held_out_validation=list(held_out_validation or []),
            proposal=proposal,
            triage=self.triage,
            budget=self.budget,
            backend=self.runner.backend,
            evidence_origin=evidence_origin,  # type: ignore[arg-type]
        )

    def _split_results(self) -> tuple[list[ExperimentResult], list[ExperimentResult]]:
        suspect: list[ExperimentResult] = []
        reviewed_good: list[ExperimentResult] = []
        for result in self.results:
            if result.status != "completed" or not result.activation.activated or not result.run:
                continue
            if result.observed_violation is True:
                suspect.append(result)
            elif result.observed_violation is False:
                reviewed_good.append(result)
        return suspect, reviewed_good

    def _revise_hypotheses(self, spec: ExperimentSpec, results: list[ExperimentResult]) -> None:
        completed = [result for result in results if result.status == "completed" and result.activation.activated and result.run]
        if not completed or not self.hypotheses:
            return
        for hypothesis in self.hypotheses:
            family = hypothesis.predicates.get("family")
            if family == "memory" and spec.operator == "remove_note":
                # Removing the obsolete note should clear the violation if memory is causal.
                ineligible = [result for result in completed if not self.runner.target.checker.expected_eligible(result.run.scenario)]  # type: ignore[union-attr]
                if not ineligible:
                    continue
                if all(result.observed_violation is False for result in ineligible):
                    hypothesis.status = "supported"
                    hypothesis.rationale = "removing the obsolete note eliminated observed violations"
                elif all(result.observed_violation is True for result in ineligible):
                    hypothesis.status = "rejected"
                    hypothesis.rationale = "removing the obsolete note did not clear the violation"
            elif family == "memory" and spec.operator == "unrelated_note":
                # Control: unrelated edit should leave the failure intact on ineligible cases.
                ineligible = [result for result in completed if not self.runner.target.checker.expected_eligible(result.run.scenario)]  # type: ignore[union-attr]
                if not ineligible:
                    continue
                if all(result.observed_violation is True for result in ineligible):
                    if hypothesis.status == "supported":
                        hypothesis.rationale += "; unrelated-note control still violated"
                    else:
                        hypothesis.rationale = "unrelated-note control still violated"
                elif all(result.observed_violation is False for result in ineligible):
                    hypothesis.status = "rejected"
                    hypothesis.rationale = "unrelated-note control cleared the violation, weakening the memory account"
            elif family == "policy" and spec.operator == "policy_notes":
                ineligible = [result for result in completed if not self.runner.target.checker.expected_eligible(result.run.scenario)]  # type: ignore[union-attr]
                if not ineligible:
                    continue
                cleared = [result for result in ineligible if result.observed_violation is False]
                still_bad = [result for result in ineligible if result.observed_violation is True]
                if cleared and not still_bad:
                    hypothesis.status = "supported"
                    hypothesis.rationale = "replacing notes with reviewed policy cleared violations on ineligible cases"
                elif cleared and still_bad:
                    hypothesis.status = "open"
                    hypothesis.rationale = "policy_notes produced mixed outcomes on ineligible cases"


@dataclass
class AdaptiveInvestigator:
    tools: Tools
    controller: InvestigatorController

    def investigate(self, scenario: Scenario, *, max_steps: int = 8, control_scenario: Scenario | None = None) -> list[ExperimentResult]:
        all_results: list[ExperimentResult] = []
        control = control_scenario or legitimate_control()
        for _ in range(max_steps):
            if not self.tools.budget.can_investigate():
                self.tools.stop_reason = self.tools.stop_reason or "investigator call budget exhausted"
                self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                break
            self.tools.budget.investigator_calls += 1
            try:
                action = self._normalize(self.controller.next_action(list(self.tools.observations)))
            except Exception as exc:
                self.tools.stop_reason = f"controller_error:{type(exc).__name__}"
                self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                break
            if action.kind == "finish":
                if not self.tools.stop_reason:
                    self.tools.stop_reason = "controller_finished"
                break
            if action.kind == "probe_case":
                run = self.tools.probe_case(scenario)
                self.tools.inspect_trace(run)
                continue
            if action.kind == "inspect_trace":
                if self.tools.runs:
                    self.tools.inspect_trace(self.tools.runs[-1])
                else:
                    self.tools.observations.append({"kind": "inspect_trace", "status": "no_run"})
                continue
            if action.kind == "triage_hypotheses":
                self.tools.triage_hypotheses(self.tools.runs)
                continue
            if action.kind == "run_experiment" and action.operator:
                value = action.value
                target = control if action.operator == "order_age" and isinstance(value, int) and value <= 14 else scenario
                if action.operator == "policy_notes" and value == "reviewed_policy":
                    value = "Refunds are allowed up to 14 days."
                if action.operator == "remove_note" and value in (None, "obsolete"):
                    value = OBSOLETE_NOTE
                if action.operator == "unrelated_note" and value in (None, "control"):
                    value = UNRELATED_NOTE
                spec = ExperimentSpec(hypothesis_id=self._active_hypothesis_id(action.operator), name=f"{action.operator}:{value}", operator=action.operator, value=value)
                try:
                    all_results.extend(self.tools.run_experiment(spec, target))
                except RuntimeError:
                    self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                    break
                continue
            if action.kind == "check_suite":
                self.tools.check_suite(self.tools.runs)
                continue
            if action.kind == "propose_tests":
                self.tools.propose_tests()
                continue
            self.tools.observations.append({"kind": "unknown_controller_action", "action": action.model_dump(mode="json")})
        return all_results

    def _active_hypothesis_id(self, operator: str) -> str:
        family = "memory" if operator in {"remove_note", "unrelated_note", "policy_notes"} else "policy"
        for hypothesis in self.tools.hypotheses:
            if hypothesis.predicates.get("family") == family:
                return hypothesis.hypothesis_id
        return self.tools.hypotheses[0].hypothesis_id if self.tools.hypotheses else "adaptive"

    @staticmethod
    def _normalize(raw: ControllerAction | dict[str, Any] | str) -> ControllerAction:
        if isinstance(raw, ControllerAction):
            return raw
        if isinstance(raw, dict):
            return ControllerAction.model_validate(raw)
        if raw == "probe":
            return ControllerAction(kind="probe_case")
        if raw == "finish":
            return ControllerAction(kind="finish")
        if raw.startswith("experiment:"):
            _, operator, value = raw.split(":", 2)
            parsed: str | int = int(value) if operator == "order_age" else value
            return ControllerAction(kind="run_experiment", operator=operator, value=parsed)  # type: ignore[arg-type]
        raise ValueError(f"unsupported controller action: {raw}")


class BranchingStubController:
    """Offline seam: chooses the next step from observed evidence.

    Sequence mirrors the plan loop: probe → triage → remove_note → unrelated
    note control → check_suite → propose_tests → finish.
    """

    def __init__(self) -> None:
        self.calls = 0

    def next_action(self, observations: list[dict[str, Any]]) -> ControllerAction:
        self.calls += 1
        kinds = [item.get("kind") for item in observations]
        if not observations:
            return ControllerAction(kind="probe_case")
        latest = observations[-1]
        if latest.get("kind") == "trace" and latest.get("checker_passed") is False and "hypotheses" not in kinds:
            return ControllerAction(kind="triage_hypotheses")
        if latest.get("kind") in {"hypotheses", "jev_triage"} and not any(item.get("kind") == "experiment" and item.get("operator") == "remove_note" for item in observations):
            return ControllerAction(kind="run_experiment", operator="remove_note", value=OBSOLETE_NOTE)
        if latest.get("kind") == "experiment" and not any(item.get("kind") == "experiment" and item.get("operator") == "unrelated_note" for item in observations):
            # Only schedule the control after the remove_note experiment batch.
            if any(item.get("kind") == "experiment" and item.get("operator") == "remove_note" for item in observations):
                return ControllerAction(kind="run_experiment", operator="unrelated_note", value=UNRELATED_NOTE)
        if "suite_check" not in kinds and any(item.get("kind") == "experiment" for item in observations):
            return ControllerAction(kind="check_suite")
        if "propose_tests" not in kinds and "suite_check" in kinds:
            return ControllerAction(kind="propose_tests")
        return ControllerAction(kind="finish")
