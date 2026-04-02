"""Entry point for the canonical policy_fsm_v3 bot."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cambc import Controller

from bots.policy_fsm_v3.policy.policy_fsm_v3 import PolicyFSMV3Solution
from bots.policy_fsm_v3.runtime.executor import execute_plan
from bots.policy_fsm_v3.runtime.sense import sense_turn


class Player:
    """Battlecode entrypoint bound to the canonical v3 policy."""

    def __init__(self):
        self.solution = PolicyFSMV3Solution()

    def run(self, controller: Controller) -> None:
        context = sense_turn(controller)
        plan = self.solution.decide(context)
        execute_plan(controller, context, plan)
