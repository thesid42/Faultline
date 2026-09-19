from __future__ import annotations

import pytest

from faultline.clock import FixedClock
from faultline.coverage import condition_matches_scenario
from faultline.demo_profiles import get_demo_profile
from faultline.models import Action, EvidenceOrigin, ExperimentSpec, Scenario
from faultline.return_desk import ReturnDesk
from faultline.scenarios import OBSOLETE_NOTE, PREFERENCE_NOTE
from faultline.trials import LocalTrialRunner


def _trigger_and_control(name: str) -> tuple[object, Scenario, Scenario]:
    profile = get_demo_profile(name)
    trigger = next(scenario for scenario in profile.stream if condition_matches_scenario(scenario, profile.condition) is True)
    control = next(scenario for scenario in profile.stream if condition_matches_scenario(scenario, profile.condition) is False)
    return profile, trigger, control


@pytest.mark.parametrize("name", ["memory-conflict", "amount-unit", "duplicate-refund"])
def test_demo_profiles_have_fresh_heldouts_and_disclosed_control_notes(name: str) -> None:
    profile, trigger, control = _trigger_and_control(name)
    assert len(profile.suite) == 6
    assert len(profile.held_out) == 2
    assert {item.order_id for item in profile.stream}.isdisjoint(item.order_id for item in profile.held_out)
    assert condition_matches_scenario(trigger, profile.condition) is True
    assert condition_matches_scenario(control, profile.condition) is False
    assert all(PREFERENCE_NOTE in item.notes for item in profile.stream + profile.held_out)


@pytest.mark.parametrize("name", ["memory-conflict", "amount-unit", "duplicate-refund"])
def test_each_fault_fails_suspect_and_passes_reviewed_configuration(name: str) -> None:
    _profile, trigger, control = _trigger_and_control(name)
    target = ReturnDesk()

    suspect = target.run(trigger)
    suspect_control = target.run(control)
    reviewed = target.run(trigger, configuration_id="reviewed_good")
    reviewed_control = target.run(control, configuration_id="reviewed_good")

    assert suspect.status.value == "completed"
    assert suspect.checker_passed is False
    assert suspect_control.checker_passed is True
    assert reviewed.checker_passed is True
    assert reviewed_control.checker_passed is True
    assert suspect.evidence_origin is EvidenceOrigin.SIMULATED
    assert reviewed.evidence_origin is EvidenceOrigin.SIMULATED


def test_memory_profile_promotes_only_stale_retrieved_note_and_removal_fixes_it() -> None:
    profile, trigger, _control = _trigger_and_control("memory-conflict")
    target = ReturnDesk()
    suspect = target.run(trigger)
    reviewed = target.run(trigger, configuration_id="reviewed_good")
    suspect_policy = next(event for event in suspect.events if event.kind == "retrieve_policy")
    reviewed_policy = next(event for event in reviewed.events if event.kind == "retrieve_policy")
    assert suspect_policy.payload["max_age_days"] == 30
    assert suspect_policy.payload["source"] == "customer_note"
    assert reviewed_policy.payload["max_age_days"] == 14
    assert reviewed_policy.payload["source"] == "reviewed_policy"

    runner = LocalTrialRunner(target, FixedClock())
    spec = ExperimentSpec(hypothesis_id="memory", name="remove obsolete note", operator="remove_note", value=OBSOLETE_NOTE, repetitions=1)
    result = runner.run(spec, trigger)[0]
    assert result.status == "completed"
    assert result.observed_violation is False
    assert result.run is not None
    assert OBSOLETE_NOTE not in result.run.scenario.notes


def test_reviewed_configuration_withholds_all_customer_notes_but_retains_trace() -> None:
    _profile, trigger, _control = _trigger_and_control("memory-conflict")

    class NoteCaptureProvider(DeliberatelyDenyProvider):
        def __init__(self):
            self.calls: list[list[str]] = []

        def choose_action(self, *, order, policy, notes):
            self.calls.append(list(notes))
            return super().choose_action(order=order, policy=policy, notes=notes)

    provider = NoteCaptureProvider()
    suspect = ReturnDesk(provider).run(trigger, configuration_id="suspect")
    reviewed = ReturnDesk(provider).run(trigger, configuration_id="reviewed_good")
    assert provider.calls == [trigger.notes, []]
    retrieved = next(event for event in reviewed.events if event.kind == "retrieve_notes")
    assert retrieved.payload["notes"] == trigger.notes
    context = next(event for event in reviewed.events if event.kind == "decision_context")
    assert context.payload["customer_notes_in_decision"] is False
    assert context.payload["withheld_customer_note_count"] == len(trigger.notes)
    assert "customer memory" in context.payload["reason"]
    assert next(event for event in suspect.events if event.kind == "decision_context").payload["customer_notes_in_decision"] is True


def test_unrelated_note_intervention_preserves_both_policy_notes() -> None:
    _profile, trigger, _control = _trigger_and_control("memory-conflict")
    scenario = trigger.model_copy(update={"notes": ["Refunds are allowed up to 14 days.", OBSOLETE_NOTE, PREFERENCE_NOTE]})
    spec = ExperimentSpec(hypothesis_id="memory", name="replace preference", operator="unrelated_note", value="Customer prefers phone contact.", repetitions=1)
    result = LocalTrialRunner(ReturnDesk(), FixedClock()).run(spec, scenario)[0]
    assert result.status == "completed"
    assert result.run is not None
    assert "Refunds are allowed up to 14 days." in result.run.scenario.notes
    assert OBSOLETE_NOTE in result.run.scenario.notes
    assert "Customer prefers phone contact." in result.run.scenario.notes


def test_amount_unit_trace_proves_seeded_conversion_and_intervention() -> None:
    profile, trigger, _control = _trigger_and_control("amount-unit")
    suspect = ReturnDesk().run(trigger)
    request = next(event for event in suspect.events if event.kind == "refund_gateway_request")
    assert request.payload["request_unit"] == "minor"
    assert request.payload["request_amount"] == trigger.amount
    assert suspect.actual_ledger[0]["amount"] == trigger.amount / 100

    spec = ExperimentSpec(hypothesis_id="amount", name="use major gateway units", operator=profile.intervention_operator, value=profile.intervention_value, repetitions=1)
    result = LocalTrialRunner(ReturnDesk(), FixedClock()).run(spec, trigger)[0]
    assert result.status == "completed"
    assert result.observed_violation is False
    assert result.run is not None
    assert result.run.scenario.refund_api_unit == "major"
    assert result.run.actual_ledger[0]["amount"] == trigger.amount


def test_duplicate_profile_keeps_each_retry_and_reviewed_gateway_deduplicates() -> None:
    _profile, trigger, _control = _trigger_and_control("duplicate-refund")
    suspect = ReturnDesk().run(trigger)
    requests = [event for event in suspect.events if event.kind == "refund_gateway_request"]
    assert len(requests) == 2
    assert {event.payload["dedupe_scope"] for event in requests} == {"request"}
    assert len(suspect.actual_ledger) == 2
    assert suspect.checker_passed is False

    reviewed = ReturnDesk().run(trigger, configuration_id="reviewed_good")
    responses = [event for event in reviewed.events if event.kind == "refund_gateway_response"]
    assert len(reviewed.actual_ledger) == 1
    assert responses[-1].payload["deduplicated"] is True
    assert reviewed.checker_passed is True

    spec = ExperimentSpec(hypothesis_id="duplicate", name="single delivery attempt", operator="delivery_attempts", value=1, repetitions=1)
    result = LocalTrialRunner(ReturnDesk(), FixedClock()).run(spec, trigger)[0]
    assert result.status == "completed"
    assert result.observed_violation is False
    assert result.run is not None and len(result.run.actual_ledger) == 1


class DeliberatelyDenyProvider:
    evidence_origin = EvidenceOrigin.SIMULATED
    model = "action-choice-fixture"
    provider = "deterministic-test"
    backend = "local"
    version = "1"

    def choose_action(self, *, order, policy, notes):
        return Action(kind="deny", order_id=order["order_id"], amount=None, idempotency_key="chosen-deny", reason="test choice")


def test_demo_does_not_force_action_choice_and_validates_before_gateway() -> None:
    _profile, trigger, _control = _trigger_and_control("amount-unit")
    run = ReturnDesk(DeliberatelyDenyProvider()).run(trigger)
    assert run.agent_action is not None and run.agent_action.kind == "deny"
    assert run.actual_ledger == []
    assert run.checker_passed is False


class AmountMismatchProvider(DeliberatelyDenyProvider):
    def choose_action(self, *, order, policy, notes):
        return Action(kind="refund", order_id=order["order_id"], amount=order["amount"] + 1, idempotency_key="bad-amount")


def test_model_amount_is_rejected_before_seeded_gateway_defect() -> None:
    _profile, trigger, _control = _trigger_and_control("amount-unit")
    run = ReturnDesk(AmountMismatchProvider()).run(trigger)
    assert run.status.value == "invalid"
    assert run.actual_ledger == []
    assert not any(event.kind == "refund_gateway_request" for event in run.events)


def test_safe_live_provider_failure_code_is_persisted_without_message() -> None:
    from faultline.live import LiveCallError

    class FailingProvider(DeliberatelyDenyProvider):
        def choose_action(self, *, order, policy, notes):
            raise LiveCallError("model_json_parse_failure; secret=do-not-persist")

    scenario = Scenario(order_id="safe-error", customer_id="safe-customer", order_age_days=7, amount=10)
    run = ReturnDesk(FailingProvider()).run(scenario)
    error = next(event for event in run.events if event.kind == "error")
    assert error.payload["code"] == "live_call_failed"
    assert "secret" not in str(error.payload)
