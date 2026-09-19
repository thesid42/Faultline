"""Stable pydantic contracts persisted by Faultline.

Evidence and operational metadata intentionally travel together, so a case file
can be audited without re-running a model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceOrigin(str, Enum):
    LIVE = "live"
    SIMULATED = "simulated"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID = "invalid"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    at: datetime = Field(default_factory=utc_now)
    actor: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["refund", "escalate", "deny"]
    order_id: str
    amount: float | None = Field(default=None, ge=0)
    reason: str = ""
    idempotency_key: str


class ControllerAction(BaseModel):
    """Typed controller command; no arbitrary generated code is executable."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["inspect_trace", "triage_hypotheses", "run_experiment", "probe_case", "check_suite", "propose_tests", "finish"]
    operator: Literal["policy_notes", "remove_note", "unrelated_note", "order_age"] | None = None
    value: str | int | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(default_factory=lambda: uuid4().hex)
    order_id: str
    customer_id: str
    order_age_days: int = Field(ge=0)
    amount: float = Field(gt=0)
    policy_version: str = "v1"
    notes: list[str] = Field(default_factory=list)
    requested_action: Literal["refund", "escalate"] = "refund"
    expected_eligible: bool | None = None
    control: bool = False


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    scenario: Scenario
    status: RunStatus = RunStatus.COMPLETED
    events: list[Event] = Field(default_factory=list)
    actual_ledger: list[dict[str, Any]] = Field(default_factory=list)
    execution_status: str = "not_started"
    checker_status: str = "not_run"
    checker_passed: bool | None = None
    agent_action: Action | None = None
    model: str = "unknown"
    provider: str = "unknown"
    backend: str = "unknown"
    model_version: str = "unknown"
    evidence_origin: EvidenceOrigin = EvidenceOrigin.SIMULATED
    created_at: datetime = Field(default_factory=utc_now)
    trace_digest: str = ""


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(default_factory=lambda: uuid4().hex)
    statement: str
    predicates: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0, le=1)
    status: Literal["open", "supported", "rejected", "unknown"] = "open"
    rationale: str = ""


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(default_factory=lambda: uuid4().hex)
    hypothesis_id: str
    name: str
    operator: Literal["policy_notes", "remove_note", "unrelated_note", "order_age"]
    value: str | int | None = None
    repetitions: int = Field(default=3, ge=1, le=40)
    timeout_seconds: int = Field(default=120, gt=0, le=120)
    rationale: str = ""


class ActivationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    trial_id: str
    activated: bool
    operator: str
    before_digest: str
    after_digest: str
    message: str = ""
    activated_at: datetime = Field(default_factory=utc_now)


class ExperimentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trial_id: str = Field(default_factory=lambda: uuid4().hex)
    experiment_id: str
    scenario_id: str
    repetition: int = 1
    activation: ActivationReceipt
    status: Literal["completed", "excluded", "invalid", "infrastructure_error"] = "completed"
    run: RunRecord | None = None
    excluded_reason: str | None = None
    observed_violation: bool | None = None
    evidence_origin: EvidenceOrigin = EvidenceOrigin.SIMULATED


class CoverageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(default_factory=lambda: uuid4().hex)
    condition: str
    original_suite: Literal["present", "missing", "unknown"]
    grader_observed: Literal["detected", "missed", "mixed", "unknown", "invalid", "infrastructure_error"]
    suspect_count: int = 0
    reviewed_good_count: int = 0
    detected_count: int = 0
    missed_count: int = 0
    notes: str = ""


class RegressionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    rationale: str
    tests: list[dict[str, Any]] = Field(default_factory=list)
    source_trial_ids: list[str] = Field(default_factory=list)
    digest: str = ""
    reviewed: bool = False
    approval_digest: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None


class BudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_trials: int = 0
    investigator_calls: int = 0
    jev_calls: int = 0
    paid_calls: int = 0
    reserved_usd: float = 0.0
    spent_usd: float = 0.0
    max_target_trials: int = 40
    max_investigator_calls: int = 12
    max_jev_calls: int = 1
    soft_ceiling_usd: float = 15.0
    hard_ceiling_usd: float = 20.0

    def can_target_trial(self, count: int = 1) -> bool:
        return count > 0 and self.target_trials + count <= self.max_target_trials

    def can_investigate(self, count: int = 1) -> bool:
        return count > 0 and self.investigator_calls + count <= self.max_investigator_calls

    def can_jev(self, count: int = 1) -> bool:
        return count > 0 and self.jev_calls + count <= self.max_jev_calls

    def reserve(self, estimate: float, *, paid: bool = True) -> None:
        if estimate < 0 or not math.isfinite(estimate):
            raise ValueError("estimate must be finite and non-negative")
        if paid and self.spent_usd + self.reserved_usd + estimate > self.hard_ceiling_usd:
            raise RuntimeError("budget hard ceiling exceeded")
        if paid and self.spent_usd + self.reserved_usd + estimate > self.soft_ceiling_usd:
            raise RuntimeError("budget soft stop reached")
        if paid:
            self.reserved_usd += estimate
            self.paid_calls += 1

    def settle(self, estimate: float, actual: float, *, paid: bool = True) -> None:
        if actual < 0 or estimate < 0 or not math.isfinite(actual) or not math.isfinite(estimate):
            raise ValueError("costs must be finite and non-negative")
        if paid:
            self.reserved_usd = max(0.0, self.reserved_usd - estimate)
            self.spent_usd += actual
            if self.spent_usd > self.hard_ceiling_usd:
                raise RuntimeError("budget hard ceiling exceeded after settlement")


class Approval(BaseModel):
    proposal_digest: str
    approved_by: str
    approved_at: datetime = Field(default_factory=utc_now)


class Incident(BaseModel):
    """Deduplication key for an independently observed violation."""

    incident_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str
    violation_digest: str
    status: Literal["queued", "investigating", "complete", "inconclusive"] = "queued"


class CaseFile(BaseModel):
    case_id: str = Field(default_factory=lambda: uuid4().hex)
    status: Literal["queued", "investigating", "complete", "inconclusive"] = "queued"
    stop_reason: str = ""
    incident: Incident | None = None
    scenarios: list[Scenario] = Field(default_factory=list)
    runs: list[RunRecord] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    experiments: list[ExperimentSpec] = Field(default_factory=list)
    experiment_results: list[ExperimentResult] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    coverage: list[CoverageAssessment] = Field(default_factory=list)
    held_out_validation: list[dict[str, Any]] = Field(default_factory=list)
    proposal: RegressionProposal | None = None
    triage: dict[str, Any] | None = None
    budget: BudgetState = Field(default_factory=BudgetState)
    backend: str = "local-subprocess"
    evidence_origin: EvidenceOrigin = EvidenceOrigin.SIMULATED
