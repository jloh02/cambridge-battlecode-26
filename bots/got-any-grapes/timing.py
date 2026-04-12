from __future__ import annotations

from dataclasses import dataclass
import time


TARGET_ACTION_BUDGET_NS = 1_000_000
SOFT_DECISION_BUDGET_NS = 1_900_000
HARD_DECISION_BUDGET_NS = 2_000_000
LOW_PRIORITY_RESERVE_NS = 120_000

# Anytime phase budgets — minimum remaining hard budget (ns) to enter each
# phase. If remaining time is less than this, the phase is skipped to prevent
# TLE. Budgets are carved up so that perception + A* finish well under 1.5ms
# of wall time, leaving at least 0.5ms for post-A* mode actions (move,
# build, fire) and misc overhead before the 2ms hard deadline:
#
#   0.0 .. ~0.8ms   fresh snapshot SDK loop  (defers cached tiles past 0.8ms)
#   ~0.8 .. ~1.1ms  post-snapshot: grid update, markers, inference
#   ~1.1 .. ~1.5ms  A* (clamped by A_STAR_TIME_GUARD_NANOSECONDS below)
#   ~1.5 .. ~2.0ms  move / build / fire / cleanup (post-A* safety margin)
#
# These only activate under real time pressure (e.g. Graviton3); on fast
# local hardware the remaining budget is always well above these thresholds.
SNAPSHOT_RESERVE_NS = 1_200_000    # keep 1.2ms after the snapshot → snapshot
                                   # defers cached tiles past ~0.8ms elapsed
PERCEPTION_OPTIONAL_NS = 700_000   # skip markers + connected refresh past
                                   # ~1.3ms elapsed (hard budget < 700μs)
MODE_ENTRY_NS = 300_000            # kept for external callers; no longer
                                   # used to no-op the whole mode
LOOKAHEAD_BUILD_NS = 150_000       # 150μs for lookahead build in tiling
# How many tiles to process between in-snapshot time checks. The check itself
# is a single time.time_ns() call (~50ns) and an integer comparison, so
# checking every N tiles amortises it effectively.
SNAPSHOT_CHECK_INTERVAL = 16


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

    def has_budget_for(self, budget_ns: int, now_ns: int | None = None) -> bool:
        """Anytime-return helper: does the turn have at least budget_ns of hard
        budget remaining? Used by perception/mode/lookahead gates to skip
        optional work when close to the 2ms deadline. Returns True when time
        is plentiful (the normal case), so gated code runs unchanged."""
        return self.remaining_hard_ns(now_ns) >= budget_ns
