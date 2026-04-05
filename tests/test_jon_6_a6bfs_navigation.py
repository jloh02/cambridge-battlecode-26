from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cambc import Direction, EntityType, Environment, Position


JON_6_A6_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a6bfs"
)
for module_name in ("navigation", "states", "utils"):
    sys.modules.pop(module_name, None)
if str(JON_6_A6_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A6_BFS_ROOT))
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
        self.built_roads: list[Position] = []

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
    def can_build_road(self, _pos): return True
    def build_road(self, pos): self.built_roads.append(pos)
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
    original = navigation.calculate_assault_bfs_path

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(navigation, "calculate_assault_bfs_path", wrapped)

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
    original = navigation.calculate_assault_bfs_path

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(navigation, "calculate_assault_bfs_path", wrapped)

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


def test_move_towards_can_build_roads_for_assault_bots():
    bot = _assault_bot({})
    controller = _StubController(
        position=Position(0, 0),
        movable_directions={Direction.EAST},
    )
    new_state = bot.pathfinding_state.copy()

    with patch.object(
        navigation,
        "compute_pathfinding_step",
        return_value=((navigation.ActionType.CONVEYOR, Direction.EAST), new_state),
    ):
        moved = navigation.move_towards(
            bot,
            controller,
            Position(2, 0),
            build_road=True,
        )

    assert moved is True
    assert controller.built_roads == [Position(1, 0)]


def test_connected_harvester_uses_connected_conveyor_fast_path():
    bot = _assault_bot({
        (2, 2): {
            "env": Environment.EMPTY,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
        }
    })
    bot.connected_friendly_conveyors = {(2, 2): 1}
    bot.known_connected_harvesters = set()
    controller = _StubController(position=Position(1, 2))

    assert navigation._is_connected_to_harvester(bot, controller, Position(2, 2)) is True
