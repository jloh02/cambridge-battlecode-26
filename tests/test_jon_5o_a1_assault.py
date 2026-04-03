from __future__ import annotations

import sys
from pathlib import Path

from cambc import Direction, EntityType, Environment, Position


JON_5O_A1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-5o-a1"
if str(JON_5O_A1_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_A1_ROOT))

from assault import (
    VisibleEnemy,
    build_predicted_enemy_harvesters,
    can_feed_sentinel,
    choose_alternate_harvester_anchor,
    choose_best_assault_site,
    choose_best_site_for_harvester,
    classify_ring_site,
    classify_visible_ring_state,
    connected_enemy_logistics_cluster,
    evaluate_symmetry_modes,
    prune_confirmed_enemy_harvesters,
)


def _enemy(x: int, y: int, entity_type: EntityType, direction: Direction | None = None) -> VisibleEnemy:
    return VisibleEnemy(position=Position(x, y), entity_type=entity_type, direction=direction)


def _empty_grid(*positions: Position) -> dict[tuple[int, int], dict]:
    return {
        (position.x, position.y): {"env": Environment.EMPTY, "last_seen": 50}
        for position in positions
    }


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
    site = choose_best_assault_site(
        current_position=Position(8, 10),
        enemies=[harvester],
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


def test_three_side_ring_is_accepted_when_fourth_side_is_blocked():
    harvester = Position(10, 10)
    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
    )
    grid[(9, 10)]["env"] = Environment.WALL
    enemies = [
        _enemy(10, 10, EntityType.HARVESTER),
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(12, 10, EntityType.CONVEYOR, Direction.EAST),
    ]
    site = choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(7, 10),
        enemies=enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        actor_id=7,
    )
    assert site is not None
    assert site.usable_sides == 3


def test_unseen_ring_tiles_do_not_count_as_usable_in_predictions():
    anchor = Position(16, 15)
    grid = _empty_grid(
        Position(16, 14),
        Position(16, 16),
    )
    grid[(16, 16)]["building"] = EntityType.CONVEYOR
    grid[(16, 16)]["building_team"] = 2

    predicted = build_predicted_enemy_harvesters(
        current_position=Position(3, 3),
        grid=grid,
        map_width=20,
        map_height=20,
        my_team=1,
        surviving_modes=("ROT180",),
        best_mode="ROT180",
        enemy_core_anchor=Position(18, 18),
        connected_friendly_harvesters=set(),
        remembered_ores=set(),
        confirmed_enemy_harvesters={anchor},
    )
    assert predicted
    assert predicted[0].position == anchor
    assert predicted[0].usable_sides == 2
    assert predicted[0].unseen_sides == 2


def test_mirrored_friendly_harvesters_rank_above_mirrored_ore():
    mirrored_harvester = Position(16, 15)
    mirrored_ore = Position(13, 15)
    grid = _empty_grid(
        Position(16, 14),
        Position(16, 16),
        Position(13, 14),
        Position(13, 16),
    )
    predicted = build_predicted_enemy_harvesters(
        current_position=Position(4, 4),
        grid=grid,
        map_width=20,
        map_height=20,
        my_team=1,
        surviving_modes=("ROT180",),
        best_mode="ROT180",
        enemy_core_anchor=Position(18, 18),
        connected_friendly_harvesters={Position(3, 4)},
        remembered_ores={Position(6, 4)},
        confirmed_enemy_harvesters=set(),
    )
    assert predicted
    assert predicted[0].position == mirrored_harvester
    assert predicted[0].source == "MIRRORED_FRIENDLY_HARVESTER"
    assert predicted[-1].position == mirrored_ore


def test_symmetry_solver_prefers_terrain_supported_mode():
    grid = {
        (1, 1): {"env": Environment.EMPTY, "last_seen": 20},
        (8, 1): {"env": Environment.EMPTY, "last_seen": 20},
        (2, 3): {"env": Environment.WALL, "last_seen": 25},
        (7, 3): {"env": Environment.WALL, "last_seen": 25},
        (2, 5): {"env": Environment.ORE_TITANIUM, "last_seen": 25},
        (7, 5): {"env": Environment.ORE_TITANIUM, "last_seen": 25},
        (2, 6): {"env": Environment.EMPTY, "last_seen": 25},
        (7, 6): {"env": Environment.EMPTY, "last_seen": 25},
        (2, 1): {"env": Environment.WALL, "last_seen": 25},
        (7, 1): {"env": Environment.EMPTY, "last_seen": 25},
    }
    surviving, best_mode, confidence, _ = evaluate_symmetry_modes(
        grid=grid,
        map_width=10,
        map_height=8,
        core_pos=Position(1, 1),
    )
    assert "MIRROR_X" in surviving
    assert best_mode == "MIRROR_X"
    assert confidence in {"LOW", "MEDIUM", "HIGH"}


def test_classify_ring_site_marks_unknown_tiles_as_unseen():
    assert (
        classify_ring_site(
            grid={},
            ring_position=Position(5, 5),
            map_width=20,
            map_height=20,
            my_team=1,
        )
        == "UNSEEN"
    )


def test_classify_visible_ring_state_distinguishes_built_and_occupied():
    built_grid = {
        (5, 5): {
            "env": Environment.EMPTY,
            "last_seen": 10,
            "building": EntityType.SENTINEL,
            "building_team": 1,
        }
    }
    assert (
        classify_visible_ring_state(
            grid=built_grid,
            ring_position=Position(5, 5),
            map_width=20,
            map_height=20,
            my_team=1,
        )
        == "BUILT"
    )

    occupied_grid = {
        (5, 5): {
            "env": Environment.EMPTY,
            "last_seen": 10,
            "entity": EntityType.BUILDER_BOT,
            "id": 99,
        }
    }
    assert (
        classify_visible_ring_state(
            grid=occupied_grid,
            ring_position=Position(5, 5),
            map_width=20,
            map_height=20,
            my_team=1,
            actor_id=7,
        )
        == "OCCUPIED"
    )


def test_adjacent_friendly_builder_does_not_suppress_best_site():
    harvester = Position(10, 10)
    baseline_grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
    )
    baseline_site = choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(8, 10),
        enemies=[
            _enemy(10, 10, EntityType.HARVESTER),
            _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
            _enemy(12, 10, EntityType.CONVEYOR, Direction.EAST),
        ],
        map_width=30,
        map_height=30,
        grid=baseline_grid,
        my_team=1,
        actor_id=7,
    )

    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
        Position(9, 9),
    )
    grid[(9, 9)]["entity"] = EntityType.BUILDER_BOT
    grid[(9, 9)]["id"] = 21
    grid[(9, 9)]["entity_team"] = 1
    enemies = [
        _enemy(10, 10, EntityType.HARVESTER),
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(12, 10, EntityType.CONVEYOR, Direction.EAST),
    ]
    site = choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(8, 10),
        enemies=enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        actor_id=7,
    )
    assert site is not None
    assert baseline_site is not None
    assert site.ring_position == baseline_site.ring_position


def test_prune_confirmed_enemy_harvesters_drops_visible_missing_harvester():
    pruned = prune_confirmed_enemy_harvesters(
        confirmed_enemy_harvesters={
            (10, 10): 90,
            (14, 14): 90,
        },
        current_round=100,
        visible_positions={
            (10, 10),
            (12, 12),
        },
        enemies=[
            _enemy(14, 14, EntityType.HARVESTER),
            _enemy(12, 12, EntityType.CONVEYOR, Direction.EAST),
        ],
    )
    assert (10, 10) not in pruned
    assert (14, 14) in pruned


def test_choose_alternate_harvester_anchor_prefers_visible_then_predicted():
    current_anchor = Position(10, 10)
    predicted = build_predicted_enemy_harvesters(
        current_position=Position(4, 4),
        grid=_empty_grid(
            Position(16, 14),
            Position(16, 16),
            Position(13, 14),
            Position(13, 16),
        ),
        map_width=20,
        map_height=20,
        my_team=1,
        surviving_modes=("ROT180",),
        best_mode="ROT180",
        enemy_core_anchor=Position(18, 18),
        connected_friendly_harvesters={Position(3, 4)},
        remembered_ores={Position(6, 4)},
        confirmed_enemy_harvesters=set(),
    )

    visible_choice = choose_alternate_harvester_anchor(
        current_position=Position(8, 8),
        current_anchor=current_anchor,
        enemies=[
            _enemy(10, 10, EntityType.HARVESTER),
            _enemy(15, 12, EntityType.HARVESTER),
        ],
        predicted_enemy_harvesters=predicted,
    )
    assert visible_choice == Position(15, 12)

    predicted_choice = choose_alternate_harvester_anchor(
        current_position=Position(8, 8),
        current_anchor=current_anchor,
        enemies=[_enemy(10, 10, EntityType.HARVESTER)],
        predicted_enemy_harvesters=predicted,
    )
    assert predicted_choice is not None
    assert predicted_choice != current_anchor
