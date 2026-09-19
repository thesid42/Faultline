from __future__ import annotations

from pathlib import Path

import pytest

from faultline.models import ControllerAction
from faultline.investigator import BranchingStubController
import faultline.workflow as workflow
from faultline.workflow import run_demo


class _InvalidThenCorrectingController:
    """Offline controller seam: reject one native value, then recover from feedback."""

    def __init__(self) -> None:
        self._delegate = BranchingStubController()
        self._sent_invalid = False

    def next_action(self, observations: list[dict[str, object]]) -> ControllerAction:
        if not self._sent_invalid and any(item.get("kind") == "hypotheses" for item in observations):
            self._sent_invalid = True
            hypothesis_id = next(
                (
                    row.get("hypothesis_id")
                    for item in observations
                    if item.get("kind") == "hypotheses"
                    for row in item.get("hypotheses", [])
                    if isinstance(row, dict) and isinstance(row.get("hypothesis_id"), str)
                ),
                None,
            )
            return ControllerAction(
                kind="run_experiment",
                operator="delivery_attempts",
                value=99,
                hypothesis_id=hypothesis_id,
                rationale="deliberately malformed native value for recovery coverage",
            )

        # The correction feedback is an observation, not a new incident. Let
        # the evidence-driven offline controller re-read the original
        # hypotheses and select the profile-specific observed intervention.
        if observations and observations[-1].get("kind") == "invalid_experiment_plan":
            observations = [item for item in observations if item.get("kind") != "invalid_experiment_plan"]
        return self._delegate.next_action(observations)


class _AlwaysInvalidController:
    """Offline controller seam that must fail closed without consuming trials."""

    def next_action(self, observations: list[dict[str, object]]) -> ControllerAction:
        if not observations:
            return ControllerAction(kind="probe_case")
        if observations[-1].get("kind") == "trace" and not any(item.get("kind") == "hypotheses" for item in observations):
            return ControllerAction(kind="triage_hypotheses")
        return ControllerAction(
            kind="run_experiment",
            operator="delivery_attempts",
            value=99,
            rationale="permanently malformed native value for fail-closed coverage",
        )


@pytest.mark.parametrize("profile", ["memory-conflict", "amount-unit", "duplicate-refund"])
def test_invalid_native_intervention_recovers_across_profiles(tmp_path: Path, profile: str) -> None:
    result = run_demo(
        profile=profile,
        controller=_InvalidThenCorrectingController(),
        db=tmp_path / f"recover-{profile}.sqlite3",
    )

    assert result.case.status == "complete", result.case.stop_reason
    assert result.case.proposal is not None
    assert result.case.budget.target_trials <= 40
    assert result.case.budget.investigator_calls <= 12

    rejected = [item for item in result.case.observations if item.get("kind") == "invalid_experiment_plan"]
    assert len(rejected) == 1
    assert rejected[0]["operator"] == "delivery_attempts"
    assert rejected[0]["value"] == 99
    assert rejected[0]["error_code"] == "invalid_integer_value"
    assert rejected[0]["correction_contract"]["operator"] == "delivery_attempts"  # type: ignore[index]

    # A rejected plan is feedback only: it must not create a spec or consume
    # target repetitions. The subsequent evidence must come from activated,
    # completed experiment rows and the fixed validation matrix.
    assert not any(spec.operator == "delivery_attempts" and spec.value == 99 for spec in result.case.experiments)
    assert result.case.experiments
    assert all(item.status == "completed" for item in result.case.experiment_results)
    assert all(item.activation.activated for item in result.case.experiment_results)


def test_always_invalid_intervention_is_inconclusive_without_proposal(tmp_path: Path) -> None:
    result = run_demo(
        profile="amount-unit",
        controller=_AlwaysInvalidController(),
        db=tmp_path / "always-invalid.sqlite3",
    )

    assert result.case.status == "inconclusive"
    assert result.case.proposal is None
    # The initial stream/suite fixtures are the only target calls. Rejected
    # controller plans add neither a spec nor a trial beyond those fixtures.
    assert result.case.budget.target_trials == len(result.case.runs)
    assert result.case.budget.investigator_calls <= 12
    assert result.case.experiments == []
    assert result.case.experiment_results == []
    assert any(item.get("kind") == "invalid_experiment_plan" for item in result.case.observations)


def test_reviewed_good_validation_failure_is_explicit_and_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_reviewed_reference(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("held_out_reviewed_good_failed")

    monkeypatch.setattr(workflow, "_run_held_out_matrix", fail_reviewed_reference)
    result = run_demo(profile="memory-conflict", db=tmp_path / "reviewed-failed.sqlite3")

    assert result.case.status == "inconclusive"
    assert result.case.stop_reason == "inconclusive:held_out_reviewed_good_failed"
    assert result.case.proposal is None
    failures = [item for item in result.case.observations if item.get("kind") == "validation_failure"]
    assert len(failures) == 1
    assert failures[0]["reason"] == "held_out_reviewed_good_failed"
    assert isinstance(failures[0]["failed_trial_ids"], list)
    assert "RuntimeError" not in str(failures[0])
