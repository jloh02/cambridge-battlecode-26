from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


JON_5O_A1_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-5o-a1bfs"
)
if str(JON_5O_A1_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_A1_BFS_ROOT))

import navigation
from states import BuilderMode


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
    ) -> None:
        self._position = position
        self._movable_directions = movable_directions or set()
        self._width = width
        self._height = height
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
        return 20

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


def test_assault_move_towards_switches_to_bug2_when_bfs_step_is_blocked_live():
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


def test_assault_bfs_treats_friendly_builder_body_as_blocking_and_routes_around():
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
