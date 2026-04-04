from __future__ import annotations

import sys
from pathlib import Path

from cambc import Direction, EntityType, Environment, Position


DUCK_1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "duck-1"
if str(DUCK_1_ROOT) not in sys.path:
    sys.path.insert(0, str(DUCK_1_ROOT))

from assault import (  # noqa: E402
    ANCHOR_GOOD_ENOUGH,
    ANCHOR_SATURATED,
    PredictedHarvester,
    VisibleEnemy,
    assess_anchor,
    choose_best_site_for_harvester,
    choose_predicted_scout_anchor,
)


def _enemy(
    x: int,
    y: int,
    entity_type: EntityType,
    direction: Direction | None = None,
) -> VisibleEnemy:
    return VisibleEnemy(position=Position(x, y), entity_type=entity_type, direction=direction)


def _empty_grid(*positions: Position) -> dict[tuple[int, int], dict]:
    return {
        (position.x, position.y): {"env": Environment.EMPTY, "last_seen": 50}
        for position in positions
    }


def test_outer_core_tile_does_not_count_as_center_core_target():
    harvester = Position(16, 13)
    enemies = [
        _enemy(16, 13, EntityType.HARVESTER),
        _enemy(17, 17, EntityType.CORE),
    ]
    grid = _empty_grid(
        Position(16, 12),
        Position(17, 13),
        Position(16, 14),
        Position(15, 13),
    )

    site = choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(16, 15),
        enemies=enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        actor_id=7,
        enemy_core_center=Position(18, 18),
        allow_exploratory_fallback=False,
    )

    assert site is None


def test_center_hitting_direction_beats_same_tile_logistics_when_core_preferred():
    harvester = Position(16, 13)
    enemies = [
        _enemy(16, 13, EntityType.HARVESTER),
        _enemy(17, 13, EntityType.CONVEYOR, Direction.EAST),
        _enemy(18, 18, EntityType.CORE),
    ]
    grid = _empty_grid(
        Position(16, 12),
        Position(17, 13),
        Position(16, 14),
        Position(15, 13),
    )
    grid[(16, 12)]["env"] = Environment.WALL
    grid[(17, 13)]["env"] = Environment.WALL
    grid[(15, 13)]["env"] = Environment.WALL

    site = choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(16, 15),
        enemies=enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        actor_id=7,
        enemy_core_center=Position(18, 18),
        connected_friendly_conveyors={(16, 12): {"round": 10}},
    )

    assert site is not None
    assert site.ring_position == Position(16, 14)
    assert site.sentinel_direction == Direction.SOUTHEAST
    assert site.hits_core_center is True


def test_anchor_assessment_reports_good_enough_low_gain_anchor():
    harvester = Position(10, 10)
    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
    )
    grid[(10, 9)]["building"] = EntityType.SENTINEL
    grid[(10, 9)]["building_team"] = 1
    grid[(11, 10)]["building"] = EntityType.CONVEYOR
    grid[(11, 10)]["building_team"] = 2
    grid[(10, 11)]["env"] = Environment.WALL
    grid[(9, 10)]["env"] = Environment.WALL

    assessment = assess_anchor(
        harvester_position=harvester,
        current_position=Position(10, 12),
        enemies=[
            _enemy(10, 10, EntityType.HARVESTER),
            _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
            _enemy(12, 10, EntityType.CONVEYOR, Direction.EAST),
        ],
        grid=grid,
        my_team=1,
        actor_id=7,
        map_width=30,
        map_height=30,
    )

    assert assessment.status == ANCHOR_GOOD_ENOUGH
    assert assessment.best_logistics_gain == 1


def test_anchor_assessment_reports_saturated_when_three_sides_resolved():
    harvester = Position(10, 10)
    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
    )
    grid[(10, 9)]["building"] = EntityType.SENTINEL
    grid[(10, 9)]["building_team"] = 1
    grid[(11, 10)]["env"] = Environment.WALL
    grid[(9, 10)]["env"] = Environment.WALL

    assessment = assess_anchor(
        harvester_position=harvester,
        current_position=Position(10, 12),
        enemies=[_enemy(10, 10, EntityType.HARVESTER)],
        grid=grid,
        my_team=1,
        actor_id=7,
        map_width=30,
        map_height=30,
        enemy_core_center=None,
    )

    assert assessment.status == ANCHOR_SATURATED
    assert assessment.resolved_ring_sides >= 3


def test_choose_predicted_scout_anchor_rotates_with_round_epoch():
    predicted = [
        PredictedHarvester(
            position=Position(4, 4),
            source="CONFIRMED",
            source_rank=0,
            usable_sides=2,
            immediate_open_sides=1,
            clearable_sides=1,
            unseen_sides=0,
            travel_distance=5,
            distance_to_core_anchor=10,
            same_lane=False,
            mode=None,
        ),
        PredictedHarvester(
            position=Position(8, 8),
            source="MIRRORED_ORE",
            source_rank=2,
            usable_sides=3,
            immediate_open_sides=2,
            clearable_sides=1,
            unseen_sides=0,
            travel_distance=6,
            distance_to_core_anchor=11,
            same_lane=False,
            mode="ROT180",
        ),
    ]

    assert choose_predicted_scout_anchor(
        predicted_enemy_harvesters=predicted,
        spawn_slot=0,
        current_round=0,
    ) == Position(4, 4)
    assert choose_predicted_scout_anchor(
        predicted_enemy_harvesters=predicted,
        spawn_slot=0,
        current_round=12,
    ) == Position(8, 8)
