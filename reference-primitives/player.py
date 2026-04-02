"""Generic bot entrypoint wiring.

Each game unit gets its own Player instance from the engine, which means each
solution object is already private per unit. The only shared state lives in
markers on the map.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from cambc import Controller

from .executor import execute_plan
from .sense import TurnContext, sense_turn


class SolutionProtocol(Protocol):
    """Small runtime protocol every solution class implements."""

    def decide(self, context: TurnContext):
        ...


SolutionType = TypeVar("SolutionType", bound=SolutionProtocol)


def make_player(solution_class: type[SolutionType]):
    """Return a battlecode-compatible Player class bound to a solution class."""

    class Player:
        def __init__(self):
            self.solution = solution_class()

        def run(self, controller: Controller) -> None:
            context = sense_turn(controller)
            plan = self.solution.decide(context)
            execute_plan(controller, context, plan)

    return Player
