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

import mode_assaulting
from assault import (  # noqa: E402
    ANCHOR_CAPTURED,
    ANCHOR_GOOD_ENOUGH,
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


def _mode_bot(
    grid: dict[tuple[int, int], dict],
    *,
    visible_enemy_targets=None,
    visible_positions=None,
    visible_friendly_builders=None,
    confirmed_enemy_harvesters=None,
    predicted_enemy_harvesters=None,
    connected_friendly_conveyors=None,
):
    return SimpleNamespace(
        grid=grid,
        logger=_StubLogger(),
        harvester_anchor=None,
        harvester_anchor_last_seen_round=-9999,
        assault_anchor_status=None,
        assault_last_site_signature=None,
        assault_subrole="support",
        assault_last_progress_round=-9999,
        assault_wait_state={
            "site_signature": None,
            "staging_position": None,
            "expires_round": -1,
        },
        assault_anchor_blacklist={},
        assault_exhausted_regions=[],
        visible_enemy_targets=list(visible_enemy_targets or []),
        visible_positions=set(visible_positions or set(grid)),
        visible_friendly_builders=list(visible_friendly_builders or []),
        confirmed_enemy_harvesters=dict(confirmed_enemy_harvesters or {}),
        predicted_enemy_harvesters=list(predicted_enemy_harvesters or []),
        recent_assault_waypoints={},
        pathfinding_state={"known_obstacles": set()},
        spawn_slot=0,
        connected_friendly_conveyors=dict(connected_friendly_conveyors or {}),
        symmetry_candidates=("ROT180", "MIRROR_X", "MIRROR_Y"),
        enemy_core_anchor=None,
        core_pos=None,
    )


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


def test_low_gain_anchor_becomes_good_enough_move_on():
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
    assert assessment.anchor_visible_now is True
    assert assessment.pressure_established is True
    assert assessment.best_logistics_gain == 1


def test_two_tile_logistics_jump_stays_live():
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
            _enemy(12, 11, EntityType.CONVEYOR, Direction.SOUTH),
        ],
        grid=grid,
        my_team=1,
        actor_id=7,
        map_width=30,
        map_height=30,
    )

    assert assessment.status == ANCHOR_LIVE
    assert assessment.best_logistics_gain == 2


def test_anchor_without_pressure_never_becomes_good_enough():
    harvester = Position(10, 10)
    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
    )
    grid[(11, 10)]["building"] = EntityType.CONVEYOR
    grid[(11, 10)]["building_team"] = 2

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

    assert assessment.status == ANCHOR_LIVE
    assert assessment.pressure_established is False


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


def test_remaining_turret_shot_stays_live():
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
        enemies=[
            _enemy(10, 10, EntityType.HARVESTER),
            _enemy(10, 13, EntityType.SENTINEL, Direction.NORTH),
        ],
        grid=grid,
        my_team=1,
        actor_id=7,
        map_width=30,
        map_height=30,
    )

    assert assessment.status == ANCHOR_LIVE
    assert assessment.remaining_high_value_sites == 1


def test_captured_anchor_beats_good_enough():
    harvester = Position(10, 10)
    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
    )
    grid[(10, 9)]["building"] = EntityType.SENTINEL
    grid[(10, 9)]["building_team"] = 1

    assessment = assess_anchor(
        harvester_position=harvester,
        current_position=Position(10, 12),
        enemies=[_enemy(10, 10, EntityType.HARVESTER)],
        grid=grid,
        my_team=1,
        actor_id=7,
        map_width=30,
        map_height=30,
        connected_friendly_conveyors={(11, 10): {"round": 8}},
    )

    assert assessment.status == ANCHOR_CAPTURED


def test_stale_anchor_does_not_become_good_enough():
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
    grid[(10, 11)]["env"] = Environment.WALL
    grid[(9, 10)]["env"] = Environment.WALL

    assessment = assess_anchor(
        harvester_position=harvester,
        current_position=Position(10, 12),
        enemies=[],
        grid=grid,
        my_team=1,
        actor_id=7,
        map_width=30,
        map_height=30,
    )

    assert assessment.status == ANCHOR_SATURATED
    assert assessment.anchor_visible_now is False


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
        has_high_value_target=True,
        cluster_size=1,
        usable_sides=1,
        immediate_open_sides=1,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification="IMMEDIATE",
        marginal_value=8,
        uncovered_logistics_gain=0,
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
        has_high_value_target=True,
        cluster_size=1,
        usable_sides=1,
        immediate_open_sides=1,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification="IMMEDIATE",
        marginal_value=8,
        uncovered_logistics_gain=0,
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


def test_execute_support_returns_false_for_good_enough_anchor(monkeypatch):
    bot = _mode_bot({})
    controller = _ExecuteSiteController(position=Position(5, 5))
    site = AssaultSite(
        harvester_position=Position(10, 10),
        ring_position=Position(11, 10),
        sentinel_direction=Direction.EAST,
        target=SiteTarget(Position(12, 10), EntityType.CONVEYOR, 2),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=2,
        usable_sides=1,
        immediate_open_sides=1,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification="IMMEDIATE",
        marginal_value=4,
        uncovered_logistics_gain=1,
        uncovered_target_count=1,
        total_target_value=4,
    )

    monkeypatch.setattr(
        mode_assaulting,
        "_anchor_assessment",
        lambda *_args, **_kwargs: SimpleNamespace(status=ANCHOR_GOOD_ENOUGH),
    )

    acted = mode_assaulting._execute_support(
        bot,
        controller,
        anchor=Position(10, 10),
        site=site,
    )

    assert acted is False
    assert controller.moves == []


def test_good_enough_retirement_uses_short_cooldown_and_clears_wait_state():
    bot = _mode_bot({})
    bot.assault_wait_state = {
        "site_signature": (1, 2, 3),
        "staging_position": (5, 5),
        "expires_round": 99,
    }
    controller = _ExecuteSiteController(position=Position(5, 5), current_round=20)

    mode_assaulting._retire_anchor(  # noqa: SLF001
        bot,
        controller,
        Position(10, 10),
        reason=ANCHOR_GOOD_ENOUGH,
    )

    assert bot.assault_anchor_blacklist[(10, 10)] == 32
    assert bot.assault_wait_state["site_signature"] is None
    assert len(bot.assault_exhausted_regions) == 1


def test_good_enough_retirement_prefers_visible_anchor_outside_exhausted_region():
    anchor_a = Position(10, 10)
    anchor_b = Position(12, 10)
    anchor_c = Position(20, 20)
    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
        Position(12, 9),
        Position(13, 10),
        Position(12, 11),
        Position(11, 10),
        Position(20, 19),
        Position(21, 20),
        Position(20, 21),
        Position(19, 20),
    )
    grid[(11, 10)]["building"] = EntityType.CONVEYOR
    grid[(11, 10)]["building_team"] = 2
    grid[(21, 20)]["building"] = EntityType.CONVEYOR
    grid[(21, 20)]["building_team"] = 2
    enemies = [
        _enemy(10, 10, EntityType.HARVESTER),
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(12, 10, EntityType.HARVESTER),
        _enemy(20, 20, EntityType.HARVESTER),
        _enemy(21, 20, EntityType.CONVEYOR, Direction.EAST),
    ]
    bot = _mode_bot(grid, visible_enemy_targets=enemies)
    controller = _ExecuteSiteController(position=Position(11, 12), current_round=20)

    mode_assaulting._retire_anchor(  # noqa: SLF001
        bot,
        controller,
        anchor_a,
        reason=ANCHOR_GOOD_ENOUGH,
    )

    site = mode_assaulting._best_visible_site(bot, controller, live_anchor=None)  # noqa: SLF001

    assert site is not None
    assert site.harvester_position == anchor_c


def test_delegated_last_side_counts_as_resolved():
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
        friendly_builder_positions=[(99, Position(12, 10))],
    )

    assert assessment.status == ANCHOR_SATURATED
    assert assessment.best_logistics_gain == 0
