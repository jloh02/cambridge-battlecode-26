"""Turn planning primitives shared by all solutions.

This module keeps the planner/executor contract intentionally small:

- solutions read a sensed TurnContext
- solutions return a TurnPlan
- the executor is the only code that touches the Controller mutating API

The separation makes strategy code easier to test because most tests can ignore
the actual game engine and reason about plans as plain data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cambc import Direction, Position


class BuildKind(str, Enum):
    """Supported builder/core construction actions.

    The enum deliberately uses string values so debug output and reports stay
    readable without extra formatting layers.
    """

    BUILDER_BOT = "builder_bot"
    CONVEYOR = "conveyor"
    SPLITTER = "splitter"
    ARMOURED_CONVEYOR = "armoured_conveyor"
    BRIDGE = "bridge"
    HARVESTER = "harvester"
    ROAD = "road"
    BARRIER = "barrier"
    FOUNDRY = "foundry"
    GUNNER = "gunner"
    SENTINEL = "sentinel"
    BREACH = "breach"
    LAUNCHER = "launcher"


@dataclass(slots=True)
class MarkerDecision:
    """Free one-per-round marker write."""

    position: Position
    value: int


@dataclass(slots=True)
class BuildDecision:
    """Construct a building or spawn a builder bot.

    `replace_existing` is the ergonomic escape hatch that lets solutions say
    "convert this road into a conveyor" without manually spelling out the
    destroy/build sequence. The executor handles the safe legal checks.
    """

    kind: BuildKind
    position: Position
    direction: Direction | None = None
    target: Position | None = None
    replace_existing: bool = False


@dataclass(slots=True)
class MoveDecision:
    """Single builder-bot movement."""

    direction: Direction


@dataclass(slots=True)
class FireDecision:
    """Turret fire or builder own-tile attack."""

    target: Position


@dataclass(slots=True)
class RotateDecision:
    """Gunner rotation to a new facing direction."""

    direction: Direction


@dataclass(slots=True)
class HealDecision:
    """Builder heal action on its own tile."""

    position: Position


@dataclass(slots=True)
class DestroyDecision:
    """Destroy an allied building, usually to reconfigure logistics."""

    position: Position


@dataclass(slots=True)
class LaunchDecision:
    """Launcher action for completeness, even though MVP solutions do not use it."""

    bot_position: Position
    target: Position


@dataclass(slots=True)
class ConvertDecision:
    """Core conversion of refined axionite into titanium."""

    amount: int


@dataclass(slots=True)
class IndicatorLineDecision:
    """Debug overlay line saved into the replay."""

    pos_a: Position
    pos_b: Position
    r: int
    g: int
    b: int


@dataclass(slots=True)
class IndicatorDotDecision:
    """Debug overlay dot saved into the replay."""

    pos: Position
    r: int
    g: int
    b: int


ActionDecision = (
    BuildDecision
    | FireDecision
    | RotateDecision
    | HealDecision
    | DestroyDecision
    | LaunchDecision
    | ConvertDecision
)


@dataclass(slots=True)
class TurnPlan:
    """Full desired turn for one unit.

    A Battlecode turn has multiple channels: marker write, one action, one move,
    and any number of debug indicators. The plan mirrors that instead of forcing
    every solution into a single opaque command.
    """

    marker: MarkerDecision | None = None
    action: ActionDecision | None = None
    move: MoveDecision | None = None
    indicator_lines: list[IndicatorLineDecision] = field(default_factory=list)
    indicator_dots: list[IndicatorDotDecision] = field(default_factory=list)
    note: str = ""
