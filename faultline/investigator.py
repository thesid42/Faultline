"""Typed controller tools and an adaptive evidence-driven loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import BudgetState, ControllerAction, ExperimentResult, ExperimentSpec, Hypothesis, RunRecord, Scenario
from .trials import LocalTrialRunner


class InvestigatorController(Protocol):
    def next_action(self, observations: list[dict[str, Any]]) -> ControllerAction | dict[str, Any] | str: ...


@dataclass
class Tools:
    runner: LocalTrialRunner
    budget: BudgetState
    runs: list[RunRecord] = field(default_factory=list)
    results: list[ExperimentResult] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)

    def inspect_trace(self, run: RunRecord) -> dict[str, Any]:
        evidence = {"kind": "trace", "run_id": run.run_id, "trace_digest": run.trace_digest, "events": [event.model_dump(mode="json") for event in run.events], "ledger": run.actual_ledger, "checker_passed": run.checker_passed, "status": run.status.value}
        self.observations.append(evidence)
        return evidence

    def triage_hypotheses(self, runs: list[RunRecord]) -> list[Hypothesis]:
        observed_kinds = {event.kind for run in runs for event in run.events}
        hypotheses: list[Hypothesis] = []
        if "retrieve_policy" in observed_kinds:
            hypotheses.append(Hypothesis(statement="the retrieved policy differs from the reviewed policy", predicates={"evidence_event": "retrieve_policy"}))
        if "retrieve_notes" in observed_kinds:
            hypotheses.append(Hypothesis(statement="a retrieved customer note changes the decision", predicates={"evidence_event": "retrieve_notes"}))
        if any(row.get("kind") == "refund" for run in runs for row in run.actual_ledger):
            hypotheses.append(Hypothesis(statement="the target executed a refund for a case independently marked ineligible", predicates={"evidence_event": "execute", "ledger_kind": "refund"}))
        if not hypotheses:
            hypotheses.append(Hypothesis(statement="the available trace is insufficient to localize the violation", predicates={"evidence": "incomplete"}, status="unknown"))
        self.observations.append({"kind": "hypotheses", "count": len(hypotheses)})
        return hypotheses

    def run_experiment(self, spec: ExperimentSpec, scenario: Scenario) -> list[ExperimentResult]:
        count = spec.repetitions
        if not self.budget.can_target_trial(count):
            raise RuntimeError("target trial budget exhausted")
        self.budget.target_trials += count
        output = self.runner.run(spec, scenario)
        self.results.extend(output)
        self.observations.extend({"kind": "experiment", "trial_id": result.trial_id, "activated": result.activation.activated, "status": result.status, "violation": result.observed_violation} for result in output)
        return output

    def probe_case(self, scenario: Scenario) -> RunRecord:
        if not self.budget.can_target_trial():
            raise RuntimeError("target trial budget exhausted")
        self.budget.target_trials += 1
        run = self.runner.probe(scenario)
        self.runs.append(run)
        return run

    def check_suite(self, runs: list[RunRecord]) -> dict[str, int]:
        summary = {"total": len(runs), "passed": sum(run.checker_passed is True for run in runs), "failed": sum(run.checker_passed is False for run in runs), "invalid": sum(run.status.value == "invalid" for run in runs), "infrastructure_error": sum(run.status.value == "infrastructure_error" for run in runs)}
        self.observations.append({"kind": "suite_check", **summary})
        return summary

    def propose_tests(self, *, suspect: list[ExperimentResult], reviewed_good: list[ExperimentResult]) -> list[dict[str, Any]]:
        # Expected outcomes are derived from reviewed checker rules, not model
        # opinion. Only completed, activated trials contribute evidence.
        suspect = [result for result in suspect if result.status == "completed" and result.activation.activated and result.run]
        reviewed_good = [result for result in reviewed_good if result.status == "completed" and result.activation.activated and result.run]
        cases: list[dict[str, Any]] = []
        for result in suspect + reviewed_good:
            if not result.run:
                continue
            scenario = result.run.scenario
            cases.append({"scenario": scenario.model_dump(mode="json"), "expected_eligible": self.runner.target.checker.expected_eligible(scenario), "observed_violation": result.observed_violation, "trial_id": result.trial_id, "evidence_origin": result.evidence_origin.value})
        return [{"name": "denied/allowed boundary pair", "cases": cases, "suspect_count": len(suspect), "reviewed_good_count": len(reviewed_good)}]

    def finish(self) -> dict[str, Any]:
        return {"target_trials": self.budget.target_trials, "investigator_calls": self.budget.investigator_calls, "paid_calls": self.budget.paid_calls, "spent_usd": self.budget.spent_usd}


@dataclass
class AdaptiveInvestigator:
    tools: Tools
    controller: InvestigatorController

    def investigate(self, scenario: Scenario, *, max_steps: int = 8) -> list[ExperimentResult]:
        all_results: list[ExperimentResult] = []
        for _ in range(max_steps):
            if not self.tools.budget.can_investigate():
                break
            self.tools.budget.investigator_calls += 1
            action = self._normalize(self.controller.next_action(list(self.tools.observations)))
            if action.kind == "finish":
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
                hypotheses = self.tools.triage_hypotheses(self.tools.runs)
                self.tools.observations.append({"kind": "triage_hypotheses", "hypothesis_ids": [hypothesis.hypothesis_id for hypothesis in hypotheses]})
                continue
            if action.kind == "run_experiment" and action.operator:
                value = action.value
                spec = ExperimentSpec(hypothesis_id="adaptive", name=f"{action.operator}:{value}", operator=action.operator, value=value)
                all_results.extend(self.tools.run_experiment(spec, scenario))
                continue
            if action.kind == "check_suite":
                self.tools.check_suite(self.tools.runs)
                continue
            if action.kind == "propose_tests":
                self.tools.propose_tests(suspect=self.tools.results, reviewed_good=[])
                self.tools.observations.append({"kind": "propose_tests", "status": "generated"})
                continue
            self.tools.observations.append({"kind": "unknown_controller_action", "action": action.model_dump(mode="json")})
        return all_results

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
            return ControllerAction(kind="run_experiment", operator=operator, value=int(value) if operator == "order_age" else value)
        raise ValueError(f"unsupported controller action: {raw}")


class BranchingStubController:
    """Offline seam: chooses a different next step from observed evidence."""

    def __init__(self) -> None:
        self.calls = 0

    def next_action(self, observations: list[dict[str, Any]]) -> ControllerAction:
        self.calls += 1
        if not observations:
            return ControllerAction(kind="probe_case")
        latest = observations[-1]
        if latest.get("kind") == "trace" and latest.get("checker_passed") is False:
            # This fixture controller is intentionally deterministic and clearly
            # labelled offline; live controllers must select a value from trace.
            return ControllerAction(kind="run_experiment", operator="remove_note", value="A 30-day window applies to this customer.")
        return ControllerAction(kind="finish")
