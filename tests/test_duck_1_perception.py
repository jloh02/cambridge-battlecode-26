from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cambc import Direction, EntityType, Environment, Position


DUCK_1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "duck-1"
if str(DUCK_1_ROOT) not in sys.path:
    sys.path.insert(0, str(DUCK_1_ROOT))

import marker  # noqa: E402
import perception  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _cleanup_duck1_modules():
    yield
    for module_name in ("marker", "perception", "utils"):
        sys.modules.pop(module_name, None)
    while str(DUCK_1_ROOT) in sys.path:
        sys.path.remove(str(DUCK_1_ROOT))


class _GridController:
    def __init__(
        self,
        *,
        position: Position,
        current_round: int = 50,
        team: int = 1,
        width: int = 20,
        height: int = 20,
        marker_values: dict[int, int] | None = None,
    ) -> None:
        self._position = position
        self._current_round = current_round
        self._team = team
        self._width = width
        self._height = height
        self._marker_values = marker_values or {}

    def get_position(self, _entity_id=None) -> Position:
        return self._position

    def get_current_round(self) -> int:
        return self._current_round

    def get_team(self, _entity_id=None):
        return self._team

    def get_map_width(self) -> int:
        return self._width

    def get_map_height(self) -> int:
        return self._height

    def get_marker_value(self, marker_id: int) -> int:
        return self._marker_values[marker_id]


def _perception_bot() -> SimpleNamespace:
    return SimpleNamespace(
        grid={},
        pathfinding_state={"known_obstacles": set()},
        titanium_locations=set(),
        axionite_locations=set(),
        known_friendly_conveyors=set(),
        connected_friendly_conveyors={},
        explored_tiles=set(),
        explored_chunk_last_seen={},
        visible_positions=set(),
        bot_locations=set(),
        known_harvesters={},
        claimed_harvesters=set(),
        core_pos=Position(5, 2),
        last_connected_refresh_round=-1,
        claimed_explore_chunks=set(),
    )


def test_update_master_grid_classifies_visible_tiles_and_updates_chunks():
    bot = _perception_bot()
    ct = _GridController(position=Position(1, 1), current_round=40)
    bot.titanium_locations.add(Position(4, 4))

    visible_tiles = [
        (Position(0, 0), Environment.ORE_TITANIUM, None, None),
        (Position(1, 0), Environment.WALL, None, None),
        (Position(2, 0), Environment.EMPTY, 10, None),
        (Position(3, 0), Environment.EMPTY, 11, None),
        (Position(4, 4), Environment.EMPTY, None, None),
    ]
    nearby_cache = {
        10: {
            "pos": Position(2, 0),
            "type": EntityType.CONVEYOR,
            "team": 1,
            "direction": Direction.EAST,
        },
        11: {
            "pos": Position(3, 0),
            "type": EntityType.CORE,
            "team": 2,
        },
    }

    topology_dirty = perception._update_master_grid(  # noqa: SLF001
        bot,
        ct,
        visible_tiles,
        nearby_units=[],
        nearby_cache=nearby_cache,
    )

    assert topology_dirty is True
    assert Position(0, 0) in bot.titanium_locations
    assert Position(4, 4) not in bot.titanium_locations
    assert (0, 0) in bot.pathfinding_state["known_obstacles"]
    assert (1, 0) in bot.pathfinding_state["known_obstacles"]
    assert (3, 0) in bot.pathfinding_state["known_obstacles"]
    assert (2, 0) not in bot.pathfinding_state["known_obstacles"]
    assert bot.known_friendly_conveyors == {(2, 0)}
    assert (ct.get_position().x // perception.CHUNK_SIZE, ct.get_position().y // perception.CHUNK_SIZE) in bot.explored_tiles
    assert (0, 0) in bot.explored_tiles
    assert bot.explored_chunk_last_seen[(0, 0)] == 40


def test_infer_state_updates_connected_conveyors_and_prunes_stale_harvesters():
    bot = _perception_bot()
    ct = _GridController(position=Position(1, 1), current_round=60)
    bot.grid = {
        (5, 4): {
            "env": Environment.ORE_TITANIUM,
            "building": EntityType.HARVESTER,
            "building_team": 1,
        },
        (6, 6): {
            "env": Environment.ORE_TITANIUM,
            "building": EntityType.HARVESTER,
            "building_team": 2,
        },
        (5, 3): {
            "env": Environment.EMPTY,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.NORTH,
        },
    }
    bot.known_friendly_conveyors = {(5, 3)}
    bot.known_harvesters = {
        (9, 9): {"team": 1, "adjacent_conveyors": 0},
    }
    bot.claimed_harvesters = {(9, 9)}

    perception._infer_state_from_grid(  # noqa: SLF001
        bot,
        ct,
        nearby_units=[],
        nearby_cache={},
        refresh_connected=True,
        topology_dirty=False,
    )

    assert bot.connected_friendly_conveyors == {(5, 3): 1}
    assert bot.known_harvesters[(5, 4)]["team"] == 1
    assert bot.known_harvesters[(5, 4)]["adjacent_conveyors"] == 1
    assert bot.known_harvesters[(6, 6)]["team"] == 2
    assert bot.known_harvesters[(6, 6)]["adjacent_conveyors"] == 0
    assert (5, 4) in bot.claimed_harvesters
    assert (9, 9) not in bot.known_harvesters
    assert (9, 9) not in bot.claimed_harvesters


def test_scan_nearby_markers_dispatches_by_marker_type():
    current_round = 70
    marker_values = {
        1: marker.create_explore_claim_marker((2, 3), None, current_round, 6, 6),
        2: marker.create_ore_marker(Position(8, 8), current_round, 20, 20),
        3: marker.create_connected_conveyor_marker(
            Position(9, 9), current_round, 20, 20
        ),
        4: marker.create_connected_harvester_marker(
            Position(10, 10), current_round, 20, 20
        ),
    }
    ct = _GridController(
        position=Position(1, 1),
        current_round=current_round,
        marker_values=marker_values,
    )
    bot = _perception_bot()
    nearby_cache = {
        marker_id: {"type": EntityType.MARKER, "team": 1}
        for marker_id in marker_values
    }

    perception._scan_nearby_markers(  # noqa: SLF001
        bot,
        ct,
        nearby_buildings=list(marker_values),
        nearby_cache=nearby_cache,
    )

    assert (2, 3) in bot.claimed_explore_chunks
    assert Position(8, 8) in bot.titanium_locations
    assert (8, 8) in bot.pathfinding_state["known_obstacles"]
    assert (9, 9) in bot.known_friendly_conveyors
    assert bot.connected_friendly_conveyors[(9, 9)] == 0
