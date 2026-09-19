from __future__ import annotations

import time

import pytest

from faultline.clock import FixedClock
from faultline.coverage import assess_coverage, condition_matches_scenario
from faultline.export import approve, export_proposal, prepare_proposal
from faultline.cli import approve_export
from faultline.incidents import IncidentQueue
from faultline.investigator import AdaptiveInvestigator, BranchingStubController, Tools
from faultline.models import Action, BudgetState, ExperimentSpec, EvidenceOrigin, Scenario
from faultline.return_desk import RefundTool, ReturnDesk, RuleChecker
from faultline.scenarios import incident, legitimate_control
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


def test_adaptive_controller_branches_and_terminates() -> None:
    tools = Tools(LocalTrialRunner(ReturnDesk(), FixedClock()), BudgetState())
    results = AdaptiveInvestigator(tools, BranchingStubController()).investigate(incident(), max_steps=4)
    assert results
    assert tools.budget.investigator_calls < 4
    assert all(result.status == "completed" for result in results)


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
