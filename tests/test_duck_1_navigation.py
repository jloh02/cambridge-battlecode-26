from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


DUCK_1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "duck-1"
if str(DUCK_1_ROOT) not in sys.path:
    sys.path.insert(0, str(DUCK_1_ROOT))

import navigation  # noqa: E402
from states import ActionType, BuilderMode  # noqa: E402


class _StubLogger:
    def log(self, _message: str) -> None:
        return

    def print(self, _message: str) -> None:
        return


class _StubController:
    def __init__(
        self,
        *,
        position: Position,
        movable_directions: set[Direction] | None = None,
        width: int = 8,
        height: int = 8,
        current_round: int = 20,
    ) -> None:
        self._position = position
        self._movable_directions = movable_directions or set()
        self._width = width
        self._height = height
        self._current_round = current_round
        self.moved: list[Direction] = []

    def get_position(self) -> Position:
        return self._position

    def can_move(self, direction: Direction) -> bool:
        return direction in self._movable_directions

    def move(self, direction: Direction) -> None:
        self.moved.append(direction)
        self._position = self._position.add(direction)

    def get_team(self):
        return 1

    def get_current_round(self) -> int:
        return self._current_round

    def get_id(self) -> int:
        return 7

    def get_map_width(self) -> int:
        return self._width

    def get_map_height(self) -> int:
        return self._height

    def draw_indicator_line(self, *_args, **_kwargs) -> None:
        return


def _assault_bot(grid: dict[tuple[int, int], dict]):
    return SimpleNamespace(
        builder_mode=BuilderMode.ASSAULTING,
        grid=grid,
        logger=_StubLogger(),
        pathfinding_state={
            "path": [],
            "known_obstacles": set(),
            "temporary_obstacles": {},
            "current_target": None,
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
        },
        assault_nav_state={
            "current_target": None,
            "bfs_path": [],
            "bugging": False,
            "bug_target": None,
            "bug_line_start": None,
            "bug_mline": set(),
            "bug_hit_distance_sq": None,
            "bug_side": 1,
            "bug_last_move_dir": None,
            "bug_steps": 0,
            "bug_seen_states": set(),
            "bug_flipped": False,
        },
        stats={},
    )


def _path_positions(start: Position, path):
    current = start
    out = []
    for _action_type, direction in path:
        current = current.add(direction)
        out.append((current.x, current.y))
    return out


def test_assault_bfs_routes_around_static_wall():
    bot = _assault_bot(
        {
            (2, 1): {"env": Environment.WALL},
            (2, 2): {"env": Environment.WALL},
            (2, 3): {"env": Environment.WALL},
        }
    )
    controller = _StubController(position=Position(0, 2))

    path = navigation.calculate_assault_bfs_path(
        bot,
        controller,
        Position(0, 2),
        Position(4, 2),
    )

    assert path
    assert path[0][1] in {Direction.NORTHEAST, Direction.SOUTHEAST}
    assert (2, 2) not in _path_positions(Position(0, 2), path)


def test_assault_move_towards_switches_to_bug_when_first_step_blocked_live():
    bot = _assault_bot({})
    controller = _StubController(
        position=Position(1, 1),
        movable_directions={Direction.NORTH},
        width=6,
        height=6,
    )

    moved = navigation.assault_move_towards(bot, controller, Position(3, 1))

    assert moved is True
    assert controller.moved == [Direction.NORTH]
    assert bot.assault_nav_state["bugging"] is True


def test_assault_bfs_treats_friendly_builder_body_as_blocking():
    bot = _assault_bot(
        {
            (1, 1): {
                "entity": EntityType.BUILDER_BOT,
                "entity_team": 1,
            }
        }
    )
    controller = _StubController(position=Position(0, 1))

    path = navigation.calculate_assault_bfs_path(
        bot,
        controller,
        Position(0, 1),
        Position(2, 1),
    )

    assert path
    assert path[0][1] != Direction.EAST


def test_assault_bfs_allows_enemy_builder_on_target_when_flag_enabled():
    bot = _assault_bot(
        {
            (2, 1): {
                "entity": EntityType.BUILDER_BOT,
                "entity_team": 2,
                "env": Environment.EMPTY,
            }
        }
    )
    controller = _StubController(position=Position(0, 1))

    blocked_path = navigation.calculate_assault_bfs_path(
        bot,
        controller,
        Position(0, 1),
        Position(2, 1),
        allow_enemy_builder_at_target=False,
    )
    allowed_path = navigation.calculate_assault_bfs_path(
        bot,
        controller,
        Position(0, 1),
        Position(2, 1),
        allow_enemy_builder_at_target=True,
    )

    assert blocked_path == []
    assert allowed_path
    assert _path_positions(Position(0, 1), allowed_path)[-1] == (2, 1)


def test_try_pathfinding_move_marks_friendly_builder_as_temporary_obstacle(monkeypatch):
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
    bot = _assault_bot(
        {
            (1, 0): {
                "entity": EntityType.BUILDER_BOT,
                "entity_team": 1,
                "id": 6,
            }
        }
    )
    controller = _StubController(position=Position(0, 0))

    moved, _ = navigation.try_pathfinding_move(bot, controller, Position(2, 0))

    assert moved is False
    assert bot.pathfinding_state["temporary_obstacles"] == {(1, 0): 23}


def test_try_pathfinding_move_enemy_builder_blocking_target_respects_flag(monkeypatch):
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
    base_grid = {
        (1, 0): {
            "entity": EntityType.BUILDER_BOT,
            "entity_team": 2,
        }
    }

    blocked_bot = _assault_bot(dict(base_grid))
    allowed_bot = _assault_bot(dict(base_grid))
    blocked_controller = _StubController(position=Position(0, 0))
    allowed_controller = _StubController(position=Position(0, 0))

    blocked_moved, _ = navigation.try_pathfinding_move(
        blocked_bot,
        blocked_controller,
        Position(2, 0),
        allow_enemy_builder_at_target=False,
    )
    allowed_moved, _ = navigation.try_pathfinding_move(
        allowed_bot,
        allowed_controller,
        Position(1, 0),
        allow_enemy_builder_at_target=True,
    )

    assert blocked_moved is False
    assert allowed_moved is False
    assert blocked_bot.pathfinding_state["temporary_obstacles"] == {(1, 0): 23}
    assert allowed_bot.pathfinding_state["temporary_obstacles"] == {}
