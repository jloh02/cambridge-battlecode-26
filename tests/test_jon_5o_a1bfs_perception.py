from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import EntityType, Environment, Position


JON_5O_A1_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-5o-a1bfs"
)
if str(JON_5O_A1_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_A1_BFS_ROOT))

import perception  # noqa: E402


class _StubController:
    def get_team(self, entity_id=None):
        if entity_id is None:
            return 1
        if entity_id == 99:
            return 2
        raise KeyError(entity_id)

    def get_current_round(self) -> int:
        return 40

    def get_position(self, entity_id=None):
        if entity_id is None:
            return Position(12, 12)
        if entity_id == 99:
            return Position(18, 18)
        raise KeyError(entity_id)

    def get_id(self) -> int:
        return 7

    def get_nearby_entities(self):
        return [99]

    def get_entity_type(self, entity_id):
        if entity_id == 99:
            return EntityType.CORE
        raise KeyError(entity_id)


def test_perception_keeps_single_enemy_core_target_at_center_tile():
    bot = SimpleNamespace(
        grid={
            (17, 17): {
                "env": Environment.EMPTY,
                "building": EntityType.CORE,
                "building_team": 2,
                "last_seen": 40,
            },
            (18, 17): {
                "env": Environment.EMPTY,
                "building": EntityType.CORE,
                "building_team": 2,
                "last_seen": 40,
            },
            (18, 18): {
                "env": Environment.EMPTY,
                "building": EntityType.CORE,
                "building_team": 2,
                "last_seen": 40,
            },
        },
        pathfinding_state={"known_obstacles": set()},
        visible_positions={(17, 17), (18, 17), (18, 18)},
        visible_enemy_targets=[],
        visible_enemy_passable_buildings=set(),
        visible_friendly_builders=[],
        bot_locations=set(),
        titanium_locations=set(),
        axionite_locations=set(),
        known_friendly_conveyors=set(),
        connected_friendly_conveyors={},
        last_connected_refresh_round=-1,
        last_enemy_core_position=None,
        enemy_core_anchor=None,
        enemy_core_exact=False,
        confirmed_enemy_harvesters={},
        harvester_anchor=None,
        harvester_anchor_last_seen_round=-9999,
    )

    perception._infer_state_from_grid(  # noqa: SLF001
        bot,
        _StubController(),
        nearby_units=[],
        nearby_cache={},
        refresh_connected=False,
    )

    core_targets = [
        enemy for enemy in bot.visible_enemy_targets if enemy.entity_type == EntityType.CORE
    ]
    assert len(core_targets) == 1
    assert core_targets[0].position == Position(18, 18)
    assert bot.last_enemy_core_position == Position(18, 18)
