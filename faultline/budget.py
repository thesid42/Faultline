"""Persistent, parent-owned accounting for all paid model calls.

The ledger uses SQLite transactions so two workers cannot reserve the same
remaining allowance. A child receives an immutable grant and never opens this
database for writes. Ambiguous calls intentionally remain ``pending``: an
unknown charge is exposure, not a reason to release the reservation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import math
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterator, Mapping


MICROS = 1_000_000

# Multiple parent commands can start at once (for example a test fan-out or a
# supervisor restarting a worker). SQLite's WAL-mode transition is itself a
# schema-level write and is not covered by the reservation transaction. Keep
# same-process initializers from racing, and retry the small cross-process
# window below rather than turning a harmless startup race into a lost run.
_INITIALIZE_LOCK = threading.RLock()
_INITIALIZE_ATTEMPTS = 8


def canonical_ledger_path(project_root: str | Path | None = None) -> Path:
    """Return the stable parent ledger path, independent of command cwd."""
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    return root / "results" / "budget.sqlite3"


def open_canonical_ledger(project_root: str | Path | None = None, **kwargs: Any) -> "BudgetLedger":
    """Open the one canonical ledger used by all local parent commands."""
    return BudgetLedger(canonical_ledger_path(project_root), **kwargs)


def _micros(value: int | float | Decimal | str) -> int:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("cost must be finite and non-negative") from None
    if not decimal.is_finite() or decimal < 0:
        raise ValueError("cost must be finite and non-negative")
    return int((decimal * MICROS).to_integral_value(rounding=ROUND_CEILING))


def _usd(value: int) -> float:
    return value / MICROS


class BudgetExceeded(RuntimeError):
    """The persistent global ceiling cannot accommodate a new reservation."""


class AutomationCapExceeded(BudgetExceeded):
    """The automatic run cap requires an explicit parent approval."""


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: str
    request_id: str
    max_cost_usd: float
    status: str = "pending"
    case_id: str | None = None

    @property
    def max_cost(self) -> float:
        return self.max_cost_usd


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    ceiling_usd: float
    automation_cap_usd: float
    spent_usd: float
    pending_usd: float
    automation_approved: bool

    @property
    def committed_usd(self) -> float:
        return self.spent_usd + self.pending_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.ceiling_usd - self.committed_usd)


class BudgetLedger:
    """Canonical SQLite ledger. Only the parent process may reserve/reconcile."""

    def __init__(
        self,
        path: str | Path,
        *,
        ceiling_usd: float = 10.0,
        total_ceiling_usd: float | None = None,
        automation_cap_usd: float = 2.0,
        case_cap_usd: float = 1.0,
        category_caps_usd: Mapping[str, float] | None = None,
        parent_owned: bool = True,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._parent_owned = parent_owned
        ceiling = total_ceiling_usd if total_ceiling_usd is not None else ceiling_usd
        if ceiling > 10.0:
            raise ValueError("global persistent budget ceiling cannot exceed $10")
        self._ceiling_micro = _micros(ceiling)
        if automation_cap_usd > 2.0:
            raise ValueError("automatic spend cap cannot exceed $2")
        self._automation_cap_micro = _micros(automation_cap_usd)
        if case_cap_usd < 0 or not math.isfinite(case_cap_usd) or case_cap_usd > 1.0:
            raise ValueError("case_cap_usd must be finite and between zero and one")
        self._case_cap_micro = _micros(case_cap_usd)
        self._category_caps_micro = self._validate_category_caps(category_caps_usd)
        self._initialize()

    @staticmethod
    def _validate_category_caps(category_caps_usd: Mapping[str, float] | None) -> dict[str, int]:
        if category_caps_usd is None:
            return {}
        if not isinstance(category_caps_usd, Mapping):
            raise ValueError("category_caps_usd must be a mapping")
        caps: dict[str, int] = {}
        for category, cap in category_caps_usd.items():
            if not isinstance(category, str) or not category:
                raise ValueError("category cap keys must be non-empty strings")
            amount = _micros(cap)
            if amount > _micros(10.0):
                raise ValueError("category cap cannot exceed the $10 global ceiling")
            caps[category] = amount
        return caps

    @contextmanager
    def _connect(self, *, timeout: float = 30.0) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        # Keep SQLite's busy timeout aligned with the connection timeout. The
        # normal 30-second reservation timeout must not make a bounded startup
        # retry hang for every attempt.
        connection.execute(f"PRAGMA busy_timeout={max(0, int(timeout * 1000))}")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with _INITIALIZE_LOCK:
            for attempt in range(_INITIALIZE_ATTEMPTS):
                try:
                    self._initialize_once()
                    return
                except sqlite3.OperationalError as exc:
                    error_name = getattr(exc, "sqlite_errorname", "")
                    message = str(exc).lower()
                    is_lock_error = error_name in {"SQLITE_BUSY", "SQLITE_LOCKED", "SQLITE_BUSY_SNAPSHOT"} or "database is locked" in message or "database table is locked" in message
                    if not is_lock_error or attempt == _INITIALIZE_ATTEMPTS - 1:
                        raise
                    # Exponential backoff is bounded and keeps a second
                    # process from repeatedly colliding with the WAL switch.
                    time.sleep(min(0.05 * (2**attempt), 1.0))

    def _initialize_once(self) -> None:
        # A short timeout is intentional here. Reservation operations retain
        # the longer timeout, while initialization has its own bounded retry
        # loop above.
        with self._connect(timeout=1.0) as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS budget_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS budget_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    max_micro INTEGER NOT NULL,
                    actual_micro INTEGER,
                    status TEXT NOT NULL CHECK(status IN ('pending','dispatched','settled')),
                    category TEXT NOT NULL DEFAULT 'model',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    settled_at TEXT,
                    dispatch_token TEXT,
                    case_id TEXT
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(budget_reservations)").fetchall()}
            if "dispatch_token" not in columns:
                db.execute("ALTER TABLE budget_reservations ADD COLUMN dispatch_token TEXT")
            if "case_id" not in columns:
                db.execute("ALTER TABLE budget_reservations ADD COLUMN case_id TEXT")
            existing = db.execute("SELECT key, value FROM budget_meta").fetchall()
            keys = {row["key"] for row in existing}
            if "ceiling_micro" not in keys:
                db.execute("INSERT INTO budget_meta(key,value) VALUES('ceiling_micro',?)", (self._ceiling_micro,))
            else:
                stored_ceiling = int(next(row["value"] for row in existing if row["key"] == "ceiling_micro"))
                self._ceiling_micro = min(stored_ceiling, self._ceiling_micro, _micros(10.0))
                if stored_ceiling != self._ceiling_micro:
                    db.execute("UPDATE budget_meta SET value=? WHERE key='ceiling_micro'", (self._ceiling_micro,))
            if "automation_cap_micro" not in keys:
                db.execute("INSERT INTO budget_meta(key,value) VALUES('automation_cap_micro',?)", (self._automation_cap_micro,))
            else:
                stored_cap = int(next(row["value"] for row in existing if row["key"] == "automation_cap_micro"))
                self._automation_cap_micro = min(stored_cap, self._automation_cap_micro, _micros(2.0))
                if stored_cap != self._automation_cap_micro:
                    db.execute("UPDATE budget_meta SET value=? WHERE key='automation_cap_micro'", (self._automation_cap_micro,))
            if "automation_approved" not in keys:
                db.execute("INSERT INTO budget_meta(key,value) VALUES('automation_approved',0)")
            if "case_cap_micro" not in keys:
                db.execute("INSERT INTO budget_meta(key,value) VALUES('case_cap_micro',?)", (self._case_cap_micro,))
            else:
                stored_case_cap = int(next(row["value"] for row in existing if row["key"] == "case_cap_micro"))
                self._case_cap_micro = min(stored_case_cap, self._case_cap_micro, _micros(1.0))
                if stored_case_cap != self._case_cap_micro:
                    db.execute("UPDATE budget_meta SET value=? WHERE key='case_cap_micro'", (self._case_cap_micro,))
            # Category caps live in the same metadata table so they persist
            # independently of the constructor mapping. Existing lower caps
            # are never silently raised when a caller reopens the ledger with
            # a larger value or with no mapping at all.
            stored_category_caps = {
                str(row["key"])[len("category_cap_micro:"):]: int(row["value"])
                for row in db.execute("SELECT key, value FROM budget_meta WHERE key LIKE 'category_cap_micro:%'").fetchall()
            }
            effective_categories: dict[str, int] = {}
            for category, requested in self._category_caps_micro.items():
                key = f"category_cap_micro:{category}"
                if category not in stored_category_caps:
                    db.execute("INSERT OR IGNORE INTO budget_meta(key,value) VALUES(?,?)", (key, requested))
                    stored = int(db.execute("SELECT value FROM budget_meta WHERE key=?", (key,)).fetchone()[0])
                    effective = min(stored, requested, _micros(10.0))
                    if stored != effective:
                        db.execute("UPDATE budget_meta SET value=? WHERE key=?", (effective, key))
                    effective_categories[category] = effective
                else:
                    stored = min(stored_category_caps[category], _micros(10.0))
                    effective = min(stored, requested)
                    if stored_category_caps[category] != effective:
                        db.execute("UPDATE budget_meta SET value=? WHERE key=?", (effective, key))
                    effective_categories[category] = effective
            for category, stored in stored_category_caps.items():
                if category not in effective_categories:
                    effective_categories[category] = min(stored, _micros(10.0))
                    if stored != effective_categories[category]:
                        db.execute("UPDATE budget_meta SET value=? WHERE key=?", (effective_categories[category], f"category_cap_micro:{category}"))
            self._category_caps_micro = effective_categories

    def _assert_parent(self) -> None:
        if not self._parent_owned:
            raise PermissionError("child/cloud processes cannot mutate the parent budget ledger")

    @property
    def category_caps_usd(self) -> dict[str, float]:
        """Return the effective persisted category caps."""
        return {category: _usd(amount) for category, amount in self._category_caps_micro.items()}

    @staticmethod
    def _totals(db: sqlite3.Connection) -> tuple[int, int]:
        row = db.execute(
            "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN actual_micro ELSE 0 END),0) AS spent, "
            "COALESCE(SUM(CASE WHEN status IN ('pending','dispatched') THEN max_micro ELSE 0 END),0) AS pending "
            "FROM budget_reservations"
        ).fetchone()
        return int(row["spent"]), int(row["pending"])

    def reserve(
        self,
        max_cost_usd: float | Decimal | str,
        *,
        request_id: str | None = None,
        category: str = "model",
        case_id: str | None = None,
        approved: bool = False,
    ) -> BudgetReservation:
        """Atomically reserve a bounded call before dispatching it."""
        self._assert_parent()
        amount = _micros(max_cost_usd)
        if amount > _micros(0.50):
            raise ValueError("per-call reservation cannot exceed $0.50")
        if amount > 0 and not case_id:
            raise ValueError("paid reservations require a case_id")
        request_id = request_id or uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            duplicate = db.execute("SELECT * FROM budget_reservations WHERE request_id=?", (request_id,)).fetchone()
            if duplicate is not None:
                if (
                    int(duplicate["max_micro"]) != amount
                    or duplicate["category"] != category
                    or duplicate["case_id"] != case_id
                ):
                    db.execute("ROLLBACK")
                    raise ValueError("request_id already belongs to a different immutable reservation")
                db.execute("COMMIT")
                return BudgetReservation(duplicate["reservation_id"], duplicate["request_id"], _usd(duplicate["max_micro"]), duplicate["status"], duplicate["case_id"])
            spent, pending = self._totals(db)
            ceiling = int(db.execute("SELECT value FROM budget_meta WHERE key='ceiling_micro'").fetchone()[0])
            cap = int(db.execute("SELECT value FROM budget_meta WHERE key='automation_cap_micro'").fetchone()[0])
            automation_approved = bool(db.execute("SELECT value FROM budget_meta WHERE key='automation_approved'").fetchone()[0])
            if spent + pending + amount > ceiling:
                db.execute("ROLLBACK")
                raise BudgetExceeded("global persistent budget ceiling exceeded")
            if not approved and not automation_approved and spent + pending + amount > cap:
                db.execute("ROLLBACK")
                raise AutomationCapExceeded("automatic spend cap reached; explicit approval required")
            if case_id:
                case_row = db.execute(
                    "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN actual_micro ELSE max_micro END),0) AS committed "
                    "FROM budget_reservations WHERE case_id=? AND status IN ('pending','dispatched','settled')",
                    (case_id,),
                ).fetchone()
                case_committed = int(case_row["committed"])
                if case_committed + amount > self._case_cap_micro:
                    db.execute("ROLLBACK")
                    raise BudgetExceeded("per-case budget ceiling exceeded")
            category_cap_row = db.execute("SELECT value FROM budget_meta WHERE key=?", (f"category_cap_micro:{category}",)).fetchone()
            if category_cap_row is not None:
                category_spent_pending = db.execute(
                    "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN actual_micro ELSE max_micro END),0) AS committed "
                    "FROM budget_reservations WHERE category=? AND status IN ('pending','dispatched','settled')",
                    (category,),
                ).fetchone()
                if int(category_spent_pending["committed"]) + amount > int(category_cap_row["value"]):
                    db.execute("ROLLBACK")
                    raise BudgetExceeded(f"category budget ceiling exceeded: {category}")
            reservation_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO budget_reservations(reservation_id,request_id,max_micro,status,category,case_id) VALUES(?,?,?,'pending',?,?)",
                (reservation_id, request_id, amount, category, case_id),
            )
            db.execute("COMMIT")
            return BudgetReservation(reservation_id, request_id, _usd(amount), "pending", case_id)

    def claim(self, reservation_id: str, dispatch_token: str) -> BudgetReservation:
        """Atomically claim a reservation exactly once before network dispatch."""
        self._assert_parent()
        if not dispatch_token:
            raise ValueError("dispatch_token is required")
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM budget_reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise KeyError(reservation_id)
            if row["status"] != "pending":
                db.execute("ROLLBACK")
                raise RuntimeError("reservation already dispatched or settled")
            db.execute("UPDATE budget_reservations SET status='dispatched', dispatch_token=? WHERE reservation_id=?", (dispatch_token, reservation_id))
            db.execute("COMMIT")
            return BudgetReservation(row["reservation_id"], row["request_id"], _usd(row["max_micro"]), "dispatched", row["case_id"])

    def approve_automation(self, approved: bool = True) -> None:
        self._assert_parent()
        with self._lock, self._connect() as db:
            db.execute("UPDATE budget_meta SET value=? WHERE key='automation_approved'", (1 if approved else 0,))

    def reconcile(
        self,
        reservation_id: str,
        actual_cost_usd: float | Decimal | str | None,
        *,
        usage_available: bool = True,
        dispatch_token: str | None = None,
    ) -> BudgetReservation:
        """Settle known usage; leave unknown/timeout exposure pending."""
        self._assert_parent()
        if actual_cost_usd is None or not usage_available:
            row = self._lookup(reservation_id)
            return row
        actual = _micros(actual_cost_usd)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM budget_reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise KeyError(reservation_id)
            if dispatch_token is not None and row["dispatch_token"] != dispatch_token:
                db.execute("ROLLBACK")
                raise PermissionError("receipt does not match the dispatch claim")
            if row["status"] == "settled":
                # Idempotent receipt settlement: never double-charge.
                db.execute("COMMIT")
                return BudgetReservation(row["reservation_id"], row["request_id"], _usd(row["max_micro"]), row["status"], row["case_id"])
            db.execute(
                "UPDATE budget_reservations SET actual_micro=?, status='settled', settled_at=CURRENT_TIMESTAMP WHERE reservation_id=?",
                (actual, reservation_id),
            )
            spent, pending = self._totals(db)
            ceiling = int(db.execute("SELECT value FROM budget_meta WHERE key='ceiling_micro'").fetchone()[0])
            category_cap_row = db.execute("SELECT value FROM budget_meta WHERE key=?", (f"category_cap_micro:{row['category']}",)).fetchone()
            category_committed = None
            if category_cap_row is not None:
                category_committed = int(db.execute(
                    "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN actual_micro ELSE max_micro END),0) AS committed "
                    "FROM budget_reservations WHERE category=? AND status IN ('pending','dispatched','settled')",
                    (row["category"],),
                ).fetchone()["committed"])
            db.execute("COMMIT")
            result = BudgetReservation(row["reservation_id"], row["request_id"], _usd(row["max_micro"]), "settled", row["case_id"])
            if spent + pending > ceiling or actual > _micros(0.50) or (category_cap_row is not None and category_committed is not None and category_committed > int(category_cap_row["value"])):
                raise BudgetExceeded("actual provider charge exceeded global persistent ceiling")
            return result

    def _lookup(self, reservation_id: str) -> BudgetReservation:
        with self._connect() as db:
            row = db.execute("SELECT * FROM budget_reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
        if row is None:
            raise KeyError(reservation_id)
        return BudgetReservation(row["reservation_id"], row["request_id"], _usd(row["max_micro"]), row["status"], row["case_id"])

    def snapshot(self) -> BudgetSnapshot:
        with self._connect() as db:
            spent, pending = self._totals(db)
            ceiling = int(db.execute("SELECT value FROM budget_meta WHERE key='ceiling_micro'").fetchone()[0])
            cap = int(db.execute("SELECT value FROM budget_meta WHERE key='automation_cap_micro'").fetchone()[0])
            approved = bool(db.execute("SELECT value FROM budget_meta WHERE key='automation_approved'").fetchone()[0])
        return BudgetSnapshot(_usd(ceiling), _usd(cap), _usd(spent), _usd(pending), approved)

    def pending_reservations(self) -> tuple[BudgetReservation, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM budget_reservations WHERE status IN ('pending','dispatched') ORDER BY created_at").fetchall()
        return tuple(BudgetReservation(row["reservation_id"], row["request_id"], _usd(row["max_micro"]), row["status"], row["case_id"]) for row in rows)


def conservative_cost_usd(prompt_tokens: int, output_tokens: int, *, prompt_per_million: float, completion_per_million: float) -> float:
    """Return a ceiling using uncached, non-discounted provider prices."""
    if prompt_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must be non-negative")
    if not math.isfinite(prompt_per_million) or not math.isfinite(completion_per_million) or prompt_per_million < 0 or completion_per_million < 0:
        raise ValueError("prices must be finite and non-negative")
    return prompt_tokens * prompt_per_million / 1_000_000 + output_tokens * completion_per_million / 1_000_000
