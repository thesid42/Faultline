from __future__ import annotations

from datetime import datetime, timezone


class FixedClock:
    """Resettable fixed clock used by every local trial."""

    def __init__(self, now: datetime | None = None) -> None:
        self.default = (now or datetime(2026, 1, 1, tzinfo=timezone.utc)).astimezone(timezone.utc)
        self.now_value = self.default

    def now(self) -> datetime:
        return self.now_value

    def reset(self, now: datetime | None = None) -> None:
        self.now_value = (now or self.default).astimezone(timezone.utc)
