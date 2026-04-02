"""Entry point for the orange_v1 assault variant."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cambc import Controller

from bots.orange_v1.policy.orange_v1 import OrangeV1Solution
from bots.policy_fsm_v3.runtime.executor import execute_plan
from bots.policy_fsm_v3.runtime.sense import sense_turn


class Player:
    """Battlecode entrypoint bound to the orange_v1 policy."""

    def __init__(self):
        self.solution = OrangeV1Solution()

    def run(self, controller: Controller) -> None:
        context = sense_turn(controller)
        plan = self.solution.decide(context)
        execute_plan(controller, context, plan)
