from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math

import pytest

from faultline.budget import BudgetExceeded, BudgetLedger


def _reserve(path, request_id: str, category: str = "worker", amount: float = 0.05):
    ledger = BudgetLedger(path, ceiling_usd=10.0, automation_cap_usd=2.0, case_cap_usd=1.0, category_caps_usd={"worker": 0.10})
    return ledger.reserve(amount, request_id=request_id, category=category, case_id=request_id, approved=True)


def test_worker_category_cap_is_atomic_and_categories_are_independent(tmp_path):
    path = tmp_path / "budget.sqlite"
    ledger = BudgetLedger(path, category_caps_usd={"worker": 0.10}, automation_cap_usd=2.0)
    ledger.reserve(0.05, request_id="worker-1", category="worker", case_id="case-1", approved=True)
    ledger.reserve(0.05, request_id="worker-2", category="worker", case_id="case-2", approved=True)
    with pytest.raises(BudgetExceeded, match="category"):
        ledger.reserve(0.01, request_id="worker-3", category="worker", case_id="case-3", approved=True)
    # The target cap is category-scoped; investigator/provider categories are
    # independently governed by the global/automation/case limits.
    ledger.reserve(0.20, request_id="openrouter-1", category="openrouter", case_id="case-4", approved=True)
    assert ledger.category_caps_usd == {"worker": pytest.approx(0.10)}


def test_category_cap_races_allow_only_atomic_remaining_capacity(tmp_path):
    path = tmp_path / "budget.sqlite"

    def attempt(index: int):
        try:
            return _reserve(path, f"racing-{index}")
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert sum(item is not None for item in outcomes) == 2
    reopened = BudgetLedger(path)
    assert reopened.snapshot().pending_usd == pytest.approx(0.10)


def test_repeated_concurrent_initialization_survives_wal_startup_race(tmp_path):
    path = tmp_path / "startup-race.sqlite"

    def open_ledger(index: int):
        ledger = BudgetLedger(
            path,
            ceiling_usd=10.0,
            automation_cap_usd=2.0,
            category_caps_usd={"worker": 0.10},
        )
        return index, ledger.category_caps_usd

    # Each round starts from the same already-openable database while several
    # independent instances initialize concurrently. This exercises both the
    # first WAL transition and subsequent schema reads without weakening the
    # reservation race test above.
    for _ in range(5):
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(open_ledger, range(8)))
        assert [index for index, _ in outcomes] == list(range(8))
        assert all(caps == {"worker": pytest.approx(0.10)} for _, caps in outcomes)


def test_lower_category_cap_persists_and_reopen_cannot_raise_or_remove_it(tmp_path):
    path = tmp_path / "budget.sqlite"
    first = BudgetLedger(path, category_caps_usd={"worker": 0.10}, automation_cap_usd=2.0)
    assert first.category_caps_usd["worker"] == pytest.approx(0.10)
    first.reserve(0.05, request_id="pending", category="worker", case_id="case", approved=True)

    reopened_without_mapping = BudgetLedger(path, automation_cap_usd=2.0)
    assert reopened_without_mapping.category_caps_usd["worker"] == pytest.approx(0.10)
    reopened_without_mapping.reserve(0.05, request_id="pending-2", category="worker", case_id="case-2", approved=True)
    with pytest.raises(BudgetExceeded):
        reopened_without_mapping.reserve(0.01, request_id="pending-3", category="worker", case_id="case-3", approved=True)

    reopened_higher = BudgetLedger(path, category_caps_usd={"worker": 0.50}, automation_cap_usd=2.0)
    assert reopened_higher.category_caps_usd["worker"] == pytest.approx(0.10)


def test_unknown_usage_retains_worker_category_exposure_across_reopen(tmp_path):
    path = tmp_path / "budget.sqlite"
    ledger = BudgetLedger(path, category_caps_usd={"worker": 0.10}, automation_cap_usd=2.0)
    reservation = ledger.reserve(0.10, request_id="unknown", category="worker", case_id="case", approved=True)
    ledger.reconcile(reservation.reservation_id, None, usage_available=False)

    reopened = BudgetLedger(path, automation_cap_usd=2.0)
    assert reopened.snapshot().pending_usd == pytest.approx(0.10)
    with pytest.raises(BudgetExceeded):
        reopened.reserve(0.01, request_id="after-unknown", category="worker", case_id="case-2", approved=True)


@pytest.mark.parametrize("cap", [-0.01, math.nan, math.inf, -math.inf, 10.01])
def test_category_cap_must_be_finite_nonnegative_and_within_global_hard_ceiling(tmp_path, cap):
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path / f"invalid-{str(cap)}.sqlite", category_caps_usd={"worker": cap})


def test_existing_ledger_without_category_mapping_remains_uncapped_by_new_option(tmp_path):
    path = tmp_path / "legacy.sqlite"
    legacy = BudgetLedger(path, ceiling_usd=1.0, automation_cap_usd=1.0)
    legacy.reserve(0.50, request_id="legacy-1", category="worker", case_id="case-1", approved=True)
    reopened = BudgetLedger(path, ceiling_usd=1.0, automation_cap_usd=1.0)
    reopened.reserve(0.50, request_id="legacy-2", category="worker", case_id="case-2", approved=True)
