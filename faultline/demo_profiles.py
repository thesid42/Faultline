"""Deterministic synthetic ReturnDesk fault families for the local demo."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Scenario
from .scenarios import OBSOLETE_NOTE, PREFERENCE_NOTE, default_scenarios, original_suite


@dataclass(frozen=True)
class DemoProfile:
    name: str
    title: str
    condition: str
    stream: list[Scenario]
    suite: list[Scenario]
    held_out: list[Scenario]
    intervention_operator: str
    intervention_value: str | int


def _memory_profile() -> DemoProfile:
    return DemoProfile(
        name="memory-conflict",
        title="Conflicting customer-memory policy",
        condition="memory_conflict",
        stream=default_scenarios(),
        suite=original_suite(),
        held_out=[
            Scenario(order_id="ORD-HO-MEMORY-24", customer_id="CUS-HO-M1", order_age_days=24, amount=55, notes=[OBSOLETE_NOTE, PREFERENCE_NOTE], expected_eligible=False),
            Scenario(order_id="ORD-HO-MEMORY-9", customer_id="CUS-HO-M2", order_age_days=9, amount=55, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True, control=True),
        ],
        intervention_operator="remove_note",
        intervention_value=OBSOLETE_NOTE,
    )


def _amount_profile() -> DemoProfile:
    trigger = Scenario(order_id="ORD-AMOUNT-MINOR", customer_id="CUS-AMOUNT-1", order_age_days=7, amount=60, refund_api_unit="minor", notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True)
    control = Scenario(order_id="ORD-AMOUNT-MAJOR", customer_id="CUS-AMOUNT-2", order_age_days=7, amount=60, refund_api_unit="major", notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True, control=True)
    return DemoProfile(
        name="amount-unit",
        title="Refund gateway major/minor unit conversion",
        condition="refund_minor_units",
        stream=[trigger, control],
        suite=original_suite(),
        held_out=[
            Scenario(order_id="ORD-HO-AMOUNT-MINOR", customer_id="CUS-HO-A1", order_age_days=10, amount=35.25, refund_api_unit="minor", notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True),
            Scenario(order_id="ORD-HO-AMOUNT-MAJOR", customer_id="CUS-HO-A2", order_age_days=10, amount=35.25, refund_api_unit="major", notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True, control=True),
        ],
        intervention_operator="refund_api_unit",
        intervention_value="major",
    )


def _duplicate_profile() -> DemoProfile:
    trigger = Scenario(order_id="ORD-REDELIVERY-2", customer_id="CUS-REDELIVERY-1", order_age_days=7, amount=60, delivery_attempts=2, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True)
    control = Scenario(order_id="ORD-REDELIVERY-1", customer_id="CUS-REDELIVERY-2", order_age_days=7, amount=60, delivery_attempts=1, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True, control=True)
    return DemoProfile(
        name="duplicate-refund",
        title="Redelivery idempotency across retries",
        condition="redelivery",
        stream=[trigger, control],
        suite=original_suite(),
        held_out=[
            Scenario(order_id="ORD-HO-REDELIVERY-3", customer_id="CUS-HO-R1", order_age_days=3, amount=42.50, delivery_attempts=3, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True),
            Scenario(order_id="ORD-HO-REDELIVERY-1", customer_id="CUS-HO-R2", order_age_days=3, amount=42.50, delivery_attempts=1, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True, control=True),
        ],
        intervention_operator="delivery_attempts",
        intervention_value=1,
    )


def get_demo_profile(name: str) -> DemoProfile:
    profiles = {profile.name: profile for profile in (_memory_profile(), _amount_profile(), _duplicate_profile())}
    try:
        profile = profiles[name]
    except KeyError:
        raise ValueError(f"unknown demo profile: {name}") from None
    return DemoProfile(
        name=profile.name,
        title=profile.title,
        condition=profile.condition,
        stream=[scenario.model_copy(deep=True) for scenario in profile.stream],
        suite=[scenario.model_copy(deep=True) for scenario in profile.suite],
        held_out=[scenario.model_copy(deep=True) for scenario in profile.held_out],
        intervention_operator=profile.intervention_operator,
        intervention_value=profile.intervention_value,
    )
