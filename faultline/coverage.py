"""Scenario-presence and independently observed grader coverage axes."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import CoverageAssessment, ExperimentResult, Scenario


OBSOLETE_NOTE_MARKERS = ("30-day", "30 day")


def condition_matches_scenario(scenario: Scenario, condition: str) -> bool | None:
    """Shared reviewed predicates used for suite presence and trial grouping."""
    if condition == "memory_conflict":
        return scenario.requested_action == "refund" and 14 < scenario.order_age_days <= 30 and any(marker in note.lower() for note in scenario.notes for marker in OBSOLETE_NOTE_MARKERS)
    if condition == "customer_note":
        return scenario.requested_action == "refund" and bool(scenario.notes)
    if condition == "order_age<=14":
        return scenario.requested_action == "refund" and scenario.order_age_days <= 14
    if condition == "age_boundary":
        return scenario.requested_action == "refund" and scenario.order_age_days in {14, 15}
    if condition == "ordinary_refund":
        return scenario.requested_action == "refund"
    return None


def _known(condition: str) -> bool:
    return condition_matches_scenario(Scenario(order_id="_", customer_id="_", order_age_days=0, amount=1), condition) is not None


def assess_coverage(*, original_conditions: set[str], existing_grader_conditions: set[str], suspect: Iterable[ExperimentResult], reviewed_good: Iterable[ExperimentResult], grader_observations: dict[str, Any] | list[dict[str, Any]] | None = None, discovered_conditions: set[str] | None = None) -> list[CoverageAssessment]:
    """Join grader observations to completed independently failing runs.

    Observation entries must carry `trial_id` or `run_id`, `condition`, a
    boolean `detected`, and `grader_version`. Bare labels are ignored. The
    independent violation must be present on the joined result, so a no-op,
    invalid, infrastructure, or unmatched record cannot prove a miss.
    """
    suspect = list(suspect)
    reviewed_good = list(reviewed_good)
    all_results = suspect + reviewed_good
    by_trial = {result.trial_id: result for result in all_results}
    by_run = {result.run.run_id: result for result in all_results if result.run}
    observations = grader_observations or {}
    if isinstance(observations, list):
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in observations:
            if isinstance(entry, dict) and isinstance(entry.get("condition"), str):
                grouped.setdefault(entry["condition"], []).append(entry)
        observations = grouped
    valid: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    if isinstance(observations, dict):
        for condition, entries in observations.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("condition", condition) != condition or not entry.get("grader_version") or not isinstance(entry.get("detected"), bool):
                    continue
                result = by_trial.get(entry.get("trial_id")) or by_run.get(entry.get("run_id"))
                if not result or result.status != "completed" or not result.activation.activated or not result.run or result.run.status.value != "completed" or result.run.checker_status != "completed" or result.run.checker_passed is not False or result.observed_violation is not True or condition_matches_scenario(result.run.scenario, condition) is not True:
                    continue
                evidence_id = result.trial_id or result.run.run_id
                key = (evidence_id, condition, str(entry["grader_version"]))
                if key in seen:
                    continue
                seen.add(key)
                valid.append({"condition": condition, "detected": entry["detected"]})
    conditions = sorted(original_conditions | existing_grader_conditions | (discovered_conditions or set()) | set(observations) if isinstance(observations, dict) else set())
    out: list[CoverageAssessment] = []
    for condition in conditions:
        original = "unknown" if not _known(condition) else "present" if condition in original_conditions else "missing"
        evidence = [entry for entry in valid if entry["condition"] == condition]
        detected_count = sum(entry["detected"] is True for entry in evidence)
        missed_count = sum(entry["detected"] is False for entry in evidence)
        grader = "mixed" if detected_count and missed_count else "detected" if detected_count else "missed" if missed_count else "unknown"
        valid_suspect = [result for result in suspect if result.status == "completed" and result.activation.activated and result.observed_violation is True and result.run and condition_matches_scenario(result.run.scenario, condition) is True]
        valid_good = [result for result in reviewed_good if result.status == "completed" and result.activation.activated and result.observed_violation is False and result.run and condition_matches_scenario(result.run.scenario, condition) is True]
        out.append(CoverageAssessment(condition=condition, original_suite=original, grader_observed=grader, suspect_count=len(valid_suspect), reviewed_good_count=len(valid_good), detected_count=detected_count, missed_count=missed_count, notes="Unmatched, invalid, infrastructure, or no-violation observations cannot prove a grader miss."))
    return out
