from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


JON_6_A7_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a7bfs"
)
for module_name in ("navigation", "states", "utils"):
    sys.modules.pop(module_name, None)
if str(JON_6_A7_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A7_BFS_ROOT))
importlib.invalidate_caches()

import navigation  # noqa: E402
from states import BuilderMode  # noqa: E402


class _StubLogger:
    def log(self, _msg): pass
    def print(self, _msg): pass


class _StubController:
    def __init__(self, *, position, movable_directions=None, width=10, height=10):
        self._position = position
        self._movable_directions = movable_directions or set()
        self._width = width
        self._height = height
        self.moved: list[Direction] = []

    def get_position(self): return self._position
    def can_move(self, d): return d in self._movable_directions
    def move(self, d):
        self.moved.append(d)
        self._position = self._position.add(d)
    def get_team(self): return 1
    def get_current_round(self): return 20
    def get_id(self): return 7
    def get_map_width(self): return self._width
    def get_map_height(self): return self._height
    def get_tile_building_id(self, _pos): return None
    def can_build_road(self, _pos): return False
    def build_road(self, _pos): pass
    def draw_indicator_line(self, *_a, **_kw): pass


def _assault_bot(grid):
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
            "frontier_target": None,
        },
        stats={},
    )


def _path_positions(start, path):
    current = start
    out = []
    for _action_type, direction in path:
        current = current.add(direction)
        out.append((current.x, current.y))
    return out


def test_assault_bfs_routes_around_static_wall():
    bot = _assault_bot({
        (2, 1): {"env": Environment.WALL},
        (2, 2): {"env": Environment.WALL},
        (2, 3): {"env": Environment.WALL},
    })
    controller = _StubController(position=Position(0, 2))

    path = navigation.calculate_assault_bfs_path(
        bot, controller, Position(0, 2), Position(4, 2),
    )

    assert path
    assert path[0][1] in {Direction.NORTHEAST, Direction.SOUTHEAST}
    assert (2, 2) not in _path_positions(Position(0, 2), path)


def test_assault_bfs_finds_direct_path_in_open_space():
    bot = _assault_bot({})
    controller = _StubController(position=Position(0, 0))

    path = navigation.calculate_assault_bfs_path(
        bot, controller, Position(0, 0), Position(3, 0),
    )

    assert path
    positions = _path_positions(Position(0, 0), path)
    assert (3, 0) in positions
    assert len(path) == 3  # shortest path: 3 steps east


def test_assault_bfs_path_does_not_revisit_start():
    bot = _assault_bot({})
    controller = _StubController(position=Position(2, 2))

    path = navigation.calculate_assault_bfs_path(
        bot, controller, Position(2, 2), Position(5, 2),
    )

    assert path
    positions = _path_positions(Position(2, 2), path)
    assert (2, 2) not in positions  # start not revisited
    assert (5, 2) in positions


def test_assault_move_reuses_cached_bfs_path(monkeypatch):
    bot = _assault_bot({})
    controller = _StubController(
        position=Position(0, 0),
        movable_directions={Direction.EAST},
    )
    target = Position(3, 0)
    calls = 0
    original = navigation._calculate_assault_bfs_result

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(navigation, "_calculate_assault_bfs_result", wrapped)

    assert navigation.assault_move_towards(bot, controller, target, build_road=False)
    assert navigation.assault_move_towards(bot, controller, target, build_road=False)

    assert calls == 1
    assert controller.moved == [Direction.EAST, Direction.EAST]
    assert len(bot.assault_nav_state["bfs_path"]) == 1


def test_assault_move_replans_when_target_changes(monkeypatch):
    bot = _assault_bot({})
    controller = _StubController(
        position=Position(0, 0),
        movable_directions={Direction.EAST, Direction.SOUTHEAST, Direction.SOUTH},
    )
    calls = 0
    original = navigation._calculate_assault_bfs_result

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(navigation, "_calculate_assault_bfs_result", wrapped)

    assert navigation.assault_move_towards(
        bot,
        controller,
        Position(3, 0),
        build_road=False,
    )
    assert navigation.assault_move_towards(
        bot,
        controller,
        Position(3, 2),
        build_road=False,
    )

    assert calls == 2


def test_assault_navigate_returns_frontier_blocked_and_marks_temp_obstacle():
    bot = _assault_bot({})
    controller = _StubController(
        position=Position(0, 0),
        movable_directions=set(),
    )

    moved, failure_reason = navigation.assault_navigate(
        bot,
        controller,
        Position(2, 0),
        build_road=False,
    )

    assert moved is False
    assert failure_reason == "frontier_blocked"
    assert bot.pathfinding_state["temporary_obstacles"][(1, 0)] == 25
    assert bot.assault_nav_state["frontier_target"] is None
