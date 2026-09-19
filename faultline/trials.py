"""Trusted resettable local trial runner.

Every repetition receives a fresh target, ledger and fixed clock. Invalid or
non-activated interventions are retained as excluded results rather than
silently counted as agent outcomes.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import queue
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .clock import FixedClock
from .models import ActivationReceipt, ExperimentResult, ExperimentSpec, RunRecord, RunStatus, Scenario
from .return_desk import ReturnDesk

_OBSOLETE_MARKERS = ("30-day", "30 day", "all orders")
_UNRELATED_MARKERS = ("prefers", "preference", "contact", "email", "phone")


def _is_obsolete_note(note: str) -> bool:
    lowered = note.lower()
    return any(marker in lowered for marker in _OBSOLETE_MARKERS)


def _is_known_unrelated_note(note: str) -> bool:
    lowered = note.lower()
    return any(marker in lowered for marker in _UNRELATED_MARKERS)


def _worker(target: ReturnDesk, scenario: Scenario, output: Any, configuration_id: str, fixture_partition: str, source_run_id: str | None) -> None:
    """Top-level worker so Windows spawn can start a trusted child process."""
    try:
        output.put(("ok", target.run(scenario, notes=scenario.notes, configuration_id=configuration_id, fixture_partition=fixture_partition, source_run_id=source_run_id).model_dump(mode="json")))
    except Exception as exc:
        output.put(("error", f"{type(exc).__name__}"))


@dataclass
class LocalTrialRunner:
    target: ReturnDesk
    clock: FixedClock
    target_factory: Callable[[], ReturnDesk] | None = None
    backend: str = "local-subprocess"
    reserve_trial: Callable[[ExperimentSpec, Scenario, str], Any] | None = None
    reconcile_trial: Callable[[ExperimentSpec, Scenario, str, RunRecord | None, Any], None] | None = None

    def _new_target(self) -> ReturnDesk:
        if self.target_factory:
            return self.target_factory()
        # The target's provider and reviewed checker are immutable dependencies;
        # the service ledger itself is created inside ReturnDesk.run.
        return ReturnDesk(provider=self.target.provider, checker=self.target.checker)

    def _execute_isolated(self, scenario: Scenario, timeout_seconds: int, *, configuration_id: str = "default", fixture_partition: str = "main", source_run_id: str | None = None) -> RunRecord:
        """Execute in a killable child; no timed-out target can overlap a trial."""
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        process = context.Process(target=_worker, args=(self._new_target(), scenario, output, configuration_id, fixture_partition, source_run_id), daemon=True)
        process.start()
        deadline = time.monotonic() + timeout_seconds
        received: tuple[str, Any] | None = None
        try:
            while time.monotonic() < deadline:
                try:
                    received = output.get(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
                    break
                except queue.Empty:
                    if not process.is_alive():
                        break
            if received is None:
                raise TimeoutError("trial timeout; child process terminated")
            status, value = received
        finally:
            # A worker may have queued a large serialized trace while its
            # feeder thread is still flushing; draining before join avoids
            # false timeouts. Once a result is received, no late target work is
            # allowed to survive this trial.
            if process.is_alive():
                process.join(timeout=max(0.0, deadline - time.monotonic()))
            if process.is_alive():
                process.terminate()
                process.join(2)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(2)
            output.close()
            output.join_thread()
        if received is None:
            raise RuntimeError(f"trial child exited without result (exit={process.exitcode})")
        if status != "ok":
            raise RuntimeError(value)
        return RunRecord.model_validate(value)

    def probe(self, scenario: Scenario, *, timeout_seconds: int = 120) -> RunRecord:
        self.clock.reset()
        return self._execute_isolated(scenario, timeout_seconds)

    def _activate(self, spec: ExperimentSpec, scenario: Scenario) -> tuple[Scenario, str, str, bool, str]:
        before_json = json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        before = hashlib.sha256(before_json.encode()).hexdigest()
        trial = deepcopy(scenario)
        if spec.source_scenario_id and spec.source_scenario_id != scenario.scenario_id:
            return trial, before, before, False, "source scenario does not match selected fixture"
        if spec.operator == "baseline":
            return trial, before, before, True, "baseline source activated without intervention"
        if spec.operator in ("policy_notes", "remove_note", "unrelated_note", "refund_api_unit") and not isinstance(spec.value, str):
            return trial, before, before, False, "note operator requires a string value"
        if spec.operator == "refund_api_unit":
            if spec.value not in ("major", "minor"):
                return trial, before, before, False, "refund_api_unit requires major or minor"
            trial.refund_api_unit = spec.value
        elif spec.operator == "delivery_attempts":
            if not isinstance(spec.value, int) or isinstance(spec.value, bool) or not 1 <= spec.value <= 3:
                return trial, before, before, False, "delivery_attempts requires an integer from 1 through 3"
            trial.delivery_attempts = spec.value
        elif spec.operator == "policy_notes":
            # This is a supported tool-result replacement, represented as the
            # selected notes result rather than arbitrary generated code.
            trial.notes = [spec.value]  # type: ignore[list-item]
        elif spec.operator == "remove_note":
            if spec.value not in trial.notes:
                return trial, before, before, False, "selected note was not present"
            trial.notes = [note for note in trial.notes if note != spec.value]
        elif spec.operator == "unrelated_note":
            # Control edit: change a non-policy note while leaving obsolete notes
            # intact. If the memory hypothesis is correct, the failure persists.
            unrelated_indexes = [index for index, note in enumerate(trial.notes) if _is_known_unrelated_note(note) and not _is_obsolete_note(note)]
            if not trial.notes:
                return trial, before, before, False, "unrelated_note requires existing notes"
            if spec.value in trial.notes:
                return trial, before, before, False, "unrelated note already present"
            # Replace only an explicitly recognizable preference/contact note;
            # policy-bearing notes are never selected by position.
            if unrelated_indexes:
                trial.notes[unrelated_indexes[0]] = spec.value
            else:
                # Append-only control when no known unrelated source exists.
                trial.notes.append(spec.value)
        elif spec.operator == "order_age":
            if not isinstance(spec.value, int) or isinstance(spec.value, bool) or spec.value < 0:
                return trial, before, before, False, "order_age requires a non-negative integer"
            trial.order_age_days = spec.value
        after_json = json.dumps(trial.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        after = hashlib.sha256(after_json.encode()).hexdigest()
        return trial, before, after, before != after, "activated" if before != after else "operator made no change"

    def run(self, spec: ExperimentSpec, scenario: Scenario) -> list[ExperimentResult]:
        results: list[ExperimentResult] = []
        for repetition in range(1, spec.repetitions + 1):
            self.clock.reset()
            trial, before, after, activated, message = self._activate(spec, scenario)
            trial_id = hashlib.sha256(f"{spec.experiment_id}:{scenario.scenario_id}:{repetition}".encode()).hexdigest()[:20]
            receipt = ActivationReceipt(experiment_id=spec.experiment_id, trial_id=trial_id, activated=activated, operator=spec.operator, source_scenario_id=scenario.scenario_id, configuration_id=spec.configuration_id, before_digest=before, after_digest=after, message=message)
            if not activated:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, source_run_id=spec.source_run_id, configuration_id=spec.configuration_id, fixture_partition=spec.fixture_partition, repetition=repetition, activation=receipt, status="excluded", excluded_reason="activation_not_proven", evidence_origin="simulated"))
                continue
            reservation = None
            run: RunRecord | None = None
            try:
                if self.reserve_trial is not None:
                    reservation = self.reserve_trial(spec, scenario, trial_id)
                run = self._execute_isolated(trial, spec.timeout_seconds, configuration_id=spec.configuration_id, fixture_partition=spec.fixture_partition, source_run_id=spec.source_run_id)
                run.activation_receipts = [receipt.model_dump(mode="json")]
            except TimeoutError as exc:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, source_run_id=spec.source_run_id, configuration_id=spec.configuration_id, fixture_partition=spec.fixture_partition, repetition=repetition, activation=receipt, status="infrastructure_error", excluded_reason=str(exc), evidence_origin="simulated"))
                continue
            except Exception as exc:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, source_run_id=spec.source_run_id, configuration_id=spec.configuration_id, fixture_partition=spec.fixture_partition, repetition=repetition, activation=receipt, status="infrastructure_error", excluded_reason=f"trial infrastructure error: {type(exc).__name__}", evidence_origin="simulated"))
                continue
            finally:
                if self.reconcile_trial is not None:
                    self.reconcile_trial(spec, scenario, trial_id, run, reservation)
            if run.status is not RunStatus.COMPLETED or run.checker_status != "completed" or run.checker_passed is None:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, source_run_id=spec.source_run_id, configuration_id=spec.configuration_id, fixture_partition=spec.fixture_partition, repetition=repetition, activation=receipt, status="infrastructure_error", run=run, excluded_reason="run did not complete an independent check", evidence_origin=run.evidence_origin))
                continue
            results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, source_run_id=spec.source_run_id, configuration_id=spec.configuration_id, fixture_partition=spec.fixture_partition, repetition=repetition, activation=receipt, status="completed", run=run, observed_violation=run.checker_passed is False, evidence_origin=run.evidence_origin))
        return results
