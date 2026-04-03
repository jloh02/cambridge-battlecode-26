from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Position


JON_5O_A1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-5o-a1"
if str(JON_5O_A1_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_A1_ROOT))

import navigation
from states import ActionType, BuilderMode


class _StubLogger:
    def log(self, _message: str) -> None:
        return


class _StubController:
    def __init__(self) -> None:
        self._position = Position(0, 0)

    def get_position(self) -> Position:
        return self._position

    def can_move(self, _direction) -> bool:
        return False

    def get_team(self):
        return 1

    def get_current_round(self) -> int:
        return 12

    def get_id(self) -> int:
        return 7


def _assault_bot_with_grid(grid: dict[tuple[int, int], dict]):
    return SimpleNamespace(
        builder_mode=BuilderMode.ASSAULTING,
        grid=grid,
        logger=_StubLogger(),
        pathfinding_state={
            "path": [],
            "known_obstacles": set(),
            "temporary_obstacles": {},
        },
    )


def test_enemy_builder_block_adds_temporary_obstacle_when_not_on_objective(monkeypatch):
    monkeypatch.setattr(
        navigation,
        "compute_pathfinding_step",
        lambda *args, **kwargs: (
            (ActionType.CONVEYOR, Direction.EAST),
            {
                "path": [(ActionType.CONVEYOR, Direction.EAST)],
                "known_obstacles": set(),
                "temporary_obstacles": {},
            },
        ),
    )
    bot = _assault_bot_with_grid(
        {
            (1, 0): {
                "entity": EntityType.BUILDER_BOT,
                "entity_team": 2,
            }
        }
    )
    controller = _StubController()

    moved, _ = navigation.try_pathfinding_move(
        bot,
        controller,
        Position(2, 0),
        allow_enemy_builder_at_target=False,
    )

    assert moved is False
    assert bot.pathfinding_state["temporary_obstacles"] == {(1, 0): 15}


def test_enemy_builder_on_objective_tile_does_not_add_temporary_obstacle(monkeypatch):
    monkeypatch.setattr(
        navigation,
        "compute_pathfinding_step",
        lambda *args, **kwargs: (
            (ActionType.CONVEYOR, Direction.EAST),
            {
                "path": [(ActionType.CONVEYOR, Direction.EAST)],
                "known_obstacles": set(),
                "temporary_obstacles": {},
            },
        ),
    )
    bot = _assault_bot_with_grid(
        {
            (1, 0): {
                "entity": EntityType.BUILDER_BOT,
                "entity_team": 2,
            }
        }
    )
    controller = _StubController()

    moved, _ = navigation.try_pathfinding_move(
        bot,
        controller,
        Position(1, 0),
        allow_enemy_builder_at_target=True,
    )

    assert moved is False
    assert bot.pathfinding_state["temporary_obstacles"] == {}
