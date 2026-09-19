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


def _worker(target: ReturnDesk, scenario: Scenario, output: Any) -> None:
    """Top-level worker so Windows spawn can start a trusted child process."""
    try:
        output.put(("ok", target.run(scenario, notes=scenario.notes).model_dump(mode="json")))
    except Exception as exc:
        output.put(("error", f"{type(exc).__name__}"))


@dataclass
class LocalTrialRunner:
    target: ReturnDesk
    clock: FixedClock
    target_factory: Callable[[], ReturnDesk] | None = None
    backend: str = "local-subprocess"

    def _new_target(self) -> ReturnDesk:
        if self.target_factory:
            return self.target_factory()
        # The target's provider and reviewed checker are immutable dependencies;
        # the service ledger itself is created inside ReturnDesk.run.
        return ReturnDesk(provider=self.target.provider, checker=self.target.checker)

    def _execute_isolated(self, scenario: Scenario, timeout_seconds: int) -> RunRecord:
        """Execute in a killable child; no timed-out target can overlap a trial."""
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        process = context.Process(target=_worker, args=(self._new_target(), scenario, output), daemon=True)
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
        if spec.operator in ("policy_notes", "remove_note") and not isinstance(spec.value, str):
            return trial, before, before, False, "note operator requires a string value"
        if spec.operator == "policy_notes":
            # This is a supported tool-result replacement, represented as the
            # selected notes result rather than arbitrary generated code.
            trial.notes = [spec.value]  # type: ignore[list-item]
        elif spec.operator == "remove_note":
            if spec.value not in trial.notes:
                return trial, before, before, False, "selected note was not present"
            trial.notes = [note for note in trial.notes if note != spec.value]
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
            receipt = ActivationReceipt(experiment_id=spec.experiment_id, trial_id=trial_id, activated=activated, operator=spec.operator, before_digest=before, after_digest=after, message=message)
            if not activated:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, repetition=repetition, activation=receipt, status="excluded", excluded_reason="activation_not_proven", evidence_origin="simulated"))
                continue
            try:
                run = self._execute_isolated(trial, spec.timeout_seconds)
            except TimeoutError as exc:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, repetition=repetition, activation=receipt, status="infrastructure_error", excluded_reason=str(exc), evidence_origin="simulated"))
                continue
            except Exception as exc:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, repetition=repetition, activation=receipt, status="infrastructure_error", excluded_reason=f"trial infrastructure error: {type(exc).__name__}", evidence_origin="simulated"))
                continue
            if run.status is not RunStatus.COMPLETED or run.checker_status != "completed" or run.checker_passed is None:
                results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, repetition=repetition, activation=receipt, status="infrastructure_error", run=run, excluded_reason="run did not complete an independent check", evidence_origin=run.evidence_origin))
                continue
            results.append(ExperimentResult(trial_id=trial_id, experiment_id=spec.experiment_id, scenario_id=scenario.scenario_id, repetition=repetition, activation=receipt, status="completed", run=run, observed_violation=run.checker_passed is False, evidence_origin=run.evidence_origin))
        return results
