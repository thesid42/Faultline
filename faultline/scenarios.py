"""Synthetic ReturnDesk fixtures, including held-out order IDs."""
from __future__ import annotations

from .models import Scenario

OBSOLETE_NOTE = "A 30-day window applies to this customer."
UNRELATED_NOTE = "Customer prefers phone contact."
PREFERENCE_NOTE = "Customer prefers email."


def current_incident() -> Scenario:
    return Scenario(order_id="ORD-CURRENT-14", customer_id="CUS-1", order_age_days=14, amount=40, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True)


def stale_control() -> Scenario:
    return Scenario(order_id="ORD-STALE-30", customer_id="CUS-2", order_age_days=30, amount=50, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=False)


def incident() -> Scenario:
    return Scenario(order_id="ORD-INCIDENT-21", customer_id="CUS-3", order_age_days=21, amount=60, notes=[OBSOLETE_NOTE, PREFERENCE_NOTE], expected_eligible=False)


def legitimate_control() -> Scenario:
    return Scenario(order_id="ORD-CONTROL-7", customer_id="CUS-4", order_age_days=7, amount=20, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True, control=True)


def original_suite() -> list[Scenario]:
    # Six ordinary cases intentionally omit the conflicting-memory boundary.
    return [Scenario(order_id=f"ORD-SUITE-{age}", customer_id=f"CUS-SUITE-{age}", order_age_days=age, amount=25 + age, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=age <= 14) for age in (1, 3, 7, 10, 12, 14)]


def held_out() -> list[Scenario]:
    # Separate IDs prevent memorizing the original incident.  The first row
    # withholds the conflicting stale note; the second is a legitimate current
    # policy control with no obsolete note.
    return [Scenario(order_id="ORD-HELDOUT-CONFLICT", customer_id="CUS-H1", order_age_days=21, amount=35, notes=[OBSOLETE_NOTE, PREFERENCE_NOTE], expected_eligible=False), Scenario(order_id="ORD-HELDOUT-CURRENT", customer_id="CUS-H2", order_age_days=7, amount=35, notes=["Refunds are allowed up to 14 days.", PREFERENCE_NOTE], expected_eligible=True, control=True)]


def default_scenarios() -> list[Scenario]:
    return [current_incident(), stale_control(), incident(), legitimate_control()]
