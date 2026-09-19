"""Typed controller tools and an adaptive evidence-driven loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import BudgetState, CaseFile, ControllerAction, ExperimentResult, ExperimentSpec, Hypothesis, RunRecord, Scenario
from .remote import OptionalJevTriage
from .scenarios import OBSOLETE_NOTE, UNRELATED_NOTE, legitimate_control
from .trials import LocalTrialRunner


# Arms are properties of the application configuration supplied by the
# parent session, never conclusions inferred from a run's output.  Keep this
# registry deliberately small and explicit: an unknown/default configuration
# is not silently promoted to either arm.
SUSPECT_CONFIGURATION_IDS = frozenset({"suspect", "suspect_config", "buggy", "buggy_config"})
REVIEWED_GOOD_CONFIGURATION_IDS = frozenset({"reviewed_good", "reviewed-good", "reviewed_good_config", "reviewed-good-config"})


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
    held_out_validation: list[dict[str, Any]] = field(default_factory=list)
    triage: dict[str, Any] | None = None
    jev: OptionalJevTriage | None = None
    # Optional generalized validation contract.  When absent, the legacy
    # eligibility-pair proposal rules remain in force.  When present, the
    # mapping must identify exactly the incident and control fixture IDs.
    validation_pair: dict[str, str] | None = None
    stop_reason: str = ""

    def inspect_trace(self, run: RunRecord) -> dict[str, Any]:
        evidence = {"kind": "trace", "run_id": run.run_id, "trace_digest": run.trace_digest, "events": [event.model_dump(mode="json") for event in run.events], "ledger": run.actual_ledger, "checker_passed": run.checker_passed, "status": run.status.value}
        self.observations.append(evidence)
        return evidence

    @staticmethod
    def _first_payload_value(payload: Any, *keys: str) -> Any:
        """Return the first explicitly observed payload field, including falsey values."""
        if not isinstance(payload, dict):
            return None
        for key in keys:
            if key in payload:
                return payload[key]
        return None

    def triage_hypotheses(self, runs: list[RunRecord], *, selected_run: RunRecord | None = None) -> list[Hypothesis]:
        # Triage must be scoped to the independently selected incident trace.
        # Falling back to a mixed fixture list can make an ordinary 14-day
        # suite row appear to explain a 21-day incident.
        focus = selected_run or (runs[-1] if len(runs) == 1 else None)
        focused_runs = [focus] if focus is not None else []
        observed_kinds = {event.kind for run in focused_runs for event in run.events}
        policy_event = next((event for run in focused_runs for event in run.events if event.kind == "retrieve_policy"), None)
        notes_event = next((event for run in focused_runs for event in run.events if event.kind == "retrieve_notes"), None)
        order_event = next((event for run in focused_runs for event in run.events if event.kind in {"retrieve_order", "retrieve_order_details"}), None)
        execute_events = [event for run in focused_runs for event in run.events if event.kind in {"execute", "execute_refund", "refund_attempt", "idempotency_check"}]
        policy_payload = policy_event.payload if policy_event else {}
        note_values = notes_event.payload.get("notes", []) if notes_event else []
        order_payload = order_event.payload if order_event else {}
        hypotheses: list[Hypothesis] = []
        if "retrieve_policy" in observed_kinds:
            hypotheses.append(Hypothesis(statement=f"the retrieved policy result may differ from the reviewed rule (max age {policy_payload.get('max_age_days', 'unknown')})", predicates={"evidence_event_id": policy_event.event_id if policy_event else None, "policy_version": policy_payload.get("policy_version"), "max_age_days": policy_payload.get("max_age_days"), "family": "policy"}))
        if "retrieve_notes" in observed_kinds:
            for note in note_values or ["<empty notes>"]:
                hypotheses.append(Hypothesis(statement=f"the retrieved customer note may change the decision: {note}", predicates={"evidence_event_id": notes_event.event_id if notes_event else None, "note_text": note, "family": "memory"}))

        # These hypotheses are derived only from fields actually returned by
        # the gateway/order/attempt traces.  In particular, do not consult
        # Scenario.expected_eligible or any fixture/profile label here.
        unit_value = self._first_payload_value(order_payload, "refund_api_unit", "amount_unit", "currency_unit", "unit")
        amount_mismatch = self._first_payload_value(order_payload, "amount_mismatch", "unit_mismatch", "converted_amount_mismatch", "amount_conversion_error")
        for event in execute_events:
            if amount_mismatch is None:
                amount_mismatch = self._first_payload_value(event.payload, "amount_mismatch", "unit_mismatch", "converted_amount_mismatch", "amount_conversion_error")
        if unit_value is not None:
            hypotheses.append(Hypothesis(statement=f"the refund amount may be converted using the wrong API unit ({unit_value!s})", predicates={"evidence_event_id": order_event.event_id if order_event else None, "refund_api_unit": unit_value, "amount_mismatch": amount_mismatch, "family": "amount_units"}))

        attempts_value = self._first_payload_value(order_payload, "delivery_attempts", "attempts", "retry_count", "attempt_count")
        idempotency_value = self._first_payload_value(order_payload, "idempotency_key", "request_id")
        for event in execute_events:
            if attempts_value is None:
                attempts_value = self._first_payload_value(event.payload, "delivery_attempts", "attempts", "retry_count", "attempt_count")
            if idempotency_value is None:
                idempotency_value = self._first_payload_value(event.payload, "idempotency_key", "request_id")
        duplicate_signal = any(self._first_payload_value(event.payload, "duplicate", "replayed", "idempotency_reused", "already_processed", "duplicate_refund") is True for event in execute_events)
        ledger_entries = 0
        for event in execute_events:
            raw_entries = self._first_payload_value(event.payload, "ledger_entries", "refund_count", "effects")
            try:
                ledger_entries = max(ledger_entries, int(raw_entries))
            except (TypeError, ValueError):
                continue
        if attempts_value is not None or idempotency_value is not None or duplicate_signal or ledger_entries > 1:
            hypotheses.append(Hypothesis(statement="delivery retries or idempotency handling may duplicate a refund attempt", predicates={"evidence_event_id": (execute_events[0].event_id if execute_events else (order_event.event_id if order_event else None)), "delivery_attempts": attempts_value, "idempotency_key": idempotency_value, "duplicate_signal": duplicate_signal, "ledger_entries": ledger_entries, "family": "idempotency"}))

        if any(row.get("kind") == "refund" for run in focused_runs for row in run.actual_ledger):
            hypotheses.append(Hypothesis(statement="the observed execution trace contains a refund ledger entry that requires causal explanation", predicates={"evidence_event": "execute", "ledger_kind": "refund", "family": "execution"}))
        if not hypotheses:
            hypotheses.append(Hypothesis(statement="the available trace is insufficient to localize the violation", predicates={"evidence": "incomplete"}, status="unknown"))
        if focus is not None:
            for hypothesis in hypotheses:
                hypothesis.predicates.setdefault("source_run_id", focus.run_id)
                hypothesis.predicates.setdefault("source_scenario_id", focus.scenario.scenario_id)
        self.hypotheses = hypotheses
        self.observations.append({"kind": "hypotheses", "count": len(hypotheses), "hypotheses": [{"hypothesis_id": item.hypothesis_id, "statement": item.statement, "predicates": item.predicates, "confidence": item.confidence} for item in hypotheses]})
        if self.jev is not None and self.budget.can_jev():
            self.budget.jev_calls += 1
            selected = focus
            evidence = {"events": [event.model_dump(mode="json") for event in selected.events]} if selected else {}
            judgment = self.jev.triage(hypotheses, evidence)
            self.triage = judgment
            self.observations.append({"kind": "jev_triage", "available": judgment is not None, "result": judgment})
        return hypotheses

    def run_experiment(self, spec: ExperimentSpec, scenario: Scenario) -> list[ExperimentResult]:
        if spec.source_scenario_id and spec.source_scenario_id != scenario.scenario_id:
            self.stop_reason = "inconclusive:source_scenario_mismatch"
            raise RuntimeError(self.stop_reason)
        count = spec.repetitions
        if not self.budget.can_target_trial(count):
            self.stop_reason = "inconclusive:target_trial_budget_exhausted"
            raise RuntimeError(self.stop_reason)
        self.budget.target_trials += count
        self.experiments.append(spec)
        output = self.runner.run(spec, scenario)
        self.results.extend(output)
        self.observations.extend({"kind": "experiment", "trial_id": result.trial_id, "operator": spec.operator, "source": spec.source_role, "configuration_id": spec.configuration_id, "activated": result.activation.activated, "status": result.status, "violation": result.observed_violation} for result in output)
        self._revise_hypotheses(spec, output)
        return output

    def probe_case(self, scenario: Scenario) -> RunRecord:
        if not self.budget.can_target_trial():
            self.stop_reason = "inconclusive:target_trial_budget_exhausted"
            raise RuntimeError(self.stop_reason)
        self.budget.target_trials += 1
        run = self.runner.probe(scenario)
        self.runs.append(run)
        return run

    def check_suite(self, runs: list[RunRecord], *, original_suite_runs: list[RunRecord] | None = None) -> dict[str, int]:
        runs = list(original_suite_runs if original_suite_runs is not None else runs)
        summary = {"total": len(runs), "passed": sum(run.checker_passed is True for run in runs), "failed": sum(run.checker_passed is False for run in runs), "invalid": sum(run.status.value == "invalid" for run in runs), "infrastructure_error": sum(run.status.value == "infrastructure_error" for run in runs)}
        self.observations.append({"kind": "suite_check", **summary})
        return summary

    def propose_tests(self, *, suspect: list[ExperimentResult] | None = None, reviewed_good: list[ExperimentResult] | None = None) -> list[dict[str, Any]]:
        # Expected outcomes are derived from reviewed checker rules, not model
        # opinion. Only completed, activated trials contribute evidence.
        if suspect is None or reviewed_good is None:
            suspect, reviewed_good = self._split_results()
        raw_suspect = list(suspect)
        raw_reviewed_good = list(reviewed_good)
        raw_summary = self._proposal_input_summary(raw_suspect, raw_reviewed_good)
        if self.validation_pair is not None:
            return self._propose_validation_pair(raw_suspect, raw_reviewed_good, raw_summary)
        # Filter invalid/excluded/infrastructure rows before any outcome
        # grouping, but retain their identities and reasons in the observation
        # so a missing repetition is auditable rather than silently dropped.
        suspect = [result for result in raw_suspect if self._result_arm(result) == "suspect"]
        reviewed_good = [result for result in raw_reviewed_good if self._result_arm(result) == "reviewed_good"]
        missing = []
        if not suspect:
            missing.append("missing_suspect_failure_arm")
        if not reviewed_good:
            missing.append("missing_eligible_control_arm")
        if missing:
            self.stop_reason = self.stop_reason or "inconclusive:" + ",".join(missing)
        if not suspect or not reviewed_good:
            self.observations.append({"kind": "propose_tests", "status": "inconclusive", "reason": self.stop_reason, "raw": raw_summary})
            self.proposed_tests = []
            return []

        # A proposal is a matched 2x2 validation, not a convenient collection
        # of whichever outcomes happened to look useful.  The same fixture
        # inputs must be exercised by both configurations at both eligibility
        # classes. Repetitions remain in each group, so an infrastructure or
        # contradictory result cannot be hidden by selecting one row.
        raw_suspect_by_fixture = self._group_by_fixture(raw_suspect)
        raw_reviewed_by_fixture = self._group_by_fixture(raw_reviewed_good)
        suspect_by_fixture = self._group_by_fixture(suspect)
        reviewed_by_fixture = self._group_by_fixture(reviewed_good)
        matched = []
        scenario_mismatch = False
        for fixture_key in sorted(set(raw_suspect_by_fixture) & set(raw_reviewed_by_fixture)):
            raw_suspect_group = raw_suspect_by_fixture[fixture_key]
            raw_reviewed_group = raw_reviewed_by_fixture[fixture_key]
            suspect_group = suspect_by_fixture.get(fixture_key, [])
            reviewed_group = reviewed_by_fixture.get(fixture_key, [])
            if not self._complete_repetition_cell(raw_suspect_group, suspect_group) or not self._complete_repetition_cell(raw_reviewed_group, reviewed_group):
                continue
            suspect_digest = self._scenario_digest(suspect_group)
            reviewed_digest = self._scenario_digest(reviewed_group)
            if suspect_digest is None or reviewed_digest is None or suspect_digest != reviewed_digest:
                scenario_mismatch = True
                continue
            suspect_classes = {self.runner.target.checker.expected_eligible(item.run.scenario) for item in suspect_group if item.run}
            reviewed_classes = {self.runner.target.checker.expected_eligible(item.run.scenario) for item in reviewed_group if item.run}
            if suspect_classes and reviewed_classes and suspect_classes == reviewed_classes:
                matched.append((fixture_key, suspect_group, reviewed_group))
        matched_classes = {
            self.runner.target.checker.expected_eligible(result.run.scenario)
            for _, suspect_group, reviewed_group in matched
            for result in (*suspect_group, *reviewed_group)
            if result.run
        }
        if matched_classes != {False, True}:
            reason = "inconclusive:scenario_input_mismatch_between_arms" if scenario_mismatch else "inconclusive:incomplete_2x2_repetitions"
            self.stop_reason = self.stop_reason or reason
            self.observations.append({"kind": "propose_tests", "status": "inconclusive", "reason": self.stop_reason, "raw": raw_summary})
            self.proposed_tests = []
            return []

        selected_suspect = [result for _, group, _ in matched for result in group]
        selected_reviewed = [result for _, _, group in matched for result in group]
        if any(result.run is None or result.run.checker_passed is not True or result.observed_violation is not False for result in selected_reviewed):
            self.stop_reason = self.stop_reason or "inconclusive:reviewed_good_configuration_failed"
            self.observations.append({"kind": "propose_tests", "status": "inconclusive", "reason": self.stop_reason, "raw": raw_summary})
            self.proposed_tests = []
            return []
        if not any(result.run and not self.runner.target.checker.expected_eligible(result.run.scenario) and result.run.checker_passed is False and result.observed_violation is True for result in selected_suspect):
            self.stop_reason = self.stop_reason or "inconclusive:missing_suspect_failure_arm"
            self.observations.append({"kind": "propose_tests", "status": "inconclusive", "reason": self.stop_reason, "raw": raw_summary})
            self.proposed_tests = []
            return []
        suspect = selected_suspect
        reviewed_good = selected_reviewed
        cases: list[dict[str, Any]] = []
        for result in suspect + reviewed_good:
            if not result.run:
                continue
            scenario = result.run.scenario
            cases.append({"arm": self._result_arm(result), "scenario": scenario.model_dump(mode="json"), "expected_eligible": self.runner.target.checker.expected_eligible(scenario), "observed_violation": result.observed_violation, "trial_id": result.trial_id, "configuration_id": result.configuration_id, "evidence_origin": result.evidence_origin.value})
        proposal = [{"name": "denied/allowed boundary pair", "cases": cases, "suspect_count": len(suspect), "reviewed_good_count": len(reviewed_good)}]
        self.proposed_tests = proposal
        self.observations.append({"kind": "propose_tests", "status": "generated", "suspect_count": len(suspect), "reviewed_good_count": len(reviewed_good), "raw": raw_summary})
        return proposal

    def _propose_validation_pair(self, suspect: list[ExperimentResult], reviewed_good: list[ExperimentResult], raw_summary: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate a generalized incident/control 2x2 baseline matrix.

        This path intentionally does not consult eligibility labels.  It is
        for defects where the incident may be eligible (amount units,
        delivery retries, and similar) and therefore requires explicit
        observed violation/pass outcomes for every repetition.
        """
        pair = self.validation_pair or {}
        if set(pair) != {"incident", "control"} or any(not isinstance(value, str) or not value for value in pair.values()) or pair["incident"] == pair["control"]:
            return self._validation_inconclusive("inconclusive:invalid_validation_pair", raw_summary)

        # Keep invalid rows in the raw arm until cell validation. Filtering
        # them here would silently hide failed repetitions from the matrix.
        arms = {
            "suspect": [item for item in suspect if item.configuration_id.lower() in SUSPECT_CONFIGURATION_IDS],
            "reviewed_good": [item for item in reviewed_good if item.configuration_id.lower() in REVIEWED_GOOD_CONFIGURATION_IDS],
        }
        cells: dict[tuple[str, str], list[ExperimentResult]] = {}
        reasons: list[str] = []
        for arm, rows in arms.items():
            for role, scenario_id in pair.items():
                matching = [item for item in rows if item.scenario_id == scenario_id and item.fixture_partition == "main"]
                baseline = [item for item in matching if self._spec_for_result(item) is not None and self._spec_for_result(item).operator == "baseline"]
                if len(baseline) != 3 or len({item.experiment_id for item in baseline}) != 1:
                    reasons.append(f"{arm}:{role}:baseline_repetitions")
                    continue
                spec = self._spec_for_result(baseline[0])
                assert spec is not None
                if spec.repetitions != 3 or spec.source_role != role or spec.source_scenario_id != scenario_id or not spec.source_run_id:
                    reasons.append(f"{arm}:{role}:source_scope")
                    continue
                if any(item.source_run_id != spec.source_run_id for item in baseline):
                    reasons.append(f"{arm}:{role}:source_run_mismatch")
                    continue
                invalid = [item for item in matching if self._result_exclusion_reason(item) is not None]
                if invalid:
                    reasons.append(f"{arm}:{role}:invalid_rows")
                    continue
                if {item.repetition for item in baseline} != {1, 2, 3}:
                    reasons.append(f"{arm}:{role}:repetition_ids")
                    continue
                if any(item.observed_violation not in {True, False} or item.run is None or item.run.checker_passed is None or item.observed_violation != (item.run.checker_passed is False) for item in baseline):
                    reasons.append(f"{arm}:{role}:outcome_unknown")
                    continue
                if self._scenario_digest(baseline) is None:
                    reasons.append(f"{arm}:{role}:scenario_mismatch")
                    continue
                cells[(arm, role)] = baseline

        required = [(arm, role) for arm in ("suspect", "reviewed_good") for role in ("incident", "control")]
        if reasons or any(cell not in cells for cell in required):
            return self._validation_inconclusive("inconclusive:validation_pair_matrix", raw_summary, reasons)

        for role in ("incident", "control"):
            suspect_cell = cells[("suspect", role)]
            reviewed_cell = cells[("reviewed_good", role)]
            if self._scenario_digest(suspect_cell) != self._scenario_digest(reviewed_cell):
                return self._validation_inconclusive("inconclusive:validation_pair_scenario_mismatch", raw_summary)
            if {item.source_run_id for item in suspect_cell} != {item.source_run_id for item in reviewed_cell}:
                return self._validation_inconclusive("inconclusive:validation_pair_source_mismatch", raw_summary)

        incident_suspect = cells[("suspect", "incident")]
        control_suspect = cells[("suspect", "control")]
        incident_reviewed = cells[("reviewed_good", "incident")]
        control_reviewed = cells[("reviewed_good", "control")]
        if any(item.observed_violation is not True for item in incident_suspect):
            return self._validation_inconclusive("inconclusive:validation_pair_incident_not_all_violations", raw_summary)
        if any(item.observed_violation is not False for item in (*control_suspect, *incident_reviewed, *control_reviewed)):
            return self._validation_inconclusive("inconclusive:validation_pair_pass_regression", raw_summary)

        cases: list[dict[str, Any]] = []
        for arm, role in required:
            for result in cells[(arm, role)]:
                assert result.run is not None
                cases.append({
                    "arm": arm,
                    "validation_role": role,
                    "scenario": result.run.scenario.model_dump(mode="json"),
                    # Keep the reviewed checker expectation for export/UI
                    # compatibility, but never use it as the diagnostic gate.
                    "expected_eligible": self.runner.target.checker.expected_eligible(result.run.scenario),
                    "observed_violation": result.observed_violation,
                    "trial_id": result.trial_id,
                    "configuration_id": result.configuration_id,
                    "evidence_origin": result.evidence_origin.value,
                })
        proposal = [{"name": "generalized incident/control validation pair", "validation_pair": dict(pair), "cases": cases, "suspect_count": 6, "reviewed_good_count": 6}]
        self.proposed_tests = proposal
        self.observations.append({"kind": "propose_tests", "status": "generated", "validation_pair": dict(pair), "suspect_count": 6, "reviewed_good_count": 6, "raw": raw_summary})
        return proposal

    def _validation_inconclusive(self, reason: str, raw_summary: dict[str, Any], details: list[str] | None = None) -> list[dict[str, Any]]:
        self.stop_reason = self.stop_reason or reason
        observation: dict[str, Any] = {"kind": "propose_tests", "status": "inconclusive", "reason": self.stop_reason, "raw": raw_summary}
        if details:
            observation["details"] = details
        self.observations.append(observation)
        self.proposed_tests = []
        return []

    def finish(self) -> dict[str, Any]:
        return {"target_trials": self.budget.target_trials, "investigator_calls": self.budget.investigator_calls, "jev_calls": self.budget.jev_calls, "paid_calls": self.budget.paid_calls, "spent_usd": self.budget.spent_usd, "stop_reason": self.stop_reason}

    def to_case_file(self, *, incident=None, scenarios: list[Scenario] | None = None, coverage=None, proposal=None, held_out_validation=None, status: str = "complete") -> CaseFile:
        evidence_origin = self.runs[-1].evidence_origin if self.runs else (self.results[-1].evidence_origin if self.results else "simulated")
        if incident is not None and incident.source_run_id is None:
            incident = incident.model_copy(update={"source_run_id": incident.run_id})
        source_run_id = incident.run_id if incident is not None else (self.runs[0].run_id if self.runs else None)
        if source_run_id and source_run_id not in {run.run_id for run in self.runs}:
            self.stop_reason = self.stop_reason or "inconclusive:incident_source_run_not_persisted"
            status = "inconclusive"
        elif status == "complete" and self.stop_reason.startswith("inconclusive:"):
            status = "inconclusive"
        return CaseFile(
            status=status,  # type: ignore[arg-type]
            stop_reason=self.stop_reason,
            incident=incident,
            source_run_id=source_run_id,
            scenarios=list(scenarios or []),
            runs=list(self.runs),
            hypotheses=list(self.hypotheses),
            experiments=list(self.experiments),
            experiment_results=list(self.results),
            observations=list(self.observations),
            coverage=list(coverage or []),
            held_out_validation=list(held_out_validation if held_out_validation is not None else self.held_out_validation),
            proposal=proposal,
            triage=self.triage,
            budget=self.budget,
            backend=self.runner.backend,
            evidence_origin=evidence_origin,  # type: ignore[arg-type]
        )

    def validate_held_out(self, scenarios: list[Scenario], *, fixture_partition: str = "held_out") -> list[dict[str, Any]]:
        """Run held-out cases through the same bounded runner and retain traces."""
        validation: list[dict[str, Any]] = []
        for scenario in scenarios:
            if not self.budget.can_target_trial():
                self.stop_reason = "inconclusive:target_trial_budget_exhausted_during_held_out"
                break
            self.budget.target_trials += 1
            run = self.runner.probe(scenario)
            run.fixture_partition = fixture_partition
            self.runs.append(run)
            validation.append({"scenario_id": scenario.scenario_id, "run_id": run.run_id, "fixture_partition": fixture_partition, "status": run.status.value, "checker_passed": run.checker_passed, "trace_digest": run.trace_digest, "run": run.model_dump(mode="json")})
        self.held_out_validation.extend(validation)
        return validation

    def _split_results(self) -> tuple[list[ExperimentResult], list[ExperimentResult]]:
        # Keep invalid/excluded rows in the returned raw arms.  propose_tests
        # filters them only after recording their reasons and counts.
        suspect = [result for result in self.results if result.configuration_id.lower() in SUSPECT_CONFIGURATION_IDS]
        reviewed_good = [result for result in self.results if result.configuration_id.lower() in REVIEWED_GOOD_CONFIGURATION_IDS]
        return suspect, reviewed_good

    def _result_arm(self, result: ExperimentResult) -> str | None:
        if self._result_exclusion_reason(result) is not None:
            return None
        explicit = result.configuration_id.lower()
        if explicit in SUSPECT_CONFIGURATION_IDS:
            return "suspect"
        if explicit in REVIEWED_GOOD_CONFIGURATION_IDS:
            return "reviewed_good"
        return None

    def _result_exclusion_reason(self, result: ExperimentResult) -> str | None:
        if result.status != "completed":
            return f"result_status:{result.status}"
        if not result.activation.activated:
            return "activation_not_proven"
        if result.run is None:
            return "missing_nested_run"
        if result.run.status.value != "completed":
            return f"run_status:{result.run.status.value}"
        if result.run.checker_status != "completed":
            return "checker_not_completed"
        if result.run.checker_passed is None:
            return "checker_unknown"
        if result.run.configuration_id != result.configuration_id:
            return "configuration_mismatch"
        if result.run.scenario.scenario_id != result.scenario_id:
            return "scenario_mismatch"
        if result.configuration_id.lower() not in SUSPECT_CONFIGURATION_IDS | REVIEWED_GOOD_CONFIGURATION_IDS:
            return "unknown_configuration"
        return None

    def _spec_for_result(self, result: ExperimentResult) -> ExperimentSpec | None:
        return next((spec for spec in self.experiments if spec.experiment_id == result.experiment_id), None)

    def _proposal_input_summary(self, suspect: list[ExperimentResult], reviewed_good: list[ExperimentResult]) -> dict[str, Any]:
        excluded: list[dict[str, Any]] = []
        for arm, rows in (("suspect", suspect), ("reviewed_good", reviewed_good)):
            for result in rows:
                reason = self._result_exclusion_reason(result)
                if reason is not None:
                    excluded.append({"arm": arm, "trial_id": result.trial_id, "experiment_id": result.experiment_id, "scenario_id": result.scenario_id, "reason": reason})
        return {"suspect_total": len(suspect), "reviewed_good_total": len(reviewed_good), "valid_rows": len(suspect) + len(reviewed_good) - len(excluded), "excluded_rows": len(excluded), "excluded": excluded}

    def _complete_repetition_cell(self, raw_rows: list[ExperimentResult], valid_rows: list[ExperimentResult]) -> bool:
        if not raw_rows or len({row.experiment_id for row in raw_rows}) != 1:
            return False
        spec = next((item for item in self.experiments if item.experiment_id == raw_rows[0].experiment_id), None)
        if spec is None or spec.operator != "baseline" or spec.repetitions != 3:
            return False
        if len(raw_rows) != spec.repetitions or len(valid_rows) != spec.repetitions:
            return False
        return {row.repetition for row in valid_rows} == set(range(1, spec.repetitions + 1))

    @staticmethod
    def _scenario_digest(rows: list[ExperimentResult]) -> str | None:
        import hashlib
        import json

        digests = {
            hashlib.sha256(json.dumps(result.run.scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            for result in rows
            if result.run is not None
        }
        return next(iter(digests)) if len(digests) == 1 else None

    @staticmethod
    def _group_by_fixture(results: list[ExperimentResult]) -> dict[str, list[ExperimentResult]]:
        """Group results by source fixture ID, retaining invalid rows too."""
        grouped: dict[str, list[ExperimentResult]] = {}
        for result in results:
            key = result.scenario_id
            grouped.setdefault(key, []).append(result)
        return grouped

    def _revise_hypotheses(self, spec: ExperimentSpec, results: list[ExperimentResult]) -> None:
        if self.validation_pair is not None:
            self._recompute_strict_hypothesis_evidence()
            return
        completed = [result for result in results if result.status == "completed" and result.activation.activated and result.run]
        if not completed or not self.hypotheses:
            return
        for hypothesis in self.hypotheses:
            if spec.hypothesis_id != hypothesis.hypothesis_id:
                continue
            baseline = next((run for run in self.runs if spec.source_run_id and run.run_id == spec.source_run_id and run.scenario.scenario_id == spec.source_scenario_id and run.configuration_id == spec.configuration_id and run.checker_status == "completed" and run.checker_passed is False), None)
            if baseline is None:
                self.observations.append({"kind": "hypothesis_evidence", "status": "unusable", "hypothesis_id": hypothesis.hypothesis_id, "experiment_id": spec.experiment_id, "reason": "experiment lacks a matching independently failing source baseline"})
                continue
            family = hypothesis.predicates.get("family")
            if family == "memory" and spec.operator == "remove_note":
                if hypothesis.predicates.get("note_text") != spec.value:
                    continue
                # Removing the obsolete note should clear the violation if memory is causal.
                ineligible = [result for result in completed if result.source_run_id == baseline.run_id and result.run and result.run.scenario.scenario_id == baseline.scenario.scenario_id and not self.runner.target.checker.expected_eligible(result.run.scenario)]
                if not ineligible:
                    continue
                if all(result.observed_violation is False for result in ineligible):
                    hypothesis.status = "supported"
                    hypothesis.rationale = "removing the obsolete note eliminated observed violations"
                elif all(result.observed_violation is True for result in ineligible):
                    hypothesis.status = "rejected"
                    hypothesis.rationale = "removing the obsolete note did not clear the violation"
            elif family == "memory" and spec.operator == "unrelated_note":
                if hypothesis.predicates.get("note_text") == spec.value:
                    continue
                # Control: unrelated edit should leave the failure intact on ineligible cases.
                ineligible = [result for result in completed if result.source_run_id == baseline.run_id and result.run and result.run.scenario.scenario_id == baseline.scenario.scenario_id and not self.runner.target.checker.expected_eligible(result.run.scenario)]
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
                hypothesis.rationale = "notes replacement does not test policy retrieval; policy hypothesis remains open"

    def _recompute_strict_hypothesis_evidence(self) -> None:
        """Recompute causal support from complete, source-scoped batches.

        A new-family hypothesis is supported only by three independently
        failing source baselines, three passes under the matching intervention,
        and three failures under an unrelated-note control.  Partial,
        contradictory, invalid, or differently sourced batches remain unknown.
        """
        relevant_operators = {
            "memory": "remove_note",
            "amount_units": "refund_api_unit",
            "idempotency": "delivery_attempts",
            "policy": "policy_notes",
        }
        for hypothesis in self.hypotheses:
            family = hypothesis.predicates.get("family")
            operator = relevant_operators.get(family)
            if operator is None:
                continue
            source_run_id = hypothesis.predicates.get("source_run_id")
            source_scenario_id = hypothesis.predicates.get("source_scenario_id")
            if not source_run_id or not source_scenario_id:
                continue
            source_run = next((run for run in self.runs if run.run_id == source_run_id), None)
            source_configuration_id = source_run.configuration_id if source_run is not None else None
            source_digest = self._scenario_digest_from_scenario(source_run.scenario) if source_run is not None else None
            scoped: list[tuple[ExperimentSpec, ExperimentResult]] = []
            for result in self.results:
                spec = self._spec_for_result(result)
                if spec is None or result.source_run_id != source_run_id or result.scenario_id != source_scenario_id or result.fixture_partition != "main":
                    continue
                if spec.source_run_id != source_run_id or spec.source_scenario_id != source_scenario_id or spec.source_role != "incident":
                    continue
                if source_configuration_id is not None and spec.configuration_id != source_configuration_id:
                    continue
                # Baseline rows must reproduce the complete observed source
                # input. Relevant and unrelated intervention rows are
                # intentionally controlled deltas, so their full scenario
                # digest is expected to differ while source IDs/config remain
                # fixed and the operator/value below identifies the delta.
                if spec.operator == "baseline" and source_digest is not None and (result.run is None or self._scenario_digest([result]) != source_digest):
                    continue
                scoped.append((spec, result))
            baseline = [(spec, result) for spec, result in scoped if spec.operator == "baseline"]
            relevant = [(spec, result) for spec, result in scoped if spec.operator == operator and self._relevant_value_matches(hypothesis, spec)]
            unrelated = [(spec, result) for spec, result in scoped if spec.operator == "unrelated_note"]
            evidence_rows = [result for _spec, result in (*baseline, *relevant, *unrelated)]
            if not evidence_rows:
                continue
            valid = all(self._strict_result_valid(result) for result in evidence_rows)
            complete = valid and self._strict_batch(baseline, expected_violation=True) and self._strict_batch(relevant, expected_violation=False) and self._strict_batch(unrelated, expected_violation=True)
            if complete:
                hypothesis.status = "supported"
                hypothesis.rationale = "three source baseline failures, three relevant intervention passes, and three unrelated-note failures"
            else:
                hypothesis.status = "unknown"
                hypothesis.rationale = "causal evidence is incomplete or contradictory; no hypothesis support inferred"

    @staticmethod
    def _strict_result_valid(result: ExperimentResult) -> bool:
        return result.status == "completed" and result.activation.activated and result.run is not None and result.run.status.value == "completed" and result.run.checker_status == "completed" and result.run.checker_passed is not None and result.observed_violation is not None and result.observed_violation == (result.run.checker_passed is False)

    @staticmethod
    def _strict_batch(rows: list[tuple[ExperimentSpec, ExperimentResult]], *, expected_violation: bool) -> bool:
        if len(rows) != 3 or len({spec.experiment_id for spec, _result in rows}) != 1 or {result.repetition for _spec, result in rows} != {1, 2, 3}:
            return False
        spec = rows[0][0]
        if spec.repetitions != 3:
            return False
        return all(Tools._strict_result_valid(result) and result.observed_violation is expected_violation for _spec, result in rows)

    @staticmethod
    def _relevant_value_matches(hypothesis: Hypothesis, spec: ExperimentSpec) -> bool:
        family = hypothesis.predicates.get("family")
        if family == "memory":
            return spec.value == hypothesis.predicates.get("note_text")
        if family == "amount_units":
            return spec.value is not None and spec.value != hypothesis.predicates.get("refund_api_unit")
        if family == "idempotency":
            observed = hypothesis.predicates.get("delivery_attempts")
            return spec.value is not None and observed is not None and spec.value != observed
        return True

    @staticmethod
    def _scenario_digest_from_scenario(scenario: Scenario) -> str:
        import hashlib
        import json

        return hashlib.sha256(json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class AdaptiveInvestigator:
    tools: Tools
    controller: InvestigatorController
    # Reserve room for the registered evidence phase: baseline, relevant,
    # unrelated controls (9), the suspect/reviewed-good 2x2 (12), and the
    # four held-out cells. Adaptive actions must not starve that phase.
    validation_reserve_trials: int = 0

    def investigate(self, scenario: Scenario, *, max_steps: int = 8, control_scenario: Scenario | None = None, held_out_scenarios: list[Scenario] | None = None, original_suite_runs: list[RunRecord] | None = None) -> list[ExperimentResult]:
        all_results: list[ExperimentResult] = []
        control = control_scenario or legitimate_control()
        for _ in range(max_steps):
            if not self.tools.budget.can_investigate():
                self.tools.stop_reason = self.tools.stop_reason or "inconclusive:investigator_call_budget_exhausted"
                self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                break
            self.tools.budget.investigator_calls += 1
            try:
                action = self._normalize(self.controller.next_action(list(self.tools.observations)))
            except Exception as exc:
                self.tools.stop_reason = f"inconclusive:controller_error:{type(exc).__name__}"
                self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                break
            if action.kind == "finish":
                if not self.tools.stop_reason:
                    self.tools.stop_reason = "controller_finished"
                break
            if action.kind == "probe_case":
                if self.tools.budget.target_trials + 1 > self.tools.budget.max_target_trials - self.validation_reserve_trials:
                    self.tools.observations.append(
                        {
                            "kind": "validation_handoff",
                            "status": "deferred",
                            "reason": "adaptive_probe_would_consume_registered_validation_reserve",
                            "target_trials": self.tools.budget.target_trials,
                            "reserved_trials": self.validation_reserve_trials,
                        }
                    )
                    self.tools.stop_reason = "validation_handoff"
                    break
                try:
                    run = self.tools.probe_case(scenario)
                except Exception as exc:
                    self.tools.stop_reason = f"inconclusive:probe_error:{type(exc).__name__}"
                    self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                    break
                self.tools.inspect_trace(run)
                continue
            if action.kind == "inspect_trace":
                selected_run = self._selected_run(scenario)
                if selected_run is not None:
                    self.tools.inspect_trace(selected_run)
                else:
                    self.tools.observations.append({"kind": "inspect_trace", "status": "no_run"})
                continue
            if action.kind == "triage_hypotheses":
                self.tools.triage_hypotheses(self.tools.runs, selected_run=self._selected_run(scenario))
                continue
            if action.kind == "run_experiment" and action.operator:
                planned_repetitions = 3
                if self.tools.budget.target_trials + planned_repetitions > self.tools.budget.max_target_trials - self.validation_reserve_trials:
                    self.tools.observations.append(
                        {
                            "kind": "validation_handoff",
                            "status": "deferred",
                            "reason": "adaptive_trial_would_consume_registered_validation_reserve",
                            "target_trials": self.tools.budget.target_trials,
                            "reserved_trials": self.validation_reserve_trials,
                        }
                    )
                    self.tools.stop_reason = "validation_handoff"
                    break
                value = action.value
                if action.source == "held_out":
                    target = next((item for item in (held_out_scenarios or []) if isinstance(action.value, str) and item.scenario_id == action.value), None)
                    if target is None:
                        self.tools.stop_reason = "inconclusive:held_out_source_unresolved"
                        self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                        break
                else:
                    target = control if action.source == "control" else scenario
                if action.operator == "policy_notes" and value == "reviewed_policy":
                    value = "Refunds are allowed up to 14 days."
                if action.operator == "remove_note" and value in (None, "obsolete"):
                    value = OBSOLETE_NOTE
                if action.operator == "unrelated_note" and value in (None, "control"):
                    value = UNRELATED_NOTE
                # Bind every adaptive arm to the original, unchanged fixture.
                # Intervention runs intentionally retain the scenario ID, so
                # an ID-only/reversed lookup can silently turn a later arm
                # into the source for a different experiment.  Configuration
                # is the application under test, not the source fixture;
                # source traces are always the default main-partition run.
                source_run = next(
                    (
                        run
                        for run in self.tools.runs
                        if run.scenario == target
                        and run.configuration_id == "default"
                        and run.fixture_partition == "main"
                    ),
                    None,
                )
                spec = ExperimentSpec(hypothesis_id=action.hypothesis_id or self._active_hypothesis_id(action.operator), name=f"{action.operator}:{value}", operator=action.operator, value=value, source_scenario_id=target.scenario_id, source_run_id=source_run.run_id if source_run else None, source_role=action.source, configuration_id=action.configuration_id, fixture_partition=action.fixture_partition)
                try:
                    all_results.extend(self.tools.run_experiment(spec, target))
                except RuntimeError:
                    self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
                    break
                continue
            if action.kind == "check_suite":
                self.tools.check_suite(self.tools.runs, original_suite_runs=original_suite_runs)
                continue
            if action.kind == "propose_tests":
                self.tools.propose_tests()
                continue
            self.tools.observations.append({"kind": "unknown_controller_action", "action": action.model_dump(mode="json")})
        if not self.tools.stop_reason:
            self.tools.stop_reason = "inconclusive:max_investigator_steps_exhausted"
            self.tools.observations.append({"kind": "stop", "status": "inconclusive", "reason": self.tools.stop_reason})
        return all_results

    def _selected_run(self, scenario: Scenario) -> RunRecord | None:
        # Keep the original independently observed trace as the source of
        # hypotheses. Later intervention runs are evidence, not a replacement
        # incident whose IDs could silently retarget the investigation.
        return next(
            (
                run
                for run in self.tools.runs
                if run.scenario == scenario
                and run.configuration_id == "default"
                and run.fixture_partition == "main"
            ),
            None,
        )

    def _active_hypothesis_id(self, operator: str) -> str:
        family_by_operator = {
            "remove_note": "memory",
            "unrelated_note": "memory",
            "policy_notes": "policy",
            "refund_api_unit": "amount_units",
            "delivery_attempts": "idempotency",
        }
        family = family_by_operator.get(operator, "policy")
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
            parsed: str | int = int(value) if operator in {"order_age", "delivery_attempts"} else value
            return ControllerAction(kind="run_experiment", operator=operator, value=parsed)  # type: ignore[arg-type]
        raise ValueError(f"unsupported controller action: {raw}")


class BranchingStubController:
    """Offline seam: chooses the next step from observed evidence.

    Sequence mirrors the plan loop: probe → triage → remove_note → unrelated
    note control → check_suite → propose_tests → finish.
    """

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _next_observed_intervention(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        hypothesis_rows: list[dict[str, Any]] = []
        for item in reversed(observations):
            if item.get("kind") == "hypotheses":
                hypothesis_rows = list(item.get("hypotheses", []))
                break
        if not hypothesis_rows:
            return None
        completed_operators = {item.get("operator") for item in observations if item.get("kind") == "experiment"}
        def priority(row: dict[str, Any]) -> int:
            predicates = row.get("predicates") or {}
            family = predicates.get("family")
            if family == "idempotency":
                try:
                    if int(predicates.get("delivery_attempts")) > 1:
                        return 0
                except (TypeError, ValueError):
                    pass
                if predicates.get("duplicate_signal") is True:
                    return 0
                try:
                    if int(predicates.get("ledger_entries", 0)) > 1:
                        return 0
                except (TypeError, ValueError):
                    pass
            if family == "amount_units" and str(predicates.get("refund_api_unit", "")).lower() == "minor" and predicates.get("amount_mismatch") is not False:
                return 1
            if family == "memory":
                note = str(predicates.get("note_text", "")).lower()
                if "30-day" in note or "30 day" in note or "all orders" in note:
                    return 2
            return 10

        for row in sorted(hypothesis_rows, key=priority):
            predicates = row.get("predicates") or {}
            family = predicates.get("family")
            if family == "memory" and "remove_note" not in completed_operators:
                note = predicates.get("note_text")
                note_lower = note.lower() if isinstance(note, str) else ""
                if isinstance(note, str) and ("30-day" in note_lower or "30 day" in note_lower or "all orders" in note_lower):
                    return {"operator": "remove_note", "value": note, "hypothesis_id": row.get("hypothesis_id"), "rationale": "remove the exact note observed in the selected trace"}
            if family == "amount_units" and "refund_api_unit" not in completed_operators:
                observed = predicates.get("refund_api_unit")
                value = "major" if str(observed).lower() == "minor" else "minor"
                return {"operator": "refund_api_unit", "value": value, "hypothesis_id": row.get("hypothesis_id"), "rationale": "change only the observed refund API unit"}
            if family == "idempotency" and "delivery_attempts" not in completed_operators:
                observed = predicates.get("delivery_attempts")
                try:
                    value = 1 if int(observed) > 1 else 2
                except (TypeError, ValueError):
                    value = 1
                return {"operator": "delivery_attempts", "value": value, "hypothesis_id": row.get("hypothesis_id"), "rationale": "reduce or increase the observed delivery-attempt count"}
            if family == "policy" and "policy_notes" not in completed_operators:
                return {"operator": "policy_notes", "value": "reviewed_policy", "hypothesis_id": row.get("hypothesis_id"), "rationale": "replay the policy lookup with the approved policy result"}
        return None

    def next_action(self, observations: list[dict[str, Any]]) -> ControllerAction:
        self.calls += 1
        kinds = [item.get("kind") for item in observations]
        if not observations:
            return ControllerAction(kind="probe_case")
        latest = observations[-1]
        if latest.get("kind") == "trace" and latest.get("checker_passed") is False and "hypotheses" not in kinds:
            return ControllerAction(kind="triage_hypotheses")
        if latest.get("kind") in {"hypotheses", "jev_triage"}:
            intervention = self._next_observed_intervention(observations)
            if intervention is not None:
                return ControllerAction(kind="run_experiment", **intervention)
        if latest.get("kind") == "experiment" and not any(item.get("kind") == "experiment" and item.get("operator") == "unrelated_note" for item in observations):
            # Only schedule the control after the remove_note experiment batch.
            if any(item.get("kind") == "experiment" and item.get("operator") == "remove_note" for item in observations):
                return ControllerAction(kind="run_experiment", operator="unrelated_note", value=UNRELATED_NOTE)
        if latest.get("kind") == "experiment" and not any(item.get("kind") == "experiment" and item.get("operator") == "baseline" and item.get("source") == "control" for item in observations):
            return ControllerAction(kind="run_experiment", operator="baseline", source="control", rationale="validate an eligible control through the unchanged pipeline")
        if "suite_check" not in kinds and any(item.get("kind") == "experiment" for item in observations):
            return ControllerAction(kind="check_suite")
        if "propose_tests" not in kinds and "suite_check" in kinds:
            return ControllerAction(kind="propose_tests")
        return ControllerAction(kind="finish")
