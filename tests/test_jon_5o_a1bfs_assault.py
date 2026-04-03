from __future__ import annotations

import sys
from pathlib import Path

from cambc import Direction, EntityType, Environment, Position


JON_5O_A1_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-5o-a1bfs"
)
if str(JON_5O_A1_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_A1_BFS_ROOT))

import mode_assaulting
from assault import (  # noqa: E402
    ANCHOR_LIVE,
    ANCHOR_SATURATED,
    AssaultSite,
    SiteTarget,
    VisibleEnemy,
    assess_anchor,
    choose_best_site_for_harvester,
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


class _StubLogger:
    def log(self, _message: str) -> None:
        return


class _ExecuteSiteController:
    def __init__(self, *, position: Position, current_round: int = 20) -> None:
        self._position = position
        self._current_round = current_round
        self.moves: list[Direction] = []
        self.built: list[tuple[Position, Direction]] = []
        self._can_build = False
        self._can_fire = False
        self._action_cooldown = 0
        self._resources = (100, 0)
        self._sentinel_cost = (30, 0)

    def get_position(self) -> Position:
        return self._position

    def get_current_round(self) -> int:
        return self._current_round

    def get_id(self) -> int:
        return 7

    def get_team(self) -> int:
        return 1

    def can_fire(self, _position: Position) -> bool:
        return self._can_fire

    def fire(self, _position: Position) -> None:
        raise AssertionError("fire should not be used in this test")

    def can_move(self, direction: Direction) -> bool:
        return direction in {
            Direction.NORTH,
            Direction.NORTHEAST,
            Direction.EAST,
            Direction.SOUTHEAST,
            Direction.SOUTH,
            Direction.SOUTHWEST,
            Direction.WEST,
            Direction.NORTHWEST,
        }

    def move(self, direction: Direction) -> None:
        self.moves.append(direction)
        self._position = self._position.add(direction)

    def can_build_sentinel(self, _position: Position, _direction: Direction) -> bool:
        return self._can_build

    def build_sentinel(self, position: Position, direction: Direction) -> None:
        self.built.append((position, direction))

    def get_tile_building_id(self, _position: Position):
        return None

    def get_tile_builder_bot_id(self, _position: Position):
        return None

    def get_action_cooldown(self) -> int:
        return self._action_cooldown

    def get_global_resources(self) -> tuple[int, int]:
        return self._resources

    def get_sentinel_cost(self) -> tuple[int, int]:
        return self._sentinel_cost

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30

    def get_tile_env(self, _position: Position) -> Environment:
        return Environment.EMPTY


def _site_bot(grid: dict[tuple[int, int], dict]):
    return type(
        "_Bot",
        (),
        {
            "grid": grid,
            "logger": _StubLogger(),
            "harvester_anchor": None,
            "harvester_anchor_last_seen_round": -9999,
            "assault_anchor_status": None,
            "assault_last_site_signature": None,
            "assault_subrole": "build_now",
            "assault_last_progress_round": -9999,
            "assault_wait_state": {
                "site_signature": None,
                "staging_position": None,
                "expires_round": -1,
            },
        },
    )()


def test_outer_core_tile_does_not_count_as_core_target():
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


def test_center_hitting_direction_beats_same_tile_logistics_when_core_is_preferred():
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


def test_duplicate_core_tiles_do_not_inflate_site_value():
    harvester = Position(16, 13)
    grid = _empty_grid(
        Position(16, 12),
        Position(17, 13),
        Position(16, 14),
        Position(15, 13),
    )
    grid[(16, 12)]["env"] = Environment.WALL
    grid[(17, 13)]["env"] = Environment.WALL
    grid[(15, 13)]["env"] = Environment.WALL

    base_enemies = [
        _enemy(16, 13, EntityType.HARVESTER),
        _enemy(18, 18, EntityType.CORE),
    ]
    duplicate_enemies = base_enemies + [
        _enemy(17, 17, EntityType.CORE),
        _enemy(18, 17, EntityType.CORE),
    ]

    base_site = choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(16, 15),
        enemies=base_enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        actor_id=7,
        enemy_core_center=Position(18, 18),
    )
    duplicate_site = choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(16, 15),
        enemies=duplicate_enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        actor_id=7,
        enemy_core_center=Position(18, 18),
    )

    assert base_site is not None
    assert duplicate_site is not None
    assert duplicate_site.total_target_value == base_site.total_target_value
    assert duplicate_site.marginal_value == base_site.marginal_value
    assert duplicate_site.hits_core_center == base_site.hits_core_center


def test_three_resolved_sides_with_no_high_value_side_is_saturated():
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
    assert assessment.remaining_high_value_sites == 0


def test_three_resolved_sides_with_core_center_shot_stays_live():
    harvester = Position(16, 13)
    grid = _empty_grid(
        Position(16, 12),
        Position(17, 13),
        Position(16, 14),
        Position(15, 13),
    )
    grid[(16, 12)]["building"] = EntityType.SENTINEL
    grid[(16, 12)]["building_team"] = 1
    grid[(17, 13)]["env"] = Environment.WALL
    grid[(15, 13)]["env"] = Environment.WALL

    assessment = assess_anchor(
        harvester_position=harvester,
        current_position=Position(16, 15),
        enemies=[
            _enemy(16, 13, EntityType.HARVESTER),
            _enemy(18, 18, EntityType.CORE),
        ],
        grid=grid,
        my_team=1,
        actor_id=7,
        map_width=30,
        map_height=30,
        enemy_core_center=Position(18, 18),
    )

    assert assessment.status == ANCHOR_LIVE
    assert assessment.resolved_ring_sides == 3
    assert assessment.remaining_high_value_sites == 1


def test_execute_site_holds_safe_adjacent_wait_tile_instead_of_reentering_ring():
    harvester = Position(10, 10)
    ring = Position(11, 10)
    staging = Position(12, 9)
    bot = _site_bot(
        {
            (ring.x, ring.y): {"env": Environment.EMPTY, "last_seen": 50},
            (staging.x, staging.y): {"env": Environment.EMPTY, "last_seen": 50},
        }
    )
    controller = _ExecuteSiteController(position=staging)
    controller._action_cooldown = 1
    site = AssaultSite(
        harvester_position=harvester,
        ring_position=ring,
        sentinel_direction=Direction.SOUTHEAST,
        target=SiteTarget(Position(18, 18), EntityType.CORE, 1),
        hits_core_center=True,
        cluster_size=1,
        usable_sides=1,
        immediate_open_sides=1,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification="IMMEDIATE",
        marginal_value=8,
        uncovered_target_count=1,
        total_target_value=8,
    )
    bot.assault_wait_state = {
        "site_signature": mode_assaulting._site_signature(site),
        "staging_position": (staging.x, staging.y),
        "expires_round": controller.get_current_round() + 2,
    }

    acted = mode_assaulting._execute_site(bot, controller, site)

    assert acted is True
    assert controller.moves == []
    assert controller.built == []
    assert bot.assault_subrole == "wait_adjacent"


def test_execute_site_does_not_wait_from_harvester_adjacent_tile():
    harvester = Position(10, 10)
    ring = Position(11, 10)
    clogging_position = Position(10, 9)
    bot = _site_bot(
        {
            (ring.x, ring.y): {"env": Environment.EMPTY, "last_seen": 50},
            (clogging_position.x, clogging_position.y): {
                "env": Environment.EMPTY,
                "last_seen": 50,
            },
        }
    )
    controller = _ExecuteSiteController(position=clogging_position)
    controller._action_cooldown = 1
    site = AssaultSite(
        harvester_position=harvester,
        ring_position=ring,
        sentinel_direction=Direction.SOUTHEAST,
        target=SiteTarget(Position(18, 18), EntityType.CORE, 1),
        hits_core_center=True,
        cluster_size=1,
        usable_sides=1,
        immediate_open_sides=1,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification="IMMEDIATE",
        marginal_value=8,
        uncovered_target_count=1,
        total_target_value=8,
    )
    bot.assault_wait_state = {
        "site_signature": mode_assaulting._site_signature(site),
        "staging_position": (clogging_position.x, clogging_position.y),
        "expires_round": controller.get_current_round() + 2,
    }

    acted = mode_assaulting._execute_site(bot, controller, site)

    assert acted is False
    assert bot.assault_wait_state["site_signature"] is None


def test_best_sidestep_prefers_non_harvester_adjacent_staging_tile():
    harvester = Position(10, 10)
    ring = Position(11, 10)
    bot = _site_bot(
        {
            (10, 9): {"env": Environment.EMPTY, "last_seen": 50},
            (10, 11): {"env": Environment.EMPTY, "last_seen": 50},
            (11, 9): {"env": Environment.EMPTY, "last_seen": 50},
            (11, 11): {"env": Environment.EMPTY, "last_seen": 50},
            (12, 10): {"env": Environment.EMPTY, "last_seen": 50},
        }
    )
    controller = _ExecuteSiteController(position=ring)

    sidestep = mode_assaulting._best_sidestep(bot, controller, ring, harvester)

    assert sidestep is not None
    assert abs(sidestep.x - ring.x) <= 1 and abs(sidestep.y - ring.y) <= 1
    assert abs(sidestep.x - harvester.x) + abs(sidestep.y - harvester.y) > 1
