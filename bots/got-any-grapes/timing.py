from __future__ import annotations

from dataclasses import dataclass
import time


TARGET_ACTION_BUDGET_NS = 1_000_000
SOFT_DECISION_BUDGET_NS = 1_800_000
HARD_DECISION_BUDGET_NS = 1_800_000
LOW_PRIORITY_RESERVE_NS = 120_000


@dataclass(slots=True)
class TimingGovernor:
    started_ns: int
    soft_deadline_ns: int
    hard_deadline_ns: int

    @classmethod
    def start_turn(cls, started_ns: int | None = None) -> "TimingGovernor":
        if started_ns is None:
            started_ns = time.time_ns()
        return cls(
            started_ns=started_ns,
            soft_deadline_ns=started_ns + SOFT_DECISION_BUDGET_NS,
            hard_deadline_ns=started_ns + HARD_DECISION_BUDGET_NS,
        )

    def remaining_soft_ns(self, now_ns: int | None = None) -> int:
        if now_ns is None:
            now_ns = time.time_ns()
        return self.soft_deadline_ns - now_ns

    def remaining_hard_ns(self, now_ns: int | None = None) -> int:
        if now_ns is None:
            now_ns = time.time_ns()
        return self.hard_deadline_ns - now_ns

    def should_skip_low_priority(self, now_ns: int | None = None) -> bool:
        return self.remaining_soft_ns(now_ns) <= LOW_PRIORITY_RESERVE_NS

    def is_hard_expired(self, now_ns: int | None = None) -> bool:
        return self.remaining_hard_ns(now_ns) <= 0
