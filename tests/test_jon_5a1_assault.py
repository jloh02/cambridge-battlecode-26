from __future__ import annotations

import sys
from pathlib import Path

from cambc import Direction, EntityType, Position

JON_5A1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-5a1"
if str(JON_5A1_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5A1_ROOT))

from assault import (
    VisibleEnemy,
    can_feed_sentinel,
    choose_best_assault_site,
    choose_best_site_for_harvester,
    connected_enemy_logistics_cluster,
)


def _enemy(x: int, y: int, entity_type: EntityType, direction: Direction | None = None) -> VisibleEnemy:
    return VisibleEnemy(position=Position(x, y), entity_type=entity_type, direction=direction)


def test_single_valid_site_is_accepted():
    harvester = _enemy(10, 10, EntityType.HARVESTER)
    enemies = [
        harvester,
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(12, 10, EntityType.CONVEYOR, Direction.EAST),
    ]
    site = choose_best_assault_site(
        current_position=Position(8, 10),
        enemies=enemies,
        map_width=30,
        map_height=30,
    )
    assert site is not None
    assert site.harvester_position == harvester.position


def test_local_logistics_beats_distant_core_only_option():
    harvester = _enemy(10, 10, EntityType.HARVESTER)
    enemies = [
        harvester,
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(12, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(18, 10, EntityType.CORE),
    ]
    site = choose_best_site_for_harvester(
        harvester_position=harvester.position,
        current_position=Position(8, 10),
        enemies=enemies,
        map_width=40,
        map_height=40,
    )
    assert site is not None
    assert site.target.entity_type == EntityType.CONVEYOR


def test_site_with_no_immediate_legal_shot_is_rejected():
    harvester = _enemy(10, 10, EntityType.HARVESTER)
    enemies = [harvester]
    site = choose_best_assault_site(
        current_position=Position(8, 10),
        enemies=enemies,
        map_width=30,
        map_height=30,
    )
    assert site is None


def test_feed_illegal_facing_is_rejected_even_if_geometry_hits():
    harvester_position = Position(10, 10)
    ring_position = Position(10, 9)
    assert not can_feed_sentinel(harvester_position, ring_position, Direction.SOUTH)
    assert can_feed_sentinel(harvester_position, ring_position, Direction.EAST)


def test_connected_logistics_cluster_excludes_unrelated_nearby_econ():
    harvester = _enemy(10, 10, EntityType.HARVESTER)
    connected = _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST)
    disconnected = _enemy(12, 12, EntityType.CONVEYOR, Direction.EAST)
    cluster = connected_enemy_logistics_cluster(harvester.position, [harvester, connected, disconnected])
    assert harvester.position in cluster
    assert connected.position in cluster
    assert disconnected.position not in cluster


def test_second_sentinel_stays_on_same_anchor_when_another_site_exists():
    harvester = _enemy(10, 10, EntityType.HARVESTER)
    enemies = [
        harvester,
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(12, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(10, 11, EntityType.CONVEYOR, Direction.SOUTH),
        _enemy(10, 12, EntityType.CONVEYOR, Direction.SOUTH),
    ]
    first_site = choose_best_site_for_harvester(
        harvester_position=harvester.position,
        current_position=Position(8, 10),
        enemies=enemies,
        map_width=40,
        map_height=40,
    )
    assert first_site is not None
    second_site = choose_best_site_for_harvester(
        harvester_position=harvester.position,
        current_position=Position(8, 10),
        enemies=enemies,
        map_width=40,
        map_height=40,
        blocked_ring_positions={first_site.ring_position},
    )
    assert second_site is not None
    assert second_site.harvester_position == harvester.position
    assert second_site.ring_position != first_site.ring_position
